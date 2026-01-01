"""Envelope-blindness fix (item 169, farm/T-0440): the 5 dashboard data routes
(/api/markets/trending, /api/markets/search, /api/markets/closing-soon,
/api/markets/{market_id}, /api/markets/{market_id}/analyze) propagate tool
error envelopes as 500 {"detail": ...} instead of returning them with 200.

Design derivation (1st hand, 2026-09-20): handle_tool's contract is "never
raises; failures arrive as an {"error": ...} envelope" (app.py test-connection
comment -- that route was fixed by T-0299 and is pinned 500 by
test_web_api_contracts_offline.py). The dashboard frontend consumes 500 detail
both generically (app.js apiRequest: ``error.detail``) and per-panel
(markets.html/index.html: ``errorBody.detail || errorBody.message``). Every
route's except branch already returns ``{"detail": str(e)}`` with 500 (pinned
by test_web_app_offline.py) -- the envelope path now returns the SAME body
shape, so each route has ONE error shape regardless of where the failure
originated. stats["errors"] increments (same as the except branch and the
T-0299 test-connection precedent).

The closing-soon pass-through pin (T-0373 stub-compat) was flipped in
tests/test_web_dashboard_wiring_offline.py in the same slice (superseding
design: the T-0373 flip documents the frontend surfacing; the backend now
matches).

RED pre-fix: each test below expected 500 {"detail": ...} while the routes
returned 200 with the raw envelope.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import importlib  # noqa: E402

wa = importlib.import_module("polymarket_mcp.web.app")  # noqa: E402


def _payload(obj):
    return {"type": "text", "text": json.dumps(obj)}


class FakeToolModule:
    """Fail-loud stub: records calls, returns canned text payloads."""

    def __init__(self, results):
        self.results = results
        self.calls = []

    async def handle_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        payload = self.results.get(name)
        from mcp import types
        return [types.TextContent(type="text", text=json.dumps(payload))]


@pytest.fixture
def stub(monkeypatch):
    def _install(module_attr, tool_module):
        monkeypatch.setattr(wa, module_attr, tool_module)
        return tool_module
    return _install


def _client():
    from starlette.testclient import TestClient
    return TestClient(wa.app)


def test_trending_route_envelope_becomes_500(stub):
    stub("market_discovery", FakeToolModule({
        "get_trending_markets": {"error": "gamma unreachable"},
    }))
    resp = _client().get("/api/markets/trending")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "gamma unreachable"}
    assert wa.stats["errors"] >= 1


def test_search_route_envelope_becomes_500(stub):
    stub("market_discovery", FakeToolModule({
        "search_markets": {"error": "search wire down"},
    }))
    resp = _client().get("/api/markets/search?q=bitcoin")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "search wire down"}


def test_closing_soon_route_envelope_becomes_500(stub):
    stub("market_discovery", FakeToolModule({
        "get_closing_soon_markets": {"error": "gamma unreachable"},
    }))
    resp = _client().get("/api/markets/closing-soon")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "gamma unreachable"}


def test_market_details_route_envelope_becomes_500(stub):
    stub("market_analysis", FakeToolModule({
        "get_market_details": {"error": "market lookup failed"},
    }))
    resp = _client().get("/api/markets/559651")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "market lookup failed"}


def test_analyze_route_envelope_becomes_500(stub):
    stub("market_analysis", FakeToolModule({
        "analyze_market_opportunity": {"error": "analysis failed"},
    }))
    resp = _client().get("/api/markets/559651/analyze")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "analysis failed"}


def test_success_arrays_still_wrapped(stub):
    """Anti-over-fix: the happy path is unchanged (arrays wrap as
    {"markets": [...]}; the T-0307/T-0373 contracts survive)."""
    stub("market_discovery", FakeToolModule({
        "get_trending_markets": [{"question": "BTC by Friday?"}],
    }))
    resp = _client().get("/api/markets/trending")
    assert resp.status_code == 200
    assert resp.json() == {"markets": [{"question": "BTC by Friday?"}]}
