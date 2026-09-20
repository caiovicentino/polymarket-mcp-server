"""Offline pin suite: the 7 residual raw-exception error logs never carry
hex material (T-0414).

Closes the residual DECLARED by the canonical suite
(tests/test_init_error_sanitization_offline.py: "Other error logs
(discover / tool-call / shutdown) are out of scope"): since T-0092 the hex
sanitizer (_safe_error_message, L-0155/T-0061) only guarded the
initialize_server funnel (:734). A ValidationError/ValueError/httpx error
carrying key, wallet or token material on the other exception paths would
hit the server log VERBATIM. This slice applies the SAME helper, the SAME
threshold (16 hex) and ZERO semantic change beyond the log argument:
exceptions stay re-raised / converted / swallowed by identity, the
except/finally bodies are untouched, and every existing prefix pin survives
by construction (the helper preserves the literal prefix and passes
hex-free messages through byte-identically).

Sites covered (fresh inventory 2026-09-20 @ origin/main 1d146e3):
1. "server/discover failed"      (:288, _PreHandshakeStream._respond_discover)
2. "WebSocket startup failed"    (:321, _start_websocket)
3. "Failed to cancel orders during shutdown" (:343, shutdown)
4. "Failed to close WebSocket connections"   (:357, shutdown)
5. "Tool call failed"            (:619, call_tool)
6. "Could not create API credentials" (:682, initialize_server, WARNING)
7. "Server error"                (:820, main)

Out of scope (unchanged, declared): the R8 credential DEBUG sites
(logger.debug of api_key[:8] / api_passphrase[:8]) are a SEPARATE
human-owned fix; the discover JSON-RPC error message_text keeps the raw
exception (the redaction contract of this slice is the LOG surface only);
the tool-call error envelope keeps str(e) (same class, outside the log
argument). Legitimate hex in tool errors (condition_ids, wallets) gets
masked like :734 since T-0092 - REGISTER tradeoff, accepted by the same
gates.

Pins preserved (compatibility proof, L-0023):
- tests/test_prehandshake_interceptor_offline.py:148 pins
  startswith("server/discover failed: ") - the helper preserves the prefix;
- tests/test_server_lifecycle_offline.py pins the literal prefixes
  "WebSocket startup failed" / "Failed to cancel orders during shutdown" /
  "Failed to close WebSocket connections" via `in record.message` and
  "Server error: server boom" - all preserved;
- test_init_error_sanitization_offline.py (the canonical suite) does not
  change: its docstring declares THIS residual and this suite covers
  exactly that residual.

Anti-fix probes (report evidence, outside acceptance; mutated copy in a
temp dir, L-0016):
- M1: a call-site reverted to plain {e} -> the masked integration pin for
  that site fails (the raw 64-hex key + 23-hex run appear in the log);
- M2: _safe_error_message turned into a pass-through -> every masked pin
  fails AND the unit redact pins fail;
- M3: threshold 16 -> 32 -> the 23-hex run survives -> masked pins fail;
  the 15/16 boundary pin catches drift at exactly 16.

RED pre-fix (L-0025): the masked pins FAIL before the 7 call-site edits
(the raw hex runs appear in the logged messages) and PASS after; the
pass-through pins PASS both before and after (the plain path was never
broken).

Hermeticity (P-0029): zero network by construction - the real
WebSocketManager class is never constructed (instance-level fakes per the
lifecycle suite pattern), the real PolymarketClient is never constructed,
and the pre-handshake stream is an anyio.MemoryObjectStream (zero
network). Env-sourced config fields are stripped by the clean_env autouse
fixture (P-0035/L-0130); CANCEL_ON_SHUTDOWN is controlled explicitly per
test. Order-independence (L-0099): module globals reset to the pre-init
state and the root logger level restored around every test.
"""
import asyncio
import json
import logging
import os
import re
import signal
from types import SimpleNamespace

import anyio
import mcp.types as types
import pytest

from polymarket_mcp import server as server_module
from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.utils.safety_limits import SafetyLimits

SERVER_LOGGER = "polymarket_mcp.server"

