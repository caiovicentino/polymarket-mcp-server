"""Offline wiring/error-surfacing regression suite for the Polymarket web dashboard.

Contract T-0365: dashboard wiring fixes filed by REQUER-HUMANO item 186
(NOTA DE WIRING) + item 187 option (b) + monitoring /api/stats hardening.
100% offline (no network, no server, no browser; node probe is a local
subprocess with SKIP-de-infra L-0026/L-0028).

Fixes pinned (RED pre-state proven before the fix, kept as EVIDENCE):
  1. ``filterByCategory`` searched BEFORE setting the query -- the category
     buttons ran the search with the PREVIOUS input (or empty -> wire 422 ->
     "No markets found") and only THEN set the input. Fix: set the query
     first, then search (best the wire offers today -- the gamma wire ignores
     the tag param, items 155/186, so a text search is the honest wiring).
  2. ``loadClosingSoon`` was a dead button: notification + title, no call.
     Fix: real fetch of the NEW ``/api/markets/closing-soon`` route, which
     mirrors the trending/search routes (bare tool list wrapped as
     ``{"markets": [...]}``, dict payloads pass through -- T-0307 design).
  3. search/trending/index panels swallowed error envelopes (200 + {"error"})
     and HTTP failures (no ``response.ok`` check) as "No markets found".
     Fix: surface ``data.error`` / ``err.detail`` as an error message
     (item 187 option (b) -- no backend pin flipped), and extract rows via
     the dual-state helper ``marketRowsOf`` so the panels work BOTH before
     and after the T-0307 route wrap merges (merge-order independence).
  4. monitoring.html read /api/stats without ``response.ok`` -- a 500 (the
     known item-158 quirk) rendered ``undefined`` into the DOM. Fix: guard +
     static error message (monitoring.html has no esc(); no data is
     interpolated, so no XSS surface is added).

Mechanics
---------
- Source files are read from the source tree via Path; a dev-only seam, env
  var ``WEB_WIRING_SRC_DIR``, redirects the reads to a temp copy for
  mutation oracles. Default (env unset) is always the real source tree.
- ``marketRowsOf`` behavior is exercised against the REAL app.js source via
  a ``node -e`` subprocess (DOM stubs mirror test_web_xss_offline.py; no
  network). Absent node -> explicit environment SKIP.
- Tripwire (P-0013): sha256 of every file the suite reads is snapshotted at
  session start and verified at session end -- the suite is strictly
  read-only.

Hygiene: every local variable captured inside try blocks is initialized with
a sentinel before the try (set -u equivalent); no network I/O; no writes
outside tmpdir.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
from typing import Any

import pytest
from fastapi.testclient import TestClient

from polymarket_mcp.web import app as wa

# Dummy wallet: the house-standard offline key (valid 64-hex format, zero value).
DUMMY_PRIVATE_KEY = "0" * 63 + "1"
DUMMY_ADDRESS = "0x" + "0" * 40

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

_FILES = (
    "src/polymarket_mcp/web/app.py",
    "src/polymarket_mcp/web/static/js/app.js",
    "src/polymarket_mcp/web/templates/index.html",
    "src/polymarket_mcp/web/templates/markets.html",
    "src/polymarket_mcp/web/templates/monitoring.html",
)

# Path helper honoring the dev-only seam (default: the real source tree).
_REPO_ROOT = pathlib.Path(os.environ.get("WEB_WIRING_SRC_DIR", str(_REPO_ROOT)))


def _read(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Hermeticity + tripwire
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _wallet_env_and_tripwire(monkeypatch):
    """Env-only config (no .env in the worktree root -- L-0330) + read-only tripwire."""
    assert not (_REPO_ROOT / ".env").exists(), (
        "a .env file exists in the source tree -- the suite must never depend on it"
    )
    for key in (
        "POLYGON_PRIVATE_KEY",
        "POLYGON_ADDRESS",
        "POLYMARKET_API_KEY",
        "POLYMARKET_API_SECRET",
        "POLYMARKET_PASSPHRASE",
        "POLYMARKET_API_KEY_NAME",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", DUMMY_PRIVATE_KEY)
    monkeypatch.setenv("POLYGON_ADDRESS", DUMMY_ADDRESS)
    before = {rel: hashlib.sha256((_REPO_ROOT / rel).read_bytes()).hexdigest() for rel in _FILES}
    yield
    after = {rel: hashlib.sha256((_REPO_ROOT / rel).read_bytes()).hexdigest() for rel in _FILES}
    mutated = [rel for rel in _FILES if before[rel] != after[rel]]
    assert not mutated, f"suite must be read-only; wrote to: {mutated}"


# ---------------------------------------------------------------------------
# FakeToolModule seam (mirrors test_web_app_offline.py, minimal copy)
# ---------------------------------------------------------------------------


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text


def text_payload(payload: Any) -> list[FakeMessage]:
    return [FakeMessage(text=json.dumps(payload))]


class FakeToolModule:
    def __init__(
        self,
        results: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._results = results or {}
        self._error = error

    async def handle_tool(self, name: str, arguments: dict) -> list[FakeMessage]:
        self.calls.append((name, dict(arguments)))
        if self._error is not None:
            raise self._error
        if name not in self._results:
            raise AssertionError(f"unexpected tool call: {name!r}")
        result = self._results[name]
        if callable(result):
            return result(arguments)
        return result


@pytest.fixture()
def _stubbed_discovery(monkeypatch):
    """Install a fail-loud fake on the market_discovery seam of web.app."""
    holder: dict[str, FakeToolModule] = {}

    def install(results=None, error=None) -> FakeToolModule:
        fake = FakeToolModule(results=results, error=error)
        monkeypatch.setattr(wa, "market_discovery", fake)
        holder["fake"] = fake
        return fake

    return install


# ---------------------------------------------------------------------------
# Node probe for marketRowsOf (pure helper in app.js)
# ---------------------------------------------------------------------------

_NODE_PROBE = r"""
const fs = require('fs');
const document = {
    addEventListener: () => {},
    body: { addEventListener: () => {}, appendChild: () => {} },
    documentElement: { classList: { contains: () => false, add: () => {}, remove: () => {} } },
    getElementById: () => null,
    querySelector: () => null,
};
const window = { addEventListener: () => {} };
const localStorage = { getItem: () => null, setItem: () => {} };
const navigator = { clipboard: { writeText: async () => {} } };
eval(fs.readFileSync(process.env.WEB_WIRING_APP_JS, 'utf8'));
process.stdout.write(JSON.stringify(marketRowsOf([{id: 1}, {id: 2}])) + '|');
process.stdout.write(JSON.stringify(marketRowsOf({markets: [{id: 3}]})) + '|');
process.stdout.write(JSON.stringify(marketRowsOf({error: 'boom'})) + '|');
process.stdout.write(JSON.stringify(marketRowsOf(null)) + '|');
process.stdout.write(JSON.stringify(marketRowsOf('garbage')) + '|');
"""


def _node_binary() -> str | None:
    return shutil.which("node")


# ---------------------------------------------------------------------------
# 1. marketRowsOf dual-state helper
# ---------------------------------------------------------------------------


def test_market_rows_of_dual_state():
    """marketRowsOf extracts rows in BOTH wire states; [] for error/garbage."""
    node = _node_binary()
    if not node:
        pytest.skip("node not available on this host -- environment skip (L-0026/L-0028)")
    env = dict(os.environ)
    env["WEB_WIRING_APP_JS"] = str(_REPO_ROOT / "src/polymarket_mcp/web/static/js/app.js")
    proc = subprocess_run(node, ["-e", _NODE_PROBE], env)
    parts = proc.stdout.strip().rstrip("|").split("|")
    assert parts == [
        '[{"id":1},{"id":2}]',  # bare array passes through
        '[{"id":3}]',           # {"markets": [...]} envelope extracted
        "[]",                   # error envelope -> []
        "[]",                   # null -> []
        "[]",                   # garbage string -> []
    ], f"marketRowsOf dual-state outputs diverge: {parts!r}"


def subprocess_run(node, argv, env):
    import subprocess

    return subprocess.run([node, *argv], capture_output=True, text=True, env=env, timeout=30)


# ---------------------------------------------------------------------------
# 2-6. /api/markets/closing-soon route
# ---------------------------------------------------------------------------


def test_closing_soon_route_declared_before_market_id_catch_all():
    """FastAPI matches routes in declaration order: the literal route must be
    declared BEFORE the /api/markets/{market_id} catch-all, or 'closing-soon'
    is consumed as a market_id (classic FastAPI footgun)."""
    src = _read("src/polymarket_mcp/web/app.py")
    closing = src.index('@app.get("/api/markets/closing-soon")')
    catch_all = src.index('@app.get("/api/markets/{market_id}")')
    assert closing < catch_all, "closing-soon route must be declared BEFORE the catch-all"


def test_closing_soon_route_wraps_bare_list(_stubbed_discovery):
    """A bare tool list is wrapped as {"markets": [...]} (T-0307 design)."""
    _stubbed_discovery(results={
        "get_closing_soon_markets": text_payload([{"question": "A"}, {"question": "B"}]),
    })
    with TestClient(wa.app) as client:
        resp = client.get("/api/markets/closing-soon")
    assert resp.status_code == 200
    assert resp.json() == {"markets": [{"question": "A"}, {"question": "B"}]}


def test_closing_soon_route_passthrough_error_envelope(_stubbed_discovery):
    """Dict payloads (tool error envelopes) pass through unchanged."""
    _stubbed_discovery(results={
        "get_closing_soon_markets": text_payload({"error": "boom"}),
    })
    with TestClient(wa.app) as client:
        resp = client.get("/api/markets/closing-soon")
    assert resp.status_code == 200
    assert resp.json() == {"error": "boom"}


def test_closing_soon_route_500_on_tool_crash(_stubbed_discovery):
    """A crashing tool yields the same 500 envelope as the sibling routes."""
    _stubbed_discovery(error=RuntimeError("tool exploded"))
    with TestClient(wa.app) as client:
        resp = client.get("/api/markets/closing-soon")
    assert resp.status_code == 500


def test_closing_soon_route_empty_tool_result(_stubbed_discovery):
    """An empty tool list falls back to the {"markets": []} envelope."""
    _stubbed_discovery(results={"get_closing_soon_markets": text_payload([])})
    with TestClient(wa.app) as client:
        resp = client.get("/api/markets/closing-soon")
    assert resp.status_code == 200
    assert resp.json() == {"markets": []}


# ---------------------------------------------------------------------------
# 7-9. markets.html wiring
# ---------------------------------------------------------------------------


def test_load_closing_soon_fetches_new_route():
    """loadClosingSoon fetches the NEW closing-soon route (dead button fixed)."""
    src = _read("src/polymarket_mcp/web/templates/markets.html")
    body = src[src.index("async function loadClosingSoon"):]
    body = body[: body.index("}", body.index("async function loadClosingSoon")) + 1]
    assert "fetch('/api/markets/closing-soon?limit=20')" in body, (
        "loadClosingSoon must fetch /api/markets/closing-soon"
    )


def test_filter_by_category_sets_input_before_search():
    """filterByCategory sets the search input BEFORE awaiting searchMarkets()
    (the pre-fix order searched with the PREVIOUS query, then set the input)."""
    src = _read("src/polymarket_mcp/web/templates/markets.html")
    start = src.index("async function filterByCategory")
    end = src.index("async function", start + 10)
    body = src[start:end]
    set_pos = body.index("document.getElementById('search-input').value = category;")
    await_pos = body.index("await searchMarkets();")
    assert set_pos < await_pos, (
        "filterByCategory must set the query BEFORE awaiting searchMarkets()"
    )


def test_search_and_trending_surface_envelope_errors():
    """searchMarkets AND loadTrendingMarkets surface data.error + response.ok."""
    src = _read("src/polymarket_mcp/web/templates/markets.html")
    for fn in ("async function searchMarkets", "async function loadTrendingMarkets"):
        start = src.index(fn)
        body = src[start: src.index("async function", start + 10)]
        assert "if (!response.ok)" in body, f"{fn}: missing response.ok guard"
        assert "data.error" in body, f"{fn}: missing error-envelope surfacing"


# ---------------------------------------------------------------------------
# 10-11. index.html + monitoring.html
# ---------------------------------------------------------------------------


def test_index_trending_panel_hardened():
    """index.html trending panel: response.ok + data.error + marketRowsOf."""
    src = _read("src/polymarket_mcp/web/templates/index.html")
    start = src.index("async function loadTrendingMarkets")
    body = src[start: src.index("async function", start + 10)]
    assert "if (!response.ok)" in body, "index trending: missing response.ok guard"
    assert "data.error" in body, "index trending: missing error-envelope surfacing"
    assert "marketRowsOf(data)" in body, "index trending: missing dual-state extraction"


def test_monitoring_stats_http_guard():
    """monitoring.html /api/stats: response.ok guard with a STATIC message."""
    src = _read("src/polymarket_mcp/web/templates/monitoring.html")
    fetch_pos = src.index("fetch('/api/stats')")
    guard = src.index("if (!response.ok)", fetch_pos)
    throw = src.index("throw new Error('HTTP ' + response.status)", guard)
    assert fetch_pos < guard < throw, (
        "monitoring.html must guard /api/stats with response.ok before reading JSON"
    )
    # No template-literal interpolation in the thrown message (no esc in this
    # file): the guard must carry ONLY the numeric status.
    assert "${" not in src[guard: throw], "monitoring.html error path must stay static"
