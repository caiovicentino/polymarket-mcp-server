"""Offline unit suite for the pure per-request version reader (discover.py).

Target: ``src/polymarket_mcp/discover.py::declared_request_version`` - the pure
defensive reader of the 2026-07-28 per-request ``_meta`` version. T-0046's
conformance layer exercises it only through the live pipeline (server.py:209),
so its two atypical-input guards never ran: coverage at main ``b9afddd`` is
92.00% with missing ``discover.py:152`` (non-dict ``params``) and
``discover.py:158`` (non-str or empty declared version) plus partial branches
``[151, 152]`` and ``[157, 158]``. This file calls the pure function DIRECTLY -
zero network, zero fakes, no fixtures (L-0118; the function is pure and
synchronous, no async needed).

Fork: ``farm/T-0122`` from clone main ``b9afddd`` (discover.py byte-identical
to the contract snapshot). The residual was re-derived by READING the live
blob, since the contract's second guard ref (":157/:158, ``_meta`` non-dict")
points at the VERSION guard: the ``_meta`` non-dict guard actually lives at
discover.py:154-155 and is already covered by the conformance layer's
version-less request (which omits ``_meta`` entirely). Divergence declared per
L-0152/L-0025; the goal (100.00% stmt + branch for the module) is unchanged and
proven by the full-suite acceptance with coverage.

Already covered elsewhere (dedupe): tests/test_mcp_conformance_offline.py
pins the protocol ENVELOPE (R1-R9: version-less request served on the default;
a declared version accepted; an unsupported one refused with -32022). This
file adds ONLY the pure reader's own unit semantics. The literal
``io.modelcontextprotocol/protocolVersion`` is pinned in the conformance suite
(sibling-file lock, L-0169); here the reserved key rides on the module
constant ``PER_REQUEST_VERSION_META_KEY`` (task contract rule 4).
"""

from polymarket_mcp.discover import (
    PER_REQUEST_VERSION_META_KEY,
    declared_request_version,
)


def test_declared_request_version_params_non_dict_returns_none() -> None:
    """Non-dict ``params`` is treated as version-less (discover.py:151-152).

    Closes residual :152 plus partial branch [151, 152] (the TRUE direction of
    ``if not isinstance(params, dict)``): the SDK session answers such a
    request with -32602 - a response, never a timeout - so the reader must
    return None for every non-dict shape.
    """
    assert declared_request_version(None) is None
    assert declared_request_version("2026-07-28") is None
    assert declared_request_version([1, 2]) is None


def test_declared_request_version_meta_non_dict_returns_none() -> None:
    """Non-dict ``_meta`` is treated as version-less (discover.py:154-155).

    Pins the guard's TRUE direction at unit level (missing, ``None``, ``str``
    and ``list`` payloads). The envelope path already reaches it via the
    conformance suite's version-less request (``_meta`` omitted entirely);
    this is the direct pin of the reader's own contract.
    """
    assert declared_request_version({}) is None
    assert declared_request_version({"_meta": None}) is None
    assert declared_request_version({"_meta": "2026-07-28"}) is None
    assert declared_request_version({"_meta": []}) is None


def test_declared_request_version_valid_version_roundtrip() -> None:
    """A declared, servable version roundtrips verbatim (discover.py:159).

    The envelope path (a ``_meta``-declared version is accepted, issue #40)
    already covers this line through server.py:209; the direct call pins the
    reader itself: whatever string the client declares under the reserved
    ``_meta`` key rides back verbatim (echo contract of the 2026-07-28
    per-request model).
    """
    params = {"_meta": {PER_REQUEST_VERSION_META_KEY: "2026-07-28"}}
    assert declared_request_version(params) == "2026-07-28"


def test_declared_request_version_empty_string_is_version_less() -> None:
    """An empty declared version means none (discover.py:157-158).

    Closes residual :158 plus partial branch [157, 158]: ``""`` satisfies
    ``not version`` (the rare, fragile arm of the guard) and must read as
    version-less - served on the default, never echoed back as an empty
    version.
    """
    params = {"_meta": {PER_REQUEST_VERSION_META_KEY: ""}}
    assert declared_request_version(params) is None
