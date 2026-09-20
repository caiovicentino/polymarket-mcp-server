"""Docs anti-drift: dashboard route surface (T-0434).

Derivation-first (L-0023/L-0070): the route surface is EXTRACTED from
``src/polymarket_mcp/web/app.py`` by decorator regex on every run - never
hardcoded counts or route names. A route added to app.py REDs the three
aligned artifacts (WEB_DASHBOARD.md, DASHBOARD_SUMMARY.md,
test_web_dashboard.py) until they are updated.

Content anchors only, never file:line (L-0127). Every read uses an explicit
encoding (read_text(encoding="utf-8"), item 156). Offline by construction:
file reads plus stdlib ``ast``; zero network, zero subprocess, zero markers
(runs in the default release gate).

What each test proves:

- test_app_route_surface_is_documented_in_web_dashboard: every /api/* route
  and /ws of app.py is findable in WEB_DASHBOARD.md (per-route presence with
  {param} normalized to a wildcard) AND the extracted doc endpoint set equals
  the code set both ways (catches a missing route AND a stale doc entry).
- test_app_route_surface_is_documented_in_dashboard_summary: same contract on
  DASHBOARD_SUMMARY.md for BOTH the **Endpoints** block and the recorded
  "Route registered" script output; the 4 HTML pages must appear in the
  **Endpoints** block.
- test_root_script_expected_routes_match_app_surface: the ``expected_routes``
  literal of the root script (AST-extracted, not regex) must equal the full
  app.py route surface.
- test_route_extraction_is_not_vacuous: fail-loud guard (P-0031) - if an
  extraction regex broke, tests above would pass vacuously (empty == empty).
  This pins a non-trivial extraction volume instead.

Note (2026-09-20): the "Route registered" lines recorded in
DASHBOARD_SUMMARY.md predate this suite and carry a non-ASCII check mark;
lines ADDED by T-0434 are ASCII-only (repo-wide ASCII-only doctrine,
item 147, delta-scoped acceptance 6). The extraction regex matches both
forms by content, so a future full re-recording with the original marker
stays GREEN.
"""

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "src" / "polymarket_mcp" / "web" / "app.py"
WEB_DASHBOARD = ROOT / "WEB_DASHBOARD.md"
DASH_SUMMARY = ROOT / "DASHBOARD_SUMMARY.md"
ROOT_SCRIPT = ROOT / "test_web_dashboard.py"

# Decorators of the FastAPI app. Only these three HTTP/websocket verbs exist
# on the surface; @app.middleware is intentionally not captured.
_APP_DECORATOR_RE = re.compile(r'@app\.(get|post|websocket)\("([^"]+)"')
_METHOD_OF = {"get": "GET", "post": "POST", "websocket": "WebSocket"}

# Endpoint lines in the docs: `GET /api/...`, `POST /api/...`, `WebSocket /ws`.
# Query strings are allowed and bounded by the closing backtick; /ws is
# captured so the WebSocket route is part of the compared surface.
_DOC_API_ENDPOINT_RE = re.compile(r"(?:GET|POST|WebSocket) ((?:/api/|/ws)[^`]*)")

# Any backtick endpoint bullet - needed for the 4 HTML pages, which are
# documented as `GET /`, `GET /config`, `GET /markets`, `GET /monitoring`.
_DOC_ANY_ENDPOINT_RE = re.compile(r"`(?:GET|POST|WebSocket) ([^`]+)`")

# Recorded script output lines: "Route registered: <path>" (with or without a
# leading marker glyph - content match, not glyph match).
_ROUTE_REGISTERED_RE = re.compile(r"Route registered: (\S+)")

_PARAM_RE = re.compile(r"\{[^}]*\}")

_PAGES = {"/", "/config", "/markets", "/monitoring"}


def _app_routes():
    """(method, path) list extracted from app.py decorators - the live surface."""
    src = APP.read_text(encoding="utf-8")
    return [(_METHOD_OF[method], path) for method, path in _APP_DECORATOR_RE.findall(src)]


def _normalize(path):
    """Canonical path key: drop the query string, collapse {param} to {}.

    Makes the doc rendering ({id}, {market_id}, ?limit=10) and the code path
    ({market_id}, no query) comparable without hardcoding either spelling.
    """
    return _PARAM_RE.sub("{}", path.split("?", 1)[0])


def _app_api_surface():
    """Normalized set of /api/* paths plus /ws."""
    return {_normalize(p) for _m, p in _app_routes() if p.startswith("/api/") or p == "/ws"}


def _app_full_surface():
    """Normalized set of ALL app.py routes (pages + api + ws)."""
    return {_normalize(p) for _m, p in _app_routes()}


