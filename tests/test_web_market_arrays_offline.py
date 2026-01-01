"""
Offline regression suite pinning the ARRAY-envelope contract of the web
dashboard's market LIST routes (src/polymarket_mcp/web/app.py).

T-0307 — the tools behind /api/markets/trending and /api/markets/search return
a BARE JSON ARRAY in result[0].text on the real wire (proven live:
handle_tool("get_trending_markets", {"limit": 3}) parses to a list of 3; idem
search_markets — market_discovery.handle_tool json.dumps the List[Dict] return
of the tool functions, market_discovery.py:690-706). The dashboard frontend
consumes data.markets (index.html loadTrendingMarkets; markets.html
searchMarkets/loadTrendingMarkets), so a bare array renders those panels dead
by construction ("No trending markets available" even with a healthy API).
The fix wraps arrays into {"markets": [...]} at the route layer (parse-then-
wrap); dict payloads pass through unchanged.

Stub-compat is part of the contract: the sibling suite test_web_app_offline.py
stubs these routes with the LEGACY DICT shape text_payload({"markets": [...]})
(a shape the real tool never returns). The wrap must be an identity operation
for dicts — this suite pins the passthrough with EXACT payload equality so a
double-wrap ("{"markets": {"markets": [...]}}") or a key normalization can
never slip in. The details/analyze routes return DICTS on the wire
(get_market_details -> dict; analyze_market_opportunity -> model_dump) and are
already correct: their NO-WRAP passthrough is pinned here as the
anti-over-fix guard (the wrap must NOT leak into the dict routes).

Zero network by construction (P-0031/L-0118/L-0138): EVERY test installs
fail-loud module stubs on BOTH tool seams BEFORE any request. The route under
test gets the fake with the canned payload; the sibling seam gets an empty
fail-loud module — an unexpected tool name raises AssertionError, so a
regression cannot silently fall through to the real network-touching module.
(The house rule learned live in T-0050: a stub on only one seam let a request
reach gamma-api.)

Hermeticity (L-0022 house pattern): web.app globals are MODULE state — the
autouse fixture `pristine_web_state` resets config/client/safety_limits/
active_websockets and installs a per-test COPY of the stats dict, restoring
the originals on teardown (order-independent). load_config() reads
env_file=".env" relative to CWD, so the suite asserts as a hard precondition
that the worktree root has NO .env file (fail loud — P-0026 anti-vacuo style;
these routes never load config, the guard defends the whole-worktree state).

Fixtures mirror the REAL wire shape (L-0060): gamma market dicts with the
fields the API actually emits (id, question, volume24hr, liquidity, bestBid,
bestAsk, conditionId, outcomePrices) — NEVER the snake_case keys that do not
exist on the wire.

Prerequisites: fastapi 0.141.1 + httpx 0.28.1 in the clone venv; no
integration/slow/real_api/performance markers — runs clean under the release
gate filter `-m "not integration and not slow and not real_api and not
performance"`.
"""
import json
import pathlib
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from polymarket_mcp.web import app as wa

# CWD at import time == the worktree root (pytest is invoked from there). The
# hermeticity guard asserts this directory never gains a .env file.
_WORKTREE_ROOT = pathlib.Path.cwd()

# Real gamma wire shape for one market (fields as emitted by the gamma API and
# passed through by market_discovery tools verbatim — L-0060).
GAMMA_MARKET: dict = {
    "id": "12345",
    "question": "Will BTC close above $100k on Sep 30, 2026?",
    "volume24hr": 150000.0,
    "liquidity": 25000.0,
    "bestBid": 0.55,
    "bestAsk": 0.58,
    "conditionId": "0x" + "c" * 64,
    "outcomePrices": '["0.55", "0.45"]',
}

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
    silently fall through to the real network-touching module (L-0118 — the
    stub must exist BEFORE any request reaches these routes).
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


