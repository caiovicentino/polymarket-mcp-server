"""Offline regression suite for the dashboard's Markets Closing Soon panel.

Contract T-0426: the web dashboard (polymarket_mcp/web/templates/index.html)
had live panels for trending markets but NEVER consumed the
/api/markets/closing-soon endpoint the backend already exposes
(polymarket_mcp/web/app.py, route ``@app.get("/api/markets/closing-soon")``,
already in the T-0307 array-envelope pattern {"markets": [...]}). At the
fork point, grep for "closing" in index.html and static/js/app.js returned
0 hits -- the dashboard frontend had zero references to the endpoint. This
slice wires the panel: a new card mirroring the trending panel plus an
inline loadClosingSoon() function called from the DOMContentLoaded listener.

Six named tests, 100% offline (no network, no server, no subprocess, no
browser). Anchors are matched by CONTENT (L-0127 -- never file:line, which
drifts on concurrent merges).

Mechanics
---------
- Templates and the pinned backend module are read from the source tree via
  Path.read_text with an explicit encoding (item-156 class: a bare
  read_text breaks on hosts whose locale resolves to a non-UTF-8 default
  encoding).
- A dev-only seam, env var ``WEB_CLOSING_SOON_SRC_DIR``, redirects the reads
  to a temp copy so mutation probes can exercise ONE copy without touching
  canonical files. Default (env unset) is always the real source tree --
  the seam never widens any assertion, it only changes WHERE files are
  read from.
- Tripwire (P-0013): sha256 of every file the suite reads is snapshotted
  at session start and verified at session end -- the suite must be
  strictly read-only (the suite itself never writes). The tripwire scope
  INCLUDES web/app.py: the route module is deny-scope for this slice, so
  any mutation of it makes the session fail loud.

Honesty note: this panel is FRONTEND wiring. The suite never exercises the
backend's wire behavior (zero network by construction, P-0029) -- it pins
the CODE SHAPE of the route as observed (decorator anchor, tool seam name,
{"markets": [...]} wrap for bare lists). The known wire quirks of
get_closing_soon_markets (item 152, e.g. Z-suffixed endDate) are owner-fix
territory (REQUER-HUMANO) and are NOT asserted here; the render uses the
fallback ``market.endDate || market.end_date_iso`` so the panel is robust
to either wire spelling.

Hygiene: the suite performs no network I/O and no filesystem writes.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Every path the suite reads (tripwire scope). The second entry pins the
# backend route module: deny-scope for this slice, read-only observation.
_READ_FILES = (
    "polymarket_mcp/web/templates/index.html",
    "polymarket_mcp/web/app.py",
)

# The EXACT endpoint the panel fetches (query params included: the panel
# asks for the 5 soonest markets within a 24h window).
ENDPOINT = "/api/markets/closing-soon?limit=5&hours=24"


def _src_root() -> Path:
    """Source root for reads: real tree by default, temp copy under the seam."""
    override = os.environ.get("WEB_CLOSING_SOON_SRC_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "src"


def _read(relpath: str) -> str:
    return (_src_root() / relpath).read_text(encoding="utf-8")


def _index() -> str:
    return _read("polymarket_mcp/web/templates/index.html")


def _app_py() -> str:
    return _read("polymarket_mcp/web/app.py")


def _fn_body(src: str, name: str) -> str:
    """Slice one inline-script function body by content anchors (L-0127).

    Starts at the ``async function <name>`` definition line and ends at the
    next ``async function`` occurrence (the panel functions are declared in
    sequence inside the same inline <script> block of index.html).
    """
    start = src.index("async function " + name)
    return src[start: src.index("async function", start + 10)]


def _closing_section(src: str) -> str:
    """Slice the new panel's HTML section (heading comment to </section>)."""
    start = src.index("<!-- Markets Closing Soon -->")
    return src[start: src.index("</section>", start)]


def _closing_route(app_src: str) -> str:
    """Slice the closing-soon route in app.py (decorator to next route)."""
    start = app_src.index('@app.get("/api/markets/closing-soon")')
    return app_src[start: app_src.index("@app.get", start + 10)]


@pytest.fixture(scope="session", autouse=True)
def read_only_tripwire():
    """Fail the session if the suite wrote to any file it reads (P-0013)."""
    root = _src_root()
    before = {
        rel: hashlib.sha256((root / rel).read_bytes()).hexdigest()
        for rel in _READ_FILES
    }
    yield
    after = {
        rel: hashlib.sha256((root / rel).read_bytes()).hexdigest()
        for rel in _READ_FILES
    }
    mutated = [rel for rel in _READ_FILES if before[rel] != after[rel]]
    assert not mutated, f"suite must be read-only; wrote to: {mutated}"


