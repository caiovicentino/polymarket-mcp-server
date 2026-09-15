"""
Offline regression suite for order management and smart trading in tools/trading.py.

The 6 order-management methods and the smart-trade/rebalance planning paths only
had a real_api suite (test_trading_tools.py, outside the release gate). This file
pins their OBSERVED semantics with a duck-typed fake client — zero network, zero
sleep (L-0014: the rate limiter is replaced by a fake that returns 0.0).

Source of truth (L-0020/L-0090 — code, not prose):
- src/polymarket_mcp/tools/trading.py:587-1218 (the methods under test here)
- trading.py:717-730 CONFIRMED on source: in the date filter, an order WITHOUT a
  timestamp is DROPPED (only truthy `timestamp`/`created_at` reaches the filter),
  and an order with an INVALID timestamp is KEPT via the except branch. The tests
  below pin exactly that observable behavior.
- trading.py:1130/1136: the slippage comparison is `>` (BUY) / `<` (SELL), so a
  price exactly at the limit is accepted. Proven with the interpreter:
  0.5*(1+0.02) == 0.51 (BUY at the ask 0.51 passes the default 2% gate) and
  0.5*(1-0.05) == 0.475 (SELL at the bid 0.49 passes a 5% gate).

Fake-client contract documented by the recorded kwargs (trading -> client):
get_orders(market=, asset_id=), cancel_order(order_id), cancel_all_orders(),
get_positions(), get_market(market_id), get_orderbook(token_id).

Execution-path tests (confirmation gate on create_limit_order/create_market_order,
smart trade and rebalance surfacing the gate) already live in
test_confirmation_gate.py — this suite patches those methods to isolate
PLANNING from execution, and covers the REST of the behavior.

Lessons applied: L-0002 (approx for float sums), L-0014 (no sleeps/timing),
L-0020/L-0090 (asserts pin the observed code), L-0085 (rc of verification),
P-0009 (declarative header), P-0019 (worktree of the external clone, PYTHONPATH=src).
"""
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.safety_limits import SafetyLimits


class FakeConfig:
    """Minimal stand-in for PolymarketConfig (house pattern of
    test_confirmation_gate.py)."""

    def __init__(self, autonomous: bool = True, threshold: float = 500.0):
        self.ENABLE_AUTONOMOUS_TRADING = autonomous
        self.REQUIRE_CONFIRMATION_ABOVE_USD = threshold


class FakeLimiter:
    """Rate limiter seam: instant, records the requested category, no sleep."""

    def __init__(self):
        self.calls = []

    async def acquire(self, category):
        self.calls.append(category)
        return 0.0


class FakeClient:
    """Duck-typed client that records the kwargs trading.py sends it.

    Deliberately NOT spec'd on PolymarketClient: this suite pins TradingTools
    logic, not the wrapper (which is under separate change)."""

    def __init__(self):
        self.orders = []
        self.positions = []
        self.market = {}
        self.orderbook = {}
        self.cancel_all_response = {"cancelled": []}
        # error injection
        self.get_orders_error = None
        self.cancel_order_errors = {}
        self.cancel_all_error = None
        # recorded calls
        self.get_orders_calls = []
        self.cancel_order_calls = []
        self.cancel_all_calls = 0
        self.get_market_calls = []
        self.get_orderbook_calls = []

    async def get_orders(self, market=None, asset_id=None):
        self.get_orders_calls.append({"market": market, "asset_id": asset_id})
        if self.get_orders_error is not None:
            raise self.get_orders_error
        return list(self.orders)

    async def cancel_order(self, order_id):
        self.cancel_order_calls.append(order_id)
        if order_id in self.cancel_order_errors:
            raise self.cancel_order_errors[order_id]
        return {"status": "cancelled", "orderID": order_id}

    async def cancel_all_orders(self):
        self.cancel_all_calls += 1
        if self.cancel_all_error is not None:
            raise self.cancel_all_error
        return self.cancel_all_response

    async def get_positions(self):
        return list(self.positions)

    async def get_market(self, market_id):
        self.get_market_calls.append(market_id)
        return self.market

    async def get_orderbook(self, token_id):
        self.get_orderbook_calls.append(token_id)
        return self.orderbook


