"""
Usage Examples for Polymarket MCP Market Discovery & Analysis Tools

This file demonstrates common usage patterns for the 18 new tools.
"""

import asyncio

from polymarket_mcp.tools import market_analysis, market_discovery

# ============================================
# MARKET DISCOVERY EXAMPLES
# ============================================

async def example_search_markets():
    """Example: Search for markets by keyword"""
    # Search for Trump-related markets
    markets = await market_discovery.search_markets(
        query="Trump",
        limit=5,
        filters={"active": "true"}
    )

    for market in markets:
        print(f"Found: {market.get('question', 'Unknown')}")
        print(f"  Volume 24h: ${market.get('volume24hr', 0):,.2f}")
        print(f"  Liquidity: ${market.get('liquidity', 0):,.2f}\n")


async def example_trending_markets():
    """Example: Get trending markets by volume"""
    # Get top 10 markets by 24h volume
    trending = await market_discovery.get_trending_markets(
        timeframe="24h",
        limit=10
    )

    print("Top 10 Trending Markets (24h):")
    for i, market in enumerate(trending, 1):
        volume = market.get("volume24hr", 0)
        print(f"{i}. {market.get('question', 'Unknown')}")
        print(f"   Volume: ${volume:,.2f}\n")


async def example_filter_by_category():
    """Example: Filter markets by category"""
    categories = ["Politics", "Sports", "Crypto"]

    for category in categories:
        markets = await market_discovery.filter_markets_by_category(
            category=category,
            active_only=True,
            limit=3
        )

        print(f"\n{category} Markets ({len(markets)} found):")
        for market in markets:
            print(f"  - {market.get('question', 'Unknown')}")


async def example_sports_and_crypto():
    """Example: Get sports and crypto markets"""
    # Get NFL markets
    nfl_markets = await market_discovery.get_sports_markets(
        sport_type="NFL",
        limit=5
    )

    print("NFL Markets:")
    for market in nfl_markets:
        print(f"  {market.get('question', 'Unknown')}")

    # Get Bitcoin markets
    btc_markets = await market_discovery.get_crypto_markets(
        symbol="BTC",
        limit=5
    )

    print("\nBitcoin Markets:")
    for market in btc_markets:
        print(f"  {market.get('question', 'Unknown')}")


async def example_closing_soon():
    """Example: Find markets closing soon"""
    closing_soon = await market_discovery.get_closing_soon_markets(
        hours=24,
        limit=5
    )

    print("Markets Closing in Next 24 Hours:")
    for market in closing_soon:
        end_date = market.get("endDate") or market.get("end_date_iso")
        print(f"  {market.get('question', 'Unknown')}")
        print(f"    Closes: {end_date}\n")


# ============================================
# MARKET ANALYSIS EXAMPLES
# ============================================

async def example_get_market_details():
    """Example: Get complete market details"""
    # First find a market
    markets = await market_discovery.get_trending_markets(limit=1)

    if markets:
        market_id = markets[0].get("id") or markets[0].get("market_id")

        # Get detailed information
        details = await market_analysis.get_market_details(market_id=market_id)

        print("Market Details:")
        print(f"  Question: {details.get('question', 'Unknown')}")
        print(f"  Volume 24h: ${details.get('volume24hr', 0):,.2f}")
        print(f"  Liquidity: ${details.get('liquidity', 0):,.2f}")
        print(f"  Active: {details.get('active', False)}")
        print(f"  Tags: {', '.join(details.get('tags', []))}")


async def example_price_analysis():
    """Example: Get prices and analyze spread"""
    # Get a market
    markets = await market_discovery.get_trending_markets(limit=1)

    if markets and markets[0].get("tokens"):
        token_id = markets[0]["tokens"][0].get("token_id")

        # Get current price
        price_data = await market_analysis.get_current_price(
            token_id=token_id,
            side="BOTH"
        )

        print("Price Analysis:")
        print(f"  Bid: {price_data.bid:.4f}")
        print(f"  Ask: {price_data.ask:.4f}")
        print(f"  Mid: {price_data.mid:.4f}")

        # Get spread
        spread = await market_analysis.get_spread(token_id=token_id)

        print("\nSpread Analysis:")
        print(f"  Spread: {spread['spread_value']:.4f}")
        print(f"  Spread %: {spread['spread_percentage']:.2f}%")


