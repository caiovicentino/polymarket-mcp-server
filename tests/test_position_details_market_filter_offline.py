"""Client-side market filter in get_position_details (offline).

T-0452: the Data API wire DROPS the ``market`` filter for PADDED condition
ids (sports/GAMES form -- long hex tail of zeros; probe 2026-09-20: a
padded cid returned 200 with rows whose conditionId were ALL different
from the requested one, on BOTH /positions and /trades). The tool then
presents another market's position/trades under the requested market's
header -- silent data corruption (P1). This suite pins the honest
client-side defense: rows are kept only when they carry the requested
market id, either as ``conditionId`` (camelCase, the wire truth) or as
``market`` (snake_case fallback, the legacy fixture shape of the sister
suites).

Fakes are self-contained (set_api_routes-style, house P-0031): the
transport serves canned rows INDEPENDENT of the request params -- it
mirrors the wire drop without any network. RED-pre (4 failed / 2 passed)
was re-proved first-hand at the fork-point; the 4 REDs fail ON THE BODY
asserts (L-0417), never in setup, and the oracle knows to fail against
the specific bug (L-0065).

Pins that survive (compat with sisters, provada no claim):
- tests/test_portfolio_positions_offline.py -- make_position(..., market,
  ...) uses the ``market`` key == the requested market_id: the fallback
  keeps every row; the filter precedes the [:5] slice and the empty path.
- tests/test_data_api_passthrough_offline.py :185 -- fetch_all_pages runs
  BEFORE the filter; the recorder keeps its kwargs pin.
- tests/test_portfolio_tools.py -- trade rows carrying NEITHER key are
  dropped (honest): rendering falls to "No recent trades"; the header
  assert survives by construction.

Isolation: autouse fixture clears the module-global _portfolio_cache
before AND after every test (house rule of the sister suite); zero
network (fakes fail loud on unrouted seams); zero sleep; pytest-asyncio
auto mode; PYTHONPATH=src per P-0019; ASCII-only file (L-0414).
Lessons: P-0031 (fail-loud fakes), P-0130/P-0226 (fake models the bug),
L-0417 (RED in bodies), L-0056 (negatives paired with positives).
"""
import sys
from typing import Any, Dict, List

import httpx
import pytest

sys.path.insert(0, "src")

from polymarket_mcp.tools import portfolio  # noqa: E402

ADDRESS = "0xAbCdEf0123456789AbCdEf0123456789aBcDeF01"
POSITIONS_URL = "https://data-api.polymarket.com/positions"
TRADES_URL = "https://data-api.polymarket.com/trades"

# The padded cid from the wire probe: a sports/GAMES-form condition id
# (long hex with a run of trailing zeros). The wire DROPS the market
# filter for this shape -- exactly the corruption this suite defends.
PADDED_CID = "0x0000000000000000000000000000000000000000000000000000000000000001"
FOREIGN = "mkt_other"
BASE_TS = 1700000000


class FakeResponse:
    """House-shaped response stub (raise_for_status/json)."""

    def __init__(self, payload=None, error=None):
        self.status_code = 200
        self.headers = {}
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        if self._error is not None:
            raise self._error
        return self._payload


class FakeAsyncClient:
    """Transport stub routed by exact URL. Serves canned rows INDEPENDENT
    of the request params -- mirrors the wire drop for padded cids without
    any network (the caller's params are recorded, never honored)."""

    calls: List[Dict[str, Any]] = []
    responses: Dict[str, Any] = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, timeout=None):
        type(self).calls.append({"url": url, "params": dict(params or {})})
        if url not in type(self).responses:
            raise AssertionError(f"unexpected URL routed to stub: {url}")
        value = type(self).responses[url]
        return value if isinstance(value, FakeResponse) else FakeResponse(value)


class FakePolymarketClient:
    """Duck-typed client stub: only get_orderbook is exercised here."""

    def __init__(self, orderbooks=None):
        self._orderbooks = dict(orderbooks or {})
        self.orderbook_tokens = []

    async def get_orderbook(self, token_id):
        self.orderbook_tokens.append(token_id)
        if token_id not in self._orderbooks:
            raise AssertionError(f"unexpected get_orderbook token: {token_id}")
        return self._orderbooks[token_id]


