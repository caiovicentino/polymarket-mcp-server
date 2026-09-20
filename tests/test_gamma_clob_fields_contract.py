"""
Live-contract suite for the gamma/CLOB field mapping (T-0212; REQUER-HUMANO
item 138): five xfail(strict=True) offline tests pin the bugs the human fix
will consume, plus three live integration greens pinning the REAL API contract
the fix must build on.

The 5 xfails are the flip contract (precedent: tests/test_safety_adversarial.py
audit anatomy). Each body asserts the CORRECT behavior and fails against the
current code (proof of the bug); when the item 138 fixes land, the xfail flips
to XPASS (strict -> suite RED) and the fix consumes the flip.

Findings proven live first-hand (curator preflight 2026-09-17; APIs stateless,
re-probed on this branch the same day):
- V10: market_analysis.py:319-320 reads "volume7d"/"volume30d" - keys that do
  NOT exist in gamma payloads (present: volume1wk, volume1mo, volume24hr,
  volumeNum, volumeClob, volume24hrClob, volume1wkClob, volume1moClob,
  volume1yrClob, liquidity, liquidityNum, liquidityClob) -> volume_7d and
  volume_30d are ALWAYS 0.0.
- V11: market_analysis.py:461 reads market_details.get("tokens", []) - the
  gamma object has no "tokens" key (real: "clobTokenIds" as a JSON string of
  two token ids) -> token_prices is always {} -> current_price_yes/no and
  spread are always None.
- V12a: CLOB GET /price rejects side=BOTH with HTTP 400 {"error":"Invalid
  side"} (proven live). The code default (market_analysis.py:178) and the tool
  schema default (:642-654) are "BOTH".
- V12b: the code maps side=BUY -> .ask (:194-196) and side=SELL -> .bid
  (:198-200), but the REAL semantics are BUY = best bid, SELL = best ask
  (proven live: /price BUY == max(bids of /book), SELL == min(asks of /book))
  -> PriceData bid/ask are SWAPPED.
- V13: market_analysis.py:594 reads market.get("tags", []) - no "tags" key in
  the real object -> compare_markets always fabricates "tags": [].

Declared divergences contract x code (L-0020/L-0025 - asserts follow the
observed code, never the spec text; each test docstring carries the details):
- test_get_current_price_side_both_returns_both: the contract's literal assert
  (bid/ask not None) XPASSES today because the code already makes the two
  client-side calls for side="BOTH" (market_analysis.py:193-198; pre-existing
  pins test_market_analysis_offline.py:211-215 and :603-607), so the original
  "hoje levanta" claim does not hold against the observed code. The xfail is
  therefore carried by the SEMANTIC asserts (BUY must map to bid, SELL to ask)
  which fail today through the V12b inversion. The fake's raise-on-side=BOTH
  keeps the fix honest: any implementation that sends side=BOTH to the wire
  reproduces the live HTTP 400 and keeps this test RED.
- test_analyze_token_prices_from_clob_token_ids: analyze_market_opportunity
  returns a MarketOpportunity model - there is no "token_prices" key on the
  returned surface. The observable translation of "token_prices non-empty
  (>= 2 float entries)" is current_price_yes/current_price_no becoming floats:
  the internal dict feeds exactly those fields (market_analysis.py:461-474).
- test_compare_markets_tags_not_fabricated: compare_markets takes market IDs
  (market_analysis.py:541-543) and returns the per-market comparison LIST -
  the contract's compare_markets([m1, m2]) / result["markets"] wrapper does
  not exist; the assert runs over the real list surface.

Fix note (item 138): the prescribed fix for V12 is option (i) - side="BOTH"
makes two client-side calls (BUY + SELL) with the corrected mapping
(BUY -> .bid, SELL -> .ask). Option (ii) (/midpoint + /spread, deprecate
side=BOTH in the schema) would need this file's flip adjusted by the fixer
(same caveat the contract documents for V11).

Hermeticity: the offline xfails are zero-network (module-seam fakes, fail-loud
per P-0031 - any unexpected endpoint/argument raises AssertionError, no silent
fallback to the real network). The live tests are marked `integration` - and
ONLY that, so the canonical offline selection of CONTRIBUTING.md excludes them
(P-0048) - and skip on network failure: the guard never fails the suite for
infra (A3 contract).
"""

