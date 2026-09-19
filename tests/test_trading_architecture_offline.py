"""Anti-drift suite for the architecture docs (T-0246).

Covers TWO docs against drift from the live code:

- ``TRADING_ARCHITECTURE.md`` must document the full tool registry as derived
  from the live tool modules. The registry is DERIVED on every run, never
  hardcoded in this suite (anti-drift, L-0023), and the doc must not pin hard
  counts of mutable tool state.
- ``CHANGELOG.md`` must cover the fixes merged upstream through PRs #47-#64
  and must not claim a "CI/CD pipeline (GitHub Actions)" planned item while
  the CI workflows are live and green on origin/main.

New tools registered in the live modules fail this suite until documented
(anti-drift); removing documented tools also fails it.
"""

import re
from pathlib import Path

from polymarket_mcp.tools import market_analysis, market_discovery, realtime
from polymarket_mcp.tools.portfolio import PORTFOLIO_TOOLS
from polymarket_mcp.tools.trading import get_tool_definitions

ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURE_DOC = ROOT / "TRADING_ARCHITECTURE.md"
CHANGELOG = ROOT / "CHANGELOG.md"

# Pointer to the canonical registry section (no hard count of mutable state).
CANONICAL_ROUTING_LINE = (
    "Tool routing (canonical registry, see Tool Registry section)"
)

# Heading of the canonical registry section; the doc must carry it and every
# registered tool must appear INSIDE it (a stray mention elsewhere in the doc
# does not document the registry — stronger than substring-anywhere).
REGISTRY_SECTION_HEADING = "## Tool Registry (canonical)"

# Anchors for the fixes merged upstream (PRs #47-#64), per entry.
MERGED_FIX_ANCHORS = (
    "OrderBookSummary",
    "handle_tool_call",
    "X-Frame-Options",
    "server/discover",
    "utcnow",
    "test-docker",
)

# Factually false planned item: the CI workflows (tests.yml, release.yml,
# docker-publish.yml) are live on origin/main, so it must not be listed as
# pending work.
FALSE_PLANNED_ITEM = "CI/CD pipeline (GitHub Actions)"

# Preservation anchor (paired negation, L-0056): genuine planned items belong
# to the owner and must survive the removal of the false one.
PRESERVED_PLANNED_ITEM = "Enhanced AI analysis tools"


def _tool_names(seq):
    """Extract tool names from dicts or objects (registry-shape agnostic)."""
    return [
        item["name"] if isinstance(item, dict) else item.name
        for item in seq
    ]


def _registry_section(body):
    """Return the canonical registry section (from its heading to the next
    ``## `` heading). Raises ValueError when the section is missing — the
    doc must carry it (fail loud, never silently empty)."""
    start = body.index(REGISTRY_SECTION_HEADING)
    tail = body[start + len(REGISTRY_SECTION_HEADING):]
    match = re.search(r"\n## ", tail)
    end = start + len(REGISTRY_SECTION_HEADING) + (match.start() if match else len(tail))
    return body[start:end]


def _live_registry():
    """Derive the canonical registry from the live tool modules.

    Returns a mapping of module name to the tool names exposed by the
    module's live registration surface.
    """
    return {
        "trading": _tool_names(get_tool_definitions()),
        "portfolio": _tool_names(PORTFOLIO_TOOLS),
        "market_discovery": _tool_names(market_discovery.get_tools()),
        "market_analysis": _tool_names(market_analysis.get_tools()),
        "realtime": _tool_names(realtime.get_tools()),
    }


def test_every_registered_tool_is_documented():
    registry = _live_registry()
    per_module = {name: len(tools) for name, tools in registry.items()}
    assert all(count > 0 for count in per_module.values()), (
        f"live registry derivation is broken (empty module lists): {per_module}"
    )
    body = ARCHITECTURE_DOC.read_text(encoding="utf-8")
    section = _registry_section(body)
    missing = [
        tool
        for tools in registry.values()
        for tool in tools
        if tool not in section
    ]
    assert missing == [], (
        f"{len(missing)} registered tool(s) absent from the "
        f"{REGISTRY_SECTION_HEADING!r} section: {missing}"
    )


def test_no_hardcoded_tool_counts():
    body = ARCHITECTURE_DOC.read_text(encoding="utf-8")
    # Positive pair (L-0056): proves the doc under test is the real one.
    assert CANONICAL_ROUTING_LINE in body
    # Paired negations: no hard counts of mutable tool state.
    assert re.search(r"\d+\s+tools\s+total", body) is None
    assert re.search(r"Total Tools:\s*\d+", body) is None


def test_changelog_covers_merged_fixes():
    body = CHANGELOG.read_text(encoding="utf-8")
    for anchor in MERGED_FIX_ANCHORS:
        assert anchor in body, f"CHANGELOG.md missing merged-fix anchor: {anchor}"
    # Paired negation (L-0056): the false planned item is gone while genuine
    # planned items survive the removal.
    assert FALSE_PLANNED_ITEM not in body
    assert PRESERVED_PLANNED_ITEM in body
