"""Anti-drift suite for the Confirmation Flow documentation (T-0279).

Covers ``TOOLS_REFERENCE.md`` against drift from the live confirmation gate
in ``src/polymarket_mcp/tools/trading.py`` (R3, PR #56):

- The Confirmation Flow section must document the gate for the four order
  tools that accept ``confirm`` (create_limit_order, create_market_order,
  execute_smart_trade, rebalance_position): the ``confirmation_required``
  status, the re-call semantics (``confirm=true`` executes), and the config
  pair that drives it (``ENABLE_AUTONOMOUS_TRADING`` /
  ``REQUIRE_CONFIRMATION_ABOVE_USD``).
- The scope note must not pin a hard tool count (anti-drift, L-0023): the
  reference lists the Trading family by name instead of promising "N tools,
  below" while the trading family is a one-liner list.
- The batch behavior must be documented: ``create_batch_orders`` counts
  ``awaiting_confirmation`` entries and returns a ``confirmation_required``
  status when nothing was placed.
- The discovery/analysis sections must remain intact (no collateral edits)
  and the doc must not introduce a "NO MOCKS" claim or new hard counts.

Every file read uses ``encoding="utf-8"`` (the doc carries legacy non-ASCII
bytes; a bare read_text() breaks on Windows CI).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "TOOLS_REFERENCE.md"

# The four order tools that accept `confirm` (schemas in trading.py:
# create_limit_order/create_market_order/execute_smart_trade/rebalance_position).
CONFIRM_TOOLS = (
    "create_limit_order",
    "create_market_order",
    "execute_smart_trade",
    "rebalance_position",
)

# Heading of the Confirmation Flow section (content anchor, never a line
# number): all confirm-gate documentation must live INSIDE this section
# (stronger than substring-anywhere, P-0048/L-0109).
CONFIRM_SECTION_HEADING = "### Confirmation Flow (Trading)"

# Pre-existing content anchors (pin of absence of collateral edits).
DISCOVERY_HEADING = "#### Market Discovery (8 tools)"
FIRST_DISCOVERY_TOOL = "1. search_markets"

# Pre-existing family headers that keep the structure covered (these carry
# counts from before this suite; they are not the scope note and stay).
FAMILY_HEADERS = (
    "#### Order Creation (4 tools)",
    "#### Order Management (6 tools)",
    "#### Smart Trading (2 tools)",
    "#### Market Discovery (8 tools)",
    "#### Market Analysis (10 tools)",
)

# The scope-note marker (unique in the doc).
SCOPE_NOTE_MARKER = "**Scope note**:"

# Hard-count pattern: any digit-group followed by "tools" (e.g. "30 tools").
# The scope note must never promise a hard count of mutable tool state.
HARD_TOOL_COUNT = re.compile(r"\d+\s+tools")

# Regression pin for the specific stale phrase that was removed.
STALE_COUNT_LITERAL = "30 tools"

# Claim the doc must NOT introduce (testing policy belongs to TESTING.md).
FORBIDDEN_TEST_CLAIM = "NO MOCKS"


def _doc_text() -> str:
    """Read the doc with an explicit encoding (Windows-safe, item 147)."""
    return DOC.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """Return the block from `heading` to the next same-level heading.

    Fails loud (ValueError) when the heading is missing: the section is the
    load-bearing anchor, not a decoration.
    """
    start = text.index(heading)
    rest = text[start + len(heading):]
    match = re.search(r"\n### ", rest)
    if match is None:
        return text[start:]
    return text[start:start + len(heading) + match.start()]


def _scope_note(text: str) -> str:
    """Return the scope-note paragraph (from its marker to the next heading)."""
    start = text.index(SCOPE_NOTE_MARKER)
    end = text.find("\n### ", start)
    if end == -1:
        return text[start:]
    return text[start:end]


def _one_liner(text: str, tool: str) -> bool:
    """True when a single line names the tool AND marks it supports `confirm`."""
    return any(
        tool in line and "supports `confirm`" in line
        for line in text.splitlines()
    )


def test_confirmation_flow_documented():
    """The gate is documented: status, re-call semantics, and the 4 tools."""
    text = _doc_text()

    # Doc mentions the canonical R3 semantics (test_safety_r3.py pins the
    # gate; the doc must speak the same language).
    assert "confirmation_required" in text
    assert "confirm" in text

    section = _section(text, CONFIRM_SECTION_HEADING)

    # All four confirm tools co-occur with the section (each is named inside
    # it, not merely mentioned somewhere else in the doc).
    for tool in CONFIRM_TOOLS:
        assert tool in section, f"{tool} missing from the Confirmation Flow section"

    # Re-call semantics documented (canonical wording of the gate).
    assert "confirm=true" in section

    # The config pair that drives the gate is documented (derived from
    # config.py: ENABLE_AUTONOMOUS_TRADING / REQUIRE_CONFIRMATION_ABOVE_USD).
    assert "ENABLE_AUTONOMOUS_TRADING" in section
    assert "REQUIRE_CONFIRMATION_ABOVE_USD" in section


def test_no_hard_tool_count_in_scope_note():
    """The scope note promises detail, not a hard count (anti-drift, L-0023)."""
    text = _doc_text()
    note = _scope_note(text)

    # Negation (paired with the structure positives below, L-0056): no hard
    # tool count in the scope note - neither the generic pattern nor the
    # specific stale literal that used to promise "in detail (30 tools,
    # below)".
    assert HARD_TOOL_COUNT.search(note) is None
    assert STALE_COUNT_LITERAL not in note

    # Positive: the family structure is still covered by the existing
    # headers (discovery/analysis in detail; trading sub-families present).
    for header in FAMILY_HEADERS:
        assert header in text, f"family header missing: {header}"


def test_batch_orders_awaiting_confirmation_documented():
    """Batch behavior derived from trading.py: per-entry awaiting count."""
    text = _doc_text()
    section = _section(text, CONFIRM_SECTION_HEADING)

    # The batch tool is named inside the section...
    assert "create_batch_orders" in section
    # ...and the per-entry awaiting semantics are documented (trading.py:
    # the batch result carries awaiting_confirmation and returns a
    # confirmation_required status when nothing was placed).
    assert "awaiting_confirmation" in section
    assert "confirmation_required" in section


def test_no_mock_free_zone_intact():
    """Coherence spot: no new claims/counts; discovery/analysis intact."""
    text = _doc_text()

    # Negation: the doc must not introduce a "NO MOCKS" claim (testing
    # policy belongs to TESTING.md; this reference describes tools).
    assert FORBIDDEN_TEST_CLAIM not in text

    # Negation (paired): the scope note introduces no new hard count.
    assert HARD_TOOL_COUNT.search(_scope_note(text)) is None

    # Positive anchors: the discovery/analysis sections are intact (no
    # collateral edit while documenting the confirm gate).
    assert DISCOVERY_HEADING in text
    assert FIRST_DISCOVERY_TOOL in text

    # Coherence: the 4 confirm-supporting tools are annotated in their
    # existing one-liners (the inventory names them with the capability).
    for tool in CONFIRM_TOOLS:
        assert _one_liner(text, tool), (
            f"one-liner for {tool} does not carry the supports `confirm` mark"
        )
