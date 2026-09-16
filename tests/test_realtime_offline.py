"""
Offline regression suite for the realtime TOOLS layer (polymarket_mcp.tools.realtime).

Turf premise: this slice covers the TOOL layer that CONSUMES the WebSocketManager.
The manager layer itself is owned by sibling suites (tests/test_websocket_messages.py
= T-0043 routing+reconnect; farm/T-0051 connection layer; farm/T-0052 supervision).
The real WebSocketManager is NEVER instantiated here — the manager is replaced by a
structural fake (L-0121) whose signatures mirror the real ones (websocket_manager.py):
zero sockets, zero network, zero real sleep (L-0014/L-0118).

Pinned signatures (sources of truth = observed code @ farm/T-0053 base 9e675dab;
contract line-ranges drifted, semantic descriptions match — L-0090/L-0101):

- realtime.py:22        module global `websocket_manager` (contract cited :24).
- realtime.py:25-36     set_websocket_manager writes the global (+ logger.info :36).
- realtime.py:218-261   handle_tool_call: no-manager guard :229-233 returns the exact
                        literal "Error: WebSocket manager not initialized. Real-time
                        features unavailable."; 7-route dispatch :236-249; unknown tool
                        -> f"Error: Unknown tool '{name}'" :250-254; catch-all except
                        -> f"Error: {str(e)}" :256-261.
- realtime.py:264-306   _subscribe_market_prices: args :274-275, empty market_ids guard
                        :277-281 ("Error: market_ids required"), subscribe :283-289 with
                        event_type=EventType.PRICE_CHANGE and
                        channel=ChannelType.CLOB_MARKET (NO token_ids/depth forwarded),
                        success text :291-300, inner except :302-306.
- realtime.py:309-353   _subscribe_orderbook_updates: args :319-321 (depth default 10),
                        empty token_ids guard :323-327, subscribe :329-335 with
                        event_type=EventType.AGG_ORDERBOOK (NO market_ids/depth
                        forwarded), depth echoed in text :342, inner except :349-353.
- realtime.py:356-402   _subscribe_user_orders: args :366-367, subscribe :369-375 with
                        event_type=EventType.ORDER and channel=ChannelType.CLOB_USER,
                        scope text :377 ("all markets" vs "{n} specific markets"),
                        RuntimeError branch :391-397 ("Authentication required: ..." +
                        POLYMARKET_API_KEY/POLYMARKET_PASSPHRASE), generic except
                        :398-402.
- realtime.py:405-451   _subscribe_user_trades: mirror with EventType.TRADE,
                        RuntimeError branch :440-446, generic except :447-451.
- realtime.py:454-497   _subscribe_market_resolution: args :464-465, empty guard
                        :467-471, subscribe :473-479 with
                        event_type=EventType.MARKET_RESOLVED and
                        channel=ChannelType.CLOB_MARKET, inner except :493-497.
- realtime.py:500-569   _get_realtime_status: get_status() :511, clob status :514-516
                        ("CONNECTED & AUTHENTICATED" / "CONNECTED (no auth)" /
                        "DISCONNECTED"), realtime status :517, subscriptions section
                        :520-532 (id[:8] + "...", channel, events, created, last_event
                        only when truthy; empty -> "No active subscriptions"),
                        statistics :535-547 (events_by_type lists ONLY counts > 0),
                        combined text :550-561, except :565-569.
- realtime.py:572-610   _unsubscribe_realtime: arg :582, empty guard :584-588, call
                        :591, success / not-found texts :593-604, except :606-610.

Fake manager pinned against the REAL manager signatures (websocket_manager.py):
- subscribe (async, :380-387): event_type, channel, market_ids=None, token_ids=None,
  callback_type="notification" -> str. The fake declares NO extra kwargs — a future
  tool fix that starts forwarding extras (e.g. depth) fails with TypeError at the
  call site (structural pin, L-0121; consumer-producer contract: the fix updates
  stub+test in the SAME slice, L-0073). The auth guard mirrors the real gate
  (:405-406): channel == ChannelType.CLOB_USER and not authenticated raises
  RuntimeError("CLOB authentication required for user subscriptions").
- unsubscribe (async, :470) -> bool (False when the id is unknown, :473-474).
- get_status (:937-985) -> dict in EXACTLY the structure the tool reads (the fake
  requires a configured payload — calling it without one raises AssertionError,
  fail-loud, P-0031).

Manager injection: monkeypatch.setattr(realtime, "websocket_manager", fake) per test
(automatic restore); the set_websocket_manager test writes the global directly with
monkeypatch guarding the restore. The global is NEVER left dirty across tests.

KNOWN BUG (registered in the report, deliberately NOT pinned — anti-fix per the
T-0053 contract input 4): server.py:287-288 calls realtime.handle_tool(name,
arguments, websocket_manager, server) but realtime.py:218 defines
handle_tool_call(name, arguments) — name AND arity diverge, so the 7 realtime tools
are unreachable via MCP dispatch even with the manager initialized. Additionally
server.py keeps its OWN module global websocket_manager (server.py:47) and never
calls realtime.set_websocket_manager (registration gap). Re-proved offline for this
base; probe output recorded in the report. This suite pins only the TOOL layer
(realtime.handle_tool_call with the global IT owns).

Hermeticity: no network, no real sleeps; fakes fail loud (P-0031). Verified via
env -i run + delta grep by network surfaces + runtime socket guard (P-0029).
"""
from typing import Any, Dict, List, Optional

