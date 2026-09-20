"""Offline SIGNAL-PATH coverage suite for polymarket_mcp.server (T-0429).

Closes the LAST coverage residual on the signal path (T-0398 merged,
fork-point 71aa286: 98.51% stmt on server.py with the 5 misses 380,
391-392, 773-774 + 1 BrPart - ALL in the signal path) and hardens the
T-0398 shutdown machinery against the two P2 defects proven 1st-hand by
the curator (probes /tmp/c88-redpre/probe_signal.py + probe_finally.py):

1. DOUBLE-DISPATCH (L-0408, gates of T-0398): the handler is registered
   TWICE (loop.add_signal_handler + signal.signal). One delivered signal
   invokes the Python handler directly AND re-invokes the loop's wakeup
   Handle (byte write into the wakeup socket -> _read_from_self ->
   _process_self_data -> _handle_signal -> Handle(sig, None)). Both
   invocations hit the unguarded create_task - 2 concurrent exit-tasks.
   Fix (E0/E1b/E1): one-shot flag of the SCHEDULING (the is_set() guard
   protects the SET, never the SCHEDULING - it is already True on the
   first invocation before create_task, so guarding with it would prevent
   the scheduling entirely; L-0408).
2. HELPER WITHOUT try/finally (P3-02, T-0398 sec review): an exception
   from shutdown() propagates BEFORE os._exit - the process never exits
   and the pre-fix dead-hang resurges silently. Fix (E2): try/finally -
   os._exit(0) runs even when shutdown() raises.

Sources of truth (suite-only: src/** is read, never modified):
- src/polymarket_mcp/server.py @ farm/T-0429: module globals :85-95
  (_signal_loop then the E0 one-shot flag), _signal_handler :366-401
  (E1b global + E1 one-shot guard around create_task),
  _signal_shutdown_and_exit :403-419 (E2 try/finally), main :755-796
  (E3 global + per-restart reset after _signal_loop = loop) and the
  registration fallback :790-796 (except NotImplementedError -> logger
  "loop.add_signal_handler unavailable for %s; signal.signal remains" ->
  signal.signal fallback).

Seams and fakes (P-0031/L-0133 - EVERY I/O seam patched BEFORE any call):
- _LoopRecorder: the exit-task scheduling loop - create_task records the
  coroutine and CLOSES it (never runs the body: the real helper awaits
  shutdown() and calls os._exit(0), which would kill the test process).
  Fail-loud (P-0031): any other attribute access raises AttributeError
  (no real AbstractEventLoop is ever started here).
- T3/T4: server_module.shutdown patched with an async recorder/failer and
  os._exit patched ON THE REAL os MODULE (server_module.os IS os - the
  helper resolves the attribute through it) with a fake that raises
  _ExitForced(code) to simulate the forced process exit.
- T5: the lifecycle main-test pattern MIRRORED, never imported
  (tests/test_server_lifecycle_offline.py:466-496): initialize_server
  faked, signal.signal patched on the REAL signal module with a recorder
  (never a live handler - L-0099), mcp.server.stdio.stdio_server patched
  as the REAL module attribute, the module-level Server object replaced
  by a fake that blocks in run() until the shutdown cancellation. The
  add_signal_handler failure is injected by SHADOWING the instance
  attribute of the REAL running loop (monkeypatch.setattr(loop, ...)):
  the get_running_loop() INSIDE main() returns the same loop object, so
  the raise is observed exactly where the production code catches it.
  NEVER patch asyncio.get_running_loop globally (it would affect the
  whole process).

Hermeticity (P-0029 in BOTH directions, L-0138/L-0137):
- zero network by construction: initialize_server is faked, the real
  WebSocketManager/PolymarketClient are never constructed, shutdown()
  runs with polymarket_client/websocket_manager at None (env gate
  CANCEL_ON_SHUTDOWN=false set explicitly in the main() test) - only log
  lines are emitted; no signal handler is ever installed in the process.
- clean_env (autouse; P-0035 house pattern via
  tests/test_server_lifecycle_offline.py:181-194): every config-sourced
  env prefix is stripped PLUS CANCEL_ON_SHUTDOWN (shutdown() reads it
  directly via os.getenv - server.py:338), controlled explicitly per
  test.

Order-independence (L-0099): pristine_signal_globals (autouse) registers
the ORIGINAL value of every signal-path global (_signal_loop,
_shutdown_event, _signal_scheduled) with monkeypatch for restoration at
teardown - main() assigns them DIRECTLY (server.py:751/:786/:789), so
monkeypatch cannot see the writes; the registered original is restored
regardless. The lifecycle sibling
(tests/test_server_lifecycle_offline.py:159-166) restores _shutdown_event
but NOT _signal_loop/_signal_scheduled - this suite owns the signal-path
globals and every test sets the globals it reads before reading them.

Divergences declared (L-0025/L-0020/L-0090):
1. The contract prescribed the docstring sentence with an em-dash; the
   file keeps ASCII-only purity (server.py is 0 non-ASCII lines at the
   fork-point; the delta-scoped ASCII-check family L-0414 turns any new
   non-ASCII byte into a future RED landmine) - rendered as "--", same
   sentence, same semantics.
2. T5 pins the E3 per-restart reset with a discriminant setup
   (_signal_scheduled = True BEFORE main()): after main() the flag must
   be False again - the reset line runs (coverage) and the pin is
   non-vacuous (RED pre-E3: stays True).
3. The save/restore fixture (and the per-test defensive setattrs) use
   monkeypatch raising=False: the RED-pre proof runs this suite against
   the PRE-FIX module where _signal_scheduled does not exist yet - the
   fixture must not error at setup there; on the post-fix module the
   behavior is identical (all attributes exist).

Anti-over-fix pins: T2 proves the loop-None branch schedules NOTHING (a
fix that flips the flag without checking the loop fails here); the
is_set() guard (protects the SET) stays untouched everywhere (L-0408).
"""
import asyncio
import logging
import os
import signal
from types import SimpleNamespace

