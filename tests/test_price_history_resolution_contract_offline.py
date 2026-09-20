"""Resolution-vocabulary contract suite for get_price_history (T-0453).

``get_price_history`` is a PLACEHOLDER (REQUER-HUMANO item 154/128,
owner-gated): the body never reads the ``resolution`` parameter. But the
tool's DECLARED contract (inputSchema enum + docstring Args line +
TOOLS_REFERENCE.md) advertises ``["1m", "5m", "1h", "1d"]`` -- and ``"5m"``
is a FALSE advertisement: the live CLOB /prices-history endpoint rejects
it with HTTP 400, while ``6h``/``1w`` (missing from the declaration) are
accepted.

Wire truth proven first-hand (contract emission 2026-09-20; re-probed on
this branch the same day by live token harvest from the gamma feed):

- GET {CLOB_API_URL}/prices-history?market=<token>&interval=5m
  -> HTTP 400 {"error": "invalid filters: the 'interval' value is unknown.
  Known values: '1m', '1w', '1d', '6h', '1h'"}
- GET {CLOB_API_URL}/prices-history?market=<token>&interval=6h
  -> HTTP 200 {"history": [{"t": <epoch>, "p": <price>}, ...]}

The REAL wire vocabulary is {1m, 1w, 1d, 6h, 1h}. This slice corrects the
DECLARED contract only (zero semantics -- the placeholder never reads the
parameter, so every edit here is inert until item 154 lands):
- E1: inputSchema enum -> ["1m", "1h", "6h", "1d", "1w"] (canonical order
  by granularity; the suite pins the SET, never the order, L-0023).
- E2: docstring resolution line + a wire-truth note quoting the probe.
- E3: TOOLS_REFERENCE.md resolution line (doc and schema in the SAME
  slice -- consumer<->producer, L-0073).

Declared divergence (L-0025/L-0090a): the prescribed E2 note quotes the
probe verbatim, so the literal ``5m`` survives INSIDE the docstring as the
documented REJECTED value. The "5m removed everywhere" pin therefore
asserts the surfaces that ADVERTISE resolutions (schema enum, the
docstring Args block, TOOLS_REFERENCE.md) -- not the full docstring text;
the note presence itself is pinned positive (the probe provenance must
survive). Before the fix ``5m`` was present in all three advertising
sites (RED pre: 2 failed / 2 passed).

Inertia guard (the anti-over-fix tripwire of this zero-semantics slice):
``get_price_history(token_id=..., resolution="5m")`` equals
``get_price_history(token_id=..., resolution="1h")`` -- both return the
same placeholder envelope; the enum is declared, never enforced. GREEN
before AND after this slice. It flips RED when item 154 lands (forwarding
resolution -> interval diverges the two calls): the fixer must update
this pin in the SAME change (consumer<->producer, L-0073).

Out of scope (register-only): the ``fidelity`` parameter (the wire
requires fidelity >= 10 minutes for interval=1m -- probe; the placeholder
accepts no fidelity parameter today; item 154 adds it when forwarding
lands).

Suite arithmetic (L-0260/L-0340): 4 offline tests (canonical selection)
+ 2 integration-marked live tests (deselected from the offline
selection). Live behavior: gamma/CLOB transport outages SKIP (guard),
never fail the suite; the 5m pin is an ERROR-status pin, so per P-0219 it
carries the try/except guard ONLY (a 5xx outage fails loud instead of
being swallowed -- the vocabulary cannot be verified during an outage);
the 6h pin is a success pin and uses _check_response (5xx -> skip). No
pytestmark at module level (P-0130(4): per-test markers only).
"""

import json
from pathlib import Path

import httpx
import pytest

from polymarket_mcp.tools import market_analysis

GAMMA_API_URL = market_analysis.GAMMA_API_URL
CLOB_API_URL = market_analysis.CLOB_API_URL

ROOT = Path(__file__).resolve().parent.parent
TOOLS_REFERENCE = ROOT / "TOOLS_REFERENCE.md"

# Wire truth (probed 2026-09-20, 1st hand; see module docstring).
WIRE_KNOWN_INTERVALS = {"1m", "1w", "1d", "6h", "1h"}


def _tool_schema(tool_name):
    """Fail-loud schema extraction from the LIVE registry: never a
    re-implementation of the schema in the test."""
    for tool in market_analysis.get_tools():
        if tool.name == tool_name:
            return tool.inputSchema
    raise AssertionError(f"tool {tool_name!r} not registered by market_analysis.get_tools()")


def _resolution_param_schema():
    schema = _tool_schema("get_price_history")
    props = schema.get("properties", {})
    assert "resolution" in props, (
        f"get_price_history schema lost the resolution param: {sorted(props)!r}"
    )
    return props["resolution"]


