"""
Offline gap suite for polymarket_mcp.tools.market_analysis — residual slice
(farm/T-0058; fork point 94899fe of the polymarket-mcp-server clone).

Why this suite exists
---------------------
The T-0037 suite (tests/test_market_analysis_offline.py) covers the happy
paths and the AVOID/HOLD-70/BUY-65 branches. The coverage report at the fork
point (286 stmts / 70 miss / 64 branches / 13 partial, 75.14%) leaves these
ranges dead:

    88-100      _fetch_gamma_api body (rate limiter + httpx seam)
    105-117     _fetch_clob_api body (MARKET_DATA limiter + httpx seam)
    139         get_market_details `if slug:` branch
    234-236     get_orderbook except (log + re-raise)
    253         get_spread ValueError when bid/ask missing
    291->295    get_market_volume `if timeframes is None:` false edge
    309-311     get_market_volume except (log + re-raise)
    339-341     get_liquidity except (log + re-raise)
    362-388     get_price_history body (placeholder; whole function)
    405-421     get_market_holders body (placeholder; whole function)
    463-464     analyze: else of `if yes_price.bid and yes_price.ask`
    486-487     analyze: risk "medium" / "Low trading volume"
    506-508     analyze: recommendation else -> HOLD / 50
    536-538     analyze: except (log + re-raise)
    802         handle_tool route get_market_details (no model_dump)
    808-809     handle_tool route get_orderbook (with model_dump)
    811         handle_tool route get_spread
    813-814     handle_tool route get_market_volume (with model_dump)
    818         handle_tool route get_price_history
    820         handle_tool route get_market_holders
    822-823     handle_tool route analyze_market_opportunity (with model_dump)

Every network seam is patched BEFORE any execution (L-0118/P-0031): the
httpx.AsyncClient seam is a scripted fail-loud fake that refuses to run
without a script, so a silent fallback to the real network is impossible.
Zero sleeps (L-0014), zero wall-clock dependence (frozen datetime shim). No
integration/slow/real_api markers: this file runs in the release gate
(L-0110). The rate-limiter seam is never the real process singleton
(L-0123): a fail-loud default plus a per-test recorder.

Observed divergences (L-0025/L-0090 — the contract's semantic labels for the
coverage lines drifted; the line numbers match the report, the code wins):
1. Contract labeled :486-487 "risk high / High spread"; that branch
   (:482-484) is already covered by T-0037
   (test_analyze_high_spread_recommends_avoid). The DEAD lines :486-487 are
   risk "medium" / "Low trading volume" — covered here by the complementary
   test_analyze_medium_risk_when_volume_below_1000.
2. Contract labeled :506-508 "risk low / Good liquidity"; risk "low"
   (:488-490) is already covered by T-0037 (BUY-65 / HOLD-70 tests). The
   DEAD lines :506-508 are the HOLD/50 else of the recommendation matrix —
   covered by test_analyze_market_opportunity_falls_back_to_hold_50.
3. Contract labeled :536-538 "else final HOLD/50"; the DEAD lines :536-538
   are the except/re-raise of analyze_market_opportunity — covered by the
   complementary test_analyze_market_opportunity_propagates_details_error.
4. Contract labeled :139 "elif market_id"; :139 is the `if slug:` branch
   (f"/markets/{slug}") — never exercised by T-0037. Covered by the
   complementary test_get_market_details_uses_slug_endpoint; the mandatory
   test_get_market_details_falls_back_to_market_id pins the third-fallback
   route with a PLAIN DICT payload (T-0037 only exercised market_id with
   list payloads).
5. The default dates computed in get_price_history (:364-370) are never
   used afterwards — they are pinned through recorder shims on the module's
   datetime/timedelta seams (observable: number of utcnow() calls and the
   timedelta(days=7) construction). A frozen instant makes the pin
   wall-clock independent, which subsumes the contract's ">=1h margin"
   concern (L-0014).
6. Dead parameters observed (product findings for the report, NOT patched —
   SUITE-ONLY slice, L-0090): get_market_volume's `timeframes` argument is
   accepted and never used after :291-293; get_market_holders' `limit`
   argument is never referenced in its body (:405-421).

Overlap calibration (Already Covered — do not re-pin here)
-----------------------------------------------------------
tests/test_market_analysis_offline.py (T-0037): identifier routing
(no-identifier ValueError, condition_id route, market_id route with list
payloads, empty-list quirk), price parsing (BOTH/BUY/SELL/unknown side, mid
math), spread happy path, volume parsing incl. `or 0` guards, orderbook
depth truncation, recommendation matrix AVOID via low liquidity and via
high spread, HOLD/70 healthy, BUY/65 tight spread, price-fetch failure
resilience (the :466-469 except), compare_markets validation + per-market
tolerance, tool registry, handle_tool unknown tool + the get_current_price,
get_liquidity and compare_markets routes + error wrapping.
tests/test_market_tools.py is integration-marked (real API) and excluded
from the release gate — no offline overlap.

Structural pins (L-0121)
------------------------
- FakeHttpClient.__init__ accepts ONLY `timeout`; get() accepts ONLY
  (url, params). A future change that forwards extra kwargs fails with
  TypeError at the call site, not with a silent pass.
- _Dumped.model_dump requires mode="json"; a route that starts dumping with
  another mode (or without it) fails loud.
- The analysis fakes declare exactly the kwargs the module passes today.
"""
import json
from datetime import datetime, timedelta

