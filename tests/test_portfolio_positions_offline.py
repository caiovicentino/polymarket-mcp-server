"""
Offline regression suite for the POSITIONS/VALUE/P&L slice of
src/polymarket_mcp/tools/portfolio.py (contract T-0038).

Covered slice (portfolio.py lines 21-746):
- PortfolioDataCache: TTL expiry (datetime.now().timestamp() - timestamp >= ttl),
  set/get/clear and the module-global `_portfolio_cache` (portfolio.py:47)
- get_all_positions (50-213): size<=0 skipped, current_value < min_value dropped,
  sort_by 'value'/'pnl' descending, totals, mid-price math ((best_bid+best_ask)/2
  when both truthy, else avg_price), price fallback when the orderbook fetch
  fails, cache reuse keyed f"positions_{include_closed}_{min_value}", empty and
  HTTP-error paths
- get_position_details (216-387): P&L math, suggestion thresholds (pnl_pct > 20
  "Consider taking profits", top-5 liquidity sum < 1000 "Low liquidity"),
  recent-trades [:5] cap, Data API params (market / limit: 10), no-position path
- get_portfolio_value (390-528): cash + positions + pending orders total, market
  breakdown toggle (include_breakdown), orders-failure tolerance
- get_pnl_summary (531-745): FIFO realized P&L (full + partial closes), win/loss
  counting and win rate, best/worst performer, start_time presence per timeframe
  ('all' -> absent, '24h' -> int)

Edge cases beyond the 11 contract-named tests (same file, same slice): FIFO
losing close (win-rate accounting), no-trades/HOLD suggestion path, error paths
of get_position_details/get_portfolio_value/get_pnl_summary (every function
returns error text instead of raising, portfolio.py:208, 382, 523, 740), and
PortfolioDataCache TTL expiry/eviction (portfolio.py:31-34) aged by timestamp
manipulation - zero sleep (L-0014).

Seams (module-level, zero network, zero sleep):
- portfolio.httpx.AsyncClient -> FakeAsyncClient: portfolio.py:15 does
  `import httpx` and resolves the attribute at call time (portfolio.py:86,
  239, 268, 418, 565, 583), so monkeypatch.setattr(httpx, "AsyncClient",
  FakeAsyncClient) intercepts every Data API call. The stub records (url,
  params) per call, routes by URL suffix (/positions, /trades) and fails loud
  for unexpected URLs; raise_for_status() can be seeded with an error.
- polymarket_client -> FakePolymarketClient (duck-typed get_orderbook,
  get_balance, get_orders; per-endpoint error injection)
- rate_limiter -> FakeRateLimiter (async acquire(category) -> 0.0, records
  categories); the real EndpointCategory enum is imported inside the functions
  under test, so it needs no patching
- config -> FakeConfig (POLYGON_ADDRESS string; the code calls .lower(),
  portfolio.py:88)

Isolation: the autouse fixture clears the module-global _portfolio_cache
before AND after every test (portfolio.py:47 - a global cache would otherwise
leak between tests; xdist isolates files per worker but intra-file order
matters) and installs/restores the AsyncClient stub via monkeypatch.
datetime.fromtimestamp renders in LOCAL time (portfolio.py:350), so exact date
strings are never asserted (L-0002) - only side/price/size substrings.

Prerequisites: pytest-asyncio auto mode (pyproject.toml:80); no
integration/real_api/slow markers - runs under the release gate
`-m "not integration and not slow and not real_api"`; .venv symlink +
PYTHONPATH=src per P-0019.
Lessons: L-0002 (semantic assertions), L-0014 (zero sleep), L-0020/L-0090
(asserts pin the observed behavior; expected numbers derived from the same
payloads the code parses), L-0085 (judged by real output).
"""
import sys

import httpx
import pytest

sys.path.insert(0, "src")

ADDRESS = "0xAbCdEf0123456789AbCdEf0123456789aBcDeF01"
POSITIONS_URL = "https://data-api.polymarket.com/positions"
TRADES_URL = "https://data-api.polymarket.com/trades"
BASE_TS = 1_700_000_000


def _portfolio():
    """Deferred first-party import: the sys.path insert above wins for this src."""
    import polymarket_mcp.tools.portfolio as portfolio

    return portfolio


portfolio = _portfolio()


class FakeResponse:
    """Response stub exposing .raise_for_status() and .json() (portfolio.py:96)."""

    def __init__(self, payload, error=None):
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return self._payload


