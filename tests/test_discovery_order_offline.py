"""Offline + live contract for the server-side ORDER of get_trending_markets.

Wire truth (probed 2026-09-20, farm/T-0460 preflight):
- gamma /markets WITHOUT ``order`` returns rows in id-ascending order
  (559651/559652/559653 probed), so the tool's first page is an arbitrary
  subsample and "trending" returned the top of that sample -- never the true
  top by volume for the requested timeframe.
- ``order=volume1wk&ascending=false`` is HONORED server-side (descending:
  7.15M/6.84M/2.95M probed); ``order=volume24hr&ascending=false`` likewise
  (2.74M/2.03M/1.32M probed).

The fix (farm/T-0460) resolves the sort key BEFORE the fetch and carries
``order`` + ``ascending=false`` in the request params. The client-side sort
(farm/T-0455) is retained as defense -- it is identity on the ordered sample.
"""
import httpx
import pytest

from polymarket_mcp.tools import market_discovery


def install_fetch_stub(monkeypatch, payload=None):
    """Stub market_discovery._fetch_gamma_markets with a call recorder."""
    calls = []

    async def stub(endpoint="/markets", params=None, limit=None):
        calls.append({"endpoint": endpoint, "params": params, "limit": limit})
        return payload if payload is not None else []

    monkeypatch.setattr(market_discovery, "_fetch_gamma_markets", stub)
    return calls


@pytest.mark.asyncio
async def test_trending_params_carry_server_order_default_24h(monkeypatch):
    calls = install_fetch_stub(monkeypatch, payload=[])
    await market_discovery.get_trending_markets(limit=5)

    params = calls[0]["params"]
    assert params["order"] == "volume24hr", f"missing server order: {params!r}"
    assert params["ascending"] == "false", f"missing descending: {params!r}"
    assert params["active"] == "true"
    assert params["closed"] == "false"


@pytest.mark.asyncio
async def test_trending_order_follows_timeframe_map(monkeypatch):
    calls = install_fetch_stub(monkeypatch, payload=[])
    await market_discovery.get_trending_markets(timeframe="7d", limit=5)
    await market_discovery.get_trending_markets(timeframe="30d", limit=5)

    assert calls[0]["params"]["order"] == "volume1wk"
    assert calls[1]["params"]["order"] == "volume1mo"
    assert calls[0]["params"]["ascending"] == "false"
    assert calls[1]["params"]["ascending"] == "false"


def _skip_on_transport(exc, label):
    """Network guard: infra failures SKIP (never fail the suite for infra)."""
    pytest.skip(f"{label} unreachable ({type(exc).__name__}: {exc})")


def _check_response(response, label):
    """Fail-closed response check: 5xx is an API-side outage (skip), other
    non-200 is a live-contract violation (FAIL)."""
    if response.status_code >= 500:
        pytest.skip(f"{label} outage ({response.status_code})")
    assert response.status_code == 200, f"{label} returned {response.status_code}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_gamma_order_ascending_false_is_descending():
    """Pins the wire truth the fix relies on: ordered fetch is descending."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.get(
                "https://gamma-api.polymarket.com/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": 3,
                    "order": "volume1wk",
                    "ascending": "false",
                },
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "gamma /markets ordered")
    _check_response(response, "gamma /markets ordered")
    rows = response.json()
    assert isinstance(rows, list) and len(rows) >= 2
    vols = [float(m.get("volume1wk") or 0) for m in rows]
    assert vols == sorted(vols, reverse=True), f"expected desc, got {vols}"


@pytest.mark.asyncio
async def test_closing_soon_params_carry_server_window(monkeypatch):
    calls = install_fetch_stub(monkeypatch, payload=[])
    await market_discovery.get_closing_soon_markets(hours=24, limit=10)

    params = calls[0]["params"]
    assert params["order"] == "endDate", f"missing endDate order: {params!r}"
    assert params["ascending"] == "true", f"missing soonest-first: {params!r}"
    assert params["active"] == "true" and params["closed"] == "false"
    from datetime import datetime

    floor = datetime.fromisoformat(params["end_date_min"].replace("Z", "+00:00"))
    ceil = datetime.fromisoformat(params["end_date_max"].replace("Z", "+00:00"))
    assert abs((ceil - floor).total_seconds() - 24 * 3600) <= 2
    assert params["end_date_min"].endswith("Z")
    assert params["end_date_max"].endswith("Z")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_gamma_closing_window_returns_soonest():
    """Pins the wire truth the fix relies on: the bounded window query
    returns markets closing within the window, soonest first, ascending."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    ceil = (now + timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    floor = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.get(
                "https://gamma-api.polymarket.com/markets",
                params={
                    "active": "true", "closed": "false", "limit": 5,
                    "end_date_min": floor, "end_date_max": ceil,
                    "order": "endDate", "ascending": "true",
                },
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "gamma /markets closing window")
    _check_response(response, "gamma /markets closing window")
    rows = response.json()
    assert isinstance(rows, list) and rows
    dates = [m["endDate"] for m in rows]
    parsed = [datetime.fromisoformat(d.replace("Z", "+00:00")) for d in dates]
    assert parsed == sorted(parsed), f"expected ascending endDate, got {dates}"
    assert parsed[0] >= now - timedelta(seconds=30), "floor leaked past dates"
    assert parsed[-1] <= now + timedelta(hours=48, seconds=30), "ceiling leaked"