import httpx
import pytest

from polymarket_mcp.tools import market_analysis

HISTORY_PLACEHOLDER = [
    {
        "error": "Historical price data not available via public Polymarket API",
        "suggestion": "Use real-time price tracking or third-party data providers",
    }
]
HOLDERS_PLACEHOLDER = [
    {
        "error": "Position holder data not available via public API",
        "suggestion": "This data may require authenticated access with proper permissions",
    }
]
HOLD_50_REASONING = (
    "Market conditions are acceptable but not optimal. Monitor for better entry points."
)


class _ScriptedResponse:
    """httpx.Response stand-in: raise_for_status fires the scripted error,
    json() returns the scripted payload."""

    def __init__(self, payload, status_error=None):
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error is not None:
            raise self._status_error

    def json(self):
        return self._payload


class FakeHttpClient:
    """httpx.AsyncClient stand-in at the market_analysis module seam.

    Fail-loud (P-0031): constructed without a script, or with an unexpected
    URL/params, it raises AssertionError — a silent fallback to the real
    network is impossible (L-0118). Structural pin (L-0121): __init__
    accepts only the documented timeout kwarg and get() only (url, params).
    """

    script = None
    instances = None

    def __init__(self, timeout):
        if FakeHttpClient.script is None:
            raise AssertionError(
                "httpx.AsyncClient seam entered without script (fail-loud, L-0118)"
            )
        if timeout != 30.0:
            raise AssertionError(f"unexpected AsyncClient timeout: {timeout!r}")
        self.timeout = timeout
        self.calls = []
        FakeHttpClient.instances.append(self)

    async def get(self, url, params):
        script = FakeHttpClient.script
        if url != script["url"]:
            raise AssertionError(
                f"unexpected GET url: {url!r} (expected {script['url']!r})"
            )
        if params != script["params"]:
            raise AssertionError(
                f"unexpected GET params: {params!r} (expected {script['params']!r})"
            )
        self.calls.append((url, dict(params)))
        if script.get("get_error") is not None:
            raise script["get_error"]
        return _ScriptedResponse(script["payload"], script.get("status_error"))

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _ScriptedHttpx:
    """Namespace shim replacing market_analysis.httpx: only AsyncClient is
    reachable, and it is the scripted fail-loud fake."""

    AsyncClient = FakeHttpClient


class FetchSeam:
    """Fail-loud stand-in for the module fetch helpers (_fetch_gamma_api /
    _fetch_clob_api, P-0031). Records every (endpoint, params) call; raises
    AssertionError for any endpoint without a scripted payload, or the
    scripted error when one is configured."""

    def __init__(self, payloads=None, error=None):
        self.payloads = payloads or {}
        self.error = error
        self.calls = []

    async def __call__(self, endpoint, params=None):
        params = dict(params or {})
        self.calls.append((endpoint, params))
        if self.error is not None:
            raise self.error
        if endpoint not in self.payloads:
            raise AssertionError(f"unexpected fetch endpoint: {endpoint!r}")
        return self.payloads[endpoint]


class FakeRateLimiter:
    """Records acquire() categories; never the real process singleton
    (L-0123)."""

    def __init__(self):
        self.acquires = []

    async def acquire(self, category):
        self.acquires.append(category)


class _FrozenDatetime:
    """Shim for market_analysis.datetime: utcnow() returns a FIXED real
    datetime and records each call; mode='raise' turns utcnow() into a
    deterministic error (used to reach the get_price_history except)."""

    mode = "fixed"
    calls = None
    instant = None

    @staticmethod
    def utcnow():
        _FrozenDatetime.calls.append(_FrozenDatetime.mode)
        if _FrozenDatetime.mode == "raise":
            raise RuntimeError("clock exploded")
        return _FrozenDatetime.instant


