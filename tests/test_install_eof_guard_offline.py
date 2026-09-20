"""
Offline sandbox suite for install.sh -- stdin-EOF fail-loud guards (T-0388,
REQUER-HUMANO item 105).

Contract (task T-0388): the two wallet reads in configure_env are guarded
against stdin EOF so the script fails LOUD with an explicit diagnostic
instead of dying silently under `set -e`:

  G1: `read -r -s PRIVATE_KEY` gains
      `|| { print_error "Input stream ended before a private key was provided"; return 1; }`
  G2: `read -r WALLET_ADDRESS` gains
      `|| { print_error "Input stream ended before a wallet address was provided"; return 1; }`

Red pre-fix (first-hand probe, 2026-09-19, install.sh at main tip 86a4fd8 --
byte-identical to the snapshot 7c88d6b cited by the contract): EOF at the
wallet reads kills the script with rc=1 WITHOUT any diagnostic:

  (a) stdin='y\\n' via INSTALL_TEST_MODE=1 source + `DEMO_MODE=false;
      configure_env`: the y/n prompt reads 'y', the key read consumes the
      residual newline as an EMPTY line (rc=0, "Invalid private key format"
      printed, loop iterates), the SECOND key read hits EOF and `set -e`
      kills the driver -- rc=1, message absent. NOT a hang: `set -e` kills
      it (the contract's r1 premise of "infinite loop with stdin EOF" is
      REFUTED for install.sh -- the divergence is DECLARED per L-0025; the
      prescribed fix, fail-loud with a message, is identical in both
      states). TimeoutExpired is therefore NOT the discriminating signal
      anywhere in this suite (it is a safety net, never the oracle).
  (b) stdin='y\\n<64-hex>\\n': key validates on the second read, the address
      read hits EOF -- same silent death, .env never written (the write at
      install.sh:313 happens AFTER all prompts, so EOF mid-prompt never
      leaves a partial .env).
  (c) full script `bash install.sh < /dev/null` in a HOME sandbox: rc=1
      with the pre-existing "Installation failed!" trap (the banner's
      "Press Enter to continue..." read EOFs BEFORE any wallet prompt).

Mechanism (sibling-suite pattern, T-0215/T-0221): INSTALL_TEST_MODE=1
source install.sh inside a bash subprocess; stdin limited with a BONDED
timeout (the script dies fast under `set -e`; a TimeoutExpired is captured
and declared as UNEXPECTED-HANG -- the suite NEVER hangs). Sandbox per test
(pytest tmp_path, never inside the repo): byte-exact install.sh copy, cwd
sandboxed, HOME sandboxed; the real install.sh is tripwired by sha256
before/after every test. All spawns use _bash_exe() (T-0364 pattern verbatim
-- a generic "bash" spawn is a Windows hazard: subprocess.run resolves the
executable via the CALLER's PATH, the first bash.exe hit is the System32 WSL
launcher).

Anti-over-fix (prescribed): the y/n prompts (:246/:288/:298) and the numeric
prompts (:292/:295) stay INTACT -- EOF on them kills rc=1 by `set -e` with
no diagnostic (pre-existing behavior, pinned as regression). The suite pins
the OBSERVED states (L-0090/L-0025), never the contract's stale premise.

Declarations (L-0025/L-0020):
- Red pre-fix OBSERVED (first-hand, this suite on pristine install.sh):
  4 failed / 3 passed. Failing: test 2 and test 3 (prescribed message
  absent), test 6 (stream-end count 0 != 1 -- the RED the contract's own
  suite section prescribes: "Pre-fix: 'Input stream ended' count == 0 ->
  RED on the count assert, the discriminating observable"), and the
  structural tripwire test 7 (guards absent by construction). The
  contract's restrição-2 sentence ("2/3 fail ... 1/4/5/6 pass") conflicts
  with its own suite section on test 6; the suite section prevails
  (L-0025: observables over prose) -- divergence declared in the report.
- No python/python3 shims are provisioned: this suite never invokes
  configure_claude_desktop (heredoc python) and check_python is unreachable
  (the full-script test dies at the "Press Enter" read before it) --
  sandbox parity notes declared, not divergences.
"""

