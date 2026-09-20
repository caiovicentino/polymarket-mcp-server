"""Search-pagination contract suite for search_markets (REQUER-HUMANO item 195).

V-PS, probed live by the curator at clone main c7338f4 (2026-09-19, curl
first-hand; re-proven 1st-hand at claim time of this suite -- counts vary with
data freshness, the wire FACTS do not):

- ``GET /public-search?q=btc&limit_per_type=500`` -> **50 events** (page cap),
  ``pagination.hasMore=True``, ``pagination.totalResults`` present.
- ``limit_per_type`` 20/50/51/60 -> 20/50/50/50 events: the page cap is 50 and
  larger page requests are TRUNCATED.
- ``page=2`` -> a window whose FIRST event id DIFFERS from page 1: the
  ``page=`` param is HONORED by the wire (page-2 response SIZE varies live;
  only the differing-first-id fact is pinned, never a hardcoded count).

The code (market_discovery.py ``_search_gamma_markets`` :117-146 at c7338f4)
makes ONE call (``search_params["limit_per_type"] = limit``) and flattens:
``search_markets(q, limit=100)`` silently returns <= 50 events (half the
requested limit). The ``pagination.hasMore``/``totalResults`` exposed by the
wire are IGNORED. Same class as V-GCAP (page cap + one-call truncation) but a
DISTINCT wire: /public-search paginates via ``page=`` (not offset).

Suite anatomy (playbook P-0130 -- the fake models the REAL wire):

1. Offline xfail(strict=True) with ``_FakePublicSearchClient`` installed at
   the seam ``market_discovery.httpx.AsyncClient`` (setattr on the shared
   httpx object) + ``get_rate_limiter`` -> noop limiter (hermeticity P-0096).
   The fake serves a pool of 120 synthetic events (ids "1".."120", one market
   each so the page cap binds): ``limit_per_type=N`` -> ``min(N, 50)`` events
   per page; ``page=P`` -> the window ``[(P-1)*50 : P*50]`` of the pool;
   ``pagination={"hasMore": ..., "totalResults": 120}`` (totalResults lives
   INSIDE pagination on the real wire -- probed 1st-hand). Fix-agnostic: a
   correct fix paginates via ``page=`` and reaches >= 100 markets; the
   status quo (one call) stays at 50 -> the xfail stays consumed. A fix that
   paginates BEYOND the real wire (threads/parallel fan-out) is re-derivation,
   not a flip.

2. Flip coupling (declared): the future fix consumes the flip -- fix lands ->
   >= 100 -> XPASS(strict) -> RED -> flip consumed (P-0113). COMPATIBILITY
   PINS the fix must survive (item 195, EXISTING tests are untouchable):
   test_issue_fixes.py:128-149 (call-shape ``search_markets`` ->
   ``_search_gamma_markets`` asserted awaited-once with unchanged args; the
   public-search flattening shape) and test_market_discovery_offline.py:32-34
   (:320-346 flattening pins: events flatten + limit stop + empty payloads).
   Therefore the fix's FIRST request must stay byte-identical
   (``limit_per_type=limit``, no ``page``) and the flattening / return shape
   (list of market dicts) must not change.

3. Live integration greens (part B): canonical live marking is
   ``@pytest.mark.integration`` (pattern T-0304) -- NEVER ``real_api``.
   Network guard: connection/DNS/transport failures and 5xx outages SKIP with
   a declared reason (L-0026 SKIP-de-infra); non-5xx non-200 FAILS (live
   contract violation). Ids are collected live and compared -- NEVER
   hardcoded. Zero ``pytestmark`` module-level (P-0130(4)): the markers are
   per-test so the offline xfail stays in the release-gate selection.

Zero network offline: the fake fails loud on any unexpected fetch (P-0031)
and the rate limiter is a noop -- no sleeps, no real singleton (L-0123/L-0014).
ASCII-only (item 147). Expected delta vs the observable main at claim time
(L-0320 isolated provenance; base re-proven 1st-hand: 781 passed / 146
deselected / 27 xfailed): +1 xfailed, +0 passed, +2 deselected in the
canonical release-gate selection.
"""

import httpx
import pytest

from polymarket_mcp.tools import market_discovery

GAMMA = "https://gamma-api.polymarket.com"

_PAGE_CAP = 50
_POOL_SIZE = 120

# The pool of synthetic events the fake serves: ids "1".."120" (the real wire
# carries string event ids), one market per event so the 50-event page cap
# binds the flattening at 50 markets per call (one-call status quo).
_POOL = [
    {
        "id": str(i),
        "title": f"Synthetic search event {i}",
        "slug": f"event-{i}",
        "markets": [
            {
                "id": f"mkt-{i}",
                "question": f"Synthetic market {i} about btc?",
                "slug": f"mkt-{i}",
            }
        ],
    }
    for i in range(1, _POOL_SIZE + 1)
]


class _NoopLimiter:
    """Rate limiter seam replacement: acquires nothing, sleeps nowhere."""

    async def acquire(self, category):
        return None


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP {self.status_code}")
        return None

    def json(self):
        return self._payload


