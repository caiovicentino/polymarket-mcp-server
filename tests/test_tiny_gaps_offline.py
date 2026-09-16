"""
Offline suite closing the last tiny coverage residuals (T-0061, clone main 62bfbc5).

Pins the OBSERVED behavior (L-0090: asserts follow the code, not contract
prose). Suite-only task: src/** is read, never modified.

Branches pinned (baseline measured at clone 62bfbc5 with the full offline
suite: config.py 86 stmts / 4 miss / 28 branches / 3 BrPart / 93.86% missing
"150, 153, 156-158, 213->215"; rate_limiter.py 109 / 2 / 20 / 1 / 97.67%
missing "184-185"; resources/__init__.py absent from the report — module
never imported):

- src/polymarket_mcp/config.py:149-150 — the "0x" prefix strip body
  (v = v[2:]) was never executed by any suite (existing constructions never
  pass a 0x-prefixed key). Covered by test_private_key_0x_prefix_is_stripped.
- src/polymarket_mcp/config.py:152-153 — the 64-hex-chars rejection. Covered
  by test_private_key_wrong_length_rejected.
- src/polymarket_mcp/config.py:156-158 — the int(v, 16) failure path with
  `from None` (config.py:157 comment: the inner int() error would leak key
  material into the traceback). Covered by
  test_private_key_invalid_hex_rejected_without_leaking_key.
- src/polymarket_mcp/config.py:213->215 — to_dict's POLYGON_PRIVATE_KEY mask
  is truthy-gated; the falsy side (empty key passes through UNmasked) is
  reachable offline only via post-construction mutation: model_config
  (config.py:17-22) has NO validate_assignment (observed on pydantic 2.13.5),
  so the mutation is permitted without re-validation. Covered by
  test_to_dict_private_key_falsy_not_masked.
- src/polymarket_mcp/utils/rate_limiter.py:184-185 — acquire() on a category
  whose bucket is absent: logger.warning + return 0.0, BEFORE the backoff and
  bucket paths (no sleep possible). Covered by
  test_rate_limiter_unknown_category_returns_zero_and_warns.
- src/polymarket_mcp/resources/__init__.py:3 — the package was never imported
  by any suite (coverage warning "Module polymarket_mcp.resources was never
  imported"); importing it executes the module. Covered by
  test_resources_package_importable_and_empty.

T-0030 r3 compatibility (draft .agentfarm/drafts/T-0030-r3.md, pending human
patch): the r3 adds an all-zero rejection AFTER the hex check (config.py:159
area: `if int(v, 16) == 0: raise ...`) with its own suite. This suite
deliberately does NOT pin all-zero keys — every synthetic key here is
non-zero ("ab"*32 / "ab"*31+"c" / "z"*64) — so the pinned branches (:150
strip, :153 length, :156-158 hex) survive the r3 hardening intact. Error
messages are pinned by SUBSTRING only (config.py:153/:158 texts, which the
r3 draft does not touch); the all-zero message (r3-introduced) is never
asserted.

`from None` semantics (pydantic 2.13.5 preserves the original ValueError in
ValidationError.errors()[i]["ctx"]["error"]):
- the inner error carries __suppress_context__ True and __cause__ None — the
  from None discriminant (a plain `raise` inside except leaves
  __suppress_context__ False);
- the inner int() message ("invalid literal for int() with base 16") appears
  nowhere in str(excinfo.value) NOR in the rendered traceback chain
  (traceback.format_exception) — that is the leak the config.py:157 comment
  prevents.
- Divergence notes (L-0025/L-0090): (a) pydantic 2.13 TRUNCATES the echoed
  input_value in the rendered error (~25 first + ~25 last chars), so the
  FULL key literal does not appear even though a fragment does — the
  material-absence assertions use the full literal, as the contract
  prescribes; a pydantic change here flips them LOUD, not silently. (b) The
  int() error OBJECT (inner.__context__) still holds the key material in its
  message — `from None` suppresses its RENDERING, not its existence. A
  change that un-suppresses would flip the rendering assertions LOUD.

Hermeticity (house pattern, tests/test_config_security.py:56-90; L-0086b /
L-0130 / P-0035): autouse clean_env strips every POLYGON_*/POLYMARKET_*/
DEMO_MODE/LOG_LEVEL/MAX_*/MIN_*/ENABLE_*/REQUIRE_*/AUTO_* process env var and
every construction passes _env_file=None so pydantic-settings never reads a
.env file regardless of CWD. This module-level fixture shadows
tests/conftest.py's non-autouse clean_env (same pattern as the house suite).

Zero network (L-0118/L-0138) and zero real sleep (L-0120): config.py and
resources do no I/O; the rate-limiter unknown-category path returns before
any sleep — the test replaces rate_limiter.asyncio.sleep with a fail-loud
stub so a future regression that sleeps in this path fails the test instead
of hanging. No pytest markers: this suite runs under the release-gate filter
`-m "not integration and not slow and not real_api and not performance"`
(L-0110).

Coupling notes (L-0073): a fix that (a) adds validate_assignment to
model_config would re-run the validator on the falsy mutation — the falsy
test would fail LOUD on the empty-key error and must be updated in the same
slice; (b) upgrades pydantic away from ctx.error preservation would fail the
`from None` assertions LOUD (_inner_error raises), not silently.

Already covered elsewhere (dedupe, read-only): demo-mode substitution
(config.py:140-141) and empty-key rejection (config.py:144-147) by
tests/test_config_security.py; to_dict truthy masking of the four secrets by
tests/test_config_security.py:101-137; rate-limiter bucket semantics, 429
backoff and get_status by tests/test_rate_limiter.py (T-0036).
"""

