"""
Offline regression suite for WebSocketManager message routing + reconnect.

Covers the routing funnel ``handle_message`` (per-event payload emission,
market/token subscription filters, malformed messages ignored without raising)
and the reconnect exponential backoff (fake clock, cap 60s), plus
``_resubscribe_all`` tolerating a failed subscription. Zero network and zero
real sleep:

- ``connect``/``disconnect``/``_resubscribe_all`` are replaced by AsyncMock on
  the manager object (the real ones would dial Polymarket); ``subscribe()`` is
  deliberately bypassed — it requires a connected socket (RuntimeError from
  ``_send_subscription``), and the routing under test does not depend on it.
- ``asyncio.sleep`` is monkeypatched with a recording fake (websocket_manager
  imports the global ``asyncio`` module at src/polymarket_mcp/utils/
  websocket_manager.py:10, so patching the module attribute is observed by
  ``reconnect`` at :348).

Sources of truth — asserts pin the OBSERVED code, not an idealized spec
(L-0020/L-0090): src/polymarket_mcp/utils/websocket_manager.py @ farm/T-0043
base (9c3fef6):

- handle_message          :524-558 — stats (:539-540) precede routing: a
  malformed payload with a known event type still bumps ``total_events_received``
  and ``events_by_type`` while the target subscription stays untouched; a
  message without ``type``/``event`` returns early (:533-536) and is not
  counted. The outer try/except (:557-558) logs errors — it never raises.
- _handle_price_change    :560-597 — notification payload and log callback
  (``Price change: <market or asset_id> -> <price>``).
- _handle_orderbook_update:599-636 — best levels + depth; None/0 on empty book.
- _handle_order/trade     :638-676 / :678-714 — floats, not Decimal/str.
- _handle_market_resolution:716-744.
- _find_matching_subscriptions:750-776 — the market filter is SKIPPED when the
  event carries no market (``if sub.market_ids and market_id``). Pinned as
  observed leniency (achado, not a desire) — see the dedicated test docstring.
- reconnect               :333-368 — delay = min(1 * 2**attempts, 60) with
  INITIAL_RECONNECT_DELAY=1/MAX_RECONNECT_DELAY=60/RECONNECT_MULTIPLIER=2
  (:153-155); success resets attempts and stamps ``last_reconnect_time``;
  failure increments attempts, updates neither stamp nor resubscribes, never
  raises.
- _resubscribe_all        :370-378 — per-subscription try/except: continues
  after a failed subscription.

Sibling coverage (not duplicated here): tests/test_websocket_readers.py
(offline — per-channel readers/lifecycle of the background loop) and
tests/test_websocket.py (INTEGRATION, real API — out of the release gate).
"""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.utils.websocket_manager import (
    ChannelType,
    EventType,
    Subscription,
    WebSocketManager,
)

TS = "2026-09-15T12:00:00"


@pytest.fixture
def config():
    return PolymarketConfig(
        POLYGON_PRIVATE_KEY="0" * 63 + "1",
        POLYGON_ADDRESS="0x" + "0" * 40,
        POLYMARKET_CHAIN_ID=137,
        _env_file=None,
    )


def make_manager(config):
    """Offline manager whose async callbacks append to observable lists."""
    notifications = []
    logs = []

    async def notify(payload):
        notifications.append(payload)

    async def log(message):
        logs.append(message)

    manager = WebSocketManager(config=config, notification_callback=notify, log_callback=log)
    return manager, notifications, logs


def add_sub(
    manager,
    event_type,
    *,
    channel=ChannelType.CLOB_MARKET,
    market_ids=None,
    token_ids=None,
    callback_type="notification",
    sub_id=None,
):
    """Insert a Subscription directly into manager.subscriptions (no socket)."""
    sub = Subscription(
        id=sub_id or f"sub-{len(manager.subscriptions) + 1}",
        type=event_type,
        channel=channel,
        market_ids=market_ids,
        token_ids=token_ids,
        callback_type=callback_type,
        created_at=datetime.now(),
        events_received=0,
    )
    manager.subscriptions[sub.id] = sub
    return sub