class FakeAsyncClient:
    """Stub of the httpx.AsyncClient seam used by every Data API call.

    State lives on the CLASS because each function under test builds a fresh
    instance (`async with httpx.AsyncClient()`); the autouse fixture resets it
    before every test.
    """

    calls = []
    responses = {}

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

    def __init__(
        self,
        orderbooks=None,
        balance=None,
        orders=None,
        orderbook_error=None,
        orders_error=None,
    ):
        self._orderbooks = dict(orderbooks or {})
        self._balance = balance
        self._orders = list(orders) if orders is not None else []
        self._orderbook_error = orderbook_error
        self._orders_error = orders_error
        self.orderbook_tokens = []

    async def get_orderbook(self, token_id):
        self.orderbook_tokens.append(token_id)
        if self._orderbook_error is not None:
            raise self._orderbook_error
        if token_id not in self._orderbooks:
            raise AssertionError(f"unexpected get_orderbook token: {token_id}")
        return self._orderbooks[token_id]

    async def get_balance(self):
        return {"balance": self._balance}

    async def get_orders(self):
        if self._orders_error is not None:
            raise self._orders_error
        return list(self._orders)


class FakeRateLimiter:
    """Rate limiter stub: acquire(category) -> 0.0, categories recorded."""

    def __init__(self):
        self.categories = []

    async def acquire(self, category):
        self.categories.append(category)
        return 0.0


class FakeConfig:
    """Config stub: the code only touches POLYGON_ADDRESS (and lowercases it)."""

    POLYGON_ADDRESS = ADDRESS


def make_position(size, avg_price, token, market, question, outcome="YES"):
    """Position payload in the shape the Data API returns and portfolio.py parses."""
    return {
        "size": size,
        "average_price": avg_price,
        "asset_id": token,
        "market": market,
        "market_question": question,
        "outcome": outcome,
    }


def make_trade(market, outcome, side, price, size, timestamp, seq=0):
    """Trade payload in the shape the Data API returns and portfolio.py parses."""
    return {
        "market": market,
        "outcome": outcome,
        "side": side,
        "price": price,
        "size": size,
        "timestamp": timestamp,
        "fee": 0.01,
        "id": f"trade-{seq}",
        "market_question": "Trade question",
    }


def orderbook(bid, bid_size, ask, ask_size):
    """Orderbook payload shape consumed by the mid-price math."""
    return {
        "bids": [{"price": bid, "size": bid_size}],
        "asks": [{"price": ask, "size": ask_size}],
    }


def set_api_routes(routes):
    """Route the installed AsyncClient stub: URL suffix -> payload/FakeResponse."""
    FakeAsyncClient.responses = dict(routes)


def text_of(content):
    """Extract the single text payload of a [types.TextContent] return value."""
    assert len(content) == 1
    assert content[0].type == "text"
    return content[0].text


def positions_calls():
    """(url, params) pairs recorded for the /positions Data API endpoint."""
    return [c for c in FakeAsyncClient.calls if c[0] == POSITIONS_URL]


def trades_calls():
    """(url, params) pairs recorded for the /trades Data API endpoint."""
    return [c for c in FakeAsyncClient.calls if c[0] == TRADES_URL]


@pytest.fixture(autouse=True)
def isolated_portfolio(monkeypatch):
    """Per-test isolation: reset the global cache (before/after) and the stub.

    The cache is module-global (portfolio.py:47); without this fixture a cached
    positions payload would leak between tests and flip the cache test's GET
    counter. monkeypatch restores httpx.AsyncClient at teardown.
    """
    portfolio._portfolio_cache.clear()
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = {}
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    yield
    portfolio._portfolio_cache.clear()


