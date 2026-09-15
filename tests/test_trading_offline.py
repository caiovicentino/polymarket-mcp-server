"""
Offline regression suite for order CREATION in TradingTools - the only code that
sends money (create_limit_order -> client.post_order) - plus per-market cancel.

Pinned against clone main 9c3fef6. Asserts follow the code as observed (probed
offline), not the docstrings - L-0020/L-0090. Source of truth:
- create_limit_order (src/polymarket_mcp/tools/trading.py:103-295):
  * Parameter validation runs BEFORE any client fetch: price in (0, 1],
    size > 0, side in {BUY, SELL}, order_type in {GTC, GTD, FOK, FAK}, and GTD
    requires an expiration. An invalid call must fail closed with the exact
    error, the exact 4-key error details, and zero get_market/post_order calls.
  * The USD size is converted to shares (size / price) and validated by the
    REAL SafetyLimits (utils/safety_limits.py:97-190). A safety rejection
    surfaces as "Safety check failed: <msg>" and NEVER reaches post_order.
    get_positions() feeds the exposure cap (probe: 1 call per order).
  * The confirmation gate (safety_limits.py:215-236) is strict:
    order_value_usd > REQUIRE_CONFIRMATION_ABOVE_USD. Exactly at the threshold
    the order posts; one cent above it is held until confirm=True.
  * On success post_order receives exactly token_id/price/size/side/
    order_type/expiration, and the result carries order_id, status, details
    (with a UTC-aware ISO timestamp) and the raw order_response.
- create_market_order (trading.py:297-372): BUY takes the best ask, SELL the
  best bid, delegates as FOK with the resolved outcome, and stamps
  execution_type="market_order" plus executed_price on the returned dict EVEN
  when the nested limit order was rejected by safety. With no book liquidity it
  fails closed ("No asks/bids available in orderbook") without posting.
- cancel_market_orders (trading.py:794-856): only the requested market's open
  orders are cancelled - a filled order and a live order of ANOTHER market stay
  untouched; the market/asset_id kwargs reach get_orders verbatim; a market
  with nothing open answers "No open orders to cancel" and never calls
  cancel_order.

Zero network, zero sleep: SafetyLimits is the REAL class, the rate limiter is
duck-typed no-op (the real singleton sleeps between calls - L-0014), and the
client is a recording fake. Fakes are self-contained here (house rule: never
import fakes from another test module).
"""
from datetime import datetime

import pytest

from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.safety_limits import SafetyLimits


class FakeConfig:
    """Minimal stand-in for PolymarketConfig."""

    def __init__(self, autonomous: bool = True, threshold: float = 1_000_000_000.0):
        self.ENABLE_AUTONOMOUS_TRADING = autonomous
        self.REQUIRE_CONFIRMATION_ABOVE_USD = threshold


class FakeLimiter:
    """No-op rate limiter: the real singleton sleeps between calls (L-0014)."""

    async def acquire(self, category):
        return 0.0


class FakeClient:
    """Duck-typed client that records every call the trading tools make."""

    def __init__(self):
        self.posted = []  # kwargs received by post_order
        self.get_market_calls = 0  # fetches must NOT happen before validation
        self.get_positions_calls = 0
        self.get_orders_calls = []  # kwargs received by get_orders
        self.cancel_order_calls = []
        self.cancelled = []  # order ids actually handed to cancel_order
        self.positions = []  # raw position dicts served to get_positions
        self.orders = []  # raw order dicts served to get_orders
        self.book = {  # orderbook served to get_orderbook
            "bids": [{"price": "0.49", "size": "100000"}],
            "asks": [{"price": "0.51", "size": "100000"}],
        }

    async def get_market(self, market_id):
        self.get_market_calls += 1
        return {
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes"},
                {"token_id": "no-token", "outcome": "No"},
            ],
            "volume": "1000000",
        }

    async def get_orderbook(self, token_id):
        return self.book

    async def get_positions(self):
        self.get_positions_calls += 1
        return self.positions

    async def post_order(self, **kwargs):
        self.posted.append(kwargs)
        return {"orderID": "order-1", "status": "submitted"}

    async def get_orders(self, market=None, asset_id=None):
        self.get_orders_calls.append({"market": market, "asset_id": asset_id})
        matching = [o for o in self.orders if o.get("market") == market]
        if asset_id is not None:
            matching = [o for o in matching if o.get("asset_id") == asset_id]
        return matching

    async def cancel_order(self, order_id):
        self.cancel_order_calls.append(order_id)
        self.cancelled.append(order_id)
        return {"cancelled": True}


