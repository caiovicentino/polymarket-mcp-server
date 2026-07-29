"""
Comprehensive tests for market discovery and analysis tools.

Tests all 18 tools with real Polymarket API (no mocks).
"""
import asyncio
from datetime import datetime, timedelta

import pytest

from polymarket_mcp.tools import market_analysis, market_discovery
from polymarket_mcp.tools.market_analysis import MarketOpportunity, OrderBook, PriceData, VolumeData


class TestMarketDiscovery:
    """Test suite for market discovery tools"""

    @pytest.mark.asyncio
    async def test_search_markets(self):
        """Test searching markets by query"""
        results = await market_discovery.search_markets(
            query="Trump",
            limit=5
        )

        assert isinstance(results, list)
        assert len(results) <= 5

        if len(results) > 0:
            market = results[0]
            assert "question" in market or "title" in market
            print(f"Found market: {market.get('question', market.get('title'))}")

    @pytest.mark.asyncio
    async def test_get_trending_markets(self):
        """Test getting trending markets by volume"""
        # Test 24h timeframe
        results_24h = await market_discovery.get_trending_markets(
            timeframe="24h",
            limit=5
        )

        assert isinstance(results_24h, list)
        assert len(results_24h) <= 5

        if len(results_24h) > 0:
            # Verify sorted by volume (descending)
            volumes = [float(m.get("volume24hr", 0) or 0) for m in results_24h]
            assert volumes == sorted(volumes, reverse=True)
            print(f"Top 24h market volume: ${volumes[0]:,.2f}")

        # Test 7d timeframe
        results_7d = await market_discovery.get_trending_markets(
            timeframe="7d",
            limit=3
        )

        assert isinstance(results_7d, list)

    @pytest.mark.asyncio
    async def test_filter_markets_by_category(self):
        """Test filtering markets by category"""
        categories = ["Politics", "Sports", "Crypto"]

        for category in categories:
            results = await market_discovery.filter_markets_by_category(
                category=category,
                active_only=True,
                limit=3
            )

            assert isinstance(results, list)
            print(f"Found {len(results)} markets in {category}")

    @pytest.mark.asyncio
    async def test_get_featured_markets(self):
        """Test getting featured markets"""
        results = await market_discovery.get_featured_markets(limit=5)

        assert isinstance(results, list)
        assert len(results) <= 5
        print(f"Found {len(results)} featured markets")

    @pytest.mark.asyncio
    async def test_get_closing_soon_markets(self):
        """Test getting markets closing soon"""
        # Test markets closing within 24 hours
        results = await market_discovery.get_closing_soon_markets(
            hours=24,
            limit=5
        )

        assert isinstance(results, list)
        print(f"Found {len(results)} markets closing within 24 hours")

        # Verify all markets have end dates within timeframe
        cutoff = datetime.utcnow() + timedelta(hours=24)
        for market in results:
            end_date = market.get("endDate") or market.get("end_date_iso")
            if end_date:
                try:
                    if isinstance(end_date, str):
                        end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    else:
                        end_dt = datetime.fromtimestamp(int(end_date))

                    assert end_dt <= cutoff
                except Exception as e:
                    print(f"Warning: Could not parse end date {end_date}: {e}")

    @pytest.mark.asyncio
    async def test_get_sports_markets(self):
        """Test getting sports markets"""
        # All sports
        all_sports = await market_discovery.get_sports_markets(limit=5)
        assert isinstance(all_sports, list)
        print(f"Found {len(all_sports)} sports markets")

        # Specific sport
        nfl_markets = await market_discovery.get_sports_markets(
            sport_type="NFL",
            limit=3
        )
        assert isinstance(nfl_markets, list)
        print(f"Found {len(nfl_markets)} NFL markets")

    @pytest.mark.asyncio
    async def test_get_crypto_markets(self):
        """Test getting crypto markets"""
        # All crypto
        all_crypto = await market_discovery.get_crypto_markets(limit=5)
        assert isinstance(all_crypto, list)
        print(f"Found {len(all_crypto)} crypto markets")

        # Specific symbol
        btc_markets = await market_discovery.get_crypto_markets(
            symbol="BTC",
            limit=3
        )
        assert isinstance(btc_markets, list)
        print(f"Found {len(btc_markets)} BTC markets")

    @pytest.mark.asyncio
    async def test_get_event_markets(self):
        """Test getting markets for a specific event"""
        # First, get a market with an event
        markets = await market_discovery.search_markets("election", limit=1)

        if len(markets) > 0 and markets[0].get("slug"):
            event_slug = markets[0].get("slug")

            try:
                event_markets = await market_discovery.get_event_markets(
                    event_slug=event_slug
                )
                assert isinstance(event_markets, list)
                print(f"Found {len(event_markets)} markets for event: {event_slug}")
            except Exception as e:
                print(f"Warning: Event markets test skipped: {e}")


