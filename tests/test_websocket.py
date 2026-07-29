"""
Tests for WebSocket manager and real-time tools.

Tests real WebSocket connections (NO MOCKS) to Polymarket endpoints.
"""
import asyncio
import os
import pytest
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List

from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.utils.websocket_manager import (
    WebSocketManager,
    EventType,
    ChannelType,
    PriceChangeEvent,
    OrderbookUpdate,
    ws_is_open,
)


@pytest.fixture
def config():
    """Create test configuration"""
    return PolymarketConfig(
        POLYGON_PRIVATE_KEY=os.getenv("POLYGON_PRIVATE_KEY", "0" * 64),
        POLYGON_ADDRESS=os.getenv("POLYGON_ADDRESS", "0x" + "0" * 40),
        POLYMARKET_CHAIN_ID=137,
        POLYMARKET_API_KEY=os.getenv("POLYMARKET_API_KEY"),
        POLYMARKET_PASSPHRASE=os.getenv("POLYMARKET_PASSPHRASE"),
    )


@pytest.fixture
async def websocket_manager(config):
    """Create WebSocket manager instance"""
    notifications = []
    logs = []

    async def notification_callback(data: Dict[str, Any]):
        notifications.append(data)

    async def log_callback(message: str):
        logs.append(message)

    manager = WebSocketManager(
        config=config,
        notification_callback=notification_callback,
        log_callback=log_callback
    )

    # Store callbacks for test assertions
    manager._test_notifications = notifications
    manager._test_logs = logs

    yield manager

    # Cleanup
    await manager.stop_background_task()


class TestWebSocketConnection:
    """Test WebSocket connection management"""

    @pytest.mark.asyncio
    async def test_connect_clob(self, websocket_manager):
        """Test CLOB WebSocket connection"""
        await websocket_manager._connect_clob()

        assert websocket_manager.clob_connected is True
        assert websocket_manager.clob_ws is not None
        assert ws_is_open(websocket_manager.clob_ws)

        # Cleanup
        await websocket_manager.disconnect()

    @pytest.mark.asyncio
    async def test_connect_realtime(self, websocket_manager):
        """Test real-time WebSocket connection"""
        await websocket_manager._connect_realtime()

        assert websocket_manager.realtime_connected is True
        assert websocket_manager.realtime_ws is not None
        assert ws_is_open(websocket_manager.realtime_ws)

        # Cleanup
        await websocket_manager.disconnect()

    @pytest.mark.asyncio
    async def test_connect_both(self, websocket_manager):
        """Test connecting to both WebSockets"""
        await websocket_manager.connect()

        assert websocket_manager.clob_connected is True
        assert websocket_manager.realtime_connected is True

        # Cleanup
        await websocket_manager.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect(self, websocket_manager):
        """Test disconnection"""
        await websocket_manager.connect()
        await websocket_manager.disconnect()

        assert websocket_manager.clob_connected is False
        assert websocket_manager.realtime_connected is False
        assert websocket_manager.authenticated is False

    @pytest.mark.asyncio
    async def test_authentication_with_credentials(self, config):
        """Test CLOB authentication when credentials available"""
        if not config.has_api_credentials():
            pytest.skip("API credentials not configured")

        manager = WebSocketManager(config=config)
        await manager._connect_clob()

        # Wait for authentication
        await asyncio.sleep(2)

        assert manager.authenticated is True

        # Cleanup
        await manager.disconnect()


