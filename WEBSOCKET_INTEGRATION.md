# WebSocket Integration Guide

This document describes how to integrate the WebSocket manager into `server.py`.

## Overview

The WebSocket system provides real-time data subscriptions for:
- Market price changes
- Orderbook updates
- User order updates (requires auth)
- User trade updates (requires auth)
- Market resolution events

## Files Created

1. **`src/polymarket_mcp/utils/websocket_manager.py`** - WebSocket connection manager
2. **`src/polymarket_mcp/tools/realtime.py`** - 7 real-time tools
3. **`tests/test_websocket.py`** - Comprehensive tests
4. **Updated `src/polymarket_mcp/utils/__init__.py`** - Exports WebSocket classes

## Server.py Integration

### Step 1: Add Imports

Add these imports to `server.py`:

```python
from .utils.websocket_manager import WebSocketManager
from .tools import realtime
from mcp.types import LoggingLevel
```

### Step 2: Add Global Instance

Add to global instances section:

```python
# Global instances
server = Server("polymarket-trading")
config: Optional[PolymarketConfig] = None
polymarket_client: Optional[PolymarketClient] = None
safety_limits: Optional[SafetyLimits] = None
websocket_manager: Optional[WebSocketManager] = None  # Add this
```

### Step 3: Create Notification Callbacks

Add these callback functions before the decorators:

```python
# Notification callback for WebSocket manager
async def send_notification(data: Dict[str, Any]) -> None:
    """
    Send MCP notification for WebSocket events.

    Args:
        data: Event data to send
    """
    try:
        await server.request_context.session.send_log_message(
            level=LoggingLevel.INFO,
            data=json.dumps(data, indent=2),
            logger="polymarket.websocket"
        )
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")


# Log callback for WebSocket manager
async def send_log(message: str) -> None:
    """
    Send log message for WebSocket events.

    Args:
        message: Log message to send
    """
    try:
        await server.request_context.session.send_log_message(
            level=LoggingLevel.INFO,
            data=message,
            logger="polymarket.websocket"
        )
    except Exception as e:
        logger.error(f"Failed to send log: {e}")
```

### Step 4: Update list_tools()

Extend the tools list to include real-time tools:

```python
@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """
    List available tools.

    Returns:
        List of all available tools including real-time WebSocket tools
    """
    tools = []

    # Add existing tools (trading, market discovery, etc.)
    # tools.extend(get_tool_definitions())  # If you have other tools

    # Add real-time WebSocket tools
    tools.extend(realtime.get_tools())

    return tools
```

### Step 5: Update call_tool()

Add routing for real-time tools in the `call_tool()` handler:

```python
@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """
    Handle tool calls from Claude.
    """
    try:
        # Handle real-time WebSocket tools
        if name.startswith("subscribe_") or name in ["get_realtime_status", "unsubscribe_realtime"]:
            return await realtime.handle_tool_call(name, arguments or {})

        # ... handle other tools ...

        # Unknown tool
        return [types.TextContent(
            type="text",
            text=f"Error: Unknown tool '{name}'"
        )]

    except Exception as e:
        logger.error(f"Tool call failed: {name} - {e}", exc_info=True)
        return [types.TextContent(
            type="text",
            text=f"Error executing tool '{name}': {str(e)}"
        )]
```

### Step 6: Add WebSocket Resource

Add WebSocket status to resources:

```python
@server.list_resources()
async def list_resources() -> list[types.Resource]:
    """List available resources"""
    resources = [
        # ... existing resources ...

        types.Resource(
            uri="polymarket://websocket-status",
            name="WebSocket Status",
            description="Check real-time WebSocket connection status and subscriptions",
            mimeType="application/json"
        ),
    ]
    return resources


@server.read_resource()
async def read_resource(uri: str) -> str:
    """Read resource content by URI"""
    import json

    # ... existing resource handlers ...

    if uri == "polymarket://websocket-status":
        # WebSocket status
        if not websocket_manager:
            return json.dumps({"error": "WebSocket manager not initialized"})

        status = websocket_manager.get_status()
        return json.dumps(status, indent=2)

    # ... rest of handlers ...
```