import json

import httpx
import pytest

from polymarket_mcp.tools import market_analysis

GAMMA_API_URL = "https://gamma-api.polymarket.com"
CLOB_API_URL = "https://clob.polymarket.com"

# Synthetic CLOB token ids (78 chars, same shape as the real ones) and the
# gamma conditionId both fakes agree on - so either fix shape (parse
# clobTokenIds here, or fetch CLOB /markets/{conditionId}) resolves to tokens
# the /price stub serves.
SYNTH_YES_TOKEN = "1" * 78
SYNTH_NO_TOKEN = "2" * 78
SYNTH_CONDITION_ID = "0x" + "a1b2c3d4" * 8


class FakeGamma:
    """Fail-loud stand-in for market_analysis._fetch_gamma_api (P-0031)."""

    def __init__(self, markets=None):
        # markets: {identifier: payload}; the list form exercises the
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
    """Fail-loud stand-in for market_analysis._fetch_clob_api (P-0031).

    fail_sides simulates the live CLOB /price contract: side=BOTH is rejected
    with HTTP 400 {"error":"Invalid side"} (proven live 2026-09-17), so a fix
    that sends side=BOTH to the wire reproduces the 400 here and keeps the
    xfails RED. markets serves the fix-shape (ii) alternative of item 138
    (CLOB /markets/{conditionId} exposes a real "tokens" array).
    """

    def __init__(self, prices=None, fail_sides=(), markets=None):
        # prices: {token_id: {"BUY": "0.52", "SELL": "0.53"}} - string payloads,
        # the parsing code coerces with float() (market_analysis.py:195,199).
        self.prices = prices or {}
        self.fail_sides = set(fail_sides)
        self.markets = markets or {}
        self.calls = []

    async def __call__(self, endpoint, params=None):
        params = dict(params or {})
        self.calls.append((endpoint, params))
        if endpoint == "/price":
            token_id = params.get("token_id")
            side = params.get("side")
            if side in self.fail_sides:
                raise RuntimeError("Invalid side")  # sim of the live HTTP 400 body
            side_prices = self.prices.get(token_id, {})
            if side not in side_prices:
                raise AssertionError(f"no synthetic price for token={token_id!r} side={side!r}")
            return {"price": side_prices[side]}
        if endpoint.startswith("/markets/"):
            condition_id = endpoint[len("/markets/"):]
            if condition_id not in self.markets:
                raise AssertionError(f"no synthetic clob market for {condition_id!r}")
            return self.markets[condition_id]
        raise AssertionError(f"unexpected clob endpoint: {endpoint!r}")