import pytest

import polymarket_mcp.server as server_module

SERVER_LOGGER = "polymarket_mcp.server"

# Process env names/prefixes that feed config reads, stripped by the
# autouse fixture (P-0035), PLUS CANCEL_ON_SHUTDOWN: shutdown() reads it
# directly via os.getenv (server.py:338) - it is a runtime knob, not a
# config field, so it is stripped here and controlled explicitly per test.
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

# The signal-path module globals owned by this suite (server.py:85-95) -
# registered with monkeypatch for restoration by the autouse fixture
# (L-0099); main() writes them directly, monkeypatch cannot see that.
_SIGNAL_GLOBALS = ("_signal_loop", "_shutdown_event", "_signal_scheduled")


class _ExitForced(Exception):
    """Raised by the fake os._exit to simulate the forced process exit.

    Own exception class (never Skipped): pytest.raises(_ExitForced)
    captures ONLY this - the contract note holds because a pytest skip
    exception is unrelated to this class and never flows through the
    helper under test.
    """

    def __init__(self, code):
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# Hermeticity + order-independence (autouse fixtures)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip config-sourced env vars so tests never observe the host env
    (P-0035; CANCEL_ON_SHUTDOWN included - shutdown() reads it directly,
    server.py:338)."""
    for name in list(os.environ):
        if any(name.startswith(prefix) for prefix in _ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def pristine_signal_globals(monkeypatch):
    """Order-independence (L-0099): the signal-path globals are restored
    to their PRE-TEST values after every test, whatever wrote them during
    the test.

    monkeypatch.setattr(server_module, name, original) registers the
    pre-test value for restoration at teardown - main() assigns
    _shutdown_event/_signal_loop/_signal_scheduled DIRECTLY
    (server.py:751/:786/:789), so per-test writes cannot be attributed;
    the fixture is the restore guarantee. Sibling suites that run before
    this one in the same pytest process (the lifecycle suite leaks
    _signal_loop after its main() tests) cannot contaminate a test here:
    every test below sets the globals it reads BEFORE reading them.

    raising=False (declared divergence 3): the RED-pre proof runs this
    suite against the PRE-FIX server.py (71aa286) where _signal_scheduled
    does not exist yet - the fixture must not error at setup there; on
    the post-fix module every attribute exists and the behavior is
    identical.
    """
    for name in _SIGNAL_GLOBALS:
        monkeypatch.setattr(
            server_module, name, getattr(server_module, name, None), raising=False
        )
    yield


# ---------------------------------------------------------------------------
# Fakes (P-0031: fail-loud seams owned by this file; zero class-level
# mutable state - order-independent, L-0099)
# ---------------------------------------------------------------------------
class _LoopRecorder:
    """Fail-loud stand-in for the exit-task scheduling loop.

    create_task records the coroutine and CLOSES it - never runs the body
    (the real _signal_shutdown_and_exit would await shutdown() and call
    os._exit(0), killing the pytest process). Any other attribute access
    raises AttributeError loudly (P-0031): no real AbstractEventLoop is
    ever started here.
    """

    def __init__(self):
        self.scheduled = []

    def create_task(self, coro):
        self.scheduled.append(coro)
        coro.close()


# ---------------------------------------------------------------------------
# T1: one-shot scheduling under double dispatch (E0/E1b/E1 -> :380 closes)
# ---------------------------------------------------------------------------
async def test_signal_handler_schedules_exactly_one_exit_task(monkeypatch):
    """One delivered signal schedules EXACTLY ONE exit-task even though the
    handler fires TWICE (T-0429/L-0408 double-dispatch proof).

    Real mechanics: the handler is registered both via
    loop.add_signal_handler (the loop's Handle re-invocation through the
    wakeup byte) and via signal.signal (direct Python invocation) - ONE
    delivered signal reaches _signal_handler twice. Pre-fix both
    invocations passed the unguarded create_task (server.py:380) ->
    2 concurrent exit-tasks (curator probe: scheduled_tasks_after_double_
    fire: 2). Post-fix the one-shot flag (_signal_scheduled) lets only the
    FIRST invocation schedule. The is_set() guard on _shutdown_event
    (protects the SET, L-0408) stays untouched.
    """
    recorder = _LoopRecorder()
    monkeypatch.setattr(server_module, "_signal_loop", recorder)
    # Defensive per contract: inofensivo no estado pre-fix (a fresh
    # process starts at False; a leaked True from a sibling suite cannot
    # masquerade as the first-invocation state).
    monkeypatch.setattr(
        server_module, "_signal_scheduled", False, raising=False
    )
    monkeypatch.setattr(server_module, "_shutdown_event", None)

    # Simulate the double dispatch: direct handler invocation (the
    # signal.signal path) + the loop's wakeup-byte Handle re-invocation -
    # both deliver (SIGTERM, None).
    server_module._signal_handler(signal.SIGTERM, None)
    server_module._signal_handler(signal.SIGTERM, None)

    assert len(recorder.scheduled) == 1, (
        "the one-shot flag must let only the FIRST invocation schedule the "
        f"exit-task (observed: {len(recorder.scheduled)})"
    )
    assert server_module._signal_scheduled is True, (
        "the flag latches on the first invocation (one-shot per process "
        "lifetime; main()'s reset is the only path back to False)"
    )


# ---------------------------------------------------------------------------
# T2: no loop, no scheduling (the if-False branch; anti-over-fix)
# ---------------------------------------------------------------------------
async def test_signal_handler_without_loop_schedules_nothing(monkeypatch):
    """With _signal_loop at None the handler schedules NOTHING (server.py:
    _signal_loop is not None short-circuits) - the anti-over-fix pin: a
    broken fix that flips the flag or schedules without the loop check
    fails here. Both invocations (double dispatch again) take the same
    branch; the flag stays False (never latched without a loop)."""
    monkeypatch.setattr(server_module, "_signal_loop", None)
    monkeypatch.setattr(
        server_module, "_signal_scheduled", False, raising=False
    )
    monkeypatch.setattr(server_module, "_shutdown_event", None)

    server_module._signal_handler(signal.SIGTERM, None)
    server_module._signal_handler(signal.SIGTERM, None)

    assert server_module._signal_scheduled is False, (
        "no loop means no scheduling: the flag must stay False (loop-None "
        "branch short-circuits before the flag is read)"
    )


# ---------------------------------------------------------------------------
# T3/T4: the helper - graceful shutdown THEN forced exit (E2 -> :391-392)
# ---------------------------------------------------------------------------
async def test_signal_shutdown_and_exit_runs_shutdown_then_forces_exit(
    monkeypatch,
):
    """_signal_shutdown_and_exit runs shutdown() EXACTLY once and then
    forces the exit with code 0 (server.py try/finally, T-0398 helper).

    The fake os._exit raises _ExitForced(0) instead of killing the
    process - the pytest.raises captures ONLY that class (the exception
    is propria, never Skipped). The shutdown call BEFORE the exit is the
    order pin: the graceful path executes, then the forced exit."""
    calls = []

    async def fake_shutdown():
        calls.append("shutdown")

    def fake_exit(code):
        raise _ExitForced(code)

    monkeypatch.setattr(server_module, "shutdown", fake_shutdown)
    # Patch on the REAL os module: server_module.os IS os (server.py does
    # a plain `import os`), so the helper's os._exit(0) resolves through
    # it. monkeypatch restores the builtin after the test.
    monkeypatch.setattr(os, "_exit", fake_exit)

    with pytest.raises(_ExitForced) as excinfo:
        await server_module._signal_shutdown_and_exit()

    assert calls == ["shutdown"], "shutdown runs exactly once, before the exit"
    assert excinfo.value.code == 0, "the forced exit code is 0 (T-0398 pin)"


async def test_shutdown_exception_still_forces_exit(monkeypatch):
    """RED PRE (curator probe_finally.py): an exception from shutdown()
    propagated BEFORE os._exit - the process never exited and the
    pre-fix dead-hang resurged silently (P3-02, T-0398 sec review).

    Post-fix (E2 try/finally): the RuntimeError raised inside shutdown()
    is REPLACED by the _ExitForced(0) from the finally - the forced exit
    is UNCONDITIONAL. The shutdown call still happened (calls pinned);
    the observed exception is the forced exit with code 0, never the
    RuntimeError."""
    calls = []

    async def exploding_shutdown():
        calls.append("shutdown")
        raise RuntimeError("shutdown boom")

    def fake_exit(code):
        raise _ExitForced(code)

    monkeypatch.setattr(server_module, "shutdown", exploding_shutdown)
    monkeypatch.setattr(os, "_exit", fake_exit)

    with pytest.raises(_ExitForced) as excinfo:
        await server_module._signal_shutdown_and_exit()

    assert calls == ["shutdown"], "the exploding shutdown still ran first"
    assert excinfo.value.code == 0, (
        "the finally replaces the shutdown failure with the forced exit"
    )
    assert type(excinfo.value) is _ExitForced, (
        "the RuntimeError never escapes the helper (pre-fix RED)"
    )


# ---------------------------------------------------------------------------
# T5: main() falls back to signal.signal when add_signal_handler is
# unavailable (closes :773-774) - mirrors the lifecycle main-test pattern
# ---------------------------------------------------------------------------
async def test_main_falls_back_to_signal_signal_when_add_signal_handler_unavailable(
    monkeypatch, caplog
):
    """On ProactorEventLoop (Windows) loop.add_signal_handler raises
    NotImplementedError; main() catches it, logs the per-signal fallback
    notice and registers BOTH signals via signal.signal anyway
    (server.py:790-796) - no exception escapes, the server runs.

    Construction MIRRORED from the lifecycle suite
    (tests/test_server_lifecycle_offline.py:466-496 - the house pattern
    for main() in-process; NEVER imported across test modules): the
    add_signal_handler failure is injected by SHADOWING the instance
    attribute of the REAL running loop - the get_running_loop() INSIDE
    main() returns the same object, so the raise lands exactly where the
    production except sits. signal.signal is a recorder on the REAL
    signal module (never a live handler, L-0099).

    The E3 per-restart reset is pinned with a discriminant setup: the
    flag is True BEFORE main() and must be False after (pre-E3 RED:
    stays True)."""
    monkeypatch.setenv("CANCEL_ON_SHUTDOWN", "false")
    monkeypatch.setattr(server_module, "polymarket_client", None)
    monkeypatch.setattr(server_module, "websocket_manager", None)

    bag = SimpleNamespace(
        signal_calls=[],
        initialize_calls=0,
        stdio_calls=0,
        stdio_exits=0,
    )

    async def fake_initialize_server():
        bag.initialize_calls += 1

    def fake_signal(signum, handler):
        bag.signal_calls.append((signum, handler))
        return None

    class _FakeStdioTransport:
        def __call__(self):
            bag.stdio_calls += 1
            return self

        async def __aenter__(self):
            return object(), object()

        async def __aexit__(self, exc_type, exc, tb):
            bag.stdio_exits += 1
            return False

    class _FakeServerObject:
        async def run(self, read_stream, write_stream, init_options):
            await asyncio.Event().wait()

        def create_initialization_options(self):
            return {"marker": "init-options"}

    monkeypatch.setattr(server_module, "initialize_server", fake_initialize_server)
    monkeypatch.setattr(signal, "signal", fake_signal)
    monkeypatch.setattr("mcp.server.stdio.stdio_server", _FakeStdioTransport())
    monkeypatch.setattr(server_module, "server", _FakeServerObject())

    def boom(sig, *args):
        raise NotImplementedError(
            "ProactorEventLoop does not support add_signal_handler"
        )

    running_loop = asyncio.get_running_loop()
    monkeypatch.setattr(running_loop, "add_signal_handler", boom)
    # Discriminant setup for the E3 reset pin (see divergence 2).
    monkeypatch.setattr(
        server_module, "_signal_scheduled", True, raising=False
    )

    with caplog.at_level(logging.INFO, logger=SERVER_LOGGER):
        main_task = asyncio.create_task(server_module.main())
        for _ in range(100):
            if server_module._shutdown_event is not None:
                break
            await asyncio.sleep(0)
        assert server_module._shutdown_event is not None, "main must create the event"
        server_module._shutdown_event.set()
        await main_task  # completes without raising - "no exception" pin

    unavailable = [
        record.message
        for record in caplog.records
        if "loop.add_signal_handler unavailable for" in record.message
    ]
    assert len(unavailable) == 2, (
        "the except NotImplementedError branch logged once per signal "
        f"(observed: {unavailable})"
    )
    assert any("unavailable for SIGTERM" in message for message in unavailable)
    assert any("unavailable for SIGINT" in message for message in unavailable)
    assert (signal.SIGTERM, server_module._signal_handler) in bag.signal_calls
    assert (signal.SIGINT, server_module._signal_handler) in bag.signal_calls
    assert bag.initialize_calls == 1, "main initialized exactly once"
    assert bag.stdio_calls == 1, "the stdio transport was entered once"
    assert bag.stdio_exits == 1, "the transport context exited normally"
    assert server_module._signal_scheduled is False, (
        "the E3 per-restart reset ran: a latched True from a previous "
        "lifecycle cycle never survives into this one"
    )
    messages = [record.message for record in caplog.records]
    assert "Starting MCP server..." in messages, "main reached the run"
    assert "Graceful shutdown complete" in messages, (
        "the finally's shutdown ran with the env gate OFF (no cancellation)"
    )
