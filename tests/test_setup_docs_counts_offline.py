"""F3: setup docs anti-drift — volatile line counts removed.

Contract (farm/T-0337): SUMMARY.md and SETUP_IMPROVEMENTS_SUMMARY.md carried
line/size counts (~670, ~800, ~2,900, 100KB+) that drifted ~30% from reality
(setup_wizard.py is 896 lines, not ~670). Anti-drift doctrine (L-0023,
precedent PR #101/#83): REMOVE volatile counts, never update them. Structural
claims (features, step lists, status) are preserved and pinned.
"""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SUMMARY = ROOT / "SUMMARY.md"
SETUP_IMPROV = ROOT / "SETUP_IMPROVEMENTS_SUMMARY.md"


@pytest.mark.parametrize("doc", [SUMMARY, SETUP_IMPROV])
def test_no_volatile_line_counts(doc):
    text = doc.read_text(encoding="utf-8")
    for pattern in ["~670", "~800", "~600", "~500", "~350", "~180", "~450",
                    "~2,900", "~3,000", "100KB"]:
        assert pattern not in text, f"{doc.name}: volatile count {pattern!r} must be removed"


def test_summary_structure_preserved():
    text = SUMMARY.read_text(encoding="utf-8")
    assert "### 1. Setup Wizard GUI" in text
    assert "### 2. Visual Installation Guide" in text
    assert "## " in text


def test_setup_improvements_structure_preserved():
    text = SETUP_IMPROV.read_text(encoding="utf-8")
    assert "### 1. GUI Setup Wizard" in text
    for deliverable in ["**Deliverable 1:**", "**Deliverable 2:**", "**Deliverable 3:**",
                        "**Deliverable 4:**", "**Deliverable 5:**", "**Deliverable 6:**",
                        "**Deliverable 7:**"]:
        assert deliverable in text, f"deliverable {deliverable!r} must stay"


def test_wizard_entry_point_documented():
    """The polymarket-setup console script exists in pyproject (item 83 keeps
    the removal/move decision with the owner) - the docs entry stays."""
    text = SUMMARY.read_text(encoding="utf-8")
    assert 'polymarket-setup' in text
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'polymarket-setup' in pyproject
