"""Per-market over-sell exposure suite (T-0350).

Closes the inconsistency left by the R3 fix: the TOTAL-exposure cap counts an
over-sell beyond the held position as NEW short exposure ("understating it
would hide real risk from the total-exposure limit" -- safety_limits.py R3
comment, merged PR #56), but the PER-MARKET cap silently omits the over-sell
term for SELL orders inside the order's own market.

Proven 1st-hand by the curator preflight (main dd55223):

    limits(per_market=700), positions=[Position(tok-a, m1, 1000 sh @0.5)]  # 500 USD
    order = OrderRequest(tok-a, 0.5, 3600 sh, SELL, market_id="m1")        # 1800 USD
    PRE-FIX  -> (True, None)     # per-market: 500 - min(1800,500) = 0 <= 700
                                 # (the 1300 USD over-sell short is INVISIBLE)
    POST-FIX -> (False, "...$1300.00, exceeding per-market maximum $700.00")

No existing pin covers per-market over-sell (grep proven): test_safety_limits
covers short-in-OTHER-market (:327-349) and partial-in-own-market (:351-370);
test_safety_r3 pins over-sell ONLY at the total level (TestOverSellCountsAsShort);
test_safety_adversarial's remaining 6 xfails are A2 (id-format), B1x2 (batch/
smart-trade ratchet), B2 (stale concurrent snapshot), C1 (demo places orders),
D2 (config disables safety) -- none cover per-market over-sell.

Tests 2-6 are identity/permanence guards: they hold BEFORE and AFTER the fix
(the fix only changes the over-sell accounting, never the identity cases).
"""

from polymarket_mcp.utils.safety_limits import (
    MarketData,
    OrderRequest,
    Position,
    SafetyLimits,
)


def make_limits(
    max_order_size_usd=2000.0,
    max_total_exposure_usd=5000.0,
    max_position_size_per_market=700.0,
):
    return SafetyLimits(
        max_order_size_usd=max_order_size_usd,
        max_total_exposure_usd=max_total_exposure_usd,
        max_position_size_per_market=max_position_size_per_market,
        min_liquidity_required=0.0,
        max_spread_tolerance=1.0,
        require_confirmation_above_usd=10_000.0,
    )


def make_position(token_id, market_id, size):
    """Position worth size*0.5 USD (avg price 0.5, current price 0.5)."""
    return Position(
        token_id=token_id,
        market_id=market_id,
        size=size,
        avg_price=0.5,
        current_price=0.5,
        unrealized_pnl=0.0,
    )


def make_market_data(market_id="m1"):
    return MarketData(
        market_id=market_id,
        token_id="tok-a",
        best_bid=0.49,
        best_ask=0.51,
        bid_liquidity=5000.0,
        ask_liquidity=5000.0,
        total_volume=10000.0,
    )


# ---------------------------------------------------------------------------
# The over-sell case (the bug this fatia fixes -- RED before the fix)
# ---------------------------------------------------------------------------


def test_oversell_in_own_market_counts_as_short_and_hits_per_market_cap():
    """SELL 3600 shares (1800 USD) holding 500 USD in the SAME market:
    closing 500 + shorting 1300 = per-market exposure 1300 > cap 700 -> reject.
    (Pre-fix the per-market branch clamped the reduction to 500, giving 0
    <= 700 -> pass: the over-sell short was hidden from the per-market cap.)"""
    limits = make_limits(max_position_size_per_market=700.0)
    positions = [make_position("tok-a", "m1", size=1000.0)]  # 500.0 USD

    ok, error = limits.validate_order(
        OrderRequest(token_id="tok-a", price=0.5, size=3600.0, side="SELL",
                     market_id="m1"),
        positions,
        make_market_data(),
    )

    assert ok is False
    assert error is not None
    assert "per-market maximum" in error


def test_oversell_within_cap_passes():
    """Same over-sell (1300 USD short) with a cap of 1400: the short is
    COUNTED but fits -> pass. The fix changes the accounting, not the
    prohibition (identity: pre-fix this also passed, for a wrong reason)."""
    limits = make_limits(max_position_size_per_market=1400.0)
    positions = [make_position("tok-a", "m1", size=1000.0)]

    ok, error = limits.validate_order(
        OrderRequest(token_id="tok-a", price=0.5, size=3600.0, side="SELL",
                     market_id="m1"),
        positions,
        make_market_data(),
    )

    assert (ok, error) == (True, None)


# ---------------------------------------------------------------------------
# Identity guards (hold before AND after the fix)
# ---------------------------------------------------------------------------


def test_full_close_unchanged():
    """Selling exactly the held value in the own market: pure reduction."""
    limits = make_limits()
    positions = [make_position("tok-a", "m1", size=1000.0)]  # 500 USD

    ok, error = limits.validate_order(
        OrderRequest(token_id="tok-a", price=0.5, size=1000.0, side="SELL",
                     market_id="m1"),
        positions,
        make_market_data(),
    )

    assert (ok, error) == (True, None)


def test_partial_sell_within_position_unchanged():
    """Partial sell (order value < position value): pure reduction."""
    limits = make_limits()
    positions = [make_position("tok-a", "m1", size=1000.0)]

    ok, error = limits.validate_order(
        OrderRequest(token_id="tok-a", price=0.5, size=400.0, side="SELL",
                     market_id="m1"),
        positions,
        make_market_data(),
    )

    assert (ok, error) == (True, None)


def test_short_in_other_market_counts_full_value():
    """SELL of a token held in ANOTHER market: no existing position inside the
    order's market -> the full order value counts (permanence of the sibling
    pin test_safety_limits.py:327-349, different numbers: 1600 sh = 800 USD
    vs cap 700)."""
    limits = make_limits(max_position_size_per_market=700.0)
    positions = [make_position("tok-a", "m1", size=1000.0)]

    ok, error = limits.validate_order(
        OrderRequest(token_id="tok-a", price=0.5, size=1600.0, side="SELL",
                     market_id="m2"),
        positions,
        make_market_data(market_id="m2"),
    )

    assert ok is False
    assert error is not None
    assert "per-market maximum" in error


def test_total_level_oversell_r3_unchanged():
    """The R3 total-level over-sell accounting is untouched: with a HIGH
    per-market cap the same over-sell is still rejected by the TOTAL cap
    (message 'exceeding maximum' WITHOUT 'per-market')."""
    limits = SafetyLimits(
        max_order_size_usd=2000.0,
        max_total_exposure_usd=1000.0,
        max_position_size_per_market=10_000.0,
        min_liquidity_required=0.0,
        max_spread_tolerance=1.0,
        require_confirmation_above_usd=10_000.0,
    )
    positions = [
        make_position("tok-a", "m1", size=1000.0),  # 500 USD
        make_position("tok-d", "m2", size=1200.0),  # 600 USD -> total 1100
    ]

    ok, error = limits.validate_order(
        OrderRequest(token_id="tok-a", price=0.5, size=2000.0, side="SELL",
                     market_id="m1"),
        positions,
        make_market_data(),
    )

    assert ok is False
    assert error is not None
    assert "exceeding maximum" in error
    assert "per-market" not in error