def build_tools(autonomous: bool = True, threshold: float = 500.0):
    """Wide safety limits (house pattern) so size caps never gate these tests."""
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
    tools.rate_limiter = FakeLimiter()
    return tools, client


class TestOrderStatus:
    @pytest.mark.asyncio
    async def test_get_order_status_reports_fill_percentage(self):
        tools, client = build_tools()
        client.orders = [
            {"id": "o1", "status": "live", "sizeMatched": "25", "originalSize": "100"},
            {"orderID": "o2", "status": "open", "size": "40"},
        ]

        filled = await tools.get_order_status("o1")
        assert filled["success"] is True
        assert filled["order_id"] == "o1"
        assert filled["status"] == "live"
        assert filled["fill_status"]["filled"] == 25.0
        assert filled["fill_status"]["total"] == 100.0
        assert filled["fill_status"]["remaining"] == 75.0
        assert filled["fill_status"]["fill_percentage"] == 25.0

        # Second order matches by 'orderID' (no 'id' key); no sizeMatched -> 0.0,
        # total falls back to 'size'.
        partial = await tools.get_order_status("o2")
        assert partial["success"] is True
        assert partial["fill_status"]["filled"] == 0.0
        assert partial["fill_status"]["total"] == 40.0
        assert partial["fill_status"]["fill_percentage"] == 0.0

        missing = await tools.get_order_status("nope")
        assert missing["success"] is False
        assert "not found" in missing["error"]
        assert missing["order_id"] == "nope"

    @pytest.mark.asyncio
    async def test_get_order_status_returns_error_dict_on_client_failure(self):
        tools, client = build_tools()
        client.get_orders_error = RuntimeError("L2 API credentials required")

        result = await tools.get_order_status("o9")

        assert result["success"] is False
        assert result["error"] == "L2 API credentials required"
        assert result["order_id"] == "o9"


class TestOpenOrders:
    @pytest.mark.asyncio
    async def test_get_open_orders_filters_and_groups_by_market(self):
        tools, client = build_tools()
        client.orders = [
            {"id": "a", "status": "open", "market": "m1"},
            {"id": "b", "status": "live", "market": "m1"},
            {"id": "c", "status": "pending"},  # no 'market' key -> 'unknown'
            {"id": "d", "status": "filled", "market": "m2"},
            {"id": "e", "status": "cancelled", "market": "m2"},
        ]

        result = await tools.get_open_orders()

        # client contract: get_open_orders forwards market=None when unfiltered
        assert client.get_orders_calls[-1] == {"market": None, "asset_id": None}
        assert result["success"] is True
        assert result["total_open_orders"] == 3
        assert result["markets"] == len(result["by_market"])
        assert set(result["by_market"]) == {"m1", "unknown"}
        assert [o["id"] for o in result["by_market"]["m1"]] == ["a", "b"]
        assert result["by_market"]["unknown"][0]["id"] == "c"

        scoped = await tools.get_open_orders(market_id="m1")
        assert client.get_orders_calls[-1] == {"market": "m1", "asset_id": None}
        assert scoped["success"] is True


