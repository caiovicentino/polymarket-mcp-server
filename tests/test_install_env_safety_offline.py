"""
Offline sandbox suite for install.sh — .env overwrite safety (T-0215).

Pins the FIX contract (backup first-wins + rollback restore/keep) against the
REAL install.sh of this worktree by running extracted functions
(configure_env / rollback) in a temp-dir sandbox. The file is never executed
end-to-end and the suite does NOT rely on INSTALL_TEST_MODE.

Extraction (declared choice per task §Seam — anchor-based, P-0018): the span
from the `# Colors for output` comment to the `# Main Installation Flow`
comment (colors + settings incl. ENV_CREATED init + every helper incl.
configure_env and rollback) is extracted from a byte-exact copy of install.sh
into install_lib.sh inside the sandbox. Anchors are CONTENT, not line numbers
(L-0127); extraction sanity is fail-fast (P-0018): non-empty, both target
functions anchored, main()/the footer `main "$@"` absent, `bash -n` clean.

Sandbox per test (pytest tmp_path — under the system temp dir, never inside
the repo): HOME/PATH/OS are redirected to the sandbox; the driver mirrors
production semantics (`set -e`, no -u). Zero network / zero pip / zero real
venv: only configure_env and rollback run (configure_env's demo path writes a
plain text file; nothing else is executed). All writes are confined to the
sandbox (L-0013).

Semantics pinned (task §Fix B):
- a pre-existing .env is backed up ONCE to `.env.pre-install-backup`
  (first-wins: a second run never overwrites the backup with the template;
  the name is deliberately distinct from uninstall.sh's `.env.backup` to
  avoid cross-rotation);
- rollback() restores the pre-existing .env from the backup (mv), removes an
  .env created by the current run (ENV_CREATED=1), and keeps anything else.

RED pre-fix (first-hand, task report): pre-fix configure_env overwrote a
pre-existing .env with no backup at all, and rollback() removed ANY .env
unconditionally — an install over a working setup destroyed the user's
configuration. test_demo_env_write_creates_first_backup /
test_second_run_preserves_backup / test_rollback_restores_preexisting_env /
test_rollback_removes_created_env failed pre-fix (the last one on the
ENV_CREATED=1 observability — the .env-gone part already held pre-fix).
test_bash_n_valid / test_real_file_tripwire passed pre-fix (declared).

r2 (auto-revert of the merged r1 -- revertlog 149a, CI windows evidence):
the r1 suite spawned a generic "bash" and died on import when python3 was
absent, both Windows-only hazards (T-0214 r3, same class, CI-proven on PRs
#62/#68: subprocess.run resolves the executable via the CALLER's PATH on
Windows; the first bash.exe hit is the System32 WSL launcher, rc=1 with an
empty stderr and a UTF-16LE "wsl.exe --list --online" banner on stdout).
Prescriptions implemented here (same as T-0214 r3, all merged + CI-green):
- P1-01: the bash executable is resolved EXPLICITLY on the win branch
  (Git for Windows candidates in a prescribed order, then the git.exe root
  fallback) and the FULL path is handed to subprocess. Absent everywhere ->
  LOUD RuntimeError with the prescribed label, never silent.
- P2-01: on the win branch the child env is dict(os.environ) with overrides
  (PATH/HOME/TERM) -- a minimal env without SystemRoot breaks msys-2.0.dll
  (bpo-34204 class). POSIX keeps the minimal explicit env.
- P2-02: the sandbox provisions SHEBANG shims named `python` and `python3`
  (install.sh resolves `which python` and the literal `python3` merge
  heredoc; Windows runners ship python.exe only). The shims exec the
  interpreter IN PLACE (a relocated python.exe copy cannot init:
  DLL/pyvenv.cfg discovery is location-based) and the shim dir lands on the
  CHILD PATH. Divergence from the T-0214 wording declared below.
- Dev-only proofs of the win mechanism run on EVERY platform (monkeypatched
  _IS_WIN + stubbed resolution/spawn): candidate order + short-circuit,
  git-root fallback, LOUD absence, full-path argv for both spawn helpers,
  env merge, shim provisioning -- counts and paths asserted (L-0112/L-0082).

Divergences from the T-0214 prescriptions (declared, L-0025/L-0020):
- P2-02 shims here are `python` AND `python3` (install.sh needs both); the
  `clear` fallback shim of T-0214 is NOT provisioned because install.sh only
  runs `clear` inside main() (install.sh:573), which this suite never
  executes (extraction + driver only). This suite's pinned functions
  (configure_env demo path / rollback) touch ONLY plain text files, so the
  heredoc python3 is never invoked here either -- the shim is provisioned
  for sandbox parity with the sibling suite (same _make_sandbox contract).
- PYTHONIOENCODING=utf-8 joins the win env overrides (parity with the
  T-0214 r3 prescription; deterministic child interpreter).
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"

_LIB_START = "# Colors for output"
_LIB_END = "# Main Installation Flow"
_FUNC_ANCHORS = ("configure_env()", "rollback()")

_ORIGINAL_ENV = "MAX_ORDER_SIZE_USD=777\nPOLYGON_ADDRESS=0xdead\n"

# ---------------------------------------------------------------------------
# r2 platform-aware plumbing (prescriptions P1-01/P2-01/P2-02; T-0214 r3
# pattern, merged and CI-green there). POSIX keeps the r1-proven mechanics.
# ---------------------------------------------------------------------------
_IS_WIN = sys.platform.startswith("win")

# POSIX PATH_SAFE -- r1-proven hermetic baseline; the sandbox shim dir is
# prefixed by _run_env.
PATH_SAFE = "/usr/bin:/bin:/usr/sbin:/sbin"

# P1-01: prescribed loud label when no Git Bash can be resolved (never silent).
GIT_BASH_MISSING_LABEL = "Git Bash not found; WSL bash would fail"

# Lazy cache of the resolved Git for Windows bash.exe (None until first spawn).
_WIN_BASH = None


def _win_bash_candidates():
    """Prescribed candidate order for the Git for Windows bash.exe (P1-01):
    Program Files\\Git\\bin -> Program Files (x86)\\Git\\bin ->
    Program Files\\Git\\usr\\bin. The ProgramFiles env vars are consulted
    first (standard runners define them; the prescribed literals are the
    defaults), so installs on non-C: drives still resolve."""
    pf = os.environ.get("ProgramFiles", "C:\\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
    return [
        Path(pf) / "Git" / "bin" / "bash.exe",
        Path(pf86) / "Git" / "bin" / "bash.exe",
        Path(pf) / "Git" / "usr" / "bin" / "bash.exe",
    ]


def _resolve_win_bash(candidates=None, which_fn=shutil.which):
    """Resolve the Git for Windows bash.exe EXPLICITLY, never via generic
    "bash" (r2 P1-01).

    Why: subprocess.run on Windows resolves the executable via the CALLER's
    PATH (CreateProcess; the env= of the child does not participate in the
    lookup). CI evidence (T-0214 r3, PR #62/#68, windows-latest): a generic
    "bash" spawn found System32\\bash.exe (the WSL launcher), which exits
    rc=1 with an empty stderr and a UTF-16LE banner on stdout when no distro
    is installed -- the bash WAS found and executed, it was the WRONG bash
    (classified by the observed mechanism, L-0052/L-0020). The same hazard
    killed the r1 suites of THIS task on CI (revertlog 149a).

    Order: the prescribed Git Bash candidates first; then shutil.which("git")
    -> git.exe root (dirname(dirname(git))) sibling bin\\bash.exe. If none
    exists: LOUD RuntimeError with the prescribed label -- never silent.
    """
    for cand in (candidates if candidates is not None else _win_bash_candidates()):
        if Path(cand).is_file():
            return Path(cand)
    git = which_fn("git")
    if git:
        # No .resolve(): shutil.which already returns an absolute path and the
        # root is pure parent arithmetic (relative-looking fakes must not be
        # anchored to the CWD).
        git_root = Path(git).parent.parent
        cand = git_root / "bin" / "bash.exe"
        if cand.is_file():
            return cand
    raise RuntimeError(
        GIT_BASH_MISSING_LABEL
        + " (System32\\bash.exe exits rc=1 without a WSL distro; install Git for Windows)"
    )


def _bash_exe():
    """Full bash executable for subprocess spawns (r2 P1-01).

    POSIX: the generic "bash" is kept (r1-proven: the caller PATH there is
    correct and the suite's POSIX runs are green). Windows: the FULL resolved
    Git for Windows bash.exe -- never the generic "bash" (its lookup would use
    the caller PATH and hit the System32 WSL launcher; the child env PATH does
    not change the spawn resolution -- the refuted-r2 mechanism).
    """
    global _WIN_BASH
    if not _IS_WIN:
        return "bash"
    if _WIN_BASH is None:
        _WIN_BASH = _resolve_win_bash()
    return str(_WIN_BASH)


def _win_usr_bin():
    """Coreutils dir of the resolved Git for Windows (usr\\bin) for the child
    PATH (the driver needs grep/cut/cp/mv/rm/which, all msys coreutils). Also
    load-bearing for the Git\\bin\\bash.exe DLL discovery (msys-2.0.dll lives
    in usr\\bin; the Windows DLL search falls through to PATH dirs)."""
    exe = Path(_bash_exe())
    if exe.parent.name == "bin" and exe.parent.parent.name == "usr":
        return exe.parent  # ...\\Git\\usr\\bin\\bash.exe -> ...\\Git\\usr\\bin
    return exe.parent.parent / "usr" / "bin"  # ...\\Git\\bin\\bash.exe -> ...\\Git\\usr\\bin


def _win_path_prefix(shim_dir=None):
    """Child PATH prefix on the win branch: msys coreutils (usr\\bin) FIRST,
    then the sandbox shim dir (python/python3), so sandbox-provided
    executables win over the host PATH without ever hiding the real usr/bin
    tools (the host PATH remainder is appended for anything else)."""
    parts = [str(_win_usr_bin())]
    if shim_dir is not None:
        parts.append(str(shim_dir))
    return os.pathsep.join(parts)


def _env_get(env, name):
    """Case-insensitive lookup of a plain env dict.

    Why: CPython's os.environ on Windows stores keys UPPERCASED
    (Lib/os.py _createenviron, 'nt' branch: encodekey = encode(key).upper()),
    so dict(os.environ) carries 'SYSTEMROOT' while the mixed-case lookup
    'SystemRoot' raises KeyError on win32 (works on POSIX). The
    case-insensitive lookup preserves the assertion's intent on every
    platform (provenance: CPython Lib/os.py read first-hand 2026-09-18;
    fix pattern: T-0315 #100, test_uninstall_script_offline.py).
    """
    for k, v in env.items():
        if k.upper() == name.upper():
            return v
    raise KeyError(name)


def _probe_env():
    """Env for syntax probes (bash -n executes nothing from PATH).

    POSIX: minimal explicit env, r1-proven hermetic baseline.
    Win (r2 P2-01): dict(os.environ) + overrides -- a minimal env WITHOUT
    SystemRoot breaks msys-2.0.dll (bpo-34204 class).
    """
    if not _IS_WIN:
        return {"PATH": PATH_SAFE, "TERM": "xterm"}
    env = dict(os.environ)
    env["PATH"] = _win_path_prefix() + os.pathsep + env.get("PATH", "")
    env["TERM"] = "xterm"
    return env


def _run_env(home, shim_dir):
    """Env for execution.

    POSIX: minimal explicit env with the sandbox shim dir FIRST (sandbox
    parity with the sibling suite) + PATH_SAFE + sandboxed HOME -- nothing
    else inherited from the host (hermeticity, L-0130).
    Win (r2 P2-01): dict(os.environ) + overrides (PATH/HOME/TERM) --
    SystemRoot and friends MUST survive (msys-2.0.dll requirement).
    """
    if not _IS_WIN:
        return {
            "PATH": f"{shim_dir}{os.pathsep}{PATH_SAFE}",
            "TERM": "xterm",
            "HOME": str(home),
        }
    env = dict(os.environ)
    env["PATH"] = _win_path_prefix(shim_dir) + os.pathsep + env.get("PATH", "")
    env["TERM"] = "xterm"
    env["HOME"] = str(home)
    # Parity with the T-0214 r3 prescription (deterministic child interpreter).
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _ensure_shims(bin_dir):
    """Provision sandbox executables install.sh needs that a Windows runner
    lacks (r2 P2-02). Writes are confined to the sandbox tmpdir.

    `python` (PYTHON_PATH=$(which python)) and `python3` (the merge heredoc)
    are both needed by the SIBLING suite; here the pinned functions touch
    only plain text files, so these shims are provisioned for sandbox parity
    (same _make_sandbox contract) -- see module header divergence note.
    A copy/hardlink of sys.executable named python3.exe would NOT work: the
    Windows interpreter discovers pythonXY.dll (and, for venv launchers,
    pyvenv.cfg) relative to the executable's own directory, so a relocated
    copy fails init. Instead: shebang scripts (msys bash executes shebang
    scripts found on PATH without an extension) that exec the interpreter
    IN PLACE, where its DLLs and pyvenv.cfg live.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = Path(sys.executable)
    for name in ("python", "python3"):
        shim = bin_dir / name
        shim.write_text(f"#!/bin/sh\nexec '{exe.as_posix()}' \"$@\"\n", encoding="ascii")
        shim.chmod(0o755)
    # Application proof (L-0112): exactly two shims, content-anchored.
    names = sorted(p.name for p in bin_dir.iterdir())
    assert names == ["python", "python3"], f"unexpected sandbox bin contents: {names}"
    text = (bin_dir / "python3").read_text(encoding="ascii")
    assert text.startswith("#!/bin/sh\nexec '"), "python3 shim must exec the interpreter in place"
    assert exe.as_posix() in text, "python3 shim must point at the real interpreter"
    assert '"$@"' in text, "python3 shim must forward argv"
    assert (bin_dir / "python").read_text(encoding="ascii") == text, (
        "python shim must mirror the python3 shim"
    )
    return bin_dir


# ---------------------------------------------------------------------------
# Sandbox plumbing (r1, extended for the win branch)
# ---------------------------------------------------------------------------
def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_sandbox(tmp_path: Path) -> Path:
    """Build a hermetic sandbox: shims, byte-exact install.sh copy, empty HOME."""
    sb = tmp_path / "sb"
    (sb / "bin").mkdir(parents=True)
    (sb / "home").mkdir()
    if _IS_WIN:
        # P2-02: shebang shims (a relocated python.exe copy cannot init).
        _ensure_shims(sb / "bin")
    else:
        # POSIX: r1-proven symlink shim. Fail LOUD in this test (with a clear
        # message) instead of failing the whole COLLECTION at import time --
        # that import-time RuntimeError was one of the r1 CI failures.
        py3 = shutil.which("python3")
        assert py3, "python3 is required on the PATH to build the POSIX sandbox shim"
        (sb / "bin" / "python").symlink_to(py3)
    (sb / "install.sh").write_bytes(INSTALL_SH.read_bytes())
    assert _sha256_file(sb / "install.sh") == _sha256_file(INSTALL_SH)
    return sb


def _run_bash_n(script: Path) -> subprocess.CompletedProcess[str]:
    """bash -n syntax probe through the P1-01 plumbing (full bash path on win)."""
    return subprocess.run(
        [_bash_exe(), "-n", str(script)],
        capture_output=True,
        text=True,
        env=_probe_env(),
        timeout=60,
    )


def _extract_lib(sb: Path) -> Path:
    """Extract colors+settings+helpers from the COPY by content anchors."""
    src = sb / "install.sh"
    lib = sb / "install_lib.sh"
    out: list[str] = []
    on = False
    for line in src.read_text(encoding="utf-8").splitlines(keepends=True):
        stripped = line.rstrip("\n")
        if stripped == _LIB_START:
            on = True
        if stripped == _LIB_END:
            on = False
        if on:
            out.append(line)
    lib.write_text("".join(out), encoding="utf-8")
    text = lib.read_text(encoding="utf-8")
    assert text.strip(), "extracted lib is empty (anchors drifted?)"
    for anchor in _FUNC_ANCHORS:
        assert re.search(rf"^{re.escape(anchor)}", text, re.M), f"missing anchor {anchor}"
    assert not re.search(r"^main\(\)", text, re.M), "main() must not leak into the lib"
    assert not re.search(r'^main "\$@"', text, re.M), "footer main call must not leak"
    proc = _run_bash_n(lib)
    assert proc.returncode == 0, f"extracted lib is not valid bash:\n{proc.stderr}"
    return lib


def _write_driver(sb: Path, body: str) -> Path:
    driver = sb / "driver.sh"
    driver.write_text(
        "set -e\n"
        f'export HOME="{sb / "home"}"\n'
        f'export PATH="{sb / "bin"}:$PATH"\n'
        'export OS="Linux"\n'
        f'source "{sb / "install_lib.sh"}"\n'
        f'cd "{sb}"\n'
        f"{body}\n",
        encoding="utf-8",
    )
    return driver


def _run_driver(sb: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_bash_exe(), str(sb / "driver.sh")],
        capture_output=True,
        text=True,
        cwd=str(sb),
        env=_run_env(sb / "home", sb / "bin"),
        timeout=120,
    )


@pytest.fixture(autouse=True)
def _tripwire_real_install_sh():
    before = _sha256_file(INSTALL_SH)
    yield
    assert _sha256_file(INSTALL_SH) == before, "real install.sh was modified by the suite"


def test_bash_n_valid(tmp_path: Path) -> None:
    """bash -n on a byte-exact copy of install.sh must succeed (rc=0)."""
    sb = _make_sandbox(tmp_path)
    proc = _run_bash_n(sb / "install.sh")
    assert proc.returncode == 0, proc.stderr


def test_demo_env_write_creates_first_backup(tmp_path: Path) -> None:
    """A pre-existing .env (777 custom limit) is backed up; .env becomes template."""
    sb = _make_sandbox(tmp_path)
    _extract_lib(sb)
    (sb / ".env").write_text(_ORIGINAL_ENV, encoding="utf-8")
    _write_driver(sb, "DEMO_MODE=true\nconfigure_env\n")
    proc = _run_driver(sb)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    backup = sb / ".env.pre-install-backup"
    assert backup.exists(), "first-run backup of the pre-existing .env missing"
    assert backup.read_text(encoding="utf-8") == _ORIGINAL_ENV
    env_now = (sb / ".env").read_text(encoding="utf-8")
    assert "MAX_ORDER_SIZE_USD=100" in env_now, "demo template not written"
    assert "777" not in env_now, "custom limit leaked into the rewritten .env"


def test_second_run_preserves_backup(tmp_path: Path) -> None:
    """Second run (same sandbox state): the backup keeps the ORIGINAL content."""
    sb = _make_sandbox(tmp_path)
    _extract_lib(sb)
    (sb / ".env").write_text(_ORIGINAL_ENV, encoding="utf-8")
    _write_driver(sb, "DEMO_MODE=true\nconfigure_env\nconfigure_env\n")
    proc = _run_driver(sb)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    backup = sb / ".env.pre-install-backup"
    assert backup.exists(), "backup vanished after the second run"
    assert backup.read_text(encoding="utf-8") == _ORIGINAL_ENV, (
        "second run clobbered the first-wins backup with the template"
    )


def test_rollback_restores_preexisting_env(tmp_path: Path) -> None:
    """Rollback with a backup present: .env is the pre-existing content, backup gone."""
    sb = _make_sandbox(tmp_path)
    _extract_lib(sb)
    (sb / ".env").write_text(_ORIGINAL_ENV, encoding="utf-8")
    _write_driver(sb, "DEMO_MODE=true\nconfigure_env\nrollback\n")
    proc = _run_driver(sb)
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    assert (sb / ".env").read_text(encoding="utf-8") == _ORIGINAL_ENV, (
        "rollback did not restore the pre-existing .env"
    )
    assert "Restored pre-existing .env" in proc.stdout, "restore branch not taken"
    assert not (sb / ".env.pre-install-backup").exists(), "backup not consumed by mv"


def test_rollback_removes_created_env(tmp_path: Path) -> None:
    """Same-process run+rollback with no pre-existing .env: created .env removed."""
    sb = _make_sandbox(tmp_path)
    _extract_lib(sb)
    _write_driver(
        sb,
        "DEMO_MODE=true\n"
        "configure_env\n"
        'echo "ENV_CREATED=$ENV_CREATED"\n'
        "rollback\n",
    )
    proc = _run_driver(sb)
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    assert "ENV_CREATED=1" in proc.stdout, "ENV_CREATED not observable after the write"
    assert not (sb / ".env").exists(), "rollback kept the .env created by this run"
    assert not (sb / ".env.pre-install-backup").exists(), "stray backup after removal"
    assert "Removed .env file" in proc.stdout, "remove-created branch not taken"


def test_real_file_tripwire() -> None:
    """The REAL install.sh is byte-identical across the test run (P-0013)."""
    before = _sha256_file(INSTALL_SH)
    after = _sha256_file(INSTALL_SH)
    assert before == after


# ---------------------------------------------------------------------------
# r2 dev-only proofs of the Windows mechanism (run on EVERY platform;
# monkeypatched _IS_WIN + stubbed resolution/spawn -- T-0214 r3 pattern).
# ---------------------------------------------------------------------------
def test_win_bash_resolution_prefers_git_bash_in_order(monkeypatch):
    """Dev-only proof (any platform) of the P1-01 mechanism: the candidate
    scan returns the FIRST existing candidate in the prescribed order and
    stops there (short-circuit count asserted -- L-0112/L-0082)."""
    c1 = Path("C:/Program Files/Git/bin/bash.exe")
    c2 = Path("C:/Program Files (x86)/Git/bin/bash.exe")
    c3 = Path("C:/Program Files/Git/usr/bin/bash.exe")
    probed = []

    def fake_is_file_only_second(self):
        probed.append(self)
        return self == c2

    monkeypatch.setattr(Path, "is_file", fake_is_file_only_second)
    got = _resolve_win_bash(candidates=[c1, c2, c3], which_fn=lambda _n: None)
    assert got == c2, "resolution must return the first EXISTING candidate"
    assert probed == [c1, c2], (
        f"scan must stop at the first hit; probed={[str(p) for p in probed]}"
    )

    def fake_is_file_all(self):
        probed.append(self)
        return True

    probed.clear()
    monkeypatch.setattr(Path, "is_file", fake_is_file_all)
    got = _resolve_win_bash(candidates=[c1, c2, c3], which_fn=lambda _n: None)
    assert got == c1, "when the first candidate exists it must win (order preserved)"
    assert probed == [c1], f"first hit must short-circuit; probed={[str(p) for p in probed]}"


def test_win_bash_fallback_via_git_and_loud_when_absent(monkeypatch):
    """Dev-only proof (any platform) of the P1-01 fallback + loud guard:
    shutil.which("git") -> dirname(dirname(git)) sibling bin\\bash.exe; with
    NO candidate anywhere the resolution is LOUD with the prescribed label
    (never silent -- the r1 silent-rc=1 class is exactly what CI refuted)."""
    git_exe = Path("C:/Program Files/Git/cmd/git.exe")
    root_bash = Path("C:/Program Files/Git/bin/bash.exe")
    monkeypatch.setattr(Path, "is_file", lambda self: self == root_bash)
    got = _resolve_win_bash(candidates=[], which_fn=lambda _n: str(git_exe))
    assert got == root_bash, "fallback must resolve bash.exe beside the git.exe root"
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    with pytest.raises(RuntimeError, match="Git Bash not found; WSL bash would fail"):
        _resolve_win_bash(candidates=[], which_fn=lambda _n: None)


def test_win_subprocess_receives_full_bash_path(tmp_path, monkeypatch):
    """Dev-only proof (any platform) of the P1-01/P2-01/P2-02 plumbing:
    with the win branch active, BOTH spawn helpers of this suite pass the
    FULL resolved bash path as argv[0] (never the generic "bash") and the
    child env is dict(os.environ) merged (SystemRoot inherited -- P2-01)
    with the sandbox overrides. Counts and paths asserted (L-0112)."""
    mod = sys.modules[__name__]
    fake_bash = tmp_path / "fake" / "Git" / "bin" / "bash.exe"
    monkeypatch.setattr(mod, "_IS_WIN", True)
    monkeypatch.setattr(
        mod, "_resolve_win_bash", lambda candidates=None, which_fn=shutil.which: fake_bash
    )
    monkeypatch.setattr(mod, "_WIN_BASH", None)
    monkeypatch.setenv("SystemRoot", "C:\\Windows")

    class _FakeProc:
        returncode = 0
        stdout = ""
        stderr = ""

    captured = []

    def fake_run(argv, **kwargs):
        captured.append((list(argv), kwargs.get("env")))
        return _FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)

    sb = _make_sandbox(tmp_path)
    rc_probe = _run_bash_n(sb / "install.sh")
    assert rc_probe.returncode == 0 and len(captured) == 1, (
        f"one -n spawn expected; got {len(captured)}"
    )
    argv, env = captured[0]
    assert argv == [str(fake_bash), "-n", str(sb / "install.sh")]
    assert argv[0] != "bash", "spawn must NEVER use the generic 'bash' on the win branch"
    assert _env_get(env, "SystemRoot") == "C:\\Windows", "merged env must keep SystemRoot (P2-01)"

    captured.clear()
    proc = _run_driver(sb)
    assert proc.returncode == 0 and len(captured) == 1, (
        f"one driver spawn expected; got {len(captured)}"
    )
    argv, env = captured[0]
    assert argv == [str(fake_bash), str(sb / "driver.sh")]
    assert argv[0] != "bash"
    assert _env_get(env, "SystemRoot") == "C:\\Windows"
    assert env["HOME"] == str(sb / "home")
    assert env["PYTHONIOENCODING"] == "utf-8"
    parts = env["PATH"].split(os.pathsep)
    assert parts[0] == str(tmp_path / "fake" / "Git" / "usr" / "bin"), (
        "usr/bin must lead the child PATH"
    )
    assert str(sb / "bin") in parts[:2], "shim dir must be on the child PATH (P2-02)"


def test_win_env_merges_system_root_and_overrides(monkeypatch):
    """P2-01: on the win branch the child env is dict(os.environ) WITH the
    overrides (PATH/HOME/TERM) -- a minimal env without SystemRoot breaks
    msys-2.0.dll (bpo-34204 class). On POSIX the minimal explicit env stays
    byte-identical to r1 (no host inheritance), with the shim dir prefixed."""
    mod = sys.modules[__name__]
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    monkeypatch.setenv("T0215_HOST_ONLY", "host-value")
    monkeypatch.setattr(mod, "_IS_WIN", False)
    assert _probe_env() == {"PATH": PATH_SAFE, "TERM": "xterm"}
    fake_bash = Path("C:/Program Files/Git/bin/bash.exe")
    monkeypatch.setattr(mod, "_IS_WIN", True)
    monkeypatch.setattr(mod, "_WIN_BASH", fake_bash)
    env = _probe_env()
    assert _env_get(env, "SystemRoot") == "C:\\Windows", "P2-01: SystemRoot must survive the win env merge"
    assert env["T0215_HOST_ONLY"] == "host-value", "win env is a MERGE, not a reset"
    assert env["TERM"] == "xterm"
    # PATH assertion via prefix (the fake win path contains ":", which would
    # collide with os.pathsep on POSIX proof hosts -- L-0052-class care).
    assert env["PATH"].startswith(str(Path("C:/Program Files/Git/usr/bin")) + os.pathsep)
    home = Path("/T0215-sandbox-home")
    bin_dir = Path("/T0215-sandbox-bin")
    env = _run_env(home, bin_dir)
    assert env["HOME"] == str(home), "HOME must be overridden to the sandbox"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert _env_get(env, "SystemRoot") == "C:\\Windows"
    assert env["T0215_HOST_ONLY"] == "host-value"
    assert env["PATH"].startswith(
        str(Path("C:/Program Files/Git/usr/bin"))
        + os.pathsep
        + str(bin_dir)
        + os.pathsep
    )


def test_win_sandbox_shims_provisioned(tmp_path, monkeypatch):
    """P2-02 dev-only proof (any platform): the sandbox shims are written
    INSIDE the tmpdir only; `python` and `python3` are in-place exec shebangs
    of the real interpreter; the shim dir lands on the CHILD PATH right after
    usr/bin. On the POSIX branch the sandbox uses a symlink (no shebang
    shims)."""
    mod = sys.modules[__name__]
    monkeypatch.setattr(mod, "_IS_WIN", True)
    bin_dir = _ensure_shims(tmp_path / "bin-win")
    assert sorted(p.name for p in bin_dir.iterdir()) == ["python", "python3"]
    python3 = bin_dir / "python3"
    text = python3.read_text(encoding="ascii")
    assert text.startswith("#!/bin/sh\nexec '")
    assert Path(sys.executable).as_posix() in text
    assert '"$@"' in text
    fake_bash = Path("C:/Program Files/Git/bin/bash.exe")
    monkeypatch.setattr(mod, "_WIN_BASH", fake_bash)
    home = tmp_path / "sb"
    env = _run_env(home, bin_dir)
    # PATH prefix assertion (the fake win path contains ":", which would
    # collide with os.pathsep on POSIX proof hosts).
    expected_prefix = (
        str(Path("C:/Program Files/Git/usr/bin")) + os.pathsep + str(bin_dir) + os.pathsep
    )
    assert env["PATH"].startswith(expected_prefix), (
        "shim dir must come right after usr/bin on the child PATH"
    )
    # POSIX run env keeps the r1 minimal shape with the shim dir FIRST.
    monkeypatch.setattr(mod, "_IS_WIN", False)
    assert _run_env(home, bin_dir) == {
        "PATH": f"{bin_dir}{os.pathsep}{PATH_SAFE}",
        "TERM": "xterm",
        "HOME": str(home),
    }
    assert _probe_env() == {"PATH": PATH_SAFE, "TERM": "xterm"}
