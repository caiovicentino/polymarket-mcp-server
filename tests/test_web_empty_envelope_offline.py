"""Offline regression suite for the EMPTY-RESULT paths of the Polymarket web
dashboard (coverage completion -- residual of T-0373/T-0299).

Contract T-0378 (curator, 2026-09-19): coverage of the full offline selection
on main c5cb6c7 leaves exactly one statement + two partial branches dead in
``web/app.py``:

  - ``/api/markets/closing-soon``: ``return JSONResponse({"markets": []})``
    -- the branch ``result and len(result) > 0`` has never been False. The
    T-0373 suite feeds the route a payload of ``[]`` (ONE TextContent whose
    text is "[]"), which takes the wrap branch; only a tool that returns an
    EMPTY TextContent LIST reaches the fallback envelope.
  - ``/api/test-connection``: ``if result:`` (envelope-error guard from
    T-0299) has never been False -- every existing pin feeds at least one
    TextContent (success or error envelope).

Both are OBSERVED behaviors: an empty tool result yields ``200 {"markets": []}``
on the closing-soon route and a still-successful connection report with
``markets_found: 0``. The suite pins them so a future change (e.g. surfacing
emptiness) must consciously flip the pins here. Zero network; fakes are
self-contained (FA-0079); hermeticity guard mirrors the sibling suites
(env-only config, no .env in the source tree -- L-0330).
"""

import pathlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from polymarket_mcp.web import app as wa

# Dummy wallet: the house-standard offline key (valid 64-hex format, zero value).
DUMMY_PRIVATE_KEY = "0" * 63 + "1"
DUMMY_ADDRESS = "0x" + "0" * 40

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _wallet_env(monkeypatch):
    """Env-only config; the suite must never depend on a .env file (L-0330)."""
    assert not (_REPO_ROOT / ".env").exists(), (
        "a .env file exists in the source tree -- the suite must never depend on it"
    )
    for key in (
        "POLYGON_PRIVATE_KEY",
        "POLYGON_ADDRESS",
        "POLYMARKET_API_KEY",
        "POLYMARKET_API_SECRET",
        "POLYMARKET_PASSPHRASE",
        "POLYMARKET_API_KEY_NAME",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", DUMMY_PRIVATE_KEY)
    monkeypatch.setenv("POLYGON_ADDRESS", DUMMY_ADDRESS)


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeToolModule:
    """Fail-loud fake on the market_discovery seam of web.app (house pattern).

    Unlike the sibling suites, ``results[name]`` is returned AS-IS: an empty
    LIST models a tool that produced ZERO TextContent objects (the branch
    never exercised by the existing pins)."""

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._results = results or {}

    async def handle_tool(self, name: str, arguments: dict) -> list[FakeMessage]:
        self.calls.append((name, dict(arguments)))
        if name not in self._results:
            raise AssertionError(f"unexpected tool call: {name!r}")
        result = self._results[name]
        if callable(result):
            return result(arguments)
        return result


@pytest.fixture()
def _stubbed_discovery(monkeypatch):
    """Install a fail-loud fake on the market_discovery seam of web.app."""
    holder: dict[str, FakeToolModule] = {}

    def install(results: dict[str, Any] | None = None) -> FakeToolModule:
        fake = FakeToolModule(results=results)
        monkeypatch.setattr(wa, "market_discovery", fake)
        holder["fake"] = fake
        return fake

    return install


# ---------------------------------------------------------------------------
# /api/markets/closing-soon: empty TextContent LIST -> fallback envelope
# ---------------------------------------------------------------------------


def test_closing_soon_empty_content_list_returns_empty_envelope(_stubbed_discovery):
    """A tool result that is an EMPTY list (zero TextContent) hits the
    ``result and len(result) > 0`` False branch: 200 {"markets": []}."""
    fake = _stubbed_discovery(results={"get_closing_soon_markets": []})
    with TestClient(wa.app) as client:
        resp = client.get("/api/markets/closing-soon")
    assert resp.status_code == 200
    assert resp.json() == {"markets": []}
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == "get_closing_soon_markets"


# ---------------------------------------------------------------------------
# /api/test-connection: empty TextContent LIST -> still success (branch False)
# ---------------------------------------------------------------------------


def test_test_connection_empty_tool_result_reports_success(_stubbed_discovery):
    """An empty tool result skips the T-0299 envelope guard (``if result:``
    False) and reports connection success with markets_found 0."""
    fake = _stubbed_discovery(results={"get_trending_markets": []})
    with TestClient(wa.app) as client:
        resp = client.get("/api/test-connection")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["markets_found"] == 0
    assert fake.calls and fake.calls[0][0] == "get_trending_markets"
