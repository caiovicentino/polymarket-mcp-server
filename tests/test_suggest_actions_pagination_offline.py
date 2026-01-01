"""Paginated /positions fetch inside suggest_portfolio_actions (V-PAG follow-up).

Provenance
----------
T-0273 (P-0139) paginated 7 of the 8 Data-API list sites via
``utils/data_api_pagination.fetch_all_pages`` and declared one follow-up to
the curator: the 8th single-page fetch, the manual GET issued inside
``suggest_portfolio_actions`` (portfolio.py, block "Fetch all positions").
That call requests ``https://data-api.polymarket.com/positions`` WITHOUT a
``limit`` param, so the wire serves the default page of 100 rows, and the
take-profit / stop-loss / concentration suggestions are computed over the
TRUNCATED book -- a wallet with 2,022 positions only ever has its first 100
suggested on (the exact V-PAG class; P-0139(5) follow-up, closed here).

Pre-fix RED (curator probe on dd55223, wire-faithful fake capped at 100
rows/response): PRE-FIX -> 1 call, "Analyzed 100 positions"; POST-FIX ->
2 calls (2nd carries limit=100&offset=100), "Analyzed 102 positions".

Fix under test: the manual GET is replaced by
``fetch_all_pages(client, url, {"user": config.POLYGON_ADDRESS.lower()})``.
Invariants pinned here (P-0139): the FIRST request stays byte-identical
(the helper passes ``params`` untouched and its default ``timeout=10.0``
equals the explicit timeout of the manual GET -- the fake records
``(url, params, timeout)`` and the tuple is identical); follow-up pages
are requested ONLY when the first page is full (short page = one call,
which keeps the sibling pin test_portfolio_analysis_offline.py:600
``len(calls) == 1`` green BY CONSTRUCTION); the no-progress guard stops an
offset-ignoring server after one follow-up (no hang, no duplicated rows).

Suite anatomy (P-0137 self-contained):
- The httpx fake is defined IN THIS FILE (no import from the sibling
  pagination suite), routed by URL suffix with fail-loud AssertionError
  on any unrouted URL (P-0031) -- zero network by construction.
- The fake is wire-faithful: it serves ``universe[offset:offset+100]``
  (the wire default page). The offset-blind variant (test 3) ignores the
  offset and re-serves the same first page -- the pathology the helper's
  no-progress guard protects against.
- Payloads are snake_case, the shape the parsing code reads (L-0020).
- Suggestive loop calls the orderbook fake once per position (102 ->
  102 get_orderbook calls in the fake; zero real network, zero real
  acquires). Known amplification registered NOT optimized here: large
  wallets get slower by design -- the rate limiter paces; batch /books is
  a future enhancement.

Enhancements over the prescribed asserts (declared, L-0025): the suite
additionally pins the first call tuple (byte-identity, P-0139(1)), the
single DATA_API acquire (one acquisition per tool call, P-0139(2)), and
the follow-up call-shape in the no-progress case.

Prerequisites: pytest-asyncio auto mode; runs under the canonical gate
selection ``-m "not integration and not slow and not real_api and not
performance"``; PYTHONPATH=src per P-0019. ASCII-only delta (item 147).
In-process only: no subprocess (L-0316).
"""

import hashlib
from pathlib import Path

import httpx
import pytest

from polymarket_mcp.tools.portfolio import suggest_portfolio_actions
from polymarket_mcp.utils.rate_limiter import EndpointCategory

PORTFOLIO_PY = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "polymarket_mcp"
    / "tools"
    / "portfolio.py"
)

ADDR = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
ADDR_LOWER = "0xabcdef0123456789abcdef0123456789abcdef01"
POSITIONS_URL = "https://data-api.polymarket.com/positions"
PAGE_CAP = 100  # wire default page size (proven live, T-0273 docstring)