async def test_get_all_positions_filters_sorts_and_totals():
    """size<=0 skipped, sub-min_value filtered, value/pnl sorts diverge, totals."""
    from polymarket_mcp.utils.rate_limiter import EndpointCategory

    zero = make_position(0, 0.40, "tok_zero", "mkt_zero", "Question zero size")
    tiny = make_position(1, 0.40, "tok_tiny", "mkt_tiny", "Question tiny value")
    winner = make_position(10, 0.30, "tok_win", "mkt_win", "Question winner pnl")
    loser = make_position(20, 0.60, "tok_lose", "mkt_lose", "Question loser pnl")
    set_api_routes({POSITIONS_URL: [zero, tiny, winner, loser]})

    mid_win = (0.44 + 0.46) / 2
    mid_lose = (0.48 + 0.52) / 2
    value_win = 10 * mid_win
    value_lose = 20 * mid_lose
    pnl_win = value_win - 10 * 0.30
    pnl_lose = value_lose - 20 * 0.60

    client = FakePolymarketClient(
        orderbooks={
            "tok_win": orderbook(0.44, 5, 0.46, 5),
            "tok_lose": orderbook(0.48, 5, 0.52, 5),
            # tok_tiny's book: value 0.42 still falls under min_value=1.0.
            "tok_tiny": orderbook(0.40, 5, 0.44, 5),
        }
    )
    limiter = FakeRateLimiter()

    value_text = text_of(
        await portfolio.get_all_positions(client, limiter, FakeConfig(), sort_by="value")
    )
    pnl_text = text_of(
        await portfolio.get_all_positions(client, limiter, FakeConfig(), sort_by="pnl")
    )

    # Filtering: zero-size skipped, below-min_value dropped, both valid kept.
    assert "Portfolio Positions (2 total)" in value_text
    assert "Question zero size" not in value_text
    assert "Question tiny value" not in value_text
    assert "Question winner pnl" in value_text
    assert "Question loser pnl" in value_text

    # sort_by='value' desc: 20*0.50=10.00 before 10*0.45=4.50. Each question is
    # rendered exactly once (the numbered position line), so index() pins order.
    assert value_text.index("Question loser pnl") < value_text.index("Question winner pnl")
    # sort_by='pnl' desc: +1.50 before -2.00 -> the two orders diverge.
    assert pnl_text.index("Question winner pnl") < pnl_text.index("Question loser pnl")

    # Totals derived from the same payloads the code parses.
    expected_total_value = value_lose + value_win
    expected_total_pnl = pnl_lose + pnl_win
    assert f"Total Portfolio Value: ${expected_total_value:.2f}" in value_text
    assert f"Total Unrealized P&L: ${expected_total_pnl:+.2f}" in value_text
    assert f"Current: ${mid_win:.4f} | Value: ${value_win:.2f}" in value_text
    assert f"Current: ${mid_lose:.4f} | Value: ${value_lose:.2f}" in value_text
    assert f"P&L: ${pnl_win:+.2f}" in value_text
    assert f"P&L: ${pnl_lose:+.2f}" in value_text

    # Data API contract: user param lowercased, nothing else.
    calls = positions_calls()
    assert len(calls) == 1  # second call is a cache hit (same include_closed/min_value)
    assert calls[0][1] == {"user": ADDRESS.lower()}

    # Rate limiter seam engaged for both categories.
    assert EndpointCategory.DATA_API in limiter.categories
    assert EndpointCategory.MARKET_DATA in limiter.categories


async def test_get_all_positions_uses_cache_on_second_call():
    """Same include_closed/min_value hits the cache; a new min_value refetches."""
    big = make_position(10, 0.40, "tok_big", "mkt_big", "Question big value")
    small = make_position(10, 0.30, "tok_small", "mkt_small", "Question small value")
    set_api_routes({POSITIONS_URL: [big, small]})

    client = FakePolymarketClient(
        orderbooks={
            "tok_big": orderbook(0.48, 5, 0.52, 5),  # mid 0.50 -> value 5.00
            "tok_small": orderbook(0.40, 5, 0.42, 5),  # mid 0.41 -> value 4.10
        }
    )
    limiter = FakeRateLimiter()

    first = text_of(await portfolio.get_all_positions(client, limiter, FakeConfig()))
    assert "Portfolio Positions (2 total)" in first
    assert len(positions_calls()) == 1

    second = text_of(await portfolio.get_all_positions(client, limiter, FakeConfig()))
    assert second == first  # identical output, zero extra GETs
    assert len(positions_calls()) == 1  # cache hit: no new /positions GET

    third = text_of(
        await portfolio.get_all_positions(client, limiter, FakeConfig(), min_value=4.5)
    )
    assert "Portfolio Positions (1 total)" in third  # 5.00 stays, 4.10 dropped
    assert len(positions_calls()) == 2  # new cache_key -> refetch

    for _, params in positions_calls():
        assert params == {"user": ADDRESS.lower()}  # min_value never reaches the API


