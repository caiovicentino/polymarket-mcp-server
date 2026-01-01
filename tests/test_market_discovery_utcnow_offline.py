"""Offline probe suite: datetime.utcnow() deprecation pins for market_discovery (T-0097).

Why this suite exists
---------------------
``datetime.utcnow()`` is deprecated since Python 3.12 ("scheduled for removal in a
future version"; venv is 3.12.13). The pyproject blanket
``filterwarnings = ["ignore::DeprecationWarning"]`` hides those warnings from the
default gate run, so the debt is invisible. This suite probes the three call
sites (get_trending_markets :205, get_featured_markets :335,
get_closing_soon_markets :381) with a ``warnings.catch_warnings(record=True)`` +
``simplefilter("always")`` window, which captures warnings even under the
blanket filter (proven by the RED pre-state: each test failed with exactly one
DeprecationWarning attributed to its call site). Post-migration
(``datetime.now(timezone.utc).replace(tzinfo=None)`` -- naive-identical UTC
semantics) all three probes are silent; if the deprecated call returns, the
probe fails loud.

The warning literal is pinned by SUBSTRING of the CPython message
("utcnow() is deprecated", stable 3.12+); that literal does NOT exist in src
(gate acceptance runs ``! grep -rn "utcnow"`` on the module). Semantic pins ride
along so the probe is not vacuous: each test also pins the observable behavior
around the naive ``now``/``cutoff_time`` (expired excluded / future kept;
featured params; closing-soon window), so a "fix" that silenced the warning by
changing semantics would also fail.

Fakes (P-0031/L-0118): ``_fetch_gamma_markets`` is stubbed per test via
monkeypatch with a fail-loud recorder (any endpoint other than "/markets"
raises AssertionError -- a regression can never fall back to the real network).
Zero network: the rate-limiter singleton is never acquired (the real fetch seam
is replaced before any execution) and no HTTP client is constructed. Dates are
synthetic naive ISO strings built with
``datetime.now(timezone.utc).replace(tzinfo=None)`` -- the SAME pattern as the
post-migration code (naive ISO, no suffix), so the closing-soon parse
(``fromisoformat`` WITHOUT tzinfo strip; tz-aware strings hit the TypeError ->
skip branch pinned by tests/test_market_discovery_offline.py) is exercised in
its compatible naive branch. No sleeps (L-0014). No markers: the file runs in
the release gate.
"""

import warnings
from datetime import datetime, timedelta, timezone

from polymarket_mcp.tools import market_discovery

# CPython 3.12+ literal for the deprecated datetime.utcnow() warning (stable
# surface; the literal itself does not exist in src -- see module docstring).
DEPRECATION_SUBSTRING = "utcnow() is deprecated"


class _FailLoudFetch:
    """Async stub for market_discovery._fetch_gamma_markets (P-0031 fail-loud).

    Records every call; any endpoint other than "/markets" raises
    AssertionError so a regression can never silently fall back to the real
    network (the test fails instead of reaching gamma-api). Payload is
    instance-local; monkeypatch restores the real seam after each test.
    """

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def __call__(self, endpoint="/markets", params=None, limit=None):
        self.calls.append({"endpoint": endpoint, "params": params, "limit": limit})
        if endpoint != "/markets":
            raise AssertionError(f"unexpected endpoint reached the fetch seam: {endpoint!r}")
        return self.payload


def _install_fetch(monkeypatch, payload):
    """Replace the module seam with the fail-loud recorder and return it."""
    fetch = _FailLoudFetch(payload)
    monkeypatch.setattr(market_discovery, "_fetch_gamma_markets", fetch)
    return fetch


def _utcnow_deprecation_hits(caught):
    """Filter the probe window to the CPython utcnow deprecation warnings."""
    return [
        warning
        for warning in caught
        if issubclass(warning.category, DeprecationWarning)
        and DEPRECATION_SUBSTRING in str(warning.message)
    ]


