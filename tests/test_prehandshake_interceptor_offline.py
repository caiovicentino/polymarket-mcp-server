"""Offline suite for the pre-handshake interceptor's EDGE branches (T-0236).

Closes the 7 missing statements + 3 partial branches of ``_PreHandshakeStream``
that NO suite exercised before this file (RED pré provado por coverage no main
89edfa9: server.py missing [218, 263, 264, 266, 281, 284, 285] + branches
[[217, 218], [262, 263], [265, 266]]). The T-0046 conformance suite covers the
happy flow only — these are the edge branches:

- A transport Exception received on the read stream passes through BY IDENTITY
  (:217-218): ``__anext__`` returns the SAME exception object and ``_intercept``
  NEVER transforms it — the session's error handling depends on receiving it
  (R9 pass-through byte-identical).
- A version-less ``initialize`` (``params is None``) is served on the declared
  default revision (:261-264): the params dict is injected in place with
  ``protocolVersion = DEFAULT_PROTOCOL_REVISION`` (issue #39 R7 / #40).
- Non-dict params pass through UNTOUCHED (:265-266) — defense-in-depth: the SDK
  session answers malformed params with a JSON-RPC error response, never a
  dropped message (issue #39 R7 / issue #40: "must be served").
- The ``_respond_discover`` error path (:281-285): when the cached discover
  result raises, the interceptor answers with a JSON-RPC error
  (``-32603 INTERNAL_ERROR``) carrying the SAME request id — the R1 claim
  "the interceptor must never leave a client waiting" becomes an observable
  pin (a STRING id also proves the non-int id echo).

Pins are behavioral (symbol names, never line numbers — L-0023). Anti-fix: no
xfail anywhere; no loosening of the T-0046 conformance suite.

Hermeticity: every stream is an ``anyio.MemoryObjectStream`` (zero network);
``cached_discover_result`` is patched BEFORE any real call (pytest
auto-restores, order-independent); the ``__new__`` unit-mode constructor is
instance-local (zero global state — the REAL ``__init__`` calls
``ensure_sdk_supports_declared_revisions()``, so only the exception test uses
the real constructor, mirroring the conformance suite's own pipeline usage).
No integration/slow/real_api/performance markers (runs in the release gate);
sync tests with inner ``anyio.run`` (casa pattern, ``asyncio_mode = "auto"``).
"""
from __future__ import annotations

import anyio
import mcp.types as types
from mcp.shared.message import SessionMessage

from polymarket_mcp import server as server_module


def _new_interceptor(write_stream):
    """Unit-mode constructor: ``__new__`` + ``_write_stream`` set directly.

    The real ``__init__`` mutates the SDK's public SUPPORTED_PROTOCOL_VERSIONS
    list via ``ensure_sdk_supports_declared_revisions()``; the tests below call
    private methods directly and never touch other attributes, so the bypass is
    instance-local (zero global state).
    """
    interceptor = server_module._PreHandshakeStream.__new__(
        server_module._PreHandshakeStream
    )
    interceptor._write_stream = write_stream
    return interceptor


def test_exception_passes_through_by_identity() -> None:
    """A transport exception crosses ``__anext__`` BY IDENTITY (:217-218).

    The interceptor never consumes or transforms exceptions: the session's own
    error handling depends on receiving the original exception object.
    """

    async def run() -> None:
        # anyio.create_memory_object_stream() returns (send, receive) ends.
        client_send, client_recv = anyio.create_memory_object_stream(16)
        interceptor = server_module._PreHandshakeStream(client_recv, client_send)
        await client_send.send(RuntimeError("boom-transport"))
        exc = await interceptor.__anext__()
        assert isinstance(exc, RuntimeError), type(exc)
        assert str(exc) == "boom-transport", str(exc)
        # _intercept NEVER transforms the exception (pass-through by identity).
        boom2 = RuntimeError("boom-2")
        assert await interceptor._intercept(boom2) is None

    anyio.run(run)


def test_params_none_gets_default_version() -> None:
    """Version-less initialize (params None) is served on the default revision."""

    async def run() -> None:
        send, _recv = anyio.create_memory_object_stream(16)
        interceptor = _new_interceptor(send)
        request = types.JSONRPCRequest.model_validate(
            {"jsonrpc": "2.0", "id": 7, "method": "initialize"}
        )
        assert request.params is None
        interceptor._default_initialize_version(request)
        assert isinstance(request.params, dict)
        assert (
            request.params.get("protocolVersion")
            == server_module.DEFAULT_PROTOCOL_REVISION
        )

    anyio.run(run)


def test_non_dict_params_pass_through_untouched() -> None:
    """Non-dict params leave ``_default_initialize_version`` UNTOUCHED (:265-266).

    Defense-in-depth branch: pydantic REJECTS a list in params on the wire
    ("Input should be a valid dictionary"), so the branch is only reachable by
    DIRECT attribute assignment — the SDK session answers malformed params with
    a JSON-RPC error response, never a dropped message.
    """

    async def run() -> None:
        send, _recv = anyio.create_memory_object_stream(16)
        interceptor = _new_interceptor(send)
        request = types.JSONRPCRequest.model_validate(
            {"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": {}}
        )
        request.params = [1]
        interceptor._default_initialize_version(request)
        assert request.params == [1]
        assert not isinstance(request.params, dict)

    anyio.run(run)


def test_respond_discover_error_path_answers_jsonrpc_error(monkeypatch) -> None:
    """Discover cache failure answers a -32603 JSONRPCError with the SAME id (:281-285).

    R1 pin observável: "the interceptor must never leave a client waiting" —
    the error carries the original request id (a STRING proves the non-int id
    echo). monkeypatch auto-restores (equivalente ao finally do design original;
    patched BEFORE any real call — order-independent).
    """

    def boom(_payload_builder):
        raise RuntimeError("boom-cache")

    async def run() -> None:
        send, server_to_client_recv = anyio.create_memory_object_stream(16)
        interceptor = _new_interceptor(send)
        await interceptor._respond_discover("probe-discover-err")
        message = await server_to_client_recv.receive()
        assert isinstance(message, SessionMessage)
        root = message.message.root
        assert isinstance(root, types.JSONRPCError), root
        assert root.id == "probe-discover-err", root.id
        assert root.error.code == server_module.DISCOVER_INTERNAL_ERROR_CODE
        assert root.error.message.startswith("server/discover failed: "), (
            root.error.message
        )

    monkeypatch.setattr(server_module, "cached_discover_result", boom)
    anyio.run(run)
