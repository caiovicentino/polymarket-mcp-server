"""
Adversarial security audit suite for the Polymarket MCP safety layer (T-0045,
issue #41). Every candidate bypass vector below is resolved by machine evidence:
a CONFIRMED bypass is an xfail(strict=True) whose body asserts the SAFE behavior
(the assertion fails against the current code = proof of the bypass), a REFUTED
vector is a positive test pinning the safe behavior actually observed. An xfail
that stops failing (XPASS with strict=True) turns the suite RED - fabricated
findings cannot survive this mechanism.

Sources of truth (audit-only - code is read, never modified):
- src/polymarket_mcp/utils/safety_limits.py: validate_order :97-189,
  per-market cap matching :146-168, liquidity floor :171, confirmation gate
  :215-236, _calculate_total_exposure :283-285.
- src/polymarket_mcp/tools/trading.py: create_limit_order :103-296 (param
  validation :139-155, size->shares conversion :192, confirmation gate
  :213-246, post_order :254-261), create_batch_orders :374-461,
  execute_smart_trade :893-1055 (split legs :964-1003), rebalance_position
  :1057-1191, resolve_token_id :25-77, _convert_positions :1195-1217.
- src/polymarket_mcp/config.py: DEMO_MODE :25-28, safety-limit fields :63-100
  (no ge/gt constraints), has_api_credentials :201-207.
- src/polymarket_mcp/server.py: list_tools :110-144, call_tool router :243-343
  (portfolio route :270-280 runs BEFORE the trading gate :292; error_result
  echo :330-343), initialize_server :346-444 (L2 auto-create :380-398, trading
  tools init :408-418).
- src/polymarket_mcp/auth/client.py: constructor accepts any key offline
  :36-90, create_api_credentials :129-166 (network step), get_positions
  credential gate :420-421, has_api_credentials :471-473.

Lessons applied: L-0002/L-0067 (semantic asserts, no fragile counts), L-0009
(doc claims judged by accuracy against code with file:line), L-0010/L-0022
(acceptance run from the worktree root), L-0014/L-0016/L-0082 (mutation only in
a temp-dir shadow copy, statement substitution preserved), L-0020/L-0090
(asserts follow observed code, divergences cited), L-0030/L-0064 (shadowing
proven via module.__file__), P-0029 (hermeticity proven by the env -i
acceptance run), P-0031 (offline suite anatomy, fail-loud module-seam fakes).

Hermeticity: zero network. Every client below is a duck-typed recording fake -
calling any method that is not faked raises AttributeError loudly (no silent
fallback to the real client), and the only real-world objects constructed
(PolymarketClient with the public demo key, the server module in its
pre-initialize state) never perform I/O in these tests. Fakes are defined in
this file only (house rule: never import fakes from another test module).
Boundary notes are documented per-test and consolidated in
docs/security-audit-T-0045.md.
"""
import asyncio
import inspect
import json
import math
import re

import pytest
from pydantic import ValidationError

import polymarket_mcp.config as config_module
import polymarket_mcp.server as server_module
import polymarket_mcp.tools.trading as trading_module
import polymarket_mcp.utils.safety_limits as safety_limits_module
from polymarket_mcp.auth.client import PolymarketClient
from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.tools import (
    market_analysis,
    market_discovery,
    portfolio_integration,
    realtime,
)
from polymarket_mcp.tools.trading import TradingTools, get_tool_definitions, resolve_token_id
from polymarket_mcp.utils import create_safety_limits_from_config
from polymarket_mcp.utils.safety_limits import MarketData, OrderRequest, Position, SafetyLimits

# Public demo constants substituted by config.py:139-141/:168-170 in DEMO_MODE.
DEMO_PRIVATE_KEY = "0" * 63 + "1"
DEMO_ADDRESS = "0x" + "0" * 39 + "1"


class FakeConfig:
    """Minimal stand-in for PolymarketConfig (confirmation-gate knobs only)."""

    def __init__(self, autonomous: bool = True, threshold: float = 1_000_000_000.0):
        self.ENABLE_AUTONOMOUS_TRADING = autonomous
        self.REQUIRE_CONFIRMATION_ABOVE_USD = threshold


class FakeLimiter:
    """No-op rate limiter: the real singleton sleeps between calls (L-0014)."""

    async def acquire(self, category):
        return 0.0


