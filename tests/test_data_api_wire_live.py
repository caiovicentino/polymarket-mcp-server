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

import httpx
import pytest

pytest.importorskip("httpx")

TRADES_URL = "https://data-api.polymarket.com/trades"
POSITIONS_URL = "https://data-api.polymarket.com/positions"
ACTIVITY_URL = "https://data-api.polymarket.com/activity"


def _skip_on_transport(exc, label):
    """Network guard: infra failures SKIP (never fail the suite for infra)."""
    pytest.skip(f"{label} unreachable ({type(exc).__name__}: {exc})")


def _check_response(response, label):
    """Fail-closed response check: 5xx is an API-side outage (documented
    skip); any other non-200 is a live-contract violation (FAIL)."""
    if response.status_code >= 500:
        pytest.skip(f"{label}: live API outage (HTTP {response.status_code})")
    assert response.status_code == 200, f"{label}: expected HTTP 200, got {response.status_code}"


async def _harvest(client):
    """Derive a user address from the public trades feed (never hardcoded)."""
    try:
        resp = await client.get(TRADES_URL, params={"limit": 5})
    except (httpx.HTTPError, OSError) as exc:
        _skip_on_transport(exc, "data-api /trades")
    _check_response(resp, "data-api /trades")
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
        try:
            resp = await client.get(
                ACTIVITY_URL, params={"user": user, "limit": 10, "start": future}
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "data-api /activity")
        _check_response(resp, "data-api /activity")
        assert resp.json() == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wire_trades_ignores_all_window_params():
    """/trades has NO window support: start AND start_time are both ignored."""
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        future = int(time.time()) + 30 * 86400
        for param in ("start", "start_time"):
            try:
                resp = await client.get(TRADES_URL, params={"limit": 10, param: future})
            except (httpx.HTTPError, OSError) as exc:
                _skip_on_transport(exc, f"data-api /trades ({param})")
            _check_response(resp, f"data-api /trades ({param})")
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
        try:
            resp = await client.get(
                ACTIVITY_URL, params={"user": user, "limit": 5, "type": "trades"}
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "data-api /activity type lowercase")
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
        try:
            resp = await client.get(
                ACTIVITY_URL, params={"user": user, "limit": 20, "type": "TRADE"}
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "data-api /activity type")
        _check_response(resp, "data-api /activity type")
        for item in resp.json():
            assert item.get("type") == "TRADE"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wire_positions_market_filter_honored():
    """`market=<valid-format cid>` filters /positions (malformed cids dropped)."""
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.get(TRADES_URL, params={"limit": 5})
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "data-api /trades")
        _check_response(resp, "data-api /trades")
        trades = resp.json()
        assert isinstance(trades, list) and trades, "public trades feed returned no trades"
        user = trades[0]["proxyWallet"]
        cid = trades[0]["conditionId"]

        try:
            filtered = await client.get(
                POSITIONS_URL, params={"user": user, "market": cid}
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "data-api /positions market")
        _check_response(filtered, "data-api /positions market")
        for position in filtered.json():
            assert position.get("conditionId") == cid

        # Malformed cid: the wire DROPS the param (200, unfiltered payload).
        try:
            malformed = await client.get(
                POSITIONS_URL, params={"user": user, "market": "0xdeadbeef"}
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "data-api /positions market malformed")
        _check_response(malformed, "data-api /positions market malformed")
        assert isinstance(malformed.json(), list)


@pytest.mark.asyncio
async def test_transport_guard_skips_on_connect_error(monkeypatch):
    """The network guard is a SKIP, not a FAIL (L-0026): with the transport
    dead, the live test is skipped for infra reasons, never failed."""
    async def boom(self, *args, **kwargs):
        raise httpx.ConnectError("simulated transport failure")

    monkeypatch.setattr(httpx.AsyncClient, "get", boom)
    name = None
    try:
        await test_wire_activity_honors_start_epoch()
    except BaseException as exc:
        name = type(exc).__name__
    assert name in ("Skipped", "Skip"), (
        f"expected the live test to SKIP on transport failure, got {name}"
    )


@pytest.mark.asyncio
async def test_transport_guard_skips_on_direct_call_site(monkeypatch):
    """A transport failure at a DIRECT call site (not only the shared
    helper) also skips: the guard wraps every live call site."""
    calls = {"n": 0}

    class _FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return [{"proxyWallet": "0xp", "conditionId": "0xc"}]

    async def boom(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise httpx.ConnectError("simulated transport failure")
        return _FakeResp()

    monkeypatch.setattr(httpx.AsyncClient, "get", boom)
    name = None
    try:
        await test_wire_positions_market_filter_honored()
    except BaseException as exc:
        name = type(exc).__name__
    assert name in ("Skipped", "Skip"), (
        f"expected the live test to SKIP on direct-site transport failure, got {name}"
    )
