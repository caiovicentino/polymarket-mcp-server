"""Contract: graceful shutdown via SIGTERM/SIGINT on the stdio MCP server.

Pins the OBSERVED exit behavior of the real server subprocess when it
receives SIGTERM/SIGINT while the asyncio loop is idle: the process must
exit with code 0 within 15 seconds and the three shutdown log markers
must appear in ORDER on stderr (received < initiated < complete).

Background (T-0398, proven 1st-hand by the curator 2026-09-19): the
registration via ``signal.signal`` alone does NOT wake an idle macOS
kqueue loop - the handler's ``Event.set()`` appends the callback to
``_ready`` without writing the wakeup-fd, and the EINTR-restarted kevent
sleeps with the original timeout, so ``_ready`` is only processed on the
NEXT I/O; the process hangs until SIGKILL and the graceful shutdown
(cancel orders skip, WSS stop) NEVER runs. The fix registers the signals
ADDITIVELY via ``loop.add_signal_handler`` (C-level wakeup write into the
wakeup socket immediately before any Python handler runs) while KEEPING
the ``signal.signal`` registration (the lifecycle pin at
tests/test_server_lifecycle_offline.py:965-966 requires
bag.signal_calls with (SIGTERM|SIGINT, _signal_handler)).

RED pre-fix: every signal test hangs to the 15s cap and fails with the
explicit "graceful shutdown never ran" message. Post-fix: exit in ~1s
with the full ordered log sequence.

Windows-safe by construction (item 147/147b, L-0316): no bash spawn, no
``pty``/``termios`` import, no ``select`` on pipes (one pump thread per
pipe feeds a queue - house pattern of the robustness/e2e transport
suites), env merged from os.environ, all literals ASCII, subprocess
resolved via ``sys.executable``. The graceful-signal path itself is
POSIX-only: on Windows ``send_signal(SIGTERM)`` is TerminateProcess, so
each signal test skips there with the reason inline (L-0026/L-0316).

Hermeticity note: the spawned server reaches the REAL network in one
place without API credentials (the WebSocketManager background task dials
the two hardcoded wss:// endpoints); DEMO_MODE=true and the five
Polymarket credential keys scrubbed from the subprocess env keep auth
inert while the WSS connects live (~1-2s; slow-import hosts up to 7-30s
per the robustness sibling - hence the 120s drain budget in boot).

Derived from first-hand probes 2026-09-19 (curator, T-0398 contract):
  - repro minimal: signal.signal handler + Event.set() -> HANDLER-RAN
    printed, process never wakes (HUNG >5s, kill needed) on macOS kqueue;
  - fix confirmed: loop.add_signal_handler -> EXITED in 0.0s (wake-up ok);
  - real server: SIGTERM logs "Received SIGTERM, initiating shutdown..."
    but NO shutdown logs follow and the process does not exit (3 reps).
"""
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time

import pytest

SERVER_NAME = "polymarket-trading"

_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0.0"},
    },
}
_INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}

# The three shutdown markers (substring pins - the exact text is runtime
# log output, same convention as the e2e sibling's shutdown assertion).
MARKER_RECEIVED = "Received"
MARKER_INITIATED = "Graceful shutdown initiated"
MARKER_COMPLETE = "Graceful shutdown complete"


def _frame(msg: dict) -> bytes:
    return (json.dumps(msg) + "\n").encode()


