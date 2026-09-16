"""
Offline dispatch suite for polymarket_mcp.server (T-0055, increment 13).

Covers the dispatch/resource surface that sat at 23.64% statement coverage on
main 9e675da (153/211 statements dead): the signal handler, list_tools
credential gating, list_resources, read_resource and the call_tool router.

Sources of truth (suite-only: src/** is read, never modified):
- src/polymarket_mcp/server.py: globals :41-52 (config/polymarket_client/
  safety_limits/trading_tools/websocket_manager all None pre-init),
  _signal_handler :102-107, list_tools :110-144 (credential gate :130-139),
  list_resources :147-178 (3 URIs), read_resource :181-240 (status :194-206,
  config :208-231, rate-limits :233-237, unknown :239-240), call_tool :243-343
  (discovery :259-262, analysis :265-268, portfolio :271-280, realtime
  :283-289, trading :292-326, final else :327-328, error envelope :330-343).
- Family tool lists are derived from the definition functions themselves
  (market_discovery.get_tools / market_analysis.get_tools /
  realtime.get_tools / get_tool_definitions /
  get_portfolio_tool_definitions) and verified equal to the router's literal
  name lists (8/10/8/7/12) before this suite was written - asserts derive
  from code (L-0002), so tools added by a later slice are picked up
  automatically instead of breaking counts.
- Version: src/polymarket_mcp/__init__.py (single source of truth; "0.2.0"
  at the time of writing - asserted by reflection, not by constant).

Coupling farm/T-0046 (in-flight on server.py): list_tools pins are BY MEMBER
OF NAME (presence/absence), never exact tool counts, so conformance
additions landing in T-0046 cannot break this suite. Overlap with
tests/test_safety_adversarial.py (T-0045) is calibrated: that suite already
pins the pre-init unknown-tool envelope, the create_limit_order-only
fallthrough without trading_tools, the portfolio pre-init plain-text failure
and list_tools pre-auth as an EXACT 25-name equality. This suite adds the
authenticated surface (FakeClient(True)), the with-tools-set unknown-tool
branch (server.py:317-318 inner else), per-family routing with recorded
handlers, portfolio context identity, cancel_all_orders argument ignoring
(the other 11 kwarg methods), the rate-limits resource and the signal
handler - no test here re-pins the sibling's exact-count assertions.

REGISTER-ONLY known bug (contract inputs section 3, deliberately NOT pinned
- anti-fix): server.py:288 calls realtime.handle_tool(name, arguments,
websocket_manager, server) but tools/realtime.py:218 defines
handle_tool_call(name, arguments) - the 7 real-time tools are unreachable
through the MCP dispatch even when the manager is initialized (probe
evidence: envelope error "module 'polymarket_mcp.tools.realtime' has no
attribute 'handle_tool'"). This suite pins ONLY the manager-None path
(server.py:286-287 ValueError "WebSocket manager not initialized"), which a
future fix can keep; the broken with-manager path is intentionally left
unpinned and reported to the curator as a follow-up slice (it collides with
in-flight farm/T-0046, so it is not emitted now).

Fakes are fail-loud module seams (P-0031): route recorders return one unique
sentinel object per family so the asymmetry pin is OBJECT IDENTITY -
discovery/analysis/portfolio results are returned unwrapped (server.py:262/
268/274) while trading results are wrapped in json.dumps (server.py:321-326)
- and unexpected handler calls raise instead of silently hitting network
code. cancel_all_orders pins by SIGNATURE: the fake declares no parameters,
so a fix that starts forwarding arguments fails loudly with a TypeError
inside the error envelope instead of silently recording them (L-0121). The
rate limiter is patched at the module seam (L-0123: get_rate_limiter is a
process-wide singleton) and the real singleton is never constructed here.

Hermeticity (L-0014/L-0118/L-0120): zero network (no socket/requests/httpx/
urllib/subprocess anywhere in this file), zero sleeps, and initialize_server
/ main are NEVER invoked (calling them with a real key would create API
credentials over the network); the suite exercises only the dispatch and
resource layer with patched module globals (monkeypatch restores state after
every test). Proven at write time by the env -i pytest run and by the
surface grep recorded in the task report.
"""
import json
import signal

