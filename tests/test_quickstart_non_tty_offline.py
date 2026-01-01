"""Offline hermetic suite for quickstart.sh non-TTY hardening (T-0224).

Contract: quickstart.sh is the documented one-liner (`curl -sSL ... | bash`,
quickstart.sh:9) but its two interactive `read` sites consumed STDIN, which
under curl|bash IS the script stream itself (the reads swallowed script
bytes) and under `bash quickstart.sh < /dev/null` (CI) died on EOF under
`set -e`. The fix (same slice) routes every prompt through /dev/tty with
safe non-TTY fallbacks: proceed on the install confirmation, NEVER run the
destructive `rm -rf` on "remove and reinstall?" (safe default "n").

Pre-fix RED forensics (proven 1st hand on this host, /bin/bash 3.2.57,
main 89edfa9, script extracted via `git show main:quickstart.sh` into a
tempdir — P-0020/P-0016 copy-path; reproduction harness kept out of the
suite, the suite pins the POST-fix contract):
- `bash quickstart.sh < /dev/null` -> rc=1, no install call (death at the
  bare `read`, quickstart.sh:51 in the 97-line layout).
- curl|bash exact (pty ctty + stdin dup2'd to the script stream, fresh
  machine: no pyproject.toml in cwd + existing install dir) -> rc=127
  "/bin/bash: line 76: cho: command not found": the bare `read` swallowed
  the whole next stream line and the reinstall `read -n 1` stole the first
  byte of the line after bash's parse boundary, corrupting the script;
  install never ran.
- `bash quickstart.sh < quickstart.sh` -> rc=0 BY LUCK: stdin is a separate
  fd at offset 0, so the reads consumed the shebang (harmless). Declared
  divergence from today's behavior (L-0025); test 7 pins the post-fix
  contract with a STRONGER oracle than rc: zero stdin consumption measured
  by the pipe's remaining bytes (pre-fix the shebang was consumed, so this
  oracle is RED pre-fix too).

Declared divergences (L-0020/L-0025, proven observable > spec text):
1. The contract sketched test 3's sandbox with pyproject.toml present;
   empirically the pre-fix death does NOT manifest in that flavor (the
   script survived by luck: the stolen byte was a harmless "\\n"). Test 3
   therefore uses the fresh-machine reinstall flavor (no pyproject.toml in
   cwd + existing install dir), where the death manifests deterministically.
2. Canary design (L-0065 anti-vacuo; mutation in the direction of the bug,
   L-0030): the stream under test replaces the two BLANK lines that mask
   the theft with `echo CANARY_*` lines. Pre-fix: canary 1 (right after the
   confirm read) is consumed by the bare `read` and canary 2 (right after
   the outer `if`'s `fi`, bash 3.2's parse boundary for the -n 1 read) is
   the stolen byte that kills the script. Post-fix: no stdin reads exist,
   both canaries print. Anchors are context strings, not line numbers;
   if the script's layout drifts the construction fails loudly (assert),
   never silently.

Sandbox: tmpdir OUTSIDE the repo (pytest tmp_path; guarded by the autouse
tripwire below). Stub install.sh records `install $* cwd=$PWD` to $QS_LOG
and writes a marker; stub bin/git records `git $*` and, on `clone`, creates
the target dir + copies the install stub — any other subcommand records and
fails loudly (P-0031). Sandbox env is minimal (PATH/HOME/QS_* only,
L-0130-style clean env); HOME is sandboxed so the script's
`rm -rf "$HOME/polymarket-mcp-server"` can only ever land inside the
sandbox by construction. The script under test is invoked by ABSOLUTE path
with cwd = sandbox root. NO real git clone, NO real install.sh, NO real
.env, NO network (house rules; offline suite, P-0029/P-0031).

Mechanics (L-0014/L-0163): pty children via pty.fork() + execve; parents
drain the master with select + deadline (never sleep-as-oracle), reap with
waitpid (WNOHANG polling inside the drain, final blocking reap), close the
master in a finally, and kill+reap on deadline so a hung child fails loud
with its partial output. Subprocess children run with preexec_fn=os.setsid:
a fresh session has NO controlling terminal, so /dev/tty fails with ENXIO
deterministically regardless of whether pytest itself has a ctty — the
fallback branch of the fix is exercised by construction, not by host luck.
"""
import os
import pty
import select
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
QUICKSTART = REPO_ROOT / "quickstart.sh"
BASH = "/bin/bash"  # the shell curl|bash users on macOS get (3.2.57 here)

C1 = "CANARY_AFTER_CONFIRM_T-0224"  # stream line: f"echo {C1}"; output line: C1
C2 = "CANARY_AFTER_REINSTALL_T-0224"

