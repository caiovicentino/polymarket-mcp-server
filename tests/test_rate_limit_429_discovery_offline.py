"""429-backoff wiring: market_discovery fetch surfaces (offline).

``RateLimiter.handle_429_error`` documents "exponential backoff on 429
errors" but had ZERO callers in src/ (grep-proven before this fatia): a real
429 from the wire armed no backoff and immediate retries hammered the API.
This suite pins the NEW wiring on the two fetch sites of market_discovery.py
(the ``_fetch_gamma_markets`` page loop and the ``/public-search`` call):

- on a 429 the limiter arms backoff, observable via the PUBLIC
  ``get_status()[category.value]["is_throttled"]`` /
  ``["backoff_remaining_sec"]``; the raise path is UNCHANGED (the scripted
  raise still propagates -- the wiring runs BEFORE raise_for_status and
  swallows nothing);
- a ``Retry-After`` header value is honored (server wins over the default);
- 200 / 500 arm NOTHING;
- a response stub WITHOUT ``status_code`` cannot break the wiring
  (fake-compat guard: the offline suites' fakes never carry status_code, so
  the getattr-with-default wiring must not AttributeError on them);
- the helper accepts a REAL ``httpx.Response`` (type-fidelity pin).
"""

import httpx
import pytest

from polymarket_mcp.tools import market_discovery
from polymarket_mcp.utils.rate_limiter import EndpointCategory, RateLimiter


class ScriptedResponse:
    """httpx.Response stand-in. ``bare=True`` omits status_code/headers to
    model the older offline-suite fakes (fake-compat guard)."""

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


class FakeGammaClient:
    """Fail-loud client stub at the market_discovery httpx seam (P-0031).
    Serves one scripted response per GET in order; anything else is a fail."""

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
    monkeypatch.setattr(market_discovery, "get_rate_limiter", lambda: limiter)
    monkeypatch.setattr(market_discovery.httpx, "AsyncClient",
                        lambda *a, **k: client)


def _throttled(limiter, category):
    return limiter.get_status()[category.value]["is_throttled"]


def _remaining(limiter, category):
    return limiter.get_status()[category.value]["backoff_remaining_sec"]


# --- _fetch_gamma_markets (page loop site) -----------------------------------


async def test_gamma_429_with_retry_after_arms_backoff_and_raises(monkeypatch):
    limiter = RateLimiter()
    err = RuntimeError("scripted raise_for_status")
    client = FakeGammaClient([ScriptedResponse(status_code=429, retry_after="2",
                                               error=err)])
    _install(monkeypatch, limiter, client)
    with pytest.raises(RuntimeError):
        await market_discovery._fetch_gamma_markets(limit=10)
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is True
    assert 1.5 <= _remaining(limiter, EndpointCategory.GAMMA_API) <= 2.1


async def test_gamma_429_without_retry_after_arms_default_backoff(monkeypatch):
    limiter = RateLimiter()
    err = RuntimeError("scripted raise_for_status")
    client = FakeGammaClient([ScriptedResponse(status_code=429, error=err)])
    _install(monkeypatch, limiter, client)
    with pytest.raises(RuntimeError):
        await market_discovery._fetch_gamma_markets(limit=10)
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is True
    assert 0.5 <= _remaining(limiter, EndpointCategory.GAMMA_API) <= 1.1


async def test_gamma_200_returns_rows_and_arms_nothing(monkeypatch):
    limiter = RateLimiter()
    rows = [{"id": "1", "question": "q"}]
    client = FakeGammaClient([ScriptedResponse(payload=rows)])
    _install(monkeypatch, limiter, client)
    result = await market_discovery._fetch_gamma_markets(limit=10)
    assert result == rows
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is False


async def test_gamma_500_arms_nothing(monkeypatch):
    limiter = RateLimiter()
    err = RuntimeError("scripted raise_for_status")
    client = FakeGammaClient([ScriptedResponse(status_code=500, error=err)])
    _install(monkeypatch, limiter, client)
    with pytest.raises(RuntimeError):
        await market_discovery._fetch_gamma_markets(limit=10)
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is False


async def test_gamma_bare_stub_without_status_code_cannot_break_wiring(monkeypatch):
    limiter = RateLimiter()
    err = RuntimeError("scripted raise_for_status")
    client = FakeGammaClient([ScriptedResponse(error=err, bare=True)])
    _install(monkeypatch, limiter, client)
    with pytest.raises(RuntimeError):
        await market_discovery._fetch_gamma_markets(limit=10)
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is False


# --- _search_gamma_markets (public-search site) ------------------------------


async def test_public_search_429_arms_backoff_and_raises(monkeypatch):
    limiter = RateLimiter()
    err = RuntimeError("scripted raise_for_status")
    client = FakeGammaClient([ScriptedResponse(status_code=429, error=err)])
    _install(monkeypatch, limiter, client)
    with pytest.raises(RuntimeError):
        await market_discovery._search_gamma_markets("bitcoin", limit=5)
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is True
    assert 0.5 <= _remaining(limiter, EndpointCategory.GAMMA_API) <= 1.1


# --- helper type fidelity: REAL httpx.Response -------------------------------


async def test_helper_accepts_real_httpx_response_429():
    limiter = RateLimiter()
    response = httpx.Response(
        429,
        headers={"retry-after": "3"},
        request=httpx.Request("GET", "https://gamma-api.polymarket.com/markets"),
    )
    await market_discovery._note_http_429(
        limiter, response, EndpointCategory.GAMMA_API
    )
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is True
    assert 2.5 <= _remaining(limiter, EndpointCategory.GAMMA_API) <= 3.1


async def test_helper_real_httpx_response_200_arms_nothing():
    limiter = RateLimiter()
    response = httpx.Response(
        200, request=httpx.Request("GET", "https://gamma-api.polymarket.com/markets")
    )
    await market_discovery._note_http_429(
        limiter, response, EndpointCategory.GAMMA_API
    )
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is False
