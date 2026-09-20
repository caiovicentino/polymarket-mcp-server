"""Contract honesty r3: declare the missing schema bounds (T-0444).

Series: T-0352 (schema-minimum) -> T-0439 (user-capped maximum, merged #199)
-> this slice. Wire truths proven first-hand in the mission (2026-09-20):

- /markets caps pages at 100 rows and gamma pagination runs at most
  _GAMMA_MAX_PAGES pages, so the honest declared ceiling for the paginated
  gamma tools is _GAMMA_PAGE_SIZE * _GAMMA_MAX_PAGES (== 1000). The runtime
  already pins that ceiling in test_gamma_pagination_offline.py::
  test_fetch_max_pages_guard (assert len(result) == 1000); the schema was
  silent about it (this slice fixes the silence).
- /public-search caps results per TYPE at 50 and search results are
  flattened from matching events before truncation: there is NO fixed
  global ceiling, so search_markets.limit deliberately declares NO maximum
  and the description states the per-type cap.
- compare_markets already raises ValueError for fewer than 2 and more than
  10 ids (fires before any API call); the schema now declares minItems/
  maxItems 2/10 -- a zero-semantic declaration.
- hours < 0 moves the cutoff into the past (meaningless look-behind for a
  "closing soon" tool) => minimum 1; min_value < 0 and max_actions < 1 are
  meaningless for the same class of reason => minimum 0 / minimum 1.

Every pin derives from the LIVE registries (market_discovery.get_tools(),
market_analysis.get_tools(), portfolio.PORTFOLIO_TOOLS) -- never from
hand-copied literals (anti-drift by construction). This file is part of the
suite regression net: registry renames fail loud, not silently.

RED pre-state proven first-hand against the pre-edit tree (git archive of
7e4ed3a) in the mission report: schema-bound pins fail, behavior pins
(handler raises, T-0439 maximums, unchanged signatures/defaults) pass --
discriminants by construction.
"""

import inspect

import pytest

from polymarket_mcp.tools import market_analysis, market_discovery, portfolio

_GAMMA_CEILING = market_discovery._GAMMA_PAGE_SIZE * market_discovery._GAMMA_MAX_PAGES

_PAGED_GAMMA_TOOLS = (
    "get_trending_markets",
    "filter_markets_by_category",
    "get_featured_markets",
    "get_closing_soon_markets",
    "get_sports_markets",
    "get_crypto_markets",
)


def _discovery_schema(tool_name: str) -> dict:
    """inputSchema of `tool_name` from the live discovery registry; fail loud."""
    for tool in market_discovery.get_tools():
        if tool.name == tool_name:
            return tool.inputSchema
    raise AssertionError(f"tool not found in live discovery registry: {tool_name}")


def _analysis_schema(tool_name: str) -> dict:
    """inputSchema of `tool_name` from the live analysis registry; fail loud."""
    for tool in market_analysis.get_tools():
        if tool.name == tool_name:
            return tool.inputSchema
    raise AssertionError(f"tool not found in live analysis registry: {tool_name}")


def _portfolio_entry(tool_name: str) -> dict:
    """Registry entry of `tool_name` from the live portfolio registry; fail loud."""
    for entry in portfolio.PORTFOLIO_TOOLS:
        if entry.get("name") == tool_name:
            return entry
    raise AssertionError(f"tool not found in live portfolio registry: {tool_name}")


def _paged_limits() -> list:
    """(tool_name, limit schema) pairs for the 6 paginated gamma tools."""
    out = []
    for tool in market_discovery.get_tools():
        if tool.name in _PAGED_GAMMA_TOOLS:
            limit_schema = tool.inputSchema["properties"]["limit"]
            out.append((tool.name, limit_schema))
    # Anti-vacuo guard: a renamed/dropped registry tool must fail loud here
    # instead of silently shrinking the pin set below.
    if len(out) != len(_PAGED_GAMMA_TOOLS):
        raise AssertionError(
            f"paged registry coverage degraded: {len(out)} of "
            f"{len(_PAGED_GAMMA_TOOLS)} tools found"
        )
    return out


def test_paginated_gamma_limits_declare_wire_ceiling() -> None:
    """All 6 paginated gamma tools declare maximum == _GAMMA_PAGE_SIZE * _GAMMA_MAX_PAGES."""
    failures = []
    for name, limit_schema in _paged_limits():
        declared = limit_schema.get("maximum")
        if declared != _GAMMA_CEILING:
            failures.append(f"{name}: maximum={declared!r} != {_GAMMA_CEILING!r}")
    assert not failures, (
        "paginated gamma tools missing/incorrect maximum: " + "; ".join(failures)
    )


def test_gamma_ceiling_matches_runtime_max_pages_guard() -> None:
    """The declared ceiling is the wire ceiling already pinned at runtime.

    Cross-ref: test_gamma_pagination_offline.py::test_fetch_max_pages_guard
    pins the runtime at len(result) == 1000 for limit=5000. The schema must
    declare the SAME ceiling, and this pin goes RED first if the module
    constants change without the wire re-probe (ceiling is a wire truth).
    """
    assert _GAMMA_CEILING == 1000