BANNER_PROCEED = "non-interactive: proceeding with installation"
BANNER_KEEP = "non-interactive: keeping existing installation directory"

COMPLETE = "Quick Start Complete"
INSTALL_DIR_NAME = "polymarket-mcp-server"

INSTALL_STUB = """#!/bin/bash
printf '%s\\n' "install $* cwd=$PWD" >> "$QS_LOG"
printf 'install-ok\\n' > "$QS_MARKER"
exit 0
"""

GIT_STUB = """#!/bin/bash
printf '%s\\n' "git $*" >> "$QS_LOG"
if [ "$1" = "clone" ]; then
    mkdir -p "$3"
    cp "$QS_INSTALL_STUB" "$3/install.sh"
    chmod +x "$3/install.sh"
    exit 0
fi
echo "git stub: unexpected subcommand: $*" >&2
exit 1
"""


def _build_sandbox(base: Path, with_pyproject: bool, with_install_dir: bool) -> dict:
    sb = base / "sb"
    bindir = sb / "bin"
    home = sb / "home"
    bindir.mkdir(parents=True)
    home.mkdir(parents=True)
    stub = sb / "install.sh"
    stub.write_text(INSTALL_STUB)
    stub.chmod(0o755)
    gitstub = bindir / "git"
    gitstub.write_text(GIT_STUB)
    gitstub.chmod(0o755)
    if with_pyproject:
        (sb / "pyproject.toml").write_text("[project]\nname = 'sandbox'\n")
    install_dir = home / INSTALL_DIR_NAME
    if with_install_dir:
        install_dir.mkdir()
        (install_dir / "sentinel.txt").write_text("prior install\n")
        stub2 = install_dir / "install.sh"
        stub2.write_text(INSTALL_STUB)
        stub2.chmod(0o755)
    return {
        "root": sb,
        "bin": bindir,
        "home": home,
        "log": sb / "calls.log",
        "marker": sb / "marker.txt",
        "install_dir": install_dir,
    }


def _sandbox_env(sb: dict) -> dict:
    return {
        "PATH": f"{sb['bin']}:/usr/bin:/bin",
        "HOME": str(sb["home"]),
        "QS_LOG": str(sb["log"]),
        "QS_MARKER": str(sb["marker"]),
        "QS_INSTALL_STUB": str(sb["root"] / "install.sh"),
    }


def _build_canary_stream() -> bytes:
    """The real script's bytes with the two theft-masking blank lines replaced
    by echo canaries (see module docstring, divergence 2)."""
    text = QUICKSTART.read_text()
    mod = text.replace(
        "tty_read_line\n\n# Check if we're in the repo directory",
        f"tty_read_line\necho {C1}\n# Check if we're in the repo directory",
        1,
    )
    if mod == text:
        pytest.fail("canary-1 anchor drifted from quickstart.sh (test layout, not a fix bug)")
    mod2 = mod.replace(
        '    echo "Using current directory..."\nfi\n\n'
        "# Make install script executable if needed",
        f'    echo "Using current directory..."\nfi\necho {C2}\n'
        "# Make install script executable if needed",
        1,
    )
    if mod2 == mod:
        pytest.fail("canary-2 anchor drifted from quickstart.sh (test layout, not a fix bug)")
    return mod2.encode()


def _drain_pty(master: int, pid: int, deadline: float = 8.0):
    """Drain the pty until the child exits (EIO/EOF) or the deadline. Returns
    (output, status-or-None). select-based; no sleep-as-oracle (L-0014)."""
    chunks = []
    status = None
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                data = os.read(master, 65536)
            except OSError:
                break  # EIO on macOS/BSD once the slave side is gone
            if not data:
                break
            chunks.append(data)
            continue
        try:
            wpid, st = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            break
        if wpid == pid:
            status = st
            while True:  # drain whatever is still buffered before EIO
                ready, _, _ = select.select([master], [], [], 0.2)
                if not ready:
                    break
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
            break
    return b"".join(chunks).decode(errors="replace"), status


