"""F1-r8: CHANGELOG follow-up - PR #203 registered in [Unreleased].

Contract (farm/T-0449): the CHANGELOG [Unreleased] Fixed section documents
every merged product PR since #200 (the r7 follow-up covered #193-#200,
contract farm/T-0443 via PR #202; r6 covered #180-#192, r5 #165-#179,
r4 #151-#164, r3 #137-#150, r2 #108-#136, r1 #86-#107).

Fixed x1 in this range:
- #203 (T-0444): schema bounds r3 - the tool registry declares the missing
  bounds: the six paginated gamma tools declare `maximum` as the
  module-constant product (`_GAMMA_PAGE_SIZE * _GAMMA_MAX_PAGES` == 1000
  rows per call), `compare_markets` gains `minItems: 2`/`maxItems: 10`, and
  the `hours`, `min_value` and `max_actions` parameters gain minimums;
  `search_markets` deliberately declares no maximum (the per-type cap of
  50 lives in the inputSchema description, per the T-0444 contract).

Provenance note (divergence declared in the farm report): the emitting
contract labelled the schema-bounds slice as PR #202, but the live history
(git log origin/main + gh api repos/.../pulls/N, re-proved at claim time)
shows the r7 follow-up itself consumed PR #202 (farm/T-0443, merged
2026-09-20T12:00:24Z) and the schema-bounds slice is PR #203 (farm/T-0444,
merged 2026-09-20T12:04:13Z) - the entry records the real number
(L-0101/L-0090(g): docs follow the observable source of truth, never the
stale label).

Omissions in the #201-#203 range, with declared justification:
- #201 (T-0445): test-only - the /api/stats and /monitoring wire-truth
  contract suite (the item-158 fix targets; zero src edits).
- #202 (T-0443): CHANGELOG-self update - content is the CHANGELOG itself.
"""
import pathlib
import subprocess
import sys

import pytest

CHANGELOG = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"

FORK_BASE = "3ad9954106f4111c7bb2072cad3837c0f3fd5804"  # T-0444 merge (fork point)

R8_ENTRY = """- **Schema bounds r3**: the tool registry declares the missing bounds - six
  Gamma pagination tools cap each call at `maximum: 1000` rows (derived from
  the module constants), `compare_markets` requires 2-10 markets, and the
  `hours`, `min_value` and `max_actions` parameters gain minimums (PR #203)."""

R8_PRS = [
    203,  # T-0444 schema bounds r3 (gamma ceiling, compare 2-10, minimums)
]
OMITTED_PRS = {
    201: "test-only (T-0445) /api/stats and /monitoring wire-truth contract suite",
    202: "CHANGELOG-self update (T-0443) - content is the CHANGELOG itself",
}
_ANCHORS = [
    "Schema bounds r3",
]


def _unreleased(text):
    """The [Unreleased] block of the CHANGELOG (terminates at the release
    template header, mirroring the r7 helper)."""
    return text[text.index("## [Unreleased]"):text.index("## [X.Y.Z]")]


def _new_fixed_block(text):
    """The r8 delta in Fixed: lines inserted between the r7 Fixed tail and
    the Added section, scoped to the [Unreleased] block."""
    unreleased = _unreleased(text)
    start = unreleased.index("(PR #200).") + len("(PR #200).")
    end = unreleased.index("### Added")
    return unreleased[start:end]


@pytest.mark.parametrize("pr", R8_PRS)
def test_pr_registered_once(pr):
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count(f"(PR #{pr})") == 1, f"PR #{pr} must appear exactly once"
    assert _unreleased(text).count(f"(PR #{pr})") == 1, (
        f"PR #{pr} must appear exactly once in [Unreleased]"
    )


@pytest.mark.parametrize("pr", sorted(OMITTED_PRS))
def test_omitted_prs_absent(pr):
    text = CHANGELOG.read_text(encoding="utf-8")
    assert f"(PR #{pr})" not in text, (
        f"PR #{pr} must stay omitted: {OMITTED_PRS[pr]}"
    )


def test_predecessor_pins_hold():
    """The r7/r6 pins survive this slice: the tails of the sections this
    slice extends are still present exactly once."""
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count("(PR #194)") == 1  # r7 Fixed head (T-0434)
    assert text.count("(PR #196)") == 1  # r7 CI doc claims (T-0437)
    assert text.count("(PR #199)") == 1  # r7 user-capped contracts (T-0439)
    assert text.count("(PR #200)") == 1  # r7 Fixed tail (T-0440)
    assert text.count("(PR #192)") == 1  # r6 Fixed tail (T-0429)
    assert text.count("(PR #190)") == 1  # Added tail (T-0426)
    assert text.count("(PR #187)") == 1  # Changed tail (T-0419)


def test_r8_entry_in_fixed_block():
    """The r8 anchor lives in the new Fixed delta (not elsewhere), between
    the r7 tail and the Added section, and the entry text is pinned
    verbatim (anti-drift)."""
    block = _new_fixed_block(CHANGELOG.read_text(encoding="utf-8"))
    for anchor in _ANCHORS:
        assert anchor in block, f"'{anchor}' must be in the r8 Fixed delta"
    assert R8_ENTRY in block, "the r8 entry must be recorded verbatim"


def test_r8_docs_ascii_delta_scoped():
    """The CHANGELOG stays ASCII: count non-ASCII bytes in the ADDED lines
    of the diff for the r8 range (python-puro, portable - the T-0441
    lesson: never bash -c, WSL stdout is UTF-16)."""
    out = subprocess.run(
        [sys.executable, "-c", (
            "import subprocess,sys\n"
            f"d=subprocess.run(['git','diff','{FORK_BASE}..HEAD','--','CHANGELOG.md'],"
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
        f"non-ASCII bytes added to CHANGELOG.md since {FORK_BASE[:7]}: {out.stdout!r}"
    )