class RecordingClient:
    """Duck-typed client that records every trading-relevant call.

    Any call to a method that is not defined here raises AttributeError loudly:
    a safety regression that reaches for an unfaked network endpoint fails the
    test instead of silently hitting the real API (P-0031 fail-loud seam).
    """

    def __init__(self):
        self.posted = []  # kwargs received by post_order
        self.get_market_calls = 0
        self.get_positions_calls = 0
        self.positions = []  # raw position dicts served to get_positions
        self.book = {
            "bids": [{"price": "0.49", "size": "100000"}],
            "asks": [{"price": "0.51", "size": "100000"}],
        }

    async def get_market(self, market_id):
        self.get_market_calls += 1
        return {
            "tokens": [
                {"token_id": "yes-token", "outcome": "Yes"},
                {"token_id": "no-token", "outcome": "No"},
            ],
            "volume": "1000000",
        }

    async def get_orderbook(self, token_id):
        return self.book

    async def get_positions(self):
        self.get_positions_calls += 1
        return self.positions

    async def post_order(self, **kwargs):
        self.posted.append(kwargs)
        return {"orderID": "order-1", "status": "submitted"}


class ConcurrentPositionsClient(RecordingClient):
    """Fake whose get_positions only returns once BOTH concurrent callers
    fetched - a deterministic model of two tool calls that validate against the
    same pre-trade exposure snapshot (no sleeps, no wall-clock timing).

    DEADLOCK GUARD: use this client ONLY for the concurrency test; a single
    order would wait forever for a second fetch that never comes.
    """

    def __init__(self):
        super().__init__()
        self.fetch_count = 0
        self.release = asyncio.Event()

    async def get_positions(self):
        self.fetch_count += 1
        if self.fetch_count >= 2:
            self.release.set()
        await self.release.wait()
        return self.positions


def build_limits(
    max_order_size_usd: float = 100_000.0,
    max_total_exposure_usd: float = 1_000_000.0,
    max_position_size_per_market: float = 100_000.0,
    min_liquidity_required: float = 0.0,
    max_spread_tolerance: float = 1.0,
    threshold: float = 1_000_000_000.0,
):
    """Real SafetyLimits with wide defaults so single tests can tighten one knob."""
    return SafetyLimits(
        max_order_size_usd=max_order_size_usd,
        max_total_exposure_usd=max_total_exposure_usd,
        max_position_size_per_market=max_position_size_per_market,
        min_liquidity_required=min_liquidity_required,
        max_spread_tolerance=max_spread_tolerance,
        require_confirmation_above_usd=threshold,
    )


def build_tools(**kwargs):
    """Real TradingTools over the recording fake (autonomous=True: gate off)."""
    client = RecordingClient()
    tools = TradingTools(client, build_limits(**kwargs), FakeConfig())
    tools.rate_limiter = FakeLimiter()
    return tools, client


def demo_config() -> PolymarketConfig:
    """PolymarketConfig in DEMO_MODE with no L2 credentials.

    Explicit None kwargs outrank the process env (pydantic-settings precedence),
    so has_api_credentials() is deterministic under both acceptance environments.
    """
    return PolymarketConfig(
        DEMO_MODE=True,
        POLYMARKET_API_KEY=None,
        POLYMARKET_API_SECRET=None,
        POLYMARKET_PASSPHRASE=None,
        POLYMARKET_API_KEY_NAME=None,
    )


# =====================================================================
# Zone A - numeric limits (validate_order + tool entry)
# =====================================================================