class _RecordingTimedelta(timedelta):
    """Real timedelta subclass: constructs REAL instances (so
    `datetime - timedelta` keeps working) while recording the constructor
    args the module passes (observable: the 7-day default range)."""

    constructed = None

    def __new__(cls, *args, **kwargs):
        _RecordingTimedelta.constructed.append((args, kwargs))
        return timedelta.__new__(timedelta, *args, **kwargs)


class _SplitLogger:
    """logger shim for the get_market_holders except-path: warning()
    explodes deterministically, error() records instead of raising."""

    def __init__(self):
        self.errors = []

    def warning(self, message, *args):
        raise RuntimeError("logger exploded")

    def error(self, message, *args):
        self.errors.append(message)


class _Dumped:
    """Minimal stand-in for the pydantic models the model_dump routes
    return: model_dump(mode) hands back the marked payload; any other mode
    fails loud (L-0121)."""

    def __init__(self, payload):
        self._payload = payload

    def model_dump(self, mode):
        if mode != "json":
            raise AssertionError(f"unexpected model_dump mode: {mode!r}")
        return self._payload


def _http_status_error(url):
    """Build a REAL httpx.HTTPStatusError offline (object construction only,
    no network) for the fetcher error-path tests."""
    request = httpx.Request("GET", url)
    response = httpx.Response(500, request=request)
    return httpx.HTTPStatusError(
        f"Server error '500 Internal Server Error' for url {url}",
        request=request,
        response=response,
    )


def _fail_loud_rate_limiter():
    raise AssertionError("rate limiter seam entered without recorder fixture")


@pytest.fixture(autouse=True)
def isolated_seams(monkeypatch):
    """Patch the market_analysis module seams BEFORE any execution
    (L-0118): the network seam refuses to run unless a test scripts it, and
    the rate-limiter seam refuses to run unless a test installs the
    recorder. Class-level state is reset around every test."""
    FakeHttpClient.script = None
    FakeHttpClient.instances = []
    _FrozenDatetime.calls = []
    _FrozenDatetime.mode = "fixed"
    _RecordingTimedelta.constructed = []
    monkeypatch.setattr(market_analysis, "httpx", _ScriptedHttpx)
    monkeypatch.setattr(market_analysis, "get_rate_limiter", _fail_loud_rate_limiter)
    yield
    FakeHttpClient.script = None  # defensive: never leak a script across tests
    FakeHttpClient.instances = []


@pytest.fixture
def rate_limiter(monkeypatch):
    """Recorder limiter for the fetcher tests (L-0123)."""
    limiter = FakeRateLimiter()
    monkeypatch.setattr(market_analysis, "get_rate_limiter", lambda: limiter)
    return limiter


@pytest.fixture
def frozen_clock(monkeypatch):
    """Pins the module's datetime/timedelta seams for the placeholder tests."""
    _FrozenDatetime.calls = []
    _FrozenDatetime.mode = "fixed"
    _FrozenDatetime.instant = datetime(2026, 9, 15, 12, 0, 0)
    _RecordingTimedelta.constructed = []
    monkeypatch.setattr(market_analysis, "datetime", _FrozenDatetime)
    monkeypatch.setattr(market_analysis, "timedelta", _RecordingTimedelta)


def patch_analysis(monkeypatch, *, details, volume, liquidity, prices):
    """Patch the four analysis input seams with fakes that declare EXACTLY
    the kwargs the module passes today (L-0121): a future change that
    forwards extra kwargs fails with TypeError at the call site."""

    async def fake_details(market_id=None, condition_id=None, slug=None):
        return details

    async def fake_volume(market_id, timeframes=None):
        return volume

    async def fake_liquidity(market_id):
        return liquidity

    async def fake_price(token_id, side="BOTH"):
        return prices[token_id]

    monkeypatch.setattr(market_analysis, "get_market_details", fake_details)
    monkeypatch.setattr(market_analysis, "get_market_volume", fake_volume)
    monkeypatch.setattr(market_analysis, "get_liquidity", fake_liquidity)
    monkeypatch.setattr(market_analysis, "get_current_price", fake_price)


def two_token_details(question="Analysis?"):
    return {
        "question": question,
        "tokens": [{"token_id": "tok-yes"}, {"token_id": "tok-no"}],
    }


