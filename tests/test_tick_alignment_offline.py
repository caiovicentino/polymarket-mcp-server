"""
Offline regression suite for TICK ALIGNMENT on the money path (T-0278).

Why this suite exists
---------------------
suggest_order_price emitted prices that are NOT multiples of the market tick
size. The live Fed book (token 111061902544814266207267295505639408607400625
795891618462682726460921782993748, curator probe 2026-09-18: 32 bids asc /
38 asks desc, best bid 0.52, best ask 0.53, /tick-size -> minimum_tick_size
0.01) yields mid=0.525, passive BUY=0.521, passive SELL=0.529 - NONE of the
three is a multiple of 0.01. py-clob-client 0.34.6 then SILENTLY rounds the
submitted price (OrderBuilder.get_order_amounts: round_normal(price,
ROUNDING_CONFIG[tick].price) -> 2 decimals for tick 0.01; round-half-even):
0.525 -> 0.52, 0.521 -> 0.52, 0.529 -> 0.53. Proven consequences by
float arithmetic: a "Mid-price SELL" becomes a 0.52 order that CROSSES the
book and executes immediately at the bid (the tool promised the mid but
behaves marketable); a passive BUY 0.521 lands ON the best bid (the intent
"above the best bid" is lost); a passive SELL 0.529 lands ON the best ask
(the intent "below the best ask" is lost). The reasoning string printed the
unaligned price - the tool was lying about the price that would execute.

create_limit_order validated only (0, 1] (trading.py:141): it accepted
0.995, which the client REJECTS (py_clob_client/utilities.py:69-70
price_valid = [tick, 1-tick] -> "price (0.995), min: 0.01 - max: 0.99"), and
accepted any unaligned price that the builder silently rounded (same drift
class with an explicit user price).

Fix contract: every computation runs in Decimal FROM THE WIRE STRINGS
(bids[0]['price'] is a str; OrderBookSummary.tick_size is a str). Float
arithmetic corrupts even "aligned" candidates (0.40 + 0.10*0.1 =
0.40999999999999998 -> ceil -> 0.42). Books WITHOUT a tick_size field keep
the legacy behavior (identity) - the pinned fixtures of
test_trading_gaps_offline.py carry no tick field.

Alignment intent (curator sim $TMPDIR/c61-sim/sim_math2.py, proven on this
exact arithmetic):
- aggressive: book prices only - UNCHANGED (aligned by CLOB construction).
- passive BUY: smallest tick-aligned price STRICTLY above the best bid.
- passive SELL: largest tick-aligned price STRICTLY below the best ask.
- mid BUY: ROUND_FLOOR to tick (never crosses the ask); mid SELL:
  ROUND_CEILING to tick (never crosses the bid); an already-aligned mid is
  the identity.

Two LIVE probes (marked integration - deselected by the offline acceptance
command) pin the real endpoint contract: every /book price is a multiple of
the /tick-size minimum_tick_size, and the endpoint answers a documented
tick set.

Zero network, zero sleep in the offline tests (L-0018/L-0014): the client is
a recording stub, the rate limiter a duck-typed no-op. Fakes are
self-contained (house rule: never import fakes from another test module).
"""
from decimal import Decimal

import httpx
import pytest
from py_clob_client.exceptions import PolyApiException

from polymarket_mcp.auth.client import PolymarketClient
from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.safety_limits import SafetyLimits

# Live probe token (curator preflight, 2026-09-18) - Fed-shaped 0.52/0.53
# book with minimum_tick_size 0.01 (proven live via GET /tick-size).
FED_TOKEN = (
    "111061902544814266207267295505639408607400625795891618462682726460921782993748"
)
KEY = "0" * 63 + "1"
ADDRESS = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"


class FakeConfig:
    """Minimal stand-in for PolymarketConfig (house pattern)."""

    def __init__(self, autonomous: bool = True, threshold: float = 1_000_000_000.0):
        self.ENABLE_AUTONOMOUS_TRADING = autonomous
        self.REQUIRE_CONFIRMATION_ABOVE_USD = threshold


