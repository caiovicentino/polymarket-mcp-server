"""
Offline regression suite for polymarket_mcp.tools.market_analysis.

Why this suite exists
---------------------
Before this file, the only coverage for tools/market_analysis.py was
tests/test_market_tools.py, which is marked `integration` (real Polymarket
API) and therefore excluded from the release gate
(`-m "not integration and not slow and not real_api"`). A regression in the
spread math or in the recommendation matrix (AVOID/BUY/HOLD) would not trip
any alarm. This suite pins that semantics offline: the two module-level fetch
helpers (`_fetch_gamma_api` / `_fetch_clob_api`) are replaced by synthetic
stubs whose payload shapes are derived from the PARSING code itself
(lesson L-0020), not from API documentation. Zero network, zero sleeps
(L-0014), semantic assertions (L-0002), observed behavior pinned over prose
(L-0020/L-0025).

Pre-requisites
--------------
- Runs from the repo root with PYTHONPATH=src (release-gate environment).
- pytest-asyncio auto mode is configured in pyproject.toml (autoio_mode).
- No integration/slow/real_api markers: this file runs in the release gate.
- Only this file is touched; src/** is read, never modified.

Observed divergences recorded per L-0025
----------------------------------------
1. The original task spec suggested liquidity=60000 + volume_24h=20000 +
   tight spread should yield BUY/65; the code checks the healthy-market
   branch (liquidity > 50000 AND volume > 10000 -> HOLD/70) BEFORE the
   tight-spread BUY branch (market_analysis.py:497-504), so those inputs
   yield HOLD/70. test_analyze_liquid_market_recommends_buy therefore uses
   inputs that actually exercise the BUY branch (high liquidity, volume
   below 10000), and test_analyze_healthy_market_holds_despite_tight_spread
   pins the branch order with the spec's original inputs.
2. price_trend_24h is always "stable" in the current code
   (market_analysis.py:511 - historical data is not implemented); pinned as
   current behavior, not aspiration.
"""
import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from polymarket_mcp.tools import market_analysis
from polymarket_mcp.tools.market_analysis import (
    MarketOpportunity,
    OrderBook,
    OrderBookEntry,
    PriceData,
    VolumeData,
)


class FakeGamma:
    """Synthetic stand-in for market_analysis._fetch_gamma_api.

    Payload shapes follow the parsing code (get_market_details /
    get_market_volume / get_liquidity), not API docs (L-0020).
    """

    def __init__(self, markets=None):
        # markets: {identifier: payload}; a list payload exercises the
        # list-collapse branch of get_market_details.
        self.markets = markets or {}
        self.calls = []

    async def __call__(self, endpoint, params=None):
        params = dict(params or {})
        self.calls.append((endpoint, params))
        if endpoint == "/markets":
            condition_id = params.get("condition_id")
            if condition_id not in self.markets:
                raise AssertionError(f"no synthetic gamma payload for {condition_id!r}")
            return [self.markets[condition_id]]
        if endpoint.startswith("/markets/"):
            market_id = endpoint[len("/markets/"):]
            if market_id not in self.markets:
                raise AssertionError(f"no synthetic gamma payload for {market_id!r}")
            return self.markets[market_id]
        raise AssertionError(f"unexpected gamma endpoint: {endpoint!r}")


class FakeClob:
    """Synthetic stand-in for market_analysis._fetch_clob_api."""

    def __init__(self, prices=None, books=None, fail_sides=()):
        # prices: {token_id: {"BUY": "0.60", "SELL": "0.55"}}. String payloads:
        # the parsing code coerces them with float() (market_analysis.py:177,181).
        self.prices = prices or {}
        self.books = books or {}
        self.fail_sides = set(fail_sides)
        self.calls = []

    async def __call__(self, endpoint, params=None):
        params = dict(params or {})
        self.calls.append((endpoint, params))
        if endpoint == "/price":
            token_id = params.get("token_id")
            side = params.get("side")
            if side in self.fail_sides:
                raise ValueError(f"book has no {str(side).lower()}-side orders")
            side_prices = self.prices.get(token_id, {})
            if side not in side_prices:
                raise AssertionError(f"no synthetic price for token={token_id!r} side={side!r}")
            return {"price": side_prices[side]}
        if endpoint == "/book":
            token_id = params.get("token_id")
            if token_id not in self.books:
                raise AssertionError(f"no synthetic book for token={token_id!r}")
            return self.books[token_id]
        raise AssertionError(f"unexpected clob endpoint: {endpoint!r}")


