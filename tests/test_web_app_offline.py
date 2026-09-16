"""
Offline regression suite for the FastAPI web dashboard (src/polymarket_mcp/web/app.py).

T-0050 — web/app.py was the only src/ module with ZERO coverage (0.00%, 228 stmts
missing 11-524 @ main 9e675da). This suite pins every region of the module with
TestClient (fastapi.testclient, httpx transport) — ZERO network, ZERO real sleeps.

Coverage map (all pinned OBSERVED, L-0020/L-0025):
- lifespan (:37-49): load_mcp_config() on startup with a valid dummy wallet env
  sets wa.config/wa.client/wa.safety_limits; on shutdown the finally-block closes
  every active WebSocket (and — pinned quirk — leaves them in the list).
- load_mcp_config (:97-122): env without a key makes load_config() raise; the
  exception is captured (logger.error + logger.warning) and the dashboard keeps
  serving with globals None.
- HTML pages (:129-227): / renders index.html; /config and /markets render their
  templates; /monitoring has TWO observable states (see FINDING-2 below).
- /api/status (:234-253): disconnected report without globals; connected READ-ONLY
  report (25 tools) with config+client; rate_limits payload is the read-only
  rate_limiter.get_status() (offline-safe).
- /api/stats (:433-440): 500 — the stats dict contains `uptime_start: datetime`,
  which JSONResponse cannot serialize (FINDING-1, broken on main; pinned as
  regression guard, NOT fixed here — src is out of scope for this slice).
- /api/test-connection (:256-280): without client -> HTTPException 500 "MCP client
  not initialized"; with client, market_discovery.handle_tool is stubbed at the
  module seam BEFORE any request (L-0118) — success counts len(result) (pinned
  quirk: it counts MCP messages, not markets); failure returns a JSONResponse
  with {"success": False, "error": str(e)} (pinned: not an HTTPException detail).
- /api/markets/trending|search|{id}|{id}/analyze (:283-376): handle_tool stubs;
  payloads parsed from result[0].text; empty result -> {"markets": []} for
  trending/search but 500 "404: Market not found" for details/analyze (FINDING-3:
  the HTTPException(404) raised inside the try is re-wrapped by the except into
  500 — pinned OBSERVED, app.py:346/369); tool errors -> 500 detail=str(e);
  search forwards {"query": q, "limit": limit} verbatim.
- POST /api/config (:377-430): writes Path(".env") RELATIVE TO CWD — every test
  of this route runs under monkeypatch.chdir(tmp_path) and re-proves the worktree
  .env is untouched before/after. The 8 safety keys are rewritten (floats via
  str(float) e.g. "10.0"; bools via str(bool).lower() e.g. "false"), unmanaged
  lines are preserved in place, and secrets (POLYGON_PRIVATE_KEY et al.) are
  never touched. Missing .env -> the HTTPException(404) raised inside the try is
  re-wrapped into 500 "404: .env file not found" (FINDING-3 sibling, app.py:388).
  After the write load_mcp_config() is awaited; the real reload re-reads the
  REWRITTEN .env (config.MAX_ORDER_SIZE_USD == 10.0 observed). Pinned quirk
  (FINDING-4): keys ABSENT from the .env are silently NOT appended — the update
  loop only replaces lines that already start with "<KEY>=" (app.py:406-414).
- /ws (:447-482) and broadcast_update (:485-497): driven directly with fake
  sockets; asyncio.sleep is replaced on the wa module namespace by an instant
  fake that records its calls (L-0014 — no real 5s wait); the disconnect path
  removes the socket from active_websockets and logs; the generic-error branch
  removes it too; broadcast_update removes failed senders and keeps good ones.
- start() (:504-524): uvicorn.run is replaced on the wa module namespace (never
  executed); defaults are loopback 127.0.0.1:8080 with NO warning; any
  non-loopback host emits the WARNING "not loopback"; WEB_HOST/WEB_PORT env
  override the defaults.

Seams declared (house style, P-0031 — fail-loud module stubs):
- wa.market_discovery / wa.market_analysis replaced by FakeToolModule whose
  handle_tool raises AssertionError on an unexpected tool name — a regression
  cannot silently fall through to the real network-touching module (L-0118: the
  stub is installed BEFORE any request reaches these routes).
- wa.asyncio replaced by a namespace whose sleep records and returns instantly
  (only inside the /ws tests; monkeypatch restores the real module attribute).
- wa.uvicorn replaced by a namespace whose run() only records arguments.
- wa.load_mcp_config wrapped by a recorder that delegates to the real loader
  (reload pin keeps the real read-the-rewritten-file semantics).
- Websocket clients in the shutdown test are FakeWebSocket instances (the
  lifespan only calls await ws.close()).

Hermeticity (L-0022): web.app globals are MODULE state — the autouse fixture
`pristine_web_state` resets config/client/safety_limits/active_websockets to
None/[] and installs a per-test COPY of the stats dict, then restores the
originals (including the original stats object identity) on teardown. The
lifespan writes the globals directly (bypassing monkeypatch), so explicit
snapshot/restore is mandatory. Env is fully managed via monkeypatch (setenv/
delenv — automatic restore); `load_config()` also reads env_file=".env" relative
to CWD, so every lifespan/POST test asserts as PRECONDITION that the worktree
root has no .env file (fail loud otherwise — P-0026 anti-vacuo style).

FINDINGS (behavior observed on main 9e675da — pinned as regression guards; src/
is SUITE-ONLY for this slice, so none are fixed here; follow-ups for the report):
- FINDING-1: GET /api/stats always 500 — stats contains uptime_start: datetime,
  JSONResponse render raises TypeError (app.py:76-82/436-439).
- FINDING-2: GET /monitoring with config set -> 500 — monitoring.html:84-91
  renders status.remaining/status.limit but rate_limiter.get_status() provides
  available_tokens/max_tokens (jinja2 UndefinedError). Without config the page
  renders 200 "No rate limit data available".
- FINDING-3: HTTPException(404) raised INSIDE the try of /api/markets/{id},
  /api/markets/{id}/analyze and POST /api/config is re-wrapped by the except
  into 500 (detail "404: ...") — app.py:346/369/388.
- FINDING-4: POST /api/config only rewrites keys ALREADY PRESENT in the .env;
  keys absent are silently not appended (app.py:406-414).

Prerequisites: pytest-asyncio auto mode (pyproject [tool.pytest.ini_options]);
fastapi 0.141.1 + httpx 0.28.1 + Jinja2 3.1.6 in the clone venv; no
integration/slow/real_api/performance markers — runs clean under the release
gate filter `-m "not integration and not slow and not real_api and not performance"`.

Known coupling (L-0073, consumer↔producer): this suite pins template rendering
markers (index title, monitoring else-branch text) and the exact str(float)/
str(bool).lower() env rewrite format. A src/ fix that changes these formats must
update this file in the SAME slice.
"""
import json
import logging
import pathlib
from types import SimpleNamespace
from typing import Any, Optional

