"""
Market Discovery Tools for Polymarket MCP Server.

Provides 8 tools for discovering and filtering markets:
- search_markets: Search by text/slug/keywords
- get_trending_markets: Markets with highest volume
- filter_markets_by_category: Filter by tags/categories
- get_event_markets: All markets for an event
- get_featured_markets: Featured/promoted markets
- get_closing_soon_markets: Markets closing within timeframe
- get_sports_markets: Sports betting markets
- get_crypto_markets: Cryptocurrency markets
"""
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import mcp.types as types
import httpx

from ..utils.rate_limiter import EndpointCategory, get_rate_limiter

logger = logging.getLogger(__name__)

# Gamma API base URL
GAMMA_API_URL = "https://gamma-api.polymarket.com"
CLOB_API_URL = "https://clob.polymarket.com"


async def _fetch_gamma_markets(
    endpoint: str = "/markets",
    params: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Fetch markets from Gamma API with rate limiting.

    Args:
        endpoint: API endpoint (default: /markets)
        params: Query parameters
        limit: Maximum number of results to return

    Returns:
        List of market dictionaries
    """
    rate_limiter = get_rate_limiter()

    await rate_limiter.acquire(EndpointCategory.GAMMA_API)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{GAMMA_API_URL}{endpoint}"

            if params is None:
                params = {}

            if limit:
                params["limit"] = limit

            logger.debug(f"Fetching from {url} with params: {params}")

            response = await client.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            if isinstance(data, list):
                return data[:limit] if limit else data
            elif isinstance(data, dict):
                if "data" in data:
                    return data["data"][:limit] if limit else data["data"]
                return [data]

            return []

    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching markets: {e}")
        raise
    except Exception as e:
        logger.error(f"Error fetching markets: {e}")
        raise


async def _fetch_events_with_markets(
    params: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Fetch events from Gamma API and extract markets.

    Args:
        params: Query parameters (active=true, etc.)
        limit: Maximum number of MARKETS to return (not events)

    Returns:
        List of market dictionaries extracted from events
    """
    rate_limiter = get_rate_limiter()
    await rate_limiter.acquire(EndpointCategory.GAMMA_API)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{GAMMA_API_URL}/events"

            if params is None:
                params = {}

            if limit:
                params["limit"] = min(limit * 2, 100)

            logger.debug(f"Fetching events from {url} with params: {params}")

            response = await client.get(url, params=params)
            response.raise_for_status()

            events = response.json()

            all_markets = []
            if isinstance(events, dict) and "data" in events:
                events = events["data"]

            if isinstance(events, list):
                for event in events:
                    markets = event.get("markets", []) if isinstance(event, dict) else []
                    all_markets.extend(markets)

                    if limit and len(all_markets) >= limit:
                        break

            return all_markets[:limit] if limit else all_markets

    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching events: {e}")
        raise
    except Exception as e:
        logger.error(f"Error fetching events: {e}")
        raise


async def _fetch_clob_markets(
    params: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Fetch markets from CLOB API sampling-markets endpoint.

    Returns current/active markets from CLOB API.

    Args:
        params: Query parameters
        limit: Maximum number of results to return

    Returns:
        List of market dictionaries
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{CLOB_API_URL}/sampling-markets"

            if params is None:
                params = {}

            if limit:
                params["limit"] = limit

            logger.debug(f"Fetching from CLOB {url} with params: {params}")

            response = await client.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            if isinstance(data, dict):
                if "data" in data:
                    data = data["data"]
                elif "markets" in data:
                    data = list(data["markets"].values())

            if isinstance(data, list):
                return data[:limit] if limit else data

            return []

    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching CLOB markets: {e}")
        raise
    except Exception as e:
        logger.error(f"Error fetching CLOB markets: {e}")
        raise


async def search_markets(
    query: str,
    limit: int = 20,
    filters: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Search markets by text query, slug, or keywords.

    Args:
        query: Search query (market title, slug, or keywords)
        limit: Maximum number of results (default 20)
        filters: Optional filters (active, closed, tags, etc.)

    Returns:
        List of markets matching the query
    """
    try:
        markets = await _fetch_clob_markets(params=None, limit=limit * 2)

        if query:
            query_lower = query.lower()
            markets = [
                m for m in markets
                if query_lower in m.get("question", "").lower() or
                   query_lower in m.get("description", "").lower() or
                   query_lower in m.get("slug", "").lower() or
                   any(query_lower in str(tag).lower() for tag in m.get("tags", []))
            ]

        if filters:
            if filters.get("active") == "true":
                markets = [m for m in markets if m.get("active", True)]
            if filters.get("closed") == "true":
                markets = [m for m in markets if not m.get("active", True)]
            if filters.get("tag"):
                tag = filters["tag"].lower()
                markets = [m for m in markets if tag in str(m.get("tags", [])).lower()]

        logger.info(f"Found {len(markets)} markets for query: {query}")
        return markets[:limit]

    except Exception as e:
        logger.error(f"Failed to search markets: {e}")
        raise


async def get_trending_markets(
    timeframe: str = "24h",
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Get markets with highest trading volume.

    Args:
        timeframe: Time period ('24h', '7d', '30d')
        limit: Number of markets to return (default 10)

    Returns:
        Top markets by volume in the specified timeframe
    """
    try:
        markets = await _fetch_clob_markets(params=None, limit=100)

        volume_key_map = {
            "24h": "volume24hr",
            "7d": "volume7d",
            "30d": "volume30d"
        }

        volume_key = volume_key_map.get(timeframe, "volume24hr")

        sorted_markets = sorted(
            markets,
            key=lambda m: float(m.get(volume_key, 0) or 0),
            reverse=True
        )

        result = sorted_markets[:limit]
        logger.info(f"Found {len(result)} trending markets for timeframe: {timeframe}")

        return result

    except Exception as e:
        logger.error(f"Failed to get trending markets: {e}")
        raise


async def filter_markets_by_category(
    category: str,
    active_only: bool = True,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Filter markets by category or tag.

    Args:
        category: Category/tag to filter by (e.g., "Politics", "Sports", "Crypto")
        active_only: Only return active markets (default True)
        limit: Maximum number of results (default 20)

    Returns:
        Markets in the specified category
    """
    try:
        markets = await _fetch_clob_markets(params=None, limit=limit * 2)

        category_lower = category.lower()
        filtered_markets = [
            m for m in markets
            if category_lower in m.get("question", "").lower() or
               category_lower in m.get("description", "").lower() or
               category_lower in str(m.get("tags", [])).lower()
        ]

        if active_only:
            filtered_markets = [m for m in filtered_markets if m.get("active", True)]

        logger.info(f"Found {len(filtered_markets)} markets in category: {category}")
        return filtered_markets[:limit]

    except Exception as e:
        logger.error(f"Failed to filter markets by category: {e}")
        raise


async def get_event_markets(
    event_slug: Optional[str] = None,
    event_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get all markets for a specific event.

    Note: The Gamma API events endpoint is deprecated. This function now:
    1. Searches markets for matching event_slug in tags
    2. Returns filtered results

    Args:
        event_slug: Event slug (e.g., "presidential-election-2024")
        event_id: Event ID (alternative to slug, not currently supported)

    Returns:
        All markets belonging to the event
    """
    try:
        if not event_slug and not event_id:
            raise ValueError("Either event_slug or event_id must be provided")

        # Use CLOB API to get all markets and filter by event
        markets = await _fetch_clob_markets(params=None, limit=500)

        # Filter markets matching the event_slug in tags, slug, or description
        filtered_markets = []
        event_slug_lower = (event_slug or event_id).lower()

        for market in markets:
            # Check in tags
            tags = market.get('tags', [])
            if isinstance(tags, list):
                if any(event_slug_lower in str(tag).lower() for tag in tags):
                    filtered_markets.append(market)
                    continue

            # Check in market slug
            if event_slug_lower in market.get('market_slug', '').lower():
                filtered_markets.append(market)
                continue

            # Check in description
            if event_slug_lower in market.get('description', '').lower():
                filtered_markets.append(market)
                continue

        logger.info(f"Found {len(filtered_markets)} markets for event: {event_slug or event_id}")
        return filtered_markets

    except Exception as e:
        logger.error(f"Failed to get event markets: {e}")
        raise


async def get_featured_markets(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get featured or promoted markets.

    Args:
        limit: Number of markets to return (default 10)

    Returns:
        Featured markets
    """
    try:
        markets = await get_trending_markets("24h", limit)

        logger.info(f"Found {len(markets)} featured markets")
        return markets

    except Exception as e:
        logger.error(f"Failed to get featured markets: {e}")
        raise


async def get_closing_soon_markets(
    hours: int = 24,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Get markets closing within specified timeframe.

    Args:
        hours: Number of hours to look ahead (default 24)
        limit: Maximum number of results (default 20)

    Returns:
        Markets closing soon
    """
    try:
        cutoff_time = datetime.utcnow().replace(tzinfo=None) + timedelta(hours=hours)

        markets = await _fetch_clob_markets(params=None, limit=100)

        closing_soon = []
        for market in markets:
            end_date = market.get("endDate") or market.get("end_date_iso")
            if end_date:
                try:
                    if isinstance(end_date, str):
                        end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    else:
                        end_dt = datetime.fromtimestamp(int(end_date))

                    if end_dt.replace(tzinfo=None) <= cutoff_time:
                        closing_soon.append(market)

                except Exception as parse_error:
                    logger.warning(f"Failed to parse end_date: {end_date}, error: {parse_error}")
                    continue

        closing_soon.sort(key=lambda m: m.get("endDate", m.get("end_date_iso", "")))

        result = closing_soon[:limit]
        logger.info(f"Found {len(result)} markets closing within {hours} hours")

        return result

    except Exception as e:
        logger.error(f"Failed to get closing soon markets: {e}")
        raise


async def get_sports_markets(
    sport_type: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Get sports betting markets.

    Args:
        sport_type: Specific sport (e.g., "NFL", "NBA", "Soccer") or None for all
        limit: Maximum number of results (default 20)

    Returns:
        Sports markets
    """
    try:
        markets = await _fetch_clob_markets(params=None, limit=100)

        sports_keywords = ["sport", "basketball", "football", "soccer", "baseball", "hockey", "tennis", "golf", "nfl", "nba", "mlb", "nhl", "fifa", "olympics"]
        sports_markets = [
            m for m in markets
            if any(kw in m.get("question", "").lower() or kw in str(m.get("tags", [])).lower() for kw in sports_keywords)
        ]

        if sport_type:
            sport_type_lower = sport_type.lower()
            sports_markets = [
                m for m in sports_markets
                if sport_type_lower in m.get("question", "").lower() or
                   sport_type_lower in str(m.get("tags", [])).lower()
            ]

        result = sports_markets[:limit]
        logger.info(f"Found {len(result)} sports markets (type: {sport_type or 'all'})")

        return result

    except Exception as e:
        logger.error(f"Failed to get sports markets: {e}")
        raise


async def get_crypto_markets(
    symbol: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Get cryptocurrency-related markets.

    Args:
        symbol: Specific crypto symbol (e.g., "BTC", "ETH") or None for all
        limit: Maximum number of results (default 20)

    Returns:
        Crypto-related markets
    """
    try:
        markets = await _fetch_clob_markets(params=None, limit=100)

        crypto_keywords = ["bitcoin", "ethereum", "crypto", "btc", "eth", "solana", "cardano", "dogecoin"]
        crypto_markets = [
            m for m in markets
            if any(kw in m.get("question", "").lower() or kw in str(m.get("tags", [])).lower() for kw in crypto_keywords)
        ]

        if symbol:
            symbol_upper = symbol.upper()
            crypto_markets = [
                m for m in crypto_markets
                if symbol_upper in m.get("question", "").upper() or
                   symbol_upper in str(m.get("tags", [])).upper()
            ]

        result = crypto_markets[:limit]
        logger.info(f"Found {len(result)} crypto markets (symbol: {symbol or 'all'})")

        return result

    except Exception as e:
        logger.error(f"Failed to get crypto markets: {e}")
        raise


# Tool definitions for MCP
def get_tools() -> List[types.Tool]:
    """Get list of market discovery tools"""
    return [
        types.Tool(
            name="search_markets",
            description="Search markets by text query, slug, or keywords. Returns markets matching the search criteria.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (market title, slug, or keywords)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default 20)",
                        "default": 20
                    },
                    "filters": {
                        "type": "object",
                        "description": "Optional filters (active, closed, tags, etc.)",
                        "properties": {
                            "active": {"type": "string"},
                            "closed": {"type": "string"},
                            "tag": {"type": "string"}
                        }
                    }
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="get_trending_markets",
            description="Get markets with highest trading volume in specified timeframe. Returns top markets sorted by volume.",
            inputSchema={
                "type": "object",
                "properties": {
                    "timeframe": {
                        "type": "string",
                        "enum": ["24h", "7d", "30d"],
                        "description": "Time period for volume calculation",
                        "default": "24h"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of markets to return (default 10)",
                        "default": 10
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="filter_markets_by_category",
            description="Filter markets by category or tag (e.g., Politics, Sports, Crypto). Returns markets in the specified category.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Category/tag to filter by"
                    },
                    "active_only": {
                        "type": "boolean",
                        "description": "Only return active markets (default True)",
                        "default": True
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default 20)",
                        "default": 20
                    }
                },
                "required": ["category"]
            }
        ),
        types.Tool(
            name="get_event_markets",
            description="Get all markets for a specific event. Returns all markets belonging to the event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_slug": {
                        "type": "string",
                        "description": "Event slug (e.g., 'presidential-election-2024')"
                    },
                    "event_id": {
                        "type": "string",
                        "description": "Event ID (alternative to slug)"
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="get_featured_markets",
            description="Get featured or promoted markets. Returns curated list of important markets.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of markets to return (default 10)",
                        "default": 10
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="get_closing_soon_markets",
            description="Get markets closing within specified timeframe. Returns markets sorted by closing time.",
            inputSchema={
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "integer",
                        "description": "Number of hours to look ahead (default 24)",
                        "default": 24
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default 20)",
                        "default": 20
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="get_sports_markets",
            description="Get sports betting markets. Optionally filter by specific sport type.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sport_type": {
                        "type": "string",
                        "description": "Specific sport (e.g., 'NFL', 'NBA', 'Soccer') or None for all"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default 20)",
                        "default": 20
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="get_crypto_markets",
            description="Get cryptocurrency-related markets. Optionally filter by specific crypto symbol.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Specific crypto symbol (e.g., 'BTC', 'ETH') or None for all"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default 20)",
                        "default": 20
                    }
                },
                "required": []
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
        if name == "search_markets":
            result = await search_markets(**arguments)
        elif name == "get_trending_markets":
            result = await get_trending_markets(**arguments)
        elif name == "filter_markets_by_category":
            result = await filter_markets_by_category(**arguments)
        elif name == "get_event_markets":
            result = await get_event_markets(**arguments)
        elif name == "get_featured_markets":
            result = await get_featured_markets(**arguments)
        elif name == "get_closing_soon_markets":
            result = await get_closing_soon_markets(**arguments)
        elif name == "get_sports_markets":
            result = await get_sports_markets(**arguments)
        elif name == "get_crypto_markets":
            result = await get_crypto_markets(**arguments)
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