def patch_fetches(monkeypatch, gamma=None, clob=None):
    """Install the fetch-helper stubs at module level (the seams this module
    exposes). monkeypatch restores the originals after each test."""
    if gamma is not None:
        monkeypatch.setattr(market_analysis, "_fetch_gamma_api", gamma)
    if clob is not None:
        monkeypatch.setattr(market_analysis, "_fetch_clob_api", clob)


def market_payload(
    question="Will the proposal pass before December?",
    with_tokens=True,
    liquidity="60000",
    volume24hr="20000",
    **overrides,
):
    payload = {
        "question": question,
        "volume24hr": volume24hr,
        "volume7d": "90000",
        "volume30d": "400000",
        "volumeNum": "1200000",
        "liquidity": liquidity,
        "endDate": "2026-12-31T00:00:00Z",
        "active": True,
        "tags": ["politics"],
    }
    if with_tokens:
        payload["tokens"] = [
            {"token_id": "tok-yes", "outcome": "YES"},
            {"token_id": "tok-no", "outcome": "NO"},
        ]
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Data models (market_analysis.py:35-84)
# ---------------------------------------------------------------------------
def test_models_validate_required_fields():
    # OrderBookEntry requires both price and size (no defaults).
    with pytest.raises(ValidationError):
        OrderBookEntry(price=0.55)  # missing size
    with pytest.raises(ValidationError):
        OrderBookEntry(size=100.0)  # missing price

    # MarketOpportunity enforces each required field one at a time.
    required = [
        "market_id",
        "market_question",
        "risk_assessment",
        "recommendation",
        "confidence_score",
        "reasoning",
    ]
    base = {
        "market_id": "m1",
        "market_question": "Will it pass?",
        "risk_assessment": "low",
        "recommendation": "HOLD",
        "confidence_score": 50,
        "reasoning": "conditions acceptable",
    }
    for field in required:
        partial = {key: value for key, value in base.items() if key != field}
        with pytest.raises(ValidationError):
            MarketOpportunity(**partial)

    # Optional models construct with defaults.
    price = PriceData(token_id="t1")
    assert price.token_id == "t1"
    assert price.bid is None
    assert price.ask is None
    assert price.mid is None
    assert price.last is None
    assert isinstance(price.timestamp, datetime)

    book = OrderBook(token_id="t1", bids=[], asks=[])
    assert book.bids == []
    assert book.asks == []
    assert isinstance(book.timestamp, datetime)

    volume = VolumeData(market_id="m1")
    assert volume.volume_24h is None
    assert volume.volume_7d is None
    assert volume.volume_30d is None
    assert volume.volume_all_time is None


# ---------------------------------------------------------------------------
# Price parsing (market_analysis.py:158-193)
# ---------------------------------------------------------------------------
async def test_get_current_price_from_book(monkeypatch):
    clob = FakeClob(prices={"tok": {"BUY": "0.60", "SELL": "0.55"}})
    patch_fetches(monkeypatch, clob=clob)

    both = await market_analysis.get_current_price("tok", "BOTH")
    assert both.token_id == "tok"
    assert both.ask == pytest.approx(0.60)
    assert both.bid == pytest.approx(0.55)
    assert both.mid == pytest.approx((0.55 + 0.60) / 2)
    # The payload is a string; the parse code coerces with float().
    assert isinstance(both.ask, float)

    buy_only = await market_analysis.get_current_price("tok", "BUY")
    assert buy_only.ask == pytest.approx(0.60)
    assert buy_only.bid is None
    assert buy_only.mid is None  # mid is only computed when both sides exist

    sell_only = await market_analysis.get_current_price("tok", "SELL")
    assert sell_only.bid == pytest.approx(0.55)
    assert sell_only.ask is None
    assert sell_only.mid is None

    # An unrecognized side never reaches the wire and populates nothing.
    no_side = await market_analysis.get_current_price("tok", "MIDDLE")
    assert no_side.bid is None
    assert no_side.ask is None
    assert no_side.mid is None
    price_sides = [params.get("side") for endpoint, params in clob.calls if endpoint == "/price"]
    assert set(price_sides) == {"BUY", "SELL"}


