"""Offline MCP conformance suite for the protocol layer (issues #39 + #40).

Pins the 9 requirements (R1-R9) of the conformance reports 1:1:
- R1  server/discover is answered without a session or handshake (within the
      suite's 10s budget; no -32602, no timeout), carrying every field the
      2026-07-28 schema requires on DiscoverResult       [issue #39]
- R2  server/discover advertises the versions the server can serve: the two
      declared revisions, and the version negotiated for a version-less
      client must itself appear in the list               [issue #39]
- R3  server/discover is a CacheableResult with usable cache hints
      (resultType, ttlMs >= 0, cacheScope public/private) [issue #39]
- R4  server/discover reports server identity (serverInfo name/version) and
      capabilities (mirror of what initialize declares)   [issue #39]
- R5  server/discover is stable across calls within its own TTL
      (two calls -> identical result)                     [issue #39]
- R6  server/discover advertises a revision the suite supports
      (overlap with the two-revision window)              [issue #39]
- R7  a request with no version at all is served on the default (a response,
      never a timeout)                       [issue #39 + #40, both revisions]
- R8  an unsupported version offered at the handshake is refused or
      downgraded, not echoed (and never a timeout); in the 2026-07-28
      per-request model the same refusal carries -32022 and the supported
      list ("an unsupported version is rejected with the supported list")
                                         [issue #39 + #40]
- R9  the well-formed handshake still works (official-SDK interop regression
      guard: initialize settles on a declared revision + tools/list after)  [R9]

The two R8-family cases mirror the exact wire shapes @hasmcp/mcp-spec-test
sends (lib/rpc.mjs buildRequest/requestMeta): the per-request version rides in
``params._meta["io.modelcontextprotocol/protocolVersion"]`` together with
``io.modelcontextprotocol/clientCapabilities`` and
``io.modelcontextprotocol/clientInfo``, and a version-less request omits
``_meta`` entirely.

Seam (proven against mcp 1.30.0; see polymarket_mcp.discover docstring): the
in-process pipeline below wires Server.run through the same
_PreHandshakeStream interceptor main() installs on stdio, over anyio
MemoryObjectStreams. initialize_server/_start_websocket are NEVER invoked, so
no Polymarket/WSS traffic is possible (hermeticity: the env -i acceptance in
the task contract is the executable proof; P-0029).

Anatomy: zero sleeps (L-0014), zero network, zero integration/slow/real_api
markers, fakes fail-loud (unexpected input raises AssertionError, P-0031),
semantic assertions (L-0002), no monkeypatch of SDK internals - the only
global touched is the SDK's public SUPPORTED_PROTOCOL_VERSIONS list via
discover.ensure_sdk_supports_declared_revisions (idempotent).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
from typing import Any, Iterator

import anyio
import mcp.types as types
from mcp.server.lowlevel.server import NotificationOptions
from mcp.shared.message import SessionMessage

import polymarket_mcp
import polymarket_mcp.discover as discover
from polymarket_mcp import server as server_module

# The two-revision window the conformance suite supports (mcp-spec-test README:
# "It supports the two most recent spec revisions only").
SUITE_SUPPORTED_REVISIONS = {"2026-07-28", "2025-11-25"}
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# DiscoverResult required list, pinned from the published 2026-07-28 schema
# (spec/2026-07-28/schema.json $defs.DiscoverResult.required). Literal, not
# imported from the implementation, so a field the implementation drops
# (rather than forgets to declare) still fails this check.
DISCOVER_RESULT_REQUIRED_FIELDS = frozenset(
    {"cacheScope", "capabilities", "resultType", "supportedVersions", "ttlMs"}
)


def _suite_meta(version: str) -> dict[str, Any]:
    """The per-request _meta the conformance suite sends (rpc.mjs requestMeta).

    Mirrors buildRequest: protocolVersion + clientCapabilities (both
    schema-required) plus clientInfo (a SHOULD, included by the suite by
    default).
    """
    return {
        "io.modelcontextprotocol/protocolVersion": version,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {
            "name": "mcp-spec-test",
            "version": "0.1.1",
        },
    }


class _FailLoudJsonRpcClient:
    """Raw JSON-RPC client over in-process memory streams.

    Mirrors the stdio wire format: payloads are validated through
    types.JSONRPCMessage.model_validate_json exactly like the stdio transport
    (mcp/server/stdio.py:62-66) does on each line, without any socket.
    Unexpected input fails loud (AssertionError), never silently ignored.
    """

    def __init__(self) -> None:
        self._next_id = 0
        # anyio.create_memory_object_stream() returns (send, receive) ends.
        self.to_server_send, self.to_server_recv = anyio.create_memory_object_stream(16)
        self.server_to_client_send, self.server_to_client_recv = (
            anyio.create_memory_object_stream(16)
        )

    async def send_request(self, method: str, params: dict[str, Any] | None) -> int:
        assert isinstance(method, str), f"method must be str, got {type(method)}"
        assert params is None or isinstance(params, dict), (
            f"params must be dict|None, got {type(params)}"
        )
        self._next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        message = types.JSONRPCMessage.model_validate_json(json.dumps(payload))
        await self.to_server_send.send(SessionMessage(message=message))
        return self._next_id

    async def send_notification(self, method: str) -> None:
        message = types.JSONRPCMessage.model_validate_json(
            json.dumps({"jsonrpc": "2.0", "method": method})
        )
        await self.to_server_send.send(SessionMessage(message=message))

    async def receive_result(self, request_id: int, timeout_seconds: float) -> dict[str, Any]:
        """Await the response for one request; fail loud on anything else."""
        assert isinstance(request_id, int), f"request_id must be int, got {type(request_id)}"
        try:
            with anyio.fail_after(timeout_seconds):
                async for message in self.server_to_client_recv:
                    if isinstance(message, Exception):
                        raise AssertionError(f"transport exception: {message!r}")
                    root = message.message.root
                    if isinstance(root, types.JSONRPCResponse) and root.id == request_id:
                        assert isinstance(root.result, dict), (
                            f"result must be dict, got {type(root.result)}"
                        )
                        return root.result
                    if isinstance(root, types.JSONRPCError):
                        raise AssertionError(
                            f"unexpected JSON-RPC error for {request_id}: {root.error}"
                        )
                    # Our flows emit no notifications: any non-response shape
                    # here is unexpected protocol traffic -> fail loud.
                    raise AssertionError(f"unexpected message shape: {type(root).__name__}")
        except TimeoutError as exc:
            raise AssertionError(
                f"no response for request {request_id} within {timeout_seconds}s (timeout)"
            ) from exc
        raise AssertionError(f"stream closed before result for request {request_id}")

    async def receive_error(self, request_id: int, timeout_seconds: float) -> types.ErrorData:
        """Await an error response for one request; fail loud on anything else."""
        try:
            with anyio.fail_after(timeout_seconds):
                async for message in self.server_to_client_recv:
                    if isinstance(message, Exception):
                        raise AssertionError(f"transport exception: {message!r}")
                    root = message.message.root
                    if isinstance(root, types.JSONRPCError) and root.id == request_id:
                        return root.error
                    if isinstance(root, types.JSONRPCResponse):
                        raise AssertionError(
                            f"expected a refusal for {request_id}, got a result: {root.result}"
                        )
                    raise AssertionError(f"unexpected message shape: {type(root).__name__}")
        except TimeoutError as exc:
            raise AssertionError(
                f"no error response for request {request_id} within {timeout_seconds}s (timeout)"
            ) from exc
        raise AssertionError(f"stream closed before error for request {request_id}")


@contextlib.asynccontextmanager
async def _mcp_pipeline() -> Iterator[_FailLoudJsonRpcClient]:
    """Server.run over in-process memory streams through the real interceptor.

    The task is cancelled in cleanup; stream closes are best-effort because
    the session itself closes them on exit (mcp/shared/session.py:351-356).
    """
    client = _FailLoudJsonRpcClient()
    intercepted_read = server_module._PreHandshakeStream(
        client.to_server_recv, client.server_to_client_send
    )
    task = asyncio.create_task(
        server_module.server.run(
            intercepted_read,
            client.server_to_client_send,
            server_module.server.create_initialization_options(),
        )
    )
    try:
        yield client
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with contextlib.suppress(Exception):
            await client.to_server_send.aclose()
        with contextlib.suppress(Exception):
            await client.server_to_client_send.aclose()


async def test_discover_responds_pre_handshake() -> None:
    """R1: discover answered with NO session/handshake, within the 10s budget."""
    async with _mcp_pipeline() as client:
        request_id = await client.send_request(server_module.DISCOVER_METHOD, {})
        result = await client.receive_result(request_id, timeout_seconds=10.0)
        assert isinstance(result, dict)
        # The suite's R1 also checks every schema-required DiscoverResult field
        # is present (missingRequired('DiscoverResult', out) == []) - the exact
        # set from the published 2026-07-28 schema, pinned above as a literal.
        assert DISCOVER_RESULT_REQUIRED_FIELDS.issubset(result), (
            f"DiscoverResult is missing schema-required fields: "
            f"{sorted(DISCOVER_RESULT_REQUIRED_FIELDS - set(result))}"
        )
        # No -32602: an error response would have failed loud above.


async def test_discover_advertises_supported_revisions() -> None:
    """R2: the versions the server can serve, plus the version-less default."""
    async with _mcp_pipeline() as client:
        request_id = await client.send_request(server_module.DISCOVER_METHOD, {})
        result = await client.receive_result(request_id, timeout_seconds=10.0)
        supported = result["supportedVersions"]
        assert isinstance(supported, list) and supported, "supportedVersions must be non-empty"
        for revision in supported:
            assert isinstance(revision, str) and ISO_DATE_PATTERN.match(revision), (
                f"revision must be an ISO date, got {revision!r}"
            )
        assert "2026-07-28" in supported, "declared revision 2026-07-28 must be advertised"
        assert "2025-11-25" in supported, "declared revision 2025-11-25 must be advertised"
        # The version negotiated for a client that declares none (the suite's
        # defaultVersion = newest(supportedVersions) on stdio) must itself be
        # advertised - satisfied here because the declared default is the
        # newest entry; the R7 test pins the negotiated value itself.


async def test_discover_result_envelope_is_cacheable() -> None:
    """R3: CacheableResult envelope with usable cache hints."""
    async with _mcp_pipeline() as client:
        request_id = await client.send_request(server_module.DISCOVER_METHOD, {})
        result = await client.receive_result(request_id, timeout_seconds=10.0)
        assert result["resultType"] == "complete"
        ttl_ms = result["ttlMs"]
        assert isinstance(ttl_ms, int) and ttl_ms >= 0, f"ttlMs must be >= 0, got {ttl_ms!r}"
        # Literal pin (not the module constant): the hint must be a usable,
        # non-zero TTL; a drift in the implementation's constant fails loud
        # (proven by mutation M6: the cache removed, R5 - not this pin - broke).
        assert ttl_ms == 60_000
        assert result["cacheScope"] in ("public", "private")
        assert result["cacheScope"] == "public"  # discover carries no user data


async def test_discover_reports_identity_and_capabilities() -> None:
    """R4: server identity (serverInfo) + capabilities mirror of initialize."""
    async with _mcp_pipeline() as client:
        request_id = await client.send_request(server_module.DISCOVER_METHOD, {})
        result = await client.receive_result(request_id, timeout_seconds=10.0)
        meta = result["_meta"]
        assert isinstance(meta, dict)
        # Literal key pin (the suite reads exactly this reserved _meta key).
        server_info = meta["io.modelcontextprotocol/serverInfo"]
        assert server_info["name"] == "polymarket-trading"
        assert server_info["version"] == polymarket_mcp.__version__
        capabilities = result["capabilities"]
        assert isinstance(capabilities, dict) and capabilities
        # Mirror of what initialize declares (same Server.get_capabilities call).
        assert "tools" in capabilities
        assert "resources" in capabilities


async def test_discover_stable_within_ttl() -> None:
    """R5: two calls within the TTL return identical results."""
    async with _mcp_pipeline() as client:
        first_id = await client.send_request(server_module.DISCOVER_METHOD, {})
        first = await client.receive_result(first_id, timeout_seconds=10.0)
        second_id = await client.send_request(server_module.DISCOVER_METHOD, {})
        second = await client.receive_result(second_id, timeout_seconds=10.0)
        assert first == second, "discover must be stable within its own TTL"
        assert discover.DISCOVER_CACHE_TTL_MS > 0


async def test_discover_advertises_suite_supported_revision() -> None:
    """R6: the advertised list overlaps the suite's two-revision window."""
    async with _mcp_pipeline() as client:
        request_id = await client.send_request(server_module.DISCOVER_METHOD, {})
        result = await client.receive_result(request_id, timeout_seconds=10.0)
        advertised = set(result["supportedVersions"])
        assert advertised & SUITE_SUPPORTED_REVISIONS, (
            f"advertised revisions {advertised} must overlap {SUITE_SUPPORTED_REVISIONS}"
        )