def _real_gamma_market(market_id, **overrides):
    """Real-shaped gamma market payload: only fields the live API provides.
    Deliberately NO volume7d/volume30d, NO "tokens" and NO "tags" - that is
    the whole point of V10/V11/V13 (the pre-existing market_payload fixture in
    test_market_analysis_offline.py carries those fabricated keys, which is
    why the bugs went unnoticed; this suite pins the REAL shape)."""
    payload = {
        "id": market_id,
        "question": f"Will the proposal pass before December? ({market_id})",
        "conditionId": SYNTH_CONDITION_ID,
        "clobTokenIds": json.dumps([SYNTH_YES_TOKEN, SYNTH_NO_TOKEN]),
        "volume24hr": "20000",
        "volume1wk": "90000",
        "volume1mo": "400000",
        "volumeNum": "1200000",
        "liquidity": "60000",
        "endDate": "2026-12-31T00:00:00Z",
        "active": True,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Offline xfail-strict tests - the flip contract for REQUER-HUMANO item 138
# (fakes simulate the REAL API behavior; P-0031/P-0040 fail-loud anatomy)
# ---------------------------------------------------------------------------
@pytest.mark.xfail(
    strict=True,
    reason=(
        "V10: code reads volume7d/volume30d which do not exist in gamma "
        "payloads (REQUER-HUMANO item 138)"
    ),
)
async def test_volume_reads_volume1wk_1mo_not_7d_30d(monkeypatch):
    """get_market_volume (market_analysis.py:319-320) must read the REAL
    gamma fields (volume1wk -> volume_7d, volume1mo -> volume_30d); today it
    reads the nonexistent volume7d/volume30d and returns 0.0 for both."""
    market = {
        "volume1wk": "90000",
        "volume1mo": "400000",
        "volume24hr": "12000",
        "volumeNum": 123456.0,
        "liquidity": "5000",
    }
    gamma = FakeGamma(markets={"m-vol": market})
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", gamma)

    volume = await market_analysis.get_market_volume("m-vol")

    # The fix reads the real fields into the 7d/30d attributes (minimal
    # semantic fix of item 138; a model rename would adjust this flip).
    assert volume.volume_7d == pytest.approx(90000.0)
    assert volume.volume_30d == pytest.approx(400000.0)
    # Control pins: reads that are already correct today (unchanged by the fix).
    assert volume.volume_24h == pytest.approx(12000.0)
    assert volume.volume_all_time == pytest.approx(123456.0)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "V11: gamma market has no 'tokens' key; real field is clobTokenIds "
        "(JSON string) (REQUER-HUMANO item 138)"
    ),
)
async def test_analyze_token_prices_from_clob_token_ids(monkeypatch):
    """analyze_market_opportunity (market_analysis.py:461) must derive the
    token list from the real field; today it reads the nonexistent 'tokens'
    key, so token_prices stays {} and the model fields stay None.

    Divergence (L-0025): the contract's literal `result["token_prices"]` does
    not exist on the returned surface - analyze_market_opportunity returns a
    MarketOpportunity whose current_price_yes/current_price_no fields are fed
    by exactly that internal dict (market_analysis.py:461-474); the asserts
    pin the observable translation. The fake serves BOTH fix shapes of item
    138 (parse clobTokenIds here, or CLOB /markets/{conditionId}) fail-loud.
    """
    market = _real_gamma_market("m-clob")
    gamma = FakeGamma(markets={"m-clob": market})
    clob = FakeClob(
        prices={
            SYNTH_YES_TOKEN: {"BUY": "0.52", "SELL": "0.53"},
            SYNTH_NO_TOKEN: {"BUY": "0.52", "SELL": "0.53"},
        },
        fail_sides=("BOTH",),
        markets={
            SYNTH_CONDITION_ID: {
                "tokens": [
                    {"token_id": SYNTH_YES_TOKEN, "outcome": "YES"},
                    {"token_id": SYNTH_NO_TOKEN, "outcome": "NO"},
                ]
            }
        },
    )
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", gamma)
    monkeypatch.setattr(market_analysis, "_fetch_clob_api", clob)

    opportunity = await market_analysis.analyze_market_opportunity("m-clob")

    # "token_prices non-empty (>= 2 float entries)" on the observable surface.
    assert opportunity.current_price_yes is not None
    assert opportunity.current_price_no is not None
    assert opportunity.spread is not None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "V12a: CLOB /price rejects side=BOTH with HTTP 400 Invalid side "
        "(REQUER-HUMANO item 138)"
    ),
)
async def test_get_current_price_side_both_returns_both(monkeypatch):
    """side=BOTH (code default market_analysis.py:178; tool schema default
    :642-654) must return BOTH bid and ask using ONLY the two calls the real
    CLOB /price accepts (BUY and SELL). The fake raises the live-proven 400
    ("Invalid side") for any other side, so an implementation that sends
    side=BOTH to the wire keeps this test RED.

    Divergences (L-0025), declared:
    - The contract's literal assert (bid/ask not None) XPASSES today: the code
      ALREADY makes the two client-side calls for side="BOTH"
      (market_analysis.py:193-198; pre-existing pins
      test_market_analysis_offline.py:211-215 and :603-607), so the original
      "hoje levanta" claim does not hold against the observed code.
    - The xfail therefore fires today through the V12b inversion: with the
      real semantics BUY=best bid / SELL=best ask, the current mapping
      (BUY -> .ask, SELL -> .bid) swaps the values, so the semantic asserts
      below fail today and flip with fix option (i) (two client-side calls +
      corrected mapping). Fix option (ii) (/midpoint + /spread) would need
      this flip adjusted by the fixer - item 138 documents the choice."""
    clob = FakeClob(prices={"tok": {"BUY": "0.52", "SELL": "0.53"}}, fail_sides=("BOTH",))
    monkeypatch.setattr(market_analysis, "_fetch_clob_api", clob)

    price_data = await market_analysis.get_current_price("tok", "BOTH")

    assert price_data.bid is not None and price_data.ask is not None
    assert price_data.bid == pytest.approx(0.52)  # BUY = best bid (real semantics)
    assert price_data.ask == pytest.approx(0.53)  # SELL = best ask (real semantics)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "V12b: code maps BUY\u2192.ask and SELL\u2192.bid; real semantics are "
        "BUY=best bid, SELL=best ask (REQUER-HUMANO item 138)"
    ),
)
async def test_get_current_price_mapping_not_inverted(monkeypatch):
    """The corrected mapping is BUY -> .bid and SELL -> .ask; today the code
    assigns them swapped (market_analysis.py:194-196/:198-200), so the single
    -side PriceData comes back with the fields crossed. With only one side
    fetched, mid stays None (it is computed only when both sides exist)."""
    clob = FakeClob(prices={"tok": {"BUY": "0.52", "SELL": "0.53"}})
    monkeypatch.setattr(market_analysis, "_fetch_clob_api", clob)

    buy = await market_analysis.get_current_price("tok", "BUY")

    assert buy.bid == pytest.approx(0.52)  # BUY = best bid
    assert buy.ask is None
    assert buy.mid is None

    sell = await market_analysis.get_current_price("tok", "SELL")

    assert sell.ask == pytest.approx(0.53)  # SELL = best ask
    assert sell.bid is None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "V13: gamma market has no 'tags' key; compare fabricates empty tags "
        "(REQUER-HUMANO item 138)"
    ),
)
async def test_compare_markets_tags_not_fabricated(monkeypatch):
    """compare_markets (market_analysis.py:594) must not fabricate a "tags"
    field that no real source provides; the honest fix removes the field from
    the output (no gamma source exists today).

    Divergence (L-0025): the contract's compare_markets([m1, m2]) /
    result["markets"] shape does not exist - the function takes market IDs
    (market_analysis.py:541-543) and returns the per-market comparison LIST;
    the assert runs over the real list surface."""
    gamma = FakeGamma(
        markets={
            "m1": _real_gamma_market("m1", question="Will the first pass?"),
            "m2": _real_gamma_market("m2", question="Will the second pass?"),
        }
    )
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", gamma)

    result = await market_analysis.compare_markets(["m1", "m2"])

    assert len(result) == 2
    assert all("tags" not in market or market["tags"] is None for market in result)


