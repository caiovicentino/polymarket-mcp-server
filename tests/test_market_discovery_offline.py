"""Offline regression suite for polymarket_mcp.tools.market_discovery.

Why this suite exists
---------------------
Before this file, the only coverage for tools/market_discovery.py in the
release gate was incidental: tests/test_market_tools.py is marked
`integration` (real Polymarket API) and therefore excluded from the gate
(`-m "not integration and not slow and not real_api and not performance"`).
A regression in the payload-format branches, the expired-market filter, the
closing-soon window, the category/sport/crypto filters or the tool router
would not trip any alarm. This suite pins that semantics offline.

Coverage baseline re-proven at claim time (L-0096), clone main 62bfbc5,
release gate selection: 40.26% stmt (130/232 missing) -- the dead lines are
exactly the branches this suite exercises. market_discovery.py is
byte-identical since 9e675da (git diff empty), so the file:line pins below
hold for both. Divergence from the task contract recorded (L-0025/L-0090):
the contract claims 56.17% / 93 dead stmts; the observed release-gate
baseline is 40.26% / 130 missing (re-measured with
--cov=polymarket_mcp.tools.market_discovery; the contract's dotted
--cov=src.* path does not resolve under PYTHONPATH=src). The contract's
dead-line list matches the observed Missing lines within line-drift
tolerance; the observed numbers are the oracle.

Pin targets (file:line @ clone main 62bfbc5 == 9e675da for this file,
src/polymarket_mcp/tools/market_discovery.py)
-------------------------------------------------------------------------------------
- _fetch_gamma_markets :30-86 -- rate-limiter acquire :46-48, params default :55-56,
  limit injection :59-60, payload formats :70-79 (LIST slice / envelope slice /
  direct-dict wrap / unrecognized -> []), HTTPError re-raise :81-83, generic
  re-raise :84-86.
- _flatten_public_search_markets :89-102 -- events flatten, limit stop.
- _search_gamma_markets :105-148 -- rate limiter :116-118, fixed params :122-126,
  limit_per_type :128-129, extras merge :131-132, /public-search URL :134,
  re-raise paths :143-148.
- search_markets :151-181 -- filters merge :171-172, error re-raise :179-181.
- get_trending_markets :184-244 -- expired filter :204-219 (key precedence
  `end_date_iso or endDate` :208, str/int branches :211-214, malformed
  PRESERVED via `except: pass` :217-218), volume_key_map + default :222-228,
  desc sort :231-235, slice :237, error re-raise :242-244.
- filter_markets_by_category :247-276 -- params by active_only :263-269,
  error re-raise :274-276.
- get_event_markets :279-316 -- ValueError :294-295, slug/id URL :298-301,
  list/dict extraction :304-309, error re-raise :314-316.
- get_featured_markets :319-362 -- same expired filter :334-350, fallback to
  trending :352-355, error re-raise :360-362.
- get_closing_soon_markets :365-416 -- cutoff :381, key precedence
  `endDate or end_date_iso` :389, str/int branches :393-396, window
  comparison :399-400, malformed SKIP with warning :402-404, raw-string sort
  :407, error re-raise :414-416.
- get_sports_markets :419-455 / get_crypto_markets :458-494 -- tag params
  :434/:473, case-insensitive filter :439-446/:478-485, slice :448/:487,
  error re-raise :453-455/:492-494.
- handle_tool :668-710 -- 8 routes + JSON envelope :681-703, unknown ->
  error JSON :697-698/:705-710.

Already Covered (overlap calibration)
--------------------------------------
- tests/test_market_tools.py: pytestmark = pytest.mark.integration (real API,
  excluded from the release gate) -- happy-path discovery/analysis flows only.
  Its endDate parse (:108-110) mirrors the closing-soon parse but never runs
  in the gate. This suite has ZERO overlap inside the release gate.
- tests/test_market_analysis_offline.py (T-0037): market_analysis.py only --
  disjoint module.
- tests/test_rate_limiter.py: rate-limiter internals. This suite NEVER
  touches the singleton (L-0123): the module seam market_discovery.
  get_rate_limiter is replaced with a per-test fake recorder.
- Lines 498-665 (get_tools literals) are covered by the existing gate suite
  (0 missing in the baseline report) and are NOT duplicated here.

Observed divergences recorded per L-0025/L-0090 (code is the oracle)
---------------------------------------------------------------------
1. Key precedence is INVERTED between siblings: trending uses
   `end_date_iso or endDate` (:208) while closing_soon uses
   `endDate or end_date_iso` (:389). Pinned by the contradictory pair in
   test_precedence_enddate_iso_vs_enddate_diverges_trending_closing_soon.
2. Z-suffixed ISO dates: trending strips tzinfo (:212 -> naive -> kept);
   closing_soon does NOT strip (:394 -> tz-aware) and its comparison against
   the naive cutoff raises TypeError -> caught -> market SKIPPED with a
   warning. Formerly pinned by test_z_suffixed_dates_trending_keeps_closing
   _soon_skips (flipped to inclusion by farm/T-0460, item 152).
3. closing_soon includes already-expired markets (:399-400, `<= cutoff`, no
   past floor); trending excludes them (:215-216). Pinned by
   test_closing_soon_includes_already_expired_markets.
4. closing_soon sorts by the RAW STRING endDate (:407): same-format ISO
   strings sort chronologically, but mixing an included ISO market with an
   included int-timestamp market raises TypeError -> re-raised. Pinned by
   test_closing_soon_mixed_date_types_re_raises.
5. trending coerces volume with `float(m.get(key, 0) or 0)` (:233): missing/
   None become 0.0, but a non-numeric string raises ValueError which is
   re-raised (:242-244). Pinned by test_trending_re_raises_errors.
6. get_event_markets with an empty LIST payload falls into the `else` branch
   (:306-307) and then crashes on `event.get("markets")` (list has no .get)
   -> AttributeError re-raised (:314-316). Pinned by
   test_event_markets_empty_list_payload_re_raises.

Hermeticity (P-0029/P-0031/L-0118/L-0123)
-----------------------------------------
Zero network: market_discovery.httpx is replaced by a fail-loud fake module
BEFORE any execution (unexpected HTTP GET -> AssertionError, the suite fails
loud instead of reaching the real API); market_discovery.get_rate_limiter is
replaced by a per-test recorder (the real singleton is never acquired);
public functions are exercised via module-level stubs of _fetch_gamma_markets
/ _search_gamma_markets (isolated per test, restored by monkeypatch).
Dates are synthetic (datetime.utcnow() base, same-format ISO strings), no
sleeps (L-0014). No markers: the file runs in the release gate.
"""