async def test_versionless_request_served_on_default() -> None:
    """R7: a version-less request is served on the default (never timeout)."""
    async with _mcp_pipeline() as client:
        request_id = await client.send_request(
            "initialize",
            {
                "capabilities": {},
                "clientInfo": {"name": "conformance-probe", "version": "0"},
            },
        )
        result = await client.receive_result(request_id, timeout_seconds=10.0)
        settled = result["protocolVersion"]
        # Literal pin of the contract-prescribed default (issue #39 R7: "a
        # mais alta suportada: 2026-07-28"); asserting against the module
        # constant would be circular with the implementation (proven by
        # mutation M3: the constant flipped and the suite stayed green).
        assert settled == "2026-07-28", (
            f"version-less request must be served on the declared default "
            f"'2026-07-28', got {settled!r}"
        )
        assert settled in discover.SUPPORTED_PROTOCOL_REVISIONS


async def test_unsupported_version_refused_or_downgraded() -> None:
    """R8: unsupported version is refused or downgraded, never echoed/timeout.

    Downgrade is the documented choice (SDK semantics, mcp/server/session.py:
    186-187): the response settles on a real declared revision; the offered
    version is never echoed back.
    """
    async with _mcp_pipeline() as client:
        request_id = await client.send_request(
            "initialize",
            {
                "protocolVersion": "1999-01-01",
                "capabilities": {},
                "clientInfo": {"name": "conformance-probe", "version": "0"},
            },
        )
        result = await client.receive_result(request_id, timeout_seconds=10.0)
        settled = result["protocolVersion"]
        assert settled in discover.SUPPORTED_PROTOCOL_REVISIONS, (
            f"downgrade must settle on a declared revision, got {settled!r}"
        )
        assert settled != "1999-01-01", "the unsupported version must never be echoed"