async def test_get_all_positions_falls_back_to_avg_price_when_orderbook_fails():
    """Orderbook failure -> current_price = avg_price; the position stays listed."""
    pos = make_position(5, 0.50, "tok_fb", "mkt_fb", "Question fallback avg")
    set_api_routes({POSITIONS_URL: [pos]})

    client = FakePolymarketClient(orderbook_error=RuntimeError("orderbook down"))
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_all_positions(client, limiter, FakeConfig()))

    avg = 0.50
    size = 5
    value = size * avg
    pnl_pct = 0.0 if size * avg <= 0 else (value - size * avg) / (size * avg) * 100
    assert "Portfolio Positions (1 total)" in text  # price failure does not drop it
    assert "Question fallback avg" in text
    assert f"Current: ${avg:.4f} | Value: ${value:.2f}" in text
    assert f"P&L: ${value - size * avg:+.2f} ({pnl_pct:+.2f}%)" in text


async def test_get_all_positions_empty_returns_no_positions_message():
    set_api_routes({POSITIONS_URL: []})
    client = FakePolymarketClient()
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_all_positions(client, limiter, FakeConfig()))

    assert text == "No positions found."


async def test_get_all_positions_http_error_returns_error_text():
    """raise_for_status failure surfaces as error text; nothing propagates."""
    set_api_routes(
        {POSITIONS_URL: FakeResponse([], error=httpx.HTTPError("boom"))}
    )
    client = FakePolymarketClient()
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_all_positions(client, limiter, FakeConfig()))

    assert text.startswith("Error fetching positions:")
    assert "boom" in text
    assert "Portfolio Positions" not in text


async def test_get_position_details_computes_pnl_and_suggestions():
    """Mid-price math, suggestion thresholds, [:5] trade cap, Data API params."""
    market_id = "mkt_details"
    trade_sides = ["BUY", "BUY", "SELL", "BUY", "SELL", "BUY", "SELL"]
    trade_prices = [0.61, 0.62, 0.63, 0.64, 0.65, 0.66, 0.67]
    set_api_routes(
        {
            POSITIONS_URL: [
                make_position(100, 0.40, "tok_details", market_id, "Details question")
            ],
            TRADES_URL: [
                make_trade(market_id, "YES", trade_sides[i], trade_prices[i], 5,
                           BASE_TS + i, i)
                for i in range(7)
            ],
        }
    )

    client = FakePolymarketClient(
        orderbooks={"tok_details": orderbook(0.55, 5, 0.60, 5)}
    )
    limiter = FakeRateLimiter()

    text = text_of(
        await portfolio.get_position_details(client, limiter, FakeConfig(), market_id)
    )

    bid, ask = 0.55, 0.60
    mid = (bid + ask) / 2
    cost_basis = 100 * 0.40
    current_value = 100 * mid
    unrealized = current_value - cost_basis
    pnl_pct = unrealized / cost_basis * 100
    liquidity = bid * 5 + ask * 5

    assert text.startswith("Position Details: Details question")
    assert f"Current Mid Price: ${mid:.4f}" in text
    assert f"Cost Basis: ${cost_basis:.2f}" in text
    assert f"Current Value: ${current_value:.2f}" in text
    assert f"Unrealized P&L: ${unrealized:+.2f} ({pnl_pct:+.2f}%)" in text
    assert f"Liquidity: ${liquidity:.2f}" in text

    # Suggestion thresholds: pnl_pct > 20 and liquidity < 1000 fire; spread 0.05
    # is not > 0.05 and best_bid 0.55 trips neither extreme.
    assert "Consider taking profits" in text
    assert f"Low liquidity (${liquidity:.2f}) - may impact exit price" in text
    assert "Wide spread" not in text
    assert "highly confident" not in text
    assert "lowly valued" not in text
    assert "HOLD - Position within normal parameters" not in text

    # 7 payload trades -> only the first 5 are rendered ([:5]).
    assert text.count(" | BUY ") == 3
    assert text.count(" | SELL ") == 2
    assert f"${trade_prices[4]:.4f}" in text
    assert f"${trade_prices[5]:.4f}" not in text

    # Data API contract: market filter + limit on /trades.
    assert len(positions_calls()) == 1
    assert len(trades_calls()) == 1
    assert positions_calls()[0][1] == {"user": ADDRESS.lower(), "market": market_id}
    assert trades_calls()[0][1] == {
        "user": ADDRESS.lower(),
        "market": market_id,
        "limit": 10,
    }
    assert client.orderbook_tokens == ["tok_details"]


