"""
Real-time WebSocket tools for Polymarket MCP server.

Provides 6 tools for real-time market data subscriptions:
1. subscribe_market_prices - Monitor price changes
2. subscribe_orderbook_updates - Real-time orderbook
3. subscribe_user_orders - Monitor user's orders
4. subscribe_user_trades - Monitor user's trades
5. subscribe_market_resolution - Alert on market close
6. get_realtime_status - Status of all subscriptions
"""
import logging
from typing import Any, Dict, List, Optional

import mcp.types as types

from ..utils.websocket_manager import ChannelType, EventType, WebSocketManager

logger = logging.getLogger(__name__)

# Global WebSocket manager instance (will be set by server)
websocket_manager: Optional[WebSocketManager] = None


def set_websocket_manager(manager: WebSocketManager) -> None:
    """
    Set the global WebSocket manager instance.

    Called by server during initialization.

    Args:
        manager: WebSocketManager instance
    """
    global websocket_manager
    websocket_manager = manager
    logger.info("WebSocket manager registered with realtime tools")


def get_tools() -> List[types.Tool]:
    """
    Get list of real-time WebSocket tools.

    Returns:
        List of MCP Tool definitions
    """
    return [
        types.Tool(
            name="subscribe_market_prices",
            description=(
                "Subscribe to real-time price changes for one or more markets. "
                "Receives notifications whenever the price changes for subscribed markets. "
                "Useful for monitoring market movements and price action."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "market_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of market condition IDs to monitor",
                        "minItems": 1
                    },
                    "callback_type": {
                        "type": "string",
                        "enum": ["notification", "log"],
                        "default": "notification",
                        "description": "How to receive updates: 'notification' (MCP notification) or 'log' (log message)"
                    }
                },
                "required": ["market_ids"]
            }
        ),
        types.Tool(
            name="subscribe_orderbook_updates",
            description=(
                "Subscribe to real-time orderbook updates for one or more tokens. "
                "Receives notifications with aggregated bid/ask levels whenever the orderbook changes. "
                "Useful for monitoring liquidity and best bid/ask prices."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "token_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of token IDs to monitor orderbooks for",
                        "minItems": 1
                    },
                    "depth": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Number of price levels to include (default: 10)"
                    },
                    "callback_type": {
                        "type": "string",
                        "enum": ["notification", "log"],
                        "default": "notification",
                        "description": "How to receive updates"
                    }
                },
                "required": ["token_ids"]
            }
        ),
        types.Tool(
            name="subscribe_user_orders",
            description=(
                "Subscribe to real-time updates for user's orders. "
                "Receives notifications when orders are created, filled, partially filled, or cancelled. "
                "Requires CLOB authentication. Optionally filter by specific markets."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "market_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of market IDs to filter. If not provided, monitors all markets.",
                        "minItems": 1
                    },
                    "callback_type": {
                        "type": "string",
                        "enum": ["notification", "log"],
                        "default": "notification",
                        "description": "How to receive updates"
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="subscribe_user_trades",
            description=(
                "Subscribe to real-time updates for user's trades. "
                "Receives notifications when orders are matched and trades execute. "
                "Requires CLOB authentication. Optionally filter by specific markets."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "market_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of market IDs to filter. If not provided, monitors all markets.",
                        "minItems": 1
                    },
                    "callback_type": {
                        "type": "string",
                        "enum": ["notification", "log"],
                        "default": "notification",
                        "description": "How to receive updates"
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="subscribe_market_resolution",
            description=(
                "Subscribe to market resolution alerts. "
                "Receives notifications when specified markets are resolved (closed with final outcome). "
                "Useful for tracking when bets settle and positions can be claimed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "market_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of market condition IDs to monitor for resolution",
                        "minItems": 1
                    },
                    "callback_type": {
                        "type": "string",
                        "enum": ["notification", "log"],
                        "default": "notification",
                        "description": "How to receive updates"
                    }
                },
                "required": ["market_ids"]
            }
        ),
        types.Tool(
            name="get_realtime_status",
            description=(
                "Get status of all real-time WebSocket subscriptions. "
                "Shows active subscriptions, connection status, event statistics, and errors. "
                "Use this to monitor the health of real-time data feeds."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        types.Tool(
            name="unsubscribe_realtime",
            description=(
                "Unsubscribe from a real-time data feed. "
                "Removes a subscription by ID (obtained from subscribe_* tools). "
                "Stops receiving updates for that subscription."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Subscription ID to remove"
                    }
                },
                "required": ["subscription_id"]
            }
        )
    ]


