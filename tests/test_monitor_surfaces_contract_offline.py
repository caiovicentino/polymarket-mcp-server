"""
Offline contract suite for the monitor surfaces (item 158 -- T-0445).

Two defects are re-proven first-hand at the emission fork-point (7e4ed3a, the
sister suite's OBSERVED pins test_web_app_offline.py FINDING-1/FINDING-2):

- FINDING-1: GET /api/stats always 500s. The handler feeds
  stats["uptime_start"] (a datetime) to JSONResponse, whose json.dumps raises
  TypeError("Object of type datetime is not JSON serializable"). The monitor
  panel polls /api/stats every 5s -- so on any configured deploy the
  observability feed is dead.
- FINDING-2: GET /monitoring 500s whenever config is set (the NORMAL state).
  The Jinja loop renders status.remaining/status.limit (monitoring.html),
  keys the real RateLimiter.get_status() payload never provides (it has
  available_tokens/max_tokens/refill_rate_per_sec/backoff_remaining_sec/
  is_throttled) -> jinja2.UndefinedError RAISES during render. The page only
  renders in the no-config state (the else-branch).

Contract shape (house pattern T-0339/T-0340/T-0404/T-0433): the suite pins the
DESIRED behavior as xfail(strict=True); when the item-158 fix lands
(serialization in app.py + template fields + client-side panel), the xfails
XPASS -> strict RED -> forces the flip of ALL pins in the SAME PR: the 2
OBSERVED pins in the sister suite (:463-476, :543-560) + the 4 xfails here.
One fix, one package.

The 4 xfails-strict (desired behavior, broken today):
1. test_api_stats_returns_200_json_payload -- 200 with a JSON body
   (requests_total present). RED pre: the tolerant client sees 500.
2. test_monitoring_renders_200_with_config -- 200 + "API Rate Limits". TRAP
   (proven in the preflight sim): the crash is a RAISE (UndefinedError), not
   an assert-failure -- xfail only captures FAILURES. The test converts the
   raise into an explicit assert failure (status = "raised: ...") so the RED
   reason carries the real mechanism. Config enters via
   monkeypatch.setattr(wa, "config", load_config()) (house pattern :463 -- the
   lifespan is NOT needed: the route reads the global directly).
3. test_template_reads_real_rate_limit_fields -- grep-pin:
   status.available_tokens/status.max_tokens PRESENT,
   status.limit/status.remaining ABSENT in monitoring.html.
4. test_template_fetches_api_status_and_renders_safely -- grep-pin:
   fetch('/api/status'), is_throttled, backoff_remaining_sec, esc( present.
   TRAP (proven in the preflight sim): the checked function name MUST carry
   the test_ prefix or pytest never collects it (it silently "passes" by
   absence -- a false GREEN would hide the gap).

The 3 greens (guards over what must NOT change):
5. test_monitoring_renders_200_without_config -- 200 + "No rate limit data
   available" (the else-branch half of the sister OBSERVED pin).
6. test_api_status_contract_has_full_limiter_shape -- the panel's DATA
   source: /api/status (under lifespan) -> 200 + connected:True + rate_limits
   with EXACTLY 7 categories (clob_general, market_data, batch_ops,
   trading_burst, trading_sustained, gamma_api, data_api) x EXACTLY 5 keys
   (available_tokens, max_tokens, refill_rate_per_sec, backoff_remaining_sec,
   is_throttled). The fixture uses lifespan (with TestClient(wa.app)):
   WITHOUT it the route answers connected:False with an EMPTY rate_limits
   (proven first-hand in the preflight).
7. test_stats_interval_still_polls_api_stats -- anti-over-fix: the 5s
   interval keeps polling /api/stats (the fix ADDS a fetch, never replaces).

Isolation (order-dependence proven first-hand in the preflight): web.app
writes config/client/safety_limits/stats as PROCESS globals (lifespan AND
handlers). Without the reset, the no-config test REDs when it runs AFTER a
configured test (the global leaks). The autouse fixture below mirrors
pristine_web_state (test_web_app_offline.py) EXACTLY: pristine baseline
before AND after each test.

Delta (L-0260): baseline 1286 passed/46 xfailed @ 7e4ed3a -> +3 passed/+4
xfailed (7 collected) in the solo state. RED pre: the 4 xfails are xfailed
BY CONSTRUCTION (the broken state is the expected one); the 3 greens are
GREEN pre AND post.
"""

import pathlib

import jinja2
import pytest
from fastapi.testclient import TestClient

from polymarket_mcp.config import load_config
from polymarket_mcp.web import app as wa