# ---------------------------------------------------------------------------
# Spread math (market_analysis.py:239-273)
# ---------------------------------------------------------------------------
async def test_get_spread_from_book(monkeypatch):
    clob = FakeClob(prices={"tok": {"BUY": "0.60", "SELL": "0.55"}})
    patch_fetches(monkeypatch, clob=clob)

    spread = await market_analysis.get_spread("tok")
    assert spread["token_id"] == "tok"
    assert spread["bid"] == pytest.approx(0.55)
    assert spread["ask"] == pytest.approx(0.60)
    assert spread["mid"] == pytest.approx(0.575)
    assert spread["spread_value"] == pytest.approx(0.05)
    expected_pct = 0.05 / 0.575 * 100  # 8.695652...
    assert abs(spread["spread_percentage"] - expected_pct) < 1e-9

    # Without a buy side there is no ask to quote: the failure propagates as a
    # ValueError instead of a silently partial result.
    broken = FakeClob(prices={"tok2": {"BUY": "0.60", "SELL": "0.55"}}, fail_sides={"BUY"})
    patch_fetches(monkeypatch, clob=broken)
    with pytest.raises(ValueError, match="no buy-side orders"):
        await market_analysis.get_spread("tok2")


# ---------------------------------------------------------------------------
# Volume parsing (market_analysis.py:276-311)
# ---------------------------------------------------------------------------
async def test_get_market_volume_from_gamma(monkeypatch):
    payload = market_payload(
        with_tokens=False,
        liquidity="0",
        volume24hr="15000.5",
        volume7d="90000",
        volume30d="400000",
        volumeNum="1200000",
    )
    gamma = FakeGamma(markets={"m-vol": payload})
    patch_fetches(monkeypatch, gamma=gamma)

    volume = await market_analysis.get_market_volume("m-vol")
    assert volume.market_id == "m-vol"
    assert volume.volume_24h == pytest.approx(15000.5)
    assert volume.volume_7d == pytest.approx(90000.0)
    assert volume.volume_30d == pytest.approx(400000.0)
    assert volume.volume_all_time == pytest.approx(1200000.0)
    # String payloads are coerced to float by the parse code.
    assert isinstance(volume.volume_24h, float)
    # The gamma call used the market_id path with no extra params.
    assert gamma.calls == [("/markets/m-vol", {})]

    # Missing keys fall back to zero (the `or 0` guard).
    bare_gamma = FakeGamma(markets={"m-bare": {"question": "Bare?"}})
    patch_fetches(monkeypatch, gamma=bare_gamma)
    bare = await market_analysis.get_market_volume("m-bare")
    assert bare.volume_24h == 0.0
    assert bare.volume_7d == 0.0
    assert bare.volume_30d == 0.0
    assert bare.volume_all_time == 0.0

    # Explicit None payloads also collapse to zero (the `or 0` guard).
    null_gamma = FakeGamma(
        markets={
            "m-null": {
                "question": "Nulls?",
                "volume24hr": None,
                "volume7d": None,
                "volume30d": None,
                "volumeNum": None,
            }
        }
    )
    patch_fetches(monkeypatch, gamma=null_gamma)
    null_volume = await market_analysis.get_market_volume("m-null")
    assert null_volume.volume_24h == 0.0
    assert null_volume.volume_all_time == 0.0

    # A gamma response delivered as a one-element list collapses to the dict.
    gamma_listed = FakeGamma(markets={"m-listed": [payload]})
    patch_fetches(monkeypatch, gamma=gamma_listed)
    listed = await market_analysis.get_market_volume("m-listed")
    assert listed.volume_24h == pytest.approx(15000.5)
    assert gamma_listed.calls == [("/markets/m-listed", {})]