def _assert_no_env_in_worktree() -> None:
    """Fail loud if a .env appeared in the worktree root (hermeticity guard).

    These routes never load config, but the house invariant holds for the
    whole worktree: load_config() would read env_file=".env" relative to CWD.
    A .env here would invalidate the env-only isolation every web suite
    depends on — refuse to run.
    """
    assert not (_WORKTREE_ROOT / ".env").exists(), (
        "A .env file appeared in the worktree root — the web suites require a "
        "clean root (env-only config). Refusing to run: hermeticity "
        "precondition violated."
    )


def _install_stubs(
    monkeypatch: pytest.MonkeyPatch,
    discovery: Optional[FakeToolModule] = None,
    analysis: Optional[FakeToolModule] = None,
) -> tuple[FakeToolModule, FakeToolModule]:
    """Patch BOTH tool seams of web.app BEFORE any request (L-0118).

    Each route's seam gets the fake with canned results; the OTHER seam gets
    an empty fail-loud module (unexpected tool -> AssertionError) so a
    regression that swaps the seams — or adds a cross-module call — fails the
    test loudly instead of reaching the real network-touching module.
    """
    if discovery is None:
        discovery = FakeToolModule()
    if analysis is None:
        analysis = FakeToolModule()
    monkeypatch.setattr(wa, "market_discovery", discovery)
    monkeypatch.setattr(wa, "market_analysis", analysis)
    return discovery, analysis


