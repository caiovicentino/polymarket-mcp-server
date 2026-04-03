"""
WebSocket manager for Polymarket real-time data.

Manages connections to:
- CLOB WebSocket (wss://ws-subscriptions-clob.polymarket.com/ws/)
- Real-time data WebSocket (wss://ws-live-data.polymarket.com)

Handles authentication, subscriptions, and event routing.
"""
import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from enum import Enum

import websockets
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ChannelType(str, Enum):
    """WebSocket channel types"""
    CLOB_USER = "user"  # User-specific orders/trades
    CLOB_MARKET = "market"  # Market data (prices, orderbook)
    ACTIVITY = "activity"  # Trade/order activity
    CRYPTO_PRICES = "crypto_prices"  # Crypto price feeds


class EventType(str, Enum):
    """WebSocket event types"""
    # CLOB User events (requires auth)
    ORDER = "order"
    TRADE = "trade"

    # CLOB Market events (no auth)
    PRICE_CHANGE = "price_change"
    AGG_ORDERBOOK = "agg_orderbook"
    LAST_TRADE_PRICE = "last_trade_price"
    TICK_SIZE_CHANGE = "tick_size_change"
    MARKET_CREATED = "market_created"
    MARKET_RESOLVED = "market_resolved"

    # Activity events
    TRADES = "trades"
    ORDERS_MATCHED = "orders_matched"

    # Crypto prices
    CRYPTO_UPDATE = "update"


class PriceChangeEvent(BaseModel):
    """Price change event data"""
    asset_id: str
    price: Decimal
    timestamp: datetime
    market: Optional[str] = None


class OrderbookUpdate(BaseModel):
    """Orderbook update event data"""
    asset_id: str
    bids: List[Tuple[Decimal, Decimal]]  # [(price, size), ...]
    asks: List[Tuple[Decimal, Decimal]]
    timestamp: datetime


class OrderUpdate(BaseModel):
    """Order update event data"""
    order_id: str
    status: str
    filled_size: Decimal
    remaining_size: Decimal
    price: Decimal
    side: str
    timestamp: datetime
    market_id: Optional[str] = None


class TradeUpdate(BaseModel):
    """Trade update event data"""
    trade_id: str
    order_id: str
    market_id: str
    price: Decimal
    size: Decimal
    side: str
    timestamp: datetime


class MarketResolutionEvent(BaseModel):
    """Market resolution event data"""
    market_id: str
    outcome: str
    timestamp: datetime


class Subscription(BaseModel):
    """Active subscription tracking"""
    id: str
    type: EventType
    channel: ChannelType
    market_ids: Optional[List[str]] = None
    token_ids: Optional[List[str]] = None
    callback_type: str = "notification"  # or "log"
    created_at: datetime
    events_received: int = 0
    last_event_at: Optional[datetime] = None