# ---------------------------------------------------------------------------
# _fetch_gamma_api / _fetch_clob_api (market_analysis.py:86-117)
# ---------------------------------------------------------------------------
async def test_fetch_gamma_api_returns_json(rate_limiter):
    url = f"{market_analysis.GAMMA_API_URL}/markets/abc"
    FakeHttpClient.script = {"url": url, "params": {}, "payload": {"id": "abc", "ok": True}}

    result = await market_analysis._fetch_gamma_api("/markets/abc")

    assert result == {"id": "abc", "ok": True}
    assert rate_limiter.acquires == [market_analysis.EndpointCategory.GAMMA_API]
    assert FakeHttpClient.instances[0].calls == [(url, {})]
    assert FakeHttpClient.instances[0].timeout == 30.0


async def test_fetch_clob_api_returns_json(rate_limiter):
    url = f"{market_analysis.CLOB_API_URL}/book"
    FakeHttpClient.script = {
        "url": url,
        "params": {"token_id": "tok"},
        "payload": {"bids": [], "asks": []},
    }

    result = await market_analysis._fetch_clob_api("/book", {"token_id": "tok"})

    assert result == {"bids": [], "asks": []}
    # Observed: the CLOB helper acquires the MARKET_DATA category (L-0123).
    assert rate_limiter.acquires == [market_analysis.EndpointCategory.MARKET_DATA]
    assert FakeHttpClient.instances[0].calls == [(url, {"token_id": "tok"})]


async def test_fetch_gamma_api_logs_and_reraises_on_http_error(rate_limiter, caplog):
    url = f"{market_analysis.GAMMA_API_URL}/markets/abc"
    FakeHttpClient.script = {
        "url": url,
        "params": {},
        "payload": None,
        "status_error": _http_status_error(url),
    }

    with pytest.raises(httpx.HTTPStatusError):
        await market_analysis._fetch_gamma_api("/markets/abc")

    assert "Gamma API error for /markets/abc:" in caplog.text
    # The limiter ran before the failing fetch (acquire-first invariant).
    assert rate_limiter.acquires == [market_analysis.EndpointCategory.GAMMA_API]


async def test_fetch_clob_api_logs_and_reraises_on_http_error(rate_limiter, caplog):
    url = f"{market_analysis.CLOB_API_URL}/book"
    FakeHttpClient.script = {
        "url": url,
        "params": {"token_id": "tok"},
        "payload": None,
        "status_error": _http_status_error(url),
    }

    with pytest.raises(httpx.HTTPStatusError):
        await market_analysis._fetch_clob_api("/book", {"token_id": "tok"})

    assert "CLOB API error for /book:" in caplog.text
    assert rate_limiter.acquires == [market_analysis.EndpointCategory.MARKET_DATA]


async def test_fetch_gamma_api_acquires_rate_limit_before_fetch(rate_limiter):
    # No script: the client construction itself fails loud. If the fetch ran
    # before the limiter, the assertion would fire with acquires == [].
    with pytest.raises(AssertionError, match="fail-loud"):
        await market_analysis._fetch_gamma_api("/markets/abc")
    assert rate_limiter.acquires == [market_analysis.EndpointCategory.GAMMA_API]


# ---------------------------------------------------------------------------
# get_market_details identifier fallbacks (market_analysis.py:136-151)
# ---------------------------------------------------------------------------
async def test_get_market_details_falls_back_to_market_id(monkeypatch):
    # slug=None, condition_id=None -> the third identifier fallback. The
    # payload is a plain dict: T-0037 only exercised market_id with LIST
    # payloads, so the non-collapse `return data` path is pinned here.
    gamma = FetchSeam({"/markets/xyz": {"question": "Third fallback?", "id": "xyz"}})
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", gamma)

    details = await market_analysis.get_market_details(market_id="xyz")

    assert details == {"question": "Third fallback?", "id": "xyz"}
    assert gamma.calls == [("/markets/xyz", {})]


async def test_get_market_details_uses_slug_endpoint(monkeypatch):
    # Kills the coverage-dead `if slug:` branch (:138-139).
    gamma = FetchSeam(
        {"/markets/will-x-pass": {"question": "Slug?", "slug": "will-x-pass"}}
    )
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", gamma)

    details = await market_analysis.get_market_details(slug="will-x-pass")

    assert details["question"] == "Slug?"
    assert details["slug"] == "will-x-pass"
    assert gamma.calls == [("/markets/will-x-pass", {})]


