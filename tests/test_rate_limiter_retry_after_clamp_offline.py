"""Offline regression suite for the Retry-After clamp in RateLimiter.

``RateLimiter.handle_429_error`` honored a server-provided ``Retry-After``
VERBATIM (``backoff_time = float(retry_after)``) while the exponential path
caps its own backoff at 60s (``min(remaining * 2, 60.0)``). The 429 wiring
(T-0356/T-0357/T-0358/T-0362/T-0363) made that path LIVE: a real 429 with a
hostile/errant ``Retry-After: 999999`` header now arms ~11.5 days of backoff
and every ``acquire()`` for the category sleeps the whole window -- the
honoring of an untrusted header became a local DoS vector the moment the
callers landed (lesson L-0377: clamp every wire-supplied duration at the
parse border; never rely on the neighbor's cap).

The fix clamps the parsed hint to ``_RETRY_AFTER_MAX_SECONDS`` (the same
ceiling the exponential path uses -- single source of truth for the cap).
Asserts follow the code as observed (probed offline), not the docstrings
(L-0020/L-0090). Source of truth:

- handle_429_error (src/polymarket_mcp/utils/rate_limiter.py):
  * retry_after present and > ceiling -> backoff is EXACTLY the ceiling
    (60.0s under the fake clock), not the header value.
  * retry_after present and <= ceiling -> honored verbatim (regression pin).
  * retry_after present but non-positive -> no FUTURE backoff is armed
    (backoff_until <= now; the next acquire pays zero). OBSERVED pre-fix and
    preserved post-fix -- the clamp only touches the upper bound.
  * retry_after falsy (None or 0) -> the exponential path, unchanged.
- acquire() sleeps at most the ceiling when the backoff is armed by a huge
  hint (the wire-to-wait contract, not just the stored state).

Zero network, zero real sleep: the module's clock and sleep seams are
patched onto a fake clock (house rule: fakes self-contained, never imported
from another test module).
"""
import pytest

from polymarket_mcp.utils import rate_limiter
from polymarket_mcp.utils.rate_limiter import (
    EndpointCategory,
    RateLimiter,
)


class FakeClock:
    """Mutable fake clock: time.monotonic() reads .t; sleeps record and advance it."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def advance(self, seconds: float) -> None:
        """Advance the fake clock without going through asyncio.sleep."""
        self.t += seconds


@pytest.fixture()
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Patch rate_limiter's clock and sleep seams onto a fake clock.

    rate_limiter reads time.monotonic() and awaits asyncio.sleep() via the
    module-global time/asyncio modules; monkeypatch restores both after each
    test. No real sleep is ever executed (L-0014).
    """
    clock = FakeClock()
    monkeypatch.setattr(rate_limiter.time, "monotonic", lambda: clock.t)

    async def fake_sleep(seconds: float) -> None:
        clock.sleeps.append(seconds)
        clock.t += seconds

    monkeypatch.setattr(rate_limiter.asyncio, "sleep", fake_sleep)
    return clock


def _remaining(limiter: RateLimiter, category: EndpointCategory) -> float:
    return limiter.get_status()[category.value]["backoff_remaining_sec"]


def _throttled(limiter: RateLimiter, category: EndpointCategory) -> bool:
    return limiter.get_status()[category.value]["is_throttled"]


async def test_retry_after_huge_is_clamped_to_ceiling(fake_clock):
    """Retry-After: 999999 must NOT arm an 11.5-day backoff (L-0377).

    RED pre-fix: the header was honored verbatim and the category's callers
    would sleep ~999999s. The clamp caps the parsed hint at the ceiling.
    """
    limiter = RateLimiter()
    cat = EndpointCategory.DATA_API
    await limiter.handle_429_error(cat, 999999)
    assert _throttled(limiter, cat) is True
    assert 59.9 <= _remaining(limiter, cat) <= 60.0 + 1e-9


async def test_retry_after_acquire_sleeps_at_most_the_ceiling(fake_clock):
    """The wire-to-wait contract: acquire() sleeps the clamped window."""
    limiter = RateLimiter()
    cat = EndpointCategory.MARKET_DATA
    await limiter.handle_429_error(cat, 999999)
    t_before = fake_clock.t
    wait = await limiter.acquire(cat)
    assert wait == 60.0
    assert fake_clock.sleeps == [60.0]
    assert fake_clock.t == t_before + 60.0


async def test_retry_after_above_ceiling_is_exactly_capped(fake_clock):
    """A hint one second above the ceiling lands exactly on the ceiling."""
    limiter = RateLimiter()
    cat = EndpointCategory.GAMMA_API
    await limiter.handle_429_error(cat, 61)
    assert _remaining(limiter, cat) == 60.0


async def test_retry_below_ceiling_honored_verbatim(fake_clock):
    """Hints at or below the ceiling keep being honored verbatim.

    Regression pin for the original behavior (mirrors
    test_rate_limiter_retry_after_honored, with this suite's own fixture).
    """
    limiter = RateLimiter()
    cat = EndpointCategory.DATA_API
    await limiter.handle_429_error(cat, 30)
    assert _remaining(limiter, cat) == 30.0
    assert _throttled(limiter, cat) is True

    t_before = fake_clock.t
    assert await limiter.acquire(cat) == 30.0
    assert fake_clock.sleeps == [30.0]
    assert fake_clock.t == t_before + 30.0


async def test_retry_after_non_positive_does_not_arm_future_backoff(fake_clock):
    """A non-positive hint arms no FUTURE backoff (OBSERVED pre-fix).

    The clamp touches only the upper bound: -5 yields backoff_until <= now,
    so the next acquire pays zero and is_throttled stays False. Both the
    pre-fix (backoff_until = now - 5) and post-fix states satisfy the
    semantic pin; the observable is the WAIT, not the stored value.
    """
    limiter = RateLimiter()
    cat = EndpointCategory.BATCH_OPS
    await limiter.handle_429_error(cat, -5)
    assert _throttled(limiter, cat) is False
    t_before = fake_clock.t
    assert await limiter.acquire(cat) == 0.0
    assert fake_clock.sleeps == []
    assert fake_clock.t == t_before


async def test_retry_after_zero_falls_through_to_exponential(fake_clock):
    """retry_after=0 is falsy: the exponential path starts at 1.0 (unchanged)."""
    limiter = RateLimiter()
    cat = EndpointCategory.CLOB_GENERAL
    await limiter.handle_429_error(cat, 0)
    assert _remaining(limiter, cat) == 1.0


async def test_exponential_path_unchanged(fake_clock):
    """Anti-over-fix: the exponential doubling path keeps its exact series.

    The fix only adds the clamp to the parsed path; None-driven backoffs
    must remain 1.0 -> 2.0 -> 4.0 ... -> 60.0 (capped by the same constant).
    """
    limiter = RateLimiter()
    cat = EndpointCategory.GAMMA_API
    await limiter.handle_429_error(cat)
    assert _remaining(limiter, cat) == 1.0
    await limiter.handle_429_error(cat)
    assert _remaining(limiter, cat) == 2.0