import jinja2
import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from polymarket_mcp.auth import create_polymarket_client
from polymarket_mcp.config import load_config
from polymarket_mcp.web import app as wa

# Dummy wallet: the house-standard offline key (valid 64-hex format, zero value).
DUMMY_PRIVATE_KEY = "0" * 63 + "1"
DUMMY_ADDRESS = "0x" + "0" * 40

# CWD at import time == the worktree root (pytest is invoked from there). Every
# POST /api/config test re-proves this directory is never touched by the route.
_WORKTREE_ROOT = pathlib.Path.cwd()

# Every env key the web module can observe — cleared per test (monkeypatch
# restores automatically). The 8 POST-managed keys are included so .env-file
# values in the isolated CWD win over ambient environment in reload assertions.
_KEYS_CLEANED = (
    "POLYGON_PRIVATE_KEY",
    "POLYGON_ADDRESS",
    "POLYMARKET_API_KEY",
    "POLYMARKET_API_SECRET",
    "POLYMARKET_PASSPHRASE",
    "POLYMARKET_API_KEY_NAME",
    "DEMO_MODE",
    "WEB_HOST",
    "WEB_PORT",
    "MAX_ORDER_SIZE_USD",
    "MAX_TOTAL_EXPOSURE_USD",
    "MAX_POSITION_SIZE_PER_MARKET",
    "MIN_LIQUIDITY_REQUIRED",
    "MAX_SPREAD_TOLERANCE",
    "ENABLE_AUTONOMOUS_TRADING",
    "REQUIRE_CONFIRMATION_ABOVE_USD",
    "AUTO_CANCEL_ON_LARGE_SPREAD",
)

# Captured at import time, before any test runs: the pristine stats dict (the
# module never mutates it directly — handlers only see per-test copies).
_PRISTINE_STATS = dict(wa.stats)


class FakeMessage:
    """Stand-in for the MCP TextContent objects the routes consume (.text only)."""

    def __init__(self, text: str) -> None:
        self.text = text


def text_payload(payload: Any) -> list[FakeMessage]:
    """Build the [TextContent-like] list a successful handle_tool returns."""
    return [FakeMessage(text=json.dumps(payload))]


class FakeToolModule:
    """Fail-loud module seam for market_discovery/market_analysis (P-0031).

    handle_tool records every call and returns the canned result for the tool
    name; an unexpected tool name raises AssertionError so a regression cannot
    silently fall through to the real network-touching module (L-0118 — the stub
    must exist BEFORE any request reaches these routes).
    """

    def __init__(
        self,
        results: Optional[dict[str, Any]] = None,
        error: Optional[Exception] = None,
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._results = results or {}
        self._error = error

    async def handle_tool(self, name: str, arguments: dict) -> list[FakeMessage]:
        self.calls.append((name, dict(arguments)))
        if self._error is not None:
            raise self._error
        if name not in self._results:
            raise AssertionError(
                f"unexpected tool call: {name!r} args={arguments!r} — the stub "
                "must answer every tool the route may call (L-0118 fail-loud)"
            )
        result = self._results[name]
        if callable(result):
            return result(arguments)
        return result


class FakeWebSocket:
    """Minimal async WebSocket stand-in for wa.websocket_endpoint/broadcast_update.

    accept/send_json/close are recorded. fail_on_send_index (1-based) makes the
    Nth send_json raise `fail_with` — driving the disconnect/generic-error paths
    of the endpoint without a real server.
    """

    def __init__(
        self,
        fail_on_send_index: Optional[int] = None,
        fail_with: Optional[Exception] = None,
    ) -> None:
        self.accepted = 0
        self.sent: list[dict] = []
        self.closed = 0
        self.fail_on_send_index = fail_on_send_index
        self.fail_with = fail_with

    async def accept(self) -> None:
        self.accepted += 1

    async def send_json(self, message: dict, mode: str = "text") -> None:
        self.sent.append(message)
        if (
            self.fail_on_send_index is not None
            and len(self.sent) == self.fail_on_send_index
        ):
            raise self.fail_with

    async def close(self) -> None:
        self.closed += 1


@pytest.fixture(autouse=True)
def pristine_web_state():
    """Reset web.app module globals per test and restore the originals (L-0022).

    The lifespan writes wa.config/wa.client/wa.safety_limits DIRECTLY (global
    statement) and handlers mutate wa.stats in place — both bypass monkeypatch.
    Each test therefore starts from the pristine baseline (captured at import)
    with a per-test COPY of stats, and teardown restores the original objects,
    making the suite order-independent.
    """
    wa.config = None
    wa.client = None
    wa.safety_limits = None
    wa.active_websockets = []
    wa.stats = dict(_PRISTINE_STATS)
    yield
    wa.config = None
    wa.client = None
    wa.safety_limits = None
    wa.active_websockets = []
    wa.stats = _PRISTINE_STATS


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch):
    """Remove every env key the web module can observe; return the monkeypatch."""
    for key in _KEYS_CLEANED:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