import json
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from polymarket_mcp.tools import market_discovery
from polymarket_mcp.utils.rate_limiter import EndpointCategory

MD_LOGGER = "polymarket_mcp.tools.market_discovery"
_EPOCH = datetime(1970, 1, 1)


# ---------------------------------------------------------------------------
# Fail-loud fakes (P-0031/L-0118) and seams (P-0031/L-0123)
# ---------------------------------------------------------------------------
class FakeGammaResponse:
    """Synthetic httpx.Response: payload, HTTP error or json error."""

    def __init__(self, payload=None, http_error=None, json_error=None):
        self._payload = payload
        self._http_error = http_error
        self._json_error = json_error
        self.status_code = 200

    def raise_for_status(self):
        if self._http_error is not None:
            raise self._http_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeRateLimiter:
    """Inert stand-in for RateLimiter: records acquire() categories (L-0123)."""

    def __init__(self):
        self.acquires = []

    async def acquire(self, category):
        self.acquires.append(category)


def install_gamma_http(monkeypatch, response=None):
    """Replace market_discovery.httpx with a fail-loud fake module.

    The fake AsyncClient records every GET as (url, params) into a registry
    and raises AssertionError on any call when no response was configured --
    an unexpected endpoint/param fails the test instead of reaching the
    network (P-0031). HTTPError is the real class so the module's except
    clauses (:81, :143) keep working.
    """
    registry = []

    class _Client:
        def __init__(self, _registry, _response):
            self._registry = _registry
            self._response = _response

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, params=None):
            self._registry.append({"url": url, "params": dict(params or {})})
            if self._response is None:
                raise AssertionError(f"unexpected HTTP GET to {url!r} params={params!r}")
            return self._response

    def client_factory(**kwargs):
        return _Client(registry, response)

    fake_http = SimpleNamespace(AsyncClient=client_factory, HTTPError=httpx.HTTPError)
    monkeypatch.setattr(market_discovery, "httpx", fake_http)
    return registry


def install_rate_limiter(monkeypatch):
    """Patch the module seam get_rate_limiter (L-0123: never the singleton)."""
    fake = FakeRateLimiter()
    monkeypatch.setattr(market_discovery, "get_rate_limiter", lambda: fake)
    return fake


def install_fetch_stub(monkeypatch, payload=None, error=None):
    """Stub market_discovery._fetch_gamma_markets with a call recorder."""
    calls = []

    async def stub(endpoint="/markets", params=None, limit=None):
        calls.append({"endpoint": endpoint, "params": params, "limit": limit})
        if error is not None:
            raise error
        return payload

    monkeypatch.setattr(market_discovery, "_fetch_gamma_markets", stub)
    return calls