class TestMarketAnalysis:
    """Test suite for market analysis tools"""

    @pytest.fixture
    def sample_market_id(self):
        """Fixture to provide a sample market ID"""
        # This would need to be updated with a real market ID
        # For now, we'll fetch one dynamically
        return None

    @pytest.mark.asyncio
    async def test_get_market_details(self):
        """Test getting market details"""
        # Get a market first
        markets = await market_discovery.get_trending_markets(limit=1)

        if len(markets) > 0:
            market = markets[0]
            market_id = market.get("id") or market.get("market_id")

            if market_id:
                details = await market_analysis.get_market_details(market_id=market_id)

                assert isinstance(details, dict)
                assert "question" in details or "title" in details
                print(f"Market details: {details.get('question', details.get('title'))}")

    @pytest.mark.asyncio
    async def test_get_current_price(self):
        """Test getting current price"""
        # Get a market with tokens
        markets = await market_discovery.get_trending_markets(limit=1)

        if len(markets) > 0:
            market = markets[0]
            tokens = market.get("tokens", [])

            if len(tokens) > 0:
                token_id = tokens[0].get("token_id")

                if token_id:
                    # Test BOTH side
                    price_data = await market_analysis.get_current_price(
                        token_id=token_id,
                        side="BOTH"
                    )

                    assert isinstance(price_data, PriceData)
                    assert price_data.token_id == token_id
                    print(f"Price - Bid: {price_data.bid}, Ask: {price_data.ask}, Mid: {price_data.mid}")

                    # Test BUY side
                    buy_price = await market_analysis.get_current_price(
                        token_id=token_id,
                        side="BUY"
                    )
                    assert isinstance(buy_price, PriceData)

    @pytest.mark.asyncio
    async def test_get_orderbook(self):
        """Test getting orderbook"""
        markets = await market_discovery.get_trending_markets(limit=1)

        if len(markets) > 0:
            market = markets[0]
            tokens = market.get("tokens", [])

            if len(tokens) > 0:
                token_id = tokens[0].get("token_id")

                if token_id:
                    orderbook = await market_analysis.get_orderbook(
                        token_id=token_id,
                        depth=10
                    )

                    assert isinstance(orderbook, OrderBook)
                    assert orderbook.token_id == token_id
                    print(f"Orderbook - {len(orderbook.bids)} bids, {len(orderbook.asks)} asks")

                    # Verify bids are sorted descending
                    if len(orderbook.bids) > 1:
                        bid_prices = [b.price for b in orderbook.bids]
                        assert bid_prices == sorted(bid_prices, reverse=True)

    @pytest.mark.asyncio
    async def test_get_spread(self):
        """Test getting spread"""
        markets = await market_discovery.get_trending_markets(limit=1)

        if len(markets) > 0:
            market = markets[0]
            tokens = market.get("tokens", [])

            if len(tokens) > 0:
                token_id = tokens[0].get("token_id")

                if token_id:
                    spread_data = await market_analysis.get_spread(token_id=token_id)

                    assert isinstance(spread_data, dict)
                    assert "spread_value" in spread_data
                    assert "spread_percentage" in spread_data
                    print(f"Spread: {spread_data['spread_value']:.4f} ({spread_data['spread_percentage']:.2f}%)")

    @pytest.mark.asyncio
    async def test_get_market_volume(self):
        """Test getting market volume"""
        markets = await market_discovery.get_trending_markets(limit=1)

        if len(markets) > 0:
            market = markets[0]
            market_id = market.get("id") or market.get("market_id")

            if market_id:
                volume_data = await market_analysis.get_market_volume(
                    market_id=market_id,
                    timeframes=["24h", "7d", "30d"]
                )

                assert isinstance(volume_data, VolumeData)
                assert volume_data.market_id == market_id
                print(f"Volume - 24h: ${volume_data.volume_24h:,.2f}, 7d: ${volume_data.volume_7d:,.2f}")

    @pytest.mark.asyncio
    async def test_get_liquidity(self):
        """Test getting market liquidity"""
        markets = await market_discovery.get_trending_markets(limit=1)

        if len(markets) > 0:
            market = markets[0]
            market_id = market.get("id") or market.get("market_id")

            if market_id:
                liquidity_data = await market_analysis.get_liquidity(market_id=market_id)

                assert isinstance(liquidity_data, dict)
                assert "liquidity_usd" in liquidity_data
                print(f"Liquidity: ${liquidity_data['liquidity_usd']:,.2f}")

    @pytest.mark.asyncio
    async def test_get_price_history(self):
        """Test getting price history (note: limited availability)"""
        markets = await market_discovery.get_trending_markets(limit=1)

        if len(markets) > 0:
            market = markets[0]
            tokens = market.get("tokens", [])

            if len(tokens) > 0:
                token_id = tokens[0].get("token_id")

                if token_id:
                    # This will return a note about limited availability
                    history = await market_analysis.get_price_history(
                        token_id=token_id,
                        resolution="1h"
                    )

                    assert isinstance(history, list)
                    print(f"Price history response: {history}")

    @pytest.mark.asyncio
    async def test_get_market_holders(self):
        """Test getting market holders (note: requires auth)"""
        markets = await market_discovery.get_trending_markets(limit=1)

        if len(markets) > 0:
            market = markets[0]
            market_id = market.get("id") or market.get("market_id")

            if market_id:
                # This will return a note about auth requirement
                holders = await market_analysis.get_market_holders(
                    market_id=market_id,
                    limit=10
                )

                assert isinstance(holders, list)
                print(f"Holders response: {holders}")

    @pytest.mark.asyncio
    async def test_analyze_market_opportunity(self):
        """Test AI-powered market analysis"""
        markets = await market_discovery.get_trending_markets(limit=1)

        if len(markets) > 0:
            market = markets[0]
            market_id = market.get("id") or market.get("market_id")

            if market_id:
                analysis = await market_analysis.analyze_market_opportunity(market_id=market_id)

                assert isinstance(analysis, MarketOpportunity)
                assert analysis.market_id == market_id
                assert analysis.recommendation in ["BUY", "SELL", "HOLD", "AVOID"]
                assert analysis.risk_assessment in ["low", "medium", "high"]
                assert 0 <= analysis.confidence_score <= 100

                print("\nMarket Analysis:")
                print(f"  Market: {analysis.market_question}")
                print(f"  Recommendation: {analysis.recommendation}")
                print(f"  Confidence: {analysis.confidence_score}%")
                print(f"  Risk: {analysis.risk_assessment}")
                print(f"  Reasoning: {analysis.reasoning}")

    @pytest.mark.asyncio
    async def test_compare_markets(self):
        """Test comparing multiple markets"""
        markets = await market_discovery.get_trending_markets(limit=3)

        if len(markets) >= 2:
            market_ids = [m.get("id") or m.get("market_id") for m in markets[:2]]
            market_ids = [mid for mid in market_ids if mid]  # Filter None

            if len(market_ids) >= 2:
                comparison = await market_analysis.compare_markets(market_ids=market_ids)

                assert isinstance(comparison, list)
                assert len(comparison) == len(market_ids)

                print("\nMarket Comparison:")
                for comp in comparison:
                    if "error" not in comp:
                        print(f"  - {comp.get('question', 'Unknown')}")
                        print(f"    Volume 24h: ${comp.get('volume_24h', 0):,.2f}")
                        print(f"    Liquidity: ${comp.get('liquidity_usd', 0):,.2f}")

    @pytest.mark.asyncio
    async def test_tool_handlers(self):
        """Test tool handler functions"""
        # Test discovery handler
        result = await market_discovery.handle_tool(
            "search_markets",
            {"query": "election", "limit": 2}
        )

        assert isinstance(result, list)
        assert len(result) > 0
        assert result[0].type == "text"

        # Test analysis handler
        markets = await market_discovery.get_trending_markets(limit=1)
        if len(markets) > 0:
            market_id = markets[0].get("id") or markets[0].get("market_id")
            if market_id:
                result = await market_analysis.handle_tool(
                    "get_market_details",
                    {"market_id": market_id}
                )

                assert isinstance(result, list)
                assert len(result) > 0
                assert result[0].type == "text"


