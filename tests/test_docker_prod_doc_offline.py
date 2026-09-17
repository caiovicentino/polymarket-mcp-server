"""Offline suite: DOCKER.md production deployment delivers the full config.

Bug (pre-fix, RED proven on main 89edfa9 — curator probes /tmp/probe-c52*.py,
re-proven in this slice's preflight): the Production Deployment section of
DOCKER.md showed a `docker-compose.prod.yml` example that does NOT extend the
base file, and instructed the standalone `docker compose -f
docker-compose.prod.yml up -d`. The standalone example renders ZERO config
variables (its `environment:` block holds only LOG_LEVEL=WARNING): a stack
started that way boots without credentials — without POLYMARKET_API_SECRET the
auth client falls back to `api_secret or passphrase`, which breaks HMAC request
signing (.env.example note). DOCKER.md's base section already instructs
`cp .env.example .env`; the prod example ignored that .env.

Fix under test (2 edits, nothing else — `version: '3.8'` obsolescence is a
declared cosmetic follow-up, out of scope):
1. `env_file: - path: .env / required: false` inserted in the prod example
   BEFORE its `environment:` block (list-of-maps long form, Compose v2.24+
   semantics; proven live on compose v5.0.2, standalone AND merged).
2. The start command becomes the base+overlay pair:
   `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.

Declared overlay divergence: with base+prod, the prod `environment:`
(LOG_LEVEL=WARNING) overrides LOG_LEVEL loaded from .env via env_file —
intended production hardening, not a bug.

`docker compose config` expands env_file entries into the rendered service
environment (env_file itself disappears from the render — it is consumed), so
the merged render carries all 22 PolymarketConfig fields with .env present and
still succeeds (rc=0) without it (base `${VAR}` interpolation warnings do not
affect the rc).

House rules applied:
- P-0029 hermeticity: this suite NEVER writes .env in the repo worktree; live
  renders run in per-test tmp dirs (pytest tmp_path, outside the repo) and the
  spawned docker process gets the host env stripped of config field names, so
  the project .env — not the host env — drives the render.
- L-0026/L-0094: docker-dependent tests SKIP with an explicit reason when
  docker compose is unavailable (CI without docker).
- L-0002/L-0008: set-based semantic assertions (superset of MODEL_FIELDS),
  never fragile counts — sibling slices may grow the render legally.
- L-0056: every negation is paired with a positive presence assertion.
- pyyaml is only needed by render tests; pytest.importorskip with an explicit
  reason keeps text-only tests runnable on bare environments.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from polymarket_mcp.config import PolymarketConfig  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKER_MD = REPO_ROOT / "DOCKER.md"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE_FILE = REPO_ROOT / ".env.example"
SERVICE = "polymarket-mcp"

MODEL_FIELDS = set(PolymarketConfig.model_fields)
assert len(MODEL_FIELDS) == 22, "PolymarketConfig field set drifted from the bug report"

# Fields the bug report calls out by name — their absence is what breaks HMAC
# signing / risk limits. Redundant with the set assertion below by design
# (deliberate domain guard, L-0002): each is pinned independently so a future
# regression report names the exact field.
CALLOUT_FIELDS = (
    "POLYMARKET_API_SECRET",
    "POLYMARKET_API_KEY_NAME",
    "USDC_ADDRESS",
    "CTF_EXCHANGE_ADDRESS",
    "CONDITIONAL_TOKEN_ADDRESS",
    "MAX_POSITION_SIZE_PER_MARKET",
)

# The env_file block exactly as prescribed (pin by content, compose v2.24+
# list-of-maps long form). Indentation is the service (4) / list item (6) /
# key (8) level.
ENV_FILE_BLOCK_PATTERN = re.compile(
    r"^    env_file:\n      - path: \.env\n        required: false$",
    re.MULTILINE,
)

# The start command exactly as prescribed: base file first, prod overlay on top.
MERGED_START_COMMAND = (
    "docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
)

# Whitespace-normalized so the fixed-width lookbehind works on any wrapping.
_WS_RUNS = re.compile(r"\s+")
# Negation: an occurrence of `<prod.yml> up` that is NOT preceded by the base
# prefix `docker-compose.yml -f ` (the merged command CONTAINS the prod suffix
# as a substring — the lookbehind is what keeps the negation off it).
STANDALONE_PROD_UP = re.compile(r"(?<!docker-compose\.yml -f )docker-compose\.prod\.yml up")


def _prod_block_lines() -> list[str]:
    """Extract the prod example block from DOCKER.md.

    Start: the first line that STARTS with the `# docker-compose.prod.yml`
    comment (the opening ```yaml fence precedes that comment and is NOT
    captured). End: the first line whose stripped content is the closing
    fence — so the captured range holds the YAML without any fences.
    Extraction anchors are content-based, never line numbers (L-0070).
    """
    lines = DOCKER_MD.read_text(encoding="utf-8").splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.startswith("# docker-compose.prod.yml")),
        None,
    )
    assert start is not None, (
        "prod block anchor '# docker-compose.prod.yml' missing from DOCKER.md"
    )
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].strip() == "```"),
        None,
    )
    assert end is not None, "closing fence after the prod block missing from DOCKER.md"
    return lines[start:end]