# ---------------------------------------------------------------------------
# Order book parsing (market_analysis.py:196-237)
# ---------------------------------------------------------------------------
async def test_get_orderbook_truncates_to_depth(monkeypatch):
    book = {
        "bids": [
            {"price": "0.55", "size": "100"},
            {"price": "0.54", "size": "200"},
            {"price": "0.53", "size": "300"},
        ],
        "asks": [
            {"price": "0.60", "size": "150"},
            {"price": "0.61", "size": "250"},
            {"price": "0.62", "size": "350"},
        ],
    }
    clob = FakeClob(books={"tok": book})
    patch_fetches(monkeypatch, clob=clob)

    trimmed = await market_analysis.get_orderbook("tok", depth=2)
    assert isinstance(trimmed, OrderBook)
    assert trimmed.token_id == "tok"
    assert [entry.price for entry in trimmed.bids] == pytest.approx([0.55, 0.54])
    assert [entry.size for entry in trimmed.bids] == pytest.approx([100.0, 200.0])
    assert [entry.price for entry in trimmed.asks] == pytest.approx([0.60, 0.61])
    assert all(isinstance(entry, OrderBookEntry) for entry in trimmed.bids + trimmed.asks)

    full = await market_analysis.get_orderbook("tok")  # default depth 20 keeps all levels
    assert len(full.bids) == 3
    assert len(full.asks) == 3


# ---------------------------------------------------------------------------
# Market details (market_analysis.py:120-157)
# ---------------------------------------------------------------------------
async def test_get_market_details_identifier_rules(monkeypatch):
    gamma = FakeGamma(markets={})
    patch_fetches(monkeypatch, gamma=gamma)

    # No identifier at all is a hard error.
    with pytest.raises(ValueError, match="One of market_id"):
        await market_analysis.get_market_details()

    # The condition_id path queries /markets with params and collapses the list.
    gamma_cond = FakeGamma(
        markets={"cond-1": market_payload(question="Cond?", with_tokens=False)}
    )
    patch_fetches(monkeypatch, gamma=gamma_cond)
    details = await market_analysis.get_market_details(condition_id="cond-1")
    assert details["question"] == "Cond?"
    assert gamma_cond.calls == [("/markets", {"condition_id": "cond-1"})]

    # A one-element list response collapses to the dict itself.
    gamma_listed = FakeGamma(
        markets={"m2": [market_payload(question="Listed?", with_tokens=False)]}
    )
    patch_fetches(monkeypatch, gamma=gamma_listed)
    details = await market_analysis.get_market_details(market_id="m2")
    assert details["question"] == "Listed?"

    # Observed quirk: an EMPTY list response is returned as-is (no collapse,
    # no error) - market_analysis.py:148-151.
    gamma_empty = FakeGamma(markets={"m3": []})
    patch_fetches(monkeypatch, gamma=gamma_empty)
    assert await market_analysis.get_market_details(market_id="m3") == []


# ---------------------------------------------------------------------------
# Recommendation matrix (market_analysis.py:424-538)
# ---------------------------------------------------------------------------
async def test_analyze_liquid_market_recommends_buy(monkeypatch):
    # Observed: the BUY branch only fires when the healthy-market branch
    # (liquidity > 50000 AND volume > 10000) does not (market_analysis.py:497-504).
    # High liquidity + volume below 10000 + spread under 2% lands in BUY.
    market = market_payload(liquidity="60000", volume24hr="9000")
    prices = {
        "tok-yes": {"BUY": "0.60", "SELL": "0.59"},  # spread 1.68% (< 2%)
        "tok-no": {"BUY": "0.42", "SELL": "0.40"},
    }
    gamma = FakeGamma(markets={"m-buy": market})
    clob = FakeClob(prices=prices)
    patch_fetches(monkeypatch, gamma=gamma, clob=clob)

    opportunity = await market_analysis.analyze_market_opportunity("m-buy")
    assert isinstance(opportunity, MarketOpportunity)
    assert opportunity.risk_assessment == "low"
    assert opportunity.recommendation == "BUY"
    assert opportunity.confidence_score == 65
    assert opportunity.price_trend_24h == "stable"  # always "stable" in current code
    assert opportunity.current_price_yes == pytest.approx(0.595)
    assert opportunity.current_price_no == pytest.approx(0.41)
    assert opportunity.spread == pytest.approx(0.01)
    assert abs(opportunity.spread_pct - (0.01 / 0.595 * 100)) < 1e-9
    assert "Tight spread" in opportunity.reasoning