### Step 7: Update initialize_server()

Add WebSocket initialization:

```python
async def initialize_server() -> None:
    """
    Initialize server components.
    """
    global config, polymarket_client, safety_limits, websocket_manager

    try:
        # ... existing initialization (config, client, safety_limits) ...

        # Initialize WebSocket manager
        logger.info("Initializing WebSocket manager...")
        websocket_manager = WebSocketManager(
            config=config,
            notification_callback=send_notification,
            log_callback=send_log
        )

        # Set WebSocket manager in realtime tools
        realtime.set_websocket_manager(websocket_manager)

        # Connect WebSocket and start background task
        logger.info("Connecting to WebSocket endpoints...")
        await websocket_manager.connect()
        await websocket_manager.start_background_task()
        logger.info("WebSocket connections established and background task started")

        logger.info("Server initialization complete!")
        logger.info("Available tools include 7 Real-time WebSocket tools")

    except Exception as e:
        logger.error(f"Failed to initialize server: {e}")
        raise
```

### Step 8: Add Shutdown Handler

Add graceful shutdown:

```python
async def shutdown_server() -> None:
    """
    Shutdown server components gracefully.
    """
    global websocket_manager

    try:
        if websocket_manager:
            logger.info("Shutting down WebSocket manager...")
            await websocket_manager.stop_background_task()
            logger.info("WebSocket manager stopped")

    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


async def main() -> None:
    """
    Main entry point for MCP server.
    """
    try:
        # Initialize server components
        await initialize_server()

        # Run MCP server with stdio transport
        logger.info("Starting MCP server...")
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options()
            )

    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        # Cleanup
        await shutdown_server()
```

## Available Tools

After integration, these 7 tools will be available:

### 1. subscribe_market_prices
Subscribe to real-time price changes for markets.

**Parameters:**
- `market_ids` (array of strings, required) - Market condition IDs to monitor
- `callback_type` (string, optional) - "notification" or "log" (default: "notification")

**Returns:** Subscription ID

### 2. subscribe_orderbook_updates
Subscribe to real-time orderbook updates.

**Parameters:**
- `token_ids` (array of strings, required) - Token IDs to monitor
- `depth` (integer, optional) - Number of price levels (default: 10)
- `callback_type` (string, optional) - "notification" or "log"

**Returns:** Subscription ID

### 3. subscribe_user_orders
Subscribe to user's order updates (requires CLOB auth).

**Parameters:**
- `market_ids` (array of strings, optional) - Filter by markets (all if not provided)
- `callback_type` (string, optional) - "notification" or "log"

**Returns:** Subscription ID

### 4. subscribe_user_trades
Subscribe to user's trade updates (requires CLOB auth).

**Parameters:**
- `market_ids` (array of strings, optional) - Filter by markets (all if not provided)
- `callback_type` (string, optional) - "notification" or "log"

**Returns:** Subscription ID

### 5. subscribe_market_resolution
Subscribe to market resolution events.

**Parameters:**
- `market_ids` (array of strings, required) - Markets to monitor
- `callback_type` (string, optional) - "notification" or "log"

**Returns:** Subscription ID

### 6. get_realtime_status
Get status of all subscriptions and WebSocket connections.

**Parameters:** None

**Returns:** Detailed status including:
- Connection status (CLOB & Real-time)
- Active subscriptions
- Event statistics
- Background task status

### 7. unsubscribe_realtime
Unsubscribe from a real-time feed.

**Parameters:**
- `subscription_id` (string, required) - Subscription ID to remove

**Returns:** Success/failure message

## WebSocket Endpoints

The system connects to two WebSocket endpoints:

1. **CLOB WebSocket**: `wss://ws-subscriptions-clob.polymarket.com/ws/`
   - User orders and trades (requires auth)
   - Market data (prices, orderbook)

