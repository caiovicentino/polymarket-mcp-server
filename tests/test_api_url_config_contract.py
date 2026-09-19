"""Contract: endpoint config fields are display-only (execution divergence).

Pins the OBSERVED divergence between the configuration layer and the
execution layer for API endpoints, so a future wiring fix must consciously
flip these pins (they are OBSERVED facts, not wishes):

  1. GAMMA_API_URL config field is INERT for discovery: market_discovery
     fetches via the module-level constant GAMMA_API_URL (market_discovery.py
     :27, used at :52 and :122). An operator overriding GAMMA_API_URL in .env
     (proxy / private endpoint) silently keeps hitting the default.
  2. CLOB_API_URL config field is INERT for trading: PolymarketClient defaults
     host to the hardcoded "https://clob.polymarket.com" (auth/client.py:46)
     and create_polymarket_client never passes a host (auth/client.py:502-532
     does not forward one), so the .env override never reaches the trading
     client.
  3. The config resource (polymarket://config) DOES display the overridden
     values (server.py:483-484) - display follows config while execution does
     not. That visible mismatch is exactly why this divergence matters.
  4. The Data API (positions/trades) is not configurable at all: portfolio.py
     hardcodes "https://data-api.polymarket.com" at six call sites and
     PolymarketConfig has no DATA_API_URL field.

If a future change wires any of these to the config, the corresponding pin
goes RED and forces a conscious flip with the new contract stated.

Provenance: source of design sim/c70-preflight @ 9cf373c (5 passed proven
by curator 3x: 1.62s / 4.58s / 2.62s; ruff-clean). Re-derived identical
against main 13b059aa (c9bd601..main: zero diff in the four pinned files;
merge-base of farm/T-0325 = main tip). Sole adaptation vs the sim: the
duplicated class attribute ``last_url = None`` in _FakeGammaClient was
collapsed to a single declaration (cosmetic, declared per L-0025).
Fern-hermetic by construction: no network (fake AsyncClient intercepts at
the market_discovery.httpx seam before any socket), config built from
explicit kwargs with _env_file=None. Windows-safe: no subprocess; source
reads use read_text(encoding="utf-8") (P-0099); all literals ASCII.
"""
import asyncio
import inspect
import json
import pathlib

import pytest

from polymarket_mcp import server as server_module
from polymarket_mcp.auth.client import PolymarketClient
from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.tools import market_discovery, portfolio
from polymarket_mcp.utils.safety_limits import SafetyLimits

GAMMA_DEFAULT = "https://gamma-api.polymarket.com"
CLOB_DEFAULT = "https://clob.polymarket.com"
GAMMA_OVERRIDE = "http://127.0.0.1:9999"
CLOB_OVERRIDE = "http://127.0.0.1:8443"

KEY = "0" * 63 + "1"
ADDRESS = "0x" + "0" * 40


class _NoopLimiter:
    async def acquire(self, category):  # noqa: ANN001 - probe-shape stub
        return None


class _FakeResponse:
    def __init__(self, payload=None):
        self.status_code = 200
        self._payload = {"events": []} if payload is None else payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeGammaClient:
    """Async-context client that records every requested absolute URL."""

    last_url = None
    response_payload = []  # tests set {"events": []} for the search site

    def __init__(self, *args, **kwargs):
        self._kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, timeout=None):
        type(self).last_url = url
        return _FakeResponse(self.response_payload)


def _house_config(**overrides) -> PolymarketConfig:
    fields = dict(
        POLYGON_PRIVATE_KEY=KEY,
        POLYGON_ADDRESS=ADDRESS,
        POLYMARKET_CHAIN_ID=137,
        GAMMA_API_URL=GAMMA_OVERRIDE,
        CLOB_API_URL=CLOB_OVERRIDE,
        _env_file=None,
    )
    fields.update(overrides)
    return PolymarketConfig(**fields)


@pytest.fixture
def clean_server_state(monkeypatch):
    monkeypatch.setattr(server_module, "config", None)
    monkeypatch.setattr(server_module, "safety_limits", None)


