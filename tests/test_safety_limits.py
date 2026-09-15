"""
Regression tests for SafetyLimits (src/polymarket_mcp/utils/safety_limits.py) —
the risk gate that decides whether an order may be sent to the exchange.

Covers, 100% offline (stdlib-only module; no network, no env, no randomness):
- validate_order: order-size cap, total-exposure cap (BUY vs SELL, including
  the short branch when selling a token with no existing position),
  per-market cap (applied only when order.market_id is set), liquidity
  minimum, and spread tolerance with the auto_cancel_on_large_spread toggle
- check_exposure over/within the limit (inclusive boundary pinned)
- should_require_confirmation (autonomous off confirms everything; threshold)
- get_position_summary totals and per-market grouping
- create_safety_limits_from_config field mapping

All limits/positions/orders are constructed in-test with explicit values —
no config file, no os.environ. Asserts follow the OBSERVED behavior of the
module (lesson L-0020): this suite is a regression lock, not a new spec; if a
branch diverges from its docstring, the report records it instead of "fixing"
the test to the docstring.
"""
from types import SimpleNamespace

import pytest

from polymarket_mcp.utils.safety_limits import (
    MarketData,
    OrderRequest,
    Position,
    SafetyLimits,
    create_safety_limits_from_config,
)


def make_limits(**overrides) -> SafetyLimits:
    """SafetyLimits with generous passing defaults; each test tightens one knob."""
    defaults = dict(
        max_order_size_usd=1_000.0,
        max_total_exposure_usd=10_000.0,
        max_position_size_per_market=10_000.0,
        min_liquidity_required=100.0,
        max_spread_tolerance=0.5,
        require_confirmation_above_usd=500.0,
    )
    return SafetyLimits(**{**defaults, **overrides})


def make_order(
    token_id="tok-a", price=0.5, size=100.0, side="BUY", market_id=None
) -> OrderRequest:
    return OrderRequest(
        token_id=token_id, price=price, size=size, side=side, market_id=market_id
    )


def make_position(
    token_id,
    market_id,
    size,
    current_price=0.5,
    avg_price=0.5,
    unrealized_pnl=0.0,
) -> Position:
    return Position(
        token_id=token_id,
        market_id=market_id,
        size=size,
        avg_price=avg_price,
        current_price=current_price,
        unrealized_pnl=unrealized_pnl,
    )


def make_market_data(
    market_id="m1",
    token_id="tok-a",
    best_bid=0.45,
    best_ask=0.55,
    bid_liquidity=1_000.0,
    ask_liquidity=1_000.0,
    total_volume=100_000.0,
) -> MarketData:
    return MarketData(
        market_id=market_id,
        token_id=token_id,
        best_bid=best_bid,
        best_ask=best_ask,
        bid_liquidity=bid_liquidity,
        ask_liquidity=ask_liquidity,
        total_volume=total_volume,
    )


def test_validate_order_rejects_oversized_order():
    """size * price above max_order_size_usd is rejected ("exceeds maximum")."""
    limits = make_limits(max_order_size_usd=100.0)

    ok, error = limits.validate_order(
        make_order(price=20.0, size=10.0),  # 200.0 USD > 100.0
        [],
        make_market_data(),
    )

    assert ok is False
    assert error is not None
    assert "exceeds maximum" in error

    # Boundary: value exactly at the cap is allowed (strictly-greater check).
    ok, error = limits.validate_order(
        make_order(price=20.0, size=5.0),  # 100.0 USD == cap
        [],
        make_market_data(),
    )
    assert (ok, error) == (True, None)


def test_validate_order_rejects_exposure_over_total_cap():
    """BUY that pushes total exposure past the cap is rejected."""
    limits = make_limits(max_total_exposure_usd=1_000.0)
    positions = [
        make_position("tok-b", "m2", size=600.0),  # 300.0 USD
        make_position("tok-c", "m3", size=800.0),  # 400.0 USD -> total 700.0
    ]

    ok, error = limits.validate_order(
        make_order(token_id="tok-a", price=0.5, size=700.0),  # 350.0 USD
        positions,
        make_market_data(),
    )

    assert ok is False
    assert error is not None
    assert "exceeding maximum" in error

    # Boundary: BUY that lands exactly on the cap is allowed (<= comparison).
    ok, error = limits.validate_order(
        make_order(token_id="tok-a", price=0.5, size=600.0),  # 300.0 USD
        positions,
        make_market_data(),
    )
    assert (ok, error) == (True, None)