@pytest.mark.xfail(
    strict=True,
    reason="SEC-ADVR-A1: NaN size passes every guard and reaches post_order",
)
async def test_nan_size_bypasses_all_limits_and_reaches_post_order():
    """SEC-ADVR-A1: size=NaN defeats every numeric safety comparison.

    trading.py:143 `if size <= 0:` is False for NaN, so the order enters the
    flow; safety_limits.py:117/:139/:164 compare NaN > limit which is always
    False, so every cap is skipped; :236 NaN > threshold skips the confirmation
    gate. The safe behavior (order rejected, nothing posted) is asserted and
    fails against the current code. Reachability precondition (not asserted
    here): the MCP transport may deliver NaN because Python's json.loads
    accepts NaN literals by default; the proof here covers the tool-layer
    frontier (see docs/security-audit-T-0045.md, section Findings).
    """
    tools, client = build_tools(max_order_size_usd=100.0)

    result = await tools.create_limit_order("m1", "BUY", 0.5, float("nan"))

    assert not result.get("success"), (
        f"SEC-ADVR-A1 bypass reproduced: NaN order was accepted and posted: "
        f"result={result!r} posted={client.posted!r}"
    )
    assert client.posted == [], "a NaN-sized order must never reach the exchange"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SEC-ADVR-A2: per-market cap matches market_id by exact string; a "
        "format-divergent position id makes the cap blind"
    ),
)
async def test_per_market_cap_bypassed_by_position_market_id_format_mismatch():
    """SEC-ADVR-A2: the per-market cap is bypassed by id-format divergence.

    safety_limits.py:147-150 filters positions with p.market_id == order.market_id
    (exact string equality, no normalization). A position held in the same
    logical market under a different id format is invisible to the cap: with
    matching formats the order below is rejected (450 + 100 = 550 > 500), with
    divergent formats it is accepted. _convert_positions (trading.py:1206) maps
    the upstream 'market' field verbatim while rebalance_position:1087 matches
    EITHER 'market' or 'condition_id' - evidence that both formats circulate.
    Reachability precondition (honest, not asserted): whether the live Data API
    returns 'market' values in the same format as the caller's market_id is not
    provable offline; the matching semantics are the machine-verified part.
    """
    limits = build_limits(max_position_size_per_market=500.0)
    positions = [
        Position(
            token_id="tok-held",
            market_id="0xcondition-id-format",
            size=900.0,
            avg_price=0.5,
            current_price=0.5,
            unrealized_pnl=0.0,
        )
    ]
    order = OrderRequest(token_id="tok-new", price=0.5, size=200.0, side="BUY", market_id="m1-slug")
    market_data = MarketData("m1-slug", "tok-new", 0.49, 0.51, 1_000_000.0, 1_000_000.0, 1_000_000.0)

    ok, error = limits.validate_order(order, positions, market_data)

    assert not ok, (
        f"SEC-ADVR-A2 bypass reproduced: format-divergent position invisible to the "
        f"per-market cap (ok={ok}, error={error!r}); the same order against the "
        f"matching format is rejected (market exposure 550 > 500)"
    )


async def test_side_padded_whitespace_is_rejected():
    """SEC-ADVR-A3 (refuted): side matching is exact after .upper() - padded
    input cannot pass. Pinned before any market fetch (fail-closed)."""
    tools, client = build_tools()

    result = await tools.create_limit_order("m1", " buy ", 0.5, 10.0)

    assert result["success"] is False
    assert result["error"] == "Side must be BUY or SELL, got  BUY "
    assert client.posted == []
    assert client.get_market_calls == 0, "rejection must happen before any fetch"


async def test_side_spaced_letters_are_rejected():
    """SEC-ADVR-A3 (refuted): spaced letters ('B U Y') never normalize to a
    valid side - the allow-list is exact equality, so this class is N/A."""
    tools, client = build_tools()

    result = await tools.create_limit_order("m1", "B U Y", 0.5, 10.0)

    assert result["success"] is False
    assert result["error"] == "Side must be BUY or SELL, got B U Y"
    assert client.posted == []


async def test_side_cyrillic_confusable_is_rejected():
    """SEC-ADVR-A3 (refuted): the Cyrillic homoglyph of 'B' (U+0412) is a
    distinct string from Latin 'B' - confusable unicode cannot pass the
    exact-match allow-list."""
    tools, client = build_tools()

    result = await tools.create_limit_order("m1", "ВUY", 0.5, 10.0)

    assert result["success"] is False
    assert result["error"] == "Side must be BUY or SELL, got ВUY"
    assert client.posted == []


