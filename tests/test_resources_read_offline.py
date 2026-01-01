"""Offline resources/read suite for polymarket_mcp.server (T-0288).

Pins the REAL MCP SDK dispatcher path for the three announced resources
(polymarket://status, polymarket://config, polymarket://rate-limits) plus the
anti-drift guard on the list_tools docstring.

The bug this suite closes (proven 1st-hand against main b240bb9, both in-process
and over stdio wire): the SDK's ReadResourceRequest dispatcher calls the
registered handler with ``req.params.uri`` which is a pydantic v2 ``AnyUrl`` -
NOT a ``str`` subclass (probed on pydantic 2.13.5: ``isinstance(u, str)`` False,
``u == "polymarket://status"`` False, ``str(u) == ...`` True). The pre-fix
handler compared ``uri == "polymarket://status"`` with the raw AnyUrl, so every
comparison fell through to the unknown-resource branch: the wire response was
``{"error": "Unknown resource: polymarket://..."}`` with mimeType text/plain for
ALL three resources. The unknown-resource branch itself was always correct and
is pinned here so it cannot regress.

Fix shape (contract-prescribed): normalize once (``uri_text = str(uri)``),
compare as ``str``, keep the handler's ``str`` return type (NOT
``ReadResourceContents`` - the T-0055 dispatch pins call ``read_resource`` with
a plain str and ``json.loads(await ...)``; migrating the return type breaks 5
pins and is a future slice). The SDK DeprecationWarning emitted by the
str-return path ("Returning str or bytes from read_resource is deprecated")
is a suite-only finding recorded in the task report - intentionally NOT fixed
in this slice (pyproject filterwarnings ignores DeprecationWarning, so the
suite stays green either way).

Anatomy (P-0040 house pattern, sibling tests/test_server_dispatch_offline.py):
module globals are patched per-test via monkeypatch with automatic restore;
the real PolymarketConfig is built by explicit kwargs with ``_env_file=None``
(P-0035) so no host .env is ever read; the rate limiter is patched at the
``get_rate_limiter`` seam (L-0142: the seam is the singleton accessor, not an
import) with a recording fake. Fakes are fail-loud (P-0031) so a dispatch
regression that reaches an unfaked network endpoint fails the test instead of
silently hitting the network. ``initialize_server``/``main`` are NEVER invoked
(L-0118: they would create API credentials over the network).

Hermeticity (P-0029/P-0035/P-0037): autouse ``clean_env`` removes every
PolymarketConfig-mapped env key in BOTH directions (prefixes derived from the
config fields - POLYGON_/POLYMARKET_ plus unprefixed config keys), no real
sockets (L-0138), zero sleeps, order-independent.

The anti-drift test (L-0023/L-0109/L-0056) reads the source with explicit
``encoding="utf-8"`` (P-0099, Windows CI cp1252 locale) and asserts the ABSENCE
of the five volatile tool-count fragments paired with the PRESENCE of the
stable semantic fragments INSIDE the parsed list_tools docstring (stricter
than substring-anywhere: an AST-parsed docstring can only pass if the list_tools
docstring itself carries the semantic bullets).
"""

import ast
import json
import os
from pathlib import Path

import mcp.types as types
import pytest

import polymarket_mcp.server as server_module
from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.utils.safety_limits import SafetyLimits

