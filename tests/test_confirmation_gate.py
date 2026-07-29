"""
Tests for the order confirmation gate.

Before the fix, create_limit_order logged "Order requires confirmation" and then
posted the order anyway, so REQUIRE_CONFIRMATION_ABOVE_USD had no effect. These
tests pin that an unconfirmed order is never sent to the exchange.
"""
import pytest

from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.safety_limits import SafetyLimits


class FakeConfig:
    """Minimal stand-in for PolymarketConfig."""

    def __init__(self, autonomous: bool, threshold: float = 500.0):
        self.ENABLE_AUTONOMOUS_TRADING = autonomous
        self.REQUIRE_CONFIRMATION_ABOVE_USD = threshold


class FakeClient:
    """Records whether an order was actually posted."""

    def __init__(self):
        self.posted = []

    async def get_market(self, market_id):
        return {
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes"},
                {"token_id": "no-token", "outcome": "No"},
            ],
            "volume": "1000000",
        }

    async def get_orderbook(self, token_id):
        return {
            "bids": [{"price": "0.49", "size": "100000"}],
            "asks": [{"price": "0.51", "size": "100000"}],
        }

    async def get_positions(self):
        return []

    async def post_order(self, **kwargs):
        self.posted.append(kwargs)
        return {"orderID": "order-1", "status": "submitted"}


def build_tools(autonomous: bool, threshold: float = 500.0):
    limits = SafetyLimits(
        max_order_size_usd=100_000.0,
        max_total_exposure_usd=1_000_000.0,
        max_position_size_per_market=100_000.0,
        min_liquidity_required=0.0,
        max_spread_tolerance=1.0,
        require_confirmation_above_usd=threshold,
    )
    client = FakeClient()
    tools = TradingTools(client, limits, FakeConfig(autonomous, threshold))
    return tools, client


class TestGateBlocks:
    @pytest.mark.asyncio
    async def test_large_order_is_not_placed_without_confirm(self):
        tools, client = build_tools(autonomous=True, threshold=100.0)

        result = await tools.create_limit_order(
            market_id="m1", side="BUY", price=0.5, size=500.0, outcome="Yes"
        )

        assert result["success"] is False
        assert result["status"] == "confirmation_required"
        assert client.posted == [], "order must not reach the exchange"

    @pytest.mark.asyncio
    async def test_every_order_blocked_when_autonomous_disabled(self):
        tools, client = build_tools(autonomous=False, threshold=100_000.0)

        result = await tools.create_limit_order(
            market_id="m1", side="BUY", price=0.5, size=1.0, outcome="Yes"
        )

        assert result["status"] == "confirmation_required"
        assert "autonomous trading is disabled" in result["reason"]
        assert client.posted == []

    @pytest.mark.asyncio
    async def test_blocked_response_describes_the_order(self):
        tools, _ = build_tools(autonomous=True, threshold=100.0)

        result = await tools.create_limit_order(
            market_id="m1", side="BUY", price=0.5, size=500.0, outcome="No"
        )

        details = result["details"]
        assert details["outcome"] == "No"
        assert details["token_id"] == "no-token"
        assert details["side"] == "BUY"
        assert details["size_usd"] == 500.0


class TestGateAllows:
    @pytest.mark.asyncio
    async def test_confirmed_order_is_placed(self):
        tools, client = build_tools(autonomous=True, threshold=100.0)

        result = await tools.create_limit_order(
            market_id="m1", side="BUY", price=0.5, size=500.0,
            outcome="Yes", confirm=True
        )

        assert result["success"] is True
        assert len(client.posted) == 1
        assert client.posted[0]["token_id"] == "yes-token"

    @pytest.mark.asyncio
    async def test_small_order_below_threshold_needs_no_confirm(self):
        tools, client = build_tools(autonomous=True, threshold=500.0)

        result = await tools.create_limit_order(
            market_id="m1", side="BUY", price=0.5, size=10.0, outcome="Yes"
        )

        assert result["success"] is True
        assert len(client.posted) == 1