async def test_price_change_event_dispatches_to_subscribers(config):
    """Exact payload per subscriber type, per-sub counters, global stats.

    The ``event`` key alias routes exactly like ``type`` (handle_message:533).
    """
    manager, notifications, logs = make_manager(config)
    a = add_sub(manager, EventType.PRICE_CHANGE, market_ids=["mkt-1"])
    b = add_sub(manager, EventType.PRICE_CHANGE, market_ids=["mkt-2"])
    c = add_sub(manager, EventType.PRICE_CHANGE, market_ids=["mkt-1"], callback_type="log")
    d = add_sub(manager, EventType.AGG_ORDERBOOK, token_ids=["tok-1"])

    await manager.handle_message(
        "clob",
        {"type": "price_change", "asset_id": "tok-1", "price": "0.55", "timestamp": TS, "market": "mkt-1"},
    )

    assert notifications == [
        {
            "type": "price_change",
            "subscription_id": a.id,
            "asset_id": "tok-1",
            "price": 0.55,
            "market": "mkt-1",
            "timestamp": TS,
        }
    ]
    assert logs == ["Price change: mkt-1 -> 0.55"]
    assert (a.events_received, b.events_received, c.events_received, d.events_received) == (1, 0, 1, 0)
    assert a.last_event_at is not None
    assert b.last_event_at is None
    assert manager.total_events_received == 1
    assert dict(manager.events_by_type) == {"price_change": 1}

    # Alias: "event" instead of "type" routes the same way (observed: 2nd
    # notification, total 2). Decimal("0.60") keeps its trailing zero in the
    # log message — pinned as observed.
    await manager.handle_message(
        "clob",
        {"event": "price_change", "asset_id": "tok-1", "price": "0.60", "timestamp": TS, "market": "mkt-1"},
    )

    assert len(notifications) == 2
    assert notifications[1] == {
        "type": "price_change",
        "subscription_id": a.id,
        "asset_id": "tok-1",
        "price": 0.6,
        "market": "mkt-1",
        "timestamp": TS,
    }
    assert logs == ["Price change: mkt-1 -> 0.55", "Price change: mkt-1 -> 0.60"]
    assert (a.events_received, b.events_received, c.events_received, d.events_received) == (2, 0, 2, 0)
    assert manager.total_events_received == 2
    assert dict(manager.events_by_type) == {"price_change": 2}


async def test_price_change_without_market_reaches_market_filtered_subscribers(config):
    """ACHADO (observado, não desejo): a price_change payload without "market".

    The market filter is skipped when the event carries no market
    (websocket_manager.py:765 — ``if sub.market_ids and market_id``), so EVERY
    price_change subscription is notified, including ones filtered for other
    markets. The log callback falls back to the asset_id (:593).
    """
    manager, notifications, logs = make_manager(config)
    a = add_sub(manager, EventType.PRICE_CHANGE, market_ids=["mkt-1"])
    b = add_sub(manager, EventType.PRICE_CHANGE, market_ids=["mkt-2"])
    c = add_sub(manager, EventType.PRICE_CHANGE, market_ids=["mkt-1"], callback_type="log")

    await manager.handle_message(
        "clob",
        {"type": "price_change", "asset_id": "tok-9", "price": "0.55", "timestamp": TS},
    )

    assert [n["subscription_id"] for n in notifications] == [a.id, b.id]
    assert notifications[0] == {
        "type": "price_change",
        "subscription_id": a.id,
        "asset_id": "tok-9",
        "price": 0.55,
        "market": None,
        "timestamp": TS,
    }
    assert notifications[1]["market"] is None
    # c also matches (filter skipped); its log message falls back to asset_id.
    assert logs == ["Price change: tok-9 -> 0.55"]
    assert (a.events_received, b.events_received, c.events_received) == (1, 1, 1)
    assert manager.total_events_received == 1


