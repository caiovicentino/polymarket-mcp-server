"""
Portfolio Management Tools for Polymarket MCP Server.

Provides comprehensive position tracking, portfolio analytics, and optimization suggestions.
Implements 8 tools for portfolio management:
- Position tracking (4 tools)
- Activity monitoring (2 tools)
- Risk analysis (2 tools)
"""

import logging
from typing import Dict, Any, List, Optional, Tuple, Literal
from datetime import datetime, timedelta
from collections import defaultdict
import httpx

import mcp.types as types

logger = logging.getLogger(__name__)


class PortfolioDataCache:
    """Simple cache for portfolio data to reduce API calls"""

    def __init__(self, ttl_seconds: int = 30):
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired"""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if datetime.now().timestamp() - timestamp < self.ttl_seconds:
                return value
            # Expired, remove
            del self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """Set cached value with current timestamp"""
        self._cache[key] = (value, datetime.now().timestamp())

    def clear(self) -> None:
        """Clear all cached values"""
        self._cache.clear()


# Global cache instance
_portfolio_cache = PortfolioDataCache()


async def get_all_positions(
    polymarket_client,
    rate_limiter,
    config,
    include_closed: bool = False,
    min_value: float = 1.0,
    sort_by: Literal["value", "pnl", "size"] = "value",
) -> List[types.TextContent]:
    """
    Get all user positions with filtering and sorting.

    Args:
        polymarket_client: PolymarketClient instance
        rate_limiter: RateLimiter instance
        config: PolymarketConfig instance
        include_closed: Include closed positions (default: False)
        min_value: Minimum position value in USD (default: 1.0)
        sort_by: Sort field - 'value', 'pnl', or 'size' (default: 'value')

    Returns:
        List with formatted position data
    """
    try:
        from ..utils.rate_limiter import EndpointCategory

        # Rate limit for data API
        await rate_limiter.acquire(EndpointCategory.DATA_API)

        # Check cache first
        cache_key = f"positions_{include_closed}_{min_value}"
        cached_data = _portfolio_cache.get(cache_key)
        if cached_data:
            logger.debug("Using cached positions data")
            positions_data = cached_data
        else:
            # Fetch positions using direct HTTP call to Data API
            async with httpx.AsyncClient() as client:
                params = {"user": config.POLYGON_ADDRESS.lower()}

                response = await client.get(
                    "https://data-api.polymarket.com/positions", params=params, timeout=10.0
                )
                response.raise_for_status()
                positions_data = response.json()

                # Cache the result
                _portfolio_cache.set(cache_key, positions_data)

        if not positions_data:
            return [types.TextContent(type="text", text="No positions found.")]

        # Filter positions
        filtered_positions = []
        for pos in positions_data:
            # Parse position data
            size = float(pos.get("size", 0))
            avg_price = float(pos.get("average_price", 0))

            # Skip zero or very small positions
            if size <= 0:
                continue

            # Get current market price
            token_id = pos.get("asset_id")
            market = pos.get("market")

            # Fetch current price from orderbook
            try:
                await rate_limiter.acquire(EndpointCategory.MARKET_DATA)
                orderbook = await polymarket_client.get_orderbook(token_id)

                # Calculate mid price
                best_bid = (
                    float(orderbook.get("bids", [{}])[0].get("price", 0))
                    if orderbook.get("bids")
                    else 0
                )
                best_ask = (
                    float(orderbook.get("asks", [{}])[0].get("price", 0))
                    if orderbook.get("asks")
                    else 0
                )
                current_price = (best_bid + best_ask) / 2 if (best_bid and best_ask) else avg_price
            except Exception as e:
                logger.warning(f"Failed to fetch current price for {token_id}: {e}")
                current_price = avg_price

            # Calculate values
            current_value = size * current_price
            cost_basis = size * avg_price
            unrealized_pnl = current_value - cost_basis
            pnl_pct = (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0

            # Apply filters
            if not include_closed and size <= 0:
                continue
            if current_value < min_value:
                continue

            filtered_positions.append(
                {
                    "market_id": market,
                    "market_question": pos.get("market_question", "Unknown"),
                    "token_id": token_id,
                    "outcome": pos.get("outcome", "Unknown"),
                    "size": size,
                    "avg_price": avg_price,
                    "current_price": current_price,
                    "cost_basis": cost_basis,
                    "current_value": current_value,
                    "unrealized_pnl": unrealized_pnl,
                    "pnl_pct": pnl_pct,
                }
            )

        # Sort positions
        sort_keys = {
            "value": lambda p: p["current_value"],
            "pnl": lambda p: p["unrealized_pnl"],
            "size": lambda p: p["size"],
        }
        filtered_positions.sort(key=sort_keys.get(sort_by, sort_keys["value"]), reverse=True)

        # Format output
        output_lines = [f"Portfolio Positions ({len(filtered_positions)} total)", "=" * 80, ""]

        total_value = 0
        total_pnl = 0

        for i, pos in enumerate(filtered_positions, 1):
            output_lines.extend(
                [
                    f"{i}. {pos['market_question']}",
                    f"   Outcome: {pos['outcome']}",
                    f"   Position: {pos['size']:.2f} shares @ ${pos['avg_price']:.4f} avg",
                    f"   Current: ${pos['current_price']:.4f} | Value: ${pos['current_value']:.2f}",
                    f"   P&L: ${pos['unrealized_pnl']:+.2f} ({pos['pnl_pct']:+.2f}%)",
                    f"   Market ID: {pos['market_id']}",
                    f"   Token ID: {pos['token_id']}",
                    "",
                ]
            )

            total_value += pos["current_value"]
            total_pnl += pos["unrealized_pnl"]

        # Summary
        output_lines.extend(
            [
                "=" * 80,
                f"Total Portfolio Value: ${total_value:.2f}",
                f"Total Unrealized P&L: ${total_pnl:+.2f}",
                "",
            ]
        )

        return [types.TextContent(type="text", text="\n".join(output_lines))]

    except Exception as e:
        logger.error(f"Error fetching positions: {e}")
        return [types.TextContent(type="text", text=f"Error fetching positions: {str(e)}")]


async def get_position_details(
    polymarket_client, rate_limiter, config, market_id: str
) -> List[types.TextContent]:
    """
    Get detailed view of a specific position including recent trades and suggestions.

    Args:
        polymarket_client: PolymarketClient instance
        rate_limiter: RateLimiter instance
        config: PolymarketConfig instance
        market_id: Market condition ID

    Returns:
        List with detailed position data
    """
    try:
        from ..utils.rate_limiter import EndpointCategory

        # Fetch position data
        await rate_limiter.acquire(EndpointCategory.DATA_API)
        async with httpx.AsyncClient() as client:
            params = {"user": config.POLYGON_ADDRESS.lower(), "market": market_id}

            response = await client.get(
                "https://data-api.polymarket.com/positions", params=params, timeout=10.0
            )
            response.raise_for_status()
            positions = response.json()

        if not positions:
            return [
                types.TextContent(type="text", text=f"No position found for market {market_id}")
            ]

        position = positions[0]
        token_id = position.get("asset_id")

        # Fetch market details
        await rate_limiter.acquire(EndpointCategory.CLOB_GENERAL)
        _market = await polymarket_client.get_market(market_id)

        # Fetch current orderbook
        await rate_limiter.acquire(EndpointCategory.MARKET_DATA)
        orderbook = await polymarket_client.get_orderbook(token_id)

        # Fetch recent trades in this market
        await rate_limiter.acquire(EndpointCategory.DATA_API)
        async with httpx.AsyncClient() as client:
            trade_response = await client.get(
                "https://data-api.polymarket.com/trades",
                params={"user": config.POLYGON_ADDRESS.lower(), "market": market_id, "limit": 10},
                timeout=10.0,
            )
            trade_response.raise_for_status()
            recent_trades = trade_response.json()

        # Calculate position metrics
        size = float(position.get("size", 0))
        avg_price = float(position.get("average_price", 0))

        # Current market prices
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])
        best_bid = float(bids[0]["price"]) if bids else 0
        best_ask = float(asks[0]["price"]) if asks else 0
        mid_price = (best_bid + best_ask) / 2 if (best_bid and best_ask) else avg_price
        spread = best_ask - best_bid if (best_bid and best_ask) else 0

        # Calculate P&L
        current_value = size * mid_price
        cost_basis = size * avg_price
        unrealized_pnl = current_value - cost_basis
        pnl_pct = (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0

        # Generate suggestions
        suggestions = []
        if pnl_pct > 20:
            suggestions.append("Consider taking profits - position up >20%")
        elif pnl_pct < -15:
            suggestions.append("Position down >15% - consider cutting losses or averaging down")

        if spread > 0.05:
            suggestions.append(
                f"Wide spread ({spread:.4f}) - may be difficult to exit at fair price"
            )

        if best_bid > 0.90:
            suggestions.append(
                "Market highly confident - consider closing position if you disagree"
            )
        elif best_bid < 0.10:
            suggestions.append("Market lowly valued - high upside if outcome occurs")

        # Liquidity check
        bid_liquidity = sum(float(b["price"]) * float(b["size"]) for b in bids[:5]) if bids else 0
        ask_liquidity = sum(float(a["price"]) * float(a["size"]) for a in asks[:5]) if asks else 0
        total_liquidity = bid_liquidity + ask_liquidity

        if total_liquidity < 1000:
            suggestions.append(f"Low liquidity (${total_liquidity:.2f}) - may impact exit price")

        # Format output
        output_lines = [
            f"Position Details: {position.get('market_question', 'Unknown')}",
            "=" * 80,
            "",
            "POSITION OVERVIEW",
            "-" * 80,
            f"Outcome: {position.get('outcome', 'Unknown')}",
            f"Size: {size:.2f} shares",
            f"Average Entry Price: ${avg_price:.4f}",
            f"Current Mid Price: ${mid_price:.4f}",
            f"Cost Basis: ${cost_basis:.2f}",
            f"Current Value: ${current_value:.2f}",
            f"Unrealized P&L: ${unrealized_pnl:+.2f} ({pnl_pct:+.2f}%)",
            "",
            "MARKET CONDITIONS",
            "-" * 80,
            f"Best Bid: ${best_bid:.4f}",
            f"Best Ask: ${best_ask:.4f}",
            f"Spread: ${spread:.4f} ({spread * 100:.2f}%)",
            f"Liquidity: ${total_liquidity:.2f}",
            "",
            "RECENT TRADES",
            "-" * 80,
        ]

        if recent_trades:
            for trade in recent_trades[:5]:
                trade_time = datetime.fromtimestamp(int(trade.get("timestamp", 0))).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                trade_side = trade.get("side", "UNKNOWN")
                trade_price = float(trade.get("price", 0))
                trade_size = float(trade.get("size", 0))
                output_lines.append(
                    f"  {trade_time} | {trade_side:4s} | {trade_size:6.2f} @ ${trade_price:.4f}"
                )
        else:
            output_lines.append("  No recent trades")

        output_lines.extend(["", "SUGGESTED ACTIONS", "-" * 80])

        if suggestions:
            for suggestion in suggestions:
                output_lines.append(f"  • {suggestion}")
        else:
            output_lines.append("  • HOLD - Position within normal parameters")

        output_lines.extend(["", "=" * 80])

        return [types.TextContent(type="text", text="\n".join(output_lines))]

    except Exception as e:
        logger.error(f"Error fetching position details: {e}")
        return [types.TextContent(type="text", text=f"Error fetching position details: {str(e)}")]


async def get_portfolio_value(
    polymarket_client, rate_limiter, config, include_breakdown: bool = True
) -> List[types.TextContent]:
    """
    Get total portfolio value with optional breakdown by market.

    Args:
        polymarket_client: PolymarketClient instance
        rate_limiter: RateLimiter instance
        config: PolymarketConfig instance
        include_breakdown: Include market-by-market breakdown (default: True)

    Returns:
        List with portfolio value data
    """
    try:
        from ..utils.rate_limiter import EndpointCategory

        # Get balance
        await rate_limiter.acquire(EndpointCategory.CLOB_GENERAL)
        balance_data = await polymarket_client.get_balance()
        cash_balance = float(balance_data.get("balance", 0))

        # Get all positions
        await rate_limiter.acquire(EndpointCategory.DATA_API)
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://data-api.polymarket.com/positions",
                params={"user": config.POLYGON_ADDRESS.lower()},
                timeout=10.0,
            )
            response.raise_for_status()
            positions = response.json()

        # Get open orders
        try:
            await rate_limiter.acquire(EndpointCategory.CLOB_GENERAL)
            orders = await polymarket_client.get_orders()
        except Exception as e:
            logger.warning(f"Failed to fetch orders: {e}")
            orders = []

        # Calculate position values
        position_value = 0
        market_breakdown = defaultdict(lambda: {"value": 0, "positions": []})

        for pos in positions:
            size = float(pos.get("size", 0))
            if size <= 0:
                continue

            token_id = pos.get("asset_id")
            market_id = pos.get("market")

            # Get current price
            try:
                await rate_limiter.acquire(EndpointCategory.MARKET_DATA)
                orderbook = await polymarket_client.get_orderbook(token_id)
                best_bid = (
                    float(orderbook.get("bids", [{}])[0].get("price", 0))
                    if orderbook.get("bids")
                    else 0
                )
                best_ask = (
                    float(orderbook.get("asks", [{}])[0].get("price", 0))
                    if orderbook.get("asks")
                    else 0
                )
                mid_price = (
                    (best_bid + best_ask) / 2
                    if (best_bid and best_ask)
                    else float(pos.get("average_price", 0))
                )
            except Exception as e:
                logger.warning(f"Failed to fetch price for {token_id}: {e}")
                mid_price = float(pos.get("average_price", 0))

            value = size * mid_price
            position_value += value

            market_breakdown[market_id]["value"] += value
            market_breakdown[market_id]["positions"].append(
                {"outcome": pos.get("outcome", "Unknown"), "size": size, "value": value}
            )

        # Calculate pending order value
        pending_value = 0
        for order in orders:
            order_size = float(order.get("size", 0))
            order_price = float(order.get("price", 0))
            pending_value += order_size * order_price

        # Total value
        total_value = cash_balance + position_value + pending_value

        # Format output
        output_lines = [
            "Portfolio Value Summary",
            "=" * 80,
            "",
            f"Cash Balance (USDC): ${cash_balance:.2f}",
            f"Open Positions Value: ${position_value:.2f}",
            f"Pending Orders Value: ${pending_value:.2f}",
            "-" * 80,
            f"TOTAL PORTFOLIO VALUE: ${total_value:.2f}",
            "",
        ]

        if include_breakdown and market_breakdown:
            output_lines.extend(["Market Breakdown", "-" * 80])

            sorted_markets = sorted(
                market_breakdown.items(), key=lambda x: x[1]["value"], reverse=True
            )

            for market_id, data in sorted_markets:
                pct = (data["value"] / position_value * 100) if position_value > 0 else 0
                output_lines.extend(
                    [
                        f"Market: {market_id}",
                        f"  Value: ${data['value']:.2f} ({pct:.1f}% of positions)",
                        f"  Positions: {len(data['positions'])}",
                    ]
                )
                for pos in data["positions"]:
                    output_lines.append(
                        f"    - {pos['outcome']}: {pos['size']:.2f} shares (${pos['value']:.2f})"
                    )
                output_lines.append("")

        output_lines.append("=" * 80)

        return [types.TextContent(type="text", text="\n".join(output_lines))]

    except Exception as e:
        logger.error(f"Error calculating portfolio value: {e}")
        return [types.TextContent(type="text", text=f"Error calculating portfolio value: {str(e)}")]


async def get_pnl_summary(
    polymarket_client, rate_limiter, config, timeframe: Literal["24h", "7d", "30d", "all"] = "all"
) -> List[types.TextContent]:
    """
    Get profit/loss summary for specified timeframe.

    Args:
        polymarket_client: PolymarketClient instance
        rate_limiter: RateLimiter instance
        config: PolymarketConfig instance
        timeframe: Time period - '24h', '7d', '30d', or 'all' (default: 'all')

    Returns:
        List with P&L summary data
    """
    try:
        from ..utils.rate_limiter import EndpointCategory

        # Calculate time range
        now = datetime.now()
        timeframe_map = {
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
            "all": None,
        }

        start_time = (
            None if timeframe == "all" else int((now - timeframe_map[timeframe]).timestamp())
        )

        # Fetch trades
        await rate_limiter.acquire(EndpointCategory.DATA_API)
        async with httpx.AsyncClient() as client:
            params = {"user": config.POLYGON_ADDRESS.lower(), "limit": 500}
            if start_time:
                params["start_time"] = start_time

            response = await client.get(
                "https://data-api.polymarket.com/trades", params=params, timeout=10.0
            )
            response.raise_for_status()
            trades = response.json()

        # Fetch current positions for unrealized P&L
        await rate_limiter.acquire(EndpointCategory.DATA_API)
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://data-api.polymarket.com/positions",
                params={"user": config.POLYGON_ADDRESS.lower()},
                timeout=10.0,
            )
            response.raise_for_status()
            positions = response.json()

        # Calculate realized P&L from trades
        # Group trades by market and outcome to match buys with sells
        market_trades = defaultdict(lambda: defaultdict(list))
        for trade in trades:
            market_id = trade.get("market")
            outcome = trade.get("outcome")
            market_trades[market_id][outcome].append(trade)

        realized_pnl = 0
        wins = 0
        losses = 0

        for market_id, outcomes in market_trades.items():
            for outcome, outcome_trades in outcomes.items():
                # Sort by timestamp
                outcome_trades.sort(key=lambda t: int(t.get("timestamp", 0)))

                # Track position using FIFO
                position_queue = []  # [(price, size), ...]

                for trade in outcome_trades:
                    side = trade.get("side", "")
                    price = float(trade.get("price", 0))
                    size = float(trade.get("size", 0))

                    if side == "BUY":
                        position_queue.append((price, size))
                    elif side == "SELL":
                        # Match sells with buys
                        remaining_size = size
                        while remaining_size > 0 and position_queue:
                            buy_price, buy_size = position_queue[0]

                            if buy_size <= remaining_size:
                                # Full close of this buy
                                pnl = (price - buy_price) * buy_size
                                realized_pnl += pnl
                                if pnl > 0:
                                    wins += 1
                                else:
                                    losses += 1
                                remaining_size -= buy_size
                                position_queue.pop(0)
                            else:
                                # Partial close
                                pnl = (price - buy_price) * remaining_size
                                realized_pnl += pnl
                                if pnl > 0:
                                    wins += 1
                                else:
                                    losses += 1
                                position_queue[0] = (buy_price, buy_size - remaining_size)
                                remaining_size = 0

        # Calculate unrealized P&L from current positions
        unrealized_pnl = 0
        best_performer = None
        worst_performer = None

        for pos in positions:
            size = float(pos.get("size", 0))
            if size <= 0:
                continue

            avg_price = float(pos.get("average_price", 0))
            token_id = pos.get("asset_id")

            # Get current price
            try:
                await rate_limiter.acquire(EndpointCategory.MARKET_DATA)
                orderbook = await polymarket_client.get_orderbook(token_id)
                best_bid = (
                    float(orderbook.get("bids", [{}])[0].get("price", 0))
                    if orderbook.get("bids")
                    else 0
                )
                best_ask = (
                    float(orderbook.get("asks", [{}])[0].get("price", 0))
                    if orderbook.get("asks")
                    else 0
                )
                mid_price = (best_bid + best_ask) / 2 if (best_bid and best_ask) else avg_price
            except Exception as e:
                logger.warning(f"Failed to fetch price for {token_id}: {e}")
                mid_price = avg_price

            pnl = (mid_price - avg_price) * size
            unrealized_pnl += pnl

            # Track best/worst
            if best_performer is None or pnl > best_performer["pnl"]:
                best_performer = {
                    "question": pos.get("market_question", "Unknown"),
                    "outcome": pos.get("outcome", "Unknown"),
                    "pnl": pnl,
                }

            if worst_performer is None or pnl < worst_performer["pnl"]:
                worst_performer = {
                    "question": pos.get("market_question", "Unknown"),
                    "outcome": pos.get("outcome", "Unknown"),
                    "pnl": pnl,
                }

        # Calculate metrics
        total_pnl = realized_pnl + unrealized_pnl
        total_trades = wins + losses
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

        # Format output
        output_lines = [
            f"P&L Summary ({timeframe})",
            "=" * 80,
            "",
            "PROFIT & LOSS",
            "-" * 80,
            f"Realized P&L: ${realized_pnl:+.2f}",
            f"Unrealized P&L: ${unrealized_pnl:+.2f}",
            f"Total P&L: ${total_pnl:+.2f}",
            "",
            "TRADING STATISTICS",
            "-" * 80,
            f"Closed Trades: {total_trades}",
            f"Winning Trades: {wins}",
            f"Losing Trades: {losses}",
            f"Win Rate: {win_rate:.1f}%",
            "",
        ]

        if best_performer:
            output_lines.extend(
                [
                    "BEST PERFORMER",
                    "-" * 80,
                    f"{best_performer['question']}",
                    f"Outcome: {best_performer['outcome']}",
                    f"P&L: ${best_performer['pnl']:+.2f}",
                    "",
                ]
            )

        if worst_performer:
            output_lines.extend(
                [
                    "WORST PERFORMER",
                    "-" * 80,
                    f"{worst_performer['question']}",
                    f"Outcome: {worst_performer['outcome']}",
                    f"P&L: ${worst_performer['pnl']:+.2f}",
                    "",
                ]
            )

        output_lines.append("=" * 80)

        return [types.TextContent(type="text", text="\n".join(output_lines))]

    except Exception as e:
        logger.error(f"Error calculating P&L summary: {e}")
        return [types.TextContent(type="text", text=f"Error calculating P&L summary: {str(e)}")]


async def get_trade_history(
    polymarket_client,
    rate_limiter,
    config,
    market_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
    side: Literal["BUY", "SELL", "BOTH"] = "BOTH",
) -> List[types.TextContent]:
    """
    Get historical trades with filtering.

    Args:
        polymarket_client: PolymarketClient instance
        rate_limiter: RateLimiter instance
        config: PolymarketConfig instance
        market_id: Filter by market ID (optional)
        start_date: Start date in ISO format (optional)
        end_date: End date in ISO format (optional)
        limit: Maximum trades to return (default: 100)
        side: Filter by side - 'BUY', 'SELL', or 'BOTH' (default: 'BOTH')

    Returns:
        List with trade history
    """
    try:
        from ..utils.rate_limiter import EndpointCategory

        # Build query parameters
        params = {"user": config.POLYGON_ADDRESS.lower(), "limit": min(limit, 500)}

        if market_id:
            params["market"] = market_id

        if start_date:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            params["start_time"] = int(start_dt.timestamp())

        if end_date:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            params["end_time"] = int(end_dt.timestamp())

        # Fetch trades
        await rate_limiter.acquire(EndpointCategory.DATA_API)
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://data-api.polymarket.com/trades", params=params, timeout=10.0
            )
            response.raise_for_status()
            trades = response.json()

        # Filter by side
        if side != "BOTH":
            trades = [t for t in trades if t.get("side", "").upper() == side.upper()]

        if not trades:
            return [types.TextContent(type="text", text="No trades found matching criteria.")]

        # Format output
        output_lines = [f"Trade History ({len(trades)} trades)", "=" * 80, ""]

        total_volume = 0

        for trade in trades[:limit]:
            timestamp = int(trade.get("timestamp", 0))
            trade_date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
            market_question = trade.get("market_question", "Unknown")
            outcome = trade.get("outcome", "Unknown")
            trade_side = trade.get("side", "UNKNOWN")
            price = float(trade.get("price", 0))
            size = float(trade.get("size", 0))
            value = price * size
            fee = float(trade.get("fee", 0))

            total_volume += value

            output_lines.extend(
                [
                    f"[{trade_date}] {trade_side}",
                    f"Market: {market_question}",
                    f"Outcome: {outcome}",
                    f"Price: ${price:.4f} | Size: {size:.2f} shares",
                    f"Value: ${value:.2f} | Fee: ${fee:.4f}",
                    f"Trade ID: {trade.get('id', 'N/A')}",
                    "",
                ]
            )

        output_lines.extend(["=" * 80, f"Total Volume: ${total_volume:.2f}", ""])

        return [types.TextContent(type="text", text="\n".join(output_lines))]

    except Exception as e:
        logger.error(f"Error fetching trade history: {e}")
        return [types.TextContent(type="text", text=f"Error fetching trade history: {str(e)}")]


async def get_activity_log(
    polymarket_client,
    rate_limiter,
    config,
    activity_type: Literal["trades", "splits", "merges", "redeems", "all"] = "all",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
) -> List[types.TextContent]:
    """
    Get on-chain activity log.

    Args:
        polymarket_client: PolymarketClient instance
        rate_limiter: RateLimiter instance
        config: PolymarketConfig instance
        activity_type: Filter by type - 'trades', 'splits', 'merges', 'redeems', or 'all'
        start_date: Start date in ISO format (optional)
        end_date: End date in ISO format (optional)
        limit: Maximum events to return (default: 100)

    Returns:
        List with activity log
    """
    try:
        from ..utils.rate_limiter import EndpointCategory

        # Build query parameters
        params = {"user": config.POLYGON_ADDRESS.lower(), "limit": min(limit, 500)}

        if activity_type != "all":
            params["type"] = activity_type

        if start_date:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            params["start_time"] = int(start_dt.timestamp())

        if end_date:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            params["end_time"] = int(end_dt.timestamp())

        # Fetch activity
        await rate_limiter.acquire(EndpointCategory.DATA_API)
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://data-api.polymarket.com/activity", params=params, timeout=10.0
            )
            response.raise_for_status()
            activities = response.json()

        if not activities:
            return [types.TextContent(type="text", text="No activity found matching criteria.")]

        # Format output
        output_lines = [f"Activity Log ({len(activities)} events)", "=" * 80, ""]

        for activity in activities[:limit]:
            timestamp = int(activity.get("timestamp", 0))
            activity_date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
            event_type = activity.get("type", "UNKNOWN").upper()
            market_question = activity.get("market_question", "N/A")
            amount = float(activity.get("amount", 0))
            value = float(activity.get("value", 0))
            tx_hash = activity.get("transaction_hash", "N/A")

            output_lines.extend(
                [
                    f"[{activity_date}] {event_type}",
                    f"Market: {market_question}",
                    f"Amount: {amount:.2f} | Value: ${value:.2f}",
                    f"Tx Hash: {tx_hash[:10]}...{tx_hash[-8:] if len(tx_hash) > 18 else tx_hash}",
                    "",
                ]
            )

        output_lines.append("=" * 80)

        return [types.TextContent(type="text", text="\n".join(output_lines))]

    except Exception as e:
        logger.error(f"Error fetching activity log: {e}")
        return [types.TextContent(type="text", text=f"Error fetching activity log: {str(e)}")]


async def analyze_portfolio_risk(
    polymarket_client, rate_limiter, config
) -> List[types.TextContent]:
    """
    Analyze portfolio risk and provide risk metrics.

    Args:
        polymarket_client: PolymarketClient instance
        rate_limiter: RateLimiter instance
        config: PolymarketConfig instance

    Returns:
        List with risk analysis
    """
    try:
        from ..utils.rate_limiter import EndpointCategory

        # Fetch all positions
        await rate_limiter.acquire(EndpointCategory.DATA_API)
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://data-api.polymarket.com/positions",
                params={"user": config.POLYGON_ADDRESS.lower()},
                timeout=10.0,
            )
            response.raise_for_status()
            positions = response.json()

        if not positions:
            return [types.TextContent(type="text", text="No positions to analyze.")]

        # Calculate position metrics
        position_values = []
        market_exposures = defaultdict(float)
        low_liquidity_positions = []

        total_exposure = 0

        for pos in positions:
            size = float(pos.get("size", 0))
            if size <= 0:
                continue

            token_id = pos.get("asset_id")
            market_id = pos.get("market")
            avg_price = float(pos.get("average_price", 0))

            # Get current price and liquidity
            try:
                await rate_limiter.acquire(EndpointCategory.MARKET_DATA)
                orderbook = await polymarket_client.get_orderbook(token_id)

                bids = orderbook.get("bids", [])
                asks = orderbook.get("asks", [])
                best_bid = float(bids[0]["price"]) if bids else 0
                best_ask = float(asks[0]["price"]) if asks else 0
                mid_price = (best_bid + best_ask) / 2 if (best_bid and best_ask) else avg_price

                # Calculate liquidity
                bid_liquidity = (
                    sum(float(b["price"]) * float(b["size"]) for b in bids[:5]) if bids else 0
                )
                ask_liquidity = (
                    sum(float(a["price"]) * float(a["size"]) for a in asks[:5]) if asks else 0
                )
                total_liquidity = bid_liquidity + ask_liquidity

                if total_liquidity < 1000:
                    low_liquidity_positions.append(
                        {
                            "question": pos.get("market_question", "Unknown"),
                            "outcome": pos.get("outcome", "Unknown"),
                            "liquidity": total_liquidity,
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to fetch orderbook for {token_id}: {e}")
                mid_price = avg_price
                total_liquidity = 0

            value = size * mid_price
            position_values.append(value)
            market_exposures[market_id] += value
            total_exposure += value

        # Calculate risk metrics

        # 1. Concentration risk
        largest_position = max(position_values) if position_values else 0
        concentration_risk = (largest_position / total_exposure * 100) if total_exposure > 0 else 0

        largest_market = max(market_exposures.values()) if market_exposures else 0
        market_concentration = (largest_market / total_exposure * 100) if total_exposure > 0 else 0

        # 2. Diversification score (higher is better)
        num_positions = len(position_values)
        num_markets = len(market_exposures)
        diversification_score = min(100, (num_positions * 10 + num_markets * 20))

        # 3. Liquidity risk
        liquidity_risk = len(low_liquidity_positions)

        # 4. Calculate overall risk score (0-100, lower is better)
        risk_score = 0

        # Concentration penalty (0-40 points)
        if concentration_risk > 50:
            risk_score += 40
        elif concentration_risk > 30:
            risk_score += 25
        elif concentration_risk > 20:
            risk_score += 15

        # Market concentration penalty (0-30 points)
        if market_concentration > 60:
            risk_score += 30
        elif market_concentration > 40:
            risk_score += 20
        elif market_concentration > 30:
            risk_score += 10

        # Liquidity penalty (0-20 points)
        liquidity_risk_pct = (liquidity_risk / num_positions * 100) if num_positions > 0 else 0
        if liquidity_risk_pct > 50:
            risk_score += 20
        elif liquidity_risk_pct > 30:
            risk_score += 15
        elif liquidity_risk_pct > 10:
            risk_score += 10

        # Diversification bonus (reduce risk)
        risk_score = max(0, risk_score - (diversification_score // 5))

        # Generate recommendations
        recommendations = []

        if concentration_risk > 30:
            recommendations.append(
                f"High position concentration ({concentration_risk:.1f}% in largest position) - "
                "Consider reducing largest position"
            )

        if market_concentration > 40:
            recommendations.append(
                f"High market concentration ({market_concentration:.1f}% in one market) - "
                "Diversify across more markets"
            )

        if liquidity_risk_pct > 20:
            recommendations.append(
                f"{liquidity_risk} positions have low liquidity - "
                "May be difficult to exit at fair prices"
            )

        if num_markets < 3:
            recommendations.append(
                "Portfolio concentrated in few markets - "
                "Consider diversifying to reduce correlation risk"
            )

        if not recommendations:
            recommendations.append("Portfolio risk levels are within acceptable parameters")

        # Format output
        output_lines = [
            "Portfolio Risk Analysis",
            "=" * 80,
            "",
            "EXPOSURE METRICS",
            "-" * 80,
            f"Total Exposure: ${total_exposure:.2f}",
            f"Number of Positions: {num_positions}",
            f"Number of Markets: {num_markets}",
            "",
            "CONCENTRATION RISK",
            "-" * 80,
            f"Largest Position: ${largest_position:.2f} ({concentration_risk:.1f}% of total)",
            f"Largest Market: ${largest_market:.2f} ({market_concentration:.1f}% of total)",
            "",
            "LIQUIDITY RISK",
            "-" * 80,
            f"Positions with Low Liquidity (<$1000): {liquidity_risk}",
        ]

        if low_liquidity_positions:
            for pos in low_liquidity_positions[:5]:
                output_lines.append(
                    f"  • {pos['question'][:60]}... - ${pos['liquidity']:.2f} liquidity"
                )

        output_lines.extend(
            [
                "",
                "RISK SCORE",
                "-" * 80,
                f"Overall Risk Score: {risk_score}/100",
                f"Diversification Score: {diversification_score}/100",
                "",
            ]
        )

        # Risk level
        if risk_score < 30:
            risk_level = "LOW"
        elif risk_score < 60:
            risk_level = "MODERATE"
        else:
            risk_level = "HIGH"

        output_lines.extend([f"Risk Level: {risk_level}", "", "RECOMMENDATIONS", "-" * 80])

        for rec in recommendations:
            output_lines.append(f"  • {rec}")

        output_lines.extend(["", "=" * 80])

        return [types.TextContent(type="text", text="\n".join(output_lines))]

    except Exception as e:
        logger.error(f"Error analyzing portfolio risk: {e}")
        return [types.TextContent(type="text", text=f"Error analyzing portfolio risk: {str(e)}")]


async def suggest_portfolio_actions(
    polymarket_client,
    rate_limiter,
    config,
    goal: Literal["balanced", "aggressive", "conservative"] = "balanced",
    max_actions: int = 5,
) -> List[types.TextContent]:
    """
    Suggest portfolio optimization actions based on goal.

    Args:
        polymarket_client: PolymarketClient instance
        rate_limiter: RateLimiter instance
        config: PolymarketConfig instance
        goal: Investment goal - 'balanced', 'aggressive', or 'conservative' (default: 'balanced')
        max_actions: Maximum number of suggestions (default: 5)

    Returns:
        List with suggested actions
    """
    try:
        from ..utils.rate_limiter import EndpointCategory

        # Fetch all positions
        await rate_limiter.acquire(EndpointCategory.DATA_API)
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://data-api.polymarket.com/positions",
                params={"user": config.POLYGON_ADDRESS.lower()},
                timeout=10.0,
            )
            response.raise_for_status()
            positions = response.json()

        if not positions:
            return [types.TextContent(type="text", text="No positions to optimize.")]

        # Analyze positions and generate suggestions
        suggestions = []

        total_value = 0
        position_data = []

        for pos in positions:
            size = float(pos.get("size", 0))
            if size <= 0:
                continue

            token_id = pos.get("asset_id")
            avg_price = float(pos.get("average_price", 0))

            # Get current market data
            try:
                await rate_limiter.acquire(EndpointCategory.MARKET_DATA)
                orderbook = await polymarket_client.get_orderbook(token_id)

                bids = orderbook.get("bids", [])
                asks = orderbook.get("asks", [])
                best_bid = float(bids[0]["price"]) if bids else 0
                best_ask = float(asks[0]["price"]) if asks else 0
                mid_price = (best_bid + best_ask) / 2 if (best_bid and best_ask) else avg_price
                spread = (best_ask - best_bid) if (best_bid and best_ask) else 0

                # Liquidity
                bid_liquidity = (
                    sum(float(b["price"]) * float(b["size"]) for b in bids[:5]) if bids else 0
                )
                ask_liquidity = (
                    sum(float(a["price"]) * float(a["size"]) for a in asks[:5]) if asks else 0
                )
                total_liquidity = bid_liquidity + ask_liquidity
            except Exception as e:
                logger.warning(f"Failed to fetch orderbook for {token_id}: {e}")
                mid_price = avg_price
                spread = 0
                total_liquidity = 0

            value = size * mid_price
            cost_basis = size * avg_price
            pnl = value - cost_basis
            pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0

            total_value += value

            position_data.append(
                {
                    "question": pos.get("market_question", "Unknown"),
                    "outcome": pos.get("outcome", "Unknown"),
                    "market_id": pos.get("market"),
                    "value": value,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "price": mid_price,
                    "spread": spread,
                    "liquidity": total_liquidity,
                }
            )

        # Sort by value
        position_data.sort(key=lambda x: x["value"], reverse=True)

        # Goal-specific thresholds
        thresholds = {
            "conservative": {
                "take_profit": 15,
                "stop_loss": -10,
                "concentration_max": 20,
                "min_liquidity": 2000,
            },
            "balanced": {
                "take_profit": 25,
                "stop_loss": -20,
                "concentration_max": 30,
                "min_liquidity": 1000,
            },
            "aggressive": {
                "take_profit": 40,
                "stop_loss": -30,
                "concentration_max": 40,
                "min_liquidity": 500,
            },
        }

        thresh = thresholds[goal]

        # Generate suggestions

        # 1. Take profit suggestions
        for pos in position_data:
            if pos["pnl_pct"] > thresh["take_profit"]:
                suggestions.append(
                    {
                        "action": "CLOSE",
                        "market": pos["question"],
                        "outcome": pos["outcome"],
                        "reasoning": f"Take profit - position up {pos['pnl_pct']:+.1f}%",
                        "impact": f"Realize ${pos['pnl']:+.2f} gain",
                        "priority": (
                            "HIGH" if pos["pnl_pct"] > thresh["take_profit"] * 1.5 else "MEDIUM"
                        ),
                    }
                )

        # 2. Stop loss suggestions
        for pos in position_data:
            if pos["pnl_pct"] < thresh["stop_loss"]:
                suggestions.append(
                    {
                        "action": "CLOSE",
                        "market": pos["question"],
                        "outcome": pos["outcome"],
                        "reasoning": f"Cut losses - position down {pos['pnl_pct']:+.1f}%",
                        "impact": f"Limit loss to ${pos['pnl']:+.2f}",
                        "priority": (
                            "HIGH" if pos["pnl_pct"] < thresh["stop_loss"] * 1.5 else "MEDIUM"
                        ),
                    }
                )

        # 3. Concentration reduction
        for pos in position_data:
            concentration_pct = (pos["value"] / total_value * 100) if total_value > 0 else 0
            if concentration_pct > thresh["concentration_max"]:
                suggestions.append(
                    {
                        "action": "REDUCE",
                        "market": pos["question"],
                        "outcome": pos["outcome"],
                        "reasoning": f"Reduce concentration - {concentration_pct:.1f}% of portfolio",
                        "impact": f"Reduce to {thresh['concentration_max']}% max ({thresh['concentration_max'] / 100 * total_value:.2f} USD)",
                        "priority": "MEDIUM",
                    }
                )

        # 4. Low liquidity warnings
        for pos in position_data:
            if pos["liquidity"] < thresh["min_liquidity"]:
                suggestions.append(
                    {
                        "action": "CLOSE",
                        "market": pos["question"],
                        "outcome": pos["outcome"],
                        "reasoning": f"Exit low liquidity position (${pos['liquidity']:.2f} available)",
                        "impact": "Avoid potential slippage on future exit",
                        "priority": "LOW",
                    }
                )

        # 5. Wide spread warnings
        for pos in position_data:
            if pos["spread"] > 0.10:  # 10% spread
                suggestions.append(
                    {
                        "action": "REDUCE",
                        "market": pos["question"],
                        "outcome": pos["outcome"],
                        "reasoning": f"Wide spread ({pos['spread'] * 100:.1f}%) - poor exit conditions",
                        "impact": "Reduce exposure until spread improves",
                        "priority": "LOW",
                    }
                )

        # Sort by priority and limit
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        suggestions.sort(
            key=lambda x: (priority_order[x["priority"]], -abs(position_data[0]["pnl_pct"]))
        )
        suggestions = suggestions[:max_actions]

        # Format output
        output_lines = [
            f"Portfolio Optimization Suggestions ({goal.upper()} goal)",
            "=" * 80,
            "",
            f"Analyzed {len(position_data)} positions worth ${total_value:.2f}",
            f"Generated {len(suggestions)} actionable suggestions",
            "",
            "SUGGESTED ACTIONS",
            "=" * 80,
            "",
        ]

        if not suggestions:
            output_lines.extend(
                [
                    "No optimization actions recommended at this time.",
                    "Portfolio appears well-balanced for your goals.",
                    "",
                ]
            )
        else:
            for i, sugg in enumerate(suggestions, 1):
                output_lines.extend(
                    [
                        f"{i}. {sugg['action']} - {sugg['market'][:60]}...",
                        f"   Outcome: {sugg['outcome']}",
                        f"   Reasoning: {sugg['reasoning']}",
                        f"   Expected Impact: {sugg['impact']}",
                        f"   Priority: {sugg['priority']}",
                        "",
                    ]
                )

        output_lines.append("=" * 80)

        return [types.TextContent(type="text", text="\n".join(output_lines))]

    except Exception as e:
        logger.error(f"Error generating portfolio suggestions: {e}")
        return [
            types.TextContent(type="text", text=f"Error generating portfolio suggestions: {str(e)}")
        ]


# Tool registration data for server integration
PORTFOLIO_TOOLS = [
    {
        "name": "get_all_positions",
        "description": "Get all user positions with filtering and sorting options",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_closed": {
                    "type": "boolean",
                    "description": "Include closed positions (default: false)",
                    "default": False,
                },
                "min_value": {
                    "type": "number",
                    "description": "Minimum position value in USD (default: 1.0)",
                    "default": 1.0,
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["value", "pnl", "size"],
                    "description": "Sort field (default: value)",
                    "default": "value",
                },
            },
        },
        "handler": get_all_positions,
    },
    {
        "name": "get_position_details",
        "description": "Get detailed view of a specific position including market data and suggestions",
        "inputSchema": {
            "type": "object",
            "properties": {"market_id": {"type": "string", "description": "Market condition ID"}},
            "required": ["market_id"],
        },
        "handler": get_position_details,
    },
    {
        "name": "get_portfolio_value",
        "description": "Get total portfolio value with optional market breakdown",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_breakdown": {
                    "type": "boolean",
                    "description": "Include market-by-market breakdown (default: true)",
                    "default": True,
                }
            },
        },
        "handler": get_portfolio_value,
    },
    {
        "name": "get_pnl_summary",
        "description": "Get profit/loss summary for specified timeframe",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeframe": {
                    "type": "string",
                    "enum": ["24h", "7d", "30d", "all"],
                    "description": "Time period (default: all)",
                    "default": "all",
                }
            },
        },
        "handler": get_pnl_summary,
    },
    {
        "name": "get_trade_history",
        "description": "Get historical trades with filtering options",
        "inputSchema": {
            "type": "object",
            "properties": {
                "market_id": {"type": "string", "description": "Filter by market ID (optional)"},
                "start_date": {
                    "type": "string",
                    "description": "Start date in ISO format (optional)",
                },
                "end_date": {"type": "string", "description": "End date in ISO format (optional)"},
                "limit": {
                    "type": "number",
                    "description": "Maximum trades to return (default: 100)",
                    "default": 100,
                },
                "side": {
                    "type": "string",
                    "enum": ["BUY", "SELL", "BOTH"],
                    "description": "Filter by side (default: BOTH)",
                    "default": "BOTH",
                },
            },
        },
        "handler": get_trade_history,
    },
    {
        "name": "get_activity_log",
        "description": "Get on-chain activity log (trades, splits, merges, redeems)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "activity_type": {
                    "type": "string",
                    "enum": ["trades", "splits", "merges", "redeems", "all"],
                    "description": "Activity type filter (default: all)",
                    "default": "all",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in ISO format (optional)",
                },
                "end_date": {"type": "string", "description": "End date in ISO format (optional)"},
                "limit": {
                    "type": "number",
                    "description": "Maximum events to return (default: 100)",
                    "default": 100,
                },
            },
        },
        "handler": get_activity_log,
    },
    {
        "name": "analyze_portfolio_risk",
        "description": "Analyze portfolio risk including concentration, liquidity, and correlation",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": analyze_portfolio_risk,
    },
    {
        "name": "suggest_portfolio_actions",
        "description": "Get AI-powered portfolio optimization suggestions based on investment goal",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "enum": ["balanced", "aggressive", "conservative"],
                    "description": "Investment goal (default: balanced)",
                    "default": "balanced",
                },
                "max_actions": {
                    "type": "number",
                    "description": "Maximum number of suggestions (default: 5)",
                    "default": 5,
                },
            },
        },
        "handler": suggest_portfolio_actions,
    },
]
