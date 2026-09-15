"""
Offline regression suite for the rate limiter (src/polymarket_mcp/utils/rate_limiter.py).

Proves the semantics of rate limiting and 429 backoff with a deterministic
fake clock — zero network, zero real sleeps (T-0036; L-0014):

- Token bucket: starts full; acquire() consumes tokens; refill follows
  elapsed time and is capped at max_tokens; acquire() waits (asyncio.sleep)
  when tokens are insufficient and charges the wait into the returned
  wait_time.
- 429 backoff: first hit arms 1.0s; successive hits double the remaining
  backoff (1→2→4→8→16→32) and cap at 60s; retry_after is honored verbatim;
  reset_backoff() clears one category or all.
- RateLimiter.acquire honors the armed backoff (waits the remainder) unless
  retry_on_429=False, which bypasses the backoff without sleeping.
- get_status() reflects throttling and per-category config; categories are
  isolated (separate buckets); get_rate_limiter() is a singleton.

Determinism: every test drives a fake clock (fixture `fake_clock`) —
time.monotonic() reads clock.t and asyncio.sleep(s) advances clock.t by s and
returns immediately. Under the fake clock every expectation below is EXACT
(no timing tolerance is needed); sleeps are recorded in clock.sleeps so tests
can prove both "this wait happened" and "no sleep happened".

Pinned as OBSERVED (L-0020/L-0025), not as the idealized matrix of the
contract (divergences declared):
- test_token_bucket_refills_with_elapsed_time: the contract's literal
  sequence ("advance 5s → 100; advance 2s → 70") is internally inconsistent
  (after the cap, tokens stay at 100). The test derives a coherent sequence
  producing every declared observable: +2s → 70 (partial refill), +3s → 100
  (exact cap boundary), +2s → 100 (cap holds).
- test_token_bucket_acquire_waits_when_insufficient: the contract's
  "tokens finais == 5.0" is not what the code produces — the 5 tokens
  refilled during the wait are exactly consumed by acquire() (tokens == 0.0
  right after; advancing the clock 0.5s makes 5 tokens available again).

Prerequisites: pytest-asyncio auto mode (pyproject [tool.pytest.ini_options]);
no integration/real_api/slow markers — runs clean under the release gate
filter `-m "not integration and not slow and not real_api"`.

Known quirks pinned by reading the source (P3, NOT fixed here — src is out of
scope for this slice): get_status() annotates Dict[str, any] with the builtin
`any` (rate_limiter.py:247); TokenBucket.acquire() holds the bucket lock
across the whole wait loop, serializing concurrent waiters (head-of-line
blocking, rate_limiter.py:111-137).
"""
import pytest

