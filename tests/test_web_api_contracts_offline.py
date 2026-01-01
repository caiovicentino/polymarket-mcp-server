"""Contract suite for /api/test-connection envelope detection and the derived
tools_available count (T-0299, offline).

Context (curator probe, 2026-09-18, main b240bb9): handle_tool NEVER raises —
market_discovery.py:707-712 catches `except Exception` and returns the failure
as a TextContent envelope {"error": str(e)}. The /api/test-connection route
treated every returned result as success: with a broken network/API it replied
200 {"success": True, "message": "Connection successful", "markets_found": 1}
while BOTH dashboard buttons (index.html "Test Connection", config.html "Test
Configuration") displayed success on a TRADING dashboard. The route's `except`
branch was dead code for the real module (it only fires if handle_tool raises,
which it never does).

Fix under contract (byte-identical to sim/c66-preflight @ 556d38d):
(A) envelope detection inside /api/test-connection: parse result[0].text; a
    dict carrying an "error" key -> 500 {"success": False, "error": str(...)}
    (same shape as the surviving except branch) and stats["errors"] bumped.
    The REAL success shape of get_trending_markets is a JSON ARRAY (handle_tool
    does json.dumps(result) of a LIST) — isinstance(payload, dict) is
    mandatory: calling .get on an array would raise AttributeError.
(B) tools_available literals (45/25, app.py:154/:262) replaced by
    _derived_tools_available(has_credentials), mirroring server.get_tools():
    discovery + analysis + realtime always; trading + portfolio only with
    credentials. Live counts observed while writing this suite: 8 + 10 + 7 = 25
    without credentials; + 12 + 8 = 45 with. The derivation tests below pin the
    DERIVED INVARIANT from the live registries — never the literals (L-0023/
    L-0002 anti-drift); the only literal pin is the pre-existing sibling pin
    (test_web_app_offline.py:534, tools_available == 25, untouched).

Fake fidelity (contract rule): the fakes model the TWO REAL shapes of
market_discovery.handle_tool — success = JSON ARRAY of market dicts (the real
module json.dumps()s a LIST); failure = dict {"error": ...} envelope. The
{"markets": [...]} success shape used by the sibling suite's stub is UNFAITHFUL
to the real module (its own docstring says so) and is NEVER replicated here.

RED line: the markets_found quirk (len(result) counts MCP messages, not
markets) is PINNED as OBSERVED in tests/test_web_app_offline.py:578-601 and is
NOT changed by this slice (REQUER-HUMANO item 164).

Hermeticity (T-0220 class): the worktree root must have NO .env (mirror of the
sibling guard) — every test asserts the precondition; no test creates one. No
network: every tool seam is a fail-loud fake installed BEFORE any request.
"""
import json
import pathlib
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from polymarket_mcp.auth import create_polymarket_client
from polymarket_mcp.tools import market_analysis, market_discovery, portfolio_integration, realtime
from polymarket_mcp.tools.trading import get_tool_definitions
from polymarket_mcp.web import app as wa

# Dummy wallet: the house-standard offline key (valid 64-hex format, zero value).
DUMMY_PRIVATE_KEY = "0" * 63 + "1"
DUMMY_ADDRESS = "0x" + "0" * 40

# CWD at import time == the worktree root (pytest is invoked from there).
_WORKTREE_ROOT = pathlib.Path.cwd()

# Captured at import time, before any test runs: the pristine stats dict (the
# module never mutates it directly — handlers only see per-test copies).
_PRISTINE_STATS = dict(wa.stats)

# Real-shaped success payload: a JSON ARRAY of market dicts (the REAL shape of
# get_trending_markets — the module json.dumps()s the LIST it produced).
_REAL_SHAPED_MARKETS = [
    {"question": "Will X settle YES by December?", "volume24hr": 1000.0},
    {"question": "Will Y settle YES by December?", "volume24hr": 2000.0},
    {"question": "Will Z settle YES by December?", "volume24hr": 3000.0},
]


class FakeMessage:
    """Stand-in for the MCP TextContent objects the routes consume (.text only)."""

    def __init__(self, text: str) -> None:
        self.text = text


def text_payload(payload: Any) -> list[FakeMessage]:
    """Build the [TextContent-like] list a successful handle_tool returns."""
    return [FakeMessage(text=json.dumps(payload))]


