"""Offline E2E stdio suite for polymarket_mcp.server (T-0288).

Spawns the REAL server process (``sys.executable -m polymarket_mcp.server``)
and drives it over the wire with newline-delimited JSON-RPC, covering the
handshake, tools/list credential gating, resources/list, resources/read and
the JSON-RPC error envelope - the full stdio surface, offline.

The bug this suite closes (proven 1st-hand on main b240bb9 over the real wire):
resources/read for ALL three announced URIs answered
``{"error": "Unknown resource: <uri>"}`` because the SDK passes
``req.params.uri`` as a pydantic v2 ``AnyUrl`` (NOT a str subclass) and the
pre-fix handler compared the raw AnyUrl against str literals. The fix
normalizes once (``uri_text = str(uri)``); the unknown branch is pinned too
(it was always correct and must not regress).

Sources of truth for every assert are OBSERVABLES probed 1st-hand against the
real subprocess (L-0020/L-0025), with two declared divergences from the
contract's prose (contract claims that did not reproduce are recorded, never
silently dropped):

1. Contract test 6 expected config (cwd pristine, no .env) to answer
   ``{"error": "Configuration not loaded"}``. OBSERVED: with DEMO_MODE=true
   and no .env, initialize_server loads a real demo config, so the config
   resource serves DATA (safety_limits/trading_controls/endpoints derived
   from a reference PolymarketConfig built in the test process). The
   "Configuration not loaded" observable belongs to the pre-init dispatch
   suite (tests/test_server_dispatch_offline.py, already pinned there) -
   here we pin the observed E2E behavior.
2. Contract test 7 expected ``tools/call name=unknown_tool_xyz`` to answer
   JSON-RPC error -32602. OBSERVED: with VALID params (``arguments: {}``) the
   request passes pydantic validation, reaches the call_tool handler (the SDK
   warns "Tool 'unknown_tool_xyz' not listed, no validation will be
   performed") and the error envelope comes back as a RESULT with
   ``isError: false``. The -32602 "Invalid request parameters" error is
   produced by the SDK request validation (mcp/shared/session.py:364-391)
   when params are malformed - e.g. ``arguments: "not-a-dict"``. This suite
   pins the -32602 observable with malformed arguments (matching the
   contract's observable) and, as the paired contrast case (L-0056), the
   valid-params observable (envelope as result).

Hermeticity: the spawned server would reach the real network in two places
when running without API credentials (initialize_server attempts
``create_api_credentials`` via httpx; the WebSocketManager background task
dials the two hardcoded wss:// endpoints). Both channels are made
deterministically inoperative by an inoperative local proxy env
(``HTTP_PROXY``/``HTTPS_PROXY``/``ALL_PROXY`` = ``http://127.0.0.1:1``):
httpx (trust_env) and the websockets library both fail fast against the
local port with zero external network traffic (probed 1st-hand: httpx
``PolyApiException[status_code=None]`` captured by the initialize_server
except, WSS ``[Errno 61] Connect call failed ('127.0.0.1', 1)`` in the
background task). The credential-gated test never attempts credential
creation (has_api_credentials is True, so initialize_server skips the
creation attempt entirely). The subprocess env is built by sanitizing every
PolymarketConfig-mapped key from the host env (P-0035 both directions) with
``DEMO_MODE=true`` and a PYTHONPATH derived from this file's location
(never a hardcoded author path). ``cwd`` is a pristine ``tmp_path`` so the
host's .env never leaks (P-0037).

Reader mechanics: one pump thread per pipe (portable - no select on pipes,
Windows-safe), newline-delimited JSON-RPC with explicit flush, per-request
timeout <= 30s with kill-on-hang in the fixture teardown, explicit
``encoding="utf-8"`` on Popen (P-0099, Windows CI cp1252 locale). Tool names
and rate-limit buckets are DERIVED from the real registries
(market_discovery/market_analysis/realtime/trading/portfolio ``get_tools``
accessors and RATE_LIMITS) - never literal counts (L-0002); the server
version is asserted by reflection against ``polymarket_mcp.__version__``
(never a literal).
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import polymarket_mcp
import polymarket_mcp.tools.market_analysis as market_analysis
import polymarket_mcp.tools.market_discovery as market_discovery
import polymarket_mcp.tools.portfolio_integration as portfolio_integration
import polymarket_mcp.tools.realtime as realtime
import polymarket_mcp.tools.trading as trading
from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.utils import create_safety_limits_from_config
from polymarket_mcp.utils.rate_limiter import RATE_LIMITS

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

# Every env key the spawned config would read, removed from the host env
# before the subprocess starts (P-0035 both directions): prefixed credentials
# plus the unprefixed gap fields of the house pattern, plus proxy vars so the
# inoperative proxy defense below cannot be silently neutralized.
_ENV_PREFIXES = ("POLYGON_", "POLYMARKET_")
_ENV_KEYS = (
    "DEMO_MODE",
    "LOG_LEVEL",
    "CLOB_API_URL",
    "GAMMA_API_URL",
    "USDC_ADDRESS",
    "CTF_EXCHANGE_ADDRESS",
    "CONDITIONAL_TOKEN_ADDRESS",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)
_ENV_LOOSE_PREFIXES = ("MAX_", "MIN_", "ENABLE_", "REQUIRE_", "AUTO_")

# Inoperative local proxy: every outbound channel of the spawned server
# (httpx via trust_env, websockets) fails fast against this dead local port
# with zero external network traffic. See module docstring.
_INOPERATIVE_PROXY = "http://127.0.0.1:1"

DEMO_CREDENTIALS_ENV = {
    "POLYMARKET_API_KEY": "dummy",
    "POLYMARKET_API_SECRET": "dummy",
    "POLYMARKET_PASSPHRASE": "dummy",
    "POLYMARKET_API_KEY_NAME": "dummy",
}

_STATUS_URI = "polymarket://status"
_CONFIG_URI = "polymarket://config"
_RATE_LIMITS_URI = "polymarket://rate-limits"

# Observed names/mimeTypes from the real resources/list wire response.
_ANNOUNCED_RESOURCES = {
    _STATUS_URI: "Connection Status",
    _CONFIG_URI: "Configuration",
    _RATE_LIMITS_URI: "Rate Limiter Status",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove every config-mapped env key from the TEST process (P-0035).

    This sanitizes the os.environ the subprocess env is built from, so a
    hostile host env cannot leak credentials or controls into the spawned
    server. DEMO_MODE and PYTHONPATH are re-set explicitly in _build_env.
    """
    for key in list(os.environ):
        if (
            key.startswith(_ENV_PREFIXES)
            or key.startswith(_ENV_LOOSE_PREFIXES)
            or key in _ENV_KEYS
        ):
            monkeypatch.delenv(key, raising=False)


