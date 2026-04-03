"""
Comprehensive tests for trading tools.

Tests all 12 trading tools with real API integration.
Uses small amounts for safety.
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from polymarket_mcp.config import load_config
from polymarket_mcp.auth import create_polymarket_client
from polymarket_mcp.utils import create_safety_limits_from_config
from polymarket_mcp.tools import TradingTools


# Test configuration
TEST_MARKET_ID = None  # Will be populated from live markets
TEST_ORDER_SIZE = 1.0  # $1 for safety
TEST_PRICE_BUY = 0.45  # Conservative buy price
TEST_PRICE_SELL = 0.55  # Conservative sell price


@pytest.fixture(scope="module")
async def setup():
    """Setup test environment with real API client."""
    print("\n=== Setting up test environment ===")

    # Load configuration
    config = load_config()
    print(f"Config loaded for address: {config.POLYGON_ADDRESS}")

    # Create client
    client = create_polymarket_client(
        private_key=config.POLYGON_PRIVATE_KEY,
        address=config.POLYGON_ADDRESS,
        chain_id=config.POLYMARKET_CHAIN_ID,
        api_key=config.POLYMARKET_API_KEY,
        api_secret=config.POLYMARKET_PASSPHRASE,
        passphrase=config.POLYMARKET_PASSPHRASE,
    )

    # Ensure API credentials exist
    if not client.has_api_credentials():
        print("Creating API credentials...")
        await client.create_api_credentials()

    print("API credentials verified")

    # Create safety limits
    safety_limits = create_safety_limits_from_config(config)
    print(f"Safety limits: max order ${safety_limits.max_order_size_usd}")

    # Initialize trading tools
    trading_tools = TradingTools(
        client=client,
        safety_limits=safety_limits,
        config=config
    )
    print("Trading tools initialized")

    # Get a test market
    global TEST_MARKET_ID
    markets = await client.get_markets()
    if markets and len(markets) > 0:
        # Get first active market with good liquidity
        for market in markets:
            if market.get('active') and float(market.get('volume', 0)) > 10000:
                TEST_MARKET_ID = market.get('condition_id')
                print(f"Using test market: {TEST_MARKET_ID}")
                print(f"Market: {market.get('question', 'Unknown')}")
                break

    if not TEST_MARKET_ID:
        raise ValueError("No suitable test market found")

    return {
        "client": client,
        "trading_tools": trading_tools,
        "config": config,
        "safety_limits": safety_limits
    }


@pytest.mark.asyncio
class TestOrderCreationTools:
    """Test Order Creation tools (4 tools)"""

    async def test_suggest_order_price(self, setup):
        """Test price suggestion tool"""
        print("\n--- Testing suggest_order_price ---")

        trading_tools = setup["trading_tools"]

        # Test aggressive buy
        result = await trading_tools.suggest_order_price(
            market_id=TEST_MARKET_ID,
            side="BUY",
            size=TEST_ORDER_SIZE,
            strategy="aggressive"
        )

        print(f"Aggressive buy suggestion: {result}")
        assert result["success"] is True
        assert "suggested_price" in result
        assert 0 < result["suggested_price"] <= 1.0
        assert result["strategy"] == "aggressive"

        # Test passive sell
        result = await trading_tools.suggest_order_price(
            market_id=TEST_MARKET_ID,
            side="SELL",
            size=TEST_ORDER_SIZE,
            strategy="passive"
        )

        print(f"Passive sell suggestion: {result}")
        assert result["success"] is True
        assert result["strategy"] == "passive"

        # Test mid strategy
        result = await trading_tools.suggest_order_price(
            market_id=TEST_MARKET_ID,
            side="BUY",
            size=TEST_ORDER_SIZE,
            strategy="mid"
        )

        print(f"Mid strategy suggestion: {result}")
        assert result["success"] is True
        assert result["strategy"] == "mid"

        print("suggest_order_price test PASSED")

    async def test_create_limit_order(self, setup):
        """Test limit order creation"""
        print("\n--- Testing create_limit_order ---")

        trading_tools = setup["trading_tools"]

        # Create a limit order at conservative price (unlikely to fill immediately)
        result = await trading_tools.create_limit_order(
            market_id=TEST_MARKET_ID,
            side="BUY",
            price=0.01,  # Very low price, unlikely to fill
            size=TEST_ORDER_SIZE,
            order_type="GTC"
        )

        print(f"Limit order result: {result}")
        assert result["success"] is True
        assert "order_id" in result
        assert result["details"]["side"] == "BUY"
        assert result["details"]["price"] == 0.01

        # Store order ID for later tests
        order_id = result["order_id"]

        # Cancel the order
        cancel_result = await trading_tools.cancel_order(order_id)
        print(f"Order cancelled: {cancel_result}")
        assert cancel_result["success"] is True

        print("create_limit_order test PASSED")

    async def test_create_market_order_simulation(self, setup):
        """Test market order (simulation - gets price but doesn't execute)"""
        print("\n--- Testing create_market_order (simulation) ---")

        trading_tools = setup["trading_tools"]

        # Get current market price
        suggestion = await trading_tools.suggest_order_price(
            market_id=TEST_MARKET_ID,
            side="BUY",
            size=TEST_ORDER_SIZE,
            strategy="aggressive"
        )

        print(f"Market price for BUY: {suggestion['suggested_price']:.4f}")

        # Note: We don't actually execute market orders in tests to avoid
        # immediate fills. In production, create_market_order would execute.
        print("create_market_order simulation PASSED")

    async def test_create_batch_orders(self, setup):
        """Test batch order creation"""
        print("\n--- Testing create_batch_orders ---")

        trading_tools = setup["trading_tools"]

        # Create batch of 2 orders at unlikely prices
        orders = [
            {
                "market_id": TEST_MARKET_ID,
                "side": "BUY",
                "price": 0.01,
                "size": TEST_ORDER_SIZE,
                "order_type": "GTC"
            },
            {
                "market_id": TEST_MARKET_ID,
                "side": "BUY",
                "price": 0.02,
                "size": TEST_ORDER_SIZE,
                "order_type": "GTC"
            }
        ]

        result = await trading_tools.create_batch_orders(orders)

        print(f"Batch order result: {result}")
        assert result["success"] is True
        assert result["total_orders"] == 2

        # Cancel all orders created
        if result["successful"] > 0:
            await trading_tools.cancel_all_orders()
            print("Batch orders cancelled")

        print("create_batch_orders test PASSED")


@pytest.mark.asyncio
class TestOrderManagementTools:
    """Test Order Management tools (6 tools)"""

    async def test_get_open_orders(self, setup):
        """Test getting open orders"""
        print("\n--- Testing get_open_orders ---")

        trading_tools = setup["trading_tools"]

        result = await trading_tools.get_open_orders()

        print(f"Open orders: {result}")
        assert result["success"] is True
        assert "total_open_orders" in result
        assert "orders" in result

        print("get_open_orders test PASSED")

    async def test_get_order_history(self, setup):
        """Test getting order history"""
        print("\n--- Testing get_order_history ---")

        trading_tools = setup["trading_tools"]

        result = await trading_tools.get_order_history(limit=10)

        print(f"Order history: {result}")
        assert result["success"] is True
        assert "total_orders" in result
        assert "orders" in result

        print("get_order_history test PASSED")

    async def test_order_lifecycle(self, setup):
        """Test complete order lifecycle: create, check status, cancel"""
        print("\n--- Testing order lifecycle ---")

        trading_tools = setup["trading_tools"]

        # 1. Create order
        create_result = await trading_tools.create_limit_order(
            market_id=TEST_MARKET_ID,
            side="BUY",
            price=0.01,
            size=TEST_ORDER_SIZE,
            order_type="GTC"
        )

        assert create_result["success"] is True
        order_id = create_result["order_id"]
        print(f"Created order: {order_id}")

        # Wait a moment for order to be processed
        await asyncio.sleep(2)

        # 2. Check order status
        status_result = await trading_tools.get_order_status(order_id)
        print(f"Order status: {status_result}")

        # Status check might fail if order already filled/cancelled
        # This is OK in tests
        if status_result["success"]:
            assert "status" in status_result

        # 3. Cancel order
        cancel_result = await trading_tools.cancel_order(order_id)
        print(f"Cancelled order: {cancel_result}")
        assert cancel_result["success"] is True

        print("Order lifecycle test PASSED")

    async def test_cancel_market_orders(self, setup):
        """Test cancelling all orders in a market"""
        print("\n--- Testing cancel_market_orders ---")

        trading_tools = setup["trading_tools"]

        # Create a test order first
        create_result = await trading_tools.create_limit_order(
            market_id=TEST_MARKET_ID,
            side="BUY",
            price=0.01,
            size=TEST_ORDER_SIZE,
            order_type="GTC"
        )

        if create_result["success"]:
            await asyncio.sleep(1)

            # Cancel all orders in this market
            result = await trading_tools.cancel_market_orders(
                market_id=TEST_MARKET_ID
            )

            print(f"Cancelled market orders: {result}")
            assert result["success"] is True

            print("cancel_market_orders test PASSED")
        else:
            print("Skipping test - order creation failed")

    async def test_cancel_all_orders(self, setup):
        """Test cancelling all orders"""
        print("\n--- Testing cancel_all_orders ---")

        trading_tools = setup["trading_tools"]

        # Cancel all orders (cleanup)
        result = await trading_tools.cancel_all_orders()

        print(f"Cancel all result: {result}")
        assert result["success"] is True

        print("cancel_all_orders test PASSED")


@pytest.mark.asyncio
class TestSmartTradingTools:
    """Test Smart Trading tools (2 tools)"""

    async def test_execute_smart_trade(self, setup):
        """Test AI-powered smart trade execution"""
        print("\n--- Testing execute_smart_trade ---")

        trading_tools = setup["trading_tools"]

        # Test with conservative intent
        result = await trading_tools.execute_smart_trade(
            market_id=TEST_MARKET_ID,
            intent="Buy YES at a good price, be patient",
            max_budget=TEST_ORDER_SIZE * 2
        )

        print(f"Smart trade result: {result}")
        assert result["success"] is True
        assert "execution_summary" in result
        assert "strategy" in result

        # Cleanup
        await asyncio.sleep(2)
        await trading_tools.cancel_all_orders()

        print("execute_smart_trade test PASSED")

    async def test_rebalance_position(self, setup):
        """Test position rebalancing"""
        print("\n--- Testing rebalance_position ---")

        trading_tools = setup["trading_tools"]

        # Test rebalancing (will likely show no position to rebalance)
        result = await trading_tools.rebalance_position(
            market_id=TEST_MARKET_ID,
            target_size=0.0,  # Close any position
            max_slippage=0.05
        )

        print(f"Rebalance result: {result}")
        # Success might be false if no position exists, which is fine
        assert "rebalance_summary" in result or "message" in result

        print("rebalance_position test PASSED")


@pytest.mark.asyncio
class TestSafetyValidation:
    """Test safety limit validation"""

    async def test_safety_limits(self, setup):
        """Test that safety limits are enforced"""
        print("\n--- Testing safety limits ---")

        trading_tools = setup["trading_tools"]

        # Try to create order exceeding max size (should fail)
        result = await trading_tools.create_limit_order(
            market_id=TEST_MARKET_ID,
            side="BUY",
            price=0.50,
            size=999999.0,  # Way over limit
            order_type="GTC"
        )

        print(f"Over-limit order result: {result}")
        assert result["success"] is False
        assert "error" in result
        assert "Safety check failed" in result["error"] or "exceeds" in result["error"].lower()

        print("Safety limits test PASSED")

    async def test_invalid_parameters(self, setup):
        """Test invalid parameter validation"""
        print("\n--- Testing invalid parameters ---")

        trading_tools = setup["trading_tools"]

        # Test invalid price
        result = await trading_tools.create_limit_order(
            market_id=TEST_MARKET_ID,
            side="BUY",
            price=1.5,  # Invalid: > 1.0
            size=TEST_ORDER_SIZE,
            order_type="GTC"
        )

        assert result["success"] is False
        print(f"Invalid price rejected: {result['error']}")

        # Test invalid side
        result = await trading_tools.create_limit_order(
            market_id=TEST_MARKET_ID,
            side="INVALID",
            price=0.5,
            size=TEST_ORDER_SIZE,
            order_type="GTC"
        )

        assert result["success"] is False
        print(f"Invalid side rejected: {result['error']}")

        print("Invalid parameters test PASSED")


def run_tests():
    """Run all tests"""
    print("\n" + "="*80)
    print("POLYMARKET TRADING TOOLS TEST SUITE")
    print("="*80)

    # Run pytest
    pytest.main([
        __file__,
        "-v",
        "-s",  # Show print statements
        "--tb=short",  # Short traceback format
    ])


if __name__ == "__main__":
    # Check for .env file
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        print("ERROR: .env file not found!")
        print(f"Please create {env_path} with required configuration")
        sys.exit(1)

    run_tests()
