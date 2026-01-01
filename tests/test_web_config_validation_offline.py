"""
Offline regression suite for POST /api/config input validation
(src/polymarket_mcp/web/app.py, ConfigUpdateRequest).

T-0220 — Facet A: the request model had 8 float/bool fields with ZERO
constraints; three defects were proven RED pre-fix on the unfixed worktree
(curator probes re-executed, `PROBE-*` lines in the task report):

1. `NaN` in the raw JSON body -> 200 + `.env` written with `nan` (dashboard cap
   comparisons become False — SEC-ADVR-A1 class).
2. `max_spread_tolerance: 2.0` (outside the real 0..1 range) -> 200 + `.env`
   written with `2.0`; on re-install `load_config()` REJECTS the file
   ("MAX_SPREAD_TOLERANCE must be between 0 and 1" — observed in the probe
   logs) = bricked .env.
3. `max_order_size_usd: -1.0` -> 200 — negative limit accepted and persisted.

The fix prescribes pydantic Field constraints on the model (the handler
`update_config` is UNTOUCHED — FastAPI validates BEFORE the handler runs, so
the write only ever sees valid values):

    max_order_size_usd / max_total_exposure_usd / max_position_size_per_market /
    min_liquidity_required           -> Field(gt=0, allow_inf_nan=False)
    max_spread_tolerance             -> Field(ge=0, le=1, allow_inf_nan=False)
    require_confirmation_above_usd   -> Field(ge=0, allow_inf_nan=False)
    enable_autonomous_trading / auto_cancel_on_large_spread -> bool (unchanged)

QUIRKS pinned as OBSERVED (L-0090/L-0020 — semantic pin, not literal):
- `NaN` with allow_inf_nan=False -> pydantic rejects -> FastAPI builds a 422
  whose `detail` ECHOES the input NaN -> Starlette's JSONResponse render raises
  ("Out of range float values are not JSON compliant") -> the CLIENT sees 500.
  The pin is therefore SEMANTIC: `status != 200` + `.env` byte-identical —
  NEVER the literal 422/500. (Observed post-fix: 500 "Internal Server Error"
  with TestClient(raise_server_exceptions=False).)
- `require_confirmation_above_usd: 0.0` is VALID (ge=0); `max_spread_tolerance`
  0.0 and 1.0 are VALID (boundary inclusive) — pinned by
  test_boundary_values_accepted.
- Invalid payloads never reach the handler: `wa.stats["api_calls"]` stays 0
  (FastAPI validates before the route body).

COMPATIBILITY pins (coexistence, NOT duplication):
- The response body of a valid POST keeps its shape
  `{"success": True, "message": ...}` (frontend consumers, T-0216 coexistence:
  the API does not sanitize market data, and the security-headers middleware
  of the sibling suite does not touch bodies).
- The .env rewrite format (str(float), str(bool).lower(), unmanaged lines and
  secrets preserved) is pinned by tests/test_web_app_offline.py — this suite
  only asserts the NEW values land (e.g. MAX_ORDER_SIZE_USD=1500.0).

Hermeticity: Path(".env") is written RELATIVE TO CWD — every POST runs under
monkeypatch.chdir(tmp_path) with the .env pre-created there; the worktree root
is asserted .env-free before/after (fail-loud guard mirroring
tests/test_web_app_offline.py:279). load_mcp_config() after a valid write reads
the REWRITTEN .env — clean_env delenvs the 8 managed keys so the .env value
wins in pydantic priority; wallet_env supplies the dummy wallet so the reload
succeeds deterministically. The autouse pristine_web_state fixture restores
module globals (stats copy; config/client/safety_limits/active_websockets),
keeping the suite order-independent (proven by running it twice). Zero network;
no SDK on any exercised path.
"""

import pathlib

import pytest
from fastapi.testclient import TestClient

from polymarket_mcp.web import app as wa

# Dummy wallet: the house-standard offline key (valid 64-hex format, zero value).
DUMMY_PRIVATE_KEY = "0" * 63 + "1"
DUMMY_ADDRESS = "0x" + "0" * 40

# CWD at import time == the worktree root (pytest is invoked from there).
_WORKTREE_ROOT = pathlib.Path.cwd()

# Every env key the web module can observe — cleared per test so .env values in
# the isolated CWD win over ambient environment in reload assertions (mirrors
# tests/test_web_app_offline.py _KEYS_CLEANED; pydantic BaseSettings reads HOST
# env for fields not passed explicitly — L-0130/P-0036 face).
_KEYS_CLEANED = (
    "POLYGON_PRIVATE_KEY",
    "POLYGON_ADDRESS",
    "POLYMARKET_API_KEY",
    "POLYMARKET_API_SECRET",
    "POLYMARKET_PASSPHRASE",
    "POLYMARKET_API_KEY_NAME",
    "DEMO_MODE",
    "WEB_HOST",
    "WEB_PORT",
    "MAX_ORDER_SIZE_USD",
    "MAX_TOTAL_EXPOSURE_USD",
    "MAX_POSITION_SIZE_PER_MARKET",
    "MIN_LIQUIDITY_REQUIRED",
    "MAX_SPREAD_TOLERANCE",
    "ENABLE_AUTONOMOUS_TRADING",
    "REQUIRE_CONFIRMATION_ABOVE_USD",
    "AUTO_CANCEL_ON_LARGE_SPREAD",
)

