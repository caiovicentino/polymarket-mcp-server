"""Contract suite for SETUP_GUIDE.md (T-0250) — doc x code consistency.

Source of truth:
- install.sh:366 writes the MCP entry name "polymarket" into
  claude_desktop_config.json ("mcpServers": {"polymarket": {...}}).
- QUICKSTART_GUIDE.md:13-14 canonizes the cloned directory name
  "polymarket-mcp-server" (git clone ... + cd polymarket-mcp-server).

SETUP_GUIDE.md must therefore NOT teach a stale entry name
("polymarket-trading"), author-machine absolute paths (/Users/caiovicentino)
or a machine-specific python path (/opt/anaconda3). Note:
WEBSOCKET_INTEGRATION.md:39 `Server("polymarket-trading")` is the MCP
protocol-level Server name (consistent with server.py:79) — NOT covered here.

Lesson alignment:
- L-0090: the counts asserted here are the observables the T-0250 contract
  declares (replace-counts 1/1/1/4/2); asserted 1:1.
- L-0148: suite COUNT totals are never pinned; this suite pins only its own
  file-level content counts, not the global suite total.
- FA-0079 / item 147b: read_text(encoding="utf-8") EXPLICIT — Windows CI
  opens files with a charmap codec by default (UnicodeDecodeError).
- P-0085: content-assertion suite over a static doc; read-only, no network,
  no writes, no seams (the doc is a repo fixture, not executable code).
- L-0056: every negative assertion is paired with a positive sibling.
"""

from pathlib import Path

SETUP_GUIDE = Path(__file__).resolve().parent.parent / "SETUP_GUIDE.md"

# Canonical offline pytest selection (T-0093 compat pin).
CANONICAL_SELECTION = "not integration and not slow and not real_api and not performance"


def _read_setup_guide() -> str:
    """Read SETUP_GUIDE.md with an explicit UTF-8 codec (FA-0079/item 147b)."""
    return SETUP_GUIDE.read_text(encoding="utf-8")


def test_no_stale_entry_name() -> None:
    """The stale MCP entry name is gone; the installed entry name present."""
    text = _read_setup_guide()
    assert text.count("polymarket-trading") == 0
    assert text.count("polymarket") >= 2


def test_log_path_matches_entry_name() -> None:
    """Claude Desktop logs at mcp-server-<entry-name>.log; entry is polymarket."""
    text = _read_setup_guide()
    assert text.count("mcp-server-polymarket.log") == 1


def test_no_author_absolute_paths() -> None:
    """No author-machine paths survive; the canonical clone-dir cd is used."""
    text = _read_setup_guide()
    assert text.count("/Users/caiovicentino") == 0
    assert text.count("/opt/anaconda3") == 0
    assert text.count("cd polymarket-mcp-server") == 4


def test_canonical_selection_preserved() -> None:
    """T-0093 compat pin: the canonical offline pytest selection survives."""
    text = _read_setup_guide()
    assert text.count(CANONICAL_SELECTION) == 1
