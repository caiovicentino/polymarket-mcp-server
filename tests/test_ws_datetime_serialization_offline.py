"""
Offline regression suite for the /ws datetime-serialization crash (V-WSDT).

T-0282 (farm 2026-09-18, curator contract; provenance: probe $TMPDIR/c62-probe-ws.py
-- RED SENT=0 against pristine app.py, GREEN 2 full frames + clean disconnect after
the fix on sim/c62-ws @ ac374e5). Playbooks: [P-0036 RED-first, P-0031 fail-loud
seams, P-0012 no-network].

DEFECT (V-WSDT): the module-level ``stats`` dict in src/polymarket_mcp/web/app.py
carries ``uptime_start: datetime``. The /ws endpoint (websocket_endpoint) calls
``websocket.send_json`` on the FIRST frame (status) and on every stats_update frame
-- and Starlette's send_json serializes with plain ``json.dumps``, which cannot
encode datetime -> ``TypeError: Object of type datetime is not JSON serializable``
on the FIRST frame. The endpoint's generic ``except Exception`` swallows the error
and removes the socket: every dashboard WebSocket dies instantly, and the browser
reconnect loop spams the server log with ``WebSocket error: Object of type datetime
is not JSON serializable`` (proven live 2026-09-18).

WHY THE EXISTING SUITE MISSED IT: tests/test_web_app_offline.py:199-231 ships a
FakeWebSocket whose send_json only APPENDS the message -- it never serializes
(stub-vs-real gap). The /ws pins there (sent types, connected flag, sleeps == [5])
pass vacuously against the broken app because the fake never runs json.dumps.

WHY NO TestClient HERE: probed 1st-hand, the real TestClient HANGS (120s+) against
the pristine app -- the server swallows the TypeError inside the endpoint and the
client's receive waits forever (RED-state hang). This suite drives
``wa.websocket_endpoint`` DIRECTLY with an in-memory SerializingFakeWebSocket:
deterministic, zero-network, zero real sleeps.

Divergences contract x implementation (declared per L-0025/L-0090, observable wins):
1. The contract's inline fake snippet used ``len(self.sent) > self._fail_on`` with
   fail_on=2, which would record 3 frames / sleeps [5, 5] -- contradicting the
   contract's own mandated assertions (len == 2, sleeps == [5]) and its own words
   ("2 entries with fail_on 2, identical to the existing FakeWebSocket"). The
   curator's probe provenance ($TMPDIR/c62-probe-ws.py) uses the ``==`` comparison,
   identical to the existing FakeWebSocket (raise AFTER appending the fail-th
   send). Implemented with ``==`` -- the observable contract wins.
2. The contract's parenthetical for test 2 ("receive_text that raises
   StopAsyncIteration/Exception to exit after the 2 sends") is dead mechanically:
   websocket_endpoint never calls receive_text (app.py:458-493 -- accept/append/
   send/sleep/send only). The loop exits via the fake's WebSocketDisconnect raised
   on the fail-th send (fail_on=2), mirroring the existing house pin.
3. The contract labels uptime_start "(isoformat)"; the actual ``default=str``
   conversion produces str(datetime) -- "YYYY-MM-DD HH:MM:SS.ffffff" (space
   separator), exactly as the fix's own docstring states. Pinned as isinstance(str)
   only (the mandatory assertion); no format regex (over-coupling avoidance).

Seams (P-0031): wa.asyncio replaced by a SimpleNamespace whose sleep records and
returns instantly (L-0014 -- no real 5s wait, ever; monkeypatch restores). The
socket is an in-memory fake; no HTTP surface is touched (no TestClient, no httpx)
-- zero network BY CONSTRUCTION, not by discipline.

Hermeticity: autouse fixture pristine_web_state (inlined, zero-config -- FA-0079;
fixtures are not imported across suites) resets wa.config/wa.client/
wa.safety_limits/wa.active_websockets and installs a per-test COPY of stats,
restoring the original object identity on teardown (L-0022).

Prerequisites: pytest-asyncio auto mode (pyproject [tool.pytest.ini_options]);
fastapi in the clone venv. No integration/slow/real_api/performance markers.
"""
import json
import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Optional

import pytest
from fastapi import WebSocketDisconnect

from polymarket_mcp.web import app as wa

# Captured at import time, before any test runs: the pristine stats dict (the
# module never mutates it directly -- handlers only see per-test copies; the
# /ws fix serializes a COPY via _json_safe, never mutating module state).
_PRISTINE_STATS = dict(wa.stats)


