"""
Offline dispatch suite for the REAL-TIME route of polymarket_mcp.server
(T-0073; fix of the REGISTER-ONLY bug catalogued in L-0137).

THE BUG (L-0137, proved offline in increment 13 and re-proved on main
d2f328e by the curator probe): the MCP dispatch of the 7 real-time tools
was UNREACHABLE through 3 independent facets in src/polymarket_mcp/server.py:

1. the route called `realtime.handle_tool(name, arguments, websocket_manager,
   server)` while tools/realtime.py:218 defines `handle_tool_call(name,
   arguments)` - name AND arity diverge -> AttributeError swallowed by the
   call_tool catch-all as the uniform envelope {"success": false,
   "error": "module 'polymarket_mcp.tools.realtime' has no attribute
   'handle_tool'"} (mypy 2.3.1 pin: server.py:524 [attr-defined]);
2. the route checked server.py's OWN global `websocket_manager` while the
   tools layer reads realtime's global (realtime.py:22);
3. `realtime.set_websocket_manager` (realtime.py:25) was never called from
   src/ - the tools global stayed None forever.

THE FIX (this slice touches server.py ONLY; tools/realtime.py and
utils/websocket_manager.py are sibling turf): the route now returns
`realtime.handle_tool_call(name, arguments)` with NO json.dumps wrap
(handle_tool_call already returns List[types.TextContent]; the wrap was part
of the original bug - json.dumps of a TextContent list raises TypeError),
and initialize_server registers the SAME manager object with the tools
layer via realtime.set_websocket_manager(websocket_manager) (facet 2 closes
by identity). The manager-None guard of the route is UNCHANGED.

FAMILIES:
- A REGISTRATION: initialize_server() with EVERY seam faked (P-0040
  anatomy, P-0035 clean_env, L-0142 rate-limiter seam) proves the DOUBLE
  identity server_module.websocket_manager IS realtime.websocket_manager
  IS fake_manager (facets 2+3 closed) and that the websocket startup task
  still runs (connect + start_background_task recorded by the structural
  fake). config is a REAL PolymarketConfig built by kwargs with
  _env_file=None; the fake client reports has_api_credentials() False and
  create_api_credentials RAISES (READ-ONLY path, zero network; R8: this
  suite never asserts the CONTENT of credential logs - the raise happens
  before they could exist). TradingTools is never instantiated.
- B DISPATCH: for EACH of the 7 names - the routed name is validated
  against the surface DERIVED from realtime.get_tools() (presence pins by
  member, never by count; L-0148b) - call_tool(name, arguments) returns
  EXACTLY what realtime.handle_tool_call(name, arguments) returns when
  called directly in the SAME test (pin by equality, L-0109/L-0090: the
  handler texts are already pinned by tests/test_realtime_offline.py,
  T-0053 - this suite pins the ROUTING, not the texts). No AttributeError,
  no error envelope, no double json.dumps. The manager records 2 identical
  attempts (one direct, one dispatched), proving the routed arguments
  reached the handler.
- C FIX-COMPATIBILITY (no test here): the manager-None path of the route is
  intentionally NOT re-pinned - tests/test_server_dispatch_offline.py
  (T-0055, :639-653) already pins the uniform ValueError envelope for all
  7 names with the server manager None; that path is unchanged by the fix
  (overlap cited in the report).

ANTI-FIX (L-0137, binding): the broken name appears ONLY in this docstring
as the known-bug reference; no expected-failure markers anywhere (the bug
is FIXED, not expected-fail); every equality pin fails loudly if the broken
dispatch returns the AttributeError envelope.

FAKES (P-0031 fail-loud module seams; L-0121 structural):
- FakeInitManager mirrors the REAL WebSocketManager signatures
  (websocket_manager.py: connect :210, subscribe :380-387, unsubscribe
  :470, start_background_task :778, stop_background_task :792, get_status
  :937) and raises AssertionError on ANY undeclared attribute. Divergence
  from the sibling fake (tests/test_realtime_offline.py:128): subscribe
  returns a FIXED id instead of an incrementing one so the direct call and
  the dispatched call produce IDENTICAL observable text (the equality pin
  needs deterministic output; the attempts list still distinguishes the
  two calls).
- get_status requires a payload built by _make_status (mirrored
  field-by-field from tests/test_realtime_offline.py:42-118, including
  fields the tool does not read yet - KeyError-proof, L-0121).
- FakeInitClient: has_api_credentials() False + create_api_credentials
  raises; anything else raises AssertionError.
- create_safety_limits_from_config -> inert fake; get_rate_limiter ->
  recorder at the server seam (L-0142: the process-wide singleton is NEVER
  constructed).

HERMETICITY (P-0029/P-0035/L-0130/L-0014/L-0138): env -i direction +
hostile-env direction (clean_env delenvs every config-sourced prefix);
zero network (no socket/requests/httpx/urllib/subprocess anywhere in this
file); zero real sleeps - the fire-and-forget startup task is DRAINED by
awaiting it directly (pure scheduling, no wall time); no socket is ever
created.

TEARDOWN (P-0037, order-independent): the autouse fixture restores
server_module.{config, polymarket_client, safety_limits, trading_tools,
websocket_manager, _shutdown_event, _background_tasks} to the values
captured BEFORE the test and realtime.websocket_manager to its pre-test
value (None in steady state, mirroring the sibling suite's own guard).
"""
import os
from typing import Any, Dict, List, Optional

