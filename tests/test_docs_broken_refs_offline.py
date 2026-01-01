"""Offline regression suite for broken doc refs (T-0298).

Contract T-0298: 5 named tests, 100% offline (read-only, no network, no
subprocess, no server). Three residual broken/incorrect sites in the root
docs, discovered in the post-T-0250/T-0252 sweep on main b240bb9:

1. SETUP_GUIDE.md referenced IMPLEMENTATION_SUMMARY.md, which does not
   exist in the repo root (T-0252 removed the SAME broken ref from
   AGENT_INTEGRATION_GUIDE.md; this copy in SETUP_GUIDE.md was orphaned
   because SETUP_GUIDE.md was T-0250's turf and that scope did not cover
   the reference).
2. SETUP_GUIDE.md pinned a HARD tool count ("45 tools"). The count is
   correct today but goes stale on the first tool addition; the anti-drift
   doctrine (L-0023) is to REMOVE the count, never to update it.
3. AGENT_INTEGRATION_GUIDE.md carried a config-snippet typo: the block
   defined ``POLYGON_CHAIN_ID = 137`` while the real config field is
   ``POLYMARKET_CHAIN_ID`` (src/polymarket_mcp/config.py). Any agent that
   copies the snippet reads a nonexistent attribute.
4. DOCKER.md carried a markdown link ``[examples/](examples/)`` to a
   directory that does not exist; the reader clicks and gets a 404.

Mechanics
---------
- Docs are read with an EXPLICIT encoding (item 147b -- never rely on the
  platform default; a Windows CI charmap decode would crash the suite).
- Every asserted absence is PAIRED with a positive sibling assertion
  (L-0056) so the suite cannot pass vacuously (e.g. a truncated file
  would satisfy "absent" without the siblings failing).
- Content-anchored pins only (L-0023): no file:line pins; exact counts
  mirror the contract's own acceptance and were preflighted on the
  post-fix tree (0/0/1, 0/1, 0/1/1 -- see each test's docstring).
- Anti-drift: the broken refs are asserted ABSENT by bare token (a future
  rename of the target cannot silently re-break the doc), and the hard
  tool count is asserted absent BOTH literally ("45 tools") and as a
  pattern (``Referência de todas as <digits> tools``), so any
  reintroduction of a hard count at that site fails the suite.
- Tripwire (P-0085/P-0013): sha256 of every file the suite reads is
  snapshotted at session start and verified at session end -- the suite
  must be strictly read-only.

RED pre-state (proven by the curator's probes on main b240bb9, 1st hand):
SETUP_GUIDE.md:277 referenced the missing file, SETUP_GUIDE.md:279 pinned
"45 tools", AGENT_INTEGRATION_GUIDE.md:301 had the typo (grep = exactly 1
occurrence), DOCKER.md:482 carried the broken link. GREEN state is the
post-fix tree with the counts pinned below.

Hygiene: the suite performs no network I/O and no filesystem writes
(tripwire-enforced).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Files under test (read-only; tripwire scope).
_DOC_RELPATHS = (
    "SETUP_GUIDE.md",
    "AGENT_INTEGRATION_GUIDE.md",
    "DOCKER.md",
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


def test_setup_guide_no_broken_implementation_ref():
    """SETUP_GUIDE.md: the orphaned IMPLEMENTATION_SUMMARY ref is gone.

    - ``IMPLEMENTATION_SUMMARY`` must be ABSENT (bare-token pin: the file
      does not exist in the repo root, so the doc line was deleted --
      anti-drift L-0023, a future rename of some other doc cannot
      silently re-break this one).
    - Positive siblings (L-0056): the documentation section still lists
      the surviving entries (README.md, TOOLS_REFERENCE.md), exactly once
      each in the section -- proving the section was pruned, not gutted.
    """
    content = _read("SETUP_GUIDE.md")
    broken = content.count("IMPLEMENTATION_SUMMARY")
    readme = content.count("**README.md**")
    tools_ref = content.count("**TOOLS_REFERENCE.md**")
    assert broken == 0, (
        "broken ref IMPLEMENTATION_SUMMARY must be absent in "
        f"SETUP_GUIDE.md (found {broken})"
    )
    assert readme == 1, (
        f"expected exactly 1 README.md entry in SETUP_GUIDE.md, found {readme}"
    )
    assert tools_ref == 1, (
        "expected exactly 1 TOOLS_REFERENCE.md entry in SETUP_GUIDE.md, "
        f"found {tools_ref}"
    )


def test_setup_guide_no_hard_tool_count():
    """SETUP_GUIDE.md: the hard tool count is gone, countless phrasing in.

    - ``45 tools`` must be ABSENT (contract pin: grep -c '45 tools' == 0).
    - Anti-drift: no ``Referência de todas as <digits> tools`` pattern may
      reappear (L-0023: remove the count, never update it -- a future
      "50 tools" reintroduction at that site fails this suite too).
    - Positive sibling (L-0056): the countless phrasing
      ``Referência de todas as tools`` is present exactly once (contract
      pin: grep -c == 1).
    """
    content = _read("SETUP_GUIDE.md")
    hard = content.count("45 tools")
    pattern = re.findall(r"Referência de todas as \d+ tools", content)
    countless = content.count("Referência de todas as tools")
    assert hard == 0, (
        f"hard tool count '45 tools' must be absent (found {hard})"
    )
    assert not pattern, (
        f"hard tool count pattern must be absent, found {pattern}"
    )
    assert countless == 1, (
        "expected exactly 1 countless 'Referência de todas as tools' in "
        f"SETUP_GUIDE.md, found {countless}"
    )


def test_agent_guide_config_field_name_fixed():
    """AGENT_INTEGRATION_GUIDE.md: config snippet uses the real field name.

    The constants block (``# From config``) defined ``POLYGON_CHAIN_ID =
    137``; the real field in src/polymarket_mcp/config.py is
    ``POLYMARKET_CHAIN_ID``. Any agent copying the snippet would read a
    nonexistent attribute.

    - ``POLYGON_CHAIN_ID`` must be ABSENT (bare token; the curator's grep
      proved exactly 1 occurrence pre-fix, and no legitimate token
      contains it as a substring -- POLYMARKET_CHAIN_ID does not).
    - Positive sibling (L-0056): the corrected constant
      ``POLYMARKET_CHAIN_ID = 137`` is present exactly once (contract pin:
      grep -c == 1).
    - Second sibling: the doc also references the real field via
      ``config.POLYMARKET_CHAIN_ID`` elsewhere (the snippet block that
      shows the config being read), so the whole doc names the field
      consistently.
    """
    content = _read("AGENT_INTEGRATION_GUIDE.md")
    typo = content.count("POLYGON_CHAIN_ID")
    fixed = content.count("POLYMARKET_CHAIN_ID = 137")
    usage = content.count("config.POLYMARKET_CHAIN_ID")
    assert typo == 0, (
        "config-snippet typo POLYGON_CHAIN_ID must be absent "
        f"(found {typo})"
    )
    assert fixed == 1, (
        "expected exactly 1 'POLYMARKET_CHAIN_ID = 137' in "
        f"AGENT_INTEGRATION_GUIDE.md, found {fixed}"
    )
    assert usage >= 1, (
        "expected at least 1 'config.POLYMARKET_CHAIN_ID' usage in "
        f"AGENT_INTEGRATION_GUIDE.md, found {usage}"
    )


def test_docker_no_broken_examples_link():
    """DOCKER.md: the broken [examples/](examples/) link is gone.

    The Next Steps section linked a directory that does not exist in the
    repo root; the reader clicking the link gets a 404.

    - The exact markdown link ``examples/](examples/)`` must be ABSENT
      (contract pin: grep -c == 0).
    - Positive sibling (L-0056): the adjacent CONTRIBUTING.md bullet
      survives, proving the section was pruned by one line, not gutted.
    """
    content = _read("DOCKER.md")
    broken = content.count("examples/](examples/)")
    contributing = content.count(
        "[CONTRIBUTING.md](CONTRIBUTING.md) for development setup"
    )
    assert broken == 0, (
        f"broken examples/ link must be absent in DOCKER.md (found {broken})"
    )
    assert contributing == 1, (
        "expected exactly 1 CONTRIBUTING.md bullet in DOCKER.md, "
        f"found {contributing}"
    )


def test_docker_next_steps_still_intact():
    """DOCKER.md Next Steps: the surviving bullets are untouched.

    The examples/ bullet was removed as a full line; the two bullets the
    fix must PRESERVE are asserted present (paired positives, L-0056):
    the README.md API-documentation bullet (contract pin: exactly 1) and
    the Kubernetes manifests bullet (kept intact by the sim state).
    """
    content = _read("DOCKER.md")
    readme_bullet = content.count(
        "Read [README.md](README.md) for API documentation"
    )
    k8s_bullet = content.count("[k8s/](k8s/) manifests")
    assert readme_bullet == 1, (
        "expected exactly 1 README.md API-documentation bullet in "
        f"DOCKER.md, found {readme_bullet}"
    )
    assert k8s_bullet == 1, (
        "expected exactly 1 Kubernetes manifests bullet in DOCKER.md, "
        f"found {k8s_bullet}"
    )