# ---------------------------------------------------------------------------
# Error paths with log + re-raise (market_analysis.py:234-236/253/309-311/339-341)
# ---------------------------------------------------------------------------
async def test_get_orderbook_propagates_fetch_error(monkeypatch, caplog):
    clob = FetchSeam(error=RuntimeError("clob offline"))
    monkeypatch.setattr(market_analysis, "_fetch_clob_api", clob)

    with pytest.raises(RuntimeError, match="clob offline"):
        await market_analysis.get_orderbook("tok")

    assert clob.calls == [("/book", {"token_id": "tok"})]
    assert "Failed to get orderbook: clob offline" in caplog.text


async def test_get_spread_raises_value_error_when_prices_missing(monkeypatch, caplog):
    async def bidless(token_id, side="BOTH"):
        return market_analysis.PriceData(token_id=token_id, ask=0.50)

    monkeypatch.setattr(market_analysis, "get_current_price", bidless)
    with pytest.raises(ValueError, match="Could not retrieve both bid and ask prices"):
        await market_analysis.get_spread("tok")
    assert "Failed to get spread: Could not retrieve both bid and ask prices" in caplog.text

    async def askless(token_id, side="BOTH"):
        return market_analysis.PriceData(token_id=token_id, bid=0.40)

    monkeypatch.setattr(market_analysis, "get_current_price", askless)
    with pytest.raises(ValueError, match="Could not retrieve both bid and ask prices"):
        await market_analysis.get_spread("tok")


async def test_get_market_volume_propagates_fetch_error(monkeypatch, caplog):
    async def broken_details(market_id=None, condition_id=None, slug=None):
        raise RuntimeError("gamma down for volume")

    monkeypatch.setattr(market_analysis, "get_market_details", broken_details)

    with pytest.raises(RuntimeError, match="gamma down for volume"):
        await market_analysis.get_market_volume("m-err")

    assert "Failed to get market volume: gamma down for volume" in caplog.text


async def test_get_liquidity_propagates_fetch_error(monkeypatch, caplog):
    gamma = FetchSeam(error=RuntimeError("gamma down for liquidity"))
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", gamma)

    with pytest.raises(RuntimeError, match="gamma down for liquidity"):
        await market_analysis.get_liquidity("m-err")

    # The failure chain: the inner details helper logs first, then liquidity.
    assert "Failed to get market details: gamma down for liquidity" in caplog.text
    assert "Failed to get liquidity: gamma down for liquidity" in caplog.text


# ---------------------------------------------------------------------------
# get_market_volume explicit timeframes (market_analysis.py:291->295)
# ---------------------------------------------------------------------------
async def test_get_market_volume_explicit_timeframes_skips_default(monkeypatch):
    # The false edge of `if timeframes is None:` — the parameter is accepted
    # and never used afterwards (dead parameter, product finding in report).
    payload = {"volume24hr": "15000.5", "volume7d": "90000"}
    gamma = FetchSeam({"/markets/m-tf": payload})
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", gamma)

    volume = await market_analysis.get_market_volume("m-tf", timeframes=["24h", "7d"])

    assert volume.market_id == "m-tf"
    assert volume.volume_24h == pytest.approx(15000.5)
    assert volume.volume_7d == pytest.approx(90000.0)
    assert gamma.calls == [("/markets/m-tf", {})]


# ---------------------------------------------------------------------------
# Placeholders (market_analysis.py:362-388 / 405-421)
# ---------------------------------------------------------------------------
async def test_get_price_history_returns_placeholder_with_default_range(
    frozen_clock, monkeypatch, caplog
):
    # Fail-loud guards: the placeholder path must not fetch anything.
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", FetchSeam())
    monkeypatch.setattr(market_analysis, "_fetch_clob_api", FetchSeam())

    result = await market_analysis.get_price_history("tok")

    assert result == HISTORY_PLACEHOLDER
    # Two utcnow() calls: one for end_date, one for start_dt. The frozen
    # instant makes both deterministic (wall-clock independent, L-0014).
    assert _FrozenDatetime.calls == ["fixed", "fixed"]
    assert _RecordingTimedelta.constructed == [((), {"days": 7})]
    assert "Historical price data not available via public API" in caplog.text
    assert market_analysis._fetch_gamma_api.calls == []
    assert market_analysis._fetch_clob_api.calls == []