async def test_get_position_details_no_position_message():
    market_id = "mkt_missing"
    set_api_routes({POSITIONS_URL: []})
    client = FakePolymarketClient()
    limiter = FakeRateLimiter()

    text = text_of(
        await portfolio.get_position_details(client, limiter, FakeConfig(), market_id)
    )

    assert text == f"No position found for market {market_id}"
    assert "Position Details" not in text


async def test_get_portfolio_value_sums_cash_positions_and_pending():
    """cash + positions (mid) + pending orders, with the breakdown toggle."""
    from polymarket_mcp.utils.rate_limiter import EndpointCategory

    set_api_routes(
        {
            POSITIONS_URL: [
                make_position(100, 0.40, "tok_val", "mkt_val", "Question valued"),
                # Zero-size position: skipped before any orderbook fetch.
                make_position(0, 0.40, "tok_zero", "mkt_zero", "Question zero value"),
            ]
        }
    )
    client = FakePolymarketClient(
        orderbooks={"tok_val": orderbook(0.49, 5, 0.51, 5)},  # mid 0.50
        balance=100.0,
        orders=[{"size": 10, "price": 0.4}],
    )
    limiter = FakeRateLimiter()

    with_breakdown = text_of(
        await portfolio.get_portfolio_value(client, limiter, FakeConfig())
    )

    mid = (0.49 + 0.51) / 2
    position_value = 100 * mid
    pending = 10 * 0.4
    expected_total = 100.0 + position_value + pending

    assert f"Cash Balance (USDC): ${100.0:.2f}" in with_breakdown
    assert f"Open Positions Value: ${position_value:.2f}" in with_breakdown
    assert f"Pending Orders Value: ${pending:.2f}" in with_breakdown
    assert f"TOTAL PORTFOLIO VALUE: ${expected_total:.2f}" in with_breakdown
    assert "Market Breakdown" in with_breakdown
    assert "(100.0% of positions)" in with_breakdown
    assert f"- YES: 100.00 shares (${position_value:.2f})" in with_breakdown
    assert "Question zero value" not in with_breakdown  # size<=0 skipped

    without = text_of(
        await portfolio.get_portfolio_value(
            client, limiter, FakeConfig(), include_breakdown=False
        )
    )
    assert "Market Breakdown" not in without
    assert f"TOTAL PORTFOLIO VALUE: ${expected_total:.2f}" in without
    assert len(positions_calls()) == 2  # no cache in get_portfolio_value
    assert EndpointCategory.CLOB_GENERAL in limiter.categories


async def test_get_portfolio_value_tolerates_orders_failure():
    """get_orders failure -> pending 0 with warning; total still computed."""
    set_api_routes(
        {POSITIONS_URL: [make_position(100, 0.40, "tok_val", "mkt_val", "Question valued")]}
    )
    client = FakePolymarketClient(
        orderbooks={"tok_val": orderbook(0.49, 5, 0.51, 5)},
        balance=100.0,
        orders_error=RuntimeError("orders down"),
    )
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_portfolio_value(client, limiter, FakeConfig()))

    mid = (0.49 + 0.51) / 2
    expected_total = 100.0 + 100 * mid
    assert "Pending Orders Value: $0.00" in text
    assert f"TOTAL PORTFOLIO VALUE: ${expected_total:.2f}" in text
    assert "Error" not in text


