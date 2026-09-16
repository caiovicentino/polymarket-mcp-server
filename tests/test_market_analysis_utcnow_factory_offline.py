"""Offline suite: `default_factory` utcnow migration in tools/market_analysis.py (T-0098).

Pins:
- The 3 `Field(default_factory=...)` sites (PriceData.timestamp :42, OrderBook.timestamp
  :56, MarketOpportunity.last_updated :83) no longer resolve the deprecated
  `datetime.utcnow`. Constructing each model must NOT emit the CPython 3.12
  DeprecationWarning "utcnow() is deprecated" (surfaced at pydantic/main.py:263 when
  pydantic invokes the default factory) and the default value must remain NAIVE UTC
  (tzinfo is None — byte-identical semantics to the old utcnow()).
- `market_analysis._utcnow_naive` is IMMUNE to module-level patching of
  `market_analysis.datetime`: the offline gaps suite shims that name with a frozen
  clock that only implements utcnow() (tests/test_market_analysis_gaps_offline.py,
  _FrozenDatetime), so a factory resolving the module-level name would raise
  AttributeError under that shim. The helper imports the stdlib module locally, so a
  trap that raises on ANY attribute access through the patched module name cannot
  break it (structural pin by signature, P-0031).

The out-of-scope get_price_history sites (datetime.utcnow() at :365/:369) are pinned
INTACT by the contract acceptance greps — migrating them requires the human flip of
the _FrozenDatetime shim (REQUER-HUMANO item 84).

Hermetic (P-0029): no network, no filesystem writes, no real credentials.
"""

import warnings
from datetime import datetime, timezone

from polymarket_mcp.tools import market_analysis


class _TrapDatetime:
    """Shim-immunity probe: ANY attribute access through this object fails LOUD.

    Installed in place of `market_analysis.datetime` — if the helper (or any
    default_factory) resolves the module-level `datetime` name, construction of the
    AttributeError/AssertionError below fails the test with the exact discriminator
    message (a lambda resolving the module-level name is the regression this pin
    discriminates against).
    """

    def __getattr__(self, name):
        raise AssertionError(
            f"helper must not resolve module-level 'datetime' (accessed {name!r})"
        )


def _assert_no_utcnow_warning(caught):
    hits = [
        w
        for w in caught
        if issubclass(w.category, DeprecationWarning) and "utcnow() is deprecated" in str(w.message)
    ]
    assert hits == [], (
        f"deprecated utcnow default_factory still active: {[str(w.message) for w in hits]}"
    )


def test_price_data_factory_no_utcnow_warning_naive_default():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = market_analysis.PriceData(token_id="tok")
    _assert_no_utcnow_warning(caught)
    assert model.timestamp.tzinfo is None


def test_orderbook_factory_no_utcnow_warning_naive_default():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = market_analysis.OrderBook(token_id="tok", bids=[], asks=[])
    _assert_no_utcnow_warning(caught)
    assert model.timestamp.tzinfo is None


def test_market_opportunity_factory_no_utcnow_warning_naive_default():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = market_analysis.MarketOpportunity(
            market_id="mkt",
            market_question="Will event X happen?",
            risk_assessment="low",
            recommendation="HOLD",
            confidence_score=50.0,
            reasoning="neutral baseline",
        )
    _assert_no_utcnow_warning(caught)
    assert model.last_updated.tzinfo is None


def test_helper_ignores_module_patch(monkeypatch):
    monkeypatch.setattr(market_analysis, "datetime", _TrapDatetime())
    result = market_analysis._utcnow_naive()
    assert result.tzinfo is None
    drift = abs((result - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds())
    assert drift < 5, f"naive wall-clock drifted {drift:.3f}s"