class SerializingFakeWebSocket:
    """FakeWebSocket that REALLY serializes (plain json.dumps) before recording.

    Exposes the V-WSDT crash that the non-serializing FakeWebSocket of
    tests/test_web_app_offline.py hides (stub-vs-real gap): Starlette's send_json
    runs json.dumps on every frame, so a datetime in the payload raises TypeError
    THERE -- not at the fake's append. Append-then-raise order mirrors the
    existing FakeWebSocket exactly (raise AFTER recording the fail-th send), so
    the same assertions apply.

    Args:
        fail_on_send_index: 1-based index of the send that raises (after being
            recorded). None = never raise (the caller must terminate the loop
            another way; here the /ws loop runs forever, so tests always set it).
        fail_with: the exception to raise on the fail-th send.
    """

    def __init__(
        self,
        fail_on_send_index: Optional[int] = None,
        fail_with: Optional[Exception] = None,
    ) -> None:
        self.accepted = 0
        self.sent: list[dict] = []
        self.closed = 0
        self.fail_on_send_index = fail_on_send_index
        self.fail_with = fail_with

    async def accept(self) -> None:
        self.accepted += 1

    async def send_json(self, message: dict, mode: str = "text") -> None:
        json.dumps(message)  # the REAL Starlette contract: datetime -> TypeError
        self.sent.append(message)
        if (
            self.fail_on_send_index is not None
            and len(self.sent) == self.fail_on_send_index
        ):
            raise self.fail_with

    async def close(self) -> None:
        self.closed += 1


@pytest.fixture(autouse=True)
def pristine_web_state():
    """Reset web.app module globals per test and restore the originals (L-0022).

    The lifespan writes wa.config/wa.client/wa.safety_limits DIRECTLY (global
    statement) and handlers mutate wa.stats in place -- both bypass monkeypatch.
    Each test therefore starts from the pristine baseline (captured at import)
    with a per-test COPY of stats, and teardown restores the original objects,
    making the suite order-independent.
    """
    wa.config = None
    wa.client = None
    wa.safety_limits = None
    wa.active_websockets = []
    wa.stats = dict(_PRISTINE_STATS)
    yield
    wa.config = None
    wa.client = None
    wa.safety_limits = None
    wa.active_websockets = []
    wa.stats = _PRISTINE_STATS


def _install_fake_sleep(monkeypatch: pytest.MonkeyPatch, sleeps: list) -> None:
    """Replace wa.asyncio with a namespace whose sleep records and returns (L-0014)."""

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(wa, "asyncio", SimpleNamespace(sleep=fake_sleep))


# ============================================================================
# V-WSDT: /ws frames must survive REAL serialization
# ============================================================================


async def test_ws_frames_survive_datetime_serialization(monkeypatch):
    """V-WSDT: /ws must deliver BOTH frames (status + stats_update) when the
    fake REALLY serializes -- the pristine app dies on frame 1 (TypeError from
    json.dumps, swallowed by the endpoint's generic except -> socket removed).

    RED pre (proven 2026-09-18 against pristine app.py, P-0036): the first
    send_json raises TypeError BEFORE the fake appends, so len(socket.sent) == 0
    -- clean AssertionError, no hang (the fake sleep never waits; the endpoint's
    except Exception swallows the error and returns)."""
    sleeps: list[float] = []
    _install_fake_sleep(monkeypatch, sleeps)
    socket = SerializingFakeWebSocket(
        fail_on_send_index=2, fail_with=WebSocketDisconnect()
    )
    await wa.websocket_endpoint(socket)
    assert socket.accepted == 1
    assert len(socket.sent) == 2
    # Initial frame: status with the module's connected state (globals clean).
    assert socket.sent[0]["type"] == "status"
    assert socket.sent[0]["data"]["connected"] is False
    # Second frame: the periodic stats_update.
    assert socket.sent[1]["type"] == "stats_update"
    # The loop's only real dependency: a 5-second cadence, never awaited real.
    assert sleeps == [5]


async def test_ws_stats_payload_is_json_safe(monkeypatch):
    """The stats payload carried by BOTH /ws frames is JSON-serializable
    end-to-end, and uptime_start is delivered as a str (the fix's default=str
    conversion). The module-level stats dict keeps its REAL datetime -- the fix
    serializes a COPY, never mutating module state (updateDashboardStats in the
    JS monitor reads data.stats.*, so the shape must stay compatible)."""
    sleeps: list[float] = []
    _install_fake_sleep(monkeypatch, sleeps)
    socket = SerializingFakeWebSocket(
        fail_on_send_index=2, fail_with=WebSocketDisconnect()
    )
    await wa.websocket_endpoint(socket)
    assert len(socket.sent) == 2
    for frame in socket.sent:
        json.dumps(frame)  # must not raise (V-WSDT: TypeError pre-fix)
        json.dumps(frame["data"]["stats"])
    stats_payload = socket.sent[1]["data"]["stats"]
    assert isinstance(stats_payload["uptime_start"], str)
    assert isinstance(wa.stats["uptime_start"], datetime)


async def test_ws_disconnect_after_fix_is_clean(monkeypatch, caplog):
    """With fail_on=2 (WebSocketDisconnect raised AFTER the 2nd send is recorded),
    the endpoint takes the CLEAN disconnect path: the socket is removed from
    active_websockets and 'WebSocket client disconnected' is logged (mirrors the
    removal pin of tests/test_web_app_offline.py:976-981)."""
    sleeps: list[float] = []
    _install_fake_sleep(monkeypatch, sleeps)
    socket = SerializingFakeWebSocket(
        fail_on_send_index=2, fail_with=WebSocketDisconnect()
    )
    with caplog.at_level(logging.INFO, logger="polymarket_mcp.web.app"):
        await wa.websocket_endpoint(socket)
    assert socket not in wa.active_websockets
    assert wa.active_websockets == []
    assert any(
        "WebSocket client disconnected" in record.getMessage()
        for record in caplog.records
    )
