"""429-backoff wiring: market_analysis fetch surfaces (offline).

Same wiring as the discovery fatia, pinned on ``_fetch_gamma_api``
(GAMMA_API) and ``_fetch_clob_api`` (MARKET_DATA): on a 429 the limiter arms
backoff (public ``get_status()`` observable) and the raise path is
UNCHANGED; ``Retry-After`` wins over the default; 200/500/stub-responses
arm NOTHING; the helper accepts a REAL ``httpx.Response``.
"""

import httpx
import pytest

from polymarket_mcp.tools import market_analysis
from polymarket_mcp.utils.rate_limiter import EndpointCategory, RateLimiter


class ScriptedResponse:
    def __init__(self, payload=None, status_code=200, retry_after=None, error=None,
                 bare=False):
        if not bare:
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
    """Fail-loud client stub at the market_analysis httpx seam (P-0031).
    Serves ONE scripted response in sequence; further fetches fail."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        self.calls.append({"url": url, "params": params})
        assert self._responses, f"unexpected fetch: {url} {params}"
        return self._responses.pop(0)


def _install(monkeypatch, limiter, client):
    monkeypatch.setattr(market_analysis, "get_rate_limiter", lambda: limiter)
    monkeypatch.setattr(market_analysis.httpx, "AsyncClient",
                        lambda *a, **k: client)


def _throttled(limiter, category):
    return limiter.get_status()[category.value]["is_throttled"]


def _remaining(limiter, category):
    return limiter.get_status()[category.value]["backoff_remaining_sec"]


# --- _fetch_gamma_api --------------------------------------------------------


async def test_gamma_api_429_with_retry_after_arms_backoff(monkeypatch):
    limiter = RateLimiter()
    err = RuntimeError("scripted raise_for_status")
    _install(monkeypatch, limiter,
             FakeHttpClient([ScriptedResponse(status_code=429, retry_after="2",
                                              error=err)]))
    with pytest.raises(RuntimeError):
        await market_analysis._fetch_gamma_api("/markets", {})
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is True
    assert 1.5 <= _remaining(limiter, EndpointCategory.GAMMA_API) <= 2.1


async def test_gamma_api_200_arms_nothing(monkeypatch):
    limiter = RateLimiter()
    payload = {"data": [{"id": "1"}]}
    _install(monkeypatch, limiter,
             FakeHttpClient([ScriptedResponse(payload=payload)]))
    result = await market_analysis._fetch_gamma_api("/markets", {})
    assert result == payload
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is False


async def test_gamma_api_500_arms_nothing(monkeypatch):
    limiter = RateLimiter()
    err = RuntimeError("scripted raise_for_status")
    _install(monkeypatch, limiter,
             FakeHttpClient([ScriptedResponse(status_code=500, error=err)]))
    with pytest.raises(RuntimeError):
        await market_analysis._fetch_gamma_api("/markets", {})
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is False


async def test_gamma_api_bare_stub_cannot_break_wiring(monkeypatch):
    limiter = RateLimiter()
    err = RuntimeError("scripted raise_for_status")
    _install(monkeypatch, limiter,
             FakeHttpClient([ScriptedResponse(error=err, bare=True)]))
    with pytest.raises(RuntimeError):
        await market_analysis._fetch_gamma_api("/markets", {})
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is False


# --- _fetch_clob_api ---------------------------------------------------------


async def test_clob_api_429_arms_market_data_backoff(monkeypatch):
    limiter = RateLimiter()
    err = RuntimeError("scripted raise_for_status")
    _install(monkeypatch, limiter,
             FakeHttpClient([ScriptedResponse(status_code=429, retry_after="1",
                                              error=err)]))
    with pytest.raises(RuntimeError):
        await market_analysis._fetch_clob_api("/prices-history", {})
    assert _throttled(limiter, EndpointCategory.MARKET_DATA) is True
    assert 0.5 <= _remaining(limiter, EndpointCategory.MARKET_DATA) <= 1.1
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is False


async def test_clob_api_200_arms_nothing(monkeypatch):
    limiter = RateLimiter()
    payload = {"history": [{"t": 1, "p": "0.5"}]}
    _install(monkeypatch, limiter,
             FakeHttpClient([ScriptedResponse(payload=payload)]))
    result = await market_analysis._fetch_clob_api("/prices-history", {})
    assert result == payload
    assert _throttled(limiter, EndpointCategory.MARKET_DATA) is False


# --- helper type fidelity: REAL httpx.Response -------------------------------


async def test_helper_accepts_real_httpx_response_429():
    limiter = RateLimiter()
    response = httpx.Response(
        429,
        headers={"retry-after": "2"},
        request=httpx.Request("GET", "https://clob.polymarket.com/book"),
    )
    await market_analysis._note_http_429(
        limiter, response, EndpointCategory.MARKET_DATA
    )
    assert _throttled(limiter, EndpointCategory.MARKET_DATA) is True
    assert 1.5 <= _remaining(limiter, EndpointCategory.MARKET_DATA) <= 2.1
