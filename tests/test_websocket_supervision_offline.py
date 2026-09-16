"""
Offline regression suite for the WebSocketManager SUPERVISION LAYER (T-0052).

Regions under test (src/polymarket_mcp/utils/websocket_manager.py @ clone main
40c4412 — the LIVE tip forked at claim time; the contract draft cited main
9e675da and merges that only ADDED code before :778 shifted the numbers —
forking the live main is the FA-0044/L-0096 protocol; the numbers below were
re-derived from the live blob):

- start_background_task :778-791 — live-task guard :784-787 (warning + return,
  the SAME task object is kept — idempotency), creation :788-789.
- stop_background_task  :792-806 — should_run=False :797; ``wait_for(task,
  timeout=5.0)`` :801 with TimeoutError → warning + ``task.cancel()``
  :802-804; ``await self.disconnect()`` runs UNCONDITIONALLY afterwards :805.
- _background_loop      :809-886 — the ``readers`` registry is LOCAL to the
  call :820; ``while self.should_run`` :826; NOT-CONNECTED branch :829-832
  (_cancel_readers + reconnect + continue — this branch PREEMPTS the spawn
  block, see the divergence note below); clob spawn gate :834-841
  (``ws_is_open(clob_ws) and "clob" not in readers``); realtime spawn gate
  :842-849; idle branch :850-852 (no readers → ``await asyncio.sleep(1.0)``
  + continue); FIRST_COMPLETED wait :856-860 (real wall timeout 1.0 —
  replaced by the bounded fake below); done-processing :863-874 (``del
  readers[name]`` :865, ``task.cancelled() → continue`` :866-867, error →
  warning :868-870 + flag SELECTIVITY :871-874 — ONLY the dead channel's
  flag is cleared: ``clob_connected and name != "clob"`` / the realtime
  twin); ConnectionClosed branch :876-879 (warning + _cancel_readers +
  reconnect AGAIN — the second reconnect must succeed for the loop to
  survive); generic Exception branch :880-882 (error + sleep(1.0)); finally
  :883-885 (_cancel_readers on every exit path) + the "stopped" log :886.
- _read_channel         :888-897 — ``while self.should_run and is_open()``
  calls receive_one N times; stops when is_open() goes False OR should_run
  goes False.
- _cancel_readers       :899-905 — cancel each reader, gather with
  return_exceptions=True when non-empty, clear the registry.
- _receive_clob_messages :907-920 — closed-socket guard :910-911 (return
  BEFORE recv); recv → json.loads → handle_message("clob", data) :913-915;
  JSONDecodeError → logged and SWALLOWED :916-917 (handle_message NOT
  called, no raise); generic Exception → logged AND re-raised :918-920 (the
  reader task dies with the error — the input of the flag-selectivity
  branch).
- _receive_realtime_messages :922-935 — the same trio for the realtime
  channel (:925 guard, :932-933 swallow, :934-936 re-raise).

Divergences declared (L-0025/L-0143 — contract refs are LOCALIZATION, the
semantics come from reading the live code):
- The draft's "one channel connected → only one reader" scenario is
  UNREACHABLE as described: the not-connected branch (:829-832) PREEMPTS the
  spawn block, so with a single channel flagged connected the loop
  reconnects and NO reader spawns. The observable one-reader scenarios are
  (a) both flags up with ONE socket closed (the spawn gate :834/:842 fails
  only for the closed one) and (b) the flag selectivity after a reader
  error (clob dies → only the clob flag clears). This suite pins (a) and
  (b) instead of the draft's literal wording.
- A reader completes "cleanly" (the done-processing branch with error None)
  only when it exits WITHOUT an exception — reachable when is_open() flips
  False (socket closes) while the supervisor keeps running. FiniteSocket
  models the server-initiated close after the last message; the respawn on
  the next iteration (:834) then needs an OPEN socket, which the test
  swaps in — the same thing a successful reconnect installs.

Determinism contract (L-0014/L-0120 — zero wall sleep, zero network; the
mode is registered here per L-0120: fakes fail LOUD, the 120s pytest-timeout
is a safety NET, never the oracle):
- ``asyncio.sleep`` is monkeypatched with a recorder that yields exactly one
  real ``sleep(0)`` step (websocket_manager imports the global ``asyncio``
  module — :10 — so the patch is observed at :851/:882 and inside
  ``reconnect`` :348). ``_yield_once`` uses the ORIGINAL function object
  captured at import time, so test-side stepping never recurses.
- ``asyncio.wait`` is monkeypatched with a bounded fake: it yields steps
  until a task completes (real FIRST_COMPLETED semantics) or the bounded
  step budget expires (the 1.0s-timeout wake-up — zero wall time). Every
  async fake invoked BY the loop yields (a synchronous fake would spin the
  loop forever inside one scheduling quantum — hang, L-0120).
- Every loop-driving test installs a fail-loud reconnect recorder on the
  instance EXCEPT the end-to-end reconnect test (the real reconnect with
  ``websockets.connect`` stubbed BEFORE any dial, L-0118). No Polymarket
  endpoint is ever contacted; the teardown runs in ``finally`` so a failed
  assert never leaves a live loop behind (which, post-monkeypatch-restore,
  would resume with REAL sleeps/network).

Hermeticity (P-0029/P-0035, BOTH directions): autouse ``clean_env`` strips
every config-sourced env var; configs are built with explicit kwargs +
``_env_file=None``. Zero network proven at runtime by the sockets-inoperable
harness (report evidence).

Mutation oracle (L-0112/L-0124 — temp-copy replaces asserted individually,
P-0020 real-file shadow, module.__file__ validated per FA-0036): M1 clears
BOTH flags on any reader error (selectivity :871-874) →
``test_background_loop_replaces_failed_reader_and_clears_its_flag`` fails;
M2 makes clean completions look like errors (``error = task.exception() or
RuntimeError(...)``) → ``test_background_loop_replaces_reader_on_clean_
completion`` fails. Both runs: ``PYTHONPATH=<tmp>/src:src``.

Sibling coverage (dedupe by reading, P-0009/P-0039): tests/test_websocket_
readers.py owns the drain-pattern lifecycle (spawns under load, no-leak on
stop, closed-socket no-spin) and the _read_channel/_cancel_readers
mechanics — this file pins the CALL COUNTERS (N calls) instead of re-pinning
those mechanics; tests/test_websocket_messages.py (T-0043) owns
handle_message routing and the reconnect BACKOFF FORMULA (this suite calls
reconnect END-TO-END but never re-pins its internal formula); tests/
test_websocket_lifecycle_offline.py (T-0051) owns the connection layer;
tests/test_realtime_offline.py (T-0053) owns the consumer side (the real
manager is never instantiated there). This file owns the supervision slice
only — the fakes below are OWNED here, never imported from a sibling suite
(P-0031).
"""
import asyncio
import logging
import os