@pytest.fixture()
def wallet_env(clean_env, monkeypatch: pytest.MonkeyPatch):
    """Env with a valid dummy wallet so load_config() succeeds."""
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", DUMMY_PRIVATE_KEY)
    monkeypatch.setenv("POLYGON_ADDRESS", DUMMY_ADDRESS)
    return monkeypatch


def _assert_no_env_in_worktree() -> None:
    """Fail loud if a .env appeared in the worktree root (hermeticity guard).

    load_config() reads env_file=".env" relative to CWD; the lifespan tests
    depend on the worktree root having NO .env (env-only config), and the POST
    /api/config tests depend on the route never writing outside the isolated
    tmp CWD. A .env here would invalidate both.
    """
    assert not (_WORKTREE_ROOT / ".env").exists(), (
        "A .env file appeared in the worktree root — the web suite requires a "
        "clean root (env-only config; POST /api/config writes only under the "
        "isolated tmp CWD). Refusing to run: hermeticity precondition violated."
    )


def _install_stubs(
    monkeypatch: pytest.MonkeyPatch,
    discovery: Optional[FakeToolModule] = None,
    analysis: Optional[FakeToolModule] = None,
) -> tuple[FakeToolModule, FakeToolModule]:
    """Patch BOTH tool seams of web.app BEFORE any request (L-0118).

    Each route's seam gets the fake with canned results; the OTHER seam gets an
    empty fail-loud module (unexpected tool -> AssertionError) so a regression
    that swaps the seams — or adds a cross-module call — fails the test loudly
    instead of reaching the real network-touching module. (Learned live: a stub
    installed on only one seam let a request through to gamma-api — the window
    the lesson warns about.)
    """
    if discovery is None:
        discovery = FakeToolModule()
    if analysis is None:
        analysis = FakeToolModule()
    monkeypatch.setattr(wa, "market_discovery", discovery)
    monkeypatch.setattr(wa, "market_analysis", analysis)
    return discovery, analysis


def _config_payload(**overrides: Any) -> dict:
    """Full valid ConfigUpdateRequest body (all 8 fields)."""
    payload = {
        "max_order_size_usd": 10.0,
        "max_total_exposure_usd": 50.0,
        "max_position_size_per_market": 20.0,
        "min_liquidity_required": 100.0,
        "max_spread_tolerance": 0.02,
        "enable_autonomous_trading": False,
        "require_confirmation_above_usd": 25.0,
        "auto_cancel_on_large_spread": False,
    }
    payload.update(overrides)
    return payload


# ============================================================================
# Lifespan
# ============================================================================


def test_lifespan_loads_config_client_and_safety_limits(wallet_env):
    """with TestClient(app) runs lifespan: config/client/safety_limits are set."""
    _assert_no_env_in_worktree()
    with TestClient(wa.app):
        # Globals set by the REAL load_mcp_config (no monkeypatch on them).
        assert wa.config is not None
        assert wa.client is not None
        assert wa.safety_limits is not None
        # The loaded values come from the env-only config (no .env in CWD).
        assert wa.config.POLYGON_PRIVATE_KEY == DUMMY_PRIVATE_KEY
        assert wa.config.POLYGON_ADDRESS == DUMMY_ADDRESS.lower()
        assert wa.config.POLYMARKET_CHAIN_ID == 137
        # Safety limits derived from the same config (defaults, no env overrides).
        assert wa.safety_limits.max_order_size_usd == 1000.0
        assert wa.client.get_address() == DUMMY_ADDRESS.lower()
        # Dummy key carries no L2 credentials: READ-ONLY (25 tools).
        assert wa.client.has_api_credentials() is False
    # Pinned OBSERVED (L-0022): globals PERSIST after the lifespan exits —
    # the module never resets them; the autouse fixture restores the baseline.
    assert wa.config is not None
    assert wa.client is not None
    assert wa.safety_limits is not None


def test_lifespan_config_failure_serves_dashboard_without_mcp(clean_env, caplog):
    """Env without a key: load_config raises, is captured, dashboard serves."""
    _assert_no_env_in_worktree()
    with TestClient(wa.app) as client:
        assert wa.config is None
        assert wa.client is None
        assert wa.safety_limits is None
        # The dashboard still serves: status reports the disconnected state.
        response = client.get("/api/status")
        assert response.status_code == 200
        assert response.json() == {"connected": False, "error": "MCP not configured"}
        response = client.get("/")
        assert response.status_code == 200
    # The failure was captured and reported (app.py:120-122).
    messages = [record.getMessage() for record in caplog.records]
    assert any("Failed to load configuration" in message for message in messages)
    assert any(
        "Dashboard running without MCP connection" in message for message in messages
    )


def test_lifespan_closes_active_websockets_on_shutdown(wallet_env):
    """The lifespan finally-block closes every active WebSocket (app.py:43-48)."""
    _assert_no_env_in_worktree()
    fake_one = FakeWebSocket()
    fake_two = FakeWebSocket()
    wa.active_websockets.extend([fake_one, fake_two])
    with TestClient(wa.app):
        pass
    assert fake_one.closed == 1
    assert fake_two.closed == 1
    # Pinned OBSERVED quirk: the list is NOT cleared after closing (app.py:44-48
    # closes each socket but never empties active_websockets).
    assert wa.active_websockets == [fake_one, fake_two]


def test_lifespan_shutdown_tolerates_close_failures(wallet_env):
    """A socket whose close() raises is swallowed by the finally-block's bare
    except (app.py:45-48): the remaining sockets still get closed, shutdown
    completes."""
    _assert_no_env_in_worktree()

    class ExplodingCloseSocket(FakeWebSocket):
        async def close(self) -> None:
            self.closed += 1
            raise RuntimeError("close exploded")

    healthy = FakeWebSocket()
    exploding = ExplodingCloseSocket()
    wa.active_websockets.extend([exploding, healthy])
    with TestClient(wa.app):
        pass
    # Both close attempts happened; the explosion did not abort the loop.
    assert exploding.closed == 1
    assert healthy.closed == 1


