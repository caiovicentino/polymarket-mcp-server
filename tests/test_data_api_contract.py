"""Contract suite for the REAL Data-API response shapes (positions, trades,
activity) against the code that consumes them.

Findings proven live first-hand (curator preflight 2026-09-17; public
stateless endpoints, data-api.polymarket.com):

- GET /positions?user=<addr> -> 200 list; camelCase fields: asset,
  avgPrice, curPrice, currentValue, percentPnl, cashPnl, realizedPnl,
  outcome, outcomeIndex, size, conditionId, slug, title, endDate,
  redeemable, negativeRisk, eventId, eventSlug, totalBought,
  grossInitialValue, initialValue, entryFeesUsdc, oppositeAsset,
  oppositeOutcome, mergeable, icon, proxyWallet.
  ABSENT: average_price, asset_id, market, market_question, value.
  The consumers read the ABSENT snake_case names:
    portfolio.py  x8 'average_price' sites, x7 'asset_id' sites,
                  'market' x3 (:121/:444/:596), 'market_question' output,
                  pos['value'] :512 direct index
    trading.py    _convert_positions :1217 (asset_id/market/avg_price)
  Consequences: avg_price=0.0 (cost_basis=0 -> unrealized_pnl = full
  current value), token_id=None -> get_orderbook(None) raises -> caught ->
  current_price=0.0 -> current_value=0.0 < min_value -> EVERY position
  filtered -> "No positions found." despite real positions (proven live:
  a wallet with 13 positions).
- GET /trades?limit=N -> 200 list; fields: asset, bio, conditionId,
  eventSlug, icon, name, outcome, outcomeIndex, price, profileImage,
  profileImageOptimized, proxyWallet, pseudonym, side, size, slug,
  timestamp (int epoch), title, transactionHash.
  ABSENT: 'market' (portfolio.py:596 groups FIFO P&L under None -> all
  trades lumped in one bucket -> cross-market buy/sell matching).
- GET /activity?user=<addr> -> 200 list; fields: type (TRADE), timestamp,
  size, price, usdcSize, title, conditionId, side, transactionHash,
  outcome, outcomeIndex, asset, eventSlug, slug, icon, name, bio,
  profileImage(+Optimized), proxyWallet, pseudonym.
  ABSENT: amount, value, market_question, transaction_hash
  (portfolio.py:940-944 -> "Market: N/A", "Amount: 0.00 | Value: $0.00",
  "Tx Hash: N/A..." for every event).

This suite pins the REAL shapes as xfail(strict=True) (the flip contract
for the human fix -- precedent R3/tests/test_safety_adversarial.py and
T-0212: the plugin blocks agents from editing existing tests). Fakes feed
the REAL-shaped payloads through the module seams (P-0031 fail-loud, same
anatomy as tests/test_portfolio_gaps_offline.py). When the fix lands the
xfails flip to FAIL and the fix's flips consume them.

Fix-agnostic outcome pins: the fix may normalize at the fetch boundary
(client.get_positions + the direct httpx fetches) or at the read sites
(camelCase reads) -- the pinned observables are identical either way.
Known flip targets when the fix lands: tests/test_portfolio_analysis_offline.py
and tests/test_portfolio_gaps_offline.py (snake_case fixtures feeding the
seams), tests/test_client_compat.py:193 (raw passthrough identity of
client.get_positions -- breaks only under the normalize-at-boundary
option).
"""

import pytest

import polymarket_mcp.tools.portfolio as portfolio
from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.safety_limits import Position, SafetyLimits

ADDRESS = "0xAbCdEf0123456789AbCdEf0123456789aBcDeF01"
TOKEN_ID = (
    "111061902544814266207267295505639408607400625795891618462682726460921782993748"
)
CONDITION_ID = "0xdf9bf27ee5757c55b44b8b9826ddc9ec3a8809aa3278634c45edbb7fc8f1a3e3"
POSITIONS_URL = "https://data-api.polymarket.com/positions"
TRADES_URL = "https://data-api.polymarket.com/trades"
ACTIVITY_URL = "https://data-api.polymarket.com/activity"
LOGGER_NAME = "polymarket_mcp.tools.portfolio"