async def test_get_pnl_summary_fifo_realized_and_win_rate():
    """FIFO matching (full + partial close), win rate, start_time per timeframe."""
    market_id = "mkt_fifo"
    # Payload order is deliberately out of chronological order: the FIFO matcher
    # sorts by timestamp (portfolio.py:607) before matching.
    trades = [
        make_trade(market_id, "YES", "SELL", 0.60, 15, BASE_TS + 3, 2),
        make_trade(market_id, "YES", "BUY", 0.40, 10, BASE_TS + 1, 0),
        make_trade(market_id, "YES", "BUY", 0.50, 10, BASE_TS + 2, 1),
    ]
    set_api_routes({TRADES_URL: trades, POSITIONS_URL: []})
    client = FakePolymarketClient()
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_pnl_summary(client, limiter, FakeConfig()))

    # FIFO: full close of 10 @ 0.40 (+2.00) then partial close of 5 @ 0.50 (+0.50).
    expected_realized = (0.60 - 0.40) * 10 + (0.60 - 0.50) * (15 - 10)
    assert f"Realized P&L: ${expected_realized:+.2f}" in text
    assert "Winning Trades: 2" in text
    assert "Losing Trades: 0" in text
    assert "Win Rate: 100.0%" in text
    assert "Closed Trades: 2" in text
    assert "Unrealized P&L: $+0.00" in text  # positions payload is empty
    assert f"Total P&L: ${expected_realized + 0.0:+.2f}" in text

    # timeframe='all': no start_time param reaches the API.
    all_params = trades_calls()[0][1]
    assert all_params == {"user": ADDRESS.lower(), "limit": 500}

    # timeframe='24h': start_time present and int.
    await portfolio.get_pnl_summary(client, limiter, FakeConfig(), timeframe="24h")
    day_params = trades_calls()[-1][1]
    assert "start_time" in day_params
    assert isinstance(day_params["start_time"], int)
    assert day_params["user"] == ADDRESS.lower()
    assert day_params["limit"] == 500

    # Queue exhaustion: a SELL larger than every buy drains the queue with
    # remaining_size > 0 - only the closed lots count toward realized P&L.
    # The unknown-side trade falls through both branches (portfolio.py:617-619).
    set_api_routes(
        {
            TRADES_URL: [
                make_trade(market_id, "YES", "BUY", 0.40, 5, BASE_TS + 1, 0),
                make_trade(market_id, "YES", "SELL", 0.60, 10, BASE_TS + 2, 1),
                make_trade(market_id, "YES", "UNKNOWN", 0.50, 5, BASE_TS + 3, 2),
            ],
            POSITIONS_URL: [],
        }
    )
    exhausted = text_of(await portfolio.get_pnl_summary(client, limiter, FakeConfig()))
    assert f"Realized P&L: ${(0.60 - 0.40) * 5:+.2f}" in exhausted
    assert "Winning Trades: 1" in exhausted
    assert "Closed Trades: 1" in exhausted


async def test_get_pnl_summary_tracks_best_and_worst_performer():
    """No closed trades: unrealized P&L drives best/worst performer sections."""
    set_api_routes(
        {
            TRADES_URL: [],
            # Loser first: the first position seeds BOTH sections; the winner
            # then upgrades best only; the mid performer upgrades neither.
            POSITIONS_URL: [
                make_position(10, 0.70, "tok_lose", "mkt_lose", "Question loser pnl"),
                make_position(10, 0.30, "tok_win", "mkt_win", "Question winner pnl"),
                make_position(10, 0.50, "tok_mid", "mkt_mid", "Question mid pnl"),
                # Zero-size position: skipped before any orderbook fetch.
                make_position(0, 0.50, "tok_zero", "mkt_zero", "Question zero pnl"),
            ],
        }
    )
    client = FakePolymarketClient(
        orderbooks={
            "tok_win": orderbook(0.44, 5, 0.46, 5),  # mid 0.45 -> pnl +1.50
            "tok_lose": orderbook(0.48, 5, 0.52, 5),  # mid 0.50 -> pnl -2.00
            "tok_mid": orderbook(0.45, 5, 0.47, 5),  # mid 0.46 -> pnl -0.40
        }
    )
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_pnl_summary(client, limiter, FakeConfig()))

    win_pnl = ((0.44 + 0.46) / 2 - 0.30) * 10
    lose_pnl = ((0.48 + 0.52) / 2 - 0.70) * 10
    mid_pnl = ((0.45 + 0.47) / 2 - 0.50) * 10
    expected_unrealized = lose_pnl + win_pnl + mid_pnl  # payload order

    assert "Realized P&L: $+0.00" in text
    assert f"Unrealized P&L: ${expected_unrealized:+.2f}" in text
    assert "Closed Trades: 0" in text
    assert "Winning Trades: 0" in text
    assert "Losing Trades: 0" in text
    assert "Win Rate: 0.0%" in text
    assert "Question zero pnl" not in text  # size<=0 skipped in the unrealized loop

    # Each question is rendered exactly once -> section-scoped checks are sound.
    assert text.count("Question winner pnl") == 1
    assert text.count("Question loser pnl") == 1

    best_section = text.split("BEST PERFORMER", 1)[1].split("WORST PERFORMER", 1)[0]
    assert "Question winner pnl" in best_section
    assert "Question loser pnl" not in best_section
    assert f"P&L: ${win_pnl:+.2f}" in best_section

    worst_section = text.split("WORST PERFORMER", 1)[1]
    assert "Question loser pnl" in worst_section
    assert f"P&L: ${lose_pnl:+.2f}" in worst_section