async def example_orderbook():
    """Example: Get and analyze orderbook"""
    markets = await market_discovery.get_trending_markets(limit=1)

    if markets and markets[0].get("tokens"):
        token_id = markets[0]["tokens"][0].get("token_id")

        # Get orderbook
        orderbook = await market_analysis.get_orderbook(
            token_id=token_id,
            depth=10
        )

        print("Order Book:")
        print("\nTop 5 Bids:")
        for bid in orderbook.bids[:5]:
            print(f"  {bid.price:.4f} - Size: {bid.size:.2f}")

        print("\nTop 5 Asks:")
        for ask in orderbook.asks[:5]:
            print(f"  {ask.price:.4f} - Size: {ask.size:.2f}")


async def example_volume_and_liquidity():
    """Example: Analyze volume and liquidity"""
    markets = await market_discovery.get_trending_markets(limit=1)

    if markets:
        market_id = markets[0].get("id") or markets[0].get("market_id")

        # Get volume data
        volume = await market_analysis.get_market_volume(
            market_id=market_id,
            timeframes=["24h", "7d", "30d"]
        )

        print("Volume Analysis:")
        print(f"  24h: ${volume.volume_24h:,.2f}")
        print(f"  7d: ${volume.volume_7d:,.2f}")
        print(f"  30d: ${volume.volume_30d:,.2f}")

        # Get liquidity
        liquidity = await market_analysis.get_liquidity(market_id=market_id)

        print(f"\nLiquidity: {liquidity['liquidity_formatted']}")


async def example_ai_opportunity_analysis():
    """Example: AI-powered market opportunity analysis"""
    # Get trending markets
    markets = await market_discovery.get_trending_markets(limit=3)

    print("AI Market Opportunity Analysis:\n")

    for market in markets:
        market_id = market.get("id") or market.get("market_id")

        # Analyze opportunity
        analysis = await market_analysis.analyze_market_opportunity(market_id)

        print(f"Market: {analysis.market_question}")
        print(f"  Recommendation: {analysis.recommendation}")
        print(f"  Confidence: {analysis.confidence_score}%")
        print(f"  Risk: {analysis.risk_assessment}")
        print(f"  Reasoning: {analysis.reasoning}")

        # Show key metrics
        if analysis.current_price_yes:
            print(f"  YES Price: {analysis.current_price_yes:.4f}")
        if analysis.spread_pct:
            print(f"  Spread: {analysis.spread_pct:.2f}%")
        if analysis.volume_24h:
            print(f"  Volume 24h: ${analysis.volume_24h:,.2f}")
        if analysis.liquidity_usd:
            print(f"  Liquidity: ${analysis.liquidity_usd:,.2f}")

        print()


async def example_compare_markets():
    """Example: Compare multiple markets"""
    # Get crypto markets
    crypto = await market_discovery.get_crypto_markets(limit=3)

    if len(crypto) >= 2:
        market_ids = [m.get("id") or m.get("market_id") for m in crypto]
        market_ids = [mid for mid in market_ids if mid]

        # Compare markets
        comparison = await market_analysis.compare_markets(market_ids)

        print("Market Comparison:\n")
        print(f"{'Market':<50} {'Volume 24h':<15} {'Liquidity':<15}")
        print("-" * 80)

        for comp in comparison:
            if "error" not in comp:
                question = comp.get("question", "Unknown")[:47] + "..."
                volume = f"${comp.get('volume_24h', 0):,.0f}"
                liquidity = f"${comp.get('liquidity_usd', 0):,.0f}"
                print(f"{question:<50} {volume:<15} {liquidity:<15}")


# ============================================
# COMPLETE WORKFLOW EXAMPLES
# ============================================

async def workflow_find_best_opportunity():
    """Complete workflow: Find best trading opportunity"""
    print("=== Finding Best Trading Opportunity ===\n")

    # Step 1: Get trending markets
    print("1. Searching trending markets...")
    markets = await market_discovery.get_trending_markets(timeframe="24h", limit=10)
    print(f"   Found {len(markets)} trending markets\n")

    # Step 2: Analyze each market
    print("2. Analyzing opportunities...\n")
    opportunities = []

    for market in markets[:5]:  # Analyze top 5
        market_id = market.get("id") or market.get("market_id")

        try:
            analysis = await market_analysis.analyze_market_opportunity(market_id)
            opportunities.append(analysis)
        except Exception as e:
            print(f"   Skipped {market.get('question', 'Unknown')}: {e}")

    # Step 3: Filter by recommendation and confidence
    print("3. Filtering opportunities...\n")
    buy_opportunities = [
        opp for opp in opportunities
        if opp.recommendation == "BUY" and opp.confidence_score > 60
    ]

    # Step 4: Sort by confidence
    buy_opportunities.sort(key=lambda x: x.confidence_score, reverse=True)

    # Step 5: Display results
    print(f"4. Results: Found {len(buy_opportunities)} BUY opportunities\n")

    if buy_opportunities:
        best = buy_opportunities[0]
        print("=== BEST OPPORTUNITY ===")
        print(f"Market: {best.market_question}")
        print(f"Recommendation: {best.recommendation}")
        print(f"Confidence: {best.confidence_score}%")
        print(f"Risk: {best.risk_assessment}")
        print(f"Reasoning: {best.reasoning}")

        if best.current_price_yes:
            print(f"\nEntry Price (YES): {best.current_price_yes:.4f}")
        if best.spread_pct:
            print(f"Spread: {best.spread_pct:.2f}%")

        print("\n=== Next Steps ===")
        print("1. Review market details")
        print("2. Check orderbook for liquidity")
        print("3. Use trading tools to execute order")
    else:
        print("No BUY opportunities found at this time.")


