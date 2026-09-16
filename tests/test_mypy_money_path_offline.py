"""
Offline regression suite for the money-path mypy fixes (T-0069).

Pinned against farm/T-0069 (fork of clone main 946aca0). Asserts follow the
code as observed (probed offline), not the docstrings - L-0020/L-0090.
Source of truth:

- cancel_market_orders (src/polymarket_mcp/tools/trading.py:794-856): orders
  without an id (neither "id" nor "orderID") fail closed WITHOUT calling
  cancel_order: the None guard (:833-842) logs "Order without id/orderID
  cannot be cancelled", appends {"order_id": None, "error": "order has no
  id/orderID field"} to failed_orders and continues. Before the guard the
  call went out with None (probed: cancel_order_calls == [None] against both
  a raising and a succeeding client), which the real client rejects
  (PolymarketClient.cancel_order -> RuntimeError without L2 credentials).
  failed_count stays 1 for the same open order - only the attempt is gone.

Zero network, zero sleep: SafetyLimits is the REAL class, the rate limiter is
duck-typed no-op (the real singleton sleeps between calls - L-0014), and the
client is a recording fake. Fakes are self-contained here (house rule: never
import fakes from another test module).
"""
import pytest

from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.safety_limits import SafetyLimits


class FakeConfig:
    """Minimal stand-in for PolymarketConfig."""

    def __init__(self):
        self.ENABLE_AUTONOMOUS_TRADING = True
        self.REQUIRE_CONFIRMATION_ABOVE_USD = 1_000_000_000.0


class FakeLimiter:
    """No-op rate limiter: the real singleton sleeps between calls (L-0014)."""

    async def acquire(self, category):
        return 0.0


class FakeClient:
    """Duck-typed client that records every call the trading tools make."""

    def __init__(self):
        self.orders = []  # raw order dicts served to get_orders
        self.get_orders_calls = []  # kwargs received by get_orders
        self.cancel_order_calls = []  # every order_id handed to cancel_order

    async def get_orders(self, market=None, asset_id=None):
        self.get_orders_calls.append({"market": market, "asset_id": asset_id})
        return list(self.orders)

    async def cancel_order(self, order_id):
        self.cancel_order_calls.append(order_id)
        return {"cancelled": True}


def build_tools():
    """Wide safety limits (house pattern) so size caps never gate these tests."""
    limits = SafetyLimits(
        max_order_size_usd=100_000.0,
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


@pytest.mark.asyncio
async def test_cancel_market_orders_order_without_id_fails_closed_without_call(caplog):
    """None guard :833-842: an open order carrying neither "id" nor "orderID"
    is recorded as failed with order_id=None and cancel_order is NEVER called
    (before the guard the call went out with None - probed, cancel_order_calls
    == [None]). The success envelope is unchanged: same failed_count=1. The
    guard logs the exact substring it emits for id-less orders."""
    tools, client = build_tools()
    client.orders = [
        {"market": "m1", "status": "open"},  # no id, no orderID -> order_id None
        {"id": "o1", "market": "m1", "status": "live"},
    ]

    with caplog.at_level("ERROR", logger="polymarket_mcp.tools.trading"):
        result = await tools.cancel_market_orders("m1")

    assert result["success"] is True
    assert result["cancelled_count"] == 1
    assert result["cancelled_orders"] == ["o1"]
    assert result["failed_count"] == 1
    assert result["failed_orders"] == [
        {"order_id": None, "error": "order has no id/orderID field"}
    ]
    assert client.cancel_order_calls == ["o1"], "None must never reach cancel_order"
    assert any(
        "Order without id/orderID cannot be cancelled" in record.message
        for record in caplog.records
    ), "guard log must fire for id-less orders"


@pytest.mark.asyncio
async def test_cancel_market_orders_id_takes_precedence_over_orderid():
    """order.get('id') or order.get('orderID') (:833): with both keys present
    the truthy "id" wins - the guard's FALSE path routes a real id straight
    to cancel_order, never through the None branch."""
    tools, client = build_tools()
    client.orders = [{"id": "real-id", "orderID": "alt-id", "market": "m1", "status": "open"}]

    result = await tools.cancel_market_orders("m1")

    assert result["cancelled_orders"] == ["real-id"]
    assert result["failed_count"] == 0
    assert client.cancel_order_calls == ["real-id"]


@pytest.mark.asyncio
async def test_cancel_market_orders_orderid_used_when_id_missing():
    """An order carrying only "orderID" (no "id") is handled by the falsy
    fallback of :833 - the guard's FALSE path cancels it normally, with no
    failed entry and no synthetic error."""
    tools, client = build_tools()
    client.orders = [{"orderID": "only-orderid", "market": "m1", "status": "pending"}]

    result = await tools.cancel_market_orders("m1")

    assert result["cancelled_orders"] == ["only-orderid"]
    assert result["failed_count"] == 0
    assert client.cancel_order_calls == ["only-orderid"]
