"""
Configuration validation tests for Polymarket MCP Server.

Offline suite (no network, no real keys, no external services) validating the
config layer in isolation:

- POLYGON_PRIVATE_KEY format checks (64 hex, valid hex, optional 0x prefix)
- the all-zero key (scalar 0) must be rejected at load time with an actionable
  error pointing at .env / DEMO_MODE, instead of crashing later in the signer
- DEMO_MODE=true substitutes the fixed demo key (existing behavior, now pinned)

Isolation: each test starts from a clean config env (repo pattern: del in
finally) and pins DEMO_MODE explicitly, so neither a local .env file nor an
ambient env var can flip the branch under test (env vars outrank .env in
pydantic-settings). No .env is created; load_config() resolves only from the
environment under test. The env var that feeds the DEMO_MODE field is the bare
"DEMO_MODE" (field name, no prefix - config.py:25-28), matching .env.example:16.
"""
import os
import sys

import pytest

sys.path.insert(0, "src")

DEMO_KEY = "0" * 63 + "1"
VALID_ADDRESS = "0x" + "0" * 40
CONFIG_ENV_KEYS = (
    "DEMO_MODE",
    "POLYMARKET_DEMO_MODE",
    "POLYGON_PRIVATE_KEY",
    "POLYGON_ADDRESS",
)


def _clear_config_env():
    """Remove config env vars so each test starts from a clean slate."""
    for key in CONFIG_ENV_KEYS:
        if key in os.environ:
            del os.environ[key]


def _load():
    """Load config under the environment prepared by the caller."""
    from polymarket_mcp.config import load_config

    return load_config()


class TestPrivateKeyValidation:
    """POLYGON_PRIVATE_KEY validation at load time (offline)."""

    def test_zero_key_rejected_with_actionable_error(self):
        """The all-zero key (scalar 0) is rejected at load, not in the signer."""
        _clear_config_env()
        os.environ["DEMO_MODE"] = "false"
        os.environ["POLYGON_PRIVATE_KEY"] = "0" * 64
        os.environ["POLYGON_ADDRESS"] = VALID_ADDRESS
        try:
            from pydantic import ValidationError

            # Type pinned to the observed one (pydantic wraps validator
            # ValueError into ValidationError); message must be actionable.
            with pytest.raises(ValidationError, match="DEMO_MODE"):
                _load()
        finally:
            _clear_config_env()

    def test_valid_dummy_key_accepted(self):
        """A non-zero 64-hex key passes validation and is preserved verbatim."""
        _clear_config_env()
        os.environ["DEMO_MODE"] = "false"
        os.environ["POLYGON_PRIVATE_KEY"] = DEMO_KEY
        os.environ["POLYGON_ADDRESS"] = VALID_ADDRESS
        try:
            config = _load()
            assert config.POLYGON_PRIVATE_KEY == DEMO_KEY
        finally:
            _clear_config_env()

    def test_demo_mode_substitutes_demo_key(self):
        """DEMO_MODE=true swaps any key for the fixed demo key before checks."""
        _clear_config_env()
        os.environ["DEMO_MODE"] = "true"
        os.environ["POLYGON_PRIVATE_KEY"] = "0" * 64
        try:
            config = _load()
            assert config.POLYGON_PRIVATE_KEY == DEMO_KEY
        finally:
            _clear_config_env()

    def test_invalid_hex_rejected(self):
        """64 chars of non-hex content hit the valid-hex branch."""
        _clear_config_env()
        os.environ["DEMO_MODE"] = "false"
        os.environ["POLYGON_PRIVATE_KEY"] = "z" * 64
        os.environ["POLYGON_ADDRESS"] = VALID_ADDRESS
        try:
            from pydantic import ValidationError

            with pytest.raises(ValidationError, match="valid hex"):
                _load()
        finally:
            _clear_config_env()

    def test_wrong_length_rejected(self):
        """A 63-char key hits the length branch."""
        _clear_config_env()
        os.environ["DEMO_MODE"] = "false"
        os.environ["POLYGON_PRIVATE_KEY"] = "f" * 63
        os.environ["POLYGON_ADDRESS"] = VALID_ADDRESS
        try:
            from pydantic import ValidationError

            with pytest.raises(ValidationError, match="64 hex characters"):
                _load()
        finally:
            _clear_config_env()

    def test_0x_prefix_accepted(self):
        """The 0x prefix is accepted and stripped (normalization as observed)."""
        _clear_config_env()
        os.environ["DEMO_MODE"] = "false"
        os.environ["POLYGON_PRIVATE_KEY"] = "0x" + DEMO_KEY
        os.environ["POLYGON_ADDRESS"] = VALID_ADDRESS
        try:
            config = _load()
            assert config.POLYGON_PRIVATE_KEY == DEMO_KEY
        finally:
            _clear_config_env()
