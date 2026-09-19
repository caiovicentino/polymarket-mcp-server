"""Live wire-contract suite for the Data-API window/type/segment params.

PROVES (continuously, against the real API) the wire contracts that the
offline flip-contract suite pins from fakes
(test_data_api_date_params_contract.py, REQUER-HUMANO item 183):

- `/activity` HONORS ``start`` (epoch SECONDS) -- a future ``start`` filters
  the feed EMPTY (probed live 2026-09-18: 0 events); ``start_time`` is
  IGNORED (the same future value returns the unfiltered feed).
- `/trades` has NO window support AT ALL: ``start`` and ``start_time`` are
  both ignored -- the feed always returns the latest N trades (probed: the
  same latest trades for bare/future-start/future-start_time). This is why
  portfolio.py's /trades-backed windows (get_pnl_summary, get_trade_history)
  are silently ALL-TIME and need CLIENT-SIDE filtering (item 183).
- `/activity` ``type`` rejects lowercase values with HTTP 400 ("invalid
  activity filter type X. must be: [...]", probed verbatim) and accepts the
  uppercase vocabulary (``TRADE`` -> 200 with type==TRADE items).
- `/positions` honors ``market`` (condition-id filter) for VALID-FORMAT cids
  (probed: own cid -> the position; valid non-owned cid -> empty). A
  MALFORMED cid is DROPPED by the wire (unfiltered results, probed:
  0xdeadbeef-like -> the plain positions payload) -- registered quirk, NOT a
  code bug.

House rules: addresses are harvested from the public /trades feed (NUNCA
hardcoded); shape assertions only (no exact counts -- live data moves);
integration-marked so the canonical offline suite deselects these.
"""

import time

import pytest

pytest.importorskip("httpx")

TRADES_URL = "https://data-api.polymarket.com/trades"
POSITIONS_URL = "https://data-api.polymarket.com/positions"
ACTIVITY_URL = "https://data-api.polymarket.com/activity"


async def _harvest(client):
    """Derive a user address from the public trades feed (never hardcoded)."""
    resp = await client.get(TRADES_URL, params={"limit": 5})
    assert resp.status_code == 200, f"feed /trades failed: {resp.status_code}"
    trades = resp.json()
    assert isinstance(trades, list) and trades, "public trades feed returned no trades"
    return trades[0]["proxyWallet"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wire_activity_honors_start_epoch():
    """A future `start` (epoch seconds) filters the /activity feed EMPTY."""
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        user = await _harvest(client)
        future = int(time.time()) + 30 * 86400
        resp = await client.get(
            ACTIVITY_URL, params={"user": user, "limit": 10, "start": future}
        )
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wire_trades_ignores_all_window_params():
    """/trades has NO window support: start AND start_time are both ignored."""
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        future = int(time.time()) + 30 * 86400
        for param in ("start", "start_time"):
            resp = await client.get(TRADES_URL, params={"limit": 10, param: future})
            assert resp.status_code == 200
            trades = resp.json()
            assert isinstance(trades, list) and trades, (
                f"wire started honoring {param} on /trades -- re-derive "
                "item 183 (client-side windowing may be obsolete)"
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wire_activity_rejects_lowercase_type():
    """/activity rejects lowercase type with 400 (the wire vocabulary)."""
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        user = await _harvest(client)
        resp = await client.get(
            ACTIVITY_URL, params={"user": user, "limit": 5, "type": "trades"}
        )
        assert resp.status_code == 400, (
            f"wire accepted lowercase type (got {resp.status_code}) -- "
            "re-derive the tool fix (REQUER-HUMANO item 183)"
        )
        assert "must be" in resp.text  # the wire's error message shape


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wire_activity_accepts_uppercase_type():
    """/activity accepts type=TRADE (200; items all type=='TRADE')."""
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        user = await _harvest(client)
        resp = await client.get(
            ACTIVITY_URL, params={"user": user, "limit": 20, "type": "TRADE"}
        )
        assert resp.status_code == 200
        for item in resp.json():
            assert item.get("type") == "TRADE"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wire_positions_market_filter_honored():
    """`market=<valid-format cid>` filters /positions (malformed cids dropped)."""
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(TRADES_URL, params={"limit": 5})
        assert resp.status_code == 200
        trades = resp.json()
        assert isinstance(trades, list) and trades, "public trades feed returned no trades"
        user = trades[0]["proxyWallet"]
        cid = trades[0]["conditionId"]

        filtered = await client.get(
            POSITIONS_URL, params={"user": user, "market": cid}
        )
        assert filtered.status_code == 200
        for position in filtered.json():
            assert position.get("conditionId") == cid

        # Malformed cid: the wire DROPS the param (200, unfiltered payload).
        malformed = await client.get(
            POSITIONS_URL, params={"user": user, "market": "0xdeadbeef"}
        )
        assert malformed.status_code == 200
        assert isinstance(malformed.json(), list)
