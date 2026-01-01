"""
Offline regression suite for the ORDERBOOK SHAPE contract (T-0211): what
get_orderbook hands to its consumers.

Why this suite exists
---------------------
py-clob-client 0.34.6 hands `get_order_book` back as an OrderBookSummary
DATACLASS (no .get() -> AttributeError in every consumer) and the live CLOB
/book endpoint orders levels WORST-FIRST (bids ascending, asks descending).
Every consumer reads bids[0]/asks[0] as the BEST prices
(trading.py:505-512, trading.py:163-165, portfolio.py:126-130) and
market_analysis.get_orderbook sliced [:depth] BEFORE any ordering. Both bugs
were hidden because every pre-existing stub returns plain dicts. This suite
pins, offline: the dataclass->dict conversion (asdict) with best-first
normalization in auth/client.py, the plain-dict passthrough BY IDENTITY
(mirrors the pin at test_client_auth_offline.py:328), and the sort-then-slice
depth semantics in market_analysis.py. Two e2e tests drive the REAL
PolymarketClient through TradingTools to prove the money path
(create_limit_order / suggest_order_price) reaches post_order / correct
pricing when served a worst-first dataclass book.

Fixture shapes are derived from LIVE probes (curator preflight, 2026-09-17,
token Fed 111061902544814266207267295505639408607400625795891618462682726460921782993748):
32 ascending bids 0.01->0.52, 38 descending asks 0.99->0.53, plus a one-sided
book (65 bids, 0 asks). Fakes are fail-loud (P-0031/P-0040) and self-contained
(house rule: never import fakes from another test module). Zero network, zero
sleeps (L-0014): the rate limiter is a duck-typed no-op and the client slot is
swapped for a recording stub.
"""
import pytest
from py_clob_client.clob_types import OrderArgs, OrderBookSummary, OrderType

from polymarket_mcp.auth.client import PolymarketClient
from polymarket_mcp.tools import market_analysis
from polymarket_mcp.tools.market_analysis import OrderBook, OrderBookEntry
from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.safety_limits import SafetyLimits

KEY = "0" * 63 + "1"
ADDRESS = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"

# Live CLOB /book layout: bids ascending (best bid LAST), asks descending
# (best ask LAST). 32 bids spread 0.01->0.52; 38 asks spread 0.99->0.53.
FED_BIDS = [f"{0.01 + i * (0.52 - 0.01) / 31:.4f}" for i in range(32)]
FED_ASKS = [f"{0.99 - i * (0.99 - 0.53) / 37:.4f}" for i in range(38)]

TOKENS_PAYLOAD = {
    "tokens": [
        {"token_id": "tok_yes", "outcome": "Yes"},
        {"token_id": "tok_no", "outcome": "No"},
    ],
    "volume": "1000000",
}


class FakeConfig:
    """Minimal stand-in for PolymarketConfig (self-contained copy)."""

    def __init__(self, autonomous: bool = True, threshold: float = 1_000_000_000.0):
        self.ENABLE_AUTONOMOUS_TRADING = autonomous
        self.REQUIRE_CONFIRMATION_ABOVE_USD = threshold


class FakeLimiter:
    """No-op rate limiter: the real singleton sleeps between calls (L-0014)."""

    async def acquire(self, category):
        return 0.0


class _StubClob:
    """Recording stand-in for the underlying ClobClient (SDK slot).

    The SDK surface is SYNC (get_market/get_order_book/create_order/post_order
    are sync methods on the real ClobClient - the async wrappers live on
    PolymarketClient). Fail-loud: a stub method reached without its seed set
    raises AssertionError - never a silent success (P-0031/P-0040).
    """

    def __init__(self):
        self.get_order_book_calls = []
        self.orderbook_response = None  # OrderBookSummary dataclass or plain dict
        self.get_market_calls = []
        self.get_market_response = None
        self.create_order_calls = []  # OrderArgs received by create_order
        self.post_order_calls = []  # (signed, orderType) received by post_order
        self.post_order_response = {"orderID": "0xabc", "status": "live"}

    def get_order_book(self, token_id):
        self.get_order_book_calls.append(token_id)
        if self.orderbook_response is None:
            raise AssertionError("get_order_book stub not seeded")
        return self.orderbook_response

    def get_market(self, condition_id):
        self.get_market_calls.append(condition_id)
        if self.get_market_response is None:
            raise AssertionError("get_market stub not seeded")
        return self.get_market_response

    def create_order(self, order_args):
        self.create_order_calls.append(order_args)
        return order_args  # eco: the stub "signs" by identity

    def post_order(self, signed, orderType=None):
        self.post_order_calls.append({"signed": signed, "orderType": orderType})
        return self.post_order_response