import pytest
import websockets
import websockets.exceptions

from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.utils.websocket_manager import WebSocketManager

# ACHADO (SUITE-ONLY, L-0025/L-0090): in websockets 17.1 the ``exceptions``
# SUBMODULE is not bound on the package by a bare ``import websockets`` — the
# lazy-import machinery (websockets/imports.py) only provides the exception
# CLASSES by alias ("ConnectionClosed": ".exceptions"). The manager's
# ``except websockets.exceptions.ConnectionClosed`` (:876) EVALUATES the
# submodule attribute when an exception propagates out of its try — in a fresh
# interpreter (nothing imported websockets.exceptions yet) that evaluation
# raises AttributeError, REPLACING the original exception (the CancelledError
# of a cancelled loop became "module 'websockets' has no attribute
# 'exceptions'"). In production any successful connect() binds the submodule
# (the lazy alias imports .asyncio.client, whose internals do ``from
# ..exceptions import ...``), so the window is narrow — but a supervisor
# started BEFORE any connect with an in-loop exception crashes. This suite
# normalizes the environment by importing the submodule (test-side only —
# src/ is NEVER touched) and the finding is reported. Proof of mechanism:
# fresh process getattr(websockets, "exceptions") → MISSING; after the import
# → bound.

MANAGER_LOGGER = "polymarket_mcp.utils.websocket_manager"

# Process env prefixes/names that feed PolymarketConfig fields; stripped by the
# autouse fixture so tests never observe the host environment (P-0035 — house
# pattern of tests/test_config_security.py).
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