class FakeLimiter:
    """No-op rate limiter: the real singleton sleeps between calls (L-0014)."""

    def __init__(self):
        self.calls = []

    async def acquire(self, category):
        self.calls.append(category)
        return 0.0


def _fed_book(with_tick: bool = True):
    """Fed-shaped top-of-book with wire-faithful STRINGS.

    bids[0]="0.52", asks[0]="0.53", tick_size="0.01" - exactly the live
    top-of-book (curator probe 2026-09-18). with_tick=False models the
    stubbed books of the sibling suites (no tick field -> identity path).
    """
    book = {
        "bids": [{"price": "0.52", "size": "2500"}],
        "asks": [{"price": "0.53", "size": "2500"}],
    }
    if with_tick:
        book["tick_size"] = "0.01"
    return book


class FakeClient:
    """Duck-typed client stub recording every call trading.py makes.

    Structural pin: post_order receives ONLY the kwargs the observed call
    site sends (trading.py:257-264). Endpoints never touch the network
    (L-0118)."""

    def __init__(self):
        self.market = {
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes"},
                {"token_id": "no-token", "outcome": "No"},
            ],
            "volume": "1000000",
        }
        self.book = _fed_book()
        self.positions = []
        self.get_orderbook_calls = []
        self.get_positions_calls = 0
        self.posted = []  # kwargs received by post_order

    async def get_market(self, market_id):
        return self.market

    async def get_orderbook(self, token_id):
        self.get_orderbook_calls.append(token_id)
        return self.book

    async def get_positions(self):
        self.get_positions_calls += 1
        return list(self.positions)

    async def post_order(self, **kwargs):
        self.posted.append(kwargs)
        return {"orderID": "order-1", "status": "submitted"}


def build_tools(max_order_size_usd: float = 100_000.0):
    """REAL SafetyLimits (wide caps, threshold at galaxy scale) + the stub."""
    limits = SafetyLimits(
        max_order_size_usd=max_order_size_usd,
        max_total_exposure_usd=1_000_000.0,
        max_position_size_per_market=100_000.0,
        min_liquidity_required=0.0,
        max_spread_tolerance=1.0,
        require_confirmation_above_usd=1_000_000_000.0,
    )
    client = FakeClient()
    tools = TradingTools(client, limits, FakeConfig())
    tools.rate_limiter = FakeLimiter()
    return tools, client


def _assert_tick_aligned(price: float, tick: str = "0.01"):
    """Semantic alignment oracle: the suggested price is a tick multiple
    (Decimal from the string form - never float arithmetic)."""
    assert Decimal(str(price)) % Decimal(tick) == 0, (
        f"suggested price {price!r} is not a multiple of tick {tick}"
    )


# --- suggest_order_price: alignment on the Fed book (tick 0.01) --------------


async def test_suggest_mid_buy_aligns_to_bid_on_odd_book():
    """Mid BUY on the odd Fed book: 0.525 is not tick-aligned; the aligned
    suggestion is 0.52 (ROUND_FLOOR - never crosses the ask). Pre-fix this
    emitted 0.525, which the client silently rounded to 0.52 - the reasoning
    string lied about the executing price."""
    tools, _client = build_tools()

    result = await tools.suggest_order_price("m1", "BUY", 100.0, "mid", "Yes")

    assert result["success"] is True
    assert result["suggested_price"] == 0.52
    _assert_tick_aligned(result["suggested_price"])
    # The reasoning string shows the ALIGNED price (0.5200), not the raw mid.
    assert "0.5200" in result["reasoning"]
    # market_context pins stay float-native (book floats untouched).
    assert result["market_context"]["mid_price"] == 0.525
    assert result["market_context"]["best_bid"] == 0.52
    assert result["market_context"]["best_ask"] == 0.53