async def handle_tool_call(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
    """
    Handle real-time tool calls.

    Args:
        name: Tool name
        arguments: Tool arguments

    Returns:
        List of TextContent responses
    """
    if not websocket_manager:
        return [types.TextContent(
            type="text",
            text="Error: WebSocket manager not initialized. Real-time features unavailable."
        )]

    try:
        if name == "subscribe_market_prices":
            return await _subscribe_market_prices(arguments)
        elif name == "subscribe_orderbook_updates":
            return await _subscribe_orderbook_updates(arguments)
        elif name == "subscribe_user_orders":
            return await _subscribe_user_orders(arguments)
        elif name == "subscribe_user_trades":
            return await _subscribe_user_trades(arguments)
        elif name == "subscribe_market_resolution":
            return await _subscribe_market_resolution(arguments)
        elif name == "get_realtime_status":
            return await _get_realtime_status(arguments)
        elif name == "unsubscribe_realtime":
            return await _unsubscribe_realtime(arguments)
        else:
            return [types.TextContent(
                type="text",
                text=f"Error: Unknown tool '{name}'"
            )]

    except Exception as e:
        logger.error(f"Error handling tool call {name}: {e}", exc_info=True)
        return [types.TextContent(
            type="text",
            text=f"Error: {str(e)}"
        )]


async def _subscribe_market_prices(arguments: Dict[str, Any]) -> List[types.TextContent]:
    """
    Subscribe to market price changes.

    Args:
        arguments: Tool arguments with market_ids and callback_type

    Returns:
        List of TextContent with subscription ID
    """
    market_ids = arguments.get("market_ids", [])
    callback_type = arguments.get("callback_type", "notification")

    if not market_ids:
        return [types.TextContent(
            type="text",
            text="Error: market_ids required"
        )]

    try:
        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.PRICE_CHANGE,
            channel=ChannelType.CLOB_MARKET,
            market_ids=market_ids,
            callback_type=callback_type
        )

        return [types.TextContent(
            type="text",
            text=f"Price change subscription created:\n\n"
                 f"Subscription ID: {subscription_id}\n"
                 f"Markets: {len(market_ids)}\n"
                 f"Callback: {callback_type}\n\n"
                 f"You will receive {callback_type}s when prices change for these markets.\n"
                 f"Use get_realtime_status to monitor events.\n"
                 f"Use unsubscribe_realtime with ID '{subscription_id}' to stop."
        )]

    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"Error subscribing to market prices: {str(e)}"
        )]


async def _subscribe_orderbook_updates(arguments: Dict[str, Any]) -> List[types.TextContent]:
    """
    Subscribe to orderbook updates.

    Args:
        arguments: Tool arguments with token_ids, depth, and callback_type

    Returns:
        List of TextContent with subscription ID
    """
    token_ids = arguments.get("token_ids", [])
    depth = arguments.get("depth", 10)
    callback_type = arguments.get("callback_type", "notification")

    if not token_ids:
        return [types.TextContent(
            type="text",
            text="Error: token_ids required"
        )]

    try:
        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.AGG_ORDERBOOK,
            channel=ChannelType.CLOB_MARKET,
            token_ids=token_ids,
            callback_type=callback_type
        )

        return [types.TextContent(
            type="text",
            text=f"Orderbook subscription created:\n\n"
                 f"Subscription ID: {subscription_id}\n"
                 f"Tokens: {len(token_ids)}\n"
                 f"Depth: {depth} levels\n"
                 f"Callback: {callback_type}\n\n"
                 f"You will receive {callback_type}s with aggregated bid/ask updates.\n"
                 f"Use get_realtime_status to monitor events.\n"
                 f"Use unsubscribe_realtime with ID '{subscription_id}' to stop."
        )]

    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"Error subscribing to orderbook updates: {str(e)}"
        )]


