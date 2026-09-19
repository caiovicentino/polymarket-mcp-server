"""429-backoff wiring: trading money path (offline).

py_clob_client raises ``PolyApiException`` carrying ``status_code`` from the
wire response. A real 429 from the CLOB armed NO backoff (``handle_429_error``
had ZERO callers in src/, grep-proven) and immediate retries hammered the
API. This suite pins the NEW wiring on the two order-submission except paths
(``create_limit_order`` and ``create_market_order`` -- the funnels of
``create_batch_orders``/``execute_smart_trade``/``rebalance_position``):

- a REAL ``PolyApiException`` built from an httpx 429 response arms the
  TRADING_BURST backoff (public ``get_status()`` observable) and the error
  envelope is returned UNCHANGED;
- a PolyApiException WITHOUT status_code (client-side construction), a
  500 PolyApiException and a plain RuntimeError arm NOTHING;
- the Retry-After header is not exposed by PolyApiException (only the
  parsed body), so the exponential default is used.
"""

import httpx
from py_clob_client.exceptions import PolyApiException

from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.rate_limiter import RateLimiter
from polymarket_mcp.utils.safety_limits import SafetyLimits

CLOB_ORDER_URL = "https://clob.polymarket.com/order"


class FakeConfig:
    def __init__(self, autonomous: bool = True, threshold: float = 1_000_000_000.0):
        self.ENABLE_AUTONOMOUS_TRADING = autonomous
        self.REQUIRE_CONFIRMATION_ABOVE_USD = threshold


class FakeClient:
    """Duck-typed client stub (house pattern, P-0031). Only the
    create_limit_order/create_market_order surface is exercised."""

    def __init__(self, post_error=None, book_error=None):
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
        self.posted = []
        self.post_error = post_error
        self.book_error = book_error

    async def get_market(self, market_id):
        return self.market

    async def get_orderbook(self, token_id):
        if self.book_error is not None:
            raise self.book_error
        return self.book

    async def get_positions(self):
        return []

    async def post_order(self, **kwargs):
        self.posted.append(kwargs)
        if self.post_error is not None:
            raise self.post_error
        return {"orderID": "order-1", "status": "submitted"}


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


def _throttled(limiter):
    return limiter.get_status()["trading_burst"]["is_throttled"]


def _429_exception():
    response = httpx.Response(429, text="rate limited",
                              request=httpx.Request("POST", CLOB_ORDER_URL))
    return PolyApiException(resp=response)


def _500_exception():
    response = httpx.Response(500, text="server error",
                              request=httpx.Request("POST", CLOB_ORDER_URL))
    return PolyApiException(resp=response)


# --- create_limit_order ------------------------------------------------------


async def test_limit_order_429_arms_backoff_and_envelope_unchanged():
    tools = build_tools(FakeClient(post_error=_429_exception()))
    result = await tools.create_limit_order(
        market_id="m1", side="BUY", price=0.50, size=10.0
    )
    assert result["success"] is False
    assert "429" in result["error"] or "PolyApiException" in result["error"]
    assert _throttled(tools.rate_limiter) is True


async def test_limit_order_polyapiexception_without_status_arms_nothing():
    tools = build_tools(FakeClient(post_error=PolyApiException(error_msg="boom")))
    result = await tools.create_limit_order(
        market_id="m1", side="BUY", price=0.50, size=10.0
    )
    assert result["success"] is False
    assert _throttled(tools.rate_limiter) is False


async def test_limit_order_500_exception_arms_nothing():
    tools = build_tools(FakeClient(post_error=_500_exception()))
    result = await tools.create_limit_order(
        market_id="m1", side="BUY", price=0.50, size=10.0
    )
    assert result["success"] is False
    assert _throttled(tools.rate_limiter) is False


async def test_limit_order_plain_runtime_error_arms_nothing():
    tools = build_tools(FakeClient(post_error=RuntimeError("scripted boom")))
    result = await tools.create_limit_order(
        market_id="m1", side="BUY", price=0.50, size=10.0
    )
    assert result["success"] is False
    assert "scripted boom" in result["error"]
    assert _throttled(tools.rate_limiter) is False


async def test_limit_order_happy_path_arms_nothing():
    tools = build_tools(FakeClient())
    result = await tools.create_limit_order(
        market_id="m1", side="BUY", price=0.50, size=10.0
    )
    assert result["success"] is True
    assert _throttled(tools.rate_limiter) is False


# --- create_market_order (funnel surface) ------------------------------------


async def test_market_order_book_error_429_arms_backoff():
    tools = build_tools(FakeClient(book_error=_429_exception()))
    result = await tools.create_market_order(market_id="m1", side="BUY", size=10.0)
    assert result["success"] is False
    assert _throttled(tools.rate_limiter) is True


async def test_market_order_post_429_arms_backoff_via_funnel():
    tools = build_tools(FakeClient(post_error=_429_exception()))
    result = await tools.create_market_order(market_id="m1", side="BUY", size=10.0)
    assert result["success"] is False
    assert _throttled(tools.rate_limiter) is True