# ---------------------------------------------------------------------------
# Synthetic seams (fakes defined IN this file; monkeypatch restores httpx)
# ---------------------------------------------------------------------------
class FakeResponse:
    """Minimal stand-in for httpx.Response as consumed by the fetch path."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def make_data_api_client(calls, universe, offset_blind=False):
    """Build an httpx.AsyncClient replacement wired as the Data API.

    - Every GET is recorded in `calls` as (url, dict(params), timeout) so
      tests can pin the exact call tuple (call-shape pins, P-0139).
    - Only the /positions suffix is routed; any other URL raises
      AssertionError (fail-loud, P-0031 -- no silent fallback to network).
    - Wire-faithful paging: serves universe[offset:offset+PAGE_CAP]. With
      offset_blind=True the offset is IGNORED and every response is
      universe[:PAGE_CAP] (the pathology the no-progress guard stops).
    """

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, params=None, timeout=None):
            params = dict(params or {})
            calls.append((url, params, timeout))
            if not url.endswith("/positions"):
                raise AssertionError(f"unexpected URL routed to stub: {url}")
            offset = int(params.get("offset", 0))
            if offset_blind:
                return FakeResponse(list(universe[:PAGE_CAP]))
            return FakeResponse(list(universe[offset:offset + PAGE_CAP]))

    return _FakeAsyncClient


class FakeRateLimiter:
    """Inert stand-in for RateLimiter: records acquire() categories."""

    def __init__(self):
        self.categories = []

    async def acquire(self, category):
        self.categories.append(category)
        return 0.0


class FakeConfig:
    """Stand-in for PolymarketConfig as consumed by portfolio.py."""

    POLYGON_ADDRESS = ADDR


class FakePolymarketClient:
    """Stand-in for PolymarketClient: only get_orderbook is consumed here.

    books maps token_id -> {"bids": [...], "asks": [...]}; a token without
    a book raises AssertionError (fail-loud, P-0031).
    """

    def __init__(self, books=None):
        self.books = books or {}
        self.orderbook_calls = []

    async def get_orderbook(self, token_id):
        self.orderbook_calls.append(token_id)
        if token_id not in self.books:
            raise AssertionError(f"no synthetic orderbook for token={token_id!r}")
        return self.books[token_id]


# ---------------------------------------------------------------------------
# Payload helpers (snake_case shape the parsing code reads, L-0020)
# ---------------------------------------------------------------------------
def make_position(seq, size=10.0, avg_price=0.5):
    return {
        "size": size,
        "average_price": avg_price,
        "asset_id": f"tok-{seq}",
        "market": f"0xmarket-{seq}",
        "market_question": f"Question {seq}",
        "outcome": "YES",
    }


def make_books(tokens):
    """Flat book per token: mid 0.6, top-5 liquidity 2100 (above thresholds)."""
    levels = [{"price": 0.6, "size": 700.0} for _ in range(5)]
    return {token: {"bids": levels, "asks": levels} for token in tokens}


# ---------------------------------------------------------------------------
# Session tripwire + per-test isolation
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def read_only_tripwire():
    """Fail the session if the suite wrote to the file under test (P-0013)."""
    before = hashlib.sha256(PORTFOLIO_PY.read_bytes()).hexdigest()
    yield
    after = hashlib.sha256(PORTFOLIO_PY.read_bytes()).hexdigest()
    assert before == after, "suite must be read-only; portfolio.py mutated"


@pytest.fixture(autouse=True)
def _clean_portfolio_cache():
    """Isolation: clear the module-level portfolio cache around every test
    (same guard as the sibling pagination suite; nothing in this tool path
    reads it, the clear is cheap insurance against cross-test leakage)."""
    from polymarket_mcp.tools import portfolio

    portfolio._portfolio_cache.clear()
    yield
    portfolio._portfolio_cache.clear()


# ---------------------------------------------------------------------------
# 1. Full first page -> paginate and see ALL positions (the RED case)
# ---------------------------------------------------------------------------
async def test_full_first_page_paginates_and_sees_all_positions(monkeypatch):
    """First response holds 100 rows (full page) and a 2-row second page
    follows: the tool must paginate (2 calls; the 2nd carries
    limit=100&offset=100) and analyze ALL 102 positions.

    Pre-fix RED: exactly 1 call and "Analyzed 100 positions" -- the
    truncation this slice closes."""
    universe = [make_position(i) for i in range(102)]
    calls = []
    monkeypatch.setattr(httpx, "AsyncClient", make_data_api_client(calls, universe))
    client = FakePolymarketClient(books=make_books([f"tok-{i}" for i in range(102)]))
    limiter = FakeRateLimiter()
    config = FakeConfig()

    result = await suggest_portfolio_actions(client, limiter, config)

    assert len(calls) == 2
    # First request byte-identical to the pre-fix GET (P-0139(1)).
    assert calls[0] == (POSITIONS_URL, {"user": ADDR_LOWER}, 10.0)
    # Follow-up request: explicit page size and offset (P-0139 pagination).
    assert calls[1][0] == POSITIONS_URL
    assert calls[1][1] == {"user": ADDR_LOWER, "limit": 100, "offset": 100}
    # One acquire per tool call: pages are fetched inside the already
    # acquired DATA_API window (helper docstring / P-0139(2)).
    assert limiter.categories.count(EndpointCategory.DATA_API) == 1
    text = result[0].text
    assert "Analyzed 102 positions" in text


# ---------------------------------------------------------------------------
# 2. Short first page -> exactly ONE byte-identical call (compat fast-path)
# ---------------------------------------------------------------------------
async def test_short_first_page_makes_single_byte_identical_call(monkeypatch):
    """A short first page (2 rows < cap) is complete: exactly ONE call, and
    the recorded tuple is byte-identical to the pre-fix GET: url, params
    untouched (no limit/offset keys), timeout 10.0. The sibling pin
    test_portfolio_analysis_offline.py:600 ``len(calls) == 1`` (empty case)
    holds by construction (short page = no follow-up)."""
    universe = [make_position(0), make_position(1)]
    calls = []
    monkeypatch.setattr(httpx, "AsyncClient", make_data_api_client(calls, universe))
    client = FakePolymarketClient(books=make_books(["tok-0", "tok-1"]))
    limiter = FakeRateLimiter()
    config = FakeConfig()

    result = await suggest_portfolio_actions(client, limiter, config)

    assert len(calls) == 1
    assert calls[0] == (POSITIONS_URL, {"user": ADDR_LOWER}, 10.0)
    assert result[0].text.startswith("Portfolio Optimization Suggestions")


# ---------------------------------------------------------------------------
# 3. No-progress guard: offset-ignoring server stops after one follow-up
# ---------------------------------------------------------------------------
async def test_no_progress_guard_stops_on_repeated_page(monkeypatch):
    """First page full (100 rows, first row R) and the follow-up serves the
    SAME page again (offset ignored): the helper's no-progress guard stops
    the loop after exactly 2 calls, the repeated page is NOT appended
    (text stays "Analyzed 100 positions" -- 200 would mean duplication)
    and the call terminates (no hang)."""
    universe = [make_position(i) for i in range(100)]
    calls = []
    monkeypatch.setattr(
        httpx, "AsyncClient", make_data_api_client(calls, universe, offset_blind=True)
    )
    client = FakePolymarketClient(books=make_books([f"tok-{i}" for i in range(100)]))
    limiter = FakeRateLimiter()
    config = FakeConfig()

    result = await suggest_portfolio_actions(client, limiter, config)

    assert len(calls) == 2
    assert calls[1][1] == {"user": ADDR_LOWER, "limit": 100, "offset": 100}
    assert "Analyzed 100 positions" in result[0].text


# ---------------------------------------------------------------------------
# 4. Empty book -> one call, unchanged message (sibling pin permanence)
# ---------------------------------------------------------------------------
async def test_empty_positions_single_call_unchanged(monkeypatch):
    """/positions serving [] -> exactly ONE call and the unchanged
    "No positions to optimize." message (sibling pin permanence)."""
    calls = []
    monkeypatch.setattr(httpx, "AsyncClient", make_data_api_client(calls, []))
    limiter = FakeRateLimiter()
    config = FakeConfig()

    result = await suggest_portfolio_actions(FakePolymarketClient(), limiter, config)

    assert len(calls) == 1
    assert calls[0] == (POSITIONS_URL, {"user": ADDR_LOWER}, 10.0)
    assert result[0].text == "No positions to optimize."
