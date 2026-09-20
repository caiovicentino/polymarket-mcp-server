"""Offline regression suite for non-finite tick_size values (trading tools).

The tick_size field arrives on the wire as a string. The CLOB never sends
``nan``/``inf`` in practice, but a broken server/proxy/stub can - and the
contract of ``parse_tick_size`` promises ``None`` for UNUSABLE values
("non-numeric / non-positive"). The OBSERVED pre-fix behavior violates that
contract:

- tick_size="nan" -> ``Decimal('nan')`` is built, then the ``tick <= 0``
  comparison RAISES ``decimal.InvalidOperation`` (NaN comparisons are
  trapped) from OUTSIDE the try block -> both ``create_limit_order`` and
  ``suggest_order_price`` return the cryptic error envelope
  ``"[<class 'decimal.InvalidOperation'>]"``.
- tick_size="inf" -> ``Decimal('Infinity')`` is returned as a VALID tick ->
  the limit-order range check fails with the nonsense message
  "outside the valid range [Infinity, -inf]" and the suggestion path dies
  with the same cryptic InvalidOperation.

The fix makes non-finite values unusable (None -> legacy no-alignment
behavior, exactly like an absent tick_size field). Asserts follow the code
as observed (probed offline), not the docstrings (L-0020/L-0090). Source of
truth:

- parse_tick_size (src/polymarket_mcp/tools/trading.py):
  * "nan" / "inf" / float('nan') -> None (unusable).
  * "-inf" / "0" / "-0.01" / "not-a-number" -> None (unchanged pre-fix).
  * "1E+1000000000" (finite but huge) still PARSES to a Decimal - the
    huge-tick range rejection is the caller's job and is OUT of this fix's
    scope (anti-over-fix: NUNCA retornar None para valores finitos).
- create_limit_order / suggest_order_price with a book whose tick_size is
  "nan"/"inf": the order POSTS (suggested price is the legacy mid 0.525 on
  a 0.52/0.53 book) - identical to the pinned tickless fixtures
  (test_trading_orders_offline.py).

Zero network, zero sleep: the rate limiter is duck-typed no-op (L-0014),
SafetyLimits is the REAL class, and the client is a recording fake.
Fakes are self-contained here (house rule: never import fakes from another
test module).
"""
from decimal import Decimal

from polymarket_mcp.tools.trading import TradingTools, parse_tick_size
from polymarket_mcp.utils.safety_limits import SafetyLimits


class FakeConfig:
    """Minimal stand-in for PolymarketConfig."""

    def __init__(self, autonomous: bool = True, threshold: float = 1_000_000_000.0):
        self.ENABLE_AUTONOMOUS_TRADING = autonomous
        self.REQUIRE_CONFIRMATION_ABOVE_USD = threshold


class FakeLimiter:
    """No-op rate limiter: the real singleton sleeps between calls (L-0014)."""

    async def acquire(self, category):
        return 0.0

    async def handle_429_error(self, *args, **kwargs):
        return None


class FakeClient:
    """Duck-typed client that records the order the tool submits."""

    def __init__(self, book: dict):
        self.book = book
        self.posted = []

    async def get_market(self, market_id):
        return {
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes"},
                {"token_id": "no-token", "outcome": "No"},
            ],
        }

    async def get_orderbook(self, token_id):
        return self.book

    async def get_positions(self):
        return []

    async def post_order(self, **kwargs):
        self.posted.append(kwargs)
        return {"orderID": "order-1", "status": "submitted"}


def _book(tick_raw):
    book = {
        "bids": [{"price": "0.52", "size": "100"}],
        "asks": [{"price": "0.53", "size": "100"}],
    }
    if tick_raw is not None:
        book["tick_size"] = tick_raw
    return book


def build_tools(tick_raw):
    limits = SafetyLimits(
        max_order_size_usd=1_000.0,
        max_total_exposure_usd=5_000.0,
        max_position_size_per_market=2_000.0,
        min_liquidity_required=10.0,
        max_spread_tolerance=0.05,
        require_confirmation_above_usd=1_000_000_000.0,
    )
    client = FakeClient(_book(tick_raw))
    tools = TradingTools(client, limits, FakeConfig())
    tools.rate_limiter = FakeLimiter()
    return tools, client


