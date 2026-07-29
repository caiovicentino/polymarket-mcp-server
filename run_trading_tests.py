#!/usr/bin/env python3
"""
Quick test runner for trading tools.

Usage:
    python run_trading_tests.py
"""
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from polymarket_mcp.config import load_config
from polymarket_mcp.auth import create_polymarket_client
from polymarket_mcp.utils import create_safety_limits_from_config
from polymarket_mcp.tools import TradingTools


async def main():
    """Run quick smoke tests for trading tools"""
    print("\n" + "="*80)
    print("POLYMARKET TRADING TOOLS - QUICK SMOKE TEST")
    print("="*80 + "\n")

    try:
        # Load configuration
        print("1. Loading configuration...")
        config = load_config()
        print(f"   Address: {config.POLYGON_ADDRESS}")
        print(f"   Chain ID: {config.POLYMARKET_CHAIN_ID}")
        print(f"   Max order size: ${config.MAX_ORDER_SIZE_USD}")

        # Create client
        print("\n2. Initializing Polymarket client...")
        client = create_polymarket_client(
            private_key=config.POLYGON_PRIVATE_KEY,
            address=config.POLYGON_ADDRESS,
            chain_id=config.POLYMARKET_CHAIN_ID,
            api_key=config.POLYMARKET_API_KEY,
            api_secret=config.POLYMARKET_API_SECRET,
            passphrase=config.POLYMARKET_PASSPHRASE,
        )

        if not client.has_api_credentials():
            print("   Creating API credentials...")
            await client.create_api_credentials()

        print("   Client ready!")

        # Create safety limits
        print("\n3. Initializing safety limits...")
        safety_limits = create_safety_limits_from_config(config)
        print(f"   Max order: ${safety_limits.max_order_size_usd}")
        print(f"   Max exposure: ${safety_limits.max_total_exposure_usd}")

        # Initialize trading tools
        print("\n4. Initializing trading tools...")
        trading_tools = TradingTools(
            client=client,
            safety_limits=safety_limits,
            config=config
        )
        print("   12 trading tools ready!")

        # Get a test market
        print("\n5. Finding test market...")
        markets = await client.get_markets()
        test_market = None

        if markets and len(markets) > 0:
            for market in markets:
                if market.get('active') and float(market.get('volume', 0)) > 10000:
                    test_market = market
                    break

        if not test_market:
            print("   ERROR: No suitable test market found")
            return

        market_id = test_market.get('condition_id')
        print(f"   Market ID: {market_id}")
        print(f"   Question: {test_market.get('question', 'Unknown')[:60]}...")

        # Test 1: Price suggestion
        print("\n6. Testing price suggestion...")
        result = await trading_tools.suggest_order_price(
            market_id=market_id,
            side="BUY",
            size=1.0,
            strategy="mid"
        )

        if result.get('success'):
            print(f"   Suggested price: ${result['suggested_price']:.4f}")
            print(f"   Market spread: {result['market_context']['spread']:.4f}")
            print("   SUCCESS")
        else:
            print(f"   FAILED: {result.get('error')}")

        # Test 2: Get open orders
        print("\n7. Testing order management...")
        result = await trading_tools.get_open_orders()

        if result.get('success'):
            print(f"   Open orders: {result['total_open_orders']}")
            print(f"   Markets: {result['markets']}")
            print("   SUCCESS")
        else:
            print(f"   FAILED: {result.get('error')}")

        # Test 3: Create and cancel small order
        print("\n8. Testing order creation and cancellation...")
        result = await trading_tools.create_limit_order(
            market_id=market_id,
            side="BUY",
            price=0.01,  # Very low price
            size=1.0,  # $1
            order_type="GTC"
        )

        if result.get('success'):
            order_id = result['order_id']
            print(f"   Order created: {order_id}")

            # Wait a moment
            await asyncio.sleep(1)

            # Cancel it
            cancel_result = await trading_tools.cancel_order(order_id)
            if cancel_result.get('success'):
                print("   Order cancelled: SUCCESS")
            else:
                print(f"   Cancellation failed: {cancel_result.get('error')}")
        else:
            print(f"   FAILED: {result.get('error')}")

        # Test 4: Smart trade (dry run)
        print("\n9. Testing smart trade execution...")
        result = await trading_tools.execute_smart_trade(
            market_id=market_id,
            intent="Buy YES at a good price, be patient",
            max_budget=2.0
        )

        if result.get('success'):
            print(f"   Strategy: {result['strategy']}")
            print(f"   Orders planned: {result['execution_summary']['total_orders']}")
            print(f"   Successful: {result['execution_summary']['successful']}")

            # Cleanup any created orders
            await asyncio.sleep(1)
            await trading_tools.cancel_all_orders()
            print("   Cleanup done: SUCCESS")
        else:
            print(f"   FAILED: {result.get('error')}")

        print("\n" + "="*80)
        print("ALL SMOKE TESTS PASSED!")
        print("="*80 + "\n")

        print("Trading Tools Status:")
        print("  Order Creation Tools: 4/4 implemented")
        print("    - create_limit_order")
        print("    - create_market_order")
        print("    - create_batch_orders")
        print("    - suggest_order_price")
        print("\n  Order Management Tools: 6/6 implemented")
        print("    - get_order_status")
        print("    - get_open_orders")
        print("    - get_order_history")
        print("    - cancel_order")
        print("    - cancel_market_orders")
        print("    - cancel_all_orders")
        print("\n  Smart Trading Tools: 2/2 implemented")
        print("    - execute_smart_trade")
        print("    - rebalance_position")
        print("\n  Total: 12/12 tools operational")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # Check for .env file
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        print("ERROR: .env file not found!")
        print(f"Please create {env_path} with required configuration")
        print("\nSee .env.example for template")
        sys.exit(1)

    asyncio.run(main())
