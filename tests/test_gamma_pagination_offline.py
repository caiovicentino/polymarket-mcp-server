"""Offline suite for Gamma /markets pagination (V-GCAP) in market_discovery.

Provenance
----------
Defect V-GCAP (curator, proven live 2026-09-18 with probes c62-probe-gcap.py
and c62-probe-toollevel.py): the Gamma wire caps /markets pages at 100 rows
(limit=500 -> exactly 100 rows) and HONORS `offset` (offset=0 and offset=100
return disjoint ids). ``_fetch_gamma_markets`` made a single call, so a user
asking for limit>100 received a silent truncation to <=100 rows, and the 4
tools with a hardcoded limit=100 (trending/closing_soon/sports/crypto)
ignored a larger user limit.

Fix (provenance sim/c62-gcap @ 3ca11b1, curator-proven): paginate via
`offset` when limit>100 (max _GAMMA_MAX_PAGES pages), keep the fast path for
limit<=100 byte-identical to the pre-fix wire (exactly one call, no `offset`
key, same params/acquires -- the compat pins of
tests/test_market_discovery_offline.py :243/:362/:454-456/:653-655/:781-782/
:812-813 are inviolable), and pass a tool-level fetch_limit for
trending/closing_soon/sports/crypto. `offset` is sent ONLY when > 0 so the
first call is byte-identical to the pre-fix wire.

Red-before-green (P-0036)
-------------------------
Written FIRST and observed RED against the pristine module: the limit>100
tests (paginated fetch, last-page stop, no-progress guard, max-pages guard,
tool pass-through) failed with the single-call <=100-row truncation; the
byte-identity guards (fast path limit<=100, limit==100, limit=None) were
GREEN both before and after the fix.

Wire model (curator probe c62-probe-gcap.py)
--------------------------------------------
FakeGammaClient.get slices a synthetic universe exactly like the real wire:
lim = min(int(params.get("limit", 100)), 100) and off =
int(params.get("offset", 0)), returning universe[off : off + lim]. The
ignore_offset=True variant models a degenerate wire that always returns the
first page: the no-progress guard (first-id equality) must stop the loop in
at most 2 GETs, without hanging.

Hermeticity (P-0031/P-0012/L-0138/L-0014)
-----------------------------------------
Zero network: market_discovery.httpx is replaced BEFORE any execution -- by
the wire model in the fetch tests, by a fail-loud stub in the tool-level
tests; market_discovery.get_rate_limiter is replaced by a per-test recorder
(the real singleton is never acquired); public tools are exercised via
module-level stubs of _fetch_gamma_markets. No sleeps, no sockets.
ASCII-only (FA-0079). No markers: the file runs in the release gate.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx

from polymarket_mcp.tools import market_discovery
from polymarket_mcp.utils.rate_limiter import EndpointCategory


# ---------------------------------------------------------------------------
# Fail-loud fakes and wire model (P-0031/L-0138; wire modeled from the
# curator probe c62-probe-gcap.py)
# ---------------------------------------------------------------------------
class FakeRateLimiter:
    """Per-test recorder: acquire() categories are appended, never the real
    singleton (L-0123)."""

    def __init__(self):
        self.acquires = []

    async def acquire(self, category):
        self.acquires.append(category)


class FakeGammaClient:
    """httpx.AsyncClient stand-in slicing a universe like the real wire.

    Wire model (curator probe c62-probe-gcap.py): lim = min(limit, 100),
    off = int(params.get("offset", 0)), rows = universe[off : off + lim].
    ignore_offset=True models a degenerate wire that returns the first page
    regardless of `offset` (the no-progress guard must stop the loop).
    """

    def __init__(self, registry, universe, ignore_offset=False):
        self._registry = registry
        self._universe = universe
        self._ignore_offset = ignore_offset

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, params=None):
        params = dict(params or {})
        self._registry.append({"url": url, "params": params})
        lim = min(int(params.get("limit", 100)), 100)
        off = 0 if self._ignore_offset else int(params.get("offset", 0))
        rows = self._universe[off : off + lim]
        return SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: rows,
        )


def universe(n_rows):
    """Synthetic /markets page universe: {"id": "m<i>"} dicts."""
    return [{"id": f"m{i}"} for i in range(n_rows)]


def install_wire(monkeypatch, n_rows, ignore_offset=False):
    """Replace market_discovery.httpx with the wire model + rate limiter
    recorder BEFORE any execution (one acquire per page is the post-fix
    contract; the fast path stays exactly one acquire)."""
    calls = []
    rate = FakeRateLimiter()

    def client_factory(**kwargs):
        return FakeGammaClient(calls, universe(n_rows), ignore_offset)

    monkeypatch.setattr(
        market_discovery,
        "httpx",
        SimpleNamespace(AsyncClient=client_factory, HTTPError=httpx.HTTPError),
    )
    monkeypatch.setattr(market_discovery, "get_rate_limiter", lambda: rate)
    return calls, rate


class _FailLoudClient:
    """Client that records and then raises: any GET reaching the network
    path fails the test loud instead of touching the wire (P-0031)."""

    def __init__(self, registry):
        self._registry = registry

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, params=None):
        self._registry.append({"url": url, "params": dict(params or {})})
        raise AssertionError(f"unexpected HTTP GET to {url!r} params={params!r}")


def install_fail_loud_http(monkeypatch):
    """Guard for tool-level tests: the seam _fetch_gamma_markets is stubbed,
    so httpx must never fire."""
    registry = []
    monkeypatch.setattr(
        market_discovery,
        "httpx",
        SimpleNamespace(
            AsyncClient=lambda **kwargs: _FailLoudClient(registry),
            HTTPError=httpx.HTTPError,
        ),
    )
    return registry


def install_fetch_recorder(monkeypatch, rows):
    """Stub market_discovery._fetch_gamma_markets with a call recorder that
    returns rows[:limit] (simulating the real helper's limit semantics)."""
    calls = []

    async def stub(endpoint="/markets", params=None, limit=None):
        calls.append({"endpoint": endpoint, "params": params, "limit": limit})
        return rows[:limit] if limit else rows

    monkeypatch.setattr(market_discovery, "_fetch_gamma_markets", stub)
    return calls


# ---------------------------------------------------------------------------
# _fetch_gamma_markets pagination (V-GCAP)
# ---------------------------------------------------------------------------
async def test_fetch_paginates_when_limit_exceeds_page_size(monkeypatch):
    calls, rate = install_wire(monkeypatch, 1000)

    result = await market_discovery._fetch_gamma_markets(
        "/markets", {"active": "true"}, limit=250
    )

    assert len(result) == 250
    assert [row["id"] for row in result] == [f"m{i}" for i in range(250)]
    assert len(calls) == 3
    # First call is byte-identical to the pre-fix wire: NO "offset" key.
    assert [c["params"].get("offset", "<absent>") for c in calls] == [
        "<absent>",
        100,
        200,
    ]
    assert [c["params"]["limit"] for c in calls] == [100, 100, 100]
    assert rate.acquires == [EndpointCategory.GAMMA_API] * 3


async def test_fetch_fast_path_single_call(monkeypatch):
    calls, rate = install_wire(monkeypatch, 1000)

    result = await market_discovery._fetch_gamma_markets(
        "/markets", {"active": "true"}, limit=50
    )

    assert len(result) == 50
    assert len(calls) == 1
    assert calls[0]["params"] == {"active": "true", "limit": 50}
    assert rate.acquires == [EndpointCategory.GAMMA_API]


async def test_fetch_limit_100_single_call(monkeypatch):
    calls, rate = install_wire(monkeypatch, 1000)

    result = await market_discovery._fetch_gamma_markets(
        "/markets", {"active": "true"}, limit=100
    )

    assert len(result) == 100
    assert len(calls) == 1
    assert calls[0]["params"] == {"active": "true", "limit": 100}
    assert rate.acquires == [EndpointCategory.GAMMA_API]


async def test_fetch_limit_none_single_call(monkeypatch):
    calls, rate = install_wire(monkeypatch, 1000)

    result = await market_discovery._fetch_gamma_markets(
        "/markets", {"active": "true"}, limit=None
    )

    # limit=None: one GET without "limit"/"offset" (byte-identical to the
    # pre-fix behavior); the wire model returns its capped page (100 rows).
    assert len(result) == 100
    assert len(calls) == 1
    assert calls[0]["params"] == {"active": "true"}
    assert rate.acquires == [EndpointCategory.GAMMA_API]


async def test_fetch_last_page_short_stops(monkeypatch):
    calls, rate = install_wire(monkeypatch, 150)

    result = await market_discovery._fetch_gamma_markets(limit=250)

    assert len(result) == 150
    assert len(calls) == 2
    assert [c["params"].get("offset", "<absent>") for c in calls] == [
        "<absent>",
        100,
    ]
    assert rate.acquires == [EndpointCategory.GAMMA_API] * 2


async def test_fetch_no_progress_guard_ignoring_offset(monkeypatch):
    calls, rate = install_wire(monkeypatch, 300, ignore_offset=True)

    result = await market_discovery._fetch_gamma_markets(limit=250)

    # Degenerate wire ignoring `offset`: the no-progress guard stops the
    # loop on the second GET (same first id) -- 100 rows, no hang.
    assert len(result) == 100
    assert len(calls) == 2
    assert rate.acquires == [EndpointCategory.GAMMA_API] * 2


async def test_fetch_max_pages_guard(monkeypatch):
    calls, rate = install_wire(monkeypatch, 1000)

    result = await market_discovery._fetch_gamma_markets(limit=5000)

    assert len(result) == 1000  # _GAMMA_MAX_PAGES * _GAMMA_PAGE_SIZE
    assert len(calls) == 10
    assert [c["params"].get("offset", "<absent>") for c in calls] == [
        "<absent>",
        100,
        200,
        300,
        400,
        500,
        600,
        700,
        800,
        900,
    ]
    assert rate.acquires == [EndpointCategory.GAMMA_API] * 10


# ---------------------------------------------------------------------------
# Tool-level fetch_limit pass-through (trending/closing_soon/sports/crypto)
# ---------------------------------------------------------------------------
async def test_trending_tool_passes_limit_through(monkeypatch):
    install_fail_loud_http(monkeypatch)
    rows = [{"id": f"m{i}", "volume24hr": 1.0} for i in range(250)]
    calls = install_fetch_recorder(monkeypatch, rows)

    result = await market_discovery.get_trending_markets(timeframe="24h", limit=250)

    assert calls[0]["endpoint"] == "/markets"
    # FIXED (farm/T-0460): params gain order/ascending (server-side order).
    assert calls[0]["params"] == {
        "active": "true", "closed": "false", "order": "volume24hr",
        "ascending": "false",
    }
    assert calls[0]["limit"] == 250
    assert len(result) == 250

    result2 = await market_discovery.get_trending_markets(timeframe="24h", limit=10)

    assert calls[1]["params"] == {
        "active": "true", "closed": "false", "order": "volume24hr",
        "ascending": "false",
    }
    assert calls[1]["limit"] == 100  # byte-identical to the :454-456 pin
    assert len(result2) == 10


async def test_closing_soon_tool_passes_limit_through(monkeypatch):
    install_fail_loud_http(monkeypatch)
    base = datetime.utcnow()
    rows = [
        {"id": f"m{i}", "endDate": (base + timedelta(hours=2)).isoformat()}
        for i in range(250)
    ]
    calls = install_fetch_recorder(monkeypatch, rows)

    result = await market_discovery.get_closing_soon_markets(limit=250)

    # FIXED (farm/T-0459): params gain the server-side closing window; the
    # limit-passthrough assertions are unchanged.
    params0 = calls[0]["params"]
    assert params0["order"] == "endDate" and params0["ascending"] == "true"
    assert "end_date_min" in params0 and "end_date_max" in params0
    assert calls[0]["limit"] == 250
    assert len(result) == 250

    result2 = await market_discovery.get_closing_soon_markets(limit=10)

    params1 = calls[1]["params"]
    assert params1["order"] == "endDate" and params1["ascending"] == "true"
    assert calls[1]["limit"] == 100  # byte-identical to the :653-655 pin
    assert len(result2) == 10


async def test_sports_tool_passes_limit_through(monkeypatch):
    install_fail_loud_http(monkeypatch)
    rows = [{"id": f"m{i}"} for i in range(250)]
    calls = install_fetch_recorder(monkeypatch, rows)

    result = await market_discovery.get_sports_markets(limit=250)

    assert calls[0]["params"] == {"tag": "Sports", "active": "true", "closed": "false"}
    assert calls[0]["limit"] == 250
    assert len(result) == 250

    result2 = await market_discovery.get_sports_markets(limit=10)

    assert calls[1]["params"] == {"tag": "Sports", "active": "true", "closed": "false"}
    assert calls[1]["limit"] == 100  # byte-identical to the :781-782 pin
    assert len(result2) == 10


async def test_crypto_tool_passes_limit_through(monkeypatch):
    install_fail_loud_http(monkeypatch)
    rows = [{"id": f"m{i}"} for i in range(250)]
    calls = install_fetch_recorder(monkeypatch, rows)

    result = await market_discovery.get_crypto_markets(limit=250)

    assert calls[0]["params"] == {"tag": "Crypto", "active": "true", "closed": "false"}
    assert calls[0]["limit"] == 250
    assert len(result) == 250

    result2 = await market_discovery.get_crypto_markets(limit=10)

    assert calls[1]["params"] == {"tag": "Crypto", "active": "true", "closed": "false"}
    assert calls[1]["limit"] == 100  # byte-identical to the :812-813 pin
    assert len(result2) == 10