import polymarket_mcp.tools.realtime as realtime
from polymarket_mcp.utils.websocket_manager import ChannelType, EventType

AUTH_ERROR = "CLOB authentication required for user subscriptions"


def _make_status(
    *,
    clob_connected: bool = True,
    clob_authenticated: bool = True,
    realtime_connected: bool = True,
    total: int = 0,
    active: Optional[List[Dict[str, Any]]] = None,
    total_events: int = 0,
    events_by_type: Optional[Dict[str, int]] = None,
    connection_errors: int = 0,
    reconnect_count: int = 0,
    last_reconnect: Optional[str] = None,
    background_running: bool = True,
) -> Dict[str, Any]:
    """Synthetic get_status() payload in the EXACT structure the tool reads.

    Mirrors websocket_manager.py:937-985 field-by-field (including the fields the
    tool does not read yet, so a future fix reading them does not KeyError).
    """
    return {
        "connections": {
            "clob": {
                "connected": clob_connected,
                "authenticated": clob_authenticated,
                "url": "wss://fake.clob.local/ws/market",
            },
            "realtime": {
                "connected": realtime_connected,
                "url": "wss://fake.data.local/stream",
            },
        },
        "subscriptions": {
            "total": total,
            "by_type": {},
            "active": list(active) if active is not None else [],
        },
        "statistics": {
            "total_events": total_events,
            "events_by_type": dict(events_by_type) if events_by_type else {},
            "connection_errors": connection_errors,
            "reconnect_count": reconnect_count,
            "last_reconnect": last_reconnect,
        },
        "background_task": {
            "running": background_running,
            "task_exists": background_running,
        },
    }


def _active_pair() -> List[Dict[str, Any]]:
    """Two active subscriptions: one with last_event filled, one without."""
    return [
        {
            "id": "aaaaaaaa-1111-2222-3333-444444444444",
            "type": "price_change",
            "channel": "market",
            "events_received": 42,
            "created_at": "2026-01-01T00:00:00+00:00",
            "last_event": "price 0.55 for 0xabc",
        },
        {
            "id": "bbbbbbbb-2222-3333-4444-555555555555",
            "type": "agg_orderbook",
            "channel": "market",
            "events_received": 0,
            "created_at": "2026-01-01T00:00:05+00:00",
            "last_event": None,
        },
    ]


