"""
Test examples for Polymarket MCP infrastructure.

These examples show how to use the core components.
Run with proper .env configuration.
"""
import asyncio
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_config():
    """Test configuration loading"""
    from polymarket_mcp.config import load_config

    print("\n=== Testing Configuration ===")
    try:
        config = load_config()
        print(f"✓ Config loaded for address: {config.POLYGON_ADDRESS}")
        print(f"✓ Chain ID: {config.POLYMARKET_CHAIN_ID}")
        print(f"✓ Max order size: ${config.MAX_ORDER_SIZE_USD}")
        print(f"✓ Max exposure: ${config.MAX_TOTAL_EXPOSURE_USD}")
        return config
    except Exception as e:
        print(f"✗ Config failed: {e}")
        return None


async def test_client(config):
    """Test Polymarket client initialization"""
    from polymarket_mcp.auth import create_polymarket_client

    print("\n=== Testing Polymarket Client ===")
    try:
        client = create_polymarket_client(
            private_key=config.POLYGON_PRIVATE_KEY,
            address=config.POLYGON_ADDRESS,
            chain_id=config.POLYMARKET_CHAIN_ID,
            api_key=config.POLYMARKET_API_KEY,
            api_secret=config.POLYMARKET_API_SECRET,
        )
        print(f"✓ Client initialized for {client.get_address()}")
        print(f"✓ Has API credentials: {client.has_api_credentials()}")
        return client
    except Exception as e:
        print(f"✗ Client initialization failed: {e}")
        return None


async def test_signer(config):
    """Test order signer"""
    from polymarket_mcp.auth import create_order_signer

    print("\n=== Testing Order Signer ===")
    try:
        signer = create_order_signer(
            private_key=config.POLYGON_PRIVATE_KEY,
            chain_id=config.POLYMARKET_CHAIN_ID
        )
        print(f"✓ Signer initialized for {signer.address}")

        # Test signing a dummy message
        test_order = {
            "salt": 1,
            "maker": signer.address,
            "signer": signer.address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": "12345",
            "makerAmount": "1000000",
            "takerAmount": "1000000",
            "expiration": 0,
            "nonce": 1,
            "feeRateBps": 0,
            "side": 0,
            "signatureType": 0,
        }
        signature = signer.sign_order(test_order)
        print(f"✓ Signature created: {signature[:20]}...")

        # Verify signature
        is_valid = signer.verify_signature(test_order, signature)
        print(f"✓ Signature valid: {is_valid}")

        return signer
    except Exception as e:
        print(f"✗ Signer failed: {e}")
        return None


async def test_rate_limiter():
    """Test rate limiter"""
    from polymarket_mcp.utils import get_rate_limiter, EndpointCategory

    print("\n=== Testing Rate Limiter ===")
    try:
        rate_limiter = get_rate_limiter()
        print("✓ Rate limiter initialized")

        # Test acquiring tokens
        wait_time = await rate_limiter.acquire(EndpointCategory.MARKET_DATA, tokens=1)
        print(f"✓ Acquired tokens (waited {wait_time:.3f}s)")

        # Check status
        status = rate_limiter.get_status()
        print(f"✓ Rate limit status retrieved ({len(status)} categories)")

        # Show market data bucket status
        market_data_status = status.get("market_data")
        if market_data_status:
            print(f"  - Market Data: {market_data_status['available_tokens']}/{market_data_status['max_tokens']} tokens")

        return rate_limiter
    except Exception as e:
        print(f"✗ Rate limiter failed: {e}")
        return None