def _doc_args_block():
    """Content-anchored Args block of the get_price_history docstring
    (never line numbers, L-0127). Fail-loud when the anchors move."""
    doc = market_analysis.get_price_history.__doc__ or ""
    assert doc, "get_price_history lost its docstring"
    start = doc.index("Args:")
    end = doc.index("Returns:")
    block = doc[start:end]
    assert block.strip(), "get_price_history Args block is empty"
    return block


def test_resolution_enum_matches_wire_known_values():
    """The declared enum must EQUAL the real /prices-history vocabulary
    (probed 2026-09-20: interval=5m -> HTTP 400 naming the known values).
    Set equality (L-0023: the list order is presentation, not contract).
    The rest of the resolution property (type/description/default) stays
    the pre-slice values (anti-over-fix for E1 itself)."""
    resolution = _resolution_param_schema()
    enum = resolution.get("enum")
    assert isinstance(enum, list) and enum, f"resolution enum missing: {enum!r}"
    assert set(enum) == WIRE_KNOWN_INTERVALS, (
        f"declared resolution enum {sorted(enum)!r} diverges from the wire "
        f"vocabulary {sorted(WIRE_KNOWN_INTERVALS)!r}"
    )
    assert resolution.get("type") == "string"
    assert resolution.get("default") == "1h"
    assert resolution.get("description") == "Time resolution (default: 1h)"


def test_five_minute_removed_everywhere():
    """``5m`` is absent from every surface that ADVERTISES resolutions:
    the schema enum, the docstring Args block, and TOOLS_REFERENCE.md
    (read with explicit encoding, P-0099 -- the doc carries legacy
    non-ASCII bytes). Paired positives first (L-0056): each surface exists
    and carries the ALIVE wire vocabulary before the negations are
    trusted."""
    enum = _resolution_param_schema().get("enum")
    args_block = _doc_args_block()
    ref_text = TOOLS_REFERENCE.read_text(encoding="utf-8")
    resolution_lines = [
        line for line in ref_text.splitlines() if '"resolution": "enum[' in line
    ]
    assert len(resolution_lines) == 1, (
        f"expected exactly one resolution enum line in TOOLS_REFERENCE.md, "
        f"got {len(resolution_lines)}: {resolution_lines!r}"
    )
    ref_resolution_line = resolution_lines[0]

    # Paired positives (L-0056): the alive vocabulary is present in every
    # surface (the two NEW values are the discriminating presence pins).
    assert enum and all(value in enum for value in ("1m", "1h", "6h", "1d", "1w"))
    assert "'1w'" in args_block and "'6h'" in args_block
    assert "'1w'" in ref_resolution_line and "'6h'" in ref_resolution_line

    # Negations: the false advertisement is gone from every advertising
    # surface (5m was present in all three before the fix -- RED pre).
    assert "5m" not in enum
    assert "5m" not in args_block
    assert "5m" not in ref_text

    # The probe provenance survives in the docstring (E2 note, positive).
    assert "rejects unknown intervals" in market_analysis.get_price_history.__doc__


async def test_resolution_remains_inert_in_placeholder():
    """Zero semantics: the placeholder body never reads the parameter, so
    the (now wire-corrected) declaration changes NO behavior. GREEN before
    AND after this slice. Flips RED when item 154 lands: forwarding
    resolution -> interval diverges the two calls, and the fixer must
    update this pin in the SAME change (consumer<->producer, L-0073)."""
    result_5m = await market_analysis.get_price_history(token_id="t", resolution="5m")
    result_1h = await market_analysis.get_price_history(token_id="t", resolution="1h")

    assert result_5m == result_1h, (
        "resolution started to influence the placeholder output -- item 154 "
        "forwarding landed; update this inertia pin in the same change"
    )
    # Non-vacuo discriminator: both calls really hit the placeholder path.
    assert isinstance(result_5m, list) and result_5m and "error" in result_5m[0]