async def test_get_price_history_accepts_explicit_dates(frozen_clock, monkeypatch):
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", FetchSeam())
    monkeypatch.setattr(market_analysis, "_fetch_clob_api", FetchSeam())

    result = await market_analysis.get_price_history(
        "tok", start_date="2026-09-01T00:00:00", end_date="2026-09-15T00:00:00"
    )

    assert result == HISTORY_PLACEHOLDER
    # Discriminating pair with the default-range test: explicit dates run
    # NEITHER utcnow() nor the 7-day timedelta construction.
    assert _FrozenDatetime.calls == []
    assert _RecordingTimedelta.constructed == []


async def test_get_price_history_propagates_clock_error(frozen_clock, caplog):
    _FrozenDatetime.mode = "raise"

    with pytest.raises(RuntimeError, match="clock exploded"):
        await market_analysis.get_price_history("tok")

    assert "Failed to get price history: clock exploded" in caplog.text


async def test_get_market_holders_returns_placeholder_with_warning(caplog):
    result = await market_analysis.get_market_holders("m-holders", limit=5)

    assert result == HOLDERS_PLACEHOLDER
    assert "Position holder data requires authenticated access" in caplog.text


async def test_get_market_holders_propagates_logger_error(monkeypatch):
    split = _SplitLogger()
    monkeypatch.setattr(market_analysis, "logger", split)

    with pytest.raises(RuntimeError, match="logger exploded"):
        await market_analysis.get_market_holders("m-holders")

    assert split.errors == ["Failed to get market holders: logger exploded"]


# ---------------------------------------------------------------------------
# analyze_market_opportunity residual branches
# (market_analysis.py:463-464 / 486-487 / 505-508 / 536-538)
# ---------------------------------------------------------------------------
async def test_analyze_market_opportunity_spread_none_when_token_prices_falsy(
    monkeypatch,
):
    # Observed: `if yes_price.bid and yes_price.ask` treats bid=0.0 as
    # missing (falsy) even though ask is truthy — the else sets both spread
    # fields to None (:462-464).
    prices = {
        "tok-yes": market_analysis.PriceData(token_id="tok-yes", bid=0.0, ask=0.5),
        "tok-no": market_analysis.PriceData(
            token_id="tok-no", bid=0.49, ask=0.51, mid=0.5
        ),
    }
    patch_analysis(
        monkeypatch,
        details=two_token_details("Falsy bid?"),
        volume=market_analysis.VolumeData(market_id="m-falsy", volume_24h=5000.0),
        liquidity={"market_id": "m-falsy", "liquidity_usd": 20000.0},
        prices=prices,
    )

    opportunity = await market_analysis.analyze_market_opportunity("m-falsy")

    assert opportunity.spread is None
    assert opportunity.spread_pct is None
    # The yes token's mid was never populated (the fake hands the model back
    # as constructed) — the analysis passes it through unchanged.
    assert opportunity.current_price_yes is None
    assert opportunity.current_price_no == pytest.approx(0.5)
    # Inputs exclude every earlier risk branch: risk low; the recommendation
    # falls to the final HOLD/50 else.
    assert opportunity.risk_assessment == "low"
    assert opportunity.recommendation == "HOLD"
    assert opportunity.confidence_score == 50


async def test_analyze_market_opportunity_high_risk_when_spread_above_five_pct(
    monkeypatch,
):
    # liquidity 20000 (>= 10000) and volume 5000 (>= 1000) exclude the
    # low-liquidity and low-volume branches: the ONLY path to high risk is
    # the spread branch. bid 0.40 / ask 0.50 over mid 0.45 -> ~22.2%.
    prices = {
        "tok-yes": market_analysis.PriceData(
            token_id="tok-yes", bid=0.40, ask=0.50, mid=0.45
        ),
        "tok-no": market_analysis.PriceData(
            token_id="tok-no", bid=0.60, ask=0.70, mid=0.65
        ),
    }
    patch_analysis(
        monkeypatch,
        details=two_token_details("Wide spread?"),
        volume=market_analysis.VolumeData(market_id="m-wide", volume_24h=5000.0),
        liquidity={"market_id": "m-wide", "liquidity_usd": 20000.0},
        prices=prices,
    )

    opportunity = await market_analysis.analyze_market_opportunity("m-wide")

    assert opportunity.risk_assessment == "high"
    assert opportunity.recommendation == "AVOID"
    assert opportunity.confidence_score == 30
    assert opportunity.reasoning == (
        "Risk assessment: High spread. Market conditions not favorable for trading."
    )
    assert abs(opportunity.spread_pct - (0.10 / 0.45 * 100)) < 1e-9


