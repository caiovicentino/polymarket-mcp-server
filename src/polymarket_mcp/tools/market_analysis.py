"""
Market Analysis Tools for Polymarket MCP Server.

Provides 10 tools for analyzing markets:
- get_market_details: Complete market information
- get_current_price: Current bid/ask prices
- get_orderbook: Complete order book
- get_spread: Current spread
- get_market_volume: Volume statistics
- get_liquidity: Available liquidity
- get_price_history: Historical price data
- get_market_holders: Top position holders
- analyze_market_opportunity: AI-powered analysis
- compare_markets: Compare multiple markets
"""
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
import mcp.types as types
import httpx

from ..utils.rate_limiter import EndpointCategory, get_rate_limiter

logger = logging.getLogger(__name__)

# API URLs
GAMMA_API_URL = "https://gamma-api.polymarket.com"
CLOB_API_URL = "https://clob.polymarket.com"


# Data Models
class PriceData(BaseModel):
    """Price information for a token"""
    token_id: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    last: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class OrderBookEntry(BaseModel):
    """Single order book entry"""
    price: float
    size: float


class OrderBook(BaseModel):
    """Complete order book"""
    token_id: str
    bids: List[OrderBookEntry]
    asks: List[OrderBookEntry]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class VolumeData(BaseModel):
    """Volume statistics"""
    market_id: str
    volume_24h: Optional[float] = None
    volume_7d: Optional[float] = None
    volume_30d: Optional[float] = None
    volume_all_time: Optional[float] = None


class MarketOpportunity(BaseModel):
    """Market analysis and opportunity assessment"""
    market_id: str
    market_question: str
    current_price_yes: Optional[float] = None
    current_price_no: Optional[float] = None
    spread: Optional[float] = None
    spread_pct: Optional[float] = None
    volume_24h: Optional[float] = None
    liquidity_usd: Optional[float] = None
    price_trend_24h: Optional[str] = None  # "up", "down", "stable"
    risk_assessment: str  # "low", "medium", "high"
    recommendation: str  # "BUY", "SELL", "HOLD", "AVOID"
    confidence_score: float  # 0-100
    reasoning: str
    last_updated: datetime = Field(default_factory=datetime.utcnow)


async def _fetch_gamma_api(endpoint: str, params: Optional[Dict] = None) -> Any:
    """Fetch from Gamma API with rate limiting"""
    rate_limiter = get_rate_limiter()

    await rate_limiter.acquire(EndpointCategory.GAMMA_API)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{GAMMA_API_URL}{endpoint}"
            response = await client.get(url, params=params or {})
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Gamma API error for {endpoint}: {e}")
        raise


async def _fetch_clob_api(endpoint: str, params: Optional[Dict] = None) -> Any:
    """Fetch from CLOB API with rate limiting"""
    rate_limiter = get_rate_limiter()

    await rate_limiter.acquire(EndpointCategory.MARKET_DATA)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{CLOB_API_URL}{endpoint}"
            response = await client.get(url, params=params or {})
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"CLOB API error for {endpoint}: {e}")
        raise