# --- Real-shaped fixtures (field-for-field from the live API) -------------

REAL_POSITION = {
    "asset": TOKEN_ID,
    "avgPrice": 0.3789,
    "cashPnl": -12.1744,
    "conditionId": CONDITION_ID,
    "curPrice": 0,
    "currentValue": 0,
    "endDate": "2027-01-01T04:59:00Z",
    "eventId": "1",
    "eventSlug": "example-event",
    "grossInitialValue": 12.1744,
    "icon": "https://polymarket-upload.s3.amazonaws.com/icon.png",
    "initialValue": 12.1744,
    "mergeable": True,
    "negativeRisk": False,
    "oppositeAsset": "53802988913486039264903583858360705910611596492194108642493072174015304337587",
    "oppositeOutcome": "No",
    "outcome": "Jennifer Ruggeri",
    "outcomeIndex": 0,
    "percentPnl": -99.9994,
    "percentRealizedPnl": 73.1389,
    "proxyWallet": "0xe7fe243cedf4c0ae5a8d208c8508103c581e261e",
    "realizedPnl": 8.9034,
    "redeemable": True,
    "size": 32.1292,
    "slug": "example-market",
    "title": "Spread: Bills (-10.5)",
    "totalBought": 32.1292,
}

REAL_TRADES = [
    {
        "proxyWallet": "0xe7fe243cedf4c0ae5a8d208c8508103c581e261e",
        "side": "BUY",
        "asset": TOKEN_ID,
        "conditionId": CONDITION_ID,
        "size": 10.0,
        "price": 0.40,
        "timestamp": 1789687906,
        "title": "Spread: Bills (-10.5)",
        "outcome": "Jennifer Ruggeri",
        "outcomeIndex": 0,
        "slug": "example-market",
        "eventSlug": "example-event",
        "transactionHash": "0xabc123",
    },
    {
        "proxyWallet": "0xe7fe243cedf4c0ae5a8d208c8508103c581e261e",
        "side": "SELL",
        "asset": TOKEN_ID,
        "conditionId": CONDITION_ID,
        "size": 4.0,
        "price": 0.60,
        "timestamp": 1789688006,
        "title": "Spread: Bills (-10.5)",
        "outcome": "Jennifer Ruggeri",
        "outcomeIndex": 0,
        "slug": "example-market",
        "eventSlug": "example-event",
        "transactionHash": "0xabc456",
    },
]

REAL_ACTIVITY = {
    "proxyWallet": "0xe7fe243cedf4c0ae5a8d208c8508103c581e261e",
    "type": "TRADE",
    "timestamp": 1789688271,
    "side": "SELL",
    "size": 6.02,
    "price": 0.67,
    "usdcSize": 3.96685,
    "title": "Spread: Bills (-10.5)",
    "conditionId": "0x79f9e94cf6793d0c3792e15c6820d5d35cd950a29b6378075a677c99bf9cb284",
    "outcome": "Jennifer Ruggeri",
    "outcomeIndex": 0,
    "asset": TOKEN_ID,
    "slug": "example-market",
    "eventSlug": "example-event",
    "transactionHash": "0xdeadbeef12345678",
}


# --- Seams (mirror test_portfolio_gaps_offline.py; P-0031 fail-loud) ------

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
    def __init__(self, books=None, fail_tokens=()):
        self._books = dict(books or {})
        self._fail_tokens = set(fail_tokens)
        self.orderbook_calls = []

    async def get_orderbook(self, token_id):
        self.orderbook_calls.append(token_id)
        if token_id in self._fail_tokens:
            raise RuntimeError(f"synthetic orderbook failure for {token_id}")
        if token_id not in self._books:
            raise AssertionError(f"unexpected get_orderbook token: {token_id}")
        return self._books[token_id]


class FakeRateLimiter:
    def __init__(self):
        self.categories = []

    async def acquire(self, category):
        self.categories.append(category)
        return 0.0


class FakeConfig:
    POLYGON_ADDRESS = ADDRESS