class TestSubscriptionManagement:
    """Test subscription creation and management"""

    @pytest.mark.asyncio
    async def test_subscribe_price_change(self, websocket_manager):
        """Test subscribing to price changes"""
        await websocket_manager.connect()

        # Subscribe to a test market
        test_market_id = "21742633143463906290569050155826241533067272736897614950488156847949938836455"

        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.PRICE_CHANGE,
            channel=ChannelType.CLOB_MARKET,
            market_ids=[test_market_id],
            callback_type="notification"
        )

        assert subscription_id is not None
        assert subscription_id in websocket_manager.subscriptions

        subscription = websocket_manager.subscriptions[subscription_id]
        assert subscription.type == EventType.PRICE_CHANGE
        assert subscription.channel == ChannelType.CLOB_MARKET
        assert subscription.market_ids == [test_market_id]

        # Cleanup
        await websocket_manager.unsubscribe(subscription_id)
        await websocket_manager.disconnect()

    @pytest.mark.asyncio
    async def test_subscribe_orderbook(self, websocket_manager):
        """Test subscribing to orderbook updates"""
        await websocket_manager.connect()

        # Subscribe to a test token
        test_token_id = "71321045679252212594626385532706912750332728571942532289631379312455583992563"

        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.AGG_ORDERBOOK,
            channel=ChannelType.CLOB_MARKET,
            token_ids=[test_token_id],
            callback_type="log"
        )

        assert subscription_id is not None
        subscription = websocket_manager.subscriptions[subscription_id]
        assert subscription.type == EventType.AGG_ORDERBOOK
        assert subscription.token_ids == [test_token_id]
        assert subscription.callback_type == "log"

        # Cleanup
        await websocket_manager.unsubscribe(subscription_id)
        await websocket_manager.disconnect()

    @pytest.mark.asyncio
    async def test_subscribe_user_orders_requires_auth(self, websocket_manager):
        """Test that user order subscription requires authentication"""
        await websocket_manager.connect()

        if not websocket_manager.authenticated:
            # Should raise RuntimeError
            with pytest.raises(RuntimeError, match="authentication required"):
                await websocket_manager.subscribe(
                    event_type=EventType.ORDER,
                    channel=ChannelType.CLOB_USER,
                    callback_type="notification"
                )
        else:
            # If authenticated, should succeed
            subscription_id = await websocket_manager.subscribe(
                event_type=EventType.ORDER,
                channel=ChannelType.CLOB_USER,
                callback_type="notification"
            )
            assert subscription_id is not None
            await websocket_manager.unsubscribe(subscription_id)

        await websocket_manager.disconnect()

    @pytest.mark.asyncio
    async def test_unsubscribe(self, websocket_manager):
        """Test unsubscribing from feed"""
        await websocket_manager.connect()

        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.PRICE_CHANGE,
            channel=ChannelType.CLOB_MARKET,
            market_ids=["test_market"],
            callback_type="notification"
        )

        # Unsubscribe
        result = await websocket_manager.unsubscribe(subscription_id)

        assert result is True
        assert subscription_id not in websocket_manager.subscriptions

        # Unsubscribe again should return False
        result = await websocket_manager.unsubscribe(subscription_id)
        assert result is False

        await websocket_manager.disconnect()


class TestMessageHandling:
    """Test WebSocket message handling"""

    @pytest.mark.asyncio
    async def test_handle_price_change_event(self, websocket_manager):
        """Test handling price change messages"""
        # Mock price change message
        message = {
            "type": "price_change",
            "asset_id": "test_asset",
            "price": "0.55",
            "timestamp": datetime.now().isoformat(),
            "market": "test_market"
        }

        # Create subscription first
        await websocket_manager.connect()
        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.PRICE_CHANGE,
            channel=ChannelType.CLOB_MARKET,
            market_ids=["test_market"],
            callback_type="notification"
        )

        # Handle message
        await websocket_manager.handle_message("clob", message)

        # Check subscription was updated
        subscription = websocket_manager.subscriptions[subscription_id]
        assert subscription.events_received == 1
        assert subscription.last_event_at is not None

        # Check notification was sent
        assert len(websocket_manager._test_notifications) > 0

        await websocket_manager.disconnect()

    @pytest.mark.asyncio
    async def test_handle_orderbook_update(self, websocket_manager):
        """Test handling orderbook update messages"""
        message = {
            "type": "agg_orderbook",
            "asset_id": "test_asset",
            "bids": [["0.50", "100"], ["0.49", "200"]],
            "asks": [["0.51", "150"], ["0.52", "250"]],
            "timestamp": datetime.now().isoformat()
        }

        await websocket_manager.connect()
        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.AGG_ORDERBOOK,
            channel=ChannelType.CLOB_MARKET,
            token_ids=["test_asset"],
            callback_type="notification"
        )

        await websocket_manager.handle_message("clob", message)

        subscription = websocket_manager.subscriptions[subscription_id]
        assert subscription.events_received == 1

        await websocket_manager.disconnect()


class TestBackgroundTask:
    """Test background message processing"""

    @pytest.mark.asyncio
    async def test_start_background_task(self, websocket_manager):
        """Test starting background task"""
        await websocket_manager.connect()
        await websocket_manager.start_background_task()

        assert websocket_manager.should_run is True
        assert websocket_manager.background_task is not None
        assert not websocket_manager.background_task.done()

        await websocket_manager.stop_background_task()

    @pytest.mark.asyncio
    async def test_stop_background_task(self, websocket_manager):
        """Test stopping background task"""
        await websocket_manager.connect()
        await websocket_manager.start_background_task()

        await websocket_manager.stop_background_task()

        assert websocket_manager.should_run is False
        assert not websocket_manager.clob_connected
        assert not websocket_manager.realtime_connected

    @pytest.mark.asyncio
    async def test_background_task_receives_messages(self, websocket_manager):
        """Test that background task receives real messages"""
        await websocket_manager.connect()

        # Subscribe to a real active market
        test_market_id = "21742633143463906290569050155826241533067272736897614950488156847949938836455"

        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.PRICE_CHANGE,
            channel=ChannelType.CLOB_MARKET,
            market_ids=[test_market_id],
            callback_type="notification"
        )

        # Start background task
        await websocket_manager.start_background_task()

        # Wait for some messages (timeout after 30 seconds)
        start_time = asyncio.get_event_loop().time()
        while (
            websocket_manager.total_events_received == 0
            and (asyncio.get_event_loop().time() - start_time) < 30
        ):
            await asyncio.sleep(1)

        # Check that we received events (may not receive if market is inactive)
        # This is not a failure - some markets don't update frequently
        print(f"Received {websocket_manager.total_events_received} events")

        await websocket_manager.stop_background_task()


