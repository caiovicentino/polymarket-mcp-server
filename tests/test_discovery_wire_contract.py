"""Wire-contract suite for the market_discovery tool gaps (REQUER-HUMANO item 155).

Four user-facing gaps proven first-hand against the live gamma API (curator
probes, increment 60, 2026-09-18):

1. ``filter_markets_by_category`` / ``get_sports_markets`` / ``get_crypto_markets``
   pass ``tag=<category>`` to ``GET /markets`` -- but the wire IGNORES ``tag``
   and ``tag_slug`` (probed: the first market of ``tag=Crypto`` is the Xi Jinping
   politics market, identical to the plain listing, while 8/8 results carry no
   crypto tag). The WORKING filter is ``tag_id``: ``/tags/slug/crypto`` resolves
   id 21, ``/markets?tag_id=21`` returns only crypto markets, and a bogus
   ``tag_id`` returns ``[]``. IMPORTANT: the markets of the ``/markets`` LIST
   response carry ``events`` arrays whose ``tags`` are EMPTY on the wire, so
   client-side filtering via ``events[].tags`` is NOT viable -- the fix must use
   the ``tag_id`` route (or prove another working wire param).

2. ``get_featured_markets`` passes ``featured=true`` to ``GET /markets`` -- the
   wire IGNORES the param (probed: 100 results whose ``featured`` field is
   ``False``). The market objects DO carry a boolean ``featured`` field, so the
   correct observable is client-side filtering by ``m["featured"]``.

3. ``get_event_markets(event_slug=...)`` calls ``/events/{slug}`` (path), which
   the wire rejects with ``{"type": "validation error", "error": "id is invalid"}``;
   the working route is ``/events?slug=<slug>`` (probed 200, event objects carry
   a ``markets`` array). The numeric ``/events/{id}`` path WORKS (probed 200)
   and stays supported.

Each xfail-strict test pins the DESIRED observable with a fake that models the
real wire (params ignored exactly as the wire ignores them), so only a correct
fix flips it (XPASS -> RED -> human flip, the established contract-suite
pattern of tests/test_gamma_clob_fields_contract.py,
tests/test_data_api_contract.py and tests/test_gamma_list_contract.py). The
live tests (``integration`` marker) pin the wire facts themselves and are
deselected from the offline suite.

Flip coupling: fixing these tools flips the params pins in
``tests/test_market_discovery_offline.py`` (:524/:529 category, :560/:566/:574
event endpoints, :605/:623 featured, :769-:794 sports/crypto) and the featured
probe in ``tests/test_market_discovery_utcnow_offline.py`` (:134-153) --
EXISTING tests are untouchable for agents, the flips belong to the human fix
(item 155).
"""

import httpx
import pytest

from polymarket_mcp.tools import market_discovery

GAMMA = "https://gamma-api.polymarket.com"

XI_SLUG = "xi-jinping-out-before-2027"
EVENT_WITH_MARKETS = {
    "id": "30828",
    "slug": XI_SLUG,
    "title": "Xi Jinping out before 2027?",
    "markets": [
        {"id": "559651", "question": "Xi Jinping out before 2027?", "slug": XI_SLUG}
    ],
}


def _market(mid, question, featured=False):
    return {
        "id": mid,
        "question": question,
        "slug": f"mk-{mid}",
        "featured": featured,
        # Wire-faithful: the /markets LIST response embeds events whose tags
        # are EMPTY, so client-side tag filtering cannot work on this payload.
        "events": [{"id": f"ev-{mid}", "tags": []}],
    }


MIXED = [
    _market("1", "Will Bitcoin hit $150k by December 31?", featured=True),
    _market("2", "Xi Jinping out before 2027?"),
    _market("3", "BTC whale buys 500 coins?", featured=True),
    _market("4", "Will BTC be legal tender in France?"),
    _market("5", "Will the Chiefs win the Super Bowl?"),
    _market("6", "Will Real Madrid win La Liga?"),
]

CRYPTO_ONLY = [MIXED[0], MIXED[2]]
SPORTS_ONLY = [MIXED[4], MIXED[5]]

TAG_BY_SLUG = {
    "crypto": {"id": "21", "label": "Crypto", "slug": "crypto"},
    "sports": {"id": "30", "label": "Sports", "slug": "sports"},
}
TAG_ID_RESPONSES = {"21": CRYPTO_ONLY, "30": SPORTS_ONLY}


class _NoopLimiter:
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


class _FakeGammaClient:
    """Models the REAL gamma wire: tag/tag_slug/featured params ignored,
    tag_id honored, /tags/slug/<slug> and /tags list resolve, /events?slug=
    works and /events/{numeric-id} works. Anything else fails loud."""

    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        self.calls.append({"url": url, "params": params})
        if "/tags/slug/" in url:
            tag = TAG_BY_SLUG.get(url.rsplit("/", 1)[-1])
            if tag is None:
                return _FakeResponse({"error": "not found"}, status_code=404)
            return _FakeResponse(tag)
        if url.endswith("/tags"):
            return _FakeResponse(list(TAG_BY_SLUG.values()))
        if url.endswith("/markets"):
            params = params or {}
            if params.get("tag_id"):
                canned = TAG_ID_RESPONSES.get(str(params["tag_id"]), [])
                return _FakeResponse(list(canned))
            # Wire-faithful: tag / tag_slug / featured params are IGNORED.
            return _FakeResponse(list(MIXED))
        if url.endswith("/events") and params and params.get("slug"):
            return _FakeResponse([dict(EVENT_WITH_MARKETS)])
        if "/events/" in url and url.rsplit("/", 1)[-1].isdigit():
            return _FakeResponse(dict(EVENT_WITH_MARKETS))
        raise AssertionError(f"unexpected fetch: {url} {params}")