class _FakePublicSearchClient:
    """Models the REAL /public-search wire: page cap 50 events per page, the
    ``page=`` param is honored as a 50-stride window over the pool, and
    ``pagination`` exposes ``hasMore``/``totalResults`` exactly as the wire
    does (totalResults inside pagination). Any fetch other than the
    public-search GET fails loud (P-0031). Call log is kept for diagnostics
    only -- the xfail pins the OUTCOME, never the call count."""

    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        self.calls.append({"url": url, "params": params})
        if not url.endswith("/public-search"):
            raise AssertionError(f"unexpected fetch: {url} {params}")
        params = dict(params or {})
        limit = int(params.get("limit_per_type") or _PAGE_CAP)
        page_size = min(limit, _PAGE_CAP)
        if "page" in params:
            page = int(params["page"])
            window = _POOL[(page - 1) * _PAGE_CAP : page * _PAGE_CAP]
            has_more = page * _PAGE_CAP < _POOL_SIZE
        else:
            window = _POOL[0:page_size]
            has_more = page_size < _POOL_SIZE
        payload = {
            "events": [dict(event) for event in window],
            "pagination": {"hasMore": has_more, "totalResults": _POOL_SIZE},
        }
        return _FakeResponse(payload)


def _install(monkeypatch):
    """Wire the module onto the fake at the single seam + noop rate limiter.

    The module constructs its OWN client instance, so a plain class swap
    would leave the call log unreachable. The factory captures every created
    instance so the diagnostics can report the TOTAL call count honestly.
    """
    created = []

    def _factory(*args, **kwargs):
        instance = _FakePublicSearchClient(*args, **kwargs)
        created.append(instance)
        return instance

    monkeypatch.setattr(market_discovery.httpx, "AsyncClient", _factory)
    monkeypatch.setattr(market_discovery, "get_rate_limiter", lambda: _NoopLimiter())
    return created


@pytest.mark.xfail(
    strict=True,
    reason=(
        "REQUER-HUMANO item 195: search_markets truncates at the /public-search "
        "page cap (50) - one call, pagination ignored"
    ),
)
async def test_search_markets_limit_above_page_cap_returns_full_result(monkeypatch):
    """search_markets(limit=100) must return >= 100 markets via pagination.

    Today: one call with limit_per_type=100 -> the wire page caps at 50 events
    -> 50 markets -> the assert fails -> xfail consumed by the RIGHT assert.
    After the fix (paginates via page=): >= 100 markets -> XPASS(strict) ->
    RED -> the fix consumes the flip (P-0113). The fake NEVER helps the fix:
    it models the real wire (cap 50, page= honored, hasMore exposed).
    """
    created = _install(monkeypatch)
    result = await market_discovery.search_markets(query="btc", limit=100)
    total_calls = sum(len(instance.calls) for instance in created)
    assert len(result) >= 100, (
        f"search_markets(limit=100) must honor the user limit via pagination: got "
        f"{len(result)} markets after {total_calls} call(s); the "
        f"/public-search page cap is {_PAGE_CAP} events and the wire exposes "
        f"pagination.hasMore/totalResults (item 195)"
    )


# ---------------------------------------------------------------------------
# Live integration greens - the REAL wire facts the future fix builds on
# (marked integration ONLY; deselected from the offline release gate)
# ---------------------------------------------------------------------------
def _public_search_get(params, label):
    """Live GET with the declared network guard: infra failures SKIP
    (connection/DNS/transport, L-0026), 5xx is an API-side outage SKIP;
    any other non-200 is a live-contract violation (FAIL)."""
    try:
        response = httpx.get(f"{GAMMA}/public-search", params=params, timeout=30.0)
    except (httpx.HTTPError, OSError) as exc:
        pytest.skip(f"network unavailable ({type(exc).__name__}: {exc})")
    if response.status_code >= 500:
        pytest.skip(f"{label}: live API outage (HTTP {response.status_code})")
    assert response.status_code == 200, (
        f"{label}: expected HTTP 200, got {response.status_code}"
    )
    return response


@pytest.mark.integration
def test_public_search_page_param_honored_live():
    """The page= param is honored: page 2's first event id DIFFERS from
    page 1's. Ids are collected live and compared -- never hardcoded."""
    first = _public_search_get(
        {"q": "btc", "limit_per_type": 500}, "public-search page 1"
    )
    second = _public_search_get(
        {"q": "btc", "limit_per_type": 500, "page": 2}, "public-search page 2"
    )
    first_events = first.json().get("events") or []
    second_events = second.json().get("events") or []
    assert first_events, "page 1 must return events"
    assert second_events, "page 2 must return events"
    first_id = first_events[0]["id"]
    second_id = second_events[0]["id"]
    assert first_id != second_id, (
        f"page=2 must return a DIFFERENT window: page-2 first id {second_id!r} "
        f"equals page-1 first id {first_id!r} -- the page param is not honored (item 195)"
    )


@pytest.mark.integration
def test_public_search_page_cap_is_50_live():
    """The /public-search page cap is 50 events and pagination.hasMore is
    True at the cap: more pages exist and the one-call code ignores them."""
    response = _public_search_get(
        {"q": "btc", "limit_per_type": 500}, "public-search cap probe"
    )
    body = response.json()
    events = body.get("events") or []
    assert len(events) == 50, (
        f"the /public-search page cap must be 50 events: got {len(events)} "
        f"events for limit_per_type=500 (item 195)"
    )
    pagination = body.get("pagination") or {}
    assert pagination.get("hasMore") is True, (
        f"pagination.hasMore must be True at the cap (pagination={pagination!r}): "
        f"more pages exist and the one-call code ignores them (item 195)"
    )