def _build_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["DEMO_MODE"] = "true"
    # Dev-only seam (P-0085 house pattern): where the spawned server's code
    # comes from. The contract acceptance never sets this var, so the suite
    # always runs against the real tree derived from this file's location;
    # the pre-fix RED-pré proof points it at the pre-fix checkout instead.
    env["PYTHONPATH"] = os.environ.get("T288_STDIO_SRC_DIR") or str(SRC_DIR)
    env["HTTP_PROXY"] = _INOPERATIVE_PROXY
    env["HTTPS_PROXY"] = _INOPERATIVE_PROXY
    env["ALL_PROXY"] = _INOPERATIVE_PROXY
    if extra:
        env.update(extra)
    return env


def _tool_names(accessor) -> set[str]:
    """Derive the tool names from a real registry accessor (L-0002)."""
    return {tool.name for tool in accessor()}


def _derivable_public_names() -> set[str]:
    """The set of tool names served WITHOUT API credentials, derived from the
    real registries: market discovery (8), market analysis (10) and the
    always-listed realtime family (7)."""
    return (
        _tool_names(market_discovery.get_tools)
        | _tool_names(market_analysis.get_tools)
        | _tool_names(realtime.get_tools)
    )


def _derivable_gated_names() -> set[str]:
    """The trading (12) + portfolio (8) names that require API credentials,
    derived from their registry accessors."""
    return _tool_names(trading.get_tool_definitions) | _tool_names(
        portfolio_integration.get_portfolio_tool_definitions
    )