import mcp.types as mcp_types
import pytest

import polymarket_mcp.server as server_module
import polymarket_mcp.tools.market_analysis as market_analysis
import polymarket_mcp.tools.market_discovery as market_discovery
import polymarket_mcp.tools.portfolio_integration as portfolio_integration
import polymarket_mcp.tools.realtime as realtime
from polymarket_mcp import __version__
from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.tools.trading import get_tool_definitions
from polymarket_mcp.utils.safety_limits import SafetyLimits

# The only trading method the router calls without arguments (server.py:312).
NO_KWARG_TRADING_METHOD = "cancel_all_orders"


@pytest.fixture
def clean_server_state(monkeypatch):
    """Reset the module globals to the pre-initialize state (server.py:41-52).

    Defensive by design: every test that touches server state sets what it
    needs on top of this baseline, and monkeypatch restores the original
    values after each test, so sibling suites that rely on the pre-init
    state are never affected by this file.
    """
    monkeypatch.setattr(server_module, "config", None)
    monkeypatch.setattr(server_module, "polymarket_client", None)
    monkeypatch.setattr(server_module, "safety_limits", None)
    monkeypatch.setattr(server_module, "trading_tools", None)
    monkeypatch.setattr(server_module, "websocket_manager", None)
    monkeypatch.setattr(server_module, "_shutdown_event", None)


@pytest.fixture
def house_config():
    """Real PolymarketConfig with the house test pattern (sibling
    test_websocket_readers.py:20-25) and _env_file=None so no real .env file
    is ever read (P-0029 hermeticity)."""
    return PolymarketConfig(
        POLYGON_PRIVATE_KEY="0" * 63 + "1",
        POLYGON_ADDRESS="0x" + "0" * 40,
        POLYMARKET_CHAIN_ID=137,
        _env_file=None,
    )


@pytest.fixture
def house_limits():
    """Real SafetyLimits with synthetic limits; values are asserted through
    the object itself, never as literals (L-0002/L-0090)."""
    return SafetyLimits(
        max_order_size_usd=25.0,
        max_total_exposure_usd=250.0,
        max_position_size_per_market=100.0,
        min_liquidity_required=500.0,
        max_spread_tolerance=0.05,
        require_confirmation_above_usd=50.0,
        auto_cancel_on_large_spread=True,
    )


class FakeClient:
    """Duck-typed credential oracle (server.py:130 and :200-203).

    Only has_api_credentials is faked; any other attribute access raises
    AttributeError loudly (P-0031 fail-loud seam) so a dispatch regression
    that reaches for an unfaked network endpoint fails the test instead of
    silently falling back to the real client.
    """

    def __init__(self, has_credentials: bool):
        self._has_credentials = has_credentials
        self.has_api_credentials_calls = 0

    def has_api_credentials(self) -> bool:
        self.has_api_credentials_calls += 1
        return self._has_credentials


class RouteRecorder:
    """Fail-loud module-seam recorder for one tool family (P-0031).

    Records (name, arguments, extra positional args) and always returns the
    same unique marker object, so the call_tool asymmetry pin is object
    identity: discovery/analysis/portfolio results must come back unwrapped
    (server.py:262/268/274). If the router ever starts json.dumps-wrapping
    them like trading does, the identity assert fails loudly.
    """

    def __init__(self, family: str):
        self.family = family
        self.calls = []
        self.marker = object()  # unique per family and per call site

    async def __call__(self, name, arguments, *extra):
        self.calls.append((name, arguments, extra))
        return self.marker


class FakeRateLimiter:
    """Recorder for the get_rate_limiter seam (server.py:235 and :278).

    get_status() returns a fixed dict; the real singleton (L-0123) is never
    constructed or consulted by this suite.
    """

    def __init__(self, status):
        self._status = status
        self.get_status_calls = 0

    def get_status(self):
        self.get_status_calls += 1
        return self._status


