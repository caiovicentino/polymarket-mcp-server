"""Contract suite for the slug lookup of get_market_details (T-0448).

Wire truth probed first-hand against gamma-api.polymarket.com (2026-09-20):

- ``GET /markets/{slug}`` -> HTTP 422 ``{"type": "validation error",
  "error": "id is invalid"}``: the gamma wire parses the path segment as a
  NUMERIC market id; a slug is never valid there.
- ``GET /markets/{numeric-id}`` -> HTTP 200 with the full market object.
- ``GET /markets?slug=<slug>`` -> HTTP 200 with a LIST of markets.

Before T-0448 the slug branch of get_market_details built the path form
(market_analysis.py:173: ``f"/markets/{slug}"``) - dead-on-arrival: every
slug call surfaced an error envelope instead of the market. The fix uses
the query form, consistent with the condition_id branch (market_analysis
.py:174). The live integration tests pin the wire facts themselves; the
offline tests pin the tool-level branch selection with a fail-loud fake
(P-0031): the fake serves ONLY the query form for slug lookups, because
the wire rejects the path form for slugs - a code path that still builds
``/markets/{slug}`` cannot reach a success payload here.

Suite hygiene: no module-level pytestmark (P-0130(4) - per-test markers
only); live tests carry ONLY ``@pytest.mark.integration`` so the canonical
offline selection of CONTRIBUTING.md excludes them; the transport guard
never fails the suite for infra (5xx = documented skip, other non-200 on
the pinned routes FAIL loud).
"""

import httpx
import pytest

from polymarket_mcp.tools import market_analysis

GAMMA_API_URL = market_analysis.GAMMA_API_URL

SLUG = "xi-jinping-out-before-2027"


class SlugAwareFakeGamma:
    """Fail-loud stand-in for market_analysis._fetch_gamma_api (P-0031).

    Serves ONLY the wire semantics the branch selection must honor:

    - query form ``/markets`` with a ``slug`` param -> the recorded slug
      payload (or the explicit empty list for the unknown-slug pin);
    - query form ``/markets`` with a ``condition_id`` param -> the
      condition_id payload (the sibling branch, pinned unchanged);
    - PATH form ``/markets/{anything}`` -> AssertionError: the wire
      rejects slug path lookups (HTTP 422 'id is invalid'), so a success
      payload would model a behavior the wire never returns.

    Any other endpoint fails loud - no silent fallback to the real network.
    """

    def __init__(self, by_slug=None, by_condition_id=None):
        self.by_slug = dict(by_slug or {})
        self.by_condition_id = dict(by_condition_id or {})
        self.calls = []

    async def __call__(self, endpoint, params=None):
        params = dict(params or {})
        self.calls.append((endpoint, params))
        if endpoint == "/markets":
            slug = params.get("slug")
            if slug is not None:
                if slug not in self.by_slug:
                    raise AssertionError(
                        f"no synthetic gamma payload for slug={slug!r}"
                    )
                return self.by_slug[slug]
            condition_id = params.get("condition_id")
            if condition_id not in self.by_condition_id:
                raise AssertionError(
                    f"no synthetic gamma payload for condition_id={condition_id!r}"
                )
            return self.by_condition_id[condition_id]
        if endpoint.startswith("/markets/"):
            raise AssertionError(
                f"gamma wire rejects slug lookups via the path form "
                f"({endpoint!r} -> HTTP 422 'id is invalid'); the working "
                f"route is /markets?slug="
            )
        raise AssertionError(f"unexpected gamma endpoint: {endpoint!r}")


