"""DEMO_MODE env alias — POLYMARKET_DEMO_MODE must map to the DEMO_MODE field.

Bug (L-0153, probed live 2026-09-18): PolymarketConfig uses SettingsConfigDict
without env_prefix and WITHOUT validation_alias on DEMO_MODE, so the prefixed
env var `POLYMARKET_DEMO_MODE` (set by the CI demo-mode job and
tests/test_integration.py) NEVER reaches the field: the env is silently inert
and the config keeps DEMO_MODE=False (the address/validators keep firing).
The unprefixed `DEMO_MODE` env works today (pydantic-settings maps by field
name) and must keep working (retrocompat with .env.example:16).

Fix shape (byte-equivalent to the curator sim): validation_alias=AliasChoices(
"DEMO_MODE", "POLYMARKET_DEMO_MODE") + populate_by_name=True so init kwargs
(PolymarketConfig(DEMO_MODE=True)) keep working.
"""
from polymarket_mcp.config import PolymarketConfig

VALID_KEY = "a" * 64
VALID_ADDRESS = "0x" + "1" * 40


def _clean_env(monkeypatch):
    for var in ("DEMO_MODE", "POLYMARKET_DEMO_MODE"):
        monkeypatch.delenv(var, raising=False)


def test_prefixed_env_sets_demo_mode(monkeypatch):
    """POLYMARKET_DEMO_MODE=true must activate demo mode (the CI job's form)."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("POLYMARKET_DEMO_MODE", "true")
    cfg = PolymarketConfig(POLYGON_PRIVATE_KEY=VALID_KEY)
    assert cfg.DEMO_MODE is True


def test_unprefixed_env_still_wins(monkeypatch):
    """Retrocompat: bare DEMO_MODE=true env (the .env.example form) keeps working."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("DEMO_MODE", "true")
    cfg = PolymarketConfig(POLYGON_PRIVATE_KEY=VALID_KEY)
    assert cfg.DEMO_MODE is True


def test_kwargs_still_accepted(monkeypatch):
    """populate_by_name: init kwargs by field name keep working (house tests)."""
    _clean_env(monkeypatch)
    cfg = PolymarketConfig(POLYGON_PRIVATE_KEY=VALID_KEY, DEMO_MODE=True)
    assert cfg.DEMO_MODE is True


def test_kwargs_beat_env(monkeypatch):
    """Explicit kwargs take precedence over the env (pydantic-settings order)."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("POLYMARKET_DEMO_MODE", "true")
    cfg = PolymarketConfig(POLYGON_PRIVATE_KEY=VALID_KEY, POLYGON_ADDRESS=VALID_ADDRESS, DEMO_MODE=False)
    assert cfg.DEMO_MODE is False


def test_env_absent_defaults_false(monkeypatch):
    """No env at all -> DEMO_MODE=False (baseline)."""
    _clean_env(monkeypatch)
    cfg = PolymarketConfig(POLYGON_PRIVATE_KEY=VALID_KEY, POLYGON_ADDRESS=VALID_ADDRESS)
    assert cfg.DEMO_MODE is False


def test_prefixed_env_false_string_parses_false(monkeypatch):
    """POLYMARKET_DEMO_MODE=false parses as False (bool env coercion)."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("POLYMARKET_DEMO_MODE", "false")
    cfg = PolymarketConfig(POLYGON_PRIVATE_KEY=VALID_KEY, POLYGON_ADDRESS=VALID_ADDRESS)
    assert cfg.DEMO_MODE is False
