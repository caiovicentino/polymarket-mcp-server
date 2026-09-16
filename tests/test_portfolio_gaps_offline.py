"""
Offline gap-closing suite for the RESIDUAL branches of
src/polymarket_mcp/tools/portfolio.py (contract T-0060).

Baseline at the claim tip (L-0096, proved, not assumed)
-------------------------------------------------------
Clone tip 94899fe (farm-fix/ci-p1-1; src/ identical to main 2f28d21 and
9e675da -- portfolio.py blob 2f92205f13a9c8e068f7bbd3a3425cbaf31c7abb in all
three). Coverage of the full release-gate suite at that tip: 548 stmts,
29 missed, 184 branches, 11 partial -> 94.54%. Miss lines: 144, 858-860,
903-904, 907-908, 958-960, 1012, 1075->1079, 1084, 1091, 1093, 1192-1194,
1249, 1270-1274, 1376, 1404, 1427-1429.

Branches pinned per L-0025 (source of truth = code, divergences declared)
------------------------------------------------------------------------
- get_all_positions filter :143-144 (`if not include_closed and size <= 0`):
  DEAD CODE by construction -- the unconditional skip at :116-117 already
  dropped every size<=0 position before :143 is reached, so the :144
  `continue` is unreachable for ANY include_closed value. The suite pins the
  OBSERVED behavior: a size<=0 position is absent with include_closed=False
  (mandatory test) AND with include_closed=True (contradictory pair proving
  the dead branch; the contract's premise "include_closed=True -> presentes"
  is false for this code). Line :144 remains uncovered -- residual justified
  in the report (product follow-up, never patched in a SUITE-ONLY slice).
- get_trade_history error envelope :858-860 -> exact TextContent
  "Error fetching trade history: boom".
- get_activity_log date conversion :903-904/:907-908: ISO strings WITH and
  WITHOUT the Z suffix -> params["start_time"]/["end_time"] = int(epoch),
  asserted with the SAME expression as the code (timezone-independent).
- get_activity_log error envelope :958-960 -> "Error fetching activity log: boom".
- analyze_portfolio_risk non-positive skip :1012: size<=0 positions never
  reach the orderbook seam (mechanical pin on the fake's call list) and never
  enter the counts.
- analyze_portfolio_risk penalty tiers: the contract labeled :1084/:1091/:1093
  as "liquidity penalty tiers", but the CODE shows :1084 is the MARKET
  concentration tier (`elif market_concentration > 30: += 10`, :1079-1084)
  while :1091/:1093 are the liquidity tiers (+15/+10). Per L-0020/L-0090 the
  tests follow the code. The contract's mechanism sketch "1 position per case
  -> liquidity_risk_pct >50/>30/>10" is unreachable for the >30/>10 tiers
  (with 1 position the ratio is only 0% or 100%) -- scenarios are derived to
  EXCLUDE the prior branch (L-0109): 2/4 = 50.0% (not > 50) fires :1091;
  1/4 = 25.0% (not > 30) fires :1093. Note the low-liquidity count only
  increments for positions whose orderbook fetch SUCCEEDS with top-5
  liquidity < 1000 (:1045-1054, the append is inside the try) -- thin books,
  not failed fetches. The constant 20 of the >50 tier (:1088) is already
  pinned by the sister suite (84/100 scenario) -- see "Already Covered".
- analyze_portfolio_risk fall-through arc :1075->1079: concentration_risk
  <= 20 with 5x20% equal positions -> score 0 (LOW, "acceptable parameters").
- analyze_portfolio_risk error envelope :1192-1194 -> "Error analyzing
  portfolio risk: boom".
- suggest_portfolio_actions non-positive skip :1249: same mechanical pin
  (no orderbook fetch for the dead weight).
- suggest_portfolio_actions orderbook-failure fallback :1270-1274: the failing
  token gets mid_price = avg_price, spread = 0, total_liquidity = 0 --
  observable as value 50.00 in "Analyzed 2 positions worth $115.00", a
  concentration REDUCE block for the failed position (mid = avg keeps it at
  43.5% > 30), an "Exit low liquidity position ($0.00 available)" CLOSE block,
  and the warning "Failed to fetch orderbook for tok-fail" via caplog.
- suggest_portfolio_actions wide-spread REDUCE :1375-1383: spread > 0.10
  (0.20) -> "Wide spread (20.0%)" blocks; never fired by the sisters
  (spreads < 0.10 there).
- suggest_portfolio_actions no-actions message :1403-1408: balanced
  positions (pnl 0, concentration 25%, deep books, zero spread) -> exact
  literals "No optimization actions recommended at this time." and
  "Portfolio appears well-balanced for your goals."; contradictory pair with
  avg_price shifted so pnl_pct crosses the take-profit threshold -> message
  absent.
- suggest_portfolio_actions error envelope :1427-1432 -> "Error generating
  portfolio suggestions: boom".

Seams (module-level, zero network, zero sleep)
----------------------------------------------
- portfolio.httpx.AsyncClient -> FakeAsyncClient (mirrors
  tests/test_portfolio_positions_offline.py): portfolio.py resolves the
  attribute at call time (:87, :795, :899, :996, :1225), so
  monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient) intercepts every
  Data API call; routes are exact-URL and fail loud for unexpected URLs
  (P-0031); FakeResponse carries an optional error for the envelopes.
- polymarket_client -> FakePolymarketClient: books per token, fail_tokens per
  token raising RuntimeError, unexpected token -> AssertionError (fail loud).
- rate_limiter -> FakeRateLimiter (async acquire(category) records categories;
  L-0123: portfolio.py never imports get_rate_limiter -- the limiter is a
  PARAMETER of every tool here, so the recording fake IS the sanctioned seam;
  the real singleton is never touched and no real acquire can happen).
- config -> FakeConfig (POLYGON_ADDRESS; the code lowercases it).

Isolation: the autouse fixture clears the module-global _portfolio_cache
(:47) before AND after every test and resets the class-level stub state;
monkeypatch restores httpx.AsyncClient at teardown. pytest-asyncio auto mode
(pyproject.toml:80); no integration/slow/real_api markers -- runs under the
release gate; .venv symlink + PYTHONPATH=src per P-0019.

Lessons: L-0002 (semantic asserts), L-0014 (zero sleep), L-0020/L-0090
(asserts follow the observed code; divergences declared above), L-0109
(contradictory pairs pin branch exclusion), L-0115/L-0124 (mutation oracle),
L-0118 (stub installed before any execution; exploration read-only), L-0123
(recording fake limiter; singleton untouched), P-0031 (fail-loud module
seams). Overlap with the sister suites is calibrated in the report's
"Already Covered" section.
"""
import logging
import re