async def test_orderbook_update_reports_best_levels_and_depth(config):
    """Exact payload for a token-filtered subscription; empty book → None/0.

    A token NOT subscribed receives nothing (token filter, :770-772) — but the
    global stats still count the event (stats precede routing, :539-540).
    """
    manager, notifications, _ = make_manager(config)
    d = add_sub(manager, EventType.AGG_ORDERBOOK, token_ids=["tok-1"])

    await manager.handle_message(
        "clob",
        {
            "type": "agg_orderbook",
            "asset_id": "tok-1",
            "bids": [["0.50", "100"], ["0.49", "200"]],
            "asks": [["0.51", "150"]],
            "timestamp": TS,
        },
    )
    assert notifications == [
        {
            "type": "orderbook_update",
            "subscription_id": d.id,
            "asset_id": "tok-1",
            "best_bid": 0.5,
            "best_ask": 0.51,
            "bid_depth": 2,
            "ask_depth": 1,
            "timestamp": TS,
        }
    ]
    assert d.events_received == 1
    assert d.last_event_at is not None

    # Empty book: bests are None, depths 0 — still dispatched.
    await manager.handle_message(
        "clob",
        {"type": "agg_orderbook", "asset_id": "tok-1", "bids": [], "asks": [], "timestamp": TS},
    )
    assert notifications[1] == {
        "type": "orderbook_update",
        "subscription_id": d.id,
        "asset_id": "tok-1",
        "best_bid": None,
        "best_ask": None,
        "bid_depth": 0,
        "ask_depth": 0,
        "timestamp": TS,
    }

    # Unsubscribed token: no dispatch (stats still bump).
    await manager.handle_message(
        "clob",
        {
            "type": "agg_orderbook",
            "asset_id": "tok-other",
            "bids": [["0.50", "1"]],
            "asks": [["0.51", "1"]],
            "timestamp": TS,
        },
    )
    assert len(notifications) == 2
    assert d.events_received == 2
    assert manager.total_events_received == 3
    assert dict(manager.events_by_type) == {"agg_orderbook": 3}


async def test_order_and_trade_updates_dispatch_with_numeric_fields(config):
    """order_update/trade_update payloads carry floats (not Decimal/str)."""
    manager, notifications, _ = make_manager(config)
    order_sub = add_sub(manager, EventType.ORDER, channel=ChannelType.CLOB_USER, market_ids=["mkt-1"])
    trade_sub = add_sub(manager, EventType.TRADE, market_ids=["mkt-1"])

    await manager.handle_message(
        "clob",
        {
            "type": "order",
            "order_id": "o-1",
            "status": "MATCHED",
            "filled_size": "10",
            "remaining_size": "5",
            "price": "0.4",
            "side": "BUY",
            "timestamp": TS,
            "market_id": "mkt-1",
        },
    )
    assert notifications[0] == {
        "type": "order_update",
        "subscription_id": order_sub.id,
        "order_id": "o-1",
        "status": "MATCHED",
        "filled_size": 10.0,
        "remaining_size": 5.0,
        "price": 0.4,
        "side": "BUY",
        "market_id": "mkt-1",
        "timestamp": TS,
    }
    assert isinstance(notifications[0]["filled_size"], float)
    assert isinstance(notifications[0]["remaining_size"], float)
    assert isinstance(notifications[0]["price"], float)

    await manager.handle_message(
        "clob",
        {
            "type": "trade",
            "trade_id": "t-1",
            "order_id": "o-1",
            "market_id": "mkt-1",
            "price": "0.4",
            "size": "10",
            "side": "SELL",
            "timestamp": TS,
        },
    )
    assert notifications[1] == {
        "type": "trade_update",
        "subscription_id": trade_sub.id,
        "trade_id": "t-1",
        "order_id": "o-1",
        "market_id": "mkt-1",
        "price": 0.4,
        "size": 10.0,
        "side": "SELL",
        "timestamp": TS,
    }
    assert isinstance(notifications[1]["price"], float)
    assert isinstance(notifications[1]["size"], float)
    assert (order_sub.events_received, trade_sub.events_received) == (1, 1)
    assert manager.total_events_received == 2


