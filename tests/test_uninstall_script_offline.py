"""
Offline suite for uninstall.sh (T-0214) -- 100% offline, byte-exact copy discipline.

The real uninstall.sh was syntactically invalid (bash -n rc=2 'unexpected end
of file') because of two compounded defects (contract T-0214):

- :141 opened a heredoc WITHOUT passing the config file as argv
  (`python3 << 'PYEOF'`): the body's `sys.argv[1]` raised IndexError, the
  internal except printed a warning and the polymarket entry NEVER left the
  Claude Desktop config.
- :164 had the heredoc terminator with an invalid suffix
  (`PYEOF "$CONFIG_FILE" || true`). Bash requires the delimiter alone on its
  own line, so the heredoc never terminated, the parser swallowed the rest of
  the file and bash -n failed at EOF. A real run died MID-uninstall (after the
  .env was renamed), leaving partial state (config untouched, no summary).

Fix under test (verbatim, 2 lines):
- :141 -> `python3 - "$CONFIG_FILE" << 'PYEOF' || true`
- :164 -> `PYEOF`   (delimiter alone on the line)

Mechanics (contract-mandated):
- The REAL script is NEVER executed: every case copies it byte-exactly into a
  pytest tmp_path (P-0018, hash-provable) and exercises ONLY the copy with a
  sandboxed HOME and cwd. Tripwire: sha256 of the real file is captured at
  import time (pre) and re-checked in test_real_file_tripwire (post).
- Assertions are content-anchored, never file:line (L-0127/L-0023): the
  parser error of the broken script lands on whatever line the EOF falls on;
  the FIX itself is anchored by its literal text.
- Mutation oracle (L-0065/L-0094): test_bash_n_valid_after_fix reverts the two
  fix lines on a SECOND copy and proves bash -n fails again (rc=2) -- the
  oracle knows how to fail. Substitution counts are asserted == 1
  (L-0082/L-0112/L-0128: no silent no-op mutations).

Offline proof (L-0138/L-0133): subprocesses run with an explicit env. On POSIX
the MINIMAL env (PATH_SAFE, TERM, HOME) is kept so no host env vars or
credentials leak into the run (r1/r2-proven hermetic). The script only uses
stdlib `json` + core shell tools; zero sockets are created; zero writes
outside the tmpdir (the script only touches cwd and $HOME/$APPDATA, all pinned
inside the sandbox).

r3 (reviewer-arch prescriptions after first-hand CI evidence -- PR #62/#68
windows jobs; the r2 platform-aware suite did NOT fix windows):
- P1-01 (blocking): on the win branch the bash executable is resolved
  EXPLICITLY (Git for Windows candidates in a prescribed order, then the
  git.exe root fallback) and the FULL path is handed to subprocess. A generic
  "bash" resolves via the CALLER's PATH on Windows (CreateProcess; the child
  env does not participate in the lookup), and CI proved that first bash.exe
  is the System32 WSL launcher (rc=1, empty stderr, "wsl.exe --list --online"
  banner on stdout): the r2 hypothesis (bash MISSING -> FileNotFoundError)
  was refuted -- the observed mechanism is "wrong bash" (L-0052/L-0020).
  Absent everywhere -> LOUD RuntimeError with the prescribed label, never
  silent.
- P2-01: on the win branch the child env is dict(os.environ) with overrides
  (PATH/HOME/APPDATA/TERM) -- a minimal env without SystemRoot breaks
  msys-2.0.dll (bpo-34204 class). POSIX keeps the minimal explicit env.
- P2-02: the script invokes literal `python3`, absent on Windows runners --
  the sandbox provisions a shim (shebang script exec'ing sys.executable IN
  PLACE; a relocated python.exe copy cannot init: DLL/pyvenv.cfg discovery is
  location-based) and puts its dir on the CHILD PATH. A `clear` fallback shim
  rides along (only reachable when the resolved usr/bin lacks clear.exe;
  usr/bin precedes in the child PATH). Writes confined to the tmpdir.
- Dev-only proofs of the win mechanism run on EVERY platform (monkeypatched
  _IS_WIN + stubbed resolution/spawn): candidate order + short-circuit,
  git-root fallback, LOUD absence, full-path argv for both spawn helpers,
  env merge, shim provisioning -- counts and paths asserted (L-0112/L-0082).

Divergences from the arch prescriptions (declared, L-0025/L-0020):
- P2-02 said "copy/hardlink sys.executable as python3.exe": a relocated copy
  of the Windows interpreter cannot initialize (it looks for pythonXY.dll
  next to the executable and, for venv launchers, for pyvenv.cfg), so the
  shim is a shebang script named `python3` that execs the interpreter in
  place -- same observable (a `python3` entry resolvable by the CHILD bash
  via its own PATH), same tmpdir confinement, robust mechanism.
- The `clear` fallback shim is an un-prescribed defensive provision for
  runner packaging variance (declared here, never silent); it can only be
  reached when the real msys clear.exe is absent (PATH order keeps usr/bin
  first).
- PYTHONIOENCODING=utf-8 joins the win env overrides: without it the heredoc
  python's pipe stdout defaults to the ANSI code page (cp1252) and its
  unicode glyphs raise UnicodeEncodeError (absorbed by the script's
  `|| true` -- the config is already written before the print -- but the
  traceback noise would be confusing).

Divergence notes (L-0025/L-0090, r1):
- P-0021 "set -u, no -e, sentinel rc=99 on captures": materialized directly --
  every captured returncode starts as the sentinel 99 and is only overwritten
  after a successful subprocess.run (no bash pipelines exist to mask a rc);
  the timeout guard turns a hang into a loud rc=99 failure with the right
  label instead of a dead suite.
- L-0089g/FA-0061 "trap 'rc=$?; cleanup; exit $rc' at the top": there is no
  bash trap here (the suite is Python); the pytest tmp_path fixture is the
  Python-idiomatic equivalent (teardown guaranteed on every exit path,
  including exceptions), declared here instead of silently skipped.
- L-0163b: no banner path -- the suite prints no sandbox paths in its own
  output (pytest may echo tmp paths only on failure, which is its teardown
  surface, not our banner).

Prediction (TDD, causal proof -- L-0130/P-0036): RED pre-fix (r1) = 4 failed /
1 passed (only the tripwire passes; CI reproduced the same RED on PR #62/#68).
r3 GREEN on any POSIX dev box = 10 passed (5 original + 5 dev-only
win-mechanism proofs); the windows CI legs are the real-world re-check
(P3-04: re-publish the branch so the PR CI runs the r3 suite).
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL = REPO_ROOT / "uninstall.sh"

# Pre-state hash captured at import time -- BEFORE any test touches anything.
REAL_SHA_PRE = hashlib.sha256(REAL.read_bytes()).hexdigest()

# Fix under test (verbatim, content-anchored -- never file:line, L-0127/L-0023).
FIX_HEREDOC = 'python3 - "$CONFIG_FILE" << \'PYEOF\' || true'
FIX_TERM = "PYEOF"
# The broken state (re-applied by the dev-only oracle mutation).
BAD_HEREDOC = "python3 << 'PYEOF'"
BAD_TERM = 'PYEOF "$CONFIG_FILE" || true'

_IS_WIN = sys.platform.startswith("win")

# POSIX PATH_SAFE -- byte-identical to r1/r2 (hermeticity proven there; L-0130).
PATH_SAFE = "/usr/bin:/bin:/usr/sbin:/sbin"

# r3 P1-01: prescribed loud label when no Git Bash can be resolved (never silent).
GIT_BASH_MISSING_LABEL = "Git Bash not found; WSL bash would fail"

# Lazy cache of the resolved Git for Windows bash.exe (None until first spawn).
_WIN_BASH = None

# Claude Desktop config path mirroring uninstall.sh's $OSTYPE branches so the
# entry-removal assertion is portable across CI platforms (the sandbox pins the
# path the script actually resolves on THIS platform).
if sys.platform == "darwin":
    CFG_REL = Path("Library") / "Application Support" / "Claude" / "claude_desktop_config.json"
elif _IS_WIN:
    CFG_REL = Path("AppData") / "Roaming" / "Claude" / "claude_desktop_config.json"
else:
    CFG_REL = Path(".config") / "Claude" / "claude_desktop_config.json"

ENV_CONTENT = "FAKE_SECRET=sentinel-env-content\n"
ORIGINAL_SERVERS = {
    "polymarket": {"command": "python-fake-a", "args": ["-m", "fake_a"]},
    "other-mcp": {"command": "python-fake-b", "args": ["-m", "fake_b"]},
    "another": {"command": "python-fake-c"},
}


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
    "bash" (r3 P1-01).

    Why: subprocess.run on Windows resolves the executable via the CALLER's
    PATH (CreateProcess; the env= of the child does not participate in the
    lookup). CI evidence (PR #62/#68, windows-latest): a generic "bash" spawn
    found System32\\bash.exe (the WSL launcher), which exits rc=1 with an
    empty stderr and a UTF-16LE "wsl.exe --list --online" banner on stdout
    when no distro is installed. The r2 hypothesis (bash MISSING ->
    FileNotFoundError) was refuted by that evidence: the bash WAS found and
    executed -- it was the WRONG bash (classified by the observed mechanism,
    L-0052/L-0020).

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
    """Full bash executable for subprocess spawns (r3 P1-01).

    POSIX: the generic "bash" is kept (r1/r2-proven: the caller PATH there is
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
    PATH (r3 prescription 4: the child needs the coreutils). Also load-bearing
    for the Git\\bin\\bash.exe DLL discovery (msys-2.0.dll lives in usr\\bin;
    the Windows DLL search falls through to PATH dirs)."""
    exe = Path(_bash_exe())
    if exe.parent.name == "bin" and exe.parent.parent.name == "usr":
        return exe.parent  # ...\\Git\\usr\\bin\\bash.exe -> ...\\Git\\usr\\bin
    return exe.parent.parent / "usr" / "bin"  # ...\\Git\\bin\\bash.exe -> ...\\Git\\usr\\bin


def _win_path_prefix(shim_dir=None):
    """Child PATH prefix on the win branch: msys coreutils (usr\\bin) FIRST,
    then the sandbox shim dir (python3/clear fallbacks), so sandbox-provided
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
    platform (provenance: CPython Lib/os.py read first-hand 2026-09-18).
    """
    for k, v in env.items():
        if k.upper() == name.upper():
            return v
    raise KeyError(name)


def _probe_env():
    """Env for syntax probes (bash -n executes nothing).

    POSIX: minimal explicit env, byte-identical to r1/r2 (hermeticity proven).
    Win (r3 P2-01): dict(os.environ) + overrides -- a minimal env WITHOUT
    SystemRoot breaks msys-2.0.dll (bpo-34204 class). Overrides here: PATH
    (usr\\bin first), TERM.
    """
    if not _IS_WIN:
        return {"PATH": PATH_SAFE, "TERM": "xterm"}
    env = dict(os.environ)
    env["PATH"] = _win_path_prefix() + os.pathsep + env.get("PATH", "")
    env["TERM"] = "xterm"
    return env


def _run_env(home, shim_dir=None):
    """Env for execution.

    POSIX: minimal explicit env (PATH_SAFE, TERM, sandboxed HOME) -- nothing
    else inherited from the host (hermeticity direction 2, L-0130, r1/r2-proven).
    Win (r3 P2-01): dict(os.environ) + overrides (PATH/HOME/APPDATA/TERM) --
    SystemRoot and friends MUST survive (msys-2.0.dll requirement).
    """
    if not _IS_WIN:
        if shim_dir is not None:
            raise RuntimeError(
                "shim_dir is a Windows-sandbox provision (POSIX resolves python3 natively)"
            )
        return {"PATH": PATH_SAFE, "TERM": "xterm", "HOME": str(home)}
    env = dict(os.environ)
    env["PATH"] = _win_path_prefix(shim_dir) + os.pathsep + env.get("PATH", "")
    env["TERM"] = "xterm"
    env["HOME"] = str(home)
    # uninstall.sh resolves CONFIG_DIR=$APPDATA/Claude under msys/cygwin
    # (Git Bash: OSTYPE=msys); the sandbox pins APPDATA so the resolved config
    # IS the sandboxed one (r2, CI-proven geometry).
    env["APPDATA"] = str(home / "AppData" / "Roaming")
    # The heredoc python prints unicode glyphs; a pipe stdout on Windows
    # defaults to the ANSI code page (cp1252) and would die on them. Pin
    # utf-8 so the child interpreter is deterministic (the script's `|| true`
    # absorbs even the failure case, but the traceback noise would be
    # confusing).
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _ensure_shims(bin_dir):
    """Provision sandbox executables the script needs that a Windows runner
    lacks (r3 P2-02 + clear fallback). Writes are confined to the sandbox
    tmpdir.

    python3: the script invokes literal `python3` (the :141 heredoc); Windows
    runners ship python.exe, not python3.exe. A copy/hardlink of
    sys.executable named python3.exe would NOT work: the Windows interpreter
    discovers pythonXY.dll (and, for venv launchers, pyvenv.cfg) relative to
    the executable's own directory, so a relocated copy fails init -- and the
    script's `|| true` would absorb that failure silently, leaving the config
    untouched (the exact silent-failure class this suite pins). Instead: a
    shebang script (msys bash executes shebang scripts found on PATH without
    an extension) that execs the interpreter IN PLACE, where its DLLs and
    pyvenv.cfg live.

    clear: fallback only -- usr\\bin precedes the shim dir in the child PATH,
    so the real msys clear.exe wins when present; the shim only fills a
    runner-packaging gap (a missing clear under `set -e` would kill the
    script before any uninstall step).
    """
    if not _IS_WIN:
        raise RuntimeError(
            "sandbox shims are a Windows-only provision (POSIX resolves python3 natively)"
        )
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = Path(sys.executable)
    python3 = bin_dir / "python3"
    python3.write_text(f"#!/bin/sh\nexec '{exe.as_posix()}' \"$@\"\n", encoding="ascii")
    clear = bin_dir / "clear"
    clear.write_text("#!/bin/sh\nprintf '\\033[H\\033[2J'\n", encoding="ascii")
    python3.chmod(0o755)
    clear.chmod(0o755)
    # Application proof (L-0112): exactly two shims, content-anchored.
    names = sorted(p.name for p in bin_dir.iterdir())
    assert names == ["clear", "python3"], f"unexpected sandbox bin contents: {names}"
    text = python3.read_text(encoding="ascii")
    assert text.startswith("#!/bin/sh\nexec '"), "python3 shim must exec the interpreter in place"
    assert exe.as_posix() in text, "python3 shim must point at the real interpreter"
    assert '"$@"' in text, "python3 shim must forward argv"
    return bin_dir


def _copy_byte_exact(tmp_path):
    """Copy the REAL script byte-exactly into the sandbox (P-0018)."""
    dst = tmp_path / "uninstall.sh"
    dst.write_bytes(REAL.read_bytes())
    post = hashlib.sha256(dst.read_bytes()).hexdigest()
    assert post == REAL_SHA_PRE, "sandbox copy is not byte-identical to the real script"
    return dst


def _bash_n(script):
    """bash -n syntax probe (P-0021 sentinel rc=99; FULL resolved bash path on
    the win branch -- r3 P1-01)."""
    rc = 99
    stderr = ""
    try:
        proc = subprocess.run(
            [_bash_exe(), "-n", str(script)],
            capture_output=True,
            env=_probe_env(),
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:  # hang guard: fails LOUD, not dead
        stderr = f"TIMEOUT (hang guard): {(exc.stderr or b'').decode('utf-8', errors='replace')}"
    else:
        rc = proc.returncode
        stderr = proc.stderr.decode("utf-8", errors="replace")
    return rc, stderr


def _run_force(script, cwd, home):
    """Run the SANDBOX COPY with --force (never the real script). On the win
    branch, provisions the sandbox shims (python3/clear) FIRST so the child
    PATH can resolve them (r3 P2-02). rc starts as the P-0021 sentinel 99 and
    is only overwritten after a successful run."""
    shim_dir = None
    if _IS_WIN:
        shim_dir = script.parent / ".sandbox-bin"
        _ensure_shims(shim_dir)
    rc = 99
    stdout = ""
    stderr = ""
    try:
        proc = subprocess.run(
            [_bash_exe(), str(script), "--force"],
            cwd=str(cwd),
            env=_run_env(home, shim_dir=shim_dir),
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:  # hang guard: fails LOUD, not dead
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = f"TIMEOUT (hang guard): {(exc.stderr or b'').decode('utf-8', errors='replace')}"
    else:
        rc = proc.returncode
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
    return rc, stdout, stderr


def _mutate_revert_fix(src, dst):
    """Dev-only oracle mutation: revert the 2 fix lines on the SECOND copy
    (never the real script -- L-0128a: substitution, never deletion)."""
    text = src.read_text(encoding="utf-8")
    n_open = text.count(FIX_HEREDOC)
    assert n_open == 1, (
        f"mutation precondition failed: FIX_HEREDOC occurs {n_open} times (expected 1)"
    )
    text = text.replace(FIX_HEREDOC, BAD_HEREDOC)
    lines = text.splitlines(keepends=True)
    lone = [i for i, line in enumerate(lines) if line.strip() == FIX_TERM]
    assert len(lone) == 1, (
        f"mutation precondition failed: lone terminator appears on {len(lone)} lines (expected 1)"
    )
    eol = "\n" if lines[lone[0]].endswith("\n") else ""
    lines[lone[0]] = BAD_TERM + eol
    dst.write_text("".join(lines), encoding="utf-8")
    # Application proof (L-0112): each mutation applied exactly once, in the copy.
    mutated = dst.read_text(encoding="utf-8")
    assert BAD_HEREDOC in mutated, "mutation 1 (heredoc open) not applied in the copy"
    assert BAD_TERM in mutated, "mutation 2 (terminator suffix) not applied in the copy"
    assert FIX_HEREDOC not in mutated, "fix line survived the mutation (no-op)"
    assert not [line for line in mutated.splitlines() if line.strip() == FIX_TERM], (
        "lone terminator survived the mutation (no-op)"
    )


def test_bash_n_valid_after_fix(tmp_path):
    """The copy of the FIXED script parses (rc=0); the dev-only oracle reverts
    the two fix lines on a second copy and bash -n fails again (rc=2)."""
    copy = _copy_byte_exact(tmp_path)
    rc, stderr = _bash_n(copy)
    assert rc == 0, f"bash -n must accept the fixed script; stderr: {stderr}"
    mutated = tmp_path / "uninstall.sh.reverted"
    _mutate_revert_fix(copy, mutated)
    rc2, stderr2 = _bash_n(mutated)
    assert rc2 == 2, f"oracle must know how to fail: rc={rc2}, stderr: {stderr2}"
    assert "unexpected end of file" in stderr2, (
        f"oracle failure must be the parse error itself; stderr: {stderr2}"
    )


def test_heredoc_passes_config_file_arg(tmp_path):
    """Content anchors: the heredoc open passes $CONFIG_FILE as argv and the
    terminator is alone on its own line (verified line by line)."""
    copy = _copy_byte_exact(tmp_path)
    text = copy.read_text(encoding="utf-8")
    # Positive (paired with the negations -- L-0056): the fix literal is present.
    assert FIX_HEREDOC in text, (
        "heredoc must pass $CONFIG_FILE as argv (python3 - \"$CONFIG_FILE\")"
    )
    # Negation: the terminator is never seen with a suffix anywhere.
    assert 'PYEOF "$CONFIG_FILE"' not in text, (
        "terminator must be alone on its own line"
    )
    # Terminator alone, verified line by line: exactly one lone 'PYEOF'.
    lone = [line for line in text.splitlines() if line.strip() == FIX_TERM]
    assert len(lone) == 1, f"expected exactly 1 lone 'PYEOF' line, got {len(lone)}"


def test_force_uninstall_removes_entry_and_preserves_others(tmp_path):
    """Sandbox (HOME + cwd inside tmp): fake .env, fake config (path mirrored
    per platform via CFG_REL) with polymarket + other-mcp + another, fake
    venv/ (empty dir) -> `bash <copy> --force` rc=0; .env GONE and .env.backup
    with the old content; config after: polymarket ABSENT, other-mcp+another
    PRESERVED; ${CONFIG_FILE}.backup exists with the whole original config;
    summary 'Uninstallation Complete' present on stdout."""
    home = tmp_path / "sb"
    cfg = home / CFG_REL
    cfg.parent.mkdir(parents=True)
    original_config = {"mcpServers": ORIGINAL_SERVERS}
    cfg.write_text(json.dumps(original_config, indent=2) + "\n", encoding="utf-8")

    (tmp_path / ".env").write_text(ENV_CONTENT, encoding="utf-8")
    (tmp_path / "venv").mkdir()  # fake venv: empty dir

    copy = _copy_byte_exact(tmp_path)
    rc, stdout, stderr = _run_force(copy, cwd=tmp_path, home=home)

    assert rc == 0, f"script must exit 0; stderr: {stderr}\nstdout tail: {stdout[-400:]}"
    # .env GONE, .env.backup with the old content.
    assert not (tmp_path / ".env").exists(), ".env must be removed (moved)"
    backup = tmp_path / ".env.backup"
    assert backup.exists(), ".env.backup must exist after the uninstall"
    assert backup.read_text(encoding="utf-8") == ENV_CONTENT, ".env.backup holds the old content"
    # Fake venv removed (step 1 of the observed flow).
    assert not (tmp_path / "venv").exists(), "venv/ must be removed"

    # Config after: polymarket ABSENT, other-mcp+another PRESERVED.
    post = json.loads(cfg.read_text(encoding="utf-8"))
    post_servers = post.get("mcpServers", {})
    assert "polymarket" not in post_servers, "polymarket entry must be removed"
    assert post_servers.get("other-mcp") == ORIGINAL_SERVERS["other-mcp"], (
        "other-mcp must be preserved"
    )
    assert post_servers.get("another") == ORIGINAL_SERVERS["another"], "another must be preserved"

    # ${CONFIG_FILE}.backup exists with the WHOLE original config.
    cfg_backup = cfg.parent / (cfg.name + ".backup")
    assert cfg_backup.exists(), "config backup must exist"
    assert json.loads(cfg_backup.read_text(encoding="utf-8")) == original_config, (
        "config backup must hold the whole original config"
    )

    # Summary on stdout.
    assert "Uninstallation Complete" in stdout, f"summary missing; stdout: {stdout[-600:]}"


def test_uninstall_clean_slate_rc0(tmp_path):
    """Clean-slate sandbox (no .env, no config): rc=0 with the 'not found'
    messages -- clean-state idempotency; NEVER an error."""
    home = tmp_path / "sb"
    home.mkdir()
    copy = _copy_byte_exact(tmp_path)
    rc, stdout, stderr = _run_force(copy, cwd=tmp_path, home=home)
    assert rc == 0, f"clean slate must exit 0; stderr: {stderr}"
    assert "Virtual environment not found" in stdout
    assert "Environment file not found" in stdout
    assert "Claude Desktop config not found" in stdout
    assert "Uninstallation Complete" in stdout
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / ".env.backup").exists()
    assert not (home / CFG_REL).exists()


def test_real_file_tripwire():
    """The suite NEVER touches the real script: sha256 pre (import time)
    == post (now)."""
    post = hashlib.sha256(REAL.read_bytes()).hexdigest()
    assert post == REAL_SHA_PRE, "real uninstall.sh was modified by the suite run (tripwire)"


def test_win_bash_resolution_prefers_git_bash_in_order(monkeypatch):
    """Dev-only proof (any platform) of the r3 P1-01 mechanism: the candidate
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
    """Dev-only proof (any platform) of the r3 P1-01 fallback + loud guard:
    shutil.which("git") -> dirname(dirname(git)) sibling bin\\bash.exe; with
    NO candidate anywhere the resolution is LOUD with the prescribed label
    (never silent -- the r2 silent-rc=1 class is exactly what CI refuted)."""
    git_exe = Path("C:/Program Files/Git/cmd/git.exe")
    root_bash = Path("C:/Program Files/Git/bin/bash.exe")
    monkeypatch.setattr(Path, "is_file", lambda self: self == root_bash)
    got = _resolve_win_bash(candidates=[], which_fn=lambda _n: str(git_exe))
    assert got == root_bash, "fallback must resolve bash.exe beside the git.exe root"
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    with pytest.raises(RuntimeError, match="Git Bash not found; WSL bash would fail"):
        _resolve_win_bash(candidates=[], which_fn=lambda _n: None)


def test_win_subprocess_receives_full_bash_path(tmp_path, monkeypatch):
    """Dev-only proof (any platform) of the r3 P1-01/P2-01/P2-02 plumbing:
    with the win branch active, BOTH spawn helpers pass the FULL resolved bash
    path as argv[0] (never the generic "bash") and the child env is
    dict(os.environ) merged (SystemRoot inherited -- P2-01) with the sandbox
    overrides. Counts and paths asserted (L-0112)."""
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
        stdout = b""
        stderr = b""

    captured = []

    def fake_run(argv, **kwargs):
        captured.append((list(argv), kwargs.get("env")))
        return _FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)

    copy = _copy_byte_exact(tmp_path)
    rc, stderr = _bash_n(copy)
    assert rc == 0 and len(captured) == 1, f"one -n spawn expected; got {len(captured)}"
    argv, env = captured[0]
    assert argv == [str(fake_bash), "-n", str(copy)]
    assert argv[0] != "bash", "spawn must NEVER use the generic 'bash' on the win branch"
    assert _env_get(env, "SystemRoot") == "C:\\Windows", "merged env must keep SystemRoot (P2-01)"

    captured.clear()
    home = tmp_path / "sb"
    rc, stdout, stderr = _run_force(copy, cwd=tmp_path, home=home)
    assert rc == 0 and len(captured) == 1, f"one --force spawn expected; got {len(captured)}"
    argv, env = captured[0]
    assert argv == [str(fake_bash), str(copy), "--force"]
    assert argv[0] != "bash"
    assert _env_get(env, "SystemRoot") == "C:\\Windows"
    assert env["HOME"] == str(home) and env["APPDATA"] == str(home / "AppData" / "Roaming")
    parts = env["PATH"].split(os.pathsep)
    assert parts[0] == str(tmp_path / "fake" / "Git" / "usr" / "bin"), (
        "usr/bin must lead the child PATH"
    )
    assert str(tmp_path / ".sandbox-bin") in parts[:2], "shim dir must be on the child PATH (P2-02)"


