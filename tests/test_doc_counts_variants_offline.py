"""F3: variant-form doc counts anti-drift guard (P-0154).

Contract (farm/T-0366): the T-0337 guard pinned only the dominant tilde form
(~N lines / 100KB). The SAME volatile count classes survived in variant forms:
bare "(N lines)" suffixes, "+N lines" deltas, KB file sizes, and "N new files"
totals (P-0154; measured on main b690f68: DASHBOARD_SUMMARY.md 16 "lines"
matches, SETUP_IMPROVEMENTS_SUMMARY.md 3 "lines" + 7 KB matches). Anti-drift
doctrine (L-0023/P-0105): REMOVE volatile counts, never update them. The
structural claims (4 pages, Quick start guide, file names of the B2 tree,
template section headers A3) are preserved and pinned.

The suite only READS the two docs (content anchors, never file:line
references - L-0070/L-0141). A session-scoped read-only tripwire (P-0013)
proves the run does not mutate either file.
"""

import hashlib
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "DASHBOARD_SUMMARY.md"
SETUP_IMPROV = ROOT / "SETUP_IMPROVEMENTS_SUMMARY.md"

# Variant count forms (P-0154) - volatile claim classes beyond the dominant
# tilde form. Absence is asserted on BOTH docs (superset of the acceptance
# grep "[0-9][0-9,.+]* lines": whitespace-insensitive between number and unit).
COUNT_PATTERNS = [
    r"[0-9][0-9,.+]*\s*lines",
    r"[0-9.]+KB",
    r"12 new files",
    r"12 files",
    r"\*\*3,695",
    r"\*\*12 files\*\*",
    r"\+2900",
    r"2,900\+",
]


@pytest.fixture(scope="session", autouse=True)
def _docs_read_only_guard():
    """P-0013 read-only tripwire: this suite never writes the two docs."""
    docs = (DASHBOARD, SETUP_IMPROV)
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in docs}
    yield
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in docs}
    assert after == before, (
        "read-only guard violated: doc digests changed during the suite run "
        f"(before={before}, after={after})"
    )


@pytest.mark.parametrize("pattern", COUNT_PATTERNS)
def test_dashboard_no_variant_count_forms(pattern):
    text = DASHBOARD.read_text(encoding="utf-8")
    matches = re.findall(pattern, text)
    assert not matches, (
        f"DASHBOARD_SUMMARY.md: variant count form {pattern!r} found {matches!r} "
        "- REMOVE, never update (L-0023/P-0105)"
    )


@pytest.mark.parametrize("pattern", COUNT_PATTERNS)
def test_setup_improvements_no_variant_count_forms(pattern):
    text = SETUP_IMPROV.read_text(encoding="utf-8")
    matches = re.findall(pattern, text)
    assert not matches, (
        f"SETUP_IMPROVEMENTS_SUMMARY.md: variant count form {pattern!r} found "
        f"{matches!r} - REMOVE, never update (L-0023/P-0105)"
    )


def test_dashboard_structural_claims_preserved():
    """A2/A3/A4/A7: the structural totals, headers, paths and feature labels
    survive WITHOUT the volatile counts."""
    text = DASHBOARD.read_text(encoding="utf-8")
    assert text.count("4 pages") == 1, (
        f"DASHBOARD_SUMMARY.md: structural total '4 pages' must appear exactly "
        f"once (found {text.count('4 pages')})"
    )
    for template in ("index.html", "config.html", "markets.html", "monitoring.html"):
        assert re.search(rf"^#### {re.escape(template)}$", text, re.M), (
            f"DASHBOARD_SUMMARY.md: template header '#### {template}' must stay "
            "without a line count"
        )
    for path in (
        "/src/polymarket_mcp/web/app.py",
        "/src/polymarket_mcp/web/static/css/style.css",
        "/src/polymarket_mcp/web/static/js/app.js",
        "WEB_DASHBOARD.md",
    ):
        assert path in text, f"DASHBOARD_SUMMARY.md: path {path!r} must stay"
    for label in ("Pages:", "Charts:", "Interactive Forms:", "Modals:", "Real-time Updates:"):
        assert label in text, f"DASHBOARD_SUMMARY.md: feature label {label!r} must stay"


def test_setup_improvements_structural_claims_preserved():
    """B1/B2: the structural bonus entry and the 7 file names of the final
    file structure tree survive WITHOUT sizes/counts (tree-anchored pins)."""
    text = SETUP_IMPROV.read_text(encoding="utf-8")
    assert text.count("Quick start guide") == 1, (
        f"SETUP_IMPROVEMENTS_SUMMARY.md: structural bonus 'Quick start guide' "
        f"must appear exactly once (found {text.count('Quick start guide')})"
    )
    for name in (
        "setup_wizard.py",
        "QUICKSTART_GUIDE.md",
        "VISUAL_INSTALL_GUIDE.md",
        "FAQ.md",
        "DEMO_VIDEO_SCRIPT.md",
        "INSTALLATION_COMPARISON.md",
        "SUMMARY.md",
    ):
        assert re.search(rf"^├── {re.escape(name)}", text, re.M), (
            f"SETUP_IMPROVEMENTS_SUMMARY.md: file structure entry {name!r} must stay"
        )