class _FakeWebSocketManager:
    """Structural stand-in for WebSocketManager (L-0121), fail-loud (P-0031).

    - subscribe/unsubscribe/get_status mirror the REAL signatures; any attribute
      NOT declared below raises AssertionError (no silent fallback, P-0031).
    - subscribe records EVERY attempt (kwargs as passed by the tool) and only
      records the id in created_subscription_ids on success — the auth guard
      (mirroring websocket_manager.py:405-406) raises before any id exists, so
      "rejection before registration" is pinned mechanically.
    - No `depth` parameter exists on purpose: the orderbook tool must NOT forward
      depth to the manager; a fix that starts doing so fails with TypeError here.
    """

    def __init__(
        self,
        *,
        authenticated: bool = True,
        status: Optional[Dict[str, Any]] = None,
        subscribe_error: Optional[BaseException] = None,
        unsubscribe_error: Optional[BaseException] = None,
        status_error: Optional[BaseException] = None,
        unsubscribe_result: bool = True,
    ) -> None:
        self.authenticated = authenticated
        self._status = status
        self._subscribe_error = subscribe_error
        self._unsubscribe_error = unsubscribe_error
        self._status_error = status_error
        self._unsubscribe_result = unsubscribe_result
        self.subscribe_attempts: List[Dict[str, Any]] = []
        self.created_subscription_ids: List[str] = []
        self.unsubscribe_calls: List[str] = []
        self.status_reads = 0
        self._next_id = 0

    def __getattr__(self, name: str):
        raise AssertionError(f"Unexpected endpoint access on fake manager: {name}")

    async def subscribe(
        self,
        event_type: EventType,
        channel: ChannelType,
        market_ids: Optional[List[str]] = None,
        token_ids: Optional[List[str]] = None,
        callback_type: str = "notification",
    ) -> str:
        self.subscribe_attempts.append(
            {
                "event_type": event_type,
                "channel": channel,
                "market_ids": market_ids,
                "token_ids": token_ids,
                "callback_type": callback_type,
            }
        )
        if channel == ChannelType.CLOB_USER and not self.authenticated:
            raise RuntimeError(AUTH_ERROR)
        if self._subscribe_error is not None:
            raise self._subscribe_error
        self._next_id += 1
        subscription_id = f"sub-{self._next_id}"
        self.created_subscription_ids.append(subscription_id)
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        self.unsubscribe_calls.append(subscription_id)
        if self._unsubscribe_error is not None:
            raise self._unsubscribe_error
        return self._unsubscribe_result

    def get_status(self) -> Dict[str, Any]:
        self.status_reads += 1
        if self._status_error is not None:
            raise self._status_error
        if self._status is None:
            raise AssertionError("get_status called without a configured payload")
        return self._status


def _text(results) -> str:
    assert len(results) == 1, f"expected exactly 1 TextContent, got {len(results)}"
    assert results[0].type == "text"
    return results[0].text


async def test_no_manager_returns_unavailable_error(monkeypatch):
    """No manager -> the exact literal from realtime.py:229-233; dispatch skipped."""
    monkeypatch.setattr(realtime, "websocket_manager", None)
    assert realtime.websocket_manager is None
    results = await realtime.handle_tool_call("get_realtime_status", {})
    assert _text(results) == (
        "Error: WebSocket manager not initialized. Real-time features unavailable."
    )


async def test_subscribe_market_prices_requires_market_ids(monkeypatch):
    """Empty/absent market_ids -> guard text :277-281; the manager is never called."""
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    for arguments in ({}, {"market_ids": []}):
        results = await realtime.handle_tool_call("subscribe_market_prices", arguments)
        assert _text(results) == "Error: market_ids required"
    assert fake.subscribe_attempts == []
    assert fake.created_subscription_ids == []


async def test_subscribe_market_prices_pins_event_type_and_channel(monkeypatch):
    """Success path pins PRICE_CHANGE/CLOB_MARKET kwargs and the success text.

    Also pins (L-0121 style): the tool forwards NO token_ids (recorded value is
    None) and NO depth (the fake signature has no depth -> forwarding it would
    raise TypeError at the call).
    """
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call(
        "subscribe_market_prices", {"market_ids": ["0xabc", "0xdef"]}
    )
    text = _text(results)
    assert len(fake.subscribe_attempts) == 1
    call = fake.subscribe_attempts[0]
    assert call["event_type"] is EventType.PRICE_CHANGE
    assert call["channel"] is ChannelType.CLOB_MARKET
    assert call["market_ids"] == ["0xabc", "0xdef"]
    assert call["token_ids"] is None
    assert call["callback_type"] == "notification"
    assert fake.created_subscription_ids == ["sub-1"]
    assert "Price change subscription created" in text
    assert "Subscription ID: sub-1" in text
    assert "Markets: 2" in text
    assert "Callback: notification" in text
    assert "Use unsubscribe_realtime with ID 'sub-1' to stop." in text


async def test_subscribe_orderbook_requires_token_ids(monkeypatch):
    """Empty/absent token_ids -> guard text :323-327; the manager is never called."""
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    for arguments in ({}, {"token_ids": []}):
        results = await realtime.handle_tool_call(
            "subscribe_orderbook_updates", arguments
        )
        assert _text(results) == "Error: token_ids required"
    assert fake.subscribe_attempts == []
    assert fake.created_subscription_ids == []


