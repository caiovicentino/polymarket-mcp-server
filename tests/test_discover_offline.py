"""Offline unit suite for ``discover.declared_request_version`` (issue #39 R7).

The module-level conformance suite (tests/test_mcp_conformance_offline.py)
exercises ``declared_request_version`` only through wire-shaped dict params,
leaving the two defensive ``return None`` branches at module lines 152 and 158
uncovered (discover.py at 92.00% stmt/branch). These four tests close exactly
those two misses:

- line 152: non-dict ``params`` (list/None/str) is treated as version-less -
  the SDK session answers such requests with ``-32602``, a response, never a
  timeout (see the function's docstring at discover.py:148-149);
- line 158: a declared version that is not a non-empty string (``7`` covers
  ``not isinstance(version, str)``; ``""`` covers ``not version``) is treated
  as version-less, like a missing or non-dict ``_meta``.

Overlap is calibrated (no duplication with the conformance suite): these tests
pin ``declared_request_version`` in isolation and never touch
``get_cached_discover_payload``/``unsupported_version_error``.

The meta key is imported from the module (never hardcoded) so the suite cannot
drift from the production constant. Anatomy: zero network, zero sleeps, no
integration/slow/real_api/performance markers (offline by construction).
"""
from __future__ import annotations

from polymarket_mcp import discover

# Anti-drift: the payload key is the production constant itself (never the
# literal string), so a rename in discover.py fails this suite loudly.
PER_REQUEST_META = discover.PER_REQUEST_VERSION_META_KEY


def test_non_dict_params_returns_none() -> None:
    """Non-dict params (list / None / str) hit branch :152 -> None."""
    assert discover.declared_request_version([1, 2]) is None
    assert discover.declared_request_version(None) is None
    assert discover.declared_request_version("x") is None


def test_non_dict_meta_returns_none() -> None:
    """Non-dict _meta (str / list) hits branch :155; empty dict falls to :158."""
    assert discover.declared_request_version({"_meta": "x"}) is None
    assert discover.declared_request_version({"_meta": []}) is None
    # Empty dict: key absent -> meta.get(key) is None -> not isinstance(None, str)
    assert discover.declared_request_version({"_meta": {}}) is None


def test_invalid_version_returns_none() -> None:
    """Non-str / empty version hits branch :158 -> None (both disjuncts)."""
    # int: covers ``not isinstance(version, str)`` (first disjunct)
    assert discover.declared_request_version({"_meta": {PER_REQUEST_META: 7}}) is None
    # empty str: isinstance str, covers ``not version`` (second disjunct)
    assert discover.declared_request_version({"_meta": {PER_REQUEST_META: ""}}) is None
    # None: meta.get yields None when the key is absent from the dict
    assert discover.declared_request_version({"_meta": {PER_REQUEST_META: None}}) is None


def test_valid_version_returned() -> None:
    """A non-empty str version is returned verbatim (branch :159)."""
    params = {"_meta": {PER_REQUEST_META: "2026-07-28"}}
    assert discover.declared_request_version(params) == "2026-07-28"