async def test_get_pnl_summary_fifo_losing_trade_counts_as_loss():
    """FIFO edge: SELLs below entry are losses - full and partial closes alike."""
    market_id = "mkt_fifo_loss"
    # SELL 12 @ 0.45: full close of the 0.60 buy (-1.50) then a partial close of
    # 2 shares of the 0.50 buy (-0.10) -> two losses, one SELL.
    trades = [
        make_trade(market_id, "YES", "SELL", 0.45, 12, BASE_TS + 3, 2),
        make_trade(market_id, "YES", "BUY", 0.60, 10, BASE_TS + 1, 0),
        make_trade(market_id, "YES", "BUY", 0.50, 10, BASE_TS + 2, 1),
    ]
    set_api_routes({TRADES_URL: trades, POSITIONS_URL: []})
    client = FakePolymarketClient()
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_pnl_summary(client, limiter, FakeConfig()))

    expected_realized = (0.45 - 0.60) * 10 + (0.45 - 0.50) * 2
    assert f"Realized P&L: ${expected_realized:+.2f}" in text
    assert "Winning Trades: 0" in text
    assert "Losing Trades: 2" in text
    assert "Win Rate: 0.0%" in text
    assert "Closed Trades: 2" in text


async def test_get_position_details_no_trades_and_hold_suggestion():
    """No trades payload and no fired suggestion thresholds -> HOLD line."""
    market_id = "mkt_calm"
    set_api_routes(
        {
            POSITIONS_URL: [
                make_position(10, 0.50, "tok_calm", market_id, "Calm question")
            ],
            TRADES_URL: [],
        }
    )
    # Liquidity 1050 >= 1000 and spread 0.01: no threshold fires.
    client = FakePolymarketClient(orderbooks={"tok_calm": orderbook(0.52, 1000, 0.53, 1000)})
    limiter = FakeRateLimiter()

    text = text_of(
        await portfolio.get_position_details(client, limiter, FakeConfig(), market_id)
    )

    assert "No recent trades" in text
    assert "HOLD - Position within normal parameters" in text
    assert "Low liquidity" not in text
    assert "Consider taking profits" not in text
    assert "Wide spread" not in text
    assert text.count(" | BUY ") + text.count(" | SELL ") == 0


async def test_get_position_details_error_returns_error_text():
    """get_orderbook failure inside details surfaces as error text (never raises)."""
    market_id = "mkt_details_err"
    set_api_routes(
        {POSITIONS_URL: [make_position(10, 0.50, "tok_err", market_id, "Question err")]}
    )
    client = FakePolymarketClient(orderbook_error=RuntimeError("orderbook down"))
    limiter = FakeRateLimiter()

    text = text_of(
        await portfolio.get_position_details(client, limiter, FakeConfig(), market_id)
    )

    assert text.startswith("Error fetching position details:")
    assert "orderbook down" in text
    assert "Position Details:" not in text


async def test_get_portfolio_value_http_error_returns_error_text():
    """Positions HTTP failure inside value surfaces as error text (never raises)."""
    set_api_routes(
        {POSITIONS_URL: FakeResponse([], error=httpx.HTTPError("boom"))}
    )
    client = FakePolymarketClient(balance=50.0)
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_portfolio_value(client, limiter, FakeConfig()))

    assert text.startswith("Error calculating portfolio value:")
    assert "boom" in text
    assert "TOTAL PORTFOLIO VALUE" not in text


async def test_get_pnl_summary_http_error_returns_error_text():
    """Trades HTTP failure inside P&L summary surfaces as error text."""
    set_api_routes({TRADES_URL: FakeResponse([], error=httpx.HTTPError("boom"))})
    client = FakePolymarketClient()
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_pnl_summary(client, limiter, FakeConfig()))

    assert text.startswith("Error calculating P&L summary:")
    assert "boom" in text
    assert "Realized P&L" not in text


