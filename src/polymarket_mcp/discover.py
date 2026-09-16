"""Pre-handshake MCP protocol layer: ``server/discover`` (spec 2026-07-28).

Closes the MCP conformance findings of issues #39 (spec 2026-07-28) and #40
(spec 2025-11-25): the server now answers ``server/discover`` without any
session or handshake and tolerates atypical version-negotiation inputs.

Envelope (pinned 1:1 to the published 2026-07-28 schema, ``DiscoverResult``):
required fields are ``cacheScope``, ``capabilities``, ``resultType``,
``supportedVersions`` and ``ttlMs``; server identity rides in
``_meta["io.modelcontextprotocol/serverInfo"]`` (``Implementation``: name +
version), which is where a client learns what it is talking to now that the
handshake is replaced by discover in that revision.

SDK seams (mcp 1.30.0 in this venv; proven in tests/test_mcp_conformance_offline.py):
- ``mcp/shared/session.py:362`` validates every incoming ``JSONRPCRequest``
  against the fixed ``ClientRequest`` union (``mcp/types.py:1814``); a method
  outside the union (e.g. ``server/discover``) fails validation and is answered
  with ``-32602 Invalid request parameters`` by the session itself
  (``mcp/shared/session.py:380-397``) - the exact error the conformance report
  observed on five of the six discover checks.
- ``mcp/server/session.py:203-205`` raises ``RuntimeError`` for any request
  other than initialize/ping before the handshake; on SDK versions without the
  ``except Exception`` wrap of ``mcp/shared/session.py:380`` this propagates
  and the receive loop dies, leaving the request unanswered (the timeouts in
  the reports). The tolerant pre-parse interceptor installed in
  ``polymarket_mcp.server`` (read-stream wrapper before ``Server.run``) makes
  the path version-independent: pre-handshake requests are answered at the
  transport boundary on every SDK version.
- ``mcp/server/lowlevel/server.py:735`` dispatches by request TYPE only, and
  ``Server.run`` constructs the ``ServerSession`` itself
  (``mcp/server/lowlevel/server.py:664-671``), so neither a custom request
  type registered in ``request_handlers`` nor a subclassed session can be
  injected through the public API - which is why the interceptor lives at the
  stream boundary instead.
- ``mcp/server/session.py:186-187`` already refuses-or-downgrades unsupported
  handshake versions (echo only when the version is in
  ``SUPPORTED_PROTOCOL_VERSIONS``, else downgrades to
  ``LATEST_PROTOCOL_VERSION``, which on mcp 1.30.0 is ``2025-11-25`` - one of
  the revisions this server serves); ``ensure_sdk_supports_declared_revisions``
  extends that public list with the revisions this server serves so the
  version-less path is served exactly on this server's declared default.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Final

# Protocol revisions this server can serve (declared constants; the
# conformance reports pin "Revisions supported | 2026-07-28, 2025-11-25").
SUPPORTED_PROTOCOL_REVISIONS: Final[tuple[str, ...]] = ("2026-07-28", "2025-11-25")

# Version served to a client that declares none: the highest revision this
# server serves (issue #39 R7: "served on the default").
DEFAULT_PROTOCOL_REVISION: Final[str] = "2026-07-28"

# Cache hint for the discover result (issue #39 R3/R5: CacheableResult with
# usable hints, stable across calls within its own TTL).
DISCOVER_CACHE_TTL_MS: Final[int] = 60_000

# Reserved _meta key that carries server identity in the 2026-07-28 result
# envelope (mcp-spec-test: "results identify the server in _meta").
MCP_META_SERVER_INFO_KEY: Final[str] = "io.modelcontextprotocol/serverInfo"

# The 2026-07-28 revision declares the protocol version per request, in _meta
# (spec: RequestMetaObject requires clientCapabilities + protocolVersion). A
# request whose declared version is not servable is refused with this error
# code and the supported list, so the client can retry with a servable one
# (never echoing back a version the server cannot speak).
PER_REQUEST_VERSION_META_KEY: Final[str] = (
    "io.modelcontextprotocol/protocolVersion"
)
UNSUPPORTED_PROTOCOL_VERSION_CODE: Final[int] = -32022

# Envelope value: a discover result is a complete response (the value the
# suite's envelope check expects on cacheable results).
_RESULT_TYPE_COMPLETE: Final[str] = "complete"

_cache: dict[str, Any] | None = None
_cache_monotonic_at: float = -1.0


def build_discover_result(
    server_name: str,
    server_version: str,
    capabilities: dict[str, Any],
) -> dict[str, Any]:
    """Build the ``DiscoverResult`` payload (pure, deterministic given inputs).

    Args:
        server_name: Server identity name (e.g. ``Server.name``).
        server_version: Server identity version (the package ``__version__``).
        capabilities: Capabilities mirror of what ``initialize`` would declare
            (``Server.get_capabilities``), as a plain dict.

    Returns:
        The discover payload dict: cacheable envelope fields plus identity in
        ``_meta``.
    """
    return {
        "resultType": _RESULT_TYPE_COMPLETE,
        "capabilities": capabilities,
        "supportedVersions": list(SUPPORTED_PROTOCOL_REVISIONS),
        "ttlMs": DISCOVER_CACHE_TTL_MS,
        "cacheScope": "public",
        "_meta": {
            MCP_META_SERVER_INFO_KEY: {
                "name": server_name,
                "version": server_version,
            }
        },
    }


def cached_discover_result(builder: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Return the discover payload, rebuilding only past the TTL.

    Stability contract (issue #39 R5): identical within ``DISCOVER_CACHE_TTL_MS``;
    the cache is in-memory only - no network on the discover path.

    Args:
        builder: Zero-arg callable producing a fresh payload when the cache is
            empty or stale.

    Returns:
        The cached payload dict (same object while fresh).
    """
    global _cache, _cache_monotonic_at
    now = time.monotonic()
    if _cache is None or (now - _cache_monotonic_at) >= DISCOVER_CACHE_TTL_MS / 1000.0:
        _cache = builder()
        _cache_monotonic_at = now
    return _cache