import hashlib
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"

# Prescribed messages (verbatim, ASCII-only; pins match by substring).
MSG_KEY = "Input stream ended before a private key was provided"
MSG_ADDR = "Input stream ended before a wallet address was provided"
MSG_STREAM_END = "Input stream ended"

# Synthetic wallet credentials (never real; both validate in install.sh).
_VALID_KEY = "a" * 64
_VALID_ADDR = "0x" + "b" * 40

# Bonded spawn timeout: the script dies fast under `set -e` (probe-proven);
# a TimeoutExpired is declared as UNEXPECTED-HANG, never left to hang the
# suite.
_SPAWN_TIMEOUT = 15

# Prescribed guard shapes (structural tripwire; content-anchored, never
# line-numbered -- L-0171/L-0148). The fix is prescribed as 2 small hunks
# (6 added lines, 2 replaced): each read line is followed by a multi-line
# `|| { print_error <message>; return 1; }` block in the file's indentation
# style, so the pin anchors the read-line prefix + the prescribed message
# inside the block, each exactly once.
GUARD_KEY_READ = "read -r -s PRIVATE_KEY || {"
GUARD_ADDR_READ = "read -r WALLET_ADDRESS || {"
GUARD_KEY_MSG = 'print_error "%s"' % MSG_KEY
GUARD_ADDR_MSG = 'print_error "%s"' % MSG_ADDR

# ---------------------------------------------------------------------------
# Platform-aware plumbing (T-0364 pattern verbatim for _bash_exe; sibling
# pattern test_install_env_safety_offline.py for the win env prefix).
# ---------------------------------------------------------------------------
_IS_WIN = sys.platform.startswith("win")

