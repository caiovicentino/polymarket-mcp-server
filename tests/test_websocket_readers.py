"""
Tests for per-channel WebSocket readers (issue #13, third item).

The background loop used to await both channels with FIRST_COMPLETED and cancel
the loser on every iteration. Under load the busy channel always won, so the
quiet one was starved, and a recv() cancelled mid-flight dropped whatever it had
already taken off the wire. Each channel now owns a long-lived reader.

These use fake sockets so the behaviour is deterministic — no network.
"""
import asyncio

import pytest

from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.utils.websocket_manager import WebSocketManager


@pytest.fixture
def config():
    return PolymarketConfig(
        POLYGON_PRIVATE_KEY="0" * 64,
        POLYGON_ADDRESS="0x" + "0" * 40,
        POLYMARKET_CHAIN_ID=137,
    )


class FakeSocket:
    """Yields queued messages, then blocks like an idle socket would."""

    def __init__(self, messages):
        self._messages = list(messages)
        self.close_code = None
        self.delivered = 0

    async def recv(self):
        if self._messages:
            self.delivered += 1
            return self._messages.pop(0)
        # Idle: never resolves, so the reader parks here instead of spinning.
        await asyncio.Event().wait()

    async def close(self):
        self.close_code = 1000


async def drain(manager, timeout=1.5):
    """Run the background loop briefly, then stop it."""
    await manager.start_background_task()
    try:
        await asyncio.wait_for(asyncio.shield(_settle(manager)), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        manager.should_run = False
        if manager.background_task:
            manager.background_task.cancel()
            await asyncio.gather(manager.background_task, return_exceptions=True)


async def _settle(manager):
    """Wait until both fake sockets have handed over everything they had."""
    while True:
        clob_done = not manager.clob_ws._messages
        realtime_done = not manager.realtime_ws._messages
        if clob_done and realtime_done:
            # Give the handlers a beat to finish processing the last message.
            await asyncio.sleep(0.05)
            return
        await asyncio.sleep(0.01)


class TestBothChannelsAreRead:
    @pytest.mark.asyncio
    async def test_quiet_channel_is_not_starved_by_a_busy_one(self, config):
        """The regression: a chatty CLOB feed must not block the realtime feed."""
        manager = WebSocketManager(config=config)

        # 50 messages on one side, 1 on the other.
        manager.clob_ws = FakeSocket(['{"type":"price_change","asset_id":"a","price":"0.5"}'] * 50)
        manager.realtime_ws = FakeSocket(['{"type":"trades","asset_id":"b"}'])
        manager.clob_connected = True
        manager.realtime_connected = True

        await drain(manager)

        assert manager.clob_ws.delivered == 50, "busy channel should drain"
        assert manager.realtime_ws.delivered == 1, (
            "quiet channel was starved by the busy one"
        )

    @pytest.mark.asyncio
    async def test_every_queued_message_is_consumed(self, config):
        """No message is lost to a cancelled recv()."""
        manager = WebSocketManager(config=config)

        manager.clob_ws = FakeSocket(['{"type":"price_change","asset_id":"a","price":"0.5"}'] * 20)
        manager.realtime_ws = FakeSocket(['{"type":"trades","asset_id":"b"}'] * 20)
        manager.clob_connected = True
        manager.realtime_connected = True

        await drain(manager)

        assert manager.clob_ws.delivered == 20
        assert manager.realtime_ws.delivered == 20
        assert manager.total_events_received == 40


class TestReaderLifecycle:
    @pytest.mark.asyncio
    async def test_readers_stop_when_the_manager_stops(self, config):
        manager = WebSocketManager(config=config)
        manager.clob_ws = FakeSocket([])
        manager.realtime_ws = FakeSocket([])
        manager.clob_connected = True
        manager.realtime_connected = True

        await manager.start_background_task()
        await asyncio.sleep(0.2)

        manager.should_run = False
        manager.background_task.cancel()
        await asyncio.gather(manager.background_task, return_exceptions=True)

        # No reader task may outlive the loop.
        leaked = [
            t for t in asyncio.all_tasks()
            if not t.done() and "_read_channel" in repr(t)
        ]
        assert leaked == [], f"reader tasks leaked: {leaked}"

    @pytest.mark.asyncio
    async def test_closed_socket_does_not_spin(self, config):
        """A reader on a closed socket must exit, not busy-loop."""
        manager = WebSocketManager(config=config)

        closed = FakeSocket([])
        closed.close_code = 1000  # already closed

        calls = 0

        async def receive_one():
            nonlocal calls
            calls += 1

        await asyncio.wait_for(
            manager._read_channel(receive_one, lambda: False), timeout=1.0
        )
        assert calls == 0, "reader ran against a closed socket"