class FakeTradingTools:
    """Recording stand-in for TradingTools with the 12 routed methods
    (server.py:292-316).

    Every kwarg method records (name, kwargs) and returns the same marked
    dict, so each route is pinned mechanically and the json.dumps wrap
    (server.py:321-326) is verified by round-tripping the text. The methods
    are declared one by one on purpose: the fake's surface IS the structural
    pin (L-0121) - a future route that calls an attribute the fake lacks
    fails with AttributeError loudly, and a route that starts forwarding
    arguments to cancel_all_orders fails with TypeError (that fake method
    declares no parameters).
    """

    RESULT = {"marker": "trading-result"}

    def __init__(self):
        self.calls = []
        self.result = dict(self.RESULT)

    def _record(self, name, kwargs):
        self.calls.append((name, kwargs))
        return dict(self.result)

    async def create_limit_order(self, **kwargs):
        return self._record("create_limit_order", dict(kwargs))

    async def create_market_order(self, **kwargs):
        return self._record("create_market_order", dict(kwargs))

    async def create_batch_orders(self, **kwargs):
        return self._record("create_batch_orders", dict(kwargs))

    async def suggest_order_price(self, **kwargs):
        return self._record("suggest_order_price", dict(kwargs))

    async def get_order_status(self, **kwargs):
        return self._record("get_order_status", dict(kwargs))

    async def get_open_orders(self, **kwargs):
        return self._record("get_open_orders", dict(kwargs))

    async def get_order_history(self, **kwargs):
        return self._record("get_order_history", dict(kwargs))

    async def cancel_order(self, **kwargs):
        return self._record("cancel_order", dict(kwargs))

    async def cancel_market_orders(self, **kwargs):
        return self._record("cancel_market_orders", dict(kwargs))

    async def cancel_all_orders(self):
        self.calls.append(("cancel_all_orders", None))
        return dict(self.RESULT)

    async def execute_smart_trade(self, **kwargs):
        return self._record("execute_smart_trade", dict(kwargs))

    async def rebalance_position(self, **kwargs):
        return self._record("rebalance_position", dict(kwargs))


class ExplodingTradingTools:
    """Trading fake whose every method raises - exercises the catch-all
    error envelope (server.py:330-343) without depending on any real
    network/client code."""

    def __init__(self, message):
        self._message = message
        self.calls = []

    async def create_limit_order(self, **kwargs):
        self.calls.append(("create_limit_order", dict(kwargs)))
        raise RuntimeError(self._message)


class FakeShutdownEvent:
    """Recording stand-in for the asyncio.Event held by _shutdown_event
    (server.py:48, set by main :461 and consumed by _signal_handler
    :106-107)."""

    def __init__(self, is_set=False):
        self._is_set = is_set
        self.set_calls = 0

    def is_set(self):
        return self._is_set

    def set(self):
        self.set_calls += 1
        self._is_set = True


def _names_of(tools):
    return [tool.name for tool in tools]


def _discovery_names():
    return _names_of(market_discovery.get_tools())


def _analysis_names():
    return _names_of(market_analysis.get_tools())


def _realtime_names():
    return _names_of(realtime.get_tools())


def _trading_names():
    return _names_of(get_tool_definitions())


def _portfolio_names():
    return _names_of(portfolio_integration.get_portfolio_tool_definitions())


# =====================================================================
# list_tools - credential gating (server.py:110-144)
# =====================================================================


async def test_list_tools_readonly_omits_trading_and_portfolio(monkeypatch, clean_server_state):
    """With no client at all (pre-init state) the advertised surface must
    omit every trading and portfolio name while keeping the three always-on
    families (server.py:126-139, :142). Pinned BY MEMBER of name - never by
    total count (T-0046 coupling)."""
    names = {tool.name for tool in await server_module.list_tools()}

    for name in ("create_limit_order", "execute_smart_trade", "get_all_positions", "get_pnl_summary"):
        assert name not in names, f"{name} must not be advertised without credentials"
    for name in _discovery_names() + _analysis_names() + _realtime_names():
        assert name in names, f"{name} is always advertised (public/realtime)"