def build_tools(
    max_order_size_usd: float = 100_000.0,
    max_total_exposure_usd: float = 1_000_000.0,
    max_position_size_per_market: float = 100_000.0,
    min_liquidity_required: float = 0.0,
    max_spread_tolerance: float = 1.0,
    threshold: float = 1_000_000_000.0,
    autonomous: bool = True,
):
    """Real SafetyLimits + recording fake client (house pattern, self-contained)."""
    limits = SafetyLimits(
        max_order_size_usd=max_order_size_usd,
        max_total_exposure_usd=max_total_exposure_usd,
        max_position_size_per_market=max_position_size_per_market,
        min_liquidity_required=min_liquidity_required,
        max_spread_tolerance=max_spread_tolerance,
        require_confirmation_above_usd=threshold,
    )
    client = FakeClient()
    tools = TradingTools(client, limits, FakeConfig(autonomous, threshold))
    tools.rate_limiter = FakeLimiter()
    return tools, client


async def test_limit_order_rejected_by_safety_limits_never_posts():
    tools, client = build_tools(max_order_size_usd=100.0)

    result = await tools.create_limit_order("m1", "BUY", 0.5, 500.0)

    assert result["success"] is False
    assert result["error"] == (
        "Safety check failed: Order size $500.00 exceeds maximum $100.00"
    )
    assert client.posted == [], "a safety-rejected order must never reach the exchange"

    # Second rule in isolation: minimum liquidity, wide limits otherwise.
    tools, client = build_tools(min_liquidity_required=1_000_000_000.0)

    result = await tools.create_limit_order("m1", "BUY", 0.5, 500.0)

    assert result["success"] is False
    assert result["error"] == (
        "Safety check failed: Insufficient market liquidity $100000.00, "
        "minimum required $1000000000.00"
    )
    assert client.posted == []


async def test_limit_order_rejected_by_exposure_cap_with_existing_positions():
    tools, client = build_tools(max_total_exposure_usd=600.0)
    client.positions = [
        {
            "asset_id": "yes-token",
            "market": "m1",
            "size": "1000",
            "avg_price": "0.5",
            "current_price": "0.5",
            "unrealized_pnl": "0",
        }
    ]

    result = await tools.create_limit_order("m1", "BUY", 0.5, 200.0)

    assert client.get_positions_calls == 1, "positions must feed the exposure cap"
    assert result["success"] is False
    assert result["error"] == (
        "Safety check failed: Order would increase exposure to $700.00, "
        "exceeding maximum $600.00"
    )
    assert client.posted == []


async def test_limit_order_above_threshold_requires_confirmation():
    # Exactly at the threshold: order_value_usd == threshold -> the order posts.
    tools, client = build_tools(threshold=100.0)

    result = await tools.create_limit_order("m1", "BUY", 0.5, 100.0)

    assert result["success"] is True
    assert result["status"] == "submitted"
    assert len(client.posted) == 1

    # One cent above: strictly greater than the threshold -> held until confirm.
    tools, client = build_tools(threshold=100.0)

    result = await tools.create_limit_order("m1", "BUY", 0.5, 100.01)

    assert result["success"] is False
    assert result["status"] == "confirmation_required"
    assert result["reason"] == (
        "order value $100.01 exceeds the confirmation threshold of $100.00"
    )
    assert client.posted == [], "a gated order must not reach the exchange"


@pytest.mark.parametrize(
    ("kwargs", "expected_error", "expected_side", "expected_price", "expected_usd"),
    [
        (
            {"side": "HOLD", "price": 0.5, "size": 50.0},
            "Side must be BUY or SELL, got HOLD",
            "HOLD",
            0.5,
            50.0,
        ),
        (
            {"side": "BUY", "price": 1.5, "size": 50.0},
            "Price must be between 0 and 1, got 1.5",
            "BUY",
            1.5,
            50.0,
        ),
        (
            {"side": "BUY", "price": 0.5, "size": 0.0},
            "Size must be positive, got 0.0",
            "BUY",
            0.5,
            0.0,
        ),
        (
            {"side": "BUY", "price": 0.5, "size": 50.0, "order_type": "IOC"},
            "Invalid order type: IOC",
            "BUY",
            0.5,
            50.0,
        ),
        (
            {"side": "BUY", "price": 0.5, "size": 50.0, "order_type": "GTD"},
            "GTD orders require expiration timestamp",
            "BUY",
            0.5,
            50.0,
        ),
    ],
)
async def test_limit_order_invalid_params_fail_closed_without_posting(
    kwargs, expected_error, expected_side, expected_price, expected_usd
):
    tools, client = build_tools()

    result = await tools.create_limit_order("m1", **kwargs)

    assert result["success"] is False
    assert result["error"] == expected_error
    assert result["details"] == {
        "market_id": "m1",
        "side": expected_side,
        "price": expected_price,
        "size_usd": expected_usd,
    }
    assert client.posted == [], "invalid input must fail closed before posting"
    assert client.get_market_calls == 0, "validation must precede the market fetch"


