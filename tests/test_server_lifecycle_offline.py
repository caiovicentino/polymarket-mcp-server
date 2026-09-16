"""
Offline LIFECYCLE suite for polymarket_mcp.server (T-0065).

Covers the lifecycle surface that sat at 57.45% statement coverage on clone
main 136241e (211 statements, 100 dead; T-0046 then inserted the
pre-handshake/discover layer, growing server.py to 290 statements on the
r2 fork, main ed882e8): _start_websocket :291-297, shutdown :300-335,
initialize_server :582-680, main :683-745 and run :747-749 - the wiring
path every real deployment traverses
(config -> client -> safety limits -> rate limiter -> trading tools ->
websocket manager -> stdio entrypoint) with zero offline proof before this
suite.

Sources of truth (suite-only: src/** is read, never modified):
- src/polymarket_mcp/server.py @ farm/T-0065 r2 (server.py byte-identical
  to main ed882e8 - the slice adds only this test file): globals :59-69
  (config/polymarket_client/safety_limits/trading_tools/websocket_manager/
  _shutdown_event all None pre-init; _background_tasks an empty set at :69),
  _start_websocket :291-297 (await manager.connect() :294 THEN await
  manager.start_background_task() :295 inside ONE try - the except logs
  "WebSocket startup failed" WITHOUT re-raising :296-297), shutdown
  :300-335 (CANCEL_ON_SHUTDOWN read via os.getenv with default "true" at
  :310; credentialed cancel branch :313-319; cancel failure :318-319;
  no-credentials skip :320-321; disabled skip :322-323; websocket close
  :326-333 with its own try/except; final log :335), _signal_handler
  :338-343, initialize_server :582-680 (load_config :598, root logger
  setLevel :601, create_polymarket_client :607-614, credential creation
  :617-634 with the DEBUG api_key/passphrase fragments :627-628 -
  R8/REQUER-HUMANO item 76: NEVER pinned, see below; safety limits :638;
  rate limiter :641; trading gate :644-654; WebSocketManager(config) :658 +
  startup task :661-663; mode logs :669-676; except :678-680 logs "Failed
  to initialize server" and RE-RAISES), main :683-745 (initialize_server
  :694, shutdown event :697, signal registration :698-699, stdio transport
  :703, pre-handshake wrapper :708 (T-0046: read_stream =
  _PreHandshakeStream(read_stream, write_stream) - the class guards
  _read_stream :144 and _write_stream :145), server task :710-716, shutdown
  watcher :717, asyncio.wait FIRST_COMPLETED :719-723, pending
  cancellation :725-731, exception propagation :734-735, except
  KeyboardInterrupt :737-738, except Exception :739-741 with RE-RAISE,
  finally -> shutdown :742-744), run :747-749 (asyncio.run(main())).

Seams and fakes (P-0031/L-0133 - EVERY I/O seam patched BEFORE any call):
- _install_stubs patches load_config, create_polymarket_client and the
  WebSocketManager class in the server module namespace; the fakes fail loud
  on any unexpected surface. create_safety_limits_from_config and
  get_rate_limiter stay REAL (offline-safe): they prove the wiring with real
  objects, per contract.
- _install_main_stubs patches initialize_server, signal.signal (attribute
  patch on the real signal module), mcp.server.stdio.stdio_server (attribute
  patch on the REAL mcp module - the contract seam) and the module-level
  Server object; the fake server.run blocks until cancelled or raises on
  demand.

Hermeticity (P-0029 in BOTH directions, L-0138):
- zero network by construction: the real WebSocketManager class is never
  constructed (its connect() dials wss://), the real PolymarketClient is
  never constructed, and the runtime socket-killer proof (connect /
  connect_ex / create_connection / getaddrinfo -> RuntimeError) runs this
  whole suite green - recorded in the task report.
- clean_env (autouse; P-0035 house pattern of tests/test_config_security.py
  via T-0042/T-0051): every config-sourced env prefix is stripped
  (POLYGON_/POLYMARKET_/DEMO_MODE/LOG_LEVEL/MAX_/MIN_/ENABLE_/REQUIRE_/
  AUTO_) PLUS CANCEL_ON_SHUTDOWN - NOT a config field: shutdown() reads it
  directly via os.getenv (server.py:310), so it is controlled EXPLICITLY per
  test (absent in the default-branch tests, monkeypatch.setenv("false") in
  the disabled ones).
- every PolymarketConfig is built by explicit kwargs with _env_file=None
  (L-0130: pydantic still reads the host env for fields not passed - the
  fixture makes the host env neutral by construction).

Order-independence (L-0099): pristine_server_state (autouse) resets every
module global the lifecycle functions touch (server.py:59-69) to the pre-init
None state and restores the ORIGINAL value after each test; _background_tasks
is replaced by a fresh set per test (mutations land on the copy, the original
set object is restored untouched); the ROOT logger level mutated by
initialize_server (server.py:601) is saved and restored.

R8 red line (REQUER-HUMANO item 76): server.py:627-628 log DEBUG fragments of
api_key/passphrase. Those two log records are NEVER asserted (no values, no
substrings of the fragment); the fake api_creds carries synthetic strings
only. The future R8 fix (redacting those lines) cannot break this suite.

Divergences declared (L-0025/L-0043/FA-0043 - prescriptions vs observed
reality; asserts follow the CODE, L-0020/L-0090):
1. KeyboardInterrupt mechanism: the contract prescribed the fake server.run
   raising KeyboardInterrupt. Observed reality, proven with this repo's
   Python 3.12 venv: a KeyboardInterrupt raised inside a NESTED asyncio task
   escapes the event loop and kills it BEFORE main()'s
   "except KeyboardInterrupt" can run (Task.__step re-raises BaseException
   out of run_forever - the report records the probe). The suite injects the
   KeyboardInterrupt from the fake stdio transport's __aenter__ instead - a
   DIRECT await in main()'s own frame - reaching the SAME except branch
   (server.py:737-738) with the same observables: the log record,
   shutdown() in the finally, main() completing without an exception.
2. Line refs: the contract cited shutdown "~:63-99", initialize_server
   "~:354-444", main "~:446-503", run "~:505-508"; the r1 fork (257d932)
   showed :64-99, :346-444, :447-503, :506-508 and the r2 fork (main
   ed882e8, T-0046 inserted the pre-handshake layer) shows :300-335,
   :582-680, :683-745, :747-749. Refs localize; semantics re-derived from
   the code at each round (L-0143/L-0096).
3. initialize_server read-only overlap: the two read-only tests exercise the
   SAME failure->fallback code path with two complementary pin sets -
   ..._read_only_mode_without_credentials pins the END STATE (mode logs,
   trading_tools None, real SafetyLimits, ws manager constructed and
   connected after the drain) while ..._credential_creation_failure_
   falls_back_readonly pins the FALLBACK MECHANISM (no propagation, the
   warning record, init continuing past the failure) - deliberate,
   documented overlap (P-0039 dedupe note).

REGISTER-ONLY (L-0137, deliberately NOT pinned - anti-fix): server.py:524-525
(the broken realtime dispatch pair - realtime.handle_tool vs
tools/realtime.py:218 handle_tool_call) stays uncovered; the full-suite
coverage residual on the r2 fork is that pair PLUS the pre-handshake/
discover layer's FOREIGN residual (server.py:198, :243-244, :246, :261-265
- T-0046's own coverage gap, NOT this slice's debt; L-0146: registered,
not closed here).

Coupling (consumer<->producer, L-0073/L-0121): the fakes' surfaces ARE the
structural pins - a lifecycle fix that changes a seam must update the fake +
asserts in the SAME slice (e.g. WebSocketManager gaining constructor kwargs,
create_polymarket_client gaining parameters, shutdown() reading a different
env name, cancel_all_orders starting to take arguments - the fake declares
NO parameters, so any forwarding fails loudly with TypeError).
"""
import asyncio
import logging
import os
import signal
from types import SimpleNamespace

