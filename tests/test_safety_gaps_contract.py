"""
Offline flip-contract suite for the item 112 safety-layer gaps (T-0339;
REQUER-HUMANO item 112): four xfail(strict=True) tests pin the defects the
human fix will consume.

Provenance of the probes (curator 2026-09-19, main c7338f4, environment
PYTHONPATH=src .venv/bin/python; re-proven first-hand on this branch the
same day - all four gaps reproduce deterministically):

- Gap 1 (negative size accepted): validate_order(OrderRequest(size=-1.0,
  price=0.5, side='BUY')) returns (True, None). The finite guard at
  safety_limits.py:118-121 (isinstance + math.isfinite) only catches
  NaN/inf - the SIGN is never validated; order_value_usd = -0.50 is far
  below max_order_size_usd and passes every value/exposure check.
- Gap 2 (zero size accepted): size=0.0 -> (True, None); a no-op order
  "validates".
- Gap 3 (size=None -> TypeError, not a validation error): the multiply
  order.size * order.price at safety_limits.py:117 raises
  "TypeError: unsupported operand type(s) for *: 'NoneType' and 'float'"
  BEFORE the isinstance finite guard at :118 can fire. Fix prescribed by
  item 112: check isinstance(order.size, (int, float)) BEFORE the
  multiply and return (False, "Order value must be finite, got size=None
  price=0.5") - the SAME message format the R3 finite guard uses at
  :119-121.
- Gap 4 (whitespace side silently routes suggest_order_price to the SELL
  branch): suggest_order_price('m1', ' buy ', 100.0, 'aggressive', 'Yes')
  returns suggested_price=0.49 (best_bid) with reasoning "Aggressive sell
  at best bid 0.4900 ..." - side.upper() at trading.py:590 does not
  strip, so ' BUY ' matches neither 'BUY' nor 'SELL' and falls into the
  else SELL branch at :630; the BUY intent is silently lost.
  create_limit_order validates STRICTLY (:183: "Side must be BUY or
  SELL, got ...") - inconsistent UX between the tool and the suggestion.
  Fix prescribed by item 112: side.strip().upper() + strict validation
  identical to :183.

The R3 side-validation inside validate_order (merged PR #56) already
works - side=' buy ' -> (True, None) there; its permanence pin lives in
tests/test_safety_r3.py and is NOT duplicated here (P-0113). The gaps of
this suite are the SIZE gaps and the suggest_order_price whitespace gap,
both OUTSIDE the R3 scope.

These 4 xfails are the flip contract: each body asserts the CORRECT
behavior and fails against the current code (proof of the gap); when the
item 112 fix lands, the xfail flips to XPASS (strict -> suite RED) and
the fix consumes the flip. Never loosen a strict xfail to "pass" - an
accidental XPASS means the code state changed and item 112 needs
re-derivation.

Defense-in-depth note: every real trade funnels through
create_limit_order (trading.py:411/:471) which validates size>0 and side
strictly BEFORE this layer - the validate_order gaps are the same vector
class R3 documented ("direct callers of validate_order bypass the
tool-layer checks", :132-134). The fix is REQUER-HUMANO item 112 (human
channel); this suite never touches src/.

Hermeticity: zero network, zero sleep. The trading test uses the
house-pattern duck-typed fakes (fail-loud seams, P-0031) adapted from
test_trading_gaps_offline.py:104-175 (trimmed to the seams
suggest_order_price touches; book bids='0.49'/asks='0.51', no tick_size
field -> legacy identity behavior). The SafetyLimits/MarketData fixtures
are the REAL classes with every cap loose EXCEPT the gap under test, so
the spread/liquidity/exposure limits can never mask the size reason
(expected rejection reason is ONLY the size).
"""

import pytest

from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.safety_limits import MarketData, OrderRequest, SafetyLimits

# ---------------------------------------------------------------------------
# Shared fixtures (anti-masking: all caps loose except the gap under test)
# ---------------------------------------------------------------------------