async def test_subscribe_orderbook_pins_token_ids_and_event_type(monkeypatch):
    """Success path pins AGG_ORDERBOOK kwargs, the depth echo and the success text.

    Structural pin: the fake declares NO depth kwarg (mirrors the real manager,
    websocket_manager.py:380-387) — if a future fix starts forwarding depth to
    subscribe, this suite fails with TypeError at the call (L-0121).
    """
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call(
        "subscribe_orderbook_updates",
        {"token_ids": ["tok-1", "tok-2"], "depth": 5},
    )
    text = _text(results)
    assert len(fake.subscribe_attempts) == 1
    call = fake.subscribe_attempts[0]
    assert call["event_type"] is EventType.AGG_ORDERBOOK
    assert call["channel"] is ChannelType.CLOB_MARKET
    assert call["token_ids"] == ["tok-1", "tok-2"]
    assert call["market_ids"] is None
    assert call["callback_type"] == "notification"
    assert fake.created_subscription_ids == ["sub-1"]
    assert "Orderbook subscription created" in text
    assert "Subscription ID: sub-1" in text
    assert "Tokens: 2" in text
    assert "Depth: 5 levels" in text
    assert "Callback: notification" in text


async def test_subscribe_user_orders_auth_error_mentions_credentials(monkeypatch):
    """Auth gate -> RuntimeError branch :391-397; no subscription is created."""
    fake = _FakeWebSocketManager(authenticated=False)
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call(
        "subscribe_user_orders", {"market_ids": ["m-1"]}
    )
    text = _text(results)
    assert "Authentication required" in text
    assert AUTH_ERROR in text
    assert "POLYMARKET_API_KEY" in text
    assert "POLYMARKET_PASSPHRASE" in text
    assert fake.created_subscription_ids == []
    assert len(fake.subscribe_attempts) == 1
    assert fake.subscribe_attempts[0]["event_type"] is EventType.ORDER
    assert fake.subscribe_attempts[0]["channel"] is ChannelType.CLOB_USER


async def test_subscribe_user_orders_scope_filter_all_vs_specific(monkeypatch):
    """Scope text pins the conditional at realtime.py:377 (None vs list)."""
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)

    all_markets = await realtime.handle_tool_call("subscribe_user_orders", {})
    text_all = _text(all_markets)
    assert "User order subscription created" in text_all
    assert "Scope: all markets" in text_all
    assert fake.subscribe_attempts[0]["market_ids"] is None

    specific = await realtime.handle_tool_call(
        "subscribe_user_orders", {"market_ids": ["m-1", "m-2", "m-3"]}
    )
    text_specific = _text(specific)
    assert "Scope: 3 specific markets" in text_specific
    assert fake.subscribe_attempts[1]["market_ids"] == ["m-1", "m-2", "m-3"]
    assert fake.created_subscription_ids == ["sub-1", "sub-2"]


async def test_subscribe_user_trades_auth_error_mentions_credentials(monkeypatch):
    """Auth gate -> RuntimeError branch :440-446; TRADE/CLOB_USER observed."""
    fake = _FakeWebSocketManager(authenticated=False)
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call("subscribe_user_trades", {})
    text = _text(results)
    assert "Authentication required" in text
    assert AUTH_ERROR in text
    assert "POLYMARKET_API_KEY" in text
    assert "POLYMARKET_PASSPHRASE" in text
    assert fake.created_subscription_ids == []
    assert len(fake.subscribe_attempts) == 1
    assert fake.subscribe_attempts[0]["event_type"] is EventType.TRADE
    assert fake.subscribe_attempts[0]["channel"] is ChannelType.CLOB_USER


async def test_subscribe_market_resolution_requires_market_ids(monkeypatch):
    """Empty/absent market_ids -> guard text :467-471; the manager is never called."""
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    for arguments in ({}, {"market_ids": []}):
        results = await realtime.handle_tool_call(
            "subscribe_market_resolution", arguments
        )
        assert _text(results) == "Error: market_ids required"
    assert fake.subscribe_attempts == []
    assert fake.created_subscription_ids == []