class TestOrderHistory:
    @pytest.mark.asyncio
    async def test_get_order_history_filters_by_date_and_limit(self):
        tools, client = build_tools()
        client.orders = [
            {"id": "h1", "status": "filled", "size": "10", "price": "0.5",
             "timestamp": "2026-09-10T12:00:00Z"},  # before the window
            {"id": "h2", "status": "filled", "size": "20", "price": "0.5",
             "timestamp": "2026-09-14T10:00:00Z"},  # inside the window
            {"id": "h3", "status": "cancelled", "size": "5", "price": "0.4",
             "timestamp": "2026-09-15T10:00:00Z"},  # inside the window
            {"id": "h4", "status": "filled", "size": "7", "price": "0.3",
             "timestamp": "not-a-date"},  # invalid -> kept via except branch
            {"id": "h5", "status": "cancelled", "size": "3", "price": "0.2"},
            # no timestamp/created_at -> dropped by the date filter
        ]

        # Aware ISO bounds so the comparison against Z-timestamps is clean.
        window = await tools.get_order_history(
            start_date="2026-09-14T00:00:00+00:00",
            end_date="2026-09-15T23:59:59+00:00",
            limit=3,
        )
        assert window["success"] is True
        assert [o["id"] for o in window["orders"]] == ["h2", "h3", "h4"]
        assert window["total_orders"] == 3

        # Limit applies after date filtering.
        clipped = await tools.get_order_history(
            start_date="2026-09-14T00:00:00+00:00",
            end_date="2026-09-15T23:59:59+00:00",
            limit=2,
        )
        assert clipped["total_orders"] == 2
        assert [o["id"] for o in clipped["orders"]] == ["h2", "h3"]

        # Without date bounds nothing is dropped; stats count the [:limit] orders.
        plain = await tools.get_order_history(limit=100)
        assert plain["total_orders"] == 5
        assert plain["filled"] == 3  # h1, h2, h4
        assert plain["cancelled"] == 2  # h3, h5
        expected_volume = 10 * 0.5 + 20 * 0.5 + 5 * 0.4 + 7 * 0.3 + 3 * 0.2
        assert plain["total_volume_usd"] == pytest.approx(expected_volume)


class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_cancel_order_success_and_failure(self):
        tools, client = build_tools()

        ok = await tools.cancel_order("o1")
        assert ok["success"] is True
        assert ok["cancelled"] is True
        assert ok["order_id"] == "o1"
        assert ok["response"] == {"status": "cancelled", "orderID": "o1"}
        assert client.cancel_order_calls == ["o1"]
        parsed = datetime.fromisoformat(ok["timestamp"])
        assert parsed.tzinfo is not None

        client.cancel_order_errors["o2"] = RuntimeError("order already filled")
        bad = await tools.cancel_order("o2")
        assert bad["success"] is False
        assert bad["error"] == "order already filled"
        assert bad["order_id"] == "o2"


class TestCancelMarketOrders:
    @pytest.mark.asyncio
    async def test_cancel_market_orders_cancels_only_open_and_collects_failures(self):
        tools, client = build_tools()
        client.orders = [
            {"id": "o1", "status": "open", "market": "m1"},
            {"orderID": "o2", "status": "live", "market": "m1"},  # cancel fails
            {"id": "o3", "status": "filled", "market": "m1"},  # ignored
        ]
        client.cancel_order_errors["o2"] = RuntimeError("gateway down")

        result = await tools.cancel_market_orders("m1", asset_id="token-1")

        # client contract: both kwargs forwarded (preflight proved the wrapper
        # accepts asset_id=).
        assert client.get_orders_calls[-1] == {"market": "m1", "asset_id": "token-1"}
        assert result["success"] is True
        assert result["cancelled_count"] == 1
        assert result["cancelled_orders"] == ["o1"]
        assert result["failed_count"] == 1
        assert result["failed_orders"] == [
            {"order_id": "o2", "error": "gateway down"}
        ]
        assert client.cancel_order_calls == ["o1", "o2"]

        # No open orders -> friendly message, nothing attempted.
        client.orders = [{"id": "o9", "status": "filled", "market": "m1"}]
        client.cancel_order_calls = []
        quiet = await tools.cancel_market_orders("m1")
        assert quiet["success"] is True
        assert quiet["message"] == "No open orders to cancel"
        assert quiet["cancelled_count"] == 0
        assert client.cancel_order_calls == []


