"""429-backoff wiring: portfolio CLOB surfaces (offline).

Companion of the Data-API fatia (test_rate_limit_429_portfolio_offline):
``auth/client.py`` re-raises py-clob-client errors, so the CLOB-surface
failures inside portfolio.py carry ``status_code`` from the wire. This suite
pins the NEW wiring on the eight except paths that receive PolyApiException:

- get_all_positions/get_pnl_summary/analyze_portfolio_risk/
  suggest_portfolio_actions per-position orderbook fallbacks arm
  MARKET_DATA and KEEP the degraded-mode output (envelope unchanged);
- get_position_details outer except arms MARKET_DATA with the error
  envelope unchanged;
- get_portfolio_value get_orders fallback arms CLOB_GENERAL, its
  orderbook fallback arms MARKET_DATA, and the outer except (get_balance
  surface) arms CLOB_GENERAL with the error envelope unchanged;
- a 500 PolyApiException and a plain RuntimeError arm NOTHING
  (anti-over-fix). Direct Data-API (httpx) responses are intentionally NOT
  noted here - the sibling ``_note_http_429`` wiring (and the declared
  fetch_all_pages pass-through follow-up) covers that surface; the outer
  excepts check ONLY the exception-carried status so a wired pass-through
  can never double-arm.
"""

import sys

import httpx
import pytest
from py_clob_client.exceptions import PolyApiException

sys.path.insert(0, "src")

ADDRESS = "0xAbCdEf0123456789AbCdEf0123456789aBcDeF01"
POSITIONS_URL = "https://data-api.polymarket.com/positions"
TRADES_URL = "https://data-api.polymarket.com/trades"
BOOK_URL = "https://clob.polymarket.com/book"
BALANCE_URL = "https://clob.polymarket.com/balance-allowance"
ORDERS_URL = "https://clob.polymarket.com/data/orders"


def _portfolio():
    """Deferred first-party import: the sys.path insert above wins for this src."""
    import polymarket_mcp.tools.portfolio as portfolio

    return portfolio


portfolio = _portfolio()

from polymarket_mcp.utils.rate_limiter import RateLimiter  # noqa: E402


class FakeResponse:
    def __init__(self, payload, error=None):
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return self._payload


class FakeAsyncClient:
    calls = []
    responses = {}

    def __init__(self, timeout=30.0):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, timeout=None):
        type(self).calls.append((url, dict(params or {})))
        if url not in type(self).responses:
            raise AssertionError(f"unexpected URL routed to stub: {url}")
        value = type(self).responses[url]
        return value if isinstance(value, FakeResponse) else FakeResponse(value)


class FakePolymarketClient:
    """Duck-typed client stub: get_orderbook/get_balance/get_orders."""

    def __init__(self, orderbooks=None, balance=0.0, orders=None,
                 orderbook_error=None, orders_error=None, balance_error=None):
        self._orderbooks = dict(orderbooks or {})
        self._balance = balance
        self._orders = list(orders) if orders is not None else []
        self._orderbook_error = orderbook_error
        self._orders_error = orders_error
        self._balance_error = balance_error

    async def get_orderbook(self, token_id):
        if self._orderbook_error is not None:
            raise self._orderbook_error
        if token_id not in self._orderbooks:
            raise AssertionError(f"unexpected get_orderbook token: {token_id}")
        return self._orderbooks[token_id]

    async def get_balance(self):
        if self._balance_error is not None:
            raise self._balance_error
        return {"balance": self._balance}

    async def get_orders(self):
        if self._orders_error is not None:
            raise self._orders_error
        return list(self._orders)


class FakeConfig:
    POLYGON_ADDRESS = ADDRESS


def make_position(size, avg_price, token, market, question, outcome="YES"):
    return {
        "size": size,
        "average_price": avg_price,
        "asset_id": token,
        "market": market,
        "market_question": question,
        "outcome": outcome,
    }