# ============================================================================
# HTML pages
# ============================================================================


def test_home_page_renders_html():
    """GET / renders index.html: 200, text/html, template marker, stat bump."""
    response = TestClient(wa.app).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Polymarket MCP Dashboard" in response.text
    # The handler mutated the per-test stats copy (not the module original).
    assert wa.stats["requests_total"] == 1
    assert _PRISTINE_STATS["requests_total"] == 0
    # Without globals the page renders the disconnected status block.
    assert "MCP Status" in response.text


def test_config_and_markets_pages_render_html():
    """GET /config and /markets render their templates (200, text/html)."""
    client = TestClient(wa.app)
    config_response = client.get("/config")
    assert config_response.status_code == 200
    assert config_response.headers["content-type"].startswith("text/html")
    assert "Configuration" in config_response.text
    markets_response = client.get("/markets")
    assert markets_response.status_code == 200
    assert markets_response.headers["content-type"].startswith("text/html")
    assert "Market Discovery" in markets_response.text
    # Both pages bump the request counter.
    assert wa.stats["requests_total"] == 2


def test_config_page_with_config_renders_limits_and_wallet(wallet_env, monkeypatch):
    """GET /config with globals set renders the populated form (app.py:163-182):
    wallet address, READ-ONLY marker and the safety-limit values."""
    monkeypatch.setattr(wa, "config", load_config())
    monkeypatch.setattr(wa, "client", create_polymarket_client(
        private_key=DUMMY_PRIVATE_KEY, address=DUMMY_ADDRESS))
    monkeypatch.setattr(wa, "safety_limits", wa.create_safety_limits_from_config(
        wa.config))
    response = TestClient(wa.app).get("/config")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # The wallet and the READ-ONLY L2 status are rendered from the globals.
    assert DUMMY_ADDRESS.lower() in response.text
    assert "Not Configured (Read-Only Mode)" in response.text
    # The default safety limits flow into the form inputs.
    assert 'value="1000.0"' in response.text
    assert wa.stats["requests_total"] == 1


def test_monitoring_page_renders_without_config_and_errors_with_config(
    wallet_env, monkeypatch
):
    """GET /monitoring: 200 without config; 500 (template crash) with config.

    FINDING-2 (pinned OBSERVED, NOT fixed — src is SUITE-ONLY): with config set
    the page passes rate_limiter.get_status() to monitoring.html, whose loop
    renders status.remaining/status.limit (monitoring.html:91) — keys the real
    payload never provides (it has available_tokens/max_tokens) — so the render
    raises jinja2.UndefinedError and the route 500s.
    """
    client = TestClient(wa.app)
    # State 1: config None -> rate_status {} -> template else-branch -> 200.
    response = client.get("/monitoring")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "No rate limit data available" in response.text

    # State 2: config set -> non-empty rate_status -> template crash.
    monkeypatch.setattr(wa, "config", load_config())
    rate_status = wa.get_rate_limiter().get_status()
    # Mechanism pin from the DATA side: the payload lacks the keys the template
    # renders (remaining/limit).
    assert rate_status  # non-empty -> the template loop actually runs
    assert "limit" not in next(iter(rate_status.values()))
    assert "remaining" not in next(iter(rate_status.values()))
    # The 500 as the client observes it.
    tolerant = TestClient(wa.app, raise_server_exceptions=False)
    crashed = tolerant.get("/monitoring")
    assert crashed.status_code == 500
    assert crashed.text == "Internal Server Error"
    # The mechanism as the server raises it.
    strict = TestClient(wa.app)
    with pytest.raises(
        jinja2.exceptions.UndefinedError, match="has no attribute 'limit'"
    ):
        strict.get("/monitoring")


# ============================================================================
# /api/status
# ============================================================================


def test_api_status_without_mcp_reports_disconnected():
    """No globals (lifespan never ran): 200 disconnected report."""
    response = TestClient(wa.app).get("/api/status")
    assert response.status_code == 200
    assert response.json() == {"connected": False, "error": "MCP not configured"}
    # The handler counted the call on the per-test stats copy.
    assert wa.stats["api_calls"] == 1


def test_api_status_with_client_reports_readonly_connection(wallet_env, monkeypatch):
    """config+client set: connected READ-ONLY report (25 tools, rate_limits)."""
    config = load_config()
    client_obj = create_polymarket_client(
        private_key=DUMMY_PRIVATE_KEY,
        address=DUMMY_ADDRESS,
        chain_id=config.POLYMARKET_CHAIN_ID,
    )
    monkeypatch.setattr(wa, "config", config)
    monkeypatch.setattr(wa, "client", client_obj)
    response = TestClient(wa.app).get("/api/status")
    body = response.json()
    assert response.status_code == 200
    assert body["connected"] is True
    assert body["address"] == DUMMY_ADDRESS.lower()
    assert body["chain_id"] == 137
    assert body["has_api_credentials"] is False
    assert body["mode"] == "READ-ONLY"
    assert body["tools_available"] == 25
    # rate_limits is the read-only rate limiter status (offline-safe).
    assert body["rate_limits"] == wa.get_rate_limiter().get_status()
    assert body["rate_limits"]  # non-empty: every category is present


# ============================================================================
# /api/stats
# ============================================================================


def test_api_stats_returns_internal_server_error():
    """GET /api/stats 500s: uptime_start (datetime) is not JSON serializable.

    FINDING-1 (pinned OBSERVED, NOT fixed — src is SUITE-ONLY): app.py:76-82
    stores uptime_start as datetime and app.py:436-439 feeds it to JSONResponse,
    whose json.dumps raises TypeError. Pinned both as the 500 the client sees
    and as the underlying TypeError the server raises.
    """
    tolerant = TestClient(wa.app, raise_server_exceptions=False)
    response = tolerant.get("/api/stats")
    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    strict = TestClient(wa.app)
    with pytest.raises(TypeError, match="not JSON serializable"):
        strict.get("/api/stats")