def _run_pty(sb: dict, mode: str, responses: bytes, deadline: float = 8.0):
    """Run /bin/bash under a forkpty. mode='script': bash <quickstart> with
    stdin=pty (local interactive run). mode='stream': curl|bash exact — bash
    reads the script from fd0 (stdin dup2'd to the stream file), /dev/tty is
    the pty. responses are written to the master BEFORE the reads block
    (pty input queue holds them — SETUP, not arbitration, L-0014)."""
    env = _sandbox_env(sb)
    stream_fd = None
    if mode == "stream":
        stream = sb["root"] / "stream.sh"
        stream.write_bytes(_build_canary_stream())
        stream_fd = os.open(stream, os.O_RDONLY)

    pid, master = pty.fork()
    if pid == 0:  # child: never return into pytest; exec or _exit
        try:
            if stream_fd is not None:
                os.dup2(stream_fd, 0)
                os.close(stream_fd)
                os.chdir(sb["root"])
                os.execve(BASH, [BASH], env)
            else:
                os.chdir(sb["root"])
                os.execve(BASH, [BASH, str(QUICKSTART)], env)
        except BaseException:
            os._exit(127)
        os._exit(127)

    output, status = "", None
    try:
        if responses:
            os.write(master, responses)
        output, status = _drain_pty(master, pid, deadline)
        if status is None:
            # deadline hit: kill so a hung child fails loud, then reap
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            _, status = os.waitpid(pid, 0)
    finally:
        os.close(master)
        if stream_fd is not None:
            os.close(stream_fd)
    return os.waitstatus_to_exitcode(status), output


def _run_subprocess(sb: dict, stdin_file: Path | None = None, stdin_pipe: bool = False):
    """Run /bin/bash <quickstart> with cwd=sandbox, sandboxed env, NO ctty
    (preexec_fn=os.setsid) and captured output. stdin: /dev/null by default,
    a file stream, or a pre-filled pipe (whose remaining bytes are returned
    as the zero-stdin-consumption oracle)."""
    env = _sandbox_env(sb)
    extra_fd = None
    if stdin_pipe:
        r, w = os.pipe()
        os.write(w, QUICKSTART.read_bytes())
        os.close(w)  # EOF right after the script bytes
        extra_fd = r
    stdin_obj = None if stdin_pipe else open(os.devnull if stdin_file is None else stdin_file, "rb")
    try:
        p = subprocess.Popen(
            [BASH, str(QUICKSTART)],
            cwd=str(sb["root"]),
            stdin=extra_fd if stdin_pipe else stdin_obj,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            preexec_fn=os.setsid,
        )
        out, _ = p.communicate(timeout=30)
        rc = p.returncode
    finally:
        if stdin_obj is not None:
            stdin_obj.close()
    remaining = None
    if stdin_pipe:
        assert extra_fd is not None, (
            "FAIL-LOUD: pipe fd ausente (impossível se stdin_pipe=True — narrowing mypy)"
        )
        remaining = b""
        while True:  # read the pipe dry: what the script did NOT consume
            chunk = os.read(extra_fd, 65536)
            if not chunk:
                break
            remaining += chunk
        os.close(extra_fd)
    return rc, out.decode(errors="replace"), remaining


def _assert_install_ran_once(sb: dict, cwd: Path):
    assert sb["log"].exists(), "install stub never recorded a call"
    assert sb["log"].read_text().splitlines() == [f"install --demo cwd={cwd}"]
    assert sb["marker"].read_text() == "install-ok\n"


@pytest.fixture(autouse=True)
def _guard_repo_tree(tmp_path: Path):
    """Tripwire (P-0013/L-0013): nothing from the sandbox may leak into the
    repo working tree. Checks the worktree's git status for the sandbox
    prefix after every test, and fails loudly if tmp_path ever lives inside
    the repo (hermeticity broken by configuration)."""
    if REPO_ROOT == tmp_path or str(tmp_path).startswith(str(REPO_ROOT)):
        pytest.fail("tmp_path inside the repo tree: hermeticity broken")
    before = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    yield
    after = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    leaked = [line for line in after.splitlines() if str(tmp_path) in line and line not in before.splitlines()]
    assert not leaked, f"sandbox residue leaked into the repo tree: {leaked}"


def test_bash_syntax():
    rc = subprocess.run([BASH, "-n", str(QUICKSTART)], capture_output=True, text=True)
    assert rc.returncode == 0, rc.stderr


def test_devnull_completes_install(tmp_path: Path):
    """stdin=/dev/null (CI) must complete the install: pre-fix RED was rc=1
    with no install call (death at the bare `read` under set -e)."""
    sb = _build_sandbox(tmp_path, with_pyproject=True, with_install_dir=False)
    rc, out, remaining = _run_subprocess(sb)
    assert rc == 0, out
    _assert_install_ran_once(sb, sb["root"])
    assert COMPLETE in out
    assert BANNER_PROCEED in out  # fallback branch exercised (setsid => no ctty)
    assert remaining is None  # stdin was /dev/null, no remaining-bytes oracle


