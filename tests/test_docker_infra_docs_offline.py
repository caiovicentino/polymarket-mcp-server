"""Offline suite: docker-infra docs carry NO volatile counts (anti-drift).

Bug (pre-fix, RED proven on main 3b87f7e -- curator sim /tmp/c57-sim.py,
re-proven in this slice's preflight): DOCKER_INFRASTRUCTURE_COMPLETE.md and
PROJECT_COMPLETE.md enumerated MUTABLE state as static text. Two merge events
proved the drift (T-0222 reverted test-docker.sh, T-0235 landed Makefile):
every line count in the Core Infrastructure table except Dockerfile was stale
(docker-compose 86 vs 89, .dockerignore 47 vs 89, docker-start.sh 172 vs 165,
.env.example 79 vs 111, test-docker.sh 237 vs 184, Makefile 162 vs 167), and
PROJECT_COMPLETE.md's per-test counts (8/20/18/15) and hook count (17) are
stale (26 hooks / 12 repos today).

Fix under test (REMOVAL, never update -- L-0023: numbers that change on every
merge must be deleted, not maintained):
1. DOCKER: Lines column dropped from the Core table, Pages column dropped from
   the Documentation table, `(6 files)` header corrected to `(5 files)`
   (5 rows listed), CI/CD section retitled `(3 workflows)` listing the 3 real
   workflows (tests.yml, release.yml, docker-publish.yml); FUNDING.yml (GitHub
   Sponsors config, not CI/CD) row REMOVED from the doc -- the file itself is
   untouched; volatile totals (17 files / 1,457 lines / ~40 pages / 6 guides)
   removed.
2. PROJECT: per-test counts stripped (smoke/integration/E2E/performance),
   `Testing Tools (5)` -> `(6)` (6 items listed), `CI/CD (3)` -> `CI/CD &
   Quality (4)` (3 workflows + pre-commit = quality tooling), hook count
   replaced by a qualitative label.

House rules applied:
- L-0002: structural counts only (headers == items listed); volatile numbers
  are asserted ABSENT, never re-hardcoded.
- L-0056: every negation (volatile string gone) is paired with the positive
  replacement (honest label present).
- FA-0079: reads use explicit encoding="utf-8" (Windows CI charmap guard).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKER_DOC = REPO_ROOT / "DOCKER_INFRASTRUCTURE_COMPLETE.md"
PROJECT_DOC = REPO_ROOT / "PROJECT_COMPLETE.md"

# Structural headers that must survive untouched (1 occurrence each).
_PROJECT_HEADERS = (
    "### **Getting Started (7 docs)**",
    "### **User Guides (5 docs)**",
    "### **Developer Guides (4 docs)**",
    "### **Deployment (4 docs)**",
    "### **Reference (3 docs)**",
    "### **Installation Tools (6)**",
    "### **Monitoring Tools (2)**",
)

_CICD_WORKFLOWS = (
    ".github/workflows/tests.yml",
    ".github/workflows/release.yml",
    ".github/workflows/docker-publish.yml",
)

_NUMERIC_CELL = re.compile(r"\|\s*\d+\s*\|\s*\S+\s*\|$")


def _docker_text() -> str:
    return DOCKER_DOC.read_text(encoding="utf-8")


def _project_text() -> str:
    return PROJECT_DOC.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def _star_rows(section: str) -> list[str]:
    return [line for line in section.splitlines() if line.startswith("| **") and "| ✅ |" in line]


def test_infrastructure_tables_have_no_count_columns() -> None:
    doc = _docker_text()
    assert "| Lines |" not in doc
    assert "| Pages |" not in doc

    core = _between(doc, "### Core Infrastructure (7 files)", "### Documentation (5 files)")
    assert "| File | Purpose | Status |" in core
    assert "| Lines |" not in core
    assert len(_star_rows(core)) == 7
    assert _NUMERIC_CELL.search(core) is None

    docs = _between(doc, "### Documentation (5 files)", "### Kubernetes (5 files)")
    assert "| Document | Target Audience | Status |" in docs
    assert "| Pages |" not in docs
    assert len(_star_rows(docs)) == 5
    assert _NUMERIC_CELL.search(docs) is None


def test_cicd_section_lists_the_three_real_workflows() -> None:
    doc = _docker_text()
    assert doc.count("### CI/CD (3 workflows)") == 1

    cicd = _between(doc, "### CI/CD (3 workflows)", "## 🚀 Quick Start Commands")
    for workflow, purpose in (
        (_CICD_WORKFLOWS[0], "Test pipeline (unit + integration + E2E)"),
        (_CICD_WORKFLOWS[1], "Release automation"),
        (_CICD_WORKFLOWS[2], "Automated builds & publishing"),
    ):
        assert f"**{workflow}**" in cicd
        assert purpose in cicd
    assert len(_star_rows(cicd)) == 3

    # Paired negation (L-0056): FUNDING.yml is GitHub Sponsors config, not CI/CD
    # -- declassified in the doc; the file itself is out of scope and untouched.
    assert "FUNDING" not in doc


def test_volatile_totals_removed_from_docker_doc() -> None:
    doc = _docker_text()
    assert "17 files created" not in doc
    assert "1,457" not in doc
    assert "~40 pages" not in doc
    assert "6 comprehensive guides" not in doc
    assert "(6 files)" not in doc

    # Positive replacements (L-0056): qualitative labels stay, structural
    # headers are exact.
    assert doc.count("Comprehensive guides") == 2
    assert doc.count("### Documentation (5 files)") == 1
    assert doc.count("### Core Infrastructure (7 files)") == 1
    assert "- **Test coverage**: Docker infrastructure 100%" in doc


def test_project_complete_per_test_counts_removed() -> None:
    proj = _project_text()
    for volatile in ("(8 testes)", "20 integration tests", "18 E2E tests", "15 performance tests"):
        assert volatile not in proj
    assert "17 pre-commit hooks" not in proj

    # Positive replacements (L-0056): qualitative labels present.
    assert "- ✅ smoke_test.py - Validação rápida" in proj
    assert "- ✅ tests/test_integration.py - Integration tests" in proj
    assert "- ✅ tests/test_e2e.py - E2E tests" in proj
    assert "- ✅ tests/test_performance.py - Performance tests" in proj
    assert "- ✅ .pre-commit-config.yaml - automated pre-commit hooks" in proj

    # Retitled sections: counts now match the items listed (structural).
    assert proj.count("### **Testing Tools (6)**") == 1
    assert proj.count("### **CI/CD & Quality (4)**") == 1
    assert "### **Testing Tools (5)**" not in proj
    assert "### **CI/CD (3)**" not in proj


def test_structural_section_headers_untouched() -> None:
    proj = _project_text()
    for header in _PROJECT_HEADERS:
        assert proj.count(header) == 1
