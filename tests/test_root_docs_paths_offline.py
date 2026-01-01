"""Offline regression suite for root-doc path hygiene (T-0252).

Contract T-0252: 5 named tests, 100% offline (read-only, no network, no
subprocess, no server). The 4 root docs carried the AUTHOR's absolute
machine path (/Users/caiovicentino/Desktop/poly/polymarket-mcp/...) --
commands copied from the docs fail with "no such file or directory" on
every user machine (P2). One guide also referenced a file that does not
exist (IMPLEMENTATION_SUMMARY.md), and the portfolio test command was
presented as a routine test while the suite is real_api-marked (LIVE,
L2 credentials) with no tier note.

Canonical dir: QUICKSTART_GUIDE.md:14 uses ``cd polymarket-mcp-server``;
every doc command must match that name (relative to the repo checkout).

Mechanics
---------
- Docs are read with an EXPLICIT encoding (item 147b -- never rely on the
  platform default). Reads are content-anchored (L-0127), never file:line,
  so concurrent merges that shift lines do not flip the suite.
- Exact counts (12/3/2 and the 0-sum) are contract-declared and were
  preflighted clean: zero pre-existing occurrences of the canonical
  strings in any of the 4 docs, so the fixed state produces exactly the
  pinned numbers (no inflate-by-drift).
- Anti-drift (L-0023): the broken ref is REMOVED, not re-pointed -- the
  asserted absence is of the bare token IMPLEMENTATION_SUMMARY, so a
  future rename of the target file cannot silently re-break the doc.
- Tripwire (P-0085/P-0013): sha256 of every file the suite reads is
  snapshotted at session start and verified at session end -- the suite
  must be strictly read-only (zero writes anywhere; the suite itself
  never writes).

RED pre-state (proven before the fix, kept as EVIDENCE): all 5 tests
FAIL against the untouched tree -- 18 author-path occurrences total
(12+4+1+1), zero canonical refs, zero tier note. GREEN state is the
post-fix tree with the exact replace-counts 12/4/1/1.

Hygiene: the suite performs no network I/O and no filesystem writes
(tripwire-enforced).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Files under test (read-only; tripwire scope).
_DOC_RELPATHS = (
    "DOCKER_SUMMARY.md",
    "AGENT_INTEGRATION_GUIDE.md",
    "DASHBOARD_SUMMARY.md",
    "PORTFOLIO_INTEGRATION.md",
)


def _read(relpath: str) -> str:
    """Read a doc with an EXPLICIT encoding (item 147b)."""
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


@pytest.fixture(scope="session", autouse=True)
def read_only_tripwire():
    """Fail the session if the suite modified any file it reads (P-0013)."""
    before = {
        rel: hashlib.sha256((REPO_ROOT / rel).read_bytes()).hexdigest()
        for rel in _DOC_RELPATHS
    }
    yield
    after = {
        rel: hashlib.sha256((REPO_ROOT / rel).read_bytes()).hexdigest()
        for rel in _DOC_RELPATHS
    }
    mutated = [rel for rel in _DOC_RELPATHS if before[rel] != after[rel]]
    assert not mutated, f"suite must be read-only; wrote to: {mutated}"


def test_no_author_paths_anywhere():
    """Zero occurrences of the author's home prefix in the 4 root docs.

    The needle is the bare home prefix (not the full repo path) so ANY
    variant rooted at the author's machine is caught. RED pre-state:
    18 occurrences total (12+4+1+1).
    """
    needle = "/Users/caiovicentino"
    per_file = {rel: _read(rel).count(needle) for rel in _DOC_RELPATHS}
    total = sum(per_file.values())
    assert total == 0, f"author path still present: {per_file}"


def test_docker_summary_relative_refs():
    """DOCKER_SUMMARY.md carries exactly 12 relative repo refs.

    The 12 file-reference sites (Dockerfile, docker-compose.yml,
    .dockerignore, docker-start.sh, .env.example, DOCKER.md, 5x k8s/*,
    .github/workflows/docker-publish.yml) each gained the canonical
    ``polymarket-mcp-server/`` prefix (replace-count 12, contract-
    declared; preflight showed 0 pre-existing occurrences).
    """
    count = _read("DOCKER_SUMMARY.md").count("polymarket-mcp-server/")
    assert count == 12, (
        f"expected 12 relative refs in DOCKER_SUMMARY.md, found {count}"
    )


def test_agent_guide_no_broken_ref():
    """AGENT_INTEGRATION_GUIDE.md: broken ref removed, 3 relative refs left.

    - ``IMPLEMENTATION_SUMMARY`` must be ABSENT (the file does not exist
      in the repo root; the doc line was deleted, anti-drift L-0023 --
      the assertion pins the bare token so re-pointing to a renamed doc
      cannot silently reintroduce the break).
    - ``polymarket-mcp-server/README.md``: exactly 1 (the Full
      documentation pointer).
    - ``polymarket-mcp-server/``: exactly 3 total (Base line, README.md,
      .env.example -- 4 original sites minus the deleted line).
    """
    content = _read("AGENT_INTEGRATION_GUIDE.md")
    broken = content.count("IMPLEMENTATION_SUMMARY")
    readme = content.count("polymarket-mcp-server/README.md")
    rel = content.count("polymarket-mcp-server/")
    assert broken == 0, (
        "broken ref IMPLEMENTATION_SUMMARY must be absent "
        f"(found {broken})"
    )
    assert readme == 1, f"expected exactly 1 README.md ref, found {readme}"
    assert rel == 3, (
        f"expected exactly 3 relative refs (Base, README.md, .env.example), "
        f"found {rel}"
    )


def test_cd_commands_use_canonical_dir():
    """Both cd instructions use the canonical dir name (>= 1 occurrence).

    Canonical name: QUICKSTART_GUIDE.md:14 = ``cd polymarket-mcp-server``.
    RED pre-state: 0 occurrences in each file (the cd lines carried the
    author's absolute path).
    """
    for rel in ("DASHBOARD_SUMMARY.md", "PORTFOLIO_INTEGRATION.md"):
        count = _read(rel).count("cd polymarket-mcp-server")
        assert count >= 1, (
            f"expected at least 1 'cd polymarket-mcp-server' in {rel}, "
            f"found {count}"
        )


def test_portfolio_live_command_has_tier_note():
    """PORTFOLIO_INTEGRATION.md: live-only suite is marked with a tier note.

    tests/test_portfolio_tools.py carries ``pytestmark =
    pytest.mark.real_api`` -- it hits REAL Polymarket APIs and needs L2
    credentials, so the doc command must (a) carry the tier note and
    (b) filter explicitly with ``-m "real_api"`` (pyproject addopts has
    NO marker filter -- the bare command would run LIVE). Exactly 2
    ``real_api`` occurrences: the note + the explicit filter.
    """
    count = _read("PORTFOLIO_INTEGRATION.md").count("real_api")
    assert count == 2, (
        f"expected exactly 2 'real_api' occurrences in PORTFOLIO_INTEGRATION.md "
        f"(tier note + explicit -m filter), found {count}"
    )