def _assert_no_utcnow_deprecation(caught, context):
    """Post-migration pin: the probe window must be free of utcnow warnings.

    Each probe emits at most one such warning per call site under
    simplefilter("always"); pre-migration this assertion fails with the
    captured DeprecationWarning (attribution file:line included in the
    message). Post-migration, zero hits is the passing state.
    """
    hits = _utcnow_deprecation_hits(caught)
    assert not hits, (
        f"datetime.utcnow() DeprecationWarning still emitted from {context}: "
        + "; ".join(f"{w.filename}:{w.lineno}: {w.message}" for w in hits)
    )


async def test_trending_markets_no_utcnow_deprecation(monkeypatch):
    """Probe :205 (get_trending_markets) + expired/future semantics pin."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    payload = [
        {
            "id": "expired",
            "end_date_iso": (now - timedelta(hours=1)).isoformat(),
            "volume24hr": "999",
        },
        {
            "id": "live",
            "end_date_iso": (now + timedelta(hours=2)).isoformat(),
            "volume24hr": "500",
        },
    ]
    fetch = _install_fetch(monkeypatch, payload)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await market_discovery.get_trending_markets()

    _assert_no_utcnow_deprecation(caught, "get_trending_markets")

    # Semantic pin: past end_date_iso is excluded, future is kept, in volume
    # order. The naive-ISO dates exercise the str branch (tzinfo stripped, a
    # no-op on naive strings) around the migrated naive ``now``.
    assert [m["id"] for m in result] == ["live"]
    # FIXED (farm/T-0460): params gain order/ascending (server-side order);
    # the expired-filter and no-utcnow-deprecation pins are unchanged.
    assert fetch.calls == [
        {
            "endpoint": "/markets",
            "params": {
                "active": "true", "closed": "false",
                "order": "volume24hr", "ascending": "false",
            },
            "limit": 100,
        }
    ]


async def test_featured_markets_no_utcnow_deprecation(monkeypatch):
    """Probe :335 (get_featured_markets) + params pin + future-only semantics."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    payload = [
        {
            "id": "stale",
            "end_date_iso": (now - timedelta(hours=1)).isoformat(),
            "volume24hr": "999",
        },
        {
            "id": "feat",
            "end_date_iso": (now + timedelta(hours=2)).isoformat(),
            "volume24hr": "100",
        },
    ]
    fetch = _install_fetch(monkeypatch, payload)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await market_discovery.get_featured_markets()

    _assert_no_utcnow_deprecation(caught, "get_featured_markets")

    # Semantic pin: featured params are exact (:329) and only the future-dated
    # market survives the migrated naive filter (non-empty result also proves
    # the fallback to trending was NOT taken -- calls stay at exactly one).
    assert [m["id"] for m in result] == ["feat"]
    assert fetch.calls == [
        {
            "endpoint": "/markets",
            "params": {"featured": "true", "active": "true", "closed": "false"},
            "limit": 10,
        }
    ]


async def test_closing_soon_no_utcnow_deprecation(monkeypatch):
    """Probe :381 (get_closing_soon_markets) + 24h window semantics pin."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    payload = [
        {"id": "far", "endDate": (now + timedelta(days=30)).isoformat()},
        {"id": "near", "endDate": (now + timedelta(hours=2)).isoformat()},
    ]
    fetch = _install_fetch(monkeypatch, payload)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await market_discovery.get_closing_soon_markets(hours=24)

    _assert_no_utcnow_deprecation(caught, "get_closing_soon_markets")

    # Semantic pin: only the market closing within the 24h window survives the
    # naive cutoff (cutoff_time = migrated naive now + timedelta(hours=hours)).
    # Dates are naive ISO without suffix, so the comparison is naive-vs-naive.
    assert [m["id"] for m in result] == ["near"]
    # FIXED (farm/T-0459): params gain the server-side closing window; the
    # no-utcnow-deprecation probe and the naive cutoff pin are unchanged.
    params0 = fetch.calls[0]["params"]
    assert params0["order"] == "endDate" and params0["ascending"] == "true"
    assert "end_date_min" in params0 and "end_date_max" in params0
    assert fetch.calls[0]["limit"] == 100