def _429(url, method="GET"):
    response = httpx.Response(429, text="rate limited",
                              request=httpx.Request(method, url))
    return PolyApiException(resp=response)


def _500(url, method="GET"):
    response = httpx.Response(500, text="server error",
                              request=httpx.Request(method, url))
    return PolyApiException(resp=response)


def text_of(content):
    assert len(content) == 1
    assert content[0].type == "text"
    return content[0].text


@pytest.fixture(autouse=True)
def isolated_portfolio(monkeypatch):
    """Per-test isolation: reset the global cache and the stub (house pattern)."""
    portfolio._portfolio_cache.clear()
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = {}
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    yield
    portfolio._portfolio_cache.clear()


# --- per-position orderbook fallbacks (MARKET_DATA) --------------------------


async def test_get_all_positions_orderbook_429_degrades_and_arms_market_data():
    pos = make_position(10, 0.40, "tok1", "0xm1", "Question one")
    FakeAsyncClient.responses[POSITIONS_URL] = [pos]
    limiter = RateLimiter()
    client = FakePolymarketClient(orderbook_error=_429(BOOK_URL))
    out = await portfolio.get_all_positions(client, limiter, FakeConfig())
    text = text_of(out)
    assert "Question one" in text
    assert limiter.get_status()["market_data"]["is_throttled"] is True


async def test_get_pnl_summary_orderbook_429_degrades_and_arms_market_data():
    pos = make_position(10, 0.40, "tok1", "0xm1", "Question one")
    FakeAsyncClient.responses[TRADES_URL] = []
    FakeAsyncClient.responses[POSITIONS_URL] = [pos]
    limiter = RateLimiter()
    client = FakePolymarketClient(orderbook_error=_429(BOOK_URL))
    out = await portfolio.get_pnl_summary(client, limiter, FakeConfig())
    text = text_of(out)
    assert "P&L" in text or "pnl" in text.lower()
    assert limiter.get_status()["market_data"]["is_throttled"] is True


async def test_analyze_portfolio_risk_orderbook_429_degrades_and_arms_market_data():
    pos = make_position(10, 0.40, "tok1", "0xm1", "Question one")
    FakeAsyncClient.responses[POSITIONS_URL] = [pos]
    limiter = RateLimiter()
    client = FakePolymarketClient(orderbook_error=_429(BOOK_URL))
    out = await portfolio.analyze_portfolio_risk(client, limiter, FakeConfig())
    assert "Error" not in text_of(out)[:40]
    assert limiter.get_status()["market_data"]["is_throttled"] is True


async def test_suggest_portfolio_actions_orderbook_429_degrades_and_arms_market_data():
    pos = make_position(10, 0.40, "tok1", "0xm1", "Question one")
    FakeAsyncClient.responses[POSITIONS_URL] = [pos]
    limiter = RateLimiter()
    client = FakePolymarketClient(orderbook_error=_429(BOOK_URL))
    out = await portfolio.suggest_portfolio_actions(client, limiter, FakeConfig())
    assert limiter.get_status()["market_data"]["is_throttled"] is True
    assert "Error" not in text_of(out)[:40]


# --- get_position_details outer except (MARKET_DATA) -------------------------


async def test_get_position_details_orderbook_429_error_envelope_unchanged():
    pos = make_position(10, 0.40, "tok1", "0xm1", "Question one")
    FakeAsyncClient.responses[POSITIONS_URL] = [pos]
    limiter = RateLimiter()
    client = FakePolymarketClient(orderbook_error=_429(BOOK_URL))
    out = await portfolio.get_position_details(client, limiter, FakeConfig(), "0xm1")
    text = text_of(out)
    assert text.startswith("Error fetching position details")
    assert limiter.get_status()["market_data"]["is_throttled"] is True


# --- get_portfolio_value (orders CLOB_GENERAL / orderbook MARKET_DATA /
# --- balance CLOB_GENERAL outer) ---------------------------------------------