class _Session:
    """Subprocess server with stdin held open; pump-thread line draining.

    One pump thread per pipe (no select on pipes: Windows-portable, house
    pattern of the e2e/robustness transport suites) feeds raw stdout lines
    into a queue; EOF is signaled as a None sentinel in the queue. stderr
    is drained into a list for the shutdown-marker assertions.
    """

    def __init__(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = "src"
        env["DEMO_MODE"] = "true"
        for k in (
            "POLYMARKET_API_KEY",
            "POLYMARKET_API_SECRET",
            "POLYMARKET_API_PASSPHRASE",
            "POLYMARKET_API_KEY_NAME",
            "POLYGON_PRIVATE_KEY",
        ):
            env.pop(k, None)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "polymarket_mcp.server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self._lines: queue.Queue = queue.Queue()
        self._stderr_lines: list[str] = []
        self._stderr_thread = threading.Thread(
            target=self._pump_stderr, daemon=True
        )
        self._stdout_thread = threading.Thread(
            target=self._pump_stdout, daemon=True
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _pump_stdout(self) -> None:
        for raw in self.proc.stdout:
            self._lines.put(raw.decode("utf-8", errors="replace").strip())
        self._lines.put(None)  # EOF sentinel

    def _pump_stderr(self) -> None:
        for raw in self.proc.stderr:
            self._stderr_lines.append(raw.decode("utf-8", errors="replace"))

    def _drain(self, match, timeout: float) -> str:
        """Return the first line satisfying `match`; "" on EOF or timeout."""
        end = time.monotonic() + timeout
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return ""
            try:
                item = self._lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if item is None:
                return ""  # EOF
            if match(item):
                return item

    def boot(self) -> str:
        self.proc.stdin.write(_frame(_INIT))
        self.proc.stdin.flush()
        return self._drain(lambda t: SERVER_NAME in t, 120.0)

    def send_initialized(self) -> None:
        self.proc.stdin.write(_frame(_INITIALIZED))
        self.proc.stdin.flush()

    def stderr_text(self) -> str:
        if self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=2.0)
        return "\n".join(self._stderr_lines)

    def kill(self) -> None:
        """Kill-on-hang teardown: never wedges the suite on a stuck server."""
        try:
            self.proc.kill()
        except ProcessLookupError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


@pytest.fixture
def session():
    s = _Session()
    try:
        handshake = s.boot()
        assert SERVER_NAME in handshake, f"handshake failed: {handshake[:200]!r}"
        yield s
    finally:
        s.kill()


def _signal_exit_and_logs(s: _Session, sig: int) -> int:
    """Deliver `sig`, wait <=15s for exit, return the exit code.

    Fail-loudly with the explicit hang message when the server does not
    exit in time (the dead-hang regression this suite pins: graceful
    shutdown never ran). The process is killed first so a RED never
    wedges the suite.
    """
    s.send_initialized()
    s.proc.send_signal(sig)
    try:
        returncode = s.proc.wait(timeout=15.0)
    except subprocess.TimeoutExpired:
        s.kill()
        pytest.fail(
            f"server did not exit within 15s after {signal.Signals(sig).name} "
            "(graceful shutdown never ran)"
        )
    return returncode


def _assert_shutdown_log_sequence(stderr: str, sig_name: str) -> None:
    """The three markers are present AND ordered (received < initiated <
    complete by first-occurrence index on stderr)."""
    idx_received = stderr.find(MARKER_RECEIVED + " " + sig_name)
    idx_initiated = stderr.find(MARKER_INITIATED)
    idx_complete = stderr.find(MARKER_COMPLETE)
    assert idx_received != -1, (
        f"missing {MARKER_RECEIVED + ' ' + sig_name!r} marker on stderr"
    )
    assert idx_initiated != -1, "missing 'Graceful shutdown initiated' marker"
    assert idx_complete != -1, "missing 'Graceful shutdown complete' marker"
    assert idx_received < idx_initiated, (
        "log order violated: received must precede 'Graceful shutdown "
        f"initiated' (got {idx_received} >= {idx_initiated})"
    )
    assert idx_initiated < idx_complete, (
        "log order violated: 'Graceful shutdown initiated' must precede "
        f"'Graceful shutdown complete' (got {idx_initiated} >= {idx_complete})"
    )


def test_sigterm_exits_gracefully_within_timeout(session):
    """SIGTERM during an idle loop -> exit 0 within 15s with the full
    shutdown log sequence (RED pre-fix: hangs to the 15s cap)."""
    if sys.platform == "win32":
        pytest.skip(
            "SIGTERM is not deliverable on Windows (TerminateProcess; "
            "graceful-signal path is POSIX-only)",
            allow_module_level=False,
        )
    returncode = _signal_exit_and_logs(session, signal.SIGTERM)
    assert returncode == 0, f"expected exit 0 after SIGTERM, got {returncode}"
    _assert_shutdown_log_sequence(session.stderr_text(), "SIGTERM")


def test_sigint_exits_gracefully_within_timeout(session):
    """SIGINT during an idle loop -> exit 0 within 15s (same body as the
    SIGTERM test with signal.SIGINT)."""
    if sys.platform == "win32":
        pytest.skip(
            "SIGINT is not deliverable on Windows (TerminateProcess; "
            "graceful-signal path is POSIX-only)",
            allow_module_level=False,
        )
    returncode = _signal_exit_and_logs(session, signal.SIGINT)
    assert returncode == 0, f"expected exit 0 after SIGINT, got {returncode}"
    _assert_shutdown_log_sequence(session.stderr_text(), "SIGINT")


def test_shutdown_logs_ordered(session):
    """The three shutdown markers appear IN ORDER on stderr (received <
    initiated < complete by first-occurrence index)."""
    if sys.platform == "win32":
        pytest.skip(
            "SIGTERM is not deliverable on Windows (TerminateProcess; "
            "graceful-signal path is POSIX-only)",
            allow_module_level=False,
        )
    returncode = _signal_exit_and_logs(session, signal.SIGTERM)
    assert returncode == 0, f"expected exit 0 after SIGTERM, got {returncode}"
    _assert_shutdown_log_sequence(session.stderr_text(), "SIGTERM")