# Dummy wallet: the house-standard offline key (valid 64-hex format, zero value).
DUMMY_PRIVATE_KEY = "0" * 63 + "1"
DUMMY_ADDRESS = "0x" + "0" * 40

# Every env key the web module can observe -- cleared per test (mirror of the
# sister suite's _KEYS_CLEANED; monkeypatch restores automatically).
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

# The 7 categories the real RateLimiter.get_status() exposes (rate_limiter.py
# EndpointCategory; each bucket renders EXACTLY these 5 keys).
_EXPECTED_CATEGORIES = {
    "clob_general",
    "market_data",
    "batch_ops",
    "trading_burst",
    "trading_sustained",
    "gamma_api",
    "data_api",
}
_EXPECTED_STATUS_KEYS = {
    "available_tokens",
    "max_tokens",
    "refill_rate_per_sec",
    "backoff_remaining_sec",
    "is_throttled",
}

# Captured at import time, before any test runs: the pristine stats dict
# (mirrors the sister suite's _PRISTINE_STATS).
_PRISTINE_STATS = dict(wa.stats)


def _monitoring_html() -> str:
    """Return the monitoring.html template text.

    Path derived from the wa package location (hermetic, no CWD dependence);
    read with explicit encoding (item 156 -- house standard).
    """
    return (
        pathlib.Path(wa.__file__).parent / "templates" / "monitoring.html"
    ).read_text(encoding="utf-8")


def _assert_no_env_in_worktree() -> None:
    """Fail loud if a .env appeared in the worktree root (hermeticity guard).

    Mirrors the sister suite: load_config() reads env_file=".env" relative to
    CWD; the lifespan test depends on the worktree root having NO .env
    (env-only config). A .env here would invalidate the shape assertion.
    """
    assert not (pathlib.Path.cwd() / ".env").exists(), (
        "A .env file appeared in the worktree root -- the monitor surfaces "
        "suite requires a clean root (env-only config). Refusing to run: "
        "hermeticity precondition violated."
    )


@pytest.fixture(autouse=True)
def pristine_monitor_state():
    """Reset web.app module globals per test and restore the originals.

    Mirror of pristine_web_state (test_web_app_offline.py -- L-0022): the
    lifespan writes wa.config/wa.client/wa.safety_limits DIRECTLY (global
    statement) and handlers mutate wa.stats in place -- both bypass
    monkeypatch. Each test starts from the pristine baseline with a per-test
    COPY of stats; teardown restores, making the suite order-independent
    (without this, the no-config test REDs after a configured test -- proven
    first-hand in the preflight).
    """
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


# ============================================================================
# Desired behavior: /api/stats serves a JSON payload (FINDING-1)
# ============================================================================


@pytest.mark.xfail(
    reason=(
        "FINDING-1 (OBSERVED, item 158): stats['uptime_start'] is a datetime "
        "fed raw to JSONResponse -> TypeError 'Object of type datetime is not "
        "JSON serializable' -> the client sees 500. The item-158 fix must "
        "serialize/drop uptime_start so this contract turns GREEN."
    ),
    strict=True,
)
def test_api_stats_returns_200_json_payload():
    """GET /api/stats returns 200 with a JSON body exposing requests_total.

    DESIRED contract for the item-158 fix: the monitor panel polls /api/stats
    every 5s; on any deploy the endpoint must answer 200 with a JSON payload
    (not the OBSERVED 500 "Internal Server Error").
    """
    tolerant = TestClient(wa.app, raise_server_exceptions=False)
    response = tolerant.get("/api/stats")
    assert response.status_code == 200
    body = response.json()
    assert "requests_total" in body


# ============================================================================
# Desired behavior: /monitoring renders with config (FINDING-2)
# ============================================================================


@pytest.mark.xfail(
    reason=(
        "FINDING-2 (OBSERVED, item 158): the Jinja loop renders "
        "status.remaining/status.limit -- keys the real get_status() payload "
        "never provides (available_tokens/max_tokens/...) -> "
        "jinja2.UndefinedError RAISES during render -> the route 500s on any "
        "configured deploy. The item-158 fix must correct the template fields."
    ),
    strict=True,
)
def test_monitoring_renders_200_with_config(wallet_env, monkeypatch):
    """GET /monitoring renders 200 with the API Rate Limits section (DESIRED).

    TRAP (proven in the preflight sim): the crash is a RAISE
    (jinja2.UndefinedError), not an assert-failure -- xfail only captures
    FAILURES, so the test converts the raise into an explicit assert failure
    (status string) and the RED reason carries the real mechanism. Config
    enters via monkeypatch.setattr (house pattern :463): the route reads the
    wa.config global directly, the lifespan is NOT needed.
    """
    monkeypatch.setattr(wa, "config", load_config())
    status = None
    response = None
    try:
        response = TestClient(wa.app).get("/monitoring")
        status = response.status_code
    except jinja2.exceptions.UndefinedError as exc:
        status = f"raised: {type(exc).__name__}"
    assert status == 200, (
        f"/monitoring must render 200 with config set: observed {status!r}"
    )
    assert "API Rate Limits" in response.text


