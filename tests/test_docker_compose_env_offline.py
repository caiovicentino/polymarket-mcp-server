"""Offline suite: docker-compose.yml delivers the full PolymarketConfig.

Bug (pre-fix, RED proven on main 89edfa9): docker-compose.yml had no env_file,
so inside the container only the 10 vars of the `environment:` block reached
PolymarketConfig — 12 of the 22 model fields were unreachable in Docker
(POLYMARKET_API_SECRET, POLYMARKET_API_KEY_NAME, MAX_POSITION_SIZE_PER_MARKET,
MIN_LIQUIDITY_REQUIRED, MAX_SPREAD_TOLERANCE, ENABLE_AUTONOMOUS_TRADING,
AUTO_CANCEL_ON_LARGE_SPREAD, CLOB_API_URL, GAMMA_API_URL, USDC_ADDRESS,
CTF_EXCHANGE_ADDRESS, CONDITIONAL_TOKEN_ADDRESS). DOCKER.md instructs
`cp .env.example .env` but the compose file ignored it; and without
POLYMARKET_API_SECRET the client guard falls back to `api_secret or
passphrase`, which breaks HMAC request signing.

Fix under test: `env_file: - path: .env / required: false` (Compose v2.24+
semantics) added after `image:` and before `environment:`. With .env present
in the compose project dir, the rendered service environment carries all 22
fields; without .env, `docker compose config -q` still succeeds (rc=0), so
the stack keeps starting exactly as before. Proven live on compose v5.0.2:
`docker compose config` expands env_file entries into the rendered service
environment (env_file itself disappears from the render — it is consumed).

House rules applied:
- P-0029 hermeticity: this suite NEVER writes .env in the repo worktree;
  live renders run in per-test tmp dirs (pytest tmp_path, outside the repo)
  and the spawned docker process gets the host env stripped of config field
  names, so the project .env — not the host env — drives the render.
- L-0026/L-0094: docker-dependent tests SKIP with an explicit reason when
  docker compose is unavailable (CI without docker).
- L-0002/L-0008: set-based semantic assertions, never fragile counts.
- L-0056: every negation is paired with a positive presence assertion.
- pyyaml is only needed by structural/render tests; pytest.importorskip with
  an explicit reason keeps text-only tests runnable on bare environments.
"""
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Union, get_args, get_origin

import pytest
from pydantic import TypeAdapter
from pydantic.fields import FieldInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE_FILE = REPO_ROOT / ".env.example"
SERVICE = "polymarket-mcp"

_SRC = str(REPO_ROOT / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from polymarket_mcp.config import PolymarketConfig  # noqa: E402

MODEL_FIELDS = set(PolymarketConfig.model_fields)
assert len(MODEL_FIELDS) == 22, "PolymarketConfig field set drifted from the bug report"

# The environment block that predates this fix. Design rule: the block stays
# untouched (interpolations with real defaults preserved) — set pin, not count
# (L-0002). This is the regression guard for that decision.
EXPECTED_ENV_BLOCK_KEYS = {
    "POLYGON_PRIVATE_KEY",
    "POLYGON_ADDRESS",
    "POLYMARKET_API_KEY",
    "POLYMARKET_PASSPHRASE",
    "DEMO_MODE",
    "LOG_LEVEL",
    "POLYMARKET_CHAIN_ID",
    "MAX_ORDER_SIZE_USD",
    "MAX_TOTAL_EXPOSURE_USD",
    "REQUIRE_CONFIRMATION_ABOVE_USD",
}

# The env_file block exactly as prescribed (pin by content, compose v2.24+
# long form). Indentation is the service (4) / list item (6) / key (8) level.
ENV_FILE_BLOCK_PATTERN = re.compile(
    r"^    env_file:\n      - path: \.env\n        required: false$",
    re.MULTILINE,
)


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


def _import_yaml() -> Any:
    return pytest.importorskip(
        "yaml",
        reason="pyyaml not installed: structural compose parsing is skipped here "
        "(declared CI state — dev extras not installed)",
    )


def _load_compose() -> Any:
    yaml = _import_yaml()
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def _service_env(compose: Any) -> list[str]:
    env = compose["services"][SERVICE]["environment"]
    assert isinstance(env, list) and env, "environment block missing or malformed"
    return env


def _clean_config_env() -> dict[str, str]:
    """Host env minus the config field names — the compose project .env (not
    the host env) must drive the render under test (P-0029 hermeticity)."""
    return {k: v for k, v in os.environ.items() if k not in MODEL_FIELDS}


def _accepts_empty_string(key: str, field: FieldInfo) -> bool:
    """Whether '' is a boot-safe value for a config field.

    float/bool/int fields raise pydantic ValidationError on '' at boot; LOG_LEVEL
    is a str validated against a fixed level list at boot (validate_log_level),
    so '' breaks it too. Plain/Optional str fields accept '' as the degraded
    fallback value (auth client guard: api_secret or passphrase), so they are
    exempt from the empty-default ban.
    """
    if key == "LOG_LEVEL":
        return False
    annotation = field.annotation
    if annotation is str:
        return True
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = get_args(annotation)
        return all(arg is str or arg is type(None) for arg in args)
    return False


def test_env_file_declared() -> None:
    """docker-compose.yml declares env_file with path .env and required: false."""
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    match = ENV_FILE_BLOCK_PATTERN.search(text)
    assert match is not None, (
        "docker-compose.yml must declare env_file: - path: .env / required: false"
    )


def test_env_example_covers_model_fields() -> None:
    """Set of .env.example keys == set of PolymarketConfig.model_fields (22)."""
    example_keys: set[str] = set()
    for line in ENV_EXAMPLE_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", stripped)
        if match:
            example_keys.add(match.group(1))
    assert example_keys == MODEL_FIELDS, (
        f"missing_in_example={sorted(MODEL_FIELDS - example_keys)} "
        f"extra_in_example={sorted(example_keys - MODEL_FIELDS)}"
    )


def test_render_with_env_covers_all_fields(tmp_path: Path) -> None:
    """With .env present (copied from .env.example), the rendered service
    environment carries all 22 config fields — including POLYMARKET_API_SECRET,
    which was unreachable in Docker before this fix."""
    _require_docker_compose()
    yaml = _import_yaml()
    shutil.copy(COMPOSE_FILE, tmp_path / "docker-compose.yml")
    shutil.copy(ENV_EXAMPLE_FILE, tmp_path / ".env")
    out = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "config"],
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
    assert rendered_keys == MODEL_FIELDS, (
        f"missing={sorted(MODEL_FIELDS - rendered_keys)} "
        f"extra={sorted(rendered_keys - MODEL_FIELDS)}"
    )
    assert "POLYMARKET_API_SECRET" in rendered_keys, (
        "the field whose absence breaks HMAC signing must reach the container"
    )