async def test_analyze_market_opportunity_medium_risk_when_volume_below_1000(
    monkeypatch,
):
    # Same liquidity/prices as the low-risk test below; only volume differs
    # (500 vs 5000): the contradictory pair pins that volume < 1000 fires
    # BEFORE the risk-low else (elif order, L-0128e).
    prices = {
        "tok-yes": market_analysis.PriceData(
            token_id="tok-yes", bid=0.49, ask=0.51, mid=0.50
        ),
        "tok-no": market_analysis.PriceData(
            token_id="tok-no", bid=0.51, ask=0.49, mid=0.50
        ),
    }
    patch_analysis(
        monkeypatch,
        details=two_token_details("Quiet book?"),
        volume=market_analysis.VolumeData(market_id="m-quiet", volume_24h=500.0),
        liquidity={"market_id": "m-quiet", "liquidity_usd": 20000.0},
        prices=prices,
    )

    opportunity = await market_analysis.analyze_market_opportunity("m-quiet")

    assert opportunity.risk_assessment == "medium"
    assert opportunity.recommendation == "HOLD"
    assert opportunity.confidence_score == 50


async def test_analyze_market_opportunity_low_risk_with_good_conditions(monkeypatch):
    # liquidity 20000 (>= 10000), spread 4.0% (<= 5), volume 5000 (>= 1000):
    # every earlier risk branch is excluded, so risk falls to "low"
    # (:488-490). The market is not healthy, so the recommendation falls to
    # the HOLD/50 else.
    prices = {
        "tok-yes": market_analysis.PriceData(
            token_id="tok-yes", bid=0.49, ask=0.51, mid=0.50
        ),
        "tok-no": market_analysis.PriceData(
            token_id="tok-no", bid=0.51, ask=0.49, mid=0.50
        ),
    }
    patch_analysis(
        monkeypatch,
        details=two_token_details("Good conditions?"),
        volume=market_analysis.VolumeData(market_id="m-good", volume_24h=5000.0),
        liquidity={"market_id": "m-good", "liquidity_usd": 20000.0},
        prices=prices,
    )

    opportunity = await market_analysis.analyze_market_opportunity("m-good")

    assert opportunity.risk_assessment == "low"
    assert opportunity.recommendation == "HOLD"
    assert opportunity.confidence_score == 50
    assert opportunity.reasoning == HOLD_50_REASONING


async def test_analyze_market_opportunity_falls_back_to_hold_50(monkeypatch):
    # Contract inputs: liquidity 10001-50000, volume 1000-10000, spread >= 2%
    # — excludes AVOID (risk not high), excludes HOLD/70 (not healthy),
    # excludes BUY (spread not < 2) -> the final else fires (:505-508).
    prices = {
        "tok-yes": market_analysis.PriceData(
            token_id="tok-yes", bid=0.4925, ask=0.5075, mid=0.50
        ),
        "tok-no": market_analysis.PriceData(
            token_id="tok-no", bid=0.5075, ask=0.4925, mid=0.50
        ),
    }
    patch_analysis(
        monkeypatch,
        details=two_token_details("Acceptable?"),
        volume=market_analysis.VolumeData(market_id="m-mid", volume_24h=8000.0),
        liquidity={"market_id": "m-mid", "liquidity_usd": 30000.0},
        prices=prices,
    )

    opportunity = await market_analysis.analyze_market_opportunity("m-mid")

    assert opportunity.risk_assessment == "low"
    assert opportunity.recommendation == "HOLD"
    assert opportunity.confidence_score == 50
    assert opportunity.reasoning == HOLD_50_REASONING
    assert abs(opportunity.spread_pct - 3.0) < 1e-9
    assert opportunity.volume_24h == pytest.approx(8000.0)
    assert opportunity.liquidity_usd == pytest.approx(30000.0)
    assert opportunity.price_trend_24h == "stable"


async def test_analyze_market_opportunity_propagates_details_error(
    monkeypatch, caplog
):
    async def broken_details(market_id=None, condition_id=None, slug=None):
        raise RuntimeError("details down")

    monkeypatch.setattr(market_analysis, "get_market_details", broken_details)

    with pytest.raises(RuntimeError, match="details down"):
        await market_analysis.analyze_market_opportunity("m-broken")

    assert "Failed to analyze market opportunity: details down" in caplog.text