# ---------------------------------------------------------------------------
# Live integration greens - the REAL API contract the item 138 fix builds on
# (marked integration ONLY; network guard never fails the suite for infra)
# ---------------------------------------------------------------------------
def _skip_on_transport(exc, label):
    """Network guard: infra failures SKIP (never fail the suite for infra)."""
    pytest.skip(f"{label} unreachable ({type(exc).__name__}: {exc})")


def _check_response(response, label):
    """Fail-closed response check: 5xx is an API-side outage (documented
    skip); any other non-200 is a live-contract violation (FAIL)."""
    if response.status_code >= 500:
        pytest.skip(f"{label}: live API outage (HTTP {response.status_code})")
    assert response.status_code == 200, f"{label}: expected HTTP 200, got {response.status_code}"


async def _fetch_top_markets(client):
    """The pattern of the existing integration suites: the gamma /markets
    endpoint. Top-volume live slice - a liquid market for the /book pins."""
    try:
        response = await client.get(
            f"{GAMMA_API_URL}/markets",
            params={"limit": 5, "order": "volume24hr", "ascending": "false",
                    "active": "true", "closed": "false"},
        )
    except (httpx.HTTPError, OSError) as exc:
        _skip_on_transport(exc, "gamma /markets")
    _check_response(response, "gamma /markets")
    markets = response.json()
    assert isinstance(markets, list) and markets, "gamma /markets returned no markets"
    return markets


