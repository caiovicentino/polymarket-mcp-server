"""F1-r2: CHANGELOG follow-up - PRs #108-#136 registered in [Unreleased].

Contract (farm/T-0381): the CHANGELOG [Unreleased] section documents every
merged fix PR since #108 (the previous follow-up covered #86-#107, contract
farm/T-0335). Anti-drift: volatile counts are never introduced; test-only
PRs, CHANGELOG-self PRs and non-farm fix(ci) commits are omitted with a
declared justification (precedent: PR #71/#74/#75 omissions in the
predecessor suite).
"""
import pathlib

import pytest

CHANGELOG = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"

# PRs that MUST appear exactly once (merged, user-facing or reference docs).
FIX_PRS = [
    110,  # T-0292 Windows CI encoding (grouped with the Windows CI entry)
    111,  # T-0308 dashboard market fields
    115,  # T-0331 windows install printf
    116,  # T-0330 test-docker MSYS guard
    119,  # T-0282 /ws crash
    120,  # T-0283 gamma pagination
    131,  # T-0373 dashboard wiring
    132,  # T-0362 rate limit backoff (trading)
    133,  # T-0336 FAQ code samples
    134,  # T-0299 connection test honesty
    135,  # T-0363 rate limit backoff (portfolio)
]
ADDED_PRS = [113, 114, 117]  # T-0273 pagination, T-0287 README, T-0279 tools ref
CHANGED_PRS = [112, 121, 130, 136]  # T-0313 hook, T-0344 pins, T-0284 makefile, T-0374 pip
# PRs that MUST stay absent, with the declared justification:
OMITTED_PRS = {
    108: "CHANGELOG-self update (T-0267) - content is the CHANGELOG itself",
    118: "test-only (T-0324 stdio robustness suite)",
    122: "docs-only internal counts (T-0337)",
    125: "non-farm fix(ci) commit",
    127: "CI test-side fix (T-0364) - internal, no user-facing surface",
    128: "CHANGELOG-self update (T-0335) - content is the CHANGELOG itself",
    129: "non-farm fix(ci) commit",
}


@pytest.mark.parametrize("pr", FIX_PRS + ADDED_PRS + CHANGED_PRS)
def test_pr_registered_once(pr):
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count(f"(PR #{pr})") == 1, f"PR #{pr} must appear exactly once"


@pytest.mark.parametrize("pr", sorted(OMITTED_PRS))
def test_omitted_prs_stay_absent(pr):
    text = CHANGELOG.read_text(encoding="utf-8")
    assert f"(PR #{pr})" not in text, (
        f"PR #{pr} must stay omitted: {OMITTED_PRS[pr]}"
    )


def test_prior_followup_pins_hold():
    """The predecessor suite's own pins keep passing (no regression to the
    #86-#107 coverage)."""
    text = CHANGELOG.read_text(encoding="utf-8")
    for pr in (86, 90, 94, 95, 98, 99, 100, 101, 103, 104, 105, 107):
        assert text.count(f"(PR #{pr})") == 1, f"PR #{pr} regression"


def test_new_entries_ascii_only():
    """Every line carrying one of the NEW PR references is pure ASCII
    (FA-0079 house rule)."""
    text = CHANGELOG.read_text(encoding="utf-8")
    anchors = [
        "Dashboard market fields", "Connection test honesty", "Dashboard wiring",
        "Rate limit backoff (trading)", "Rate limit backoff (portfolio)",
        "Gamma pagination", "WebSocket dashboard crash", "Windows install",
        "Windows docker-test", "FAQ code samples", "Data-API pagination",
        "Community directory", "Confirmation flow reference",
        "Pre-commit pytest-fast hook", "Dependency pins", "Makefile hygiene",
        "Frozen requirements",
    ]
    for anchor in anchors:
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