def test_maximum_derived_from_live_constants() -> None:
    """Anti-drift: the maximum equals the product of the LIVE module constants.

    If the constants change (e.g. wire pagination changes), schema and
    runtime move together by construction: the declared maximum is an
    expression, not a frozen literal.
    """
    live_product = market_discovery._GAMMA_PAGE_SIZE * market_discovery._GAMMA_MAX_PAGES
    assert live_product == _GAMMA_CEILING
    entries = _paged_limits()
    assert len(entries) == len(_PAGED_GAMMA_TOOLS)
    assert {limit_schema.get("maximum") for _, limit_schema in entries} == {
        _GAMMA_CEILING
    }


def test_compare_markets_minitems_2() -> None:
    schema = _analysis_schema("compare_markets")
    assert schema["properties"]["market_ids"]["minItems"] == 2


def test_compare_markets_maxitems_10() -> None:
    schema = _analysis_schema("compare_markets")
    assert schema["properties"]["market_ids"]["maxItems"] == 10


async def test_compare_markets_handler_still_raises_below_two() -> None:
    """Zero-semantic guard: the ValueError for len<2 fires before any API call."""
    with pytest.raises(ValueError, match="At least 2 markets required"):
        await market_analysis.compare_markets(["0xonly-one-id"])


async def test_compare_markets_handler_still_raises_above_ten() -> None:
    """Zero-semantic guard: the ValueError for len>10 fires before any API call."""
    with pytest.raises(ValueError, match="Maximum 10 markets"):
        await market_analysis.compare_markets([f"0xid-{i:02d}" for i in range(11)])


def test_closing_soon_hours_minimum_1() -> None:
    """hours must be at least 1: hours < 1 looks behind the cutoff."""
    schema = _discovery_schema("get_closing_soon_markets")
    assert schema["properties"]["hours"]["minimum"] == 1


def test_get_all_positions_min_value_minimum_0() -> None:
    entry = _portfolio_entry("get_all_positions")
    assert entry["inputSchema"]["properties"]["min_value"]["minimum"] == 0


def test_suggest_portfolio_actions_max_actions_minimum_1() -> None:
    entry = _portfolio_entry("suggest_portfolio_actions")
    assert entry["inputSchema"]["properties"]["max_actions"]["minimum"] == 1


def test_search_markets_limit_has_no_maximum() -> None:
    """search_markets.limit deliberately declares NO maximum (per-type cap 50).

    Paired with the positive sibling below: the absence is only meaningful
    while the description states the cap (L-0056 paired-negation rule).
    """
    limit_schema = _discovery_schema("search_markets")["properties"]["limit"]
    assert "maximum" not in limit_schema


def test_search_markets_description_states_per_type_cap_50() -> None:
    schema = _discovery_schema("search_markets")
    description = schema["properties"]["limit"]["description"]
    assert "caps results per type at 50" in description
    assert "flattened" in description


def test_tool_function_signatures_unchanged() -> None:
    """Zero-semantic: the edits declare bounds only, signatures stay untouched."""
    expected_domain_defaults = {
        market_discovery.get_trending_markets: {"timeframe": "24h", "limit": 10},
        market_discovery.filter_markets_by_category: {"active_only": True, "limit": 20},
        market_discovery.get_featured_markets: {"limit": 10},
        market_discovery.get_closing_soon_markets: {"hours": 24, "limit": 20},
        market_discovery.get_sports_markets: {"sport_type": None, "limit": 20},
        market_discovery.get_crypto_markets: {"symbol": None, "limit": 20},
        market_analysis.compare_markets: {"market_ids": inspect.Parameter.empty},
        portfolio.get_all_positions: {"min_value": 1.0, "sort_by": "value"},
        portfolio.suggest_portfolio_actions: {"goal": "balanced", "max_actions": 5},
    }
    problems = []
    for func, expected in expected_domain_defaults.items():
        signature = inspect.signature(func)
        for param_name, expected_default in expected.items():
            param = signature.parameters.get(param_name)
            if param is None:
                problems.append(f"{func.__name__}: missing param {param_name}")
            elif param.default != expected_default:
                problems.append(
                    f"{func.__name__}.{param_name}: "
                    f"default={param.default!r} != {expected_default!r}"
                )
    assert not problems, "tool function signatures drifted: " + "; ".join(problems)


def test_t0439_user_capped_maximums_intact() -> None:
    """Green guard: the T-0439 maximums (500, merged #199) survive untouched."""
    for tool_name in ("get_trade_history", "get_activity_log"):
        entry = _portfolio_entry(tool_name)
        limit_schema = entry["inputSchema"]["properties"]["limit"]
        assert limit_schema.get("maximum") == 500, (
            f"{tool_name} lost the T-0439 user-capped maximum (500)"
        )


def test_paged_tools_limit_type_and_default_unchanged() -> None:
    """Anti-over-fix: type and default stay exactly as before (additive edit)."""
    expected_defaults = {
        "get_trending_markets": 10,
        "filter_markets_by_category": 20,
        "get_featured_markets": 10,
        "get_closing_soon_markets": 20,
        "get_sports_markets": 20,
        "get_crypto_markets": 20,
    }
    entries = _paged_limits()
    assert len(entries) == len(expected_defaults)
    for name, limit_schema in entries:
        assert limit_schema["type"] == "integer", f"{name}: limit type changed"
        assert limit_schema["default"] == expected_defaults[name], (
            f"{name}: limit default drifted"
        )