def install_search_stub(monkeypatch, payload=None, error=None):
    """Stub market_discovery._search_gamma_markets with a call recorder."""
    calls = []

    async def stub(query, params=None, limit=None):
        calls.append({"query": query, "params": params, "limit": limit})
        if error is not None:
            raise error
        return payload

    monkeypatch.setattr(market_discovery, "_search_gamma_markets", stub)
    return calls


def epoch_int(dt):
    """Epoch seconds treating dt as UTC (code renders it back in local time)."""
    return int((dt - _EPOCH).total_seconds())


# ---------------------------------------------------------------------------
# _fetch_gamma_markets (:30-86) -- payload formats, limit, error paths
# ---------------------------------------------------------------------------
async def test_fetch_returns_list_sliced_by_limit(monkeypatch):
    rate = install_rate_limiter(monkeypatch)
    registry = install_gamma_http(
        monkeypatch, response=FakeGammaResponse(payload=[{"i": 1}, {"i": 2}, {"i": 3}])
    )

    result = await market_discovery._fetch_gamma_markets("/markets", {"active": "true"}, limit=2)

    assert result == [{"i": 1}, {"i": 2}]
    assert rate.acquires == [EndpointCategory.GAMMA_API]
    assert registry[0]["url"] == market_discovery.GAMMA_API_URL + "/markets"
    assert registry[0]["params"] == {"active": "true", "limit": 2}


async def test_fetch_full_list_and_empty_params_without_limit(monkeypatch):
    install_rate_limiter(monkeypatch)
    registry = install_gamma_http(
        monkeypatch, response=FakeGammaResponse(payload=[{"i": 1}, {"i": 2}])
    )

    result = await market_discovery._fetch_gamma_markets()

    # params default to {} (:55-56) and no "limit" key is injected (:59-60);
    # a list payload without limit is returned intact (:71 else branch).
    assert result == [{"i": 1}, {"i": 2}]
    assert registry[0]["params"] == {}


async def test_fetch_unwraps_data_envelope_and_slices(monkeypatch):
    install_rate_limiter(monkeypatch)
    registry = install_gamma_http(
        monkeypatch,
        response=FakeGammaResponse(
            payload={"data": [{"i": 1}, {"i": 2}, {"i": 3}], "next_cursor": "c1"}
        ),
    )

    sliced = await market_discovery._fetch_gamma_markets(limit=2)
    full = await market_discovery._fetch_gamma_markets(limit=None)

    assert sliced == [{"i": 1}, {"i": 2}]
    assert full == [{"i": 1}, {"i": 2}, {"i": 3}]
    assert registry[1]["params"] == {}  # limit=None injects no "limit" key


async def test_fetch_wraps_direct_dict_market(monkeypatch):
    install_rate_limiter(monkeypatch)
    install_gamma_http(
        monkeypatch, response=FakeGammaResponse(payload={"id": "m1", "question": "Q?"})
    )

    result = await market_discovery._fetch_gamma_markets("/markets/m1")

    assert result == [{"id": "m1", "question": "Q?"}]


async def test_fetch_returns_empty_for_unrecognized_payload(monkeypatch):
    install_rate_limiter(monkeypatch)
    for weird in (42, "garbage", None):
        install_gamma_http(monkeypatch, response=FakeGammaResponse(payload=weird))
        assert await market_discovery._fetch_gamma_markets() == []


async def test_fetch_re_raises_http_error(monkeypatch):
    install_rate_limiter(monkeypatch)
    install_gamma_http(
        monkeypatch, response=FakeGammaResponse(http_error=httpx.HTTPError("boom"))
    )

    with pytest.raises(httpx.HTTPError):
        await market_discovery._fetch_gamma_markets()


async def test_fetch_re_raises_generic_exception(monkeypatch):
    install_rate_limiter(monkeypatch)
    install_gamma_http(
        monkeypatch, response=FakeGammaResponse(json_error=ValueError("bad json"))
    )

    with pytest.raises(ValueError):
        await market_discovery._fetch_gamma_markets()


# ---------------------------------------------------------------------------
# _flatten_public_search_markets (:89-102)
# ---------------------------------------------------------------------------
def test_flatten_public_search_stops_at_limit():
    data = {
        "events": [
            {"markets": [{"i": 1}, {"i": 2}]},
            {"markets": [{"i": 3}, {"i": 4}]},
        ]
    }

    assert market_discovery._flatten_public_search_markets(data, limit=3) == [
        {"i": 1},
        {"i": 2},
        {"i": 3},
    ]
    # limit=None walks the whole flattened list (:99 guard is falsy).
    assert market_discovery._flatten_public_search_markets(data) == [
        {"i": 1},
        {"i": 2},
        {"i": 3},
        {"i": 4},
    ]