# ============================================================================
# /api/test-connection
# ============================================================================


def test_test_connection_without_client_raises_500():
    """No client: HTTPException 500 "MCP client not initialized" + error bump."""
    tolerant = TestClient(wa.app, raise_server_exceptions=False)
    response = tolerant.get("/api/test-connection")
    assert response.status_code == 500
    assert response.json() == {"detail": "MCP client not initialized"}
    # The route counted the failure on the stats copy (app.py:262).
    assert wa.stats["errors"] == 1
    assert wa.stats["api_calls"] == 1


def test_test_connection_with_stubbed_discovery_reports_success_count(monkeypatch):
    """Stubbed discovery answers: 200 success with markets_found == len(result).

    Pinned OBSERVED quirk: markets_found counts the MCP messages returned by
    handle_tool, NOT the markets inside the payload (app.py:269-273) — one
    message carrying three markets still reports markets_found == 1.
    """
    fake, _ = _install_stubs(monkeypatch, discovery=FakeToolModule(results={
        "get_trending_markets": text_payload({"markets": ["m1", "m2", "m3"]}),
    }))
    monkeypatch.setattr(wa, "client", create_polymarket_client(
        private_key=DUMMY_PRIVATE_KEY, address=DUMMY_ADDRESS))
    response = TestClient(wa.app).get("/api/test-connection")
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Connection successful",
        "markets_found": 1,  # len(result) — the message count (OBSERVED)
    }
    # The exact tool call the route makes (fail-loud stub proves the seam).
    assert fake.calls == [("get_trending_markets", {"limit": 5})]
    assert wa.stats["errors"] == 0


def test_test_connection_failure_returns_error_json_500(monkeypatch):
    """Stub raises: 500 JSONResponse {"success": False, "error": str(e)}.

    Pinned OBSERVED: this failure path returns a JSONResponse with a "success"
    key (app.py:277-280), NOT the {"detail": ...} shape of an HTTPException —
    the two 500s of this route have different body shapes.
    """
    fake, _ = _install_stubs(
        monkeypatch, discovery=FakeToolModule(error=RuntimeError("gamma unreachable"))
    )
    monkeypatch.setattr(wa, "client", create_polymarket_client(
        private_key=DUMMY_PRIVATE_KEY, address=DUMMY_ADDRESS))
    response = TestClient(wa.app, raise_server_exceptions=False).get(
        "/api/test-connection")
    assert response.status_code == 500
    assert response.json() == {"success": False, "error": "gamma unreachable"}
    assert fake.calls == [("get_trending_markets", {"limit": 5})]
    assert wa.stats["errors"] == 1


# ============================================================================
# /api/markets/trending
# ============================================================================


def test_trending_markets_parses_stub_text_payload(monkeypatch):
    """Stubbed payload parsed from result[0].text: 200 with the payload body."""
    payload = {"markets": [{"question": "Will X happen?", "volume": 1234.5}]}
    fake, _ = _install_stubs(monkeypatch, discovery=FakeToolModule(results={
        "get_trending_markets": text_payload(payload),
    }))
    response = TestClient(wa.app).get("/api/markets/trending?limit=10")
    assert response.status_code == 200
    assert response.json() == payload
    assert fake.calls == [("get_trending_markets", {"limit": 10})]
    assert wa.stats["markets_viewed"] == 1


def test_trending_markets_empty_result_returns_empty_markets(monkeypatch):
    """Empty handle_tool result: 200 {"markets": []} (no parse attempted)."""
    fake, _ = _install_stubs(
        monkeypatch, discovery=FakeToolModule(results={"get_trending_markets": []}))
    response = TestClient(wa.app).get("/api/markets/trending")
    assert response.status_code == 200
    assert response.json() == {"markets": []}
    assert fake.calls == [("get_trending_markets", {"limit": 10})]  # default limit
    assert wa.stats["markets_viewed"] == 1


def test_trending_markets_tool_error_becomes_500_with_detail(monkeypatch):
    """Tool error: HTTPException 500 with detail=str(e) (from e)."""
    fake, _ = _install_stubs(
        monkeypatch, discovery=FakeToolModule(error=RuntimeError("boom")))
    response = TestClient(wa.app, raise_server_exceptions=False).get(
        "/api/markets/trending")
    assert response.status_code == 500
    assert response.json() == {"detail": "boom"}
    assert fake.calls == [("get_trending_markets", {"limit": 10})]
    assert wa.stats["errors"] == 1
    assert wa.stats["markets_viewed"] == 0


# ============================================================================
# /api/markets/search
# ============================================================================


def test_search_markets_forwards_query_and_limit(monkeypatch):
    """q/limit forwarded verbatim as {"query": q, "limit": limit}; payload 200."""
    payload = {"markets": [{"question": "BTC by Friday?"}]}
    fake, _ = _install_stubs(monkeypatch, discovery=FakeToolModule(results={
        "search_markets": text_payload(payload),
    }))
    response = TestClient(wa.app).get("/api/markets/search?q=bitcoin&limit=7")
    assert response.status_code == 200
    assert response.json() == payload
    assert fake.calls == [("search_markets", {"query": "bitcoin", "limit": 7})]
    assert wa.stats["markets_viewed"] == 1

    # Default limit (20) when the query param is omitted.
    default_response = TestClient(wa.app).get("/api/markets/search?q=trump")
    assert default_response.status_code == 200
    assert fake.calls[-1] == ("search_markets", {"query": "trump", "limit": 20})


def test_search_markets_empty_result_returns_empty_markets(monkeypatch):
    """Empty search result: 200 {"markets": []} (app.py:323) — the trending
    route's empty branch mirrors this one."""
    fake, _ = _install_stubs(
        monkeypatch, discovery=FakeToolModule(results={"search_markets": []}))
    response = TestClient(wa.app).get("/api/markets/search?q=void")
    assert response.status_code == 200
    assert response.json() == {"markets": []}
    assert fake.calls == [("search_markets", {"query": "void", "limit": 20})]
    assert wa.stats["markets_viewed"] == 1