def _presence_pattern(path):
    """Regex matching a code path as rendered in a doc.

    Query strings are dropped and each {param} segment becomes a placeholder
    wildcard ``\\{[^`\\s]+\\}``, so the doc's ``{id}`` matches the code's
    ``{market_id}``.
    """
    parts = re.split(r"\{[^}]*\}", path.split("?", 1)[0])
    return re.compile(r"\{[^`\s]+\}".join(re.escape(part) for part in parts))


def _assert_surface_covered(surface, doc_set, label):
    missing = surface - doc_set
    stale = doc_set - surface
    assert not missing, f"{label} misses routes {sorted(missing)}"
    assert not stale, f"{label} documents stale endpoints {sorted(stale)}"


def test_app_route_surface_is_documented_in_web_dashboard():
    """Every /api/* route and /ws of app.py is documented in WEB_DASHBOARD.md,
    and every endpoint the doc claims exists in app.py (set-equality both ways)."""
    text = WEB_DASHBOARD.read_text(encoding="utf-8")
    for method, path in _app_routes():
        if not (path.startswith("/api/") or path == "/ws"):
            continue
        assert _presence_pattern(path).search(text), (
            f"WEB_DASHBOARD.md misses {method} {path} (route exists in app.py)"
        )
    doc = {_normalize(p) for p in _DOC_API_ENDPOINT_RE.findall(text)}
    _assert_surface_covered(_app_api_surface(), doc, "WEB_DASHBOARD.md")


def test_app_route_surface_is_documented_in_dashboard_summary():
    """Same contract on DASHBOARD_SUMMARY.md: the **Endpoints** block and the
    recorded "Route registered" output must cover /api/* + /ws, and the 4 HTML
    pages must appear in the **Endpoints** block."""
    lines = DASH_SUMMARY.read_text(encoding="utf-8").splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.strip().startswith("**Endpoints**")),
        None,
    )
    assert start is not None, (
        "DASHBOARD_SUMMARY.md: '**Endpoints**' block marker missing (fail loud)"
    )
    block_lines = []
    for line in lines[start + 1 :]:
        if not line.strip():
            break
        block_lines.append(line)
    assert block_lines, (
        "DASHBOARD_SUMMARY.md: '**Endpoints**' block is empty (fail loud)"
    )
    block = "\n".join(block_lines)

    block_set = {_normalize(p) for p in _DOC_ANY_ENDPOINT_RE.findall(block)}
    doc_api = {p for p in block_set if p.startswith("/api/") or p == "/ws"}
    _assert_surface_covered(_app_api_surface(), doc_api, "DASHBOARD_SUMMARY.md **Endpoints**")
    missing_pages = _PAGES - block_set
    assert not missing_pages, (
        f"DASHBOARD_SUMMARY.md **Endpoints** misses pages {sorted(missing_pages)}"
    )

    registered = {_normalize(p) for p in _ROUTE_REGISTERED_RE.findall(
        DASH_SUMMARY.read_text(encoding="utf-8")
    )}
    # The recorded script output lists the FULL expected_routes surface
    # (pages + api + ws), so the equality target is the full surface: a route
    # missing from app.py output shows up as missing here, and a stale entry
    # (registered but not on the app surface) as stale.
    _assert_surface_covered(
        _app_full_surface(), registered, "DASHBOARD_SUMMARY.md 'Route registered' output"
    )


def test_root_script_expected_routes_match_app_surface():
    """The ``expected_routes`` literal of test_web_dashboard.py (AST-extracted)
    must equal the full app.py route surface - both directions."""
    tree = ast.parse(ROOT_SCRIPT.read_text(encoding="utf-8"))
    expected = None
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple))):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "expected_routes"
            for target in node.targets
        ):
            expected = [
                elt.value
                for elt in node.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
            break
    assert expected is not None, (
        "test_web_dashboard.py: 'expected_routes' string literal not found (fail loud)"
    )
    script_set = {_normalize(p) for p in expected}
    _assert_surface_covered(
        _app_full_surface(), script_set, "test_web_dashboard.py expected_routes"
    )


def test_route_extraction_is_not_vacuous():
    """Fail-loud guard (P-0031): a broken extraction regex would make the tests
    above pass vacuously (empty set == empty set). Pin the extraction to a
    non-trivial volume on every artifact."""
    routes = _app_routes()
    assert len(routes) >= 10, f"app.py route extraction degraded: {routes!r}"

    web_lines = len(_DOC_API_ENDPOINT_RE.findall(WEB_DASHBOARD.read_text(encoding="utf-8")))
    assert web_lines >= 10, (
        f"WEB_DASHBOARD.md endpoint extraction degraded: {web_lines} matches"
    )

    summary = DASH_SUMMARY.read_text(encoding="utf-8")
    summary_lines = len(_DOC_API_ENDPOINT_RE.findall(summary)) + len(
        _ROUTE_REGISTERED_RE.findall(summary)
    )
    assert summary_lines >= 10, (
        f"DASHBOARD_SUMMARY.md endpoint extraction degraded: {summary_lines} matches"
    )