def test_flatten_returns_empty_without_events():
    assert market_discovery._flatten_public_search_markets({}) == []
    assert market_discovery._flatten_public_search_markets({"events": None}) == []
    # Events without markets contribute nothing (:97 `or []`).
    assert market_discovery._flatten_public_search_markets({"events": [{"title": "e"}]}) == []


# ---------------------------------------------------------------------------
# _search_gamma_markets (:105-148) -- endpoint, params, error paths
# ---------------------------------------------------------------------------
async def test_search_uses_public_search_endpoint_and_params(monkeypatch):
    rate = install_rate_limiter(monkeypatch)
    registry = install_gamma_http(
        monkeypatch,
        response=FakeGammaResponse(payload={"events": [{"markets": [{"i": 1}]}]}),
    )

    result = await market_discovery._search_gamma_markets("bitcoin", params={"page": 1}, limit=5)

    assert result == [{"i": 1}]
    assert rate.acquires == [EndpointCategory.GAMMA_API]
    assert len(registry) == 1
    assert registry[0]["url"] == market_discovery.GAMMA_API_URL + "/public-search"
    assert registry[0]["params"] == {
        "q": "bitcoin",
        "events_status": "active",
        "keep_closed_markets": 0,
        "limit_per_type": 5,
        "page": 1,
    }


async def test_search_without_limit_or_params_uses_fixed_defaults(monkeypatch):
    install_rate_limiter(monkeypatch)
    registry = install_gamma_http(
        monkeypatch, response=FakeGammaResponse(payload={"events": []})
    )

    result = await market_discovery._search_gamma_markets("fed")

    assert result == []
    assert registry[0]["params"] == {
        "q": "fed",
        "events_status": "active",
        "keep_closed_markets": 0,
    }


async def test_search_re_raises_http_error(monkeypatch):
    install_rate_limiter(monkeypatch)
    install_gamma_http(
        monkeypatch, response=FakeGammaResponse(http_error=httpx.HTTPError("boom"))
    )

    with pytest.raises(httpx.HTTPError):
        await market_discovery._search_gamma_markets("bitcoin")


async def test_search_re_raises_generic_exception(monkeypatch):
    install_rate_limiter(monkeypatch)
    install_gamma_http(
        monkeypatch, response=FakeGammaResponse(json_error=ValueError("bad json"))
    )

    with pytest.raises(ValueError):
        await market_discovery._search_gamma_markets("bitcoin")


# ---------------------------------------------------------------------------
# search_markets (:151-181) -- filters merge + error path
# ---------------------------------------------------------------------------
async def test_search_markets_merges_filters_into_params(monkeypatch):
    calls = install_search_stub(monkeypatch, payload=[{"id": "m1"}])

    result = await market_discovery.search_markets("bitcoin", limit=7, filters={"tag": "politics"})
    merged = await market_discovery.search_markets("bitcoin")

    assert result == [{"id": "m1"}]
    assert merged == [{"id": "m1"}]
    assert calls[0] == {"query": "bitcoin", "params": {"tag": "politics"}, "limit": 7}
    # No filters -> params stay empty (:171 guard falsy).
    assert calls[1] == {"query": "bitcoin", "params": {}, "limit": 20}


async def test_search_markets_re_raises_errors(monkeypatch):
    install_search_stub(monkeypatch, error=ValueError("boom"))

    with pytest.raises(ValueError):
        await market_discovery.search_markets("bitcoin")


# ---------------------------------------------------------------------------
# get_trending_markets (:184-244) -- filter, sort, slice, error path
# ---------------------------------------------------------------------------
async def test_trending_filters_expired_and_keeps_malformed_dates(monkeypatch):
    base = datetime.utcnow()
    payload = [
        {"id": "expired", "end_date_iso": (base - timedelta(hours=48)).isoformat()},
        {"id": "future", "end_date_iso": (base + timedelta(hours=48)).isoformat()},
        {"id": "malformed", "end_date_iso": "not-a-date"},
        {"id": "no-date"},
        {"id": "int-future", "end_date_iso": epoch_int(base + timedelta(hours=72))},
        {"id": "int-past", "end_date_iso": epoch_int(base - timedelta(hours=48))},
    ]
    calls = install_fetch_stub(monkeypatch, payload=payload)

    result = await market_discovery.get_trending_markets(timeframe="24h", limit=10)

    # Expired (ISO + int) are dropped (:215-216); malformed is PRESERVED via
    # `except: pass` (:217-218); markets without dates are kept (:209 falsy).
    # Stable sort with all-zero volumes keeps insertion order (:231-235).
    assert [m["id"] for m in result] == ["future", "malformed", "no-date", "int-future"]
    assert calls[0]["endpoint"] == "/markets"
    # FIXED (farm/T-0460): the params gain the server-side order key
    # (farm/T-0455 client sort stays; the wire honors order+ascending=false).
    assert calls[0]["params"] == {
        "active": "true", "closed": "false", "order": "volume24hr",
        "ascending": "false",
    }
    assert calls[0]["limit"] == 100


