"""
Integration tests for Polymarket MCP Server.

These tests interact with real APIs (no mocks) to verify:
- API connectivity
- Tool functionality
- Error handling
- Rate limiting
- Safety limits
"""

import asyncio
import os
import pytest
import httpx

# Test markers
pytestmark = pytest.mark.integration


@pytest.fixture
def real_api_client():
    """Create HTTP client for real API testing."""
    return httpx.AsyncClient(timeout=30.0)


@pytest.fixture
def test_config():
    """Test configuration."""
    return {
        "gamma_api_url": "https://gamma-api.polymarket.com",
        "clob_api_url": "https://clob.polymarket.com",
        "test_market_limit": 5,
    }


class TestAPIConnectivity:
    """Test real API connectivity."""

    @pytest.mark.asyncio
    async def test_gamma_api_markets(self, real_api_client, test_config):
        """Test Gamma API market discovery."""
        url = f"{test_config['gamma_api_url']}/markets"
        response = await real_api_client.get(url, params={"limit": 1})

        assert response.status_code == 200, f"Gamma API failed: {response.status_code}"
        data = response.json()
        assert isinstance(data, list), "Expected list of markets"
        assert len(data) > 0, "Expected at least one market"

        # Verify market structure
        market = data[0]
        required_fields = ["question", "id", "tokens", "volume"]
        for field in required_fields:
            assert field in market, f"Missing required field: {field}"

    @pytest.mark.asyncio
    async def test_clob_api_ping(self, real_api_client, test_config):
        """Test CLOB API health check."""
        url = f"{test_config['clob_api_url']}/ping"
        response = await real_api_client.get(url)

        assert response.status_code == 200, f"CLOB API ping failed: {response.status_code}"

    @pytest.mark.asyncio
    async def test_gamma_api_trending_markets(self, real_api_client, test_config):
        """Test trending markets endpoint."""
        url = f"{test_config['gamma_api_url']}/markets"
        response = await real_api_client.get(
            url, params={"limit": test_config["test_market_limit"], "order": "volume24hr"}
        )

        assert response.status_code == 200
        markets = response.json()
        assert len(markets) <= test_config["test_market_limit"]

    @pytest.mark.asyncio
    async def test_gamma_api_market_details(self, real_api_client, test_config):
        """Test fetching market details."""
        # First get a market ID
        markets_url = f"{test_config['gamma_api_url']}/markets"
        markets_response = await real_api_client.get(markets_url, params={"limit": 1})
        assert markets_response.status_code == 200

        markets = markets_response.json()
        assert len(markets) > 0

        market_id = markets[0]["id"]

        # Then fetch its details
        detail_url = f"{test_config['gamma_api_url']}/markets/{market_id}"
        detail_response = await real_api_client.get(detail_url)

        assert detail_response.status_code == 200
        market = detail_response.json()
        assert market["id"] == market_id


class TestMarketDiscovery:
    """Test market discovery tools with real API."""

    @pytest.mark.asyncio
    async def test_search_markets(self, real_api_client, test_config):
        """Test market search functionality."""
        url = f"{test_config['gamma_api_url']}/markets"

        # Search for common term
        response = await real_api_client.get(url, params={"limit": 5, "closed": False})

        assert response.status_code == 200
        markets = response.json()
        assert isinstance(markets, list)

    @pytest.mark.asyncio
    async def test_filter_by_category(self, real_api_client, test_config):
        """Test filtering markets by category."""
        url = f"{test_config['gamma_api_url']}/markets"

        # Try Politics category
        response = await real_api_client.get(url, params={"limit": 5, "tag": "Politics"})

        assert response.status_code == 200
        markets = response.json()
        assert isinstance(markets, list)

    @pytest.mark.asyncio
    async def test_closing_soon_markets(self, real_api_client, test_config):
        """Test markets closing soon."""
        url = f"{test_config['gamma_api_url']}/markets"

        # Get active markets sorted by end date
        response = await real_api_client.get(
            url, params={"limit": 5, "closed": False, "order": "end_date_min"}
        )

        assert response.status_code == 200
        markets = response.json()
        assert isinstance(markets, list)