def test_win_env_merges_system_root_and_overrides(monkeypatch):
    """r3 P2-01: on the win branch the child env is dict(os.environ) WITH the
    overrides (PATH/HOME/APPDATA/TERM) -- a minimal env without SystemRoot
    breaks msys-2.0.dll (bpo-34204 class). On POSIX the minimal explicit env
    stays byte-identical to r1/r2 (no host inheritance)."""
    mod = sys.modules[__name__]
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    monkeypatch.setenv("FARM_T0214_HOST_ONLY", "host-value")
    monkeypatch.setattr(mod, "_IS_WIN", False)
    assert _probe_env() == {"PATH": PATH_SAFE, "TERM": "xterm"}
    fake_bash = Path("C:/Program Files/Git/bin/bash.exe")
    monkeypatch.setattr(mod, "_IS_WIN", True)
    monkeypatch.setattr(mod, "_WIN_BASH", fake_bash)
    env = _probe_env()
    assert _env_get(env, "SystemRoot") == "C:\\Windows", "P2-01: SystemRoot must survive the win env merge"
    assert env["FARM_T0214_HOST_ONLY"] == "host-value", "win env is a MERGE, not a reset"
    assert env["TERM"] == "xterm"
    # PATH assertion via prefix (the fake win path contains ":", which would
    # collide with os.pathsep on POSIX proof hosts -- L-0052-class care).
    assert env["PATH"].startswith(str(Path("C:/Program Files/Git/usr/bin")) + os.pathsep)
    home = Path("/T0214-sandbox-home")
    env = _run_env(home)
    assert env["HOME"] == str(home), "HOME must be overridden to the sandbox"
    assert env["APPDATA"] == str(home / "AppData" / "Roaming"), "APPDATA must be sandbox-pinned"
    assert _env_get(env, "SystemRoot") == "C:\\Windows"
    assert env["FARM_T0214_HOST_ONLY"] == "host-value"
    assert env["PATH"].startswith(str(Path("C:/Program Files/Git/usr/bin")) + os.pathsep)


