"""Contract suite for the REAL gamma /markets LIST endpoints
(get_trending_markets, get_featured_markets, get_closing_soon_markets).

Findings proven live first-hand (curator preflight 2026-09-17; gamma-api
stateless public endpoints):

1. Objects in the /markets LIST have ``volume1wk``/``volume1mo``/
   ``volume24hr``/``volumeNum`` -- ``volume7d``/``volume30d`` DO NOT EXIST
   (same family as REQUER-HUMANO item 138 V10, which pinned the
   single-market object; THIS suite pins the LIST consumers).
   Consequence: get_trending_markets builds
   ``volume_key_map = {"24h": "volume24hr", "7d": "volume7d",
   "30d": "volume30d"}`` (:232-236) -- for timeframe 7d/30d every market
   falls back to 0.0 -> the sort is a NO-OP -> the "trending" output is in
   ARBITRARY (API) order (proven live: 7d volumes came back
   287k/459k/76k/19k/85k -- clearly unsorted).
2. ``endDate`` on the wire is a Z-suffixed ISO string
   ("2027-01-01T04:59:00Z"); ``end_date_iso`` does not exist (the code
   checks both keys -- harmless).
3. get_closing_soon_markets parses ``endDate`` with
   ``datetime.fromisoformat(end_date.replace("Z", "+00:00"))`` -> AWARE
   datetime, then compares with a NAIVE cutoff -> TypeError
   ("can't compare offset-naive and offset-aware datetimes") caught by the
   per-market handler -> EVERY real market skipped -> the tool returns []
   even with hours=720 (proven live). The sibling get_trending_markets
   does it CORRECTLY (``.replace(tzinfo=None)``) -- copy-paste divergence.
4. GET /markets?featured=true&active=true&closed=false -> 200 (the
   ``featured`` query param is accepted by the API).

This suite pins the REAL contract as xfail(strict=True) for the two bugs
(the flip contract for the human fix -- precedent R3/T-0212) plus live
integration greens pinning the wire fields. Known flip targets when the
fixes land: tests/test_market_discovery_offline.py :473 (fixture feeds the
NON-EXISTENT ``volume7d`` key -- a rename of the volume_key_map makes the
sort tie) and :733 (pins the Z-divergence as OBSERVED -- the fix makes
closing_soon include Z dates).
"""

import pytest

from polymarket_mcp.tools import market_discovery


def market(volume1wk, volume1mo, m_id="m", volume24hr=100):
    """Real-shaped /markets element: volume1wk/1mo/24hr, NO volume7d/30d."""
    return {
        "id": m_id,
        "volume1wk": volume1wk,
        "volume1mo": volume1mo,
        "volume24hr": volume24hr,
        "volumeNum": volume24hr,
    }


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


# --- Offline xfail-strict pins (the flip contract) -------------------------

@pytest.mark.xfail(reason="get_trending_markets sorts by volume7d/"
                          "volume30d which DO NOT EXIST in the gamma /markets "
                          "list (real: volume1wk/1mo) -- sort is a no-op "
                          "(REQUER-HUMANO item 141)", strict=True)
@pytest.mark.asyncio
async def test_trending_7d_sorts_by_real_volume_field(monkeypatch):
    """timeframe=7d must sort by the REAL wire field volume1wk (desc)."""
    install_fetch_stub(
        monkeypatch,
        payload=[
            market(volume1wk=100, volume1mo=1000, m_id="a"),
            market(volume1wk=300, volume1mo=100, m_id="b"),
            market(volume1wk=200, volume1mo=1000, m_id="c"),
        ],
    )

    result = await market_discovery.get_trending_markets(timeframe="7d", limit=3)

    assert [m["id"] for m in result] == ["b", "c", "a"]


@pytest.mark.xfail(reason="get_trending_markets sorts by volume7d/"
                          "volume30d which DO NOT EXIST in the gamma /markets "
                          "list (real: volume1wk/1mo) -- sort is a no-op "
                          "(REQUER-HUMANO item 141)", strict=True)
@pytest.mark.asyncio
async def test_trending_30d_sorts_by_real_volume_field(monkeypatch):
    """timeframe=30d must sort by the REAL wire field volume1mo (desc)."""
    install_fetch_stub(
        monkeypatch,
        payload=[
            market(volume1wk=1000, volume1mo=10, m_id="a"),
            market(volume1wk=1, volume1mo=500, m_id="b"),
            market(volume1wk=10, volume1mo=100, m_id="c"),
        ],
    )

    result = await market_discovery.get_trending_markets(timeframe="30d", limit=3)

    assert [m["id"] for m in result] == ["b", "c", "a"]


@pytest.mark.xfail(reason="get_closing_soon_markets parses the Z-suffixed "
                          "endDate AWARE and compares against a NAIVE cutoff "
                          "-> TypeError -> every real market skipped "
                          "(REQUER-HUMANO item 141)", strict=True)
@pytest.mark.asyncio
async def test_closing_soon_includes_z_suffixed_end_date(monkeypatch):
    """A REAL endDate ('...Z') within the window must be INCLUDED.

    Today the aware-vs-naive comparison raises, the per-market except
    logs a warning and skips the market -> [] (proven live: a wallet-era
    probe with hours=720 returned 0 markets).
    """
    from datetime import datetime, timedelta

    z_date = (
        (datetime.utcnow() + timedelta(hours=2)).replace(microsecond=0).isoformat() + "Z"
    )
    install_fetch_stub(monkeypatch, payload=[{"id": "m", "endDate": z_date}])

    result = await market_discovery.get_closing_soon_markets(hours=24, limit=10)

    assert [m["id"] for m in result] == ["m"]


# ---------------------------------------------------------------------------
# Live contract (integration; deselected by the offline suite run)
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_markets_list_field_contract():
    """Prove the real /markets LIST field contract once, live."""
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            "https://gamma-api.polymarket.com/markets",
            params={"active": "true", "closed": "false", "limit": 3},
        )
        response.raise_for_status()
        markets = response.json()
    assert isinstance(markets, list) and markets
    for m in markets:
        for field in ("volume1wk", "volume1mo", "volume24hr", "volumeNum"):
            assert field in m, f"gamma market missing {field}"
        for absent in ("volume7d", "volume30d", "end_date_iso"):
            assert absent not in m, f"gamma market unexpectedly has {absent}"
        if m.get("endDate"):
            assert isinstance(m["endDate"], str)
            assert m["endDate"].endswith("Z")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_featured_query_accepted():
    """The featured=true query param is accepted (200) by gamma /markets."""
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            "https://gamma-api.polymarket.com/markets",
            params={"featured": "true", "active": "true", "closed": "false", "limit": 2},
        )
    assert response.status_code == 200
    assert isinstance(response.json(), list)