def test_search_markets_tool_error_becomes_500_with_detail(monkeypatch):
    """Search tool error: HTTPException 500 with detail=str(e) (app.py:325-328)."""
    fake, _ = _install_stubs(
        monkeypatch, discovery=FakeToolModule(error=RuntimeError("search down")))
    response = TestClient(wa.app, raise_server_exceptions=False).get(
        "/api/markets/search?q=bitcoin")
    assert response.status_code == 500
    assert response.json() == {"detail": "search down"}
    assert fake.calls == [("search_markets", {"query": "bitcoin", "limit": 20})]
    assert wa.stats["errors"] == 1
    assert wa.stats["markets_viewed"] == 0


# ============================================================================
# /api/markets/{market_id} and /api/markets/{market_id}/analyze
# ============================================================================


def test_market_details_empty_result_wraps_not_found_error(monkeypatch):
    """Empty result: the 404 raised inside the try is re-wrapped into 500.

    FINDING-3 (pinned OBSERVED, NOT fixed — src is SUITE-ONLY): app.py:346
    raises HTTPException(404) INSIDE the try block, so the except at :348-351
    catches it and re-raises 500 with detail str(HTTPException) == "404: Market
    not found". The client never sees a real 404 on this route.
    """
    _, fake = _install_stubs(monkeypatch, analysis=FakeToolModule(
        results={"get_market_details": []}))
    response = TestClient(wa.app, raise_server_exceptions=False).get(
        "/api/markets/0xabc")
    assert response.status_code == 500
    assert response.json() == {"detail": "404: Market not found"}
    assert fake.calls == [("get_market_details", {"market_id": "0xabc"})]
    assert wa.stats["errors"] == 1


def test_market_details_and_analyze_forward_market_id(monkeypatch):
    """market_id forwarded verbatim to analysis.handle_tool in BOTH routes."""
    _, fake = _install_stubs(monkeypatch, analysis=FakeToolModule(results={
        "get_market_details": text_payload({"question": "Market?", "id": "0xabc"}),
        "analyze_market_opportunity": text_payload({"recommendation": "BUY"}),
    }))
    client = TestClient(wa.app)
    details = client.get("/api/markets/0xabc123")
    assert details.status_code == 200
    assert details.json() == {"question": "Market?", "id": "0xabc"}
    analyze = client.get("/api/markets/0xabc123/analyze")
    assert analyze.status_code == 200
    assert analyze.json() == {"recommendation": "BUY"}
    # Both tool calls forwarded the market_id verbatim, in order.
    assert fake.calls == [
        ("get_market_details", {"market_id": "0xabc123"}),
        ("analyze_market_opportunity", {"market_id": "0xabc123"}),
    ]
    # Pinned OBSERVED: these two routes do NOT bump markets_viewed (only
    # trending/search do — app.py:290/316).
    assert wa.stats["markets_viewed"] == 0
    assert wa.stats["errors"] == 0


def test_analyze_market_empty_result_wraps_not_found_error(monkeypatch):
    """Empty analyze result: 404 raised inside the try re-wrapped into 500
    (FINDING-3, app.py:369) — the same shape as the details route."""
    _, fake = _install_stubs(monkeypatch, analysis=FakeToolModule(
        results={"analyze_market_opportunity": []}))
    response = TestClient(wa.app, raise_server_exceptions=False).get(
        "/api/markets/0xdead/analyze")
    assert response.status_code == 500
    assert response.json() == {"detail": "404: Market not found"}
    assert fake.calls == [("analyze_market_opportunity", {"market_id": "0xdead"})]
    assert wa.stats["errors"] == 1


def test_analyze_market_tool_error_becomes_500_with_detail(monkeypatch):
    """Analyze tool error: HTTPException 500 with detail=str(e) (app.py:371-374)."""
    _, fake = _install_stubs(
        monkeypatch, analysis=FakeToolModule(error=RuntimeError("analyze down")))
    response = TestClient(wa.app, raise_server_exceptions=False).get(
        "/api/markets/0xdead/analyze")
    assert response.status_code == 500
    assert response.json() == {"detail": "analyze down"}
    assert fake.calls == [("analyze_market_opportunity", {"market_id": "0xdead"})]
    assert wa.stats["errors"] == 1


# ============================================================================
# POST /api/config
# ============================================================================


def test_post_config_missing_env_yields_500_with_not_found_detail(
    tmp_path, monkeypatch
):
    """No .env in CWD: the 404 raised inside the try is re-wrapped into 500.

    FINDING-3 sibling (pinned OBSERVED): app.py:388 raises HTTPException(404,
    ".env file not found") INSIDE the try, so the except re-wraps it — the
    client sees 500 with detail "404: .env file not found", never a real 404.
    """
    _assert_no_env_in_worktree()
    monkeypatch.chdir(tmp_path)  # Path(".env") resolves here; worktree untouched
    response = TestClient(wa.app, raise_server_exceptions=False).post(
        "/api/config", json=_config_payload())
    assert response.status_code == 500
    assert response.json() == {"detail": "404: .env file not found"}
    # Pinned OBSERVED quirk: the error counter is bumped TWICE on this path —
    # once before raising the 404 (app.py:387) and once again in the except
    # that re-wraps it (app.py:428).
    assert wa.stats["errors"] == 2
    # The route did not create a .env as a side effect.
    assert not (tmp_path / ".env").exists()