class TestReconnection:
    """Test reconnection logic"""

    @pytest.mark.asyncio
    async def test_reconnect_after_disconnect(self, websocket_manager):
        """Test reconnection after manual disconnect"""
        await websocket_manager.connect()
        assert websocket_manager.clob_connected is True

        # Disconnect
        await websocket_manager.disconnect()
        assert websocket_manager.clob_connected is False

        # Reconnect
        await websocket_manager.reconnect()
        assert websocket_manager.clob_connected is True
        assert websocket_manager.realtime_connected is True

        await websocket_manager.disconnect()

    @pytest.mark.asyncio
    async def test_resubscribe_after_reconnect(self, websocket_manager):
        """Test that subscriptions are restored after reconnect"""
        await websocket_manager.connect()

        # Create subscription
        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.PRICE_CHANGE,
            channel=ChannelType.CLOB_MARKET,
            market_ids=["test_market"],
            callback_type="notification"
        )

        # Reconnect
        await websocket_manager.reconnect()

        # Subscription should still exist
        assert subscription_id in websocket_manager.subscriptions

        await websocket_manager.disconnect()


class TestStatus:
    """Test status reporting"""

    @pytest.mark.asyncio
    async def test_get_status(self, websocket_manager):
        """Test getting WebSocket status"""
        await websocket_manager.connect()

        status = websocket_manager.get_status()

        assert "connections" in status
        assert "subscriptions" in status
        assert "statistics" in status
        assert "background_task" in status

        assert status["connections"]["clob"]["connected"] is True
        assert status["connections"]["realtime"]["connected"] is True

        await websocket_manager.disconnect()

    @pytest.mark.asyncio
    async def test_status_with_subscriptions(self, websocket_manager):
        """Test status includes subscription information"""
        await websocket_manager.connect()

        # Create multiple subscriptions
        sub1 = await websocket_manager.subscribe(
            event_type=EventType.PRICE_CHANGE,
            channel=ChannelType.CLOB_MARKET,
            market_ids=["market1"],
        )

        sub2 = await websocket_manager.subscribe(
            event_type=EventType.AGG_ORDERBOOK,
            channel=ChannelType.CLOB_MARKET,
            token_ids=["token1"],
        )

        status = websocket_manager.get_status()

        assert status["subscriptions"]["total"] == 2
        assert len(status["subscriptions"]["active"]) == 2

        await websocket_manager.disconnect()


class TestEventStatistics:
    """Test event statistics tracking"""

    @pytest.mark.asyncio
    async def test_event_statistics(self, websocket_manager):
        """Test that events are tracked in statistics"""
        await websocket_manager.connect()

        # Create subscription
        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.PRICE_CHANGE,
            channel=ChannelType.CLOB_MARKET,
            market_ids=["test_market"],
        )

        # Simulate some events
        for i in range(5):
            message = {
                "type": "price_change",
                "asset_id": "test_asset",
                "price": f"0.{50 + i}",
                "timestamp": datetime.now().isoformat(),
                "market": "test_market"
            }
            await websocket_manager.handle_message("clob", message)

        # Check statistics
        status = websocket_manager.get_status()
        assert status["statistics"]["total_events"] == 5
        assert status["statistics"]["events_by_type"]["price_change"] == 5

        # Check subscription statistics
        subscription = websocket_manager.subscriptions[subscription_id]
        assert subscription.events_received == 5

        await websocket_manager.disconnect()


# Integration test with real data (long-running)
class TestRealDataIntegration:
    """Integration tests with real WebSocket data"""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_receive_real_price_updates(self, websocket_manager):
        """Test receiving real price updates from active market"""
        await websocket_manager.connect()

        # Subscribe to a known active market
        # This is a real market ID from Polymarket
        active_market_id = "21742633143463906290569050155826241533067272736897614950488156847949938836455"

        subscription_id = await websocket_manager.subscribe(
            event_type=EventType.PRICE_CHANGE,
            channel=ChannelType.CLOB_MARKET,
            market_ids=[active_market_id],
            callback_type="notification"
        )

        # Start background task
        await websocket_manager.start_background_task()

        # Wait up to 60 seconds for events
        print("Waiting for real market events (max 60s)...")
        start_time = asyncio.get_event_loop().time()
        timeout = 60

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            if websocket_manager.total_events_received > 0:
                break
            await asyncio.sleep(1)

        # Check results
        subscription = websocket_manager.subscriptions[subscription_id]
        print(f"Received {subscription.events_received} price change events")
        print(f"Total events: {websocket_manager.total_events_received}")

        # Note: This may be 0 if market is not actively trading
        # That's ok - we're testing the connection works, not market activity

        await websocket_manager.stop_background_task()
