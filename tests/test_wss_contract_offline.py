"""Contract suite for the REAL CLOB WebSocket market-channel shapes.

Findings proven live first-hand (curator preflight 2026-09-17,
wss://ws-subscriptions-clob.polymarket.com/ws/market, token
111061902544814266207267295505639408607400625795891618462682726460921782993748):

1. The real stream wraps the initial book in a JSON ARRAY (a list with one
   book message); subsequent price_change events arrive as plain dicts.
   The old receive path called ``handle_message`` on the raw list, whose
   ``message.get`` raised AttributeError and KILLED the receive loop.
2. Real messages carry ``event_type`` (NOT ``type``/``event``). Before the
   fix, handle_message treated every real message as "Message without event
   type" and dropped it silently (total_events_received never incremented;
   the realtime feed was dead end-to-end).
3. The orderbook event_type on the wire is ``book``; the enum only had
   ``agg_orderbook``, so the real type fell through to the generic handler.
4. Orderbook levels are DICTS (``{"price": "0.46", "size": "8190"}``) --
   the parser indexed them as ``[price, size]`` pairs (TypeError).
5. Timestamps are millisecond-epoch STRINGS ("1789688342096") -- the
   parser called datetime.fromisoformat on them (ValueError).
6. price_change events carry a ``price_changes`` LIST of per-asset entries
   ({asset_id, price, size, side, hash, best_bid, best_ask}) -- the parser
   read top-level asset_id/price, which are absent on the real stream.

This suite pins the REAL wire contract end-to-end and is additive-safe:
the legacy shapes ("type"/"event" keys, pair levels, ISO timestamps,
top-level price_change fields) keep working -- pinned by
tests/test_websocket_messages.py (T-0043) and
tests/test_ws_message_error_paths_offline.py (T-0239). Malformed
non-digit timestamps keep raising into the handler catch (error-path
pins preserved).

Hermeticity: the offline tests use in-memory fixtures and a FakeSocket
(no network). The live test is marked ``integration`` and is deselected by
the offline suite run (contributing selection in CONTRIBUTING.md).
"""

import asyncio
import json
from datetime import datetime, timezone

import pytest

from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.utils.websocket_manager import (
    ChannelType,
    EventType,
    WebSocketManager,
)

websockets = pytest.importorskip("websockets")

TOKEN_ID = (
    "111061902544814266207267295505639408607400625795891618462682726460921782993748"
)
CONDITION_ID = "0xdf9bf27ee5757c55b44b8b9826ddc9ec3a8809aa3278634c45edbb7fc8f1a3e3"
MS_TS = "1789688342096"
# 1789688342096 ms since epoch, UTC-naive (same instant, no local offset).
EXPECTED_DT = datetime.fromtimestamp(1789688342096 / 1000.0, tz=timezone.utc).replace(
    tzinfo=None
)

# Real-shaped book message (captured live 2026-09-17; levels abbreviated).
# The REAL wire order is worst-first: bids ASCENDING (best bid last), asks
# DESCENDING (best ask last) -- same ordering as the REST /book (proven live).
REAL_BOOK = {
    "market": CONDITION_ID,
    "asset_id": TOKEN_ID,
    "timestamp": MS_TS,
    "hash": "43b50ffb5406ef8a6644b8ab9e6921fa76c1fd77",
    "bids": [
        {"price": "0.01", "size": "2288995.71"},
        {"price": "0.02", "size": "44884.39"},
        {"price": "0.52", "size": "1200"},
    ],
    "asks": [
        {"price": "0.99", "size": "500"},
        {"price": "0.53", "size": "800"},
    ],
    "event_type": "book",
    "tick_size": "0.01",
    "last_trade_price": "0.52",
}

# Real-shaped price_change message (captured live 2026-09-17).
REAL_PRICE_CHANGE = {
    "event_type": "price_change",
    "market": CONDITION_ID,
    "timestamp": MS_TS,
    "price_changes": [
        {
            "asset_id": TOKEN_ID,
            "price": "0.46",
            "size": "8190",
            "side": "BUY",
            "hash": "8fce57c26fafcd8a6e1e083ce7982ccaf18b4811",
            "best_bid": "0.49",
            "best_ask": "0.5",
        }
    ],
}