async def test_analyze_healthy_market_holds_despite_tight_spread(monkeypatch):
    # Pins the branch order with the inputs the original task spec suggested
    # (liquidity 60000, volume 20000, tight spread): the healthy branch
    # precedes the tight-spread BUY branch, so the verdict is HOLD/70.
    market = market_payload(liquidity="60000", volume24hr="20000")
    prices = {
        "tok-yes": {"BUY": "0.60", "SELL": "0.59"},
        "tok-no": {"BUY": "0.42", "SELL": "0.40"},
    }
    gamma = FakeGamma(markets={"m-healthy": market})
    clob = FakeClob(prices=prices)
    patch_fetches(monkeypatch, gamma=gamma, clob=clob)

    opportunity = await market_analysis.analyze_market_opportunity("m-healthy")
    assert opportunity.risk_assessment == "low"
    assert opportunity.recommendation == "HOLD"
    assert opportunity.confidence_score == 70
    assert "Healthy market" in opportunity.reasoning


async def test_analyze_low_liquidity_recommends_avoid(monkeypatch):
    # No tokens -> spread stays None; the liquidity branch fires first and wins
    # even with high trading volume (order-of-ifs pin).
    market = market_payload(liquidity="5000", volume24hr="20000", with_tokens=False)
    gamma = FakeGamma(markets={"m-low": market})
    patch_fetches(monkeypatch, gamma=gamma)

    opportunity = await market_analysis.analyze_market_opportunity("m-low")
    assert opportunity.risk_assessment == "high"
    assert opportunity.recommendation == "AVOID"
    assert opportunity.confidence_score == 30
    assert "Low liquidity" in opportunity.reasoning
    assert opportunity.spread is None
    assert opportunity.spread_pct is None
    assert opportunity.current_price_yes is None
    assert opportunity.current_price_no is None
    assert opportunity.volume_24h == pytest.approx(20000.0)
    assert opportunity.liquidity_usd == pytest.approx(5000.0)
    assert opportunity.price_trend_24h == "stable"


async def test_analyze_high_spread_recommends_avoid(monkeypatch):
    # The spread branch fires BEFORE the low-volume branch: liquidity 20000
    # (> 10000) with spread 8% and volume 500 (< 1000) is still AVOID/30.
    market = market_payload(liquidity="20000", volume24hr="500")
    prices = {
        "tok-yes": {"BUY": "0.52", "SELL": "0.48"},  # spread 0.04, mid 0.50 -> 8.0%
        "tok-no": {"BUY": "0.52", "SELL": "0.48"},
    }
    gamma = FakeGamma(markets={"m-spread": market})
    clob = FakeClob(prices=prices)
    patch_fetches(monkeypatch, gamma=gamma, clob=clob)

    opportunity = await market_analysis.analyze_market_opportunity("m-spread")
    assert opportunity.risk_assessment == "high"
    assert opportunity.recommendation == "AVOID"
    assert opportunity.confidence_score == 30
    assert abs(opportunity.spread_pct - 8.0) < 1e-9
    assert "High spread" in opportunity.reasoning


async def test_analyze_survives_price_fetch_failure(monkeypatch):
    # A price-fetch failure inside the analysis is caught: the analysis
    # continues without spread data and the verdict comes from volume/liquidity.
    market = market_payload(liquidity="60000", volume24hr="20000")
    gamma = FakeGamma(markets={"m-fail": market})

    async def broken_price(token_id, side="BOTH"):
        raise RuntimeError(f"clob offline for {token_id}")

    patch_fetches(monkeypatch, gamma=gamma)
    monkeypatch.setattr(market_analysis, "get_current_price", broken_price)

    opportunity = await market_analysis.analyze_market_opportunity("m-fail")
    assert isinstance(opportunity, MarketOpportunity)
    assert opportunity.spread is None
    assert opportunity.spread_pct is None
    assert opportunity.current_price_yes is None
    assert opportunity.current_price_no is None
    # Verdict comes from liquidity (60000 > 50000) and volume (20000 > 10000).
    assert opportunity.risk_assessment == "low"
    assert opportunity.recommendation == "HOLD"
    assert opportunity.confidence_score == 70