def test_post_config_rewrites_safety_keys_and_preserves_other_lines(
    tmp_path, monkeypatch, wallet_env
):
    """All 8 safety keys rewritten (exact str(float)/str(bool).lower() formats),
    unmanaged lines preserved in place, file byte-identical otherwise."""
    _assert_no_env_in_worktree()
    original = (
        "MAX_ORDER_SIZE_USD=999.0\n"
        "MAX_TOTAL_EXPOSURE_USD=4000.0\n"
        "MAX_POSITION_SIZE_PER_MARKET=1500.0\n"
        "MIN_LIQUIDITY_REQUIRED=20000.0\n"
        "MAX_SPREAD_TOLERANCE=0.03\n"
        "ENABLE_AUTONOMOUS_TRADING=true\n"
        "REQUIRE_CONFIRMATION_ABOVE_USD=30.0\n"
        "AUTO_CANCEL_ON_LARGE_SPREAD=true\n"
        "OTHER_KEY=keepme\n"
        "POLYGON_PRIVATE_KEY=real-secret-kept\n"
    )
    (tmp_path / ".env").write_text(original)
    monkeypatch.chdir(tmp_path)
    response = TestClient(wa.app).post("/api/config", json=_config_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "Configuration updated successfully" in body["message"]
    # Pinned rewrite format: str(float) e.g. "10.0"; str(bool).lower() "false".
    expected = (
        "MAX_ORDER_SIZE_USD=10.0\n"
        "MAX_TOTAL_EXPOSURE_USD=50.0\n"
        "MAX_POSITION_SIZE_PER_MARKET=20.0\n"
        "MIN_LIQUIDITY_REQUIRED=100.0\n"
        "MAX_SPREAD_TOLERANCE=0.02\n"
        "ENABLE_AUTONOMOUS_TRADING=false\n"
        "REQUIRE_CONFIRMATION_ABOVE_USD=25.0\n"
        "AUTO_CANCEL_ON_LARGE_SPREAD=false\n"
        "OTHER_KEY=keepme\n"
        "POLYGON_PRIVATE_KEY=real-secret-kept\n"
    )
    assert (tmp_path / ".env").read_text() == expected
    assert wa.stats["errors"] == 0


def test_post_config_never_touches_private_key(tmp_path, monkeypatch, wallet_env):
    """Secrets survive the rewrite verbatim: POLYGON_PRIVATE_KEY + API key."""
    _assert_no_env_in_worktree()
    original = (
        "POLYGON_PRIVATE_KEY=real-secret-kept\n"
        "POLYMARKET_API_KEY=api-secret-kept\n"
        "OTHER_KEY=keepme\n"
    )
    (tmp_path / ".env").write_text(original)
    monkeypatch.chdir(tmp_path)
    response = TestClient(wa.app).post("/api/config", json=_config_payload())
    assert response.status_code == 200
    rewritten = (tmp_path / ".env").read_text()
    # None of the 8 managed keys existed -> nothing to rewrite (FINDING-4);
    # the secrets and the unmanaged line survive byte-identically.
    assert rewritten == original
    assert "real-secret-kept" in rewritten
    assert "api-secret-kept" in rewritten


def test_post_config_rejects_invalid_payload_with_422(tmp_path, monkeypatch):
    """max_order_size_usd="abc" fails pydantic validation before the handler."""
    _assert_no_env_in_worktree()
    monkeypatch.chdir(tmp_path)
    payload = _config_payload(max_order_size_usd="abc")
    response = TestClient(wa.app).post("/api/config", json=payload)
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert errors[0]["loc"] == ["body", "max_order_size_usd"]
    assert errors[0]["type"] == "float_parsing"
    # The handler never ran: no .env was read or written, no call counted.
    assert not (tmp_path / ".env").exists()
    assert wa.stats["api_calls"] == 0


def test_post_config_triggers_config_reload_after_write(
    tmp_path, monkeypatch, wallet_env
):
    """load_mcp_config is awaited after the write; the real reload reads the
    REWRITTEN .env (config.MAX_ORDER_SIZE_USD == 10.0 observed)."""
    _assert_no_env_in_worktree()
    (tmp_path / ".env").write_text(
        "MAX_ORDER_SIZE_USD=999.0\n"
        "MAX_TOTAL_EXPOSURE_USD=4000.0\n"
        "MAX_POSITION_SIZE_PER_MARKET=1500.0\n"
        "MIN_LIQUIDITY_REQUIRED=20000.0\n"
        "MAX_SPREAD_TOLERANCE=0.03\n"
        "ENABLE_AUTONOMOUS_TRADING=true\n"
        "REQUIRE_CONFIRMATION_ABOVE_USD=30.0\n"
        "AUTO_CANCEL_ON_LARGE_SPREAD=true\n"
    )
    monkeypatch.chdir(tmp_path)

    reload_calls: list[str] = []
    real_load = wa.load_mcp_config

    async def recording_load() -> None:
        reload_calls.append("load_mcp_config")
        await real_load()

    monkeypatch.setattr(wa, "load_mcp_config", recording_load)
    response = TestClient(wa.app).post("/api/config", json=_config_payload())
    assert response.status_code == 200
    # The reload ran EXACTLY once, after the write (seam recorded + delegated).
    assert reload_calls == ["load_mcp_config"]
    # The REAL loader re-read the rewritten file (env has no MAX_ORDER_SIZE_USD
    # — clean_env delenvs it — so the .env value wins in pydantic priority).
    assert wa.config is not None
    assert wa.config.MAX_ORDER_SIZE_USD == 10.0
    assert wa.safety_limits is not None
    assert wa.safety_limits.max_order_size_usd == 10.0


def test_post_config_missing_keys_are_not_appended(tmp_path, monkeypatch, wallet_env):
    """FINDING-4 (pinned OBSERVED, NOT fixed — src is SUITE-ONLY): keys ABSENT
    from the .env are silently not appended; the update loop only replaces
    lines already starting with "<KEY>=" (app.py:406-414)."""
    _assert_no_env_in_worktree()
    original = "OTHER_KEY=keepme\nPOLYGON_PRIVATE_KEY=real-secret-kept\n"
    (tmp_path / ".env").write_text(original)
    monkeypatch.chdir(tmp_path)
    response = TestClient(wa.app).post("/api/config", json=_config_payload())
    assert response.status_code == 200
    # The file is byte-identical: none of the 8 keys were ADDED.
    assert (tmp_path / ".env").read_text() == original


# ============================================================================
# /ws and broadcast_update
# ============================================================================


async def test_websocket_endpoint_sends_status_and_cleans_up_on_disconnect(
    monkeypatch, caplog
):
    """Fake socket drives /ws: initial status frame, stats_update frame, then a
    WebSocketDisconnect on the 2nd send cleans the socket up (app.py:476-478).

    L-0014: the real asyncio.sleep(5) is replaced on the wa namespace by an
    instant fake that only records its argument — no real wait, ever.
    """
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(wa, "asyncio", SimpleNamespace(sleep=fake_sleep))
    socket = FakeWebSocket(fail_on_send_index=2, fail_with=WebSocketDisconnect())
    # The disconnect log is INFO — raise the capture level for this logger so
    # the pin sees it (root level is WARNING by default under pytest).
    with caplog.at_level(logging.INFO, logger="polymarket_mcp.web.app"):
        await wa.websocket_endpoint(socket)
    assert socket.accepted == 1
    assert len(socket.sent) == 2
    # Initial frame: status with the module's connected state (globals clean).
    assert socket.sent[0]["type"] == "status"
    assert socket.sent[0]["data"]["connected"] is False
    # Second frame: the periodic stats_update.
    assert socket.sent[1]["type"] == "stats_update"
    # The loop's only real dependency: a 5-second cadence, never awaited real.
    assert sleeps == [5]
    # Disconnect path removed the socket and logged.
    assert socket not in wa.active_websockets
    assert wa.active_websockets == []
    assert any(
        "WebSocket client disconnected" in record.getMessage()
        for record in caplog.records
    )


async def test_websocket_endpoint_generic_error_removes_socket(monkeypatch, caplog):
    """Generic send failure: except Exception logs the error and removes the
    socket only if present (app.py:479-482)."""
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(wa, "asyncio", SimpleNamespace(sleep=fake_sleep))
    socket = FakeWebSocket(fail_on_send_index=2, fail_with=RuntimeError("exploded"))
    await wa.websocket_endpoint(socket)
    assert len(socket.sent) == 2
    assert sleeps == [5]
    assert socket not in wa.active_websockets
    assert wa.active_websockets == []
    messages = [record.getMessage() for record in caplog.records]
    assert any("WebSocket error: exploded" in message for message in messages)


async def test_websocket_generic_error_with_already_removed_socket(monkeypatch, caplog):
    """The `if websocket in active_websockets` guard (app.py:481-482): a socket
    that removed itself before the failure reaches the except is NOT re-removed
    (no ValueError) — the guard branch is exercised with the socket absent."""
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    class SelfRemovingSocket(FakeWebSocket):
        async def send_json(self, message: dict, mode: str = "text") -> None:
            self.sent.append(message)
            if len(self.sent) == 2:
                # Another actor (e.g. broadcast) removed the socket first.
                wa.active_websockets.remove(self)
                raise RuntimeError("exploded after removal")

    monkeypatch.setattr(wa, "asyncio", SimpleNamespace(sleep=fake_sleep))
    socket = SelfRemovingSocket()
    await wa.websocket_endpoint(socket)
    assert len(socket.sent) == 2
    assert sleeps == [5]
    assert wa.active_websockets == []
    messages = [record.getMessage() for record in caplog.records]
    assert any("WebSocket error: exploded after removal" in message
               for message in messages)


async def test_broadcast_update_removes_failed_sockets(caplog):
    """broadcast_update: good sockets receive the message; failed senders are
    removed from active_websockets (app.py:485-497)."""
    good = FakeWebSocket()
    bad = FakeWebSocket(fail_on_send_index=1, fail_with=RuntimeError("gone"))
    wa.active_websockets.extend([good, bad])
    await wa.broadcast_update({"type": "update", "payload": 1})
    assert good.sent == [{"type": "update", "payload": 1}]
    assert wa.active_websockets == [good]  # the failed sender was removed
    messages = [record.getMessage() for record in caplog.records]
    assert any("Failed to send to WebSocket: gone" in message for message in messages)


async def test_broadcast_update_with_no_sockets_is_noop():
    """Broadcast with an empty registry completes without touching anything."""
    await wa.broadcast_update({"type": "update"})
    assert wa.active_websockets == []


# ============================================================================
# start()
# ============================================================================


def test_start_defaults_to_loopback_without_warning_and_warns_on_non_loopback(
    monkeypatch, caplog, clean_env
):
    """start(): loopback defaults (127.0.0.1:8080) with NO warning; any
    non-loopback host emits the WARNING "not loopback"; WEB_HOST/WEB_PORT
    override the defaults. uvicorn.run is never executed (recorder seam)."""
    recorded: dict[str, Any] = {}

    def fake_run(app, host=None, port=None, **kwargs):
        recorded["app"] = app
        recorded["host"] = host
        recorded["port"] = port

    monkeypatch.setattr(wa, "uvicorn", SimpleNamespace(run=fake_run))
    logger_name = "polymarket_mcp.web.app"

    with caplog.at_level(logging.WARNING, logger=logger_name):
        wa.start()
    assert recorded["app"] is wa.app
    assert recorded["host"] == "127.0.0.1"
    assert recorded["port"] == 8080
    # No non-loopback warning on the loopback default.
    assert not any("not loopback" in record.getMessage() for record in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=logger_name):
        wa.start(host="0.0.0.0")
    assert recorded["host"] == "0.0.0.0"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("not loopback" in record.getMessage() for record in warnings)

    # Env overrides: WEB_HOST/WEB_PORT win when the explicit args are omitted.
    monkeypatch.setenv("WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("WEB_PORT", "9999")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=logger_name):
        wa.start()
    assert recorded["host"] == "0.0.0.0"
    assert recorded["port"] == 9999
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("not loopback" in record.getMessage() for record in warnings)

    # The loopback names are all exempt from the warning (pin the allowlist).
    for allowed in ("127.0.0.1", "localhost", "::1"):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=logger_name):
            wa.start(host=allowed)
        assert not any(
            "not loopback" in record.getMessage() for record in caplog.records
        )