class FakeToolModule:
    """Fail-loud module seam for wa.market_discovery (P-0031).

    handle_tool records every call and returns the canned result for the tool
    name; an unexpected tool name raises AssertionError so a regression cannot
    silently fall through to the real network-touching module (L-0118 — the
    stub is installed BEFORE any request reaches the route). Callable results
    receive the arguments (used by the stateful stats test to flip shapes
    between calls).
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


def _install_stubs(monkeypatch: pytest.MonkeyPatch, discovery: FakeToolModule):
    """Patch BOTH tool seams of web.app BEFORE any request (L-0118).

    The discovery seam gets the fake under test; the analysis seam gets an
    empty fail-loud module so a cross-module regression fails loudly instead of
    reaching the real network-touching module.
    """
    monkeypatch.setattr(wa, "market_discovery", discovery)
    monkeypatch.setattr(wa, "market_analysis", FakeToolModule())
    return discovery


def _make_client(api_creds: bool):
    """Real offline client factory; api_creds toggles has_api_credentials()."""
    if api_creds:
        return create_polymarket_client(
            private_key=DUMMY_PRIVATE_KEY,
            address=DUMMY_ADDRESS,
            api_key="dummy-key",
            api_secret="dummy-secret",
            passphrase="dummy-pass",
        )
    return create_polymarket_client(
        private_key=DUMMY_PRIVATE_KEY, address=DUMMY_ADDRESS
    )


@pytest.fixture(autouse=True)
def pristine_web_state():
    """Reset web.app module globals per test and restore the originals (L-0022).

    Handlers mutate wa.stats in place (the global is read directly), so each
    test starts from the pristine baseline with a per-test COPY of stats and
    teardown restores the original object identity — suite order-independent.
    Also asserts the hermeticity precondition (no .env in the worktree root).
    """
    assert not (_WORKTREE_ROOT / ".env").exists(), (
        "A .env file appeared in the worktree root — this suite requires a "
        "clean root (hermeticity guard mirroring test_web_app_offline.py:279; "
        "T-0220: a .env in the root turned 10 tests spurious-fail). "
        "Refusing to run: precondition violated."
    )
    wa.config = None
    wa.client = None
    wa.safety_limits = None
    wa.stats = dict(_PRISTINE_STATS)
    yield
    wa.config = None
    wa.client = None
    wa.safety_limits = None
    wa.stats = _PRISTINE_STATS


# ============================================================================
# (A) /api/test-connection — envelope detection
# ============================================================================


def test_test_connection_error_envelope_returns_500(monkeypatch):
    """The REAL failure shape ({"error": ...} TextContent) -> 500, not a
    200 "Connection successful" false positive.

    Same body shape as the surviving except branch (pinned OBSERVED by
    test_web_app_offline.py:617): {"success": False, "error": str(...)}.
    """
    fake = _install_stubs(monkeypatch, FakeToolModule(results={
        "get_trending_markets": text_payload({"error": "gamma unreachable"}),
    }))
    monkeypatch.setattr(wa, "client", _make_client(api_creds=False))
    response = TestClient(wa.app).get("/api/test-connection")
    assert response.status_code == 500
    assert response.json() == {"success": False, "error": "gamma unreachable"}
    # The exact tool call the route makes (fail-loud stub proves the seam).
    assert fake.calls == [("get_trending_markets", {"limit": 5})]


def test_test_connection_success_array_payload_unchanged(monkeypatch):
    """The REAL success shape (JSON ARRAY) still returns the 200 success body.

    isinstance(payload, dict) is load-bearing: an ARRAY payload must fall
    through to the success return — the response shape is UNCHANGED (RED line:
    the markets_found == 1 quirk (len(result), the message count) is pinned
    OBSERVED by test_web_app_offline.py:595 and NOT touched by this slice).
    """
    fake = _install_stubs(monkeypatch, FakeToolModule(results={
        "get_trending_markets": text_payload(_REAL_SHAPED_MARKETS),
    }))
    monkeypatch.setattr(wa, "client", _make_client(api_creds=False))
    response = TestClient(wa.app).get("/api/test-connection")
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Connection successful",
        # len(result) == 1: one MCP message carrying all three markets.
        "markets_found": 1,
    }
    assert fake.calls == [("get_trending_markets", {"limit": 5})]


def test_test_connection_direct_raise_preserved(monkeypatch):
    """The except branch survives: a direct raise keeps the 500 error body.

    Guards the fix from breaking the branch that covers raises (the envelope
    detection must ADD a path, not replace the except handling).
    """
    fake = _install_stubs(monkeypatch, FakeToolModule(
        error=RuntimeError("gamma unreachable")
    ))
    monkeypatch.setattr(wa, "client", _make_client(api_creds=False))
    response = TestClient(wa.app, raise_server_exceptions=False).get(
        "/api/test-connection"
    )
    assert response.status_code == 500
    assert response.json() == {"success": False, "error": "gamma unreachable"}
    assert fake.calls == [("get_trending_markets", {"limit": 5})]


def test_test_connection_stats_errors_bumped_on_envelope(monkeypatch):
    """stats["errors"] bumps on the envelope path and NOT on the success path.

    Stateful fake (callable result): call 1 answers the failure envelope,
    call 2 answers the real-shaped success array — the bump happens exactly
    once, on the envelope call.
    """
    shapes = iter([
        text_payload({"error": "gamma unreachable"}),
        text_payload(_REAL_SHAPED_MARKETS),
    ])
    fake = _install_stubs(monkeypatch, FakeToolModule(results={
        "get_trending_markets": lambda arguments: next(shapes),
    }))
    monkeypatch.setattr(wa, "client", _make_client(api_creds=False))
    first = TestClient(wa.app).get("/api/test-connection")
    assert first.status_code == 500
    assert wa.stats["errors"] == 1
    second = TestClient(wa.app).get("/api/test-connection")
    assert second.status_code == 200
    # The success path leaves the counter alone (contrast: sibling pin :599).
    assert wa.stats["errors"] == 1
    assert fake.calls == [
        ("get_trending_markets", {"limit": 5}),
        ("get_trending_markets", {"limit": 5}),
    ]


# ============================================================================
# (B) tools_available — derived from the live registries (anti-drift)
# ============================================================================


def test_derived_tools_available_read_only_excludes_trading_portfolio():
    """Read-only total == the live always-on registries (no trading/portfolio).

    Anti-drift (L-0023/L-0002): the count is asserted against the LIVE
    registries, never a 45/25 literal. If the helper ever started counting
    credentials-only tools into the read-only total, this equality fails.
    """
    base = wa._derived_tools_available(False)
    assert base == (
        len(market_discovery.get_tools())
        + len(market_analysis.get_tools())
        + len(realtime.get_tools())
    )
    # Pure function of the registries: stable across calls.
    assert wa._derived_tools_available(False) == base


def test_derived_tools_available_full_includes_trading_portfolio():
    """Full total == read-only + live trading + live portfolio (derived
    invariant — the ONLY safe pin without literals, L-0023/L-0002).

    Mirrors server.get_tools(): with credentials, trading + portfolio tool
    definitions are added on top of the always-on registries.
    """
    base = wa._derived_tools_available(False)
    full = wa._derived_tools_available(True)
    assert base + len(get_tool_definitions()) + len(
        portfolio_integration.get_portfolio_tool_definitions()
    ) == full
    # Credentials strictly add tools (never subtract).
    assert full > base


def test_status_route_uses_derived_count(monkeypatch):
    """GET /api/status reports the DERIVED count (not the 45/25 literals).

    Both modes exercised against the live derivation: read-only client ->
    _derived_tools_available(False); credentials-bearing client ->
    _derived_tools_available(True). config is a SimpleNamespace (the route
    reads only POLYGON_ADDRESS/POLYMARKET_CHAIN_ID from it — no env needed).
    """
    monkeypatch.setattr(wa, "config", SimpleNamespace(
        POLYGON_ADDRESS=DUMMY_ADDRESS, POLYMARKET_CHAIN_ID=137,
    ))
    monkeypatch.setattr(wa, "client", _make_client(api_creds=False))
    read_only = TestClient(wa.app).get("/api/status").json()
    assert read_only["tools_available"] == wa._derived_tools_available(False)
    assert read_only["connected"] is True
    assert read_only["mode"] == "READ-ONLY"

    monkeypatch.setattr(wa, "client", _make_client(api_creds=True))
    full = TestClient(wa.app).get("/api/status").json()
    assert full["tools_available"] == wa._derived_tools_available(True)
    assert full["mode"] == "FULL"