def make_limits():
    """Real SafetyLimits with galaxy-scale caps: the spread (~2.04% << 100%),
    liquidity (2e6 >> 0.0), order-size (0.5 << 1e9) and exposure checks can
    NEVER fire - the only possible rejection reason is the size defect under
    test."""
    return SafetyLimits(
        max_order_size_usd=1e9,
        max_total_exposure_usd=1e9,
        max_position_size_per_market=1e9,
        min_liquidity_required=0.0,
        max_spread_tolerance=1.0,
        require_confirmation_above_usd=1e12,
    )


def make_market_data():
    """Two-sided, liquid, tight-spread market data (spread ~2.04% << the
    100% tolerance of make_limits)."""
    return MarketData(
        market_id="m1",
        token_id="tok",
        best_bid=0.49,
        best_ask=0.50,
        bid_liquidity=1e6,
        ask_liquidity=1e6,
        total_volume=1e6,
    )


class FakeConfig:
    """Minimal stand-in for PolymarketConfig (house pattern,
    test_trading_gaps_offline.py:104-110)."""

    def __init__(self, autonomous: bool = True, threshold: float = 1_000_000_000.0):
        self.ENABLE_AUTONOMOUS_TRADING = autonomous
        self.REQUIRE_CONFIRMATION_ABOVE_USD = threshold


class FakeLimiter:
    """No-op rate limiter: the real singleton sleeps between calls (L-0014)."""

    def __init__(self):
        self.calls = []

    async def acquire(self, category):
        self.calls.append(category)
        return 0.0


class FakeClient:
    """Duck-typed client stub trimmed to the seams suggest_order_price
    touches (fail-loud pattern P-0031, adapted from
    test_trading_gaps_offline.py:127-189). Endpoints never touch the
    network; an unexpected call signature fails with TypeError at call
    time (structural pin, L-0121)."""

    def __init__(self):
        self.market = {
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes"},
                {"token_id": "no-token", "outcome": "No"},
            ],
            "volume": "1000000",
        }
        self.book = {
            "bids": [{"price": "0.49", "size": "100000"}],
            "asks": [{"price": "0.51", "size": "100000"}],
        }
        self.get_market_calls = []
        self.get_orderbook_calls = []

    async def get_market(self, market_id):
        self.get_market_calls.append(market_id)
        return self.market

    async def get_orderbook(self, token_id):
        self.get_orderbook_calls.append(token_id)
        return self.book


def build_tools():
    """REAL SafetyLimits (loose caps) + the fail-loud stub."""
    client = FakeClient()
    tools = TradingTools(client, make_limits(), FakeConfig())
    tools.rate_limiter = FakeLimiter()
    return tools, client