class StdioSession:
    """A newline-delimited JSON-RPC session with the real server subprocess.

    One pump thread per pipe (no select-on-pipes: Windows-portable), each
    request flushed as a single line, per-request timeout with loud failure
    and kill-on-hang at teardown. Explicit encoding="utf-8" (P-0099).
    """

    REQUEST_TIMEOUT_SEC = 30.0

    def __init__(self, cwd: Path, extra_env: dict[str, str] | None = None):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "polymarket_mcp.server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_build_env(extra_env),
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
        )
        self._next_id = 0
        self._responses: queue.Queue = queue.Queue()
        self._unsolicited: list[dict] = []
        self._stderr_lines: list[str] = []
        self._closed = False
        self._stdout_thread = threading.Thread(
            target=self._pump_stdout, daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._pump_stderr, daemon=True
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _pump_stdout(self) -> None:
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                message = {"__non_json__": line}
            self._responses.put(message)
        self._responses.put(None)  # EOF sentinel

    def _pump_stderr(self) -> None:
        for line in self.proc.stderr:
            self._stderr_lines.append(line)

    def _write_line(self, text: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()

    def send_notification(self, method: str) -> None:
        self._write_line(json.dumps({"jsonrpc": "2.0", "method": method}))

    def request(self, method: str, params: dict | None = None,
                timeout: float | None = None) -> dict:
        """Send one JSON-RPC request and return its response (error or result).

        Times out loudly (killing the server) instead of hanging; responses
        with a different id are parked in _unsolicited.
        """
        deadline = time.monotonic() + (timeout or self.REQUEST_TIMEOUT_SEC)
        self._next_id += 1
        request_id = self._next_id
        payload: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._write_line(json.dumps(payload))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.terminate()
                pytest.fail(
                    f"timed out after {timeout or self.REQUEST_TIMEOUT_SEC}s "
                    f"waiting for response id={request_id} to {method!r} "
                    "(subprocess killed on hang)"
                )
            try:
                message = self._responses.get(timeout=remaining)
            except queue.Empty:
                continue  # deadline check above raises fail
            if message is None:
                self.terminate()
                pytest.fail(
                    f"server stdout closed before responding to id="
                    f"{request_id} {method!r} (subprocess killed)"
                )
            if message.get("id") != request_id:
                self._unsolicited.append(message)
                continue
            return message

    def stderr_text(self) -> str:
        return "\n".join(self._stderr_lines)

    def terminate(self, timeout: float = 15.0) -> None:
        """Idempotent teardown: graceful EOF, then kill if it hangs."""
        if self._closed:
            return
        self._closed = True
        try:
            if self.proc.stdin is not None and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)

    def shutdown_and_wait(self, timeout: float = REQUEST_TIMEOUT_SEC) -> int:
        """Close stdin (EOF) and wait for the graceful shutdown exit code."""
        returncode: int | None = None
        if self.proc.stdin is not None and not self.proc.stdin.closed:
            self.proc.stdin.close()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            returncode = self.proc.poll()
            if returncode is not None:
                break
            time.sleep(0.05)
        if returncode is None:
            self.proc.kill()
            pytest.fail(
                f"server did not exit within {timeout}s after stdin EOF "
                "(killed on hang)"
            )
        return returncode


@pytest.fixture
def demo_session(tmp_path):
    """Function-scoped pristine session: one fresh server subprocess per
    test, cwd=tmp_path (host .env never leaks), killed on hang."""
    session = StdioSession(cwd=tmp_path)
    try:
        yield session
    finally:
        session.terminate()


def _handshake(session: StdioSession) -> dict:
    """initialize + notifications/initialized; returns the initialize result."""
    result = session.request(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pytest-offline-e2e", "version": "0"},
        },
    )["result"]
    session.send_notification("notifications/initialized")
    return result


def _read_resource(session: StdioSession, uri: str) -> dict:
    """resources/read returning the parsed JSON payload of the first content."""
    response = session.request("resources/read", {"uri": uri})
    contents = response["result"]["contents"]
    return json.loads(contents[0]["text"])


# =====================================================================
# 1. initialize handshake
# =====================================================================