async def test_get_portfolio_value_orders_429_degrades_and_arms_clob_general():
    pos = make_position(10, 0.40, "tok1", "0xm1", "Question one")
    FakeAsyncClient.responses[POSITIONS_URL] = [pos]
    limiter = RateLimiter()
    client = FakePolymarketClient(
        balance=500.0, orders_error=_429(ORDERS_URL),
        orderbooks={"tok1": {"bids": [{"price": "0.42", "size": "100"}],
                             "asks": [{"price": "0.44", "size": "100"}]}})
    out = await portfolio.get_portfolio_value(client, limiter, FakeConfig())
    text = text_of(out)
    assert "TOTAL PORTFOLIO VALUE" in text
    assert limiter.get_status()["clob_general"]["is_throttled"] is True
    assert limiter.get_status()["market_data"]["is_throttled"] is False


async def test_get_portfolio_value_orderbook_429_degrades_and_arms_market_data():
    pos = make_position(10, 0.40, "tok1", "0xm1", "Question one")
    FakeAsyncClient.responses[POSITIONS_URL] = [pos]
    limiter = RateLimiter()
    client = FakePolymarketClient(balance=500.0, orders=[],
                                  orderbook_error=_429(BOOK_URL))
    out = await portfolio.get_portfolio_value(client, limiter, FakeConfig())
    text = text_of(out)
    assert "TOTAL PORTFOLIO VALUE" in text
    assert limiter.get_status()["market_data"]["is_throttled"] is True
    assert limiter.get_status()["clob_general"]["is_throttled"] is False


async def test_get_portfolio_value_balance_429_error_envelope_unchanged():
    pos = make_position(10, 0.40, "tok1", "0xm1", "Question one")
    FakeAsyncClient.responses[POSITIONS_URL] = [pos]
    limiter = RateLimiter()
    client = FakePolymarketClient(balance_error=_429(BALANCE_URL))
    out = await portfolio.get_portfolio_value(client, limiter, FakeConfig())
    text = text_of(out)
    assert text.startswith("Error calculating portfolio value")
    assert limiter.get_status()["clob_general"]["is_throttled"] is True


# --- anti-over-fix guards -----------------------------------------------------


async def test_get_all_positions_500_arms_nothing():
    pos = make_position(10, 0.40, "tok1", "0xm1", "Question one")
    FakeAsyncClient.responses[POSITIONS_URL] = [pos]
    limiter = RateLimiter()
    client = FakePolymarketClient(orderbook_error=_500(BOOK_URL))
    out = await portfolio.get_all_positions(client, limiter, FakeConfig())
    text_of(out)
    assert limiter.get_status()["market_data"]["is_throttled"] is False


async def test_get_portfolio_value_plain_runtime_error_arms_nothing():
    limiter = RateLimiter()
    client = FakePolymarketClient(balance_error=RuntimeError("scripted boom"))
    out = await portfolio.get_portfolio_value(client, limiter, FakeConfig())
    text = text_of(out)
    assert "scripted boom" in text
    assert limiter.get_status()["clob_general"]["is_throttled"] is False


async def test_httpx_429_from_positions_route_is_not_noted_here():
    """The Data-API httpx surface is the sibling helper's turf: a 429 raised
    from the raw positions fetch arms NOTHING in this wiring (no double-arm
    when the fetch_all_pages pass-through follow-up lands)."""
    response = httpx.Response(429, text="rate limited",
                              request=httpx.Request("GET", POSITIONS_URL))
    from httpx import HTTPStatusError

    error = HTTPStatusError("429", request=response.request, response=response)
    FakeAsyncClient.responses[POSITIONS_URL] = FakeResponse([], error=error)
    limiter = RateLimiter()
    client = FakePolymarketClient()
    out = await portfolio.get_all_positions(client, limiter, FakeConfig())
    text = text_of(out)
    assert "Error" in text
    assert limiter.get_status()["data_api"]["is_throttled"] is False
