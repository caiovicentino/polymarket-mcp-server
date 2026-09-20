"""Offline contract for the client-side market defense in get_trade_history.

The Data API DROPS the ``market`` query filter for padded condition ids
(sports/GAMES form, trailing hex zeros -- wire truth probed 2026-09-20, the
same class T-0452 closed for /positions), so a request for a padded cid
returns unfiltered rows and the tool rendered another market's trades under
the requested header. farm/T-0456 adds the honest client-side defense:
``_trade_matches_market`` (conditionId primary, ``market`` fallback, strict
when neither key is present) applied right after the fetch.

RED pre (deterministic, this suite): the padded-cid, fallback and mixed
cases leak foreign rows pre-fix; the no-filter and exact-match cases are
regression guards that pass in both states.
"""
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from polymarket_mcp.tools import portfolio
from polymarket_mcp.tools.portfolio import get_trade_history

PADDED_CID = "0x03134343d7e9908b433e3be00cdaffa14a" + "0" * 32
UNPADDED_CID = "0xmarket123"


class FakeLimiter:
    def __init__(self):
        self.calls = []

    async def acquire(self, category):
        self.calls.append(category)


class FakeConfig:
    POLYGON_ADDRESS = "0xABC0000000000000000000000000000000000000"


def trade_row(cid=None, market=None, trade_id="t-1", side="BUY"):
    row: Dict[str, Any] = {
        "market_question": "Will the DAO proposal pass?",
        "outcome": "YES",
        "side": side,
        "price": 0.5,
        "size": 10.0,
        "timestamp": 1767225600,
        "fee": 0.0,
        "id": trade_id,
    }
    if cid is not None:
        row["conditionId"] = cid
    if market is not None:
        row["market"] = market
    return row


@pytest.fixture
def http_env(monkeypatch):
    """Routes /trades through a fake AsyncClient that records params."""
    import httpx as real_httpx

    calls: List[Dict[str, Any]] = []

    class FakeResponse:
        def __init__(self, rows):
            self._rows = rows
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return self._rows

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, timeout=None):
            calls.append({"url": url, "params": params})
            return FakeResponse(ROWS[0])

    monkeypatch.setattr(real_httpx, "AsyncClient", FakeAsyncClient)
    return calls


ROWS: List[List[Dict[str, Any]]] = []


@pytest.mark.asyncio
async def test_padded_cid_filters_foreign_trades(http_env):
    """A padded cid must NOT leak another market's trades (the wire drops
    the server-side filter; the client-side defense must catch it)."""
    ROWS[:] = [[
        trade_row(cid="0xothermarket0000000000000000000000000000000000", trade_id="t-foreign"),
        trade_row(cid=PADDED_CID, trade_id="t-own"),
    ]]
    result = await get_trade_history(
        SimpleNamespace(), FakeLimiter(), FakeConfig(), market_id=PADDED_CID
    )
    text = result[0].text
    assert "t-own" in text
    assert "t-foreign" not in text
    assert "Trade History (1 trades)" in text


@pytest.mark.asyncio
async def test_unpadded_cid_match_survives(http_env):
    """Exact unpadded cid still matches (regression guard)."""
    ROWS[:] = [[
        trade_row(cid=UNPADDED_CID, trade_id="t-own"),
        trade_row(cid="0xothermarket0000000000000000000000000000000000", trade_id="t-foreign"),
    ]]
    result = await get_trade_history(
        SimpleNamespace(), FakeLimiter(), FakeConfig(), market_id=UNPADDED_CID
    )
    text = result[0].text
    assert "t-own" in text
    assert "t-foreign" not in text


@pytest.mark.asyncio
async def test_market_fallback_key_matches(http_env):
    """Rows carrying only the legacy ``market`` key still match (the fallback
    the T-0452 helper established for fixture compatibility)."""
    ROWS[:] = [[trade_row(market=UNPADDED_CID, trade_id="t-own")]]
    result = await get_trade_history(
        SimpleNamespace(), FakeLimiter(), FakeConfig(), market_id=UNPADDED_CID
    )
    assert "t-own" in result[0].text


@pytest.mark.asyncio
async def test_all_filtered_returns_honest_empty(http_env):
    """When the defense drops every row the honest empty message shows."""
    ROWS[:] = [[trade_row(cid="0xothermarket0000000000000000000000000000000000")]]
    result = await get_trade_history(
        SimpleNamespace(), FakeLimiter(), FakeConfig(), market_id=PADDED_CID
    )
    assert [c.text for c in result] == ["No trades found matching criteria."]


@pytest.mark.asyncio
async def test_no_market_id_keeps_rows_without_ids(http_env):
    """Without a market_id there is no filter -- rows keep flowing."""
    ROWS[:] = [[trade_row(trade_id="t-nofilter")]]
    result = await get_trade_history(SimpleNamespace(), FakeLimiter(), FakeConfig())
    assert "t-nofilter" in result[0].text


def test_server_params_still_carry_market(monkeypatch):
    """The ``market`` param stays in the server query (the defense is
    additive; the param-passing pin of the sibling suite survives)."""
    assert hasattr(portfolio, "_trade_matches_market")
    assert portfolio._trade_matches_market({"conditionId": "0xA"}, "0xa")
    assert not portfolio._trade_matches_market({"conditionId": "0xB"}, "0xa")
    assert portfolio._trade_matches_market({"market": "0xa"}, "0xa")
    assert not portfolio._trade_matches_market({}, "0xa")
