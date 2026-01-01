"""F1-r4: CHANGELOG follow-up - PRs #151-#164 registered in [Unreleased].

Contract (farm/T-0403): the CHANGELOG [Unreleased] Fixed section documents
every merged product PR since #151 (the r3 follow-up covered #137-#150,
contract farm/T-0390 via PR #163; r2 covered #108-#136, r1 covered #86-#107).

Omissions in the #151-#164 range, with declared justification:
- #151 (T-0325): test-only contract suite (config x execution endpoints).
- #152 (T-0339, CLOSED): first attempt closed unmerged; content published
  via #155.
- #153 (T-0380, CLOSED): first attempt closed unmerged; content published
  via #161.
- #155 (T-0339): test-only contract suite (safety gaps).
- #157 (T-0340): test-only contract suite (search pagination).
- #159 (T-0379): test-only coverage closure (trading.py tick/bump).
- #161 (T-0380): test-only coverage closure (web/app.py result-empty).
- #163 (T-0390): CHANGELOG-self update - content is the CHANGELOG itself.
"""
import pathlib

import pytest

CHANGELOG = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"

# PRs that MUST appear exactly once (merged, user-facing).
R4_PRS = [
    154,  # T-0356 429-backoff wiring (order submission)
    156,  # T-0351 Data-API positions pagination (suggest_portfolio_actions)
    158,  # T-0353 per-market over-sell as short exposure in validate_order
    160,  # T-0357 429-backoff wiring (Data-API read surface)
    162,  # T-0389 stdio child env inheritance on Windows (WinError 10106)
    164,  # T-0388 install.sh fail-loud on stdin EOF
]
# PRs that MUST stay absent, with the declared justification:
OMITTED_PRS = {
    151: "test-only contract suite (T-0325 config x execution endpoints)",
    152: "first attempt closed unmerged (T-0339); content published via #155",
    153: "first attempt closed unmerged (T-0380); content published via #161",
    155: "test-only contract suite (T-0339 safety gaps)",
    157: "test-only contract suite (T-0340 search pagination)",
    159: "test-only coverage closure (T-0379 trading.py tick/bump)",
    161: "test-only coverage closure (T-0380 web/app.py result-empty)",
    163: "CHANGELOG-self update (T-0390) - content is the CHANGELOG itself",
}
_ANCHORS = [
    "Rate-limit backoff wired into the order-submission path",
    "paginates the Data-API positions feed",
    "counted as short exposure",
    "wired into the Data-API read surface",
    "now inherits the OS environment",
    "fails loudly with a clear message",
]


def _new_fixed_block(text):
    """The r4 delta: lines inserted between the last r3 Fixed entry and the
    Added section, scoped to the [Unreleased] block."""
    unreleased = text[text.index("## [Unreleased]"):text.index("## [X.Y.Z]")]
    start = unreleased.index("(PR #150).") + len("(PR #150).")
    end = unreleased.index("### Added")
    return unreleased[start:end]


@pytest.mark.parametrize("pr", R4_PRS)
def test_pr_registered_once(pr):
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count(f"(PR #{pr})") == 1, f"PR #{pr} must appear exactly once"


@pytest.mark.parametrize("pr", sorted(OMITTED_PRS))
def test_omitted_prs_absent(pr):
    text = CHANGELOG.read_text(encoding="utf-8")
    assert f"(PR #{pr})" not in text, (
        f"PR #{pr} must stay omitted: {OMITTED_PRS[pr]}"
    )


def test_new_entries_ascii_only():
    """Every line carrying one of the NEW PR references is pure ASCII, and
    the whole inserted r4 block has zero non-ASCII bytes (P-0154a: the
    equivalent of LC_ALL=C tr -d '\\0-\\177' | wc -c == 0 over the delta)."""
    text = CHANGELOG.read_text(encoding="utf-8")
    for anchor in _ANCHORS:
        lines = [ln for ln in text.splitlines() if anchor in ln]
        assert lines, f"anchor {anchor!r} missing from CHANGELOG"
        for line in lines:
            assert all(ord(c) <= 127 for c in line), (
                f"non-ascii in line with {anchor!r}: {line!r}"
            )
    block = _new_fixed_block(text)
    assert all(ord(c) <= 127 for c in block), (
        "non-ascii byte in the inserted r4 block"
    )


def test_unreleased_sections_intact():
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count("## [Unreleased]") == 1
    # The r3 follow-up pins hold (r3 is NOT touched by this slice).
    assert text.count("(PR #150)") == 1
    unreleased = text[text.index("## [Unreleased]"):text.index("## [X.Y.Z]")]
    for section in ("### Fixed", "### Added", "### Changed",
                    "### Planned Features"):
        assert unreleased.count(section) == 1, (
            f"section {section!r} must stay unique"
        )
