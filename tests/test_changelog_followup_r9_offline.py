"""F1-r9: CHANGELOG follow-up - PRs #204 and #206 registered in [Unreleased].

Contract (farm/T-0457): the CHANGELOG [Unreleased] Fixed section documents
every merged product PR since #203 (the r8 follow-up covered #201-#202,
contract farm/T-0449 via PR #205; r7 covered #193-#200; r6 #180-#192;
r5 #165-#179; r4 #151-#164; r3 #137-#150; r2 #108-#136; r1 #86-#107).

Fixed x2 in this range:
- #204 (T-0447): batch order_type enum honesty - the create_batch_orders
  item schema declares the same GTC/GTD/FOK/FAK enum as create_limit_order
  (mirroring the runtime validator each entry already enforces) via a
  module-level constant shared by both schemas.
- #206 (T-0451): batch item bounds - the batch item gains the same
  declarative price/size bounds as the single order (price 0.01-0.99,
  size minimum 1) derived from the same module-level constants
  (single-source anti-drift).

Omissions in the #204-#206 range, with declared justification:
- #205 (T-0449): CHANGELOG-self update - content is the CHANGELOG itself.

NOTE (L-0101/L-0090(g)): the entry numbers follow the live history
(git log origin/main re-proved at claim time); if a pub lands between the
emission and the claim, the PR numbers shift by the consumed pubs - the
worker re-derives and records the real numbers, never the stale labels.

Fork-base provenance (contract risk (c), L-0025): the emission pinned
FORK_BASE = "fd44276" (origin/main at emission time); the fork was taken
from origin/main e35bcad (PRs #207/#208 landed between emission and
claim, and touch no CHANGELOG lines - `git diff fd44276..e35bcad --
CHANGELOG.md` is empty, so both pins measure the identical delta). The
suite pins the fork of this claim, re-derived per the contract.
"""
import pathlib
import subprocess
import sys

import pytest

CHANGELOG = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"

FORK_BASE = "e35bcad43e4f8ef009ee865dc94b6d5c478b2f28"  # T-0453 merge (fork point of this claim)

R9_ENTRY = """- **Batch order schema honesty**: the `create_batch_orders` item schema now
  declares the same `order_type` enum (`GTC`/`GTD`/`FOK`/`FAK`) as
  `create_limit_order`, mirroring the runtime validator that each entry
  already enforces, via a module-level constant shared by both schemas
  (PR #204).
- **Batch item bounds**: the `create_batch_orders` item gains the same
  declarative price/size bounds as the single order (`price` 0.01-0.99,
  `size` minimum 1), derived from the same module-level constants
  (single-source anti-drift) (PR #206)."""

R9_PRS = [
    204,  # T-0447 batch order_type enum (single-source constant)
    206,  # T-0451 batch item bounds (price/size single-source)
]
OMITTED_PRS = {
    205: "CHANGELOG-self update (T-0449) - content is the CHANGELOG itself",
}
_ANCHORS = ["Batch order schema honesty", "Batch item bounds"]


def _unreleased(text):
    """The [Unreleased] block of the CHANGELOG (terminates at the release
    template header, mirroring the r8 helper)."""
    return text[text.index("## [Unreleased]"):text.index("## [X.Y.Z]")]


def _new_fixed_block(text):
    """The r9 delta in Fixed: lines inserted between the r8 Fixed tail and
    the Added section, scoped to the [Unreleased] block."""
    unreleased = _unreleased(text)
    start = unreleased.index("(PR #203).") + len("(PR #203).")
    end = unreleased.index("### Added")
    return unreleased[start:end]


@pytest.mark.parametrize("pr", R9_PRS)
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
    """The r8/r7/r6 pins survive this slice: the tails of the sections this
    slice extends are still present exactly once."""
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.count("(PR #203)") == 1  # r8 Fixed tail (T-0444)
    assert text.count("(PR #199)") == 1  # r7 user-capped contracts (T-0439)
    assert text.count("(PR #200)") == 1  # r7 Fixed (T-0440)
    assert text.count("(PR #192)") == 1  # r6 Fixed tail (T-0429)
    assert text.count("(PR #190)") == 1  # Added tail (T-0426)
    assert text.count("(PR #187)") == 1  # Changed tail (T-0419)


def test_r9_entry_in_fixed_block():
    """The r9 anchors live in the new Fixed delta (not elsewhere), between
    the r8 tail and the Added section, and the entry text is pinned
    verbatim (anti-drift)."""
    block = _new_fixed_block(CHANGELOG.read_text(encoding="utf-8"))
    for anchor in _ANCHORS:
        assert anchor in block, f"'{anchor}' must be in the r9 Fixed delta"
    assert R9_ENTRY in block, "the r9 entries must be recorded verbatim"


def test_r9_docs_ascii_delta_scoped():
    """The CHANGELOG stays ASCII: count non-ASCII bytes in the ADDED lines
    of the diff for the r9 range (python-puro, portable - the T-0441
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
