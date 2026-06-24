"""
Deterministic, offline tests for the safety fixes:
  - Real confirmation gate (orders are NOT placed without confirm=true)
  - Correct YES/NO outcome token selection (no more blind tokens[0])

Run directly:  python tests/test_safety_fixes.py
Or via pytest:  pytest tests/test_safety_fixes.py
"""
import asyncio
from types import SimpleNamespace

from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.safety_limits import SafetyLimits


class FakeClient:
    """Minimal async stand-in for PolymarketClient (no network)."""

    def __init__(self):
        self.post_calls = []

    async def get_market(self, market_id):
        return {
            "tokens": [
                {"token_id": "tok_yes", "outcome": "Yes"},
                {"token_id": "tok_no", "outcome": "No"},
            ],
            "volume": 100000,
        }

    async def get_orderbook(self, token_id):
        return {
            "bids": [{"price": "0.49", "size": "1000"}],
            "asks": [{"price": "0.51", "size": "1000"}],
        }

    async def get_positions(self):
        return []

    async def post_order(self, **kwargs):
        self.post_calls.append(kwargs)
        return {"orderID": "ORDER-123", "status": "submitted"}


def _make_tools(autonomous: bool):
    client = FakeClient()
    limits = SafetyLimits(
        max_order_size_usd=1000,
        max_total_exposure_usd=5000,
        max_position_size_per_market=2000,
        min_liquidity_required=100,
        max_spread_tolerance=0.05,
        require_confirmation_above_usd=500,
        auto_cancel_on_large_spread=True,
    )
    config = SimpleNamespace(
        ENABLE_AUTONOMOUS_TRADING=autonomous,
        REQUIRE_CONFIRMATION_ABOVE_USD=500,
    )
    return TradingTools(client=client, safety_limits=limits, config=config), client


def test_select_token():
    tools, _ = _make_tools(autonomous=True)
    market = {"tokens": [
        {"token_id": "tok_yes", "outcome": "Yes"},
        {"token_id": "tok_no", "outcome": "No"},
    ]}
    assert tools._select_token(market, None) == ("tok_yes", "Yes")
    assert tools._select_token(market, "YES") == ("tok_yes", "Yes")
    assert tools._select_token(market, "no") == ("tok_no", "No")
    assert tools._select_token(market, "No")[0] == "tok_no"
    try:
        tools._select_token(market, "banana")
        raise AssertionError("expected ValueError for unknown outcome")
    except ValueError:
        pass
    print("PASS test_select_token")


def test_confirmation_blocks_without_confirm():
    """autonomous=False -> even a tiny order must NOT be placed without confirm=true."""
    tools, client = _make_tools(autonomous=False)
    result = asyncio.run(tools.create_limit_order(
        market_id="0xMARKET", side="BUY", price=0.5, size=10, outcome="NO"
    ))
    assert result["success"] is False, result
    assert result["status"] == "confirmation_required", result
    assert client.post_calls == [], "order must NOT have been posted"
    assert result["pending_order"]["outcome"] == "No"
    print("PASS test_confirmation_blocks_without_confirm")


def test_confirm_true_executes_and_uses_no_token():
    """confirm=true -> order is posted, and it trades the NO token (not tokens[0])."""
    tools, client = _make_tools(autonomous=False)
    result = asyncio.run(tools.create_limit_order(
        market_id="0xMARKET", side="BUY", price=0.5, size=10, outcome="NO", confirm=True
    ))
    assert result["success"] is True, result
    assert len(client.post_calls) == 1, "order should have been posted exactly once"
    assert client.post_calls[0]["token_id"] == "tok_no", client.post_calls[0]
    assert result["details"]["outcome"] == "No"
    print("PASS test_confirm_true_executes_and_uses_no_token")


def test_autonomous_small_order_no_confirm_needed():
    """autonomous=True + below threshold -> executes without confirm."""
    tools, client = _make_tools(autonomous=True)
    result = asyncio.run(tools.create_limit_order(
        market_id="0xMARKET", side="BUY", price=0.5, size=10
    ))
    assert result["success"] is True, result
    assert len(client.post_calls) == 1
    assert client.post_calls[0]["token_id"] == "tok_yes"  # default outcome
    print("PASS test_autonomous_small_order_no_confirm_needed")


if __name__ == "__main__":
    test_select_token()
    test_confirmation_blocks_without_confirm()
    test_confirm_true_executes_and_uses_no_token()
    test_autonomous_small_order_no_confirm_needed()
    print("\nALL SAFETY-FIX TESTS PASSED")