def _prod_yaml_text() -> str:
    block = _prod_block_lines()
    text = "\n".join(block) + "\n"
    assert text.strip(), "extracted prod block is empty (extraction anchor drift)"
    assert "polymarket-mcp:" in text, (
        "extracted prod block lost its service entry (extraction anchor drift)"
    )
    return text


def _docker_compose_available() -> bool:
    try:
        probe = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def _require_docker_compose() -> None:
    if not _docker_compose_available():
        pytest.skip(
            "docker compose unavailable: live render tests are infra-dependent "
            "(SKIP-de-infra with explicit reason, L-0026/L-0094)"
        )


def _import_yaml() -> object:
    return pytest.importorskip(
        "yaml",
        reason="pyyaml not installed: render parsing is skipped here "
        "(declared CI state — dev extras not installed)",
    )


def _clean_config_env() -> dict[str, str]:
    """Host env minus the config field names — the compose project .env (not
    the host env) must drive the render under test (P-0029 hermeticity)."""
    return {k: v for k, v in os.environ.items() if k not in MODEL_FIELDS}


def test_prod_block_has_env_file() -> None:
    """The prod example declares env_file (.env, required: false) BEFORE its
    environment: block — the doc's prod service receives config from .env
    independently of the base file's state (L-0148f coexistence: correct in
    ANY merge order of the sibling slices)."""
    block_text = _prod_yaml_text()
    match = ENV_FILE_BLOCK_PATTERN.search(block_text)
    assert match is not None, (
        "prod block must declare env_file: - path: .env / required: false "
        "(list-of-maps long form)"
    )
    env_idx = block_text.index("    environment:")
    env_file_idx = block_text.index("    env_file:")
    assert env_file_idx < env_idx, (
        "env_file must be declared BEFORE environment: in the prod example"
    )
    assert "LOG_LEVEL=WARNING" in block_text, (
        "prod block sanity: the overlay LOG_LEVEL=WARNING entry must remain "
        "(declared overlay behavior, not removed)"
    )


def test_start_command_uses_base_and_prod() -> None:
    """The doc instructs the base+overlay start command, and NO standalone
    prod-up command remains (negation paired with the positive assertion,
    L-0056). The merged command CONTAINS `docker-compose.prod.yml up` as a
    substring — the fixed-width negative lookbehind is what keeps the negation
    from flagging it."""
    text = _WS_RUNS.sub(" ", DOCKER_MD.read_text(encoding="utf-8"))
    assert MERGED_START_COMMAND in text, (
        "DOCKER.md must instruct the merged start command "
        f"{MERGED_START_COMMAND!r}"
    )
    standalone = STANDALONE_PROD_UP.findall(text)
    assert standalone == [], (
        "no standalone prod-up command may remain "
        f"(found {len(standalone)}: {standalone!r})"
    )


def test_render_with_env_covers_all_fields(tmp_path: Path) -> None:
    """With .env present (copied from .env.example), the rendered service
    environment of the base+prod pair carries all 22 config fields — including
    POLYMARKET_API_SECRET, whose absence breaks HMAC signing. Superset
    assertion (contract wording: 'contains all 22'), not equality — sibling
    slices may legally grow the render (L-0148)."""
    _require_docker_compose()
    yaml = _import_yaml()
    shutil.copy(COMPOSE_FILE, tmp_path / "docker-compose.yml")
    (tmp_path / "prod.yml").write_text(_prod_yaml_text(), encoding="utf-8")
    shutil.copy(ENV_EXAMPLE_FILE, tmp_path / ".env")
    out = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "prod.yml", "config"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        env=_clean_config_env(),
    )
    assert out.returncode == 0, f"compose render with .env failed: {out.stderr[-300:]}"
    rendered = yaml.safe_load(out.stdout)
    service_env = rendered["services"][SERVICE]["environment"]
    assert isinstance(service_env, dict) and service_env, (
        "rendered service environment is missing or malformed"
    )
    rendered_keys = set(service_env)
    missing = MODEL_FIELDS - rendered_keys
    assert missing == set(), (
        f"render is missing {len(missing)} config fields: {sorted(missing)}"
    )
    for required in CALLOUT_FIELDS:
        assert required in rendered_keys, (
            f"{required} must reach the production container (bug-report callout)"
        )


def test_render_without_env_rc0(tmp_path: Path) -> None:
    """required: false: the merged base+prod render succeeds WITHOUT .env
    (`config -q` rc=0), so a fresh clone without credentials still renders a
    valid (degraded, demo-able) stack. The tmp project dir starts clean —
    this suite never creates .env in the repo worktree (P-0029)."""
    _require_docker_compose()
    shutil.copy(COMPOSE_FILE, tmp_path / "docker-compose.yml")
    (tmp_path / "prod.yml").write_text(_prod_yaml_text(), encoding="utf-8")
    assert not (tmp_path / ".env").exists(), "tmp project dir must start without .env"
    out = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "prod.yml", "config", "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        env=_clean_config_env(),
    )
    assert out.returncode == 0, (
        f"required: false violated — merged render fails without .env: "
        f"rc={out.returncode}, stderr={out.stderr[-300:]}"
    )