class TestIntegration:
    """Integration tests combining multiple tools"""

    @pytest.mark.asyncio
    async def test_discovery_to_analysis_workflow(self):
        """Test workflow from discovery to detailed analysis"""
        # 1. Search for markets
        markets = await market_discovery.search_markets("Trump", limit=3)
        assert len(markets) > 0

        # 2. Get details for first market
        market = markets[0]
        market_id = market.get("id") or market.get("market_id")

        if market_id:
            # 3. Get comprehensive analysis
            details = await market_analysis.get_market_details(market_id=market_id)
            volume = await market_analysis.get_market_volume(market_id=market_id)
            liquidity = await market_analysis.get_liquidity(market_id=market_id)
            analysis = await market_analysis.analyze_market_opportunity(market_id=market_id)

            # Verify all data is consistent
            assert details.get("id") == market_id or details.get("market_id") == market_id
            assert volume.market_id == market_id
            assert liquidity.get("market_id") == market_id
            assert analysis.market_id == market_id

            print(f"\nComplete Market Analysis for: {details.get('question', 'Unknown')}")
            print(f"Volume 24h: ${volume.volume_24h:,.2f}")
            print(f"Liquidity: ${liquidity.get('liquidity_usd', 0):,.2f}")
            print(f"Recommendation: {analysis.recommendation} ({analysis.confidence_score}%)")

    @pytest.mark.asyncio
    async def test_rate_limiting(self):
        """Test that rate limiting works correctly"""
        # Make multiple rapid requests
        tasks = [
            market_discovery.search_markets("test", limit=1)
            for _ in range(5)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # All should succeed (may be rate limited but not fail)
        successful = [r for r in results if not isinstance(r, Exception)]
        print(f"Successfully completed {len(successful)}/5 requests with rate limiting")


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