import pytest

import polymarket_mcp.server as server_module
import polymarket_mcp.tools.realtime as realtime
from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.utils.websocket_manager import ChannelType, EventType

# Process env prefixes/names that feed PolymarketConfig fields; stripped by
# the autouse fixture so tests never observe the host environment (P-0035;
# mirrored from tests/test_config_security.py:53-63).
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

# Module globals restored by the autouse fixture (P-0037, order-independent;
# the realtime tools-layer global is handled separately below).
_SERVER_GLOBALS = (
    "config",
    "polymarket_client",
    "safety_limits",
    "trading_tools",
    "websocket_manager",
    "_shutdown_event",
    "_background_tasks",
)

# The routed surface is DERIVED from the definition functions (never a
# hand-written list; L-0148b pins by member, not by count). Note: the module
# header of tools/realtime.py still says "6 tools" - STALE docstring, the
# definition list has 7 (unsubscribe_realtime included); registered as a
# doc finding in the task report, NOT edited in this slice.
_REALTIME_NAMES = [tool.name for tool in realtime.get_tools()]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip config-sourced env vars so the initialize path never observes
    the host environment (P-0035; hermeticity direction 2, L-0130)."""
    for name in list(os.environ):
        if any(name.startswith(prefix) for prefix in _ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def pristine_server_state(monkeypatch):
    """Restore the module globals and the realtime registration to the
    values captured BEFORE each test (P-0037, order-independent). Setting an
    attribute to its CURRENT value through monkeypatch registers a restore
    of exactly that value; realtime.websocket_manager is additionally forced
    to None during the test (pre-initialize semantics) and restored to its
    pre-test value at teardown."""
    for name in _SERVER_GLOBALS:
        monkeypatch.setattr(server_module, name, getattr(server_module, name))
    monkeypatch.setattr(realtime, "websocket_manager", None)


def _house_config() -> PolymarketConfig:
    """Real PolymarketConfig with the house test pattern (mirrors
    test_server_dispatch_offline.py house_config: synthetic key/address,
    chain 137) and _env_file=None so no .env file is ever read (P-0029)."""
    return PolymarketConfig(
        POLYGON_PRIVATE_KEY="0" * 63 + "1",
        POLYGON_ADDRESS="0x" + "0" * 40,
        POLYMARKET_CHAIN_ID=137,
        _env_file=None,
    )


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
    """Synthetic get_status() payload - mirrored field-by-field from
    tests/test_realtime_offline.py:42-118 (websocket_manager.py:937-985
    structure, including fields the tool does not read yet - KeyError-proof,
    L-0121)."""
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


class FakeInitManager:
    """Structural stand-in for WebSocketManager covering BOTH layers
    (L-0121): the lifecycle methods the initialize path exercises
    (connect/start_background_task via _start_websocket, server.py:291-297)
    AND the tool signatures the realtime layer consumes (subscribe
    websocket_manager.py:380-387, unsubscribe :470, get_status :937). Any
    undeclared attribute raises AssertionError (fail-loud, P-0031). The
    subscribe id is FIXED so the direct call and the dispatched call
    produce IDENTICAL observable text (equality pin needs deterministic
    output; the attempts list still distinguishes the two calls)."""

    FIXED_SUBSCRIPTION_ID = "sub-1"

    def __init__(
        self,
        config: Any = None,
        *,
        authenticated: bool = True,
        status: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.created_with = config
        self.authenticated = authenticated
        self._status = status
        self.connect_calls = 0
        self.background_starts = 0
        self.background_stops = 0
        self.subscribe_attempts: List[Dict[str, Any]] = []
        self.created_subscription_ids: List[str] = []
        self.unsubscribe_calls: List[str] = []
        self.status_reads = 0

    def __getattr__(self, name: str):
        raise AssertionError(f"Unexpected endpoint access on fake manager: {name}")

    async def connect(self) -> None:
        self.connect_calls += 1

    async def start_background_task(self) -> None:
        self.background_starts += 1

    async def stop_background_task(self) -> None:
        self.background_stops += 1

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
            raise RuntimeError("CLOB authentication required for user subscriptions")
        self.created_subscription_ids.append(self.FIXED_SUBSCRIPTION_ID)
        return self.FIXED_SUBSCRIPTION_ID

    async def unsubscribe(self, subscription_id: str) -> bool:
        self.unsubscribe_calls.append(subscription_id)
        return True

    def get_status(self) -> Dict[str, Any]:
        self.status_reads += 1
        if self._status is None:
            raise AssertionError("get_status called without a configured payload")
        return self._status


class FakeInitClient:
    """Duck-typed credential oracle for the initialize path (P-0031):
    has_api_credentials() is always False (READ-ONLY path) and
    create_api_credentials RAISES - the auto-create branch can never reach a
    real network endpoint because the client itself is the fake (zero
    network by construction, L-0138). R8: this suite never asserts the
    CONTENT of credential logs; the raise happens before they could exist."""

    def __init__(self) -> None:
        self.credentials_attempts = 0

    def __getattr__(self, name: str):
        raise AssertionError(f"Unexpected endpoint access on fake client: {name}")

    def has_api_credentials(self) -> bool:
        return False

    async def create_api_credentials(self) -> None:
        self.credentials_attempts += 1
        raise RuntimeError("offline suite: the network seam must never be touched")


class FakeLimits:
    """Inert stand-in for SafetyLimits: the initialize path only stores it
    in the module global; any attribute access would be a dispatch
    regression and fails loudly (P-0031)."""

    def __getattr__(self, name: str):
        raise AssertionError(
            f"Unexpected endpoint access on fake safety limits: {name}"
        )


class FakeRateLimiter:
    """Recorder standing in for the process-wide singleton (L-0142): the
    real singleton is NEVER constructed here - the server seam
    get_rate_limiter is patched with this recorder."""

    def __init__(self) -> None:
        self.calls = 0

    def __getattr__(self, name: str):
        raise AssertionError(
            f"Unexpected endpoint access on fake rate limiter: {name}"
        )


def _arguments_for(name: str) -> Dict[str, Any]:
    """Success-path arguments per realtime tool. The handler TEXTS are
    pinned by tests/test_realtime_offline.py (T-0053) - this suite pins the
    routing by equality with the direct handler call, so the arguments only
    need to reach the success path of each handler."""
    return {
        "subscribe_market_prices": {
            "market_ids": ["0xmarket-1"],
            "callback_type": "notification",
        },
        "subscribe_orderbook_updates": {"token_ids": ["0xtoken-1"], "depth": 5},
        "subscribe_user_orders": {"market_ids": ["0xmarket-1"]},
        "subscribe_user_trades": {"market_ids": ["0xmarket-1"]},
        "subscribe_market_resolution": {"market_ids": ["0xmarket-1"]},
        "get_realtime_status": {},
        "unsubscribe_realtime": {"subscription_id": FakeInitManager.FIXED_SUBSCRIPTION_ID},
    }[name]


async def _pin_dispatch(monkeypatch, name: str, arguments: Dict[str, Any]):
    """Route `name` through the MCP dispatch and compare against a DIRECT
    realtime.handle_tool_call in the SAME test (pin by equality, L-0109):
    same TextContent list, no AttributeError envelope, no double json.dumps.
    The routed name is validated against the surface derived from
    realtime.get_tools() (presence, not count - L-0148b). Returns the fake
    so each test can pin its own recorder."""
    assert name in _REALTIME_NAMES, f"{name} must be derived from realtime.get_tools()"
    fake = FakeInitManager()
    monkeypatch.setattr(server_module, "websocket_manager", fake)
    realtime.set_websocket_manager(fake)

    direct = await realtime.handle_tool_call(name, dict(arguments))
    dispatched = await server_module.call_tool(name, dict(arguments))

    assert len(dispatched) == 1, f"expected exactly 1 TextContent for {name}"
    assert dispatched[0].type == "text"
    assert dispatched == direct, (
        f"dispatch for {name} diverged from the direct handler call: "
        f"{dispatched[0].text!r} != {direct[0].text!r}"
    )
    return fake


# =====================================================================
# Family A - REGISTRATION through initialize_server (facets 2 + 3)
# =====================================================================


async def test_initialize_server_registers_manager_in_both_layers(monkeypatch):
    """initialize_server builds the manager through the patched
    WebSocketManager seam and registers the SAME object with the realtime
    tools layer (realtime.set_websocket_manager) - the double identity
    closes facets 2+3 of L-0137. The READ-ONLY path runs end-to-end (fake
    client with has_api_credentials False and a RAISING
    create_api_credentials - zero network, R8-safe), TradingTools stays
    uninitialized, the rate limiter seam is hit exactly once, and the
    websocket startup task drains with connect + start_background_task
    recorded by the fake."""
    fake_config = _house_config()
    fake_client = FakeInitClient()
    fake_limits = FakeLimits()
    fake_limiter = FakeRateLimiter()
    managers_built: List[FakeInitManager] = []
    client_factory_calls = 0

    def _fake_client_factory(**_kwargs):
        nonlocal client_factory_calls
        client_factory_calls += 1
        return fake_client

    def _fake_limits_factory(_config):
        return fake_limits

    def _fake_limiter():
        fake_limiter.calls += 1
        return fake_limiter

    def _fake_manager_factory(config):
        # Mirrors the real constructor flow: WebSocketManager(config) - the
        # config reaches the manager instance (L-0121 pass-through pin).
        manager = FakeInitManager(config)
        managers_built.append(manager)
        return manager

    monkeypatch.setattr(server_module, "load_config", lambda: fake_config)
    monkeypatch.setattr(server_module, "create_polymarket_client", _fake_client_factory)
    monkeypatch.setattr(
        server_module, "create_safety_limits_from_config", _fake_limits_factory
    )
    monkeypatch.setattr(server_module, "get_rate_limiter", _fake_limiter)
    monkeypatch.setattr(server_module, "WebSocketManager", _fake_manager_factory)

    await server_module.initialize_server()

    # Drain the fire-and-forget startup task deterministically (no wall
    # time): _start_websocket only awaits the two recorded no-ops.
    pending = list(server_module._background_tasks)
    for task in pending:
        await task

    fake_manager = managers_built[0]

    # The double identity closes facets 2+3: the manager the server owns and
    # the manager the realtime tools layer reads are the SAME object.
    assert server_module.config is fake_config
    assert server_module.polymarket_client is fake_client
    assert server_module.safety_limits is fake_limits
    assert server_module.trading_tools is None
    assert server_module.websocket_manager is fake_manager
    assert realtime.websocket_manager is fake_manager
    assert fake_manager.created_with is fake_config
    # The startup task ran and was discarded from the strong-reference set.
    assert fake_manager.connect_calls == 1
    assert fake_manager.background_starts == 1
    assert server_module._background_tasks == set()
    # READ-ONLY path: the auto-create attempt hit the fake exactly once.
    assert fake_client.credentials_attempts == 1
    assert client_factory_calls == 1
    assert fake_limiter.calls == 1


# =====================================================================
# Family B - DISPATCH of the 7 real-time names (facet 1)
# =====================================================================


async def test_call_tool_dispatches_subscribe_market_prices(monkeypatch):
    """The routed call returns EXACTLY what the direct handler call returns
    (pin by equality) and records 2 identical subscribe attempts - one from
    the direct call, one from the dispatch - with the price-change event
    type on the market channel (routing + argument pass-through)."""
    fake = await _pin_dispatch(
        monkeypatch,
        "subscribe_market_prices",
        _arguments_for("subscribe_market_prices"),
    )
    assert len(fake.subscribe_attempts) == 2
    assert fake.subscribe_attempts[0] == fake.subscribe_attempts[1]
    assert fake.subscribe_attempts[0]["event_type"] == EventType.PRICE_CHANGE
    assert fake.subscribe_attempts[0]["channel"] == ChannelType.CLOB_MARKET
    assert fake.subscribe_attempts[0]["market_ids"] == ["0xmarket-1"]
    assert fake.created_subscription_ids == [fake.FIXED_SUBSCRIPTION_ID] * 2


async def test_call_tool_dispatches_subscribe_orderbook_updates(monkeypatch):
    """Same equality pin for the orderbook family: 2 identical attempts with
    the aggregated-orderbook event type on the market channel and the token
    ids passed through (depth is echoed by the handler text but must NOT be
    forwarded to the manager - the fake declares no depth parameter,
    L-0121)."""
    fake = await _pin_dispatch(
        monkeypatch,
        "subscribe_orderbook_updates",
        _arguments_for("subscribe_orderbook_updates"),
    )
    assert len(fake.subscribe_attempts) == 2
    assert fake.subscribe_attempts[0] == fake.subscribe_attempts[1]
    assert fake.subscribe_attempts[0]["event_type"] == EventType.AGG_ORDERBOOK
    assert fake.subscribe_attempts[0]["channel"] == ChannelType.CLOB_MARKET
    assert fake.subscribe_attempts[0]["token_ids"] == ["0xtoken-1"]


async def test_call_tool_dispatches_subscribe_user_orders(monkeypatch):
    """Same equality pin for the user-orders family: 2 identical attempts
    with the ORDER event type on the user channel (authenticated fake ->
    success path; the auth guard itself is pinned by the sibling suite)."""
    fake = await _pin_dispatch(
        monkeypatch,
        "subscribe_user_orders",
        _arguments_for("subscribe_user_orders"),
    )
    assert len(fake.subscribe_attempts) == 2
    assert fake.subscribe_attempts[0] == fake.subscribe_attempts[1]
    assert fake.subscribe_attempts[0]["event_type"] == EventType.ORDER
    assert fake.subscribe_attempts[0]["channel"] == ChannelType.CLOB_USER
    assert fake.subscribe_attempts[0]["market_ids"] == ["0xmarket-1"]


async def test_call_tool_dispatches_subscribe_user_trades(monkeypatch):
    """Same equality pin for the user-trades family: 2 identical attempts
    with the TRADE event type on the user channel."""
    fake = await _pin_dispatch(
        monkeypatch,
        "subscribe_user_trades",
        _arguments_for("subscribe_user_trades"),
    )
    assert len(fake.subscribe_attempts) == 2
    assert fake.subscribe_attempts[0] == fake.subscribe_attempts[1]
    assert fake.subscribe_attempts[0]["event_type"] == EventType.TRADE
    assert fake.subscribe_attempts[0]["channel"] == ChannelType.CLOB_USER
    assert fake.subscribe_attempts[0]["market_ids"] == ["0xmarket-1"]


async def test_call_tool_dispatches_subscribe_market_resolution(monkeypatch):
    """Same equality pin for the market-resolution family: 2 identical
    attempts with the MARKET_RESOLVED event type on the market channel."""
    fake = await _pin_dispatch(
        monkeypatch,
        "subscribe_market_resolution",
        _arguments_for("subscribe_market_resolution"),
    )
    assert len(fake.subscribe_attempts) == 2
    assert fake.subscribe_attempts[0] == fake.subscribe_attempts[1]
    assert fake.subscribe_attempts[0]["event_type"] == EventType.MARKET_RESOLVED
    assert fake.subscribe_attempts[0]["channel"] == ChannelType.CLOB_MARKET
    assert fake.subscribe_attempts[0]["market_ids"] == ["0xmarket-1"]


async def test_call_tool_dispatches_get_realtime_status(monkeypatch):
    """Same equality pin for the status tool: get_status() is read exactly
    twice (once by the direct call, once by the dispatch) with the
    configured payload mirrored field-by-field from the sibling suite."""
    fake = FakeInitManager(status=_make_status())
    monkeypatch.setattr(server_module, "websocket_manager", fake)
    realtime.set_websocket_manager(fake)

    direct = await realtime.handle_tool_call("get_realtime_status", {})
    dispatched = await server_module.call_tool("get_realtime_status", {})

    assert dispatched == direct
    assert fake.status_reads == 2


async def test_call_tool_dispatches_unsubscribe_realtime(monkeypatch):
    """Same equality pin for the unsubscribe tool: 2 identical unsubscribe
    calls with the same subscription id (the fake returns True for both, so
    the success text is identical and the equality pin holds without an id
    counter reset)."""
    fake = await _pin_dispatch(
        monkeypatch,
        "unsubscribe_realtime",
        _arguments_for("unsubscribe_realtime"),
    )
    assert fake.unsubscribe_calls == [fake.FIXED_SUBSCRIPTION_ID] * 2
