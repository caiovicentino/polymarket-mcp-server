"""Rate-limiter pass-through at the fetch_all_pages call sites (offline).

T-0399: the T-0357 design (#160) gave ``fetch_all_pages`` opt-in kwargs
``rate_limiter``/``category`` so a 429 on ANY page (first OR follow-ups)
arms backoff via ``_note_http_429`` -- but none of the 8 call sites passed
them, so a 429 on page 2+ armed NOTHING (silent loop against a throttled
wire). This suite pins the wiring at every site:

- Tests 1-8 (recorder-fake, one per call site): ``portfolio.fetch_all_pages``
  (and ``auth.client.fetch_all_pages`` for the client site) is monkeypatched
  with an async recorder that captures kwargs and returns ``[]``; the tool is
  called with house fakes (fail-loud client, recorder limiter, dummy config)
  and the recorder asserts the 2 kwargs are PRESENT: ``rate_limiter`` is not
  None and ``category`` is ``EndpointCategory.DATA_API``. get_pnl_summary
  gets ONE test per fetch site (trades :631, positions :640) -- both calls
  are recorded and each test pins its own call's kwargs.
- Test 9 (behavioral, mechanism pin): a transport fake serves page 1 = 200
  with exactly ``limit`` rows and page 2 = 429 with Retry-After;
  ``fetch_all_pages`` called DIRECTLY with a limiter + DATA_API category
  must arm ``handle_429_error(DATA_API, retry_after)`` on page 2+ (regression
  pin of the merged T-0357 mechanism; GREEN by construction pre-fix -- the
  wiring itself is pinned by tests 1-8).

Isolation mirrors the house suites: autouse fixture clears the module-global
``_portfolio_cache`` before AND after every test; zero network (fakes fail
loud on unrouted seams); zero sleep. Prerequisites: pytest-asyncio auto mode;
offline gate markers; PYTHONPATH=src per P-0019; read_text-free (L-0252).
Lessons: P-0031 (fail-loud stubs), P-0113 (pins of the OBSERVED wiring),
L-0225f (content-anchored asserts), L-0381 (ASCII-only file).
"""
import sys

import pytest

sys.path.insert(0, "src")

from polymarket_mcp.auth import client as client_module  # noqa: E402
from polymarket_mcp.auth.client import PolymarketClient  # noqa: E402
from polymarket_mcp.tools import portfolio  # noqa: E402
from polymarket_mcp.utils.rate_limiter import EndpointCategory  # noqa: E402

ADDRESS = "0xAbCdEf0123456789AbCdEf0123456789aBcDeF01"
POSITIONS_URL = "https://data-api.polymarket.com/positions"
TRADES_URL = "https://data-api.polymarket.com/trades"


class FakeConfig:
    """Config stub: the tools only touch POLYGON_ADDRESS (lowercased)."""

    POLYGON_ADDRESS = ADDRESS


class FakePolyClient:
    """Fail-loud duck-typed client stub (get_balance/get_orders/get_orderbook);
    the empty-result paths of the tools never reach get_orderbook."""

    async def get_balance(self):
        return {"balance": "1000000"}

    async def get_orders(self):
        return []

    async def get_orderbook(self, token_id):
        raise AssertionError(f"unexpected get_orderbook token: {token_id}")


class FakeRateLimiter:
    """Recorder limiter stub: acquire(category) records and returns 0.0."""

    def __init__(self):
        self.categories = []

    async def acquire(self, category):
        self.categories.append(category)
        return 0.0


class Fake429Limiter:
    """Limiter stub for the behavioral mechanism pin: records 429 arming."""

    def __init__(self):
        self.handle_429_calls = []

    async def acquire(self, category):
        raise AssertionError("fetch_all_pages must NOT acquire per page")

    async def handle_429_error(self, category, retry_after):
        self.handle_429_calls.append((category, retry_after))


class ScriptedResponse:
    """Response stub: raise_for_status honors a scripted error (house shape,
    mirrors test_rate_limit_429_portfolio_offline.ScriptedResponse)."""

    def __init__(self, payload=None, status_code=200, retry_after=None,
                 error=None):
        self.status_code = status_code
        self.headers = {"retry-after": retry_after} if retry_after else {}
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        if self._error is not None:
            raise self._error
        return self._payload