import httpx
import pytest

import polymarket_mcp.tools.portfolio as portfolio

ADDRESS = "0xAbCdEf0123456789AbCdEf0123456789aBcDeF01"
POSITIONS_URL = "https://data-api.polymarket.com/positions"
TRADES_URL = "https://data-api.polymarket.com/trades"
ACTIVITY_URL = "https://data-api.polymarket.com/activity"
LOGGER_NAME = "polymarket_mcp.tools.portfolio"


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
    instance (`async with httpx.AsyncClient(timeout=30.0)`); the autouse
    fixture resets it before every test. Routes are EXACT URLs; anything else
    fails loud. __init__ accepts the documented timeout kwarg only (L-0121).
    """

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
    """Duck-typed client stub: get_orderbook with per-token books/failures."""

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


def orderbook(bid, ask, level_size):
    """Orderbook payload: five identical levels per side.

    Top-5 liquidity = 5*bid*level_size + 5*ask*level_size, mirroring the
    bids[:5]/asks[:5] sums the code computes.
    """
    return {
        "bids": [{"price": bid, "size": level_size} for _ in range(5)],
        "asks": [{"price": ask, "size": level_size} for _ in range(5)],
    }


def deep_book(mid, level_size=700):
    """Book whose top-5 liquidity >= 1000 by construction: mid*level_size*10."""
    return orderbook(mid, mid, level_size)


def thin_book(mid, level_size=10):
    """Book whose top-5 liquidity is far below 1000 (counts as low liquidity)."""
    return orderbook(mid, mid, level_size)


def set_api_routes(routes):
    """Route the installed AsyncClient stub: URL -> payload/FakeResponse."""
    FakeAsyncClient.responses = dict(routes)


def text_of(content):
    """Extract the single text payload of a [types.TextContent] return value."""
    assert len(content) == 1
    assert content[0].type == "text"
    return content[0].text


def api_calls(url):
    """(url, params) pairs recorded for one Data API endpoint."""
    return [c for c in FakeAsyncClient.calls if c[0] == url]


def suggestion_blocks(text):
    """Split the SUGGESTED ACTIONS section into numbered suggestion blocks."""
    blocks = []
    current = None
    for line in text.splitlines():
        if re.match(r"^\d+\. ", line):
            current = [line]
            blocks.append(current)
        elif current is not None:
            current.append(line)
    return ["\n".join(block) for block in blocks]


def block_with(blocks, needle):
    """The (unique) suggestion block containing `needle`."""
    matches = [block for block in blocks if needle in block]
    assert len(matches) == 1, f"expected exactly one block containing {needle!r}"
    return matches[0]


@pytest.fixture(autouse=True)
def isolated_portfolio(monkeypatch):
    """Per-test isolation: reset the global cache and the class-level stub.

    The cache is module-global (portfolio.py:47); clearing it before/after
    every test keeps suite order independent. monkeypatch restores
    httpx.AsyncClient at teardown (L-0118: the stub is in place before any
    execution; no real network path can be reached).
    """
    portfolio._portfolio_cache.clear()
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = {}
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    yield
    portfolio._portfolio_cache.clear()


# ---------------------------------------------------------------------------
# get_all_positions residual: the include_closed dead filter (:143-144)
# ---------------------------------------------------------------------------
async def test_get_positions_skips_nonpositive_when_not_include_closed():
    """Mandatory: size<=0 skipped under include_closed=False (default).

    The skip happens at the UNconditional :116-117; the contract's
    include_closed-aware filter :143-144 is unreachable (dead code) -- pinned
    by the contradictory pair in the complementary test below. Derived
    observables: only the size>0 position survives (value 10*0.35 = 3.50).
    """
    zero = make_position(0, 0.40, "tok-zero", "mkt-zero", "Question zero size")
    valid = make_position(10, 0.30, "tok-valid", "mkt-valid", "Question valid size")
    set_api_routes({POSITIONS_URL: [zero, valid]})

    client = FakePolymarketClient(books={"tok-valid": deep_book(0.35)})
    limiter = FakeRateLimiter()

    text = text_of(
        await portfolio.get_all_positions(
            client, limiter, FakeConfig(), include_closed=False
        )
    )

    assert "Portfolio Positions (1 total)" in text
    assert "Question zero size" not in text
    assert "Question valid size" in text
    assert f"Current: ${0.35:.4f} | Value: ${10 * 0.35:.2f}" in text
    # Mechanical pin (P-0031): the size<=0 position never reaches the orderbook
    # seam -- it is dropped at :116 BEFORE any fetch.
    assert client.orderbook_calls == ["tok-valid"]
    assert [cat.name for cat in limiter.categories] == ["DATA_API", "MARKET_DATA"]


async def test_get_positions_nonpositive_skipped_even_with_include_closed():
    """Complementary contradictory pair (L-0109): include_closed=True does NOT
    resurrect size<=0 positions. If the :143-144 filter were reachable, the
    include_closed=True call would list the zero-size position -- it does not.
    Distinct cache keys (positions_True_1.0 / positions_False_1.0) force two
    refetches; both list only the valid position."""
    zero = make_position(0, 0.40, "tok-zero", "mkt-zero", "Question zero size")
    valid = make_position(10, 0.30, "tok-valid", "mkt-valid", "Question valid size")
    set_api_routes({POSITIONS_URL: [zero, valid]})

    client = FakePolymarketClient(books={"tok-valid": deep_book(0.35)})
    limiter = FakeRateLimiter()

    closed_text = text_of(
        await portfolio.get_all_positions(
            client, limiter, FakeConfig(), include_closed=True
        )
    )
    open_text = text_of(
        await portfolio.get_all_positions(
            client, limiter, FakeConfig(), include_closed=False
        )
    )

    # Same observable outcome either way: zero-size never listed (L-0025).
    for text in (closed_text, open_text):
        assert "Portfolio Positions (1 total)" in text
        assert "Question zero size" not in text
    # Distinct cache keys -> two refetches.
    assert len(api_calls(POSITIONS_URL)) == 2
    assert client.orderbook_calls == ["tok-valid", "tok-valid"]


# ---------------------------------------------------------------------------
# get_trade_history residual: error envelope (:858-860)
# ---------------------------------------------------------------------------
async def test_get_trade_history_error_returns_error_text_content():
    """Mandatory: a Data API failure surfaces as the exact error TextContent
    (prefix + str(e), L-0020) instead of raising."""
    set_api_routes({TRADES_URL: FakeResponse([], error=httpx.HTTPError("boom"))})
    limiter = FakeRateLimiter()

    result = await portfolio.get_trade_history(
        FakePolymarketClient(), limiter, FakeConfig()
    )

    assert result[0].type == "text"
    assert result[0].text == "Error fetching trade history: boom"


# ---------------------------------------------------------------------------
# get_activity_log residuals: date conversion (:903-908) + error (:958-960)
# ---------------------------------------------------------------------------
async def test_get_activity_log_converts_dates_to_epoch_params():
    """Mandatory: start_date/end_date become int epoch params (:903-908).

    Two calls: WITH the Z suffix (fromisoformat(replace('Z', '+00:00'))) and
    WITHOUT (naive fromisoformat). Both expected values are computed with the
    SAME expression as the code, so the assert is timezone-independent (the
    naive variant uses the process-local tz on both sides).
    """
    from datetime import datetime

    limiter = FakeRateLimiter()

    start_z = "2026-01-01T00:00:00Z"
    end_naive = "2026-02-01T12:30:45"
    set_api_routes({ACTIVITY_URL: []})
    await portfolio.get_activity_log(
        FakePolymarketClient(),
        limiter,
        FakeConfig(),
        start_date=start_z,
        end_date=end_naive,
    )
    expected_start_z = int(datetime.fromisoformat(start_z.replace("Z", "+00:00")).timestamp())
    expected_end_naive = int(datetime.fromisoformat(end_naive).timestamp())

    start_naive = "2026-03-01T08:15:00"
    end_z = "2026-04-01T00:00:00Z"
    await portfolio.get_activity_log(
        FakePolymarketClient(),
        limiter,
        FakeConfig(),
        start_date=start_naive,
        end_date=end_z,
    )
    expected_start_naive = int(datetime.fromisoformat(start_naive).timestamp())
    expected_end_z = int(datetime.fromisoformat(end_z.replace("Z", "+00:00")).timestamp())

    calls = api_calls(ACTIVITY_URL)
    assert len(calls) == 2
    assert calls[0][1] == {
        "user": ADDRESS.lower(),
        "limit": 100,
        "start_time": expected_start_z,
        "end_time": expected_end_naive,
    }
    assert calls[1][1] == {
        "user": ADDRESS.lower(),
        "limit": 100,
        "start_time": expected_start_naive,
        "end_time": expected_end_z,
    }
    # int (not float/str): the epoch params are ints by construction.
    assert isinstance(calls[0][1]["start_time"], int)
    assert isinstance(calls[1][1]["end_time"], int)
    # Rate limiter engaged once per call for the DATA_API category (L-0123).
    assert len(limiter.categories) == 2


async def test_get_activity_log_error_returns_error_text_content():
    """Mandatory: Data API failure -> exact error TextContent (:958-960)."""
    set_api_routes({ACTIVITY_URL: FakeResponse([], error=httpx.HTTPError("boom"))})
    limiter = FakeRateLimiter()

    result = await portfolio.get_activity_log(FakePolymarketClient(), limiter, FakeConfig())

    assert result[0].type == "text"
    assert result[0].text == "Error fetching activity log: boom"


# ---------------------------------------------------------------------------
# analyze_portfolio_risk residuals: skips (:1012), tiers (:1084/:1091/:1093),
# fall-through arc (:1075->1079), error envelope (:1192-1194)
# ---------------------------------------------------------------------------
async def test_analyze_portfolio_risk_skips_nonpositive_sizes():
    """Mandatory: size<=0 positions are dropped BEFORE the orderbook seam and
    never enter exposure/markets/counts (:1012).

    Contradictory pair: the valid position IS analyzed. Expected score derived
    from :1071-1096 for this payload: concentration 100% -> +40; market
    concentration 100% -> +30; liquidity 0 -> +0; diversification min(100,
    10+20) = 30; 70 - 30//5 = 64 -> HIGH.
    """
    zero = make_position(0, 0.50, "tok-zero", "mkt-zero", "Question zero risk")
    dead = make_position(-1, 0.40, "tok-dead", "mkt-dead", "Question dead risk")
    valid = make_position(100, 0.50, "tok-valid", "mkt-valid", "Question valid risk")
    set_api_routes({POSITIONS_URL: [zero, dead, valid]})

    client = FakePolymarketClient(books={"tok-valid": deep_book(0.50)})
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.analyze_portfolio_risk(client, limiter, FakeConfig()))

    assert "Number of Positions: 1" in text
    assert "Number of Markets: 1" in text
    assert "Total Exposure: $50.00" in text
    assert "Positions with Low Liquidity (<$1000): 0" in text
    assert "Overall Risk Score: 64/100" in text
    assert "Risk Level: HIGH" in text
    # Mechanical pin: only the size>0 position ever reaches the orderbook seam.
    assert client.orderbook_calls == ["tok-valid"]


async def test_analyze_portfolio_risk_liquidity_penalty_tiers():
    """Mandatory: the three missed penalty branches, each with inputs that
    EXCLUDE the prior branch (L-0109).

    Contract divergence (L-0020/L-0090): :1084 is the MARKET-concentration
    tier (`elif market_concentration > 30: risk_score += 10`, :1079-1084),
    not a liquidity tier; :1091/:1093 are the liquidity tiers. The ">50"
    liquidity tier (:1088) is covered by the sister suite (84/100 scenario).
    The contract's "1 position per case" sketch is unreachable for >30/>10
    (ratio is 0% or 100% with one position); scenarios below use 4 equal
    positions so the ratios are exactly 35%/50%/25%. The low-liquidity count
    only increments for SUCCESSFUL orderbook fetches with top-5 liquidity
    < 1000 (the append is inside the try, :1045-1054) -- thin books, not
    failed fetches.

    Phase MC   (:1084, market concentration in (30, 40]): exposures 35/25/20/20
               across 4 markets -> market_conc 35.0 -> +10; concentration 35.0
               -> +25 (:1073); liquidity 0; diversification 100 -> bonus 20
               -> score 25+10-20 = 15.
    Phase LIQ30 (:1091, liquidity pct in (30, 50]): 2 thin books of 4 equal
               positions -> 50.0% (NOT > 50) -> +15; concentration 25.0 -> +15
               (:1075); market 25.0 -> +0; score 15+0+15-20 = 10.
    Phase LIQ10 (:1093, liquidity pct in (10, 30]): 1 thin book of 4 -> 25.0%
               (NOT > 30) -> +10; score 15+0+10-20 = 5.
    """
    limiter = FakeRateLimiter()

    # Phase MC: market-concentration tier only (all books deep).
    mc_positions = [
        make_position(100, mid, f"tok-mc{i}", f"mkt-mc{i}", f"Will MC{i} pass?")
        for i, mid in enumerate([0.35, 0.25, 0.20, 0.20], start=1)
    ]
    set_api_routes({POSITIONS_URL: mc_positions})
    client = FakePolymarketClient(
        books={p["asset_id"]: deep_book(p["average_price"]) for p in mc_positions}
    )
    text = text_of(await portfolio.analyze_portfolio_risk(client, limiter, FakeConfig()))
    assert "Number of Positions: 4" in text
    assert "Number of Markets: 4" in text
    assert "Largest Market: $35.00 (35.0% of total)" in text
    assert "Positions with Low Liquidity (<$1000): 0" in text
    assert "Overall Risk Score: 15/100" in text
    assert "Risk Level: LOW" in text

    # Phase LIQ30: two thin books -> 2/4 = 50.0% fires the >30 tier (+15).
    liq_positions = [
        make_position(100, 0.25, f"tok-l{i}", f"mkt-l{i}", f"Will L{i} pass?")
        for i in range(1, 5)
    ]
    set_api_routes({POSITIONS_URL: liq_positions})
    books = {
        p["asset_id"]: (
            thin_book(p["average_price"]) if i <= 2 else deep_book(p["average_price"])
        )
        for i, p in enumerate(liq_positions, start=1)
    }
    client = FakePolymarketClient(books=books)
    text = text_of(await portfolio.analyze_portfolio_risk(client, limiter, FakeConfig()))
    assert "Positions with Low Liquidity (<$1000): 2" in text
    assert "have low liquidity" in text
    assert "Overall Risk Score: 10/100" in text

    # Phase LIQ10: one thin book -> 1/4 = 25.0% fires the >10 tier (+10).
    set_api_routes({POSITIONS_URL: liq_positions})
    books = {
        p["asset_id"]: (
            thin_book(p["average_price"]) if i == 1 else deep_book(p["average_price"])
        )
        for i, p in enumerate(liq_positions, start=1)
    }
    client = FakePolymarketClient(books=books)
    text = text_of(await portfolio.analyze_portfolio_risk(client, limiter, FakeConfig()))
    assert "Positions with Low Liquidity (<$1000): 1" in text
    assert "Overall Risk Score: 5/100" in text

    # Rate limiter: 1 DATA_API + N MARKET_DATA acquires per call (L-0123).
    assert len(limiter.categories) == 15
    assert len([c for c in limiter.categories if c.name == "DATA_API"]) == 3


async def test_analyze_portfolio_risk_low_concentration_falls_through_tiers():
    """Complementary: concentration_risk == 20 falls through the concentration
    elif chain (:1075 -> :1079 arc) and every penalty tier stays at 0 ->
    score 0/100, LOW, 'acceptable parameters' (5x20% equal positions)."""
    positions = [
        make_position(100, 0.20, f"tok-ft{i}", f"mkt-ft{i}", f"Will FT{i} pass?")
        for i in range(1, 6)
    ]
    set_api_routes({POSITIONS_URL: positions})
    client = FakePolymarketClient(
        books={p["asset_id"]: deep_book(p["average_price"]) for p in positions}
    )
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.analyze_portfolio_risk(client, limiter, FakeConfig()))

    assert "Number of Positions: 5" in text
    assert "Number of Markets: 5" in text
    assert "Largest Position: $20.00 (20.0% of total)" in text
    assert "Largest Market: $20.00 (20.0% of total)" in text
    assert "Positions with Low Liquidity (<$1000): 0" in text
    assert "Overall Risk Score: 0/100" in text
    assert "Diversification Score: 100/100" in text
    assert "Risk Level: LOW" in text
    assert "within acceptable parameters" in text


async def test_analyze_portfolio_risk_error_returns_error_text_content():
    """Mandatory: Data API failure -> exact error TextContent (:1192-1194)."""
    set_api_routes({POSITIONS_URL: FakeResponse([], error=httpx.HTTPError("boom"))})
    limiter = FakeRateLimiter()

    result = await portfolio.analyze_portfolio_risk(
        FakePolymarketClient(), limiter, FakeConfig()
    )

    assert result[0].type == "text"
    assert result[0].text == "Error analyzing portfolio risk: boom"


# ---------------------------------------------------------------------------
# suggest_portfolio_actions residuals: skip (:1249), fallback (:1270-1274),
# wide-spread (:1375-1383), no-actions (:1403-1408), error (:1427-1432)
# ---------------------------------------------------------------------------
async def test_suggest_actions_skips_nonpositive_sizes():
    """Mandatory: size<=0 positions are dropped BEFORE the orderbook seam and
    never generate suggestions (:1249).

    Contradictory pair: the valid position IS analyzed (value 100*0.65 = 65,
    pnl_pct +30% -> take-profit MEDIUM; concentration 100% -> REDUCE MEDIUM).
    """
    zero = make_position(0, 0.40, "tok-zero", "mkt-zero", "Question zero sugg")
    valid = make_position(100, 0.50, "tok-valid", "mkt-valid", "Question valid sugg")
    set_api_routes({POSITIONS_URL: [zero, valid]})

    client = FakePolymarketClient(books={"tok-valid": deep_book(0.65)})
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.suggest_portfolio_actions(client, limiter, FakeConfig()))

    assert "Analyzed 1 positions worth $65.00" in text
    assert "Take profit - position up +30.0%" in text
    assert "Reduce concentration" in text
    assert "Question zero sugg" not in text
    # Mechanical pin: the dead weight never reaches the orderbook seam.
    assert client.orderbook_calls == ["tok-valid"]
    assert [cat.name for cat in limiter.categories] == ["DATA_API", "MARKET_DATA"]


async def test_suggest_actions_orderbook_failure_falls_back_to_avg_price(
    monkeypatch, caplog
):
    """Mandatory: a failing orderbook degrades gracefully (:1270-1274) --
    mid_price = avg_price, spread = 0, total_liquidity = 0.

    Observable: the failed position is still analyzed (value 100*0.50 = 50 in
    the $115.00 total; mid = avg keeps its concentration at 50/115 = 43.5% > 30
    so a REDUCE fires for it), gets the low-liquidity CLOSE ($0.00 available),
    gets NO take-profit (pnl_pct 0.0) and NO wide-spread suggestion (0 < 0.10);
    the warning is pinned via caplog.
    """
    ok_pos = make_position(100, 0.50, "tok-ok", "mkt-ok", "Will Okpos win?")
    fail_pos = make_position(100, 0.50, "tok-fail", "mkt-fail", "Will Failpos win?")
    set_api_routes({POSITIONS_URL: [ok_pos, fail_pos]})

    client = FakePolymarketClient(books={"tok-ok": deep_book(0.65)}, fail_tokens={"tok-fail"})
    limiter = FakeRateLimiter()

    with caplog.at_level(logging.WARNING):
        text = text_of(
            await portfolio.suggest_portfolio_actions(client, limiter, FakeConfig())
        )

    # avg_price IS used for the failed position (mid=0 would give $65.00).
    assert "Analyzed 2 positions worth $115.00" in text
    blocks = suggestion_blocks(text)
    ok_tp = block_with(blocks, "Take profit - position up +30.0%")
    assert "Will Okpos" in ok_tp
    ok_reduce = block_with(blocks, "Reduce concentration - 56.5% of portfolio")
    assert "Will Okpos" in ok_reduce
    # mid = avg_price -> value 50.00 -> concentration 43.5% still exceeds the
    # balanced threshold (the fallback keeps the position actionable).
    fail_reduce = block_with(blocks, "Reduce concentration - 43.5% of portfolio")
    assert "Will Failpos" in fail_reduce
    # spread = 0 -> no wide-spread block for the failed position.
    assert "Wide spread" not in fail_reduce
    fail_close = block_with(
        blocks, "Exit low liquidity position ($0.00 available)"
    )
    assert "Will Failpos" in fail_close
    # ok-pos: TP + REDUCE; fail-pos: REDUCE + CLOSE-low-liquidity.
    assert "Generated 4 actionable suggestions" in text
    # The warning seam: exact logger, exact level, exact message.
    records = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(records) == 1
    assert records[0].levelname == "WARNING"
    assert (
        records[0].getMessage()
        == "Failed to fetch orderbook for tok-fail: synthetic orderbook failure for tok-fail"
    )
    # Monkeypatch participated in the isolation (unused-parameter hygiene).
    assert monkeypatch is not None


async def test_suggest_portfolio_actions_wide_spread_triggers_reduce():
    """Complementary (:1375-1383): spread > 0.10 fires the wide-spread REDUCE.

    4 equal positions with books bid 0.30 / ask 0.50: spread = 0.20 > 0.10 ->
    one REDUCE per position; pnl_pct 0.0 (mid = avg), concentration 25.0%
    (<= 30) and deep liquidity (top-5 sum = 0.30*1000*5 + 0.50*1000*5 = 4000)
    keep every other rule silent -> exactly 4 suggestions.
    """
    positions = [
        make_position(100, 0.40, f"tok-ws{i}", f"mkt-ws{i}", f"Will WS{i} pass?")
        for i in range(1, 5)
    ]
    set_api_routes({POSITIONS_URL: positions})
    client = FakePolymarketClient(
        books={p["asset_id"]: orderbook(0.30, 0.50, 1000) for p in positions}
    )
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.suggest_portfolio_actions(client, limiter, FakeConfig()))

    assert "Generated 4 actionable suggestions" in text
    assert text.count("Wide spread (20.0%) - poor exit conditions") == 4
    assert "Take profit" not in text
    assert "Cut losses" not in text
    assert "Exit low liquidity position" not in text
    assert "Reduce concentration" not in text


async def test_suggest_portfolio_actions_reports_no_actions_when_balanced():
    """Mandatory (:1403-1408): a balanced portfolio (pnl_pct 0.0 inside the
    take-profit/stop-loss band, concentration 25.0% <= 30, deep books
    (liquidity 0.30*700*10 = 2100 >= 1000), zero spread) generates no
    suggestions and prints the exact no-action literals."""
    positions = [
        make_position(100, 0.30, f"tok-b{i}", f"mkt-b{i}", f"Will B{i} pass?")
        for i in range(1, 5)
    ]
    set_api_routes({POSITIONS_URL: positions})
    client = FakePolymarketClient(
        books={p["asset_id"]: deep_book(p["average_price"]) for p in positions}
    )
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.suggest_portfolio_actions(client, limiter, FakeConfig()))

    assert "Generated 0 actionable suggestions" in text
    assert "No optimization actions recommended at this time." in text
    assert "Portfolio appears well-balanced for your goals." in text
    assert suggestion_blocks(text) == []


async def test_suggest_portfolio_actions_no_actions_pair_contradictory():
    """Complementary contradictory pair for the no-actions path (L-0109):
    identical positions/books except avg_price 0.23 -> pnl_pct +30.4% crosses
    the balanced take-profit threshold (25) -> the no-action literals are
    GONE and exactly one take-profit suggestion per position appears."""
    positions = [
        make_position(100, 0.23, f"tok-b{i}", f"mkt-b{i}", f"Will B{i} pass?")
        for i in range(1, 5)
    ]
    set_api_routes({POSITIONS_URL: positions})
    client = FakePolymarketClient(books={p["asset_id"]: deep_book(0.30) for p in positions})
    limiter = FakeRateLimiter()

    text = text_of(await portfolio.suggest_portfolio_actions(client, limiter, FakeConfig()))

    assert "No optimization actions recommended at this time." not in text
    assert "Portfolio appears well-balanced for your goals." not in text
    assert "Generated 4 actionable suggestions" in text
    assert text.count("Take profit - position up +30.4%") == 4


async def test_suggest_portfolio_actions_error_returns_error_text_content():
    """Mandatory: Data API failure -> exact error TextContent (:1427-1432)."""
    set_api_routes({POSITIONS_URL: FakeResponse([], error=httpx.HTTPError("boom"))})
    limiter = FakeRateLimiter()

    result = await portfolio.suggest_portfolio_actions(
        FakePolymarketClient(), limiter, FakeConfig()
    )

    assert result[0].type == "text"
    assert result[0].text == "Error generating portfolio suggestions: boom"