async def test_list_tools_authenticated_includes_trading_and_portfolio(monkeypatch, clean_server_state):
    """With a client reporting has_api_credentials() == True the trading (12)
    and portfolio (8) names join the surface (server.py:132-136). The fake
    is the only object touched - get_tool_definitions and
    get_portfolio_tool_definitions are pure definition lists."""
    client = FakeClient(has_credentials=True)
    monkeypatch.setattr(server_module, "polymarket_client", client)

    names = {tool.name for tool in await server_module.list_tools()}

    assert client.has_api_credentials_calls >= 1, "the gate must consult the client"
    for name in _trading_names() + _portfolio_names():
        assert name in names, f"{name} must be advertised with credentials"
    for name in _discovery_names() + _analysis_names() + _realtime_names():
        assert name in names, f"{name} must never disappear once authenticated"


async def test_list_tools_always_includes_public_and_realtime_names(monkeypatch, clean_server_state):
    """A client that exists but reports no credentials keeps the False branch
    of the gate (server.py:130): public and real-time names stay, trading and
    portfolio stay out. This is the third state of the gate expression
    (client present, credentials absent) after the None-state and True-state
    tests above."""
    client = FakeClient(has_credentials=False)
    monkeypatch.setattr(server_module, "polymarket_client", client)

    names = {tool.name for tool in await server_module.list_tools()}

    assert client.has_api_credentials_calls >= 1
    for name in _discovery_names() + _analysis_names() + _realtime_names():
        assert name in names
    for name in _trading_names() + _portfolio_names():
        assert name not in names


# =====================================================================
# list_resources (server.py:147-178)
# =====================================================================


async def test_list_resources_exposes_three_status_uris(clean_server_state):
    """The resource surface exposes the three documented URIs as JSON
    resources (server.py:157-176). Pinned by member of URI - extra resources
    from future slices do not break the pin."""
    resources = await server_module.list_resources()
    by_uri = {str(resource.uri): resource for resource in resources}

    for uri in ("polymarket://status", "polymarket://config", "polymarket://rate-limits"):
        assert uri in by_uri, f"{uri} must be exposed"
        assert by_uri[uri].mimeType == "application/json"
    assert by_uri["polymarket://status"].name == "Connection Status"
    assert by_uri["polymarket://config"].name == "Configuration"
    assert by_uri["polymarket://rate-limits"].name == "Rate Limiter Status"


# =====================================================================
# read_resource (server.py:181-240)
# =====================================================================


async def test_read_resource_status_reflects_client_and_version(monkeypatch, clean_server_state, house_config):
    """polymarket://status reflects the module globals verbatim (server.py
    :194-206): with everything at pre-init defaults connected/has_api_
    credentials/address/chain_id are false/null; with a fake client and the
    house config they reflect those objects, and server_version mirrors the
    package __version__ (single source of truth, never a literal)."""
    clean = json.loads(await server_module.read_resource("polymarket://status"))
    assert clean == {
        "connected": False,
        "address": None,
        "chain_id": None,
        "has_api_credentials": False,
        "server_version": __version__,
    }

    monkeypatch.setattr(server_module, "polymarket_client", FakeClient(has_credentials=True))
    monkeypatch.setattr(server_module, "config", house_config)
    loaded = json.loads(await server_module.read_resource("polymarket://status"))
    assert loaded == {
        "connected": True,
        "address": house_config.POLYGON_ADDRESS,
        "chain_id": house_config.POLYMARKET_CHAIN_ID,
        "has_api_credentials": True,
        "server_version": __version__,
    }


async def test_read_resource_config_without_state_returns_error(monkeypatch, clean_server_state):
    """Before initialize_server, polymarket://config fails closed with the
    documented error object and nothing else (server.py:208-211)."""
    payload = json.loads(await server_module.read_resource("polymarket://config"))

    assert payload == {"error": "Configuration not loaded"}