async def workflow_monitor_category():
    """Workflow: Monitor specific category for opportunities"""
    category = "Politics"

    print(f"=== Monitoring {category} Markets ===\n")

    # Get markets in category
    markets = await market_discovery.filter_markets_by_category(
        category=category,
        active_only=True,
        limit=5
    )

    print(f"Found {len(markets)} active {category} markets\n")

    # Analyze each
    for market in markets:
        market_id = market.get("id") or market.get("market_id")
        question = market.get("question", "Unknown")

        print(f"Market: {question[:60]}...")

        try:
            # Get volume and liquidity
            volume = await market_analysis.get_market_volume(market_id)
            liquidity = await market_analysis.get_liquidity(market_id)

            print(f"  Volume 24h: ${volume.volume_24h:,.2f}")
            print(f"  Liquidity: ${liquidity.get('liquidity_usd', 0):,.2f}")

            # Analyze if high volume
            if volume.volume_24h > 10000:
                analysis = await market_analysis.analyze_market_opportunity(market_id)
                print(f"  → {analysis.recommendation} ({analysis.confidence_score}%)")
                print(f"    {analysis.reasoning}")

        except Exception as e:
            print(f"  Error: {e}")

        print()


async def workflow_pre_close_analysis():
    """Workflow: Analyze markets closing soon"""
    print("=== Markets Closing Soon Analysis ===\n")

    # Get markets closing in 24 hours
    closing = await market_discovery.get_closing_soon_markets(hours=24, limit=5)

    print(f"Found {len(closing)} markets closing in 24 hours\n")

    for market in closing:
        market_id = market.get("id") or market.get("market_id")
        question = market.get("question", "Unknown")
        end_date = market.get("endDate") or market.get("end_date_iso")

        print(f"Market: {question[:60]}...")
        print(f"  Closes: {end_date}")

        try:
            # Full analysis
            analysis = await market_analysis.analyze_market_opportunity(market_id)

            print(f"  Recommendation: {analysis.recommendation}")
            print(f"  Confidence: {analysis.confidence_score}%")

            if analysis.current_price_yes:
                print(f"  Current YES Price: {analysis.current_price_yes:.4f}")

            # Closing strategy
            if analysis.recommendation in ["BUY", "HOLD"]:
                print("  → Consider entering before close")
            elif analysis.recommendation == "SELL":
                print("  → Consider exiting position")
            else:
                print("  → Avoid - high risk near close")

        except Exception as e:
            print(f"  Error: {e}")

        print()


# ============================================
# MAIN EXECUTION
# ============================================

async def main():
    """Run example workflows"""
    print("=" * 80)
    print("POLYMARKET MCP - MARKET TOOLS EXAMPLES")
    print("=" * 80)
    print()

    # Choose which examples to run
    examples = [
        ("Search Markets", example_search_markets),
        ("Trending Markets", example_trending_markets),
        ("Filter by Category", example_filter_by_category),
        ("Sports & Crypto", example_sports_and_crypto),
        ("Closing Soon", example_closing_soon),
        ("Market Details", example_get_market_details),
        ("Price Analysis", example_price_analysis),
        ("Orderbook", example_orderbook),
        ("Volume & Liquidity", example_volume_and_liquidity),
        ("AI Opportunity Analysis", example_ai_opportunity_analysis),
        ("Compare Markets", example_compare_markets),
        ("Workflow: Find Best Opportunity", workflow_find_best_opportunity),
        ("Workflow: Monitor Category", workflow_monitor_category),
        ("Workflow: Pre-Close Analysis", workflow_pre_close_analysis),
    ]

    # Run selected examples (modify as needed)
    selected_examples = [
        workflow_find_best_opportunity,
        example_ai_opportunity_analysis,
    ]

    for example_func in selected_examples:
        try:
            await example_func()
            print("\n" + "=" * 80 + "\n")
        except Exception as e:
            print(f"Error running example: {e}\n")


if __name__ == "__main__":
    # Run examples
    asyncio.run(main())
