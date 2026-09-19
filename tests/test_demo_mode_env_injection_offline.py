"""Offline pin: the POLYMARKET_DEMO_MODE env injection must never disarm the
private-key hex validation (gap SW3-P1-2, xfail-strict).

Gap (SW3-P1-2, first-hand source: proposals/ci-audit-2026-09-19-sweep3.md):
T-0271 (PR #109) maps the CI demo env onto the DEMO_MODE field via
``validation_alias=AliasChoices("DEMO_MODE", "POLYMARKET_DEMO_MODE")``. With
that mapping in place, ANY process carrying ``POLYMARKET_DEMO_MODE=true`` in
its environment (the CI demo step, tests.yml demo-mode step) activates the
demo-skip of ``validate_private_key`` (config.py:140-141) and the offline
security pin
``tests/test_init_error_sanitization_offline.py::test_validation_error_hex_echo_redacted_in_log``
stops raising ("DID NOT RAISE ValidationError", CI run 35431170179). The fix
for the semantic gap is a separate slice (owner channel, items 112/198); this
suite PINS, it does not fix.

STATE-AWARE PIN (L-0025/L-0340 divergence declared in the report):
the task inputs assumed T-0271 was already merged into main. First-hand
re-proof at claim time (2026-09-19): PR #109 is OPEN (never merged) and
``git log main -S AliasChoices`` is empty - the mapping is ABSENT from main @
69acd97. The suite therefore derives the code state at module import from the
field itself (``_ALIAS_PRESENT``) and pins BOTH states:

- State N (mapping absent, main today): the prefixed env is inert (demo stays
  False) and every invalid-hex vector raises - all six tests pass as plain
  PASSED pins of the healthy behavior (6 passed, 0 xfailed).
- State M (mapping present, post-T-0271, fix pending): the env activates demo
  mode and ``test_demo_mode_does_not_disable_hex_validation`` becomes XFAILED
  (the gap, expected-failure). 5 passed + 1 xfailed.
- State M post-fix: the same test XPASSes under ``strict=True`` and turns the
  suite RED - the flip signal the fixing slice consumes (never silent,
  L-0025/L-0030).

Load-bearing pytest 9.1.1 caveat (probed first-hand): ``pytest.mark.xfail``
does NOT call a callable condition - a callable is truthy-evaluated (the
condition function is never invoked), which would arm the xfail in the WRONG
state. The condition is therefore a module-import-time BOOLEAN derived by code
introspection (anti-tautologia: derived from the code under test, not
hardcoded).

Hermeticity (FA-0038): pydantic-settings reads the HOST environment for every
field not passed explicitly, even with ``_env_file=None`` (which only disables
the .env file). The autouse fixture delenv's every config-relevant key before
each test (monkeypatch restores at teardown, so cross-test session fixtures
keep working); every construction passes ``_env_file=None``. A ``.env`` in the
worktree root would invalidate the hermeticity precondition (guard mirrors
test_web_app_offline.py:279).

Declared residual (out of scope): ``str(ValidationError)`` still echoes a
truncated copy of the key - documented residual of
tests/test_init_error_sanitization_offline.py:15-16; the sanitized diagnostic
message ("must be valid hex") is what this suite pins. The ``validate_address``
non-hex acceptance is the same security class (item 198) and is a register-only
follow-up here (not pinnable without the coupled flip).

Divergence from the contract's literal example: ``("0xzz" * 20)`` is 78 chars
after the 0x strip and triggers the LENGTH branch ("must be 64 hex
characters"), not the hex branch; the sanitized-message pin requires a
valid-length invalid-hex key, so the vectors mirror the existing pin's
construction (the exact CI-failure shape, same class of input).
"""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from polymarket_mcp.config import PolymarketConfig

VALID_KEY = "a" * 64
VALID_ADDRESS = "0x" + "a" * 40
# 64 chars, valid length, invalid hex (leading 'g'): the exact CI-failure
# shape of test_init_error_sanitization_offline.py:44-53 (_invalid_hex_key_error).
_KEY_HEX_64 = "b73b1c5c0f1c78b7a91f2e0a8c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d"
INVALID_HEX_KEY = "g" + _KEY_HEX_64[1:]

# Demo placeholder substituted by validate_private_key in demo mode
# (config.py:140-141, pre-existing on main).
DEMO_PLACEHOLDER_KEY = "0" * 63 + "1"

# Env surface this suite controls (narrow scope: the vectors only depend on
# these; the config-security suite carries the wider strip for its own pins).
_ENV_PREFIXES = ("POLYMARKET_", "POLYGON_")
_ENV_UNPREFIXED_KEYS = ("DEMO_MODE",)