2. **Real-time Data WebSocket**: `wss://ws-live-data.polymarket.com`
   - Activity feeds
   - Crypto price feeds

## Authentication

- **Market data subscriptions** (prices, orderbook) do NOT require authentication
- **User subscriptions** (orders, trades) REQUIRE CLOB authentication
- CLOB auth uses `POLYMARKET_API_KEY` and `POLYMARKET_PASSPHRASE` from config
- Authentication happens automatically during connection if credentials available

## Event Flow

1. User calls a `subscribe_*` tool
2. WebSocketManager creates a subscription and sends subscribe message
3. Background task continuously receives messages from both WebSockets
4. Incoming messages are routed to `handle_message()`
5. Message handler finds matching subscriptions
6. For each matching subscription:
   - Updates event counters
   - Calls notification_callback (sends MCP notification) OR log_callback
7. User sees real-time updates in Claude Desktop

## Auto-Reconnect

The WebSocket manager implements auto-reconnect with exponential backoff:
- Initial delay: 1 second
- Max delay: 60 seconds
- Multiplier: 2x
- Automatically resubscribes to all active subscriptions after reconnect

## Testing

Run tests with:

```bash
# All tests
pytest tests/test_websocket.py -v

# Skip slow integration tests
pytest tests/test_websocket.py -v -m "not slow"

# Run only integration tests
pytest tests/test_websocket.py -v -m "slow"
```

Tests in `tests/test_websocket.py` use REAL WebSocket connections (integration-marked) to ensure the integration works with actual Polymarket endpoints. The offline layer — `tests/test_websocket_messages.py` (message routing and reconnect backoff), `tests/test_websocket_lifecycle_offline.py`, and `tests/test_websocket_readers.py` — covers the same manager logic with fakes, and is what the default gate selection (`not integration and not slow and not real_api and not performance`) runs.

## Configuration

Required environment variables (same as existing config):
- `POLYGON_PRIVATE_KEY` - Polygon wallet private key
- `POLYGON_ADDRESS` - Polygon wallet address
- `POLYMARKET_API_KEY` - L2 API key (optional, created if missing)
- `POLYMARKET_PASSPHRASE` - API passphrase (optional, created if missing)

## Example Usage

```python
# In Claude Desktop, users can:

# 1. Subscribe to price changes
subscribe_market_prices({
    "market_ids": ["21742633143463906290569050155826241533067272736897614950488156847949938836455"],
    "callback_type": "notification"
})
# Returns: subscription_id

# 2. Monitor orderbook
subscribe_orderbook_updates({
    "token_ids": ["71321045679252212594626385532706912750332728571942532289631379312455583992563"],
    "depth": 10
})

# 3. Check status
get_realtime_status({})
# Returns detailed status with active subscriptions and statistics

# 4. Unsubscribe
unsubscribe_realtime({
    "subscription_id": "abc-123-def-456"
})
```

## Troubleshooting

### WebSocket not connecting
- Check network connectivity
- Verify WebSocket URLs are accessible
- Check logs for connection errors

### Authentication failing
- Ensure `POLYMARKET_API_KEY` and `POLYMARKET_PASSPHRASE` are set
- Verify credentials are valid
- Check CLOB WebSocket authentication response

### No events received
- Market may not be actively trading
- Check subscription filters (market_ids, token_ids)
- Verify background task is running: `get_realtime_status()`

### High memory usage
- Limit number of active subscriptions
- Use `unsubscribe_realtime()` for unused subscriptions
- Message buffer is capped at 1000 messages

## Performance Considerations

- Each subscription adds minimal overhead
- Background task processes messages asynchronously
- Notifications are sent via MCP session (non-blocking)
- Auto-reconnect prevents connection loss issues
- Event statistics help monitor system health

## Security Notes

- WebSocket connections use WSS (encrypted)
- CLOB authentication uses HMAC signing
- API credentials never logged or exposed
- User-specific data only accessible with valid auth
