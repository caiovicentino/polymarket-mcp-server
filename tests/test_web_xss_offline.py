"""Offline XSS-hardening regression suite for the Polymarket MCP web frontend.

Contract T-0216: 9 named tests, 100% offline (no network, no server, no
browser). Anchors are matched by CONTENT (L-0127 -- never file:line, which
drifts on concurrent merges).

Mechanics
---------
- Templates/JS are read from the source tree via Path. A dev-only seam, env
  var ``WEB_XSS_SRC_DIR``, redirects the reads to a temp copy so the per-site
  mutation oracle (worker report, L-0090/P-0073) can revert ONE esc() site
  without touching canonical files. Default (env unset) is always the real
  source tree -- the seam never widens any assertion, it only changes WHERE
  files are read from.
- ``esc()`` behavior is exercised against the REAL app.js source via a
  ``node -e`` subprocess (local execution, no network). If node is absent
  the test SKIPs with an explicit reason (environment, L-0026/L-0028).
- Tripwire (P-0013): sha256 of every file the suite reads is snapshotted at
  session start and verified at session end -- the suite must be strictly
  read-only (zero writes outside tmpdir; the suite itself never writes).

Backend pin (test_backend_does_not_sanitize_and_notifications_safe)
-------------------------------------------------------------------
The fix is 100% frontend. ``src/polymarket_mcp/web/app.py`` must NOT gain
any HTML escape/sanitization (that would change the API contract for every
client), and ``showNotification`` must keep using ``textContent`` (safe by
construction -- wrapping it in esc() would double-escape).

RED pre-state (proven by the worker before the fix, kept as EVIDENCE):
tests 1-8 FAIL (esc absent, interpolated onclick present, no confidence
clamp, no encodeURIComponent on market-id URLs); test 9 PASSES (pin of an
invariant that must survive the fix).

Hygiene: every local variable captured inside try blocks is initialized
with a sentinel before the try (set -u equivalent); the suite performs no
network I/O and no filesystem writes.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Every path the suite reads (tripwire scope). Anchors must be added here
# when a new file is read, or the tripwire does not cover it.
_READ_FILES = (
    "polymarket_mcp/web/static/js/app.js",
    "polymarket_mcp/web/templates/index.html",
    "polymarket_mcp/web/templates/markets.html",
    "polymarket_mcp/web/app.py",
)


def _src_root() -> Path:
    """Source root for reads: real tree by default, temp copy under the seam."""
    override = os.environ.get("WEB_XSS_SRC_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "src"


def _read(relpath: str) -> str:
    return (_src_root() / relpath).read_text(encoding="utf-8")


def _app_js() -> str:
    return _read("polymarket_mcp/web/static/js/app.js")


def _markets() -> str:
    return _read("polymarket_mcp/web/templates/markets.html")


def _index() -> str:
    return _read("polymarket_mcp/web/templates/index.html")


def _app_py() -> str:
    return _read("polymarket_mcp/web/app.py")


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


# Node probe: loads the REAL app.js (DOM stubs only touch what app.js touches
# at load time -- addEventListener registrations; no callback runs), then
# prints one line per esc() probe. The ORACLE stays in Python: this process
# only transports the outputs.
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
eval(fs.readFileSync(process.env.WEBXSS_APP_JS, 'utf8'));
process.stdout.write(esc('<img src=x onerror=a>') + '\n');
process.stdout.write(esc('"a" & b \' c') + '\n');
"""