# ---------------------------------------------------------------------------
# handle_tool residual routes (market_analysis.py:802-823)
# ---------------------------------------------------------------------------
async def test_handle_tool_routes_get_market_details(monkeypatch):
    calls = []

    async def recorder(**kwargs):
        calls.append(kwargs)
        return {"question": "Routed details?", "marker": "details-raw"}

    monkeypatch.setattr(market_analysis, "get_market_details", recorder)

    contents = await market_analysis.handle_tool("get_market_details", {"market_id": "m1"})

    assert calls == [{"market_id": "m1"}]
    assert contents[0].type == "text"
    # No model_dump on this route: the raw dict passes through verbatim. If
    # a model_dump were added, the dict (no such method) would raise and the
    # error path would return {"error": ...} instead.
    assert json.loads(contents[0].text) == {
        "question": "Routed details?",
        "marker": "details-raw",
    }


async def test_handle_tool_routes_get_orderbook_with_model_dump(monkeypatch):
    calls = []

    async def recorder(**kwargs):
        calls.append(kwargs)
        return _Dumped({"marker": "orderbook-dumped", "token_id": kwargs["token_id"]})

    monkeypatch.setattr(market_analysis, "get_orderbook", recorder)

    contents = await market_analysis.handle_tool(
        "get_orderbook", {"token_id": "tok", "depth": 5}
    )

    assert calls == [{"token_id": "tok", "depth": 5}]
    # The result suffered model_dump(mode="json"): the dumped payload came
    # through as a dict. Without the dump, json.dumps would fail on the
    # non-serializable stand-in and the error path would take over.
    assert json.loads(contents[0].text) == {
        "marker": "orderbook-dumped",
        "token_id": "tok",
    }


async def test_handle_tool_routes_get_spread(monkeypatch):
    calls = []

    async def recorder(**kwargs):
        calls.append(kwargs)
        return {"token_id": kwargs["token_id"], "marker": "spread-raw"}

    monkeypatch.setattr(market_analysis, "get_spread", recorder)

    contents = await market_analysis.handle_tool("get_spread", {"token_id": "tok"})

    assert calls == [{"token_id": "tok"}]
    assert json.loads(contents[0].text) == {
        "token_id": "tok",
        "marker": "spread-raw",
    }


async def test_handle_tool_routes_get_market_volume_with_model_dump(monkeypatch):
    calls = []

    async def recorder(**kwargs):
        calls.append(kwargs)
        return _Dumped({"marker": "volume-dumped", "market_id": kwargs["market_id"]})

    monkeypatch.setattr(market_analysis, "get_market_volume", recorder)

    contents = await market_analysis.handle_tool(
        "get_market_volume", {"market_id": "m1"}
    )

    assert calls == [{"market_id": "m1"}]
    assert json.loads(contents[0].text) == {
        "marker": "volume-dumped",
        "market_id": "m1",
    }


async def test_handle_tool_routes_get_price_history(monkeypatch):
    calls = []

    async def recorder(**kwargs):
        calls.append(kwargs)
        return ["history-payload"]

    monkeypatch.setattr(market_analysis, "get_price_history", recorder)

    contents = await market_analysis.handle_tool(
        "get_price_history",
        {"token_id": "tok", "start_date": "2026-01-01", "end_date": "2026-02-01"},
    )

    assert calls == [
        {"token_id": "tok", "start_date": "2026-01-01", "end_date": "2026-02-01"}
    ]
    # The list result passes through verbatim (no model_dump on this route).
    assert json.loads(contents[0].text) == ["history-payload"]


async def test_handle_tool_routes_get_market_holders(monkeypatch):
    calls = []

    async def recorder(**kwargs):
        calls.append(kwargs)
        return ["holders-payload"]

    monkeypatch.setattr(market_analysis, "get_market_holders", recorder)

    contents = await market_analysis.handle_tool(
        "get_market_holders", {"market_id": "m1", "limit": 5}
    )

    assert calls == [{"market_id": "m1", "limit": 5}]
    assert json.loads(contents[0].text) == ["holders-payload"]


async def test_handle_tool_routes_analyze_market_opportunity_with_model_dump(
    monkeypatch,
):
    calls = []

    async def recorder(**kwargs):
        calls.append(kwargs)
        return _Dumped({"marker": "analysis-dumped", "market_id": kwargs["market_id"]})

    monkeypatch.setattr(market_analysis, "analyze_market_opportunity", recorder)

    contents = await market_analysis.handle_tool(
        "analyze_market_opportunity", {"market_id": "m1"}
    )

    assert calls == [{"market_id": "m1"}]
    assert json.loads(contents[0].text) == {
        "marker": "analysis-dumped",
        "market_id": "m1",
    }