# ---------------------------------------------------------------------------
# The 4 xfail-strict flip contracts for REQUER-HUMANO item 112
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Gap 1: negative size is accepted by validate_order - the finite "
        "guard only catches NaN/inf, the sign is never validated "
        "(REQUER-HUMANO item 112)"
    ),
)
def test_negative_size_is_rejected_by_validate_order():
    """Gap 1 - safety_limits.py:117-126.

    The finite guard (:118-121) only checks isinstance + math.isfinite, so
    order_value_usd = -1.0 * 0.5 = -0.50 is finite and far below
    max_order_size_usd; the sign is never validated and every remaining
    check passes -> today: (True, None).

    Post-fix (item 112): (False, <reason>) with 'size' in the message
    (case-insensitive), e.g. the R3 finite-guard format "Order value must
    be finite, got size=-1.0 price=0.5" or an explicit positive-size
    check. The caps stay loose so the rejection reason can ONLY be the
    size defect."""
    limits = make_limits()

    ok, error = limits.validate_order(
        OrderRequest(token_id="tok", price=0.5, size=-1.0, side="BUY"),
        [],
        make_market_data(),
    )

    assert ok is False
    assert error is not None
    assert "size" in error.lower()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Gap 2: zero size is accepted by validate_order - a no-op order "
        "passes every safety check (REQUER-HUMANO item 112)"
    ),
)
def test_zero_size_is_rejected_by_validate_order():
    """Gap 2 - safety_limits.py:117-126.

    size=0.0 -> order_value_usd = 0.0, finite and below every cap; the
    zero-signature order "validates" -> today: (True, None).

    Post-fix (item 112): (False, <reason>) with 'size' in the message
    (case-insensitive). The caps stay loose so the rejection reason can
    ONLY be the size defect."""
    limits = make_limits()

    ok, error = limits.validate_order(
        OrderRequest(token_id="tok", price=0.5, size=0.0, side="BUY"),
        [],
        make_market_data(),
    )

    assert ok is False
    assert error is not None
    assert "size" in error.lower()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Gap 3: size=None raises TypeError (the multiply precedes the "
        "finite guard) instead of returning a validation error "
        "(REQUER-HUMANO item 112)"
    ),
)
def test_none_size_returns_validation_error_not_type_error():
    """Gap 3 - safety_limits.py:117-121.

    order_value_usd = order.size * order.price (:117) raises
    "TypeError: unsupported operand type(s) for *: 'NoneType' and 'float'"
    BEFORE the isinstance finite guard (:118) can fire - the guard exists
    but is unreachable for the None size.

    Post-fix (item 112): the isinstance(order.size, (int, float)) check
    happens BEFORE the multiply and returns the R3-format validation
    error at :119-121 - (False, "Order value must be finite, got size=None
    price=0.5"). So the correct behavior is a TUPLE, never an exception:
    if a TypeError is raised the test fails explicitly with the reason;
    if a tuple is returned it must be (False, <msg>) with 'finite' in the
    message (same format as the R3 guard)."""
    limits = make_limits()

    try:
        result = limits.validate_order(
            OrderRequest(token_id="tok", price=0.5, size=None, side="BUY"),
            [],
            make_market_data(),
        )
    except TypeError as exc:
        pytest.fail(
            "size=None raised TypeError instead of returning a validation "
            f"error: {exc}"
        )

    ok, error = result
    assert ok is False
    assert error is not None
    assert "finite" in error


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Gap 4: whitespace side ' buy ' silently routes suggest_order_price "
        "to the SELL branch - the BUY intent is lost (REQUER-HUMANO item 112)"
    ),
)
async def test_suggest_order_price_whitespace_side_uses_buy_semantics():
    """Gap 4 - trading.py:590 (side.upper() without strip) falling into the
    else SELL branch at :630; contrast with the STRICT tool-layer
    validation in create_limit_order (:183: "Side must be BUY or SELL, got
    ...").

    suggest_order_price('m1', ' buy ', 100.0, 'aggressive', 'Yes') must
    apply BUY semantics: aggressive BUY prices AT THE ASK (0.51 in the
    house book). Today side_upper=' BUY ' matches neither 'BUY' nor
    'SELL', so the SELL branch runs: suggested_price=0.49 (best_bid) with
    reasoning "Aggressive sell at best bid 0.4900 ..." - the BUY intent is
    silently lost.

    Post-fix (item 112: side.strip().upper() + strict validation identical
    to :183): the suggestion uses BUY semantics - suggested_price == 0.51
    (best ask) with a BUY reasoning. Secondary pin: the reasoning must
    reflect a BUY (it does today: 'Aggressive sell at best bid 0.4900')."""
    tools, _client = build_tools()

    result = await tools.suggest_order_price("m1", " buy ", 100.0, "aggressive", "Yes")

    assert result["success"] is True
    # BUY aggressive = best ask 0.51 (the BUY intent must survive the
    # whitespace); today the silent SELL branch returns best bid 0.49.
    assert result["suggested_price"] == pytest.approx(0.51)
    assert "buy" in result["reasoning"].lower()
