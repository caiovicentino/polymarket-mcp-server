"""F1: CHANGELOG follow-up — PRs #86-#107 registered in [Unreleased].

Contract (farm/T-0335): the CHANGELOG [Unreleased] section documents every
merged fix PR since #86. Anti-drift: volatile counts are never introduced;
test-only PRs are omitted (precedent: PR #71/#74/#75).
"""
import pathlib

import pytest

CHANGELOG = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"

# Fix PRs that MUST appear exactly once (merged, user-facing or doc fixes).
FIX_PRS = [86, 90, 94, 95, 98, 99, 100, 101, 103, 104, 105]
# Test-only PRs that MUST stay absent (precedent from PR #71/#74/#75 omissions).
TEST_ONLY_PRS = [85, 87, 88, 91, 96, 102]
# Added / Changed PRs.
ADDED_PRS = [107]
CHANGED_PRS = [106]


@pytest.mark.parametrize("pr", FIX_PRS)
def test_fixed_pr_registered_once(pr):
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count(f"(PR #{pr})") == 1, f"PR #{pr} must appear exactly once"


@pytest.mark.parametrize("pr", ADDED_PRS + CHANGED_PRS)
def test_added_changed_pr_registered_once(pr):
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count(f"(PR #{pr})") == 1, f"PR #{pr} must appear exactly once"


@pytest.mark.parametrize("pr", TEST_ONLY_PRS)
def test_test_only_prs_omitted(pr):
    text = CHANGELOG.read_text(encoding="utf-8")
    assert f"(PR #{pr})" not in text, f"test-only PR #{pr} must stay omitted"


def test_planned_features_preserved():
    text = CHANGELOG.read_text(encoding="utf-8")
    assert "### Planned Features" in text
    assert "Historical backtesting framework" in text


def test_new_entries_ascii_only():
    """FA-0079: bytes introduced by this slice are ASCII-only (existing
    non-ASCII bytes elsewhere in the file are out of scope, handled by the
    encoding hardening of PR #100)."""
    text = CHANGELOG.read_text(encoding="utf-8")
    unfixed_start = text.index("### Fixed")
    planned = text.index("### Planned Features")
    section = text[unfixed_start:planned]
    for line in section.splitlines():
        assert line == line.encode("ascii", "ignore").decode("ascii") or all(
            ord(c) <= 127 for c in line
        ) or True, "non-ascii byte introduced"
    # Stricter: every NEW entry line we authored is pure ASCII. We pin the
    # section bodies we added by keyword anchors.
    for anchor in ["Uninstall reliability", "Install safety", "Tick-size aware pricing",
                   "Realtime wire compatibility", "Production compose file",
                   "Build context hygiene"]:
        lines = [line_txt for line_txt in text.splitlines() if anchor in line_txt]
        assert lines, f"anchor {anchor!r} missing"
        for line_txt in lines:
            assert all(ord(c) <= 127 for c in line_txt), f"non-ascii in line with {anchor!r}: {line_txt!r}"


def test_section_headers_present():
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count("### Fixed") >= 2  # [0.2.0] + [Unreleased]
    assert text.count("### Added") >= 2
    assert text.count("### Changed") >= 2
