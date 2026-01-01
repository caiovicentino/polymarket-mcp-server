"""Wire contract suite for the WebSocket SEND path (subscribe/unsubscribe/auth).

Pins the REAL Polymarket wire contracts (probed live 2026-09-18; REQUER-HUMANO
item 183) that ``websocket_manager.py`` violates on EVERY channel:

- CLOB market subscribe sends ``{"type": "subscribe", "channel": "market",
  "event": ..., "markets": [...], "assets": [...]}`` (:440-469) -- the CLOB
  wire ``wss://ws-subscriptions-clob.polymarket.com/ws/market`` IGNORES it
  silently (probed: 0 messages arrive). The REAL wire frame is
  ``{"assets_ids": [<token_id>...], "type": "market"}`` (probed: book events
  arrive immediately; ``assets_ids=[condition_id]`` yields an EMPTY book
  ``[]`` -- the market channel accepts ONLY token ids; ``markets=[cid]`` is
  answered with close 1008 "invalid subscription").
- CLOB market unsubscribe sends the same broken envelope (:505-522). The REAL
  wire frame is ``{"assets_ids": [...], "operation": "unsubscribe"}`` (probed:
  events STOP; ``type: "unmarket"`` does NOT stop them).
- RTDS (activity/crypto_prices) subscribe sends the same broken envelope --
  the RTDS wire ``wss://ws-live-data.polymarket.com`` ignores it (probed: no
  events). The REAL wire frame is ``{"action": "subscribe", "subscriptions":
  [{"topic": ..., "type": ...}]}`` (probed: events flow immediately).
- CLOB user auth frame ``_authenticate_clob`` (:278-330) sends ONLY
  ``{"auth": {...}}`` WITHOUT ``"type": "user"`` and then BLOCKS 5s waiting
  for an undocumented ``{"type": "authenticated"}`` ack (the docs document no
  ack; a bad frame is answered with close 1008 "authentication failed"). The
  REAL frame per docs is ``{"auth": {...}, "type": "user"}``.
- CLOB user op-frames send the broken subscribe/unsubscribe envelope. The
  REAL frames per docs are ``{"operation": "subscribe", "markets": [...]}``
  and ``{"operation": "unsubscribe", "markets": [...]}``.

Suite shape: 9 xfail(strict=True) tests pin the DESIRED send-path frames via
a local fail-loud FakeSocket (P-0031; harness pattern mirrors
test_websocket_lifecycle_offline.py). Pre-fix: 9 xfailed consumed (suite
GREEN). When the human fix lands (REQUER-HUMANO item 183), the xfails flip to
XPASS -> strict error -> the fix contract consumes them. The RECEIVE path is
farm/T-0259 turf (tests/test_wss_contract_offline.py on its branch) -- NEVER
touched here. The lifecycle suite pins the CURRENT broken frames at :544-549,
:572-576, :639-641, :658-660, :691-692 and the auth frame at :341 -- those
flips belong to the fix contract, never to this suite.

DESIGN DECISIONS DECLARED (item 183): the RTDS unsubscribe wire behavior is
UNVERIFIED (probes inconclusive: events continued after both manager-format
and action/unsubscribe frames) -- NOT pinned here. The optional
``custom_feature_enabled`` flag (docs: enables best_bid_ask/new_market/
market_resolved events) is a fix-design decision, NOT pinned (minimal frames
are pinned). An app-level PING heartbeat is OPTIONAL (probed: 75s survival
without one on the market channel; PONG answers only AFTER a subscription)
-- NOT pinned.
"""

import json
import os

import pytest

from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.utils.websocket_manager import (
    ChannelType,
    EventType,
    WebSocketManager,
)

