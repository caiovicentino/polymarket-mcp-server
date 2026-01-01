"""Offline UX regression suite for the config dashboard save path
(src/polymarket_mcp/web/templates/config.html) and explicit text-IO encoding
in src/polymarket_mcp/web/app.py.

T-0289 — three proven bugs (RED pre-fix on the merge base):

1. The save handler concatenated the FastAPI 422 `detail` payload directly
   (`'Failed to save: ' + result.detail`). For validation errors `detail` is
   an array of objects `{loc, msg, type}`, so the rendered notification is
   literally "Failed to save: [object Object]" -- illegible UX noise. Fix: a
   pure `formatDetailErrors(detail)` helper delimited by explicit anchor
   comments (`// formatDetailErrors-begin` / `// formatDetailErrors-end`)
   renders array entries as `loc.join('.') + ': ' + msg` joined with '; ' and
   non-array details via String(); the direct concatenation pattern disappears
   from the file.
2. Six `<input type="range">` sliders carried min/max values DIVERGENT from
   the real server domain of `ConfigUpdateRequest`
   (gt=0 / ge=0 le=1 / ge=0). The HTML spec clamps a range input's `.value`
   to its min/max AT RENDER, so a save silently rewrote manually-edited .env
   values with the clamped one. Fix: convert all six inputs to
   `type="number"` with min/max aligned to the server domain. Number inputs
   do NOT clamp: out-of-domain values mark the field `:invalid` and the form
   (no `novalidate`) blocks submit with an explicit browser message --
   explicit feedback, no silent rewrite.
   - max_order_size / max_exposure / max_position / min_liquidity:
     min="0.01", NO max (server gt=0 has no upper bound; a UI max would
     re-create the clamp bug).
   - max_spread: min="0" max="1" step="0.01" (exact mirror of ge=0 le=1).
   - confirmation_threshold: min="0", NO max (server ge=0).
3. app.py:402 `env_file.read_text()` and app.py:428 `write_text(...)` used
   bare text IO without `encoding="utf-8"` (P-0099: every farm-written
   read/write of text uses explicit encoding -- the cp1252 default on Windows
   CI breaks on non-ASCII bytes). app.py is the ONLY bare site in src/.

Compatibility: the `updateRangeValue` oninput handlers and the max_spread
percent display stay unchanged (observed behavior); the form keeps its
native validation (no `novalidate`); backend 422 behavior and its pins
(tests/test_web_config_validation_offline.py) are untouched.

Static-file tests only (no server, no network, no .env IO). Every
file read uses read_text(encoding="utf-8") (P-0099). Absence assertions are
paired with presence assertions (L-0056); the formatter is extracted via
content anchors, never line numbers (L-0127/L-0070).
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CONFIG_HTML = REPO / "src" / "polymarket_mcp" / "web" / "templates" / "config.html"
APP_PY = REPO / "src" / "polymarket_mcp" / "web" / "app.py"

FMT_BEGIN = "// formatDetailErrors-begin"
FMT_END = "// formatDetailErrors-end"

# The 6 USD/fraction inputs converted from range to number (T-0289 fix b).
_NUMBER_INPUT_IDS = (
    "max_order_size",
    "max_exposure",
    "max_position",
    "min_liquidity",
    "max_spread",
    "confirmation_threshold",
)
# The 4 USD inputs whose server domain is gt=0 with NO upper bound: the UI
# must not carry a max= attribute (a UI max re-creates the silent clamp).
_NO_MAX_IDS = ("max_order_size", "max_exposure", "max_position", "min_liquidity")

# Inline 422 fixture mirroring FastAPI's real ValidationError detail shape
# (loc is a path array, msg is the human message): consumed verbatim by the
# node probe of test_config_save_error_detail_node_output_legible.
_NODE_PROBE = (
    "const fixture = ["
    '{ loc: ["body", "max_order_size_usd"], '
    'msg: "Input should be greater than 0", '
    'type: "greater_than" }];\n'
    "console.log(JSON.stringify({"
    "arr: formatDetailErrors(fixture), "
    'str: formatDetailErrors("boom")}));\n'
)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _extract_block(html: str) -> str:
    """Extract the text between the formatDetailErrors anchor comments."""
    begin = html.index(FMT_BEGIN)
    end = html.index(FMT_END)
    return html[begin + len(FMT_BEGIN) : end]


def _extract_input(html: str, input_id: str) -> str:
    """Extract the full <input ...> element (line + continuation lines up to
    the closing '>') for the given id. Content-anchored, never global grep --
    ids are unique exactly ('max_order_size' vs span id
    'max_order_size_value' does not collide because the closing quote is
    part of the anchor)."""
    anchor = 'id="' + input_id + '"'
    lines = html.split("\n")
    for i, line in enumerate(lines):
        if anchor in line and "<input" in line:
            buf = [line]
            j = i
            while not buf[-1].rstrip().endswith(">"):
                j += 1
                buf.append(lines[j])
            return "\n".join(buf)
    raise AssertionError("input element with " + anchor + " not found")


def _call_slices(src: str, name: str) -> list:
    """Return each `<name>(...)` call site source slice (balanced-paren
    scan), so assertions inspect the WHOLE call, not one line."""
    out = []
    idx = 0
    while True:
        start = src.find(name + "(", idx)
        if start == -1:
            break
        i = start + len(name) + 1
        depth = 1
        while i < len(src) and depth:
            c = src[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        out.append(src[start:i])
        idx = i
    return out


def test_config_save_error_detail_not_object_noise():
    """The direct concatenation of result.detail is GONE from the template;
    paired with the positive presence of the formatter call at the same
    site (L-0056: absence is only meaningful next to presence)."""
    html = _read(CONFIG_HTML)
    assert "' + result.detail" not in html
    assert "formatDetailErrors(result.detail)" in html


def test_config_save_error_detail_formatter_anchors_and_shape():
    """Exactly one begin/end anchor pair; the delimited block is the pure
    formatter (no DOM), pinning the prescribed structure."""
    html = _read(CONFIG_HTML)
    assert html.count(FMT_BEGIN) == 1
    assert html.count(FMT_END) == 1
    block = _extract_block(html)
    assert "Array.isArray" in block
    assert "d.loc" in block
    assert "d.msg" in block


def test_config_save_error_detail_node_output_legible(tmp_path):
    """Execute the extracted formatter verbatim under node with a real
    422-shaped fixture: the rendered detail is legible
    ('loc: msg') and never '[object Object]'; a string detail passes
    through unchanged. Infra skip when node is unavailable."""
    if shutil.which("node") is None:
        pytest.skip("node unavailable")
    html = _read(CONFIG_HTML)
    block = _extract_block(html)
    script = block + "\n" + _NODE_PROBE
    probe = tmp_path / "probe.js"
    probe.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        ["node", str(probe)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "body.max_order_size_usd: Input should be greater than 0" in out
    assert "[object Object]" not in out
    assert '"str":"boom"' in out


def test_config_html_no_range_inputs_silent_clamp_removed():
    """No range inputs remain (silent clamp vector removed); paired with the
    positive replacement: exactly 6 number inputs."""
    html = _read(CONFIG_HTML)
    assert html.count('type="range"') == 0
    assert html.count('type="number"') == 6


def test_config_html_number_inputs_min_penny_floor():
    """Each converted input carries min aligned to the server domain,
    asserted on the WHOLE extracted element (L-0089b: never a bare global
    grep on a missing/shifted fragment)."""
    html = _read(CONFIG_HTML)
    for input_id in ("max_order_size", "max_exposure", "max_position", "min_liquidity"):
        el = _extract_input(html, input_id)
        assert 'min="0.01"' in el, input_id
    el = _extract_input(html, "max_spread")
    assert 'min="0"' in el
    assert 'max="1"' in el
    el = _extract_input(html, "confirmation_threshold")
    assert 'min="0"' in el


def test_config_html_no_ui_max_on_server_domain():
    """The 4 USD inputs have NO max= attribute: the server domain (gt=0) has
    no upper bound, and a UI max would re-create the silent clamp bug."""
    html = _read(CONFIG_HTML)
    for input_id in _NO_MAX_IDS:
        el = _extract_input(html, input_id)
        assert re.search(r"\bmax\s*=", el) is None, input_id


def test_app_py_text_io_explicit_encoding():
    """app.py (the only bare text-IO site in src/) uses explicit utf-8
    encoding on BOTH its read_text and its write_text; no bare read_text()
    and no write_text without encoding remain in the file."""
    src = _read(APP_PY)
    # Positive presence, paired with the absence assertions below (L-0056).
    assert 'read_text(encoding="utf-8")' in src
    assert 'encoding="utf-8"' in src
    reads = _call_slices(src, "read_text")
    writes = _call_slices(src, "write_text")
    assert reads, "read_text( present in app.py"
    assert writes, "write_text( present in app.py"
    assert not re.search(r"read_text\(\s*\)", src)
    for call in reads:
        assert 'encoding="utf-8"' in call
    for call in writes:
        assert 'encoding="utf-8"' in call