def _demo_env_alias_present() -> bool:
    """True when POLYMARKET_DEMO_MODE maps to the DEMO_MODE field via alias.

    Code-derived (L-0020/L-0025): introspects the DEMO_MODE field's
    validation_alias. AliasChoices("DEMO_MODE", "POLYMARKET_DEMO_MODE") is the
    T-0271 shape (config.py:25-33 on the PR branch); absent or other alias
    forms read as False - the conservative direction: the suite keeps pinning
    the healthy state and the consuming slice re-derives.
    """
    alias = PolymarketConfig.model_fields["DEMO_MODE"].validation_alias
    if alias is None:
        return False
    choices = getattr(alias, "choices", ())
    return "POLYMARKET_DEMO_MODE" in choices


# Evaluated ONCE at module import: the xfail condition must be a BOOLEAN
# (pytest 9.1.1 does not call callable conditions - see module docstring).
_ALIAS_PRESENT = _demo_env_alias_present()


def _assert_no_env_in_worktree() -> None:
    """Fail loud if a .env appeared in the worktree root (hermeticity guard).

    Mirrors test_web_app_offline.py:279 (root resolved from this file, so the
    guard is cwd-independent): every construction here passes _env_file=None,
    so a .env in the root would mean the precondition drifted.
    """
    root = Path(__file__).resolve().parent.parent
    assert not (root / ".env").exists(), (
        "A .env file appeared in the worktree root - the demo-mode-env-injection "
        "suite requires a clean root (hermeticity precondition violated; "
        "mirrors test_web_app_offline.py:279)."
    )


@pytest.fixture(autouse=True)
def _clean_config_env(monkeypatch):
    """FA-0038: delenv every config-relevant key before each test.

    pydantic-settings reads the HOST environment for every field not passed
    explicitly, even with ``_env_file=None`` (which only disables the .env
    file). Covers DEMO_MODE, POLYMARKET_DEMO_MODE, POLYGON_PRIVATE_KEY,
    POLYGON_ADDRESS and every POLYMARKET_/POLYGON_ prefixed key - including
    values planted session-wide by conftest's test_env_vars fixture when
    another module activates it. monkeypatch restores the recorded values at
    teardown.
    """
    _assert_no_env_in_worktree()
    for key in _ENV_UNPREFIXED_KEYS:
        monkeypatch.delenv(key, raising=False)
    for var in [name for name in list(os.environ) if name.startswith(_ENV_PREFIXES)]:
        monkeypatch.delenv(var, raising=False)
    yield


def _demo_env_config(monkeypatch, *, key):
    """The CI demo vector: POLYMARKET_DEMO_MODE=true + config WITHOUT the
    DEMO_MODE kwarg (mirrors the construction of
    test_init_error_sanitization_offline.py::_invalid_hex_key_error: env-only
    demo flag, explicit key/address kwargs, .env disabled)."""
    monkeypatch.setenv("POLYMARKET_DEMO_MODE", "true")
    return PolymarketConfig(
        _env_file=None,
        POLYGON_PRIVATE_KEY=key,
        POLYGON_ADDRESS=VALID_ADDRESS,
    )


def test_demo_mode_env_sets_config_flag(monkeypatch):
    """State table: mapping absent -> demo stays False (the prefixed env is
    inert - pins that no accidental activation exists before the mapping
    lands); mapping present -> demo_mode is True (the T-0271 feature pin:
    feature, not bug)."""
    cfg = _demo_env_config(monkeypatch, key=VALID_KEY)
    if _ALIAS_PRESENT:
        assert cfg.DEMO_MODE is True, (
            "the POLYMARKET_DEMO_MODE env must reach the DEMO_MODE field "
            "(T-0271 mapping)"
        )
    else:
        assert cfg.DEMO_MODE is False, (
            "the POLYMARKET_DEMO_MODE env is inert on this tree (no alias "
            "mapping); demo mode must not activate from the prefixed env"
        )


def test_demo_mode_alias_precedence_observed(monkeypatch):
    """The DEMO_MODE env value wins over POLYMARKET_DEMO_MODE in both
    directions (paired negation, L-0056).

    Derivation (anti-tautologia: derived from the code, not hardcoded): with
    the alias present the winner is the FIRST AliasChoices choice - asserted
    against the introspected declared order (AliasChoices("DEMO_MODE",
    "POLYMARKET_DEMO_MODE"), config.py:29 on the T-0271 branch); with the
    alias absent the winner is the field name itself (pydantic-settings env
    mapping) and the prefixed env is inert (probed first-hand on main @
    69acd97)."""
    alias = PolymarketConfig.model_fields["DEMO_MODE"].validation_alias
    if alias is not None:
        choices = list(getattr(alias, "choices", ()))
        assert choices[:1] == ["DEMO_MODE"], (
            "the AliasChoices declared order drifted: the first choice must "
            f"stay 'DEMO_MODE' (introspected: {choices!r})"
        )
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("POLYMARKET_DEMO_MODE", "false")
    cfg = PolymarketConfig(
        _env_file=None, POLYGON_PRIVATE_KEY=VALID_KEY, POLYGON_ADDRESS=VALID_ADDRESS
    )
    assert cfg.DEMO_MODE is True, "the DEMO_MODE env value must win (direction 1)"
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("POLYMARKET_DEMO_MODE", "true")
    cfg = PolymarketConfig(
        _env_file=None, POLYGON_PRIVATE_KEY=VALID_KEY, POLYGON_ADDRESS=VALID_ADDRESS
    )
    assert cfg.DEMO_MODE is False, "the DEMO_MODE env value must win (direction 2)"


