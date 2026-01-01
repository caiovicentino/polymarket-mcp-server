"""429-backoff wiring: portfolio Data-API surfaces (offline).

Same wiring as the discovery/analysis fatias, pinned on the three direct
Data-API fetch sites of portfolio.py (``get_position_details`` trades,
``get_trade_history``, ``get_activity_log``) plus the ``fetch_all_pages``
helper (opt-in kwargs: the existing call sites are byte-identical until they
pass the limiter -- declared follow-up). On a 429 the limiter arms backoff
(public ``get_status()`` observable) and the raise/return path is UNCHANGED
(the error envelopes the suites already pin stay intact); ``Retry-After``
wins over the default; 200/500/stub-responses arm NOTHING.
"""

import httpx
import pytest

from polymarket_mcp.tools import portfolio
from polymarket_mcp.utils.data_api_pagination import fetch_all_pages
from polymarket_mcp.utils.rate_limiter import EndpointCategory, RateLimiter

TRADES_URL = "https://data-api.polymarket.com/trades"
POSITIONS_URL = "https://data-api.polymarket.com/positions"


class FakeConfig:
    POLYGON_ADDRESS = "0xAbCdEf0123456789AbCdEf0123456789aBcDeF01"


class ScriptedResponse:
    def __init__(self, payload=None, status_code=200, retry_after=None, error=None):
        self.status_code = status_code
        self.headers = {"retry-after": retry_after} if retry_after else {}
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        if self._error is not None:
            raise self._error
        return self._payload


class FakeHttpClient:
    """Fail-loud client stub at the portfolio httpx seam (P-0031). Serves ONE
    scripted response; further fetches fail loud."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        assert self._responses, f"unexpected fetch: {url} {params}"
        return self._responses.pop(0)


class FakePolyClient:
    """Minimal client stub: only get_orderbook is touched on the
    get_position_details path."""

    def __init__(self):
        self.book = {
            "bids": [{"price": "0.49", "size": "100"}],
            "asks": [{"price": "0.51", "size": "100"}],
        }

    async def get_orderbook(self, token_id):
        return dict(self.book)


def _throttled(limiter, category):
    return limiter.get_status()[category.value]["is_throttled"]


def _remaining(limiter, category):
    return limiter.get_status()[category.value]["backoff_remaining_sec"]


# --- get_trade_history (direct site) -----------------------------------------


async def test_trade_history_429_arms_backoff_and_returns_error_envelope():
    limiter = RateLimiter()
    err = RuntimeError("scripted raise_for_status")
    client = FakeHttpClient([ScriptedResponse(status_code=429, error=err)])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(portfolio.httpx, "AsyncClient", lambda *a, **k: client)
        result = await portfolio.get_trade_history(
            FakePolyClient(), limiter, FakeConfig(), limit=10
        )
    text = result[0].text
    assert "scripted raise_for_status" in text
    assert _throttled(limiter, EndpointCategory.DATA_API) is True
    assert 0.5 <= _remaining(limiter, EndpointCategory.DATA_API) <= 1.1


async def test_trade_history_200_returns_data_and_arms_nothing():
    limiter = RateLimiter()
    client = FakeHttpClient([ScriptedResponse(payload=[])])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(portfolio.httpx, "AsyncClient", lambda *a, **k: client)
        await portfolio.get_trade_history(
            FakePolyClient(), limiter, FakeConfig(), limit=10
        )
    assert _throttled(limiter, EndpointCategory.DATA_API) is False


# --- get_activity_log (direct site) ------------------------------------------


async def test_activity_log_429_arms_backoff_and_returns_error_envelope():
    limiter = RateLimiter()
    err = RuntimeError("scripted raise_for_status")
    client = FakeHttpClient([ScriptedResponse(status_code=429, retry_after="2",
                                              error=err)])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(portfolio.httpx, "AsyncClient", lambda *a, **k: client)
        result = await portfolio.get_activity_log(
            FakePolyClient(), limiter, FakeConfig(), activity_type="trades", limit=10
        )
    text = result[0].text
    assert "scripted raise_for_status" in text
    assert _throttled(limiter, EndpointCategory.DATA_API) is True
    assert 1.5 <= _remaining(limiter, EndpointCategory.DATA_API) <= 2.1


# --- get_position_details (direct site, trades block) ------------------------


async def test_position_details_trades_429_arms_backoff():
    limiter = RateLimiter()
    position = {
        "size": "5", "average_price": "0.5", "asset_id": "tok",
        "market": "m1", "market_question": "q", "outcome": "YES",
    }
    err = RuntimeError("scripted raise_for_status")
    client = FakeHttpClient([
        ScriptedResponse(payload=[position]),      # positions page (short)
        ScriptedResponse(status_code=429, error=err),  # trades fetch
    ])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(portfolio.httpx, "AsyncClient", lambda *a, **k: client)
        await portfolio.get_position_details(
            FakePolyClient(), limiter, FakeConfig(), market_id="m1"
        )
    assert _throttled(limiter, EndpointCategory.DATA_API) is True


# --- fetch_all_pages (opt-in kwargs wiring) ----------------------------------


async def test_fetch_all_pages_429_arms_backoff_when_limiter_passed():
    limiter = RateLimiter()
    err = RuntimeError("scripted raise_for_status")
    client = FakeHttpClient([ScriptedResponse(status_code=429, error=err)])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(portfolio.httpx, "AsyncClient", lambda *a, **k: client)
        with pytest.raises(RuntimeError):
            await fetch_all_pages(
                client, TRADES_URL, {"user": "0xabc", "limit": 10},
                rate_limiter=limiter, category=EndpointCategory.DATA_API,
            )
    assert _throttled(limiter, EndpointCategory.DATA_API) is True


async def test_fetch_all_pages_default_kwargs_arm_nothing():
    limiter = RateLimiter()
    client = FakeHttpClient([ScriptedResponse(payload=[{"x": 1}])])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(portfolio.httpx, "AsyncClient", lambda *a, **k: client)
        rows = await fetch_all_pages(client, TRADES_URL, {"user": "0xabc"})
    assert rows == [{"x": 1}]
    assert _throttled(limiter, EndpointCategory.DATA_API) is False


# --- helper type fidelity: REAL httpx.Response -------------------------------


async def test_portfolio_helper_accepts_real_httpx_response_429():
    limiter = RateLimiter()
    response = httpx.Response(
        429,
        headers={"retry-after": "1"},
        request=httpx.Request("GET", TRADES_URL),
    )
    await portfolio._note_http_429(
        limiter, response, EndpointCategory.DATA_API
    )
    assert _throttled(limiter, EndpointCategory.DATA_API) is True
    assert 0.5 <= _remaining(limiter, EndpointCategory.DATA_API) <= 1.1
