"""Wire-contract suite for the market_analysis tool gaps (REQUER-HUMANO item 154).

Three user-facing gaps proven first-hand against the live APIs (curator probes,
increment 60, 2026-09-18):

1. ``get_price_history`` is a hard stub: it returns ``[{"error": ...}]`` while
   claiming "Polymarket doesn't have a public historical price API" -- but
   ``https://clob.polymarket.com/prices-history`` IS public and returns
   ``{"history": [{"t": <epoch>, "p": <price>}, ...]}``. Wire contract (probed):
   the ``market`` param (token id) is mandatory, a time component is mandatory
   (``interval`` like ``1d``/``1h`` or ``startTs``/``endTs``), and ``fidelity``
   is minutes (probed 5/60/1440 all accepted).

2. ``get_market_holders`` is a hard stub claiming "requires authenticated
   access" -- but ``https://data-api.polymarket.com/holders?market=<conditionId>``
   IS public and returns ``[{"token": ..., "holders": [{"proxyWallet", "amount",
   "pseudonym", "outcomeIndex", ...}]}]``. The numeric gamma id is NOT accepted
   (``required query param 'market' not provided``), so the tool must resolve
   the conditionId first -- gamma market objects carry ``conditionId``.

3. ``get_market_details(slug=...)`` calls ``/markets/{slug}`` (path), which the
   wire rejects with ``{"type": "validation error", "error": "id is invalid"}``;
   the working wire route is ``/markets?slug=<slug>`` (probed 200). The
   ``condition_id`` branch already works (probed 200) and is pinned green.

Each xfail-strict test pins the DESIRED observable with a fake that models the
real wire, so only a correct fix flips it (XPASS -> RED -> human flip, the
established contract-suite pattern of tests/test_gamma_clob_fields_contract.py,
tests/test_data_api_contract.py and tests/test_gamma_list_contract.py). The
live tests (``integration`` marker) pin the wire facts themselves and are
deselected from the offline suite.

Flip coupling: fixing the stubs flips the placeholder pins in
``tests/test_market_analysis_gaps_offline.py`` (:539/:558/:573/:582/:589) and
the slug-endpoint pin (:449) -- EXISTING tests are untouchable for agents, the
flips belong to the human fix (item 154).
"""

import json

import httpx
import pytest

from polymarket_mcp.tools import market_analysis

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

# Real wire shapes (curator probes, increment 60).
MARKET_XI = {
    "id": "559651",
    "question": "Xi Jinping out before 2027?",
    "slug": "xi-jinping-out-before-2027",
    "conditionId": "0xa467b14d51f01b957109d9cbb1d6c124fab2a089d52ed8f471d23c2812e743b7",
}
PRICES_WIRE = {"history": [{"t": 1789500013, "p": 0.615}, {"t": 1789506016, "p": 0.605}]}
HOLDERS_WIRE = [
    {
        "token": "32338220190071351435772801779725302244575775216413325951443816017994629993401",
        "holders": [
            {
                "proxyWallet": "0x6806d2ab8efb9c41baa28c72e44fdfc4b3293a05",
                "asset": "32338220190071351435772801779725302244575775216413325951443816017994629993401",
                "amount": 644533.794669,
                "pseudonym": "Icky-Puma",
                "outcomeIndex": 0,
            }
        ],
    }
]


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


@pytest.mark.xfail(
    strict=True,
    reason="get_price_history is a stub; CLOB /prices-history is public and works (item 154)",
)
async def test_get_price_history_surfaces_history_points(monkeypatch):
    calls = []

    async def fake_fetch(endpoint, params=None):
        calls.append({"endpoint": endpoint, "params": params})
        # The real wire: market is mandatory, a time component is mandatory.
        assert endpoint == "/prices-history", endpoint
        assert params.get("market") == "tok", params
        assert "startTs" in params or "interval" in params, params
        return dict(PRICES_WIRE)

    monkeypatch.setattr(market_analysis, "_fetch_clob_api", fake_fetch)
    monkeypatch.setattr(market_analysis, "get_rate_limiter", lambda: _NoopLimiter())

    explicit = await market_analysis.get_price_history(
        token_id="tok", start_date="2026-09-01", end_date="2026-09-08", resolution="1h"
    )
    assert explicit, "explicit-range history must not be empty"
    assert not any(isinstance(p, dict) and "error" in p for p in explicit)
    assert "0.615" in json.dumps(explicit)

    default_range = await market_analysis.get_price_history(token_id="tok")
    assert default_range, "default-range history must not be empty"
    assert not any(isinstance(p, dict) and "error" in p for p in default_range)
    assert len(calls) == 2, calls


