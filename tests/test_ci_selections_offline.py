"""Offline pins for CI selections in tests.yml + CONTRIBUTING.md (main RED cure).

Defect pinned here (proved pre-fix by three RED CI runs with the same signature,
all httpx.ConnectError on the "Run demo mode tests" step inside the matrix jobs):

- run 35491657720 (push main @ 1d146e3, 05:25:54Z): job "Test (Python 3.10 on
  ubuntu-latest)" step "Run demo mode tests" RED with 3 FAILED live integration
  tests (test_analysis_wire_contract.py::test_live_condition_id_query_works,
  test_integration.py::TestAPIConnectivity::test_gamma_api_market_details,
  test_market_tools.py::TestMarketAnalysis::test_get_price_history);
  "Test Summary" propagated exit 1 (fail-list includes integration-test).
- run 35491686140 (PR #171 farm/T-0400-pub, 05:29Z): same step, same class,
  3 different live tests (test_live_prices_history_wire_returns_points,
  test_live_featured_query_accepted, test_get_trending_markets).
- run 35492978776 (farm/T-0399-pub, 05:59:16Z): demo step, ConnectError.

Root cause: the demo step selected ``-m "not real_api"`` which does NOT exclude
the ``integration`` tier (109 live tests) nor the ``performance`` tier (9 live
benchmarks) - they ran LIVE inside the matrix jobs. A runner network hiccup
(gamma-api.polymarket.com unreachable) turned the job RED, and the "Test
Summary" fail-list gated the whole workflow. The coverage step
(``-m "not slow and not real_api"``) had the same leak (latent - it passed
only because the network happened to be up on its runners).

Owner policy (PR #129, 0d8c5ef, "canal do dono"): "real-API nao deve fazer o
merge refem da estabilidade da API externa... o gate de merge segue nos jobs
unit/hermeticos". PR #129 aligned the unit job and declared the integration
job informational - but its continue-on-error landed at STEP level on
"Set up Python", which is inert for that intent: a failing "Run integration
tests" step still failed the job and gated the Test Summary fail-list.

This fix: (1) demo + coverage steps select the canonical offline selection;
(2) integration-test and e2e-test get job-level ``continue-on-error: true``
(the live tier keeps running for visibility, now non-gating); (3) the
CONTRIBUTING.md "CI runs these selections" block is aligned to the real
workflow. Pins are content-level (YAML parsed; exact-match ``-m`` args per
step - a raw-text regex over the whole file produces false positives: the
unit canonical string would match as a mere presence).

Note on T5 (divergence declared per L-0025): the task text says release.yml
-m == CANONICAL; the real release.yml selection (line ~48) uses the coverage
term order ("not slow and not real_api and not integration and not
performance") - the same four exclusions (set semantics; pytest -m term order
does not change the selection). The pin asserts the observed exact string.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TESTS_WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"

CANONICAL_ARG = "not integration and not slow and not real_api and not performance"
COVERAGE_CANONICAL_ARG = "not slow and not real_api and not integration and not performance"
STALE_DEMO_ARG = "not real_api"
STALE_COVERAGE_ARG = "not slow and not real_api"

EXPECTED_JOBS = (
    "smoke-test",
    "lint",
    "test",
    "coverage",
    "integration-test",
    "e2e-test",
    "performance-test",
    "test-summary",
)

MARKER = "ci-unblock 2026-09-20"


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _m_args(text: str) -> list[str]:
    """Exact ``-m "..."`` args - used per-step/per-line, never on whole files."""
    return re.findall(r'-m "([^"]+)"', text)


def _step_run(jobs: dict, job: str, name: str) -> str:
    for step in jobs[job]["steps"]:
        if step.get("name") == name:
            return step.get("run", "")
    raise AssertionError(f"step {name!r} not found in job {job!r}")


def _all_pytest_m_args(jobs: dict) -> list[tuple[str, str, str]]:
    collected: list[tuple[str, str, str]] = []
    for job_name, job in jobs.items():
        for step in job.get("steps", []):
            run = step.get("run", "")
            if "pytest" not in run:
                continue
            for arg in _m_args(run):
                collected.append((job_name, step.get("name", ""), arg))
    return collected


def _contributing_ci_block_lines() -> list[str]:
    lines = CONTRIBUTING.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if "# CI runs these selections" in ln)
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "```")
    return lines[start:end]


def test_tests_workflow_parses_and_expected_jobs_present():
    jobs = _yaml(TESTS_WORKFLOW)["jobs"]
    for job in EXPECTED_JOBS:
        assert job in jobs, f"job {job!r} removed from tests.yml"


def test_demo_step_selection_is_canonical_offline():
    args = _m_args(_step_run(_yaml(TESTS_WORKFLOW)["jobs"], "test", "Run demo mode tests"))
    assert CANONICAL_ARG in args, (
        f"demo step args {args!r} do not select the canonical offline tier - "
        "the integration (109 live) and performance (9 live) tiers would run "
        "inside the matrix jobs again (main RED cure regression)"
    )


def test_coverage_step_selection_is_canonical():
    args = _m_args(_step_run(_yaml(TESTS_WORKFLOW)["jobs"], "coverage", "Run tests with coverage"))
    assert COVERAGE_CANONICAL_ARG in args, (
        f"coverage step args {args!r} still leak the integration/performance tiers"
    )


def test_unit_step_selection_guard_pr129():
    args = _m_args(_step_run(_yaml(TESTS_WORKFLOW)["jobs"], "test", "Run unit tests (parallel)"))
    assert CANONICAL_ARG in args, f"unit step selection regressed: {args!r}"


def test_release_workflow_selection_is_canonical_offline():
    data = _yaml(RELEASE_WORKFLOW)
    args: list[str] = []
    for job in data["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run", "")
            if "pytest" in run:
                args.extend(_m_args(run))
    assert COVERAGE_CANONICAL_ARG in args, f"release.yml selection regressed: {args!r}"


def test_integration_test_job_informational_and_tier_survives():
    jobs = _yaml(TESTS_WORKFLOW)["jobs"]
    job = jobs["integration-test"]
    assert job.get("continue-on-error") is True, (
        "integration-test must be informational at JOB level "
        "(step-level flag on 'Set up Python' was inert: a failing step still "
        "failed the job and gated the Test Summary fail-list)"
    )
    run = _step_run(jobs, "integration-test", "Run integration tests")
    assert '-m "integration"' in run, (
        "over-fix: the live integration tier must still run in this job "
        "(now informational), not be deleted"
    )


def test_e2e_test_job_informational_and_command_unchanged():
    jobs = _yaml(TESTS_WORKFLOW)["jobs"]
    job = jobs["e2e-test"]
    assert job.get("continue-on-error") is True, (
        "e2e-test must be informational at JOB level (test_e2e.py is 100% "
        "integration-marked: 'not integration' collects 0 tests = pytest exit 5)"
    )
    run = _step_run(jobs, "e2e-test", "Run E2E tests")
    assert "test_e2e.py" in run, "over-fix: the E2E command itself must stay unchanged"


def test_no_stale_selection_args_anywhere_in_workflow():
    collected = _all_pytest_m_args(_yaml(TESTS_WORKFLOW)["jobs"])
    assert collected, "no pytest -m args found (workflow structure or parser broken)"
    for job, step, arg in collected:
        assert arg != STALE_DEMO_ARG, f"stale demo arg {arg!r} at {job}/{step}"
        assert arg != STALE_COVERAGE_ARG, f"stale coverage arg {arg!r} at {job}/{step}"


def test_contributing_ci_block_matches_workflow():
    block = _contributing_ci_block_lines()
    pytest_lines = [ln for ln in block if ln.strip().startswith("pytest")]
    args = [arg for ln in pytest_lines for arg in _m_args(ln)]
    assert args, "no pytest -m args in the 'CI runs these selections' block"
    assert CANONICAL_ARG in args, (
        f"CONTRIBUTING block args {args!r} missing the canonical offline selection"
    )
    assert COVERAGE_CANONICAL_ARG in args, (
        f"CONTRIBUTING block args {args!r} missing the canonical coverage selection"
    )
    for arg in args:
        assert arg != STALE_DEMO_ARG, f"CONTRIBUTING block still has stale demo arg {arg!r}"
        assert arg != STALE_COVERAGE_ARG, f"CONTRIBUTING block still has stale coverage arg {arg!r}"


def test_unblock_marker_lines_are_ascii():
    wf_hits = [ln for ln in TESTS_WORKFLOW.read_text(encoding="utf-8").splitlines() if MARKER in ln]
    ct_hits = [ln for ln in CONTRIBUTING.read_text(encoding="utf-8").splitlines() if MARKER in ln]
    for line in wf_hits + ct_hits:
        assert line.isascii(), f"non-ASCII byte in marker line: {line!r}"


def test_test_summary_fail_list_preserved():
    summary = _yaml(TESTS_WORKFLOW)["jobs"]["test-summary"]
    cond = None
    for step in summary["steps"]:
        if step.get("name") == "Fail if any test failed":
            cond = step.get("if", "")
    assert cond is not None, "Test Summary fail-list step removed (over-fix)"
    for job in ("smoke-test", "lint", "test", "coverage", "integration-test", "e2e-test"):
        assert f"needs.{job}.result == 'failure'" in cond, f"fail-list lost job {job!r}"
