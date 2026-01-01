"""Offline pins for the shared 429-note util and its per-module delegates.

The consolidation of the 7 per-module ``_note_*`` helpers (L-0073) into
``polymarket_mcp.utils.rate_limit_note`` must preserve, per module, the
helper NAME and SIGNATURE: the 21 wired call sites and the six wired 429
suites are untouched by design. These pins cover the canonical helpers
directly and each delegate's routing - the trading legacy hardcode keeps
``TRADING_BURST``, the category pass-through forwards verbatim, the
pagination delegate keeps the opt-in None-guard, and the Data-API
delegates route to the canonical helper with Retry-After parsed.
"""

from polymarket_mcp.tools import market_analysis, market_discovery, portfolio, trading
from polymarket_mcp.utils import data_api_pagination, rate_limit_note
from polymarket_mcp.utils.rate_limiter import EndpointCategory


class FakeLimiter:
    """Recorder fake: captures (category, retry_after) per handle_429_error
    call; every other limiter surface is out of scope here."""

    def __init__(self):
        self.calls = []

    async def handle_429_error(self, category, retry_after):
        self.calls.append((category, retry_after))


class _NoStatus:
    """Stub without ``status_code`` (the offline suites' fake shape)."""


def _resp(status_code=429, retry_after=None, with_headers=True):
    obj = _NoStatus()
    obj.status_code = status_code
    obj.headers = {"retry-after": retry_after} if with_headers else None
    return obj


# --- canonical note_http_429 (direct) ---


async def test_note_http_429_digit_retry_after_parsed():
    limiter = FakeLimiter()
    await rate_limit_note.note_http_429(limiter, _resp(retry_after="12"), "cat")
    assert limiter.calls == [("cat", 12)]


async def test_note_http_429_non_digit_retry_after_forwarded_none():
    limiter = FakeLimiter()
    await rate_limit_note.note_http_429(limiter, _resp(retry_after="soon"), "cat")
    assert limiter.calls == [("cat", None)]


async def test_note_http_429_missing_retry_after_forwarded_none():
    limiter = FakeLimiter()
    # headers present WITHOUT the retry-after key
    await rate_limit_note.note_http_429(limiter, _resp(with_headers=True), "cat")
    # headers attribute is None entirely
    await rate_limit_note.note_http_429(limiter, _resp(with_headers=False), "cat")
    assert limiter.calls == [("cat", None), ("cat", None)]


async def test_note_http_429_non_429_noop():
    limiter = FakeLimiter()
    for status in (200, 404, 500):
        await rate_limit_note.note_http_429(limiter, _resp(status_code=status), "cat")
    assert limiter.calls == []


async def test_note_http_429_stub_without_status_code_noop():
    limiter = FakeLimiter()
    await rate_limit_note.note_http_429(limiter, _NoStatus(), "cat")
    assert limiter.calls == []


# --- canonical note_clob_429 (direct) ---


async def test_note_clob_429_arms_given_category_retry_none():
    limiter = FakeLimiter()
    exc = _NoStatus()
    exc.status_code = 429
    await rate_limit_note.note_clob_429(limiter, exc, EndpointCategory.MARKET_DATA)
    assert limiter.calls == [(EndpointCategory.MARKET_DATA, None)]


async def test_note_clob_429_non_429_noop():
    limiter = FakeLimiter()
    exc = _NoStatus()
    exc.status_code = 500
    await rate_limit_note.note_clob_429(limiter, exc, EndpointCategory.MARKET_DATA)
    assert limiter.calls == []


async def test_note_clob_429_stub_without_status_code_noop():
    limiter = FakeLimiter()
    await rate_limit_note.note_clob_429(
        limiter, _NoStatus(), EndpointCategory.MARKET_DATA
    )
    assert limiter.calls == []


# --- per-module delegates ---


async def test_delegate_trading_legacy_arms_trading_burst():
    """Pin: the order-placement wiring keeps the TRADING_BURST hardcode -
    arming a different category would delay the wrong tool's backoff."""
    limiter = FakeLimiter()
    exc = _NoStatus()
    exc.status_code = 429
    await trading._note_clob_429(limiter, exc)
    assert limiter.calls == [(EndpointCategory.TRADING_BURST, None)]


async def test_delegate_trading_cat_passes_category_through():
    limiter = FakeLimiter()
    exc = _NoStatus()
    exc.status_code = 429
    await trading._note_clob_429_cat(limiter, exc, EndpointCategory.CLOB_GENERAL)
    assert limiter.calls == [(EndpointCategory.CLOB_GENERAL, None)]


async def test_delegate_pagination_none_guard_rate_limiter():
    """Opt-in None-guard stays in the delegate: no limiter, no arming."""
    limiter = FakeLimiter()
    await data_api_pagination._note_http_429(
        None, _resp(retry_after="30"), EndpointCategory.DATA_API
    )
    assert limiter.calls == []


async def test_delegate_pagination_none_guard_category():
    limiter = FakeLimiter()
    await data_api_pagination._note_http_429(limiter, _resp(retry_after="30"), None)
    assert limiter.calls == []


async def test_delegate_pagination_opt_in_arms_with_parsed_retry_after():
    limiter = FakeLimiter()
    await data_api_pagination._note_http_429(
        limiter, _resp(retry_after="30"), EndpointCategory.DATA_API
    )
    assert limiter.calls == [(EndpointCategory.DATA_API, 30)]


async def test_delegate_market_analysis_routes_to_canonical():
    limiter = FakeLimiter()
    await market_analysis._note_http_429(
        limiter, _resp(retry_after="7"), EndpointCategory.GAMMA_API
    )
    assert limiter.calls == [(EndpointCategory.GAMMA_API, 7)]


async def test_delegate_market_discovery_routes_to_canonical():
    limiter = FakeLimiter()
    await market_discovery._note_http_429(
        limiter, _resp(retry_after="7"), EndpointCategory.GAMMA_API
    )
    assert limiter.calls == [(EndpointCategory.GAMMA_API, 7)]


async def test_delegate_portfolio_routes_to_canonical():
    limiter = FakeLimiter()
    await portfolio._note_http_429(
        limiter, _resp(retry_after="7"), EndpointCategory.DATA_API
    )
    assert limiter.calls == [(EndpointCategory.DATA_API, 7)]