async def test_trending_keeps_enddate_only_and_int_timestamp_dates(monkeypatch):
    base = datetime.utcnow()
    payload = [
        {"id": "enddate-only", "endDate": (base + timedelta(hours=48)).isoformat()},
    ]
    install_fetch_stub(monkeypatch, payload=payload)

    result = await market_discovery.get_trending_markets()

    # `end_date_iso or endDate` (:208): only-endDate markets fall to the
    # second operand and survive the expired filter.
    assert [m["id"] for m in result] == ["enddate-only"]


async def test_trending_sorts_by_timeframe_volume_desc(monkeypatch):
    low = {"id": "low", "volume24hr": 10, "volume1wk": 10, "volume1mo": 10}
    high = {"id": "high", "volume24hr": 1, "volume1wk": 30, "volume1mo": 10}
    mid = {"id": "mid", "volume24hr": 5, "volume1wk": 20, "volume1mo": 10}
    install_fetch_stub(monkeypatch, payload=[low, high, mid])

    result = await market_discovery.get_trending_markets(timeframe="7d", limit=3)

    # volume24hr order would be low > mid > high; the assert proves the sort
    # keyed on volume1wk (the real wire field; L-0115 discriminating inputs).
    assert [m["id"] for m in result] == ["high", "mid", "low"]


async def test_trending_defaults_to_24h_volume_and_slices_limit(monkeypatch):
    payload = [
        {"id": "a", "volume24hr": 5},
        {"id": "b", "volume24hr": "50"},  # string coerced by float() (:233)
        {"id": "c", "volume24hr": None},  # `or 0` -> 0.0
        {"id": "d"},  # missing key -> 0.0
    ]
    install_fetch_stub(monkeypatch, payload=payload)

    result = await market_discovery.get_trending_markets(timeframe="weekly", limit=2)

    # Unknown timeframe falls back to volume24hr (:228).
    assert [m["id"] for m in result] == ["b", "a"]


async def test_trending_re_raises_errors(monkeypatch):
    install_fetch_stub(monkeypatch, error=ValueError("boom"))
    with pytest.raises(ValueError):
        await market_discovery.get_trending_markets()

    # Non-numeric volume string explodes inside float() during the sort and
    # is re-raised by the outer handler (:242-244).
    install_fetch_stub(monkeypatch, payload=[{"id": "x", "volume24hr": "abc"}])
    with pytest.raises(ValueError):
        await market_discovery.get_trending_markets()


# ---------------------------------------------------------------------------
# filter_markets_by_category (:247-276)
# ---------------------------------------------------------------------------
async def test_filter_category_params_reflect_active_only(monkeypatch):
    calls = install_fetch_stub(monkeypatch, payload=[])

    await market_discovery.filter_markets_by_category("Politics", active_only=True, limit=7)
    await market_discovery.filter_markets_by_category("Politics", active_only=False, limit=3)

    assert calls[0] == {
        "endpoint": "/markets",
        "params": {"tag": "Politics", "closed": "false", "active": "true"},
        "limit": 7,
    }
    assert calls[1] == {
        "endpoint": "/markets",
        "params": {"tag": "Politics", "closed": "false"},
        "limit": 3,
    }


async def test_filter_category_re_raises_errors(monkeypatch):
    install_fetch_stub(monkeypatch, error=ValueError("boom"))

    with pytest.raises(ValueError):
        await market_discovery.filter_markets_by_category("Politics")


# ---------------------------------------------------------------------------
# get_event_markets (:279-316) -- validation, slug/id, extraction
# ---------------------------------------------------------------------------
async def test_event_markets_requires_slug_or_id(monkeypatch):
    calls = install_fetch_stub(monkeypatch, payload=[])

    with pytest.raises(ValueError, match="Either event_slug or event_id must be provided"):
        await market_discovery.get_event_markets()

    # Rejected BEFORE any fetch (P-0031 mechanical pin).
    assert calls == []


async def test_event_markets_extracts_markets_from_list_and_dict_payload(monkeypatch):
    # LIST payload: first element is the event dict (:304-305).
    calls_list = install_fetch_stub(monkeypatch, payload=[{"markets": [{"q": "m1"}]}])
    result = await market_discovery.get_event_markets(event_slug="presidential-election")
    assert result == [{"q": "m1"}]
    assert calls_list == [
        {"endpoint": "/events/presidential-election", "params": None, "limit": None}
    ]

    calls_dict = install_fetch_stub(monkeypatch, payload={"markets": [{"q": "m2"}]})
    result = await market_discovery.get_event_markets(event_id="12345")
    assert result == [{"q": "m2"}]
    assert calls_dict == [{"endpoint": "/events/12345", "params": None, "limit": None}]


