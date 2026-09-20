"""Offline flip-contract suite for the Data-API window/type/side params.

Restores the lost T-0302 contract (the item-183 prescribed flip script --
the suite was prescribed in REQUER-HUMANO item 183 but never landed in the
clone; ``git log --all -- tests/test_data_api_date_params_contract.py``
holds only the curator's sim preflight, proven 1st hand on 2026-09-19) and
adds the NEW wire truth probed live on 2026-09-19:

- On the USER-filtered path, ``/trades`` HONORS ``start``/``end`` (probed:
  start=future -> 0 rows; start=mid-history -> rows with min_ts >= start;
  end=old -> rows with max_ts <= end). The 2026-09-18 probes that
  motivated the client-side-filter design (REQUER-HUMANO item 183
  CORRECTION) hit the GLOBAL no-user feed, where ``start`` is indeed
  ignored (pinned by tests/test_data_api_wire_live.py). The tools ALWAYS
  send ``user``, so the server-side window is available to them -- the
  item-183 fix design may use it for get_trade_history (render-only) but
  NOT for get_pnl_summary (the FIFO realized-P&L needs the pre-window
  history to match buys/sells; a server-side window would truncate the
  match set and corrupt the P&L math -- keep the client-side filter there).
- ``/trades`` (user path) HONORS ``side`` (probed: side=SELL -> all SELL;
  side=BUY -> all BUY; side=both -> HTTP 400). get_trade_history filters
  client-side today.
- ``/activity`` ``type`` is UPPERCASE-only (probed verbatim: lowercase ->
  ``{"error": "invalid activity filter type TRADES. must be: [TRADE SPLIT
  MERGE REDEEM REWARD CONVERSION MIGRATION DEPOSIT WITHDRAWAL YIELD
  MAKER_REBATE TAKER_REBATE REFERRAL_REWARD]"}``; ``TRADE`` -> 200 TRADE
  rows). get_activity_log sends the tool's lowercase enum today.
- ``start_time``/``end_time`` are IGNORED by the wire on BOTH endpoints
  (the wire vocabulary is ``start``/``end``, epoch SECONDS).

The 4 xfail-strict tests pin the POST-FIX behavior (REQUER-HUMANO item 183
flips -- which also flips the stale pins
tests/test_portfolio_analysis_offline.py:275-284 and :345 and
tests/test_portfolio_positions_offline.py:578-582): they FAIL today (RED
pre-fix, proven by the curator preflight) and XPASS -> RED when the fix
lands, forcing the flip in the SAME change (L-0073).

The 3 live tests (integration-marked, deselected by the canonical offline
selection) pin the wire truth as a drift detector for the fix window.

House rules: addresses are harvested from the public /trades feed (NUNCA
hardcoded); the offline fakes emulate the OBSERVED wire semantics (window
on ``start``/``end``, ignore the snake params, UPPERCASE type vocabulary).
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from polymarket_mcp.tools import portfolio

DATA_API = "https://data-api.polymarket.com"

UPPER_ERROR = (
    "invalid activity filter type TRADES. must be: [TRADE SPLIT MERGE REDEEM "
    "REWARD CONVERSION MIGRATION DEPOSIT WITHDRAWAL YIELD MAKER_REBATE "
    "TAKER_REBATE REFERRAL_REWARD]"
)


class _FakeResponse:
    def __init__(self, status_code: int, payload, url: str) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)
        self.url = url

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", self.url)
            raise httpx.HTTPStatusError(
                f"{self.status_code} Client Error for {self.url}",
                request=request,
                response=httpx.Response(
                    self.status_code, request=request, text=self.text
                ),
            )


class FakeDataApi:
    """Records (url, params) and serves the OBSERVED wire semantics."""

    def __init__(self) -> None:
        self.trades = []
        self.activity = []
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def get(self, url: str, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        params = dict(params or {})
        start = params.get("start")
        end = params.get("end")
        limit = int(params.get("limit") or 100)

        if url == f"{DATA_API}/trades":
            rows = list(self.trades)
            if params.get("market"):
                rows = [r for r in rows if r.get("conditionId") == params["market"]]
            # `side` is honored (probed 2026-09-19); `start_time`/`end_time`
            # are IGNORED by the wire (the code's snake params).
            side = params.get("side")
            if side:
                rows = [r for r in rows if r.get("side") == side]
            if start is not None:
                rows = [r for r in rows if r.get("timestamp", 0) >= int(start)]
            if end is not None:
                rows = [r for r in rows if r.get("timestamp", 0) <= int(end)]
            return _FakeResponse(200, rows[:limit], url)

        if url == f"{DATA_API}/activity":
            # type is UPPERCASE-only on the wire (probed verbatim).
            raw_type = params.get("type")
            if raw_type is not None and raw_type != raw_type.upper():
                return _FakeResponse(400, {"error": UPPER_ERROR}, url)
            rows = list(self.activity)
            if raw_type:
                rows = [r for r in rows if r.get("type") == raw_type]
            if start is not None:
                rows = [r for r in rows if r.get("timestamp", 0) >= int(start)]
            if end is not None:
                rows = [r for r in rows if r.get("timestamp", 0) <= int(end)]
            return _FakeResponse(200, rows[:limit], url)

        return _FakeResponse(200, [], url)


class FakeConfig:
    POLYGON_ADDRESS = "0x" + "a" * 40


class FakeRateLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def acquire(self, category) -> None:
        self.calls += 1


@pytest.fixture
def fake_api(monkeypatch):
    api = FakeDataApi()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: api)
    # NOTE (L-0142/L-0250b adaptation, declared vs the sim/c82-preflight
    # reference f9cdf30): the modules' tools receive the rate limiter as a
    # per-call PARAMETER (portfolio.py never imports get_rate_limiter), so
    # the reference suite's ``monkeypatch.setattr(portfolio,
    # "get_rate_limiter", ...)`` line crashes at fixture setup on the pure
    # main (AttributeError) and the strict xfails would be consumed
    # green-vacuously (L-0260b). The FakeRateLimiter is injected through the
    # real seam (the tool call argument) instead; the singleton is never
    # touched (0 acquires from the module seam).
    return api


def _trade(ts: int, side: str, price: float, size: float, cid: str = "0xdeadbeef"):
    return {
        "proxyWallet": "0x1",
        "timestamp": ts,
        "side": side,
        "price": price,
        "size": size,
        "conditionId": cid,
        "id": f"t-{ts}-{side}",
        "market_question": "Question?",
        "outcome": "Yes",
        "fee": 0.0,
    }


# ---------------------------------------------------------------------------
# Offline xfail-strict pins (the item-183 flip script)
# ---------------------------------------------------------------------------
@pytest.mark.xfail(
    reason="get_trade_history sends start_time/end_time -- the wire ignores "
    "them on BOTH paths; today the window is silently ALL-TIME "
    "(REQUER-HUMANO item 183 (B))",
    strict=True,
)
@pytest.mark.asyncio
async def test_trade_history_window_filters_rows_today_all_time(fake_api):
    """Post-fix: only the in-window trades are rendered."""
    now = int(datetime.now(timezone.utc).timestamp())
    fake_api.trades = [
        _trade(now - 3600, "BUY", 0.5, 10.0),
        _trade(now - 48 * 3600, "SELL", 0.75, 4.0),
    ]

    result = await portfolio.get_trade_history(
        None,
        FakeRateLimiter(),
        FakeConfig(),
        start_date=(datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(),
        end_date=datetime.now(timezone.utc).isoformat(),
    )

    text = result[0].text
    assert "Trade History (1 trades)" in text, (
        "the out-of-window trade must be excluded after the item-183 fix"
    )
    assert "0.7500" not in text, "the out-of-window SELL must not be rendered"


@pytest.mark.xfail(
    reason="get_pnl_summary sends start_time -- the wire ignores it; realized "
    "P&L is computed over ALL-TIME trades today (REQUER-HUMANO item 183 (B); "
    "fix = client-side filter BEFORE the FIFO, NOT a server-side window: the "
    "FIFO needs the pre-window history to match)",
    strict=True,
)
@pytest.mark.asyncio
async def test_pnl_summary_realized_pnl_is_window_scoped(fake_api):
    """Post-fix: realized P&L reflects ONLY the in-window match set."""
    now = int(datetime.now(timezone.utc).timestamp())
    fake_api.trades = [
        _trade(now - 48 * 3600, "BUY", 0.5, 10.0, cid="0xmkt"),
        _trade(now - 3600, "SELL", 0.75, 10.0, cid="0xmkt"),
    ]

    result = await portfolio.get_pnl_summary(
        None, FakeRateLimiter(), FakeConfig(), timeframe="24h"
    )

    text = result[0].text
    # The all-time FIFO matches the pre-window BUY with the in-window SELL
    # and reports the realized +$2.50; the item-183 fix (client-side window
    # filter BEFORE the FIFO) must exclude the pre-window BUY from the match
    # set, so the realized P&L must NOT be +2.50 after the fix.
    assert "+2.50" not in text, (
        "all-time FIFO output reached the tool output; the item-183 fix "
        "(client-side window filter before the FIFO) must exclude the "
        "pre-window BUY from the match set"
    )


@pytest.mark.xfail(
    reason="get_activity_log sends the tool's lowercase enum ('trades') -- the "
    "wire is UPPERCASE-only (HTTP 400 verbatim); REQUER-HUMANO item 183 (C)",
    strict=True,
)
@pytest.mark.asyncio
async def test_activity_type_uses_wire_vocabulary(fake_api):
    """Post-fix: params['type'] == 'TRADE' (the wire's uppercase vocabulary)."""
    fake_api.activity = [{"timestamp": 1, "type": "TRADE", "proxyWallet": "0x1"}]

    await portfolio.get_activity_log(
        None, FakeRateLimiter(), FakeConfig(), activity_type="trades", limit=10
    )

    url, params = fake_api.calls[0]
    assert params.get("type") == "TRADE", (
        f"expected the wire's uppercase vocabulary, got {params.get('type')!r}"
    )


@pytest.mark.xfail(
    reason="get_activity_log sends start_time/end_time -- the wire vocabulary "
    "is start/end (epoch seconds, honored on the user path); "
    "REQUER-HUMANO item 183 (C)",
    strict=True,
)
@pytest.mark.asyncio
async def test_activity_dates_use_wire_params(fake_api):
    """Post-fix: the dates ride the wire's start/end params."""
    await portfolio.get_activity_log(
        None,
        FakeRateLimiter(),
        FakeConfig(),
        start_date="2026-09-01T00:00:00Z",
        end_date="2026-09-19T00:00:00Z",
    )

    url, params = fake_api.calls[0]
    assert "start" in params and "end" in params, (
        f"expected the wire's start/end params, got {sorted(params)!r}"
    )
    assert "start_time" not in params and "end_time" not in params, (
        "the snake_case params are wire-ignored dead weight after the fix"
    )


# ---------------------------------------------------------------------------
# Live drift detectors (integration-marked; need network)
# ---------------------------------------------------------------------------
async def _harvest_any(client) -> str:
    resp = await client.get(f"{DATA_API}/trades", params={"limit": 1})
    rows = resp.json()
    assert isinstance(rows, list) and rows, "empty public /trades feed"
    wallet = rows[0].get("proxyWallet")
    assert wallet, "public /trades row without proxyWallet"
    return wallet


async def _harvest_side(client, side: str) -> str:
    resp = await client.get(f"{DATA_API}/trades", params={"limit": 1, "side": side})
    rows = resp.json()
    assert isinstance(rows, list) and rows, f"no {side} rows on the public feed"
    wallet = rows[0].get("proxyWallet")
    assert wallet, "public /trades row without proxyWallet"
    return wallet


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wire_trades_user_path_honors_start_and_end():
    """NEW wire truth (2026-09-19): the USER-filtered /trades honors start/end."""
    import time

    async with httpx.AsyncClient(timeout=20.0) as client:
        wallet = await _harvest_any(client)

        future = int(time.time()) + 30 * 86400
        resp = await client.get(
            f"{DATA_API}/trades", params={"user": wallet, "limit": 10, "start": future}
        )
        assert resp.json() == [], "user-path /trades must filter by start"

        resp = await client.get(
            f"{DATA_API}/trades", params={"user": wallet, "limit": 10, "start": 0}
        )
        rows = resp.json()
        assert rows, "user-path /trades with start=0 must return the feed"

        # end = (newest fetched row) - 1 must EXCLUDE the newest row (older
        # rows are allowed to remain); end=0 is NOT used (a falsy value could
        # be treated as absent by the wire).
        newest = max(int(r["timestamp"]) for r in rows)
        resp = await client.get(
            f"{DATA_API}/trades",
            params={"user": wallet, "limit": 10, "end": newest - 1},
        )
        rows2 = resp.json()
        assert all(
            int(r["timestamp"]) <= newest - 1 for r in rows2
        ), "user-path /trades must filter by end (the newest row is excluded)"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wire_activity_user_path_honors_end():
    """NEW probe (2026-09-19): /activity honors end on the user path."""

    async with httpx.AsyncClient(timeout=20.0) as client:
        wallet = await _harvest_any(client)

        resp = await client.get(
            f"{DATA_API}/activity", params={"user": wallet, "limit": 10}
        )
        rows = resp.json()
        assert rows, "the harvested wallet has no /activity rows"
        newest = max(int(r["timestamp"]) for r in rows)
        resp = await client.get(
            f"{DATA_API}/activity",
            params={"user": wallet, "limit": 10, "end": newest - 1},
        )
        rows2 = resp.json()
        assert all(
            int(r["timestamp"]) <= newest - 1 for r in rows2
        ), "user-path /activity must filter by end (the newest row is excluded)"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wire_trades_user_path_honors_side():
    """NEW probe (2026-09-19): the user-path /trades honors the side filter."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        wallet = await _harvest_side(client, "SELL")

        resp = await client.get(
            f"{DATA_API}/trades", params={"user": wallet, "limit": 10, "side": "SELL"}
        )
        rows = resp.json()
        assert rows, "harvested SELL wallet must have SELL trades"
        assert all(r["side"] == "SELL" for r in rows), "side=SELL must filter"

        resp = await client.get(
            f"{DATA_API}/trades", params={"user": wallet, "limit": 10, "side": "BUY"}
        )
        rows = resp.json()
        assert all(r["side"] == "BUY" for r in rows), "side=BUY must filter"
