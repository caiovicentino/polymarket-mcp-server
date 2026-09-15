"""
Offline security suite for PolymarketConfig (src/polymarket_mcp/config.py).

Pins the OBSERVED behavior at clone 9c3fef6 (L-0090: asserts follow the code,
not the contract prose). Suite-only task: src/** is read, never modified.

Behaviors pinned:
- to_dict (config.py:209-221) masks the 4 secret fields ONLY when truthy.
  POLYMARKET_API_KEY_NAME is NOT masked (observed); masking is dump-only —
  the live attribute keeps the real value.
- validate_address (config.py:161-181) rejects empty / missing 0x / wrong
  length, lowercases, and does NOT validate hex ("0xzz..." accepted) —
  pinned as an observed finding (P3 for the human), not a desired behavior.
- DEMO_MODE (declared BEFORE the credential fields, config.py:25-28) makes
  both wallet validators substitute fixed demo constants (config.py:140-141
  and 169-170).
- validate_log_level (config.py:191-199) uppercases and rejects unknown
  levels.
- validate_spread_tolerance (config.py:183-189) requires 0 <= v <= 1
  (inclusive bounds).
- has_api_credentials (config.py:201-207) checks API_KEY + PASSPHRASE +
  API_KEY_NAME but NOT API_SECRET — inconsistent with the auth client, which
  creates ApiCreds when api_key and (api_secret or passphrase)
  (src/polymarket_mcp/auth/client.py:59-72) and falls back to
  passphrase-as-secret with a warning when the secret is absent
  (client.py:63-67). Pinned as observed; the inconsistency is a finding for
  the human/roadmap, NOT fixed here (suite-only task).

Hermeticity (L-0086b): the autouse clean_env fixture strips every
POLYGON_*/POLYMARKET_*/DEMO_MODE/LOG_LEVEL/MAX_*/MIN_*/ENABLE_*/REQUIRE_*/
AUTO_* process env var, and every construction passes _env_file=None so
pydantic-settings never reads a .env file regardless of CWD (proven against
a real .env in a temp dir in test_env_var_overrides_default_and_env_file_
is_disabled).

Divergence note (L-0025/L-0090): the contract prose said json.dumps(to_dict())
"does not contain ... 's'". As bare substrings, 'k'/'s'/'p' DO occur — the
endpoint URL values ("https://gamma-api.polymarket.com") contain them. The
discriminating assertions therefore use the JSON-token form ('"s"' etc.) plus
the full 64-char key literal: a mask regression would serialize the raw value
as a JSON string, which these assertions detect.

Note: this module shadows tests/conftest.py's clean_env fixture (a sys.path
helper, non-autouse) with a same-named autouse fixture — pytest resolves
module-level fixtures before conftest ones for this module.
"""

import json
import os

import pytest
from pydantic import ValidationError

from polymarket_mcp.config import PolymarketConfig

# Process env prefixes/names that feed PolymarketConfig fields; stripped by
# the autouse fixture so tests never observe the host environment (L-0086b).
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

