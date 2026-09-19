"""Data-API pagination contract + fix suite (V-PAG).

The Polymarket Data API (data-api.polymarket.com) pages list endpoints
(positions/trades/activity) with ``limit`` + ``offset``:

- no limit -> default page of 100 rows (proven live 2026-09-18: 7/8 sampled
  wallets returned exactly 100);
- limit=N -> N rows per call, CAPPED at 500 per call (proven live:
  limit=1000 and limit=2000 both return 500; a wallet was measured with
  2,022 positions total via offsets).

Consequence: the code fetches a SINGLE page everywhere
(auth/client.py get_positions; portfolio.py get_all_positions,
get_position_details-positions, get_portfolio_value, get_pnl_summary-trades
(limit=500) and -positions, analyze_portfolio_risk) -- everything beyond
the first page is INVISIBLE: portfolio valuation and P&L are computed over
a TRUNCATED book for active wallets (P2, money-adjacent display).

Fix: ``utils/data_api_pagination.fetch_all_pages`` keeps the FIRST request
byte-identical to the pre-fix call (existing call-shape pins hold) and
fetches follow-up pages ONLY when the first page is full. Sites with
user-capped semantics (get_position_details trades limit=10,
get_trade_history limit=min(limit,500), get_activity_log
limit=min(limit,500)) are OUT OF SCOPE: the limit is the user's cap, not a
page size.

Guards exercised here: short page = no follow-up call; exactly-cap
boundary fetches one more (empty) page; an offset-ignoring server/stub
terminates via the no-progress guard; MAX_PAGES caps runaway fakes.

Prerequisites: pytest-asyncio auto mode; no integration/real_api markers
on the offline tests -- runs under the canonical gate selection
`-m "not integration and not slow and not real_api and not performance"`;
PYTHONPATH=src per P-0019; read_text-free suite (L-0252).
Lessons: L-0020/L-0090 (asserts pin the observed behavior), L-0261
(hermeticity: zero network -- fakes fail loud on unrouted URLs).
"""
import sys

import httpx
import pytest

sys.path.insert(0, "src")

from polymarket_mcp.auth.client import PolymarketClient  # noqa: E402
from polymarket_mcp.tools import portfolio  # noqa: E402

KEY = "a" * 64
ADDRESS = "0x" + "1" * 40
POSITIONS_URL = "https://data-api.polymarket.com/positions"
TRADES_URL = "https://data-api.polymarket.com/trades"


def make_position(seq, size=3.0, avg_price=0.4):
    """Position payload in the OFFLINE fixture shape the tools parse."""
    return {
        "size": size,
        "average_price": avg_price,
        "asset_id": f"token-{seq}",
        "market": f"0xmarket-{seq}",
        "market_question": f"Question {seq}",
        "outcome": "YES",
    }


def make_trade(seq, side, price, size=1.0, ts=1):
    """Trade payload in the OFFLINE fixture shape get_pnl_summary parses."""
    return {
        "market": "0xmarket-1",
        "outcome": "YES",
        "side": side,
        "price": price,
        "size": size,
        "timestamp": ts,
        "fee": 0.0,
        "id": f"trade-{seq}",
        "market_question": "Trade question",
    }


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeAsyncClient:
    """Offset-aware Data API stub for portfolio.py (class-state seam)."""

    calls = []
    pages = {}  # url -> full row list; served in 100-row offset windows

    def __init__(self, timeout=30.0):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, timeout=None):
        params = dict(params or {})
        type(self).calls.append((url, params))
        if url not in type(self).pages:
            raise AssertionError(f"unexpected URL routed to stub: {url}")
        offset = int(params.get("offset", 0))
        limit = int(params.get("limit", 100))
        return FakeResponse(list(type(self).pages[url][offset:offset + limit]))


class FakeRateLimiter:
    def __init__(self):
        self.categories = []

    async def acquire(self, category):
        self.categories.append(category)
        return 0.0


class FakeConfig:
    POLYGON_ADDRESS = ADDRESS


