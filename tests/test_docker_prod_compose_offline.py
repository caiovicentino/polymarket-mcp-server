"""docker-compose.prod.yml EXISTS and mirrors the DOCKER.md production example.

Live finding (curator probe, 2026-09-18): DOCKER.md ("Production Deployment")
shows the docker-compose.prod.yml example and then teaches
`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` -
but the FILE never existed in the repo. Following the doc verbatim fails:

    stat <repo>/docker-compose.prod.yml: no such file or directory

Fix (this contract's deliverable): create docker-compose.prod.yml with the
EXACT content of the DOCKER.md example block, so the documented production
command works out of the box.

Validated by the curator pre-fix:
- `docker compose -f docker-compose.yml -f docker-compose.prod.yml config -q`
  -> rc=0 (merged render; LOG_LEVEL resolves to WARNING from the prod env
  block, overriding the base INFO fallback)
- `docker compose -f docker-compose.prod.yml config -q` -> rc=0 standalone
- the healthcheck block without a `test:` key is accepted by Compose (the
  base service healthcheck carries the test and the override merges
  interval/timeout/retries) - renders clean both standalone and merged

Hermeticity: no .env is required and none is written; the docker renders are
client-side (no daemon needed - proved on this host) and SKIP (infra) when
the docker binary is absent (L-0026). All reads are relative to the repo
root resolved from __file__ (worktree-safe, L-0011). The file is pure ASCII
(FA-0079 repo-content doctrine).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PROD_FILE = REPO_ROOT / "docker-compose.prod.yml"
BASE_FILE = REPO_ROOT / "docker-compose.yml"


def test_prod_file_exists_with_doc_example_anchors():
    """The file exists and carries the anchors the DOCKER.md example defines."""
    text = PROD_FILE.read_text(encoding="utf-8")
    for anchor in (
        "restart: always",
        "required: false",
        "LOG_LEVEL=WARNING",
        "dockerfile: Dockerfile",
        "max-size: \"50m\"",
        "cpus: '2.0'",
    ):
        assert anchor in text, f"docker-compose.prod.yml missing anchor: {anchor!r}"


def test_prod_file_pure_ascii():
    """Repo content is ASCII-only (FA-0079 doctrine; item 147)."""
    raw = PROD_FILE.read_bytes()
    non_ascii = [b for b in raw if b > 127]
    assert non_ascii == [], f"non-ASCII bytes in docker-compose.prod.yml: {non_ascii[:5]}"


def test_prod_env_file_block_makes_env_optional():
    """The env_file block is list-of-maps with required: false.

    The production override must NOT hard-require .env (the demo/bootstrap
    flow may run without it); with the block present the documented prod
    command picks up every config variable when .env exists.
    """
    text = PROD_FILE.read_text(encoding="utf-8")
    assert "env_file:" in text
    assert "- path: .env" in text
    assert "required: false" in text


def _run_compose(*args: str) -> subprocess.CompletedProcess:
    if shutil.which("docker") is None:
        pytest.skip("docker binary not available (L-0026 SKIP-de-infra)")
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_merged_render_succeeds_and_resolves_log_warning():
    """The documented prod command renders: base + prod override, rc=0."""
    proc = _run_compose(
        "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml", "config"
    )
    assert proc.returncode == 0, f"merged render failed: {proc.stderr[-400:]}"
    assert "LOG_LEVEL: WARNING" in proc.stdout, (
        "the prod override must resolve LOG_LEVEL to WARNING in the merged "
        f"render; got stdout tail: {proc.stdout[-300:]}"
    )


def test_prod_standalone_render_succeeds():
    """Standalone render of the prod file also succeeds (rc=0)."""
    proc = _run_compose("-f", "docker-compose.prod.yml", "config", "-q")
    assert proc.returncode == 0, f"standalone render failed: {proc.stderr[-400:]}"