async def test_subscribe_market_resolution_pins_event_type(monkeypatch):
    """Success path pins MARKET_RESOLVED/CLOB_MARKET kwargs and the success text."""
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call(
        "subscribe_market_resolution", {"market_ids": ["0xm-1"]}
    )
    text = _text(results)
    assert len(fake.subscribe_attempts) == 1
    call = fake.subscribe_attempts[0]
    assert call["event_type"] is EventType.MARKET_RESOLVED
    assert call["channel"] is ChannelType.CLOB_MARKET
    assert call["market_ids"] == ["0xm-1"]
    assert call["token_ids"] is None
    assert call["callback_type"] == "notification"
    assert fake.created_subscription_ids == ["sub-1"]
    assert "Market resolution subscription created" in text
    assert "Subscription ID: sub-1" in text
    assert "Markets: 1" in text


async def test_unknown_tool_returns_error_text(monkeypatch):
    """Unknown name -> else branch :250-254; the manager is never touched."""
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call("not_a_real_tool", {"x": 1})
    assert _text(results) == "Error: Unknown tool 'not_a_real_tool'"
    assert fake.subscribe_attempts == []
    assert fake.unsubscribe_calls == []
    assert fake.status_reads == 0


async def test_handler_exception_becomes_error_content(monkeypatch):
    """Catch-all :256-261 becomes "Error: {str(e)}" TextContent.

    Trigger: non-dict arguments reach handlers' `arguments.get` BEFORE the inner
    try blocks (e.g. realtime.py:274), so the exception propagates to the
    handle_tool_call catch-all — distinguishable from the inner-handler templates
    ("Error subscribing to ...") which never appear here.
    """
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call("subscribe_market_prices", None)
    text = _text(results)
    assert text.startswith("Error: ")
    assert "NoneType" in text
    assert "Error subscribing to market prices" not in text
    assert fake.subscribe_attempts == []
    assert fake.created_subscription_ids == []


async def test_unsubscribe_requires_subscription_id(monkeypatch):
    """Absent/empty id -> guard text :584-588; the manager is never called."""
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    for arguments in ({}, {"subscription_id": ""}):
        results = await realtime.handle_tool_call("unsubscribe_realtime", arguments)
        assert _text(results) == "Error: subscription_id required"
    assert fake.unsubscribe_calls == []


async def test_unsubscribe_success_and_not_found_paths(monkeypatch):
    """unsubscribe True -> success text :593-598; False -> not-found :599-604."""
    ok = _FakeWebSocketManager(unsubscribe_result=True)
    monkeypatch.setattr(realtime, "websocket_manager", ok)
    results = await realtime.handle_tool_call(
        "unsubscribe_realtime", {"subscription_id": "sub-9"}
    )
    assert _text(results) == (
        "Successfully unsubscribed from: sub-9\n\n"
        "You will no longer receive updates for this subscription."
    )
    assert ok.unsubscribe_calls == ["sub-9"]

    missing = _FakeWebSocketManager(unsubscribe_result=False)
    monkeypatch.setattr(realtime, "websocket_manager", missing)
    results = await realtime.handle_tool_call(
        "unsubscribe_realtime", {"subscription_id": "sub-404"}
    )
    assert _text(results) == (
        "Subscription not found: sub-404\n\n"
        "Use get_realtime_status to see active subscriptions."
    )
    assert missing.unsubscribe_calls == ["sub-404"]


async def test_get_realtime_status_formats_connections_and_subscriptions(monkeypatch):
    """Full status rendering over a synthetic payload (websocket_manager.py:937-985
    structure): clob authenticated, realtime connected, one subscription with
    last_event + one without, positive and zero event counts, background RUNNING.
    """
    fake = _FakeWebSocketManager(
        status=_make_status(
            total=2,
            active=_active_pair(),
            total_events=5,
            events_by_type={"price_change": 5, "trade": 0},
            connection_errors=1,
            reconnect_count=2,
        )
    )
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call("get_realtime_status", {})
    text = _text(results)

    assert "Real-time WebSocket Status" in text
    assert "==========================" in text
    assert "• CLOB: CONNECTED & AUTHENTICATED" in text
    assert "• Real-time Data: CONNECTED" in text
    assert "• Total Active: 2" in text
    assert "• aaaaaaaa... (price_change)" in text
    assert "  Channel: market" in text
    assert "  Events: 42" in text
    assert "  Created: 2026-01-01T00:00:00+00:00" in text
    assert "• bbbbbbbb... (agg_orderbook)" in text
    assert "  Events: 0" in text
    assert text.count("Last Event:") == 1
    assert "  Last Event: price 0.55 for 0xabc" in text
    assert "• Total Events: 5" in text
    assert "• Connection Errors: 1" in text
    assert "• Reconnects: 2" in text
    assert "Background Task: RUNNING" in text
    assert fake.status_reads == 1