async def _serve_empty_positions():
    """Async replacement for PolymarketClient.get_positions (the real method
    hits the Data API over httpx - never run in these offline tests)."""
    return []


class _FakeClobApi:
    """Synthetic stand-in for market_analysis._fetch_clob_api (fail-loud)."""

    def __init__(self, books):
        self.books = books
        self.calls = []

    async def __call__(self, endpoint, params=None):
        params = dict(params or {})
        self.calls.append((endpoint, params))
        if endpoint != "/book":
            raise AssertionError(f"unexpected CLOB endpoint: {endpoint}")
        token_id = params.get("token_id")
        if token_id not in self.books:
            raise AssertionError(f"no synthetic book for token={token_id!r}")
        return self.books[token_id]


def _level(price, size="100000"):
    return {"price": price, "size": size}


def _worst_first_summary(bids_prices, asks_prices, size="100"):
    """Real OrderBookSummary dataclass in the live worst-first CLOB layout."""
    return OrderBookSummary(
        market="m",
        asset_id="tok",
        timestamp="0",
        bids=[_level(price, size) for price in bids_prices],
        asks=[_level(price, size) for price in asks_prices],
        min_order_size="1",
        neg_risk=False,
        tick_size="0.01",
        last_trade_price=None,
        hash="h",
    )


def _make_client(orderbook_response):
    """PolymarketClient built offline (L2 creds seeded for the order path);
    its client slot holds the stub."""
    pmc = PolymarketClient(
        private_key=KEY,
        address=ADDRESS,
        api_key="k",
        api_secret="s",
        passphrase="p",
    )
    stub = _StubClob()
    pmc.client = stub
    stub.orderbook_response = orderbook_response
    return pmc, stub


def _permissive_limits():
    return SafetyLimits(
        max_order_size_usd=100_000.0,
        max_total_exposure_usd=1_000_000.0,
        max_position_size_per_market=100_000.0,
        min_liquidity_required=0.0,
        max_spread_tolerance=1.0,
        require_confirmation_above_usd=1_000_000_000.0,
    )


def _build_tools(pmc):
    """TradingTools around the real client, rate limiter replaced post-init."""
    tools = TradingTools(pmc, _permissive_limits(), FakeConfig())
    tools.rate_limiter = FakeLimiter()
    return tools


# --- PolymarketClient.get_orderbook: dataclass conversion + ordering --------


async def test_get_orderbook_converts_dataclass_and_normalizes():
    """OrderBookSummary worst-first -> dict best-first; dataclass stays untouched."""
    pmc, stub = _make_client(
        _worst_first_summary(
            bids_prices=["0.01", "0.02", "0.52"],
            asks_prices=["0.99", "0.54", "0.53"],
        )
    )
    original = stub.orderbook_response

    result = await pmc.get_orderbook("tok")

    assert isinstance(result, dict)
    assert [float(e["price"]) for e in result["bids"]] == pytest.approx([0.52, 0.02, 0.01])
    assert [float(e["price"]) for e in result["asks"]] == pytest.approx([0.53, 0.54, 0.99])
    assert stub.get_order_book_calls == ["tok"]
    # asdict deep-copies: the ORIGINAL dataclass keeps its worst-first order.
    assert [level["price"] for level in original.bids] == ["0.01", "0.02", "0.52"]
    assert [level["price"] for level in original.asks] == ["0.99", "0.54", "0.53"]


async def test_get_orderbook_fed_shape_best_first():
    """Fed-shaped live book: bids[0]/asks[0] are the BEST prices (money-path pin)."""
    pmc, stub = _make_client(_worst_first_summary(FED_BIDS, FED_ASKS, size="2500"))

    result = await pmc.get_orderbook("tok")

    assert len(result["bids"]) == 32 and len(result["asks"]) == 38
    assert float(result["bids"][0]["price"]) == pytest.approx(0.52)
    assert float(result["asks"][0]["price"]) == pytest.approx(0.53)
    # The pre-fix behavior would have handed 0.01 / 0.99 as the "best" prices.
    assert float(result["bids"][-1]["price"]) == pytest.approx(0.01)
    assert float(result["asks"][-1]["price"]) == pytest.approx(0.99)


async def test_get_orderbook_one_sided_book_empty_side():
    """One-sided book (65 bids, no asks): no crash, empty asks preserved as []."""
    pmc, stub = _make_client(
        _worst_first_summary(
            bids_prices=[f"0.{value:02d}" for value in range(1, 66)],
            asks_prices=[],
        )
    )

    result = await pmc.get_orderbook("tok")

    assert result["asks"] == []
    assert len(result["bids"]) == 65
    assert float(result["bids"][0]["price"]) == pytest.approx(0.65)


