"""
Polymarket MCP Server - Main entry point.

Provides MCP server for Polymarket trading integration with Claude Desktop.
"""
import asyncio
import logging
import os
import re
import signal
from typing import Any, Dict, Final, Optional, Union, cast

import mcp.server.stdio
import mcp.types as types
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.server import Server
from mcp.server.lowlevel.server import NotificationOptions
from mcp.shared.message import SessionMessage

from . import __version__
from .auth import PolymarketClient, create_polymarket_client
from .config import PolymarketConfig, load_config
from .discover import (
    DEFAULT_PROTOCOL_REVISION,
    SUPPORTED_PROTOCOL_REVISIONS,
    UNSUPPORTED_PROTOCOL_VERSION_CODE,
    build_discover_result,
    cached_discover_result,
    declared_request_version,
    ensure_sdk_supports_declared_revisions,
    unsupported_version_error,
)
from .tools import (
    TradingTools,
    get_tool_definitions,
    market_analysis,
    market_discovery,
    portfolio_integration,
    realtime,
)
from .utils import (
    SafetyLimits,
    WebSocketManager,
    create_safety_limits_from_config,
    get_rate_limiter,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

_HEX_RUN_RE = re.compile(r"[0-9a-fA-F]{16,}")


def _safe_error_message(exc: BaseException) -> str:
    """Redact hex runs of 16+ chars from an exception message before logging.

    str(pydantic.ValidationError) echoes a truncated copy of the invalid
    input_value (pydantic 2.13.5: two ~23-hex-char runs around '...' for a
    64-char key), so a malformed POLYGON_PRIVATE_KEY would otherwise put
    184 bits of key material into the server log (L-0155/T-0061). Plain
    messages - and every message without a 16+ hex run - pass through
    byte-identically, keeping the lifecycle compat pin green. Pinned by
    tests/test_init_error_sanitization_offline.py.
    """
    return _HEX_RUN_RE.sub(
        lambda match: f"[REDACTED:{len(match.group(0))} hex chars]", str(exc)
    )


# Global instances
# version=__version__ keeps serverInfo consistent between the initialize
# handshake and server/discover (issue #39 R4): without it the SDK falls back
# to the mcp package version (lowlevel/server.py:183) and the two paths would
# report different identities.
server = Server("polymarket-trading", version=__version__)
config: Optional[PolymarketConfig] = None
polymarket_client: Optional[PolymarketClient] = None
safety_limits: Optional[SafetyLimits] = None
trading_tools: Optional[TradingTools] = None
websocket_manager: Optional[WebSocketManager] = None
_shutdown_event: Optional[asyncio.Event] = None

# Strong references to fire-and-forget tasks, so they are not garbage collected
# mid-flight (asyncio only keeps weak references to running tasks).
_background_tasks: set = set()

# Pre-handshake method served before any initialize (spec 2026-07-28,
# issue #39): the MCP session never sees it - the interceptor below answers it
# at the transport boundary.
DISCOVER_METHOD: Final[str] = "server/discover"

# JSON-RPC error code for the discover error fallback (never leave a client
# waiting: any failure answering discover is answered, not dropped).
DISCOVER_INTERNAL_ERROR_CODE: Final[int] = types.INTERNAL_ERROR


def _synthetic_initialized_notification() -> SessionMessage:
    """Server-internal era bridge for the 2026-07-28 sessionless model.

    The SDK-era session refuses ordinary requests before initialization
    (mcp/server/session.py:203-205); the 2026-07-28 revision has no handshake
    at all - the session concept is replaced by per-request versions. When a
    request declares a servable version in _meta, this notification is
    injected into the session's READ path (mcp/server/session.py:210-211 sets
    the session to the initialized state on it) so the request is served. It
    is never written to the client-bound stream, so the wire stays clean.
    """
    return SessionMessage(
        message=types.JSONRPCMessage(
            types.JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")
        )
    )


def _server_capabilities_dict() -> dict[str, Any]:
    """Capabilities mirror of what ``initialize`` declares.

    Single source of truth: ``Server.get_capabilities`` - the same call
    ``create_initialization_options`` makes (mcp/server/lowlevel/server.py:184),
    so ``server/discover`` and the handshake never disagree (issue #39 R4).
    """
    return server.get_capabilities(NotificationOptions(), {}).model_dump(
        exclude_none=True, by_alias=True
    )


def _build_discover_payload() -> dict[str, Any]:
    """Fresh discover payload for the cache (deterministic within the TTL)."""
    return build_discover_result(
        server_name=server.name,
        server_version=__version__,
        capabilities=_server_capabilities_dict(),
    )


class _PreHandshakeStream:
    """Read-stream interceptor serving pre-handshake requests.

    Installed in :func:`main` between the stdio transport and ``Server.run``:
    - ``server/discover`` is answered here (before any session exists), so the
      request never reaches the SDK union validation that produced -32602, nor
      the pre-handshake ``RuntimeError`` that drops it on some SDK versions
      (seam map: polymarket_mcp.discover docstring, issues #39/#40).
    - A version-less ``initialize`` is served on this server's declared default
      revision by injecting the version before session validation (issue #39
      R7 / issue #40: "a version-less request must be served", never timeout).
    - A request whose per-request ``_meta`` declares an unsupported protocol
      version is refused with ``-32022`` and the supported list (2026-07-28
      negotiation model; mcp-spec-test: "an unsupported version is rejected
      with the supported list"). A well-declared version passes through.
    Everything else passes through byte-identical, so the stock official-SDK
    handshake keeps its exact semantics (issue #39 R9).
    """

    def __init__(
        self,
        read_stream: MemoryObjectReceiveStream[Union[SessionMessage, Exception]],
        write_stream: MemoryObjectSendStream[SessionMessage],
    ) -> None:
        self._read_stream = read_stream
        self._write_stream = write_stream
        self._iterator: Any = None
        # Sessionless serving bridge (2026-07-28 model): set once the synthetic
        # ``notifications/initialized`` has been queued for this session, so a
        # later real initialize still runs its full negotiation path.
        self._sessionless_bridge_installed = False
        # A request stashed while its synthetic-initialized bridge is emitted
        # first (see _intercept); delivered on the following __anext__ call.
        self._queued_message: Optional[SessionMessage] = None
        # Serve the declared revisions at handshake time (see discover.py).
        ensure_sdk_supports_declared_revisions()

    def __aiter__(self) -> "_PreHandshakeStream":
        return self

    async def __anext__(self) -> Union[SessionMessage, Exception]:
        if self._iterator is None:
            self._iterator = self._read_stream.__aiter__()
        while True:
            if self._queued_message is not None:
                message, self._queued_message = self._queued_message, None
                return message
            message = await self._iterator.__anext__()
            bridged = await self._intercept(message)
            if bridged is True:
                continue  # consumed (answered by the interceptor)
            if isinstance(bridged, SessionMessage):
                # Emit the era bridge first; the original request follows on
                # the next call (the session processes messages in order).
                self._queued_message = message
                return bridged
            return cast("SessionMessage | Exception", message)

    async def __aenter__(self) -> "_PreHandshakeStream":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # Mirror the contract the raw stream had with the session
        # (mcp/shared/session.py:351-356 closes both stream ends on exit).
        await self._read_stream.aclose()

    async def _intercept(
        self,
        message: Union[SessionMessage, Exception],
    ) -> Union[bool, SessionMessage, None]:
        """Handle pre-handshake requests.

        Returns:
            True: consumed (answered at the transport boundary). A
            SessionMessage: the era bridge to emit BEFORE the original
            message (queued). None: pass through byte-identical.
        """
        if isinstance(message, Exception):
            return None
        root = message.message.root
        if not isinstance(root, types.JSONRPCRequest):
            return None
        if root.method == DISCOVER_METHOD:
            await self._respond_discover(request_id=root.id)
            return True
        if root.method == "initialize":
            # The handshake carries the version in params (older revisions);
            # _meta version validation below still applies to it.
            self._default_initialize_version(root)
        version = declared_request_version(root.params)
        if version is not None and version not in SUPPORTED_PROTOCOL_REVISIONS:
            # 2026-07-28 per-request version model: refuse with the supported
            # list instead of echoing or serving (issue #39 R8 recusa path,
            # mcp-spec-test -32022 UnsupportedProtocolVersion case).
            await self._send_discover_error(
                request_id=root.id,
                code=UNSUPPORTED_PROTOCOL_VERSION_CODE,
                message_text=f"Unsupported protocol version: {version}",
                data=unsupported_version_error(version),
            )
            return True
        if version is not None and not self._sessionless_bridge_installed:
            # 2026-07-28 is sessionless: a request declaring a servable
            # version per-request is era-valid with no handshake, but the
            # SDK-era session refuses it before initialization
            # (mcp/server/session.py:203-205). Bridge the eras by moving the
            # session into the initialized state with a server-internal
            # synthetic notification - it enters the session's read path only
            # and is never written to the client-bound stream.
            self._sessionless_bridge_installed = True
            return _synthetic_initialized_notification()
        return None

    def _default_initialize_version(self, request: types.JSONRPCRequest) -> None:
        """Serve a version-less handshake on the declared default revision.

        Absent, null or empty protocolVersion all mean "no version declared";
        anything else (including non-dict params) passes through untouched -
        the SDK session answers those with a JSON-RPC error response, never a
        dropped message (issue #39 R7 / issue #40: "must be served").
        """
        params = request.params
        if params is None:
            params = {}
            request.params = params
        if not isinstance(params, dict):
            return
        if not params.get("protocolVersion"):
            params["protocolVersion"] = DEFAULT_PROTOCOL_REVISION

    async def _respond_discover(self, request_id: Union[str, int]) -> None:
        """Answer ``server/discover`` with the cached CacheableResult envelope."""
        try:
            result = cached_discover_result(_build_discover_payload)
            await self._write_stream.send(
                SessionMessage(
                    message=types.JSONRPCMessage(
                        types.JSONRPCResponse(jsonrpc="2.0", id=request_id, result=result)
                    )
                )
            )
        except Exception as exc:
            # The interceptor must never leave a client waiting: answer with a
            # JSON-RPC error instead of dropping the request (issue #39 R1).
            logger.error(f"server/discover failed: {exc}")
            await self._send_discover_error(
                request_id=request_id,
                code=DISCOVER_INTERNAL_ERROR_CODE,
                message_text=f"server/discover failed: {exc}",
            )

    async def _send_discover_error(
        self,
        request_id: Union[str, int],
        code: int,
        message_text: str,
        data: Any = None,
    ) -> None:
        await self._write_stream.send(
            SessionMessage(
                message=types.JSONRPCMessage(
                    types.JSONRPCError(
                        jsonrpc="2.0",
                        id=request_id,
                        error=types.ErrorData(code=code, message=message_text, data=data),
                    )
                )
            )
        )


async def _start_websocket(manager: WebSocketManager) -> None:
    """Connect the WebSocket manager and start its message loop."""
    try:
        await manager.connect()
        await manager.start_background_task()
    except Exception as e:
        logger.error(f"WebSocket startup failed: {e}")


async def shutdown() -> None:
    """
    Graceful shutdown handler.

    1. Cancel all open orders (if CANCEL_ON_SHUTDOWN is enabled and credentials exist)
    2. Close all WebSocket connections
    3. Log shutdown sequence
    """
    logger.info("Graceful shutdown initiated...")

    cancel_on_shutdown = os.getenv("CANCEL_ON_SHUTDOWN", "true").lower() in ("true", "1", "yes")

    # Cancel all open orders if enabled and authenticated
    if cancel_on_shutdown and polymarket_client and polymarket_client.has_api_credentials():
        try:
            logger.info("Canceling all open orders...")
            await polymarket_client.cancel_all_orders()
            logger.info("All open orders canceled successfully")
        except Exception as e:
            logger.error(f"Failed to cancel orders during shutdown: {e}")
    elif cancel_on_shutdown:
        logger.info("Skipping order cancellation (no API credentials)")
    else:
        logger.info("Skipping order cancellation (CANCEL_ON_SHUTDOWN=false)")

    # Close WebSocket connections
    if websocket_manager:
        try:
            logger.info("Closing WebSocket connections...")
            # Stops the background loop and disconnects both sockets.
            await websocket_manager.stop_background_task()
            logger.info("WebSocket connections closed")
        except Exception as e:
            logger.error(f"Failed to close WebSocket connections: {e}")

    logger.info("Graceful shutdown complete")


def _signal_handler(signum: int, frame) -> None:
    """Handle SIGTERM/SIGINT by scheduling async shutdown."""
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name}, initiating shutdown...")
    if _shutdown_event and not _shutdown_event.is_set():
        _shutdown_event.set()


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """
    List available tools.

    Returns:
        List of tools (conditional on authentication):
        - Market Discovery tools (always available - public API)
        - Market Analysis tools (always available - public API)
        - Trading tools (require API credentials)
        - Portfolio Management tools (require API credentials)
        - Real-time WebSocket tools (partial - some require auth)
    """
    tools = []

    # Always available - public APIs (no auth needed)
    tools.extend(market_discovery.get_tools())
    tools.extend(market_analysis.get_tools())

    # Only available with API credentials
    has_credentials = polymarket_client and polymarket_client.has_api_credentials()

    if has_credentials:
        # Trading tools (require L2 auth)
        tools.extend(get_tool_definitions())
        # Portfolio management tools (require auth)
        tools.extend(portfolio_integration.get_portfolio_tool_definitions())
        logger.info("Trading and Portfolio tools enabled (authenticated)")
    else:
        logger.info("Trading and Portfolio tools disabled (no API credentials - read-only mode)")

    # Real-time tools (partial functionality without auth)
    tools.extend(realtime.get_tools())

    return tools