def test_win_sandbox_shims_provisioned(tmp_path, monkeypatch):
    """r3 P2-02 dev-only proof (any platform): the sandbox shims are written
    INSIDE the tmpdir only, `python3` is an in-place exec shebang of the real
    interpreter, and the shim dir lands on the CHILD PATH right after
    usr/bin. POSIX NEVER provisions (loud misuse guard) and keeps the r1/r2
    minimal env."""
    mod = sys.modules[__name__]
    monkeypatch.setattr(mod, "_IS_WIN", False)
    with pytest.raises(RuntimeError, match="Windows-only provision"):
        _ensure_shims(tmp_path / "bin-posix")
    monkeypatch.setattr(mod, "_IS_WIN", True)
    bin_dir = _ensure_shims(tmp_path / "bin-win")
    assert sorted(p.name for p in bin_dir.iterdir()) == ["clear", "python3"]
    python3 = bin_dir / "python3"
    text = python3.read_text(encoding="ascii")
    assert text.startswith("#!/bin/sh\nexec '")
    assert Path(sys.executable).as_posix() in text
    assert '"$@"' in text
    assert (bin_dir / "clear").read_text(encoding="ascii").startswith("#!/bin/sh\nprintf")
    fake_bash = Path("C:/Program Files/Git/bin/bash.exe")
    monkeypatch.setattr(mod, "_WIN_BASH", fake_bash)
    home = tmp_path / "sb"
    env = _run_env(home, shim_dir=bin_dir)
    # PATH prefix assertion (the fake win path contains ":", which would
    # collide with os.pathsep on POSIX proof hosts).
    expected_prefix = (
        str(Path("C:/Program Files/Git/usr/bin")) + os.pathsep + str(bin_dir) + os.pathsep
    )
    assert env["PATH"].startswith(expected_prefix), (
        "shim dir must come right after usr/bin on the child PATH"
    )
    # POSIX run env must never carry the shim (hermeticity r1/r2 intact).
    monkeypatch.setattr(mod, "_IS_WIN", False)
    with pytest.raises(RuntimeError, match="POSIX resolves python3 natively"):
        _run_env(home, shim_dir=bin_dir)
    assert _run_env(home) == {"PATH": PATH_SAFE, "TERM": "xterm", "HOME": str(home)}