@pytest.fixture
def config():
    return PolymarketConfig(
        POLYGON_PRIVATE_KEY="0" * 63 + "1",
        POLYGON_ADDRESS="0x" + "0" * 40,
        POLYMARKET_CHAIN_ID=137,
    )


def make_manager(config):
    notifications = []
    logs = []

    async def notify(payload):
        notifications.append(payload)

    async def log(message):
        logs.append(message)

    manager = WebSocketManager(
        config=config, notification_callback=notify, log_callback=log
    )
    return manager, notifications, logs


def add_sub(manager, event_type, *, market_ids=None, token_ids=None, callback_type="notification"):
    from polymarket_mcp.utils.websocket_manager import Subscription

    sub = Subscription(
        id=f"sub-{len(manager.subscriptions) + 1}",
        type=event_type,
        channel=ChannelType.CLOB_MARKET,
        market_ids=market_ids,
        token_ids=token_ids,
        callback_type=callback_type,
        created_at=datetime.now(),
        events_received=0,
    )
    manager.subscriptions[sub.id] = sub
    if token_ids:
        for token_id in token_ids:
            manager.token_subscriptions[token_id].add(sub.id)
    if market_ids:
        for market_id in market_ids:
            manager.market_subscriptions[market_id].add(sub.id)
    return sub


class FakeSocket:
    """Yields queued raw JSON strings, then blocks like an idle socket."""

    def __init__(self, messages):
        self._messages = list(messages)
        self.delivered = 0

    async def recv(self):
        if self._messages:
            self.delivered += 1
            return self._messages.pop(0)
        await asyncio.Event().wait()

    async def close(self):
        pass


async def drain(manager, timeout=1.5):
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
    while True:
        clob_done = not manager.clob_ws._messages
        realtime_done = not manager.realtime_ws._messages
        if clob_done and realtime_done:
            await asyncio.sleep(0.05)
            return
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_real_book_array_fans_out_to_orderbook_handler(config):
    """The initial book arrives as a JSON ARRAY and must fan out per element.

    Before the fix the raw list hit handle_message's message.get ->
    AttributeError -> the receive loop's outer except -> `raise` (loop dead).
    """
    manager, notifications, logs = make_manager(config)
    sub = add_sub(manager, EventType.AGG_ORDERBOOK, token_ids=[TOKEN_ID])
    manager.clob_ws = FakeSocket([json.dumps([REAL_BOOK])])
    manager.realtime_ws = FakeSocket([])
    manager.clob_connected = True
    manager.realtime_connected = True

    await drain(manager)

    assert manager.clob_ws.delivered == 1
    assert manager.total_events_received == 1
    assert sub.events_received == 1
    assert len(notifications) == 1
    n = notifications[0]
    assert n["type"] == "orderbook_update"
    assert n["asset_id"] == TOKEN_ID
    # The wire sends worst-first (bids ascending, asks descending); the
    # handler must report the BEST levels (same normalization as
    # client.get_orderbook, T-0211).
    assert n["best_bid"] == 0.52
    assert n["best_ask"] == 0.53
    assert n["bid_depth"] == 3
    assert n["ask_depth"] == 2
    assert n["timestamp"] == EXPECTED_DT.isoformat()


@pytest.mark.asyncio
async def test_real_book_dict_levels_and_ms_timestamp(config):
    """Direct handle_message with the real book dict: dict levels + ms epoch."""
    manager, notifications, logs = make_manager(config)
    sub = add_sub(manager, EventType.AGG_ORDERBOOK, token_ids=[TOKEN_ID])

    await manager.handle_message("clob", dict(REAL_BOOK))

    assert manager.total_events_received == 1
    assert sub.events_received == 1
    n = notifications[0]
    assert n["best_bid"] == 0.52
    assert n["best_ask"] == 0.53
    assert n["timestamp"] == EXPECTED_DT.isoformat()
    # events_by_type uses the REAL wire type, not the enum alias.
    assert dict(manager.events_by_type) == {"book": 1}