async def _subscribe_user_orders(arguments: Dict[str, Any]) -> List[types.TextContent]:
    """
    Subscribe to user order updates.

    Args:
        arguments: Tool arguments with optional market_ids and callback_type

    Returns:
        List of TextContent with subscription ID
    """
    market_ids = arguments.get("market_ids")
    callback_type = arguments.get("callback_type", "notification")

    try:
        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.ORDER,
            channel=ChannelType.CLOB_USER,
            market_ids=market_ids,
            callback_type=callback_type
        )

        market_filter = f"{len(market_ids)} specific markets" if market_ids else "all markets"

        return [types.TextContent(
            type="text",
            text=f"User order subscription created:\n\n"
                 f"Subscription ID: {subscription_id}\n"
                 f"Scope: {market_filter}\n"
                 f"Callback: {callback_type}\n\n"
                 f"You will receive {callback_type}s when your orders are created, filled, or cancelled.\n"
                 f"Requires CLOB authentication.\n"
                 f"Use get_realtime_status to monitor events.\n"
                 f"Use unsubscribe_realtime with ID '{subscription_id}' to stop."
        )]

    except RuntimeError as e:
        return [types.TextContent(
            type="text",
            text=f"Authentication required: {str(e)}\n\n"
                 f"User order subscriptions require CLOB API credentials.\n"
                 f"Ensure POLYMARKET_API_KEY and POLYMARKET_PASSPHRASE are configured."
        )]
    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"Error subscribing to user orders: {str(e)}"
        )]


async def _subscribe_user_trades(arguments: Dict[str, Any]) -> List[types.TextContent]:
    """
    Subscribe to user trade updates.

    Args:
        arguments: Tool arguments with optional market_ids and callback_type

    Returns:
        List of TextContent with subscription ID
    """
    market_ids = arguments.get("market_ids")
    callback_type = arguments.get("callback_type", "notification")

    try:
        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.TRADE,
            channel=ChannelType.CLOB_USER,
            market_ids=market_ids,
            callback_type=callback_type
        )

        market_filter = f"{len(market_ids)} specific markets" if market_ids else "all markets"

        return [types.TextContent(
            type="text",
            text=f"User trade subscription created:\n\n"
                 f"Subscription ID: {subscription_id}\n"
                 f"Scope: {market_filter}\n"
                 f"Callback: {callback_type}\n\n"
                 f"You will receive {callback_type}s when your orders are matched and trades execute.\n"
                 f"Requires CLOB authentication.\n"
                 f"Use get_realtime_status to monitor events.\n"
                 f"Use unsubscribe_realtime with ID '{subscription_id}' to stop."
        )]

    except RuntimeError as e:
        return [types.TextContent(
            type="text",
            text=f"Authentication required: {str(e)}\n\n"
                 f"User trade subscriptions require CLOB API credentials.\n"
                 f"Ensure POLYMARKET_API_KEY and POLYMARKET_PASSPHRASE are configured."
        )]
    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"Error subscribing to user trades: {str(e)}"
        )]


