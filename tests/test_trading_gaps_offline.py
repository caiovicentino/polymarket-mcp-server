"""
Offline regression suite for the RESIDUAL gaps in tools/trading.py - the only
module that sends money.

Pins the 34 dead statements measured on clone main 2f28d21 (trading.py blob
b0c39ae, IDENTICAL at the farm/T-0059 fork point 94899fe - no src/ change,
proven by git diff; baseline: 383 stmts, 34 miss, 124 branches, 7 BrPart,
91.12% - miss lines: 431, 435-443, 463-465, 506, 524-525, 531-542, 548,
578-580, 680-682, 725, 753-755, 850-852, 1140).

Source of truth (L-0020/L-0090 - code as observed, not prose):
- create_batch_orders (trading.py:374-469): the else-counting branch at
  :430-431 (a plain failure: result without 'confirmation_required' status
  and falsy 'success' -> failed += 1); the per-order except at :435-443
  (entry {"index": idx, "success": False, "error": str(e), "details": order}
  - 'details' carries the RAW order dict, and both a stub raising inside
  create_limit_order and a malformed order dict (missing keys at :407-410)
  land here); the outer except at :463-469 ({"success": False, "error":
  str(e), "total_orders": len(orders)} - reachable via the rate limiter seam,
  because create_limit_order swallows its own client errors internally at
  :284-295 and only re-raises OUTSIDE its try block). batch_result keys
  (:445-452): success/total_orders/successful/awaiting_confirmation/failed/
  results.
- suggest_order_price (trading.py:471-583): :506 raise ValueError("Insufficient
  orderbook depth") when bids or asks are empty; BUY passive :524-525
  (suggested = best_bid + spread * 0.1 - the contract mislabeled this range
  as "SELL passive"); SELL aggressive :531-534 (suggested = best_bid),
  SELL passive :535-538 (suggested = best_ask - spread * 0.1), SELL mid
  :539-542 (suggested = mid_price); fill_probability :545-550
  (aggressive 0.95 / passive 0.4 / mid 0.7 - :548 is the dead passive line);
  error envelope :578-583 ({"success": False, "error": str(e)} - exactly two
  keys; the contract mislabeled :578-580 as get_open_orders).
- get_open_orders (trading.py:640-685): except envelope :680-685 =
  {"success": False, "error": str(e)} (contract mislabeled :680-682 as
  get_order_history filters).
- get_order_history (trading.py:687-758): the end-date filter :724-725
  (order_time > end_dt -> continue; :722-723 start-side and :727-728
  invalid-timestamp keep are ALREADY covered by test_trading_orders_offline.py);
  except envelope :753-758 = {"success": False, "error": str(e)}.
- cancel_market_orders (trading.py:794-856): outer except :850-856 =
  {"success": False, "error": str(e), "market_id": market_id} (three keys;
  reachable when get_orders itself raises - per-order cancel failures are
  caught inside at :837-839 and are already covered).
- rebalance_position (trading.py:1057-1191): the slippage guards live HERE,
  not in execute_smart_trade. BUY guard :1128-1135 compares
  expected_price > max_price (= mid*(1+max_slippage)) and raises
  "Slippage too high: expected {X:.4f} > max {Y:.4f}"; SELL guard
  :1136-1143 compares expected_price < min_price (= mid*(1-max_slippage))
  and raises "Slippage too high: expected {X:.4f} < min {Y:.4f}" (the raise
  start :1140 is the dead line; the BUY raise is already covered by
  test_trading_orders_offline.py but re-pinned here with the exact message).

DIVERGENCES contract X code (L-0025, declared - asserts follow the code):
- Contract's "execute_smart_trade (guards de slippage :850-852 e ~:1136-1140)":
  :850-852 is cancel_market_orders' outer except; the guards live in
  rebalance_position (:1128-1143). execute_smart_trade (893-1055) has NO
  slippage check. The mandated test names are kept verbatim; docstrings name
  the real method under test.
- Contract's BUY guard description ("expected < mid*(1-max_slippage) -> '<
  min'") describes the SELL comparison; the observed BUY comparison is
  '> max' with a '> max' message.
- Contract's ":524-525 SELL passive" is the BUY passive branch; the SELL
  passive branch is :535-538. Contract's ":506 envelope" is the
  insufficient-orderbook raise; the suggest envelope is :578-583.

Already covered (overlap calibration against the sibling suites):
- test_trading_offline.py (T-0041/R2): create_limit_order validation+safety+
  gate, create_market_order sides/liquidity, cancel_market_orders happy path
  and per-market filter, confirmation threshold edge.
- test_trading_orders_offline.py (T-0043): get_order_status fill stats +
  error dict, get_open_orders happy path (filter/group), get_order_history
  date filter (start-side continue :722-723, invalid-timestamp keep :727-728,
  limit clipping), cancel_order/cancel_all happy+error, execute_smart_trade
  intent parsing/split/failure reporting, rebalance_position noop/BUY-pass/
  BUY-reject/close-SELL, _convert_positions.
- test_confirmation_gate.py: batch gating (awaiting_confirmation entries
  :424-427), batch all-gated, per-order confirm forwarding, smart-trade and
  rebalance gate surfacing.
- test_safety_adversarial.py (T-0045): execute_smart_trade split ratchet,
  rebalance BUY slippage raise reachability.
This suite adds the MISSING branches listed above; no overlap test is edited
(turf: never edit existing suites - plugin DENIED by design).

Zero network, zero sleep: SafetyLimits is the REAL class, the rate limiter is
a duck-typed no-op (the real singleton sleeps - L-0014), and the client stub
records every call. Error injection happens ONLY through the *_error seams
(P-0031 - deterministic RuntimeError, never network; L-0118: stub materialized
before any execution). The stub is structurally pinned (L-0121): it accepts
ONLY the kwargs the observed call sites send (get_orders(market=, asset_id=),
post_order(**kwargs) per trading.py:254-261) - an undocumented kwarg added by
a future fix fails with TypeError at call time. Lessons: L-0002 (derived
floats/approx for sums), L-0109/L-0128e (contradictory pairs; mandatory names
do not forbid complementary tests), P-0019 (worktree of the external clone),
P-0029 (env -i hermeticity).
"""
from unittest.mock import AsyncMock

