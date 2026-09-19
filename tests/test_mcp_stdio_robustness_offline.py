"""Contract: MCP stdio transport robustness (SDK 1.30.0 behavior pins).

Pins the OBSERVED, correct behaviors of the stdio transport under malformed
input, so a future mcp SDK upgrade (pyproject pins `mcp>=1.0,<2.0`) cannot
silently regress them. Every scenario runs the REAL server as a subprocess
with stdin HELD OPEN (probes proved requests pending at EOF are abandoned).

Windows-safe by construction (item 147/147b): no bash spawn, no `pty` or
`termios` import, no `select` on pipes (one pump thread per pipe feeds a
queue - Windows-portable, house pattern of the e2e transport suite), env
merged from os.environ (SystemRoot inherited, never re-looked-up), all
literals ASCII, subprocess resolved via `sys.executable` (portable),
generous timeouts (slow-import hosts 7-30s).

Derived from first-hand probes 2026-09-18 (curator increment 70):
  S1  garbage bytes           -> error notification + survive (S6 proves resume)
  S2  JSON without method     -> error notification
  S4  method: null            -> error notification
  S5  unknown JSON-RPC method -> JSON-RPC -32602 Invalid request parameters
  R2  id as STRING            -> response echoes the string id
  R4  batch array             -> error notification + survive
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
NOTIF_LOGGER = "mcp.server.exception_handler"
NOTIF_DATA = "Internal Server Error"

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

_CALL_OK = {
    "jsonrpc": "2.0",
    "id": "str-id-42",
    "method": "tools/call",
    "params": {"name": "get_realtime_status", "arguments": {}},
}


def _frame(msg: dict) -> bytes:
    return (json.dumps(msg) + "\n").encode()


class _Session:
    """Subprocess server with stdin held open; pump-thread line draining.

    One pump thread per pipe (no select on pipes: Windows-portable, house
    pattern of the e2e transport suite) feeds raw stdout lines into a
    queue; EOF is signaled as a None sentinel in the queue. Every wait
    returns AS SOON as `match` sees the expected line (probes showed
    full-timeout drains waste minutes on loaded hosts); bounded wait
    returns "".
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
        self._stdout_thread = threading.Thread(
            target=self._pump_stdout, daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._pump_stderr, daemon=True
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
        """Return the first line satisfying `match`; "" on EOF or timeout.

        Early-match draining: returns AS SOON as the expected line arrives
        (never drains the whole timeout). EOF arrives as a None sentinel in
        the queue (pending requests are abandoned, never answered).
        """
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

    def send(self, payload: bytes, match, timeout: float = 30.0) -> str:
        self.proc.stdin.write(payload)
        self.proc.stdin.flush()
        self.proc.stdin.write(_frame(_INITIALIZED))
        self.proc.stdin.flush()
        return self._drain(match, timeout)

    def close(self) -> None:
        try:
            self.proc.send_signal(signal.SIGTERM)
            self.proc.wait(timeout=45)
        except Exception:
            self.proc.kill()


@pytest.fixture
def session():
    s = _Session()
    try:
        handshake = s.boot()
        assert SERVER_NAME in handshake, f"handshake failed: {handshake[:200]!r}"
        yield s
    finally:
        s.close()


def _is_error_notification(line: str) -> bool:
    if '"notifications/message"' not in line:
        return False
    try:
        d = json.loads(line)
    except ValueError:
        return False
    p = d.get("params", {})
    return p.get("logger") == NOTIF_LOGGER and p.get("data") == NOTIF_DATA


def _response_for(line: str, rid):
    if '"id":' not in line.replace(" ", ""):
        return None
    try:
        d = json.loads(line)
    except ValueError:
        return None
    return d if d.get("id") == rid else None


def test_garbage_bytes_survive_and_resume(session):
    """S1+S6: garbage stdin -> error notification, then a VALID call answers."""
    out = session.send(b"this is not json\n", _is_error_notification)
    assert out, "no error notification for garbage (timeout or EOF)"
    # Resume: a well-formed call AFTER the garbage still answers.
    out2 = session.send(_frame(_CALL_OK), lambda t: _response_for(t, "str-id-42"))
    resp = _response_for(out2, "str-id-42")
    assert resp is not None, "server did not resume after garbage"
    text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
    assert "realtime" in text.lower() or "status" in text.lower()


def test_json_without_method_yields_error_notification(session):
    """S2: valid JSON-RPC frame without `method` -> error notification."""
    out = session.send(_frame({"jsonrpc": "2.0", "id": 7}), _is_error_notification)
    assert out, "no error notification for method-less frame (timeout or EOF)"


def test_null_method_yields_error_notification(session):
    """S4: `method: null` -> error notification (never a crash)."""
    out = session.send(_frame({"jsonrpc": "2.0", "method": None}), _is_error_notification)
    assert out, "no error notification for null method (timeout or EOF)"


def test_unknown_method_returns_invalid_request(session):
    """S5: unknown JSON-RPC method -> -32602 Invalid request parameters."""
    out = session.send(
        _frame({"jsonrpc": "2.0", "id": 9, "method": "bogus/xyz"}),
        lambda t: _response_for(t, 9),
    )
    resp = _response_for(out, 9)
    assert resp is not None, "no response for unknown method"
    assert resp["error"]["code"] == -32602
    assert resp["error"]["message"] == "Invalid request parameters"


def test_string_request_id_echoed(session):
    """R2: string request ids round-trip (spec-valid id form)."""
    out = session.send(_frame(_CALL_OK), lambda t: _response_for(t, "str-id-42"))
    resp = _response_for(out, "str-id-42")
    assert resp is not None, "no response for string-id call"
    assert resp["id"] == "str-id-42"


def test_batch_array_yields_error_notification_and_survives(session):
    """R4: JSON-RPC batch (array) -> error notification, server alive."""
    batch = (
        json.dumps([_INIT, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]) + "\n"
    ).encode()
    out = session.send(batch, _is_error_notification)
    assert out, "no error notification for batch array (timeout or EOF)"
    out2 = session.send(_frame(_CALL_OK), lambda t: _response_for(t, "str-id-42"))
    assert _response_for(out2, "str-id-42") is not None, "server did not survive batch"