class TestCancelAllOrders:
    @pytest.mark.asyncio
    async def test_cancel_all_orders_counts_dict_and_list_responses(self):
        tools, client = build_tools()

        client.cancel_all_response = {"cancelled": ["a", "b"]}
        first = await tools.cancel_all_orders()
        assert first["success"] is True
        assert first["cancelled_count"] == 2
        assert client.cancel_all_calls == 1

        client.cancel_all_response = ["x"]
        second = await tools.cancel_all_orders()
        assert second["success"] is True
        assert second["cancelled_count"] == 1

        client.cancel_all_response = "weird"
        third = await tools.cancel_all_orders()
        assert third["success"] is True
        assert third["cancelled_count"] == 0

        client.cancel_all_error = RuntimeError("network down")
        client.cancel_all_response = {"cancelled": ["should-not-count"]}
        bad = await tools.cancel_all_orders()
        assert bad["success"] is False
        assert bad["error"] == "network down"


class TestSmartTrade:
    @pytest.mark.asyncio
    async def test_smart_trade_parses_side_and_strategy_from_intent(self, monkeypatch):
        tools, _client = build_tools()
        suggestion = {
            "success": True,
            "suggested_price": 0.5,
            "order_details": {"estimated_fill_probability": 0.9},
        }
        suggest = AsyncMock(return_value=suggestion)
        create_market = AsyncMock(return_value={"success": True, "orderID": "mk-1"})
        create_limit = AsyncMock(return_value={"success": True, "orderID": "lt-1"})
        monkeypatch.setattr(tools, "suggest_order_price", suggest)
        monkeypatch.setattr(tools, "create_market_order", create_market)
        monkeypatch.setattr(tools, "create_limit_order", create_limit)

        # 'now' -> aggressive; fill 0.9 -> single MARKET order with full budget.
        aggressive = await tools.execute_smart_trade(
            market_id="m1", intent="Buy YES now", max_budget=100.0, outcome="Yes"
        )
        assert aggressive["success"] is True
        assert aggressive["strategy"] == "aggressive"
        suggest.assert_called_with(
            market_id="m1", side="BUY", size=100.0,
            strategy="aggressive", outcome="Yes",
        )
        create_market.assert_called_with(
            market_id="m1", side="BUY", size=100.0, outcome="Yes", confirm=False
        )
        assert create_limit.await_count == 0
        assert aggressive["execution_summary"]["total_orders"] == 1
        assert aggressive["execution_summary"]["budget_used"] == 100.0

        # 'good price' -> passive; fill 0.9 > 0.8 -> single LIMIT order.
        passive = await tools.execute_smart_trade(
            market_id="m1", intent="sell at a good price",
            max_budget=100.0, outcome="Yes",
        )
        assert passive["success"] is True
        assert passive["strategy"] == "passive"
        suggest.assert_called_with(
            market_id="m1", side="SELL", size=100.0,
            strategy="passive", outcome="Yes",
        )
        create_limit.assert_called_with(
            market_id="m1", side="SELL", price=0.5, size=100.0,
            order_type="GTC", outcome="Yes", confirm=False,
        )
        assert passive["execution_summary"]["total_orders"] == 1

        # No strategy keyword -> 'mid' (still plans from the suggestion).
        mid = await tools.execute_smart_trade(
            market_id="m1", intent="Buy some", max_budget=50.0, outcome="Yes"
        )
        assert mid["success"] is True
        assert mid["strategy"] == "mid"
        last = suggest.call_args_list[-1]
        assert last.kwargs["strategy"] == "mid"
        assert last.kwargs["size"] == 50.0

        # Unparseable intent -> error dict, no suggestion, no order.
        unclear = await tools.execute_smart_trade(
            market_id="m1", intent="hold everything", max_budget=50.0
        )
        assert unclear["success"] is False
        assert "Cannot determine BUY or SELL" in unclear["error"]
        assert unclear["intent"] == "hold everything"
        assert unclear["max_budget"] == 50.0
        assert suggest.await_count == 3
        assert create_market.await_count == 1  # unchanged since the first call
        assert create_limit.await_count == 2

    @pytest.mark.asyncio
    async def test_smart_trade_splits_low_fill_probability_into_two_limit_orders(
        self, monkeypatch
    ):
        tools, _client = build_tools()
        high_price_suggestion = {
            "success": True,
            "suggested_price": 0.985,
            "order_details": {"estimated_fill_probability": 0.5},
        }
        monkeypatch.setattr(
            tools, "suggest_order_price", AsyncMock(return_value=high_price_suggestion)
        )
        buy_limit = AsyncMock(return_value={"success": True, "orderID": "lt-buy"})
        monkeypatch.setattr(tools, "create_limit_order", buy_limit)
        monkeypatch.setattr(
            tools, "create_market_order", AsyncMock(return_value={"success": True})
        )

        buy = await tools.execute_smart_trade(
            market_id="m1", intent="buy", max_budget=100.0, outcome="Yes"
        )
        assert buy["success"] is True
        assert buy["execution_summary"]["successful"] == 2
        assert buy["execution_summary"]["budget_used"] == 100.0
        assert [c.kwargs["price"] for c in buy_limit.call_args_list] == [0.985, 0.99]
        assert all(c.kwargs["size"] == 50.0 for c in buy_limit.call_args_list)
        assert all(c.kwargs["side"] == "BUY" for c in buy_limit.call_args_list)
        assert all(c.kwargs["order_type"] == "GTC" for c in buy_limit.call_args_list)

        # SELL side: prices step down and clamp at 0.01.
        low_price_suggestion = {
            "success": True,
            "suggested_price": 0.015,
            "order_details": {"estimated_fill_probability": 0.5},
        }
        monkeypatch.setattr(
            tools, "suggest_order_price", AsyncMock(return_value=low_price_suggestion)
        )
        sell_limit = AsyncMock(return_value={"success": True, "orderID": "lt-sell"})
        monkeypatch.setattr(tools, "create_limit_order", sell_limit)
        sell = await tools.execute_smart_trade(
            market_id="m1", intent="sell", max_budget=100.0, outcome="Yes"
        )
        assert sell["success"] is True
        assert [c.kwargs["price"] for c in sell_limit.call_args_list] == [0.015, 0.01]
        assert all(c.kwargs["side"] == "SELL" for c in sell_limit.call_args_list)

        # Second leg fails -> partial execution, half the budget used.
        failing_second = AsyncMock(side_effect=[
            {"success": True, "orderID": "a"},
            {"success": False, "error": "rate limited"},
        ])
        monkeypatch.setattr(
            tools, "suggest_order_price", AsyncMock(return_value=high_price_suggestion)
        )
        monkeypatch.setattr(tools, "create_limit_order", failing_second)
        partial = await tools.execute_smart_trade(
            market_id="m1", intent="buy", max_budget=100.0, outcome="Yes"
        )
        assert partial["success"] is True  # one leg succeeded
        assert partial["execution_summary"]["successful"] == 1
        assert partial["execution_summary"]["failed"] == 1
        assert partial["execution_summary"]["total_value"] == 50.0
        assert partial["execution_summary"]["budget_used"] == 50.0

    @pytest.mark.asyncio
    async def test_smart_trade_reports_price_suggestion_failure(self, monkeypatch):
        tools, _client = build_tools()
        monkeypatch.setattr(
            tools, "suggest_order_price",
            AsyncMock(return_value={"success": False, "error": "no book"}),
        )
        create_market = AsyncMock()
        create_limit = AsyncMock()
        monkeypatch.setattr(tools, "create_market_order", create_market)
        monkeypatch.setattr(tools, "create_limit_order", create_limit)

        result = await tools.execute_smart_trade(
            market_id="m1", intent="buy", max_budget=100.0, outcome="Yes"
        )

        assert result["success"] is False
        assert "Failed to get price suggestion" in result["error"]
        assert "no book" in result["error"]
        assert result["intent"] == "buy"
        assert result["max_budget"] == 100.0
        assert create_market.await_count == 0
        assert create_limit.await_count == 0