# POSIX PATH_SAFE -- r1-proven hermetic baseline (sibling suites).
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
    "bash" (T-0364 pattern).

    Why: subprocess.run on Windows resolves the executable via the CALLER's
    PATH (CreateProcess; the env= of the child does not participate in the
    lookup). CI evidence (T-0214 r3, PR #62/#68, windows-latest): a generic
    "bash" spawn found System32\\bash.exe (the WSL launcher), which exits
    rc=1 with an empty stderr and a UTF-16LE banner on stdout when no distro
    is installed -- the bash WAS found and executed, it was the WRONG bash.
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
    """Full bash executable for subprocess spawns (T-0364 pattern verbatim).

    POSIX: the absolute literal /bin/bash is kept -- this suite's spawns
    pass a SANDBOX-ONLY child PATH (the host PATH is never inherited in the
    sourced-driver spawns), and POSIX subprocess resolves argv[0] via
    os.get_exec_path(env), i.e. the CHILD env PATH (first-hand probe,
    T-0364: FileNotFoundError on bare "bash" with a bash-less child PATH).
    Windows: the FULL resolved Git for Windows bash.exe -- never the generic
    "bash" (its lookup would use the caller PATH and hit the System32 WSL
    launcher; the child env PATH does not change the spawn resolution).
    """
    global _WIN_BASH
    if not _IS_WIN:
        return "/bin/bash"
    if _WIN_BASH is None:
        _WIN_BASH = _resolve_win_bash()
    return str(_WIN_BASH)


def _win_usr_bin():
    """Coreutils dir of the resolved Git for Windows (usr\\bin) for the child
    PATH: the driver and the full-script test need cp/clear/rm/echo tools,
    all msys coreutils. Also load-bearing for the Git\\bin\\bash.exe DLL
    discovery (msys-2.0.dll lives in usr\\bin)."""
    exe = Path(_bash_exe())
    if exe.parent.name == "bin" and exe.parent.parent.name == "usr":
        return exe.parent  # ...\\Git\\usr\\bin\\bash.exe -> ...\\Git\\usr\\bin
    return exe.parent.parent / "usr" / "bin"  # ...\\Git\\bin\\bash.exe -> ...\\Git\\usr\\bin


def _win_path_prefix():
    """Child PATH prefix on the win branch: msys coreutils (usr\\bin) FIRST,
    then the host PATH remainder (no python shims needed here -- this suite
    never invokes configure_claude_desktop, and check_python is unreachable)."""
    return str(_win_usr_bin())


def _child_path():
    """PATH handed to the child process.

    POSIX: hermetic PATH_SAFE (cp/clear/awk/sed/cut/rm all live there on the
    CI matrix hosts). WIN: msys usr\\bin FIRST, then the host PATH remainder
    (SystemRoot survives via dict(os.environ) in the callers -- P2-01)."""
    if not _IS_WIN:
        return PATH_SAFE
    return _win_path_prefix() + os.pathsep + os.environ.get("PATH", "")


def _run_env(home: Path):
    """Env for execution (sibling pattern).

    POSIX: minimal explicit env -- nothing else inherited from the host
    (hermeticity, L-0130). WIN (P2-01): dict(os.environ) + overrides
    (PATH/HOME/TERM) -- SystemRoot and friends MUST survive (msys-2.0.dll
    requirement, bpo-34204 class) + PYTHONIOENCODING=utf-8 (deterministic
    child output; the sibling suites use it for glyph parity)."""
    if not _IS_WIN:
        return {
            "PATH": _child_path(),
            "TERM": "xterm",
            "HOME": str(home),
        }
    env = dict(os.environ)
    env["PATH"] = _child_path()
    env["TERM"] = "xterm"
    env["HOME"] = str(home)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _probe_env():
    """Env for syntax probes (bash -n executes nothing from PATH)."""
    if not _IS_WIN:
        return {"PATH": PATH_SAFE, "TERM": "xterm"}
    env = dict(os.environ)
    env["PATH"] = _win_path_prefix() + os.pathsep + env.get("PATH", "")
    env["TERM"] = "xterm"
    return env


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_sandbox(tmp_path: Path) -> Path:
    """Build a hermetic sandbox: byte-exact install.sh copy, empty HOME.
    No shims are provisioned (see module header declaration)."""
    sb = tmp_path / "sb"
    (sb / "home").mkdir(parents=True)
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


def _spawn(sb: Path, body: str, stdin_text: str, sourced: bool = True):
    """Run the prescribed driver in a subprocess with LIMITED stdin.

    Contract prescription: spawns use [_bash_exe(), "-c", script]. The
    sourced drivers run `set -e; INSTALL_TEST_MODE=1; source install.sh;
    <body>` (the INSTALL_TEST_MODE seam -- install.sh:604-607 -- keeps the
    interactive main() out); the full-script driver runs the script
    end-to-end with EOF stdin. Timeout is BONDED: TimeoutExpired is
    declared as UNEXPECTED-HANG (fail-loud, never hangs the suite)."""
    if sourced:
        script = (
            "set -e\n"
            f"cd {shlex.quote(str(sb))}\n"
            f"export HOME={shlex.quote(str(sb / 'home'))}\n"
            f"export PATH={shlex.quote(_child_path())}\n"
            "export TERM=xterm\n"
            "export INSTALL_TEST_MODE=1\n"
            f"source {shlex.quote(str(sb / 'install.sh'))}\n"
            f"{body}\n"
        )
    else:
        script = (
            "set -e\n"
            f"cd {shlex.quote(str(sb))}\n"
            f"export HOME={shlex.quote(str(sb / 'home'))}\n"
            f"export PATH={shlex.quote(_child_path())}\n"
            "export TERM=xterm\n"
            f"bash {shlex.quote(str(sb / 'install.sh'))}\n"
        )
    try:
        return subprocess.run(
            [_bash_exe(), "-c", script],
            capture_output=True,
            # [ci-unblock-r3 2026-09-19, canal do dono] stdin em BYTES: com text=True o
            # Windows traduz \n -> \r\n no stdin e o `read` do install.sh recebe CR --
            # o prompt itera "Invalid private key format" e o EOF guard NUNCA dispara
            # (run 3545... test_eof_at_wallet_address_read_fails_loud). Classe L-0316
            # (win env merge). O output cru é decodificado em _output (errors=replace).
            cwd=str(sb),
            env=_run_env(sb / "home"),
            input=stdin_text.encode("utf-8"),
            timeout=_SPAWN_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"UNEXPECTED-HANG: stdin EOF must terminate fast under set -e "
            f"(timeout={_SPAWN_TIMEOUT}s; body={body!r})",
            pytrace=False,
        )


def _output(proc) -> str:
    """stdout+stderr joined: bash `read -p` writes prompts to STDERR when
    stdin is not a TTY, and print_error writes to STDOUT -- the diagnostic
    observables may land on either stream."""
    def _d(b):
        return b.decode("utf-8", "replace") if isinstance(b, bytes) else (b or "")
    return _d(proc.stdout) + _d(proc.stderr)


def _assert_no_env(sb: Path) -> None:
    """The .env write (install.sh:313) happens AFTER all wallet prompts --
    EOF mid-prompt NEVER leaves a partial .env in the sandbox cwd."""
    assert not (sb / ".env").exists(), (
        ".env was created despite the EOF death (the write must come after all prompts)"
    )


@pytest.fixture(autouse=True)
def _tripwire_real_install_sh():
    before = _sha256_file(INSTALL_SH)
    yield
    assert _sha256_file(INSTALL_SH) == before, "real install.sh was modified by the suite"
    assert not (REPO_ROOT / ".env").exists(), (
        ".env leaked into the repo root (P-0132 hermeticity guard)"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_syntax_valid(tmp_path: Path) -> None:
    """bash -n on a byte-exact copy of install.sh must succeed (rc=0)."""
    sb = _make_sandbox(tmp_path)
    proc = _run_bash_n(sb / "install.sh")
    assert proc.returncode == 0, proc.stderr


def test_eof_at_private_key_read_fails_loud(tmp_path: Path) -> None:
    """EOF right after the wallet y/n prompt: fail LOUD with the prescribed
    message, rc!=0, .env never written.

    stdin='y\\n': y/n reads 'y' (residual newline left in the stream), key
    read #1 consumes the empty line -> "Invalid private key format" printed,
    the loop iterates, key read #2 hits EOF. Pre-fix: silent death (rc=1,
    message ABSENT) -- the MESSAGE is the discriminating observable (rc=1 in
    both states, contract-declared)."""
    sb = _make_sandbox(tmp_path)
    proc = _spawn(sb, "DEMO_MODE=false\nconfigure_env", "y\n")
    assert proc.returncode != 0, "EOF at the key read must fail (rc!=0)"
    out = _output(proc)
    assert MSG_KEY in out, (
        f"prescribed diagnostic missing after EOF at the key read:\n--- stdout ---\n"
        f"{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    _assert_no_env(sb)


def test_eof_at_wallet_address_read_fails_loud(tmp_path: Path) -> None:
    """EOF after a valid private key: fail LOUD with the prescribed address
    message, rc!=0, .env never written.

    stdin='y\\n<64-hex>\\n': key read #1 consumes the residual empty line
    (validation error printed), key read #2 reads the valid key, the address
    read hits EOF. Pre-fix: silent death; post-fix: the G2 diagnostic."""
    sb = _make_sandbox(tmp_path)
    proc = _spawn(sb, "DEMO_MODE=false\nconfigure_env", f"y\n{_VALID_KEY}\n")
    assert proc.returncode != 0, "EOF at the address read must fail (rc!=0)"
    out = _output(proc)
    assert MSG_ADDR in out, (
        f"prescribed diagnostic missing after EOF at the address read:\n--- stdout ---\n"
        f"{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    _assert_no_env(sb)


def test_full_script_eof_regression_pin(tmp_path: Path) -> None:
    """Full script with EOF stdin: the PRE-EXISTING error path is unchanged
    (regression pin; anti-over-fix).

    `bash install.sh` with EOF stdin dies at the banner's "Press Enter to
    continue..." read -- BEFORE any wallet prompt -- so the pre-existing
    ERR-trap rollback prints "Installation failed!" and cleans up. The y/n
    prompts are NOT guarded (unchanged pre/post); no guard message may
    appear (the death happens before the wallet section)."""
    sb = _make_sandbox(tmp_path)
    proc = _spawn(sb, "", "", sourced=False)
    assert proc.returncode != 0, "EOF stdin must fail the full script (rc!=0)"
    out = _output(proc)
    assert "Installation failed!" in out, (
        f"pre-existing error treatment missing:\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
    assert MSG_STREAM_END not in out, (
        "guard message must NOT appear for the unguarded banner read (anti-over-fix)"
    )
    _assert_no_env(sb)


def test_numeric_prompt_eof_regression_pin(tmp_path: Path) -> None:
    """EOF at the numeric limits prompts: pre-existing silent death unchanged
    (regression pin; anti-over-fix).

    stdin='y\\n<64-hex>\\n0x<40-hex>\\ny\\n': the wallet flow completes (key
    and address validate on their reads), the safety-limits y/n reads 'y'
    (residual newline left), the first numeric read consumes the empty line
    (default applies), the second numeric read hits EOF -- `set -e` kills
    the script (the numeric reads are UNTOUCHED by the guards). .env is
    never written (the write comes after ALL prompts)."""
    sb = _make_sandbox(tmp_path)
    proc = _spawn(
        sb,
        "DEMO_MODE=false\nconfigure_env",
        f"y\n{_VALID_KEY}\n{_VALID_ADDR}\ny\n",
    )
    assert proc.returncode != 0, "EOF at the numeric read must fail (rc!=0)"
    out = _output(proc)
    assert MSG_STREAM_END not in out, (
        "guard message must NOT appear for the numeric reads (anti-over-fix)"
    )
    _assert_no_env(sb)


def test_validation_errors_distinct_from_stream_end(tmp_path: Path) -> None:
    """Validation and stream-end diagnostics must stay DISTINCT: the guard
    never replaces validation.

    stdin='y\\nzz\\n': key read #1 consumes the residual empty line ->
    "Invalid private key format" printed (validation working); key read #2
    reads 'zz' -> invalid again; key read #3 hits EOF -> the G1 guard fires
    EXACTLY once (only the final EOF; no default fallback, no validation
    bypass). Pre-fix: the stream-end count is 0 -> RED on the count assert
    (the discriminating observable)."""
    sb = _make_sandbox(tmp_path)
    proc = _spawn(sb, "DEMO_MODE=false\nconfigure_env", "y\nzz\n")
    out = _output(proc)
    assert proc.returncode != 0, "EOF after invalid key must fail (rc!=0)"
    assert out.count("Invalid private key format") >= 1, (
        f"validation error missing while validating 'zz':\n--- stdout ---\n"
        f"{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert out.count(MSG_STREAM_END) == 1, (
        f"stream-end diagnostic must appear EXACTLY once (only the final EOF), "
        f"got {out.count(MSG_STREAM_END)}:\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
    _assert_no_env(sb)


def test_guards_present_exact_once(tmp_path: Path) -> None:
    """Structural tripwire: exactly the TWO prescribed guards exist in
    install.sh (content-anchored, never line-numbered), and no OTHER read
    gained the stream-end guard (anti-over-fix, structural)."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert text.count(GUARD_KEY_READ) == 1, (
        f"key guard read-line must appear exactly once, got {text.count(GUARD_KEY_READ)}"
    )
    assert text.count(GUARD_KEY_MSG) == 1, (
        f"key guard message must appear exactly once, got {text.count(GUARD_KEY_MSG)}"
    )
    assert text.count(GUARD_ADDR_READ) == 1, (
        f"address guard read-line must appear exactly once, got {text.count(GUARD_ADDR_READ)}"
    )
    assert text.count(GUARD_ADDR_MSG) == 1, (
        f"address guard message must appear exactly once, got {text.count(GUARD_ADDR_MSG)}"
    )
    assert text.count(MSG_STREAM_END) == 2, (
        "exactly the two prescribed guard sites may mention the stream-end "
        "diagnostic (anti-over-fix)"
    )