from polymarket_mcp.utils import rate_limiter
from polymarket_mcp.utils.rate_limiter import (
    RATE_LIMITS,
    EndpointCategory,
    RateLimitConfig,
    RateLimiter,
    TokenBucket,
    get_rate_limiter,
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


async def test_token_bucket_starts_full(fake_clock):
    bucket = TokenBucket(RateLimitConfig(max_tokens=100, refill_rate=10.0, window_seconds=10.0))
    assert bucket.tokens == 100.0
    assert bucket.available_tokens() == 100


async def test_token_bucket_acquire_consumes_tokens(fake_clock):
    bucket = TokenBucket(RateLimitConfig(max_tokens=100, refill_rate=10.0, window_seconds=10.0))
    assert await bucket.acquire(1) == 0.0
    assert bucket.tokens == 99.0
    assert bucket.available_tokens() == 99


async def test_token_bucket_refills_with_elapsed_time(fake_clock):
    bucket = TokenBucket(RateLimitConfig(max_tokens=100, refill_rate=10.0, window_seconds=10.0))
    assert await bucket.acquire(50) == 0.0
    assert bucket.tokens == 50.0
    # Partial refill: 2s at 10/s adds 20 -> 70 (the contract's "2s -> 70.0").
    fake_clock.advance(2.0)
    assert bucket.available_tokens() == 70
    # Three more seconds: 70 + 30 == max -> refill lands exactly on the cap.
    fake_clock.advance(3.0)
    assert bucket.available_tokens() == 100
    # Cap holds: further elapsed time never pushes tokens above max_tokens.
    fake_clock.advance(2.0)
    assert bucket.available_tokens() == 100


async def test_token_bucket_acquire_waits_when_insufficient(fake_clock):
    bucket = TokenBucket(RateLimitConfig(max_tokens=10, refill_rate=10.0, window_seconds=10.0))
    assert await bucket.acquire(10) == 0.0
    assert bucket.tokens == 0.0
    # Empty bucket: acquire(5) must sleep exactly 5/10 == 0.5s, then consume
    # the tokens refilled by that elapsed time.
    wait = await bucket.acquire(5)
    assert wait == 0.5
    assert fake_clock.sleeps == [0.5]
    # OBSERVED: the 5 refilled tokens are exactly consumed by this acquire
    # (contract idealized "tokens finais == 5.0" — divergence declared in the
    # module docstring).
    assert bucket.tokens == 0.0
    assert bucket.available_tokens() == 0
    # Refill resumes from the empty bucket once the clock advances again.
    fake_clock.advance(0.5)
    assert bucket.available_tokens() == 5


async def test_rate_limiter_categories_are_isolated(fake_clock):
    limiter = RateLimiter()
    market = EndpointCategory.MARKET_DATA
    clob = EndpointCategory.CLOB_GENERAL
    assert limiter.buckets[market] is not limiter.buckets[clob]

    market_max = RATE_LIMITS[market].max_tokens
    clob_max = RATE_LIMITS[clob].max_tokens
    # Sanity pin of the Polymarket domain constants read from the module (L-0002).
    assert market_max == 200
    assert clob_max == 5000

    assert await limiter.acquire(market, tokens=market_max) == 0.0  # exhaust MARKET_DATA
    status = limiter.get_status()
    assert status[market.value]["available_tokens"] == 0
    assert status[clob.value]["available_tokens"] == clob_max  # CLOB untouched, still full

    # Functional isolation: CLOB acquires instantly even with MARKET_DATA drained.
    assert await limiter.acquire(clob, tokens=1000) == 0.0
    status = limiter.get_status()
    assert status[market.value]["available_tokens"] == 0
    assert status[clob.value]["available_tokens"] == clob_max - 1000


async def test_rate_limiter_applies_429_backoff(fake_clock):
    limiter = RateLimiter()
    cat = EndpointCategory.MARKET_DATA
    assert limiter.get_status()[cat.value]["is_throttled"] is False

    await limiter.handle_429_error(cat)  # no retry_after -> arms 1.0s
    assert limiter.get_status()[cat.value]["backoff_remaining_sec"] == 1.0
    assert limiter.get_status()[cat.value]["is_throttled"] is True

    # acquire() while the backoff is armed waits exactly the remaining window.
    # Under the fake clock the wait is exact (module docstring).
    t_before = fake_clock.t
    wait = await limiter.acquire(cat)
    assert wait == 1.0
    assert fake_clock.t == t_before + 1.0  # the fake sleep advanced the clock
    assert fake_clock.sleeps == [1.0]

    # Backoff consumed: the next acquire pays no backoff wait.
    assert await limiter.acquire(cat) == 0.0
    assert limiter.get_status()[cat.value]["is_throttled"] is False


async def test_rate_limiter_backoff_doubles_then_caps_at_60(fake_clock):
    limiter = RateLimiter()
    cat = EndpointCategory.GAMMA_API
    # Frozen clock: each successive 429 doubles the remaining backoff until
    # the 60s cap absorbs it (7th call: min(64, 60) == 60; 8th stays 60).
    series = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]
    for call, expected in enumerate(series, start=1):
        await limiter.handle_429_error(cat)
        status = limiter.get_status()[cat.value]
        assert status["backoff_remaining_sec"] == expected, (
            f"429 #{call}: expected {expected}s, got {status['backoff_remaining_sec']}s"
        )
        assert status["is_throttled"] is True

    # Once the cap window elapses on the clock, throttling clears.
    fake_clock.advance(60.0)
    status = limiter.get_status()[cat.value]
    assert status["backoff_remaining_sec"] == 0.0
    assert status["is_throttled"] is False