async def test_get_orderbook_dict_passthrough_by_identity():
    """Plain dicts pass through BY IDENTITY - never re-sorted, never copied.

    Mirrors the pre-existing pin at test_client_auth_offline.py:328. Even with
    out-of-order levels the dict is handed back untouched: normalization only
    applies to the OrderBookSummary dataclass.
    """
    pmc, stub = _make_client(
        {
            "bids": [_level("0.42", "10"), _level("0.41", "20")],
            "asks": [_level("0.45", "30")],
        }
    )
    original = stub.orderbook_response

    result = await pmc.get_orderbook("tok")

    assert result is original
    assert [level["price"] for level in result["bids"]] == ["0.42", "0.41"]
    assert [level["price"] for level in result["asks"]] == ["0.45"]


# --- Consumers end-to-end (money path) --------------------------------------


async def test_create_limit_order_reaches_post_order_with_dataclass_book(monkeypatch):
    """E2E: real client + worst-first dataclass book -> limit order posts.

    RED pre-fix: orderbook.get('bids') raised AttributeError on the dataclass.
    GREEN post-fix: the wrapper signs the resolved Yes token and post_order
    receives it with the exact USD->shares conversion. get_positions (Data API
    over httpx in the real wrapper) is shadowed at the instance level - zero
    network (P-0029).
    """
    pmc, stub = _make_client(
        _worst_first_summary(
            bids_prices=["0.01", "0.02", "0.52"],
            asks_prices=["0.99", "0.54", "0.53"],
        )
    )
    stub.get_market_response = TOKENS_PAYLOAD
    monkeypatch.setattr(pmc, "get_positions", _serve_empty_positions)
    tools = _build_tools(pmc)

    result = await tools.create_limit_order("0xcond", "BUY", 0.5, 50.0, outcome="Yes")

    assert result["success"] is True
    assert result["order_id"] == "0xabc"
    assert result["status"] == "live"
    expected_args = OrderArgs(token_id="tok_yes", price=0.5, size=100.0, side="BUY")
    assert stub.create_order_calls == [expected_args]
    assert stub.post_order_calls == [
        {"signed": expected_args, "orderType": OrderType.GTC}
    ]
    assert result["order_response"] == {"orderID": "0xabc", "status": "live"}


async def test_suggest_order_price_aggressive_buy_uses_best_ask_normalized():
    """Aggressive BUY prices at asks[0] AFTER normalization: 0.53 (bug: 0.99)."""
    pmc, stub = _make_client(_worst_first_summary(FED_BIDS, FED_ASKS, size="2500"))
    stub.get_market_response = TOKENS_PAYLOAD
    tools = _build_tools(pmc)

    result = await tools.suggest_order_price("0xcond", "BUY", 100.0, strategy="aggressive")

    assert result["success"] is True
    assert result["strategy"] == "aggressive"
    assert result["suggested_price"] == pytest.approx(0.53)
    assert result["market_context"]["best_bid"] == pytest.approx(0.52)
    assert result["market_context"]["best_ask"] == pytest.approx(0.53)


# --- market_analysis.get_orderbook: sort-then-slice -------------------------


async def test_market_analysis_get_orderbook_sorts_worst_first_clob(monkeypatch):
    """Depth=2 on a worst-first CLOB book keeps the BEST levels, not the first.

    RED pre-fix: the [:depth] slice over the raw array would have kept the two
    WORST levels ([0.01, 0.51] bids / [0.99, 0.54] asks).
    """
    clob = _FakeClobApi(
        books={
            "tok": {
                "bids": [_level("0.01", "100"), _level("0.51", "200"), _level("0.52", "300")],
                "asks": [_level("0.99", "100"), _level("0.54", "200"), _level("0.53", "300")],
            }
        }
    )
    monkeypatch.setattr(market_analysis, "_fetch_clob_api", clob)

    book = await market_analysis.get_orderbook("tok", depth=2)

    assert isinstance(book, OrderBook)
    assert [entry.price for entry in book.bids] == pytest.approx([0.52, 0.51])
    assert [entry.size for entry in book.bids] == pytest.approx([300.0, 200.0])
    assert [entry.price for entry in book.asks] == pytest.approx([0.53, 0.54])
    assert [entry.size for entry in book.asks] == pytest.approx([300.0, 200.0])
    assert all(isinstance(entry, OrderBookEntry) for entry in book.bids + book.asks)
    assert clob.calls == [("/book", {"token_id": "tok"})]
