"""F1-r7: CHANGELOG follow-up - PRs #193-#200 registered in [Unreleased].

Contract (farm/T-0443): the CHANGELOG [Unreleased] Fixed section documents
every merged product PR since #192 (the r6 follow-up covered #180-#192,
contract farm/T-0435 via PR #197; r5 covered #165-#179, r4 #151-#164,
r3 #137-#150, r2 #108-#136, r1 #86-#107).

Fixed x4 in this range:
- #194 (T-0434): dashboard route inventory - the closing-soon route was
  live but undocumented; the root inventory script covers all 14 routes.
- #196 (T-0437): CI documentation claims corrected (informational/gating
  mismatch, stale unit-step claim) + last author-path reference removed.
- #199 (T-0439): user-capped tool contracts - maximum: 500 declared on the
  data-api user tools; the /trades cap claim corrected.
- #200 (T-0440): dashboard error surfacing - the five data routes propagate
  tool error envelopes as 500 {"detail": ...}.

Omissions in the #193-#200 range, with declared justification:
- #193 (T-0433): test-only - the /spread and /midpoint wire-truth contract
  suite (the get_spread xfail-strict target of the item-138 fix).
- #195 (T-0421): test-only - the /positions market-filter live-contract
  derivation (padded/sports cids); the fix is test-side.
- #197 (T-0435): CHANGELOG-self update - content is the CHANGELOG itself.
- #198 (T-0441): test-only - the ASCII-guard portability fix; the
  CI-unblocking effect is tracked by the M-1 criterion, not the CHANGELOG.
"""
import pathlib
import subprocess
import sys

import pytest

CHANGELOG = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"
DOCS = ["CONTRIBUTING.md", "WEB_DASHBOARD.md"]

R7_PRS = [
    194,  # T-0434 dashboard route inventory (closing-soon documented)
    196,  # T-0437 CI documentation claims corrected
    199,  # T-0439 user-capped tool contracts (maximum: 500)
    200,  # T-0440 dashboard error surfacing (error envelopes)
]
OMITTED_PRS = {
    193: "test-only (T-0433) /spread and /midpoint wire-truth contract suite",
    195: "test-only (T-0421) /positions market-filter live-contract derivation",
    197: "CHANGELOG-self update (T-0435) - content is the CHANGELOG itself",
    198: "test-only (T-0441) ASCII-guard portability (CI-unblocking = M-1)",
}
_ANCHORS = [
    "Dashboard route inventory",
    "CI documentation claims",
    "User-capped tool contracts",
    "Dashboard error surfacing",
]


def _unreleased(text):
    """The [Unreleased] block of the CHANGELOG (terminates at the release
    template header, mirroring the r6 helper)."""
    return text[text.index("## [Unreleased]"):text.index("## [X.Y.Z]")]


def _new_fixed_block(text):
    """The r7 delta in Fixed: lines inserted between the r6 Fixed tail and
    the Added section, scoped to the [Unreleased] block."""
    unreleased = _unreleased(text)
    start = unreleased.index("(PR #192).") + len("(PR #192).")
    end = unreleased.index("### Added")
    return unreleased[start:end]


@pytest.mark.parametrize("pr", R7_PRS)
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
    """The r6 pins survive this slice: the tails of the sections this
    slice extends are still present exactly once."""
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count("(PR #192)") == 1  # r6 Fixed tail (T-0429)
    assert text.count("(PR #190)") == 1  # Added tail (T-0426)
    assert text.count("(PR #187)") == 1  # Changed tail (T-0419)


def test_r7_entries_in_fixed_block():
    """All four r7 anchors live in the new Fixed delta (not elsewhere)."""
    block = _new_fixed_block(CHANGELOG.read_text(encoding="utf-8"))
    for anchor in _ANCHORS:
        assert anchor in block, f"'{anchor}' must be in the r7 Fixed delta"


def test_r7_docs_ascii_delta_scoped():
    """The docs edited by this range stay ASCII: count non-ASCII bytes in
    the ADDED lines of the CHANGELOG diff for the r7 range (python-puro,
    portable - the T-0441 lesson: never bash -c, WSL stdout is UTF-16)."""
    base = "e39701341ad49ba8ddbe691dc38a186577db8e0c"  # T-0437 fork point
    out = subprocess.run(
        [sys.executable, "-c", (
            "import subprocess,sys\n"
            f"d=subprocess.run(['git','diff','{base}..HEAD','--','CHANGELOG.md'],"
            "capture_output=True)\n"
            "lines=[l for l in d.stdout.split(b'\\n') if l.startswith(b'+') "
            "and not l.startswith(b'+++')]\n"
            "bad=[l for l in lines if any(b > 0x7E or (b < 0x20 and b not in (9,)) for b in l)]\n"
            "print(len(bad))"
        )],
        capture_output=True,
    )
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    assert out.stdout.strip() == b"0", (
        f"non-ASCII bytes added to CHANGELOG.md since {base[:7]}: {out.stdout!r}"
    )