async def test_rate_limiter_retry_after_honored(fake_clock):
    limiter = RateLimiter()
    cat = EndpointCategory.DATA_API
    await limiter.handle_429_error(cat, retry_after=30)
    status = limiter.get_status()[cat.value]
    assert status["backoff_remaining_sec"] == 30.0  # honored verbatim, not doubled
    assert status["is_throttled"] is True

    # acquire() waits exactly the server-provided window.
    t_before = fake_clock.t
    wait = await limiter.acquire(cat)
    assert wait == 30.0
    assert fake_clock.t == t_before + 30.0
    assert fake_clock.sleeps == [30.0]


async def test_rate_limiter_reset_backoff_single_and_all(fake_clock):
    limiter = RateLimiter()
    cat_a = EndpointCategory.MARKET_DATA
    cat_b = EndpointCategory.GAMMA_API
    await limiter.handle_429_error(cat_a)
    await limiter.handle_429_error(cat_b)
    status = limiter.get_status()
    assert status[cat_a.value]["is_throttled"] is True
    assert status[cat_b.value]["is_throttled"] is True

    # Single reset: only cat_a is cleared, cat_b keeps its backoff.
    limiter.reset_backoff(cat_a)
    status = limiter.get_status()
    assert status[cat_a.value]["is_throttled"] is False
    assert status[cat_a.value]["backoff_remaining_sec"] == 0.0
    assert status[cat_b.value]["is_throttled"] is True

    # Re-arm cat_a, then reset_backoff() with no argument clears every category.
    await limiter.handle_429_error(cat_a)
    assert limiter.get_status()[cat_a.value]["is_throttled"] is True
    limiter.reset_backoff()
    status = limiter.get_status()
    assert status[cat_a.value]["is_throttled"] is False
    assert status[cat_b.value]["is_throttled"] is False


async def test_rate_limiter_get_status_reflects_throttling(fake_clock):
    limiter = RateLimiter()
    cat = EndpointCategory.MARKET_DATA
    config = RATE_LIMITS[cat]

    status = limiter.get_status()
    assert set(status) == {c.value for c in EndpointCategory}  # every category exposed
    before = status[cat.value]
    assert before["is_throttled"] is False
    assert before["backoff_remaining_sec"] == 0.0
    assert before["available_tokens"] == config.max_tokens
    assert before["max_tokens"] == config.max_tokens
    assert before["refill_rate_per_sec"] == config.refill_rate

    await limiter.handle_429_error(cat)
    during = limiter.get_status()[cat.value]
    assert during["is_throttled"] is True
    assert during["backoff_remaining_sec"] == 1.0
    assert during["available_tokens"] == config.max_tokens  # backoff consumes no tokens
    assert during["max_tokens"] == config.max_tokens
    assert during["refill_rate_per_sec"] == config.refill_rate

    fake_clock.advance(1.0)
    after = limiter.get_status()[cat.value]
    assert after["is_throttled"] is False
    assert after["backoff_remaining_sec"] == 0.0


async def test_rate_limiter_skips_backoff_when_retry_disabled(fake_clock):
    limiter = RateLimiter()
    cat = EndpointCategory.MARKET_DATA
    await limiter.handle_429_error(cat)  # arms 1.0s backoff
    assert limiter.get_status()[cat.value]["is_throttled"] is True

    # retry_on_429=False bypasses the armed backoff entirely: no sleep, no wait.
    t_before = fake_clock.t
    assert await limiter.acquire(cat, retry_on_429=False) == 0.0
    assert fake_clock.t == t_before
    assert fake_clock.sleeps == []

    # The backoff stays armed: a later acquire WITH retry honors it.
    assert await limiter.acquire(cat, retry_on_429=True) == 1.0
    assert limiter.get_status()[cat.value]["is_throttled"] is False


def test_get_rate_limiter_returns_singleton(fake_clock):
    first = get_rate_limiter()
    second = get_rate_limiter()
    assert isinstance(first, RateLimiter)
    assert first is second