async def test_read_resource_config_with_state_shows_limits_and_controls(monkeypatch, clean_server_state, house_config, house_limits):
    """With the real config and limits loaded the resource maps safety_limits
    (5 fields), trading_controls (3 knobs) and endpoints (2 URLs) from the
    objects themselves (server.py:213-231) - values asserted through the
    objects, key sets pinned exactly."""
    monkeypatch.setattr(server_module, "config", house_config)
    monkeypatch.setattr(server_module, "safety_limits", house_limits)

    payload = json.loads(await server_module.read_resource("polymarket://config"))

    assert payload == {
        "safety_limits": {
            "max_order_size_usd": house_limits.max_order_size_usd,
            "max_total_exposure_usd": house_limits.max_total_exposure_usd,
            "max_position_size_per_market": house_limits.max_position_size_per_market,
            "min_liquidity_required": house_limits.min_liquidity_required,
            "max_spread_tolerance": house_limits.max_spread_tolerance,
        },
        "trading_controls": {
            "enable_autonomous_trading": house_config.ENABLE_AUTONOMOUS_TRADING,
            "require_confirmation_above_usd": house_config.REQUIRE_CONFIRMATION_ABOVE_USD,
            "auto_cancel_on_large_spread": house_config.AUTO_CANCEL_ON_LARGE_SPREAD,
        },
        "endpoints": {
            "clob_api": house_config.CLOB_API_URL,
            "gamma_api": house_config.GAMMA_API_URL,
        },
    }


async def test_read_resource_rate_limits_returns_rate_limiter_status(monkeypatch, clean_server_state):
    """polymarket://rate-limits goes through the get_rate_limiter seam and
    wraps its get_status() dict in JSON verbatim (server.py:233-237). The
    seam is patched (L-0123) so the process-wide singleton is never touched
    and no rate-limit budget is consumed by this suite."""
    status = {"marker": "rate-status", "buckets": {"discovery": {"calls": 3}}}
    limiter = FakeRateLimiter(status)
    monkeypatch.setattr(server_module, "get_rate_limiter", lambda: limiter)

    text = await server_module.read_resource("polymarket://rate-limits")

    assert limiter.get_status_calls == 1
    assert json.loads(text) == status


async def test_read_resource_unknown_uri_returns_error_json(monkeypatch, clean_server_state):
    """An unknown URI fails closed with the exact error object carrying the
    requested URI back (server.py:239-240)."""
    uri = "polymarket://definitely-not-a-resource"

    payload = json.loads(await server_module.read_resource(uri))

    assert payload == {"error": f"Unknown resource: {uri}"}


# =====================================================================
# call_tool - routing of the four working families (server.py:243-343)
# =====================================================================


async def test_call_tool_routes_discovery_names_to_market_discovery(monkeypatch, clean_server_state):
    """Every discovery name defined by market_discovery.get_tools() routes to
    market_discovery.handle_tool(name, arguments) and comes back UNWRAPPED:
    the recorder's marker object is returned by identity (server.py:259-262).
    Names derive from the definition function (L-0002), matching the router's
    literal 8-name list as verified at write time."""
    recorder = RouteRecorder("discovery")
    monkeypatch.setattr(market_discovery, "handle_tool", recorder)

    for name in _discovery_names():
        recorder.calls.clear()
        arguments = {"query": name}

        result = await server_module.call_tool(name, arguments)

        assert recorder.calls == [(name, arguments, ())], recorder.calls
        assert result is recorder.marker, "discovery results must not be wrapped"