async def test_market_resolved_event_dispatches(config):
    """Exact market_resolved payload to a matching subscription."""
    manager, notifications, _ = make_manager(config)
    sub = add_sub(manager, EventType.MARKET_RESOLVED, market_ids=["mkt-1"])

    await manager.handle_message(
        "clob",
        {"type": "market_resolved", "market_id": "mkt-1", "outcome": "Yes", "timestamp": TS},
    )

    assert notifications == [
        {
            "type": "market_resolved",
            "subscription_id": sub.id,
            "market_id": "mkt-1",
            "outcome": "Yes",
            "timestamp": TS,
        }
    ]
    assert sub.events_received == 1
    assert sub.last_event_at is not None
    assert manager.total_events_received == 1
    assert dict(manager.events_by_type) == {"market_resolved": 1}


async def test_malformed_message_is_ignored(config):
    """Malformed payloads never raise; the two-sided counter behaviour is pinned.

    A message WITHOUT type/event is dropped before stats (:533-536) — counters
    unchanged. A malformed payload WITH a known event type bumps the global
    stats (they precede routing, :539-540) while the subscription is untouched
    (the handler fails before matching). A payload without "timestamp" is NOT
    malformed: it dispatches with datetime.now() as default (:566, :610, ...).
    """
    manager, notifications, _ = make_manager(config)
    price_sub = add_sub(manager, EventType.PRICE_CHANGE, market_ids=["mkt-1"])
    book_sub = add_sub(manager, EventType.AGG_ORDERBOOK, token_ids=["tok-1"])

    # No type/event: not counted, not dispatched.
    await manager.handle_message("clob", {"asset_id": "tok-1", "price": "0.55", "timestamp": TS})
    assert notifications == []
    assert manager.total_events_received == 0
    assert dict(manager.events_by_type) == {}
    assert (price_sub.events_received, book_sub.events_received) == (0, 0)

    # Non-numeric price: counted, not dispatched.
    await manager.handle_message(
        "clob",
        {"type": "price_change", "asset_id": "tok-1", "price": "abc", "timestamp": TS, "market": "mkt-1"},
    )
    assert manager.total_events_received == 1
    assert dict(manager.events_by_type) == {"price_change": 1}
    assert (price_sub.events_received, book_sub.events_received) == (0, 0)
    assert notifications == []

    # Invalid timestamp: counted, not dispatched.
    await manager.handle_message(
        "clob",
        {"type": "price_change", "asset_id": "tok-1", "price": "0.55", "timestamp": "not-a-date", "market": "mkt-1"},
    )
    assert manager.total_events_received == 2
    assert price_sub.events_received == 0

    # Malformed bids level: counted, not dispatched.
    await manager.handle_message(
        "clob",
        {"type": "agg_orderbook", "asset_id": "tok-1", "bids": [["x"]], "asks": [], "timestamp": TS},
    )
    assert manager.total_events_received == 3
    assert book_sub.events_received == 0
    assert notifications == []

    # Missing timestamp: dispatches normally with the datetime.now() default.
    await manager.handle_message(
        "clob",
        {"type": "price_change", "asset_id": "tok-1", "price": "0.55", "market": "mkt-1"},
    )
    assert manager.total_events_received == 4
    assert len(notifications) == 1
    payload = notifications[0]
    assert payload["subscription_id"] == price_sub.id
    assert payload["price"] == 0.55
    assert payload["market"] == "mkt-1"
    parsed = datetime.fromisoformat(payload["timestamp"])
    assert parsed.isoformat() == payload["timestamp"]
    assert payload["timestamp"] != TS