class TestRebalancePosition:
    @pytest.mark.asyncio
    async def test_rebalance_position_noop_within_one_dollar(self):
        tools, client = build_tools()
        client.positions = [
            {"market": "m1", "size": "100", "price": "0.5"},  # $50 in m1
            {"market": "m2", "size": "999", "price": "0.9"},  # other market
        ]

        result = await tools.rebalance_position(
            market_id="m1", target_size=50.5, outcome="Yes"
        )

        assert result["success"] is True
        assert result["message"] == "Position already at target"
        assert result["current_size"] == 50.0
        assert result["target_size"] == 50.5
        assert result["adjustment_needed"] == pytest.approx(0.5)
        assert client.get_market_calls == []
        assert client.get_orderbook_calls == []

    @pytest.mark.asyncio
    async def test_rebalance_position_buys_up_and_rejects_slippage(self, monkeypatch):
        tools, client = build_tools()
        client.positions = [{"market": "m1", "size": "100", "price": "0.5"}]  # $50
        client.market = {
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes"},
                {"token_id": "no-token", "outcome": "No"},
            ],
        }
        create_limit = AsyncMock(return_value={"success": True, "orderID": "lt"})
        monkeypatch.setattr(tools, "create_limit_order", create_limit)

        # Balanced book: BUY at the ask is exactly at the default 2% limit and
        # the comparison is '>', so the equal price is ACCEPTED (proven float).
        client.orderbook = {
            "bids": [{"price": "0.49", "size": "100000"}],
            "asks": [{"price": "0.51", "size": "100000"}],
        }
        result = await tools.rebalance_position(
            market_id="m1", target_size=100.0, outcome="Yes"
        )
        create_limit.assert_called_with(
            market_id="m1", side="BUY", price=0.51, size=50.0,
            order_type="GTC", outcome="Yes", confirm=False,
        )
        assert result["success"] is True
        summary = result["rebalance_summary"]
        assert summary["mid_price"] == 0.5
        assert summary["slippage"] == pytest.approx(0.02, abs=1e-9)
        assert summary["side"] == "BUY"
        assert summary["size"] == 50.0
        assert summary["execution_price"] == 0.51

        # Wide ask: expected price is far beyond the tolerated slippage.
        client.orderbook = {
            "bids": [{"price": "0.49", "size": "100000"}],
            "asks": [{"price": "0.60", "size": "100000"}],
        }
        create_limit.reset_mock()
        rejected = await tools.rebalance_position(
            market_id="m1", target_size=100.0, outcome="Yes"
        )
        assert rejected["success"] is False
        assert "Slippage too high" in rejected["error"]
        assert rejected["target_size"] == 100.0
        assert create_limit.await_count == 0

        # Closing the position (target None): SELL at best bid; with the 2%
        # default the bid 0.49 sits exactly at the equality edge — fragile float
        # border (L-0002), so this leg passes a 5% tolerance instead.
        client.orderbook = {
            "bids": [{"price": "0.49", "size": "100000"}],
            "asks": [{"price": "0.51", "size": "100000"}],
        }
        create_limit.reset_mock()
        close = await tools.rebalance_position(
            market_id="m1", target_size=None, max_slippage=0.05, outcome="Yes"
        )
        create_limit.assert_called_with(
            market_id="m1", side="SELL", price=0.49, size=50.0,
            order_type="GTC", outcome="Yes", confirm=False,
        )
        assert close["success"] is True
        assert close["rebalance_summary"]["side"] == "SELL"


class TestConvertPositions:
    def test_convert_positions_skips_malformed_entries(self):
        tools, _client = build_tools()
        raw = [
            {"asset_id": "t", "market": "m", "size": "10", "avg_price": "0.4",
             "current_price": "0.5", "unrealized_pnl": "1"},
            {"asset_id": "bad", "size": "abc"},  # malformed -> skipped with warning
        ]

        positions = tools._convert_positions(raw)

        assert len(positions) == 1
        pos = positions[0]
        assert pos.token_id == "t"
        assert pos.market_id == "m"
        assert pos.size == 10.0
        assert pos.avg_price == 0.4
        assert pos.current_price == 0.5
        assert pos.value_usd == 5.0
        assert pos.unrealized_pnl == 1.0
