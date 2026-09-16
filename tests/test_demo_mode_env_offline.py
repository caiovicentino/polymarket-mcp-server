"""
Offline suite for the POLYMARKET_DEMO_MODE env alias on PolymarketConfig
(src/polymarket_mcp/config.py) — T-0115.

L-0153 proved the env was INERT before this slice: PolymarketConfig uses
SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore") with NO
env_prefix, so the field DEMO_MODE (config.py:25-31 @ farm/T-0115) only ever read
the literal env `DEMO_MODE`. `POLYMARKET_DEMO_MODE=true` — the name set by the CI
demo-mode job (.github/workflows/tests.yml:177) and by
tests/test_integration.py:280/:293 — never reached the field (INERT-PROBE:
construction with that env set succeeded and left DEMO_MODE=False).

The fix maps the field via validation_alias=AliasChoices("DEMO_MODE",
"POLYMARKET_DEMO_MODE") (config.py:7 import + field edit). Pinned behaviors:

- POLYMARKET_DEMO_MODE=true maps to DEMO_MODE=True and triggers the demo
  credential substitution in the existing validators (config.py:140-141/:169-170
  pre-edit): POLYGON_PRIVATE_KEY becomes "0"*63+"1" and POLYGON_ADDRESS becomes
  "0x"+"0"*39+"1" — byte-identical to the values the CI demo-mode job already
  sets (tests.yml:175-176), so the fix is behaviorally neutral for that job.
- Plain DEMO_MODE=true keeps mapping (FIRST AliasChoices choice — retrocompat
  with .env.example and every existing .env file, which use the unprefixed name).
- POLYMARKET_DEMO_MODE=false maps to DEMO_MODE=False (bool parsing, no demo
  substitution).
- Explicit kwargs outrank env (pydantic-settings precedence) — DEMO_MODE=False
  passed as a kwarg wins over POLYMARKET_DEMO_MODE=true in the process env.

The literal alias wiring is ALSO pinned by the acceptance greps on config.py
(validation_alias=AliasChoices("DEMO_MODE", "POLYMARKET_DEMO_MODE") + the import
line) — declared sibling lock (L-0169: pin the literal in the suite OR the
sibling grep as a declared lock; here the grep is the lock and the header
declares it).

Hermeticity (L-0086b house rule): every construction passes _env_file=None so no
.env in CWD can influence results; the autouse clean_env fixture strips every
config-sourced env var (monkeypatch.delenv) and every test sets ONLY the env keys
it names, with explicit values — POLYGON_PRIVATE_KEY/POLYGON_ADDRESS are never
left to ambient state, so no ValidationError can escape. monkeypatch restores
env automatically on teardown (no manual delenv).

RED pre-fix (proved by the curator and re-proven here): tests 1-2 fail on the
unpatched config (assert-based RED — construction succeeds, behavior is inert),
tests 3-5 pass both pre- and post-fix as stability pins.
"""
import os

import pytest

from polymarket_mcp.config import PolymarketConfig

# Process env prefixes/names that feed PolymarketConfig fields; stripped by the
# autouse fixture so tests never observe the host environment (same set as
# tests/test_config_security.py — mirrored, NOT imported: fakes/fixtures are
# never shared across suites, house rule).
_ENV_PREFIXES = (
    "POLYGON_",
    "POLYMARKET_",
    "DEMO_MODE",
    "LOG_LEVEL",
    "MAX_",
    "MIN_",
    "ENABLE_",
    "REQUIRE_",
    "AUTO_",
)

# Fixed demo constants substituted by the validators when DEMO_MODE is True
# (config.py:141/:170 pre-edit — the same values tests/test_config_security.py
# pins as DEMO_PRIVATE_KEY/DEMO_ADDRESS).
DEMO_PRIVATE_KEY = "0" * 63 + "1"
DEMO_ADDRESS = "0x" + "0" * 39 + "1"