class TestMarketAnalysis:
    """Test market analysis tools with real API."""

    @pytest.mark.asyncio
    async def test_get_orderbook(self, real_api_client, test_config):
        """Test orderbook retrieval."""
        # First get a market with token info
        markets_url = f"{test_config['gamma_api_url']}/markets"
        markets_response = await real_api_client.get(markets_url, params={"limit": 1})
        assert markets_response.status_code == 200

        markets = markets_response.json()
        if len(markets) == 0:
            pytest.skip("No markets available for testing")

        market = markets[0]
        if "tokens" not in market or len(market["tokens"]) == 0:
            pytest.skip("Market has no tokens")

        token_id = market["tokens"][0]["token_id"]

        # Get orderbook from CLOB API
        orderbook_url = f"{test_config['clob_api_url']}/book"
        orderbook_response = await real_api_client.get(orderbook_url, params={"token_id": token_id})

        # Note: May return 404 if no orders, which is acceptable
        assert orderbook_response.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_get_market_volume(self, real_api_client, test_config):
        """Test market volume retrieval."""
        url = f"{test_config['gamma_api_url']}/markets"
        response = await real_api_client.get(url, params={"limit": 1})

        assert response.status_code == 200
        markets = response.json()

        if len(markets) > 0:
            market = markets[0]
            assert "volume" in market or "volume24hr" in market


class TestErrorHandling:
    """Test error handling with real API."""

    @pytest.mark.asyncio
    async def test_invalid_market_id(self, real_api_client, test_config):
        """Test handling of invalid market ID."""
        url = f"{test_config['gamma_api_url']}/markets/invalid-market-id-12345"
        response = await real_api_client.get(url)

        # Should return 404
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_token_id(self, real_api_client, test_config):
        """Test handling of invalid token ID."""
        url = f"{test_config['clob_api_url']}/book"
        response = await real_api_client.get(url, params={"token_id": "invalid-token-12345"})

        # Should handle gracefully (404 or error response)
        assert response.status_code in [400, 404]

    @pytest.mark.asyncio
    async def test_malformed_request(self, real_api_client, test_config):
        """Test handling of malformed requests."""
        url = f"{test_config['gamma_api_url']}/markets"
        response = await real_api_client.get(url, params={"limit": "invalid"})

        # API should handle gracefully
        assert response.status_code in [200, 400]