async def test_event_markets_slug_takes_precedence_over_id(monkeypatch):
    calls = install_fetch_stub(monkeypatch, payload={"markets": []})

    await market_discovery.get_event_markets(event_slug="the-slug", event_id="9")

    assert calls[0]["endpoint"] == "/events/the-slug"


async def test_event_markets_empty_list_payload_re_raises(monkeypatch):
    install_fetch_stub(monkeypatch, payload=[])

    # Empty list skips the first-element branch (:304-305) and the dict
    # extraction crashes on list.get -> AttributeError re-raised (:314-316).
    with pytest.raises(AttributeError):
        await market_discovery.get_event_markets(event_slug="the-slug")


# ---------------------------------------------------------------------------
# get_featured_markets (:319-362) -- filter, fallback, error path
# ---------------------------------------------------------------------------
async def test_featured_falls_back_to_trending_when_empty(monkeypatch):
    install_fetch_stub(monkeypatch, payload=[])
    fallback_calls = []

    async def trending_stub(timeframe="24h", limit=10):
        fallback_calls.append({"timeframe": timeframe, "limit": limit})
        return [{"id": "t1"}]

    monkeypatch.setattr(market_discovery, "get_trending_markets", trending_stub)

    result = await market_discovery.get_featured_markets(limit=3)

    assert result == [{"id": "t1"}]
    assert fallback_calls == [{"timeframe": "24h", "limit": 3}]


async def test_featured_returns_filtered_without_fallback(monkeypatch):
    base = datetime.utcnow()
    payload = [
        {"id": "expired", "endDate": (base - timedelta(hours=48)).isoformat()},
        {"id": "malformed", "end_date_iso": "nope"},
        {"id": "int-future", "end_date_iso": epoch_int(base + timedelta(hours=72))},
        {"id": "no-date"},
    ]
    calls = install_fetch_stub(monkeypatch, payload=payload)

    async def trending_stub(timeframe="24h", limit=10):
        raise AssertionError("fallback must not run when featured markets exist")

    monkeypatch.setattr(market_discovery, "get_trending_markets", trending_stub)

    result = await market_discovery.get_featured_markets(limit=10)

    assert [m["id"] for m in result] == ["malformed", "int-future", "no-date"]
    assert calls[0]["params"] == {"featured": "true", "active": "true", "closed": "false"}


async def test_featured_re_raises_errors(monkeypatch):
    install_fetch_stub(monkeypatch, error=ValueError("boom"))

    with pytest.raises(ValueError):
        await market_discovery.get_featured_markets()


# ---------------------------------------------------------------------------
# get_closing_soon_markets (:365-416) -- window, malformed dates, sort
# ---------------------------------------------------------------------------
async def test_closing_soon_includes_within_window_and_excludes_after(monkeypatch):
    base = datetime.utcnow()
    payload = [
        {"id": "within", "endDate": (base + timedelta(hours=2)).isoformat()},
        {"id": "after", "endDate": (base + timedelta(hours=48)).isoformat()},
        {"id": "iso-only", "end_date_iso": (base + timedelta(hours=1)).isoformat()},
        {"id": "no-date"},
    ]
    calls = install_fetch_stub(monkeypatch, payload=payload)

    result = await market_discovery.get_closing_soon_markets(hours=24, limit=10)

    # `endDate or end_date_iso` (:389): the iso-only market falls to the
    # second operand and is included (soonest, first after the raw sort).
    # A market without any date fails the `if end_date:` guard (:390) and is
    # silently excluded -- no warning, not appended.
    assert [m["id"] for m in result] == ["iso-only", "within"]
    assert calls[0]["endpoint"] == "/markets"
    # FIXED (farm/T-0459): the params gain the server-side closing window
    # (end_date_min/end_date_max bound the wire; order=endDate ascending
    # returns the soonest-closing first). The window is time-dependent, so
    # the pin checks structure + the window span instead of exact strings.
    params = calls[0]["params"]
    assert params["order"] == "endDate" and params["ascending"] == "true"
    assert params["active"] == "true" and params["closed"] == "false"
    floor = datetime.fromisoformat(params["end_date_min"].replace("Z", "+00:00"))
    ceil = datetime.fromisoformat(params["end_date_max"].replace("Z", "+00:00"))
    assert abs((ceil - floor).total_seconds() - 24 * 3600) <= 2
    assert calls[0]["limit"] == 100