# =====================================================================
# Zone B - confirmation gate and multi-leg orders
# =====================================================================


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SEC-ADVR-B1: batch legs each validate against filled positions only; "
        "in-flight orders ratchet exposure past the cap"
    ),
)
async def test_batch_orders_ratchet_exposure_past_total_cap():
    """SEC-ADVR-B1: create_batch_orders re-validates each leg via
    create_limit_order (trading.py:404-415), which reads get_positions()
    (trading.py:188) - the FILLED positions only. A resting (unfilled) limit
    order never appears there, so N legs each under max_order_size stack
    exposure far above max_total_exposure_usd. The fake models positions that
    do not include the in-flight first leg, matching real semantics for
    unfilled resting orders; the same mechanism drives execute_smart_trade's
    split legs (trading.py:985-1003) and rebalance_position (:1148).
    """
    tools, client = build_tools(max_order_size_usd=1000.0, max_total_exposure_usd=1000.0)
    client.positions = []

    batch = await tools.create_batch_orders(
        [
            {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 800.0},
            {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 800.0},
        ]
    )

    assert len(client.posted) <= 1, (
        f"SEC-ADVR-B1 ratchet reproduced: both legs posted, combined exposure "
        f"$1600 > cap $1000; batch summary: "
        f"successful={batch['successful']} posted={client.posted!r}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SEC-ADVR-B1: smart-trade split legs each validate against filled "
        "positions only; in-flight orders ratchet exposure past the cap"
    ),
)
async def test_smart_trade_split_orders_ratchet_exposure_past_cap():
    """SEC-ADVR-B1 (second repro, different caller): execute_smart_trade splits
    a budget into legs when fill_probability <= 0.8 (trading.py:964-979, mid
    strategy -> 0.7) and runs each leg through create_limit_order
    (:995-1003). Each leg is individually under max_order_size, none sees the
    in-flight siblings, and the combined exposure exceeds the total cap."""
    tools, client = build_tools(max_order_size_usd=1000.0, max_total_exposure_usd=1000.0)
    client.positions = []

    result = await tools.execute_smart_trade("m1", "buy yes at a fair price", 1200.0, confirm=True)

    assert len(client.posted) <= 1, (
        f"SEC-ADVR-B1 ratchet reproduced via smart-trade split: "
        f"{len(client.posted)} legs posted, combined exposure $1200 > cap "
        f"$1000; plan={result.get('execution_plan')!r} posted={client.posted!r}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SEC-ADVR-B2: two concurrent orders both validate against the same "
        "pre-trade exposure snapshot (TOCTOU)"
    ),
)
async def test_concurrent_orders_both_validate_stale_exposure_snapshot():
    """SEC-ADVR-B2: no serialization between tool calls - positions are fetched
    per call (trading.py:188, :~192 `await self.client.get_positions()`) and no
    lock exists in the module, so two concurrent create_limit_order calls both
    validate against the same snapshot and both post. The deterministic fake
    guarantees both get_positions calls complete before any post_order (no
    sleeps). Precondition (not asserted): the MCP client may parallelize tool
    calls; the server does not impose serialization (observation in the audit
    doc, not machine-verified)."""
    client = ConcurrentPositionsClient()
    tools = TradingTools(client, build_limits(max_order_size_usd=1000.0, max_total_exposure_usd=1000.0), FakeConfig())
    tools.rate_limiter = FakeLimiter()

    first, second = await asyncio.gather(
        tools.create_limit_order("m1", "BUY", 0.5, 800.0),
        tools.create_limit_order("m1", "BUY", 0.5, 800.0),
    )

    assert len(client.posted) <= 1, (
        f"SEC-ADVR-B2 TOCTOU reproduced: {client.fetch_count} concurrent "
        f"get_positions calls completed before any post_order; both orders "
        f"accepted (success={first.get('success')}/{second.get('success')}), "
        f"combined exposure $1600 > cap $1000: {client.posted!r}"
    )


# =====================================================================
# Zone C - tool-call scope and claims-vs-code
# =====================================================================


def test_demo_config_reports_no_credentials():
    """SEC-ADVR-C1 (link A, refuted-safe): a DEMO_MODE config without L2 vars
    reports has_api_credentials()=False - which is exactly what drives
    server.py:381 into the L2 auto-creation branch (server.py:380-398, no
    DEMO_MODE check anywhere in initialize_server)."""
    config = demo_config()

    assert config.has_api_credentials() is False
    assert config.POLYGON_PRIVATE_KEY == DEMO_PRIVATE_KEY
    assert config.POLYGON_ADDRESS == DEMO_ADDRESS
    assert config.POLYMARKET_CHAIN_ID == 137, "demo wiring targets mainnet chain by default"