def test_esc_function_exists_with_five_entities():
    """esc() exists in app.js and escapes the 5 HTML-significant entities.

    Probes (exact expectations, 5 entities: & < > " '):
      esc('<img src=x onerror=a>') -> '&lt;img src=x onerror=a&gt;'
      esc('"a" & b \\' c')          -> '&quot;a&quot; &amp; b &#x27; c'
    """
    source = _app_js()
    assert "function esc" in source

    node = shutil.which("node")
    if not node:
        pytest.skip(
            "node not available on this host -- environment skip (L-0026/L-0028)"
        )

    env = dict(os.environ)
    env["WEBXSS_APP_JS"] = str(
        _src_root() / "polymarket_mcp" / "web" / "static" / "js" / "app.js"
    )
    proc = subprocess.run(
        [node, "-e", _NODE_PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert proc.returncode == 0, (
        f"node probe rc={proc.returncode}; stderr: {proc.stderr.strip()}"
    )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == 2, f"expected 2 probe lines, got: {lines!r}"
    # Entities < and > (attr/text context).
    assert lines[0] == "&lt;img src=x onerror=a&gt;"
    # Entities " & ' (attribute context) -- single quote uses numeric ref.
    assert lines[1] == "&quot;a&quot; &amp; b &#x27; c"


def test_market_question_escaped_in_both_templates():
    """market.question is esc()'d at every innerHTML render site it reaches.

    Sites (anchored by content, L-0127):
      - markets.html modal details block: <h3>${esc(market.question ...)}</h3>
      - markets.html markets table cell:  market-question">${esc(...)}
      - index.html trending list:         ${esc(market.question ...)}
    """
    markets = _markets()
    index = _index()
    # Markets page: modal details block.
    assert "${esc(market.question || 'Unknown Market')}" in markets
    # Markets page: markets table cell (class-marked anchor, unique to it).
    assert 'market-question">${esc(market.question' in markets
    # Dashboard page: trending list.
    assert "${esc(market.question || 'Unknown Market')}" in index


def test_market_description_escaped():
    """markets.html modal interpolates market.description through esc()."""
    assert "${esc(market.description" in _markets()


def test_no_interpolated_onclick_remains_and_delegation_present():
    """No onclick="...${...}" may remain; app.js must own the delegation.

    HTML-escaping does NOT protect a JS attribute (the value is decoded
    before the JS parser sees it), so interpolated onclick attributes must
    be GONE and replaced by data-action/data-market-id delegation handled
    once in app.js.
    """
    interpolated_onclick = re.compile(r'onclick="[^"]*\$\{')
    markets = _markets()
    index = _index()
    assert interpolated_onclick.search(markets) is None
    assert interpolated_onclick.search(index) is None

    app = _app_js()
    assert "data-action" in app
    assert "addEventListener" in app
    # Functional anchor (L-0065): the delegation SELECTOR itself, not a
    # prose mention -- a comment citing data-action must not satisfy this.
    assert "closest('[data-action]')" in app


def test_key_factors_li_escaped():
    """analysis.key_factors items are interpolated through esc() in <li>."""
    assert "<li>${esc(factor)}</li>" in _markets()


def test_error_message_escaped_in_innerhtml_sites():
    """Every innerHTML error.message interpolation is esc()'d (4 sites).

    Sites (anchored by each block's literal prefix, L-0127):
      - markets.html search failure block
      - markets.html trending-load failure block
      - markets.html details-modal failure block
      - index.html trending failure block
    showNotification sites ('...' + error.message) are textContent and stay
    unescaped by design (contract pin -- see test 9).
    """
    markets = _markets()
    index = _index()
    assert "Search failed: ${esc(error.message)}" in markets
    assert "Failed to load: ${esc(error.message)}" in markets
    assert "Failed to load details: ${esc(error.message)}" in markets
    assert "Failed to load markets: ${esc(error.message)}" in index
    # No raw interpolation of error.message may remain in any template.
    raw = re.compile(r"\$\{error\.message\}")
    assert raw.search(markets) is None
    assert raw.search(index) is None


def test_confidence_clamped_numeric():
    """Confidence is clamped to [0, 100] BEFORE interpolation into style.

    The clamp is NaN-safe via ``Number(...) || 0``; neither the style width
    nor the span may interpolate the raw external value.
    """
    markets = _markets()
    assert "Math.min(100" in markets
    assert "Math.max(0" in markets
    assert "Number(analysis.confidence_score)" in markets
    assert 'style="width: ${pct}%"' in markets
    assert "${pct.toFixed(0)}%" in markets
    # No raw confidence arithmetic may remain interpolated into the style.
    assert re.search(r"\$\{\(analysis\.confidence_score", markets) is None


def test_market_id_urls_encoded():
    """marketId goes through encodeURIComponent in every fetch URL in app.js."""
    app = _app_js()
    assert "`/api/markets/${encodeURIComponent(marketId)}`" in app
    assert "`/api/markets/${encodeURIComponent(marketId)}/analyze`" in app
    # Raw market-id interpolation in URLs must be gone (negative, paired with
    # the positive anchors above -- L-0056).
    assert "/api/markets/${marketId}" not in app


def test_backend_does_not_sanitize_and_notifications_safe():
    """Contract pin: the fix is 100% frontend.

    - app.py must NOT contain any HTML escape/sanitization (escaping
      server-side would change the API contract for every client).
    - showNotification must keep assigning ``textContent`` (safe by
      construction; wrapping it in esc() would double-escape).
    """
    app_py = _app_py()
    assert "html.escape" not in app_py
    assert "escape(" not in app_py
    assert "sanitize" not in app_py
    assert "notification.textContent = message" in _app_js()