@pytest.fixture(autouse=True)
def _isolate():
    """Isolation: clear the module-global portfolio cache before AND after
    every test (a global cache would otherwise leak between tests) and
    reset the class-state stub."""
    portfolio._portfolio_cache.clear()
    FakeAsyncClient.calls = []
    FakeAsyncClient.pages = {}
    yield
    portfolio._portfolio_cache.clear()


def positions_calls():
    return [c for c in FakeAsyncClient.calls if c[0] == POSITIONS_URL]


def trades_calls():
    return [c for c in FakeAsyncClient.calls if c[0] == TRADES_URL]


# --- client.get_positions (auth/client.py) ----------------------------------


def _client_with_pages(page1, page2, page3):
    """PolymarketClient whose /positions GETs serve offset-aware pages."""
    pmc = PolymarketClient(
        private_key=KEY,
        address=ADDRESS,
        api_key="k",
        api_secret="s",
        passphrase="p",
    )

    def handler(request):
        params = dict(request.url.params)
        offset = int(params.get("offset", 0))
        if offset == 0:
            return httpx.Response(200, json=page1)
        if offset == 100:
            return httpx.Response(200, json=page2)
        if offset == 200:
            return httpx.Response(200, json=page3)
        return httpx.Response(200, json=[])

    return pmc, handler


async def test_client_get_positions_collects_all_offset_pages(monkeypatch):
    """100 + 100 + 22 pages -> ALL 222 positions (was: first 100 only)."""
    page1 = [make_position(i) for i in range(100)]
    page2 = [make_position(100 + i) for i in range(100)]
    page3 = [make_position(200 + i) for i in range(22)]
    pmc, handler = _client_with_pages(page1, page2, page3)

    real_async_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    positions = await pmc.get_positions()

    assert len(positions) == 222
    assert {p["asset_id"] for p in positions} == {f"token-{i}" for i in range(222)}


# --- portfolio.get_all_positions (portfolio.py get_all_positions) -----------


async def test_portfolio_get_all_positions_collects_all_pages(monkeypatch):
    """Page 1 (100 rows) + page 2 (75 rows) -> 175 positions; the text must
    include a marker position that ONLY exists on page 2."""
    page1 = [make_position(i) for i in range(100)]
    page2 = [make_position(100 + i) for i in range(75)]
    FakeAsyncClient.pages = {POSITIONS_URL: page1 + page2}
    monkeypatch.setattr(portfolio.httpx, "AsyncClient", FakeAsyncClient)

    texts = await portfolio.get_all_positions(None, FakeRateLimiter(), FakeConfig())

    text = "".join(t.text for t in texts)
    assert "Question 174" in text  # exists ONLY on page 2
    assert "Question 99" in text   # page 1 marker


async def test_short_first_page_makes_no_followup_call(monkeypatch):
    """A first page shorter than the cap is complete: exactly ONE call, with
    byte-identical params (the existing call-shape pins keep holding)."""
    FakeAsyncClient.pages = {POSITIONS_URL: [make_position(i) for i in range(37)]}
    monkeypatch.setattr(portfolio.httpx, "AsyncClient", FakeAsyncClient)

    await portfolio.get_all_positions(None, FakeRateLimiter(), FakeConfig())

    assert len(positions_calls()) == 1
    assert positions_calls()[0][1] == {"user": ADDRESS.lower()}


async def test_exactly_cap_boundary_fetches_one_more_page(monkeypatch):
    """Exactly 100 rows -> one follow-up (empty) call; the total stays 100."""
    FakeAsyncClient.pages = {POSITIONS_URL: [make_position(i) for i in range(100)]}
    monkeypatch.setattr(portfolio.httpx, "AsyncClient", FakeAsyncClient)

    await portfolio.get_all_positions(None, FakeRateLimiter(), FakeConfig())

    assert len(positions_calls()) == 2
    assert positions_calls()[1][1]["offset"] == 100
    assert positions_calls()[1][1]["limit"] == 100