@pytest.mark.xfail(
    condition=_ALIAS_PRESENT,
    reason=(
        "gap SW3-P1-2 (T-0271 alias present): the demo env suppresses hex "
        "validation - DID NOT RAISE; the fix (items 112/198) flips this"
    ),
    strict=True,
)
def test_demo_mode_does_not_disable_hex_validation(monkeypatch):
    """Semantic target: hex FORMAT is validated EVEN in demo mode.

    xfail-strict arms only when the T-0271 alias is present (condition
    ``_ALIAS_PRESENT`` is a module-import-time boolean; pytest 9.1.1 does not
    call callable conditions). Mapping absent (main today): the env is inert,
    the raise happens and the test passes as a plain regression pin of the
    healthy path. Mapping present, fix pending: DID NOT RAISE -> XFAILED (the
    gap). Mapping present, fixed: raises -> XPASS(strict) turns the suite RED
    (the flip signal consumed by the fixing slice - never silent, L-0025)."""
    with pytest.raises(ValidationError, match="must be valid hex"):
        _demo_env_config(monkeypatch, key=INVALID_HEX_KEY)


def test_no_demo_mode_env_invalid_hex_raises(monkeypatch):
    """Control (L-0056): WITHOUT any demo env the invalid-hex key raises with
    the sanitized branch message - the healthy behavior that the fix must
    never break, pinned in every code state."""
    with pytest.raises(ValidationError, match="must be valid hex"):
        PolymarketConfig(
            _env_file=None,
            POLYGON_PRIVATE_KEY=INVALID_HEX_KEY,
            POLYGON_ADDRESS=VALID_ADDRESS,
        )


def test_demo_mode_env_valid_hex_unchanged(monkeypatch):
    """A VALID hex key boots in every state (the fix may never break the
    legit demo path). The resulting key value is intentionally unpinned: the
    demo-skip substitutes the placeholder (config.py:140-141) while demo-skip
    lasts, and the fixed semantics either keep it or keep the caller's key."""
    cfg = _demo_env_config(monkeypatch, key=VALID_KEY)
    assert cfg.POLYGON_PRIVATE_KEY in (VALID_KEY, DEMO_PLACEHOLDER_KEY)


def test_ci_demo_env_replicates_required_check_failure_shape(monkeypatch):
    """Oracle of the CI window: the exact required-check vector
    (POLYMARKET_DEMO_MODE=true + config WITHOUT the DEMO_MODE kwarg, the
    construction of test_init_error_sanitization_offline) with the outcome
    table declared per state (state-aware, L-0025):

    - mapping absent (main today): the shape does NOT reproduce - the
      construction raises with the sanitized message (the security pin stays
      armed). A raise-less outcome here would be a NEW regression: the
      validator broke independent of demo mode, fail loud.
    - mapping present, fix pending (the bug window): the construction
      succeeds with the demo placeholder - the demo-skip mechanism is pinned
      (config.py:140-141) and the outcome is declared here and in the report.
    - mapping present, fixed: the construction raises again; the branch
      message survives. The flip oracle itself is
      test_demo_mode_does_not_disable_hex_validation (xfail-strict); this
      branch pins only the sanitized message.
    """
    try:
        cfg = _demo_env_config(monkeypatch, key=INVALID_HEX_KEY)
    except ValidationError as exc:
        assert "must be valid hex" in str(exc), (
            "the sanitized branch message survives (raise observed)"
        )
        return
    if not _ALIAS_PRESENT:
        pytest.fail(
            "mapping absent but the CI-shape vector did not raise: the "
            "validator broke independent of demo mode (new regression)"
        )
    assert cfg.DEMO_MODE is True, (
        "the CI env activates demo mode (T-0271 mapping): the bug window is "
        "reproduced and declared"
    )
    assert cfg.POLYGON_PRIVATE_KEY == DEMO_PLACEHOLDER_KEY, (
        "the demo-skip substituted the placeholder (config.py:140-141): the "
        "DID NOT RAISE shape of CI run 35431170179"
    )
