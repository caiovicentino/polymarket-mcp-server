"""Offline regression suite for the tick-LESS and tick-BROKEN fallback paths
of ``suggest_order_price`` (coverage completion -- residual of T-0278).

Contract T-0377 (curator, 2026-09-19): the aligned money path (books WITH a
usable ``tick_size``) is pinned by ``test_tick_alignment_offline.py``.
Coverage of the full offline selection on main c5cb6c7 shows 5 statements +
3 partial branches still dead in ``trading.py``:

  - ``parse_tick_size``: the ``except (TypeError, ValueError, ArithmeticError)``
    branch and the non-positive branch -- no offline test ever passes an
    unparsable or non-positive tick_size (the aligned suite only feeds
    "0.01" / no field).
  - ``suggest_order_price`` legacy fallbacks when ``tick is None``: mid BUY
    returns the RAW mid (``suggested_price = mid_price``) and passive SELL
    returns ``best_ask - (spread * 0.1)`` -- float arithmetic, no Decimal.

These fallbacks are OBSERVED legacy behavior (the docstring of T-0278 keeps
"Books WITHOUT a usable tick_size field ... legacy behavior (identity)"). The
suite pins the exact values so a future alignment change to the fallback path
must consciously flip the pins here. Zero network, zero sleep (L-0018/L-0014);
fakes are self-contained (FA-0079 house rule -- never import from another
test module).
"""

from typing import Any, Dict, List

import pytest

from polymarket_mcp.tools.trading import TradingTools, parse_tick_size
from polymarket_mcp.utils.safety_limits import SafetyLimits

# House-standard offline wallet (valid 64-hex, zero value).
KEY = "0" * 63 + "1"
ADDRESS = "0x" + "0" * 40


class FakeConfig:
    """Minimal stand-in for PolymarketConfig (house pattern)."""

    def __init__(self, autonomous: bool = True, threshold: float = 1_000_000_000.0):
        self.ENABLE_AUTONOMOUS_TRADING = autonomous
        self.REQUIRE_CONFIRMATION_ABOVE_USD = threshold


class FakeLimiter:
    """No-op rate limiter: the real singleton sleeps between calls (L-0014)."""

    def __init__(self):
        self.calls: List[str] = []

    async def acquire(self, category: Any) -> float:
        self.calls.append(str(category))
        return 0.0


def _book(tick_value: Any = None) -> Dict[str, Any]:
    """Top-of-book with wire-faithful STRINGS; best-first per T-0211.

    bids[0]="0.52", asks[0]="0.53". ``tick_value=None`` models the tickless
    books of the sibling suites (no field -> identity path); a string value
    (including garbage) is delivered byte-as-is.
    """
    book: Dict[str, Any] = {
        "bids": [{"price": "0.52", "size": "2500"}],
        "asks": [{"price": "0.53", "size": "2500"}],
    }
    if tick_value is not None:
        book["tick_size"] = tick_value
    return book


class FakeClient:
    """Duck-typed client stub recording every call trading.py makes."""

    def __init__(self) -> None:
        self.market: Dict[str, Any] = {
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes"},
                {"token_id": "no-token", "outcome": "No"},
            ],
            "volume": "1000000",
        }
        self.book = _book()
        self.get_orderbook_calls: List[str] = []

    async def get_market(self, market_id: str) -> Dict[str, Any]:
        return self.market

    async def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        self.get_orderbook_calls.append(token_id)
        return self.book


def build_tools():
    """REAL SafetyLimits (wide caps) + the stub client."""
    limits = SafetyLimits(
        max_order_size_usd=100_000.0,
        max_total_exposure_usd=1_000_000.0,
        max_position_size_per_market=100_000.0,
        min_liquidity_required=0.0,
        max_spread_tolerance=1.0,
        require_confirmation_above_usd=1_000_000_000.0,
    )
    client = FakeClient()
    tools = TradingTools(client, limits, FakeConfig())
    tools.rate_limiter = FakeLimiter()
    return tools, client


# ---------------------------------------------------------------------------
# parse_tick_size error/non-positive branches
# ---------------------------------------------------------------------------


