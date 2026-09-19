"""Offline pins for TEST_SUMMARY.md and TESTING.md claim re-derivation.

These suites are the executable acceptance of the docs fatia: every claim that
was stale against the current repository state (bare live-API commands, volatile
per-test counts, stale hook/tool counts, missing live-tier note for the E2E
guide) is pinned either as REMOVED (the stale string) or PRESENT (the corrected
wording). Anti-drift rules: volatile counts are removed rather than updated;
structural facts keep explicit pointers to their source of truth.

Conventions: read_text(encoding="utf-8"), paired negations, content anchors.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CANONICAL = (
    'pytest -m "not integration and not slow and not real_api and not performance"'
)

# Historical non-ASCII glyphs already in the docs (pre-existing unicode, preserved byte-exact).
SUMMARY_GLYPHS = {"\u2705", "\u2014", "\u2192", "\u2265", "\u00d7"}
TESTING_GLYPHS = {"\u2014"}

SUMMARY = ROOT / "TEST_SUMMARY.md"
TESTING = ROOT / "TESTING.md"


def test_offline_summary_has_canonical_selection():
    """The canonical offline selection is the documented default (multiple sites)."""
    text = SUMMARY.read_text(encoding="utf-8")
    assert text.count(CANONICAL) >= 3, (
        "canonical offline selection under-documented in TEST_SUMMARY.md "
        f"(found {text.count(CANONICAL)})"
    )


def test_offline_summary_has_no_bare_full_suite_command():
    """`pytest tests/` runs live tiers - must not be presented as a runnable default."""
    text = SUMMARY.read_text(encoding="utf-8")
    bare = [ln for ln in text.splitlines() if ln.strip() == "pytest tests/"]
    assert not bare, f"bare live-tier command still present at lines: {bare}"


def test_offline_summary_coverage_commands_have_explicit_target():
    """`--cov` without a target measures the whole environment; the doc must pin the target."""
    text = SUMMARY.read_text(encoding="utf-8")
    assert "pytest tests/ --cov --cov-report=html" not in text, (
        "coverage command without --cov=src/polymarket_mcp target"
    )
    assert "--cov=src/polymarket_mcp" in text, (
        "corrected coverage command with explicit target missing"
    )


def test_offline_summary_hook_count_is_a_pointer_not_a_number():
    """The hook count lives in .pre-commit-config.yaml; hard numbers drift (was '17')."""
    text = SUMMARY.read_text(encoding="utf-8")
    assert "17 automated checks" not in text, "stale hook count still present"
    assert text.count(".pre-commit-config.yaml") >= 2, (
        "expected a pointer to the hook source of truth in both pre-commit sections"
    )


def test_offline_summary_smoke_check_has_no_tool_count():
    """smoke_test.py prints 'Tool initialization' with no count; the doc must match."""
    text = SUMMARY.read_text(encoding="utf-8")
    assert "Tool initialization (45 tools)" not in text, (
        "hard tool count in smoke-check list; smoke_test.py does not print one"
    )


def test_offline_summary_class_listings_keep_names_without_counts():
    """Anti-drift: per-class counts removed, class names preserved (no over-fix)."""
    text = SUMMARY.read_text(encoding="utf-8")
    tail = re.compile(r"^- \*\*.+\*\* \(\d+ (?:tests?|benchmarks)\)$", re.M)
    assert not tail.search(text), "per-class count tails still present"
    for cls in (
        "TestAPIConnectivity",
        "TestErrorHandling",
        "TestSafetyValidation",
        "TestServerInitialization",
        "TestInstallationFlow",
        "TestAPIPerformance",
        "TestStressScenarios",
    ):
        assert f"**{cls}**" in text, f"class {cls} removed by over-fix"
    for stale_total in (
        "**Total: 20 integration tests**",
        "**Total: 18 E2E tests**",
        "**Total: 15 performance tests**",
    ):
        assert stale_total not in text, f"stale section total still present: {stale_total}"
    assert not re.search(r"\*\*Total: \d+ \w+ tests?\*\*", text), (
        "another numeric section total remains"
    )


def test_offline_summary_pyramid_has_no_per_tier_counts():
    """The ASCII pyramid keeps its shape; numeric per-tier counts are gone (INT was stale 20 vs 21)."""
    text = SUMMARY.read_text(encoding="utf-8")
    for stale in ("18 tests - Complete workflows", "20 tests - Real API integration", "- 8 tests"):
        assert stale not in text, f"stale pyramid count still present: {stale}"
    assert "/E2E\\" in text and "/  INT  \\" in text and "SMOKE" in text, (
        "pyramid art structure damaged by over-fix"
    )
    assert "Real API integration (live)" in text, "live tier marker missing from pyramid"


def test_offline_summary_files_created_has_no_line_counts():
    """Per-file line counts and the '~3,400 lines' total are volatile snapshots - removed."""
    text = SUMMARY.read_text(encoding="utf-8")
    assert not re.search(r"^\d+\. `[^`]+` \(\d+ lines\)$", text, re.M), (
        "Files Created line counts still present"
    )
    assert "~3,400 lines" not in text, "stale total line count still present"
    start = text.index("## Files Created")
    section = text[start : text.index("## Usage Examples")]
    items = re.findall(r"^\d+\. ", section, re.M)
    assert len(items) == 12, f"expected the 12-item file list preserved, got {len(items)}"


def test_offline_summary_files_created_keeps_codecov_reference():
    """.codecov.yml exists at the repo root (target 80%) - the doc entry must survive the cleanup."""
    text = SUMMARY.read_text(encoding="utf-8")
    assert (ROOT / ".codecov.yml").is_file(), ".codecov.yml missing from repo"
    assert ".codecov.yml" in text, ".codecov.yml entry removed by over-fix"


def test_offline_summary_dev_deps_block_points_at_pyproject():
    """The TOML dependency snapshot omitted packages (jinja2, pyyaml); a pointer cannot drift."""
    text = SUMMARY.read_text(encoding="utf-8")
    assert '"pytest-benchmark>=4.0.0"' not in text, "stale TOML dependency snapshot still present"
    assert "see pyproject.toml for the current list" in text, "pointer to source of truth missing"


def test_offline_summary_execution_levels_have_no_volatile_timings():
    """'~3s measured' etc. age instantly; levels describe intent, not stale durations."""
    text = SUMMARY.read_text(encoding="utf-8")
    for stale in ("~3s measured", "(~5min)", "(~10min)"):
        assert stale not in text, f"volatile timing still present: {stale}"


def test_offline_summary_dev_examples_no_not_slow_trap():
    """`-m "not slow"` silently includes live tiers; dev examples must use the offline selection."""
    text = SUMMARY.read_text(encoding="utf-8")
    assert 'pytest tests/ -m "not slow"' not in text, "live-tier trap still in dev examples"


def test_offline_summary_benefits_kept_defensible_claims():
    """80% is a real codecov target (.codecov.yml status.project) - the claim stays; no churn."""
    text = SUMMARY.read_text(encoding="utf-8")
    assert "80% coverage enforced" in text, "defensible codecov-backed claim removed (over-fix)"


def test_offline_summary_non_ascii_set_is_frozen():
    """Byte-exact pre-existing unicode preserved: only the historical set survives (no new glyphs)."""
    text = SUMMARY.read_text(encoding="utf-8")
    non_ascii = {c for c in text if ord(c) > 127}
    assert non_ascii <= SUMMARY_GLYPHS, (
        f"new non-ASCII characters introduced: {sorted(non_ascii - SUMMARY_GLYPHS)}"
    )


def test_testing_guide_e2e_section_marks_live_api():
    """test_e2e.py sets module-level pytestmark=integration; the E2E guide must say so."""
    text = TESTING.read_text(encoding="utf-8")
    start = text.index("### End-to-End Tests")
    end = text.index("### Performance Tests")
    section = text[start:end]
    assert "live" in section and "integration" in section and "tests/test_e2e.py" in section, (
        "E2E section lacks the live-API note (module-level pytestmark = integration)"
    )
    assert "# Run E2E tests (live API - needs network)" in section, (
        "E2E run command lacks the network comment"
    )


def test_testing_guide_overview_marks_e2e_live():
    text = TESTING.read_text(encoding="utf-8")
    assert "- **End-to-End Tests**: Complete workflow testing (live API)" in text, (
        "overview bullet not marked live"
    )


def test_testing_guide_non_ascii_set_is_frozen():
    """Only the pre-existing em-dashes survive; the fix adds ASCII-only wording."""
    text = TESTING.read_text(encoding="utf-8")
    non_ascii = {c for c in text if ord(c) > 127}
    assert non_ascii <= TESTING_GLYPHS, (
        f"unexpected non-ASCII in TESTING.md: {sorted(non_ascii - TESTING_GLYPHS)}"
    )