@pytest.fixture(autouse=True)
def pristine_web_state():
    """Reset web.app module globals per test and restore the originals (L-0022).

    Handlers mutate wa.stats in place (bypassing monkeypatch); each test
    starts from the pristine baseline (captured at import) with a per-test
    COPY of stats, and teardown restores the original objects, making the
    suite order-independent.
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


# ============================================================================
# /api/markets/trending and /api/markets/search — the wrap contract
# ============================================================================


def test_trending_real_list_shape_wrapped(monkeypatch):
    """Real wire shape (bare array): 200 {"markets": [array]} — the fix.

    The real tool returns a bare List[Dict] (market_discovery.py:690-706
    json.dumps the list). RED before the fix: the route returned the bare
    array and the frontend's data.markets lookup was undefined — the panel
    rendered "No trending markets available" with a healthy API.
    """
    _assert_no_env_in_worktree()
    payload = [dict(GAMMA_MARKET), dict(GAMMA_MARKET, id="67890")]
    fake, _ = _install_stubs(monkeypatch, discovery=FakeToolModule(results={
        "get_trending_markets": text_payload(payload),
    }))
    response = TestClient(wa.app).get("/api/markets/trending?limit=3")
    assert response.status_code == 200
    assert response.json() == {"markets": payload}
    assert fake.calls == [("get_trending_markets", {"limit": 3})]
    assert wa.stats["markets_viewed"] == 1


def test_search_real_list_shape_wrapped(monkeypatch):
    """Same wrap contract on /api/markets/search; q/limit forwarded verbatim."""
    _assert_no_env_in_worktree()
    payload = [dict(GAMMA_MARKET, id="42", question="Search hit?")]
    fake, _ = _install_stubs(monkeypatch, discovery=FakeToolModule(results={
        "search_markets": text_payload(payload),
    }))
    response = TestClient(wa.app).get("/api/markets/search?q=bitcoin&limit=7")
    assert response.status_code == 200
    assert response.json() == {"markets": payload}
    assert fake.calls == [("search_markets", {"query": "bitcoin", "limit": 7})]
    assert wa.stats["markets_viewed"] == 1


def test_empty_array_result_still_returns_empty_markets(monkeypatch):
    """text "[]" parses to an empty list and STILL wraps: 200 {"markets": []}.

    Distinct path from the no-TextContent fallback (result == [] short-
    circuits into the pre-existing `return JSONResponse({"markets": []})`
    branch): here the tool DID return a TextContent, the parse succeeds, and
    the wrap must still produce the frontend-consumable envelope. RED before
    the fix: this path returned the bare [] — another way the panel showed
    "No trending markets available" by construction.
    """
    _assert_no_env_in_worktree()
    fake, _ = _install_stubs(monkeypatch, discovery=FakeToolModule(results={
        "get_trending_markets": text_payload([]),
    }))
    response = TestClient(wa.app).get("/api/markets/trending")
    assert response.status_code == 200
    assert response.json() == {"markets": []}
    assert fake.calls == [("get_trending_markets", {"limit": 10})]  # default limit
    assert wa.stats["markets_viewed"] == 1


def test_dict_payload_passthrough_unchanged(monkeypatch):
    """Legacy stub shape {"markets": [...]}: passed through EXACTLY, no double wrap.

    Stub-compat with the sibling suite test_web_app_offline.py, whose route
    tests stub text_payload({"markets": [...]}) — a shape the real tool never
    returns. The wrap must be an identity operation for dicts: the response
    body equals the payload EXACTLY (a double wrap would produce
    {"markets": {"markets": [...]}} and fail this pin on BOTH pre and post
    states).
    """
    _assert_no_env_in_worktree()
    payload = {"markets": [{"question": "Will X happen?", "volume": 1234.5}]}
    fake, _ = _install_stubs(monkeypatch, discovery=FakeToolModule(results={
        "get_trending_markets": text_payload(payload),
        "search_markets": text_payload(payload),
    }))
    trending = TestClient(wa.app).get("/api/markets/trending")
    assert trending.status_code == 200
    assert trending.json() == payload
    search = TestClient(wa.app).get("/api/markets/search?q=bitcoin")
    assert search.status_code == 200
    assert search.json() == payload
    assert fake.calls == [
        ("get_trending_markets", {"limit": 10}),
        ("search_markets", {"query": "bitcoin", "limit": 20}),
    ]
    assert wa.stats["markets_viewed"] == 2


# ============================================================================
# /api/markets/{market_id} and /api/markets/{market_id}/analyze — NO-WRAP guard
# ============================================================================


def test_details_route_dict_passthrough_unchanged(monkeypatch):
    """get_market_details returns a DICT on the wire: NO wrap on this route.

    Anti-over-fix guard: the array-wrap must not leak into the dict routes.
    get_market_details already returns a single dict (the tool extracts
    data[0]); the response must equal the payload exactly — a wrap here would
    produce {"markets": {...}} and break the market-detail panel.
    """
    _assert_no_env_in_worktree()
    payload = {
        "id": "12345",
        "question": "Details market?",
        "conditionId": GAMMA_MARKET["conditionId"],
        "description": "Resolved description",
    }
    _, fake = _install_stubs(monkeypatch, analysis=FakeToolModule(results={
        "get_market_details": text_payload(payload),
    }))
    response = TestClient(wa.app).get("/api/markets/0xabc")
    assert response.status_code == 200
    assert response.json() == payload
    assert fake.calls == [("get_market_details", {"market_id": "0xabc"})]
    # Pinned OBSERVED: details/analyze do NOT bump markets_viewed (only
    # trending/search do — app.py:301/327).
    assert wa.stats["markets_viewed"] == 0


def test_analyze_route_dict_passthrough_unchanged(monkeypatch):
    """analyze_market_opportunity returns a model_dump DICT: NO wrap either."""
    _assert_no_env_in_worktree()
    payload = {
        "market_id": "0xdead",
        "recommendation": "BUY",
        "confidence": 0.72,
        "reasoning": "Spread within tolerance",
    }
    _, fake = _install_stubs(monkeypatch, analysis=FakeToolModule(results={
        "analyze_market_opportunity": text_payload(payload),
    }))
    response = TestClient(wa.app).get("/api/markets/0xdead/analyze")
    assert response.status_code == 200
    assert response.json() == payload
    assert fake.calls == [("analyze_market_opportunity", {"market_id": "0xdead"})]
    assert wa.stats["markets_viewed"] == 0
