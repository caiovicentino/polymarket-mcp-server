"""Offline suite: root docs carry the CURRENT version (0.2.0) and no volatile counts.

Bug (pre-fix, proven by curator probes on main b240bb9 -- sim/c66-preflight
@556d38d): four root docs advertised the STALE version 0.1.0 while the package
is 0.2.0 (proven by curator: src/polymarket_mcp __init__.__version__ == 0.2.0,
pyproject dynamic version, CHANGELOG 0.2.0, git tag v0.2.0 exists). Concrete
defects:
- WEB_DASHBOARD.md contradicted the code it documents: the dashboard exposes
  app.version = __version__ = 0.2.0, but the doc said 0.1.0 (:563).
- DOCKER_SUMMARY.md instructed releasing the WRONG tag: `git tag v0.1.0` +
  `git push origin v0.1.0` -- tagging v0.1.0 would re-publish the old release.
- DASHBOARD_SUMMARY.md (:529) and PROJECT_COMPLETE.md (:6) carried stale
  version claims.
- INSTALLATION_SUMMARY.md "File Changes Summary" table had a `Lines Added`
  column whose EVERY cell had drifted (config.py ~50 vs 238 real,
  .env.example ~40 vs 111, install.sh ~370, quickstart ~80, uninstall ~180,
  TEST_INSTALLATION ~450, INSTALLATION ~550, README ~100) plus a volatile
  total claim (~2,120 lines).

Fix under test (anti-drift doctrine L-0023 -- REMOVE volatile counts, never
update them; precedents T-0124/T-0166/T-0254/T-0255: the done-pile re-stales
enumerations within days):
- WEB_DASHBOARD.md: version 0.1.0 -> 0.2.0; broken test reference
  `pytest tests/test_web.py -v` (nonexistent file + bare command -- family
  L-0154a) -> `pytest tests/test_web_app_offline.py -v` (real offline suite).
- DASHBOARD_SUMMARY.md / PROJECT_COMPLETE.md: 0.1.0 -> 0.2.0 (qualitative
  suffix preserved).
- DOCKER_SUMMARY.md: release instructions now tag/push v0.2.0.
- INSTALLATION_SUMMARY.md: `Lines Added` column REMOVED (all 9 file rows
  preserved with qualitative Changes/Status cells), volatile
  `**Total Lines Added:** ~2,120...` claim REMOVED with its separating blank
  line.

House rules applied:
- L-0023: volatile numbers are asserted ABSENT, never re-hardcoded (this
  suite pins NO new counts -- only absence of volatile counts and presence of
  structural content).
- L-0056: every negation (stale string gone) is paired with the positive
  replacement (current string/row present).
- P-0099: explicit encoding="utf-8" on every doc read (Windows CI cp1252
  locale guard; repo precedent: tests/test_web_xss_offline.py).
- P-0085: read-only suite -- no network, no writes.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

WEB_DOC = REPO_ROOT / "WEB_DASHBOARD.md"
DASHBOARD_DOC = REPO_ROOT / "DASHBOARD_SUMMARY.md"
DOCKER_DOC = REPO_ROOT / "DOCKER_SUMMARY.md"
PROJECT_DOC = REPO_ROOT / "PROJECT_COMPLETE.md"
INSTALL_DOC = REPO_ROOT / "INSTALLATION_SUMMARY.md"

_VERSIONED_DOCS = (WEB_DOC, DASHBOARD_DOC, DOCKER_DOC, PROJECT_DOC)

# Structural content of the post-fix File Changes Summary table (verbatim from
# the fix). Rows are identified by their ASCII name + qualitative Changes
# cell; the pre-existing check-mark status cells are NOT asserted here (the
# emoji is pre-existing doc content, not farm-written -- FA-0085).
_INSTALL_ROWS = (
    ("config.py", "DEMO mode validation"),
    ("install.sh", "Automated installer (Unix)"),
    ("install.bat", "Automated installer (Windows)"),
    ("quickstart.sh", "One-click installer"),
    ("uninstall.sh", "Clean uninstaller"),
    (".env.example", "Updated with DEMO mode"),
    ("TEST_INSTALLATION.md", "Testing guide"),
    ("INSTALLATION.md", "User installation guide"),
    ("README.md", "Quick start section"),
)


def _web_text() -> str:
    return WEB_DOC.read_text(encoding="utf-8")


def _dashboard_text() -> str:
    return DASHBOARD_DOC.read_text(encoding="utf-8")


def _docker_text() -> str:
    return DOCKER_DOC.read_text(encoding="utf-8")


def _project_text() -> str:
    return PROJECT_DOC.read_text(encoding="utf-8")


def _install_text() -> str:
    return INSTALL_DOC.read_text(encoding="utf-8")


def _install_table(text: str) -> str:
    """The File Changes Summary table section, scoped between its anchors.

    The tilde-count guard below MUST stay scoped to this table: other
    sections legitimately contain "~40%" style performance claims (L-0154:
    out-of-scope content is never touched).
    """
    start = "### File Changes Summary"
    end = "### Code Quality"
    assert start in text, "table section anchor missing (layout drift)"
    return text.split(start, 1)[1].split(end, 1)[0]


def test_no_stale_version_010_in_four_docs() -> None:
    """L-0056 pair per doc: stale 0.1.0 ABSENT and current 0.2.0 PRESENT."""
    for doc in _VERSIONED_DOCS:
        text = doc.read_text(encoding="utf-8")
        assert "0.1.0" not in text, f"stale version 0.1.0 still in {doc.name}"
        assert "0.2.0" in text, f"current version 0.2.0 missing in {doc.name}"


def test_docker_summary_tag_instructions_current() -> None:
    """Release instructions tag v0.2.0 (L-0056 pair: v0.1.0 gone, v0.2.0 in)."""
    text = _docker_text()
    assert "git tag v0.2.0" in text
    assert "git push origin v0.2.0" in text
    assert "git tag v0.1.0" not in text
    assert "git push origin v0.1.0" not in text


def test_project_complete_version_current() -> None:
    """Version bumped to v0.2.0 with the qualitative suffix preserved."""
    text = _project_text()
    assert "v0.2.0 (com melhorias massivas)" in text
    assert "v0.1.0" not in text


def test_installation_summary_counts_column_removed() -> None:
    """`Lines Added` column gone; structural 3-column header present (pair)."""
    text = _install_text()
    assert "Lines Added" not in text
    assert "| File | Changes | Status |" in text
    table = _install_table(text)
    assert re.search(r"~\d", table) is None, "volatile count cell in table"


def test_installation_summary_files_intact() -> None:
    """All 9 file rows preserved (structural, no counts pinned)."""
    text = _install_text()
    assert "| File | Changes | Status |" in text
    for name, changes in _INSTALL_ROWS:
        row = f"| `{name}` | {changes} "
        assert row in text, f"file row missing: {name}"


def test_installation_summary_no_total_lines_claim() -> None:
    """Volatile total claim gone; section anchor preserved (L-0056 pair)."""
    text = _install_text()
    assert "**Total Lines Added:**" not in text
    assert "~2,120" not in text
    assert "### File Changes Summary" in text