class FakeRateLimiter:
    """Rate limiter stub: acquire(category) -> 0.0, categories recorded."""

    def __init__(self):
        self.categories = []

    async def acquire(self, category):
        self.categories.append(category)
        return 0.0


class FakeConfig:
    """Config stub: the code only touches POLYGON_ADDRESS (lowercased)."""

    POLYGON_ADDRESS = ADDRESS


def set_api_routes(routes):
    """Route the installed client stub: exact URL -> canned payload."""
    FakeAsyncClient.responses = dict(routes)


def position_row(*, market=None, condition_id=None, question="Question",
                 token="tok", size=10.0, avg_price=0.40, outcome="YES"):
    """Position payload; market/conditionId keys only when provided.

    The wire shape carries ``conditionId`` (camelCase); the legacy fixture
    shape of the sister suites carries ``market`` (snake). Each test pins
    exactly which key its row matches by.
    """
    row: Dict[str, Any] = {}
    if condition_id is not None:
        row["conditionId"] = condition_id
    if market is not None:
        row["market"] = market
    row.update({
        "asset_id": token,
        "market_question": question,
        "outcome": outcome,
        "size": size,
        "average_price": avg_price,
    })
    return row


def trade_row(*, market=None, condition_id=None, price=0.50, size=5.0,
              side="BUY", seq=0):
    """Trade payload; same conditional-key discipline as position_row."""
    row: Dict[str, Any] = {}
    if condition_id is not None:
        row["conditionId"] = condition_id
    if market is not None:
        row["market"] = market
    row.update({
        "outcome": "YES",
        "side": side,
        "price": price,
        "size": size,
        "timestamp": BASE_TS + seq,
        "fee": 0.01,
        "id": f"trade-{seq}",
    })
    return row


def orderbook(bid, bid_size, ask, ask_size):
    """Orderbook payload shape consumed by the mid-price math."""
    return {
        "bids": [{"price": bid, "size": bid_size}],
        "asks": [{"price": ask, "size": ask_size}],
    }


def text_of(content):
    """Extract the single text payload of a [types.TextContent] return."""
    assert len(content) == 1
    assert content[0].type == "text"
    return content[0].text


@pytest.fixture(autouse=True)
def isolated_portfolio(monkeypatch):
    """Per-test isolation: reset the module cache and the stub (house rule
    of the sister suite); monkeypatch restores httpx.AsyncClient."""
    portfolio._portfolio_cache.clear()
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = {}
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    yield
    portfolio._portfolio_cache.clear()


# --- 1. Foreign position for a padded cid -> honest empty result -----------


async def test_foreign_cid_returns_no_position():
    """The wire returns a FOREIGN position for a padded cid (drop quirk):
    the filter must present the honest empty result, never another
    market's position under the requested header."""
    set_api_routes({
        POSITIONS_URL: [
            position_row(market=FOREIGN, token="tok_other",
                         question="Foreign question")
        ],
    })
    # The orderbook for the foreign token exists ONLY so the pre-fix path
    # renders the foreign position (the honest RED) instead of erroring --
    # post-fix this fetch never happens (empty path returns first).
    client = FakePolymarketClient(
        orderbooks={"tok_other": orderbook(0.50, 5, 0.50, 5)}
    )
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_position_details(
        client, limiter, FakeConfig(), PADDED_CID
    ))

    assert text == f"No position found for market {PADDED_CID}"
    assert "Position Details" not in text
    assert "Foreign question" not in text


# --- 2. conditionId (camelCase wire truth) precedes -------------------------


async def test_conditionid_precedence_over_market_key():
    """Padded cid + [foreign(market key), matching(conditionId key)]: the
    filter must keep the row matching ONLY via conditionId (the wire
    truth) and render IT, not the foreign row that sorts first."""
    matching = position_row(
        condition_id=PADDED_CID, token="tok_match",
        question="Matching question")
    foreign = position_row(market=FOREIGN, token="tok_other",
                           question="Foreign question")
    set_api_routes({
        POSITIONS_URL: [foreign, matching],
        TRADES_URL: [],  # no trades rendered here; route the second fetch
    })
    client = FakePolymarketClient(orderbooks={
        "tok_match": orderbook(0.50, 5, 0.50, 5),
        "tok_other": orderbook(0.50, 5, 0.50, 5),
    })
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_position_details(
        client, limiter, FakeConfig(), PADDED_CID
    ))

    assert text.startswith("Position Details: Matching question")
    assert "Foreign question" not in text
    assert client.orderbook_tokens == ["tok_match"]