@server.list_resources()
async def list_resources() -> list[types.Resource]:
    """
    List available resources for Claude to access.

    Resources provide read-only access to:
    - Server status and configuration
    - Rate limiter status
    - Safety limits configuration
    """
    resources = [
        types.Resource(
            uri=cast(types.AnyUrl, "polymarket://status"),
            name="Connection Status",
            description="Check Polymarket connection and authentication status",
            mimeType="application/json"
        ),
        types.Resource(
            uri=cast(types.AnyUrl, "polymarket://config"),
            name="Configuration",
            description="View current safety limits and trading configuration",
            mimeType="application/json"
        ),
        types.Resource(
            uri=cast(types.AnyUrl, "polymarket://rate-limits"),
            name="Rate Limiter Status",
            description="Check API rate limit status across all endpoint categories",
            mimeType="application/json"
        ),
    ]

    return resources


@server.read_resource()
async def read_resource(uri: str) -> str:
    """
    Read resource content by URI.

    Args:
        uri: Resource URI (e.g., polymarket://status)

    Returns:
        JSON string with resource data
    """
    import json

    # MCP SDK passes AnyUrl (pydantic v2, not a str subclass); comparing
    # AnyUrl == "literal" is always False. Normalize once, compare as str.
    uri_text = str(uri)

    if uri_text == "polymarket://status":
        # Connection and authentication status
        status_data = {
            "connected": polymarket_client is not None,
            "address": config.POLYGON_ADDRESS if config else None,
            "chain_id": config.POLYMARKET_CHAIN_ID if config else None,
            "has_api_credentials": (
                polymarket_client.has_api_credentials()
                if polymarket_client else False
            ),
            "server_version": __version__,
        }
        return json.dumps(status_data, indent=2)

    elif uri_text == "polymarket://config":
        # Safety limits and configuration
        if not config or not safety_limits:
            return json.dumps({"error": "Configuration not loaded"})

        config_data = {
            "safety_limits": {
                "max_order_size_usd": safety_limits.max_order_size_usd,
                "max_total_exposure_usd": safety_limits.max_total_exposure_usd,
                "max_position_size_per_market": safety_limits.max_position_size_per_market,
                "min_liquidity_required": safety_limits.min_liquidity_required,
                "max_spread_tolerance": safety_limits.max_spread_tolerance,
            },
            "trading_controls": {
                "enable_autonomous_trading": config.ENABLE_AUTONOMOUS_TRADING,
                "require_confirmation_above_usd": config.REQUIRE_CONFIRMATION_ABOVE_USD,
                "auto_cancel_on_large_spread": config.AUTO_CANCEL_ON_LARGE_SPREAD,
            },
            "endpoints": {
                "clob_api": config.CLOB_API_URL,
                "gamma_api": config.GAMMA_API_URL,
            }
        }
        return json.dumps(config_data, indent=2)

    elif uri_text == "polymarket://rate-limits":
        # Rate limiter status
        rate_limiter = get_rate_limiter()
        status = rate_limiter.get_status()
        return json.dumps(status, indent=2)

    else:
        return json.dumps({"error": f"Unknown resource: {uri_text}"})


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> list[types.TextContent]:
    """
    Handle tool calls from Claude.

    Args:
        name: Tool name
        arguments: Tool arguments

    Returns:
        List of TextContent with tool results
    """
    import json

    try:
        # Route to market discovery tools
        if name in ["search_markets", "get_trending_markets", "filter_markets_by_category",
                    "get_event_markets", "get_featured_markets", "get_closing_soon_markets",
                    "get_sports_markets", "get_crypto_markets"]:
            return await market_discovery.handle_tool(name, arguments)

        # Route to market analysis tools
        elif name in ["get_market_details", "get_current_price", "get_orderbook", "get_spread",
                      "get_market_volume", "get_liquidity", "get_price_history", "get_market_holders",
                      "analyze_market_opportunity", "compare_markets"]:
            return await market_analysis.handle_tool(name, arguments)

        # Route to portfolio management tools
        elif name in ["get_all_positions", "get_position_details", "get_portfolio_value",
                      "get_pnl_summary", "get_trade_history", "get_activity_log",
                      "analyze_portfolio_risk", "suggest_portfolio_actions"]:
            return await portfolio_integration.call_portfolio_tool(
                name,
                arguments,
                polymarket_client,
                get_rate_limiter(),
                config
            )

        # Route to real-time websocket tools
        elif name in ["subscribe_market_prices", "subscribe_orderbook_updates", "subscribe_user_orders",
                      "subscribe_user_trades", "subscribe_market_resolution", "get_realtime_status",
                      "unsubscribe_realtime"]:
            if not websocket_manager:
                raise ValueError("WebSocket manager not initialized")
            return await realtime.handle_tool_call(name, arguments)

        # Route to trading tools
        elif trading_tools:
            if name == "create_limit_order":
                result = await trading_tools.create_limit_order(**arguments)
            elif name == "create_market_order":
                result = await trading_tools.create_market_order(**arguments)
            elif name == "create_batch_orders":
                result = await trading_tools.create_batch_orders(**arguments)
            elif name == "suggest_order_price":
                result = await trading_tools.suggest_order_price(**arguments)
            elif name == "get_order_status":
                result = await trading_tools.get_order_status(**arguments)
            elif name == "get_open_orders":
                result = await trading_tools.get_open_orders(**arguments)
            elif name == "get_order_history":
                result = await trading_tools.get_order_history(**arguments)
            elif name == "cancel_order":
                result = await trading_tools.cancel_order(**arguments)
            elif name == "cancel_market_orders":
                result = await trading_tools.cancel_market_orders(**arguments)
            elif name == "cancel_all_orders":
                result = await trading_tools.cancel_all_orders()
            elif name == "execute_smart_trade":
                result = await trading_tools.execute_smart_trade(**arguments)
            elif name == "rebalance_position":
                result = await trading_tools.rebalance_position(**arguments)
            else:
                raise ValueError(f"Unknown tool: {name}")

            # Return result as JSON
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )
            ]
        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        logger.error(f"Tool call failed: {name} - {e}")
        error_result = {
            "success": False,
            "error": str(e),
            "tool": name,
            "arguments": arguments
        }
        return [
            types.TextContent(
                type="text",
                text=json.dumps(error_result, indent=2)
            )
        ]