def book(bid, ask, level_size):
    return {
        "bids": [{"price": bid, "size": level_size} for _ in range(5)],
        "asks": [{"price": ask, "size": level_size} for _ in range(5)],
    }


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, request):
    portfolio._portfolio_cache.clear()
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = {}
    # FakeAsyncClient is an OFFLINE seam only: it must NOT swallow the real
    # httpx used by the live (integration) tests below. portfolio.httpx IS
    # the global httpx module, so patching it unconditionally would route
    # the live tests to the stub (proven live 2026-09-17: AssertionError
    # "unexpected URL routed to stub"). Gate the patch on the marker.
    if not request.node.get_closest_marker("integration"):
        monkeypatch.setattr(portfolio.httpx, "AsyncClient", FakeAsyncClient)
    yield
    portfolio._portfolio_cache.clear()


# --- Offline xfail-strict pins (the flip contract) -------------------------

@pytest.mark.xfail(reason="portfolio reads average_price/asset_id/market/"
                          "market_question absent from the real Data API "
                          "(REQUER-HUMANO item 140)", strict=True)
@pytest.mark.asyncio
async def test_positions_surface_real_shaped_position():
    """get_all_positions must surface a REAL-shaped position.

    Real-shaped fix expected: avg_price = avgPrice (0.3789), token_id =
    asset, market_question = title, orderbook fetched for the real token.
    Today: avg_price=0.0 -> current_price=0.0 -> current_value=0.0 <
    min_value=1.0 -> position filtered -> "No positions found." even
    though the wallet holds positions (proven live).
    """
    FakeAsyncClient.responses[POSITIONS_URL] = [REAL_POSITION]
    client = FakePolymarketClient(books={TOKEN_ID: book(0.45, 0.47, "100")})
    limiter = FakeRateLimiter()

    result = await portfolio.get_all_positions(
        polymarket_client=client, rate_limiter=limiter, config=FakeConfig()
    )

    text = result[0].text
    assert "No positions found" not in text
    assert "0.3789" in text  # the REAL avgPrice surfaced
    assert REAL_POSITION["title"] in text
    assert client.orderbook_calls == [TOKEN_ID]


@pytest.mark.xfail(reason="real trades carry conditionId, not 'market' -- "
                          "FIFO groups under None (REQUER-HUMANO item 140)",
                   strict=True)
@pytest.mark.asyncio
async def test_pnl_summary_fifo_separates_real_markets():
    """get_pnl_summary must group trades PER MARKET (conditionId).

    Two markets, one round-trip each:
      A: BUY 10 @ 0.40 (ts 1000), SELL 5 @ 0.60 (ts 2000) -> +1.00
      B: BUY 10 @ 0.30 (ts 3000), SELL 5 @ 0.50 (ts 4000) -> +1.00
    Per-market FIFO (expected): realized = +2.00.
    Cross-market lump (today, all under None): the second sell matches the
    FIRST market's remaining buy at 0.40 -> (0.50-0.40)*5 = +0.50 ->
    realized = +1.50. The aggregate differs -> honest discriminating pin.
    """
    market_a = "0x" + "a" * 64
    market_b = "0x" + "b" * 64
    tok_a = "111" + "0" * 74
    tok_b = "222" + "0" * 74
    trades = [
        dict(REAL_TRADES[0], conditionId=market_a, asset=tok_a, size=10.0, price=0.40, timestamp=1000),
        dict(REAL_TRADES[1], conditionId=market_a, asset=tok_a, size=5.0, price=0.60, timestamp=2000),
        dict(REAL_TRADES[0], conditionId=market_b, asset=tok_b, side="BUY", size=10.0, price=0.30, timestamp=3000),
        dict(REAL_TRADES[1], conditionId=market_b, asset=tok_b, side="SELL", size=5.0, price=0.50, timestamp=4000),
    ]
    FakeAsyncClient.responses[TRADES_URL] = trades
    FakeAsyncClient.responses[POSITIONS_URL] = []
    client = FakePolymarketClient(books={})
    limiter = FakeRateLimiter()

    result = await portfolio.get_pnl_summary(
        polymarket_client=client, rate_limiter=limiter, config=FakeConfig(),
        timeframe="all",
    )

    text = result[0].text
    assert "Realized P&L: $+2.00" in text