async def test_wellformed_handshake_still_works() -> None:
    """R9: regression guard - the official-SDK-style handshake still works."""
    async with _mcp_pipeline() as client:
        request_id = await client.send_request(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "official-sdk-client", "version": "1.0.0"},
            },
        )
        result = await client.receive_result(request_id, timeout_seconds=10.0)
        assert result["protocolVersion"] == "2025-11-25", "the offered version must be echoed"
        server_info = result["serverInfo"]
        assert server_info["name"] == "polymarket-trading"
        assert server_info["version"] == polymarket_mcp.__version__
        # Capabilities must mirror what the SDK itself computes for the
        # handshake options - asserted through the SDK's own call (not the
        # module's helper, which this response is built from) so a drift in
        # the discover mirror is caught against the SDK source of truth.
        expected_capabilities = server_module.server.get_capabilities(
            NotificationOptions(), {}
        ).model_dump(exclude_none=True, by_alias=True)
        assert result["capabilities"] == expected_capabilities, (
            "initialize capabilities must equal the discover capabilities mirror"
        )
        await client.send_notification("notifications/initialized")
        tools_request_id = await client.send_request("tools/list", {})
        tools_result = await client.receive_result(tools_request_id, timeout_seconds=10.0)
        tools = tools_result.get("tools")
        assert isinstance(tools, list) and tools, "tools/list must return tools after handshake"
        names = [tool["name"] for tool in tools]
        assert len(names) == len(set(names)), "tool names must be unique"