# Fixed demo constants substituted by DEMO_MODE (config.py:141, 170).
DEMO_PRIVATE_KEY = "0" * 63 + "1"
DEMO_ADDRESS = "0x" + "00" * 19 + "01"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip config-sourced env vars so tests never see the host environment."""
    for name in list(os.environ):
        if any(name.startswith(prefix) for prefix in _ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


def make_config(**overrides):
    """Hermetic construction: no .env file, valid non-demo key/address."""
    kwargs = {
        "POLYGON_PRIVATE_KEY": "0" * 63 + "1",
        "POLYGON_ADDRESS": "0x" + "ab" * 20,
    }
    kwargs.update(overrides)
    return PolymarketConfig(_env_file=None, **kwargs)


def error_for_field(exc, field):
    """Return the pydantic message for `field` (aggregation-safe, L-0002)."""
    for err in exc.errors():
        if field in err.get("loc", ()):
            return err["msg"]
    return exc.errors()[0]["msg"]


def test_to_dict_masks_all_four_secrets():
    """to_dict masks the 4 secrets; name/address stay clear; no leak in JSON."""
    config = make_config(
        POLYMARKET_API_KEY="k",
        POLYMARKET_API_SECRET="s",
        POLYMARKET_PASSPHRASE="p",
        POLYMARKET_API_KEY_NAME="n",
    )
    data = config.to_dict()
    assert data["POLYGON_PRIVATE_KEY"] == "***HIDDEN***"
    assert data["POLYMARKET_API_KEY"] == "***HIDDEN***"
    assert data["POLYMARKET_API_SECRET"] == "***HIDDEN***"
    assert data["POLYMARKET_PASSPHRASE"] == "***HIDDEN***"
    # Observed: the API key NAME is not masked; the address is not masked.
    assert data["POLYMARKET_API_KEY_NAME"] == "n"
    assert data["POLYGON_ADDRESS"] == "0x" + "ab" * 20

    # Masking is dump-only: the live attribute keeps the real key.
    assert config.POLYGON_PRIVATE_KEY == "0" * 63 + "1"

    # No leak in a serialized dump. Bare single chars ('s'/'k'/'p') also occur
    # inside endpoint URLs, so the discriminating form is the JSON token (see
    # module docstring); the 64-char key literal is checked directly.
    dump = json.dumps(data)
    assert "0" * 63 + "1" not in dump
    assert '"s"' not in dump
    assert '"k"' not in dump
    assert '"p"' not in dump


def test_to_dict_leaves_unset_secrets_as_none_and_keeps_non_secrets():
    """Masking is truthy-gated: unset L2 creds stay None; non-secrets intact."""
    data = make_config().to_dict()
    assert data["POLYMARKET_API_KEY"] is None
    assert data["POLYMARKET_API_SECRET"] is None
    assert data["POLYMARKET_PASSPHRASE"] is None
    assert data["POLYGON_PRIVATE_KEY"] == "***HIDDEN***"
    assert data["MAX_ORDER_SIZE_USD"] == 1000.0


def test_validate_address_rejects_empty_missing_prefix_and_wrong_length():
    """Empty / missing 0x / wrong length raise with the pinned messages."""
    with pytest.raises(ValidationError) as excinfo:
        make_config(POLYGON_ADDRESS="")
    msg = error_for_field(excinfo.value, "POLYGON_ADDRESS")
    assert "POLYGON_ADDRESS is required (or set DEMO_MODE=true for read-only access)" in msg

    with pytest.raises(ValidationError) as excinfo:
        make_config(POLYGON_ADDRESS="ab" * 20)
    msg = error_for_field(excinfo.value, "POLYGON_ADDRESS")
    assert "POLYGON_ADDRESS must start with 0x" in msg

    with pytest.raises(ValidationError) as excinfo:
        make_config(POLYGON_ADDRESS="0x" + "ab" * 19)
    msg = error_for_field(excinfo.value, "POLYGON_ADDRESS")
    assert "POLYGON_ADDRESS must be 42 characters" in msg


def test_validate_address_lowercases_and_does_not_check_hex():
    """Uppercase hex is lowercased; non-hex '0xzz...' is ACCEPTED (observed).

    config.py:181 returns v.lower() with no hex validation. Pinned as an
    observed finding (P3 for the human), not a desired behavior: a fix that
    rejects non-hex must update this test in the same change.
    """
    lowered = make_config(POLYGON_ADDRESS="0x" + "AB" * 20).POLYGON_ADDRESS
    assert lowered == "0x" + "ab" * 20
    nonhex = make_config(POLYGON_ADDRESS="0x" + "zz" * 20).POLYGON_ADDRESS
    assert nonhex == "0x" + "zz" * 20


def test_demo_mode_substitutes_fixed_address_and_key():
    """DEMO_MODE replaces both wallet values with fixed demo constants."""
    config = make_config(
        DEMO_MODE=True,
        POLYGON_ADDRESS="0x" + "ab" * 20,
        POLYGON_PRIVATE_KEY="",
    )
    assert config.POLYGON_ADDRESS == DEMO_ADDRESS
    assert config.POLYGON_PRIVATE_KEY == DEMO_PRIVATE_KEY

    # Substitution is unconditional in demo mode: a provided (valid) key is
    # replaced too, never used.
    alt = make_config(DEMO_MODE=True, POLYGON_PRIVATE_KEY="0" * 62 + "2")
    assert alt.POLYGON_PRIVATE_KEY == DEMO_PRIVATE_KEY


def test_log_level_normalizes_case_and_rejects_unknown():
    """LOG_LEVEL is uppercased; unknown levels raise with the pinned message."""
    assert make_config(LOG_LEVEL="debug").LOG_LEVEL == "DEBUG"
    assert make_config(LOG_LEVEL="Warning").LOG_LEVEL == "WARNING"
    assert make_config(LOG_LEVEL="INFO").LOG_LEVEL == "INFO"

    with pytest.raises(ValidationError) as excinfo:
        make_config(LOG_LEVEL="TRACE")
    msg = error_for_field(excinfo.value, "LOG_LEVEL")
    assert "LOG_LEVEL must be one of" in msg
    assert "'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'" in msg


def test_spread_tolerance_bounds():
    """0.0 and 1.0 are inclusive bounds; outside values raise (observed msg)."""
    assert make_config(MAX_SPREAD_TOLERANCE=0.0).MAX_SPREAD_TOLERANCE == 0.0
    assert make_config(MAX_SPREAD_TOLERANCE=1.0).MAX_SPREAD_TOLERANCE == 1.0
    for bad in (1.5, -0.1):
        with pytest.raises(ValidationError) as excinfo:
            make_config(MAX_SPREAD_TOLERANCE=bad)
        msg = error_for_field(excinfo.value, "MAX_SPREAD_TOLERANCE")
        assert "MAX_SPREAD_TOLERANCE must be between 0 and 1" in msg


def test_has_api_credentials_ignores_api_secret():
    """SECRET is absent from the check — inconsistent with auth/client.py.

    config.py:201-207 requires API_KEY + PASSPHRASE + API_KEY_NAME. The client
    (src/polymarket_mcp/auth/client.py:59-72) instead creates ApiCreds when
    api_key and (api_secret or passphrase), falling back to
    passphrase-as-secret with a warning (client.py:63-67). Pinned as observed:
    the inconsistency is a finding for the human/roadmap, NOT fixed here.
    """
    assert make_config().has_api_credentials() is False
    # Missing SECRET still counts as "has credentials" (HMAC would be invalid).
    assert make_config(
        POLYMARKET_API_KEY="k", POLYMARKET_PASSPHRASE="p", POLYMARKET_API_KEY_NAME="n"
    ).has_api_credentials() is True
    # SECRET present without KEY_NAME: config says "no", the client would sign.
    assert make_config(
        POLYMARKET_API_KEY="k", POLYMARKET_API_SECRET="s", POLYMARKET_PASSPHRASE="p"
    ).has_api_credentials() is False
    assert make_config(
        POLYMARKET_API_KEY="k", POLYMARKET_API_SECRET="s"
    ).has_api_credentials() is False


def test_env_var_overrides_default_and_env_file_is_disabled(tmp_path, monkeypatch):
    """Env wins over defaults; _env_file=None ignores any .env on disk."""
    defaults = make_config()
    assert defaults.ENABLE_AUTONOMOUS_TRADING is False
    assert defaults.REQUIRE_CONFIRMATION_ABOVE_USD == 500.0
    assert defaults.MAX_ORDER_SIZE_USD == 1000.0
    assert defaults.LOG_LEVEL == "INFO"
    assert defaults.DEMO_MODE is False

    # Explicit process env (exact name — case_sensitive=True) overrides default.
    monkeypatch.setenv("LOG_LEVEL", "error")
    assert make_config().LOG_LEVEL == "ERROR"

    # A .env in CWD is NOT read: _env_file=None disables file loading. The
    # sentinel value would surface as POLYMARKET_API_KEY if the file leaked in
    # (env vars outrank .env for LOG_LEVEL, so the key is the discriminator).
    (tmp_path / ".env").write_text(
        "LOG_LEVEL=debug\nPOLYMARKET_API_KEY=FROM_DOTENV_SENTINEL\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    isolated = make_config()
    assert isolated.POLYMARKET_API_KEY is None
    assert isolated.LOG_LEVEL == "ERROR"