async def get_market_details(
    market_id: Optional[str] = None,
    condition_id: Optional[str] = None,
    slug: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get complete market information.

    Args:
        market_id: Market ID
        condition_id: Condition ID (alternative identifier)
        slug: Market slug (alternative identifier)

    Returns:
        Full market object with all metadata
    """
    try:
        # Determine which identifier to use
        if slug:
            data = await _fetch_gamma_api(f"/markets/{slug}")
        elif condition_id:
            data = await _fetch_gamma_api("/markets", {"condition_id": condition_id})
        elif market_id:
            data = await _fetch_gamma_api(f"/markets/{market_id}")
        else:
            raise ValueError("One of market_id, condition_id, or slug must be provided")

        # Handle list response
        if isinstance(data, list) and len(data) > 0:
            return data[0]

        return data

    except Exception as e:
        logger.error(f"Failed to get market details: {e}")
        raise


async def get_current_price(
    token_id: str,
    side: str = "BOTH"
) -> PriceData:
    """
    Get current bid/ask prices.

    Args:
        token_id: Token ID
        side: 'BUY', 'SELL', or 'BOTH' (default)

    Returns:
        PriceData object with bid, ask, and mid prices
    """
    try:
        price_data = PriceData(token_id=token_id)

        if side in ["BUY", "BOTH"]:
            buy_data = await _fetch_clob_api("/price", {"token_id": token_id, "side": "BUY"})
            price_data.ask = float(buy_data.get("price", 0))

        if side in ["SELL", "BOTH"]:
            sell_data = await _fetch_clob_api("/price", {"token_id": token_id, "side": "SELL"})
            price_data.bid = float(sell_data.get("price", 0))

        # Calculate mid price
        if price_data.bid is not None and price_data.ask is not None:
            price_data.mid = (price_data.bid + price_data.ask) / 2.0

        logger.info(f"Price for {token_id}: bid={price_data.bid}, ask={price_data.ask}")

        return price_data

    except Exception as e:
        logger.error(f"Failed to get current price: {e}")
        raise


async def get_orderbook(
    token_id: str,
    depth: int = 20
) -> OrderBook:
    """
    Get complete order book.

    Args:
        token_id: Token ID
        depth: Number of price levels to return per side (default 20)

    Returns:
        OrderBook with bids and asks
    """
    try:
        book_data = await _fetch_clob_api("/book", {"token_id": token_id})

        # Parse bids and asks
        bids = [
            OrderBookEntry(price=float(entry["price"]), size=float(entry["size"]))
            for entry in book_data.get("bids", [])[:depth]
        ]

        asks = [
            OrderBookEntry(price=float(entry["price"]), size=float(entry["size"]))
            for entry in book_data.get("asks", [])[:depth]
        ]

        orderbook = OrderBook(
            token_id=token_id,
            bids=bids,
            asks=asks
        )

        logger.info(f"Orderbook for {token_id}: {len(bids)} bids, {len(asks)} asks")

        return orderbook

    except Exception as e:
        logger.error(f"Failed to get orderbook: {e}")
        raise


async def get_spread(token_id: str) -> Dict[str, float]:
    """
    Get current spread.

    Args:
        token_id: Token ID

    Returns:
        Spread value and percentage
    """
    try:
        price_data = await get_current_price(token_id, "BOTH")

        if price_data.bid is None or price_data.ask is None:
            raise ValueError("Could not retrieve both bid and ask prices")

        spread_value = price_data.ask - price_data.bid
        spread_pct = (spread_value / price_data.mid) * 100 if price_data.mid else 0

        result = {
            "token_id": token_id,
            "spread_value": spread_value,
            "spread_percentage": spread_pct,
            "bid": price_data.bid,
            "ask": price_data.ask,
            "mid": price_data.mid
        }

        logger.info(f"Spread for {token_id}: {spread_value:.4f} ({spread_pct:.2f}%)")

        return result

    except Exception as e:
        logger.error(f"Failed to get spread: {e}")
        raise


async def get_market_volume(
    market_id: str,
    timeframes: Optional[List[str]] = None
) -> VolumeData:
    """
    Get volume statistics.

    Args:
        market_id: Market ID
        timeframes: List of timeframes (default: ['24h', '7d', '30d'])

    Returns:
        VolumeData with breakdown by timeframe
    """
    try:
        if timeframes is None:
            timeframes = ['24h', '7d', '30d']

        # Get market details which include volume data
        market_data = await get_market_details(market_id=market_id)

        volume_data = VolumeData(market_id=market_id)

        # Extract volume for each timeframe
        volume_data.volume_24h = float(market_data.get("volume24hr", 0) or 0)
        volume_data.volume_7d = float(market_data.get("volume7d", 0) or 0)
        volume_data.volume_30d = float(market_data.get("volume30d", 0) or 0)
        volume_data.volume_all_time = float(market_data.get("volumeNum", 0) or 0)

        logger.info(f"Volume for {market_id}: 24h=${volume_data.volume_24h}")

        return volume_data

    except Exception as e:
        logger.error(f"Failed to get market volume: {e}")
        raise


async def get_liquidity(market_id: str) -> Dict[str, Any]:
    """
    Get available liquidity.

    Args:
        market_id: Market ID

    Returns:
        Total liquidity in USD
    """
    try:
        market_data = await get_market_details(market_id=market_id)

        liquidity = float(market_data.get("liquidity", 0) or 0)

        result = {
            "market_id": market_id,
            "liquidity_usd": liquidity,
            "liquidity_formatted": f"${liquidity:,.2f}"
        }

        logger.info(f"Liquidity for {market_id}: ${liquidity:,.2f}")

        return result

    except Exception as e:
        logger.error(f"Failed to get liquidity: {e}")
        raise


async def get_price_history(
    token_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    resolution: str = "1h"
) -> List[Dict[str, Any]]:
    """
    Get historical price data.

    Args:
        token_id: Token ID
        start_date: Start date (ISO format or timestamp)
        end_date: End date (ISO format or timestamp)
        resolution: Time resolution ('1m', '5m', '1h', '1d')

    Returns:
        OHLC price data
    """
    try:
        # Calculate default date range if not provided
        if not end_date:
            end_date = datetime.utcnow().isoformat()

        if not start_date:
            # Default to 7 days ago
            start_dt = datetime.utcnow() - timedelta(days=7)
            start_date = start_dt.isoformat()

        # Note: Polymarket doesn't have a public historical price API
        # This would need to be implemented with a data provider or by storing prices
        # For now, return a placeholder response

        logger.warning(
            "Historical price data not available via public API. "
            "Consider using a third-party data provider."
        )

        return [{
            "error": "Historical price data not available via public Polymarket API",
            "suggestion": "Use real-time price tracking or third-party data providers"
        }]

    except Exception as e:
        logger.error(f"Failed to get price history: {e}")
        raise


async def get_market_holders(
    market_id: str,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Get top position holders.

    Args:
        market_id: Market ID
        limit: Number of top holders to return (default 10)

    Returns:
        Top holders with positions
    """
    try:
        # Note: Position holder data requires authenticated access
        # and may not be publicly available for all users

        logger.warning(
            "Position holder data requires authenticated access and "
            "may not be publicly available"
        )

        return [{
            "error": "Position holder data not available via public API",
            "suggestion": "This data may require authenticated access with proper permissions"
        }]

    except Exception as e:
        logger.error(f"Failed to get market holders: {e}")
        raise


async def analyze_market_opportunity(market_id: str) -> MarketOpportunity:
    """
    AI-powered market analysis.

    Args:
        market_id: Market ID

    Returns:
        Complete analysis with recommendation
    """
    try:
        # Get comprehensive market data
        market_details = await get_market_details(market_id=market_id)

        # Get volume and liquidity
        volume_data = await get_market_volume(market_id)
        liquidity_data = await get_liquidity(market_id)

        # Get current prices for tokens
        tokens = market_details.get("tokens", [])
        token_prices = {}

        if len(tokens) >= 2:
            # Get YES and NO token prices
            yes_token = tokens[0]
            no_token = tokens[1]

            try:
                yes_price = await get_current_price(yes_token.get("token_id"), "BOTH")
                no_price = await get_current_price(no_token.get("token_id"), "BOTH")

                token_prices["yes"] = yes_price.mid
                token_prices["no"] = no_price.mid

                # Calculate spread
                if yes_price.bid and yes_price.ask:
                    spread_value = yes_price.ask - yes_price.bid
                    spread_pct = (spread_value / yes_price.mid) * 100 if yes_price.mid else 0
                else:
                    spread_value = None
                    spread_pct = None

            except Exception as price_error:
                logger.warning(f"Could not fetch token prices: {price_error}")
                spread_value = None
                spread_pct = None
        else:
            spread_value = None
            spread_pct = None

        # Analyze market conditions
        liquidity_usd = liquidity_data.get("liquidity_usd", 0)
        volume_24h = volume_data.volume_24h or 0

        # Risk assessment
        if liquidity_usd < 10000:
            risk = "high"
            risk_reason = "Low liquidity"
        elif spread_pct and spread_pct > 5:
            risk = "high"
            risk_reason = "High spread"
        elif volume_24h < 1000:
            risk = "medium"
            risk_reason = "Low trading volume"
        else:
            risk = "low"
            risk_reason = "Good liquidity and volume"

        # Generate recommendation
        if risk == "high":
            recommendation = "AVOID"
            confidence = 30
            reasoning = f"Risk assessment: {risk_reason}. Market conditions not favorable for trading."
        elif liquidity_usd > 50000 and volume_24h > 10000:
            recommendation = "HOLD"
            confidence = 70
            reasoning = f"Healthy market with good liquidity (${liquidity_usd:,.0f}) and volume (${volume_24h:,.0f})."
        elif spread_pct and spread_pct < 2:
            recommendation = "BUY"
            confidence = 65
            reasoning = f"Tight spread ({spread_pct:.2f}%) indicates efficient market. Good entry opportunity."
        else:
            recommendation = "HOLD"
            confidence = 50
            reasoning = "Market conditions are acceptable but not optimal. Monitor for better entry points."

        # Price trend (simplified)
        price_trend = "stable"  # Would need historical data for accurate trend

        opportunity = MarketOpportunity(
            market_id=market_id,
            market_question=market_details.get("question", "Unknown"),
            current_price_yes=token_prices.get("yes"),
            current_price_no=token_prices.get("no"),
            spread=spread_value,
            spread_pct=spread_pct,
            volume_24h=volume_24h,
            liquidity_usd=liquidity_usd,
            price_trend_24h=price_trend,
            risk_assessment=risk,
            recommendation=recommendation,
            confidence_score=confidence,
            reasoning=reasoning
        )

        logger.info(
            f"Analysis for {market_id}: {recommendation} "
            f"(confidence: {confidence}%, risk: {risk})"
        )

        return opportunity

    except Exception as e:
        logger.error(f"Failed to analyze market opportunity: {e}")
        raise


async def compare_markets(market_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Compare multiple markets.

    Args:
        market_ids: List of market IDs to compare

    Returns:
        Comparison table with metrics for each market
    """
    try:
        if len(market_ids) < 2:
            raise ValueError("At least 2 markets required for comparison")

        if len(market_ids) > 10:
            raise ValueError("Maximum 10 markets can be compared at once")

        comparisons = []

        for market_id in market_ids:
            try:
                # Get market details
                market = await get_market_details(market_id=market_id)
                volume = await get_market_volume(market_id)
                liquidity = await get_liquidity(market_id)

                # Compile comparison data
                comparison = {
                    "market_id": market_id,
                    "question": market.get("question", "Unknown"),
                    "volume_24h": volume.volume_24h,
                    "volume_7d": volume.volume_7d,
                    "liquidity_usd": liquidity.get("liquidity_usd"),
                    "end_date": market.get("endDate") or market.get("end_date_iso"),
                    "active": market.get("active", True),
                    "tags": market.get("tags", [])
                }

                comparisons.append(comparison)

            except Exception as market_error:
                logger.warning(f"Failed to fetch data for {market_id}: {market_error}")
                comparisons.append({
                    "market_id": market_id,
                    "error": str(market_error)
                })

        logger.info(f"Compared {len(comparisons)} markets")

        return comparisons

    except Exception as e:
        logger.error(f"Failed to compare markets: {e}")
        raise


# Tool definitions for MCP
def get_tools() -> List[types.Tool]:
    """Get list of market analysis tools"""
    return [
        types.Tool(
            name="get_market_details",
            description="Get complete market information including metadata, tokens, volume, and liquidity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "market_id": {
                        "type": "string",
                        "description": "Market ID"
                    },
                    "condition_id": {
                        "type": "string",
                        "description": "Condition ID (alternative identifier)"
                    },
                    "slug": {
                        "type": "string",
                        "description": "Market slug (alternative identifier)"
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="get_current_price",
            description="Get current bid/ask prices for a token. Returns PriceData with bid, ask, and mid prices.",
            inputSchema={
                "type": "object",
                "properties": {
                    "token_id": {
                        "type": "string",
                        "description": "Token ID"
                    },
                    "side": {
                        "type": "string",
                        "enum": ["BUY", "SELL", "BOTH"],
                        "description": "Price side to fetch (default: BOTH)",
                        "default": "BOTH"
                    }
                },
                "required": ["token_id"]
            }
        ),
        types.Tool(
            name="get_orderbook",
            description="Get complete order book with bids and asks arrays.",
            inputSchema={
                "type": "object",
                "properties": {
                    "token_id": {
                        "type": "string",
                        "description": "Token ID"
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Number of price levels per side (default 20)",
                        "default": 20
                    }
                },
                "required": ["token_id"]
            }
        ),
        types.Tool(
            name="get_spread",
            description="Get current spread (difference between bid and ask prices).",
            inputSchema={
                "type": "object",
                "properties": {
                    "token_id": {
                        "type": "string",
                        "description": "Token ID"
                    }
                },
                "required": ["token_id"]
            }
        ),
        types.Tool(
            name="get_market_volume",
            description="Get volume statistics for different timeframes (24h, 7d, 30d, all-time).",
            inputSchema={
                "type": "object",
                "properties": {
                    "market_id": {
                        "type": "string",
                        "description": "Market ID"
                    },
                    "timeframes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of timeframes (default: ['24h', '7d', '30d'])"
                    }
                },
                "required": ["market_id"]
            }
        ),
        types.Tool(
            name="get_liquidity",
            description="Get available liquidity in USD for a market.",
            inputSchema={
                "type": "object",
                "properties": {
                    "market_id": {
                        "type": "string",
                        "description": "Market ID"
                    }
                },
                "required": ["market_id"]
            }
        ),
        types.Tool(
            name="get_price_history",
            description="Get historical price data (OHLC). Note: Limited availability via public API.",
            inputSchema={
                "type": "object",
                "properties": {
                    "token_id": {
                        "type": "string",
                        "description": "Token ID"
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date (ISO format or timestamp)"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date (ISO format or timestamp)"
                    },
                    "resolution": {
                        "type": "string",
                        "enum": ["1m", "5m", "1h", "1d"],
                        "description": "Time resolution (default: 1h)",
                        "default": "1h"
                    }
                },
                "required": ["token_id"]
            }
        ),
        types.Tool(
            name="get_market_holders",
            description="Get top position holders for a market. Note: Requires authenticated access.",
            inputSchema={
                "type": "object",
                "properties": {
                    "market_id": {
                        "type": "string",
                        "description": "Market ID"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of top holders (default 10)",
                        "default": 10
                    }
                },
                "required": ["market_id"]
            }
        ),
        types.Tool(
            name="analyze_market_opportunity",
            description="AI-powered market analysis with trading recommendation, risk assessment, and confidence score.",
            inputSchema={
                "type": "object",
                "properties": {
                    "market_id": {
                        "type": "string",
                        "description": "Market ID to analyze"
                    }
                },
                "required": ["market_id"]
            }
        ),
        types.Tool(
            name="compare_markets",
            description="Compare multiple markets side-by-side with key metrics (volume, liquidity, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "market_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of market IDs to compare (2-10 markets)"
                    }
                },
                "required": ["market_ids"]
            }
        )
    ]


async def handle_tool(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
    """
    Handle tool execution.

    Args:
        name: Tool name
        arguments: Tool arguments

    Returns:
        List of TextContent with results
    """
    try:
        # Route to appropriate function
        if name == "get_market_details":
            result = await get_market_details(**arguments)
        elif name == "get_current_price":
            result = await get_current_price(**arguments)
            # Convert Pydantic model to dict
            result = result.model_dump(mode='json')
        elif name == "get_orderbook":
            result = await get_orderbook(**arguments)
            result = result.model_dump(mode='json')
        elif name == "get_spread":
            result = await get_spread(**arguments)
        elif name == "get_market_volume":
            result = await get_market_volume(**arguments)
            result = result.model_dump(mode='json')
        elif name == "get_liquidity":
            result = await get_liquidity(**arguments)
        elif name == "get_price_history":
            result = await get_price_history(**arguments)
        elif name == "get_market_holders":
            result = await get_market_holders(**arguments)
        elif name == "analyze_market_opportunity":
            result = await analyze_market_opportunity(**arguments)
            result = result.model_dump(mode='json')
        elif name == "compare_markets":
            result = await compare_markets(**arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")

        return [types.TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]

    except Exception as e:
        logger.error(f"Tool execution failed for {name}: {e}")
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": str(e)}, indent=2)
        )]