async def test_safety_limits(config):
    """Test safety limits"""
    from polymarket_mcp.utils import (
        create_safety_limits_from_config,
        OrderRequest,
        Position,
        MarketData
    )

    print("\n=== Testing Safety Limits ===")
    try:
        safety_limits = create_safety_limits_from_config(config)
        print("✓ Safety limits initialized")

        # Create test order
        order = OrderRequest(
            token_id="12345",
            price=0.55,
            size=100.0,
            side="BUY",
            market_id="test_market"
        )
        print(f"✓ Test order created: BUY {order.size} @ {order.price}")

        # Create test market data
        market_data = MarketData(
            market_id="test_market",
            token_id="12345",
            best_bid=0.54,
            best_ask=0.56,
            bid_liquidity=50000.0,
            ask_liquidity=50000.0,
            total_volume=1000000.0
        )
        print(f"✓ Market data: spread={market_data.spread:.2%}, liquidity=${market_data.total_liquidity:,.0f}")

        # Validate order with no positions
        is_valid, error_msg = safety_limits.validate_order(order, [], market_data)
        if is_valid:
            print("✓ Order validation passed")
        else:
            print(f"✗ Order validation failed: {error_msg}")

        # Test confirmation requirement
        needs_confirmation = safety_limits.should_require_confirmation(order, True)
        print(f"✓ Requires confirmation: {needs_confirmation}")

        # Test exposure check
        total_exposure, within_limits = safety_limits.check_exposure([])
        print(f"✓ Current exposure: ${total_exposure:.2f} (within limits: {within_limits})")

        return safety_limits
    except Exception as e:
        print(f"✗ Safety limits failed: {e}")
        return None


async def test_markets(client):
    """Test fetching markets"""
    from polymarket_mcp.utils import get_rate_limiter, EndpointCategory

    print("\n=== Testing Market Data Fetch ===")
    try:
        rate_limiter = get_rate_limiter()

        # Rate limit
        await rate_limiter.acquire(EndpointCategory.MARKET_DATA)

        # Fetch markets
        markets = await client.get_markets(limit=5)
        print(f"✓ Fetched {len(markets)} markets")

        # Show first market
        if markets and len(markets) > 0:
            first_market = markets[0]
            print(f"  - Market: {first_market.get('question', 'N/A')[:60]}...")

        return markets
    except Exception as e:
        print(f"✗ Market fetch failed: {e}")
        return None


async def test_balance(client):
    """Test fetching balance"""
    from polymarket_mcp.utils import get_rate_limiter, EndpointCategory

    print("\n=== Testing Balance Fetch ===")
    try:
        if not client.has_api_credentials():
            print("⚠ Skipping - requires L2 credentials")
            return None

        rate_limiter = get_rate_limiter()
        await rate_limiter.acquire(EndpointCategory.CLOB_GENERAL)

        balance = await client.get_balance()
        print(f"✓ Balance fetched: ${balance}")
        return balance
    except Exception as e:
        print(f"✗ Balance fetch failed: {e}")
        return None


async def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("POLYMARKET MCP INFRASTRUCTURE TESTS")
    print("=" * 60)

    # Test 1: Configuration
    config = await test_config()
    if not config:
        print("\n✗ Cannot continue without config")
        return

    # Test 2: Client
    client = await test_client(config)

    # Test 3: Signer
    signer = await test_signer(config)

    # Test 4: Rate Limiter
    rate_limiter = await test_rate_limiter()

    # Test 5: Safety Limits
    safety_limits = await test_safety_limits(config)

    # Test 6: Markets (if client available)
    if client:
        markets = await test_markets(client)

    # Test 7: Balance (if client has credentials)
    if client:
        balance = await test_balance(client)

    print("\n" + "=" * 60)
    print("TESTS COMPLETE")
    print("=" * 60)

    # Summary
    print("\nSummary:")
    print(f"✓ Config: {'OK' if config else 'FAILED'}")
    print(f"✓ Client: {'OK' if client else 'FAILED'}")
    print(f"✓ Signer: {'OK' if signer else 'FAILED'}")
    print(f"✓ Rate Limiter: {'OK' if rate_limiter else 'FAILED'}")
    print(f"✓ Safety Limits: {'OK' if safety_limits else 'FAILED'}")


if __name__ == "__main__":
    # Run tests
    asyncio.run(run_all_tests())
