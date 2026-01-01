"""Schema-bounds contract suite for market_discovery + trading tools (T-0352).

14 numeric tool parameters lacked bounds: the SDK accepted any number and the
degenerate behavior was silent (limit=0 -> empty slice after a full-page
fetch; limit=-5 -> slice [:-5] = 15 rows; hours=0 -> cutoff == now; hours=-24
-> only already-ended markets surface as "closing soon"; max_budget=0 ->
size_per_order=0 -> confusing downstream error; target_size negative ->
meaningless adjustment; max_slippage=2.0 -> max_price 3x mid).

Precedent (contract inputs): T-0290 (market_analysis) proved the pattern --
``minimum: 1`` in the inputSchema is enforced by the SDK's call_tool
(jsonschema.validate BEFORE the handler), so the tools/call path makes ZERO
network by construction (stdio probe: ``isError`` result whose text contains
``minimum of 1``).

Derivation discipline (L-0002/L-0219): every pin reads the REAL registry via
``market_discovery.get_tools()`` / ``get_tool_definitions()`` -- never a
literal snapshot.

Observed RED pre-fix (measured 1st-hand on farm/T-0352 at the suite-only
commit, before the schema edits): 16 failed / 1 passed / 1 skipped --
the 14 parametrized pins + the jsonschema probe + the diff-guard fail; the
defaults-guard passes; the stdio probe SKIPs with the explicit reason below
(derived check, L-0026/L-0094 honest skip-of-infra) and turns GREEN post-fix.
Post-fix arithmetic (L-0320, re-derived at claim -- the contract's snapshot
825 pre-dated merges T-0337/T-0344): base re-proved on the fork b690f68 =
835 passed / 147 deselected / 27 xfailed; the fatia's delta is +18 collected
(14 parametrized + 4 singles), so the post-fix full-suite target is
853 passed / 147 deselected / 27 xfailed.

Greps after the fix (per-file, L-0323): market_discovery.py ``minimum`` == 8
(all new), trading.py ``minimum`` == 9 (3 pre-existing: price min/max pair +
2 size minimums -- and 6 new), ``maximum`` == 2 (1 pre-existing + 1 new on
rebalance_position.max_slippage).

Cross-platform (L-0316): the stdio probe uses ``sys.executable`` (portable),
merges ``SystemRoot`` into the child env when ``os.name == "nt"``, and reads
pipes as utf-8 (P-0099).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from polymarket_mcp.tools import market_discovery
from polymarket_mcp.tools.trading import get_tool_definitions

REPO_ROOT = Path(__file__).resolve().parent.parent

# Fork point of farm/T-0352 (= origin/main of the clone at claim time,
# b690f68). The diff-guard below is STRICT only on this branch: fork..HEAD is
# the fatia's delta there. On any other branch (e.g. main post-merge, where
# fork..HEAD would include other tasks' changes to these files) the guard
# SKIPs with an explicit reason instead of false-failing.
FORK_POINT = "b690f68a77321ced5d58c16e1aa82876abec9747"

_TIMEOUT = 30  # watchdog for the whole stdio flow (server never closes stdout)

# protocolVersion as negotiated by the SDK-era handshake (same pin as T-0290).
_PROTOCOL_VERSION = "2025-06-18"

# (tool_name, param, expected_minimum, expected_maximum_or_None)
DISCOVERY_BOUNDS = [
    ("search_markets", "limit", 1, None),
    ("get_trending_markets", "limit", 1, None),
    ("filter_markets_by_category", "limit", 1, None),
    ("get_featured_markets", "limit", 1, None),
    ("get_closing_soon_markets", "hours", 1, None),
    ("get_closing_soon_markets", "limit", 1, None),
    ("get_sports_markets", "limit", 1, None),
    ("get_crypto_markets", "limit", 1, None),
]

TRADING_BOUNDS = [
    ("create_limit_order", "expiration", 1, None),
    ("suggest_order_price", "size", 0.01, None),
    ("get_order_history", "limit", 1, None),
    ("execute_smart_trade", "max_budget", 0.01, None),
    ("rebalance_position", "target_size", 0, None),
    ("rebalance_position", "max_slippage", 0, 1),
]


def _schema_of(tools, name):
    """Derive the inputSchema from the REAL registry (L-0002: no snapshots)."""
    for tool in tools:
        if tool.name == name:
            return tool.inputSchema
    raise AssertionError(f"tool {name!r} not found in registry")


@pytest.mark.parametrize("tool,param,minimum,maximum", DISCOVERY_BOUNDS)
def test_discovery_numeric_params_have_minimum(tool, param, minimum, maximum):
    schema = _schema_of(market_discovery.get_tools(), tool)
    prop = schema["properties"][param]
    assert prop.get("minimum") == minimum, (
        f"{tool}.{param}: expected minimum={minimum}, got {prop.get('minimum')!r}"
    )
    if maximum is not None:
        assert prop.get("maximum") == maximum


@pytest.mark.parametrize("tool,param,minimum,maximum", TRADING_BOUNDS)
def test_trading_numeric_params_have_minimum(tool, param, minimum, maximum):
    schema = _schema_of(get_tool_definitions(), tool)
    prop = schema["properties"][param]
    assert prop.get("minimum") == minimum, (
        f"{tool}.{param}: expected minimum={minimum}, got {prop.get('minimum')!r}"
    )
    if maximum is not None:
        assert prop.get("maximum") == maximum


def test_schema_rejects_degenerate_values_via_jsonschema():
    jsonschema = pytest.importorskip("jsonschema")

    trending = _schema_of(market_discovery.get_tools(), "get_trending_markets")
    closing = _schema_of(market_discovery.get_tools(), "get_closing_soon_markets")
    rebalance = _schema_of(get_tool_definitions(), "rebalance_position")

    for schema, bad in [
        (trending, {"limit": 0}),
        (trending, {"limit": -5}),
        (closing, {"hours": 0}),
    ]:
        with pytest.raises(jsonschema.ValidationError, match="minimum of 1"):
            jsonschema.validate(instance=bad, schema=schema)

    # rebalance_position requires market_id: include it (valid) so the error
    # surfaces on the bounded property, not on the required-field check.
    rebalance_required = {"market_id": "0x" + "ab" * 20}
    with pytest.raises(jsonschema.ValidationError, match="greater than the maximum"):
        jsonschema.validate(
            instance={**rebalance_required, "max_slippage": 1.5}, schema=rebalance
        )

    # Paired acceptance (L-0056): 0 is the CLOSE semantic -- accepted.
    jsonschema.validate(
        instance={**rebalance_required, "target_size": 0}, schema=rebalance
    )


def test_default_values_preserved():
    """Anti-over-fix guard: the fatia adds bounds, never changes defaults."""
    trending = _schema_of(market_discovery.get_tools(), "get_trending_markets")
    closing = _schema_of(market_discovery.get_tools(), "get_closing_soon_markets")
    sports = _schema_of(market_discovery.get_tools(), "get_sports_markets")
    rebalance = _schema_of(get_tool_definitions(), "rebalance_position")
    history = _schema_of(get_tool_definitions(), "get_order_history")

    assert trending["properties"]["limit"]["default"] == 10
    assert closing["properties"]["hours"]["default"] == 24
    assert closing["properties"]["limit"]["default"] == 20
    assert sports["properties"]["limit"]["default"] == 20
    assert history["properties"]["limit"]["default"] == 100
    assert rebalance["properties"]["max_slippage"]["default"] == 0.02


def _stdio_call(arguments, cwd):
    """Spawn the real MCP server over stdio, initialize, call one tool.

    Returns the raw stdout responses. Hermeticity (transparency, T-0290): the
    tools/call path makes ZERO network by construction (the SDK's jsonschema
    validation rejects the arguments BEFORE the handler runs). The SERVER
    STARTUP performs one read-only credential-creation attempt
    (POST /auth/api-key -> observed 400) as pre-existing lifecycle behavior.

    Credential scrub (r2, P1-01 arch fix): the child env is a minimal LITERAL
    (DEMO_MODE/PYTHONPATH/PATH, T-0290 mechanism) -- host credentials
    (POLYMARKET_*/POLYGON_*) never reach the server by construction, so
    ``has_api_credentials()`` is False (pure env-check, config.py) and the
    shutdown path falls into "Skipping order cancellation (no API
    credentials)" instead of a real ``cancel_all_orders()`` mutation.

    I/O mechanics: the server NEVER closes stdout, so a plain readline loop
    hangs (proven in the curator preflight) -- ``communicate`` with a timeout
    plus a drain of the partial output on TimeoutExpired is the prescribed
    pattern (the drained buffer carries the responses produced so far).
    """
    env = {
        "DEMO_MODE": "true",
        "PYTHONPATH": str(REPO_ROOT / "src"),  # shadows editable install, P-0019
        "PATH": os.environ.get("PATH", os.defpath),
    }
    if os.name == "nt":
        # win env merge: SystemRoot must survive (bpo-34204 class, L-0316)
        env.setdefault("SystemRoot", os.environ.get("SYSTEMROOT", "C:\\Windows"))

    proc = subprocess.Popen(
        [sys.executable, "-m", "polymarket_mcp.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),  # pristine tmp cwd: no .env, P-0037
        env=env,
        text=True,
        encoding="utf-8",
    )

    initialize = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": _PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "probe", "version": "0"},
        },
    })
    initialized = '{"jsonrpc":"2.0","method":"notifications/initialized"}'
    call = json.dumps({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "get_trending_markets", "arguments": arguments},
    })

    payload = "\n".join((initialize, initialized, call)) + "\n"
    try:
        outs, _errs = proc.communicate(input=payload, timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        # The server keeps stdout open by design; drain what it produced.
        proc.kill()
        outs, _errs = proc.communicate()
    return outs or ""


def test_stdio_enforcement_get_trending_limit_zero(tmp_path):
    """SDK call_tool rejects limit=0 BEFORE the handler (isError result whose
    text contains "minimum of 1" -- the enforcement proof end-to-end)."""
    # Derived skip (L-0026/L-0094): pre-fix the minimum is absent and the
    # tool would execute -- SKIP with an explicit reason, GREEN post-fix.
    schema = _schema_of(market_discovery.get_tools(), "get_trending_markets")
    if schema["properties"]["limit"].get("minimum") != 1:
        pytest.skip("schema minimum not yet applied (pre-fix state)")

    responses = _stdio_call({"limit": 0}, cwd=tmp_path)

    assert '"isError": true' in responses or '"isError":true' in responses
    assert "minimum of 1" in responses


def test_no_logic_lines_changed():
    """Schema-only fatia: the diff against the fork point adds exactly the 14
    bound lines (15 diff lines: max_slippage gets minimum+maximum) and touches
    no executable code.

    Branch-scoped by design: strict on farm/T-0352 only. On any other branch
    (main post-merge) fork..HEAD is no longer the fatia's delta, so the guard
    SKIPs with an explicit reason instead of false-failing.
    """
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, cwd=REPO_ROOT, check=True,
    ).stdout.strip()
    if branch != "farm/T-0352":
        pytest.skip(
            f"diff-guard is branch-scoped (current branch: {branch!r}); "
            "strict only on the fatia branch farm/T-0352"
        )

    paths = [
        "src/polymarket_mcp/tools/market_discovery.py",
        "src/polymarket_mcp/tools/trading.py",
    ]
    diff = subprocess.run(
        ["git", "diff", "--numstat", FORK_POINT, "HEAD", "--", *paths],
        capture_output=True, text=True, cwd=REPO_ROOT, check=True,
    ).stdout.strip()
    assert diff == (
        "8\t0\tsrc/polymarket_mcp/tools/market_discovery.py\n"
        "7\t0\tsrc/polymarket_mcp/tools/trading.py"
    ), f"unexpected numstat (expected 8/0 and 7/0): {diff!r}"
    full = subprocess.run(
        ["git", "diff", FORK_POINT, "HEAD", "--", *paths],
        capture_output=True, text=True, cwd=REPO_ROOT, check=True,
    ).stdout
    added = [
        line[1:] for line in full.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    for forbidden in ("await ", "def ", "return "):
        assert not any(forbidden in line for line in added), (
            f"added lines contain executable code token {forbidden!r}"
        )