# Every env key the config reads, derived from PolymarketConfig fields
# (P-0035): prefixed credentials plus the unprefixed gap fields documented as
# the known limit of the house pattern.
_ENV_PREFIXES = ("POLYGON_", "POLYMARKET_")
_ENV_KEYS = (
    "DEMO_MODE",
    "LOG_LEVEL",
    "CLOB_API_URL",
    "GAMMA_API_URL",
    "USDC_ADDRESS",
    "CTF_EXCHANGE_ADDRESS",
    "CONDITIONAL_TOKEN_ADDRESS",
)
_ENV_LOOSE_PREFIXES = ("MAX_", "MIN_", "ENABLE_", "REQUIRE_", "AUTO_")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove every config-mapped env key from the test process (P-0035).

    Defensive in both directions: a hostile host env cannot leak into the
    built config (config is always built by explicit kwargs with
    ``_env_file=None`` anyway), and a legit-looking CI env cannot silently
    change the payloads asserted below.
    """
    for key in list(os.environ):
        if (
            key.startswith(_ENV_PREFIXES)
            or key.startswith(_ENV_LOOSE_PREFIXES)
            or key in _ENV_KEYS
        ):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def clean_server_state(monkeypatch):
    """Reset the module globals to the pre-initialize state (house pattern of
    tests/test_server_dispatch_offline.py clean_server_state).

    monkeypatch restores every attribute after each test, so sibling suites
    relying on the pre-init state are never affected.
    """
    monkeypatch.setattr(server_module, "config", None)
    monkeypatch.setattr(server_module, "polymarket_client", None)
    monkeypatch.setattr(server_module, "safety_limits", None)
    monkeypatch.setattr(server_module, "trading_tools", None)
    monkeypatch.setattr(server_module, "websocket_manager", None)
    monkeypatch.setattr(server_module, "_shutdown_event", None)


@pytest.fixture
def house_config():
    """Real PolymarketConfig with synthetic values, built by explicit kwargs
    with _env_file=None (P-0035 house pattern) - values are asserted through
    the object itself, never as literals (L-0002/L-0090)."""
    return PolymarketConfig(
        POLYGON_PRIVATE_KEY="0" * 63 + "1",
        POLYGON_ADDRESS="0x" + "0" * 40,
        POLYMARKET_CHAIN_ID=137,
        _env_file=None,
    )


@pytest.fixture
def house_limits():
    """Real SafetyLimits with synthetic limits (same house values as the
    sibling dispatch suite)."""
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
    """Duck-typed credential oracle (house pattern of the sibling dispatch
    suite). Only has_api_credentials is faked; any other attribute access
    raises AttributeError loudly (P-0031 fail-loud seam)."""

    def __init__(self, has_credentials: bool):
        self._has_credentials = has_credentials
        self.has_api_credentials_calls = 0

    def has_api_credentials(self) -> bool:
        self.has_api_credentials_calls += 1
        return self._has_credentials


class FakeRateLimiter:
    """Recording fake for the get_rate_limiter seam (L-0142).

    The payload mirrors the REAL get_status() structure field-for-field
    (src/polymarket_mcp/utils/rate_limiter.py:253): per-category buckets with
    available_tokens / max_tokens / refill_rate_per_sec / backoff_remaining_sec
    / is_throttled. The real process-wide singleton is never constructed or
    consulted by this suite.
    """

    def __init__(self, status: dict):
        self._status = status
        self.get_status_calls = 0

    def get_status(self):
        self.get_status_calls += 1
        return dict(self._status)


def _read_via_dispatcher(uri_text: str):
    """Call the REAL SDK request handler for ReadResourceRequest.

    This is the path the wire takes in production: the SDK Session builds a
    ``types.ReadResourceRequest`` whose ``params.uri`` is a pydantic v2
    ``AnyUrl`` and dispatches it via
    ``server.request_handlers[types.ReadResourceRequest]``. Calling the
    ``read_resource`` function directly with a plain str bypasses the exact
    bug this suite closes, so every test here goes through the handler.
    """
    request = types.ReadResourceRequest(
        params=types.ReadResourceRequestParams(uri=types.AnyUrl(uri_text))
    )
    return server_module.server.request_handlers[types.ReadResourceRequest](request)


# =====================================================================
# The real SDK dispatcher path (anyurl inputs - the bug this suite closes)
# =====================================================================


async def test_read_via_sdk_dispatcher_status_anyurl(monkeypatch, clean_server_state, house_config):
    """polymarket://status through the REAL dispatcher with an AnyUrl.

    Pre-fix RED (proven 1st-hand against b240bb9): the response text was
    '{"error": "Unknown resource: polymarket://status"}' because the AnyUrl
    never compared equal to the str literals. Post-fix the payload reflects
    the module globals member-by-member: with everything at pre-init defaults
    connected/has_api_credentials are False and address/chain_id are None;
    with a fake client and the house config they reflect those objects.
    server_version mirrors the module __version__ by reflection (never a
    literal - L-0002/P-0040(6)).
    """
    result = await _read_via_dispatcher("polymarket://status")
    contents = result.root.contents
    assert contents[0].mimeType == "text/plain"

    clean_payload = json.loads(contents[0].text)
    assert clean_payload["connected"] is False
    assert clean_payload["address"] is None
    assert clean_payload["chain_id"] is None
    assert clean_payload["has_api_credentials"] is False
    assert clean_payload["server_version"] == server_module.__version__

    monkeypatch.setattr(server_module, "polymarket_client", FakeClient(has_credentials=True))
    monkeypatch.setattr(server_module, "config", house_config)
    loaded = await _read_via_dispatcher("polymarket://status")
    loaded_payload = json.loads(loaded.root.contents[0].text)
    assert loaded_payload["connected"] is True
    assert loaded_payload["address"] == house_config.POLYGON_ADDRESS
    assert loaded_payload["chain_id"] == house_config.POLYMARKET_CHAIN_ID
    assert loaded_payload["has_api_credentials"] is True
    assert loaded_payload["server_version"] == server_module.__version__


async def test_read_via_sdk_dispatcher_config_without_state(clean_server_state):
    """Before initialize_server, polymarket://config fails closed with the
    exact documented error object (server.py: pre-fix behavior preserved)
    even when reached through the real AnyUrl dispatcher path."""
    result = await _read_via_dispatcher("polymarket://config")
    payload = json.loads(result.root.contents[0].text)

    assert payload == {"error": "Configuration not loaded"}


async def test_read_via_sdk_dispatcher_config_with_state(
    monkeypatch, clean_server_state, house_config, house_limits
):
    """With the real config and limits loaded, polymarket://config maps
    safety_limits (5 fields), trading_controls (3 knobs) and endpoints (2
    URLs) from the objects themselves - values asserted through the objects,
    never as literals (L-0002/L-0090)."""
    monkeypatch.setattr(server_module, "config", house_config)
    monkeypatch.setattr(server_module, "safety_limits", house_limits)

    result = await _read_via_dispatcher("polymarket://config")
    payload = json.loads(result.root.contents[0].text)

    safety = payload["safety_limits"]
    assert safety["max_order_size_usd"] == house_limits.max_order_size_usd
    assert safety["max_total_exposure_usd"] == house_limits.max_total_exposure_usd
    assert (
        safety["max_position_size_per_market"]
        == house_limits.max_position_size_per_market
    )
    assert safety["min_liquidity_required"] == house_limits.min_liquidity_required
    assert safety["max_spread_tolerance"] == house_limits.max_spread_tolerance

    controls = payload["trading_controls"]
    assert controls["enable_autonomous_trading"] == house_config.ENABLE_AUTONOMOUS_TRADING
    assert (
        controls["require_confirmation_above_usd"]
        == house_config.REQUIRE_CONFIRMATION_ABOVE_USD
    )
    assert (
        controls["auto_cancel_on_large_spread"]
        == house_config.AUTO_CANCEL_ON_LARGE_SPREAD
    )

    endpoints = payload["endpoints"]
    assert endpoints["clob_api"] == house_config.CLOB_API_URL
    assert endpoints["gamma_api"] == house_config.GAMMA_API_URL


async def test_read_via_sdk_dispatcher_rate_limits(monkeypatch, clean_server_state):
    """polymarket://rate-limits goes through the get_rate_limiter seam
    (L-0142: the seam is the singleton accessor) and json.dumps its
    get_status() dict verbatim. The fake payload mirrors the REAL
    get_status() structure field-for-field (rate_limiter.py:253); the seam
    is patched so the process-wide singleton is never touched."""
    fake_status = {
        "clob_general": {
            "available_tokens": 5000,
            "max_tokens": 5000,
            "refill_rate_per_sec": 500.0,
            "backoff_remaining_sec": 0.0,
            "is_throttled": False,
        },
    }
    limiter = FakeRateLimiter(fake_status)
    monkeypatch.setattr(server_module, "get_rate_limiter", lambda: limiter)

    result = await _read_via_dispatcher("polymarket://rate-limits")
    payload = json.loads(result.root.contents[0].text)

    assert limiter.get_status_calls == 1
    assert "clob_general" in payload
    bucket = payload["clob_general"]
    assert set(bucket) == {
        "available_tokens",
        "max_tokens",
        "refill_rate_per_sec",
        "backoff_remaining_sec",
        "is_throttled",
    }
    assert payload == fake_status


async def test_read_via_sdk_dispatcher_unknown_uri(clean_server_state):
    """An unknown URI fails closed with the exact error object carrying the
    requested URI back. This branch was ALWAYS correct (it used the raw
    request value, which for str inputs was byte-identical) and is pinned so
    the uri_text normalization cannot change its observable for plain str
    inputs (T-0055 pin server.py:469)."""
    result = await _read_via_dispatcher("polymarket://nonexistent")
    payload = json.loads(result.root.contents[0].text)

    assert payload == {"error": "Unknown resource: polymarket://nonexistent"}


# =====================================================================
# Anti-drift guard: list_tools docstring carries no volatile counts
# =====================================================================


def test_list_tools_docstring_no_volatile_counts():
    """The list_tools docstring must describe tool families SEMANTICALLY
    (L-0023/L-0109: enumerated counts of mutable state are structural debt -
    they go stale on the next merge) and must carry the stable semantic
    fragments. ABSENCES are paired with PRESENCES inside the parsed docstring
    (L-0056), and the presence asserts run against the AST-extracted
    docstring of the list_tools function itself - stricter than
    substring-anywhere, so the guard fails loud if the docstring is removed
    entirely (P-0246 complement item 6). Source is read with explicit
    encoding="utf-8" (P-0099, Windows CI cp1252 locale)."""
    source_path = Path(server_module.__file__).resolve()
    source = source_path.read_text(encoding="utf-8")

    volatile_counts = (
        "8 Market Discovery tools",
        "10 Market Analysis tools",
        "12 Trading tools",
        "8 Portfolio Management tools",
        "7 Real-time WebSocket tools",
    )
    for stale in volatile_counts:
        assert source.count(stale) == 0, (
            f"list_tools docstring drift: volatile count {stale!r} reappeared "
            f"in {source_path}"
        )

    tree = ast.parse(source)
    docstring = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "list_tools":
            docstring = ast.get_docstring(node)
            break
    assert docstring is not None, (
        "list_tools docstring missing: the anti-drift guard requires the "
        "semantic family bullets to live in the docstring itself"
    )
    assert docstring.count("always available - public API") >= 1
    assert docstring.count("require API credentials") >= 1