async def test_offset_ignoring_server_terminates(monkeypatch):
    """A server that ignores the offset: the no-progress guard stops the
    loop (same first row) -- no hang, no duplicated rows."""
    FakeAsyncClient.pages = {POSITIONS_URL: [make_position(i) for i in range(100)]}
    monkeypatch.setattr(portfolio.httpx, "AsyncClient", FakeAsyncClient)

    async def offset_blind_get(self, url, params=None, timeout=None):
        params = dict(params or {})
        type(self).calls.append((url, params))
        if url not in type(self).pages:
            raise AssertionError(f"unexpected URL routed to stub: {url}")
        # Offset ignored: the FULL list comes back every time.
        return FakeResponse(list(type(self).pages[url]))

    monkeypatch.setattr(FakeAsyncClient, "get", offset_blind_get)

    texts = await portfolio.get_all_positions(None, FakeRateLimiter(), FakeConfig())

    assert len(positions_calls()) == 2  # one follow-up, then the guard stops
    text = "".join(t.text for t in texts)
    assert text.count("Question 0") <= 1  # no duplicated rows in the output


async def test_max_pages_caps_runaway_fakes(monkeypatch):
    """An offset-aware fake that serves a FULL page forever: MAX_PAGES caps
    the loop (51 calls) instead of hanging."""
    FakeAsyncClient.pages = {POSITIONS_URL: [make_position(i) for i in range(100)]}

    async def runaway_get(self, url, params=None, timeout=None):
        params = dict(params or {})
        type(self).calls.append((url, params))
        if url not in type(self).pages:
            raise AssertionError(f"unexpected URL routed to stub: {url}")
        offset = int(params.get("offset", 0))
        # DISTINCT rows every call: offset-aware, never short.
        return FakeResponse([make_position(offset + i) for i in range(100)])

    monkeypatch.setattr(FakeAsyncClient, "get", runaway_get)
    monkeypatch.setattr(portfolio.httpx, "AsyncClient", FakeAsyncClient)

    await portfolio.get_all_positions(None, FakeRateLimiter(), FakeConfig())

    assert len(positions_calls()) == 51  # 1 first call + 50 follow-ups


# --- portfolio.get_pnl_summary (trades, limit=500) --------------------------


async def test_pnl_summary_trades_beyond_500_count(monkeypatch):
    """500 BUY trades (page 1) + 120 SELLs (page 2): FIFO realized P&L must
    cover ALL pages (was: only the first 500 -> no sells -> $+0.00)."""
    buys = [make_trade(i, "BUY", 0.40, 1.0, ts=i + 1) for i in range(500)]
    sells = [make_trade(500 + i, "SELL", 0.60, 1.0, ts=1000 + i) for i in range(120)]
    FakeAsyncClient.pages = {
        TRADES_URL: buys + sells,
        POSITIONS_URL: [],
    }
    monkeypatch.setattr(portfolio.httpx, "AsyncClient", FakeAsyncClient)

    texts = await portfolio.get_pnl_summary(None, FakeRateLimiter(), FakeConfig())

    text = "".join(t.text for t in texts)
    assert "Realized P&L: $+24.00" in text   # (0.60-0.40)*120 across pages
    assert "Closed Trades: 120" in text
    assert len(trades_calls()) == 2
    assert trades_calls()[0][1]["limit"] == 500          # first call unchanged
    assert trades_calls()[1][1]["limit"] == 500
    assert trades_calls()[1][1]["offset"] == 500


# --- live integration (deselected offline) -----------------------------------


@pytest.mark.integration
@pytest.mark.real_api
async def test_live_positions_offset_paging():
    """Live: the Data API honors offset -- rows differ between offset=0 and
    offset=2 (the address is derived from the live /trades feed, NEVER
    hardcoded)."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        recent = await client.get(
            "https://data-api.polymarket.com/trades", params={"limit": 5}
        )
        recent.raise_for_status()
        addr = recent.json()[0]["proxyWallet"]

        first = await client.get(
            "https://data-api.polymarket.com/positions", params={"user": addr, "limit": 2}
        )
        first.raise_for_status()
        page_a = first.json()

        second = await client.get(
            "https://data-api.polymarket.com/positions",
            params={"user": addr, "limit": 2, "offset": 2},
        )
        second.raise_for_status()
        page_b = second.json()

    if not page_a or not page_b:
        pytest.skip("wallet has fewer positions than the sampled window")
    assert page_a[0]["asset"] != page_b[0]["asset"]