async def test_closing_soon_int_timestamp_branch(monkeypatch):
    base = datetime.utcnow()
    payload = [
        {"id": "int-within", "endDate": epoch_int(base + timedelta(hours=2))},
        {"id": "int-after", "endDate": epoch_int(base + timedelta(hours=48))},
    ]
    install_fetch_stub(monkeypatch, payload=payload)

    result = await market_discovery.get_closing_soon_markets(hours=24, limit=10)

    # int branch (:395-396). fromtimestamp renders in LOCAL time; the 2h/48h
    # margins hold for any UTC offset within +-14h.
    assert [m["id"] for m in result] == ["int-within", "int-after"][:1]


async def test_closing_soon_skips_malformed_dates_with_warning(monkeypatch, caplog):
    payload = [
        {"id": "bad", "endDate": "not-a-date"},
        {"id": "good", "endDate": (datetime.utcnow() + timedelta(hours=2)).isoformat()},
    ]
    install_fetch_stub(monkeypatch, payload=payload)

    with caplog.at_level(logging.WARNING, logger=MD_LOGGER):
        result = await market_discovery.get_closing_soon_markets(hours=24, limit=10)

    assert [m["id"] for m in result] == ["good"]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("not-a-date" in r.getMessage() for r in warnings)


async def test_closing_soon_sorts_soonest_first(monkeypatch):
    base = datetime.utcnow()
    later = {"id": "later", "endDate": (base + timedelta(hours=3)).isoformat()}
    sooner = {"id": "sooner", "endDate": (base + timedelta(hours=1)).isoformat()}
    install_fetch_stub(monkeypatch, payload=[later, sooner])

    result = await market_discovery.get_closing_soon_markets(hours=24, limit=10)

    # Raw-string sort (:407): both dates come from the SAME base with the
    # same ISO format (microseconds), so lexicographic == chronological.
    assert [m["id"] for m in result] == ["sooner", "later"]


async def test_closing_soon_includes_already_expired_markets(monkeypatch):
    past = {"id": "past", "endDate": (datetime.utcnow() - timedelta(hours=48)).isoformat()}
    install_fetch_stub(monkeypatch, payload=[past])

    result = await market_discovery.get_closing_soon_markets(hours=24, limit=10)

    # <= cutoff (:399-400) with no past floor: expired markets still count as
    # closing soon in the CLIENT filter (divergence from trending, see header
    # observation 3). On the live path the server-side `end_date_min` floor
    # (farm/T-0459) already excludes expired markets; this stub-fed pin
    # exercises the client filter alone.
    assert [m["id"] for m in result] == ["past"]


async def test_closing_soon_mixed_date_types_re_raises(monkeypatch):
    base = datetime.utcnow()
    payload = [
        {"id": "iso", "endDate": (base + timedelta(hours=2)).isoformat()},
        {"id": "int", "endDate": epoch_int(base + timedelta(hours=1))},
    ]
    install_fetch_stub(monkeypatch, payload=payload)

    # Raw-string sort compares str vs int -> TypeError, caught and re-raised
    # by the outer handler (:414-416).
    with pytest.raises(TypeError):
        await market_discovery.get_closing_soon_markets(hours=24, limit=10)


async def test_closing_soon_re_raises_fetch_errors(monkeypatch):
    install_fetch_stub(monkeypatch, error=ValueError("boom"))

    with pytest.raises(ValueError):
        await market_discovery.get_closing_soon_markets()


async def test_z_suffixed_dates_trending_and_closing_soon_included(monkeypatch):
    z_date = (
        (datetime.utcnow() + timedelta(hours=48)).replace(microsecond=0).isoformat() + "Z"
    )
    market = {"id": "m", "endDate": z_date}
    install_fetch_stub(monkeypatch, payload=[market])

    trending = await market_discovery.get_trending_markets()
    assert [m["id"] for m in trending] == ["m"]

    closing = await market_discovery.get_closing_soon_markets(hours=72, limit=10)

    # FIXED (farm/T-0460, REQUER-HUMANO item 152): the Z-suffixed endDate is
    # stripped to naive UTC before the cutoff comparison, so real wire dates
    # are INCLUDED (the old pin test_z_suffixed_dates_trending_keeps_closing
    # _soon_skips asserted the [] skip plus the parse warning as OBSERVED;
    # hours=72 keeps the +48h z_date inside the window).
    assert [m["id"] for m in closing] == ["m"]


async def test_precedence_enddate_iso_vs_enddate_diverges_trending_closing_soon(monkeypatch):
    iso_past = (datetime.utcnow() - timedelta(hours=48)).isoformat()
    iso_future = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    market = {"id": "m", "end_date_iso": iso_past, "endDate": iso_future}
    install_fetch_stub(monkeypatch, payload=[market])

    # Trending reads end_date_iso FIRST (:208): past -> dropped.
    trending = await market_discovery.get_trending_markets()
    assert trending == []

    # closing_soon reads endDate FIRST (:389): near future -> included.
    closing = await market_discovery.get_closing_soon_markets(hours=24, limit=10)
    assert [m["id"] for m in closing] == ["m"]


