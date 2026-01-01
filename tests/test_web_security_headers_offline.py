"""
Offline regression suite for the security-headers middleware of the FastAPI web
dashboard (src/polymarket_mcp/web/app.py).

T-0220 — Facet B: before the fix, GET / (and every other response) carried NO
security headers (RED probe on the unfixed worktree:
`PROBE-HEADERS-GET / status=200 security_headers={}`). The fix adds ONE http
middleware that stamps three headers on every response that completes:

    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

DIVERGENCE contract×reality (declared; probes published in the task report,
L-0090(f)/L-0025/L-0020 — the observable wins over the spec text):
- The contract prescribed `GET /api/stats` for the API-route header pin. On the
  living main (89edfa9), /api/stats is a PINNED unhandled-exception 500
  (FINDING-1 in tests/test_web_app_offline.py — `stats` holds
  `uptime_start: datetime`, so JSONResponse render raises TypeError). In
  Starlette 1.6.0 the middleware stack is
  ServerErrorMiddleware -> user middleware -> ExceptionMiddleware -> router:
  an UNHANDLED exception propagates THROUGH the user middleware (call_next
  re-raises; the code after `await call_next(request)` never runs), so that 500
  response structurally CANNOT carry the headers. Post-fix probe:
  `HDR GET /api/stats: 500 {}` (headers absent) vs `HDR GET /api/status: 200
  {...3 headers...}`. The pin therefore targets /api/status (a normal 200 API
  route) — the pinned property is "API routes carry the security headers".
- The middleware DOES cover every response that completes normally, including
  HTTPException-converted errors (404 pinned here; 422 pinned by the sibling
  suite test_web_config_validation_offline.py). It does NOT cover
  500-by-unhandled-exception (mechanism above) — a known limitation of the
  prescribed form, declared in the task report (covering it would require an
  exception handler; out of scope for this slice).

CSP is OUT OF SCOPE (product decision: templates ship inline scripts + a
jsdelivr CDN; NEVER add CSP in this slice). TrustedHost / DNS-rebinding is
REQUER-HUMANO (LAN/Docker trade-off).

L-0073 (consumer↔producer): a fix that touches the middleware (name, values,
registration) must update this suite in the SAME slice.

Hermeticity: GET / mutates `stats["requests_total"]` in place — the autouse
pristine_web_state fixture resets/restores the module globals (mirrors
tests/test_web_app_offline.py). Zero network; no SDK on any exercised path; the
worktree root must remain .env-free.
"""

import pathlib

import pytest
from fastapi.testclient import TestClient

from polymarket_mcp.web import app as wa

# CWD at import time == the worktree root (pytest is invoked from there). The
# middleware stamps headers only; no route here writes files — the guard keeps
# the root provably clean across the run (mirrors test_web_app_offline.py).
_WORKTREE_ROOT = pathlib.Path.cwd()

# The 3 headers with their EXACT prescribed values (the fix is verbatim, so the
# values are part of the contract).
_EXPECTED_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

# Captured at import time, before any test runs: the pristine stats dict (the
# module never replaces it — handlers only see per-test copies).
_PRISTINE_STATS = dict(wa.stats)


@pytest.fixture(autouse=True)
def pristine_web_state():
    """Reset web.app module globals per test and restore the originals.

    GET / mutates stats in place; load_mcp_config (if any test triggered a
    reload) writes config/client/safety_limits directly. Restoring the captured
    baseline keeps the suite order-independent and safe to run twice.
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


def test_security_headers_present_on_home():
    """GET / -> 200 with the 3 security headers at their exact values."""
    response = TestClient(wa.app).get("/")
    assert response.status_code == 200
    for name, value in _EXPECTED_HEADERS.items():
        assert response.headers[name] == value, f"{name} missing/mismatched on GET /"


def test_security_headers_present_on_api_routes():
    """GET /api/status -> 200 with the 3 security headers (API-route pin).

    The contract prescribed /api/stats here; see the module docstring — on the
    living main that route is a pinned unhandled-exception 500 whose response
    bypasses the user middleware (Starlette 1.6.0 stack), so the headers are
    structurally unreachable there. /api/status completes normally (200) and
    exercises the same middleware dispatch path.
    """
    response = TestClient(wa.app).get("/api/status")
    assert response.status_code == 200
    for name, value in _EXPECTED_HEADERS.items():
        assert response.headers[name] == value, (
            f"{name} missing/mismatched on GET /api/status"
        )


def test_security_headers_present_on_error_response():
    """GET /nonexistent -> 404 WITH the 3 headers: HTTPException-converted
    errors are built by ExceptionMiddleware (INNER to the user middleware) and
    flow back through the dispatch, so they are stamped too."""
    response = TestClient(wa.app).get("/this-route-does-not-exist")
    assert response.status_code == 404
    for name, value in _EXPECTED_HEADERS.items():
        assert response.headers[name] == value, f"{name} missing/mismatched on 404"


def test_middleware_registered_once():
    """len(app.user_middleware) == 1: the module must never re-register the
    middleware (a duplicate registration would stamp every header twice and
    double response latency)."""
    assert len(wa.app.user_middleware) == 1


def test_pin_content_anchor():
    """Anti-drift pin by CONTENT (L-0023 — never by file:line): app.py contains
    the middleware function name and the 3 header names (and values)."""
    source = pathlib.Path(wa.__file__).read_text()
    assert "add_security_headers" in source
    for name, value in _EXPECTED_HEADERS.items():
        assert f'"{name}"' in source, f"header name {name!r} not pinned in app.py"
        assert value in source, f"header value {value!r} not pinned in app.py"