async def test_call_tool_routes_analysis_names_to_market_analysis(monkeypatch, clean_server_state):
    """Same contract as discovery for the analysis family: all 10 defined
    names route to market_analysis.handle_tool and return the handler's
    object by identity (server.py:265-268)."""
    recorder = RouteRecorder("analysis")
    monkeypatch.setattr(market_analysis, "handle_tool", recorder)

    for name in _analysis_names():
        recorder.calls.clear()
        arguments = {"token_id": name}

        result = await server_module.call_tool(name, arguments)

        assert recorder.calls == [(name, arguments, ())], recorder.calls
        assert result is recorder.marker, "analysis results must not be wrapped"


async def test_call_tool_routes_portfolio_names_with_context_args(monkeypatch, clean_server_state):
    """Every portfolio name routes to call_portfolio_tool with the caller
    payload AND the three module globals as trailing positional context:
    polymarket_client, get_rate_limiter() and config (server.py:271-280).
    Identity of each context object is pinned, and the seam fake for
    get_rate_limiter is what the handler receives (L-0123)."""
    client = object()  # sentinel identity, only compared with `is`
    limiter = object()
    config = object()
    monkeypatch.setattr(server_module, "polymarket_client", client)
    monkeypatch.setattr(server_module, "config", config)
    monkeypatch.setattr(server_module, "get_rate_limiter", lambda: limiter)
    recorder = RouteRecorder("portfolio")
    monkeypatch.setattr(portfolio_integration, "call_portfolio_tool", recorder)

    for name in _portfolio_names():
        recorder.calls.clear()
        arguments = {"portfolio": name}

        result = await server_module.call_tool(name, arguments)

        assert len(recorder.calls) == 1, recorder.calls
        routed_name, routed_arguments, extra = recorder.calls[0]
        assert routed_name == name
        assert routed_arguments is arguments, "the arguments dict is passed through"
        assert extra[0] is client, "polymarket_client global is forwarded"
        assert extra[1] is limiter, "get_rate_limiter() seam result is forwarded"
        assert extra[2] is config, "config global is forwarded"
        assert result is recorder.marker, "portfolio results must not be wrapped"


async def test_call_tool_trading_route_invokes_methods_with_kwargs(monkeypatch, clean_server_state):
    """Each of the 11 kwarg trading methods is invoked with the caller's
    arguments unpacked as **kwargs and its dict result wrapped in a single
    text TextContent via json.dumps (server.py:292-326). The method list
    derives from get_tool_definitions minus the no-kwarg method."""
    fake = FakeTradingTools()
    monkeypatch.setattr(server_module, "trading_tools", fake)

    kwarg_methods = [name for name in _trading_names() if name != NO_KWARG_TRADING_METHOD]
    assert len(kwarg_methods) == 11, "12 trading tools minus cancel_all_orders"

    for name in kwarg_methods:
        fake.calls.clear()
        arguments = {"market_id": "m1", "size": 2.5, "tool": name}

        contents = await server_module.call_tool(name, dict(arguments))

        assert fake.calls == [(name, arguments)], fake.calls
        assert len(contents) == 1
        assert isinstance(contents[0], mcp_types.TextContent)
        assert contents[0].type == "text"
        assert json.loads(contents[0].text) == fake.result, "trading wrap is json.dumps"


async def test_call_tool_trading_cancel_all_orders_ignores_arguments(monkeypatch, clean_server_state):
    """The router calls cancel_all_orders WITHOUT arguments (server.py:312):
    the fake records a bare call even when arguments are supplied, and the
    fake method's no-parameter signature makes any future forwarding fail
    loudly with TypeError inside the error envelope (L-0121 pin-by-
    signature)."""
    fake = FakeTradingTools()
    monkeypatch.setattr(server_module, "trading_tools", fake)

    contents = await server_module.call_tool("cancel_all_orders", {"filter": "all"})

    assert fake.calls == [("cancel_all_orders", None)], fake.calls
    assert json.loads(contents[0].text) == fake.result


