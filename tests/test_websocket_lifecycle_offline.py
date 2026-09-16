"""
Offline regression suite for the WebSocketManager CONNECTION LAYER (T-0051).

Regions under test (src/polymarket_mcp/utils/websocket_manager.py @ main
9e675da; numbers are the state at emission — L-0002/L-0008; this suite only
ADDS files):

- connect             :210-231  — orchestrates both sockets; failure bumps
                                  ``connection_errors`` and PROPAGATES.
- _connect_clob       :233-254  — dials CLOB_WS_URL with ping_interval=20 /
                                  ping_timeout=10, authenticates when
                                  ``has_api_credentials()``, warns otherwise.
- _connect_realtime   :256-271  — dials REALTIME_WS_URL with the same pings.
- _authenticate_clob  :273-310  — auth JSON pinned; response/timeout/error
                                  paths set ``authenticated`` and NEVER raise.
- disconnect          :312-331  — closes open sockets, resets state flags.
- subscribe           :380-439  — storage + registries + subscribe message.
- _send_subscription  :441-468  — channel dispatch + connection guards.
- unsubscribe         :470-503  — triple removal; send failure swallowed.
- _send_unsubscription :505-522 — no-op when the socket is not open.
- get_status          :937-985  — full dict shape (pinned as observed).
- ws_is_open          :27-41    — close_code/legacy-closed/None probes.

Disjointness (dedupe by reading, P-0009): tests/test_websocket_messages.py
(T-0043) owns handle_message/reconnect/_resubscribe_all; tests/
test_websocket_readers.py owns the reader loop (supervision slice start/stop/
_background_loop/_receive_* is T-0052's turf — not duplicated here);
tests/test_websocket.py is integration (excluded from the offline gate).
Divergence declared (L-0025): the contract draft located the subscribe auth
guard at ":395-397 already covered offline" — observed: the guard is
:405-406 and the pre-suite coverage report shows 405-439 entirely missing;
this file covers it.

Coupling declarations (consumer↔producer, L-0073/L-0121) — a fix that changes
any of these must update the fake + asserts in the SAME slice:
- ConnectStub pins the exact ``websockets.connect`` kwargs
  {"ping_interval": 20, "ping_timeout": 10} (websocket_manager.py:237-241,
  :260-264): any kwarg drift fails at the seam with AssertionError.
- The auth JSON shape (:280-289), the subscribe message (:455-464) and the
  unsubscribe message (:516-520) are pinned as observed.
- The get_status dict (:944-985) is pinned including its quirks: "running"
  mirrors ``self.should_run`` (not task liveness) and "last_reconnect"
  mirrors ``last_reconnect_time`` (epoch 0 when never reconnected).
- get_status "active" list order follows subscription insertion order
  (dict ordering of ``self.subscriptions.values()``) — incidental semantics.

ACHADO pinned as OBSERVED (not the idealized spec; L-0025/L-0115 — a fix that
removes the orphan must update the tests below in the same slice):
``subscribe`` stores the Subscription AND its registry entries (:420-429)
BEFORE calling ``_send_subscription`` (:432), so a RuntimeError from the
connection guards (:447-448, :451-452) leaves an orphan subscription plus
registry entries behind. The contract draft asserted "NADA armazenado";
the code stores first — divergence declared here and in the report.

Hermeticity (P-0029, BOTH directions): zero network, zero real sleep.
``websockets.connect`` is stubbed on the module object BEFORE any call
(L-0118 — the module holds the same ``websockets`` object, so the patch is
observed at the seam); the auth ``wait_for(..., timeout=5.0)`` never waits —
the fake recv raises ``asyncio.TimeoutError`` synchronously (L-0014). Every
test builds its own manager/sockets (order-independent; no shared mutable
state). Direction 2 — hostile host env (r2, P1-01): the autouse ``clean_env``
fixture strips every ``POLYGON_*``/``POLYMARKET_*`` (plus the other
config-sourced names/prefixes of the same settings class: ``DEMO_MODE``,
``LOG_LEVEL``, ``MAX_``, ``MIN_``, ``ENABLE_``, ``REQUIRE_``, ``AUTO_``)
process env var — house pattern of tests/test_config_security.py (T-0042).
PolymarketConfig is a pydantic ``BaseSettings`` (config.py:11,17-18):
``_env_file=None`` disables only the .env file; host env vars are still read
for every field NOT passed explicitly. Before r2 the ``fallback_creds_config``
fixture omitted POLYMARKET_API_SECRET on purpose (it IS the fallback test), so
a host secret leaked into the auth message and could print a real credential
in the assertion diff. Now the host environment is NEUTRAL by construction:
configuration comes only from explicit kwargs, ``_env_file=None`` kills the
.env file, and the fixture kills env reads (the fallback then flows
deterministically from None→passphrase).
"""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime

import pytest
import websockets

from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.utils.websocket_manager import (
    ChannelType,
    EventType,
    Subscription,
    WebSocketManager,
    ws_is_open,
)

MANAGER_LOGGER = "polymarket_mcp.utils.websocket_manager"

CREATED_AT = datetime(2026, 9, 15, 12, 0, 0)

# Process env prefixes/names that feed PolymarketConfig fields; stripped by
# the autouse fixture so tests never observe the host environment (P1-01 r2,
# direction 2 of P-0029 — house pattern of tests/test_config_security.py).
_ENV_PREFIXES = (
    "POLYGON_",
    "POLYMARKET_",
    "DEMO_MODE",
    "LOG_LEVEL",
    "MAX_",
    "MIN_",
    "ENABLE_",
    "REQUIRE_",
    "AUTO_",
)


# ---------------------------------------------------------------------------
# Hermeticity — env neutralization (autouse; P1-01 r2)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip config-sourced env vars so tests never see the host environment.

    Every test (autouse) gets a host-neutral environment: pydantic
    ``BaseSettings`` still reads env vars for fields not passed explicitly
    even with ``_env_file=None`` (config.py:11,17-18), so without this
    fixture a host ``POLYMARKET_API_SECRET``/``POLYMARKET_API_KEY`` etc.
    would change results (non-hermetic) and leak real credentials into
    assertion diffs. All configs are built with explicit kwargs, so the
    delenv changes no pin; the secret fallback flows deterministically from
    None→passphrase (websocket_manager.py:283-286).
    """
    for name in list(os.environ):
        if any(name.startswith(prefix) for prefix in _ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Fakes (P-0031: fail-loud module-seam fakes, owned by this file — never
# imported from sibling suites).
# ---------------------------------------------------------------------------
class FakeSocket:
    """Fake WebSocket connection mirroring the surface the layer touches.

    ``close_code`` stays None while open and becomes numeric once closed —
    exactly what ``ws_is_open`` (:27-41) probes on the modern websockets 14+
    protocol. Fail-loud: unexpected usage raises instead of silently passing.
    """

    def __init__(self, responses=(), send_error=None, recv_error=None, closed=False):
        self.sent = []
        self.close_calls = 0
        self.close_code = None if not closed else 1000
        self.responses = list(responses)
        self.send_error = send_error
        self.recv_error = recv_error

    async def send(self, payload):
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(payload)

    async def recv(self):
        if self.recv_error is not None:
            raise self.recv_error
        if self.responses:
            return self.responses.pop(0)
        # Simulated auth wait_for timeout: raises immediately — never waits.
        raise asyncio.TimeoutError("simulated auth timeout (no real wait)")

    async def close(self):
        self.close_calls += 1
        self.close_code = 1000


class ConnectStub:
    """Fail-loud stand-in for ``websockets.connect`` (module seam, P-0031).

    Pins the exact kwargs the module passes (:237-241, :260-264); any kwarg
    drift raises AssertionError at the seam. ``fail_on`` (1-based) makes the
    Nth dial raise instead of returning a socket.
    """

    EXPECTED_KWARGS = {"ping_interval": 20, "ping_timeout": 10}

    def __init__(self, sockets=(), fail_on=None):
        self.calls = []
        self._sockets = list(sockets)
        self._fail_on = fail_on

    async def __call__(self, url, **kwargs):
        self.calls.append((url, dict(kwargs)))
        if self._fail_on is not None and len(self.calls) == self._fail_on:
            raise ConnectionError(f"dial refused: {url}")
        if kwargs != self.EXPECTED_KWARGS:
            raise AssertionError(f"unexpected connect kwargs: {kwargs!r}")
        if not self._sockets:
            raise AssertionError("stub exhausted: more dials than sockets prepared")
        return self._sockets.pop(0)


# ---------------------------------------------------------------------------
# Config + manager helpers (pure, per-test; no shared mutable state — P-0029).
# ---------------------------------------------------------------------------
def make_config(**overrides):
    """Config factory. Dummy key is VALID: the T-0030 validator rejects
    all-zero keys, so never pass "0" * 64 (house pattern)."""
    base = dict(
        POLYGON_PRIVATE_KEY="0" * 63 + "1",
        POLYGON_ADDRESS="0x" + "0" * 40,
        POLYMARKET_CHAIN_ID=137,
        _env_file=None,
    )
    base.update(overrides)
    return PolymarketConfig(**base)


def add_subscription(manager, *, sub_id, event_type, channel, market_ids=None,
                     token_ids=None, events_received=0, last_event_at=None,
                     created_at=None):
    """Insert a Subscription + registries directly (subscribe semantics)."""
    sub = Subscription(
        id=sub_id,
        type=event_type,
        channel=channel,
        market_ids=market_ids,
        token_ids=token_ids,
        created_at=created_at or CREATED_AT,
        events_received=events_received,
        last_event_at=last_event_at,
    )
    manager.subscriptions[sub.id] = sub
    if market_ids:
        for market_id in market_ids:
            manager.market_subscriptions[market_id].add(sub.id)
    if token_ids:
        for token_id in token_ids:
            manager.token_subscriptions[token_id].add(sub.id)
    return sub


@pytest.fixture
def config():
    return make_config()


@pytest.fixture
def creds_config():
    return make_config(
        POLYMARKET_API_KEY="key-123",
        POLYMARKET_API_SECRET="secret-456",
        POLYMARKET_PASSPHRASE="pass-789",
        POLYMARKET_API_KEY_NAME="keyname",
    )


@pytest.fixture
def fallback_creds_config():
    # has_api_credentials() does NOT check the secret (config.py:201-207):
    # key+passphrase+key_name are enough, and the auth message then falls
    # back to the passphrase for "secret" (websocket_manager.py:283-286).
    return make_config(
        POLYMARKET_API_KEY="key-123",
        POLYMARKET_PASSPHRASE="pass-789",
        POLYMARKET_API_KEY_NAME="keyname",
    )


# ---------------------------------------------------------------------------
# connect — orchestrates both sockets (:210-231)
# ---------------------------------------------------------------------------
async def test_connect_establishes_both_sockets_with_ping_settings(monkeypatch):
    """connect() dials CLOB then realtime with the pinned ping settings."""
    manager = WebSocketManager(config=make_config())
    clob_socket, realtime_socket = FakeSocket(), FakeSocket()
    stub = ConnectStub([clob_socket, realtime_socket])
    monkeypatch.setattr(websockets, "connect", stub)  # stub BEFORE any call (L-0118)

    await manager.connect()

    assert manager.clob_ws is clob_socket
    assert manager.realtime_ws is realtime_socket
    assert manager.clob_connected is True
    assert manager.realtime_connected is True
    assert stub.calls == [
        (WebSocketManager.CLOB_WS_URL, {"ping_interval": 20, "ping_timeout": 10}),
        (WebSocketManager.REALTIME_WS_URL, {"ping_interval": 20, "ping_timeout": 10}),
    ]
    # Endpoint constants pinned as dialled (class attributes, :148-150).
    assert manager.CLOB_WS_URL == "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    assert manager.REALTIME_WS_URL == "wss://ws-live-data.polymarket.com"
    assert manager.authenticated is False  # no creds → no auth attempted


async def test_connect_failure_increments_connection_errors_and_raises(monkeypatch):
    """CLOB dial failure: ``connection_errors`` bumps and the error PROPAGATES
    (:228-231) — the manager does not swallow it; realtime is never dialled."""
    manager = WebSocketManager(config=make_config())
    stub = ConnectStub(fail_on=1)
    monkeypatch.setattr(websockets, "connect", stub)

    with pytest.raises(ConnectionError, match="dial refused"):
        await manager.connect()

    assert manager.connection_errors == 1
    assert manager.clob_connected is False
    assert manager.realtime_connected is False
    assert len(stub.calls) == 1
    assert stub.calls[0][0] == WebSocketManager.CLOB_WS_URL


async def test_connect_realtime_failure_marks_realtime_disconnected(monkeypatch):
    """Realtime dial failure after CLOB succeeded: ``realtime_connected`` is
    reset by the except (:270), CLOB stays connected, error still propagates."""
    manager = WebSocketManager(config=make_config())
    stub = ConnectStub([FakeSocket()], fail_on=2)
    monkeypatch.setattr(websockets, "connect", stub)

    with pytest.raises(ConnectionError, match="dial refused"):
        await manager.connect()

    assert manager.connection_errors == 1
    assert manager.clob_connected is True
    assert manager.realtime_connected is False
    assert [url for url, _ in stub.calls] == [manager.CLOB_WS_URL, manager.REALTIME_WS_URL]


# ---------------------------------------------------------------------------
# _connect_clob — credentials gate (:233-254)
# ---------------------------------------------------------------------------
async def test_connect_clob_with_credentials_sends_auth_message(creds_config, monkeypatch):
    """With credentials the auth JSON is pinned exactly (:280-289)."""
    manager = WebSocketManager(config=creds_config)
    clob_socket = FakeSocket(responses=['{"type": "authenticated"}'])
    stub = ConnectStub([clob_socket])
    monkeypatch.setattr(websockets, "connect", stub)

    await manager._connect_clob()

    assert manager.clob_connected is True
    assert manager.authenticated is True
    assert json.loads(clob_socket.sent[0]) == {
        "auth": {"apiKey": "key-123", "secret": "secret-456", "passphrase": "pass-789"}
    }
    assert len(clob_socket.sent) == 1  # exactly one auth message


async def test_connect_clob_without_credentials_warns_and_skips_auth(config, monkeypatch, caplog):
    """Without credentials: warning logged, auth NEVER called, nothing sent."""
    manager = WebSocketManager(config=config)
    clob_socket = FakeSocket(responses=['{"type": "authenticated"}'])  # would answer if asked
    stub = ConnectStub([clob_socket])
    monkeypatch.setattr(websockets, "connect", stub)
    auth_calls = []

    async def spy_authenticate():
        auth_calls.append(True)

    manager._authenticate_clob = spy_authenticate

    with caplog.at_level(logging.WARNING, logger=MANAGER_LOGGER):
        await manager._connect_clob()

    assert manager.clob_connected is True
    assert manager.authenticated is False
    assert auth_calls == []          # _authenticate_clob never called
    assert clob_socket.sent == []    # nothing sent on the wire
    assert any(
        record.levelno == logging.WARNING and "No CLOB API credentials" in record.message
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# _authenticate_clob — auth chain never raises (:273-310)
# ---------------------------------------------------------------------------
async def test_auth_success_sets_authenticated_true(creds_config):
    """{"type": "authenticated"} response flips ``authenticated`` (:298-300)."""
    manager = WebSocketManager(config=creds_config)
    manager.clob_ws = FakeSocket(responses=['{"type": "authenticated"}'])

    await manager._authenticate_clob()

    assert manager.authenticated is True
    assert json.loads(manager.clob_ws.sent[0])["auth"]["apiKey"] == "key-123"


async def test_auth_unexpected_response_sets_authenticated_false(creds_config, caplog):
    """Unexpected response: ``authenticated`` reset to False, NO raise (:301-303)."""
    manager = WebSocketManager(config=creds_config)
    manager.authenticated = True  # pre-set to prove the reset
    manager.clob_ws = FakeSocket(responses=['{"type": "pong"}'])

    await manager._authenticate_clob()

    assert manager.authenticated is False
    assert any("CLOB authentication failed" in record.message for record in caplog.records)


async def test_auth_timeout_sets_authenticated_false_without_raising(creds_config, caplog):
    """Timeout path: the wait_for never waits — the fake recv raises
    asyncio.TimeoutError synchronously (L-0014); ``authenticated`` is False
    and the auth message was still sent (fire-then-wait, :291→:295)."""
    manager = WebSocketManager(config=creds_config)
    manager.authenticated = True
    manager.clob_ws = FakeSocket()

    await manager._authenticate_clob()

    assert manager.authenticated is False
    assert len(manager.clob_ws.sent) == 1
    assert any("CLOB authentication timeout" in record.message for record in caplog.records)


async def test_auth_transport_error_sets_authenticated_false_without_raising(creds_config, caplog):
    """Transport error inside wait_for: ``authenticated`` False, NO raise
    (:308-310) — the except chain never propagates."""
    manager = WebSocketManager(config=creds_config)
    manager.authenticated = True
    manager.clob_ws = FakeSocket(recv_error=ConnectionError("transport dead"))

    await manager._authenticate_clob()

    assert manager.authenticated is False
    assert any("CLOB authentication error" in record.message for record in caplog.records)


async def test_auth_secret_falls_back_to_passphrase_when_api_secret_absent(fallback_creds_config):
    """PIN of the ``or`` fallback (:283-286): without POLYMARKET_API_SECRET the
    auth "secret" field carries the passphrase; authentication still succeeds."""
    manager = WebSocketManager(config=fallback_creds_config)
    manager.clob_ws = FakeSocket(responses=['{"type": "authenticated"}'])

    await manager._authenticate_clob()

    auth = json.loads(manager.clob_ws.sent[0])["auth"]
    assert auth["apiKey"] == "key-123"
    assert auth["secret"] == "pass-789"
    assert auth["passphrase"] == "pass-789"
    assert manager.authenticated is True


# ---------------------------------------------------------------------------
# disconnect — close open sockets, reset flags (:312-331)
# ---------------------------------------------------------------------------
async def test_disconnect_closes_open_sockets_and_resets_state(config):
    manager = WebSocketManager(config=config)
    clob_socket, realtime_socket = FakeSocket(), FakeSocket()
    manager.clob_ws, manager.realtime_ws = clob_socket, realtime_socket
    manager.clob_connected = True
    manager.realtime_connected = True
    manager.authenticated = True

    await manager.disconnect()

    assert clob_socket.close_calls == 1
    assert realtime_socket.close_calls == 1
    assert clob_socket.close_code == 1000
    assert realtime_socket.close_code == 1000
    assert manager.clob_connected is False
    assert manager.authenticated is False
    assert manager.realtime_connected is False


async def test_disconnect_skips_close_for_non_open_socket(config):
    """Closed sockets (both probes: modern close_code and legacy ``.closed``)
    are NOT closed again (:319/:326) while the flags still reset (:322-329)."""
    manager = WebSocketManager(config=config)
    clob_closed = FakeSocket(closed=True)   # modern probe: close_code set
    legacy_closed = FakeSocket()
    legacy_closed.closed = True             # legacy probe: ``.closed`` attribute (:37-39)
    manager.clob_ws, manager.realtime_ws = clob_closed, legacy_closed
    manager.clob_connected = True
    manager.realtime_connected = True
    manager.authenticated = True

    await manager.disconnect()

    assert clob_closed.close_calls == 0
    assert legacy_closed.close_calls == 0
    assert manager.clob_connected is False
    assert manager.authenticated is False
    assert manager.realtime_connected is False


async def test_disconnect_tolerates_none_socket(config):
    """A None socket (never connected) is skipped by ws_is_open (:34-35)."""
    manager = WebSocketManager(config=config)
    realtime_socket = FakeSocket()
    manager.clob_ws = None
    manager.realtime_ws = realtime_socket
    manager.clob_connected = True
    manager.realtime_connected = True
    manager.authenticated = True

    await manager.disconnect()

    assert realtime_socket.close_calls == 1
    assert manager.clob_connected is False
    assert manager.realtime_connected is False


def test_ws_is_open_probes_close_code_and_legacy_closed():
    """ws_is_open semantics pinned: modern close_code, legacy .closed, None."""
    assert ws_is_open(FakeSocket()) is True            # close_code None → open (:41)
    assert ws_is_open(FakeSocket(closed=True)) is False
    legacy_open = FakeSocket()
    legacy_open.closed = False
    assert ws_is_open(legacy_open) is True             # legacy branch (:37-39)
    legacy_closed = FakeSocket()
    legacy_closed.closed = True
    assert ws_is_open(legacy_closed) is False
    assert ws_is_open(None) is False                   # None socket (:34-35)


# ---------------------------------------------------------------------------
# subscribe — storage, registries, message (:380-439)
# ---------------------------------------------------------------------------
async def test_subscribe_stores_subscription_and_sends_subscribe_message(config):
    """Happy path: UUID4 id, Subscription stored, message shape pinned."""
    manager = WebSocketManager(config=config)
    manager.clob_ws = FakeSocket()
    manager.clob_connected = True

    sub_id = await manager.subscribe(
        EventType.PRICE_CHANGE,
        ChannelType.CLOB_MARKET,
        market_ids=["mkt-1"],
        token_ids=["tok-1"],
    )

    parsed = uuid.UUID(sub_id)
    assert str(parsed) == sub_id and parsed.version == 4

    stored = manager.subscriptions[sub_id]
    assert stored.type is EventType.PRICE_CHANGE
    assert stored.channel is ChannelType.CLOB_MARKET
    assert stored.market_ids == ["mkt-1"]
    assert stored.token_ids == ["tok-1"]
    assert stored.callback_type == "notification"
    assert stored.events_received == 0

    assert json.loads(manager.clob_ws.sent[0]) == {
        "type": "subscribe",
        "channel": "market",        # ChannelType.CLOB_MARKET.value
        "event": "price_change",    # EventType.PRICE_CHANGE.value
        "markets": ["mkt-1"],
        "assets": ["tok-1"],
    }
    assert len(manager.clob_ws.sent) == 1


async def test_subscribe_index_market_and_token_registries(config):
    """Registries populated for BOTH id lists; a subscription without ids sends
    the bare message — conditional keys are ABSENT, not empty (:461-464)."""
    manager = WebSocketManager(config=config)
    manager.clob_ws = FakeSocket()
    manager.clob_connected = True

    both_id = await manager.subscribe(
        EventType.PRICE_CHANGE,
        ChannelType.CLOB_MARKET,
        market_ids=["m1", "m2"],
        token_ids=["t1"],
    )
    assert manager.market_subscriptions["m1"] == {both_id}
    assert manager.market_subscriptions["m2"] == {both_id}
    assert manager.token_subscriptions["t1"] == {both_id}

    bare_id = await manager.subscribe(EventType.PRICE_CHANGE, ChannelType.CLOB_MARKET)
    assert bare_id != both_id
    assert json.loads(manager.clob_ws.sent[1]) == {
        "type": "subscribe",
        "channel": "market",
        "event": "price_change",
    }
    assert manager.market_subscriptions["m1"] == {both_id}  # bare sub indexed nothing


async def test_subscribe_raises_when_clob_not_connected(config):
    """CLOB guard (:447-448) raises "CLOB WebSocket not connected".

    ACHADO (observado): storage precedes send, so the RuntimeError leaves the
    subscription AND its registry entry behind (orphan) — see the module
    docstring; the fix that removes the orphan updates this test in-slice.
    """
    manager = WebSocketManager(config=config)
    manager.clob_ws = None
    manager.clob_connected = False

    with pytest.raises(RuntimeError, match="CLOB WebSocket not connected"):
        await manager.subscribe(EventType.PRICE_CHANGE, ChannelType.CLOB_MARKET, market_ids=["m1"])

    orphan_id = next(iter(manager.subscriptions))
    assert manager.subscriptions[orphan_id].market_ids == ["m1"]
    assert manager.market_subscriptions["m1"] == {orphan_id}  # orphan registry (observed)


async def test_subscribe_realtime_channel_raises_when_realtime_not_connected(config):
    """Realtime guard (:451-452) raises "Real-time WebSocket not connected";
    same observed orphan semantics as the CLOB guard."""
    manager = WebSocketManager(config=config)
    manager.realtime_ws = None
    manager.realtime_connected = False

    with pytest.raises(RuntimeError, match="Real-time WebSocket not connected"):
        await manager.subscribe(EventType.CRYPTO_UPDATE, ChannelType.ACTIVITY, token_ids=["t1"])

    orphan_id = next(iter(manager.subscriptions))
    assert manager.subscriptions[orphan_id].token_ids == ["t1"]
    assert manager.token_subscriptions["t1"] == {orphan_id}  # orphan registry (observed)


async def test_subscribe_user_channel_requires_authentication(config):
    """Auth guard (:405-406) fires BEFORE storage — this path leaves NOTHING
    (subscriptions, registries and the wire all stay untouched)."""
    manager = WebSocketManager(config=config)
    manager.clob_ws = FakeSocket()
    manager.clob_connected = True  # connection is fine; the AUTH guard raises first

    with pytest.raises(RuntimeError, match="CLOB authentication required for user subscriptions"):
        await manager.subscribe(EventType.ORDER, ChannelType.CLOB_USER)

    assert manager.subscriptions == {}
    assert manager.market_subscriptions == {}
    assert manager.clob_ws.sent == []


async def test_subscribe_user_channel_sends_when_authenticated(config):
    """Authenticated user channel reaches the CLOB socket (user branch :445-448)."""
    manager = WebSocketManager(config=config)
    manager.clob_ws = FakeSocket()
    manager.clob_connected = True
    manager.authenticated = True

    sub_id = await manager.subscribe(EventType.ORDER, ChannelType.CLOB_USER, market_ids=["m1"])

    assert manager.market_subscriptions["m1"] == {sub_id}
    assert json.loads(manager.clob_ws.sent[0]) == {
        "type": "subscribe",
        "channel": "user",
        "event": "order",
        "markets": ["m1"],
    }


async def test_subscribe_realtime_channel_sends_to_realtime_socket(config):
    """ACTIVITY/CRYPTO_PRICES channels reach the realtime socket (:449-452)."""
    manager = WebSocketManager(config=config)
    manager.realtime_ws = FakeSocket()
    manager.realtime_connected = True

    sub_id = await manager.subscribe(
        EventType.CRYPTO_UPDATE, ChannelType.CRYPTO_PRICES, token_ids=["t9"]
    )

    assert manager.token_subscriptions["t9"] == {sub_id}
    assert json.loads(manager.realtime_ws.sent[0]) == {
        "type": "subscribe",
        "channel": "crypto_prices",
        "event": "update",   # EventType.CRYPTO_UPDATE.value — pinned enum string
        "assets": ["t9"],
    }


# ---------------------------------------------------------------------------
# unsubscribe — triple removal, swallowed send failure (:470-503)
# ---------------------------------------------------------------------------
async def test_unsubscribe_removes_subscription_and_registries(config):
    """Round trip: subscribe → unsubscribe → True + removal from all three
    registries; the unsubscribe message is pinned (NO markets/assets keys)."""
    manager = WebSocketManager(config=config)
    manager.clob_ws = FakeSocket()
    manager.clob_connected = True

    sub_id = await manager.subscribe(
        EventType.PRICE_CHANGE,
        ChannelType.CLOB_MARKET,
        market_ids=["m1", "m2"],
        token_ids=["t1"],
    )

    ok = await manager.unsubscribe(sub_id)

    assert ok is True
    assert sub_id not in manager.subscriptions
    # discard leaves the (defaultdict) key mapped to an EMPTY set — observed.
    assert manager.market_subscriptions["m1"] == set()
    assert manager.market_subscriptions["m2"] == set()
    assert manager.token_subscriptions["t1"] == set()
    assert json.loads(manager.clob_ws.sent[1]) == {
        "type": "unsubscribe",
        "channel": "market",
        "event": "price_change",
    }


async def test_unsubscribe_unknown_id_returns_false(config):
    """Unknown id: False, and NOTHING is sent on either socket (:480-481)."""
    manager = WebSocketManager(config=config)
    clob_socket, realtime_socket = FakeSocket(), FakeSocket()
    manager.clob_ws, manager.realtime_ws = clob_socket, realtime_socket
    manager.clob_connected = True
    manager.realtime_connected = True

    ok = await manager.unsubscribe("no-such-id")

    assert ok is False
    assert clob_socket.sent == []
    assert realtime_socket.sent == []
    assert manager.subscriptions == {}


async def test_unsubscribe_subscription_without_id_lists(config):
    """A subscription with NO market/token ids: both registry loops are
    skipped (:492-497) and the removal still returns True."""
    manager = WebSocketManager(config=config)
    add_subscription(
        manager, sub_id="bare", event_type=EventType.PRICE_CHANGE, channel=ChannelType.CLOB_MARKET
    )

    ok = await manager.unsubscribe("bare")

    assert ok is True
    assert "bare" not in manager.subscriptions
    assert manager.market_subscriptions == {}
    assert manager.token_subscriptions == {}


async def test_unsubscribe_swallows_send_failure_and_still_removes(config, caplog):
    """A failing _send_unsubscription is swallowed (:486-489) — the removal
    still happens and the call still returns True."""
    manager = WebSocketManager(config=config)
    manager.clob_ws = FakeSocket(send_error=RuntimeError("send refused"))
    add_subscription(
        manager,
        sub_id="sub-x",
        event_type=EventType.PRICE_CHANGE,
        channel=ChannelType.CLOB_MARKET,
        market_ids=["m1"],
        token_ids=["t1"],
    )

    ok = await manager.unsubscribe("sub-x")

    assert ok is True
    assert "sub-x" not in manager.subscriptions
    assert manager.market_subscriptions["m1"] == set()
    assert manager.token_subscriptions["t1"] == set()
    assert any("Failed to send unsubscribe message" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# _send_unsubscription — no-op on a non-open socket (:505-522)
# ---------------------------------------------------------------------------
async def test_send_unsubscription_no_op_when_socket_not_open(config):
    """Closed or None socket → return BEFORE any send (:513-514)."""
    manager = WebSocketManager(config=config)
    clob_closed = FakeSocket(closed=True)
    manager.clob_ws = clob_closed
    clob_sub = add_subscription(
        manager, sub_id="s", event_type=EventType.TRADE, channel=ChannelType.CLOB_MARKET
    )

    await manager._send_unsubscription(clob_sub)
    assert clob_closed.sent == []

    realtime_sub = add_subscription(
        manager, sub_id="r", event_type=EventType.CRYPTO_UPDATE, channel=ChannelType.CRYPTO_PRICES
    )
    await manager._send_unsubscription(realtime_sub)  # realtime_ws is None → no-op
    assert manager.realtime_ws is None


async def test_send_unsubscription_sends_when_socket_open(config):
    """Open sockets: the unsubscribe message is pinned per channel family."""
    manager = WebSocketManager(config=config)
    clob_socket, realtime_socket = FakeSocket(), FakeSocket()
    manager.clob_ws, manager.realtime_ws = clob_socket, realtime_socket
    clob_sub = add_subscription(
        manager, sub_id="c", event_type=EventType.ORDER, channel=ChannelType.CLOB_USER
    )
    activity_sub = add_subscription(
        manager, sub_id="a", event_type=EventType.TRADES, channel=ChannelType.ACTIVITY
    )

    await manager._send_unsubscription(clob_sub)
    await manager._send_unsubscription(activity_sub)

    assert json.loads(clob_socket.sent[0]) == {
        "type": "unsubscribe", "channel": "user", "event": "order",
    }
    assert json.loads(realtime_socket.sent[0]) == {
        "type": "unsubscribe", "channel": "activity", "event": "trades",
    }


# ---------------------------------------------------------------------------
# get_status — full dict shape (:937-985)
# ---------------------------------------------------------------------------
async def test_get_status_reports_connections_subscriptions_and_statistics(config):
    """Full dict pinned as OBSERVED, including the quirks: "running" mirrors
    ``should_run`` (not task liveness) and "last_reconnect" mirrors
    ``last_reconnect_time`` (epoch 0 when never reconnected)."""
    manager = WebSocketManager(config=config)
    manager.clob_connected = True
    manager.authenticated = True
    manager.realtime_connected = True
    priced = add_subscription(
        manager,
        sub_id="sub-1",
        event_type=EventType.PRICE_CHANGE,
        channel=ChannelType.CLOB_MARKET,
        events_received=2,
        last_event_at=datetime(2026, 9, 15, 12, 1, 30),
    )
    add_subscription(manager, sub_id="sub-2", event_type=EventType.TRADE,
                     channel=ChannelType.CLOB_USER)
    manager.total_events_received = 5
    manager.events_by_type["price_change"] = 2
    manager.events_by_type["trade"] = 1
    manager.connection_errors = 3
    manager.reconnect_count = 2

    status = manager.get_status()

    assert status["connections"]["clob"] == {
        "connected": True,
        "authenticated": True,
        "url": manager.CLOB_WS_URL,
    }
    assert status["connections"]["realtime"] == {
        "connected": True,
        "url": manager.REALTIME_WS_URL,
    }
    assert status["subscriptions"]["total"] == 2
    expected_by_type = {event_type: 0 for event_type in EventType}
    expected_by_type[EventType.PRICE_CHANGE] = 1
    expected_by_type[EventType.TRADE] = 1
    assert status["subscriptions"]["by_type"] == expected_by_type
    assert status["subscriptions"]["active"] == [
        {
            "id": priced.id,
            "type": "price_change",
            "channel": "market",
            "created_at": "2026-09-15T12:00:00",
            "events_received": 2,
            "last_event": "2026-09-15T12:01:30",
        },
        {
            "id": "sub-2",
            "type": "trade",
            "channel": "user",
            "created_at": "2026-09-15T12:00:00",
            "events_received": 0,
            "last_event": None,  # never received an event → None (:969)
        },
    ]
    assert status["statistics"] == {
        "total_events": 5,
        "events_by_type": {"price_change": 2, "trade": 1},
        "connection_errors": 3,
        "reconnect_count": 2,
        "last_reconnect": 0,  # quirk: epoch 0 when never reconnected (:979)
    }

    # Quirk pins: "running" mirrors should_run (not task presence);
    # last_reconnect mirrors last_reconnect_time.
    manager.last_reconnect_time = 1726390000
    manager.background_task = object()  # a task object exists…
    manager.should_run = False          # …but the loop is not running
    assert manager.get_status()["statistics"]["last_reconnect"] == 1726390000
    assert manager.get_status()["background_task"] == {"running": False, "task_exists": True}
    manager.should_run = True
    assert manager.get_status()["background_task"]["running"] is True
    manager.background_task = None
    assert manager.get_status()["background_task"] == {"running": True, "task_exists": False}


async def test_get_status_fresh_manager_defaults(config):
    """Zero-state shape for a fresh manager (nothing connected, nothing sent)."""
    status = WebSocketManager(config=config).get_status()

    assert status["connections"]["clob"] == {
        "connected": False,
        "authenticated": False,
        "url": WebSocketManager.CLOB_WS_URL,
    }
    assert status["connections"]["realtime"] == {
        "connected": False,
        "url": WebSocketManager.REALTIME_WS_URL,
    }
    assert status["subscriptions"] == {
        "total": 0,
        "by_type": {event_type: 0 for event_type in EventType},
        "active": [],
    }
    assert status["statistics"] == {
        "total_events": 0,
        "events_by_type": {},
        "connection_errors": 0,
        "reconnect_count": 0,
        "last_reconnect": 0,
    }
    assert status["background_task"] == {"running": False, "task_exists": False}