def test_real_client_accepts_demo_key_offline():
    """SEC-ADVR-C1 (link B, refuted-safe): PolymarketClient is constructed with
    the public demo key without any DEMO_MODE gate at the client layer; the
    order signer derives from that key. This link is offline-provable (the
    constructor performs no I/O); the auto-creation of L2 credentials
    (client.py:129-166) is a network step and stays a documented precondition,
    never asserted here."""
    client = PolymarketClient(private_key=DEMO_PRIVATE_KEY, address=DEMO_ADDRESS, chain_id=137)

    assert client.private_key == DEMO_PRIVATE_KEY
    assert client.address == DEMO_ADDRESS
    assert client.api_creds is None
    assert client.has_api_credentials() is False
    assert client.signer is not None
    assert client.get_chain_id() == 137


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SEC-ADVR-C1: DEMO_MODE never gates trading - the tool layer accepts a "
        "demo config and places the order"
    ),
)
async def test_demo_mode_config_still_places_orders_with_confirm():
    """SEC-ADVR-C1: config.py:25-28 documents DEMO_MODE as 'read-only, no
    trading', but no line of trading.py or server.py consults config.DEMO_MODE
    (verified by grep, see the audit doc). The only guards are incidental:
    credential availability and the consultive confirmation gate. With
    confirm=True the order proceeds under the demo config - the safe behavior
    ('demo mode refuses to trade') is asserted and fails."""
    config = demo_config()
    tools = TradingTools(RecordingClient(), create_safety_limits_from_config(config), config)
    tools.rate_limiter = FakeLimiter()

    result = await tools.create_limit_order("m1", "BUY", 0.5, 10.0, confirm=True)

    assert not result.get("success"), (
        f"SEC-ADVR-C1 bypass reproduced: a DEMO_MODE config traded through the "
        f"tool layer: result={result!r} posted={tools.client.posted!r}"
    )


async def test_unknown_tool_returns_fail_closed_error():
    """SEC-ADVR-C2 (refuted): an unknown tool name fails closed with a JSON
    error result (server.py:318 -> except :330). The error carries the echoed
    arguments (reflected caller input - documented observation, not a leak of
    new information) and no stack trace or filesystem path."""
    contents = await server_module.call_tool("definitely_not_a_tool", {"x": 1})

    payload = json.loads(contents[0].text)
    assert payload["success"] is False
    assert payload["error"] == "Unknown tool: definitely_not_a_tool"
    assert payload["tool"] == "definitely_not_a_tool"
    assert payload["arguments"] == {"x": 1}
    assert "\\" not in contents[0].text, "no filesystem paths in the error body"


async def test_trading_route_fail_closed_without_tools():
    """SEC-ADVR-C2 (refuted): with trading_tools=None (no API credentials) the
    trading route falls through to 'Unknown tool' - fail-closed (server.py:292,
    :327-328)."""
    contents = await server_module.call_tool(
        "create_limit_order",
        {"market_id": "m1", "side": "BUY", "price": 0.5, "size": 10.0},
    )

    payload = json.loads(contents[0].text)
    assert payload["success"] is False
    assert payload["error"] == "Unknown tool: create_limit_order"
    assert payload["tool"] == "create_limit_order"


async def test_portfolio_route_fails_closed_preinit(monkeypatch):
    """SEC-ADVR-C2 (refuted with observation): the portfolio route
    (server.py:270-280) runs BEFORE the trading gate (:292) and is reachable
    with polymarket_client=None and config=None (pre-initialize state). The
    handler catches the AttributeError internally (portfolio.py:209-212) and
    returns a plain-text failure - fail-closed, no crash, no path leak. The
    unprotected-route aspect (reachable regardless of credentials) is a P3
    observation recorded in the audit doc, not machine-verifiable further
    offline because the live path performs a direct data-api HTTP call
    (portfolio.py:86-97) which these tests never trigger. The pre-init state
    is pinned explicitly: initialize_server() (test_e2e.py, collected before
    this file in the same pytest process under the CI selection
    -m "not real_api") persists module-level globals and made this test
    order-dependent (CI run 35044525737 hit an initialized server - a state
    this test does not exercise). monkeypatch restores the globals at
    teardown, so no state leaks either way."""
    monkeypatch.setattr(server_module, "polymarket_client", None)
    monkeypatch.setattr(server_module, "config", None)

    contents = await server_module.call_tool("get_all_positions", {})

    assert "Error fetching positions" in contents[0].text


