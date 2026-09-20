"""
Offline regression suite for the history/risk/suggestions slice of
polymarket_mcp.tools.portfolio and for polymarket_mcp.tools.portfolio_integration.

Why this suite exists
---------------------
tools/portfolio.py had only tests/test_portfolio_tools.py, which is
credential-gated (conftest.py:16-19 -> skipped without a funded wallet) and
therefore outside the release gate. The analytical half of this module --
trade history, on-chain activity, the risk-score matrix and the goal-based
action suggestions -- is what the agent relays to the user about real money;
a regression there would not trip any alarm. This suite pins the observed
semantics offline: the httpx.AsyncClient seam is replaced by a synthetic
client routing by URL suffix and RECORDING params (monkeypatch restores the
original after each test), and the polymarket_client orderbook seam is a
fake that can raise per token. Zero network, zero sleeps (L-0014), payload
shapes derived from the PARSING code (L-0020), semantic assertions (L-0002).

Pre-requisites
--------------
- Runs from the repo root with PYTHONPATH=src (release-gate environment).
- pytest-asyncio auto mode is configured in pyproject.toml (asyncio_mode).
- No integration/slow/real_api markers: this file runs in the release gate.
- Only this file is touched; src/** is read, never modified.

Observed behaviors pinned per L-0025 (source of truth = code, not prose)
-----------------------------------------------------------------------
1. suggestions.sort second key is CONSTANT (portfolio.py:1387): it uses
   position_data[0]['pnl_pct'] for EVERY suggestion, so within a priority
   level the order is Python's stable insertion order, not value-based.
   The suite pins only the HIGH->MEDIUM->LOW priority ordering (L-0002).
2. analyze_portfolio_risk except-branch (portfolio.py:1040-1043): a failed
   orderbook fetch sets total_liquidity = 0 but does NOT add the position to
   low_liquidity_positions -- pinned "Positions with Low Liquidity (<$1000):
   0" even though every position has zero liquidity.
3. get_trade_history caps the API query at min(limit, 500) (portfolio.py:780)
   but slices display/volume over trades[:limit] with the ORIGINAL limit
   (portfolio.py:824); payloads here are small so both limits coincide.
4. Activity tx hash rendering (portfolio.py:947): hash[:10] + "..." + last 8
   chars when len(hash) > 18, otherwise hash[:10] + "..." + FULL hash -- so
   the short hash "0xabc" renders "0xabc...0xabc".
5. datetime.fromtimestamp uses LOCAL time (portfolio.py:826/936): the suite
   never asserts exact dates/times, only structural shape (contract premise).
"""

import re
from datetime import datetime

import httpx
import mcp.types as types
import pytest

from polymarket_mcp.tools import portfolio
from polymarket_mcp.tools.portfolio import (
    analyze_portfolio_risk,
    get_activity_log,
    get_trade_history,
    suggest_portfolio_actions,
)
from polymarket_mcp.tools.portfolio_integration import (
    call_portfolio_tool,
    get_portfolio_tool_definitions,
)

ADDR = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
ADDR_LOWER = "0xabcdef0123456789abcdef0123456789abcdef01"