def test_stdio_initialize_handshake(demo_session):
    """initialize (2024-11-05) echoes the offered protocol version, reports
    the pinned server name and the package version by reflection (never a
    literal), and advertises both tools and resources capabilities."""
    result = _handshake(demo_session)

    assert result["protocolVersion"] == "2024-11-05"
    server_info = result["serverInfo"]
    assert server_info["name"] == "polymarket-trading"
    assert server_info["version"] == polymarket_mcp.__version__
    capabilities = result["capabilities"]
    assert "tools" in capabilities
    assert "resources" in capabilities


# =====================================================================
# 2. tools/list without credentials (derived, no literal counts)
# =====================================================================


def test_stdio_tools_list_demo_state_derived(demo_session):
    """tools/list without credentials serves EXACTLY the union of the always
    available families derived from the real registries; the credential-gated
    trading (12) and portfolio (8) families are absent BY NAME (never a
    literal 25 - L-0002)."""
    _handshake(demo_session)
    response = demo_session.request("tools/list", {})
    served = {tool["name"] for tool in response["result"]["tools"]}

    expected_public = _derivable_public_names()
    assert served == expected_public

    gated = _derivable_gated_names()
    assert gated.isdisjoint(served)


# =====================================================================
# 3. tools/list with dummy credentials (derived, no literal 45)
# =====================================================================


def test_stdio_tools_list_with_credentials_derived(tmp_path):
    """With dummy L2 credentials the same wire serves the FULL union: the
    public families plus trading (12) and portfolio (8), all derived from the
    real registries; every trading name is present by member."""
    session = StdioSession(cwd=tmp_path, extra_env=DEMO_CREDENTIALS_ENV)
    try:
        _handshake(session)
        response = session.request("tools/list", {})
        served = {tool["name"] for tool in response["result"]["tools"]}

        expected = _derivable_public_names() | _derivable_gated_names()
        assert served == expected

        for name in sorted(_tool_names(trading.get_tool_definitions)):
            assert name in served
    finally:
        session.terminate()


# =====================================================================
# 4. resources/list announces the three URIs (by member)
# =====================================================================


def test_stdio_resources_list_three_uris(demo_session):
    """resources/list carries the three announced URIs with their observed
    names and mimeType application/json (pinned per member, never by total
    count - L-0148)."""
    _handshake(demo_session)
    response = demo_session.request("resources/list", {})
    by_uri = {resource["uri"]: resource for resource in response["result"]["resources"]}

    for uri, name in _ANNOUNCED_RESOURCES.items():
        assert uri in by_uri
        assert by_uri[uri]["name"] == name
        assert by_uri[uri]["mimeType"] == "application/json"


# =====================================================================
# 5. resources/read status over the wire (the bug this suite closes)
# =====================================================================


def test_stdio_read_resource_status(demo_session):
    """polymarket://status over the real wire reflects the DEMO state:
    connected true (client built from the demo config), the demo address,
    chain_id 137, has_api_credentials false and the reflected package
    version. Pre-fix RED (proven 1st-hand against b240bb9 over the wire):
    the text was '{"error": "Unknown resource: polymarket://status"}'
    with mimeType text/plain."""
    _handshake(demo_session)
    response = demo_session.request("resources/read", {"uri": _STATUS_URI})
    contents = response["result"]["contents"]
    assert contents[0]["mimeType"] == "text/plain"
    payload = json.loads(contents[0]["text"])

    assert payload["connected"] is True
    assert payload["address"]
    assert payload["chain_id"] == 137
    assert payload["has_api_credentials"] is False
    assert payload["server_version"] == polymarket_mcp.__version__


# =====================================================================
# 6. resources/read config + rate-limits over the wire
# =====================================================================