def test_validate_order_sell_reduces_exposure_within_cap():
    """SELL of an existing position (same token_id) reduces exposure and may
    pass even with total exposure exactly at the cap."""
    limits = make_limits(max_order_size_usd=1_000.0, max_total_exposure_usd=1_000.0)
    positions = [
        make_position("tok-a", "m1", size=1_000.0),  # 500.0 USD
        make_position("tok-d", "m2", size=1_000.0),  # 500.0 USD -> total 1000.0 (at cap)
    ]

    ok, error = limits.validate_order(
        make_order(token_id="tok-a", price=0.5, size=400.0, side="SELL"),  # 200.0 USD
        positions,
        make_market_data(),
    )
    assert (ok, error) == (True, None)

    # Reduction is clamped to the position's value: selling more than held
    # cannot push exposure below zero (min(order_value, position.value_usd)).
    ok, error = limits.validate_order(
        make_order(token_id="tok-a", price=0.5, size=1_600.0, side="SELL"),  # 800.0 USD
        positions,
        make_market_data(),
    )
    assert (ok, error) == (True, None)


def test_validate_order_short_sell_increases_exposure():
    """SELL with no existing position in the token is treated as a short:
    exposure INCREASES (module lines 132-137) and the total cap rejects it."""
    limits = make_limits(max_order_size_usd=500.0, max_total_exposure_usd=600.0)
    positions = [make_position("tok-b", "m2", size=800.0)]  # 400.0 USD

    ok, error = limits.validate_order(
        make_order(token_id="tok-x", price=0.5, size=500.0, side="SELL"),  # 250.0 USD
        positions,
        make_market_data(),
    )

    assert ok is False
    assert error is not None
    assert "exceeding maximum" in error

    # Boundary: short SELL that lands exactly on the cap is allowed.
    ok, error = limits.validate_order(
        make_order(token_id="tok-x", price=0.4, size=500.0, side="SELL"),  # 200.0 USD
        positions,
        make_market_data(),
    )
    assert (ok, error) == (True, None)


def test_validate_order_rejects_insufficient_liquidity():
    """total_liquidity below min_liquidity_required is rejected."""
    limits = make_limits(min_liquidity_required=1_000.0)
    order = make_order(price=0.5, size=200.0)  # 100.0 USD, within all other caps

    ok, error = limits.validate_order(
        order,
        [],
        make_market_data(bid_liquidity=300.0, ask_liquidity=400.0),  # 700.0 < 1000.0
    )

    assert ok is False
    assert error is not None
    assert "Insufficient market liquidity" in error

    # Same order passes when liquidity meets the requirement.
    ok, error = limits.validate_order(order, [], make_market_data())
    assert (ok, error) == (True, None)  # default market data has 2000.0 liquidity


def test_validate_order_rejects_wide_spread_with_auto_cancel():
    """spread above max_spread_tolerance with auto_cancel_on_large_spread=True
    rejects the order."""
    limits = make_limits(
        max_spread_tolerance=0.1,
        min_liquidity_required=100.0,
        auto_cancel_on_large_spread=True,
    )

    ok, error = limits.validate_order(
        make_order(price=1.2, size=100.0),  # 120.0 USD, within all other caps
        [],
        make_market_data(best_bid=1.0, best_ask=1.5),  # spread 0.5 > 0.1
    )

    assert ok is False
    assert error is not None
    assert "spread" in error


def test_validate_order_allows_wide_spread_without_auto_cancel():
    """The same wide spread with auto_cancel_on_large_spread=False only logs a
    warning and the order proceeds (warning branch, module line ~186)."""
    limits = make_limits(
        max_spread_tolerance=0.1,
        min_liquidity_required=100.0,
        auto_cancel_on_large_spread=False,
    )

    ok, error = limits.validate_order(
        make_order(price=1.2, size=100.0),
        [],
        make_market_data(best_bid=1.0, best_ask=1.5),
    )

    assert (ok, error) == (True, None)