async def test_suggest_mid_sell_aligns_to_ask_on_odd_book():
    """Mid SELL on the odd Fed book: 0.525 is not tick-aligned; the aligned
    suggestion is 0.53 (ROUND_CEILING - never crosses the bid). Pre-fix the
    0.525 suggestion silently rounded to 0.52 <= best bid: the order CROSSED
    the book and executed immediately at the bid."""
    tools, _client = build_tools()

    result = await tools.suggest_order_price("m1", "SELL", 100.0, "mid", "Yes")

    assert result["success"] is True
    assert result["suggested_price"] == 0.53
    _assert_tick_aligned(result["suggested_price"])
    assert "0.5300" in result["reasoning"]
    # The aligned SELL never crosses the bid: 0.53 > best_bid 0.52.
    assert result["suggested_price"] > result["market_context"]["best_bid"]


async def test_suggest_passive_buy_tick_aligned_above_bid():
    """Passive BUY: 0.521 is not tick-aligned; the smallest tick-aligned
    price STRICTLY above the best bid 0.52 is 0.53. Pre-fix 0.521 silently
    rounded to 0.52 - exactly ON the bid, losing the passive intent."""
    tools, _client = build_tools()

    result = await tools.suggest_order_price("m1", "BUY", 100.0, "passive", "Yes")

    assert result["success"] is True
    assert result["suggested_price"] == 0.53
    _assert_tick_aligned(result["suggested_price"])
    # Intent preserved: the aligned price is STRICTLY above the best bid.
    assert result["suggested_price"] > result["market_context"]["best_bid"]
    assert result["order_details"]["estimated_fill_probability"] == 0.4


async def test_suggest_passive_sell_tick_aligned_below_ask():
    """Passive SELL: 0.529 is not tick-aligned; the largest tick-aligned
    price STRICTLY below the best ask 0.53 is 0.52. Pre-fix 0.529 silently
    rounded to 0.53 - exactly ON the ask, losing the passive intent."""
    tools, _client = build_tools()

    result = await tools.suggest_order_price("m1", "SELL", 100.0, "passive", "Yes")

    assert result["success"] is True
    assert result["suggested_price"] == 0.52
    _assert_tick_aligned(result["suggested_price"])
    # Intent preserved: the aligned price is STRICTLY below the best ask.
    assert result["suggested_price"] < result["market_context"]["best_ask"]
    assert result["order_details"]["estimated_fill_probability"] == 0.4


async def test_suggest_aggressive_unchanged_on_odd_book():
    """Anti-over-fix: aggressive strategies price AT the book (best ask for
    BUY, best bid for SELL) - book prices are tick-aligned by CLOB
    construction, so this path is identity pre- AND post-fix."""
    tools, _client = build_tools()

    buy = await tools.suggest_order_price("m1", "BUY", 100.0, "aggressive", "Yes")
    sell = await tools.suggest_order_price("m1", "SELL", 100.0, "aggressive", "Yes")

    assert buy["success"] is True
    assert buy["suggested_price"] == 0.53
    assert buy["reasoning"] == (
        "Aggressive buy at best ask 0.5300 for immediate execution"
    )
    assert sell["success"] is True
    assert sell["suggested_price"] == 0.52
    assert sell["reasoning"] == (
        "Aggressive sell at best bid 0.5200 for immediate execution"
    )