# ---------------------------------------------------------------------------
# compare_markets (market_analysis.py:541-594)
# ---------------------------------------------------------------------------
async def test_compare_markets_requires_two_markets(monkeypatch):
    gamma = FakeGamma(markets={})
    patch_fetches(monkeypatch, gamma=gamma)

    with pytest.raises(ValueError, match="At least 2"):
        await market_analysis.compare_markets([])
    with pytest.raises(ValueError, match="At least 2"):
        await market_analysis.compare_markets(["m1"])


async def test_compare_markets_rejects_more_than_ten(monkeypatch):
    gamma = FakeGamma(markets={})
    patch_fetches(monkeypatch, gamma=gamma)

    eleven = [f"m-{index}" for index in range(11)]
    with pytest.raises(ValueError, match="Maximum 10"):
        await market_analysis.compare_markets(eleven)
    # Rejection happens before any fetch.
    assert gamma.calls == []


async def test_compare_markets_tolerates_market_failure(monkeypatch):
    good_market = market_payload(
        question="Will the DAO upgrade ship?",
        liquidity="45000",
        volume24hr="15000",
        with_tokens=False,
    )
    gamma = FakeGamma(markets={"m-good": good_market})
    patch_fetches(monkeypatch, gamma=gamma)

    real_details = market_analysis.get_market_details

    async def selective_details(market_id=None, condition_id=None, slug=None):
        if market_id == "m-broken":
            raise RuntimeError("gamma exploded for m-broken")
        return await real_details(market_id=market_id, condition_id=condition_id, slug=slug)

    monkeypatch.setattr(market_analysis, "get_market_details", selective_details)

    comparisons = await market_analysis.compare_markets(["m-good", "m-broken"])
    assert len(comparisons) == 2

    ok = comparisons[0]
    assert ok["market_id"] == "m-good"
    assert ok["question"] == "Will the DAO upgrade ship?"
    assert ok["volume_24h"] == pytest.approx(15000.0)
    assert ok["volume_7d"] == pytest.approx(90000.0)
    assert ok["liquidity_usd"] == pytest.approx(45000.0)

    failed = comparisons[1]
    assert failed["market_id"] == "m-broken"
    assert "gamma exploded for m-broken" in failed["error"]


# ---------------------------------------------------------------------------
# Tool registry and dispatch (market_analysis.py:598-839)
# ---------------------------------------------------------------------------
def test_get_tools_registers_ten_tools():
    names = {tool.name for tool in market_analysis.get_tools()}
    assert names == {
        "get_market_details",
        "get_current_price",
        "get_orderbook",
        "get_spread",
        "get_market_volume",
        "get_liquidity",
        "get_price_history",
        "get_market_holders",
        "analyze_market_opportunity",
        "compare_markets",
    }


async def test_handle_tool_unknown_returns_error_text(monkeypatch):
    gamma = FakeGamma(
        markets={"m-liq": market_payload(liquidity="12345.67", with_tokens=False)}
    )
    clob = FakeClob(prices={"tok": {"BUY": "0.60", "SELL": "0.55"}})
    patch_fetches(monkeypatch, gamma=gamma, clob=clob)

    contents = await market_analysis.handle_tool("nao_existe", {})
    assert isinstance(contents, list)
    assert len(contents) == 1
    payload = json.loads(contents[0].text)
    assert payload == {"error": "Unknown tool: nao_existe"}

    # Happy path: dict results come back as JSON text.
    contents = await market_analysis.handle_tool("get_liquidity", {"market_id": "m-liq"})
    payload = json.loads(contents[0].text)
    assert payload["market_id"] == "m-liq"
    assert payload["liquidity_usd"] == pytest.approx(12345.67)
    assert payload["liquidity_formatted"] == "$12,345.67"

    # Model results are converted with model_dump(mode="json"): the datetime
    # timestamp becomes a string.
    contents = await market_analysis.handle_tool(
        "get_current_price", {"token_id": "tok", "side": "BOTH"}
    )
    payload = json.loads(contents[0].text)
    assert payload["ask"] == pytest.approx(0.60)
    assert payload["bid"] == pytest.approx(0.55)
    assert payload["mid"] == pytest.approx(0.575)
    assert isinstance(payload["timestamp"], str)

    # Validation errors from a dispatched tool become error text too.
    contents = await market_analysis.handle_tool("compare_markets", {"market_ids": ["m1"]})
    payload = json.loads(contents[0].text)
    assert "At least 2" in payload["error"]