async def test_list_tools_preauth_excludes_trading_and_portfolio():
    """SEC-ADVR-C2 (refuted): before initialize_server, list_tools() excludes
    every trading and portfolio tool (server.py:130-139) - the advertised
    surface is 25 tools, matching server.py:439's own claim."""
    names = {tool.name for tool in await server_module.list_tools()}

    assert "create_limit_order" not in names
    assert "get_all_positions" not in names
    public = {
        tool.name for tool in market_discovery.get_tools()
    } | {tool.name for tool in market_analysis.get_tools()}
    public |= {tool.name for tool in realtime.get_tools()}
    assert names == public, "pre-auth surface must be exactly discovery+analysis+realtime"
    assert len(names) == 25, "server.py:439 claims '25 total (8 Discovery, 10 Analysis, 7 Real-time)'"


def test_readme_tool_count_claim_matches_definitions():
    """SEC-ADVR-C2 (claim verified, L-0009): README:10 claims '45 comprehensive
    tools' and server.py:436 claims '45 total (8 Discovery, 10 Analysis, 12
    Trading, 8 Portfolio, 7 Real-time)'. The real definition counts match both
    claims exactly."""
    counts = {
        "discovery": len(market_discovery.get_tools()),
        "analysis": len(market_analysis.get_tools()),
        "trading": len(get_tool_definitions()),
        "portfolio": len(portfolio_integration.get_portfolio_tool_definitions()),
        "realtime": len(realtime.get_tools()),
    }

    assert counts == {"discovery": 8, "analysis": 10, "trading": 12, "portfolio": 8, "realtime": 7}
    assert sum(counts.values()) == 45


def test_all_defined_tools_are_routed():
    """SEC-ADVR-C2 (refuted): every tool name that appears in a definition
    list is dispatchable through call_tool - no defined-but-unrouted tool
    (which would silently hide a tool from the MCP surface)."""
    defined = set()
    for definitions in (
        market_discovery.get_tools(),
        market_analysis.get_tools(),
        get_tool_definitions(),
        portfolio_integration.get_portfolio_tool_definitions(),
        realtime.get_tools(),
    ):
        defined.update(tool.name for tool in definitions)

    router_source = inspect.getsource(server_module.call_tool)
    routed = set(re.findall(r'"([a-z_0-9]+)"', router_source))
    unrouted = defined - routed

    assert not unrouted, f"defined but unrouted tools: {sorted(unrouted)}"


# =====================================================================
# Zone D - config edges and attack-class applicability
# =====================================================================


async def test_nonpositive_min_liquidity_disables_liquidity_floor():
    """SEC-ADVR-D1 (observed fail-open, pinned as mechanism evidence):
    MIN_LIQUIDITY_REQUIRED <= 0 makes the floor check (safety_limits.py:171,
    `total_liquidity < min`) never fire - a $2-liquidity market passes. A fix
    that validates limits at config level must update this test in the same
    change (L-0073)."""
    limits = build_limits(min_liquidity_required=-1.0)
    illiquid = MarketData("m1", "tok", 0.49, 0.51, 1.0, 1.0, 1.0)

    ok, error = limits.validate_order(OrderRequest("tok", 0.5, 4.0, "BUY", "m1"), [], illiquid)

    assert (ok, error) == (True, None), "observed: non-positive floor disables the liquidity check"


async def test_infinite_order_cap_disables_size_limit():
    """SEC-ADVR-D1 (observed fail-open, pinned as mechanism evidence):
    max_order_size_usd=inf never rejects (x > inf is always False)."""
    limits = build_limits(
        max_order_size_usd=float("inf"),
        max_total_exposure_usd=float("inf"),
        max_position_size_per_market=float("inf"),
    )
    illiquid = MarketData("m1", "tok", 0.49, 0.51, 1.0, 1.0, 1.0)

    ok, error = limits.validate_order(OrderRequest("tok", 0.5, 2_000_000_000.0, "BUY", "m1"), [], illiquid)

    assert (ok, error) == (True, None), "observed: an infinite cap disables the order-size limit"


async def test_negative_max_order_size_fails_closed():
    """SEC-ADVR-D1 (observed fail-closed): negative size/exposure/market caps
    reject every order - the safe direction (denial of service, not bypass)."""
    limits = build_limits(max_order_size_usd=-1.0)
    illiquid = MarketData("m1", "tok", 0.49, 0.51, 1.0, 1.0, 1.0)

    ok, error = limits.validate_order(OrderRequest("tok", 0.5, 400.0, "BUY", "m1"), [], illiquid)

    assert ok is False
    assert "exceeds maximum" in error


