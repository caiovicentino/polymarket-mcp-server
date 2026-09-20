"""Offline regression suite closing the LAST FALSE arcs of the 429 helpers.

The 429 wiring (T-0357 data_api_pagination / T-0363 portfolio, consolidated
by T-0402) left the headers-MISSING arcs of ``_note_http_429`` unexercised:

- ``if headers is not None:`` (data_api_pagination arc [54->58] and
  portfolio arc [46->50]): the fakes of EVERY sibling suite carry a
  ``headers`` attribute, so a 429 response object WITHOUT ``headers`` never
  reached the ``Retry-After`` parse. On that FALSE arc the helper arms the
  DEFAULT exponential backoff by passing ``retry_after=None`` to the
  limiter.
- ``if getattr(response, "status_code", None) != 429: return`` (data_api
  arc [50->51] + statement 51): the bare-stub compat path shared with the
  portfolio helper.

The Retry-After parse-TRUE path (statement 57, arc [56->57]) is the
behavioral pin of the passthrough suite (T-0399) and is intentionally NOT
re-pinned here. The arming SEMANTICS (exponential default, throttled state)
are already pinned by the sibling suites
(test_429_helper_false_arcs_offline.py uses the real ``RateLimiter``); this
suite pins the ARC with a spy limiter instead (observed pins, L-0020/L-0090):
``handle_429_error`` calls are recorded verbatim, so the ``retry_after``
argument that reaches the limiter is observable without any sleep. A real
``RateLimiter`` is deliberately NOT used here -- arming state is the sisters'
turf, the ARC is this suite's turf.

Coverage-only slice: no ``src/`` change, GREEN before and after (L-0023).
"""

from typing import Any, List, Optional, Tuple

import pytest

from polymarket_mcp.tools import portfolio
from polymarket_mcp.utils import data_api_pagination
from polymarket_mcp.utils.rate_limiter import EndpointCategory


class _Response429NoHeaders:
    """429 wire response WITHOUT a headers attribute (parse must survive)."""

    status_code = 429


class _BareResponse:
    """Response with neither status_code nor headers (stub-compat path)."""


class _LimiterSpy:
    """Records ``handle_429_error`` calls without arming a real limiter."""

    def __init__(self) -> None:
        self.calls: List[Tuple[Any, Optional[int]]] = []

    async def handle_429_error(
        self,
        category: EndpointCategory,
        retry_after: Optional[int] = None,
    ) -> None:
        self.calls.append((category, retry_after))


@pytest.mark.asyncio
async def test_data_api_429_without_headers_arms_exponential_default():
    """A 429 WITHOUT ``headers`` arms the DEFAULT exponential backoff.

    Closes the data_api_pagination headers-missing arc [54->58]:
    ``headers is None`` skips the ``Retry-After`` parse entirely and the
    limiter receives ``retry_after=None`` (the exponential default).
    """
    spy = _LimiterSpy()
    await data_api_pagination._note_http_429(
        spy, _Response429NoHeaders(), EndpointCategory.DATA_API
    )
    assert spy.calls == [(EndpointCategory.DATA_API, None)]


@pytest.mark.asyncio
async def test_portfolio_429_without_headers_arms_exponential_default():
    """Same headers-missing arc for the portfolio helper (arc [46->50])."""
    spy = _LimiterSpy()
    await portfolio._note_http_429(
        spy, _Response429NoHeaders(), EndpointCategory.DATA_API
    )
    assert spy.calls == [(EndpointCategory.DATA_API, None)]


@pytest.mark.asyncio
async def test_bare_response_without_status_code_arms_nothing():
    """Anti-over-fix: a bare stub (no status_code, no headers) never arms.

    Exercises the getattr-default path on BOTH helpers: the data_api early
    return (arc [50->51] + statement 51) and the portfolio early return.
    Nothing is recorded on the spy, so the stub-compat path is proven
    untouched.
    """
    spy = _LimiterSpy()
    await data_api_pagination._note_http_429(
        spy, _BareResponse(), EndpointCategory.DATA_API
    )
    await portfolio._note_http_429(
        spy, _BareResponse(), EndpointCategory.DATA_API
    )
    assert spy.calls == []