def test_validate_order_earliest_check_failure_wins():
    """validate_order runs its five checks in order: size, total exposure,
    per-market (only when market_id is set), liquidity, spread — the earliest
    failing check is the one reported."""
    wide_spread = make_market_data(best_bid=1.0, best_ask=1.5)  # spread 0.5

    # Size failure wins over a wide spread.
    limits = make_limits(max_order_size_usd=100.0, min_liquidity_required=100.0)
    ok, error = limits.validate_order(make_order(price=20.0, size=10.0), [], wide_spread)
    assert ok is False
    assert "exceeds maximum" in (error or "")

    # Total-exposure failure wins over a wide spread.
    limits = make_limits(max_total_exposure_usd=1_000.0, min_liquidity_required=100.0)
    positions = [make_position("tok-b", "m2", size=4_000.0)]  # 2000.0 USD
    ok, error = limits.validate_order(
        make_order(token_id="tok-a", price=0.5, size=200.0),  # 2100.0 > 1000.0
        positions,
        wide_spread,
    )
    assert ok is False
    assert "exceeding maximum" in (error or "")

    # Liquidity failure wins over a wide spread.
    limits = make_limits(min_liquidity_required=1_000.0)
    ok, error = limits.validate_order(
        make_order(price=1.2, size=100.0),
        [],
        make_market_data(
            best_bid=1.0, best_ask=1.5, bid_liquidity=300.0, ask_liquidity=400.0
        ),
    )
    assert ok is False
    assert "Insufficient market liquidity" in (error or "")


def test_validate_order_per_market_cap_rejects_buy():
    """The per-market cap applies when order.market_id is set (line 146)."""
    limits = make_limits(
        max_order_size_usd=500.0,
        max_total_exposure_usd=10_000.0,
        max_position_size_per_market=800.0,
    )
    positions = [
        make_position("tok-b", "m1", size=1_000.0),  # 500.0 USD in m1
        make_position("tok-c", "m1", size=900.0),  # 450.0 USD in m1 -> 950.0 total
    ]

    ok, error = limits.validate_order(
        make_order(token_id="tok-a", price=0.5, size=600.0, market_id="m1"),  # 300.0
        positions,
        make_market_data(market_id="m1"),
    )

    assert ok is False
    assert error is not None
    assert "per-market maximum" in error


def test_validate_order_per_market_skipped_without_market_id():
    """Without order.market_id the per-market check is skipped entirely."""
    limits = make_limits(
        max_total_exposure_usd=10_000.0, max_position_size_per_market=800.0
    )
    positions = [make_position("tok-b", "m1", size=3_000.0)]  # 1500.0 USD, over m-cap

    ok, error = limits.validate_order(
        make_order(token_id="tok-a", price=0.5, size=200.0, market_id=None),
        positions,
        make_market_data(),
    )

    assert (ok, error) == (True, None)


def test_validate_order_sell_treated_as_short_in_other_market():
    """SELL of a token held in ANOTHER market finds no existing position within
    the order's market: the per-market check treats it as a short (lines
    156-162) and the market cap applies to the full order value."""
    limits = make_limits(
        max_order_size_usd=1_000.0,
        max_total_exposure_usd=1_000.0,
        max_position_size_per_market=800.0,
    )
    positions = [make_position("tok-a", "m1", size=1_000.0)]  # 500.0 USD in m1

    ok, error = limits.validate_order(
        make_order(
            token_id="tok-a", price=0.5, size=1_800.0, side="SELL", market_id="m2"
        ),
        positions,
        make_market_data(market_id="m2"),
    )

    assert ok is False
    assert error is not None
    assert "per-market maximum" in error


def test_check_exposure_flags_over_limit():
    """check_exposure returns (total, within); the cap boundary is within."""
    limits = make_limits(max_total_exposure_usd=1_000.0)

    over = [
        make_position("tok-b", "m1", size=600.0, current_price=1.0),  # 600.0 USD
        make_position("tok-c", "m2", size=500.0, current_price=1.0),  # 500.0 USD
    ]
    total, within = limits.check_exposure(over)
    assert total == 1_100.0
    assert within is False

    under = [
        make_position("tok-b", "m1", size=300.0, current_price=1.0),  # 300.0 USD
        make_position("tok-c", "m2", size=400.0, current_price=1.0),  # 400.0 USD
    ]
    total, within = limits.check_exposure(under)
    assert total == 700.0
    assert within is True

    at_cap = [make_position("tok-b", "m1", size=1_000.0, current_price=1.0)]  # 1000.0 == cap
    total, within = limits.check_exposure(at_cap)
    assert (total, within) == (1_000.0, True)


def test_should_require_confirmation_when_autonomous_disabled():
    """autonomous_trading_enabled=False requires confirmation for ANY order."""
    limits = make_limits(require_confirmation_above_usd=1_000.0)

    small = limits.should_require_confirmation(
        make_order(price=1.0, size=1.0), autonomous_trading_enabled=False
    )
    huge = limits.should_require_confirmation(
        make_order(price=100.0, size=50.0),  # 5000.0 USD, above the threshold too
        autonomous_trading_enabled=False,
    )

    assert small is True
    assert huge is True


