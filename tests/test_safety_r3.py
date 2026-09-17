"""
R3 hardening tests for SafetyLimits.validate_order (human channel, item 67).

Pins the target behavior decided on 2026-09-16:
1. Invalid side (anything not BUY/SELL after strip().upper()) is REJECTED
   with an actionable message instead of silently falling into the SELL
   branch (defense-in-depth: validate_order can be called directly,
   bypassing the tool-layer validation in trading.py).
2. Over-sell beyond an existing position counts the excess as NEW short
   exposure (previously clamped away, understating total exposure and
   hiding real risk from the total-exposure cap).
"""

import pytest

from polymarket_mcp.utils.safety_limits import (
    MarketData,
    OrderRequest,
    Position,
    SafetyLimits,
)


def make_limits(max_order_size_usd=1_000.0, max_total_exposure_usd=1_000.0):
    return SafetyLimits(
        max_order_size_usd=max_order_size_usd,
        max_total_exposure_usd=max_total_exposure_usd,
        max_position_size_per_market=10_000.0,
        min_liquidity_required=100.0,
        max_spread_tolerance=0.5,
        require_confirmation_above_usd=500.0,
    )


def make_position(token_id, market_id, size, avg_price=0.5, current_price=0.5):
    return Position(
        token_id=token_id,
        market_id=market_id,
        size=size,
        avg_price=avg_price,
        current_price=current_price,
        unrealized_pnl=0.0,
    )


def make_order(token_id, price, size, side, market_id=None):
    return OrderRequest(
        token_id=token_id, price=price, size=size, side=side, market_id=market_id
    )


def make_market_data():
    return MarketData(
        market_id="m1",
        token_id="tok-a",
        best_bid=0.45,
        best_ask=0.55,
        bid_liquidity=1_000.0,
        ask_liquidity=1_000.0,
        total_volume=100_000.0,
    )


class TestInvalidSideRejected:
    """SEC-R3-S1: invalid side never reaches the SELL branch."""

    @pytest.mark.parametrize("bad_side", ["HOLD", "buy_sell", "", "SHORT", "Long"])
    def test_unknown_side_rejected_with_actionable_error(self, bad_side):
        limits = make_limits()
        positions = [make_position("tok-a", "m1", size=1_000.0)]  # 500.0 USD

        ok, error = limits.validate_order(
            make_order(token_id="tok-a", price=0.5, size=100.0, side=bad_side),
            positions,
            make_market_data(),
        )

        assert ok is False
        assert error is not None
        assert "Invalid side" in error
        assert bad_side in error

    def test_non_string_side_rejected(self):
        limits = make_limits()

        ok, error = limits.validate_order(
            make_order(token_id="tok-a", price=0.5, size=100.0, side=123),
            [],
            make_market_data(),
        )

        assert ok is False
        assert error is not None
        assert "Invalid side" in error

    @pytest.mark.parametrize("noisy", ["buy ", " BUY", "Sell", " sell\t"])
    def test_whitespace_or_case_normalized_side_accepted(self, noisy):
        """Strip+upper normalization: ' buy' still means BUY (not SELL)."""
        limits = make_limits(max_total_exposure_usd=10_000.0)

        ok, error = limits.validate_order(
            make_order(token_id="tok-new", price=0.5, size=100.0, side=noisy),
            [],
            make_market_data(),
        )

        assert (ok, error) == (True, None)


class TestOverSellCountsAsShort:
    """SEC-R3-S2: over-sell beyond the held position adds short exposure."""

    def test_oversell_increases_exposure_and_hits_cap(self):
        """Sell 2000 shares (1000 USD) holding 400 USD position: closing 400 +
        shorting 600 = net +600 -> total 1000-400+600=1200 > cap 1000 -> reject.
        (Pre-R3 the reduction was clamped to 400, giving 600 <= cap -> pass:
        the over-sell short was hidden from the cap.)"""
        limits = make_limits(max_order_size_usd=1_000.0, max_total_exposure_usd=1_000.0)
        positions = [
            make_position("tok-a", "m1", size=800.0),  # 400.0 USD
            make_position("tok-d", "m2", size=1_200.0),  # 600.0 USD -> total 1000
        ]

        ok, error = limits.validate_order(
            make_order(token_id="tok-a", price=0.5, size=2_000.0, side="SELL"),
            positions,
            make_market_data(),
        )

        assert ok is False
        assert error is not None
        assert "exceeding maximum" in error

    def test_full_close_of_position_unchanged(self):
        """Selling exactly the held value: net reduction = position value
        (no over-sell term) — matches the pre-R3 behavior."""
        limits = make_limits(max_total_exposure_usd=1_000.0)
        positions = [make_position("tok-a", "m1", size=1_000.0)]  # 500.0 USD

        ok, error = limits.validate_order(
            make_order(token_id="tok-a", price=0.5, size=1_000.0, side="SELL"),
            positions,
            make_market_data(),
        )

        assert (ok, error) == (True, None)

    def test_partial_sell_within_position_unchanged(self):
        """Partial sell (order value < position value): pure reduction."""
        limits = make_limits(max_total_exposure_usd=1_000.0)
        positions = [
            make_position("tok-a", "m1", size=1_000.0),  # 500.0 USD
            make_position("tok-d", "m2", size=1_000.0),  # 500.0 USD -> total 1000
        ]

        ok, error = limits.validate_order(
            make_order(token_id="tok-a", price=0.5, size=400.0, side="SELL"),
            positions,
            make_market_data(),
        )

        assert (ok, error) == (True, None)


class TestFiniteOrderValue:
    """SEC-R3-S3 (pairs with flipped SEC-ADVR-A1): non-finite order values
    are rejected at the safety layer (defense-in-depth)."""

    @pytest.mark.parametrize("bad_size", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_size_rejected(self, bad_size):
        limits = make_limits()

        ok, error = limits.validate_order(
            make_order(token_id="tok-a", price=0.5, size=bad_size, side="BUY"),
            [],
            make_market_data(),
        )

        assert ok is False
        assert error is not None
        assert "finite" in error

    def test_nan_price_rejected(self):
        limits = make_limits()

        ok, error = limits.validate_order(
            make_order(token_id="tok-a", price=float("nan"), size=10.0, side="BUY"),
            [],
            make_market_data(),
        )

        assert ok is False
        assert error is not None
        assert "finite" in error