class TestConfirmPropagation:
    """A nested order must not lose the confirmation the caller gave."""

    @pytest.mark.asyncio
    async def test_market_order_forwards_confirm(self):
        tools, client = build_tools(autonomous=True, threshold=100.0)

        result = await tools.create_market_order(
            market_id="m1", side="BUY", size=500.0, outcome="Yes", confirm=True
        )

        assert result["success"] is True
        assert len(client.posted) == 1

    @pytest.mark.asyncio
    async def test_market_order_blocked_without_confirm(self):
        tools, client = build_tools(autonomous=True, threshold=100.0)

        result = await tools.create_market_order(
            market_id="m1", side="BUY", size=500.0, outcome="Yes"
        )

        assert result["status"] == "confirmation_required"
        assert client.posted == []

    @pytest.mark.asyncio
    async def test_market_order_keeps_the_resolved_outcome(self):
        """The nested limit order must trade the same token, not re-infer it."""
        tools, client = build_tools(autonomous=True, threshold=100_000.0)

        await tools.create_market_order(
            market_id="m1", side="BUY", size=10.0, outcome="No", confirm=True
        )

        assert client.posted[0]["token_id"] == "no-token"


class TestSmartTradeReporting:
    """A blocked smart trade must not report itself as a success."""

    @pytest.mark.asyncio
    async def test_blocked_smart_trade_reports_confirmation_required(self):
        tools, client = build_tools(autonomous=True, threshold=1.0)

        result = await tools.execute_smart_trade(
            market_id="m1",
            intent="buy quickly",
            max_budget=500.0,
            outcome="Yes",
        )

        assert client.posted == [], "no order should reach the exchange"
        assert result["success"] is False
        assert result["status"] == "confirmation_required"
        assert result["execution_summary"]["successful"] == 0
        assert result["execution_summary"]["awaiting_confirmation"] > 0

    @pytest.mark.asyncio
    async def test_confirmed_smart_trade_executes(self):
        tools, client = build_tools(autonomous=True, threshold=1.0)

        result = await tools.execute_smart_trade(
            market_id="m1",
            intent="buy quickly",
            max_budget=500.0,
            outcome="Yes",
            confirm=True,
        )

        assert result["success"] is True
        assert len(client.posted) > 0
        assert result["execution_summary"]["awaiting_confirmation"] == 0


class TestBatchAndRebalanceReporting:
    """Gated orders must be reported as pending, not as failures or successes."""

    @pytest.mark.asyncio
    async def test_batch_separates_pending_from_failed(self):
        tools, client = build_tools(autonomous=True, threshold=100.0)

        result = await tools.create_batch_orders([
            {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 500.0,
             "outcome": "Yes"},
            {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 10.0,
             "outcome": "No"},
        ])

        assert result["awaiting_confirmation"] == 1
        assert result["failed"] == 0, "a gated order has not failed"
        assert result["successful"] == 1
        # Only the small order went through.
        assert len(client.posted) == 1

    @pytest.mark.asyncio
    async def test_fully_gated_batch_is_not_a_success(self):
        tools, client = build_tools(autonomous=False)

        result = await tools.create_batch_orders([
            {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 10.0,
             "outcome": "Yes"},
        ])

        assert result["success"] is False
        assert result["status"] == "confirmation_required"
        assert client.posted == []

    @pytest.mark.asyncio
    async def test_batch_forwards_per_order_confirm(self):
        tools, client = build_tools(autonomous=True, threshold=100.0)

        result = await tools.create_batch_orders([
            {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 500.0,
             "outcome": "Yes", "confirm": True},
        ])

        assert result["successful"] == 1
        assert len(client.posted) == 1

    @pytest.mark.asyncio
    async def test_rebalance_surfaces_the_gate(self):
        tools, client = build_tools(autonomous=False)
        # No positions, so a target size means buying into the market.
        result = await tools.rebalance_position(
            market_id="m1", target_size=50.0, outcome="Yes"
        )

        assert result["success"] is False
        assert result["status"] == "confirmation_required"
        assert client.posted == []