import pytest

from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.safety_limits import SafetyLimits


class FakeConfig:
    """Minimal stand-in for PolymarketConfig (house pattern)."""

    def __init__(self, autonomous: bool = True, threshold: float = 1_000_000_000.0):
        self.ENABLE_AUTONOMOUS_TRADING = autonomous
        self.REQUIRE_CONFIRMATION_ABOVE_USD = threshold


class FakeLimiter:
    """No-op rate limiter: the real singleton sleeps between calls (L-0014).
    Records the requested categories; error seam for the batch outer except."""

    def __init__(self):
        self.calls = []
        self.acquire_error = None

    async def acquire(self, category):
        self.calls.append(category)
        if self.acquire_error is not None:
            raise self.acquire_error
        return 0.0


class FakeClient:
    """Duck-typed client stub pinning trading.py's client contract (L-0121).

    Structural pin: the signatures accept ONLY the kwargs the observed call
    sites send (trading.py:159/254/604/656/709/776/813) - an undocumented kwarg
    added by a future fix fails with TypeError AT CALL TIME. Endpoints never
    touch the network (L-0118): error injection happens only through the
    deterministic RuntimeError seams below (P-0031)."""

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
        self.positions = []
        self.orders = []
        self.get_market_calls = 0
        self.get_orderbook_calls = []
        self.get_orders_calls = []
        self.get_positions_calls = 0
        self.cancel_order_calls = []
        self.posted = []
        # deterministic error seams (P-0031) - never network
        self.get_market_error = None
        self.get_orderbook_error = None
        self.get_orders_error = None

    async def get_market(self, market_id):
        self.get_market_calls += 1
        if self.get_market_error is not None:
            raise self.get_market_error
        return self.market

    async def get_orderbook(self, token_id):
        self.get_orderbook_calls.append(token_id)
        if self.get_orderbook_error is not None:
            raise self.get_orderbook_error
        return self.book

    async def get_positions(self):
        self.get_positions_calls += 1
        return list(self.positions)

    async def get_orders(self, market=None, asset_id=None):
        self.get_orders_calls.append({"market": market, "asset_id": asset_id})
        if self.get_orders_error is not None:
            raise self.get_orders_error
        return list(self.orders)

    async def cancel_order(self, order_id):
        self.cancel_order_calls.append(order_id)
        return {"cancelled": True}

    async def post_order(self, **kwargs):
        self.posted.append(kwargs)
        return {"orderID": "order-1", "status": "submitted"}