def test_render_without_env_still_valid(tmp_path: Path) -> None:
    """required: false: `docker compose config -q` succeeds WITHOUT .env (rc=0),
    so the stack keeps starting exactly as before the fix. The tmp project dir
    starts clean — this suite never creates .env in the repo worktree."""
    _require_docker_compose()
    shutil.copy(COMPOSE_FILE, tmp_path / "docker-compose.yml")
    assert not (tmp_path / ".env").exists(), "tmp project dir must start without .env"
    out = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "config", "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        env=_clean_config_env(),
    )
    assert out.returncode == 0, (
        f"required: false violated — render fails without .env: rc={out.returncode}, "
        f"stderr={out.stderr[-300:]}"
    )


def test_environment_block_preserved() -> None:
    """Regression guard: the pre-existing environment block keeps its 10 config
    entries (set equality against the pre-fix block — L-0002)."""
    compose = _load_compose()
    env = _service_env(compose)
    keys = {entry.split("=", 1)[0] for entry in env}
    assert keys == EXPECTED_ENV_BLOCK_KEYS, (
        f"unexpected={sorted(keys - EXPECTED_ENV_BLOCK_KEYS)} "
        f"removed={sorted(EXPECTED_ENV_BLOCK_KEYS - keys)}"
    )


def test_no_empty_interpolation_defaults() -> None:
    """No environment entry interpolates an EMPTY default for a boot-validated
    field: '' raises pydantic ValidationError at boot for float/bool/int fields,
    and LOG_LEVEL's validator rejects '' too. Str/Optional-str entries are exempt
    by type ('' is the degraded-fallback value). Negation (no empty default) is
    paired with the positive presence of the real entries (L-0056)."""
    compose = _load_compose()
    env = _service_env(compose)
    keys = {entry.split("=", 1)[0] for entry in env}
    assert keys == EXPECTED_ENV_BLOCK_KEYS, (
        "positive sibling of the negation below: the 10 real entries must exist"
    )
    for entry in env:
        key, expr = entry.split("=", 1)
        field = PolymarketConfig.model_fields.get(key)
        assert field is not None, f"environment entry {key!r} is not a config field"
        if _accepts_empty_string(key, field):
            continue
        match = re.fullmatch(rf"\$\{{{re.escape(key)}:-([^}}]*)\}}", expr)
        assert match is not None, (
            f"boot-validated field {key} must interpolate a real default; got {expr!r}"
        )
        default = match.group(1)
        assert default != "", f"empty default for {key} breaks boot validation"
        # positive proof: the default parses as the field's own type
        TypeAdapter(field.annotation).validate_python(default)