async def test_suggest_no_tick_size_noop_identity():
    """Pin-compat guard: a book WITHOUT tick_size keeps the legacy behavior
    byte-for-byte (identity, green pre- AND post-fix). The sibling suites
    (test_trading_gaps_offline.py) pin exactly these values on tickless
    stubs - any alignment on tickless books would break them."""
    tools, client = build_tools()
    client.book = _fed_book(with_tick=False)

    best_bid, best_ask = 0.52, 0.53
    spread = best_ask - best_bid

    passive_buy = await tools.suggest_order_price("m1", "BUY", 100.0, "passive", "Yes")
    passive_sell = await tools.suggest_order_price(
        "m1", "SELL", 100.0, "passive", "Yes"
    )
    mid_buy = await tools.suggest_order_price("m1", "BUY", 100.0, "mid", "Yes")
    mid_sell = await tools.suggest_order_price("m1", "SELL", 100.0, "mid", "Yes")

    assert passive_buy["suggested_price"] == best_bid + (spread * 0.1)  # 0.521
    assert passive_sell["suggested_price"] == best_ask - (spread * 0.1)  # 0.529
    assert mid_buy["suggested_price"] == (best_bid + best_ask) / 2  # 0.525
    assert mid_sell["suggested_price"] == (best_bid + best_ask) / 2  # 0.525
    # And the reasoning strings still show the raw (legacy) values.
    assert "0.5210" in passive_buy["reasoning"]
    assert "0.5250" in mid_buy["reasoning"]


# --- create_limit_order: fail-loud validation --------------------------------


async def test_create_limit_order_rejects_unaligned_price():
    """price=0.525 on a tick-0.01 book must FAIL LOUD: pre-fix it proceeded
    to post_order and the builder silently rounded to 0.52 (a different
    order than requested). Post-fix the error names the tick, both nearest
    valid prices (floor 0.52 / ceil 0.53), and the exchange is never
    called."""
    tools, client = build_tools()

    result = await tools.create_limit_order("m1", "BUY", 0.525, 50.0, outcome="Yes")

    assert result["success"] is False
    assert "not aligned" in result["error"]
    assert "0.01" in result["error"], "the error must name the market tick size"
    assert "0.52" in result["error"] and "0.53" in result["error"], (
        "the error must surface both nearest valid prices"
    )
    assert client.posted == [], "an unaligned order must never reach the exchange"
    assert client.get_positions_calls == 0, (
        "validation fires before any position fetch"
    )


async def test_create_limit_order_accepts_aligned_price():
    """price=0.52 IS a multiple of tick 0.01 and inside [0.01, 0.99]: the
    order proceeds exactly as before (green pre- AND post-fix)."""
    tools, client = build_tools()

    result = await tools.create_limit_order("m1", "BUY", 0.52, 50.0, outcome="Yes")

    assert result["success"] is True
    assert result["status"] == "submitted"
    assert len(client.posted) == 1
    assert client.posted[0]["price"] == 0.52
    assert client.posted[0]["token_id"] == "yes-token"


async def test_create_limit_order_rejects_out_of_client_range():
    """price=0.995 is outside the client's price_valid range [0.01, 0.99]
    (py_clob_client/utilities.py:69-70): pre-fix create_limit_order accepted
    it and the exchange-side client raised the confusing
    "price (0.995), min: 0.01 - max: 0.99". Post-fix the tool fails loud
    BEFORE posting, naming the valid range."""
    tools, client = build_tools()

    result = await tools.create_limit_order("m1", "SELL", 0.995, 50.0, outcome="Yes")

    assert result["success"] is False
    assert "outside the valid range" in result["error"]
    assert "0.99" in result["error"], "the error must name the client range cap"
    assert client.posted == [], "an out-of-range order must never reach the exchange"


# --- LIVE probes (integration-marked: deselected by the offline acceptance) --


def _skip_on_clob_outage(exc, label):
    """Network guard for the py_clob_client surface: PolyApiException wraps
    BOTH transport errors (py_clob_client catches httpx.RequestError and
    re-raises with status_code=None - proven 1st hand in the 0.34.6 source,
    py_clob_client/http_helpers/helpers.py) AND API non-200s (status_code=
    int). Transport, 5xx and 429 are infra/outage: SKIP with reason. Any
    other non-200 is a live-contract violation (FAIL)."""
    status = getattr(exc, "status_code", None)
    if status is None or status >= 500 or status == 429:
        pytest.skip(
            f"{label}: CLOB transport/API outage "
            f"({type(exc).__name__} status={status})"
        )
    raise