def _install(monkeypatch):
    monkeypatch.setattr(market_discovery.httpx, "AsyncClient", _FakeGammaClient)
    monkeypatch.setattr(market_discovery, "get_rate_limiter", lambda: _NoopLimiter())
    return _FakeGammaClient()


@pytest.mark.xfail(
    strict=True,
    reason="the tag param is ignored by the wire; category filtering must use tag_id (item 155)",
)
async def test_filter_markets_by_category_returns_only_category(monkeypatch):
    _install(monkeypatch)
    result = await market_discovery.filter_markets_by_category("Crypto", limit=10)
    assert result, "crypto markets must be surfaced"
    leaked = [m for m in result if m["id"] not in {"1", "3"}]
    assert not leaked, f"non-crypto markets leaked through: {leaked}"


@pytest.mark.xfail(
    strict=True,
    reason="the tag param is ignored by the wire; sports filtering must use tag_id (item 155)",
)
async def test_sports_markets_returns_only_sports(monkeypatch):
    _install(monkeypatch)
    result = await market_discovery.get_sports_markets(limit=10)
    assert result, "sports markets must be surfaced"
    leaked = [m for m in result if m["id"] not in {"5", "6"}]
    assert not leaked, f"non-sports markets leaked through: {leaked}"


@pytest.mark.xfail(
    strict=True,
    reason="the tag param is ignored by the wire; crypto filtering must use tag_id (item 155)",
)
async def test_crypto_markets_with_symbol_returns_only_crypto_symbol(monkeypatch):
    _install(monkeypatch)
    result = await market_discovery.get_crypto_markets(symbol="BTC", limit=10)
    assert result, "crypto BTC markets must be surfaced"
    leaked = [m for m in result if m["id"] not in {"1", "3"}]
    assert not leaked, f"non-crypto markets leaked through: {leaked}"


@pytest.mark.xfail(
    strict=True,
    reason="the featured param is ignored by the wire; featured must be filtered client-side (item 155)",
)
async def test_featured_markets_returns_only_featured(monkeypatch):
    _install(monkeypatch)
    result = await market_discovery.get_featured_markets(limit=10)
    assert result, "featured markets must be surfaced"
    leaked = [m for m in result if not m.get("featured")]
    assert not leaked, f"non-featured markets leaked through: {leaked}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "get_event_markets(event_slug) hits /events/{slug} which the wire rejects; "
        "the working route is /events?slug= (item 155)"
    ),
)
async def test_event_markets_resolves_slug_via_query(monkeypatch):
    _install(monkeypatch)
    markets = await market_discovery.get_event_markets(event_slug=XI_SLUG)
    assert markets, "event markets must be surfaced"
    assert markets[0]["id"] == "559651"
    assert markets[0]["slug"] == XI_SLUG


async def _derive_listing(client):
    resp = await client.get(f"{GAMMA}/markets", params={"limit": 5})
    resp.raise_for_status()
    return resp.json()


@pytest.mark.integration
async def test_live_events_slug_query_returns_event_with_markets():
    async with httpx.AsyncClient(timeout=30.0) as client:
        listing = await _derive_listing(client)
        slug = listing[0]["slug"]
        resp = await client.get(f"{GAMMA}/events", params={"slug": slug})
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list) and body, body
        event = body[0]
        assert event.get("slug") == slug
        assert event.get("markets"), event


@pytest.mark.integration
async def test_live_events_path_rejects_slug():
    async with httpx.AsyncClient(timeout=30.0) as client:
        listing = await _derive_listing(client)
        slug = listing[0]["slug"]
        resp = await client.get(f"{GAMMA}/events/{slug}")
        assert resp.status_code >= 400


@pytest.mark.integration
async def test_live_featured_param_is_ignored():
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{GAMMA}/markets", params={"featured": "true", "limit": 20}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body, "listing must not be empty"
        not_featured = [m for m in body if not m.get("featured")]
        assert not_featured, (
            "the featured param filtered nothing: the wire ignores it (item 155)"
        )


@pytest.mark.integration
async def test_live_tag_param_differs_from_tag_id_filter():
    async with httpx.AsyncClient(timeout=30.0) as client:
        tagged = await client.get(f"{GAMMA}/markets", params={"tag": "Crypto", "limit": 3})
        by_id = await client.get(f"{GAMMA}/markets", params={"tag_id": "21", "limit": 3})
        assert tagged.status_code == 200 and by_id.status_code == 200
        first_tagged = tagged.json()[0]["id"] if tagged.json() else None
        first_by_id = by_id.json()[0]["id"] if by_id.json() else None
        assert first_tagged != first_by_id, (
            "tag=Crypto and tag_id=21 must differ: the tag param is ignored (item 155)"
        )


@pytest.mark.integration
async def test_live_tag_id_filters_and_bogus_returns_empty():
    async with httpx.AsyncClient(timeout=30.0) as client:
        bogus = await client.get(
            f"{GAMMA}/markets", params={"tag_id": "999999999", "limit": 3}
        )
        assert bogus.status_code == 200
        assert bogus.json() == [], bogus.json()
        real = await client.get(f"{GAMMA}/markets", params={"tag_id": "21", "limit": 3})
        assert real.status_code == 200
        assert real.json(), real.json()