def test_should_require_confirmation_above_threshold():
    """With autonomous trading on, confirmation is needed only when the order
    value strictly exceeds require_confirmation_above_usd."""
    limits = make_limits(require_confirmation_above_usd=500.0)

    above = limits.should_require_confirmation(make_order(price=0.6, size=1_000.0))
    below = limits.should_require_confirmation(make_order(price=0.4, size=1_000.0))
    # Boundary: value exactly at the threshold does NOT require confirmation.
    at_threshold = limits.should_require_confirmation(make_order(price=0.5, size=1_000.0))

    assert above is True
    assert below is False
    assert at_threshold is False


def test_get_position_summary_totals():
    """Summary aggregates totals and groups positions by market_id."""
    limits = make_limits(
        max_total_exposure_usd=2_000.0, max_position_size_per_market=1_500.0
    )
    positions = [
        make_position(
            "tok-a", "m1", size=200.0, current_price=1.0, unrealized_pnl=10.0
        ),
        make_position(
            "tok-b", "m1", size=300.0, current_price=1.0, unrealized_pnl=-5.0
        ),
        make_position(
            "tok-c", "m2", size=400.0, current_price=1.0, unrealized_pnl=20.0
        ),
    ]

    summary = limits.get_position_summary(positions)

    assert summary["total_positions"] == 3
    assert summary["total_exposure_usd"] == 900.0
    assert summary["total_unrealized_pnl"] == 25.0
    assert summary["exposure_limit_usd"] == 2_000.0
    assert summary["exposure_utilization"] == pytest.approx(900.0 / 2_000.0)

    # Positions are grouped by market_id (observed keys, L-0020).
    assert set(summary["markets"].keys()) == {"m1", "m2"}
    m1 = summary["markets"]["m1"]
    assert set(m1.keys()) == {"exposure_usd", "position_count", "limit_usd", "utilization"}
    assert m1["exposure_usd"] == 500.0
    assert m1["position_count"] == 2
    assert m1["limit_usd"] == 1_500.0
    assert m1["utilization"] == pytest.approx(500.0 / 1_500.0)
    m2 = summary["markets"]["m2"]
    assert m2["exposure_usd"] == 400.0
    assert m2["position_count"] == 1


def test_get_position_summary_empty_positions():
    """Empty portfolio: zero totals and no markets."""
    limits = make_limits(max_total_exposure_usd=1_000.0)

    summary = limits.get_position_summary([])

    assert summary["total_positions"] == 0
    assert summary["total_exposure_usd"] == 0
    assert summary["total_unrealized_pnl"] == 0
    assert summary["exposure_utilization"] == 0
    assert summary["markets"] == {}


def test_market_data_properties():
    """MarketData helpers: spread, mid_price, total_liquidity; spread falls
    back to 1.0 when best_bid == 0 (observed branch, lines 52-54)."""
    data = make_market_data(
        best_bid=0.5, best_ask=0.7, bid_liquidity=100.0, ask_liquidity=250.0
    )

    assert data.spread == pytest.approx(0.4)  # (0.7 - 0.5) / 0.5
    assert data.mid_price == pytest.approx(0.6)
    assert data.total_liquidity == 350.0

    zero_bid = make_market_data(best_bid=0.0, best_ask=0.5)
    assert zero_bid.spread == 1.0


def test_position_value_usd_uses_current_price():
    """Position.value_usd = size * current_price (NOT avg_price)."""
    position = make_position("tok-a", "m1", size=200.0, avg_price=0.4, current_price=0.6)

    assert position.value_usd == pytest.approx(120.0)


def test_create_safety_limits_from_config_maps_fields():
    """create_safety_limits_from_config maps all seven config attributes."""
    config = SimpleNamespace(
        MAX_ORDER_SIZE_USD=100.0,
        MAX_TOTAL_EXPOSURE_USD=5_000.0,
        MAX_POSITION_SIZE_PER_MARKET=2_500.0,
        MIN_LIQUIDITY_REQUIRED=250.0,
        MAX_SPREAD_TOLERANCE=0.35,
        REQUIRE_CONFIRMATION_ABOVE_USD=750.0,
        AUTO_CANCEL_ON_LARGE_SPREAD=False,
    )

    limits = create_safety_limits_from_config(config)

    assert isinstance(limits, SafetyLimits)
    assert limits.max_order_size_usd == 100.0
    assert limits.max_total_exposure_usd == 5_000.0
    assert limits.max_position_size_per_market == 2_500.0
    assert limits.min_liquidity_required == 250.0
    assert limits.max_spread_tolerance == 0.35
    assert limits.require_confirmation_above_usd == 750.0
    assert limits.auto_cancel_on_large_spread is False