# Full valid ConfigUpdateRequest body (all 8 fields) — the seed for every probe.
_VALID_PAYLOAD = {
    "max_order_size_usd": 1500.0,
    "max_total_exposure_usd": 50.0,
    "max_position_size_per_market": 20.0,
    "min_liquidity_required": 100.0,
    "max_spread_tolerance": 0.02,
    "enable_autonomous_trading": False,
    "require_confirmation_above_usd": 25.0,
    "auto_cancel_on_large_spread": False,
}

# Raw JSON body carrying a literal NaN (the `json=` kwarg of httpx rejects NaN
# at ENCODE time — the vector requires raw bytes; Python's json parser accepts
# NaN, then pydantic's allow_inf_nan=False rejects it).
NAN_BODY = (
    b'{"max_order_size_usd": NaN, "max_total_exposure_usd": 50.0,'
    b' "max_position_size_per_market": 20.0, "min_liquidity_required": 100.0,'
    b' "max_spread_tolerance": 0.02, "enable_autonomous_trading": false,'
    b' "require_confirmation_above_usd": 25.0, "auto_cancel_on_large_spread": false}'
)

# The .env every route-under-test starts from: the 8 managed keys (all rewritten
# by a valid POST) plus an unmanaged line and a secret line (both preserved).
_ENV_BODY = (
    "MAX_ORDER_SIZE_USD=999.0\n"
    "MAX_TOTAL_EXPOSURE_USD=4000.0\n"
    "MAX_POSITION_SIZE_PER_MARKET=1500.0\n"
    "MIN_LIQUIDITY_REQUIRED=20000.0\n"
    "MAX_SPREAD_TOLERANCE=0.03\n"
    "ENABLE_AUTONOMOUS_TRADING=true\n"
    "REQUIRE_CONFIRMATION_ABOVE_USD=30.0\n"
    "AUTO_CANCEL_ON_LARGE_SPREAD=true\n"
    "OTHER_KEY=keepme\n"
    "POLYGON_PRIVATE_KEY=real-secret-kept\n"
)

# Captured at import time, before any test runs: the pristine stats dict.
_PRISTINE_STATS = dict(wa.stats)


def _assert_no_env_in_worktree() -> None:
    """Fail loud if a .env appeared in the worktree root (hermeticity guard)."""
    assert not (_WORKTREE_ROOT / ".env").exists(), (
        "A .env file appeared in the worktree root — POST /api/config must only "
        "write under the isolated tmp CWD. Refusing to run: hermeticity "
        "precondition violated."
    )


@pytest.fixture(autouse=True)
def pristine_web_state():
    """Reset web.app module globals per test and restore the originals."""
    wa.config = None
    wa.client = None
    wa.safety_limits = None
    wa.active_websockets = []
    wa.stats = dict(_PRISTINE_STATS)
    yield
    wa.config = None
    wa.client = None
    wa.safety_limits = None
    wa.active_websockets = []
    wa.stats = _PRISTINE_STATS


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch):
    """Remove every env key the web module can observe; return the monkeypatch."""
    for key in _KEYS_CLEANED:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


@pytest.fixture()
def wallet_env(clean_env, monkeypatch: pytest.MonkeyPatch):
    """Env with a valid dummy wallet so load_config() succeeds."""
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", DUMMY_PRIVATE_KEY)
    monkeypatch.setenv("POLYGON_ADDRESS", DUMMY_ADDRESS)
    return monkeypatch


def test_nan_rejected_env_untouched(tmp_path, monkeypatch, wallet_env):
    """NaN in the raw body -> NOT 200 (observed 500 quirk) + .env byte-identical.

    Mechanism (observed, L-0090): pydantic rejects NaN (allow_inf_nan=False) ->
    FastAPI's 422 detail echoes the input NaN -> the JSONResponse render raises
    ("Out of range float values are not JSON compliant") -> the client sees 500
    (TestClient(raise_server_exceptions=False)). The pin is semantic on
    purpose: any rejection status satisfies it; the .env must stay byte-
    identical either way.
    """
    _assert_no_env_in_worktree()
    (tmp_path / ".env").write_text(_ENV_BODY)
    monkeypatch.chdir(tmp_path)
    before = (tmp_path / ".env").read_bytes()
    response = TestClient(wa.app, raise_server_exceptions=False).post(
        "/api/config",
        content=NAN_BODY,
        headers={"content-type": "application/json"},
    )
    assert response.status_code != 200, (
        f"NaN was accepted (status {response.status_code}) — allow_inf_nan=False "
        "is not enforced"
    )
    assert (tmp_path / ".env").read_bytes() == before, ".env was mutated by a NaN POST"
    # Validation happens BEFORE the handler: no api_calls, no errors.
    assert wa.stats["api_calls"] == 0
    assert wa.stats["errors"] == 0