def market_payload(**overrides):
    """Minimal market object for the get_market_details consumers."""
    payload = {
        "id": "559651",
        "slug": SLUG,
        "question": "Will the proposal pass before December?",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Tool-level branch selection (offline, fail-loud fake)
# ---------------------------------------------------------------------------
async def test_slug_lookup_uses_query_params(monkeypatch):
    """The slug branch must query /markets?slug= (NOT the path form).

    Wire truth: /markets/{slug} answers HTTP 422 'id is invalid' (probed
    2026-09-20); /markets?slug= answers 200 with a list. The fake fails
    loud on the path form, so a branch that still builds f"/markets/{slug}"
    cannot pass this pin.
    """
    gamma = SlugAwareFakeGamma(by_slug={SLUG: market_payload()})
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", gamma)

    details = await market_analysis.get_market_details(slug=SLUG)
    assert gamma.calls == [("/markets", {"slug": SLUG})]
    assert details["slug"] == SLUG


async def test_slug_lookup_collapses_list_to_market(monkeypatch):
    """A one-element list response collapses to the market dict itself -
    the same list-collapse branch the market_id path exercises
    (market_analysis.py:182-183)."""
    gamma = SlugAwareFakeGamma(by_slug={SLUG: market_payload()})
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", gamma)

    details = await market_analysis.get_market_details(slug=SLUG)
    assert details == market_payload()


async def test_slug_lookup_unknown_returns_empty_list(monkeypatch):
    """Observed quirk (pinned in test_get_market_details_identifier_rules
    for the market_id path): an EMPTY list response is returned as-is - no
    collapse, no error (market_analysis.py:182-185). The slug branch
    inherits the behavior; the fix must NOT change it."""
    gamma = SlugAwareFakeGamma(by_slug={SLUG: []})
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", gamma)

    result = await market_analysis.get_market_details(slug=SLUG)
    assert gamma.calls == [("/markets", {"slug": SLUG})]
    assert result == []


async def test_condition_id_branch_unchanged(monkeypatch):
    """Regression pin: the slug-branch fix must NOT touch the sibling
    condition_id branch (query form + list collapse)."""
    cid = "0xabc123"
    gamma = SlugAwareFakeGamma(
        by_condition_id={cid: [market_payload(question="Cond?")]}
    )
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", gamma)

    details = await market_analysis.get_market_details(condition_id=cid)
    assert gamma.calls == [("/markets", {"condition_id": cid})]
    assert details["question"] == "Cond?"


# ---------------------------------------------------------------------------
# Live integration pins - the REAL wire contract (marked integration ONLY;
# transport guard never fails the suite for infra)
# ---------------------------------------------------------------------------
def _skip_on_transport(exc, label):
    """Network guard: infra failures SKIP (never fail the suite for infra)."""
    pytest.skip(f"{label} unreachable ({type(exc).__name__}: {exc})")


def _check_response(response, label):
    """Fail-closed response check: 5xx is an API-side outage (documented
    skip); any other non-200 is a live-contract violation (FAIL)."""
    if response.status_code >= 500:
        pytest.skip(f"{label}: live API outage (HTTP {response.status_code})")
    assert response.status_code == 200, f"{label}: expected HTTP 200, got {response.status_code}"


async def _derive_live_slug(client):
    """Harvest a real market slug from the gamma feed - never a literal
    (a hard-coded slug would pin a volatile market; the suite must follow
    the live feed). Skip is reserved for degenerate feed slices (infra-ish),
    never for a contract violation."""
    try:
        response = await client.get(f"{GAMMA_API_URL}/markets", params={"limit": 1})
    except (httpx.HTTPError, OSError) as exc:
        _skip_on_transport(exc, "gamma /markets")
    _check_response(response, "gamma /markets")
    markets = response.json()
    assert isinstance(markets, list) and markets, "gamma /markets returned no markets"
    slug = markets[0].get("slug")
    if not isinstance(slug, str) or not slug:
        pytest.skip("gamma /markets: top market without a usable slug (degenerate slice)")
    return slug


@pytest.mark.integration
async def test_wire_slug_query_returns_market():
    """Live pin of the WORKING route (probed 2026-09-20): GET
    /markets?slug=<slug> answers HTTP 200 with a LIST carrying at least
    one market whose slug matches the harvested one."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        slug = await _derive_live_slug(client)
        try:
            response = await client.get(
                f"{GAMMA_API_URL}/markets", params={"slug": slug}
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "gamma /markets slug")
        _check_response(response, "gamma /markets slug")
        body = response.json()
        assert isinstance(body, list) and body, body
        assert body[0].get("slug") == slug


@pytest.mark.integration
async def test_wire_slug_path_rejected_422():
    """Live pin of the wire truth that MOTIVATES the fix (probed
    2026-09-20): GET /markets/{slug} answers HTTP 422 'id is invalid' -
    the gamma wire parses the path segment as a numeric id. This pin
    documents the rejection; the tool NEVER swallows it (a 4xx from the
    fetch surfaces as an error envelope to the caller)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        slug = await _derive_live_slug(client)
        try:
            response = await client.get(f"{GAMMA_API_URL}/markets/{slug}")
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "gamma /markets/{slug}")
        if response.status_code >= 500:
            pytest.skip(
                f"gamma /markets/{{slug}}: live API outage (HTTP {response.status_code})"
            )
        assert response.status_code == 422, (
            f"expected the pinned wire rejection HTTP 422 ('id is invalid'), "
            f"got {response.status_code}"
        )
