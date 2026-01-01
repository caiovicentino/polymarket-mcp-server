"""429-backoff wiring: trading management/read/cancel surfaces (offline).

Companion of the order-submission fatia (test_rate_limit_429_trading_offline):
py_clob_client raises PolyApiException carrying ``status_code`` from the wire
response. This suite pins the NEW wiring on the remaining management/read and
cancel except paths of trading.py:

- suggest_order_price (get_market/get_orderbook) and the rebalance_position
  outer except (its direct get_market/get_orderbook reads) arm MARKET_DATA;
  the order-status trio (get_order_status/get_open_orders/get_order_history,
  all via get_orders) arms CLOB_GENERAL; the cancel surfaces (cancel_order,
  cancel_market_orders outer get_orders + inner per-order cancel,
  cancel_all_orders) arm TRADING_BURST. Every error envelope is returned
  UNCHANGED, so the offline envelope pins hold;
- a PolyApiException WITHOUT status_code, a 500 PolyApiException and a plain
  RuntimeError arm NOTHING (anti-over-fix);
- the category routing is isolated: a 429 observed on one category never
  throttles another (the helper forwards the acquire-matched category);
- the per-order create_limit_order leaf of rebalance_position is wired by
  the SUBMISSION fatia (TRADING_BURST) - the outer note here covers only
  the direct read surfaces, so no exception is ever noted twice.
"""

import httpx
from py_clob_client.exceptions import PolyApiException

from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.rate_limiter import RateLimiter
from polymarket_mcp.utils.safety_limits import SafetyLimits

CLOB_URL = "https://clob.polymarket.com/order"


class FakeConfig:
    def __init__(self, autonomous: bool = True, threshold: float = 1_000_000_000.0):
        self.ENABLE_AUTONOMOUS_TRADING = autonomous
        self.REQUIRE_CONFIRMATION_ABOVE_USD = threshold


class FakeClient:
    """Duck-typed client stub (house pattern, P-0031). Serves the
    management/read/cancel surface only; unconfigured paths fail loud."""

    def __init__(
        self,
        orders=None,
        orders_error=None,
        cancel_error=None,
        cancel_all_error=None,
        book_error=None,
        market_error=None,
    ):
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
        self.orders = list(orders) if orders is not None else []
        self.orders_error = orders_error
        self.cancel_error = cancel_error
        self.cancel_all_error = cancel_all_error
        self.book_error = book_error
        self.market_error = market_error
        self.cancelled = []

    async def get_market(self, market_id):
        if self.market_error is not None:
            raise self.market_error
        return self.market

    async def get_orderbook(self, token_id):
        if self.book_error is not None:
            raise self.book_error
        return self.book

    async def get_orders(self, market=None, asset_id=None):
        if self.orders_error is not None:
            raise self.orders_error
        return list(self.orders)

    async def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        if self.cancel_error is not None:
            raise self.cancel_error
        return {"canceled": True}

    async def cancel_all_orders(self):
        if self.cancel_all_error is not None:
            raise self.cancel_all_error
        return {"cancelled": ["o1", "o2"]}


def build_tools(client):
    limits = SafetyLimits(
        max_order_size_usd=100_000.0,
        max_total_exposure_usd=1_000_000.0,
        max_position_size_per_market=100_000.0,
        min_liquidity_required=0.0,
        max_spread_tolerance=1.0,
        require_confirmation_above_usd=1_000_000_000.0,
    )
    tools = TradingTools(client, limits, FakeConfig())
    tools.rate_limiter = RateLimiter()
    return tools


def _throttled(limiter, category_value):
    return limiter.get_status()[category_value]["is_throttled"]


def _429_exception(url=CLOB_URL, method="POST"):
    response = httpx.Response(429, text="rate limited",
                              request=httpx.Request(method, url))
    return PolyApiException(resp=response)


def _500_exception(url=CLOB_URL, method="POST"):
    response = httpx.Response(500, text="server error",
                              request=httpx.Request(method, url))
    return PolyApiException(resp=response)


# --- suggest_order_price (MARKET_DATA) ---------------------------------------


async def test_suggest_order_price_429_arms_market_data_envelope_unchanged():
    tools = build_tools(FakeClient(book_error=_429_exception()))
    result = await tools.suggest_order_price(market_id="m1", side="BUY", size=10.0)
    assert result["success"] is False
    assert _throttled(tools.rate_limiter, "market_data") is True


async def test_suggest_order_price_500_exception_arms_nothing():
    tools = build_tools(FakeClient(book_error=_500_exception()))
    result = await tools.suggest_order_price(market_id="m1", side="BUY", size=10.0)
    assert result["success"] is False
    assert _throttled(tools.rate_limiter, "market_data") is False


# --- get_order_status / get_open_orders / get_order_history (CLOB_GENERAL) ---


async def test_get_order_status_429_arms_clob_general_envelope_unchanged():
    tools = build_tools(FakeClient(orders_error=_429_exception(
        url="https://clob.polymarket.com/data/orders", method="GET")))
    result = await tools.get_order_status(order_id="order-1")
    assert result["success"] is False
    assert result["order_id"] == "order-1"
    assert _throttled(tools.rate_limiter, "clob_general") is True
    assert _throttled(tools.rate_limiter, "trading_burst") is False


