"""Caps-contract pins for the user-capped Data-API tools (item 38 follow-up,
farm/T-0439; wire truth re-probed 2026-09-20, 1st hand):

- /positions?user=X&limit=501 -> 500 rows (cap 500 EXACT).
- /activity?user=X&limit=501 -> 500 rows (cap 500 EXACT).
- /trades (user path AND global feed) honor much larger limits:
  limit=1000 -> 1000, limit=5000 -> 5000, limit=10000 -> 10000 rows.
  The old docstring claim "a call WITH limit caps at 500 (proven:
  limit=1000/limit=2000 -> 500)" is FALSE for /trades -- fixed in
  src/polymarket_mcp/utils/data_api_pagination.py.

Server-side behavior (the min(limit, 500) truncation in
get_trade_history/get_activity_log) is pinned by the sibling suites
(test_portfolio_analysis_offline.py:281, test_portfolio_positions_offline.py)
and is UNCHANGED. This slice only makes the public contract HONEST: the
tool inputSchema now declares the server cap so clients (e.g. Claude) know
that requesting limit>500 yields 500, not an error and not 1000 rows.

Out of scope (register-only): the 9 gamma/CLOB tools whose limit reaches a
wire that paginates (market_discovery/market_analysis) or is a placeholder
(get_market_holders) -- their caps are a separate derivation.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import importlib  # noqa: E402

portfolio = importlib.import_module("polymarket_mcp.tools.portfolio")  # noqa: E402


def _limit_schema(tool_name):
    for tool in portfolio.PORTFOLIO_TOOLS:
        if tool["name"] == tool_name:
            return tool["inputSchema"]["properties"]["limit"]
    raise AssertionError(f"tool {tool_name} not in PORTFOLIO_TOOLS")


def test_trade_history_limit_declares_server_cap():
    """The inputSchema must declare the server-side cap (max 500) so a client
    requesting limit>500 knows the response is 500 rows, not an error."""
    lim = _limit_schema("get_trade_history")
    assert lim.get("maximum") == 500, (
        f"get_trade_history limit schema is missing the server cap: {lim!r} "
        "-- the handler truncates min(limit, 500) but the schema does not say so"
    )


def test_activity_log_limit_declares_server_cap():
    lim = _limit_schema("get_activity_log")
    assert lim.get("maximum") == 500, (
        f"get_activity_log limit schema is missing the server cap: {lim!r}"
    )


def test_limit_type_and_default_unchanged():
    """Anti-over-fix: type/default remain the pre-fix values (the cap is an
    ADDITIVE property -- the T-0352 schema-minimum pins must survive)."""
    th = _limit_schema("get_trade_history")
    al = _limit_schema("get_activity_log")
    assert th["type"] == "number" and th["default"] == 100
    assert al["type"] == "number" and al["default"] == 100


def test_pagination_docstring_reports_trades_wire_truth():
    """The fetch_all_pages docstring must NOT claim that /trades caps at 500
    (re-probed live 2026-09-20: limit=10000 -> 10000 rows); it must state the
    per-endpoint truth. Grep-level pin on the docstring itself (the wire truth
    lives in the sibling live suites; this pins the documented claim)."""
    util = importlib.import_module("polymarket_mcp.utils.data_api_pagination")
    doc = (util.__doc__ or "")
    assert "caps at 500 rows per\ncall (proven" not in doc.replace("\r\n", "\n"), (
        "fetch_all_pages docstring still claims /trades caps at 500 -- "
        "re-probed 2026-09-20: /trades honors limit=10000"
    )
    assert "trades" in doc and "500" in doc, (
        "fetch_all_pages docstring no longer mentions the per-endpoint caps"
    )
