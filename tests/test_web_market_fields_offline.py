"""Offline regression suite for the gamma wire field contract in the web UI.

Contract T-0308: the dashboard templates must read the field names the
gamma API actually ships on the wire (volume24hr, outcomePrices,
bestAsk/bestBid) instead of snake_case names that do not exist, which
rendered "Volume: $0", "N/A" prices and "0.00%" spread for every market.

Five named tests, 100% offline (no network, no server, no browser).
Anchors are matched by CONTENT (L-0127 -- never file:line, which drifts
on concurrent merges).

Mechanics
---------
- Templates are read from the source tree via Path.read_text with an
  explicit encoding (item-156 class: a bare read_text breaks on hosts
  whose locale resolves to a non-UTF-8 default encoding).
- A dev-only seam, env var ``WEB_MARKET_FIELDS_SRC_DIR``, redirects the
  reads to a temp copy so mutation probes can exercise ONE template copy
  without touching canonical files. Default (env unset) is always the
  real source tree -- the seam never widens any assertion, it only
  changes WHERE files are read from.
- Tripwire (P-0013): sha256 of every file the suite reads is snapshotted
  at session start and verified at session end -- the suite must be
  strictly read-only (the suite itself never writes).

Fix shape (proven on sim branch sim/c68-web @ cf58562, template commit F2)
--------------------------------------------------------------------------
- ``outcomePricesOf(market)``: JSON.parse of the wire's ``outcomePrices``
  JSON string, []-returning on absent/malformed input (formatPrice(null)
  renders 'N/A').
- ``marketSpread(market)``: bestAsk - bestBid from the book levels the
  wire actually provides; 0 when either level is absent.
- ``market.volume_24h`` -> ``market.volume24hr`` (table + modal + index
  trending panel).
- ``market.condition_id || market.id`` stays UNTOUCHED (3 sites): the
  numeric-id fetch resolution is the only one that works (the
  /markets/{conditionId} route 404s -- slug-shaped); the fallback
  resolves to market.id today.

RED pre-state (proven by the worker before the fix, kept as EVIDENCE):
tests 1-3 FAIL (snake_case keys still present, wire keys absent, no
helpers); tests 4-5 PASS (pins of invariants that must survive the fix).

Hygiene: the suite performs no network I/O and no filesystem writes.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Every path the suite reads (tripwire scope). Anchors must be added here
# when a new file is read, or the tripwire does not cover it.
_READ_FILES = (
    "polymarket_mcp/web/templates/index.html",
    "polymarket_mcp/web/templates/markets.html",
)


def _src_root() -> Path:
    """Source root for reads: real tree by default, temp copy under the seam."""
    override = os.environ.get("WEB_MARKET_FIELDS_SRC_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "src"


def _read(relpath: str) -> str:
    return (_src_root() / relpath).read_text(encoding="utf-8")


def _markets() -> str:
    return _read("polymarket_mcp/web/templates/markets.html")


def _index() -> str:
    return _read("polymarket_mcp/web/templates/index.html")


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


def test_wire_volume_key_used_and_snake_key_gone():
    """Volume renders from the wire key the API actually ships.

    NEG: the snake_case ``market.volume_24h`` (ABSENT on the wire) must be
    gone from BOTH templates -- any leftover keeps rendering "$0".
    POS: ``market.volume24hr`` is used with count FLOORS, never exact
    counts (L-0023): index trending >= 1, markets page >= 2 (table +
    modal).
    """
    markets = _markets()
    index = _index()
    assert "market.volume_24h" not in markets
    assert "market.volume_24h" not in index
    assert markets.count("market.volume24hr") >= 2
    assert index.count("market.volume24hr") >= 1


def test_outcome_prices_parsed_and_snake_keys_gone():
    """YES/NO prices come from the wire's outcomePrices JSON string.

    NEG: ``market.price_yes`` / ``market.price_no`` (ABSENT on the wire)
    must be gone -- any leftover keeps rendering "N/A".
    POS: the ``outcomePricesOf`` helper exists exactly once, parses the
    wire's ``outcomePrices`` field via JSON.parse, and is used at >= 4
    sites (2 in the markets table + 2 in the details modal; the helper
    definition itself brings the total occurrences to 5 -- floors, not
    exact counts, L-0023).
    """
    markets = _markets()
    assert "market.price_yes" not in markets
    assert "market.price_no" not in markets
    assert markets.count("function outcomePricesOf(") == 1
    assert "JSON.parse(market.outcomePrices" in markets
    assert markets.count("outcomePricesOf(market)") >= 4


def test_spread_computed_from_book_levels():
    """Spread is computed from bestAsk/bestBid, not read from the wire.

    NEG: ``market.spread`` (ABSENT on the wire) must be gone -- any
    leftover keeps rendering "0.00%".
    POS: the ``marketSpread`` helper exists exactly once, reads BOTH book
    levels the wire actually provides (``market.bestAsk`` and
    ``market.bestBid``), and is used at >= 2 sites (table + modal).
    """
    markets = _markets()
    assert "market.spread" not in markets
    assert markets.count("function marketSpread(") == 1
    assert "market.bestAsk" in markets
    assert "market.bestBid" in markets
    assert markets.count("marketSpread(market)") >= 2


def test_id_resolution_fallback_unchanged():
    """Pin of PERMANENCE: the id fallback stays exactly as it is.

    ``market.condition_id || market.id`` (3 sites: 2 action buttons +
    the modal "Market ID") is the ONLY resolution that works: fetching
    /markets/{conditionId} 404s (slug-shaped path); the fallback
    resolves to market.id today. This pin forbids "simplifying" it to
    market.conditionId.
    """
    markets = _markets()
    assert markets.count("market.condition_id || market.id") == 3


def test_xss_pins_still_intact():
    """Anti-collateral guard: the T-0216 XSS pins survive this change.

    Re-asserts the structural pins of tests/test_web_xss_offline.py that
    overlap the lines this contract rewrites:
    - market.question is esc()'d at 3 sites (modal h3 + table cell +
      index trending);
    - market.description is esc()'d (modal);
    - error.message is esc()'d at 3 innerHTML sites in markets.html;
    - analysis.key_factors items go through esc() in <li>;
    - no interpolated onclick="${...}" remains.
    """
    markets = _markets()
    index = _index()
    # esc(market.question): modal block + table cell + index trending.
    assert "${esc(market.question || 'Unknown Market')}" in markets
    assert 'market-question">${esc(market.question' in markets
    assert "${esc(market.question || 'Unknown Market')}" in index
    # esc(market.description): modal block.
    assert "${esc(market.description" in markets
    # error.message: 3 innerHTML sites in markets.html.
    assert "Search failed: ${esc(error.message)}" in markets
    assert "Failed to load: ${esc(error.message)}" in markets
    assert "Failed to load details: ${esc(error.message)}" in markets
    # key_factors <li>.
    assert "<li>${esc(factor)}</li>" in markets
    # No interpolated onclick attributes anywhere.
    interpolated_onclick = re.compile(r'onclick="[^"]*\$\{')
    assert interpolated_onclick.search(markets) is None
    assert interpolated_onclick.search(index) is None
