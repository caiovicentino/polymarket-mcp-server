"""Input-schema bounds suite for market_analysis tools (T-0290).

Pins the inputSchema bounds on the REAL registry (tests 1-4 derive the tools
from ``get_tools()`` -- never a literal snapshot of the schema, L-0002/L-0009).

Gaps fixed by this fatia (contract T-0290):

1. ``get_orderbook`` ``depth``: integer WITHOUT ``minimum`` -> depth=0 reached
   the handler and executed with an empty slice (observed 1st-hand in the
   pre-fix probe: a real GET to clob.polymarket.com/book with token_id="0"*40
   returned a 404 error envelope instead of -32602-style validation). Now
   ``minimum: 1``; the enforcement fires in the SDK's ``call_tool``
   (mcp/server/lowlevel/server.py: jsonschema.validate before the handler).
2. ``get_market_holders`` ``limit``: integer WITHOUT ``minimum`` -> same class.
   Now ``minimum: 1``; the default 10 is preserved (pinned).

Divergences declared (L-0025/L-0090 face (g) -- contract snapshot vs code):

- The contract's preflight snapshot claims ``compare_markets`` market_ids and
  ``get_market_volume`` timeframes lack ``items``; the tip (b240bb9) ALREADY
  satisfies both (``items: {"type": "string"}`` present since the initial
  commit ceea4e4 -- proven via ``git log -S``). The prescribed edits #3/#4 are
  therefore no-ops and tests 3/4 are GREEN GUARDS pinning the current state
  (they fail loudly if a future edit strips the items bounds).

Test 5 (subprocess stdio enforcement, mirrors the curator preflight): spawn
``sys.executable -m polymarket_mcp.server`` (env DEMO_MODE=true -- prescribed;
PYTHONPATH=<repo>/src, which SHADOWS the editable install of the clone root,
P-0019), cwd=tmp_path pristine (no .env -- P-0037), utf-8 pipes, timeout
<=30s with kill-on-hang. Flow: initialize -> notifications/initialized ->
tools/call get_orderbook. Pinned observables (proven in sandbox before the
suite was written):

- depth=0  -> ``result["isError"] is True`` AND text starts with
  ``Input validation error`` AND contains ``minimum`` (full text observed:
  ``Input validation error: 0 is less than the minimum of 1``).
- depth="abc" -> isError True AND ``not of type`` in text (pre-existing type
  validation; full text observed: ``Input validation error: 'abc' is not of
  type 'integer'``).

Hermeticity note (transparency, L-0138/L-0014): the SERVER STARTUP
(``initialize_server``) performs one read-only credential-creation attempt
(POST /auth/api-key -> observed 400 Bad Request) as pre-existing lifecycle
behavior of the server under test, OUTSIDE this fatia's enforcement path. The
tools/call path itself makes ZERO network by construction: the SDK validation
rejects the arguments BEFORE the handler runs (the validation-error text is
that proof -- the handler, which is what touches the network, never executes).
The fix-sim variant with fake API credentials was REJECTED: it moves the
startup artifact to the shutdown path (DELETE /cancel-all, 401) -- a
mutating-intent request; the prescribed DEMO_MODE env keeps the single
startup POST on the safe read-only failure path.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from polymarket_mcp.tools import market_analysis

REPO_ROOT = Path(__file__).resolve().parent.parent

_TIMEOUT = 30  # <=30s per contract; watchdog for the whole flow

# protocolVersion as declared by the SDK-era handshake the server negotiates.
_PROTOCOL_VERSION = "2025-06-18"

# 40-char synthetic token id (probed shape: clob token ids are 40 hex chars;
# the value is never used -- validation rejects before the handler).
_FAKE_TOKEN_ID = "0" * 40


def _tool_schema(name: str) -> dict:
    """Derive the inputSchema from the REAL registry (L-0002: no snapshots)."""
    for tool in market_analysis.get_tools():
        if tool.name == name:
            return tool.inputSchema
    pytest.fail(f"tool {name!r} not found in market_analysis.get_tools()")


def test_orderbook_depth_schema_minimum():
    """depth gains minimum=1; default 20 and type integer are preserved."""
    schema = _tool_schema("get_orderbook")
    depth = schema["properties"]["depth"]
    assert depth["minimum"] == 1
    assert depth["default"] == 20  # slice semantics untouched by this fatia
    assert depth["type"] == "integer"


def test_holders_limit_schema_minimum():
    """limit gains minimum=1; default 10 and type integer are preserved."""
    schema = _tool_schema("get_market_holders")
    limit = schema["properties"]["limit"]
    assert limit["minimum"] == 1
    assert limit["default"] == 10
    assert limit["type"] == "integer"


def test_compare_markets_market_ids_items_string():
    """market_ids items are pinned to strings (green guard: present since
    initial commit; strips the bound = RED)."""
    schema = _tool_schema("compare_markets")
    market_ids = schema["properties"]["market_ids"]
    assert market_ids["items"] == {"type": "string"}
    assert market_ids["type"] == "array"
    assert "market_ids" in schema["required"]  # pin preserved


def test_volume_timeframes_items_string():
    """timeframes items are pinned to strings (green guard: present since
    initial commit; strips the bound = RED)."""
    schema = _tool_schema("get_market_volume")
    timeframes = schema["properties"]["timeframes"]
    assert timeframes["items"] == {"type": "string"}
    assert timeframes["type"] == "array"


class _StdioSession:
    """Minimal newline-delimited JSON-RPC client for the server subprocess.

    Same recipe as the sandbox probes that validated the enforcement
    (sequential ids, line reads with flush, graceful close: stdin close +
    wait/kill). No infra is shared with the stdio E2E suite (sister T-0288,
    separate queue): each suite is autonomous by design.
    """

    def __init__(self, proc):
        self._proc = proc
        self._next_id = 0

    def request(self, method, params=None):
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()
        return self._next_id

    def notify(self, method):
        payload = {"jsonrpc": "2.0", "method": method}
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def response(self, request_id):
        """Read lines until the response with the expected id arrives.

        Notifications produce no response lines, so they are skipped here.
        A clean EOF with no matching response raises with the stderr tail
        (diagnostic, never used in assertions).
        """
        while True:
            line = self._proc.stdout.readline()
            if not line:
                stderr_tail = ""
                if self._proc.stderr is not None:
                    stderr_tail = self._proc.stderr.read()[-800:]
                raise RuntimeError(
                    f"EOF while waiting for response id={request_id}; "
                    f"stderr tail: {stderr_tail!r}"
                )
            message = json.loads(line)
            if message.get("id") == request_id:
                return message


def _start_server(tmp_path):
    """Spawn the server subprocess (pristine cwd, prescribed env)."""
    env = {
        "DEMO_MODE": "true",
        "PYTHONPATH": str(REPO_ROOT / "src"),
        "PATH": os.environ.get("PATH", os.defpath),
    }
    return subprocess.Popen(
        [sys.executable, "-m", "polymarket_mcp.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=str(tmp_path),
        env=env,
        bufsize=1,
    )


@pytest.fixture()
def stdio_server(tmp_path):
    """Start the server, yield a session, guarantee teardown (L-0053c)."""
    proc = _start_server(tmp_path)
    session = _StdioSession(proc)
    try:
        yield session
    finally:
        _teardown(proc)


def _teardown(proc):
    """Graceful close: stdin close + wait with timeout, kill on hang."""
    try:
        if proc.stdin is not None and not proc.stdin.closed:
            proc.stdin.close()
        try:
            proc.wait(timeout=_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    finally:
        for stream in (proc.stdout, proc.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def _handshake(session):
    request_id = session.request(
        "initialize",
        {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "t-0290-offline-suite", "version": "0.0.1"},
        },
    )
    init = session.response(request_id)
    assert init["result"]["serverInfo"]["name"] == "polymarket-trading"
    session.notify("notifications/initialized")


def test_stdio_enforcement_depth_zero_invalid_params(stdio_server):
    """depth=0 is rejected by the SDK's inputSchema validation (tool RESULT
    with isError), BEFORE the handler runs -- zero network on the tools/call
    path by construction. Complement: depth="abc" hits the pre-existing type
    validation."""
    _handshake(stdio_server)

    # depth=0: the NEW bound (minimum=1) fires.
    request_id = stdio_server.request(
        "tools/call",
        {
            "name": "get_orderbook",
            "arguments": {"token_id": _FAKE_TOKEN_ID, "depth": 0},
        },
    )
    reply = stdio_server.response(request_id)
    result = reply["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert text.startswith("Input validation error")
    assert "minimum" in text

    # depth="abc": the PRE-EXISTING type validation fires (pin duplo).
    request_id = stdio_server.request(
        "tools/call",
        {
            "name": "get_orderbook",
            "arguments": {"token_id": _FAKE_TOKEN_ID, "depth": "abc"},
        },
    )
    reply = stdio_server.response(request_id)
    result = reply["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert text.startswith("Input validation error")
    assert "not of type" in text
