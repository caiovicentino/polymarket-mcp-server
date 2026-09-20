"""F1-r3: CHANGELOG follow-up - PRs #137-#150 registered in [Unreleased].

Contract (farm/T-0390): the CHANGELOG [Unreleased] Fixed section documents
every merged product PR since #137 (the r2 follow-up covered #108-#136,
contract farm/T-0381 via PR #148; the r1 follow-up covered #86-#107,
contract farm/T-0335 via PR #128).

Omissions in the #137-#150 range, with declared justification:
- #140 (T-0366): docs-only internal counts (anti-drift), no user-facing fix.
- #142: publish PR closed unmerged by R-UNBLOCK; content landed via #145
  (the closed #142 was the unmerged T-0298 docs attempt).
- #144 (T-0376): test-only xfail-strict suite.
- #146 (T-0304): test-only live integration greens.
- #148 (T-0381): CHANGELOG-self update; content is the CHANGELOG itself.
- #149 (T-0303): test-only wire contract suite.

PR #151 (T-0325) and PR #154 (T-0356) merged after this contract was
emitted: outside the #137-#150 slice, left for the next follow-up
(precedent: batch-per-slice anti-drift derivation).
"""
import pathlib

import pytest

CHANGELOG = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"

# PRs that MUST appear exactly once (merged, user-facing or reference docs).
FIX_PRS = [
    137,  # T-0288 resources/read MCP bug (AnyUrl == str always False)
    138,  # T-0289 config dashboard UX (422 detail + range sliders)
    139,  # T-0290 input schema bounds (minimum: 1 on depth/limit)
    141,  # T-0294 docker-compose interpolation defaults aligned to config
    143,  # T-0358 429-backoff wiring (gamma/CLOB read surface)
    145,  # T-0298 broken refs/factual typo in root docs
    147,  # T-0300 stale version claims 0.1.0 -> 0.2.0 + volatile column
    150,  # T-0307 dashboard market envelopes (trending/search)
]
# PRs that MUST stay absent, with the declared justification:
OMITTED_PRS = {
    140: "docs-only internal counts (T-0366)",
    142: "publish PR closed unmerged by R-UNBLOCK; content landed via #145",
    144: "test-only xfail-strict suite (T-0376)",
    146: "test-only live integration greens (T-0304)",
    148: "CHANGELOG-self update (T-0381) - content is the CHANGELOG itself",
    149: "test-only wire contract suite (T-0303)",
}
_ANCHORS = [
    "MCP resources/read", "Dashboard configuration UX", "Tool input validation",
    "docker-compose defaults", "Rate limit backoff (gamma/CLOB reads)",
    "Docs accuracy", "Version claims", "Dashboard market envelopes",
]


@pytest.mark.parametrize("pr", FIX_PRS)
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
    """Every line carrying one of the NEW PR references is pure ASCII
    (FA-0079 house rule)."""
    text = CHANGELOG.read_text(encoding="utf-8")
    for anchor in _ANCHORS:
        lines = [ln for ln in text.splitlines() if anchor in ln]
        assert lines, f"anchor {anchor!r} missing from CHANGELOG"
        for line in lines:
            assert all(ord(c) <= 127 for c in line), (
                f"non-ascii in line with {anchor!r}: {line!r}"
            )


def test_unreleased_sections_intact():
    text = CHANGELOG.read_text(encoding="utf-8")
    unreleased = text[text.index("## [Unreleased]"):text.index("## [X.Y.Z]")]
    assert unreleased.count("### Fixed") == 1
    assert unreleased.count("### Added") == 1
    assert unreleased.count("### Changed") == 1