import logging
import os
import traceback

import pytest
from pydantic import ValidationError

from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.utils import rate_limiter
from polymarket_mcp.utils.rate_limiter import EndpointCategory, RateLimiter

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


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip config-sourced env vars so tests never see the host environment."""
    for name in list(os.environ):
        if any(name.startswith(prefix) for prefix in _ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


def make_config(**overrides):
    """Hermetic construction: no .env file, valid non-zero key/address."""
    kwargs = {
        "POLYGON_PRIVATE_KEY": "ab" * 32,
        "POLYGON_ADDRESS": "0x" + "a" * 40,
    }
    kwargs.update(overrides)
    return PolymarketConfig(_env_file=None, **kwargs)


def _inner_error(excinfo):
    """Return the validator's original ValueError preserved by pydantic (2.13.5).

    Fail-loud if pydantic stops preserving ctx.error (P-0031) — the from None
    assertions below would otherwise pass vacuously.
    """
    for err in excinfo.value.errors():
        ctx_err = (err.get("ctx") or {}).get("error")
        if ctx_err is not None:
            return ctx_err
    raise AssertionError(
        "pydantic no longer preserves the validator's ValueError in ctx.error"
    )


def test_private_key_without_0x_prefix_accepted():
    """A 64-char non-zero hex key WITHOUT '0x' builds and is kept verbatim.

    Exercises config.py:149 (False arm — no strip), :152 (False arm),
    :154-155 (int(v, 16) parses) and :159 (return v). Discriminates the strip
    branch: the attribute keeps the prefix-free value (compare
    test_private_key_0x_prefix_is_stripped, which exercises the True arm).
    """
    config = make_config(POLYGON_PRIVATE_KEY="ab" * 32)
    assert config.POLYGON_PRIVATE_KEY == "ab" * 32


def test_private_key_0x_prefix_is_stripped():
    """A '0x'-prefixed 64-char key is silently stripped to the bare 64 chars.

    Exercises config.py:149 (True arm) and :150 (the strip body — never
    executed by any suite before this one). Pin of the OBSERVED behavior
    (L-0090): the prefix is discarded silently. Order discriminant (L-0128e):
    the key is 66 chars INCLUDING the prefix — a length check that ran BEFORE
    the strip would reject it, so the construction succeeding also proves the
    strip precedes the length check (config.py:150 -> :152).
    """
    config = make_config(POLYGON_PRIVATE_KEY="0x" + "ab" * 32)
    assert config.POLYGON_PRIVATE_KEY == "ab" * 32
    assert not config.POLYGON_PRIVATE_KEY.startswith("0x")


def test_private_key_wrong_length_rejected():
    """A 63-char key raises ValidationError (config.py:152-153).

    The full key literal does not leak into the rendered ValidationError
    (observed: pydantic 2.13.5 truncates the echoed input_value). The message
    substring is the branch discriminator (config.py:153, r3-stable).
    """
    key = "ab" * 31 + "c"  # 63 hex chars, non-zero
    with pytest.raises(ValidationError) as excinfo:
        make_config(POLYGON_PRIVATE_KEY=key)
    rendered = str(excinfo.value)
    assert key not in rendered
    assert "64 hex characters" in rendered


def test_private_key_invalid_hex_rejected_without_leaking_key():
    """A 64-char non-hex key raises with the int() context SUPPRESSED.

    config.py:156-158: `raise ValueError("POLYGON_PRIVATE_KEY must be valid
    hex") from None`; the config.py:157 comment explains why: the inner int()
    error would leak key material into the traceback. Pinned semantically:

    - the inner error carries __suppress_context__ True and __cause__ None —
      the from None discriminant (a plain raise inside except leaves
      __suppress_context__ False);
    - the inner int() message ("invalid literal for int() with base 16")
      appears nowhere in str(excinfo.value) NOR in the rendered traceback
      chain (traceback.format_exception) — the leak is prevented;
    - the full key literal does not appear in the rendered ValidationError
      (observed: pydantic 2.13.5 truncates the echoed input_value).
    """
    key = "z" * 64  # 64 chars, non-hex, non-zero
    with pytest.raises(ValidationError) as excinfo:
        make_config(POLYGON_PRIVATE_KEY=key)
    rendered = str(excinfo.value)
    chain = "".join(traceback.format_exception(excinfo.value))
    assert key not in rendered
    assert key not in chain
    assert "invalid literal for int() with base 16" not in rendered
    assert "invalid literal for int() with base 16" not in chain
    assert "valid hex" in rendered  # branch discriminator (observed)

    inner = _inner_error(excinfo)
    assert isinstance(inner, ValueError)
    assert "valid hex" in str(inner)
    assert key not in str(inner)
    assert inner.__suppress_context__ is True
    assert inner.__cause__ is None


def test_to_dict_private_key_falsy_not_masked():
    """to_dict masks POLYGON_PRIVATE_KEY only when truthy (branch 213->215).

    Observed (L-0090): a falsy (empty-string) key passes through UNmasked —
    the dict carries "" instead of "***HIDDEN***". Reachable offline only via
    post-construction mutation: model_config (config.py:17-22) has NO
    validate_assignment (observed), so the mutation is permitted without
    re-validation. Documents the REAL behavior; the truthy side is already
    pinned by tests/test_config_security.py:101-137 and is asserted here on
    the SAME object so both sides of the branch are visible in one test.
    """
    config = make_config()
    assert config.to_dict()["POLYGON_PRIVATE_KEY"] == "***HIDDEN***"

    config.POLYGON_PRIVATE_KEY = ""  # permitted: no validate_assignment
    assert config.POLYGON_PRIVATE_KEY == ""
    masked = config.to_dict()
    assert masked["POLYGON_PRIVATE_KEY"] == ""
    assert masked["POLYGON_PRIVATE_KEY"] != "***HIDDEN***"


async def test_rate_limiter_unknown_category_returns_zero_and_warns(monkeypatch, caplog):
    """acquire() on a category with no bucket warns and returns 0.0.

    Exercises rate_limiter.py:183-185 (the guard: bucket missing ->
    logger.warning("Unknown category: ...") -> return 0.0). The guard fires
    BEFORE the backoff and bucket paths, so no sleep is possible — asserted
    by replacing rate_limiter.asyncio.sleep with a fail-loud stub (L-0120:
    zero real sleep in wall time; a regression that sleeps in this path
    fails the test instead of hanging).
    """

    async def fail_loud_sleep(seconds):
        raise AssertionError(f"rate limiter slept {seconds!r}s in the unknown-category path")

    monkeypatch.setattr(rate_limiter.asyncio, "sleep", fail_loud_sleep)

    limiter = RateLimiter()
    limiter.buckets.pop(EndpointCategory.CLOB_GENERAL)
    with caplog.at_level(logging.WARNING, logger="polymarket_mcp.utils.rate_limiter"):
        result = await limiter.acquire(EndpointCategory.CLOB_GENERAL)

    assert result == 0.0
    assert "Unknown category" in caplog.text
    records = [
        r for r in caplog.records if r.name == "polymarket_mcp.utils.rate_limiter"
    ]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING


def test_resources_package_importable_and_empty():
    """The resources package executes and exposes __all__ == [] (observed).

    resources/__init__.py is 2 statements (docstring at :1, __all__ = [] at
    :3) and was never imported by any suite before this one (coverage
    warning: "Module polymarket_mcp.resources was never imported").
    """
    import polymarket_mcp.resources

    assert polymarket_mcp.resources.__all__ == []