def test_parse_tick_size_rejects_unparsable_string():
    """A tick_size that Decimal() cannot parse yields None (no crash)."""
    assert parse_tick_size("not-a-number") is None


def test_parse_tick_size_rejects_non_positive():
    """Zero and negative tick sizes are unusable -> None."""
    assert parse_tick_size("0") is None
    assert parse_tick_size("-0.01") is None


def test_parse_tick_size_none_is_identity():
    """The tickless path (absent field) stays identity -> None."""
    assert parse_tick_size(None) is None


# ---------------------------------------------------------------------------
# suggest_order_price legacy fallbacks (tick is None or unusable)
# ---------------------------------------------------------------------------


async def test_suggest_mid_buy_without_tick_returns_raw_mid():
    """Mid BUY on a tickless book: the legacy float mid (0.525), not aligned."""
    tools, client = build_tools()
    client.book = _book(None)
    result = await tools.suggest_order_price("0xmarket", "BUY", 100.0, strategy="mid")
    assert result["success"] is True
    assert result["suggested_price"] == pytest.approx(0.525)
    assert "Mid-price buy" in result["reasoning"]


async def test_suggest_passive_sell_without_tick_returns_legacy_offset():
    """Passive SELL on a tickless book: legacy best_ask - spread*0.1 = 0.529."""
    tools, client = build_tools()
    client.book = _book(None)
    result = await tools.suggest_order_price("0xmarket", "SELL", 100.0, strategy="passive")
    assert result["success"] is True
    assert result["suggested_price"] == pytest.approx(0.529)
    assert "Passive sell" in result["reasoning"]


async def test_suggest_with_unparsable_tick_falls_back_to_legacy():
    """An UNPARSABLE tick_size string flows through parse -> None -> legacy
    fallback (the integrated path exercised by no sibling suite)."""
    tools, client = build_tools()
    client.book = _book("not-a-number")
    result = await tools.suggest_order_price("0xmarket", "BUY", 100.0, strategy="mid")
    assert result["suggested_price"] == pytest.approx(0.525)


# ---------------------------------------------------------------------------
# STRICTLY-above/below bump branches (zero-spread aligned book)
# ---------------------------------------------------------------------------


def _zero_spread_book() -> Dict[str, Any]:
    """Book with bids[0] == asks[0] == "0.52" and tick "0.01" (both aligned).

    Only on a ZERO-spread book can the strictness bump fire: with spread > 0
    the aligned candidate is strictly above the bid (passive BUY) / strictly
    below the ask (passive SELL) by construction, so `aligned <= bid_d` /
    `aligned >= ask_d` is unreachable. With spread == 0 the aligned candidate
    EQUALS the edge price and the bump adjusts by one tick.
    """
    return {
        "bids": [{"price": "0.52", "size": "2500"}],
        "asks": [{"price": "0.52", "size": "2500"}],
        "tick_size": "0.01",
    }


async def test_passive_buy_bumps_strictly_above_on_zero_spread_book():
    """Passive BUY on a zero-spread aligned book: the aligned candidate (0.52)
    EQUALS the best bid, so the strictness bump adds one tick -> 0.53."""
    tools, client = build_tools()
    client.book = _zero_spread_book()
    result = await tools.suggest_order_price("0xmarket", "BUY", 100.0, strategy="passive")
    assert result["success"] is True
    assert result["suggested_price"] == pytest.approx(0.53)
    assert "Passive buy at 0.5300" in result["reasoning"]


async def test_passive_sell_bumps_strictly_below_on_zero_spread_book():
    """Passive SELL on a zero-spread aligned book: the aligned candidate (0.52)
    EQUALS the best ask, so the strictness bump subtracts one tick -> 0.51."""
    tools, client = build_tools()
    client.book = _zero_spread_book()
    result = await tools.suggest_order_price("0xmarket", "SELL", 100.0, strategy="passive")
    assert result["success"] is True
    assert result["suggested_price"] == pytest.approx(0.51)
    assert "Passive sell at 0.5100" in result["reasoning"]