async def test_get_realtime_status_lists_only_positive_event_counts(monkeypatch):
    """events_by_type with a zero count: only counts > 0 are listed (:546)."""
    fake = _FakeWebSocketManager(
        status=_make_status(
            total=2,
            active=_active_pair(),
            total_events=5,
            events_by_type={"price_change": 5, "trade": 0},
        )
    )
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call("get_realtime_status", {})
    text = _text(results)
    assert "• Events by Type:" in text
    assert "  - price_change: 5" in text
    assert "trade" not in text


def test_set_websocket_manager_registers_global(monkeypatch):
    """set_websocket_manager writes the module global (realtime.py:34-35)."""
    monkeypatch.setattr(realtime, "websocket_manager", None)
    fake = _FakeWebSocketManager()
    realtime.set_websocket_manager(fake)
    assert realtime.websocket_manager is fake
    replacement = _FakeWebSocketManager()
    realtime.set_websocket_manager(replacement)
    assert realtime.websocket_manager is replacement


# --- Complementary coverage (L-0109: mandatory names do not forbid extras) ---


async def test_get_realtime_status_without_subscriptions_says_none(monkeypatch):
    """Empty active list -> "No active subscriptions" (else branch :531-532)."""
    fake = _FakeWebSocketManager(status=_make_status(total=0))
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call("get_realtime_status", {})
    text = _text(results)
    assert "No active subscriptions" in text
    assert "• Total Active: 0" in text


async def test_get_realtime_status_clob_connected_without_auth(monkeypatch):
    """Authenticated=False + connected=True -> "CONNECTED (no auth)" (:515)."""
    fake = _FakeWebSocketManager(
        status=_make_status(clob_connected=True, clob_authenticated=False)
    )
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call("get_realtime_status", {})
    assert "• CLOB: CONNECTED (no auth)" in _text(results)


async def test_get_realtime_status_disconnected_states(monkeypatch):
    """Both connections down -> "DISCONNECTED" for CLOB (:516) and realtime (:517)."""
    fake = _FakeWebSocketManager(
        status=_make_status(clob_connected=False, clob_authenticated=False,
                            realtime_connected=False)
    )
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call("get_realtime_status", {})
    text = _text(results)
    assert "• CLOB: DISCONNECTED" in text
    assert "• Real-time Data: DISCONNECTED" in text


async def test_get_realtime_status_background_task_stopped(monkeypatch):
    """running=False -> "Background Task: STOPPED" (:560)."""
    fake = _FakeWebSocketManager(status=_make_status(background_running=False))
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call("get_realtime_status", {})
    assert "Background Task: STOPPED" in _text(results)


async def test_get_realtime_status_omits_events_by_type_when_empty(monkeypatch):
    """Empty events_by_type -> the section is omitted entirely (:543-544)."""
    fake = _FakeWebSocketManager(status=_make_status(total_events=0))
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call("get_realtime_status", {})
    text = _text(results)
    assert "Events by Type" not in text
    assert "• Total Events: 0" in text


async def test_get_realtime_status_reports_manager_errors(monkeypatch):
    """get_status raising -> inner except :565-569 ("Error getting status: ...")."""
    fake = _FakeWebSocketManager(status_error=RuntimeError("boom"))
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call("get_realtime_status", {})
    assert _text(results) == "Error getting status: boom"


async def test_subscribe_market_prices_reports_manager_errors(monkeypatch):
    """subscribe raising -> inner except :302-306 with the prices-specific prefix."""
    fake = _FakeWebSocketManager(subscribe_error=RuntimeError("ws down"))
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call(
        "subscribe_market_prices", {"market_ids": ["0xabc"]}
    )
    assert _text(results) == "Error subscribing to market prices: ws down"
    assert fake.created_subscription_ids == []