def test_gamma_markets_fetch_ignores_config_override(monkeypatch):
    """Pin 1: _fetch_gamma_markets routes to the MODULE constant, not config."""
    _FakeGammaClient.response_payload = []
    _FakeGammaClient.last_url = None
    monkeypatch.setattr(market_discovery.httpx, "AsyncClient", _FakeGammaClient)
    monkeypatch.setattr(market_discovery, "get_rate_limiter", lambda: _NoopLimiter())
    cfg = _house_config()

    # Today the fetch still goes to the default host even though the config
    # layer holds the override.
    async def _run():
        return await market_discovery._fetch_gamma_markets("/markets")

    result = asyncio.run(_run())
    assert result == []
    assert _FakeGammaClient.last_url is not None
    assert _FakeGammaClient.last_url.startswith(GAMMA_DEFAULT), (
        f"expected constant routing, got {_FakeGammaClient.last_url!r}"
    )
    assert not _FakeGammaClient.last_url.startswith(GAMMA_OVERRIDE)
    assert cfg.GAMMA_API_URL == GAMMA_OVERRIDE  # config layer holds the override


def test_search_gamma_markets_ignores_config_override(monkeypatch):
    """Pin 2: _search_gamma_markets (site :122) also routes to the constant."""
    _FakeGammaClient.response_payload = {"events": []}
    _FakeGammaClient.last_url = None
    monkeypatch.setattr(market_discovery.httpx, "AsyncClient", _FakeGammaClient)
    monkeypatch.setattr(market_discovery, "get_rate_limiter", lambda: _NoopLimiter())
    cfg = _house_config()

    async def _run():
        return await market_discovery._search_gamma_markets("foo", limit=5)

    result = asyncio.run(_run())
    assert result == []
    assert _FakeGammaClient.last_url is not None
    assert _FakeGammaClient.last_url.startswith(GAMMA_DEFAULT)
    assert "/public-search" in _FakeGammaClient.last_url
    assert not _FakeGammaClient.last_url.startswith(GAMMA_OVERRIDE)
    assert cfg.GAMMA_API_URL == GAMMA_OVERRIDE


def test_clob_client_host_ignores_config_override():
    """Pin 3: PolymarketClient host stays hardcoded; config holds the override."""
    cfg = _house_config()
    # The config layer accepts and stores the override...
    assert cfg.CLOB_API_URL == CLOB_OVERRIDE
    # ...but the client default is a hardcoded literal, not the config value.
    default_host = inspect.signature(PolymarketClient.__init__).parameters["host"].default
    assert default_host == CLOB_DEFAULT
    pmc = PolymarketClient(private_key=KEY, address=ADDRESS)
    assert pmc.host == CLOB_DEFAULT
    assert pmc.host != cfg.CLOB_API_URL
    # And nothing in config.py maps DATA_API_URL either (pin 4 companion).
    assert "DATA_API_URL" not in PolymarketConfig.model_fields


def test_config_resource_displays_overridden_endpoints(
    clean_server_state, monkeypatch
):
    """Pin 4: display follows config while execution does not (divergence)."""
    monkeypatch.setattr(server_module, "config", _house_config())
    monkeypatch.setattr(
        server_module,
        "safety_limits",
        SafetyLimits(
            max_order_size_usd=25.0,
            max_total_exposure_usd=1000.0,
            max_position_size_per_market=100.0,
            min_liquidity_required=100.0,
            max_spread_tolerance=0.05,
            require_confirmation_above_usd=50.0,
            auto_cancel_on_large_spread=True,
        ),
    )
    raw = asyncio.run(server_module.read_resource("polymarket://config"))
    payload = json.loads(raw)
    assert payload["endpoints"]["clob_api"] == CLOB_OVERRIDE
    assert payload["endpoints"]["gamma_api"] == GAMMA_OVERRIDE


def test_data_api_endpoint_is_literal_and_unconfigurable():
    """Pin 5: Data API has no config field; portfolio.py hardcodes the URL."""
    assert "DATA_API_URL" not in PolymarketConfig.model_fields
    text = pathlib.Path(portfolio.__file__).read_text(encoding="utf-8")
    assert text.count("https://data-api.polymarket.com/positions") >= 3
    assert text.count("https://data-api.polymarket.com/trades") >= 2