@pytest.mark.xfail(
    strict=True,
    reason="get_market_holders is a stub; data-api /holders is public and works (item 154)",
)
async def test_get_market_holders_surfaces_holders(monkeypatch):
    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            self.calls.append({"url": url, "params": params})
            if "/holders" in url:
                # The real wire: market= must be the conditionId (0x...).
                assert isinstance(params, dict) and params.get("market"), params
                assert str(params["market"]).startswith("0x"), params
                return _FakeResponse(HOLDERS_WIRE)
            if "gamma-api.polymarket.com" in url:
                return _FakeResponse(MARKET_XI)
            raise AssertionError(f"unexpected fetch: {url} {params}")

    monkeypatch.setattr(market_analysis.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(market_analysis, "get_rate_limiter", lambda: _NoopLimiter())

    holders = await market_analysis.get_market_holders(market_id="559651", limit=5)
    assert holders, "holders must not be empty"
    assert not any(isinstance(x, dict) and "error" in x for x in holders)
    assert "0x6806d2ab8efb9c41baa28c72e44fdfc4b3293a05" in json.dumps(holders)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "get_market_details(slug) hits /markets/{slug} which the wire rejects; "
        "the working route is /markets?slug= (item 154)"
    ),
)
async def test_get_market_details_slug_resolves_via_query(monkeypatch):
    async def fake_gamma(endpoint, params=None):
        if endpoint == "/markets" and params and params.get("slug") == MARKET_XI["slug"]:
            return [dict(MARKET_XI)]
        raise AssertionError(
            f"slug must resolve via /markets?slug=... (got {endpoint} {params})"
        )

    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", fake_gamma)
    monkeypatch.setattr(market_analysis, "get_rate_limiter", lambda: _NoopLimiter())

    market = await market_analysis.get_market_details(slug=MARKET_XI["slug"])
    assert market.get("slug") == MARKET_XI["slug"]


async def _derive_listing(client):
    resp = await client.get(f"{GAMMA}/markets", params={"limit": 8})
    resp.raise_for_status()
    return resp.json()


@pytest.mark.integration
async def test_live_prices_history_wire_returns_points():
    async with httpx.AsyncClient(timeout=30.0) as client:
        listing = await _derive_listing(client)
        token = None
        for entry in listing:
            raw = entry.get("clobTokenIds")
            if not raw:
                continue
            ids = json.loads(raw) if isinstance(raw, str) else raw
            if ids:
                token = ids[0]
                break
        assert token, "live listing must expose clobTokenIds"
        resp = await client.get(
            f"{CLOB}/prices-history", params={"market": token, "interval": "1d"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("history"), body
        point = body["history"][0]
        assert "t" in point and "p" in point, point


@pytest.mark.integration
async def test_live_prices_history_requires_time_component():
    async with httpx.AsyncClient(timeout=30.0) as client:
        listing = await _derive_listing(client)
        token = None
        for entry in listing:
            raw = entry.get("clobTokenIds")
            if not raw:
                continue
            ids = json.loads(raw) if isinstance(raw, str) else raw
            if ids:
                token = ids[0]
                break
        assert token
        resp = await client.get(f"{CLOB}/prices-history", params={"market": token})
        assert resp.status_code >= 400 or "error" in resp.json()


@pytest.mark.integration
async def test_live_holders_wire_returns_holders():
    async with httpx.AsyncClient(timeout=30.0) as client:
        listing = await _derive_listing(client)
        condition_id = None
        for entry in listing:
            if entry.get("conditionId"):
                condition_id = entry["conditionId"]
                break
        assert condition_id, "live listing must expose conditionId"
        resp = await client.get(
            f"{DATA_API}/holders", params={"market": condition_id, "limit": 3}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list) and body, body
        first = body[0]
        assert "holders" in first and first["holders"], first
        holder = first["holders"][0]
        assert "proxyWallet" in holder and "amount" in holder, holder


@pytest.mark.integration
async def test_live_slug_query_works_and_path_rejects():
    async with httpx.AsyncClient(timeout=30.0) as client:
        listing = await _derive_listing(client)
        slug = listing[0]["slug"]
        ok = await client.get(f"{GAMMA}/markets", params={"slug": slug})
        assert ok.status_code == 200
        body = ok.json()
        assert isinstance(body, list) and body and body[0]["slug"] == slug
        bad = await client.get(f"{GAMMA}/markets/{slug}")
        assert bad.status_code >= 400


@pytest.mark.integration
async def test_live_condition_id_query_works():
    async with httpx.AsyncClient(timeout=30.0) as client:
        listing = await _derive_listing(client)
        condition_id = None
        for entry in listing:
            if entry.get("conditionId"):
                condition_id = entry["conditionId"]
                break
        assert condition_id
        resp = await client.get(
            f"{GAMMA}/markets", params={"condition_id": condition_id}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body and body[0]["conditionId"] == condition_id