def test_closing_soon_card_present_with_loading_state():
    """The dashboard has a Markets Closing Soon card mirroring the trending panel.

    POS: the section carries the panel title, the card > card-body wrapper
    (classes the dashboard already styles) and the container div
    id="closing-soon-markets" in the loading state with spinner and
    placeholder text -- the exact anatomy of the trending panel in the
    same file.
    """
    src = _index()
    section = _closing_section(src)
    assert '<h2>Markets Closing Soon</h2>' in section
    assert '<div class="card">' in section
    assert '<div class="card-body">' in section
    assert '<div id="closing-soon-markets" class="loading">' in section
    assert '<div class="spinner"></div>' in section
    assert '<p>Loading closing soon markets...</p>' in section


def test_dom_content_loaded_invokes_load_closing_soon():
    """DOMContentLoaded calls loadClosingSoon() alongside the existing inits.

    Order pin (observed wiring): loadTrendingMarkets() first, then
    loadClosingSoon(), then initWebSocket() -- the new panel boots with
    the page, not on demand.
    """
    src = _index()
    dl = src.index("document.addEventListener('DOMContentLoaded'")
    block = src[dl: src.index("});", dl)]
    t = block.index("loadTrendingMarkets();")
    c = block.index("loadClosingSoon();")
    w = block.index("initWebSocket();")
    assert t < c < w, (
        "DOMContentLoaded must call loadTrendingMarkets(), loadClosingSoon(), "
        "initWebSocket() in that order"
    )


def test_load_closing_soon_fetches_exact_endpoint():
    """The panel fetches the EXACT endpoint with its window parameters.

    POS: '/api/markets/closing-soon?limit=5&hours=24' via the direct fetch
    pattern of the trending panel (NOT apiRequest). Guard pins: the
    response.ok check throws a static 'HTTP <status>' error before any
    JSON read.
    """
    body = _fn_body(_index(), "loadClosingSoon")
    assert f"fetch('{ENDPOINT}')" in body
    assert "if (!response.ok)" in body
    assert "throw new Error('HTTP ' + response.status)" in body


def test_error_envelope_surfaced_with_esc_before_empty_state():
    """An error envelope is SURFACED (esc'd), never swallowed into empty-state.

    The backend passes dict payloads (error envelopes) through unchanged
    (T-0307 wrap semantics); the panel checks ``data.error`` BEFORE the
    rows.length branch, so an error renders as a text-error message via
    esc() -- the envelope-blindness failure mode (error treated as an
    empty list) cannot regress into the new panel.
    """
    body = _fn_body(_index(), "loadClosingSoon")
    err_pos = body.index("if (data.error)")
    rows_pos = body.index("if (rows.length > 0)")
    assert err_pos < rows_pos, "data.error must be checked before the rows branch"
    assert "${esc(String(data.error))}" in body
    # The error branch short-circuits with return (no fall-through).
    assert body.index("return;", err_pos) < rows_pos


def test_render_uses_marketrows_of_and_real_wire_fields():
    """Rows come from marketRowsOf(data); the render touches ONLY real fields.

    Wire fields the tools actually ship (T-0308 class): question, volume24hr,
    and the closing date with fallback market.endDate || market.end_date_iso
    (the wire ships endDate; end_date_iso is the tool-side alias the fallback
    covers). Every interpolated value goes through esc(). Empty-state:
    'No closing soon markets' as text-muted when the rows list is empty.
    """
    body = _fn_body(_index(), "loadClosingSoon")
    assert "marketRowsOf(data)" in body
    assert "${esc(market.question || 'Unknown Market')}" in body
    assert "${esc(formatNumber(market.volume24hr || 0))}" in body
    assert "market.endDate || market.end_date_iso" in body
    assert "${esc(market.endDate || market.end_date_iso || 'Unknown')}" in body
    assert '<p class="text-muted">No closing soon markets</p>' in body


def test_backend_route_pinned_in_app_py():
    """The backend route this panel consumes exists and keeps the T-0307 wrap.

    PIN of the deny-scope file (web/app.py is NOT touched by this slice):
    the route decorator, the tool seam (get_closing_soon_markets) and the
    array wrap {"markets": [...]} for bare lists (dict payloads pass
    through unchanged). The tripwire makes any mutation of app.py fail
    the session loud.
    """
    route = _closing_route(_app_py())
    assert '@app.get("/api/markets/closing-soon")' in route
    assert 'handle_tool("get_closing_soon_markets"' in route
    assert "isinstance(data, list)" in route
    assert '{"markets": data}' in route