class FakeTransport:
    """Fail-loud transport at the httpx seam (house shape of
    test_rate_limit_429_portfolio_offline.FakeHttpClient): serves ONE
    scripted response per fetch; further fetches fail loud."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        assert self._responses, f"unexpected fetch: {url} {params}"
        return self._responses.pop(0)


def install_transport(monkeypatch, transport):
    """Patch the module's httpx seam with a factory (house pattern: the tool
    code builds ``httpx.AsyncClient(...)`` -- a CLASS call -- so the patch
    must be callable)."""

    def factory(*args, **kwargs):
        return transport

    monkeypatch.setattr(portfolio.httpx, "AsyncClient", factory)


def make_recorder(calls):
    """Async recorder standing in for fetch_all_pages: captures kwargs,
    returns [] (the tools' empty-result paths, pinned GREEN in sisters)."""

    async def recorder(client, url, params, *args, **kwargs):
        calls.append({"url": url, "params": params, "kwargs": kwargs})
        return []

    return recorder


@pytest.fixture(autouse=True)
def isolated_portfolio():
    """Per-test isolation: reset the global cache before AND after (house
    rule of test_portfolio_positions_offline)."""
    portfolio._portfolio_cache.clear()
    yield
    portfolio._portfolio_cache.clear()


# --- 1. get_all_positions (portfolio.py cache-miss site) ---------------------


async def test_get_all_positions_passes_limiter_and_category(monkeypatch):
    calls = []
    monkeypatch.setattr(portfolio, "fetch_all_pages", make_recorder(calls))
    install_transport(monkeypatch, FakeTransport([None]))

    texts = await portfolio.get_all_positions(
        None, FakeRateLimiter(), FakeConfig()
    )
    assert "No positions" in texts[0].text  # empty-result path
    assert len(calls) == 1
    assert calls[0]["url"] == POSITIONS_URL
    assert calls[0]["kwargs"]["rate_limiter"] is not None
    assert calls[0]["kwargs"]["category"] is EndpointCategory.DATA_API


# --- 2. get_position_details (positions site) --------------------------------


async def test_get_position_details_passes_limiter_and_category(monkeypatch):
    calls = []
    monkeypatch.setattr(portfolio, "fetch_all_pages", make_recorder(calls))
    install_transport(monkeypatch, FakeTransport([None]))

    texts = await portfolio.get_position_details(
        FakePolyClient(), FakeRateLimiter(), FakeConfig(), market_id="0xm1"
    )
    assert "No position found" in texts[0].text  # empty-result path
    assert len(calls) == 1
    assert calls[0]["kwargs"]["rate_limiter"] is not None
    assert calls[0]["kwargs"]["category"] is EndpointCategory.DATA_API


# --- 3. get_portfolio_value --------------------------------------------------


async def test_get_portfolio_value_passes_limiter_and_category(monkeypatch):
    calls = []
    monkeypatch.setattr(portfolio, "fetch_all_pages", make_recorder(calls))
    install_transport(monkeypatch, FakeTransport([None]))

    texts = await portfolio.get_portfolio_value(
        FakePolyClient(), FakeRateLimiter(), FakeConfig()
    )
    assert texts and texts[0].type == "text"
    assert len(calls) == 1
    assert calls[0]["kwargs"]["rate_limiter"] is not None
    assert calls[0]["kwargs"]["category"] is EndpointCategory.DATA_API


# --- 4+5. get_pnl_summary (ONE test per fetch site) --------------------------


async def test_get_pnl_summary_trades_site_passes_limiter(monkeypatch):
    """Site :631 -- the trades fetch (params carry limit=500)."""
    calls = []
    monkeypatch.setattr(portfolio, "fetch_all_pages", make_recorder(calls))
    install_transport(monkeypatch, FakeTransport([None, None]))

    texts = await portfolio.get_pnl_summary(
        FakePolyClient(), FakeRateLimiter(), FakeConfig(), timeframe="all"
    )
    assert texts and texts[0].type == "text"
    assert len(calls) == 2, "get_pnl_summary must fetch trades AND positions"
    assert calls[0]["url"] == TRADES_URL
    assert calls[0]["kwargs"]["rate_limiter"] is not None
    assert calls[0]["kwargs"]["category"] is EndpointCategory.DATA_API


async def test_get_pnl_summary_positions_site_passes_limiter(monkeypatch):
    """Site :640 -- the positions fetch (second call, no limit)."""
    calls = []
    monkeypatch.setattr(portfolio, "fetch_all_pages", make_recorder(calls))
    install_transport(monkeypatch, FakeTransport([None, None]))

    texts = await portfolio.get_pnl_summary(
        FakePolyClient(), FakeRateLimiter(), FakeConfig(), timeframe="all"
    )
    assert texts and texts[0].type == "text"
    assert len(calls) == 2
    assert calls[1]["url"] == POSITIONS_URL
    assert calls[1]["kwargs"]["rate_limiter"] is not None
    assert calls[1]["kwargs"]["category"] is EndpointCategory.DATA_API


# --- 6. analyze_portfolio_risk -----------------------------------------------


async def test_analyze_portfolio_risk_passes_limiter_and_category(monkeypatch):
    calls = []
    monkeypatch.setattr(portfolio, "fetch_all_pages", make_recorder(calls))
    install_transport(monkeypatch, FakeTransport([None]))

    texts = await portfolio.analyze_portfolio_risk(
        FakePolyClient(), FakeRateLimiter(), FakeConfig()
    )
    assert "No positions to analyze" in texts[0].text  # empty-result path
    assert len(calls) == 1
    assert calls[0]["kwargs"]["rate_limiter"] is not None
    assert calls[0]["kwargs"]["category"] is EndpointCategory.DATA_API


# --- 7. suggest_portfolio_actions --------------------------------------------


async def test_suggest_portfolio_actions_passes_limiter_and_category(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(portfolio, "fetch_all_pages", make_recorder(calls))
    install_transport(monkeypatch, FakeTransport([None]))

    texts = await portfolio.suggest_portfolio_actions(
        FakePolyClient(), FakeRateLimiter(), FakeConfig(), goal="balanced"
    )
    assert "No positions to optimize" in texts[0].text  # empty-result path
    assert len(calls) == 1
    assert calls[0]["kwargs"]["rate_limiter"] is not None
    assert calls[0]["kwargs"]["category"] is EndpointCategory.DATA_API


# --- 8. auth/client.get_positions -------------------------------------------


async def test_client_get_positions_passes_limiter_and_category(monkeypatch):
    calls = []
    monkeypatch.setattr(
        client_module, "fetch_all_pages", make_recorder(calls)
    )
    fake_limiter = FakeRateLimiter()
    monkeypatch.setattr(
        client_module, "get_rate_limiter", lambda: fake_limiter
    )

    def factory(*args, **kwargs):
        return FakeTransport([None])

    monkeypatch.setattr(client_module.httpx, "AsyncClient", factory)

    pmc = PolymarketClient(
        private_key="a" * 64,
        address=ADDRESS,
        api_key="k",
        api_secret="s",
        passphrase="p",
    )
    positions = await pmc.get_positions()
    assert positions == []  # recorder returns the empty list
    assert len(calls) == 1
    assert calls[0]["kwargs"]["rate_limiter"] is fake_limiter
    assert calls[0]["kwargs"]["category"] is EndpointCategory.DATA_API


# --- 9. BEHAVIORAL: 429 on page 2+ arms backoff (mechanism pin) --------------


async def test_429_on_second_page_arms_handle_429_error():
    """The T-0357 mechanism, pinned end-to-end: page 1 is 200 with exactly
    ``limit`` rows, page 2 is 429 with Retry-After -> the limiter armed with
    (DATA_API, retry_after) BEFORE raise_for_status (regression pin; the
    wiring at the call sites is pinned by tests 1-8)."""
    limiter = Fake429Limiter()
    err = RuntimeError("scripted raise_for_status")
    transport = FakeTransport([
        ScriptedResponse(payload=[{"i": 1}, {"i": 2}]),          # full page
        ScriptedResponse(status_code=429, retry_after="2", error=err),
    ])
    from polymarket_mcp.utils.data_api_pagination import fetch_all_pages

    with pytest.raises(RuntimeError):
        await fetch_all_pages(
            transport,
            POSITIONS_URL,
            {"user": "0xabc", "limit": 2},
            rate_limiter=limiter,
            category=EndpointCategory.DATA_API,
        )
    assert len(transport.calls) == 2          # page 1 then page 2
    assert transport.calls[1]["params"]["offset"] == 2  # follow-up offset
    assert limiter.handle_429_calls == [(EndpointCategory.DATA_API, 2)]


# --- 10. ASCII-only self-guard (L-0381 enforcement-in-suite) -----------------


def test_new_suite_is_ascii_only():
    """The NEW file introduces zero non-ASCII bytes (L-0381: the grep-based
    acceptance is whole-file scoped and REDs on pre-existing bullets/PT
    comments in the src files -- this runtime guard is the load-bearing
    enforcement for the NEW file; the src deltas are audited in the report)."""
    with open(__file__, "rb") as f:
        raw = f.read()
    assert max(raw) <= 127, "non-ASCII byte in the new suite file"