async def test_call_tool_trading_without_tools_treated_unknown(monkeypatch, clean_server_state):
    """With trading_tools at its pre-init None every trading name fails
    closed through the final else (server.py:327-328) with the uniform
    error envelope - all 12 names, not just the one the T-0045 sibling
    covers."""
    for name in _trading_names():
        contents = await server_module.call_tool(name, {"any": 1})

        payload = json.loads(contents[0].text)
        assert set(payload) == {"success", "error", "tool", "arguments"}
        assert payload["success"] is False
        assert payload["error"] == f"Unknown tool: {name}"
        assert payload["tool"] == name
        assert payload["arguments"] == {"any": 1}


async def test_call_tool_unknown_tool_returns_error_envelope(monkeypatch, clean_server_state):
    """With trading tools LOADED, a name outside every family falls through
    the trading gate into the inner else (server.py:317-318) and comes back
    as the uniform error envelope with exactly the four documented keys.
    The fake records nothing - the router must never reach a fake method
    for an unrouted name."""
    fake = FakeTradingTools()
    monkeypatch.setattr(server_module, "trading_tools", fake)

    contents = await server_module.call_tool("definitely_not_a_tool", {"x": 1})

    payload = json.loads(contents[0].text)
    assert set(payload) == {"success", "error", "tool", "arguments"}
    assert payload["success"] is False
    assert payload["error"] == "Unknown tool: definitely_not_a_tool"
    assert payload["tool"] == "definitely_not_a_tool"
    assert payload["arguments"] == {"x": 1}
    assert fake.calls == []


async def test_call_tool_error_envelope_carries_tool_and_arguments(monkeypatch, clean_server_state):
    """An exception raised inside a route is converted into the uniform
    error envelope (server.py:330-343) with exactly success/error/tool/
    arguments, the message stringified and the original arguments echoed."""
    tools = ExplodingTradingTools("boom")
    monkeypatch.setattr(server_module, "trading_tools", tools)

    contents = await server_module.call_tool("create_limit_order", {"price": 0.5})

    payload = json.loads(contents[0].text)
    assert set(payload) == {"success", "error", "tool", "arguments"}
    assert payload["success"] is False
    assert payload["error"] == "boom"
    assert payload["tool"] == "create_limit_order"
    assert payload["arguments"] == {"price": 0.5}
    assert tools.calls == [("create_limit_order", {"price": 0.5})]


async def test_call_tool_realtime_without_manager_fails_closed(monkeypatch, clean_server_state):
    """Fix-compatible pin: the real-time family checks the manager BEFORE any
    handler call and fails closed with the uniform envelope when it is None
    (server.py:283-287). All 7 real-time names route through this gate, and
    none of them reaches realtime.handle_tool here (the with-manager path is
    REGISTER-ONLY - see the module docstring - and is deliberately not
    pinned)."""
    for name in _realtime_names():
        contents = await server_module.call_tool(name, {"market_id": "m1"})

        payload = json.loads(contents[0].text)
        assert set(payload) == {"success", "error", "tool", "arguments"}
        assert payload["success"] is False
        assert payload["error"] == "WebSocket manager not initialized"
        assert payload["tool"] == name
        assert payload["arguments"] == {"market_id": "m1"}


# =====================================================================
# _signal_handler (server.py:102-107)
# =====================================================================


def test_signal_handler_sets_shutdown_event(monkeypatch):
    """_signal_handler sets the shutdown event exactly once when it exists
    and is not set (server.py:106-107); an already-set event is not set
    again and a missing event (pre-init None) is tolerated without touching
    anything. All three states of the guard are pinned."""
    fresh = FakeShutdownEvent(is_set=False)
    monkeypatch.setattr(server_module, "_shutdown_event", fresh)
    server_module._signal_handler(signal.SIGTERM, None)
    assert fresh.set_calls == 1
    assert fresh.is_set() is True

    already_set = FakeShutdownEvent(is_set=True)
    monkeypatch.setattr(server_module, "_shutdown_event", already_set)
    server_module._signal_handler(signal.SIGINT, None)
    assert already_set.set_calls == 0, "an already-set event must not be set twice"

    monkeypatch.setattr(server_module, "_shutdown_event", None)
    server_module._signal_handler(signal.SIGINT, None)  # must not raise