async def initialize_server() -> None:
    """
    Initialize server components.

    - Load configuration from environment
    - Initialize Polymarket client
    - Set up safety limits
    - Initialize rate limiter
    - Initialize trading tools
    - Initialize WebSocket manager
    """
    global config, polymarket_client, safety_limits, trading_tools, websocket_manager

    try:
        # Load configuration
        logger.info("Loading configuration...")
        config = load_config()

        # Set log level from config
        logging.getLogger().setLevel(config.LOG_LEVEL)

        logger.info(f"Configuration loaded for address: {config.POLYGON_ADDRESS}")

        # Initialize Polymarket client
        logger.info("Initializing Polymarket client...")
        polymarket_client = create_polymarket_client(
            private_key=config.POLYGON_PRIVATE_KEY,
            address=config.POLYGON_ADDRESS,
            chain_id=config.POLYMARKET_CHAIN_ID,
            api_key=config.POLYMARKET_API_KEY,
            api_secret=config.POLYMARKET_API_SECRET,
            passphrase=config.POLYMARKET_PASSPHRASE,
        )

        # Create API credentials if not provided (optional - allows read-only mode)
        if not polymarket_client.has_api_credentials():
            logger.info("No API credentials found. Attempting to create...")
            try:
                await polymarket_client.create_api_credentials()
                logger.info(
                    "API credentials created successfully! "
                    "Save these to your .env file for future use."
                )
                api_key = cast(Any, polymarket_client.api_creds).api_key
                passphrase = cast(Any, polymarket_client.api_creds).api_passphrase
                logger.debug(f"POLYMARKET_API_KEY={api_key[:8]}...")
                logger.debug(f"POLYMARKET_PASSPHRASE={passphrase[:8]}...")
            except Exception as e:
                logger.warning(f"Could not create API credentials: {e}")
                logger.info("Continuing in READ-ONLY mode")
                logger.info("Available: Market Discovery (8 tools) + Market Analysis (10 tools)")
                logger.info("Unavailable: Trading (12 tools) + Portfolio (8 tools)")
                logger.info("To enable trading, fund your wallet or configure existing API credentials")

        # Initialize safety limits
        logger.info("Initializing safety limits...")
        safety_limits = create_safety_limits_from_config(config)

        # Initialize rate limiter (singleton)
        get_rate_limiter()
        logger.info("Rate limiter initialized")

        # Initialize trading tools (only if authenticated)
        if polymarket_client.has_api_credentials():
            logger.info("Initializing trading tools...")
            trading_tools = TradingTools(
                client=polymarket_client,
                safety_limits=safety_limits,
                config=config
            )
            logger.info("Trading tools initialized with 12 tools")
        else:
            logger.info("Trading tools NOT initialized (no API credentials - read-only mode)")

        # Initialize WebSocket manager
        logger.info("Initializing WebSocket manager...")
        websocket_manager = WebSocketManager(config)
        # Register the manager with the realtime tools module (the tools layer
        # owns its own global, see tools/realtime.set_websocket_manager).
        realtime.set_websocket_manager(websocket_manager)
        # Connect WebSocket (non-blocking). The background loop must be started
        # after connecting, otherwise subscriptions never receive messages.
        _websocket_startup_task = asyncio.create_task(_start_websocket(websocket_manager))
        _background_tasks.add(_websocket_startup_task)
        _websocket_startup_task.add_done_callback(_background_tasks.discard)
        logger.info("WebSocket manager initialized with 7 real-time tools")

        logger.info("Server initialization complete!")
        logger.info(f"Connected to Polymarket on chain ID {config.POLYMARKET_CHAIN_ID}")

        # Report available tools based on authentication
        if polymarket_client.has_api_credentials():
            logger.info("Mode: FULL (authenticated)")
            logger.info("Available tools: 45 total (8 Discovery, 10 Analysis, 12 Trading, 8 Portfolio, 7 Real-time)")
        else:
            logger.info("Mode: READ-ONLY (no API credentials)")
            logger.info("Available tools: 25 total (8 Discovery, 10 Analysis, 7 Real-time)")
            logger.info("Trading and Portfolio tools require API credentials")

    except Exception as e:
        logger.error(f"Failed to initialize server: {_safe_error_message(e)}")
        raise