@pytest.mark.xfail(reason="activity reads amount/value/market_question/"
                          "transaction_hash absent from the real /activity "
                          "(REQUER-HUMANO item 140)", strict=True)
@pytest.mark.asyncio
async def test_activity_log_reads_real_fields():
    """get_activity_log must render the REAL fields (title/size/usdcSize/tx)."""
    FakeAsyncClient.responses[ACTIVITY_URL] = [REAL_ACTIVITY]
    limiter = FakeRateLimiter()

    result = await portfolio.get_activity_log(
        polymarket_client=None, rate_limiter=limiter, config=FakeConfig(), limit=10
    )

    text = result[0].text
    assert REAL_ACTIVITY["title"] in text          # today: "Market: N/A"
    assert "6.02" in text                          # today: "Amount: 0.00"
    assert "3.97" in text or "3.96685" in text     # today: "Value: $0.00"
    assert "0xdeadbeef" in text                    # today: "Tx Hash: N/A..."


@pytest.mark.xfail(reason="_convert_positions reads asset_id/avg_price/"
                          "market absent from the real Data API "
                          "(REQUER-HUMANO item 140)", strict=True)
def test_convert_positions_reads_real_fields():
    """trading._convert_positions must map the real camelCase fields."""
    tools = TradingTools(
        client=object(),  # _convert_positions never touches the client
        safety_limits=SafetyLimits(
            max_order_size_usd=1_000.0,
            max_total_exposure_usd=10_000.0,
            max_position_size_per_market=10_000.0,
            min_liquidity_required=100.0,
            max_spread_tolerance=0.5,
            require_confirmation_above_usd=500.0,
        ),
        config=PolymarketConfig(
            POLYGON_PRIVATE_KEY="0" * 63 + "1",
            POLYGON_ADDRESS="0x" + "0" * 40,
            POLYMARKET_CHAIN_ID=137,
            _env_file=None,
        ),
    )

    positions = tools._convert_positions([REAL_POSITION])

    assert len(positions) == 1
    pos = positions[0]
    assert pos == Position(
        token_id=TOKEN_ID,
        market_id=CONDITION_ID,
        size=32.1292,
        avg_price=0.3789,
        current_price=0.3789,  # falls back to avg_price (curPrice absent/0)
        unrealized_pnl=0.0,
    )


# ---------------------------------------------------------------------------
# Live contract (integration; deselected by the offline suite run)
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_positions_field_contract():
    """Prove the real /positions shape: camelCase fields present.

    The user address is harvested from the public trades feed at runtime
    (no hardcoded address); positions for a random wallet may be an empty
    list -- the FIELD CONTRACT holds for any entry when present.
    """
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        trades = (await client.get("https://data-api.polymarket.com/trades", params={"limit": 3})).json()
        assert isinstance(trades, list) and trades
        for t in trades:
            for field in ("side", "size", "price", "timestamp", "asset", "conditionId", "proxyWallet"):
                assert field in t, f"trade missing {field}"
        user = trades[0]["proxyWallet"]
        positions = (
            await client.get("https://data-api.polymarket.com/positions", params={"user": user})
        ).json()
        assert isinstance(positions, list)
        for p in positions:
            for field in ("avgPrice", "asset", "size", "curPrice", "currentValue", "conditionId", "title"):
                assert field in p, f"position missing {field}"
            for absent in ("average_price", "asset_id", "market", "market_question"):
                assert absent not in p, f"position unexpectedly has {absent}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_activity_field_contract():
    """Prove the real /activity shape: type/size/usdcSize/title present."""
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        trades = (await client.get("https://data-api.polymarket.com/trades", params={"limit": 1})).json()
        user = trades[0]["proxyWallet"]
        activities = (
            await client.get("https://data-api.polymarket.com/activity", params={"user": user, "limit": 3})
        ).json()
        assert isinstance(activities, list)
        for a in activities:
            for field in ("type", "timestamp", "size", "usdcSize", "title", "conditionId"):
                assert field in a, f"activity missing {field}"
            for absent in ("amount", "value", "market_question", "transaction_hash"):
                assert absent not in a, f"activity unexpectedly has {absent}"
