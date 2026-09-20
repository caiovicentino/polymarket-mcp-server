"""F1-r6: CHANGELOG follow-up - PRs #180-#192 registered in [Unreleased].

Contract (farm/T-0435): the CHANGELOG [Unreleased] sections document every
merged product PR since #180 (the r5 follow-up covered #165-#179, contract
farm/T-0430 via PR #191; r4 covered #151-#164, r3 covered #137-#150, r2
covered #108-#136, r1 covered #86-#107).

Omissions in the #180-#192 range, with declared justification:
- #180 (T-0404): test-only - restores the data-api date-params contract
  suite lost with T-0302.
- #181 (T-0417): test-only - gamma/data_api contract transport guards.
- #182 (T-0407): test-only - live-flake fix for the gamma/CLOB
  buy_sell_tol suite.
- #183 (T-0411): test-only - 429-helper false arcs (headers-None).
- #185 (T-0416): test-only - analysis-wire transport guards.
- #186 (T-0418): test-only - discovery/data-api-wire transport guards.
- #188 (T-0423): test-only - WSS transport guards.
- #189 (T-0425): test-only - E2E conformance subprocess suite.
- #191 (T-0430): CHANGELOG-self update - content is the CHANGELOG itself.
"""
import pathlib

import pytest

CHANGELOG = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"

# PRs that MUST appear exactly once (merged, user-facing): the two Fixed
# entries, the one Added entry, then the one Changed entry.
R6_PRS = [
    184,  # T-0414 exception log redaction through the shared helper
    192,  # T-0429 signal-path hardening (one-shot scheduling, try/finally)
    190,  # T-0426 markets closing soon panel on the dashboard index page
    187,  # T-0419 CI tier alignment (offline selection, informational jobs)
]
# PRs that MUST stay absent, with the declared justification:
OMITTED_PRS = {
    180: "test-only (T-0404) restores the data-api date-params contract suite lost with T-0302",
    181: "test-only (T-0417) gamma/data_api contract transport guards",
    182: "test-only (T-0407) live-flake fix for the gamma/CLOB buy_sell_tol suite",
    183: "test-only (T-0411) 429-helper false arcs (headers-None)",
    185: "test-only (T-0416) analysis-wire transport guards",
    186: "test-only (T-0418) discovery/data-api-wire transport guards",
    188: "test-only (T-0423) WSS transport guards",
    189: "test-only (T-0425) E2E conformance subprocess suite",
    191: "CHANGELOG-self update (T-0430) - content is the CHANGELOG itself",
}
_ANCHORS = [
    "Exception log redaction",
    "Signal-path hardening",
    "Markets closing soon panel",
    "CI tier alignment",
]


def _unreleased(text):
    """The [Unreleased] block of the CHANGELOG."""
    return text[text.index("## [Unreleased]"):text.index("## [X.Y.Z]")]


def _new_fixed_block(text):
    """The r6 delta in Fixed: lines inserted between the last r5 Fixed
    entry and the Added section, scoped to the [Unreleased] block."""
    unreleased = _unreleased(text)
    start = unreleased.index("(PR #176).") + len("(PR #176).")
    end = unreleased.index("### Added")
    return unreleased[start:end]


def _new_added_block(text):
    """The r6 delta in Added: lines inserted between the last existing
    Added entry and the Changed section."""
    unreleased = _unreleased(text)
    start = unreleased.index("(PR #117).") + len("(PR #117).")
    end = unreleased.index("### Changed")
    return unreleased[start:end]


def _new_changed_block(text):
    """The r6 delta in Changed: lines inserted between the last existing
    Changed entry and the Planned Features section."""
    unreleased = _unreleased(text)
    start = unreleased.index("(PR #177).") + len("(PR #177).")
    end = unreleased.index("### Planned Features")
    return unreleased[start:end]


@pytest.mark.parametrize("pr", R6_PRS)
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
    """The r5 pins survive this slice: the tails of the sections this
    slice extends are still present exactly once (the r5/r4 suites run
    separately in the acceptance commands; this is the in-slice check of
    "predecessor sections intocaveis")."""
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count("(PR #176)") == 1  # r5 Fixed tail (T-0399, PR #176)
    assert text.count("(PR #117)") == 1  # Added tail (T-0403, PR #117)
    assert text.count("(PR #177)") == 1  # r5 Changed tail (T-0400, PR #177)


def test_new_entries_ascii_only():
    """Every line carrying one of the NEW PR references is pure ASCII, and
    all three inserted r6 blocks (Fixed, Added, Changed) have zero non-ASCII
    bytes (delta-scoped form, P-0212/L-0414: the file may carry pre-existing
    non-ASCII bytes outside the delta)."""
    unreleased = _unreleased(CHANGELOG.read_text(encoding="utf-8"))
    for anchor in _ANCHORS:
        lines = [ln for ln in unreleased.splitlines() if anchor in ln]
        assert lines, f"anchor {anchor!r} missing from [Unreleased]"
        for line in lines:
            assert all(ord(c) <= 127 for c in line), (
                f"non-ascii in line with {anchor!r}: {line!r}"
            )
    text = CHANGELOG.read_text(encoding="utf-8")
    for block in (_new_fixed_block(text), _new_added_block(text),
                  _new_changed_block(text)):
        assert all(ord(c) <= 127 for c in block), (
            "non-ascii byte in the inserted r6 block"
        )


def test_self_ascii_only():
    """The suite file itself is pure ASCII (item 147: content in external
    repos must not carry non-ASCII bytes)."""
    raw = open(__file__, "rb").read()
    assert all(c <= 127 for c in raw), (
        f"non-ascii byte in {__file__}"
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