def test_curl_bash_stdin_stream_respondible(tmp_path: Path):
    """curl|bash exact: stdin = the script stream, /dev/tty = the pty ctty.
    Post-fix the prompts are answered via /dev/tty (responses consumed, no
    fallback banner), the script completes, install runs once from the
    PRESERVED dir. Pre-fix RED: rc=127 "cho: command not found" — the
    reinstall read stole a script byte; canaries never printed."""
    sb = _build_sandbox(tmp_path, with_pyproject=False, with_install_dir=True)
    sentinel = sb["install_dir"] / "sentinel.txt"
    rc, out = _run_pty(sb, "stream", responses=b"\nn\n")
    assert rc == 0, out
    assert C1 in out, f"canary-1 missing: the confirm read consumed script bytes: {out[-800:]}"
    assert C2 in out, f"canary-2 missing: the reinstall read consumed script bytes: {out[-800:]}"
    assert sentinel.exists(), "reinstall 'n' must preserve the dir (rm -rf never ran)"
    _assert_install_ran_once(sb, sb["install_dir"])
    assert COMPLETE in out
    assert "non-interactive" not in out, "responses must come from /dev/tty, not the fallback"


def test_reinstall_no_tty_preserves_dir(tmp_path: Path):
    """No TTY at all: the reinstall prompt must default to "n" — dir preserved,
    install runs from the existing dir. Pre-fix RED: rc=1 (death at the FIRST
    read, before the reinstall block even ran)."""
    sb = _build_sandbox(tmp_path, with_pyproject=False, with_install_dir=True)
    sentinel = sb["install_dir"] / "sentinel.txt"
    rc, out, remaining = _run_subprocess(sb)
    assert rc == 0, out
    assert sentinel.exists(), "rm -rf must NEVER run non-interactively"
    assert BANNER_PROCEED in out  # site-1 fallback (no ctty)
    assert BANNER_KEEP in out  # site-2 fallback: safe default "n"
    assert COMPLETE in out
    _assert_install_ran_once(sb, sb["install_dir"])
    assert remaining is None


def test_reinstall_yes_interactive_removes_dir(tmp_path: Path):
    """Interactive 'y' (real TTY) removes the dir, clones fresh and installs —
    byte-compatibility guard of the interactive flow (green pre-fix too:
    stdin=pty was readable; the fix moved the reads to /dev/tty=pty)."""
    sb = _build_sandbox(tmp_path, with_pyproject=False, with_install_dir=True)
    sentinel = sb["install_dir"] / "sentinel.txt"
    rc, out = _run_pty(sb, "script", responses=b"\ny\n")
    assert rc == 0, out
    assert not sentinel.exists(), "interactive 'y' must remove the existing dir"
    assert "non-interactive" not in out
    lines = sb["log"].read_text().splitlines()
    assert len(lines) == 2, lines
    assert lines[0].startswith("git clone "), lines
    assert lines[0].endswith(str(sb["install_dir"])), lines
    assert lines[1] == f"install --demo cwd={sb['install_dir']}", lines
    assert sb["marker"].read_text() == "install-ok\n"
    assert COMPLETE in out


def test_reinstall_no_interactive_preserves_dir(tmp_path: Path):
    """Interactive 'n' (real TTY) preserves the dir and installs in place —
    guard of the interactive flow (green pre-fix too)."""
    sb = _build_sandbox(tmp_path, with_pyproject=False, with_install_dir=True)
    sentinel = sb["install_dir"] / "sentinel.txt"
    rc, out = _run_pty(sb, "script", responses=b"\nn\n")
    assert rc == 0, out
    assert sentinel.exists(), "interactive 'n' must preserve the existing dir"
    assert "non-interactive" not in out
    _assert_install_ran_once(sb, sb["install_dir"])
    assert "git clone" not in sb["log"].read_text()
    assert COMPLETE in out


def test_piped_stream_does_not_die(tmp_path: Path):
    """`bash quickstart.sh < quickstart.sh` (stdin = the script's own bytes,
    script parsed from the file argument): pre-fix rc=0 BY LUCK (the reads
    consumed the shebang from the separate stdin fd). Post-fix the contract
    is stronger and deterministic: rc=0, install once, and ZERO stdin
    consumption — the pipe's remaining bytes are the complete script
    (pre-fix the shebang line was consumed, so this oracle is RED pre-fix)."""
    sb = _build_sandbox(tmp_path, with_pyproject=True, with_install_dir=False)
    rc, out, remaining = _run_subprocess(sb, stdin_pipe=True)
    assert rc == 0, out
    assert BANNER_PROCEED in out
    assert COMPLETE in out
    _assert_install_ran_once(sb, sb["root"])
    assert remaining == QUICKSTART.read_bytes(), (
        "the script must consume ZERO bytes from stdin (the stream is the "
        f"documented curl|bash channel); consumed={(len(QUICKSTART.read_bytes()) - len(remaining))} bytes"
    )