# The ORIGINAL asyncio.sleep object, captured at import time — BEFORE any test
# can patch the module attribute. Used by every yield point so patching
# asyncio.sleep never recurses.
_REAL_SLEEP = asyncio.sleep


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip config-sourced env vars so tests never see the host environment.

    PolymarketConfig is a pydantic BaseSettings: ``_env_file=None`` disables
    only the .env file; env vars are still read for every field NOT passed
    explicitly (config.py:11,17-18). Every config below is built with explicit
    kwargs, so the delenv changes no pin.
    """
    for name in list(os.environ):
        if any(name.startswith(prefix) for prefix in _ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Deterministic event-loop driving (L-0014/L-0120)
# ---------------------------------------------------------------------------
async def _yield_once():
    """One real event-loop step (sleep(0) — zero wall time)."""
    await _REAL_SLEEP(0)


WAIT_MAX_STEPS = 8  # bounded fake_wait budget ≙ the real 1.0s timeout wake-up


def install_loop_fakes(monkeypatch):
    """Replace asyncio.sleep + asyncio.wait BEFORE any loop runs (L-0118).

    - fake_sleep: records the requested delay and yields one step — the loop
      never occupies the scheduler without yielding (a synchronous fake would
      busy-spin the supervisor forever; L-0120).
    - fake_wait: yields steps until some task completes (FIRST_COMPLETED
      semantics) or the bounded budget expires (the 1.0s wake-up), then
      returns (done, pending). Never waits on the wall clock.
    Returns the sleeps recorder for pinning.
    """
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)
        await _yield_once()

    async def fake_wait(fs, *, timeout=None, return_when=None):
        if not list(fs):
            return set(), set()
        for _ in range(WAIT_MAX_STEPS):
            await _yield_once()
            done = {t for t in fs if t.done()}
            if done:
                return done, {t for t in fs if not t.done()}
        return set(), {t for t in fs if not t.done()}

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(asyncio, "wait", fake_wait)
    return sleeps


async def settle(predicate, *, label, max_steps=600):
    """Bounded, fail-loud wait for a predicate over event-loop steps.

    The pytest-timeout guard (120s) is the safety net; this helper is the
    oracle: the predicate must hold within the bound or the test FAILS LOUD
    (never hangs, L-0120).
    """
    for _ in range(max_steps):
        if predicate():
            return
        await _yield_once()
    raise AssertionError(f"settle({label!r}): predicate never held within {max_steps} steps")


def assert_no_reader_leaks():
    """No reader task may outlive the supervisor (house pattern)."""
    leaked = [t for t in asyncio.all_tasks() if not t.done() and "_read_channel" in repr(t)]
    assert leaked == [], f"reader tasks leaked: {leaked}"


async def teardown_loop(manager, *, label=""):
    """Stop the supervisor through should_run=False and let it exit via its
    own finally path — NEVER cancel the supervisor task here (the finally
    reaping is part of the behaviour under test). Safe to call after a failed
    assert (finally), after stop_background_task, and on a never-started
    manager."""
    if manager.should_run:
        manager.should_run = False
    if manager.background_task is not None and not manager.background_task.done():
        await settle(lambda: manager.background_task.done(), label=f"loop-exit{label}")
        # Retrieve the outcome (clean / cancelled / exception) so no task is
        # garbage-collected with an unretrieved exception.
        await asyncio.gather(manager.background_task, return_exceptions=True)
    assert_no_reader_leaks()


def make_reconnect_recorder(calls):
    """Fail-loud instance-level reconnect recorder (P-0031).

    A PURE recorder: it never mutates the manager's flags, so the state
    observed between the error processing and the reconnect branch is
    deterministic (the loop is suspended inside the fake's yield).
    """

    async def fake_reconnect():
        calls.append(True)
        await _yield_once()

    return fake_reconnect


# ---------------------------------------------------------------------------
# Fakes owned by this file (P-0031: fail-loud, never imported from siblings)
# ---------------------------------------------------------------------------
class FakeSocket:
    """Fake connection mirroring the surface the supervision layer touches:
    ``recv`` (queue + injected error + park on a REAL Event — the reader
    suspends until cancelled), ``close`` (records + sets close_code), and the
    ``ws_is_open`` probe surface (close_code; no legacy ``.closed`` attribute,
    so the modern branch :41 is what runs). Fail-loud: unexpected usage
    raises instead of silently passing."""

    def __init__(self, messages=(), recv_error=None, closed=False):
        self._messages = list(messages)
        self.recv_error = recv_error
        self.close_calls = 0
        self.close_code = 1000 if closed else None
        self.recv_calls = 0

    async def recv(self):
        self.recv_calls += 1
        if self.recv_error is not None:
            raise self.recv_error
        if self._messages:
            return self._messages.pop(0)
        await asyncio.Event().wait()  # park: reader suspends, never spins

    async def close(self):
        self.close_calls += 1
        self.close_code = 1000


class FiniteSocket(FakeSocket):
    """Delivers its finite queue and then CLOSES itself (close_code=1000 at
    the last delivery) so the reader exits CLEANLY — no exception — right
    after the last message (is_open() False → while exits, :896). Further
    recv calls fail loud."""

    async def recv(self):
        self.recv_calls += 1
        if self.recv_error is not None:
            raise self.recv_error
        if self._messages:
            message = self._messages.pop(0)
            if not self._messages:
                self.close_code = 1000
            return message
        raise AssertionError("recv after the queue drained — fail-loud")


class SelfCancellingSocket(FakeSocket):
    """Its recv cancels the RUNNING reader task (asyncio.current_task) and
    raises CancelledError — models an external cancellation of a reader while
    it is pending, so the done-processing branch sees ``task.cancelled() →
    continue`` (:866-867) with the flags INTACT."""

    async def recv(self):
        self.recv_calls += 1
        asyncio.current_task().cancel()
        raise asyncio.CancelledError("reader cancelled while pending")


class ConnectStub:
    """Fail-loud stand-in for ``websockets.connect`` (module seam, P-0031):
    pins the exact dial kwargs the module passes (:239-243/:262-266) and hands
    out the prepared sockets in order; an exhausted stub raises."""

    EXPECTED_KWARGS = {"ping_interval": 20, "ping_timeout": 10}

    def __init__(self, sockets):
        self.calls = []
        self._sockets = list(sockets)

    async def __call__(self, url, **kwargs):
        self.calls.append((url, dict(kwargs)))
        if kwargs != self.EXPECTED_KWARGS:
            raise AssertionError(f"unexpected connect kwargs: {kwargs!r}")
        if not self._sockets:
            raise AssertionError("stub exhausted: more dials than sockets prepared")
        return self._sockets.pop(0)


# ---------------------------------------------------------------------------
# Config + manager helpers (pure, per-test; order-independent — P-0029)
# ---------------------------------------------------------------------------
def make_config(**overrides):
    """Config factory. The dummy key is VALID: the T-0030 validator rejects
    all-zero keys, so never "0" * 64 (house pattern)."""
    base = dict(
        POLYGON_PRIVATE_KEY="0" * 63 + "1",
        POLYGON_ADDRESS="0x" + "0" * 40,
        POLYMARKET_CHAIN_ID=137,
        _env_file=None,
    )
    base.update(overrides)
    return PolymarketConfig(**base)


def make_connected_manager(*, clob_socket=None, realtime_socket=None):
    """Manager with both connection flags UP and fake sockets in place — the
    state the supervisor needs to reach the spawn block."""
    manager = WebSocketManager(config=make_config())
    manager.clob_ws = clob_socket if clob_socket is not None else FakeSocket()
    manager.realtime_ws = realtime_socket if realtime_socket is not None else FakeSocket()
    manager.clob_connected = True
    manager.realtime_connected = True
    return manager


def make_handle_recorder(dispatched):
    """Fail-loud instance-level handle_message recorder (P-0031): unexpected
    channel raises; every call is recorded as (channel, parsed_message)."""

    async def record_handle(channel, message):
        if channel not in ("clob", "realtime"):
            raise AssertionError(f"unexpected channel: {channel!r}")
        dispatched.append((channel, message))

    return record_handle


# ---------------------------------------------------------------------------
# start_background_task (:778-791)
# ---------------------------------------------------------------------------
async def test_start_background_task_creates_supervisor_task(monkeypatch):
    """A fresh manager gets ONE supervisor task with should_run=True; one
    tick later the task is still alive (supervising, not done)."""
    manager = WebSocketManager(config=make_config())
    reconnect_calls = []
    manager.reconnect = make_reconnect_recorder(reconnect_calls)  # default state: disconnected
    install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()

        assert manager.should_run is True
        assert manager.background_task is not None
        await settle(lambda: reconnect_calls, label="loop is driving (reconnect branch)")
        await _yield_once()
        assert not manager.background_task.done()  # 1 tick later: still supervising
    finally:
        await teardown_loop(manager)
    assert manager.background_task.done()
    assert manager.background_task.exception() is None  # clean exit


async def test_start_background_task_restarts_after_a_completed_task(monkeypatch):
    """A supervisor task that ALREADY COMPLETED does not trigger the guard's
    warning — start creates a NEW supervisor (the restart path of :784)."""
    manager = WebSocketManager(config=make_config())
    reconnect_calls = []
    manager.reconnect = make_reconnect_recorder(reconnect_calls)
    install_loop_fakes(monkeypatch)
    try:
        stale = asyncio.create_task(_REAL_SLEEP(0))
        await settle(lambda: stale.done(), label="stale supervisor finished")
        manager.background_task = stale

        await manager.start_background_task()

        assert manager.background_task is not stale  # a NEW supervisor task
        assert not manager.background_task.done()
        assert manager.should_run is True
    finally:
        await teardown_loop(manager)


async def test_start_background_task_idempotent_while_running(monkeypatch, caplog):
    """Second call while the supervisor is alive: warning logged, the SAME
    task object is kept, no second task is created (:784-787)."""
    manager = WebSocketManager(config=make_config())
    reconnect_calls = []
    manager.reconnect = make_reconnect_recorder(reconnect_calls)
    install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()
        first_task = manager.background_task
        await settle(lambda: reconnect_calls, label="first supervisor alive")

        with caplog.at_level(logging.WARNING, logger=MANAGER_LOGGER):
            await manager.start_background_task()

        assert any(
            record.levelno == logging.WARNING and "Background task already running" in record.message
            for record in caplog.records
        )
        assert manager.background_task is first_task  # idempotency: same task
        assert manager.should_run is True
    finally:
        await teardown_loop(manager)


# ---------------------------------------------------------------------------
# stop_background_task (:792-806)
# ---------------------------------------------------------------------------
async def test_stop_background_task_awaits_loop_then_disconnects(monkeypatch, caplog):
    """The graceful path: wait_for resolves because the loop exits via
    should_run=False, then disconnect runs (sockets closed, flags reset)."""
    clob_socket, realtime_socket = FakeSocket(), FakeSocket()
    manager = make_connected_manager(clob_socket=clob_socket, realtime_socket=realtime_socket)
    reconnect_calls = []
    manager.reconnect = make_reconnect_recorder(reconnect_calls)
    install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()
        await settle(
            lambda: clob_socket.recv_calls >= 1 and realtime_socket.recv_calls >= 1,
            label="both readers spawned",
        )

        # caplog captures INFO only when its level is lowered (root logger
        # defaults to WARNING); the stop's INFO pair is part of the pin.
        with caplog.at_level(logging.INFO, logger=MANAGER_LOGGER):
            await manager.stop_background_task()  # real wait_for — the loop exits in a few steps

        assert manager.background_task.done()
        assert manager.background_task.cancelled() is False  # graceful: not cancelled
        assert manager.should_run is False
        assert clob_socket.close_calls == 1  # disconnect ran after the wait
        assert realtime_socket.close_calls == 1
        assert manager.clob_connected is False
        assert manager.realtime_connected is False
        assert manager.authenticated is False
        assert any(
            record.levelno == logging.INFO and "Background task stopped" in record.message
            for record in caplog.records
        )
    finally:
        await teardown_loop(manager)


async def test_stop_background_task_cancels_on_timeout(monkeypatch, caplog):
    """The timeout path: wait_for raises TimeoutError immediately (the 5.0s
    budget would be REAL wall time — replaced by the deterministic seam,
    L-0014) → task.cancel() + warning, and disconnect STILL runs (the
    unconditional :805). The loop ends CANCELLED, never normal-complete:
    should_run=False is set synchronously before the cancel is requested, so
    the loop cannot observe it and exit cleanly in between."""
    clob_socket, realtime_socket = FakeSocket(), FakeSocket()
    manager = make_connected_manager(clob_socket=clob_socket, realtime_socket=realtime_socket)
    reconnect_calls = []
    manager.reconnect = make_reconnect_recorder(reconnect_calls)
    install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()
        await settle(
            lambda: clob_socket.recv_calls >= 1 and realtime_socket.recv_calls >= 1,
            label="both readers spawned",
        )

        async def fake_wait_for(fut, timeout=None):
            raise asyncio.TimeoutError("simulated stop timeout (no real wait)")

        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

        with caplog.at_level(logging.WARNING, logger=MANAGER_LOGGER):
            await manager.stop_background_task()

        assert any(
            record.levelno == logging.WARNING
            and "Background task did not stop gracefully, cancelling..." in record.message
            for record in caplog.records
        )
        # disconnect ran DESPITE the timeout path (unconditional after the except):
        assert clob_socket.close_calls == 1
        assert realtime_socket.close_calls == 1
        assert manager.clob_connected is False
        assert manager.realtime_connected is False
        await settle(lambda: manager.background_task.done(), label="cancelled loop finishes")
        assert manager.background_task.cancelled() is True  # the code's cancel took effect
    finally:
        await teardown_loop(manager)


# ---------------------------------------------------------------------------
# _background_loop — spawn branches (:834-841, :842-849)
# ---------------------------------------------------------------------------
async def test_stop_background_task_without_task_disconnects_anyway():
    """stop with NO supervisor task (background_task None): the guard :799
    skips the wait/cancel entirely and disconnect STILL runs (the
    unconditional :805) — flags reset, socket closed."""
    manager = WebSocketManager(config=make_config())
    socket = FakeSocket()
    manager.realtime_ws = socket
    manager.realtime_connected = True
    manager.authenticated = True

    await manager.stop_background_task()

    assert manager.should_run is False
    assert manager.background_task is None  # never created a task
    assert socket.close_calls == 1  # disconnect ran despite the missing task
    assert manager.realtime_connected is False
    assert manager.authenticated is False


async def test_background_loop_spawns_reader_per_open_channel(monkeypatch):
    """Both flags up + both sockets open → exactly ONE reader per channel:
    each reader reaches recv exactly once, then parks on its queue."""
    clob_socket, realtime_socket = FakeSocket(), FakeSocket()
    manager = make_connected_manager(clob_socket=clob_socket, realtime_socket=realtime_socket)
    reconnect_calls = []
    manager.reconnect = make_reconnect_recorder(reconnect_calls)
    install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()
        await settle(
            lambda: clob_socket.recv_calls >= 1 and realtime_socket.recv_calls >= 1,
            label="both readers reached recv",
        )

        assert clob_socket.recv_calls == 1  # one reader, parked after the first recv
        assert realtime_socket.recv_calls == 1
        assert manager.clob_connected is True and manager.realtime_connected is True
    finally:
        await teardown_loop(manager)


async def test_background_loop_spawns_reader_only_for_open_sockets(monkeypatch):
    """Both flags up but the realtime socket ALREADY closed → only the clob
    reader spawns (the spawn gate :842 fails on ws_is_open). The closed
    socket never sees a recv call."""
    clob_socket = FakeSocket()
    realtime_closed = FakeSocket(closed=True)
    manager = make_connected_manager(clob_socket=clob_socket, realtime_socket=realtime_closed)
    reconnect_calls = []
    manager.reconnect = make_reconnect_recorder(reconnect_calls)
    install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()
        await settle(lambda: clob_socket.recv_calls >= 1, label="clob reader spawned")

        assert clob_socket.recv_calls == 1
        assert realtime_closed.recv_calls == 0  # the closed socket gets NO reader
        assert manager.realtime_connected is True  # the FLAG alone does not spawn
    finally:
        await teardown_loop(manager)


async def test_background_loop_idles_when_no_reader_can_spawn(monkeypatch):
    """Both flags up but BOTH sockets closed → readers stay empty → the idle
    branch (:850-852) sleeps the REAL 1.0 (pinned via the fake recorder) and
    loops again — no reader, no recv, forever (bounded by the test)."""
    closed_a, closed_b = FakeSocket(closed=True), FakeSocket(closed=True)
    manager = make_connected_manager(clob_socket=closed_a, realtime_socket=closed_b)
    reconnect_calls = []
    manager.reconnect = make_reconnect_recorder(reconnect_calls)
    sleeps = install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()
        await settle(lambda: len(sleeps) >= 3, label="idle sleeps recorded")

        assert sleeps[:3] == [1.0, 1.0, 1.0]  # the real idle delay, pinned
        assert reconnect_calls == []  # both flags connected → no reconnect
        assert closed_a.recv_calls == 0 and closed_b.recv_calls == 0
    finally:
        await teardown_loop(manager)


# ---------------------------------------------------------------------------
# _background_loop — done-processing branches (:863-874)
# ---------------------------------------------------------------------------
async def test_background_loop_replaces_reader_on_clean_completion(monkeypatch):
    """A reader that exits WITHOUT an exception (its socket closed after the
    last message) is removed from the registry with the flags INTACT and
    replaced on the next iteration once an open socket exists again. The
    error branch is the ONLY path that clears flags."""
    finite = FiniteSocket(['{"type":"price_change","asset_id":"a","price":"0.5"}'])
    parked = FakeSocket()  # realtime: open, parks forever
    manager = make_connected_manager(clob_socket=finite, realtime_socket=parked)
    dispatched = []
    manager.handle_message = make_handle_recorder(dispatched)
    reconnect_calls = []
    manager.reconnect = make_reconnect_recorder(reconnect_calls)
    install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()
        await settle(lambda: len(dispatched) >= 1, label="reader 1 delivered")
        assert finite.recv_calls == 1
        assert manager.clob_connected is True and manager.realtime_connected is True

        # Reader 1 completed cleanly (its socket closed itself). Swap in the
        # open socket a successful reconnect would install; the next
        # iteration spawns a REPLACEMENT reader (:834).
        fresh = FakeSocket(['{"type":"price_change","asset_id":"a2","price":"0.6"}'])
        manager.clob_ws = fresh
        await settle(
            lambda: any(c == "clob" and m.get("asset_id") == "a2" for c, m in dispatched),
            label="reader replaced after clean completion",
        )

        assert dispatched == [
            ("clob", {"type": "price_change", "asset_id": "a", "price": "0.5"}),
            ("clob", {"type": "price_change", "asset_id": "a2", "price": "0.6"}),
        ]
        # fresh.recv_calls == 2 is the OBSERVED reader semantics: one recv
        # delivers the message, the next parks on the empty queue (1 = the
        # finite socket's delivery; finite closed itself so its reader exited
        # without a park attempt).
        assert finite.recv_calls == 1 and fresh.recv_calls == 2
        # Flags remain intact after the clean replacement:
        assert manager.clob_connected is True and manager.realtime_connected is True
    finally:
        await teardown_loop(manager)


async def test_background_loop_replaces_failed_reader_and_clears_its_flag(monkeypatch, caplog):
    """A reader that dies with a transport error: the loop logs the warning,
    removes the dead reader from the registry (the del IS the replacement,
    :865) and clears ONLY the dead channel's flag (realtime stays up — the
    SELECTIVITY pin :871-874). The next iteration enters the reconnect branch
    (the recorder fires) — DIVERGENCE (L-0025/L-0143): the contract draft's
    "reader replaced on the next iteration" is NOT what the code does while a
    flag is down — the not-connected branch (:829-832) PREEMPTS the spawn
    block, so the respawn only happens after a SUCCESSFUL reconnect (pinned
    in the clean-completion test). Without a restore the dead reader is never
    respawned (recv_calls stays 1) — pinned as observed."""
    boom = FakeSocket(recv_error=RuntimeError("boom"))
    parked = FakeSocket()
    manager = make_connected_manager(clob_socket=boom, realtime_socket=parked)
    reconnect_calls = []
    manager.reconnect = make_reconnect_recorder(reconnect_calls)  # pure recorder — no restore
    install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()
        await settle(lambda: boom.recv_calls >= 1, label="clob reader hit recv")
        # The warning fires during the done-processing (before the reconnect
        # branch); while the loop is suspended inside the reconnect fake the
        # flag state is the post-processing one — deterministic window.
        await settle(
            lambda: any("clob reader stopped: boom" in r.message for r in caplog.records),
            label="dead reader processed",
        )

        assert manager.clob_connected is False
        assert manager.realtime_connected is True  # SELECTIVITY — mutation M1 target
        assert any(
            record.levelno == logging.WARNING and "clob reader stopped: boom" in record.message
            for record in caplog.records
        )
        assert any("Error receiving CLOB message: boom" in record.message for record in caplog.records)
        await settle(lambda: len(reconnect_calls) >= 1, label="reconnect branch entered")
        # No respawn while the flag is down: the not-connected branch preempts.
        assert boom.recv_calls == 1
        assert parked.recv_calls == 1  # the live reader was reaped by the reconnect branch
    finally:
        await teardown_loop(manager)


async def test_background_loop_tolerates_cancelled_reader_without_clearing_flags(monkeypatch):
    """A reader CANCELLED while pending (external cancel, not an error) is
    removed from the registry via ``task.cancelled() → continue`` (:866-867)
    with the flags INTACT — cancellation is distinct from the error branch —
    and is replaced on the next iteration (both flags still up)."""
    self_cancel = SelfCancellingSocket()
    parked = FakeSocket()
    manager = make_connected_manager(clob_socket=self_cancel, realtime_socket=parked)
    reconnect_calls = []
    manager.reconnect = make_reconnect_recorder(reconnect_calls)
    install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()
        await settle(lambda: self_cancel.recv_calls >= 2, label="cancelled reader replaced twice")

        assert manager.clob_connected is True and manager.realtime_connected is True
        assert reconnect_calls == []  # no error branch ran → no reconnect needed
        assert parked.recv_calls == 1  # the realtime reader stayed alive, parked
    finally:
        await teardown_loop(manager)


# ---------------------------------------------------------------------------
# _background_loop — reconnect branches (:829-832, :876-882)
# ---------------------------------------------------------------------------
async def test_background_loop_reconnects_when_connections_down(monkeypatch):
    """End-to-end: a dropped connection flag enters the not-connected branch
    (:829-832) — parked readers are cancelled, the REAL reconnect runs
    (fake sleep, stubbed connect), restores both flags, and the loop resumes
    reading on the NEW sockets."""
    old_clob, old_rt = FakeSocket(), FakeSocket()
    manager = make_connected_manager(clob_socket=old_clob, realtime_socket=old_rt)
    new_clob, new_rt = FakeSocket(), FakeSocket()
    stub = ConnectStub([new_clob, new_rt])
    monkeypatch.setattr(websockets, "connect", stub)  # stub BEFORE any dial (L-0118)
    sleeps = install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()
        await settle(
            lambda: old_clob.recv_calls >= 1 and old_rt.recv_calls >= 1,
            label="initial readers parked",
        )
        old_clob_count, old_rt_count = old_clob.recv_calls, old_rt.recv_calls

        manager.clob_connected = False  # the connection dropped
        await settle(
            lambda: manager.clob_ws is new_clob and manager.realtime_ws is new_rt,
            label="reconnect installed new sockets",
        )
        await settle(
            lambda: new_clob.recv_calls >= 1 and new_rt.recv_calls >= 1,
            label="loop resumed on the new sockets",
        )

        assert manager.reconnect_count == 1  # the real reconnect restored the flags
        assert len(stub.calls) == 2  # CLOB then realtime
        assert old_clob.close_calls == 1 and old_rt.close_calls == 1  # disconnect inside
        assert manager.clob_connected is True and manager.realtime_connected is True
        assert sleeps and 1.0 in sleeps  # the backoff delay before the dial (attempt 0)
        assert old_clob.recv_calls == old_clob_count  # old readers cancelled — nothing resumed
        assert old_rt.recv_calls == old_rt_count
    finally:
        await teardown_loop(manager)


async def test_background_loop_catches_connection_closed_and_reconnects(monkeypatch, caplog):
    """The ConnectionClosed branch (:876-879): reconnect raising
    websockets.exceptions.ConnectionClosed on the FIRST call is caught —
    warning logged, readers cancelled, reconnect invoked AGAIN (the 2nd call
    succeeds) — and the loop SURVIVES and keeps supervising (pinned as
    observed; L-0025/L-0090)."""
    clob_socket, rt_socket = FakeSocket(), FakeSocket()
    manager = make_connected_manager(clob_socket=clob_socket, realtime_socket=rt_socket)
    reconnect_calls = []

    async def fake_reconnect():
        reconnect_calls.append(True)
        if len(reconnect_calls) == 1:
            raise websockets.exceptions.ConnectionClosed(None, None)
        manager.clob_connected = True  # 2nd call succeeds — restores the flags
        manager.realtime_connected = True
        await _yield_once()

    manager.reconnect = fake_reconnect
    install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()
        await settle(
            lambda: clob_socket.recv_calls >= 1 and rt_socket.recv_calls >= 1,
            label="readers parked",
        )
        assert manager.realtime_connected is True

        manager.clob_connected = False  # enters the not-connected branch
        await settle(lambda: len(reconnect_calls) >= 2, label="reconnect called twice")

        assert any(
            record.levelno == logging.WARNING
            and "WebSocket connection closed, reconnecting..." in record.message
            for record in caplog.records
        )
        assert len(reconnect_calls) == 2  # the 2nd call succeeded → loop resumed
        assert manager.clob_connected is True and manager.realtime_connected is True
        # The readers respawned on the restored state — settle first: the
        # respawn happens on the iteration AFTER the 2nd reconnect returns.
        await settle(
            lambda: clob_socket.recv_calls >= 2 and rt_socket.recv_calls >= 2,
            label="readers respawned after the recovered reconnect",
        )
        assert clob_socket.recv_calls == 2 and rt_socket.recv_calls == 2
    finally:
        await teardown_loop(manager)


async def test_background_loop_survives_generic_exception_with_error_log(monkeypatch, caplog):
    """The generic Exception branch (:880-882): a reconnect that raises a
    plain RuntimeError is logged with ``Error in background loop``, followed
    by the 1.0 sleep (pinned via the fake recorder), and the loop KEEPS
    GOING — a dead reader must never kill the supervisor silently."""
    manager = WebSocketManager(config=make_config())
    reconnect_calls = []

    async def fake_reconnect():
        reconnect_calls.append(True)
        if len(reconnect_calls) == 1:
            raise RuntimeError("reconnect exploded")
        await _yield_once()

    manager.reconnect = fake_reconnect
    sleeps = install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()  # default state: disconnected → reconnect branch
        await settle(lambda: reconnect_calls, label="first reconnect attempt")
        manager.clob_connected = False  # keep the branch active
        manager.realtime_connected = False
        await settle(lambda: len(reconnect_calls) >= 3, label="loop survived the error")

        assert any(
            record.levelno == logging.ERROR and "Error in background loop: reconnect exploded"
            in record.message
            for record in caplog.records
        )
        assert sleeps and all(s == 1.0 for s in sleeps)  # the branch's sleep(1.0)
        assert manager.should_run is True  # still supervising
    finally:
        await teardown_loop(manager)


# ---------------------------------------------------------------------------
# _background_loop — clean exit (:883-886)
# ---------------------------------------------------------------------------
async def test_background_loop_exits_cleanly_when_should_run_flips_false(monkeypatch):
    """Flipping should_run exits the while → the finally reaps the parked
    readers (cancel + gather) and the task completes WITHOUT exception and
    WITHOUT cancellation."""
    clob_socket, rt_socket = FakeSocket(), FakeSocket()
    manager = make_connected_manager(clob_socket=clob_socket, realtime_socket=rt_socket)
    reconnect_calls = []
    manager.reconnect = make_reconnect_recorder(reconnect_calls)
    install_loop_fakes(monkeypatch)
    try:
        await manager.start_background_task()
        await settle(
            lambda: clob_socket.recv_calls >= 1 and rt_socket.recv_calls >= 1,
            label="readers parked",
        )

        manager.should_run = False
        await settle(lambda: manager.background_task.done(), label="loop exit via finally")

        assert manager.background_task.cancelled() is False
        assert manager.background_task.exception() is None
        assert clob_socket.recv_calls == 1  # no recv after the flip — readers were reaped
        assert rt_socket.recv_calls == 1
        assert_no_reader_leaks()  # the finally's _cancel_readers reaped everything
    finally:
        await teardown_loop(manager)


# ---------------------------------------------------------------------------
# _read_channel (:888-897) — call-counter pin (dedupe: readers.py owns the
# closed-socket mechanics; this file pins the N-call semantics)
# ---------------------------------------------------------------------------
async def test_read_channel_loops_while_open_and_stops_when_closed():
    """The reader loops while should_run AND is_open() hold: N receive_one
    calls, then stops when is_open() flips False; the other exit condition is
    should_run flipping False (the manager's stop)."""
    manager = WebSocketManager(config=make_config())
    manager.should_run = True
    calls = []
    is_open_state = {"open": True}

    async def receive_one():
        calls.append(1)
        if len(calls) >= 3:
            is_open_state["open"] = False  # socket closes → the reader stops

    await manager._read_channel(receive_one, lambda: is_open_state["open"])
    assert len(calls) == 3  # N calls, then the is_open exit

    calls2 = []
    is_open_state2 = {"open": True}

    async def receive_two():
        calls2.append(1)
        if len(calls2) >= 2:
            manager.should_run = False  # manager stop → the reader stops

    await manager._read_channel(receive_two, lambda: is_open_state2["open"])
    assert len(calls2) == 2  # N calls, then the should_run exit
    assert manager.should_run is False


# ---------------------------------------------------------------------------
# _receive_clob_messages (:907-920)
# ---------------------------------------------------------------------------
async def test_receive_clob_dispatches_parsed_message_to_handle_message():
    """recv → json.loads → handle_message("clob", parsed) — the recorder is
    pinned with the EXACT parsed dict."""
    manager = WebSocketManager(config=make_config())
    socket = FakeSocket(['{"type":"price_change","asset_id":"a","price":"0.5"}'])
    manager.clob_ws = socket
    dispatched = []
    manager.handle_message = make_handle_recorder(dispatched)

    await manager._receive_clob_messages()

    assert dispatched == [("clob", {"type": "price_change", "asset_id": "a", "price": "0.5"})]
    assert socket.recv_calls == 1


async def test_receive_clob_ignores_unparseable_message(caplog):
    """Non-JSON payload: JSONDecodeError is SWALLOWED (:916-917) — logged,
    handle_message NEVER called, no raise."""
    manager = WebSocketManager(config=make_config())
    socket = FakeSocket(["{not json"])
    manager.clob_ws = socket
    dispatched = []
    manager.handle_message = make_handle_recorder(dispatched)

    with caplog.at_level(logging.ERROR, logger=MANAGER_LOGGER):
        await manager._receive_clob_messages()  # NO raise

    assert dispatched == []
    assert socket.recv_calls == 1
    assert any(
        record.levelno == logging.ERROR and "Failed to parse CLOB message" in record.message
        for record in caplog.records
    )


async def test_receive_clob_propagates_non_json_errors(caplog):
    """A transport error is logged AND RE-RAISED (:918-920) — the reader task
    dies with the exception, which is the input of the flag-selectivity
    branch."""
    manager = WebSocketManager(config=make_config())
    socket = FakeSocket(recv_error=RuntimeError("transport dead"))
    manager.clob_ws = socket
    dispatched = []
    manager.handle_message = make_handle_recorder(dispatched)

    with caplog.at_level(logging.ERROR, logger=MANAGER_LOGGER):
        with pytest.raises(RuntimeError, match="transport dead"):
            await manager._receive_clob_messages()

    assert dispatched == []
    assert any(
        record.levelno == logging.ERROR and "Error receiving CLOB message: transport dead"
        in record.message
        for record in caplog.records
    )


async def test_receive_clob_returns_before_recv_when_socket_closed():
    """Closed socket (close_code set): the guard :910-911 returns BEFORE any
    recv — the transport is never touched and nothing dispatches."""
    manager = WebSocketManager(config=make_config())
    socket = FakeSocket(closed=True)
    manager.clob_ws = socket
    dispatched = []
    manager.handle_message = make_handle_recorder(dispatched)

    await manager._receive_clob_messages()

    assert socket.recv_calls == 0  # guard returned BEFORE recv
    assert dispatched == []


# ---------------------------------------------------------------------------
# _receive_realtime_messages (:922-935) — the mirrored trio
# ---------------------------------------------------------------------------
async def test_receive_realtime_dispatches_parsed_message():
    """recv → json.loads → handle_message("realtime", parsed) — channel
    pinned as the realtime one."""
    manager = WebSocketManager(config=make_config())
    socket = FakeSocket(['{"type":"trades","asset_id":"b"}'])
    manager.realtime_ws = socket
    dispatched = []
    manager.handle_message = make_handle_recorder(dispatched)

    await manager._receive_realtime_messages()

    assert dispatched == [("realtime", {"type": "trades", "asset_id": "b"})]
    assert socket.recv_calls == 1


async def test_receive_realtime_ignores_unparseable_message(caplog):
    """Non-JSON payload on the realtime channel: swallowed (:932-933)."""
    manager = WebSocketManager(config=make_config())
    socket = FakeSocket(["{not json"])
    manager.realtime_ws = socket
    dispatched = []
    manager.handle_message = make_handle_recorder(dispatched)

    with caplog.at_level(logging.ERROR, logger=MANAGER_LOGGER):
        await manager._receive_realtime_messages()  # NO raise

    assert dispatched == []
    assert socket.recv_calls == 1
    assert any(
        record.levelno == logging.ERROR and "Failed to parse real-time message" in record.message
        for record in caplog.records
    )


async def test_receive_realtime_propagates_non_json_errors(caplog):
    """A transport error on the realtime channel: logged AND re-raised
    (:934-936)."""
    manager = WebSocketManager(config=make_config())
    socket = FakeSocket(recv_error=RuntimeError("realtime transport dead"))
    manager.realtime_ws = socket
    dispatched = []
    manager.handle_message = make_handle_recorder(dispatched)

    with caplog.at_level(logging.ERROR, logger=MANAGER_LOGGER):
        with pytest.raises(RuntimeError, match="realtime transport dead"):
            await manager._receive_realtime_messages()

    assert dispatched == []
    assert any(
        record.levelno == logging.ERROR
        and "Error receiving real-time message: realtime transport dead" in record.message
        for record in caplog.records
    )


async def test_receive_realtime_returns_before_recv_when_socket_closed():
    """Closed realtime socket: the guard :925 returns BEFORE any recv."""
    manager = WebSocketManager(config=make_config())
    socket = FakeSocket(closed=True)
    manager.realtime_ws = socket
    dispatched = []
    manager.handle_message = make_handle_recorder(dispatched)

    await manager._receive_realtime_messages()

    assert socket.recv_calls == 0
    assert dispatched == []


# ---------------------------------------------------------------------------
# _cancel_readers (:899-905) — registry + gather semantics (dedupe: readers.py
# owns the leak checks; this file pins the registry-clear + cancelled state)
# ---------------------------------------------------------------------------
async def test_cancel_readers_awaits_and_clears_registry():
    """_cancel_readers cancels every reader, awaits them (gather with
    return_exceptions=True) and clears the registry; a done task is left
    done (cancel on a finished task is a no-op), a parked one ends
    CANCELLED."""
    async def _noop():
        return "done"

    done_task = asyncio.create_task(_noop())
    parked_task = asyncio.create_task(asyncio.Event().wait())
    await _yield_once()  # let _noop finish

    readers = {"clob": done_task, "realtime": parked_task}
    await WebSocketManager._cancel_readers(readers)

    assert readers == {}  # registry cleared
    assert parked_task.cancelled() is True  # the parked reader was awaited-and-cancelled
    assert done_task.done() and not done_task.cancelled()  # done task untouched
    assert done_task.result() == "done"