@pytest.mark.integration
async def test_live_book_prices_are_tick_aligned():
    """REAL /book + /tick-size for the SAME token: every wire price is a
    multiple of the market's minimum_tick_size (Decimal, from strings)."""
    pmc = PolymarketClient(
        private_key=KEY,
        address=ADDRESS,
        api_key="k",
        api_secret="s",
        passphrase="p",
    )
    try:
        book = await pmc.get_orderbook(FED_TOKEN)
    except (PolyApiException, OSError) as exc:
        _skip_on_clob_outage(exc, "live /book")
    tick_raw = book.get("tick_size")
    assert tick_raw is not None, "live /book payload must carry tick_size"
    tick = Decimal(str(tick_raw))
    assert tick > 0

    levels = list(book.get("bids") or []) + list(book.get("asks") or [])
    assert levels, "live book came back empty - probe token changed?"

    for level in levels:
        price = Decimal(str(level["price"]))
        assert price % tick == 0, (
            f"wire price {price} is not a multiple of tick {tick_raw}"
        )


@pytest.mark.integration
async def test_live_tick_size_endpoint():
    """/tick-size answers minimum_tick_size inside the CLOB's documented
    tick set (py_clob_client clob_constants.TickSize)."""
    pmc = PolymarketClient(
        private_key=KEY,
        address=ADDRESS,
        api_key="k",
        api_secret="s",
        passphrase="p",
    )
    try:
        tick_size = pmc.get_client().get_tick_size(FED_TOKEN)
    except (PolyApiException, OSError) as exc:
        _skip_on_clob_outage(exc, "live /tick-size")
    assert float(tick_size) in {0.001, 0.01, 0.1}


# --- Transport-guard meta-tests (offline, deterministic) --------------------


async def test_meta_clob_transport_skips_live_book_probe(monkeypatch):
    """A PolyApiException WITHOUT status (py_clob_client catches httpx
    RequestError and re-raises) makes the live probe SKIP, never FAIL."""
    async def boom(self, token_id):
        raise PolyApiException(error_msg="Request exception!")

    monkeypatch.setattr(PolymarketClient, "get_orderbook", boom)
    with pytest.raises(pytest.skip.Exception):
        await test_live_book_prices_are_tick_aligned()


async def test_meta_clob_5xx_skips_live_book_probe(monkeypatch):
    """A 5xx PolyApiException is an API-side outage: SKIP with reason."""
    async def boom(self, token_id):
        raise PolyApiException(httpx.Response(502, text="bad gateway"))

    monkeypatch.setattr(PolymarketClient, "get_orderbook", boom)
    with pytest.raises(pytest.skip.Exception):
        await test_live_book_prices_are_tick_aligned()


async def test_meta_clob_4xx_is_live_contract_violation(monkeypatch):
    """A 4xx PolyApiException is a live-contract violation: it must KEEP
    FAILING (the guard must not swallow wire-state drift)."""
    async def boom(self, token_id):
        raise PolyApiException(httpx.Response(404, text="not found"))

    monkeypatch.setattr(PolymarketClient, "get_orderbook", boom)
    with pytest.raises(PolyApiException):
        await test_live_book_prices_are_tick_aligned()


async def test_meta_clob_oserror_skips_live_book_probe(monkeypatch):
    """An OS-level socket error (DNS/refused) is transport: SKIP."""
    async def boom(self, token_id):
        raise OSError("connection refused")

    monkeypatch.setattr(PolymarketClient, "get_orderbook", boom)
    with pytest.raises(pytest.skip.Exception):
        await test_live_book_prices_are_tick_aligned()


async def test_meta_clob_tick_size_transport_skips(monkeypatch):
    """The /tick-size live probe SKIPs on transport (PolyApiException with
    no status) instead of failing the suite."""
    from py_clob_client.client import ClobClient

    def boom(self, token_id):
        raise PolyApiException(error_msg="Request exception!")

    monkeypatch.setattr(ClobClient, "get_tick_size", boom)
    with pytest.raises(pytest.skip.Exception):
        await test_live_tick_size_endpoint()