# ---------------------------------------------------------------------------
# Synthetic seams (fakes defined IN this file; monkeypatch restores httpx)
# ---------------------------------------------------------------------------
class FakeResponse:
    """Minimal stand-in for httpx.Response as consumed by portfolio.py."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def make_fake_async_client(routes, calls):
    """Build an httpx.AsyncClient replacement.

    routes maps a URL SUFFIX (".../trades", ".../activity", ".../positions")
    to the payload returned by .json(). Every GET is recorded in `calls` as
    (url, params, timeout) so tests can pin the query-param building.
    """

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, params=None, timeout=None):
            calls.append((url, dict(params or {}), timeout))
            for suffix, payload in routes.items():
                if url.endswith(suffix):
                    return FakeResponse(payload)
            raise AssertionError(f"no synthetic route for {url!r}")

    return _FakeAsyncClient


class FakeRateLimiter:
    """Inert stand-in for RateLimiter: records acquire() categories."""

    def __init__(self):
        self.calls = []

    async def acquire(self, category):
        self.calls.append(category)


class FakeConfig:
    """Stand-in for PolymarketConfig as consumed by portfolio.py."""

    POLYGON_ADDRESS = ADDR


class FakePolymarketClient:
    """Stand-in for PolymarketClient: only get_orderbook is consumed here.

    books maps token_id -> {"bids": [...], "asks": [...]}; tokens listed in
    fail_tokens raise RuntimeError to exercise the except-branch of the
    risk/suggestion functions.
    """

    def __init__(self, books=None, fail_tokens=()):
        self.books = books or {}
        self.fail_tokens = set(fail_tokens)
        self.orderbook_calls = []

    async def get_orderbook(self, token_id):
        self.orderbook_calls.append(token_id)
        if token_id in self.fail_tokens:
            raise RuntimeError(f"synthetic orderbook failure for {token_id}")
        if token_id not in self.books:
            raise AssertionError(f"no synthetic orderbook for token={token_id!r}")
        return self.books[token_id]


def fake_deps(monkeypatch, routes):
    """Install the httpx seam and return (calls, limiter, config).

    The orderbook seam is returned separately by the caller because each test
    configures its own books/failures.
    """
    calls = []
    monkeypatch.setattr(httpx, "AsyncClient", make_fake_async_client(routes, calls))
    return calls, FakeRateLimiter(), FakeConfig()


# ---------------------------------------------------------------------------
# Payload helpers (shapes follow the parsing code, not API docs -- L-0020)
# ---------------------------------------------------------------------------
def trade_payload(trade_id, side, price, size, timestamp):
    return {
        "conditionId": "0xmarket123",  # real /trades key (wire truth 2026-09-20)
        "market_question": "Will the DAO proposal pass?",
        "outcome": "YES",
        "side": side,
        "price": price,
        "size": size,
        "timestamp": timestamp,
        "fee": 0.0,
        "id": trade_id,
    }


def activity_payload(event_type, tx_hash, amount=1.0, value=2.0, timestamp=1767225600):
    return {
        "timestamp": timestamp,
        "type": event_type,
        "market_question": "Will the DAO proposal pass?",
        "amount": amount,
        "value": value,
        "transaction_hash": tx_hash,
    }


def position_payload(asset_id, market_id, question, outcome, size, avg_price):
    return {
        "size": size,
        "average_price": avg_price,
        "asset_id": asset_id,
        "market": market_id,
        "market_question": question,
        "outcome": outcome,
    }


def deep_book(bid_price, ask_price, levels=5, level_size=700):
    """Book whose top-5 liquidity is >= 1000 by construction:
    levels * bid_price * level_size + levels * ask_price * level_size."""
    return {
        "bids": [{"price": bid_price, "size": level_size} for _ in range(levels)],
        "asks": [{"price": ask_price, "size": level_size} for _ in range(levels)],
    }


# ---------------------------------------------------------------------------
# Output-text helpers (semantic assertions over the TextContent payload)
# ---------------------------------------------------------------------------
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
    matches = [block for block in blocks if needle in block]
    assert len(matches) == 1, f"expected exactly one block containing {needle!r}"
    return matches[0]


def priority_sequence(text):
    """Ordered list of 'Priority: X' values as they appear in the output."""
    return [
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.strip().startswith("Priority:")
    ]


PRIORITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


# ---------------------------------------------------------------------------
# get_trade_history (portfolio.py:748-864)
# ---------------------------------------------------------------------------
async def test_trade_history_builds_query_params_and_filters_side(monkeypatch):
    start_date = "2026-01-01T00:00:00Z"
    end_date = "2026-02-01T00:00:00Z"
    routes = {
        "/trades": [
            trade_payload("t-buy-1", "BUY", 0.5, 10, 1767225600),
            trade_payload("t-sell-1", "SELL", 0.75, 20, 1767225700),
            trade_payload("t-buy-2", "BUY", 0.25, 4, 1767225800),
        ]
    }
    calls, limiter, config = fake_deps(monkeypatch, routes)

    result = await get_trade_history(
        FakePolymarketClient(),
        limiter,
        config,
        market_id="0xmarket123",
        start_date=start_date,
        end_date=end_date,
        limit=700,
        side="BUY",
    )

    # One DATA_API fetch before the HTTP call (portfolio.py:795).
    assert len(limiter.calls) == 1
    assert len(calls) == 1
    url, params, timeout = calls[0]
    assert url == "https://data-api.polymarket.com/trades"
    assert timeout == 10.0
    # start_time/end_time recomputed with the SAME expression as the source
    # (portfolio.py:787/791) so the assert is timezone-independent.
    expected_start = int(datetime.fromisoformat(start_date.replace("Z", "+00:00")).timestamp())
    expected_end = int(datetime.fromisoformat(end_date.replace("Z", "+00:00")).timestamp())
    assert params == {
        "user": ADDR_LOWER,
        "limit": 500,  # min(700, 500) cap (portfolio.py:780)
        "market": "0xmarket123",
        "start_time": expected_start,
        "end_time": expected_end,
    }

    text = result[0].text
    assert isinstance(result[0], types.TextContent)
    # SELL filtered out BEFORE the header count (portfolio.py:806-807).
    assert "Trade History (2 trades)" in text
    assert "Trade ID: t-buy-1" in text
    assert "Trade ID: t-buy-2" in text
    assert "t-sell-1" not in text
    # Total volume sums price*size of the SURVIVING BUY trades only.
    assert "Total Volume: $6.00" in text
    # Per-trade formatting (portfolio.py:838-843).
    assert "Price: $0.5000 | Size: 10.00 shares" in text
    assert "Value: $5.00 | Fee: $0.0000" in text
    # Date line is local time; pin structure, never the clock value.
    assert re.search(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] BUY$", text, re.MULTILINE)


async def test_trade_history_empty_message(monkeypatch):
    routes = {"/trades": []}
    calls, limiter, config = fake_deps(monkeypatch, routes)

    result = await get_trade_history(FakePolymarketClient(), limiter, config)

    # Empty check happens AFTER the fetch (portfolio.py:809-813).
    assert len(calls) == 1
    assert [c.text for c in result] == ["No trades found matching criteria."]


# ---------------------------------------------------------------------------
# get_activity_log (portfolio.py:866-964)
# ---------------------------------------------------------------------------
async def test_activity_log_type_filter_and_tx_hash_truncation(monkeypatch):
    long_hash = "0x" + "0123456789abcdef" * 4  # 66 chars: first 10 + ... + last 8
    assert len(long_hash) == 66
    routes = {
        "/activity": [
            activity_payload("redeem", long_hash, amount=5.5, value=12.0),
            activity_payload("split", "0xabc"),
        ]
    }
    calls, limiter, config = fake_deps(monkeypatch, routes)

    result = await get_activity_log(
        FakePolymarketClient(), limiter, config, activity_type="redeems"
    )

    url, params, _timeout = calls[0]
    assert url == "https://data-api.polymarket.com/activity"
    # Type filter is sent only when activity_type != 'all' (portfolio.py:899-900).
    assert params["type"] == "redeems"
    assert params["user"] == ADDR_LOWER
    assert params["limit"] == 100

    text = result[0].text
    assert "Activity Log (2 events)" in text
    # Event type is uppercased (portfolio.py:937).
    assert "REDEEM" in text
    assert "SPLIT" in text
    # Truncation: len > 18 -> first 10 + "..." + last 8 (portfolio.py:947).
    assert f"Tx Hash: {long_hash[:10]}...{long_hash[-8:]}" in text
    # Short hash: len <= 18 -> first 10 + "..." + FULL hash.
    assert "Tx Hash: 0xabc...0xabc" in text
    assert "Amount: 5.50 | Value: $12.00" in text

    # 'all' must NOT send a type filter.
    calls.clear()
    result_all = await get_activity_log(
        FakePolymarketClient(), limiter, config, activity_type="all"
    )
    assert len(calls) == 1
    assert "type" not in calls[0][1]
    assert "Activity Log (2 events)" in result_all[0].text


async def test_activity_log_empty_message(monkeypatch):
    routes = {"/activity": []}
    calls, limiter, config = fake_deps(monkeypatch, routes)

    result = await get_activity_log(FakePolymarketClient(), limiter, config)

    assert len(calls) == 1
    assert [c.text for c in result] == ["No activity found matching criteria."]


# ---------------------------------------------------------------------------
# analyze_portfolio_risk (portfolio.py:966-1198)
# ---------------------------------------------------------------------------
async def test_analyze_risk_concentrated_illiquid_portfolio_is_high(monkeypatch):
    position = position_payload(
        "tok-a", "mkt-1", "Will Alpha win the election?", "YES", size=10, avg_price=0.5
    )
    # Shallow book: top-5 liquidity = 5*0.5*10 + 5*0.5*10 = 50 < 1000.
    book = {"bids": [{"price": 0.5, "size": 10}], "asks": [{"price": 0.5, "size": 10}]}
    routes = {"/positions": [position]}
    calls, limiter, config = fake_deps(monkeypatch, routes)
    client = FakePolymarketClient(books={"tok-a": book})

    result = await analyze_portfolio_risk(client, limiter, config)
    text = result[0].text

    # Risk matrix recomputed from portfolio.py:1071-1096 for this payload:
    # concentration 100% -> +40; market concentration 100% -> +30; liquidity
    # 1/1 = 100% -> +20; subtotal 90; diversification min(100, 10+20) = 30;
    # 90 - 30//5 = 84 -> HIGH.
    assert len(calls) == 1
    assert "Total Exposure: $5.00" in text
    assert "Number of Positions: 1" in text
    assert "Number of Markets: 1" in text
    assert "Largest Position: $5.00 (100.0% of total)" in text
    assert "Largest Market: $5.00 (100.0% of total)" in text
    assert "Positions with Low Liquidity (<$1000): 1" in text
    assert "Overall Risk Score: 84/100" in text
    assert "Diversification Score: 30/100" in text
    assert "Risk Level: HIGH" in text
    for rec in (
        "High position concentration",
        "High market concentration",
        "have low liquidity",
        "concentrated in few markets",
    ):
        assert rec in text


async def test_analyze_risk_diversified_liquid_portfolio_is_low(monkeypatch):
    positions = [
        position_payload(
            f"tok-{i}", f"mkt-{i}", f"Will Question {i} pass?", "YES",
            size=100, avg_price=0.5,
        )
        for i in range(1, 5)
    ]
    # Deep books: top-5 liquidity = 500 + 500 = 1000, NOT < 1000.
    books = {f"tok-{i}": deep_book(0.5, 0.5, levels=5, level_size=200) for i in range(1, 5)}
    routes = {"/positions": positions}
    calls, limiter, config = fake_deps(monkeypatch, routes)
    client = FakePolymarketClient(books=books)

    result = await analyze_portfolio_risk(client, limiter, config)
    text = result[0].text

    # concentration 25% -> +15; market concentration 25% -> +0; liquidity 0
    # positions -> +0; subtotal 15; diversification min(100, 40+80) = 100;
    # max(0, 15 - 20) = 0 -> LOW. Single "acceptable parameters" recommendation.
    assert len(calls) == 1
    assert "Total Exposure: $200.00" in text
    assert "Number of Positions: 4" in text
    assert "Number of Markets: 4" in text
    assert "Positions with Low Liquidity (<$1000): 0" in text
    assert "Overall Risk Score: 0/100" in text
    assert "Diversification Score: 100/100" in text
    assert "Risk Level: LOW" in text
    assert "within acceptable parameters" in text
    for rec in (
        "High position concentration",
        "High market concentration",
        "have low liquidity",
        "concentrated in few markets",
    ):
        assert rec not in text


async def test_analyze_risk_orderbook_failure_is_not_counted_as_low_liquidity(monkeypatch):
    positions = [
        position_payload(
            "tok-a", "mkt-1", "Will Alpha win the election?", "YES", size=100, avg_price=0.5
        ),
        position_payload(
            "tok-b", "mkt-2", "Will Beta win the race?", "NO", size=100, avg_price=0.5
        ),
    ]
    routes = {"/positions": positions}
    calls, limiter, config = fake_deps(monkeypatch, routes)
    client = FakePolymarketClient(fail_tokens={"tok-a", "tok-b"})

    result = await analyze_portfolio_risk(client, limiter, config)
    text = result[0].text

    # Except-branch observables (portfolio.py:1040-1043): mid falls back to
    # average_price and the position is NOT counted as low liquidity even
    # though total_liquidity is 0 (<$1000). Values must NOT be zeroed out.
    assert client.orderbook_calls == ["tok-a", "tok-b"]
    assert "Error" not in text
    assert "Total Exposure: $100.00" in text
    assert "Largest Position: $50.00 (50.0% of total)" in text
    assert "Largest Market: $50.00 (50.0% of total)" in text
    assert "Number of Positions: 2" in text
    assert "Number of Markets: 2" in text
    assert "Positions with Low Liquidity (<$1000): 0" in text
    # concentration 50% -> +25; market concentration 50% > 40 -> +20;
    # liquidity 0 -> +0; diversification min(100, 20+40) = 60;
    # 45 - 60//5 = 33 -> MODERATE.
    assert "Overall Risk Score: 33/100" in text
    assert "Risk Level: MODERATE" in text
    assert "have low liquidity" not in text


async def test_analyze_risk_empty_message(monkeypatch):
    routes = {"/positions": []}
    calls, limiter, config = fake_deps(monkeypatch, routes)

    result = await analyze_portfolio_risk(FakePolymarketClient(), limiter, config)

    assert len(calls) == 1
    assert [c.text for c in result] == ["No positions to analyze."]


# ---------------------------------------------------------------------------
# suggest_portfolio_actions (portfolio.py:1200-1432)
# ---------------------------------------------------------------------------
# Shared scenario: A is up +30% (avg 0.50, mid 0.65), B is down -25%
# (avg 0.40, mid ~0.30); deep books (>= 2000) and spreads < 0.10 so that
# only the take-profit / stop-loss / concentration rules can fire.
THRESHOLD_POSITIONS = [
    position_payload(
        "tok-a", "mkt-1", "Will Alpha win the election?", "YES", size=100, avg_price=0.5
    ),
    position_payload(
        "tok-b", "mkt-2", "Will Beta win the race?", "NO", size=100, avg_price=0.4
    ),
]
THRESHOLD_BOOKS = {
    "tok-a": deep_book(0.64, 0.66),  # mid 0.65; liquidity 4550
    "tok-b": deep_book(0.29, 0.31, level_size=1500),  # mid ~0.30; liquidity 4500
}


async def test_suggest_actions_take_profit_and_stop_loss_thresholds_by_goal(monkeypatch):
    routes = {"/positions": THRESHOLD_POSITIONS}
    calls, limiter, config = fake_deps(monkeypatch, routes)
    client = FakePolymarketClient(books=THRESHOLD_BOOKS)

    # balanced thresholds: tp 25 / sl -20 -> both fire (30 > 25, -25 < -20)
    # and both are MEDIUM (HIGH needs pnl_pct > tp*1.5 = 37.5 / < sl*1.5 = -30).
    result = await suggest_portfolio_actions(client, limiter, config, goal="balanced", max_actions=20)
    text_balanced = result[0].text
    assert "Portfolio Optimization Suggestions (BALANCED goal)" in text_balanced
    assert "Analyzed 2 positions worth $95.00" in text_balanced
    blocks = suggestion_blocks(text_balanced)
    tp = block_with(blocks, "Take profit - position up +30.0%")
    sl = block_with(blocks, "Cut losses - position down -25.0%")
    assert "Priority: MEDIUM" in tp
    assert "Priority: MEDIUM" in sl

    # conservative thresholds: tp 15 / sl -10 -> both fire and both are HIGH
    # (30 > 22.5 and -25 < -15). Deep books stay above min_liquidity 2000.
    result = await suggest_portfolio_actions(
        client, limiter, config, goal="conservative", max_actions=20
    )
    blocks = suggestion_blocks(result[0].text)
    tp = block_with(blocks, "Take profit - position up +30.0%")
    sl = block_with(blocks, "Cut losses - position down -25.0%")
    assert "Priority: HIGH" in tp
    assert "Priority: HIGH" in sl

    # aggressive thresholds: tp 40 / sl -30 -> +30/-25 sit inside the
    # no-action band; those suggestions must be absent entirely.
    result = await suggest_portfolio_actions(
        client, limiter, config, goal="aggressive", max_actions=20
    )
    text_aggressive = result[0].text
    assert "Take profit" not in text_aggressive
    assert "Cut losses" not in text_aggressive
    # Concentration rule still fires for tok-a (68.4% > conc_max 40) but not
    # for tok-b (31.6% < 40) -> exactly one suggestion generated.
    assert "Reduce concentration" in text_aggressive
    assert "Generated 1 actionable suggestions" in text_aggressive


async def test_suggest_actions_respects_max_actions_and_priority_order(monkeypatch):
    positions = THRESHOLD_POSITIONS + [
        position_payload(
            "tok-c", "mkt-3", "Will Gamma pass the bill?", "YES", size=100, avg_price=0.5
        ),
    ]
    # tok-c: shallow book (top-5 liquidity 10 < 2000) -> LOW liquidity alert.
    books = dict(THRESHOLD_BOOKS)
    books["tok-c"] = {"bids": [{"price": 0.5, "size": 10}], "asks": [{"price": 0.5, "size": 10}]}
    routes = {"/positions": positions}
    calls, limiter, config = fake_deps(monkeypatch, routes)
    client = FakePolymarketClient(books=books)

    # conservative generates: TP-A HIGH, SL-B HIGH, 3x concentration MEDIUM
    # (values 65/50/30 of 145 -> 44.8/34.5/20.7%, all > conc_max 20) and
    # low-liquidity-C LOW -> 6 suggestions, sorted by priority only.
    result = await suggest_portfolio_actions(client, limiter, config, goal="conservative", max_actions=20)
    text_full = result[0].text
    assert "Analyzed 3 positions worth $145.00" in text_full
    assert "Generated 6 actionable suggestions" in text_full
    sequence = priority_sequence(text_full)
    assert sequence.count("HIGH") == 2
    assert sequence.count("MEDIUM") == 3
    assert sequence.count("LOW") == 1
    ranks = [PRIORITY_RANK[p] for p in sequence]
    assert ranks == sorted(ranks)  # non-decreasing HIGH -> MEDIUM -> LOW

    # max_actions=2 keeps only the first 2 after the priority sort: the HIGHs.
    result = await suggest_portfolio_actions(
        client, limiter, config, goal="conservative", max_actions=2
    )
    text_top2 = result[0].text
    assert "Generated 2 actionable suggestions" in text_top2
    blocks = suggestion_blocks(text_top2)
    assert len(blocks) == 2
    assert all("Priority: HIGH" in block for block in blocks)
    assert "Priority: MEDIUM" not in text_top2
    assert "Priority: LOW" not in text_top2


async def test_suggest_actions_empty_message(monkeypatch):
    routes = {"/positions": []}
    calls, limiter, config = fake_deps(monkeypatch, routes)

    result = await suggest_portfolio_actions(FakePolymarketClient(), limiter, config)

    assert len(calls) == 1
    assert [c.text for c in result] == ["No positions to optimize."]


# ---------------------------------------------------------------------------
# portfolio_integration.py (definitions + dispatch)
# ---------------------------------------------------------------------------
def test_portfolio_tool_definitions_match_registry():
    tools = get_portfolio_tool_definitions()
    registry = portfolio.PORTFOLIO_TOOLS

    assert len(tools) == len(registry) == 8
    # Same names, same order.
    assert [tool.name for tool in tools] == [tool_def["name"] for tool_def in registry]
    for tool, tool_def in zip(tools, registry, strict=True):
        assert isinstance(tool, types.Tool)
        assert tool.description == tool_def["description"]
        assert tool.inputSchema == tool_def["inputSchema"]
        assert isinstance(tool.inputSchema, dict)
        assert tool.inputSchema.get("type") == "object"


async def test_call_portfolio_tool_dispatches_and_rejects_unknown(monkeypatch):
    routes = {"/activity": []}
    calls, limiter, config = fake_deps(monkeypatch, routes)

    result = await call_portfolio_tool(
        "get_activity_log", {"activity_type": "trades"}, FakePolymarketClient(), limiter, config
    )

    # Dispatch routed to the REAL get_activity_log handler with the injected
    # dependencies and forwarded the tool arguments.
    assert isinstance(result, list)
    assert isinstance(result[0], types.TextContent)
    assert result[0].text == "No activity found matching criteria."
    url, params, _timeout = calls[0]
    assert url.endswith("/activity")
    assert params["type"] == "trades"
    assert params["user"] == ADDR_LOWER

    with pytest.raises(ValueError, match="Unknown portfolio tool"):
        await call_portfolio_tool(
            "not_a_real_portfolio_tool", {}, FakePolymarketClient(), limiter, config
        )
