"""Anti-drift pins for the CI claims fixed in CONTRIBUTING.md / WEB_DASHBOARD.md (farm/T-0437).

Contract farm/T-0437: T-0419 (merged #187) made the integration-test and e2e-test jobs
informational via job-level ``continue-on-error: true`` in .github/workflows/tests.yml
but left 3 factually false CI claims in CONTRIBUTING.md (claiming the performance-test
job shares the informational treatment) and 1 author-absolute path in WEB_DASHBOARD.md.
The T-0419 sec/arch reviews (verdicts/T-0419-sec.md P3-02, verdicts/T-0419-arch.md
P3-01/P3-02) declared those claims stale and out-of-scope for that slice; this suite
closes the turf.

The 4 sites pinned (pre-fix = RED, post-fix = green):

- CONTRIBUTING.md integration-command comment: claimed "mesmo tratamento para
  e2e-test/performance-test" -- FALSE: performance-test has NO continue-on-error
  (verified 1st hand in the workflow: the integration-test and e2e-test job blocks
  carry job-level ``continue-on-error: true``; the performance-test job block carries
  no flag) -- a failing benchmark makes the run red.
- CONTRIBUTING.md [ci-unblock] block: claimed performance-test is informational;
  corrected to call performance-test out explicitly.
- CONTRIBUTING.md Notes bullet: claimed the CI unit step does not exclude the
  ``performance`` marker (stale pre-#129 statement) -- REMOVED, never updated
  (L-0023 anti-drift: the canonical "CI runs these selections" block above it is the
  source of truth).
- WEB_DASHBOARD.md install snippet: author-absolute path replaced with the
  sibling-standard relative form (QUICKSTART_GUIDE.md / SETUP_GUIDE.md /
  INSTALLATION.md all use ``cd polymarket-mcp-server``).

Pins are presence/absence (never line counts). Case-sensitivity note: the legitimate
"does NOT exclude" note (uppercase NOT, the bare-pytest warning) survives; only the
lowercase stale claim is pinned absent. Every negation is paired with a positive
sister assertion so a file-missing error cannot satisfy it.

Byte-level ASCII guards (repo item 147): the two edited docs carry pre-existing
non-ASCII bytes, so the delta-scoped guard checks ONLY the added (+) diff lines since
the static fork-point (never a moving ref), and the suite file itself must be pure
ASCII. The subprocess call reads raw bytes on purpose: counting non-ASCII bytes
requires byte inspection, not decoded text.

Companion: tests/test_ci_selections_offline.py (T-0419, merged #187) pins the
workflow selections -- untouched by this slice.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
WEB_DASHBOARD = ROOT / "WEB_DASHBOARD.md"

# Static fork-point of the fix slice (contract farm/T-0437; NOT a moving ref like
# "main" -- a moving ref would flag content of sibling tasks merged after the fix).
FORK_POINT = "e39701341ad49ba8ddbe691dc38a186577db8e0c"

STALE_PT_CLAIM = "mesmo tratamento"
STALE_UNIT_CLAIM = "does not exclude"
STALE_AUTHOR_PATH = "/Users/"

# Positive sisters: the corrected claims that must survive by construction.
CORRECTED_INTEGRATION_CLAIM = "job-level continue-on-error"
PERFORMANCE_CALLOUT = "NO continue-on-error"
PERFORMANCE_JOB_NAME = "performance-test"
CANONICAL_OFFLINE = "not integration and not slow and not real_api and not performance"
LEGITIMATE_NOT_NOTE = "does NOT exclude"
SIBLING_RELATIVE_CD = "cd polymarket-mcp-server"


def test_performance_test_informational_claim_absent():
    """Pre-fix RED: the integration-command comment claimed the performance-test
    job shares the informational treatment ("mesmo tratamento para
    e2e-test/performance-test"). The real job carries no continue-on-error flag, so
    a failing benchmark makes the run red."""
    text = CONTRIBUTING.read_text(encoding="utf-8")
    assert STALE_PT_CLAIM not in text, (
        "CONTRIBUTING.md: the false claim that performance-test shares the "
        "informational treatment is back ('mesmo tratamento para "
        "e2e-test/performance-test') -- that job has NO continue-on-error flag"
    )
    assert CORRECTED_INTEGRATION_CLAIM in text, (
        "CONTRIBUTING.md: the informational claim (job-level continue-on-error) "
        "for the integration-test job was removed by over-fix"
    )
    assert PERFORMANCE_JOB_NAME in text, (
        "CONTRIBUTING.md: performance-test is no longer called out by name "
        "(over-fix)"
    )
    assert PERFORMANCE_CALLOUT in text, (
        "CONTRIBUTING.md: the corrected claim (NO continue-on-error on "
        "performance-test) is missing"
    )


def test_stale_unit_step_claim_absent_and_legitimate_note_survives():
    """Pre-fix RED: a Notes bullet claimed the CI unit step does not exclude the
    ``performance`` marker (stale pre-#129 statement; removed per L-0023 -- the
    canonical block above is the source of truth). Case-sensitivity: the legitimate
    note on the bare-pytest warning line uses uppercase NOT and must survive."""
    text = CONTRIBUTING.read_text(encoding="utf-8")
    assert STALE_UNIT_CLAIM not in text, (
        "CONTRIBUTING.md: the stale claim that the CI unit step does not exclude "
        "the performance marker is back -- the unit step selects the canonical "
        "offline tier and the claim was REMOVED, never updated (L-0023)"
    )
    assert LEGITIMATE_NOT_NOTE in text, (
        "CONTRIBUTING.md: the legitimate 'does NOT exclude' note (uppercase NOT, "
        "the bare-pytest warning) was removed by over-fix"
    )
    assert CANONICAL_OFFLINE in text, (
        "CONTRIBUTING.md: the canonical offline selection string was removed "
        "(over-fix)"
    )


def test_author_absolute_path_absent_in_web_dashboard():
    """Pre-fix RED: the WEB_DASHBOARD.md install snippet hard-coded the author's
    absolute macOS path. Replaced by the sibling-standard relative form (the same
    form QUICKSTART_GUIDE.md, SETUP_GUIDE.md and INSTALLATION.md use)."""
    text = WEB_DASHBOARD.read_text(encoding="utf-8")
    assert STALE_AUTHOR_PATH not in text, (
        "WEB_DASHBOARD.md: author-absolute path is back -- use the sibling-standard "
        "relative form (QUICKSTART_GUIDE.md/SETUP_GUIDE.md/INSTALLATION.md)"
    )
    assert SIBLING_RELATIVE_CD in text, (
        "WEB_DASHBOARD.md: the relative install command was removed by over-fix"
    )


def test_suite_file_is_pure_ascii():
    """Repo item 147 self-guard: this file must carry zero non-ASCII bytes."""
    data = Path(__file__).read_bytes()
    assert data.isascii(), "non-ASCII byte in the suite file itself"


_VALID_ASCII_BYTES = frozenset(range(0x20, 0x7F)) | frozenset({0x09, 0x0A, 0x0B, 0x0C, 0x0D})


def _has_offender(line: bytes) -> bool:
    """True when the diff line carries at least one byte outside the POSIX
    ``[[:print:][:space:]]`` class in LC_ALL=C (printable 0x20-0x7E plus
    tab/LF/VT/FF/CR). Pure-byte check: no locale, no subprocess shell."""
    return any(b not in _VALID_ASCII_BYTES for b in line)


def test_edited_docs_delta_is_ascii():
    """Repo item 147 delta-scoped guard: the two edited docs carry pre-existing
    non-ASCII bytes, so the guard checks ONLY the added (+) diff lines since the
    static fork-point. Portability fix (farm/T-0441; CI run 35504386795):
    the previous pipeline spawned ``bash -c`` -- on windows-latest that
    resolves to the System32 WSL launcher (no distro), whose stdout is
    UTF-16LE ("Windows Subsystem for Linux has no installed distributions")
    and the assert REDed deterministically on both Windows jobs. The check is
    now pure Python over ``git diff`` bytes (git is on every runner); the
    grep '^+' semantics (lines starting with a plus sign) and the
    ``[[:print:][:space:]]`` byte class are replicated exactly."""
    diff = subprocess.run(
        ["git", "diff", f"{FORK_POINT}..HEAD", "--", "CONTRIBUTING.md", "WEB_DASHBOARD.md"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    plus_lines = [line for line in diff.stdout.split(b"\n") if line.startswith(b"+")]
    offenders = [line for line in plus_lines if _has_offender(line)]
    assert not offenders, (
        f"non-ASCII bytes added to the edited docs since {FORK_POINT}: "
        f"offending lines={offenders!r}"
    )


def test_ascii_detector_flags_nonascii_bytes():
    """The pure-byte detector knows when to fail (repo L-0065): UTF-8
    multi-byte, NUL (the UTF-16LE WSL-launcher signature), control and DEL
    bytes are offenders; CRLF, tab and printable ASCII are not."""
    assert _has_offender(b"+\xe2\x9c\x85 Route registered")
    assert _has_offender(b"+Windows\x00Subsystem")
    assert _has_offender(b"+\x01 control")
    assert _has_offender(b"+DEL\x7f")
    assert not _has_offender(b"+plain ASCII line\r\n")
    assert not _has_offender(b"+tab\tand space ok")
    assert not _has_offender(b"+A1-06 printable")