async def test_nonpositive_confirmation_threshold_gates_all_orders():
    """SEC-ADVR-D1 (observed fail-closed): require_confirmation_above_usd <= 0
    puts every order above the gate - safe direction (stricter, not looser)."""
    limits = build_limits(threshold=-1.0)

    assert limits.should_require_confirmation(OrderRequest("tok", 0.5, 1.0, "BUY", "m1")) is True


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SEC-ADVR-D1: config accepts non-positive and infinite limit values "
        "that silently disable safety checks (no ge/gt constraints)"
    ),
)
async def test_config_accepts_limits_that_disable_safety():
    """SEC-ADVR-D1: config.py:63-100 defines the safety-limit fields without
    any numeric constraint (the only constrained field is MAX_SPREAD_TOLERANCE,
    config.py:183-188). A non-positive MIN_LIQUIDITY_REQUIRED is accepted and
    silently disables the liquidity floor (safety_limits.py:171 never fires).
    The safe behavior (config rejects it) is asserted and fails."""
    with pytest.raises(ValidationError):
        PolymarketConfig(DEMO_MODE=True, MIN_LIQUIDITY_REQUIRED=-1.0)


async def test_token_id_matching_is_exact_not_prefix():
    """SEC-ADVR-D2 (refuted): resolve_token_id matches exact casefold equality
    (trading.py:54) - prefix and substring never match; confusable unicode is
    a distinct string. The issue's quote-splitting class has no regex surface
    here to attack (see the tripwire test below)."""
    market = {
        "tokens": [
            {"token_id": "t1", "outcome": "Yes"},
            {"token_id": "t2", "outcome": "No"},
        ]
    }

    with pytest.raises(ValueError) as excinfo:
        resolve_token_id(market, "YESX", "m1")
    assert "not found in market" in str(excinfo.value)

    with pytest.raises(ValueError):
        resolve_token_id(market, "Ye s", "m1")

    confusable = {
        "tokens": [
            {"token_id": "t1", "outcome": "Вuy"},
            {"token_id": "t2", "outcome": "Buy"},
        ]
    }
    token_id, label = resolve_token_id(confusable, "Buy", "m1")
    assert (token_id, label) == ("t2", "Buy"), "Cyrillic confusable must not match Latin 'Buy'"


async def test_token_id_strips_then_exact_matches():
    """SEC-ADVR-D2 (observed): outcome input is stripped then casefold-matched
    exactly (trading.py:50-53) - padded input is tolerated, not exploited, and
    still never fuzzy-matches."""
    market = {
        "tokens": [
            {"token_id": "t1", "outcome": "Yes"},
            {"token_id": "t2", "outcome": "No"},
        ]
    }

    token_id, label = resolve_token_id(market, " yes ", "m1")
    assert (token_id, label) == ("t1", "Yes")


def test_no_regex_input_validation_in_safety_layer():
    """SEC-ADVR-D2 (tripwire): the safety-relevant modules contain no
    regex-based input validation (the grep evidence is recorded in
    docs/security-audit-T-0045.md). The issue's quote-splitting deny/allow-list
    class has no surface here today. If regex validation is ever added to these
    modules, this fails loudly and the audit doc must be revisited for the
    quote-splitting vectors."""
    for module in (safety_limits_module, trading_module, config_module):
        source = inspect.getsource(module)
        for pattern in ("re.compile(", "re.match(", "re.search(", "re.fullmatch("):
            assert pattern not in source, (
                f"regex validation appeared in {module.__name__} - revisit the "
                f"quote-splitting analysis in docs/security-audit-T-0045.md"
            )


def test_nan_is_not_normalizable_by_float_helpers():
    """SEC-ADVR-A1 (boundary note, machine-checked): NaN survives float()
    conversion and every comparison - the precondition that lets it travel from
    the transport frontier (Python's json.loads accepts NaN literals) through
    the tool layer to post_order."""
    assert math.isnan(float("nan"))
    assert not (float("nan") <= 0)
    assert not (float("nan") > 1000.0)
    payload = json.loads('{"size": NaN}')
    assert math.isnan(payload["size"]), "stdlib json accepts NaN literals by default"