# --- 3. ``market`` fallback (legacy fixture shape) still matches ------------


async def test_market_key_fallback_matches_legacy_fixtures():
    """Sister-suite compatibility: a row carrying ONLY the legacy
    ``market`` key (snake) still matches the requested id -- the fallback
    keeps the house fixtures green while the wire truth (conditionId)
    precedes."""
    matching = position_row(
        market=PADDED_CID, token="tok_match",
        question="Matching question")
    foreign = position_row(market=FOREIGN, token="tok_other",
                           question="Foreign question")
    set_api_routes({
        POSITIONS_URL: [foreign, matching],
        TRADES_URL: [],  # no trades rendered here; route the second fetch
    })
    client = FakePolymarketClient(orderbooks={
        "tok_match": orderbook(0.50, 5, 0.50, 5),
        "tok_other": orderbook(0.50, 5, 0.50, 5),
    })
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_position_details(
        client, limiter, FakeConfig(), PADDED_CID
    ))

    assert text.startswith("Position Details: Matching question")
    assert "Foreign question" not in text
    assert client.orderbook_tokens == ["tok_match"]


# --- 4. Trades block: same wire drop, same filter ----------------------------


async def test_recent_trades_filtered_by_market():
    """Trades block: the wire ALSO drops the market filter there (probe
    2026-09-20) -- only the requested market's trade may render."""
    set_api_routes({
        POSITIONS_URL: [
            position_row(market=PADDED_CID, token="tok_match",
                         question="Matching question")
        ],
        TRADES_URL: [
            trade_row(market=FOREIGN, price=0.11, side="BUY", seq=0),
            trade_row(market=FOREIGN, price=0.22, side="SELL", seq=1),
            trade_row(market=PADDED_CID, price=0.37, side="BUY", seq=2),
        ],
    })
    client = FakePolymarketClient(
        orderbooks={"tok_match": orderbook(0.50, 5, 0.50, 5)}
    )
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_position_details(
        client, limiter, FakeConfig(), PADDED_CID
    ))

    assert text.startswith("Position Details: Matching question")
    assert "$0.3700" in text
    assert "$0.1100" not in text
    assert "$0.2200" not in text
    assert text.count(" | BUY ") == 1
    assert text.count(" | SELL ") == 0


# --- 5. Anti-over-fix: the [:5] cap survives the filter ----------------------


async def test_five_trade_cap_preserved_after_filter():
    """The [:5] slice still caps rendering AFTER the filter (7 matching
    trades -> exactly 5 rendered; the 6th is dropped by the cap, not by
    the filter)."""
    set_api_routes({
        POSITIONS_URL: [
            position_row(market=PADDED_CID, token="tok_match",
                         question="Matching question")
        ],
        TRADES_URL: [
            trade_row(market=PADDED_CID, price=price, side="BUY", seq=seq)
            for seq, price in enumerate(
                [0.31, 0.32, 0.33, 0.34, 0.35, 0.36, 0.37])
        ],
    })
    client = FakePolymarketClient(
        orderbooks={"tok_match": orderbook(0.50, 5, 0.50, 5)}
    )
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_position_details(
        client, limiter, FakeConfig(), PADDED_CID
    ))

    assert text.count(" | BUY ") == 5
    assert "$0.3500" in text
    assert "$0.3600" not in text


# --- 6. Empty path unchanged (filter-empty == wire-empty) --------------------


async def test_empty_positions_path_unchanged():
    """Filter-empty and wire-empty fall in the SAME honest return (the
    :474 pin of the sister suite survives by construction)."""
    set_api_routes({POSITIONS_URL: []})
    client = FakePolymarketClient()
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_position_details(
        client, limiter, FakeConfig(), PADDED_CID
    ))

    assert text == f"No position found for market {PADDED_CID}"
    assert "Position Details" not in text