async def test_get_portfolio_value_falls_back_to_avg_price_when_orderbook_fails():
    """Orderbook failure in value -> mid falls back to avg_price (never raises)."""
    set_api_routes(
        {POSITIONS_URL: [make_position(100, 0.40, "tok_fb", "mkt_fb", "Fallback question")]}
    )
    client = FakePolymarketClient(
        orderbook_error=RuntimeError("orderbook down"), balance=10.0
    )
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_portfolio_value(client, limiter, FakeConfig()))

    assert f"Open Positions Value: ${100 * 0.40:.2f}" in text
    assert f"TOTAL PORTFOLIO VALUE: ${10.0 + 100 * 0.40:.2f}" in text


async def test_get_pnl_summary_falls_back_to_avg_price_when_orderbook_fails():
    """Orderbook failure in P&L summary -> mid falls back to avg_price."""
    set_api_routes(
        {
            TRADES_URL: [],
            POSITIONS_URL: [
                make_position(10, 0.50, "tok_fb", "mkt_fb", "Fallback question")
            ],
        }
    )
    client = FakePolymarketClient(orderbook_error=RuntimeError("orderbook down"))
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.get_pnl_summary(client, limiter, FakeConfig()))

    assert "Realized P&L: $+0.00" in text
    assert "Unrealized P&L: $+0.00" in text  # mid = avg -> zero unrealized P&L
    assert "Total P&L: $+0.00" in text
    assert "BEST PERFORMER" in text  # position still tracked with pnl 0.0


async def test_get_position_details_loss_wide_spread_and_extreme_bids():
    """Cutting-losses/wide-spread thresholds and the extreme best_bid branches."""
    market_id = "mkt_loss"
    set_api_routes(
        {
            POSITIONS_URL: [
                make_position(10, 0.60, "tok_loss", market_id, "Loss question")
            ],
            TRADES_URL: [],
        }
    )
    client = FakePolymarketClient(orderbooks={"tok_loss": orderbook(0.30, 5, 0.50, 5)})
    limiter = FakeRateLimiter()

    text = text_of(
        await portfolio.get_position_details(client, limiter, FakeConfig(), market_id)
    )

    spread = 0.50 - 0.30
    mid = (0.30 + 0.50) / 2
    unrealized = 10 * mid - 10 * 0.60
    pnl_pct = unrealized / (10 * 0.60) * 100
    assert "Position down >15% - consider cutting losses or averaging down" in text
    assert f"Wide spread ({spread:.4f}) - may be difficult to exit at fair price" in text
    assert f"Unrealized P&L: ${unrealized:+.2f} ({pnl_pct:+.2f}%)" in text

    # Second scenario: extreme best bids flip the confidence suggestion.
    set_api_routes(
        {
            POSITIONS_URL: [
                make_position(10, 0.50, "tok_high", "mkt_high", "High question")
            ],
            TRADES_URL: [],
        }
    )
    client = FakePolymarketClient(orderbooks={"tok_high": orderbook(0.95, 5, 0.96, 5)})
    high_text = text_of(
        await portfolio.get_position_details(client, limiter, FakeConfig(), "mkt_high")
    )
    assert "Market highly confident - consider closing position if you disagree" in high_text

    set_api_routes(
        {
            POSITIONS_URL: [
                make_position(10, 0.50, "tok_low", "mkt_low", "Low question")
            ],
            TRADES_URL: [],
        }
    )
    client = FakePolymarketClient(orderbooks={"tok_low": orderbook(0.05, 5, 0.08, 5)})
    low_text = text_of(
        await portfolio.get_position_details(client, limiter, FakeConfig(), "mkt_low")
    )
    assert "Market lowly valued - high upside if outcome occurs" in low_text


def test_portfolio_cache_expiry_evicts_and_returns_none():
    """PortfolioDataCache: miss -> None; hit -> value; stale entry evicted."""
    cache = portfolio.PortfolioDataCache(ttl_seconds=30)
    assert cache.get("missing") is None

    cache.set("k", {"positions": 1})
    assert cache.get("k") == {"positions": 1}

    # Age the stored timestamp past the TTL directly (zero sleep, L-0014).
    value, stored_ts = cache._cache["k"]
    cache._cache["k"] = (value, stored_ts - 31)
    assert cache.get("k") is None
    assert "k" not in cache._cache  # expired entry removed (portfolio.py:34)

    cache.set("other", 2)
    cache.clear()
    assert cache.get("other") is None
    assert cache._cache == {}