def declared_request_version(params: Any) -> str | None:
    """The protocol version a request declares per-request in ``_meta``.

    2026-07-28 carries the version on every request in
    ``params._meta["io.modelcontextprotocol/protocolVersion"]``. Absent, null
    or empty means the client declares none - a version-less request, served
    on the default (issue #39 R7; spec's backward-compatibility clause).

    Args:
        params: The request's ``params`` (dict, list, or None).

    Returns:
        The declared version string, or None when the request declares none.
        Non-dict params are treated as version-less (the SDK session answers
        them with ``-32602`` - a response, never a timeout).
    """
    if not isinstance(params, dict):
        return None
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return None
    version = meta.get(PER_REQUEST_VERSION_META_KEY)
    if not isinstance(version, str) or not version:
        return None
    return version


def unsupported_version_error(version: str) -> dict[str, Any]:
    """The ``UnsupportedProtocolVersionError`` payload for a refused request.

    The error names what the server DOES support so the client can retry
    (2026-07-28 negotiation section; the conformance suite cross-checks this
    list against what ``server/discover`` advertises).

    Args:
        version: The offered (unsupported) version, for the message only.

    Returns:
        The error ``data`` payload: the supported revisions list.
    """
    return {"supported": list(SUPPORTED_PROTOCOL_REVISIONS), "offered": version}


def ensure_sdk_supports_declared_revisions() -> tuple[str, ...]:
    """Extend the SDK's public ``SUPPORTED_PROTOCOL_VERSIONS`` with this
    server's revisions, once.

    Without this, ``ServerSession._received_request``
    (``mcp/server/session.py:186-188``) would downgrade the injected default
    revision to the SDK's own ``LATEST_PROTOCOL_VERSION``; with it, a
    version-less handshake is served exactly on ``DEFAULT_PROTOCOL_REVISION``.
    Idempotent: existing entries are kept untouched, so stock SDK clients
    keep their exact negotiation semantics (official-SDK interop regression
    guard, issue #39 R9).

    Returns:
        The SDK's supported list after extension (for observability/tests).
    """
    from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS as sdk_versions

    for revision in SUPPORTED_PROTOCOL_REVISIONS:
        if revision not in sdk_versions:
            sdk_versions.append(revision)
    return tuple(sdk_versions)
