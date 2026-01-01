"""docker-compose.yml interpolation defaults MUST equal the config defaults.

Live semantics (proven by curator probe, 2026-09-18): with NO .env present,
`docker compose up` resolves each `environment` entry from its interpolation
default (`${VAR:-fallback}`) - the container then boots PolymarketConfig with
THOSE values. Any divergence between the compose fallback and the code
default means an installation without .env runs with DIFFERENT safety limits
than the documented defaults.

Found divergences (RED pre-fix, proved):
- MAX_TOTAL_EXPOSURE_USD:-10000  vs config default 5000.0 (2x looser
  exposure cap for every bare compose deployment)
- REQUIRE_CONFIRMATION_ABOVE_USD:-100 vs config default 500.0 (5x lower
  confirmation threshold -> orders between $100 and $500 that the code
  would gate for confirmation run ungated)

Fix: align both interpolation defaults to the code defaults (5000.0/500.0).

Anti-drift (L-0023/P-0007): the config defaults are DERIVED from the live
PolymarketConfig model at runtime - never hardcoded here. Adding a new
safety field to config.py without a compose entry is fine (the field falls
back to the code default); adding a compose entry with a stale value fails
this suite.

Hermeticity: no .env is required and none is written; the docker render
check is client-side (`docker compose config` renders without a daemon -
proved on this host) and SKIPS (infra) when the docker binary is absent
(L-0026). The suite reads files relative to the repo root resolved from
__file__, so it is worktree-safe (L-0011).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
CONFIG_MODULE = "polymarket_mcp.config"


def _config_defaults() -> dict[str, object]:
    """Derive the live config defaults from PolymarketConfig (anti-drift)."""
    from polymarket_mcp.config import PolymarketConfig

    return {
        name: (field.default if field.default is not None else None)
        for name, field in PolymarketConfig.model_fields.items()
    }


def _compose_env_entries() -> list[tuple[str, str | None]]:
    """Parse the `environment:` block entries of docker-compose.yml.

    Returns (name, fallback) pairs; fallback is None for `${NAME}` entries
    (no interpolation default) and for blank fallbacks `${NAME:-}`.
    """
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "environment:")
    env_lines = []
    for line in lines[start + 1:]:
        # The block ends at the next top-level key (4-space indent, not a
        # comment, not a list entry) - e.g. "    volumes:".
        if re.match(r"^    \S", line) and not line.lstrip().startswith("#") and not line.lstrip().startswith("-"):
            break
        env_lines.append(line)
    env_block = "\n".join(env_lines)
    entries: list[tuple[str, str | None]] = []
    for line in env_block.splitlines():
        match = re.match(r"\s*-\s*([A-Z][A-Z0-9_]+)=\$\{([A-Z][A-Z0-9_]+)(?::-(.*))?\}\s*$", line)
        if not match:
            continue
        name, var, fallback = match.groups()
        assert name == var, f"compose entry {name} interpolates ${{{var}}}"
        entries.append((name, fallback if fallback else None))
    return entries


def test_every_interpolation_default_matches_config_default():
    defaults = _config_defaults()
    entries = _compose_env_entries()
    assert entries, "environment block not found in docker-compose.yml"
    divergent = []
    for name, fallback in entries:
        if fallback is None:
            continue  # required or blank-fallback entries checked below
        assert name in defaults, (
            f"compose fallback for {name} has NO matching config field "
            f"(config drift or typo): {fallback!r}"
        )
        expected = defaults[name]
        if isinstance(expected, float):
            if float(fallback) != float(expected):
                divergent.append(f"{name}: compose {fallback!r} != config {expected!r}")
        elif isinstance(expected, bool):
            if fallback.strip().lower() != str(expected).lower():
                divergent.append(f"{name}: compose {fallback!r} != config {expected!r}")
        elif isinstance(expected, int):
            if int(fallback) != int(expected):
                divergent.append(f"{name}: compose {fallback!r} != config {expected!r}")
        else:
            if fallback != str(expected):
                divergent.append(f"{name}: compose {fallback!r} != config {expected!r}")
    assert divergent == [], (
        "compose interpolation defaults diverge from the code defaults: "
        + "; ".join(divergent)
    )


def test_required_credentials_have_no_silent_fallback():
    """POLYGON_PRIVATE_KEY / POLYGON_ADDRESS interpolate WITHOUT :- fallback.

    A silent fallback (empty string) would let the container boot with a
    blank key and fail validation deep in the stack; the intended behavior
    is a LOUD config-validation failure at boot.
    """
    entries = dict(_compose_env_entries())
    for required in ("POLYGON_PRIVATE_KEY", "POLYGON_ADDRESS"):
        assert required in entries, f"{required} missing from the compose environment block"
        assert entries[required] is None, (
            f"{required} must interpolate without a :- fallback (got {entries[required]!r})"
        )


def test_optional_credentials_blank_fallback_matches_client_guard():
    """POLYMARKET_API_KEY/PASSPHRASE fall back to blank == falsy.

    client.py's credential guard treats a blank string as absent, so the
    blank fallback is the sanctioned no-credentials shape.
    """
    entries = dict(_compose_env_entries())
    for optional in ("POLYMARKET_API_KEY", "POLYMARKET_PASSPHRASE"):
        assert optional in entries, f"{optional} missing from the compose environment block"
        assert entries[optional] is None, (
            f"{optional} must fall back to blank (got {entries[optional]!r}) "
            "so the client guard treats it as absent"
        )


def test_compose_render_succeeds_without_env():
    """`docker compose config` renders clean with NO .env (client-side)."""
    if shutil.which("docker") is None:
        pytest.skip("docker binary not available (L-0026 SKIP-de-infra)")
    proc = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "config", "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"docker compose config failed without .env: {proc.stderr[-400:]}"
    )