@pytest.mark.asyncio
async def test_real_price_change_entry_parsed(config):
    """Real price_change carries a price_changes LIST of per-asset entries."""
    manager, notifications, logs = make_manager(config)
    sub = add_sub(manager, EventType.PRICE_CHANGE, token_ids=[TOKEN_ID])

    await manager.handle_message("clob", dict(REAL_PRICE_CHANGE))

    assert manager.total_events_received == 1
    assert sub.events_received == 1
    n = notifications[0]
    assert n["type"] == "price_change"
    assert n["asset_id"] == TOKEN_ID
    assert n["price"] == 0.46
    assert n["market"] == CONDITION_ID
    assert n["timestamp"] == EXPECTED_DT.isoformat()
    assert dict(manager.events_by_type) == {"price_change": 1}


@pytest.mark.asyncio
async def test_real_price_change_multiple_entries_notify_each(config):
    """One message, N entries -> N notifications (per-asset granularity)."""
    manager, notifications, logs = make_manager(config)
    other = add_sub(manager, EventType.PRICE_CHANGE, token_ids=["tok-other"])
    fed = add_sub(manager, EventType.PRICE_CHANGE, token_ids=[TOKEN_ID])

    msg = dict(REAL_PRICE_CHANGE)
    msg["price_changes"] = REAL_PRICE_CHANGE["price_changes"] + [
        {"asset_id": "tok-other", "price": "0.31", "size": "5", "side": "SELL"}
    ]
    await manager.handle_message("clob", msg)

    assert manager.total_events_received == 1
    assert fed.events_received == 1
    assert other.events_received == 1
    assert [n["asset_id"] for n in notifications] == [TOKEN_ID, "tok-other"]
    assert [n["price"] for n in notifications] == [0.46, 0.31]


@pytest.mark.asyncio
async def test_real_price_change_empty_changes_is_counted_not_notified(config):
    """An event_type-only message is counted but routes nowhere (no error)."""
    manager, notifications, logs = make_manager(config)
    add_sub(manager, EventType.PRICE_CHANGE, token_ids=[TOKEN_ID])

    await manager.handle_message(
        "clob",
        {"event_type": "price_change", "market": CONDITION_ID, "timestamp": MS_TS,
         "price_changes": []},
    )

    assert manager.total_events_received == 1
    assert notifications == []


@pytest.mark.asyncio
async def test_malformed_iso_timestamp_keeps_error_path(config):
    """Non-digit, non-ISO timestamps still raise into the handler catch.

    Compat with tests/test_ws_message_error_paths_offline.py: the handlers'
    fromisoformat error path is pinned; the ms-epoch support must NOT
    swallow unrelated malformed values.
    """
    manager, notifications, logs = make_manager(config)
    add_sub(manager, EventType.AGG_ORDERBOOK, token_ids=[TOKEN_ID])

    bad = dict(REAL_BOOK)
    bad["timestamp"] = "not-a-date"
    await manager.handle_message("clob", bad)

    assert manager.total_events_received == 1  # counted before routing
    assert notifications == []


@pytest.mark.asyncio
async def test_legacy_agg_orderbook_still_routes(config):
    """Compat: the legacy agg_orderbook shape (pair levels, ISO ts) works."""
    manager, notifications, logs = make_manager(config)
    sub = add_sub(manager, EventType.AGG_ORDERBOOK, token_ids=[TOKEN_ID])

    await manager.handle_message(
        "clob",
        {
            "type": "agg_orderbook",
            "asset_id": TOKEN_ID,
            "timestamp": "2026-09-15T12:00:00",
            "bids": [["0.40", "10"]],
            "asks": [["0.60", "20"]],
        },
    )

    assert sub.events_received == 1
    assert notifications[0]["best_bid"] == 0.40
    assert notifications[0]["best_ask"] == 0.60