async def _two_sided_book(client, markets):
    """Walk the top-volume markets and return (token_id, bids, asks) for the
    first with a two-sided book; skip when every candidate is degenerate (the
    ordering/semantics contract is only pinnable on a real two-sided book).

    A gamma-active/open market may have NO deployed CLOB book: proven live in
    the T-0407 window (2026-09-20), the top-1 market by volume24hr answered
    HTTP 404 for BOTH clobTokenIds on /book while the next candidate answered
    200 with a two-sided book. A 404 for a gamma-listed token id is therefore
    a legitimate degenerate wire state, NOT a live-contract break: the walk
    SKIPS that candidate (continue). Every other non-200 still goes through
    _check_response (5xx -> infra skip, other -> live-contract violation)."""
    for market in markets:
        raw = market.get("clobTokenIds")
        if not isinstance(raw, str):
            continue
        try:
            token_ids = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not (isinstance(token_ids, list) and len(token_ids) >= 2):
            continue
        token_id = token_ids[0]
        if not isinstance(token_id, str) or not token_id:
            continue
        try:
            response = await client.get(
                f"{CLOB_API_URL}/book", params={"token_id": token_id}
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "CLOB /book")
        if response.status_code == 404:
            # No deployed CLOB book for this gamma-listed token - legitimate
            # degenerate state (see docstring); walk past instead of
            # fail-closing the whole suite.
            continue
        _check_response(response, "CLOB /book")
        book = response.json()
        bids = [float(entry["price"]) for entry in (book.get("bids") or [])]
        asks = [float(entry["price"]) for entry in (book.get("asks") or [])]
        if len(bids) >= 2 and len(asks) >= 2:
            return token_id, bids, asks
    pytest.skip("no two-sided book among the top-volume live markets (degenerate slice)")


@pytest.mark.integration
async def test_live_gamma_volume_fields_1wk_1mo_present():
    """Live pin of V10's premise: the gamma market object carries
    volume1wk/volume1mo and does NOT carry volume7d/volume30d (proven live by
    the curator preflight 2026-09-17 on 5/5 markets; APIs stateless)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        markets = await _fetch_top_markets(client)
        market = markets[0]

    assert "volume1wk" in market
    assert "volume1mo" in market
    assert "volume7d" not in market
    assert "volume30d" not in market


@pytest.mark.integration
async def test_live_clob_price_buy_sell_semantics():
    """Live pin of the REAL /price semantics (the V12b proof): side=BUY
    returns a price from the BID side and side=SELL a price from the ASK
    side of the /book. FATOS ESTAVEIS only (P-0197/L-0390): the /book
    snapshot and the two /price calls hit a LIVE matching engine at
    different instants -- CI evidence run 35486236626 (ubuntu 3.11):
    sell_price 0.13 vs min(asks) 0.12, a 1-tick move inside ONE run, with
    the same code passing the adjacent run. Exact equality is a time bomb;
    the asserts below pin the SIDE mapping with a tolerance band (0.05 =
    5 ticks of a 0.01-tick market) and the relational fact buy <= sell
    (+tol). Declared limitation: on tight-spread books (< tol) the
    inverted mapping is NOT discriminated live -- the primary inversion
    pin lives offline (test_get_current_price_mapping_not_inverted,
    xfail-strict); this test is the wire-sanity belt. A move LARGER than
    the tolerance between the bracketed calls remains RED (pathological
    volatility) -- the gate's flaky retry absorbs rare occurrences."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        markets = await _fetch_top_markets(client)
        token_id, bids, asks = await _two_sided_book(client, markets)
        try:
            buy_response = await client.get(
                f"{CLOB_API_URL}/price", params={"token_id": token_id, "side": "BUY"}
            )
            sell_response = await client.get(
                f"{CLOB_API_URL}/price", params={"token_id": token_id, "side": "SELL"}
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "CLOB /price")
        _check_response(buy_response, "CLOB /price side=BUY")
        _check_response(sell_response, "CLOB /price side=SELL")
        buy_price = float(buy_response.json()["price"])
        sell_price = float(sell_response.json()["price"])

    buy_sell_tol = 0.05  # 5 ticks of a 0.01-tick market: absorbs normal
    # freshness variance between the /book snapshot and the /price calls
    # (CI evidence run 35486236626: a 1-tick move inside one run).
    assert buy_price <= sell_price + buy_sell_tol, (
        f"BUY price must come from the BID side (buy <= sell + tol): "
        f"buy={buy_price} sell={sell_price}"
    )
    assert abs(buy_price - max(bids)) <= buy_sell_tol, (
        f"buy price drifted beyond the tolerance band from the best bid: "
        f"buy={buy_price} max(bids)={max(bids)}"
    )
    assert abs(sell_price - min(asks)) <= buy_sell_tol, (
        f"sell price drifted beyond the tolerance band from the best ask: "
        f"sell={sell_price} min(asks)={min(asks)}"
    )


