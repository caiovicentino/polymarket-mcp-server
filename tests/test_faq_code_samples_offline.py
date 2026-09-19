"""F2: FAQ.md code samples must run.

Contract (farm/T-0336): the FAQ programmatic-use example used
``from polymarket_mcp.tools import *`` and then called
``get_trending_markets`` -- a NameError, because tools/__init__.py exports
only ``market_discovery``, ``market_analysis``, ``TradingTools`` and
``get_tool_definitions``. The sample now imports from the module that owns
the function (same pattern as the earlier sample at FAQ:631). The stale
"planned for v0.2.0" claim is corrected (v0.2.0 shipped without backtesting;
CHANGELOG 0.2.0 has no backtesting entry).
"""
import pathlib

FAQ = pathlib.Path(__file__).resolve().parent.parent / "FAQ.md"


def test_no_star_import_in_samples():
    text = FAQ.read_text(encoding="utf-8")
    assert "from polymarket_mcp.tools import *" not in text


def test_module_scoped_import_present():
    text = FAQ.read_text(encoding="utf-8")
    assert (
        "from polymarket_mcp.tools.market_discovery import get_trending_markets"
        in text
    )


def test_no_stale_backtesting_claim():
    text = FAQ.read_text(encoding="utf-8")
    assert "planned for v0.2.0" not in text
    assert "planned for a future release" in text


def test_tools_package_star_export_does_not_provide_trending():
    """Pins the REASON the sample was fixed: star-import from the tools
    package never exposed get_trending_markets (NameError under the fix)."""
    import polymarket_mcp.tools as tools_pkg

    assert not hasattr(tools_pkg, "get_trending_markets")
    # ...and the corrected import path does exist.
    from polymarket_mcp.tools.market_discovery import get_trending_markets  # noqa: F401
