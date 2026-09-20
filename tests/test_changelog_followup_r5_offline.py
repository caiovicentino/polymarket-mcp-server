"""F1-r5: CHANGELOG follow-up - PRs #165-#179 registered in [Unreleased].

Contract (farm/T-0430): the CHANGELOG [Unreleased] sections document every
merged product PR since #165 (the r4 follow-up covered #151-#164, contract
farm/T-0403 via PR #179; r3 covered #137-#150, r2 covered #108-#136, r1
covered #86-#107).

Omissions in the #165-#179 range, with declared justification:
- #165 (T-0393, CLOSED): publish artifact closed unmerged; content
  re-published via #167.
- #169 (T-0394): test-only coverage closure (429-note helper false arcs).
- #171 (T-0400, CLOSED): first attempt closed unmerged; content published
  via #177.
- #172 (T-0399, CLOSED): first attempt closed unmerged; content published
  via #176.
- #174 (T-0403, CLOSED): first attempt closed unmerged; content published
  via #179.
- #175 (T-0410): test-only live-walk resilience (gamma 404 candidates).
- #178 (T-0422): test-only transport guard (tick-alignment live calls).
- #179 (T-0403): CHANGELOG-self update - content is the CHANGELOG itself.
"""
import pathlib

import pytest

CHANGELOG = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"

# PRs that MUST appear exactly once (merged, user-facing): the five Fixed
# entries in ascending order, then the two Changed entries.
R5_PRS = [
    166,  # T-0392 Retry-After clamp in RateLimiter.handle_429_error
    167,  # T-0393 parse_tick_size hardened for non-finite values
    168,  # T-0388-r2 install-script harness reads stdin as bytes
    170,  # T-0398 signal-delivered graceful shutdown actually runs
    176,  # T-0399 rate-limiter pass-through on pagination pages 2+
    173,  # T-0402 429-note helpers consolidated into utils/rate_limit_note
    177,  # T-0400 root-script lint hygiene (zero-semantic subset fixed)
]
# PRs that MUST stay absent, with the declared justification:
OMITTED_PRS = {
    165: "publish artifact closed unmerged (T-0393); re-published via #167",
    169: "test-only coverage closure (T-0394 429-note helper false arcs)",
    171: "first attempt closed unmerged (T-0400); content published via #177",
    172: "first attempt closed unmerged (T-0399); content published via #176",
    174: "first attempt closed unmerged (T-0403); content published via #179",
    175: "test-only live-walk resilience (T-0410 gamma 404 candidates)",
    178: "test-only transport guard (T-0422 tick-alignment live calls)",
    179: "CHANGELOG-self update (T-0403) - content is the CHANGELOG itself",
}
_ANCHORS = [
    "60-second ceiling",
    "non-finite tick sizes",
    "feeds stdin as bytes",
    "wake the event loop",
    "reaches follow-up pages",
    "Internal 429-note consolidation",
    "Root-script lint hygiene",
]


def _unreleased(text):
    """The [Unreleased] block of the CHANGELOG."""
    return text[text.index("## [Unreleased]"):text.index("## [X.Y.Z]")]


def _new_fixed_block(text):
    """The r5 delta in Fixed: lines inserted between the last r4 Fixed
    entry and the Added section, scoped to the [Unreleased] block."""
    unreleased = _unreleased(text)
    start = unreleased.index("(PR #164).") + len("(PR #164).")
    end = unreleased.index("### Added")
    return unreleased[start:end]


def _new_changed_block(text):
    """The r5 delta in Changed: lines inserted between the last existing
    Changed entry and the Planned Features section."""
    unreleased = _unreleased(text)
    start = unreleased.index("(PR #136).") + len("(PR #136).")
    end = unreleased.index("### Planned Features")
    return unreleased[start:end]


@pytest.mark.parametrize("pr", R5_PRS)
def test_pr_registered_once(pr):
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count(f"(PR #{pr})") == 1, f"PR #{pr} must appear exactly once"


@pytest.mark.parametrize("pr", sorted(OMITTED_PRS))
def test_omitted_prs_absent(pr):
    text = CHANGELOG.read_text(encoding="utf-8")
    assert f"(PR #{pr})" not in text, (
        f"PR #{pr} must stay omitted: {OMITTED_PRS[pr]}"
    )


def test_predecessor_pins_hold():
    """The r3/r4 pins survive this slice: the last entry of each
    predecessor Fixed section is still present exactly once, and the r4
    omissions stay omitted (the r4 suite pins them too; this is the
    in-slice double-check of "omissions r4 intocados")."""
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count("(PR #164)") == 1  # r4 Fixed tail (T-0403, PR #179)
    assert text.count("(PR #150)") == 1  # r3 Fixed tail (T-0390, PR #163)
    for pr in (151, 152, 153, 155, 157, 159, 161, 163):
        assert f"(PR #{pr})" not in text


def test_new_entries_ascii_only():
    """Every line carrying one of the NEW PR references is pure ASCII, and
    both inserted r5 blocks (Fixed and Changed) have zero non-ASCII bytes
    (delta-scoped form, P-0212/L-0414: the file may carry pre-existing
    non-ASCII bytes outside the delta)."""
    text = CHANGELOG.read_text(encoding="utf-8")
    for anchor in _ANCHORS:
        lines = [ln for ln in text.splitlines() if anchor in ln]
        assert lines, f"anchor {anchor!r} missing from CHANGELOG"
        for line in lines:
            assert all(ord(c) <= 127 for c in line), (
                f"non-ascii in line with {anchor!r}: {line!r}"
            )
    for block in (_new_fixed_block(text), _new_changed_block(text)):
        assert all(ord(c) <= 127 for c in block), (
            "non-ascii byte in the inserted r5 block"
        )


def test_unreleased_sections_intact():
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count("## [Unreleased]") == 1
    unreleased = _unreleased(text)
    for section in ("### Fixed", "### Added", "### Changed",
                    "### Planned Features"):
        assert unreleased.count(section) == 1, (
            f"section {section!r} must stay unique"
        )