# ============================================================================
# Desired behavior: template reads the REAL limiter field names (grep-pins)
# ============================================================================


@pytest.mark.xfail(
    reason=(
        "FINDING-2 (DATA side, OBSERVED): the template loop references "
        "status.limit/status.remaining -- phantom keys that crash the render "
        "-- and never references the real get_status() fields. The item-158 "
        "fix must rewrite the loop to "
        "available_tokens/max_tokens/backoff_remaining_sec/is_throttled."
    ),
    strict=True,
)
def test_template_reads_real_rate_limit_fields():
    """monitoring.html renders the REAL get_status() field names (grep-pin).

    DESIRED: the loop reads status.available_tokens/status.max_tokens (keys
    the payload provides) and NO LONGER references status.limit/status.
    remaining (the phantom keys behind the UndefinedError).
    """
    text = _monitoring_html()
    assert "status.available_tokens" in text
    assert "status.max_tokens" in text
    assert "status.limit" not in text
    assert "status.remaining" not in text


@pytest.mark.xfail(
    reason=(
        "GAP (OBSERVED): monitoring.html has NO client-side /api/status "
        "panel -- the template carries no fetch('/api/status'), no "
        "is_throttled/backoff_remaining_sec rendering, and no esc() call, so "
        "the 429 observability state is invisible. The item-158 fix must add "
        "the panel (esc() is the app.js global loaded at the page bottom)."
    ),
    strict=True,
)
def test_template_fetches_api_status_and_renders_safely():
    """monitoring.html carries the client-side /api/status panel (grep-pin).

    DESIRED: the observability panel fetches /api/status client-side, renders
    the throttling state (is_throttled, backoff_remaining_sec) and routes
    every interpolated value through esc() (app.js is loaded by this template;
    esc() is global by the time the inline script runs).
    """
    text = _monitoring_html()
    assert "fetch('/api/status')" in text
    assert "is_throttled" in text
    assert "backoff_remaining_sec" in text
    assert "esc(" in text


# ============================================================================
# Green guards: what must NOT change (GREEN pre AND post the item-158 fix)
# ============================================================================


def test_monitoring_renders_200_without_config():
    """GET /monitoring renders 200 in the no-config state (else-branch).

    GREEN guard (the surviving half of the sister OBSERVED pin): config None
    -> rate_status {} -> template else-branch -> 200 + "No rate limit data
    available". The item-158 fix must NOT break this state.
    """
    response = TestClient(wa.app).get("/monitoring")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "No rate limit data available" in response.text


def test_api_status_contract_has_full_limiter_shape(wallet_env):
    """/api/status (under lifespan) exposes the FULL limiter shape.

    GREEN guard and the panel's DATA source: 200 + connected:True +
    rate_limits with EXACTLY the 7 categories x EXACTLY the 5 status keys.
    The fixture uses lifespan (with TestClient(wa.app)): without it the route
    answers connected:False with an EMPTY rate_limits. The item-158 fix adds
    a renderer on top of this payload -- it must never narrow the source.
    """
    _assert_no_env_in_worktree()
    with TestClient(wa.app):
        response = TestClient(wa.app).get("/api/status")
        assert response.status_code == 200
        body = response.json()
        assert body["connected"] is True
        rate_limits = body["rate_limits"]
        assert set(rate_limits) == _EXPECTED_CATEGORIES
        assert len(rate_limits) == 7
        for status in rate_limits.values():
            assert set(status) == _EXPECTED_STATUS_KEYS
            assert len(status) == 5


def test_stats_interval_still_polls_api_stats():
    """The 5s interval still polls /api/stats (anti-over-fix pin).

    GREEN guard: the item-158 fix ADDS a fetch('/api/status') (the
    observability panel); it must NOT replace the existing stats polling --
    the monitoring page keeps fetching /api/stats every 5000ms via its
    inline startMonitoring() setInterval.
    """
    text = _monitoring_html()
    assert "setInterval" in text
    assert "fetch('/api/stats')" in text
    assert "5000" in text