# ---------------------------------------------------------------------------
# get_sports_markets (:419-455) / get_crypto_markets (:458-494)
# ---------------------------------------------------------------------------
async def test_sports_filters_by_type_across_question_title_tags(monkeypatch):
    by_question = {"id": "q", "question": "Will the NFL season start on time?"}
    by_title = {"id": "t", "title": "nfl playoffs bracket"}
    by_tag = {"id": "g", "tags": ["nfl", "sports"]}
    other = {"id": "other", "question": "Will Bitcoin close above 100k?"}
    calls = install_fetch_stub(monkeypatch, payload=[by_question, by_title, by_tag, other])

    result = await market_discovery.get_sports_markets(sport_type="NFL", limit=10)

    # Case-insensitive match across question/title/tags (:439-446); the
    # non-matching market is excluded; result sliced by limit (:448).
    assert [m["id"] for m in result] == ["q", "t", "g"]
    assert calls[0]["params"] == {"tag": "Sports", "active": "true", "closed": "false"}
    assert calls[0]["limit"] == 100


async def test_sports_without_type_returns_all(monkeypatch):
    install_fetch_stub(monkeypatch, payload=[{"id": 1}, {"id": 2}])

    result = await market_discovery.get_sports_markets(limit=1)

    # sport_type=None skips the filter (:439); slice applies (:448).
    assert result == [{"id": 1}]


async def test_sports_re_raises_errors(monkeypatch):
    install_fetch_stub(monkeypatch, error=ValueError("boom"))

    with pytest.raises(ValueError):
        await market_discovery.get_sports_markets()


async def test_crypto_filters_by_symbol_case_insensitive(monkeypatch):
    by_question = {"id": "q", "question": "Will BTC hit 100k?"}
    by_title = {"id": "t", "title": "btc dominance"}
    by_tag = {"id": "g", "tags": ["crypto", "BTC"]}
    other = {"id": "other", "question": "Will the election be called?"}
    calls = install_fetch_stub(monkeypatch, payload=[by_question, by_title, by_tag, other])

    result = await market_discovery.get_crypto_markets(symbol="btc", limit=10)

    # symbol.upper() matching (:479-485); non-matching market excluded.
    assert [m["id"] for m in result] == ["q", "t", "g"]
    assert calls[0]["params"] == {"tag": "Crypto", "active": "true", "closed": "false"}
    assert calls[0]["limit"] == 100


async def test_crypto_without_symbol_returns_all(monkeypatch):
    install_fetch_stub(monkeypatch, payload=[{"id": 1}, {"id": 2}])

    result = await market_discovery.get_crypto_markets(limit=1)

    assert result == [{"id": 1}]


async def test_crypto_re_raises_errors(monkeypatch):
    install_fetch_stub(monkeypatch, error=ValueError("boom"))

    with pytest.raises(ValueError):
        await market_discovery.get_crypto_markets()


# ---------------------------------------------------------------------------
# handle_tool (:668-710) -- routing + error envelope
# ---------------------------------------------------------------------------
async def test_handle_tool_routes_all_eight_names(monkeypatch):
    tool_args = {
        "search_markets": {"query": "bitcoin"},
        "get_trending_markets": {"limit": 3},
        "filter_markets_by_category": {"category": "Politics"},
        "get_event_markets": {"event_slug": "the-slug"},
        "get_featured_markets": {"limit": 2},
        "get_closing_soon_markets": {"hours": 6},
        "get_sports_markets": {"sport_type": "NFL"},
        "get_crypto_markets": {"symbol": "BTC"},
    }
    calls = []
    for name in tool_args:

        async def recorder(_name=name, **kwargs):
            calls.append((_name, dict(kwargs)))
            return {"route": _name, "args": kwargs}

        monkeypatch.setattr(market_discovery, name, recorder)

    for name, args in tool_args.items():
        contents = await market_discovery.handle_tool(name, args)
        assert len(contents) == 1
        assert contents[0].type == "text"
        assert json.loads(contents[0].text) == {"route": name, "args": args}

    assert calls == [(name, tool_args[name]) for name in tool_args]


async def test_handle_tool_unknown_returns_error_json(monkeypatch):
    contents = await market_discovery.handle_tool("definitely_not_a_tool", {})

    assert len(contents) == 1
    assert contents[0].type == "text"
    assert json.loads(contents[0].text) == {"error": "Unknown tool: definitely_not_a_tool"}