import pytest

import polymarket_mcp.server as server_module
from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.safety_limits import SafetyLimits

SERVER_LOGGER = "polymarket_mcp.server"

# Process env names/prefixes that feed PolymarketConfig fields, stripped by
# the autouse fixture (P-0035), PLUS CANCEL_ON_SHUTDOWN: shutdown() reads it
# directly via os.getenv (server.py:310) - it is a runtime knob, not a config
# field, so it is stripped here and controlled explicitly per test.
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
    "CANCEL_ON_SHUTDOWN",
)

# Module globals the lifecycle functions touch (server.py:59-69) - reset to
# the pre-init state and restored by the autouse fixture (L-0099).
_LIFECYCLE_GLOBALS = (
    "config",
    "polymarket_client",
    "safety_limits",
    "trading_tools",
    "websocket_manager",
    "_shutdown_event",
)

# Synthetic L2 credentials for the ALREADY-CREDENTIALED config scenarios.
# Test strings only - never real material (R8 red line).
_CREDS_KWARGS = {
    "POLYMARKET_API_KEY": "key-123",
    "POLYMARKET_API_SECRET": "secret-456",
    "POLYMARKET_PASSPHRASE": "pass-789",
    "POLYMARKET_API_KEY_NAME": "keyname",
}


# ---------------------------------------------------------------------------
# Hermeticity + order-independence (autouse fixtures)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip config-sourced env vars so tests never observe the host env.

    Pydantic BaseSettings reads the HOST env for every field not passed
    explicitly even with _env_file=None (config.py:11,17-18; L-0130), so
    without this fixture a hostile host POLYMARKET_API_SECRET etc. would
    leak into assertion diffs. CANCEL_ON_SHUTDOWN is stripped too: shutdown()
    reads it via os.getenv directly (server.py:310), so every default-branch
    test must observe the CODE default ("true"), never a host value.
    """
    for name in list(os.environ):
        if any(name.startswith(prefix) for prefix in _ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def pristine_server_state(monkeypatch):
    """Order-independence (L-0099): every lifecycle test starts and ends at
    the pre-init state.

    The globals the lifecycle functions touch (server.py:59-69) are set to
    their documented pre-init values and monkeypatch restores the ORIGINAL
    values after the test, so sibling suites (dispatch/realtime/web) that
    share this pytest process are never affected. _background_tasks is
    replaced by a FRESH set per test: mutations during the test land on the
    copy, the original set object comes back untouched. initialize_server
    mutates the ROOT logger level (server.py:601) - saved and restored here
    because it is process-global state outside monkeypatch's reach.
    """
    monkeypatch.setattr(server_module, "_background_tasks", set())
    for name in _LIFECYCLE_GLOBALS:
        monkeypatch.setattr(server_module, name, None)
    root_logger = logging.getLogger()
    original_level = root_logger.level
    yield
    root_logger.setLevel(original_level)


# ---------------------------------------------------------------------------
# Fakes (P-0031: fail-loud seams owned by this file; zero class-level
# mutable state - order-independent, L-0099)
# ---------------------------------------------------------------------------
class FakeClient:
    """Duck-typed PolymarketClient stand-in for the LIFECYCLE surface.

    Only what the lifecycle functions touch (server.py:313-319, :617-628,
    :645, :669-675): has_api_credentials(), create_api_credentials(),
    cancel_all_orders() and the api_creds consult (:625-626). Anything else
    raises AttributeError loudly (P-0031) so a regression that reaches for an
    unfaked network endpoint fails the test instead of hitting the network.
    cancel_all_orders declares NO parameters (L-0121 pin-by-signature): a
    fix that starts forwarding arguments fails with TypeError at the seam.
    """

    def __init__(
        self,
        *,
        has_credentials,
        creation_fails=False,
        creation_succeeds=False,
        cancel_error=None,
    ):
        self._has_credentials = has_credentials
        self.creation_fails = creation_fails
        self.creation_succeeds = creation_succeeds
        self.cancel_error = cancel_error
        self.has_api_credentials_calls = 0
        self.create_api_credentials_calls = 0
        self.cancel_all_orders_calls = 0
        self.api_creds_reads = 0
        self._api_creds = None

    def has_api_credentials(self) -> bool:
        self.has_api_credentials_calls += 1
        return self._has_credentials

    async def create_api_credentials(self):
        self.create_api_credentials_calls += 1
        if self.creation_fails:
            raise RuntimeError("credential endpoint unreachable")
        # R8: synthetic strings only - the DEBUG fragments the server logs
        # (server.py:627-628) are never asserted anywhere in this suite.
        self._api_creds = SimpleNamespace(
            api_key="synthetic-key-000000",
            api_secret="synthetic-secret-000",
            api_passphrase="synthetic-pass-000",
        )
        if self.creation_succeeds:
            self._has_credentials = True
        return self._api_creds

    @property
    def api_creds(self):
        """Records the consult the server makes after creation
        (server.py:389-390) - the flow pin without pinning log fragments."""
        self.api_creds_reads += 1
        return self._api_creds

    async def cancel_all_orders(self):
        self.cancel_all_orders_calls += 1
        if self.cancel_error is not None:
            raise self.cancel_error
        return {"canceled": 0}


class FakeWebSocketManager:
    """Instance-level recorder for the WebSocketManager surface the
    lifecycle functions touch (server.py:294-295, :330): connect /
    start_background_task / stop_background_task - async no-op recorders,
    failure injection per instance. NO class-level state (L-0099)."""

    def __init__(
        self, config=None, *, connect_error=None, start_error=None, stop_error=None
    ):
        self.config = config
        self.calls = []
        self.connect_error = connect_error
        self.start_error = start_error
        self.stop_error = stop_error

    async def connect(self):
        if self.connect_error is not None:
            raise self.connect_error
        self.calls.append("connect")

    async def start_background_task(self):
        if self.start_error is not None:
            raise self.start_error
        self.calls.append("start_background_task")

    async def stop_background_task(self):
        if self.stop_error is not None:
            raise self.stop_error
        self.calls.append("stop_background_task")


class _RecordingManagerFactory:
    """Class seam for server_module.WebSocketManager (server.py:658).

    Counts constructions per test (a fresh factory per _install_stubs call,
    so no shared state) and keeps the config identity of every instance.
    """

    def __init__(self, bag):
        self._bag = bag

    def __call__(self, config):
        manager = FakeWebSocketManager(config=config)
        self._bag.manager_instances.append(manager)
        return manager


class FakeStdioTransport:
    """Fail-loud stand-in for mcp.server.stdio.stdio_server patched as the
    REAL module attribute (contract seam). main() enters it once
    (server.py:703); the fake records the call and can raise from
    __aenter__ (the KeyboardInterrupt injection point - see divergence 1 in
    the module docstring)."""

    def __init__(self):
        self.calls = 0
        self.exits = 0
        self.enter_error = None
        self.reader = object()
        self.writer = object()

    def __call__(self):
        self.calls += 1
        return self

    async def __aenter__(self):
        if self.enter_error is not None:
            raise self.enter_error
        return self.reader, self.writer

    async def __aexit__(self, exc_type, exc, tb):
        self.exits += 1
        return False


class FakeServerObject:
    """Fail-loud stand-in for the module-level mcp Server instance
    (server.py:59) - main() awaits server.run(...) and calls
    server.create_initialization_options() (server.py:710-716).

    behavior="wait": block until the graceful-shutdown cancellation (the
    cancellation is RECORDED and re-raised, mirroring a well-behaved task);
    behavior="value_error": raise ValueError on the first step.
    A KeyboardInterrupt here is NOT offered as a behavior: raised inside a
    nested task it escapes the event loop and kills it (divergence 1).
    """

    def __init__(self, behavior="wait"):
        self.behavior = behavior
        self.run_calls = []
        self.cancelled = 0
        self.init_options = {"marker": "init-options"}

    def create_initialization_options(self):
        return self.init_options

    async def run(self, read_stream, write_stream, init_options):
        self.run_calls.append((read_stream, write_stream, init_options))
        if self.behavior == "value_error":
            raise ValueError("server boom")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


# ---------------------------------------------------------------------------
# Config factory (explicit kwargs + _env_file=None - P-0035/L-0130)
# ---------------------------------------------------------------------------
def make_config(**overrides):
    """Real PolymarketConfig built by explicit kwargs.

    The synthetic key is VALID non-zero hex (the T-0030 validator rejects
    all-zero keys, house pattern); the client is faked, so the key never
    signs anything and never touches the network.
    """
    base = dict(
        POLYGON_PRIVATE_KEY="0" * 63 + "1",
        POLYGON_ADDRESS="0x" + "0" * 40,
        POLYMARKET_CHAIN_ID=137,
        _env_file=None,
    )
    base.update(overrides)
    return PolymarketConfig(**base)


# ---------------------------------------------------------------------------
# Seam installers (L-0133/P-0031: EVERY seam patched BEFORE any call)
# ---------------------------------------------------------------------------
def _install_stubs(
    monkeypatch,
    *,
    has_credentials,
    creation_fails=False,
    creation_succeeds=False,
    load_config_error=None,
):
    """Patch every I/O seam of initialize_server BEFORE any call.

    Real objects stay real (offline-safe, per contract): the config, the
    SafetyLimits factory and the rate-limiter singleton - they prove the
    WIRING with real objects. Everything that can touch the network or the
    process is faked: load_config, create_polymarket_client (the real one
    builds a ClobClient), the client's credential surface and the
    WebSocketManager class (the real manager's connect() dials wss://).
    """
    config = make_config(**(_CREDS_KWARGS if has_credentials else {}))
    client = FakeClient(
        has_credentials=has_credentials,
        creation_fails=creation_fails,
        creation_succeeds=creation_succeeds,
    )
    bag = SimpleNamespace(
        config=config,
        client=client,
        load_config_calls=0,
        client_factory_calls=[],
        manager_instances=[],
    )

    def fake_load_config():
        bag.load_config_calls += 1
        if load_config_error is not None:
            raise load_config_error
        return config

    def fake_create_polymarket_client(**kwargs):
        bag.client_factory_calls.append(dict(kwargs))
        return client

    monkeypatch.setattr(server_module, "load_config", fake_load_config)
    monkeypatch.setattr(
        server_module, "create_polymarket_client", fake_create_polymarket_client
    )
    monkeypatch.setattr(server_module, "WebSocketManager", _RecordingManagerFactory(bag))
    return bag


def _install_main_stubs(monkeypatch, *, behavior="wait", enter_error=None):
    """Patch every seam of main() BEFORE the call (L-0133).

    initialize_server is faked (main's own logic is the object under test
    here; the init wiring is covered by the _install_stubs tests). The stdio
    transport is patched as an ATTRIBUTE of the real mcp.server.stdio
    module (contract seam); signal.signal is patched on the real signal
    module with a recorder so the process never gets a live SIGTERM/SIGINT
    handler installed by a test (order-independence, L-0099).
    """
    bag = SimpleNamespace(
        stdio=FakeStdioTransport(),
        fake_server=FakeServerObject(behavior=behavior),
        signal_calls=[],
        initialize_calls=0,
    )
    if enter_error is not None:
        bag.stdio.enter_error = enter_error

    async def fake_initialize_server():
        bag.initialize_calls += 1

    def fake_signal(signum, handler):
        bag.signal_calls.append((signum, handler))
        return None

    monkeypatch.setattr(server_module, "initialize_server", fake_initialize_server)
    monkeypatch.setattr(signal, "signal", fake_signal)
    monkeypatch.setattr("mcp.server.stdio.stdio_server", bag.stdio)
    monkeypatch.setattr(server_module, "server", bag.fake_server)
    return bag


async def _drain_background_tasks():
    """Await every task still registered in _background_tasks.

    Called after every initialize_server() run (contract: drain so no
    orphan-task warning leaks into the run). The done-callback installed at
    server.py:663 discards completed tasks, so after the drain the set is
    empty - a property test 14 pins explicitly.
    """
    for task in list(server_module._background_tasks):
        await task


def _messages(caplog):
    """Extract record messages in emission order (L-0020: assert the
    observed log text; caplog preserves order, so ordering pins are
    mechanical)."""
    return [record.message for record in caplog.records]


# =====================================================================
# _start_websocket (server.py:291-297)
# =====================================================================


async def test_start_websocket_connects_then_starts_background_task(caplog):
    """_start_websocket connects the manager FIRST and starts its
    background task SECOND (server.py:294-295) - the ORDER is the pin (the
    code comment at server.py:659-660 requires connect before the loop,
    otherwise subscriptions never receive messages; mutation M2 removes
    the connect call and breaks this pin). The fake records the ordered
    event log."""
    manager = FakeWebSocketManager()

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module._start_websocket(manager)

    assert manager.calls == ["connect", "start_background_task"]
    assert not any("WebSocket startup failed" in m for m in _messages(caplog))


async def test_start_websocket_connect_error_logged_not_raised(caplog):
    """A connect failure inside _start_websocket is logged
    ("WebSocket startup failed", server.py:297) and NOT re-raised (server.py:296-297
    swallows it) - the par contraditorio with the REAL manager, whose
    connect() propagates dial failures (T-0051). start_background_task is
    never reached after the failed connect."""
    manager = FakeWebSocketManager(connect_error=ConnectionError("dial refused"))

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module._start_websocket(manager)

    assert manager.calls == [], "no call may be recorded after a failed connect"
    assert any(
        record.levelno == logging.ERROR and "WebSocket startup failed" in record.message
        for record in caplog.records
    )


async def test_start_websocket_start_error_logged_not_raised(caplog):
    """COMPLEMENTARY (same except, second entry path): a failure from
    start_background_task AFTER a successful connect is also swallowed and
    logged (server.py:296-297) - the startup never propagates, so the server
    keeps running read-only."""
    manager = FakeWebSocketManager(start_error=RuntimeError("loop refused"))

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module._start_websocket(manager)

    assert manager.calls == ["connect"], "the successful connect is recorded"
    assert any(
        record.levelno == logging.ERROR and "WebSocket startup failed" in record.message
        for record in caplog.records
    )


# =====================================================================
# shutdown (server.py:300-335)
# =====================================================================


async def test_shutdown_cancels_orders_with_credentials_when_enabled(monkeypatch, caplog):
    """With CANCEL_ON_SHUTDOWN ABSENT (the code default "true", server.py:310)
    and a credentialed client, shutdown() cancels all open orders exactly
    once (server.py:313-319). The env-ABSENT run is mutation M1's target: a
    flipped default ("false") routes this credentialed client into the
    disabled skip branch instead."""
    monkeypatch.delenv("CANCEL_ON_SHUTDOWN", raising=False)
    client = FakeClient(has_credentials=True)
    monkeypatch.setattr(server_module, "polymarket_client", client)
    monkeypatch.setattr(server_module, "websocket_manager", None)

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.shutdown()

    assert client.cancel_all_orders_calls == 1
    assert client.has_api_credentials_calls >= 1, "the gate must consult the client"
    messages = _messages(caplog)
    assert "Canceling all open orders..." in messages
    assert "All open orders canceled successfully" in messages
    assert "Graceful shutdown complete" in messages


async def test_shutdown_skips_cancellation_without_credentials(monkeypatch, caplog):
    """With CANCEL_ON_SHUTDOWN absent (default "true") but a client WITHOUT
    credentials, shutdown() logs the credentials skip and NEVER calls
    cancel_all_orders (server.py:320-321). Same env as the credentialed test
    above - the client's credential state is what moves the branch
    (par contraditorio of the credential gate)."""
    monkeypatch.delenv("CANCEL_ON_SHUTDOWN", raising=False)
    client = FakeClient(has_credentials=False)
    monkeypatch.setattr(server_module, "polymarket_client", client)
    monkeypatch.setattr(server_module, "websocket_manager", None)

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.shutdown()

    assert client.cancel_all_orders_calls == 0
    assert client.has_api_credentials_calls >= 1
    assert "Skipping order cancellation (no API credentials)" in _messages(caplog)


async def test_shutdown_disabled_by_env_never_cancels(monkeypatch, caplog):
    """With CANCEL_ON_SHUTDOWN explicitly "false", shutdown() NEVER cancels
    orders - even for a CREDENTIALED client (server.py:322-323). Par
    contraditorio with the credentialed test above: identical client, only
    the env differs, and the env gate precedes the credential gate."""
    monkeypatch.setenv("CANCEL_ON_SHUTDOWN", "false")
    client = FakeClient(has_credentials=True)
    monkeypatch.setattr(server_module, "polymarket_client", client)
    monkeypatch.setattr(server_module, "websocket_manager", None)

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.shutdown()

    assert client.cancel_all_orders_calls == 0
    assert "Skipping order cancellation (CANCEL_ON_SHUTDOWN=false)" in _messages(caplog)


async def test_shutdown_survives_cancel_all_orders_failure(monkeypatch, caplog):
    """A cancel_all_orders failure is logged ("Failed to cancel orders
    during shutdown", server.py:319) and shutdown() CONTINUES: the websocket
    manager still gets stop_background_task (server.py:326-333) and the final
    log is reached - the shutdown is fail-safe, nothing propagates."""
    monkeypatch.delenv("CANCEL_ON_SHUTDOWN", raising=False)
    client = FakeClient(has_credentials=True, cancel_error=RuntimeError("clob unreachable"))
    manager = FakeWebSocketManager()
    monkeypatch.setattr(server_module, "polymarket_client", client)
    monkeypatch.setattr(server_module, "websocket_manager", manager)

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.shutdown()

    assert client.cancel_all_orders_calls == 1
    assert manager.calls == ["stop_background_task"], "fail-safe: ws close still runs"
    messages = _messages(caplog)
    assert any(
        record.levelno == logging.ERROR
        and "Failed to cancel orders during shutdown" in record.message
        for record in caplog.records
    )
    assert "Graceful shutdown complete" in messages


async def test_shutdown_closes_websocket_manager(monkeypatch, caplog):
    """With a websocket manager present, shutdown() stops its background
    task exactly once and logs both ends of the close (server.py:326-333)."""
    monkeypatch.delenv("CANCEL_ON_SHUTDOWN", raising=False)
    monkeypatch.setattr(server_module, "polymarket_client", None)
    manager = FakeWebSocketManager()
    monkeypatch.setattr(server_module, "websocket_manager", manager)

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.shutdown()

    assert manager.calls == ["stop_background_task"]
    messages = _messages(caplog)
    assert "Closing WebSocket connections..." in messages
    assert "WebSocket connections closed" in messages
    assert "Graceful shutdown complete" in messages


async def test_shutdown_tolerates_websocket_close_failure(monkeypatch, caplog):
    """A websocket close failure is logged ("Failed to close WebSocket
    connections", server.py:332-333) and shutdown() still completes normally
    (server.py:335 reached) - nothing propagates from the shutdown path."""
    monkeypatch.delenv("CANCEL_ON_SHUTDOWN", raising=False)
    monkeypatch.setattr(server_module, "polymarket_client", None)
    manager = FakeWebSocketManager(stop_error=RuntimeError("ws stop refused"))
    monkeypatch.setattr(server_module, "websocket_manager", manager)

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.shutdown()

    assert any(
        record.levelno == logging.ERROR
        and "Failed to close WebSocket connections" in record.message
        for record in caplog.records
    )
    assert "Graceful shutdown complete" in _messages(caplog)


async def test_shutdown_without_websocket_manager_is_noop(monkeypatch, caplog):
    """COMPLEMENTARY: with websocket_manager at its pre-init None the close
    block is skipped silently (server.py:326-333 unentered) and shutdown()
    still completes - no error, no call, final log reached."""
    monkeypatch.delenv("CANCEL_ON_SHUTDOWN", raising=False)
    monkeypatch.setattr(server_module, "polymarket_client", None)
    monkeypatch.setattr(server_module, "websocket_manager", None)

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.shutdown()

    assert "Graceful shutdown complete" in _messages(caplog)
    assert not any("Failed to close WebSocket" in m for m in _messages(caplog))

# =====================================================================
# initialize_server (server.py:582-680)
# =====================================================================


async def test_initialize_server_read_only_mode_without_credentials(monkeypatch, caplog):
    """No credentials + a FAILING create_api_credentials ends in READ-ONLY
    mode: the end-state pin (server.py:617-634, :644-654, :669-676) -
    trading_tools stays None, safety_limits is the REAL SafetyLimits built
    from the config, the ws manager is constructed with the SAME config and
    is connected after the drain (server.py:656-664). The root logger level
    was set from the config (server.py:601) - restored by the fixture."""
    bag = _install_stubs(monkeypatch, has_credentials=False, creation_fails=True)
    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.initialize_server()
    await _drain_background_tasks()

    messages = _messages(caplog)
    assert bag.client.create_api_credentials_calls == 1
    assert server_module.trading_tools is None
    assert isinstance(server_module.safety_limits, SafetyLimits)
    assert (
        server_module.safety_limits.max_order_size_usd == bag.config.MAX_ORDER_SIZE_USD
    ), "the limits are built FROM the config (wiring with real objects)"
    assert bag.manager_instances, "the ws manager must be constructed even read-only"
    manager = bag.manager_instances[0]
    assert manager.config is bag.config
    assert server_module.websocket_manager is manager
    assert manager.calls == ["connect", "start_background_task"]
    assert "Continuing in READ-ONLY mode" in messages
    assert "Mode: READ-ONLY (no API credentials)" in messages
    assert (
        "Available tools: 25 total (8 Discovery, 10 Analysis, 7 Real-time)" in messages
    )
    assert (
        "Trading tools NOT initialized (no API credentials - read-only mode)" in messages
    )
    assert logging.getLogger().level == logging.INFO, (
        "server.py:601 set the root level from config.LOG_LEVEL (INFO); the "
        "fixture restores the pre-test level afterwards"
    )


async def test_initialize_server_credential_creation_failure_falls_back_readonly(
    monkeypatch, caplog
):
    """The FALLBACK MECHANISM pin (server.py:617-634): a failing
    create_api_credentials is swallowed - initialize_server RETURNS instead
    of propagating (par contraditorio with the config-failure test below,
    where the failure re-raises) and initialization CONTINUES past the
    failure: warning logged, read-only availability logs, safety limits and
    the ws manager still constructed."""
    bag = _install_stubs(monkeypatch, has_credentials=False, creation_fails=True)
    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.initialize_server()
    await _drain_background_tasks()

    messages = _messages(caplog)
    assert bag.client.create_api_credentials_calls == 1
    warning_records = [
        record for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert any(
        "Could not create API credentials" in record.message
        for record in warning_records
    )
    assert isinstance(server_module.safety_limits, SafetyLimits)
    assert bag.manager_instances, "init continues past the failure to the ws wiring"
    assert server_module.trading_tools is None
    assert "Continuing in READ-ONLY mode" in messages
    assert "Available: Market Discovery (8 tools) + Market Analysis (10 tools)" in messages
    assert "Unavailable: Trading (12 tools) + Portfolio (8 tools)" in messages
    assert (
        "To enable trading, fund your wallet or configure existing API credentials"
        in messages
    )


async def test_initialize_server_credential_creation_success_initializes_trading(
    monkeypatch, caplog
):
    """A SUCCESSFUL create_api_credentials flips the client to credentialed
    (server.py:617-628) and initialization continues to the trading gate
    (server.py:644-652): the REAL TradingTools is constructed with the SAME
    fake client, the SAME safety limits object and the SAME config (identity
    pins, L-0128(g)). R8: only the FLOW is pinned here (creation exactly
    once, api_creds consulted, trading initialized after) - the DEBUG
    api_key/passphrase fragments at server.py:627-628 are NEVER asserted."""
    bag = _install_stubs(
        monkeypatch, has_credentials=False, creation_succeeds=True
    )
    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.initialize_server()
    await _drain_background_tasks()

    messages = _messages(caplog)
    assert bag.client.create_api_credentials_calls == 1
    assert bag.client.api_creds_reads >= 1, "api_creds consulted after creation"
    tools = server_module.trading_tools
    assert isinstance(tools, TradingTools)
    assert tools.client is bag.client, "the trading tools received the SAME client"
    assert tools.config is server_module.config, "identity: the same config object"
    assert (
        tools.safety_limits is server_module.safety_limits
    ), "identity: the same safety limits object"
    assert (
        "API credentials created successfully! Save these to your .env file for future use."
        in messages
    )
    assert "Mode: FULL (authenticated)" in messages
    assert (
        "Available tools: 45 total (8 Discovery, 10 Analysis, "
        "12 Trading, 8 Portfolio, 7 Real-time)" in messages
    )


async def test_initialize_server_with_credentials_initializes_trading_tools(
    monkeypatch, caplog
):
    """An ALREADY-credentialed client skips the creation flow entirely
    (create_api_credentials is NEVER called, server.py:617-634 unentered)
    and goes straight to trading initialization (server.py:644-652) with the
    factory receiving the config's values as EXACT kwargs (L-0128(g)
    signature pin)."""
    bag = _install_stubs(monkeypatch, has_credentials=True)
    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.initialize_server()
    await _drain_background_tasks()

    messages = _messages(caplog)
    assert bag.client.create_api_credentials_calls == 0, (
        "already credentialed: creation is never attempted"
    )
    expected_kwargs = {
        "private_key": bag.config.POLYGON_PRIVATE_KEY,
        "address": bag.config.POLYGON_ADDRESS,
        "chain_id": bag.config.POLYMARKET_CHAIN_ID,
        "api_key": bag.config.POLYMARKET_API_KEY,
        "api_secret": bag.config.POLYMARKET_API_SECRET,
        "passphrase": bag.config.POLYMARKET_PASSPHRASE,
    }
    assert bag.client_factory_calls == [expected_kwargs], (
        "the client factory receives exactly the config values (L-0128(g))"
    )
    tools = server_module.trading_tools
    assert isinstance(tools, TradingTools)
    assert tools.client is bag.client
    assert "No API credentials found" not in messages, "the creation branch is skipped"
    assert "Mode: FULL (authenticated)" in messages


async def test_initialize_server_config_failure_propagates(monkeypatch, caplog):
    """A load_config failure is logged ("Failed to initialize server",
    server.py:679) and RE-RAISED (server.py:680) - the ORIGINAL exception
    object propagates to the caller (identity pin: the except's bare raise
    does not wrap). Par contraditorio with the creation-failure fallback,
    which swallows its exception. Nothing after load_config runs."""
    error = ValueError("invalid configuration")
    bag = _install_stubs(monkeypatch, has_credentials=False, load_config_error=error)
    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        with pytest.raises(ValueError, match="invalid configuration") as excinfo:
            await server_module.initialize_server()

    assert excinfo.value is error, "the original exception object is re-raised"
    assert any(
        "Failed to initialize server: invalid configuration" in record.message
        for record in caplog.records
    )
    assert bag.client_factory_calls == [], "the failure happens before client creation"
    assert server_module.trading_tools is None
    assert bag.manager_instances == [], "the ws wiring is never reached"
    assert server_module._background_tasks == set()


async def test_initialize_server_websocket_manager_wired_and_connected(monkeypatch, caplog):
    """The ws wiring pin (server.py:656-664): exactly ONE manager is
    constructed with the SAME config object, the startup task is registered
    in _background_tasks, and after the drain the manager was connected and
    its background task started IN ORDER (connect BEFORE start - mutation
    M2 target) and the done-callback discarded the task from the set."""
    bag = _install_stubs(monkeypatch, has_credentials=True)
    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.initialize_server()

    assert len(bag.manager_instances) == 1
    manager = bag.manager_instances[0]
    assert manager.config is bag.config, "constructed with the SAME config object"
    assert server_module.websocket_manager is manager
    assert "WebSocket manager initialized with 7 real-time tools" in _messages(caplog)

    await _drain_background_tasks()
    assert manager.calls == ["connect", "start_background_task"]
    assert server_module._background_tasks == set(), (
        "the done-callback (server.py:663) discarded the completed task"
    )


# =====================================================================
# main (server.py:683-745)
# =====================================================================


async def test_main_graceful_shutdown_event_cancels_server_task(monkeypatch, caplog):
    """The graceful path (server.py:703-735): main creates the shutdown
    event, registers SIGTERM/SIGINT with _signal_handler (recorder - never a
    live handler), wraps the stdio reader in _PreHandshakeStream (the
    pre-handshake protocol layer of T-0046, server.py:708 - the class keeps
    _read_stream :144 and _write_stream :145) and runs the server task
    alongside the event watcher; setting the event from OUTSIDE completes
    the watcher first, the server task is CANCELLED through the pending loop
    (server.py:725-731) and shutdown() runs in the finally
    (server.py:742-744) - with CANCEL_ON_SHUTDOWN=false the credentialed
    client is NOT asked to cancel (env gate). The run-call pin is SEMANTIC
    (r2 fix): the wrapper MUST carry the transport reader/writer, the RAW
    writer and the init options pass through by identity - removing the
    wrapper or breaking the wiring fails loudly (AttributeError/is-fails)."""
    monkeypatch.setenv("CANCEL_ON_SHUTDOWN", "false")
    client = FakeClient(has_credentials=True)
    monkeypatch.setattr(server_module, "polymarket_client", client)
    monkeypatch.setattr(server_module, "websocket_manager", None)
    bag = _install_main_stubs(monkeypatch, behavior="wait")

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        main_task = asyncio.create_task(server_module.main())
        for _ in range(100):
            if server_module._shutdown_event is not None:
                break
            await asyncio.sleep(0)
        assert server_module._shutdown_event is not None, "main must create the event"
        server_module._shutdown_event.set()
        await main_task  # completes without raising

    assert bag.initialize_calls == 1
    assert bag.fake_server.cancelled == 1, "the event cancels the server task"
    assert len(bag.fake_server.run_calls) == 1, (
        "the server task ran exactly once"
    )
    wrapped_reader, run_writer, run_options = bag.fake_server.run_calls[0]
    assert wrapped_reader._read_stream is bag.stdio.reader, (
        "main wraps the raw reader in _PreHandshakeStream (server.py:708) "
        "whose _read_stream is the transport reader (server.py:144)"
    )
    assert wrapped_reader._write_stream is bag.stdio.writer, (
        "the wrapper keeps the transport writer too (server.py:145)"
    )
    assert run_writer is bag.stdio.writer, (
        "the RAW writer reaches Server.run unwrapped (server.py:711-716)"
    )
    assert run_options is bag.fake_server.init_options, (
        "the initialization options pass through by identity (server.py:714)"
    )
    assert (signal.SIGTERM, server_module._signal_handler) in bag.signal_calls
    assert (signal.SIGINT, server_module._signal_handler) in bag.signal_calls
    assert bag.stdio.exits == 1, "the transport context exits normally"
    assert client.cancel_all_orders_calls == 0, "env gate: false overrides credentials"
    messages = _messages(caplog)
    assert "Starting MCP server..." in messages
    assert "Graceful shutdown initiated..." in messages
    assert "Graceful shutdown complete" in messages


async def test_main_server_exception_propagates_after_shutdown(monkeypatch, caplog):
    """An exception from the server task is re-raised to the caller
    (server.py:734-735 -> :739-741) AFTER the finally's shutdown() ran
    (server.py:742-744): the exception surfaces LAST. Log order proves the
    sequence: "Server error" (except) BEFORE "Graceful shutdown initiated"
    (finally), and "Graceful shutdown complete" is already in the log when
    pytest.raises catches the ValueError."""
    monkeypatch.setenv("CANCEL_ON_SHUTDOWN", "false")
    monkeypatch.setattr(server_module, "polymarket_client", None)
    monkeypatch.setattr(server_module, "websocket_manager", None)
    bag = _install_main_stubs(monkeypatch, behavior="value_error")

    main_task = asyncio.create_task(server_module.main())
    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        with pytest.raises(ValueError, match="server boom"):
            await main_task

    messages = _messages(caplog)
    assert "Server error: server boom" in messages
    assert "Graceful shutdown initiated..." in messages
    assert "Graceful shutdown complete" in messages
    assert messages.index("Server error: server boom") < messages.index(
        "Graceful shutdown initiated..."
    ), "the except logs BEFORE the finally's shutdown runs"
    assert bag.fake_server.cancelled == 0, "the server task failed, it was not cancelled"
    assert bag.stdio.exits == 1, "the transport context exits before the finally"


async def test_main_keyboard_interrupt_logged_and_shutdown_still_runs(monkeypatch, caplog):
    """The KeyboardInterrupt branch (server.py:737-738): the interrupt is
    caught, logged ("Server stopped by user (KeyboardInterrupt)"), main()
    COMPLETES and the finally's shutdown() still ran.

    DIVERGENCE (declared, L-0025/L-0043): the contract prescribed the fake
    server.run raising KeyboardInterrupt - observed reality (proven with this
    repo's venv): a KeyboardInterrupt raised inside a NESTED task escapes the
    event loop and kills it BEFORE main's except can run, so the injection
    point is the fake stdio transport's __aenter__ - a DIRECT await in
    main()'s own frame - reaching the SAME branch with the same observables."""
    monkeypatch.setenv("CANCEL_ON_SHUTDOWN", "false")
    monkeypatch.setattr(server_module, "polymarket_client", None)
    monkeypatch.setattr(server_module, "websocket_manager", None)
    bag = _install_main_stubs(monkeypatch, enter_error=KeyboardInterrupt("simulated Ctrl-C"))

    main_task = asyncio.create_task(server_module.main())
    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await main_task  # must complete without raising

    messages = _messages(caplog)
    assert "Server stopped by user (KeyboardInterrupt)" in messages
    assert "Graceful shutdown complete" in messages
    assert not any("Server error:" in m for m in messages), (
        "the KeyboardInterrupt branch, not the generic except"
    )
    assert bag.stdio.calls == 1
    assert bag.stdio.exits == 0, "aenter raised, so aexit never ran (CM protocol)"
    assert (signal.SIGTERM, server_module._signal_handler) in bag.signal_calls
    assert (signal.SIGINT, server_module._signal_handler) in bag.signal_calls


# =====================================================================
# run (server.py:747-749)
# =====================================================================


def test_run_entrypoint_uses_asyncio_run(monkeypatch):
    """The synchronous entry point delegates EXACTLY once to asyncio.run
    with the main() coroutine (server.py:749). The patched asyncio.run
    captures the coroutine and closes it WITHOUT running it - no loop is
    started and no "never awaited" warning is emitted."""
    coros = []

    def fake_asyncio_run(coro, **kwargs):
        coros.append(coro)
        return None

    monkeypatch.setattr(asyncio, "run", fake_asyncio_run)
    server_module.run()

    assert len(coros) == 1
    assert coros[0].__name__ == "main"
    coros[0].close()  # close without running: no orphan coroutine warning