# A real-format wallet (64 hex chars / 0x + 40 hex) for non-demo assertions.
RAW_PRIVATE_KEY = "a" * 64
RAW_ADDRESS = "0x" + "1" * 40


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip config-sourced env vars so tests never see the host environment."""
    for name in list(os.environ):
        if any(name.startswith(prefix) for prefix in _ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


def build_config(**overrides) -> PolymarketConfig:
    """Construct PolymarketConfig without any .env file (L-0130 house pattern)."""
    return PolymarketConfig(_env_file=None, **overrides)


def test_env_polymarket_demo_mode_maps_to_field(monkeypatch):
    """POLYMARKET_DEMO_MODE=true (the CI/job name) activates DEMO_MODE.

    RED pre-fix: the env was inert, construction succeeded and DEMO_MODE stayed
    False — the assert (not an exception) is the RED gate (L-0153 INERT-PROBE).
    """
    monkeypatch.setenv("POLYMARKET_DEMO_MODE", "true")
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", RAW_PRIVATE_KEY)
    monkeypatch.setenv("POLYGON_ADDRESS", RAW_ADDRESS)

    cfg = build_config()

    assert cfg.DEMO_MODE is True


def test_env_demo_mode_substitutes_demo_credentials(monkeypatch):
    """With the env alias set, the validators substitute the demo constants.

    The substitution happens because DEMO_MODE is now True in the validated
    data (info.data) — the same path the plain DEMO_MODE=true env already
    exercised pre-fix (config.py:140-141/:169-170).
    """
    monkeypatch.setenv("POLYMARKET_DEMO_MODE", "true")
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", RAW_PRIVATE_KEY)
    monkeypatch.setenv("POLYGON_ADDRESS", RAW_ADDRESS)

    cfg = build_config()

    assert cfg.POLYGON_PRIVATE_KEY == DEMO_PRIVATE_KEY
    assert cfg.POLYGON_ADDRESS == DEMO_ADDRESS


def test_env_plain_demo_mode_still_maps(monkeypatch):
    """Plain DEMO_MODE=true (no prefix) keeps mapping — retrocompat pin.

    The FIRST AliasChoices choice preserves the documented env name used by
    .env.example and every existing .env file (config.py:25-31 @ farm/T-0115).
    """
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", RAW_PRIVATE_KEY)

    cfg = build_config()

    assert cfg.DEMO_MODE is True
    assert cfg.POLYGON_PRIVATE_KEY == DEMO_PRIVATE_KEY


def test_env_false_string_maps_to_false(monkeypatch):
    """POLYMARKET_DEMO_MODE=false maps to DEMO_MODE=False — no substitution."""
    monkeypatch.setenv("POLYMARKET_DEMO_MODE", "false")
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", RAW_PRIVATE_KEY)
    monkeypatch.setenv("POLYGON_ADDRESS", RAW_ADDRESS)

    cfg = build_config()

    assert cfg.DEMO_MODE is False
    assert cfg.POLYGON_PRIVATE_KEY == RAW_PRIVATE_KEY
    assert cfg.POLYGON_ADDRESS == RAW_ADDRESS.lower()


def test_kwargs_outrank_env(monkeypatch):
    """Explicit kwargs outrank the process env (pydantic-settings precedence).

    Precedence pin: a caller constructing PolymarketConfig(DEMO_MODE=False)
    stays non-demo even with POLYMARKET_DEMO_MODE=true in the environment —
    same contract as tests/test_safety_adversarial.py demo_config() ("explicit
    None kwargs outrank the process env"). POLYGON_ADDRESS has an explicit env
    value because the non-demo address validator REQUIRES one (config.py:173-175
    pre-edit) — never rely on ambient env (house rule for this suite).
    """
    monkeypatch.setenv("POLYMARKET_DEMO_MODE", "true")
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", RAW_PRIVATE_KEY)
    monkeypatch.setenv("POLYGON_ADDRESS", RAW_ADDRESS)

    cfg = build_config(DEMO_MODE=False, POLYGON_PRIVATE_KEY=RAW_PRIVATE_KEY)

    assert cfg.DEMO_MODE is False
    assert cfg.POLYGON_PRIVATE_KEY == RAW_PRIVATE_KEY
    assert cfg.POLYGON_ADDRESS == RAW_ADDRESS.lower()