async def test_limit_order_posts_shares_and_forwards_order_kwargs():
    tools, client = build_tools()

    result = await tools.create_limit_order(
        "m1", "buy", 0.25, 50.0, order_type="gtd", expiration=1700000000, outcome="No"
    )

    assert result["success"] is True
    assert result["order_id"] == "order-1"
    assert result["status"] == "submitted"
    assert result["order_response"] == {"orderID": "order-1", "status": "submitted"}
    assert client.posted == [
        {
            "token_id": "no-token",
            "price": 0.25,
            "size": 200.0,  # USD 50 / price 0.25
            "side": "BUY",
            "order_type": "GTD",
            "expiration": 1700000000,
        }
    ]
    details = result["details"]
    assert details["market_id"] == "m1"
    assert details["token_id"] == "no-token"
    assert details["outcome"] == "No"
    assert details["side"] == "BUY"
    assert details["price"] == 0.25
    assert details["size_shares"] == 200.0
    assert details["size_usd"] == 50.0
    assert details["order_type"] == "GTD"
    # The timestamp must be a real UTC-aware ISO instant, not a placeholder.
    assert datetime.fromisoformat(details["timestamp"]).tzinfo is not None


async def test_market_order_uses_best_ask_for_buy():
    tools, client = build_tools()

    result = await tools.create_market_order("m1", "BUY", 50.0)

    assert result["success"] is True
    assert result["execution_type"] == "market_order"
    assert result["executed_price"] == 0.51
    assert len(client.posted) == 1
    posted = client.posted[-1]
    assert posted["token_id"] == "yes-token"
    assert posted["price"] == 0.51
    assert posted["size"] == pytest.approx(50.0 / 0.51)
    assert posted["side"] == "BUY"
    assert posted["order_type"] == "FOK"
    assert posted["expiration"] is None


async def test_market_order_uses_best_bid_for_sell():
    tools, client = build_tools()

    result = await tools.create_market_order("m1", "SELL", 50.0)

    assert result["success"] is True
    assert result["executed_price"] == 0.49
    assert len(client.posted) == 1
    posted = client.posted[-1]
    assert posted["token_id"] == "yes-token"
    assert posted["price"] == 0.49
    assert posted["size"] == pytest.approx(50.0 / 0.49)
    assert posted["side"] == "SELL"
    assert posted["order_type"] == "FOK"
    assert posted["expiration"] is None


async def test_market_order_without_liquidity_fails_closed():
    tools, client = build_tools()
    client.book = {"bids": [{"price": "0.49", "size": "100000"}], "asks": []}

    result = await tools.create_market_order("m1", "BUY", 50.0)

    assert result == {
        "success": False,
        "error": "No asks available in orderbook",
        "execution_type": "market_order",
        "details": {"market_id": "m1", "side": "BUY", "size_usd": 50.0},
    }
    assert client.posted == []

    tools, client = build_tools()
    client.book = {"bids": [], "asks": [{"price": "0.51", "size": "100000"}]}

    result = await tools.create_market_order("m1", "SELL", 50.0)

    assert result == {
        "success": False,
        "error": "No bids available in orderbook",
        "execution_type": "market_order",
        "details": {"market_id": "m1", "side": "SELL", "size_usd": 50.0},
    }
    assert client.posted == []


async def test_market_order_surfaces_safety_rejection():
    tools, client = build_tools(max_order_size_usd=10.0)

    result = await tools.create_market_order("m1", "BUY", 50.0)

    assert result["success"] is False
    assert result["error"] == (
        "Safety check failed: Order size $50.00 exceeds maximum $10.00"
    )
    assert result["execution_type"] == "market_order"
    assert result["executed_price"] == 0.51
    assert client.posted == []


async def test_cancel_market_orders_only_cancels_matching_market():
    tools, client = build_tools()
    client.orders = [
        {"id": "m1-a", "market": "m1", "status": "open", "asset_id": "yes-token"},
        {"id": "m1-b", "market": "m1", "status": "filled", "asset_id": "yes-token"},
        {"id": "m2-a", "market": "m2", "status": "live", "asset_id": "yes-token"},
    ]

    result = await tools.cancel_market_orders("m1")

    assert result["success"] is True
    assert result["cancelled_orders"] == ["m1-a"]
    assert result["cancelled_count"] == 1
    assert result["failed_count"] == 0
    assert client.get_orders_calls[-1] == {"market": "m1", "asset_id": None}
    assert client.cancelled == ["m1-a"], "m2-a must never be cancelled"
    assert "m2-a" not in client.cancel_order_calls

    # The optional asset/token filter is forwarded verbatim to the client.
    await tools.cancel_market_orders("m1", asset_id="yes-token")

    assert client.get_orders_calls[-1] == {"market": "m1", "asset_id": "yes-token"}
    assert client.cancel_order_calls == ["m1-a", "m1-a"]

    # A market with nothing open answers friendly and attempts no cancel.
    quiet = await tools.cancel_market_orders("m3")

    assert quiet == {
        "success": True,
        "message": "No open orders to cancel",
        "market_id": "m3",
        "cancelled_count": 0,
    }
    assert client.cancel_order_calls == ["m1-a", "m1-a"], (
        "m2-a never reached cancel_order"
    )