@pytest.mark.asyncio
async def test_realtime_channel_list_envelope_fans_out(config):
    """The realtime connection's reader handles array envelopes the same way."""
    manager, notifications, logs = make_manager(config)
    sub = add_sub(manager, EventType.AGG_ORDERBOOK, token_ids=[TOKEN_ID])
    manager.clob_ws = FakeSocket([])
    manager.realtime_ws = FakeSocket([json.dumps([REAL_BOOK])])
    manager.clob_connected = True
    manager.realtime_connected = True

    await drain(manager)

    assert manager.realtime_ws.delivered == 1
    assert manager.total_events_received == 1
    assert sub.events_received == 1
    assert len(notifications) == 1


# ---------------------------------------------------------------------------
# Live contract (integration; deselected by the offline suite run)
# ---------------------------------------------------------------------------
def _skip_on_wss_outage(exc, label):
    """Network guard for the WSS surface: websockets.WebSocketException
    (InvalidHandshake/InvalidStatus/ConnectionClosed...), OS-level socket
    errors and timeouts are infra/outage: SKIP with reason. A live-contract
    violation (no book message in the window) keeps FAILING via pytest.fail
    - the guard must NOT swallow it."""
    if isinstance(
        exc,
        (websockets.exceptions.WebSocketException, OSError, asyncio.TimeoutError),
    ):
        pytest.skip(f"{label}: WSS transport outage ({type(exc).__name__}: {exc})")
    raise


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_book_message_shape():
    """Prove the REAL wire shape once: array-wrapped book with dict levels.

    Requires network. Subscribing to a market channel yields the initial
    book immediately, so this is stable; the price_change shape is pinned
    offline above via the live-captured fixture (REAL_PRICE_CHANGE).
    """
    url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    try:
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps({"assets_ids": [TOKEN_ID], "type": "market"}))
            for _ in range(5):
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
                data = json.loads(raw)
                items = data if isinstance(data, list) else [data]
                book = next((d for d in items if d.get("event_type") == "book"), None)
                if book is not None:
                    assert isinstance(book["bids"][0], dict)
                    assert "price" in book["bids"][0] and "size" in book["bids"][0]
                    assert isinstance(book["timestamp"], str)
                    assert book["timestamp"].isdigit()
                    return
    except (
        websockets.exceptions.WebSocketException,
        OSError,
        asyncio.TimeoutError,
    ) as exc:
        _skip_on_wss_outage(exc, "live WSS book probe")
    pytest.fail("no book message observed in the live window")


# --- Transport-guard meta-tests (offline, deterministic) --------------------


async def test_meta_wss_connect_refused_skips(monkeypatch):
    """An OS-level refusal at connect makes the live probe SKIP."""
    def boom(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(websockets, "connect", boom)
    with pytest.raises(pytest.skip.Exception):
        await test_live_book_message_shape()


async def test_meta_wss_handshake_error_skips(monkeypatch):
    """A WebSocketException at handshake makes the live probe SKIP."""
    def boom(*args, **kwargs):
        raise websockets.exceptions.WebSocketException("handshake failed")

    monkeypatch.setattr(websockets, "connect", boom)
    with pytest.raises(pytest.skip.Exception):
        await test_live_book_message_shape()


async def test_meta_wss_recv_timeout_skips(monkeypatch):
    """A stalled socket (recv timeout) makes the live probe SKIP."""
    class FakeWs:
        async def send(self, payload):
            pass

        async def recv(self):
            raise asyncio.TimeoutError()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    def fake_connect(*args, **kwargs):
        return FakeWs()

    monkeypatch.setattr(websockets, "connect", fake_connect)
    with pytest.raises(pytest.skip.Exception):
        await test_live_book_message_shape()


async def test_meta_wss_no_book_still_fails(monkeypatch):
    """GREEN pre and post: the deliberate pytest.fail path (no book message
    in the window) must NEVER be swallowed by the transport guard."""
    class FakeWs:
        async def send(self, payload):
            pass

        async def recv(self):
            return json.dumps({"event_type": "other"})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(websockets, "connect", lambda *a, **k: FakeWs())
    with pytest.raises(pytest.fail.Exception):
        await test_live_book_message_shape()