async def _subscribe_market_resolution(arguments: Dict[str, Any]) -> List[types.TextContent]:
    """
    Subscribe to market resolution events.

    Args:
        arguments: Tool arguments with market_ids and callback_type

    Returns:
        List of TextContent with subscription ID
    """
    market_ids = arguments.get("market_ids", [])
    callback_type = arguments.get("callback_type", "notification")

    if not market_ids:
        return [types.TextContent(
            type="text",
            text="Error: market_ids required"
        )]

    try:
        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.MARKET_RESOLVED,
            channel=ChannelType.CLOB_MARKET,
            market_ids=market_ids,
            callback_type=callback_type
        )

        return [types.TextContent(
            type="text",
            text=f"Market resolution subscription created:\n\n"
                 f"Subscription ID: {subscription_id}\n"
                 f"Markets: {len(market_ids)}\n"
                 f"Callback: {callback_type}\n\n"
                 f"You will receive {callback_type}s when these markets are resolved.\n"
                 f"Useful for tracking when positions can be claimed.\n"
                 f"Use get_realtime_status to monitor events.\n"
                 f"Use unsubscribe_realtime with ID '{subscription_id}' to stop."
        )]

    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"Error subscribing to market resolution: {str(e)}"
        )]


async def _get_realtime_status(arguments: Dict[str, Any]) -> List[types.TextContent]:
    """
    Get real-time subscription status.

    Args:
        arguments: Tool arguments (none required)

    Returns:
        List of TextContent with detailed status
    """
    try:
        status = websocket_manager.get_status()

        # Format connection status
        clob_status = "CONNECTED & AUTHENTICATED" if status["connections"]["clob"]["authenticated"] else (
            "CONNECTED (no auth)" if status["connections"]["clob"]["connected"] else "DISCONNECTED"
        )
        realtime_status = "CONNECTED" if status["connections"]["realtime"]["connected"] else "DISCONNECTED"

        # Format subscriptions
        subscriptions_text = "\n\nActive Subscriptions:\n"
        if status["subscriptions"]["active"]:
            for sub in status["subscriptions"]["active"]:
                subscriptions_text += (
                    f"\n• {sub['id'][:8]}... ({sub['type']})\n"
                    f"  Channel: {sub['channel']}\n"
                    f"  Events: {sub['events_received']}\n"
                    f"  Created: {sub['created_at']}\n"
                )
                if sub['last_event']:
                    subscriptions_text += f"  Last Event: {sub['last_event']}\n"
        else:
            subscriptions_text += "\nNo active subscriptions"

        # Format statistics
        stats = status["statistics"]
        stats_text = (
            f"\n\nStatistics:\n"
            f"• Total Events: {stats['total_events']}\n"
            f"• Connection Errors: {stats['connection_errors']}\n"
            f"• Reconnects: {stats['reconnect_count']}\n"
        )

        if stats['events_by_type']:
            stats_text += "\n• Events by Type:\n"
            for event_type, count in stats['events_by_type'].items():
                if count > 0:
                    stats_text += f"  - {event_type}: {count}\n"

        # Combine all sections
        result_text = (
            f"Real-time WebSocket Status\n"
            f"==========================\n\n"
            f"Connections:\n"
            f"• CLOB: {clob_status}\n"
            f"• Real-time Data: {realtime_status}\n\n"
            f"Subscriptions:\n"
            f"• Total Active: {status['subscriptions']['total']}\n"
            f"{subscriptions_text}"
            f"{stats_text}\n"
            f"Background Task: {'RUNNING' if status['background_task']['running'] else 'STOPPED'}"
        )

        return [types.TextContent(type="text", text=result_text)]

    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"Error getting status: {str(e)}"
        )]


async def _unsubscribe_realtime(arguments: Dict[str, Any]) -> List[types.TextContent]:
    """
    Unsubscribe from a real-time feed.

    Args:
        arguments: Tool arguments with subscription_id

    Returns:
        List of TextContent with result
    """
    subscription_id = arguments.get("subscription_id")

    if not subscription_id:
        return [types.TextContent(
            type="text",
            text="Error: subscription_id required"
        )]

    try:
        success = await websocket_manager.unsubscribe(subscription_id)

        if success:
            return [types.TextContent(
                type="text",
                text=f"Successfully unsubscribed from: {subscription_id}\n\n"
                     f"You will no longer receive updates for this subscription."
            )]
        else:
            return [types.TextContent(
                type="text",
                text=f"Subscription not found: {subscription_id}\n\n"
                     f"Use get_realtime_status to see active subscriptions."
            )]

    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"Error unsubscribing: {str(e)}"
        )]