class WebSocketManager:
    """
    Manages WebSocket connections to Polymarket real-time data feeds.

    Features:
    - Dual WebSocket connections (CLOB + Real-time data)
    - Authentication for CLOB user channel
    - Auto-reconnect with exponential backoff
    - Subscription management
    - Event routing and notifications
    - Message buffering
    """

    # WebSocket endpoints
    CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/"
    REALTIME_WS_URL = "wss://ws-live-data.polymarket.com"

    # Reconnect settings
    INITIAL_RECONNECT_DELAY = 1  # seconds
    MAX_RECONNECT_DELAY = 60  # seconds
    RECONNECT_MULTIPLIER = 2

    def __init__(
        self,
        config,
        notification_callback: Optional[Callable] = None,
        log_callback: Optional[Callable] = None
    ):
        """
        Initialize WebSocket manager.

        Args:
            config: PolymarketConfig instance with API credentials
            notification_callback: Async function to send MCP notifications
            log_callback: Async function to send log messages
        """
        self.config = config
        self.notification_callback = notification_callback
        self.log_callback = log_callback

        # WebSocket connections
        self.clob_ws: Optional[websockets.WebSocketClientProtocol] = None
        self.realtime_ws: Optional[websockets.WebSocketClientProtocol] = None

        # Connection state
        self.clob_connected = False
        self.realtime_connected = False
        self.authenticated = False

        # Subscriptions
        self.subscriptions: Dict[str, Subscription] = {}
        self.market_subscriptions: Dict[str, Set[str]] = defaultdict(set)  # market_id -> subscription_ids
        self.token_subscriptions: Dict[str, Set[str]] = defaultdict(set)  # token_id -> subscription_ids

        # Background tasks
        self.background_task: Optional[asyncio.Task] = None
        self.should_run = False

        # Reconnect tracking
        self.reconnect_attempts = 0
        self.last_reconnect_time = 0

        # Event statistics
        self.total_events_received = 0
        self.events_by_type: Dict[str, int] = defaultdict(int)
        self.connection_errors = 0
        self.reconnect_count = 0

        # Message buffer (for missed messages during disconnect)
        self.message_buffer: List[Dict[str, Any]] = []
        self.max_buffer_size = 1000

        logger.info("WebSocketManager initialized")

    async def connect(self) -> None:
        """
        Establish WebSocket connections.

        Connects to both CLOB and real-time data WebSockets.
        Authenticates CLOB connection if credentials available.
        """
        try:
            logger.info("Connecting to Polymarket WebSocket endpoints...")

            # Connect to CLOB WebSocket
            await self._connect_clob()

            # Connect to real-time data WebSocket
            await self._connect_realtime()

            logger.info("WebSocket connections established")

        except Exception as e:
            logger.error(f"Failed to establish WebSocket connections: {e}")
            self.connection_errors += 1
            raise

    async def _connect_clob(self) -> None:
        """Connect to CLOB WebSocket"""
        try:
            logger.info(f"Connecting to CLOB WebSocket: {self.CLOB_WS_URL}")
            self.clob_ws = await websockets.connect(
                self.CLOB_WS_URL,
                ping_interval=20,
                ping_timeout=10
            )
            self.clob_connected = True
            logger.info("CLOB WebSocket connected")

            # Authenticate if credentials available
            if self.config.has_api_credentials():
                await self._authenticate_clob()
            else:
                logger.warning("No CLOB API credentials - user-specific subscriptions unavailable")

        except Exception as e:
            logger.error(f"Failed to connect to CLOB WebSocket: {e}")
            self.clob_connected = False
            raise

    async def _connect_realtime(self) -> None:
        """Connect to real-time data WebSocket"""
        try:
            logger.info(f"Connecting to real-time WebSocket: {self.REALTIME_WS_URL}")
            self.realtime_ws = await websockets.connect(
                self.REALTIME_WS_URL,
                ping_interval=20,
                ping_timeout=10
            )
            self.realtime_connected = True
            logger.info("Real-time WebSocket connected")

        except Exception as e:
            logger.error(f"Failed to connect to real-time WebSocket: {e}")
            self.realtime_connected = False
            raise

    async def _authenticate_clob(self) -> None:
        """
        Authenticate CLOB WebSocket connection.

        Sends authentication message with API credentials.
        """
        try:
            auth_message = {
                "auth": {
                    "apiKey": self.config.POLYMARKET_API_KEY,
                    "secret": self.config.POLYMARKET_API_SECRET or self.config.POLYMARKET_PASSPHRASE,
                    "passphrase": self.config.POLYMARKET_PASSPHRASE
                }
            }

            await self.clob_ws.send(json.dumps(auth_message))
            logger.info("CLOB authentication message sent")

            # Wait for auth response
            response = await asyncio.wait_for(self.clob_ws.recv(), timeout=5.0)
            response_data = json.loads(response)

            if response_data.get("type") == "authenticated":
                self.authenticated = True
                logger.info("CLOB WebSocket authenticated successfully")
            else:
                logger.error(f"CLOB authentication failed: {response_data}")
                self.authenticated = False

        except asyncio.TimeoutError:
            logger.error("CLOB authentication timeout")
            self.authenticated = False
        except Exception as e:
            logger.error(f"CLOB authentication error: {e}")
            self.authenticated = False

    async def disconnect(self) -> None:
        """
        Disconnect all WebSocket connections gracefully.
        """
        logger.info("Disconnecting WebSocket connections...")

        # Close CLOB connection
        if self.clob_ws and not self.clob_ws.closed:
            await self.clob_ws.close()
            logger.info("CLOB WebSocket disconnected")
        self.clob_connected = False
        self.authenticated = False

        # Close real-time connection
        if self.realtime_ws and not self.realtime_ws.closed:
            await self.realtime_ws.close()
            logger.info("Real-time WebSocket disconnected")
        self.realtime_connected = False

        logger.info("All WebSocket connections closed")

    async def reconnect(self) -> None:
        """
        Reconnect with exponential backoff.

        Implements exponential backoff strategy to avoid overwhelming the server.
        """
        self.reconnect_count += 1

        # Calculate backoff delay
        delay = min(
            self.INITIAL_RECONNECT_DELAY * (self.RECONNECT_MULTIPLIER ** self.reconnect_attempts),
            self.MAX_RECONNECT_DELAY
        )

        logger.info(f"Reconnecting in {delay}s (attempt {self.reconnect_attempts + 1})...")
        await asyncio.sleep(delay)

        try:
            # Disconnect existing connections
            await self.disconnect()

            # Reconnect
            await self.connect()

            # Resubscribe to all active subscriptions
            await self._resubscribe_all()

            # Reset reconnect counter on success
            self.reconnect_attempts = 0
            self.last_reconnect_time = time.time()
            logger.info("Reconnection successful")

        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            self.reconnect_attempts += 1
            # Will retry in next iteration

    async def _resubscribe_all(self) -> None:
        """Resubscribe to all active subscriptions after reconnect"""
        logger.info(f"Resubscribing to {len(self.subscriptions)} active subscriptions...")

        for sub in self.subscriptions.values():
            try:
                await self._send_subscription(sub)
            except Exception as e:
                logger.error(f"Failed to resubscribe {sub.id}: {e}")

    async def subscribe(
        self,
        event_type: EventType,
        channel: ChannelType,
        market_ids: Optional[List[str]] = None,
        token_ids: Optional[List[str]] = None,
        callback_type: str = "notification"
    ) -> str:
        """
        Add a new subscription.

        Args:
            event_type: Type of event to subscribe to
            channel: Channel type
            market_ids: Optional list of market IDs to filter
            token_ids: Optional list of token IDs to filter
            callback_type: 'notification' or 'log'

        Returns:
            Subscription ID

        Raises:
            RuntimeError: If subscription not supported or connection not available
        """
        # Validate authentication for user channel
        if channel == ChannelType.CLOB_USER and not self.authenticated:
            raise RuntimeError("CLOB authentication required for user subscriptions")

        # Create subscription
        subscription = Subscription(
            id=str(uuid.uuid4()),
            type=event_type,
            channel=channel,
            market_ids=market_ids,
            token_ids=token_ids,
            callback_type=callback_type,
            created_at=datetime.now(),
            events_received=0
        )

        # Store subscription
        self.subscriptions[subscription.id] = subscription

        # Track by market/token
        if market_ids:
            for market_id in market_ids:
                self.market_subscriptions[market_id].add(subscription.id)
        if token_ids:
            for token_id in token_ids:
                self.token_subscriptions[token_id].add(subscription.id)

        # Send subscription message
        await self._send_subscription(subscription)

        logger.info(
            f"Subscription created: {subscription.id} "
            f"(type: {event_type}, channel: {channel})"
        )

        return subscription.id

    async def _send_subscription(self, subscription: Subscription) -> None:
        """Send subscription message to appropriate WebSocket"""
        # Determine which WebSocket to use
        ws = None
        if subscription.channel in [ChannelType.CLOB_USER, ChannelType.CLOB_MARKET]:
            ws = self.clob_ws
            if not self.clob_connected:
                raise RuntimeError("CLOB WebSocket not connected")
        elif subscription.channel in [ChannelType.ACTIVITY, ChannelType.CRYPTO_PRICES]:
            ws = self.realtime_ws
            if not self.realtime_connected:
                raise RuntimeError("Real-time WebSocket not connected")

        # Build subscription message
        message = {
            "type": "subscribe",
            "channel": subscription.channel.value,
            "event": subscription.type.value
        }

        if subscription.market_ids:
            message["markets"] = subscription.market_ids
        if subscription.token_ids:
            message["assets"] = subscription.token_ids

        # Send message
        await ws.send(json.dumps(message))
        logger.debug(f"Subscription message sent: {message}")

    async def unsubscribe(self, subscription_id: str) -> bool:
        """
        Remove a subscription.

        Args:
            subscription_id: ID of subscription to remove

        Returns:
            True if subscription was removed, False if not found
        """
        if subscription_id not in self.subscriptions:
            return False

        subscription = self.subscriptions[subscription_id]

        # Send unsubscribe message
        try:
            await self._send_unsubscription(subscription)
        except Exception as e:
            logger.error(f"Failed to send unsubscribe message: {e}")

        # Remove from tracking
        if subscription.market_ids:
            for market_id in subscription.market_ids:
                self.market_subscriptions[market_id].discard(subscription_id)
        if subscription.token_ids:
            for token_id in subscription.token_ids:
                self.token_subscriptions[token_id].discard(subscription_id)

        # Remove subscription
        del self.subscriptions[subscription_id]

        logger.info(f"Subscription removed: {subscription_id}")
        return True

    async def _send_unsubscription(self, subscription: Subscription) -> None:
        """Send unsubscribe message to appropriate WebSocket"""
        ws = None
        if subscription.channel in [ChannelType.CLOB_USER, ChannelType.CLOB_MARKET]:
            ws = self.clob_ws
        elif subscription.channel in [ChannelType.ACTIVITY, ChannelType.CRYPTO_PRICES]:
            ws = self.realtime_ws

        if not ws or ws.closed:
            return

        message = {
            "type": "unsubscribe",
            "channel": subscription.channel.value,
            "event": subscription.type.value
        }

        await ws.send(json.dumps(message))

    async def handle_message(self, channel: str, message: Dict[str, Any]) -> None:
        """
        Route incoming WebSocket message to appropriate handler.

        Args:
            channel: Channel the message came from ('clob' or 'realtime')
            message: Parsed message data
        """
        try:
            event_type = message.get("type") or message.get("event")
            if not event_type:
                logger.warning(f"Message without event type: {message}")
                return

            # Update statistics
            self.total_events_received += 1
            self.events_by_type[event_type] += 1

            # Route to specific handler
            if event_type == EventType.PRICE_CHANGE.value:
                await self._handle_price_change(message)
            elif event_type == EventType.AGG_ORDERBOOK.value:
                await self._handle_orderbook_update(message)
            elif event_type == EventType.ORDER.value:
                await self._handle_order_update(message)
            elif event_type == EventType.TRADE.value:
                await self._handle_trade_update(message)
            elif event_type == EventType.MARKET_RESOLVED.value:
                await self._handle_market_resolution(message)
            else:
                # Generic handler for other events
                await self._handle_generic_event(event_type, message)

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)

    async def _handle_price_change(self, data: Dict[str, Any]) -> None:
        """Handle price change event"""
        try:
            event = PriceChangeEvent(
                asset_id=data.get("asset_id", ""),
                price=Decimal(str(data.get("price", 0))),
                timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat())),
                market=data.get("market")
            )

            # Find matching subscriptions
            matching_subs = self._find_matching_subscriptions(
                EventType.PRICE_CHANGE,
                event.market,
                event.asset_id
            )

            # Notify each subscription
            for sub in matching_subs:
                sub.events_received += 1
                sub.last_event_at = datetime.now()

                if sub.callback_type == "notification" and self.notification_callback:
                    await self.notification_callback({
                        "type": "price_change",
                        "subscription_id": sub.id,
                        "asset_id": event.asset_id,
                        "price": float(event.price),
                        "market": event.market,
                        "timestamp": event.timestamp.isoformat()
                    })
                elif sub.callback_type == "log" and self.log_callback:
                    await self.log_callback(
                        f"Price change: {event.market or event.asset_id} -> {event.price}"
                    )

        except Exception as e:
            logger.error(f"Error handling price change: {e}")

    async def _handle_orderbook_update(self, data: Dict[str, Any]) -> None:
        """Handle orderbook update event"""
        try:
            # Parse bids and asks
            bids = [(Decimal(str(b[0])), Decimal(str(b[1]))) for b in data.get("bids", [])]
            asks = [(Decimal(str(a[0])), Decimal(str(a[1]))) for a in data.get("asks", [])]

            event = OrderbookUpdate(
                asset_id=data.get("asset_id", ""),
                bids=bids,
                asks=asks,
                timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat()))
            )

            matching_subs = self._find_matching_subscriptions(
                EventType.AGG_ORDERBOOK,
                None,
                event.asset_id
            )

            for sub in matching_subs:
                sub.events_received += 1
                sub.last_event_at = datetime.now()

                if sub.callback_type == "notification" and self.notification_callback:
                    await self.notification_callback({
                        "type": "orderbook_update",
                        "subscription_id": sub.id,
                        "asset_id": event.asset_id,
                        "best_bid": float(bids[0][0]) if bids else None,
                        "best_ask": float(asks[0][0]) if asks else None,
                        "bid_depth": len(bids),
                        "ask_depth": len(asks),
                        "timestamp": event.timestamp.isoformat()
                    })

        except Exception as e:
            logger.error(f"Error handling orderbook update: {e}")

    async def _handle_order_update(self, data: Dict[str, Any]) -> None:
        """Handle order update event"""
        try:
            event = OrderUpdate(
                order_id=data.get("order_id", ""),
                status=data.get("status", ""),
                filled_size=Decimal(str(data.get("filled_size", 0))),
                remaining_size=Decimal(str(data.get("remaining_size", 0))),
                price=Decimal(str(data.get("price", 0))),
                side=data.get("side", ""),
                timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat())),
                market_id=data.get("market_id")
            )

            matching_subs = self._find_matching_subscriptions(
                EventType.ORDER,
                event.market_id
            )

            for sub in matching_subs:
                sub.events_received += 1
                sub.last_event_at = datetime.now()

                if sub.callback_type == "notification" and self.notification_callback:
                    await self.notification_callback({
                        "type": "order_update",
                        "subscription_id": sub.id,
                        "order_id": event.order_id,
                        "status": event.status,
                        "filled_size": float(event.filled_size),
                        "remaining_size": float(event.remaining_size),
                        "price": float(event.price),
                        "side": event.side,
                        "market_id": event.market_id,
                        "timestamp": event.timestamp.isoformat()
                    })

        except Exception as e:
            logger.error(f"Error handling order update: {e}")

    async def _handle_trade_update(self, data: Dict[str, Any]) -> None:
        """Handle trade update event"""
        try:
            event = TradeUpdate(
                trade_id=data.get("trade_id", ""),
                order_id=data.get("order_id", ""),
                market_id=data.get("market_id", ""),
                price=Decimal(str(data.get("price", 0))),
                size=Decimal(str(data.get("size", 0))),
                side=data.get("side", ""),
                timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat()))
            )

            matching_subs = self._find_matching_subscriptions(
                EventType.TRADE,
                event.market_id
            )

            for sub in matching_subs:
                sub.events_received += 1
                sub.last_event_at = datetime.now()

                if sub.callback_type == "notification" and self.notification_callback:
                    await self.notification_callback({
                        "type": "trade_update",
                        "subscription_id": sub.id,
                        "trade_id": event.trade_id,
                        "order_id": event.order_id,
                        "market_id": event.market_id,
                        "price": float(event.price),
                        "size": float(event.size),
                        "side": event.side,
                        "timestamp": event.timestamp.isoformat()
                    })

        except Exception as e:
            logger.error(f"Error handling trade update: {e}")

    async def _handle_market_resolution(self, data: Dict[str, Any]) -> None:
        """Handle market resolution event"""
        try:
            event = MarketResolutionEvent(
                market_id=data.get("market_id", ""),
                outcome=data.get("outcome", ""),
                timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat()))
            )

            matching_subs = self._find_matching_subscriptions(
                EventType.MARKET_RESOLVED,
                event.market_id
            )

            for sub in matching_subs:
                sub.events_received += 1
                sub.last_event_at = datetime.now()

                if sub.callback_type == "notification" and self.notification_callback:
                    await self.notification_callback({
                        "type": "market_resolved",
                        "subscription_id": sub.id,
                        "market_id": event.market_id,
                        "outcome": event.outcome,
                        "timestamp": event.timestamp.isoformat()
                    })

        except Exception as e:
            logger.error(f"Error handling market resolution: {e}")

    async def _handle_generic_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle generic event (fallback)"""
        logger.debug(f"Generic event received: {event_type} - {data}")

    def _find_matching_subscriptions(
        self,
        event_type: EventType,
        market_id: Optional[str] = None,
        token_id: Optional[str] = None
    ) -> List[Subscription]:
        """Find subscriptions matching the event criteria"""
        matching = []

        for sub in self.subscriptions.values():
            # Check event type match
            if sub.type != event_type:
                continue

            # Check market filter
            if sub.market_ids and market_id:
                if market_id not in sub.market_ids:
                    continue

            # Check token filter
            if sub.token_ids and token_id:
                if token_id not in sub.token_ids:
                    continue

            matching.append(sub)

        return matching

    async def start_background_task(self) -> None:
        """
        Start background task to process WebSocket messages.

        Runs continuously until stopped, processing messages from both WebSockets.
        """
        if self.background_task and not self.background_task.done():
            logger.warning("Background task already running")
            return

        self.should_run = True
        self.background_task = asyncio.create_task(self._background_loop())
        logger.info("Background WebSocket task started")

    async def stop_background_task(self) -> None:
        """
        Stop background task gracefully.
        """
        logger.info("Stopping background WebSocket task...")
        self.should_run = False

        if self.background_task:
            try:
                await asyncio.wait_for(self.background_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Background task did not stop gracefully, cancelling...")
                self.background_task.cancel()

        await self.disconnect()
        logger.info("Background task stopped")

    async def _background_loop(self) -> None:
        """
        Main background loop for processing WebSocket messages.

        Handles both CLOB and real-time WebSocket connections simultaneously.
        Implements auto-reconnect on connection loss.
        """
        logger.info("Background WebSocket loop started")

        while self.should_run:
            try:
                # Ensure connections are active
                if not self.clob_connected or not self.realtime_connected:
                    await self.reconnect()
                    continue

                # Process messages from both WebSockets concurrently
                tasks = []

                if self.clob_ws and not self.clob_ws.closed:
                    tasks.append(asyncio.create_task(self._receive_clob_messages()))

                if self.realtime_ws and not self.realtime_ws.closed:
                    tasks.append(asyncio.create_task(self._receive_realtime_messages()))

                if tasks:
                    # Wait for all tasks with timeout to avoid starving either channel
                    done, pending = await asyncio.wait(
                        tasks,
                        timeout=1.0,
                        return_when=asyncio.ALL_COMPLETED
                    )

                    # Cancel any tasks that didn't finish within timeout
                    for task in pending:
                        task.cancel()
                else:
                    await asyncio.sleep(1.0)

            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed, reconnecting...")
                await self.reconnect()
            except Exception as e:
                logger.error(f"Error in background loop: {e}", exc_info=True)
                await asyncio.sleep(1.0)

        logger.info("Background WebSocket loop stopped")

    async def _receive_clob_messages(self) -> None:
        """Receive messages from CLOB WebSocket"""
        if not self.clob_ws or self.clob_ws.closed:
            return

        try:
            message = await self.clob_ws.recv()
            data = json.loads(message)
            await self.handle_message("clob", data)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse CLOB message: {e}")
        except Exception as e:
            logger.error(f"Error receiving CLOB message: {e}")
            raise

    async def _receive_realtime_messages(self) -> None:
        """Receive messages from real-time WebSocket"""
        if not self.realtime_ws or self.realtime_ws.closed:
            return

        try:
            message = await self.realtime_ws.recv()
            data = json.loads(message)
            await self.handle_message("realtime", data)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse real-time message: {e}")
        except Exception as e:
            logger.error(f"Error receiving real-time message: {e}")
            raise

    def get_status(self) -> Dict[str, Any]:
        """
        Get current WebSocket manager status.

        Returns:
            Dictionary with connection status, subscriptions, and statistics
        """
        return {
            "connections": {
                "clob": {
                    "connected": self.clob_connected,
                    "authenticated": self.authenticated,
                    "url": self.CLOB_WS_URL
                },
                "realtime": {
                    "connected": self.realtime_connected,
                    "url": self.REALTIME_WS_URL
                }
            },
            "subscriptions": {
                "total": len(self.subscriptions),
                "by_type": {
                    event_type: len([s for s in self.subscriptions.values() if s.type == event_type])
                    for event_type in EventType
                },
                "active": [
                    {
                        "id": sub.id,
                        "type": sub.type.value,
                        "channel": sub.channel.value,
                        "created_at": sub.created_at.isoformat(),
                        "events_received": sub.events_received,
                        "last_event": sub.last_event_at.isoformat() if sub.last_event_at else None
                    }
                    for sub in self.subscriptions.values()
                ]
            },
            "statistics": {
                "total_events": self.total_events_received,
                "events_by_type": dict(self.events_by_type),
                "connection_errors": self.connection_errors,
                "reconnect_count": self.reconnect_count,
                "last_reconnect": self.last_reconnect_time
            },
            "background_task": {
                "running": self.should_run,
                "task_exists": self.background_task is not None
            }
        }