def test_other_schemas_unchanged():
    """Anti-over-fix: ONLY the resolution enum changed in the registry.
    The side enum of get_current_price and the depth schema of
    get_orderbook are byte-identical to the pre-slice values; the
    get_market_holders schema is untouched; the per-tool census
    (parameter names + required) is unchanged for every tool."""
    tools = {tool.name: tool for tool in market_analysis.get_tools()}
    schemas = {name: tool.inputSchema for name, tool in tools.items()}

    assert schemas["get_current_price"]["properties"]["side"]["enum"] == [
        "BUY",
        "SELL",
        "BOTH",
    ]
    assert schemas["get_orderbook"]["properties"]["depth"] == {
        "type": "integer",
        "minimum": 1,
        "description": "Number of price levels per side (default 20)",
        "default": 20,
    }
    assert schemas["get_market_holders"] == {
        "type": "object",
        "properties": {
            "market_id": {"type": "string", "description": "Market ID"},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Number of top holders (default 10)",
                "default": 10,
            },
        },
        "required": ["market_id"],
    }

    census = {
        name: (sorted(schema.get("properties", {})), schema.get("required"))
        for name, schema in schemas.items()
    }
    assert census == {
        "analyze_market_opportunity": (["market_id"], ["market_id"]),
        "compare_markets": (["market_ids"], ["market_ids"]),
        "get_current_price": (["side", "token_id"], ["token_id"]),
        "get_liquidity": (["market_id"], ["market_id"]),
        "get_market_details": (["condition_id", "market_id", "slug"], []),
        "get_market_holders": (["limit", "market_id"], ["market_id"]),
        "get_market_volume": (["market_id", "timeframes"], ["market_id"]),
        "get_orderbook": (["depth", "token_id"], ["token_id"]),
        "get_price_history": (
            ["end_date", "resolution", "start_date", "token_id"],
            ["token_id"],
        ),
        "get_spread": (["token_id"], ["token_id"]),
    }


# ---------------------------------------------------------------------------
# Live integration greens - the REAL /prices-history vocabulary
# (marked integration ONLY; transport guard never fails the suite for infra)
# ---------------------------------------------------------------------------
def _skip_on_transport(exc, label):
    """Network guard: infra failures SKIP (never fail the suite for infra)."""
    pytest.skip(f"{label} unreachable ({type(exc).__name__}: {exc})")


def _check_response(response, label):
    """Fail-closed response check: 5xx is an API-side outage (documented
    skip); any other non-200 is a live-contract violation (FAIL)."""
    if response.status_code >= 500:
        pytest.skip(f"{label}: live API outage (HTTP {response.status_code})")
    assert response.status_code == 200, (
        f"{label}: expected HTTP 200, got {response.status_code}"
    )


async def _derive_live_token(client):
    """Harvest the CLOB token id LIVE from the gamma feed - never a literal
    (a 64-hex constant in this file would pin a volatile token; the suite
    must follow the live market). Skip is reserved for degenerate feed
    slices (infra-ish), never for a contract violation."""
    try:
        response = await client.get(f"{GAMMA_API_URL}/markets", params={"limit": 1})
    except (httpx.HTTPError, OSError) as exc:
        _skip_on_transport(exc, "gamma /markets")
    _check_response(response, "gamma /markets")
    markets = response.json()
    assert isinstance(markets, list) and markets, "gamma /markets returned no markets"
    raw = markets[0].get("clobTokenIds")
    try:
        token_id = json.loads(raw)[0]
    except (json.JSONDecodeError, TypeError, IndexError):
        pytest.skip(
            "gamma /markets: top market without a parseable clobTokenIds (degenerate slice)"
        )
    if not isinstance(token_id, str) or not token_id:
        pytest.skip("gamma /markets: top market without a usable token id (degenerate slice)")
    return token_id


@pytest.mark.integration
async def test_live_wire_rejects_5m():
    """Live pin of the REJECTED value (ground truth of the vocabulary):
    interval=5m answers HTTP 400 with the specific unknown-interval error
    naming the REAL known values. The token is derived live from the
    gamma feed (never a literal). P-0219: error-status pins carry the
    try/except guard ONLY -- a 5xx outage fails loud instead of skipping
    (the vocabulary cannot be verified during an outage)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        token_id = await _derive_live_token(client)
        try:
            response = await client.get(
                f"{CLOB_API_URL}/prices-history",
                params={"market": token_id, "interval": "5m"},
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "CLOB /prices-history")
    assert response.status_code == 400, (
        f"interval=5m must be rejected with HTTP 400, got {response.status_code} "
        "-- the wire vocabulary changed; re-derive WIRE_KNOWN_INTERVALS and "
        "the declared contract surfaces"
    )
    body_text = str(response.json())
    assert "interval' value is unknown" in body_text, body_text


@pytest.mark.integration
async def test_live_wire_accepts_6h():
    """Live pin of the ACCEPTED value (ground truth of the vocabulary):
    interval=6h -- absent from the pre-slice declaration -- answers HTTP
    200 with a ``history`` list. The token is derived live from the gamma
    feed (never a literal). Success pin: _check_response skips 5xx
    outages and fails on any other non-200."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        token_id = await _derive_live_token(client)
        try:
            response = await client.get(
                f"{CLOB_API_URL}/prices-history",
                params={"market": token_id, "interval": "6h"},
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "CLOB /prices-history")
    _check_response(response, "CLOB /prices-history")
    body = response.json()
    assert isinstance(body.get("history"), list), (
        f"interval=6h must return a history list, got: {body!r}"
    )