async def test_subscribe_orderbook_reports_manager_errors(monkeypatch):
    """subscribe raising -> inner except :349-353 (orderbook prefix)."""
    fake = _FakeWebSocketManager(subscribe_error=RuntimeError("ws down"))
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call(
        "subscribe_orderbook_updates", {"token_ids": ["tok-1"]}
    )
    assert _text(results) == "Error subscribing to orderbook updates: ws down"
    assert fake.created_subscription_ids == []


async def test_subscribe_user_orders_reports_generic_manager_errors(monkeypatch):
    """Non-RuntimeError -> generic except :398-402 (distinct from auth branch)."""
    fake = _FakeWebSocketManager(subscribe_error=ValueError("boom"))
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call("subscribe_user_orders", {})
    assert _text(results) == "Error subscribing to user orders: boom"
    assert fake.created_subscription_ids == []


async def test_subscribe_user_trades_success_and_scope(monkeypatch):
    """Trades success text for both scope arms (:426-438) + TRADE/CLOB_USER pin."""
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)

    all_markets = await realtime.handle_tool_call("subscribe_user_trades", {})
    text_all = _text(all_markets)
    assert "User trade subscription created" in text_all
    assert "Scope: all markets" in text_all
    assert "when your orders are matched and trades execute" in text_all
    assert fake.subscribe_attempts[0]["event_type"] is EventType.TRADE

    specific = await realtime.handle_tool_call(
        "subscribe_user_trades", {"market_ids": ["m-1"]}
    )
    assert "Scope: 1 specific markets" in _text(specific)
    assert fake.subscribe_attempts[1]["market_ids"] == ["m-1"]
    assert fake.created_subscription_ids == ["sub-1", "sub-2"]


async def test_subscribe_user_trades_reports_generic_manager_errors(monkeypatch):
    """Non-RuntimeError -> generic except :447-451 (trades prefix)."""
    fake = _FakeWebSocketManager(subscribe_error=ValueError("boom"))
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call("subscribe_user_trades", {})
    assert _text(results) == "Error subscribing to user trades: boom"
    assert fake.created_subscription_ids == []


async def test_subscribe_market_resolution_reports_manager_errors(monkeypatch):
    """subscribe raising -> inner except :493-497 (resolution prefix)."""
    fake = _FakeWebSocketManager(subscribe_error=RuntimeError("ws down"))
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call(
        "subscribe_market_resolution", {"market_ids": ["0xm-1"]}
    )
    assert _text(results) == "Error subscribing to market resolution: ws down"
    assert fake.created_subscription_ids == []


async def test_unsubscribe_reports_manager_errors(monkeypatch):
    """unsubscribe raising -> except :606-610 ("Error unsubscribing: ...")."""
    fake = _FakeWebSocketManager(unsubscribe_error=RuntimeError("boom"))
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call(
        "unsubscribe_realtime", {"subscription_id": "sub-1"}
    )
    assert _text(results) == "Error unsubscribing: boom"


async def test_user_orders_empty_market_ids_filter_treated_as_all_markets(monkeypatch):
    """market_ids=[] is falsy -> "all markets" (observed leniency, realtime.py:377).

    Pin of the OBSERVED behavior (L-0020/L-0025): an empty list is passed through
    to the manager unchanged ([]) while the scope text says "all markets".
    """
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call(
        "subscribe_user_orders", {"market_ids": []}
    )
    assert "Scope: all markets" in _text(results)
    assert fake.subscribe_attempts[0]["market_ids"] == []


async def test_callback_type_log_forwarded_and_echoed(monkeypatch):
    """callback_type='log' is forwarded to the manager and echoed in the text."""
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call(
        "subscribe_market_prices",
        {"market_ids": ["0xabc"], "callback_type": "log"},
    )
    text = _text(results)
    assert fake.subscribe_attempts[0]["callback_type"] == "log"
    assert "Callback: log" in text
    assert "You will receive logs when prices change" in text


async def test_orderbook_depth_default_echoed_as_10(monkeypatch):
    """Absent depth -> the tool's own default 10 is echoed (realtime.py:320-321)."""
    fake = _FakeWebSocketManager()
    monkeypatch.setattr(realtime, "websocket_manager", fake)
    results = await realtime.handle_tool_call(
        "subscribe_orderbook_updates", {"token_ids": ["tok-1"]}
    )
    assert "Depth: 10 levels" in _text(results)