def test_spread_above_one_rejected_422(tmp_path, monkeypatch, wallet_env):
    """max_spread_tolerance=2.0 -> 422 (le=1) + .env byte-identical."""
    _assert_no_env_in_worktree()
    (tmp_path / ".env").write_text(_ENV_BODY)
    monkeypatch.chdir(tmp_path)
    before = (tmp_path / ".env").read_bytes()
    response = TestClient(wa.app).post(
        "/api/config", json={**_VALID_PAYLOAD, "max_spread_tolerance": 2.0}
    )
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert errors[0]["loc"] == ["body", "max_spread_tolerance"]
    assert errors[0]["type"] == "less_than_equal"
    assert (tmp_path / ".env").read_bytes() == before, (
        ".env was mutated by an out-of-range spread POST"
    )
    assert wa.stats["api_calls"] == 0


def test_negative_values_rejected_422(tmp_path, monkeypatch, wallet_env):
    """max_order_size_usd=-1.0 -> 422 (gt=0) + .env byte-identical."""
    _assert_no_env_in_worktree()
    (tmp_path / ".env").write_text(_ENV_BODY)
    monkeypatch.chdir(tmp_path)
    before = (tmp_path / ".env").read_bytes()
    response = TestClient(wa.app).post(
        "/api/config", json={**_VALID_PAYLOAD, "max_order_size_usd": -1.0}
    )
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert errors[0]["loc"] == ["body", "max_order_size_usd"]
    assert errors[0]["type"] == "greater_than"
    assert (tmp_path / ".env").read_bytes() == before, (
        ".env was mutated by a negative-limit POST"
    )
    assert wa.stats["api_calls"] == 0


def test_valid_update_rewrites_env_200(tmp_path, monkeypatch, wallet_env):
    """A fully valid POST -> 200 + the .env rewritten with the NEW values
    (exact str(float)/str(bool).lower() formats), unmanaged lines and secrets
    preserved in place."""
    _assert_no_env_in_worktree()
    (tmp_path / ".env").write_text(_ENV_BODY)
    monkeypatch.chdir(tmp_path)
    response = TestClient(wa.app).post("/api/config", json=_VALID_PAYLOAD)
    assert response.status_code == 200
    expected = (
        "MAX_ORDER_SIZE_USD=1500.0\n"
        "MAX_TOTAL_EXPOSURE_USD=50.0\n"
        "MAX_POSITION_SIZE_PER_MARKET=20.0\n"
        "MIN_LIQUIDITY_REQUIRED=100.0\n"
        "MAX_SPREAD_TOLERANCE=0.02\n"
        "ENABLE_AUTONOMOUS_TRADING=false\n"
        "REQUIRE_CONFIRMATION_ABOVE_USD=25.0\n"
        "AUTO_CANCEL_ON_LARGE_SPREAD=false\n"
        "OTHER_KEY=keepme\n"
        "POLYGON_PRIVATE_KEY=real-secret-kept\n"
    )
    assert (tmp_path / ".env").read_text() == expected
    assert wa.stats["errors"] == 0


def test_boundary_values_accepted(tmp_path, monkeypatch, wallet_env):
    """Boundaries are INCLUSIVE: max_spread_tolerance 0.0 and 1.0 -> 200 each;
    require_confirmation_above_usd 0.0 -> 200 (ge=0)."""
    _assert_no_env_in_worktree()
    (tmp_path / ".env").write_text(_ENV_BODY)
    monkeypatch.chdir(tmp_path)
    client = TestClient(wa.app)

    r_zero = client.post(
        "/api/config", json={**_VALID_PAYLOAD, "max_spread_tolerance": 0.0}
    )
    assert r_zero.status_code == 200
    assert "MAX_SPREAD_TOLERANCE=0.0" in (tmp_path / ".env").read_text()

    r_one = client.post(
        "/api/config", json={**_VALID_PAYLOAD, "max_spread_tolerance": 1.0}
    )
    assert r_one.status_code == 200
    assert "MAX_SPREAD_TOLERANCE=1.0" in (tmp_path / ".env").read_text()

    r_confirm = client.post(
        "/api/config", json={**_VALID_PAYLOAD, "require_confirmation_above_usd": 0.0}
    )
    assert r_confirm.status_code == 200
    assert "REQUIRE_CONFIRMATION_ABOVE_USD=0.0" in (tmp_path / ".env").read_text()


def test_api_response_shape_unchanged(tmp_path, monkeypatch, wallet_env):
    """A valid POST keeps the response body shape exactly
    {"success": True, "message": ...} — the frontend consumers (T-0216
    coexistence) depend on this contract; the security-headers middleware of
    the sibling suite does not touch bodies."""
    _assert_no_env_in_worktree()
    (tmp_path / ".env").write_text(_ENV_BODY)
    monkeypatch.chdir(tmp_path)
    response = TestClient(wa.app).post("/api/config", json=_VALID_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"success", "message"}
    assert body["success"] is True
    assert "Configuration updated successfully" in body["message"]
