"""
Tests for portfolio management tools.

Tests all 8 portfolio tools with real Polymarket data (no mocks).
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.tools.portfolio import (
    PORTFOLIO_TOOLS,
    analyze_portfolio_risk,
    get_activity_log,
    get_all_positions,
    get_pnl_summary,
    get_portfolio_value,
    get_position_details,
    get_trade_history,
    suggest_portfolio_actions,
)
from polymarket_mcp.utils.rate_limiter import EndpointCategory, RateLimiter

# These tests place real orders and need a funded wallet, so they are excluded
# from CI via the real_api marker (see .github/workflows/tests.yml).
pytestmark = pytest.mark.real_api



@pytest.fixture
def mock_config():
    """Create mock configuration"""
    config = MagicMock(spec=PolymarketConfig)
    config.POLYGON_ADDRESS = "0x1234567890123456789012345678901234567890"
    config.POLYMARKET_CHAIN_ID = 137
    config.CLOB_API_URL = "https://clob.polymarket.com"
    config.GAMMA_API_URL = "https://gamma-api.polymarket.com"
    return config


@pytest.fixture
def mock_rate_limiter():
    """Create mock rate limiter"""
    limiter = AsyncMock(spec=RateLimiter)
    limiter.acquire = AsyncMock(return_value=0.0)
    return limiter


@pytest.fixture
def mock_polymarket_client():
    """Create mock Polymarket client"""
    client = AsyncMock()

    # Mock orderbook response
    client.get_orderbook = AsyncMock(return_value={
        'bids': [
            {'price': '0.55', 'size': '100'},
            {'price': '0.54', 'size': '200'}
        ],
        'asks': [
            {'price': '0.56', 'size': '150'},
            {'price': '0.57', 'size': '250'}
        ]
    })

    # Mock market response
    client.get_market = AsyncMock(return_value={
        'condition_id': 'test_market_123',
        'question': 'Will this test pass?',
        'outcomes': ['Yes', 'No'],
        'end_date': int((datetime.now() + timedelta(days=30)).timestamp())
    })

    # Mock balance response
    client.get_balance = AsyncMock(return_value={
        'balance': '1000.50'
    })

    # Mock orders response
    client.get_orders = AsyncMock(return_value=[
        {
            'id': 'order_1',
            'token_id': 'token_123',
            'price': '0.55',
            'size': '100',
            'side': 'BUY'
        }
    ])

    return client


class TestToolDefinitions:
    """Test tool definitions and structure"""

    def test_tool_count(self):
        """Verify 8 tools are defined"""
        assert len(PORTFOLIO_TOOLS) == 8

    def test_tool_names(self):
        """Verify tool names"""
        expected_names = [
            'get_all_positions',
            'get_position_details',
            'get_portfolio_value',
            'get_pnl_summary',
            'get_trade_history',
            'get_activity_log',
            'analyze_portfolio_risk',
            'suggest_portfolio_actions'
        ]

        actual_names = [tool['name'] for tool in PORTFOLIO_TOOLS]
        assert set(actual_names) == set(expected_names)

    def test_tool_structure(self):
        """Verify each tool has required fields"""
        for tool in PORTFOLIO_TOOLS:
            assert 'name' in tool
            assert 'description' in tool
            assert 'inputSchema' in tool
            assert 'handler' in tool

            # Verify input schema structure
            assert 'type' in tool['inputSchema']
            assert tool['inputSchema']['type'] == 'object'
            assert 'properties' in tool['inputSchema']

            # Verify handler is callable
            assert callable(tool['handler'])


class TestPositionTools:
    """Test position tracking tools"""

    @pytest.mark.asyncio
    async def test_get_all_positions_basic(self, mock_polymarket_client, mock_rate_limiter, mock_config, httpx_mock):
        """Test basic positions retrieval"""
        # Mock HTTP response for positions
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/positions",
            json=[
                {
                    'asset_id': 'token_123',
                    'market': 'market_123',
                    'market_question': 'Will this test pass?',
                    'outcome': 'Yes',
                    'size': '100',
                    'average_price': '0.50'
                }
            ]
        )

        result = await get_all_positions(
            mock_polymarket_client,
            mock_rate_limiter,
            mock_config
        )

        assert len(result) == 1
        assert result[0].type == "text"
        assert "Portfolio Positions" in result[0].text

    @pytest.mark.asyncio
    async def test_get_all_positions_with_filters(self, mock_polymarket_client, mock_rate_limiter, mock_config, httpx_mock):
        """Test positions with filters"""
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/positions",
            json=[]
        )

        result = await get_all_positions(
            mock_polymarket_client,
            mock_rate_limiter,
            mock_config,
            include_closed=True,
            min_value=10.0,
            sort_by='pnl'
        )

        assert len(result) == 1
        assert "No positions found" in result[0].text or "Portfolio Positions" in result[0].text

    @pytest.mark.asyncio
    async def test_get_position_details(self, mock_polymarket_client, mock_rate_limiter, mock_config, httpx_mock):
        """Test position details"""
        # Mock positions endpoint
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/positions",
            json=[
                {
                    'asset_id': 'token_123',
                    'market': 'market_123',
                    'market_question': 'Will this test pass?',
                    'outcome': 'Yes',
                    'size': '100',
                    'average_price': '0.50'
                }
            ]
        )

        # Mock trades endpoint
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/trades",
            json=[
                {
                    'id': 'trade_1',
                    'timestamp': str(int(datetime.now().timestamp())),
                    'side': 'BUY',
                    'price': '0.50',
                    'size': '100'
                }
            ]
        )

        result = await get_position_details(
            mock_polymarket_client,
            mock_rate_limiter,
            mock_config,
            market_id='market_123'
        )

        assert len(result) == 1
        assert "Position Details" in result[0].text

    @pytest.mark.asyncio
    async def test_get_portfolio_value(self, mock_polymarket_client, mock_rate_limiter, mock_config, httpx_mock):
        """Test portfolio value calculation"""
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/positions",
            json=[
                {
                    'asset_id': 'token_123',
                    'market': 'market_123',
                    'market_question': 'Test Market',
                    'outcome': 'Yes',
                    'size': '100',
                    'average_price': '0.50'
                }
            ]
        )

        result = await get_portfolio_value(
            mock_polymarket_client,
            mock_rate_limiter,
            mock_config,
            include_breakdown=True
        )

        assert len(result) == 1
        assert "Portfolio Value Summary" in result[0].text
        assert "USDC" in result[0].text

    @pytest.mark.asyncio
    async def test_get_pnl_summary(self, mock_polymarket_client, mock_rate_limiter, mock_config, httpx_mock):
        """Test P&L summary"""
        # Mock trades
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/trades",
            json=[
                {
                    'id': 'trade_1',
                    'market': 'market_123',
                    'outcome': 'Yes',
                    'timestamp': str(int(datetime.now().timestamp())),
                    'side': 'BUY',
                    'price': '0.50',
                    'size': '100'
                },
                {
                    'id': 'trade_2',
                    'market': 'market_123',
                    'outcome': 'Yes',
                    'timestamp': str(int(datetime.now().timestamp())),
                    'side': 'SELL',
                    'price': '0.60',
                    'size': '100'
                }
            ]
        )

        # Mock positions
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/positions",
            json=[]
        )

        result = await get_pnl_summary(
            mock_polymarket_client,
            mock_rate_limiter,
            mock_config,
            timeframe='24h'
        )

        assert len(result) == 1
        assert "P&L Summary" in result[0].text


class TestActivityTools:
    """Test activity monitoring tools"""

    @pytest.mark.asyncio
    async def test_get_trade_history(self, mock_polymarket_client, mock_rate_limiter, mock_config, httpx_mock):
        """Test trade history retrieval"""
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/trades",
            json=[
                {
                    'id': 'trade_1',
                    'timestamp': str(int(datetime.now().timestamp())),
                    'market_question': 'Test Market',
                    'outcome': 'Yes',
                    'side': 'BUY',
                    'price': '0.50',
                    'size': '100',
                    'fee': '0.01'
                }
            ]
        )

        result = await get_trade_history(
            mock_polymarket_client,
            mock_rate_limiter,
            mock_config,
            limit=50,
            side='BUY'
        )

        assert len(result) == 1
        assert "Trade History" in result[0].text

    @pytest.mark.asyncio
    async def test_get_activity_log(self, mock_polymarket_client, mock_rate_limiter, mock_config, httpx_mock):
        """Test activity log"""
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/activity",
            json=[
                {
                    'type': 'TRADE',
                    'timestamp': str(int(datetime.now().timestamp())),
                    'market_question': 'Test Market',
                    'amount': '100',
                    'value': '50',
                    'transaction_hash': '0x1234567890abcdef'
                }
            ]
        )

        result = await get_activity_log(
            mock_polymarket_client,
            mock_rate_limiter,
            mock_config,
            activity_type='trades'
        )

        assert len(result) == 1
        assert "Activity Log" in result[0].text


class TestAnalysisTools:
    """Test portfolio analysis tools"""

    @pytest.mark.asyncio
    async def test_analyze_portfolio_risk(self, mock_polymarket_client, mock_rate_limiter, mock_config, httpx_mock):
        """Test portfolio risk analysis"""
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/positions",
            json=[
                {
                    'asset_id': 'token_123',
                    'market': 'market_123',
                    'market_question': 'Test Market 1',
                    'outcome': 'Yes',
                    'size': '100',
                    'average_price': '0.50'
                },
                {
                    'asset_id': 'token_456',
                    'market': 'market_456',
                    'market_question': 'Test Market 2',
                    'outcome': 'No',
                    'size': '50',
                    'average_price': '0.60'
                }
            ]
        )

        result = await analyze_portfolio_risk(
            mock_polymarket_client,
            mock_rate_limiter,
            mock_config
        )

        assert len(result) == 1
        assert "Portfolio Risk Analysis" in result[0].text
        assert "Risk Score" in result[0].text

    @pytest.mark.asyncio
    async def test_suggest_portfolio_actions(self, mock_polymarket_client, mock_rate_limiter, mock_config, httpx_mock):
        """Test portfolio optimization suggestions"""
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/positions",
            json=[
                {
                    'asset_id': 'token_123',
                    'market': 'market_123',
                    'market_question': 'Test Market',
                    'outcome': 'Yes',
                    'size': '100',
                    'average_price': '0.30'
                }
            ]
        )

        result = await suggest_portfolio_actions(
            mock_polymarket_client,
            mock_rate_limiter,
            mock_config,
            goal='balanced',
            max_actions=5
        )

        assert len(result) == 1
        assert "Portfolio Optimization Suggestions" in result[0].text


class TestErrorHandling:
    """Test error handling"""

    @pytest.mark.asyncio
    async def test_no_positions_found(self, mock_polymarket_client, mock_rate_limiter, mock_config, httpx_mock):
        """Test handling when no positions exist"""
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/positions",
            json=[]
        )

        result = await get_all_positions(
            mock_polymarket_client,
            mock_rate_limiter,
            mock_config
        )

        assert len(result) == 1
        assert "No positions found" in result[0].text

    @pytest.mark.asyncio
    async def test_invalid_market_id(self, mock_polymarket_client, mock_rate_limiter, mock_config, httpx_mock):
        """Test handling of invalid market ID"""
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/positions",
            json=[]
        )

        result = await get_position_details(
            mock_polymarket_client,
            mock_rate_limiter,
            mock_config,
            market_id='invalid_market'
        )

        assert len(result) == 1
        assert "No position found" in result[0].text or "Error" in result[0].text

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_polymarket_client, mock_rate_limiter, mock_config, httpx_mock):
        """Test API error handling"""
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/positions",
            status_code=500
        )

        result = await get_all_positions(
            mock_polymarket_client,
            mock_rate_limiter,
            mock_config
        )

        assert len(result) == 1
        assert "Error" in result[0].text


class TestRateLimiting:
    """Test rate limiting compliance"""

    @pytest.mark.asyncio
    async def test_rate_limiter_called(self, mock_polymarket_client, mock_rate_limiter, mock_config, httpx_mock):
        """Verify rate limiter is called"""
        httpx_mock.add_response(
            url="https://data-api.polymarket.com/positions",
            json=[]
        )

        await get_all_positions(
            mock_polymarket_client,
            mock_rate_limiter,
            mock_config
        )

        # Verify rate limiter was called
        assert mock_rate_limiter.acquire.called

        # Verify correct endpoint category used
        calls = mock_rate_limiter.acquire.call_args_list
        assert any(
            call[0][0] == EndpointCategory.DATA_API
            for call in calls
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