@pytest.mark.integration
async def test_live_clob_book_worst_first_ordering():
    """Live pin of the RAW /book ordering contract that the T-0211 fix trusts:
    bids ASCENDING (best bid LAST) and asks DESCENDING (best ask LAST) -
    worst-first. The _two_sided_book walk already requires >= 2 levels per
    side, so the ordering assertions are never vacuous."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        markets = await _fetch_top_markets(client)
        _, bids, asks = await _two_sided_book(client, markets)

    assert bids == sorted(bids)
    assert asks == sorted(asks, reverse=True)
    assert bids[0] < bids[-1]  # best bid at the END of the raw /book bids
    assert asks[0] > asks[-1]  # best ask at the END of the raw /book asks


class _FakeBookResponse:
    """Minimal stand-in for an httpx.Response inside the _two_sided_book walk."""

    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _FakeBookClient:
    """Routes each token id to a canned /book response; any token NOT in the
    map answers 404 (the no-deployed-book state the walk must survive)."""

    def __init__(self, books=None):
        self.books = dict(books or {})
        self.requested = []

    async def get(self, url, params=None):
        token = params["token_id"]
        self.requested.append(token)
        return _FakeBookResponse(*self.books.get(token, (404,)))


def _walk_market(token_a, token_b):
    return {"clobTokenIds": json.dumps([token_a, token_b])}


async def test_walk_returns_first_two_sided_book():
    client = _FakeBookClient({
        "tokA": (200, {"bids": [{"price": "0.40"}, {"price": "0.52"}],
                        "asks": [{"price": "0.60"}, {"price": "0.53"}]}),
    })
    token, bids, asks = await _two_sided_book(client, [_walk_market("tokA", "tokA2")])
    assert token == "tokA"
    assert bids == [0.40, 0.52]
    assert asks == [0.60, 0.53]
    assert client.requested == ["tokA"]


async def test_walk_continues_past_book_404():
    client = _FakeBookClient({
        "tokC": (200, {"bids": [{"price": "0.01"}, {"price": "0.02"}],
                        "asks": [{"price": "0.99"}, {"price": "0.98"}]}),
    })
    markets = [_walk_market("tokB", "tokB2"), _walk_market("tokC", "tokC2")]
    token, bids, asks = await _two_sided_book(client, markets)
    assert token == "tokC"
    assert bids == [0.01, 0.02]
    assert asks == [0.99, 0.98]
    assert client.requested == ["tokB", "tokC"]


async def test_walk_continues_past_one_sided_book():
    client = _FakeBookClient({
        "tokD": (200, {"bids": [{"price": "0.10"}, {"price": "0.11"}], "asks": []}),
        "tokE": (200, {"bids": [{"price": "0.20"}, {"price": "0.21"}],
                        "asks": [{"price": "0.80"}, {"price": "0.79"}]}),
    })
    markets = [_walk_market("tokD", "tokD2"), _walk_market("tokE", "tokE2")]
    token, bids, asks = await _two_sided_book(client, markets)
    assert token == "tokE"
    assert client.requested == ["tokD", "tokE"]


async def test_walk_continues_past_malformed_token_ids():
    client = _FakeBookClient({
        "tokH": (200, {"bids": [{"price": "0.30"}, {"price": "0.31"}],
                        "asks": [{"price": "0.70"}, {"price": "0.69"}]}),
    })
    markets = [
        {"clobTokenIds": "not-json"},
        {"clobTokenIds": json.dumps(["only1"])},
        {"clobTokenIds": 42},
        _walk_market("tokH", "tokH2"),
    ]
    token, bids, asks = await _two_sided_book(client, markets)
    assert token == "tokH"
    assert client.requested == ["tokH"]


async def test_walk_skips_when_no_candidate_is_two_sided():
    client = _FakeBookClient({
        "tokJ": (200, {"bids": [{"price": "0.10"}, {"price": "0.11"}], "asks": []}),
    })
    markets = [_walk_market("tokI", "tokI2"), _walk_market("tokJ", "tokJ2")]
    with pytest.raises(pytest.skip.Exception):
        await _two_sided_book(client, markets)
    assert client.requested == ["tokI", "tokJ"]