def build_tools(max_order_size_usd: float = 100_000.0):
    """REAL SafetyLimits (wide caps, threshold at galaxy scale) + the stub."""
    limits = SafetyLimits(
        max_order_size_usd=max_order_size_usd,
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


# --- create_batch_orders -----------------------------------------------------


async def test_batch_orders_counts_success_and_failure_per_order():
    """The else-branch :430-431: a plain failure (success falsy, no
    confirmation status) is counted as failed, not successful."""
    tools, client = build_tools(max_order_size_usd=10.0)

    result = await tools.create_batch_orders([
        {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 5.0,
         "outcome": "Yes"},
        {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 500.0,
         "outcome": "Yes"},
    ])

    # Safety rejection: create_limit_order swallows the ValueError internally
    # (:284-295) and returns success=False WITHOUT a confirmation status ->
    # the else at :430-431 counts it as failed.
    assert result["successful"] == 1
    assert result["failed"] == 1
    assert result["awaiting_confirmation"] == 0
    assert result["total_orders"] == 2
    assert result["success"] is True  # successful > 0
    ok, bad = result["results"]
    assert ok["index"] == 0 and ok["success"] is True and ok["order_id"] == "order-1"
    assert ok["details"]["market_id"] == "m1"
    # The batch entry copies index/success/order_id/details ONLY - the safety
    # error MESSAGE stays inside create_limit_order's return and is NOT
    # propagated into the entry (observed at trading.py:417-422).
    assert bad == {
        "index": 1,
        "success": False,
        "order_id": None,
        "details": {
            "market_id": "m1", "side": "BUY", "price": 0.5, "size_usd": 500.0,
        },
    }
    assert "status" not in bad and "status" not in ok
    assert len(client.posted) == 1, "only the passing order reached the exchange"


async def test_batch_orders_error_entry_includes_index_error_and_details():
    """Per-order except :435-443: the raised stub produces the exact entry
    {"index", "success": False, "error", "details": order}."""
    tools, _client = build_tools()
    exploded = RuntimeError("order 1 exploded")
    stub = AsyncMock(side_effect=[
        {"success": True, "order_id": "o-1", "details": {"echo": "ok"}},
        exploded,
    ])
    tools.create_limit_order = stub
    orders = [
        {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 10.0,
         "outcome": "Yes"},
        {"market_id": "m2", "side": "SELL", "price": 0.4, "size": 20.0,
         "outcome": "Yes"},
    ]

    result = await tools.create_batch_orders(orders)

    assert result["successful"] == 1
    assert result["failed"] == 1
    assert result["results"][0] == {
        "index": 0, "success": True, "order_id": "o-1", "details": {"echo": "ok"},
    }
    # The error entry carries the RAW order dict as details - exactly.
    assert result["results"][1] == {
        "index": 1,
        "success": False,
        "error": "order 1 exploded",
        "details": orders[1],
    }
    assert stub.await_count == 2, "the loop must continue past the failure"


async def test_batch_orders_malformed_order_enters_error_entry():
    """The same except :435-443 via the natural production path: an order dict
    missing a required key raises KeyError BEFORE create_limit_order
    (:407-410) and the entry carries the raw (malformed) order."""
    tools, _client = build_tools()
    stub = AsyncMock(return_value={"success": True, "order_id": "o-1"})
    tools.create_limit_order = stub
    orders = [
        {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 10.0},
        {"market_id": "m1", "price": 0.5, "size": 10.0},  # no 'side' key
    ]

    result = await tools.create_batch_orders(orders)

    assert result["failed"] == 1
    bad = result["results"][1]
    assert bad["index"] == 1
    assert bad["success"] is False
    assert bad["error"] == "'side'"
    assert bad["details"] == {"market_id": "m1", "price": 0.5, "size": 10.0}
    assert stub.await_count == 1, "the malformed order never reaches the stub"


async def test_batch_orders_aggregates_results_structure():
    """Aggregation: a 100%-success batch (contradictory pair to the mixed one)
    and the outer except :463-469 ({"success": False, "error", "total_orders"}
    - NO results key) via the rate limiter seam."""
    tools, client = build_tools()

    clean = await tools.create_batch_orders([
        {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 5.0,
         "outcome": "Yes"},
        {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 6.0,
         "outcome": "No"},
    ])

    assert set(clean.keys()) == {
        "success", "total_orders", "successful", "awaiting_confirmation",
        "failed", "results",
    }
    assert clean["success"] is True
    assert clean["total_orders"] == 2
    assert clean["successful"] == 2  # all-success: the contradictory pair
    assert clean["failed"] == 0
    assert clean["awaiting_confirmation"] == 0
    assert len(clean["results"]) == 2
    assert len(client.posted) == 2

    tools, _client = build_tools()
    tools.rate_limiter.acquire_error = RuntimeError("rate limiter exploded")

    broken = await tools.create_batch_orders([
        {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 5.0},
        {"market_id": "m1", "side": "SELL", "price": 0.5, "size": 5.0},
    ])

    # Observed envelope at :465-469 - exactly three keys, no 'results'.
    assert broken == {
        "success": False,
        "error": "rate limiter exploded",
        "total_orders": 2,
    }


# --- suggest_order_price -----------------------------------------------------


def _priced_book():
    """Synthetic book: bid 0.40 / ask 0.50 -> spread 0.10, mid 0.45."""
    return {
        "bids": [{"price": "0.40", "size": "800"}],
        "asks": [{"price": "0.50", "size": "800"}],
    }


async def test_suggest_order_price_sell_aggressive_uses_best_bid():
    """SELL aggressive :531-534: suggested price IS the best bid."""
    tools, client = build_tools()
    client.book = _priced_book()

    result = await tools.suggest_order_price("m1", "SELL", 100.0, "aggressive", "Yes")

    assert result["success"] is True
    assert result["suggested_price"] == 0.40
    assert result["reasoning"] == (
        "Aggressive sell at best bid 0.4000 for immediate execution"
    )
    assert result["order_details"]["side"] == "SELL"
    assert result["order_details"]["estimated_fill_probability"] == 0.95
    # The stub saw the resolved token, not the market id.
    assert client.get_orderbook_calls == ["yes-token"]


async def test_suggest_order_price_sell_passive_below_best_ask():
    """SELL passive :535-538: suggested price sits 10% of the spread BELOW the
    best ask (formula pinned exactly as observed - L-0002)."""
    tools, client = build_tools()
    client.book = _priced_book()

    result = await tools.suggest_order_price("m1", "SELL", 100.0, "passive", "Yes")

    assert result["success"] is True
    best_bid = 0.40
    best_ask = 0.50
    assert result["suggested_price"] == best_ask - (best_ask - best_bid) * 0.1
    assert result["reasoning"] == (
        f"Passive sell at {result['suggested_price']:.4f}, "
        f"below best ask {best_ask:.4f}"
    )
    assert result["order_details"]["estimated_fill_probability"] == 0.4


async def test_suggest_order_price_sell_mid_uses_mid_price():
    """SELL mid :539-542: suggested price IS the mid price."""
    tools, client = build_tools()
    client.book = _priced_book()

    result = await tools.suggest_order_price("m1", "SELL", 100.0, "mid", "Yes")

    assert result["success"] is True
    assert result["suggested_price"] == (0.40 + 0.50) / 2
    assert result["reasoning"] == (
        f"Mid-price sell at {result['suggested_price']:.4f} "
        f"(bid: 0.4000, ask: 0.5000)"
    )
    assert result["order_details"]["estimated_fill_probability"] == 0.7
    assert result["market_context"]["spread"] == 0.50 - 0.40


async def test_suggest_order_price_buy_passive_above_best_bid():
    """BUY passive :524-525 (complementary, L-0109): suggested price sits 10%
    of the spread ABOVE the best bid - the branch the mandatory names skip."""
    tools, client = build_tools()
    client.book = _priced_book()

    result = await tools.suggest_order_price("m1", "BUY", 100.0, "passive", "Yes")

    assert result["success"] is True
    best_bid = 0.40
    best_ask = 0.50
    assert result["suggested_price"] == best_bid + (best_ask - best_bid) * 0.1
    assert result["reasoning"] == (
        f"Passive buy at {result['suggested_price']:.4f}, "
        f"above best bid {best_bid:.4f}"
    )
    assert result["order_details"]["estimated_fill_probability"] == 0.4


async def test_suggest_order_price_fill_probability_by_strategy():
    """fill_probability :545-550 pinned per strategy: aggressive 0.95,
    passive 0.4 (the dead :548), mid 0.7 - same book, three strategies
    (contradictory pair among themselves)."""
    book = _priced_book()
    expected = {"aggressive": 0.95, "passive": 0.4, "mid": 0.7}

    for strategy, probability in expected.items():
        tools, client = build_tools()
        client.book = book

        result = await tools.suggest_order_price(
            "m1", "BUY", 100.0, strategy, "Yes"
        )

        assert result["success"] is True
        assert result["order_details"]["estimated_fill_probability"] == probability


async def test_suggest_order_price_error_returns_failure_envelope():
    """Except envelope :578-583: a client failure collapses to
    {"success": False, "error": str(e)} - exactly two keys."""
    tools, client = build_tools()
    client.get_market_error = RuntimeError("clob market down")

    result = await tools.suggest_order_price("m1", "BUY", 100.0, "mid", "Yes")

    assert result == {"success": False, "error": "clob market down"}


async def test_suggest_order_price_insufficient_book_raises_depth_error():
    """:506: an orderbook without asks raises ValueError("Insufficient
    orderbook depth"), which surfaces through the same error envelope."""
    tools, client = build_tools()
    client.book = {
        "bids": [{"price": "0.40", "size": "800"}],
        "asks": [],  # asks empty -> :506 raise
    }

    result = await tools.suggest_order_price("m1", "BUY", 100.0, "mid", "Yes")

    assert result == {"success": False, "error": "Insufficient orderbook depth"}
    assert client.get_market_calls == 1, "the raise happens after the market fetch"


# --- order management envelopes ----------------------------------------------


async def test_get_open_orders_error_returns_failure_envelope():
    """Except envelope :680-685: get_orders failure collapses to
    {"success": False, "error": str(e)} - exactly two keys."""
    tools, client = build_tools()
    client.get_orders_error = RuntimeError("clob 503")

    result = await tools.get_open_orders("m1")

    assert result == {"success": False, "error": "clob 503"}
    assert client.get_orders_calls == [{"market": "m1", "asset_id": None}]


async def test_get_order_history_error_returns_failure_envelope():
    """Except envelope :753-758: get_orders failure collapses to
    {"success": False, "error": str(e)} - exactly two keys."""
    tools, client = build_tools()
    client.get_orders_error = RuntimeError("clob unreachable")

    result = await tools.get_order_history(market_id="m1", limit=10)

    assert result == {"success": False, "error": "clob unreachable"}
    assert client.get_orders_calls == [{"market": "m1", "asset_id": None}]


async def test_get_order_history_filters_start_and_end_dates():
    """:712-730: only orders INSIDE the [start_date, end_date] window survive.
    The end-side continue :724-725 (order_time > end_dt) is the newly covered
    branch; the start-side continue and the invalid-timestamp keep are pinned
    again as the contradictory bookends of the same window."""
    tools, client = build_tools()
    client.orders = [
        {"id": "h-before", "status": "filled", "size": "10", "price": "0.5",
         "timestamp": "2026-09-10T12:00:00Z"},  # before start -> continue
        {"id": "h-in", "status": "filled", "size": "20", "price": "0.5",
         "timestamp": "2026-09-14T12:00:00Z"},  # inside the window
        {"id": "h-after", "status": "cancelled", "size": "5", "price": "0.4",
         "timestamp": "2026-09-20T00:00:00Z"},  # after end -> continue :724-725
        {"id": "h-invalid", "status": "filled", "size": "7", "price": "0.3",
         "timestamp": "not-a-date"},  # invalid -> kept via except
    ]

    window = await tools.get_order_history(
        start_date="2026-09-14T00:00:00+00:00",
        end_date="2026-09-15T23:59:59+00:00",
    )

    assert window["success"] is True
    assert [o["id"] for o in window["orders"]] == ["h-in", "h-invalid"]
    assert window["total_orders"] == 2
    assert window["filled"] == 2
    assert window["cancelled"] == 0
    # 20*0.5 + 7*0.3 - only the surviving orders feed the volume.
    assert window["total_volume_usd"] == pytest.approx(12.1)

    # Contradictory pair: an inverted window excludes everything that has a
    # well-formed timestamp. (An order with an INVALID timestamp is kept
    # unconditionally by the except branch - observed quirk, pinned above.)
    tools, client = build_tools()
    client.orders = [
        {"id": "h-in", "status": "filled", "size": "20", "price": "0.5",
         "timestamp": "2026-09-14T12:00:00Z"},
        {"id": "h-after", "status": "cancelled", "size": "5", "price": "0.4",
         "timestamp": "2026-09-20T00:00:00Z"},
    ]
    empty = await tools.get_order_history(
        start_date="2027-01-01T00:00:00+00:00",
        end_date="2027-01-02T00:00:00+00:00",
    )

    assert empty["success"] is True
    assert empty["orders"] == []
    assert empty["total_orders"] == 0
    assert empty["total_volume_usd"] == 0


async def test_cancel_market_orders_error_returns_failure_envelope():
    """Outer except :850-856: when get_orders itself raises, the collapse is
    {"success": False, "error", "market_id"} - exactly three keys (per-order
    cancel failures are caught INSIDE the loop and are already covered)."""
    tools, client = build_tools()
    client.get_orders_error = RuntimeError("clob 503")

    result = await tools.cancel_market_orders("m1")

    assert result == {
        "success": False,
        "error": "clob 503",
        "market_id": "m1",
    }
    assert client.cancel_order_calls == [], "no cancel may be attempted"


# --- rebalance_position slippage guards --------------------------------------
# The contract attributes the guards to execute_smart_trade; they live in
# rebalance_position (trading.py:1128-1143). Mandated names kept verbatim.


async def test_execute_smart_trade_rejects_slippage_above_max_buy():
    """BUY guard :1128-1135 (rebalance_position): a BUY whose expected price
    (best ask) exceeds mid*(1+max_slippage) raises the exact ValueError and
    never reaches create_limit_order. Contradictory pair: the same book with a
    wider tolerance passes and posts at the ask."""
    tools, client = build_tools()
    client.positions = []
    client.book = {
        "bids": [{"price": "0.49", "size": "100000"}],
        "asks": [{"price": "0.60", "size": "100000"}],
    }
    create_limit = AsyncMock(return_value={"success": True, "order_id": "lt"})
    tools.create_limit_order = create_limit

    rejected = await tools.rebalance_position(
        market_id="m1", target_size=100.0, outcome="Yes"
    )

    assert rejected == {
        "success": False,
        "error": "Slippage too high: expected 0.6000 > max 0.5559",
        "market_id": "m1",
        "target_size": 100.0,
    }
    assert create_limit.await_count == 0, "a rejected trade must not post"

    # The acceptable equivalent: the same book, tolerance wide enough.
    create_limit.reset_mock()
    accepted = await tools.rebalance_position(
        market_id="m1", target_size=100.0, max_slippage=0.2, outcome="Yes"
    )

    assert accepted["success"] is True
    create_limit.assert_called_with(
        market_id="m1", side="BUY", price=0.60, size=100.0,
        order_type="GTC", outcome="Yes", confirm=False,
    )


async def test_execute_smart_trade_rejects_slippage_above_max_sell():
    """SELL guard :1136-1143 (rebalance_position): a SELL whose expected price
    (best bid) falls below mid*(1-max_slippage) raises the exact ValueError
    (the dead raise start :1140) and never reaches create_limit_order.
    Contradictory pair: the same book with a wider tolerance passes."""
    tools, client = build_tools()
    client.positions = [
        {"market": "m1", "size": "100", "price": "0.5"},  # $50 in m1
    ]
    client.book = {
        "bids": [{"price": "0.40", "size": "100000"}],
        "asks": [{"price": "0.50", "size": "100000"}],
    }
    create_limit = AsyncMock(return_value={"success": True, "order_id": "lt"})
    tools.create_limit_order = create_limit

    rejected = await tools.rebalance_position(
        market_id="m1", target_size=None, outcome="Yes"
    )

    # target_size=None is normalized to 0.0 in the local (:1090-1091) BEFORE
    # the except, so the envelope carries 0.0 - observed, not None (L-0025).
    assert rejected == {
        "success": False,
        "error": "Slippage too high: expected 0.4000 < min 0.4410",
        "market_id": "m1",
        "target_size": 0.0,
    }
    assert create_limit.await_count == 0, "a rejected trade must not post"

    # The acceptable equivalent: the same book, tolerance wide enough.
    create_limit.reset_mock()
    accepted = await tools.rebalance_position(
        market_id="m1", target_size=None, max_slippage=0.12, outcome="Yes"
    )

    assert accepted["success"] is True
    create_limit.assert_called_with(
        market_id="m1", side="SELL", price=0.40, size=50.0,
        order_type="GTC", outcome="Yes", confirm=False,
    )