async def main() -> None:
    """
    Main entry point for MCP server.

    Initializes all components and runs the stdio-based MCP server.
    Registers SIGTERM/SIGINT handlers for graceful shutdown.
    """
    global _shutdown_event

    try:
        # Initialize server components
        await initialize_server()

        # Set up shutdown event and signal handlers
        _shutdown_event = asyncio.Event()
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

        # Run MCP server with stdio transport
        logger.info("Starting MCP server...")
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            # Pre-handshake protocol layer (issues #39/#40): answer
            # server/discover and serve version-less handshakes on the
            # declared default before the SDK session exists. See
            # polymarket_mcp.discover for the SDK seam map.
            read_stream = _PreHandshakeStream(read_stream, write_stream)
            # Run server alongside shutdown watcher
            server_task = asyncio.create_task(
                server.run(
                    cast(
                        "MemoryObjectReceiveStream[SessionMessage | Exception]",
                        read_stream,
                    ),
                    write_stream,
                    server.create_initialization_options()
                )
            )
            shutdown_task = asyncio.create_task(_shutdown_event.wait())

            # Wait for either server completion or shutdown signal
            done, pending = await asyncio.wait(
                [server_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel remaining tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # If server task raised an exception, propagate it
            if server_task in done and server_task.exception():
                raise cast(BaseException, server_task.exception())

    except KeyboardInterrupt:
        logger.info("Server stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        # Always attempt graceful shutdown
        await shutdown()


def run():
    """Synchronous entry point for CLI"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
