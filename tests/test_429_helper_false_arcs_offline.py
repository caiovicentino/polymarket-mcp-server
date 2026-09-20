"""Offline regression suite closing the FALSE arcs of the HTTP-429 helpers.

The 429 wiring (T-0356/T-0357/T-0358/T-0362/T-0363) added
``_note_http_429`` helpers whose Retry-After parsing has three arcs:

- ``if getattr(response, "status_code", None) != 429: return`` (covered by
  the 200/500/stub tests of the sibling suites),
- ``if headers is not None:`` (the headers-MISSING arc is NOT covered: the
  sibling suites' fakes always carry a ``headers`` attribute, so a 429
  response object WITHOUT ``headers`` never reaches the parse),
- ``if raw is not None and str(raw).strip().isdigit():`` (covered in
  market_discovery by ``test_gamma_429_without_retry_after_arms_default_backoff``
  via ``headers={}``; NOT covered in market_analysis, whose suite only has
  retry-after-bearing tests).

This suite closes those arcs with the REAL ``RateLimiter`` (arming is
instant and sleep-free) and content-anchored, OBSERVED pins (L-0020/L-0090).
No network, no real sleep: arming a 1.0s default backoff only writes state.
"""
from types import SimpleNamespace

import pytest

from polymarket_mcp.tools import market_analysis, market_discovery
from polymarket_mcp.utils.rate_limiter import EndpointCategory, RateLimiter


class _NoHeadersResponse:
    """429 wire response WITHOUT a headers attribute (parse must survive)."""

    status_code = 429


class _BareResponse:
    """Response with neither status_code nor headers (stub-compat path)."""


def _throttled(limiter: RateLimiter, category: EndpointCategory) -> bool:
    return limiter.get_status()[category.value]["is_throttled"]


def _remaining(limiter: RateLimiter, category: EndpointCategory) -> float:
    return limiter.get_status()[category.value]["backoff_remaining_sec"]


@pytest.mark.asyncio
async def test_discovery_helper_handles_response_without_headers_attr():
    """A 429 response WITHOUT ``headers`` still arms the DEFAULT backoff.

    Closes market_discovery arc [58->62] (headers is None -> skip parsing).
    """
    limiter = RateLimiter()
    await market_discovery._note_http_429(
        limiter, _NoHeadersResponse(), EndpointCategory.GAMMA_API
    )
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is True
    assert 0.5 <= _remaining(limiter, EndpointCategory.GAMMA_API) <= 1.1


@pytest.mark.asyncio
async def test_analysis_helper_handles_response_without_headers_attr():
    """Same headers-missing arc for market_analysis's helper [126->130]."""
    limiter = RateLimiter()
    await market_analysis._note_http_429(
        limiter, _NoHeadersResponse(), EndpointCategory.GAMMA_API
    )
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is True
    assert 0.5 <= _remaining(limiter, EndpointCategory.GAMMA_API) <= 1.1


@pytest.mark.asyncio
async def test_analysis_helper_429_with_empty_headers_parses_none():
    """A 429 with an EMPTY headers dict parses retry_after=None (arc 128->130).

    Mirrors the discovery suite's no-retry-after pin for market_analysis,
    which had no equivalent test.
    """
    limiter = RateLimiter()
    response = SimpleNamespace(status_code=429, headers={})
    await market_analysis._note_http_429(
        limiter, response, EndpointCategory.GAMMA_API
    )
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is True
    assert 0.5 <= _remaining(limiter, EndpointCategory.GAMMA_API) <= 1.1


@pytest.mark.asyncio
async def test_analysis_helper_429_with_non_digit_retry_after_parses_none():
    """A NON-DIGIT Retry-After header is ignored (server wins on digits only).

    Closes the isdigit-false path of arc [128->130] and pins the semantic:
    garbage headers fall through to the default exponential backoff.
    """
    limiter = RateLimiter()
    response = SimpleNamespace(status_code=429, headers={"retry-after": "soon"})
    await market_analysis._note_http_429(
        limiter, response, EndpointCategory.GAMMA_API
    )
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is True
    assert 0.5 <= _remaining(limiter, EndpointCategory.GAMMA_API) <= 1.1


@pytest.mark.asyncio
async def test_non_429_without_attributes_arms_nothing():
    """Anti-over-fix: a bare stub (no status_code) never arms a backoff."""
    limiter = RateLimiter()
    await market_discovery._note_http_429(
        limiter, _BareResponse(), EndpointCategory.GAMMA_API
    )
    await market_analysis._note_http_429(
        limiter, _BareResponse(), EndpointCategory.GAMMA_API
    )
    assert _throttled(limiter, EndpointCategory.GAMMA_API) is False
    assert _remaining(limiter, EndpointCategory.GAMMA_API) == 0.0
