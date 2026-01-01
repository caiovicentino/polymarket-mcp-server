"""Offline E2E stdio conformance suite for the MCP pre-handshake wire shapes (T-0425).

Closes the R-27 discrepancy: research.md R-27 (2026-09-19) reported conformance
issues #39/#40 as CURRENT violations, but the timeline proves the report was a
STALE demand snapshot: the issues were opened 2026-09-16T02:04Z while the fix
(MCP conformance #39/#40) merged the SAME DAY at 14:23:19 via
"farm: lote de 25 commits - T-0046 (MCP conformance #39/#40), T-0064 (docs
claims), T-0065 (lifecycle server.py 98.91%) (#49)". The in-process suite
tests/test_mcp_conformance_offline.py (11 tests, R1-R9) is already GREEN on
main. What the in-process suite does NOT prove is TRANSPORT FIDELITY: the
external conformance suite (@hasmcp/mcp-spec-test) speaks stdio of a REAL
process, while the in-process suite drives the SAME interceptor
(_PreHandshakeStream) through the anyio pipeline. This suite proves the
spec-test wire shapes against the REAL server process over real stdio
(subprocess.Popen), offline and hermetic:

- R1-E2E: ``server/discover`` as the process's FIRST message (no session, no
  prior initialize) -> a result carrying a valid DiscoverResult (never a
  timeout, never -32602), with every field the published 2026-07-28 schema
  requires (same literal set the in-process suite pins).
- R7-E2E: a version-less ``initialize`` (params WITHOUT _meta) -> served on
  the declared default. Identity with the in-process R7
  (tests/test_mcp_conformance_offline.py:302-322): the literal pin
  "2026-07-28" is deliberate (mutation M3 proved asserting against the module
  constant is circular with the implementation).
- R8-E2E: an ``initialize`` whose params._meta declares an UNSUPPORTED
  version ("9999.99.99") -> refused with -32022 plus the supported list
  (never a timeout; the offered version never appears in the supported
  list).
- R8b-E2E: an ``initialize`` whose params._meta declares a SUPPORTED
  non-default revision (the oldest declared, "2025-11-25") -> negotiation
  pass-through (a result, never a refusal).
- R9-E2E: the well-formed official-SDK-style handshake still works
  (initialize echoes the offered SDK-era version + tools/list after
  notifications/initialized - official interop regression guard).

Wire shapes (the spec-test lib/rpc.mjs buildRequest/requestMeta): the
per-request version rides in
``params._meta["io.modelcontextprotocol/protocolVersion"]`` together with
``io.modelcontextprotocol/clientCapabilities`` and
``io.modelcontextprotocol/clientInfo``; a version-less request omits _meta
entirely.

Timeout signature: the symptoms reported in issues #39/#40 were TIMEOUTs
(the spec run's 10s budget). Every request here uses the T-0288 standard:
per-request timeout 30s with kill-on-hang - "no timeout" is the signature of
R1/R7/R8/R8b: the test returns; a hang kills the subprocess and fails loud.

Hermeticity (P-0029): the spawned server would reach the real network in two
places when running without API credentials (initialize_server attempts
create_api_credentials via httpx; the WebSocketManager background task dials
the hardcoded wss:// endpoints). Both channels are made deterministically
inoperative by an inoperative local proxy env (HTTP_PROXY/HTTPS_PROXY/
ALL_PROXY = "http://127.0.0.1:1") - the T-0288 standard, proven 1st-hand
there: httpx (trust_env) and the websockets library both fail fast against
the dead local port with ZERO external network traffic (captured by the
initialize_server except / background task). The subprocess env is built by
sanitizing every PolymarketConfig-mapped key from the host env (P-0035 both
directions) with DEMO_MODE=true (initialize_server loads a real demo config
- the T-0288 observable) and a PYTHONPATH derived from this file's location
(never a hardcoded author path). cwd is a pristine tmp_path so the host's
.env never leaks (P-0037).

Anatomy: zero sleeps (L-0014), zero network, zero integration/slow/real_api
markers, semantic assertions (L-0002), no monkeypatch of SDK internals - the
only global touched is the SDK's public SUPPORTED_PROTOCOL_VERSIONS list via
discover.ensure_sdk_supports_declared_revisions, invoked by the INTERCEPTOR
inside the spawned process (idempotent; identical to the in-process suite).

Session mechanics are COPIED (never imported) from
tests/test_mcp_stdio_e2e_offline.py (T-0288, the house stdio spawn standard):
one pump thread per pipe (portable - no select on pipes), newline-delimited
JSON-RPC with explicit flush, per-request timeout 30s with kill-on-hang,
explicit encoding="utf-8" (P-0099).
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import polymarket_mcp

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

# Every env key the spawned config would read, removed from the host env
# before the subprocess starts (P-0035 both directions): prefixed credentials
# plus the unprefixed gap fields of the house pattern, plus proxy vars so the
# inoperative proxy defense below cannot be silently neutralized.
_ENV_PREFIXES = ("POLYGON_", "POLYMARKET_")
_ENV_KEYS = (
    "DEMO_MODE",
    "LOG_LEVEL",
    "CLOB_API_URL",
    "GAMMA_API_URL",
    "USDC_ADDRESS",
    "CTF_EXCHANGE_ADDRESS",
    "CONDITIONAL_TOKEN_ADDRESS",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)
_ENV_LOOSE_PREFIXES = ("MAX_", "MIN_", "ENABLE_", "REQUIRE_", "AUTO_")

# Inoperative local proxy: every outbound channel of the spawned server
# (httpx via trust_env, websockets) fails fast against this dead local port
# with zero external network traffic (T-0288 standard).
_INOPERATIVE_PROXY = "http://127.0.0.1:1"

# ---------------------------------------------------------------------------
# Literal pins (never imported from the implementation: mutation M3 of the
# in-process suite proved the module constant is circular with itself).
# ---------------------------------------------------------------------------
SUITE_SUPPORTED_REVISIONS = frozenset({"2026-07-28", "2025-11-25"})
DISCOVER_RESULT_REQUIRED_FIELDS = frozenset(
    {"cacheScope", "capabilities", "resultType", "supportedVersions", "ttlMs"}
)
DEFAULT_DECLARED_REVISION = "2026-07-28"
OLDEST_DECLARED_REVISION = "2025-11-25"
UNSERVABLE_VERSION = "9999.99.99"
UNSUPPORTED_VERSION_CODE = -32022
SERVER_NAME = "polymarket-trading"
# The SDK-era handshake the official client speaks on stdio (T-0288 observable).
SDK_OFFICIAL_HANDSHAKE_VERSION = "2024-11-05"


def _suite_meta(version: str) -> dict[str, Any]:
    """The per-request _meta the conformance suite sends (rpc.mjs requestMeta).

    protocolVersion + clientCapabilities (both schema-required) plus
    clientInfo (a SHOULD, included by the suite by default).
    """
    return {
        "io.modelcontextprotocol/protocolVersion": version,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {
            "name": "mcp-spec-test",
            "version": "0.1.1",
        },
    }


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove every config-mapped env key from the TEST process (P-0035).

    This sanitizes the os.environ the subprocess env is built from, so a
    hostile host env cannot leak credentials or controls into the spawned
    server. DEMO_MODE and PYTHONPATH are re-set explicitly in _build_env.
    """
    for key in list(os.environ):
        if (
            key.startswith(_ENV_PREFIXES)
            or key.startswith(_ENV_LOOSE_PREFIXES)
            or key in _ENV_KEYS
        ):
            monkeypatch.delenv(key, raising=False)