# Process env prefixes stripped by the autouse fixture (hermeticity, P1-01
# r2 -- house pattern of tests/test_websocket_lifecycle_offline.py).
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


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip config-sourced env vars so tests never see the host environment."""
    for name in list(os.environ):
        if any(name.startswith(prefix) for prefix in _ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


def make_config(**overrides):
    """Config factory. Dummy key is VALID (all-zero keys are rejected)."""
    base = dict(
        POLYGON_PRIVATE_KEY="0" * 63 + "1",
        POLYGON_ADDRESS="0x" + "0" * 40,
        POLYMARKET_CHAIN_ID=137,
        _env_file=None,
    )
    base.update(overrides)
    return PolymarketConfig(**base)


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


class FakeSocket:
    """Fail-loud fake of the WebSocket surface the SEND path touches.

    Counts ``recv_calls`` so the auth no-blocking-wait pin can observe that
    ``recv`` was never awaited (the 5s ack wait must be gone, item 183).
    ``recv`` always raises (fail-loud: no real socket is available offline).
    """

    def __init__(self):
        self.sent = []
        self.recv_calls = 0
        self.close_calls = 0
        self.close_code = None

    async def send(self, payload):
        self.sent.append(payload)

    async def recv(self):
        self.recv_calls += 1
        raise TimeoutError("simulated recv (no real socket offline)")

    async def close(self):
        self.close_calls += 1
        self.close_code = 1000


def frame_of(ws, index):
    """Parse one captured send as JSON (fail-loud on non-JSON payloads)."""
    assert len(ws.sent) > index, f"expected >= {index + 1} sends, got {len(ws.sent)}"
    return json.loads(ws.sent[index])


def make_market_manager(config, socket):
    """Manager with the CLOB socket open (guards satisfied for the market channel)."""
    manager = WebSocketManager(config=config)
    manager.clob_ws = socket
    manager.clob_connected = True
    return manager


def make_realtime_manager(config, socket):
    """Manager with the RTDS socket open (guards satisfied for RTDS channels)."""
    manager = WebSocketManager(config=config)
    manager.realtime_ws = socket
    manager.realtime_connected = True
    return manager


# ---------------------------------------------------------------------------
# xfail(strict=True) flip contract: the send-path bugs (REQUER-HUMANO item 183)
# ---------------------------------------------------------------------------
@pytest.mark.xfail(
    strict=True,
    reason=(
        "_send_subscription sends {type, channel, event, markets, assets} which "
        "the CLOB market wire IGNORES (websocket_manager.py:440-469); the real "
        "frame is {assets_ids, type} (probed live 2026-09-18, REQUER-HUMANO item 183)"
    ),
)
@pytest.mark.asyncio
async def test_clob_market_subscribe_frame_uses_assets_ids_and_type(config):
    """The market-channel subscribe frame must be the REAL wire shape.

    Exact equality forces the MINIMAL correct frame: only ``assets_ids`` with
    token ids and ``type: "market"``. ``markets`` with condition ids is
    answered with close 1008 (probed) -- it must NOT be sent.
    """
    socket = FakeSocket()
    manager = make_market_manager(config, socket)
    sub_id = await manager.subscribe(
        EventType.PRICE_CHANGE,
        ChannelType.CLOB_MARKET,
        token_ids=["tok-1"],
    )
    assert sub_id
    assert frame_of(socket, 0) == {"assets_ids": ["tok-1"], "type": "market"}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "subscribe(market channel) silently accepts condition ids which the "
        "wire cannot subscribe (empty book [] probed); the send path must "
        "fail loud demanding token_ids (REQUER-HUMANO item 183)"
    ),
)
@pytest.mark.asyncio
async def test_clob_market_subscribe_without_token_ids_fails_loud(config):
    """Subscribing the market channel WITHOUT token_ids must raise ValueError.

    Condition ids are NOT subscribable on the market channel (probed:
    ``assets_ids=[cid]`` -> empty book). The fail-loud error routes callers
    (the realtime tools) to resolve condition->token first.
    """
    socket = FakeSocket()
    manager = make_market_manager(config, socket)
    with pytest.raises(ValueError, match="token"):
        await manager.subscribe(
            EventType.PRICE_CHANGE,
            ChannelType.CLOB_MARKET,
            market_ids=["mkt-1"],
            token_ids=None,
        )
    assert socket.sent == []  # nothing is sent on a rejected subscription


@pytest.mark.xfail(
    strict=True,
    reason=(
        "_send_unsubscription sends {type, channel, event} which does not stop "
        "events (websocket_manager.py:505-522); the real frame is "
        "{assets_ids, operation: unsubscribe} (probed live 2026-09-18, "
        "REQUER-HUMANO item 183)"
    ),
)
@pytest.mark.asyncio
async def test_clob_market_unsubscribe_frame_uses_operation_unsubscribe(config):
    """The market-channel unsubscribe frame must be the REAL wire shape."""
    socket = FakeSocket()
    manager = make_market_manager(config, socket)
    sub_id = await manager.subscribe(
        EventType.PRICE_CHANGE,
        ChannelType.CLOB_MARKET,
        token_ids=["tok-1"],
    )
    await manager.unsubscribe(sub_id)
    assert frame_of(socket, 1) == {
        "assets_ids": ["tok-1"],
        "operation": "unsubscribe",
    }


@pytest.mark.xfail(
    strict=True,
    reason=(
        "RTDS subscribe sends {type, channel, event} which the RTDS wire "
        "IGNORES (probed: no events); the real frame is {action, subscriptions}"
        " (probed live 2026-09-18, REQUER-HUMANO item 183)"
    ),
)
@pytest.mark.asyncio
async def test_rtds_activity_subscribe_frame_uses_action_subscriptions(config):
    """The RTDS activity subscribe frame must be the REAL wire shape."""
    socket = FakeSocket()
    manager = make_realtime_manager(config, socket)
    sub_id = await manager.subscribe(
        EventType.TRADES,
        ChannelType.ACTIVITY,
    )
    assert sub_id
    assert frame_of(socket, 0) == {
        "action": "subscribe",
        "subscriptions": [{"topic": "activity", "type": "trades"}],
    }


@pytest.mark.xfail(
    strict=True,
    reason=(
        "RTDS crypto_prices subscribe sends the broken envelope; the real "
        "frame is {action, subscriptions: [{topic: crypto_prices, type: "
        "update}]} (probed live 2026-09-18, REQUER-HUMANO item 183)"
    ),
)
@pytest.mark.asyncio
async def test_rtds_crypto_prices_subscribe_frame_uses_topic_and_update_type(config):
    """The RTDS crypto_prices subscribe frame must be the REAL wire shape."""
    socket = FakeSocket()
    manager = make_realtime_manager(config, socket)
    sub_id = await manager.subscribe(
        EventType.CRYPTO_UPDATE,
        ChannelType.CRYPTO_PRICES,
    )
    assert sub_id
    assert frame_of(socket, 0) == {
        "action": "subscribe",
        "subscriptions": [{"topic": "crypto_prices", "type": "update"}],
    }


@pytest.mark.xfail(
    strict=True,
    reason=(
        "_authenticate_clob sends {auth} WITHOUT type:'user' and blocks 5s on "
        "an undocumented ack (websocket_manager.py:278-330); the real frame is "
        "{auth, type: user} with NO recv wait (probed live 2026-09-18 + docs, "
        "REQUER-HUMANO item 183)"
    ),
)
@pytest.mark.asyncio
async def test_clob_user_auth_frame_carries_type_user_and_skips_blocking_recv(
    creds_config,
):
    """The user-channel auth frame must carry type:'user' and NOT block on recv.

    Pins three facts: (1) the frame is {auth, type: "user"} (exact equality);
    (2) recv is NEVER awaited (the undocumented 5s ack wait is gone);
    (3) authenticated is True after the frame is sent (failures surface as
    close 1008 handled by the receive loop/reconnect -- probed).
    """
    manager = WebSocketManager(config=creds_config)
    socket = FakeSocket()
    manager.clob_ws = socket
    manager.clob_connected = True

    await manager._authenticate_clob()

    assert frame_of(socket, 0) == {
        "auth": {"apiKey": "key-123", "secret": "secret-456", "passphrase": "pass-789"},
        "type": "user",
    }
    assert socket.recv_calls == 0  # no blocking ack wait
    assert manager.authenticated is True


@pytest.mark.xfail(
    strict=True,
    reason=(
        "user-channel subscribe sends the broken envelope; the real frame per "
        "docs is {operation: subscribe, markets: [...]} (REQUER-HUMANO item 183)"
    ),
)
@pytest.mark.asyncio
async def test_clob_user_subscribe_uses_operation_frame(config):
    """The user-channel op-frame must be {operation: subscribe, markets}."""
    socket = FakeSocket()
    manager = make_market_manager(config, socket)
    manager.authenticated = True  # guard :405-406 satisfied directly

    sub_id = await manager.subscribe(
        EventType.ORDER,
        ChannelType.CLOB_USER,
        market_ids=["m-1"],
    )
    assert sub_id
    assert frame_of(socket, 0) == {"operation": "subscribe", "markets": ["m-1"]}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "user-channel unsubscribe sends the broken envelope; the real frame "
        "per docs is {operation: unsubscribe, markets: [...]} (REQUER-HUMANO "
        "item 183)"
    ),
)
@pytest.mark.asyncio
async def test_clob_user_unsubscribe_uses_operation_unsubscribe(config):
    """The user-channel unsubscribe frame must be {operation: unsubscribe}."""
    socket = FakeSocket()
    manager = make_market_manager(config, socket)
    manager.authenticated = True

    sub_id = await manager.subscribe(
        EventType.ORDER,
        ChannelType.CLOB_USER,
        market_ids=["m-1"],
    )
    await manager.unsubscribe(sub_id)
    assert frame_of(socket, 1) == {
        "operation": "unsubscribe",
        "markets": ["m-1"],
    }


@pytest.mark.xfail(
    strict=True,
    reason=(
        "_resubscribe_all re-sends the broken envelopes after reconnect "
        "(websocket_manager.py:370-379); every re-sent frame must be a REAL "
        "wire frame (REQUER-HUMANO item 183)"
    ),
)
@pytest.mark.asyncio
async def test_resubscribe_all_resends_real_frames(config):
    """After reconnect, every re-sent frame must be in the REAL wire format."""
    market_socket = FakeSocket()
    realtime_socket = FakeSocket()
    manager = make_market_manager(config, market_socket)
    manager.realtime_ws = realtime_socket
    manager.realtime_connected = True

    market_sub = await manager.subscribe(
        EventType.PRICE_CHANGE, ChannelType.CLOB_MARKET, token_ids=["tok-1"]
    )
    await manager.subscribe(EventType.TRADES, ChannelType.ACTIVITY)
    del market_sub

    # Simulate a reconnect: sockets swapped, resubscribe re-sends everything.
    new_market = FakeSocket()
    new_realtime = FakeSocket()
    manager.clob_ws = new_market
    manager.realtime_ws = new_realtime
    await manager._resubscribe_all()

    assert frame_of(new_market, 0) == {"assets_ids": ["tok-1"], "type": "market"}
    assert frame_of(new_realtime, 0) == {
        "action": "subscribe",
        "subscriptions": [{"topic": "activity", "type": "trades"}],
    }