async def test_unknown_event_type_is_counted_but_not_dispatched(config):
    """Unknown event type: counted in stats, no dispatch, no raise.

    The generic fallback only logs (websocket_manager.py:746-748).
    """
    manager, notifications, _ = make_manager(config)
    add_sub(manager, EventType.PRICE_CHANGE, market_ids=["mkt-1"])

    await manager.handle_message("realtime", {"type": "weird_event", "foo": 1})

    assert notifications == []
    assert manager.total_events_received == 1
    assert dict(manager.events_by_type) == {"weird_event": 1}


async def test_reconnect_backoff_caps(config, monkeypatch):
    """Backoff delay = min(1 * 2**attempts, 60); success resets attempts.

    Fake clock: ``asyncio.sleep`` is monkeypatched with a recorder (no real
    sleep; websocket_manager uses the global asyncio module — :348). Success
    path resets attempts, stamps ``last_reconnect_time``, and awaits disconnect
    → connect → _resubscribe_all once per call.
    """
    manager, _, _ = make_manager(config)
    delays = []

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    manager.connect = AsyncMock()
    manager.disconnect = AsyncMock()
    manager._resubscribe_all = AsyncMock()

    for attempts, expected_delay in [(0, 1), (1, 2), (3, 8), (5, 32), (6, 60), (10, 60)]:
        manager.reconnect_attempts = attempts
        count_before = manager.reconnect_count
        await manager.reconnect()
        assert delays[-1] == expected_delay  # cap kicks in at attempts >= 6
        assert manager.reconnect_attempts == 0
        assert manager.last_reconnect_time > 0
        assert manager.reconnect_count == count_before + 1

    assert delays == [1, 2, 8, 32, 60, 60]
    assert manager.reconnect_count == 6
    assert manager.connect.await_count == 6
    assert manager.disconnect.await_count == 6
    assert manager._resubscribe_all.await_count == 6


async def test_reconnect_failure_increments_attempts_without_raising(config, monkeypatch):
    """Connect failure: delay grows per attempt, nothing raises, no resubscribe.

    The failure path (:365-367) increments attempts and does NOT stamp
    ``last_reconnect_time`` (only success does, :361-362) — on a fresh manager
    that stamp stays 0 across failures.
    """
    manager, _, _ = make_manager(config)
    delays = []

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    manager.disconnect = AsyncMock()
    manager.connect = AsyncMock(side_effect=RuntimeError("boom"))
    manager._resubscribe_all = AsyncMock()

    manager.reconnect_attempts = 2
    count_before = manager.reconnect_count
    await manager.reconnect()

    assert delays == [4]  # min(1 * 2**2, 60)
    assert manager.reconnect_attempts == 3
    assert manager.reconnect_count == count_before + 1
    assert manager.last_reconnect_time == 0
    assert manager.connect.await_count == 1
    assert manager.disconnect.await_count == 1
    assert manager._resubscribe_all.await_count == 0

    await manager.reconnect()

    assert delays == [4, 8]  # backoff grows with each failure
    assert manager.reconnect_attempts == 4
    assert manager._resubscribe_all.await_count == 0


async def test_resubscribe_all_continues_after_a_failed_subscription(config):
    """_resubscribe_all keeps iterating after a failing subscription (:374-378)."""
    manager, _, _ = make_manager(config)
    add_sub(manager, EventType.PRICE_CHANGE, market_ids=["mkt-1"], sub_id="ok")
    add_sub(manager, EventType.PRICE_CHANGE, market_ids=["mkt-2"], sub_id="bad")
    calls = []

    async def fake_send(sub):
        calls.append(sub.id)
        if sub.id == "bad":
            raise RuntimeError("send failed")

    manager._send_subscription = fake_send

    await manager._resubscribe_all()

    assert calls == ["ok", "bad"]