def _build_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Subprocess env: sanitized host env (P-0035) + demo mode + inoperative
    proxy + a PYTHONPATH derived from this file's location (never a hardcoded
    author path)."""
    env = dict(os.environ)
    env["DEMO_MODE"] = "true"
    env["PYTHONPATH"] = str(SRC_DIR)
    env["HTTP_PROXY"] = _INOPERATIVE_PROXY
    env["HTTPS_PROXY"] = _INOPERATIVE_PROXY
    env["ALL_PROXY"] = _INOPERATIVE_PROXY
    if extra:
        env.update(extra)
    return env


class StdioSession:
    """A newline-delimited JSON-RPC session with the real server subprocess.

    Copied from the T-0288 standard (tests/test_mcp_stdio_e2e_offline.py),
    never imported from the sibling file. One pump thread per pipe
    (Windows-portable), each request flushed as a single line, per-request
    timeout with loud failure and kill-on-hang at teardown. Explicit
    encoding="utf-8" (P-0099).
    """

    REQUEST_TIMEOUT_SEC = 30.0

    def __init__(self, cwd: Path, extra_env: dict[str, str] | None = None):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "polymarket_mcp.server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_build_env(extra_env),
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
        )
        self._next_id = 0
        self._responses: queue.Queue = queue.Queue()
        self._unsolicited: list[dict] = []
        self._stderr_lines: list[str] = []
        self._closed = False
        self._stdout_thread = threading.Thread(target=self._pump_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._pump_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _pump_stdout(self) -> None:
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                message = {"__non_json__": line}
            self._responses.put(message)
        self._responses.put(None)  # EOF sentinel

    def _pump_stderr(self) -> None:
        for line in self.proc.stderr:
            self._stderr_lines.append(line)

    def _write_line(self, text: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()

    def send_notification(self, method: str) -> None:
        self._write_line(json.dumps({"jsonrpc": "2.0", "method": method}))

    def request(self, method: str, params: dict | None = None) -> dict:
        """Send one JSON-RPC request and return its full envelope.

        Times out loudly (killing the server) instead of hanging; responses
        with a different id are parked in _unsolicited.
        """
        deadline = time.monotonic() + self.REQUEST_TIMEOUT_SEC
        self._next_id += 1
        request_id = self._next_id
        payload: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._write_line(json.dumps(payload))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.terminate()
                pytest.fail(
                    f"timed out after {self.REQUEST_TIMEOUT_SEC}s waiting for "
                    f"response id={request_id} to {method!r} (subprocess killed on hang)"
                )
            try:
                message = self._responses.get(timeout=remaining)
            except queue.Empty:
                continue  # deadline check above raises fail
            if message is None:
                self.terminate()
                pytest.fail(
                    f"server stdout closed before responding to id={request_id} "
                    f"{method!r} (subprocess killed)"
                )
            if message.get("id") != request_id:
                self._unsolicited.append(message)
                continue
            return message

    def stderr_text(self) -> str:
        return "\n".join(self._stderr_lines)

    def terminate(self, timeout: float = 15.0) -> None:
        """Idempotent teardown: graceful EOF, then kill if it hangs."""
        if self._closed:
            return
        self._closed = True
        try:
            if self.proc.stdin is not None and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)


@pytest.fixture
def session(tmp_path):
    """Function-scoped pristine session: one fresh server subprocess per
    test, cwd=tmp_path (host .env never leaks), killed on hang."""
    session = StdioSession(cwd=tmp_path)
    try:
        yield session
    finally:
        session.terminate()


# =====================================================================
# R1-E2E: server/discover with NO session, FIRST message of the process
# =====================================================================


def test_discover_served_pre_handshake_first_message(session):
    """R1-E2E: server/discover answered with NO session/handshake.

    The process's first inbound message is server/discover (no initialize
    ever precedes it); the response must be a result (never -32602, never a
    timeout) carrying a DiscoverResult with every field the published
    2026-07-28 schema requires (the exact literal set the in-process suite
    pins) and the server identity derived by reflection (never a literal).
    """
    response = session.request("server/discover", {})
    assert "error" not in response, (
        f"server/discover must be served pre-handshake, got an error: {response}"
    )
    result = response["result"]
    assert isinstance(result, dict)
    assert DISCOVER_RESULT_REQUIRED_FIELDS.issubset(result), (
        f"DiscoverResult is missing schema-required fields: "
        f"{sorted(DISCOVER_RESULT_REQUIRED_FIELDS - set(result))}"
    )
    assert result["resultType"] == "complete", (
        f"DiscoverResult envelope must be a complete result, got {result['resultType']!r}"
    )
    server_info = result["_meta"]["io.modelcontextprotocol/serverInfo"]
    assert server_info["name"] == SERVER_NAME
    assert server_info["version"] == polymarket_mcp.__version__


# =====================================================================
# R7-E2E: version-less initialize served on the declared default
# =====================================================================


def test_versionless_initialize_served_on_default(session):
    """R7-E2E: a version-less request is served on the default (never timeout).

    Identical signature to the in-process R7
    (tests/test_mcp_conformance_offline.py:302-322): the params omit _meta
    entirely, the response settles on the literal "2026-07-28" - the literal
    pin is deliberate (mutation M3 proved asserting against the module
    constant is circular with the implementation).
    """
    response = session.request(
        "initialize",
        {
            "capabilities": {},
            "clientInfo": {"name": "conformance-probe", "version": "0"},
        },
    )
    assert "error" not in response, (
        f"a version-less initialize must be served, got an error: {response}"
    )
    settled = response["result"]["protocolVersion"]
    assert settled == DEFAULT_DECLARED_REVISION, (
        f"version-less request must be served on the declared default "
        f"'{DEFAULT_DECLARED_REVISION}', got {settled!r}"
    )


# =====================================================================
# R8-E2E: unsupported per-request version refused with the supported list
# =====================================================================


def test_unsupported_per_request_version_refused_with_list(session):
    """R8-E2E: an unsupported version is refused with -32022 + the list.

    Mirrors the spec-test's "an unsupported version is rejected with the
    supported list" case over the real wire: the refusal must carry code
    -32022 with the supported revisions list, which must equal the literal
    two-revision window (the in-process suite cross-checks the same equality
    against what server/discover advertises) and must never offer the
    unsupported version back.
    """
    response = session.request(
        "initialize",
        {
            "_meta": _suite_meta(UNSERVABLE_VERSION),
            "capabilities": {},
            "clientInfo": {"name": "conformance-probe", "version": "0"},
        },
    )
    assert "error" in response, (
        f"an unsupported version must be refused, got a result: {response}"
    )
    error = response["error"]
    assert error["code"] == UNSUPPORTED_VERSION_CODE, (
        f"expected UnsupportedProtocolVersion ({UNSUPPORTED_VERSION_CODE}), "
        f"got {error['code']}"
    )
    data = error.get("data")
    supported = data.get("supported") if isinstance(data, dict) else None
    assert isinstance(supported, list) and supported, (
        f"error data must list supported versions, got {data!r}"
    )
    assert sorted(supported) == sorted(SUITE_SUPPORTED_REVISIONS), (
        f"the versions offered in the error must match the declared window "
        f"{sorted(SUITE_SUPPORTED_REVISIONS)}, got {supported!r}"
    )
    assert UNSERVABLE_VERSION not in supported, (
        "the unsupported version must never be offered back"
    )


# =====================================================================
# R8b-E2E: supported non-default version passes through negotiation
# =====================================================================


def test_supported_non_default_version_passes_through(session):
    """R8b-E2E: a declared, SERVABLE version is accepted (a result).

    The params._meta declares the oldest revision the server serves
    ("2025-11-25"): the negotiation must pass through - a result, never the
    -32022 refusal. The negotiated version is pinned semantically (one the
    server actually serves) rather than literally: the per-request _meta
    version and the params-level handshake version are different carriers,
    and the SDK settles the params-level one.
    """
    response = session.request(
        "initialize",
        {
            "_meta": _suite_meta(OLDEST_DECLARED_REVISION),
            "capabilities": {},
            "clientInfo": {"name": "conformance-probe", "version": "0"},
        },
    )
    assert "error" not in response, (
        f"a declared, servable version must be served, got a refusal: {response}"
    )
    settled = response["result"]["protocolVersion"]
    assert settled in SUITE_SUPPORTED_REVISIONS, (
        f"the negotiated version must be one the server actually serves, "
        f"got {settled!r}"
    )
    assert response["result"]["serverInfo"]["name"] == SERVER_NAME


# =====================================================================
# R9-E2E: the official-SDK-style handshake still works + tools/list
# =====================================================================


def test_wellformed_handshake_and_tools_list(session):
    """R9-E2E: the well-formed handshake still works (official-SDK regression).

    The SDK-era handshake (protocolVersion carried in params - T-0288
    observable) echoes the offered version, reports the pinned server name
    and the reflected package version, advertises tools + resources, and a
    tools/list after notifications/initialized returns tools with unique
    names (in-process R9 pin).
    """
    response = session.request(
        "initialize",
        {
            "protocolVersion": SDK_OFFICIAL_HANDSHAKE_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "official-sdk-client", "version": "1.0.0"},
        },
    )
    assert "error" not in response, (
        f"the well-formed handshake must be served, got an error: {response}"
    )
    result = response["result"]
    assert result["protocolVersion"] == SDK_OFFICIAL_HANDSHAKE_VERSION, (
        "the offered version must be echoed"
    )
    server_info = result["serverInfo"]
    assert server_info["name"] == SERVER_NAME
    assert server_info["version"] == polymarket_mcp.__version__
    capabilities = result["capabilities"]
    assert "tools" in capabilities
    assert "resources" in capabilities

    session.send_notification("notifications/initialized")
    tools_response = session.request("tools/list", {})
    assert "error" not in tools_response, (
        f"tools/list must be served after the handshake, got an error: {tools_response}"
    )
    tools = tools_response["result"]["tools"]
    assert isinstance(tools, list) and tools, "tools/list must return tools after handshake"
    names = [tool["name"] for tool in tools]
    assert len(names) == len(set(names)), "tool names must be unique"