async def test_per_request_version_declared_in_meta_is_accepted() -> None:
    """2026-07-28 per-request model: a declared, servable version is accepted.

    Mirrors the suite's "a version declared in _meta is accepted" case: the
    request declares the revision under test in _meta and must be served (a
    result, not a refusal).
    """
    async with _mcp_pipeline() as client:
        request_id = await client.send_request(
            "tools/list",
            {"_meta": _suite_meta("2026-07-28")},
        )
        result = await client.receive_result(request_id, timeout_seconds=10.0)
        tools = result.get("tools")
        assert isinstance(tools, list) and tools, "a _meta-declared request must be served"


async def test_unsupported_per_request_version_rejected_with_supported_list() -> None:
    """2026-07-28 per-request model: an unsupported version is refused (-32022).

    Mirrors the suite's "an unsupported version is rejected with the supported
    list" case: the refusal must be an UnsupportedProtocolVersionError carrying
    the supported list, which must match what server/discover advertises (a
    client that retries from the error and one that reads discover must agree).
    """
    async with _mcp_pipeline() as client:
        request_id = await client.send_request(
            "tools/list",
            {"_meta": _suite_meta("1999-01-01")},
        )
        error = await client.receive_error(request_id, timeout_seconds=10.0)
        assert error.code == -32022, (
            f"expected UnsupportedProtocolVersion (-32022), got {error.code}"
        )
        supported = error.data.get("supported") if isinstance(error.data, dict) else None
        assert isinstance(supported, list) and supported, (
            f"error data must list supported versions, got {error.data!r}"
        )
        assert sorted(supported) == sorted(SUITE_SUPPORTED_REVISIONS), (
            f"the versions offered in the error must match what server/discover "
            f"advertises, got {supported!r}"
        )
        assert "1999-01-01" not in supported, "the unsupported version must never be offered"