async def test_get_open_orders_429_arms_clob_general():
    tools = build_tools(FakeClient(orders_error=_429_exception(
        url="https://clob.polymarket.com/data/orders", method="GET")))
    result = await tools.get_open_orders()
    assert result["success"] is False
    assert _throttled(tools.rate_limiter, "clob_general") is True


async def test_get_order_history_429_arms_clob_general():
    tools = build_tools(FakeClient(orders_error=_429_exception(
        url="https://clob.polymarket.com/data/orders", method="GET")))
    result = await tools.get_order_history(limit=5)
    assert result["success"] is False
    assert _throttled(tools.rate_limiter, "clob_general") is True


async def test_order_status_500_exception_arms_nothing():
    tools = build_tools(FakeClient(orders_error=_500_exception(
        url="https://clob.polymarket.com/data/orders", method="GET")))
    result = await tools.get_order_status(order_id="order-1")
    assert result["success"] is False
    assert _throttled(tools.rate_limiter, "clob_general") is False


# --- cancel_order (TRADING_BURST) --------------------------------------------


async def test_cancel_order_429_arms_trading_burst_envelope_unchanged():
    tools = build_tools(FakeClient(cancel_error=_429_exception()))
    result = await tools.cancel_order(order_id="order-9")
    assert result["success"] is False
    assert result["order_id"] == "order-9"
    assert _throttled(tools.rate_limiter, "trading_burst") is True
    assert _throttled(tools.rate_limiter, "clob_general") is False


async def test_cancel_order_plain_runtime_error_arms_nothing():
    tools = build_tools(FakeClient(cancel_error=RuntimeError("scripted boom")))
    result = await tools.cancel_order(order_id="order-9")
    assert result["success"] is False
    assert "scripted boom" in result["error"]
    assert _throttled(tools.rate_limiter, "trading_burst") is False


# --- cancel_market_orders (outer get_orders + inner per-order) ---------------


OPEN_ORDER = {
    "id": "order-7",
    "status": "open",
    "market": "0xm1",
    "originalSize": "10",
    "size": "10",
}


async def test_cancel_market_orders_outer_429_arms_trading_burst():
    tools = build_tools(FakeClient(orders_error=_429_exception(
        url="https://clob.polymarket.com/data/orders", method="GET")))
    result = await tools.cancel_market_orders(market_id="0xm1")
    assert result["success"] is False
    assert result["market_id"] == "0xm1"
    assert _throttled(tools.rate_limiter, "trading_burst") is True


async def test_cancel_market_orders_inner_429_notes_and_envelope_unchanged():
    tools = build_tools(FakeClient(orders=[OPEN_ORDER], cancel_error=_429_exception()))
    result = await tools.cancel_market_orders(market_id="0xm1")
    assert result["success"] is True
    assert result["cancelled_count"] == 0
    assert result["failed_count"] == 1
    assert result["failed_orders"][0]["order_id"] == "order-7"
    assert _throttled(tools.rate_limiter, "trading_burst") is True


# --- cancel_all_orders (TRADING_BURST) ---------------------------------------


async def test_cancel_all_orders_429_arms_trading_burst_envelope_unchanged():
    tools = build_tools(FakeClient(cancel_all_error=_429_exception()))
    result = await tools.cancel_all_orders()
    assert result["success"] is False
    assert _throttled(tools.rate_limiter, "trading_burst") is True


async def test_cancel_all_orders_happy_path_arms_nothing():
    tools = build_tools(FakeClient())
    result = await tools.cancel_all_orders()
    assert result["success"] is True
    assert result["cancelled_count"] == 2
    assert _throttled(tools.rate_limiter, "trading_burst") is False


# --- rebalance_position outer (MARKET_DATA: direct get_market/get_orderbook
# --- reads; the create_limit_order leaf is wired by the submission fatia) ----


class RebalanceClient(FakeClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.positions = [{"market": "m1", "condition_id": "0xm1",
                           "size": "5", "price": "0.5"}]

    async def get_positions(self):
        return list(self.positions)


async def test_rebalance_position_market_read_429_arms_market_data():
    tools = build_tools(RebalanceClient(market_error=_429_exception()))
    result = await tools.rebalance_position(market_id="m1")
    assert result["success"] is False
    assert result["market_id"] == "m1"
    assert _throttled(tools.rate_limiter, "market_data") is True


async def test_rebalance_position_book_read_429_arms_market_data():
    tools = build_tools(RebalanceClient(book_error=_429_exception()))
    result = await tools.rebalance_position(market_id="m1")
    assert result["success"] is False
    assert _throttled(tools.rate_limiter, "market_data") is True
    assert _throttled(tools.rate_limiter, "trading_burst") is False


# --- category isolation (the helper forwards the acquire-matched category) --


async def test_market_data_429_never_throttles_trading_burst():
    tools = build_tools(FakeClient(book_error=_429_exception()))
    await tools.suggest_order_price(market_id="m1", side="BUY", size=10.0)
    assert _throttled(tools.rate_limiter, "market_data") is True
    assert _throttled(tools.rate_limiter, "trading_burst") is False
    assert _throttled(tools.rate_limiter, "clob_general") is False