def test_stdio_read_resource_config_and_rate_limits(demo_session):
    """polymarket://config over the wire serves the DEMO config DATA
    (declared divergence from the contract prose: with DEMO_MODE=true and no
    .env, initialize_server loads a real demo config, so the resource serves
    values derived from the same reference config; the pre-init
    "Configuration not loaded" observable is pinned in the in-process
    suites). polymarket://rate-limits serves every RATE_LIMITS category with
    the real get_status() bucket structure, values derived from RATE_LIMITS.

    DIVERGENCE-NOTE (L-0025): the contract's prose for this test expected
    {"error": "Configuration not loaded"} for cwd-pristine; the observed
    wire behavior (probed 1st-hand) is data, and the assert below pins the
    observed behavior.
    """
    _handshake(demo_session)

    config_payload = _read_resource(demo_session, _CONFIG_URI)
    reference = PolymarketConfig(DEMO_MODE=True, _env_file=None)
    reference_limits = create_safety_limits_from_config(reference)

    assert set(config_payload) == {"safety_limits", "trading_controls", "endpoints"}
    assert config_payload["safety_limits"] == {
        "max_order_size_usd": reference_limits.max_order_size_usd,
        "max_total_exposure_usd": reference_limits.max_total_exposure_usd,
        "max_position_size_per_market": reference_limits.max_position_size_per_market,
        "min_liquidity_required": reference_limits.min_liquidity_required,
        "max_spread_tolerance": reference_limits.max_spread_tolerance,
    }
    assert config_payload["trading_controls"] == {
        "enable_autonomous_trading": reference.ENABLE_AUTONOMOUS_TRADING,
        "require_confirmation_above_usd": reference.REQUIRE_CONFIRMATION_ABOVE_USD,
        "auto_cancel_on_large_spread": reference.AUTO_CANCEL_ON_LARGE_SPREAD,
    }
    assert config_payload["endpoints"] == {
        "clob_api": reference.CLOB_API_URL,
        "gamma_api": reference.GAMMA_API_URL,
    }

    rate_payload = _read_resource(demo_session, _RATE_LIMITS_URI)
    expected_categories = {category.value for category in RATE_LIMITS}
    assert set(rate_payload) == expected_categories

    for category in RATE_LIMITS:
        bucket = rate_payload[category.value]
        assert set(bucket) == {
            "available_tokens",
            "max_tokens",
            "refill_rate_per_sec",
            "backoff_remaining_sec",
            "is_throttled",
        }
        assert bucket["max_tokens"] == RATE_LIMITS[category].max_tokens
        assert bucket["refill_rate_per_sec"] == RATE_LIMITS[category].refill_rate
        assert bucket["is_throttled"] is False
        assert bucket["backoff_remaining_sec"] == 0.0
        assert bucket["available_tokens"] == bucket["max_tokens"]


# =====================================================================
# 7. tools/call with unknown tool (invalid params variant)
# =====================================================================


def test_stdio_unknown_tool_invalid_params(demo_session):
    """tools/call with an unknown tool name AND malformed arguments answers
    the JSON-RPC error -32602 "Invalid request parameters" (the SDK request
    validation rejects the params before any handler runs). Paired contrast
    case (L-0056) pinned in the same test: with VALID params
    (arguments={}) the request reaches the call_tool handler and the error
    envelope comes back as a RESULT (isError: false) with the
    unknown-tool error object inside the text content."""
    _handshake(demo_session)

    invalid = demo_session.request(
        "tools/call", {"name": "unknown_tool_xyz", "arguments": "not-a-dict"}
    )
    assert invalid["error"]["code"] == -32602
    assert invalid["error"]["message"] == "Invalid request parameters"

    valid = demo_session.request(
        "tools/call", {"name": "unknown_tool_xyz", "arguments": {}}
    )
    assert "error" not in valid
    assert valid["result"]["isError"] is False
    inner = json.loads(valid["result"]["content"][0]["text"])
    assert inner == {
        "success": False,
        "error": "Unknown tool: unknown_tool_xyz",
        "tool": "unknown_tool_xyz",
        "arguments": {},
    }


# =====================================================================
# 8. graceful shutdown on stdin EOF
# =====================================================================


def test_stdio_graceful_shutdown_on_eof(demo_session):
    """Closing stdin ends the server process with exit code 0 (observed) and
    logs "Graceful shutdown complete" on stderr (substring - the exact text
    is runtime log output)."""
    _handshake(demo_session)

    returncode = demo_session.shutdown_and_wait()
    assert returncode == 0
    assert "Graceful shutdown complete" in demo_session.stderr_text()