# Same material class as the canonical suite: a 64-char key and a 23-char
# echo run (pydantic renders a malformed key as two ~23-hex-char runs).
HEX_64 = "ab" * 32
RUN_23 = "73b1c5c0f1c78b7a91f2e0a"
HEX_RUN_RE = re.compile(r"[0-9a-fA-F]{16,}")

# Process env names/prefixes that feed PolymarketConfig fields, stripped by
# the autouse fixture (P-0035 house pattern), PLUS CANCEL_ON_SHUTDOWN: the
# shutdown path reads it directly via os.getenv, so it is controlled
# explicitly per test.
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

# Module globals the tested functions touch - reset to the pre-init state
# and restored by the autouse fixture (L-0099). _signal_loop is included:
# main() sets it to the test's own loop (:769, T-0398) and the dispatch
# suite's _signal_handler pin calls _signal_loop.create_task on it - a
# stale closed loop would crash that sibling test (restored to the original
# None by monkeypatch after every test here).
_LIFECYCLE_GLOBALS = (
    "config",
    "polymarket_client",
    "safety_limits",
    "trading_tools",
    "websocket_manager",
    "_shutdown_event",
    "_signal_loop",
)


# ---------------------------------------------------------------------------
# Hermeticity + order-independence (autouse fixtures)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip config-sourced env vars so tests never observe the host env.

    Pydantic BaseSettings reads the HOST env for every field not passed
    explicitly even with _env_file=None (L-0130); without this fixture a
    hostile host POLYMARKET_API_SECRET etc. would leak into assertion
    diffs. CANCEL_ON_SHUTDOWN is stripped too: every shutdown-path test
    controls it explicitly (absent = the code default "true").
    """
    for name in list(os.environ):
        if any(name.startswith(prefix) for prefix in _ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def pristine_server_state(monkeypatch):
    """Order-independence (L-0099): every test starts and ends at the
    pre-init state.

    The globals the tested functions touch are set to their documented
    pre-init values and monkeypatch restores the ORIGINAL values after the
    test, so sibling suites that share this pytest process are never
    affected. _background_tasks is replaced by a FRESH set per test.
    initialize_server mutates the ROOT logger level - saved and restored
    here because it is process-global state outside monkeypatch's reach.
    """
    monkeypatch.setattr(server_module, "_background_tasks", set())
    for name in _LIFECYCLE_GLOBALS:
        monkeypatch.setattr(server_module, name, None)
    root_logger = logging.getLogger()
    original_level = root_logger.level
    yield
    root_logger.setLevel(original_level)


# ---------------------------------------------------------------------------
# Hex material + masked-pin oracle (same material class as the canonical
# suite: 64-char key + 23-char echo run)
# ---------------------------------------------------------------------------
def _hex_error():
    """An exception carrying BOTH the 64-char key and the 23-char run."""
    return RuntimeError(f"key={HEX_64} run={RUN_23} boom")


def _messages(caplog):
    """Extract record messages in emission order (caplog preserves order)."""
    return [record.message for record in caplog.records]


def _pick_record(caplog, prefix, level=None):
    """The ONE record with the site prefix (exactly-one assert)."""
    records = [
        record
        for record in caplog.records
        if record.message.startswith(prefix)
        and (level is None or record.levelno == level)
    ]
    (record,) = records
    return record


def _assert_masked(record, prefix):
    """The masked-site oracle: literal prefix preserved, both runs
    redacted, ZERO raw 16+ hex run in the logged message (L-0023)."""
    message = record.message
    assert message.startswith(prefix), message
    assert f"[REDACTED:{len(HEX_64)} hex chars]" in message, message
    assert f"[REDACTED:{len(RUN_23)} hex chars]" in message, message
    assert HEX_RUN_RE.search(message) is None, message
    assert HEX_64 not in message, message
    assert RUN_23 not in message, message


def _assert_plain(record, expected_full):
    """The pass-through oracle: the hex-free message is byte-identical."""
    assert record.message == expected_full, record.message


# ---------------------------------------------------------------------------
# Fakes (instance-level, zero class-level mutable state - L-0099)
# ---------------------------------------------------------------------------
class FakeWebSocketManager:
    """Recorder for the WebSocketManager surface the tested lifecycle
    functions touch: connect / start_background_task / stop_background_task
    (async no-op recorders, per-failure injection, fail-loud otherwise)."""

    def __init__(self, config=None, *, connect_error=None, stop_error=None):
        self.config = config
        self.calls = []
        self.connect_error = connect_error
        self.stop_error = stop_error

    async def connect(self):
        if self.connect_error is not None:
            raise self.connect_error
        self.calls.append("connect")

    async def start_background_task(self):
        self.calls.append("start_background_task")

    async def stop_background_task(self):
        if self.stop_error is not None:
            raise self.stop_error
        self.calls.append("stop_background_task")


class _RecordingManagerFactory:
    """Class seam for server_module.WebSocketManager during
    initialize_server: counts constructions per test and keeps the config
    identity of every instance."""

    def __init__(self, bag):
        self._bag = bag

    def __call__(self, config):
        manager = FakeWebSocketManager(config=config)
        self._bag.manager_instances.append(manager)
        return manager


class FakeClient:
    """Duck-typed PolymarketClient stand-in for the shutdown and
    credential-creation surfaces only: has_api_credentials(),
    cancel_all_orders() and create_api_credentials(). Anything else raises
    loudly (fail-loud seams, P-0031). Synthetic strings only (R8 red
    line)."""

    def __init__(self, *, has_credentials, cancel_error=None, creation_error=None):
        self._has_credentials = has_credentials
        self.cancel_error = cancel_error
        self.creation_error = creation_error
        self.cancel_all_orders_calls = 0
        self.create_api_credentials_calls = 0

    def has_api_credentials(self) -> bool:
        return self._has_credentials

    async def cancel_all_orders(self):
        self.cancel_all_orders_calls += 1
        if self.cancel_error is not None:
            raise self.cancel_error
        return {"canceled": 0}

    async def create_api_credentials(self):
        self.create_api_credentials_calls += 1
        if self.creation_error is not None:
            raise self.creation_error
        return SimpleNamespace(
            api_key="synthetic-key-000000",
            api_passphrase="synthetic-pass-000",
        )


class HexRaisingTradingTools:
    """Trading fake whose create_limit_order raises the injected error -
    exercises the tool-call catch-all log (:619) without any real
    network/client code (dispatch-suite pattern)."""

    def __init__(self, message):
        self._message = message
        self.calls = []

    async def create_limit_order(self, **kwargs):
        self.calls.append(("create_limit_order", dict(kwargs)))
        raise RuntimeError(self._message)


class FakeStdioTransport:
    """Fail-loud stand-in for mcp.server.stdio.stdio_server patched as the
    REAL module attribute (contract seam, lifecycle-suite pattern)."""

    def __init__(self):
        self.calls = 0
        self.exits = 0
        self.reader = object()
        self.writer = object()

    def __call__(self):
        self.calls += 1
        return self

    async def __aenter__(self):
        return self.reader, self.writer

    async def __aexit__(self, exc_type, exc, tb):
        self.exits += 1
        return False


class FakeServerObject:
    """Stand-in for the module-level mcp Server instance: run() raises the
    injected exception on the first step (the server_task path that feeds
    the :820 log)."""

    def __init__(self, error):
        self._error = error
        self.run_calls = []

    def create_initialization_options(self):
        return {"marker": "init-options"}

    async def run(self, read_stream, write_stream, init_options):
        self.run_calls.append((read_stream, write_stream, init_options))
        raise self._error


def make_config(**overrides):
    """Real PolymarketConfig built by explicit kwargs (house pattern:
    _env_file=None so no real .env file is ever read)."""
    base = dict(
        POLYGON_PRIVATE_KEY="0" * 63 + "1",
        POLYGON_ADDRESS="0x" + "0" * 40,
        POLYMARKET_CHAIN_ID=137,
        _env_file=None,
    )
    base.update(overrides)
    return PolymarketConfig(**base)


def _install_init_stubs(monkeypatch, *, creation_error):
    """Patch every I/O seam of initialize_server BEFORE any call (the
    credential-creation failure feeds the :682 WARNING). Real objects stay
    real (offline-safe): config, SafetyLimits factory, rate limiter."""
    config = make_config()
    client = FakeClient(has_credentials=False, creation_error=creation_error)
    bag = SimpleNamespace(
        config=config,
        client=client,
        load_config_calls=0,
        client_factory_calls=[],
        manager_instances=[],
    )

    def fake_load_config():
        bag.load_config_calls += 1
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


def _install_main_stubs(monkeypatch, *, error):
    """Patch every seam of main() BEFORE the call (the server-task failure
    feeds the :820 log). initialize_server is faked; stdio transport and
    signal.signal are patched on the real module attributes."""
    bag = SimpleNamespace(
        stdio=FakeStdioTransport(),
        fake_server=FakeServerObject(error),
        signal_calls=[],
        initialize_calls=0,
    )

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
    """Await every task still registered in _background_tasks (no orphan
    warning leaks into the run - lifecycle-suite pattern)."""
    for task in list(server_module._background_tasks):
        await task


def _new_interceptor(write_stream):
    """Unit-mode constructor for _PreHandshakeStream (mirrors
    test_prehandshake_interceptor_offline.py: only _write_stream is touched,
    zero global state)."""
    interceptor = server_module._PreHandshakeStream.__new__(
        server_module._PreHandshakeStream
    )
    interceptor._write_stream = write_stream
    return interceptor


# =========================================================================
# Site 1 (:288): "server/discover failed" - _PreHandshakeStream.
# _respond_discover. The log carries the masked exception; the R1 JSON-RPC
# error answer to the client keeps the SAME request id and the literal
# prefix (the prehandshake pin survives). anyio.run body pattern (the
# prehandshake-suite pattern for this stream surface); monkeypatch is
# applied outside (module attribute, order-independent).
# =========================================================================
async def _receive_one(recv):
    return await recv.receive()


def test_discover_error_log_redacted(monkeypatch, caplog):
    """A cache failure inside _respond_discover logs the exception through
    _safe_error_message: the error LOG carries the literal prefix, both hex
    runs redacted, and no raw 16+ hex run."""
    error = _hex_error()

    def boom(_payload_builder):
        raise error

    monkeypatch.setattr(server_module, "cached_discover_result", boom)

    async def body():
        send, server_to_client_recv = anyio.create_memory_object_stream(16)
        interceptor = _new_interceptor(send)
        with caplog.at_level(logging.ERROR, logger=SERVER_LOGGER):
            await interceptor._respond_discover("probe-req")
        return server_to_client_recv

    recv = anyio.run(body)
    record = _pick_record(caplog, "server/discover failed: ")
    _assert_masked(record, "server/discover failed: ")

    message = anyio.run(_receive_one, recv)
    root = message.message.root
    assert isinstance(root, types.JSONRPCError), root
    assert root.id == "probe-req", root.id
    assert root.error.code == server_module.DISCOVER_INTERNAL_ERROR_CODE
    assert root.error.message.startswith("server/discover failed: ")


def test_discover_error_log_plain_passthrough(monkeypatch, caplog):
    """A hex-free cache failure logs byte-identically AND the R1 answer
    still reaches the client with the literal prefix (compat pin with
    test_prehandshake_interceptor_offline.py:148)."""

    def boom(_payload_builder):
        raise RuntimeError("boom-cache")

    monkeypatch.setattr(server_module, "cached_discover_result", boom)

    async def body():
        send, server_to_client_recv = anyio.create_memory_object_stream(16)
        interceptor = _new_interceptor(send)
        with caplog.at_level(logging.ERROR, logger=SERVER_LOGGER):
            await interceptor._respond_discover(7)
        return server_to_client_recv

    recv = anyio.run(body)
    record = _pick_record(caplog, "server/discover failed: ")
    _assert_plain(record, "server/discover failed: boom-cache")

    message = anyio.run(_receive_one, recv)
    root = message.message.root
    assert isinstance(root, types.JSONRPCError), root
    assert root.id == 7, root.id
    assert root.error.message == "server/discover failed: boom-cache"


# =========================================================================
# Site 2 (:321): "WebSocket startup failed" - _start_websocket (except
# swallows, never re-raises).
# =========================================================================
async def test_websocket_startup_error_log_redacted(caplog):
    """A connect failure inside _start_websocket logs the exception through
    _safe_error_message: literal prefix, both runs redacted, no raw hex,
    and nothing propagates (the swallow is untouched)."""
    error = _hex_error()
    manager = FakeWebSocketManager(connect_error=error)

    with caplog.at_level(logging.ERROR, logger=SERVER_LOGGER):
        await server_module._start_websocket(manager)

    record = _pick_record(caplog, "WebSocket startup failed")
    _assert_masked(record, "WebSocket startup failed: ")
    assert manager.calls == [], "no call may be recorded after a failed connect"


async def test_websocket_startup_error_log_plain_passthrough(caplog):
    """A hex-free connect failure logs byte-identically (compat pin with
    test_server_lifecycle_offline.py prefix pins)."""
    manager = FakeWebSocketManager(connect_error=ConnectionError("dial refused"))

    with caplog.at_level(logging.ERROR, logger=SERVER_LOGGER):
        await server_module._start_websocket(manager)

    record = _pick_record(caplog, "WebSocket startup failed")
    _assert_plain(record, "WebSocket startup failed: dial refused")


# =========================================================================
# Site 3 (:343): "Failed to cancel orders during shutdown" - shutdown()
# cancel branch (fail-safe: shutdown continues).
# =========================================================================
async def test_shutdown_cancel_error_log_redacted(monkeypatch, caplog):
    """A cancel_all_orders failure logs the exception through
    _safe_error_message: literal prefix, both runs redacted, no raw hex,
    and the shutdown still completes (fail-safe untouched)."""
    error = _hex_error()
    client = FakeClient(has_credentials=True, cancel_error=error)
    manager = FakeWebSocketManager()
    monkeypatch.delenv("CANCEL_ON_SHUTDOWN", raising=False)
    monkeypatch.setattr(server_module, "polymarket_client", client)
    monkeypatch.setattr(server_module, "websocket_manager", manager)

    with caplog.at_level(logging.ERROR, logger=SERVER_LOGGER):
        await server_module.shutdown()

    record = _pick_record(caplog, "Failed to cancel orders during shutdown")
    _assert_masked(record, "Failed to cancel orders during shutdown: ")
    assert client.cancel_all_orders_calls == 1
    assert manager.calls == ["stop_background_task"], "fail-safe: ws close still runs"


async def test_shutdown_cancel_error_log_plain_passthrough(monkeypatch, caplog):
    """A hex-free cancel failure logs byte-identically (compat pin with
    test_server_lifecycle_offline.py)."""
    client = FakeClient(has_credentials=True, cancel_error=RuntimeError("clob unreachable"))
    monkeypatch.delenv("CANCEL_ON_SHUTDOWN", raising=False)
    monkeypatch.setattr(server_module, "polymarket_client", client)
    monkeypatch.setattr(server_module, "websocket_manager", None)

    with caplog.at_level(logging.ERROR, logger=SERVER_LOGGER):
        await server_module.shutdown()

    record = _pick_record(caplog, "Failed to cancel orders during shutdown")
    _assert_plain(record, "Failed to cancel orders during shutdown: clob unreachable")


# =========================================================================
# Site 4 (:357): "Failed to close WebSocket connections" - shutdown()
# websocket-close branch.
# =========================================================================
async def test_shutdown_ws_close_error_log_redacted(monkeypatch, caplog):
    """A websocket close failure logs the exception through
    _safe_error_message: literal prefix, both runs redacted, no raw hex,
    and the shutdown still completes."""
    error = _hex_error()
    manager = FakeWebSocketManager(stop_error=error)
    monkeypatch.delenv("CANCEL_ON_SHUTDOWN", raising=False)
    monkeypatch.setattr(server_module, "polymarket_client", None)
    monkeypatch.setattr(server_module, "websocket_manager", manager)

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.shutdown()

    record = _pick_record(caplog, "Failed to close WebSocket connections")
    _assert_masked(record, "Failed to close WebSocket connections: ")
    assert "Graceful shutdown complete" in _messages(caplog), _messages(caplog)


async def test_shutdown_ws_close_error_log_plain_passthrough(monkeypatch, caplog):
    """A hex-free websocket close failure logs byte-identically (compat pin
    with test_server_lifecycle_offline.py)."""
    manager = FakeWebSocketManager(stop_error=RuntimeError("ws stop refused"))
    monkeypatch.delenv("CANCEL_ON_SHUTDOWN", raising=False)
    monkeypatch.setattr(server_module, "polymarket_client", None)
    monkeypatch.setattr(server_module, "websocket_manager", manager)

    with caplog.at_level(logging.ERROR, logger=SERVER_LOGGER):
        await server_module.shutdown()

    record = _pick_record(caplog, "Failed to close WebSocket connections")
    _assert_plain(record, "Failed to close WebSocket connections: ws stop refused")


# =========================================================================
# Site 5 (:619): "Tool call failed" - call_tool catch-all (converts into
# the uniform error envelope, never re-raises).
# =========================================================================
async def test_tool_call_error_log_redacted(monkeypatch, caplog):
    """An exception from a trading tool logs through _safe_error_message:
    literal prefix with the tool name, both runs redacted, no raw hex; the
    error envelope conversion is untouched."""
    error = _hex_error()
    tools = HexRaisingTradingTools(str(error))
    monkeypatch.setattr(server_module, "trading_tools", tools)

    with caplog.at_level(logging.ERROR, logger=SERVER_LOGGER):
        contents = await server_module.call_tool("create_limit_order", {"price": 0.5})

    record = _pick_record(caplog, "Tool call failed: create_limit_order - ")
    _assert_masked(record, "Tool call failed: create_limit_order - ")
    payload = json.loads(contents[0].text)
    assert payload["success"] is False
    assert payload["tool"] == "create_limit_order"
    assert tools.calls == [("create_limit_order", {"price": 0.5})]


async def test_tool_call_error_log_plain_passthrough(monkeypatch, caplog):
    """A hex-free tool failure logs byte-identically (compat pin with
    test_server_dispatch_offline.py envelope pin)."""
    tools = HexRaisingTradingTools("boom")
    monkeypatch.setattr(server_module, "trading_tools", tools)

    with caplog.at_level(logging.ERROR, logger=SERVER_LOGGER):
        contents = await server_module.call_tool("create_limit_order", {"price": 0.5})

    record = _pick_record(caplog, "Tool call failed: create_limit_order - ")
    _assert_plain(record, "Tool call failed: create_limit_order - boom")
    payload = json.loads(contents[0].text)
    assert payload["error"] == "boom"


# =========================================================================
# Site 6 (:682): "Could not create API credentials" - initialize_server
# credential-creation failure (WARNING; read-only fallback continues).
# =========================================================================
async def test_credential_creation_error_log_redacted(monkeypatch, caplog):
    """A create_api_credentials failure logs through _safe_error_message:
    literal prefix, both runs redacted, no raw hex, and the read-only
    fallback continues (safety limits built, trading tools stay None)."""
    error = _hex_error()
    bag = _install_init_stubs(monkeypatch, creation_error=error)

    with caplog.at_level(logging.WARNING, logger=SERVER_LOGGER):
        await server_module.initialize_server()
    await _drain_background_tasks()

    record = _pick_record(caplog, "Could not create API credentials")
    _assert_masked(record, "Could not create API credentials: ")
    assert bag.client.create_api_credentials_calls == 1
    assert isinstance(server_module.safety_limits, SafetyLimits)
    assert server_module.trading_tools is None
    assert bag.manager_instances, "the ws manager must be constructed even read-only"


async def test_credential_creation_error_log_plain_passthrough(monkeypatch, caplog):
    """A hex-free credential-creation failure logs byte-identically (compat
    pin with test_server_lifecycle_offline.py)."""
    _install_init_stubs(
        monkeypatch, creation_error=RuntimeError("credential endpoint unreachable")
    )

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        await server_module.initialize_server()
    await _drain_background_tasks()

    record = _pick_record(caplog, "Could not create API credentials")
    _assert_plain(
        record,
        "Could not create API credentials: credential endpoint unreachable",
    )
    assert "Continuing in READ-ONLY mode" in _messages(caplog)


# =========================================================================
# Site 7 (:820): "Server error" - main() except branch (the exception is
# re-raised by identity - the T-0065/T-0092 pin survives).
# =========================================================================
async def test_server_error_log_redacted(monkeypatch, caplog):
    """A server-task exception logs through _safe_error_message: literal
    prefix, both runs redacted, no raw hex; the exception is re-raised BY
    IDENTITY (the re-raise pin survives) and the finally's shutdown still
    ran."""
    error = _hex_error()
    monkeypatch.setenv("CANCEL_ON_SHUTDOWN", "false")
    monkeypatch.setattr(server_module, "polymarket_client", None)
    monkeypatch.setattr(server_module, "websocket_manager", None)
    bag = _install_main_stubs(monkeypatch, error=error)

    main_task = asyncio.create_task(server_module.main())
    with caplog.at_level(logging.ERROR, logger=SERVER_LOGGER):
        with pytest.raises(RuntimeError, match="boom") as excinfo:
            await main_task

    record = _pick_record(caplog, "Server error: ")
    _assert_masked(record, "Server error: ")
    assert excinfo.value is error, "the exception is re-raised by identity"
    assert bag.stdio.exits == 1, "the transport context exits before the finally"


async def test_server_error_log_plain_passthrough(monkeypatch, caplog):
    """A hex-free server-task exception logs byte-identically (compat pin
    with test_server_lifecycle_offline.py "Server error: server boom")."""
    error = ValueError("server boom")
    monkeypatch.setenv("CANCEL_ON_SHUTDOWN", "false")
    monkeypatch.setattr(server_module, "polymarket_client", None)
    monkeypatch.setattr(server_module, "websocket_manager", None)
    _install_main_stubs(monkeypatch, error=error)

    main_task = asyncio.create_task(server_module.main())
    with caplog.at_level(logging.ERROR, logger=SERVER_LOGGER):
        with pytest.raises(ValueError, match="server boom") as excinfo:
            await main_task

    record = _pick_record(caplog, "Server error: ")
    _assert_plain(record, "Server error: server boom")
    assert excinfo.value is error, "the exception is re-raised by identity"


# =========================================================================
# Unit boundary pins on the helper (re-used canonical pattern: the 15/16
# boundary catches threshold drift; context survives redaction).
# =========================================================================
def test_safe_error_message_boundary_15_16():
    """The 15-char run passes through; the 16-char run is redacted - the
    EXACT threshold edge (anti-fix M3: threshold 16 -> 32 fails here)."""
    from polymarket_mcp.server import _safe_error_message

    run_15 = "f" * 15
    assert (
        _safe_error_message(ValueError(f"short {run_15} kept"))
        == f"short {run_15} kept"
    ), "15-hex runs pass through (boundary)"

    run_16 = "a" * 16
    out = _safe_error_message(ValueError(f"tok {run_16} ."))
    assert out == f"tok [REDACTED:{len(run_16)} hex chars] ."
    assert run_16 not in out


def test_safe_error_message_preserves_context():
    """Both material runs are redacted IN PLACE; the surrounding text
    survives byte-exactly (anti-fix M2: pass-through fails here)."""
    from polymarket_mcp.server import _safe_error_message

    out = _safe_error_message(ValueError(f"key={HEX_64} run={RUN_23} end"))
    assert out == (
        f"key=[REDACTED:{len(HEX_64)} hex chars] "
        f"run=[REDACTED:{len(RUN_23)} hex chars] end"
    )
    assert HEX_64 not in out
    assert RUN_23 not in out