# --- parse_tick_size ---------------------------------------------------------


def test_parse_tick_size_nan_is_unusable():
    """tick_size "nan" must decode to None (unusable), not raise or return NaN.

    RED pre-fix: the NaN comparison raised InvalidOperation from outside the
    try block, surfacing as the cryptic "[<class 'decimal.InvalidOperation'>]"
    error envelope in both order tools.
    """
    assert parse_tick_size("nan") is None


def test_parse_tick_size_infinity_is_unusable():
    """tick_size "inf" must decode to None (unusable), not Infinity.

    RED pre-fix: Decimal('Infinity') passed the "> 0" check and the tools
    rejected every price with "outside the valid range [Infinity, -inf]".
    """
    assert parse_tick_size("inf") is None
    assert parse_tick_size("Infinity") is None


def test_parse_tick_size_non_positive_and_malformed_unchanged():
    """Anti-over-fix: the already-None paths keep their exact behavior."""
    assert parse_tick_size("-inf") is None
    assert parse_tick_size("0") is None
    assert parse_tick_size("-0.01") is None
    assert parse_tick_size("not-a-number") is None
    assert parse_tick_size(None) is None


def test_parse_tick_size_huge_finite_still_parses():
    """A finite (huge) tick still parses - the caller range-checks it.

    Out of the fix's scope (register): a finite-but-huge tick is rejected by
    the price-range check in create_limit_order. NUNCA retornar None para
    valores finitos - the docstring's "unusable" contract covers non-numeric,
    non-positive and NON-FINITE values only.
    """
    assert parse_tick_size("1E+1000000000") == Decimal("1E+1000000000")
    assert parse_tick_size(0.01) == Decimal("0.01")


# --- tool-level legacy behavior with non-finite ticks ------------------------


async def test_limit_order_nan_tick_uses_legacy_behavior():
    """A "nan" tick must behave like a TICKLESS book: the order posts.

    RED pre-fix: the tool returned the cryptic InvalidOperation envelope and
    never reached post_order.
    """
    tools, client = build_tools("nan")
    result = await tools.create_limit_order(
        market_id="0xcond", side="BUY", price=0.5, size=10.0, outcome="Yes"
    )
    assert result.get("success") is True
    assert result.get("order_id") == "order-1"
    # No alignment was applied: the submitted price is the caller's, verbatim.
    assert client.posted[0]["price"] == 0.5


async def test_suggest_order_price_nan_tick_uses_legacy():
    """A "nan" tick must not break the suggestion: legacy mid 0.525.

    RED pre-fix: the tool returned the cryptic InvalidOperation envelope.
    """
    tools, _client = build_tools("nan")
    result = await tools.suggest_order_price(
        market_id="0xcond", side="BUY", size=10.0, outcome="Yes"
    )
    assert result.get("success") is True
    assert result.get("suggested_price") == 0.525


async def test_limit_order_infinite_tick_uses_legacy_behavior():
    """An "inf" tick must behave like a TICKLESS book: the order posts.

    RED pre-fix: the tool rejected the price with the nonsense range message
    "[Infinity, -inf]" and never reached post_order.
    """
    tools, client = build_tools("inf")
    result = await tools.create_limit_order(
        market_id="0xcond", side="BUY", price=0.5, size=10.0, outcome="Yes"
    )
    assert result.get("success") is True
    assert client.posted[0]["price"] == 0.5


async def test_suggest_order_price_infinite_tick_uses_legacy():
    """An "inf" tick must not break the suggestion: legacy mid 0.525."""
    tools, _client = build_tools("inf")
    result = await tools.suggest_order_price(
        market_id="0xcond", side="BUY", size=10.0, outcome="Yes"
    )
    assert result.get("success") is True
    assert result.get("suggested_price") == 0.525