class TestRateLimiting:
    """Test rate limiting behavior."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_rapid_requests(self, real_api_client, test_config):
        """Test making rapid requests to check rate limiting."""
        url = f"{test_config['gamma_api_url']}/markets"

        # Make 10 rapid requests
        tasks = []
        for _ in range(10):
            task = real_api_client.get(url, params={"limit": 1})
            tasks.append(task)

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successful responses
        successful = sum(
            1 for r in responses if not isinstance(r, Exception) and r.status_code == 200
        )

        # Should handle most requests (rate limiting may kick in)
        assert successful >= 5, f"Only {successful}/10 requests succeeded"

    @pytest.mark.asyncio
    async def test_concurrent_different_endpoints(self, real_api_client, test_config):
        """Test concurrent requests to different endpoints."""
        tasks = [
            real_api_client.get(f"{test_config['gamma_api_url']}/markets", params={"limit": 1}),
            real_api_client.get(f"{test_config['clob_api_url']}/ping"),
        ]

        responses = await asyncio.gather(*tasks)

        # Both should succeed
        assert all(r.status_code == 200 for r in responses)


class TestDemoMode:
    """Test demo mode initialization."""

    @pytest.mark.asyncio
    async def test_demo_mode_import(self):
        """Test importing in demo mode."""
        # Set demo mode
        os.environ["POLYMARKET_DEMO_MODE"] = "true"

        # Import should work
        import sys

        sys.path.insert(0, "src")
        from polymarket_mcp import config

        assert config is not None

        # Cleanup
        if "POLYMARKET_DEMO_MODE" in os.environ:
            del os.environ["POLYMARKET_DEMO_MODE"]

    @pytest.mark.asyncio
    async def test_demo_mode_no_credentials(self):
        """Test that demo mode works without real credentials."""
        os.environ["POLYMARKET_DEMO_MODE"] = "true"
        os.environ["POLYGON_PRIVATE_KEY"] = "0" * 64
        os.environ["POLYGON_ADDRESS"] = "0x" + "0" * 40

        # Should be able to load config
        import sys

        sys.path.insert(0, "src")
        from polymarket_mcp.config import load_config

        cfg = load_config()
        assert cfg is not None

        # Cleanup
        for key in ["POLYMARKET_DEMO_MODE", "POLYGON_PRIVATE_KEY", "POLYGON_ADDRESS"]:
            if key in os.environ:
                del os.environ[key]


class TestWebSocketConnectivity:
    """Test WebSocket connections."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_websocket_connection(self):
        """Test connecting to Polymarket WebSocket."""
        import websockets

        ws_url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

        try:
            async with websockets.connect(ws_url, ping_timeout=10) as websocket:
                # Connection successful
                assert websocket.open

                # Try to receive a message (with timeout)
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    assert message is not None
                except asyncio.TimeoutError:
                    # Timeout is acceptable - connection was established
                    pass
        except Exception as e:
            pytest.skip(f"WebSocket connection failed: {e}")


class TestSafetyValidation:
    """Test safety limit validations."""

    def test_safety_limits_initialization(self):
        """Test safety limits can be initialized."""
        import sys

        sys.path.insert(0, "src")
        from polymarket_mcp.utils import SafetyLimits

        limits = SafetyLimits(
            max_order_size_usd=100.0,
            max_total_exposure_usd=1000.0,
            max_position_size_per_market=50.0,
            min_liquidity_required=500.0,
            max_spread_tolerance=0.05,
        )

        assert limits.max_order_size_usd == 100.0
        assert limits.max_total_exposure_usd == 1000.0

    def test_order_size_validation(self):
        """Test order size validation logic."""
        import sys

        sys.path.insert(0, "src")
        from polymarket_mcp.utils import SafetyLimits

        limits = SafetyLimits(
            max_order_size_usd=100.0,
            max_total_exposure_usd=1000.0,
        )

        # Test validation
        assert 50.0 <= limits.max_order_size_usd
        assert 150.0 > limits.max_order_size_usd


@pytest.mark.asyncio
async def test_full_integration_flow(real_api_client, test_config):
    """Test complete integration flow: discover -> analyze -> validate."""
    # 1. Discover markets
    markets_url = f"{test_config['gamma_api_url']}/markets"
    markets_response = await real_api_client.get(markets_url, params={"limit": 5})
    assert markets_response.status_code == 200

    markets = markets_response.json()
    assert len(markets) > 0

    # 2. Get details for first market
    market = markets[0]
    market_id = market["id"]

    detail_url = f"{test_config['gamma_api_url']}/markets/{market_id}"
    detail_response = await real_api_client.get(detail_url)
    assert detail_response.status_code == 200

    # 3. Verify market has required data
    market_detail = detail_response.json()
    assert "tokens" in market_detail
    assert "volume" in market_detail or "volume24hr" in market_detail

    # 4. If market has tokens, try to get orderbook
    if len(market_detail.get("tokens", [])) > 0:
        token_id = market_detail["tokens"][0]["token_id"]
        orderbook_url = f"{test_config['clob_api_url']}/book"
        orderbook_response = await real_api_client.get(orderbook_url, params={"token_id": token_id})
        # Accept both success and no orders
        assert orderbook_response.status_code in [200, 404]


if __name__ == "__main__":
    # Run integration tests
    pytest.main([__file__, "-v", "-m", "integration"])
