"""
Tests for GitHub issue fixes (#2, #6, #10).

- Issue #10: API credentials must not be logged at INFO level
- Issue #6: fastapi dependency must be compatible with mcp's anyio requirement
- Issue #2: Market discovery must filter out closed/expired markets
"""
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Issue #10 — Credential masking in server.py
# ---------------------------------------------------------------------------

class TestCredentialMasking:
    """Verify that API credentials are never logged in full."""

    def test_server_logs_truncated_key(self):
        """Credentials should be logged at DEBUG with only first 8 chars."""
        import polymarket_mcp.server as server_module
        import inspect
        source_code = inspect.getsource(server_module)

        # Must NOT contain the old full-logging pattern
        assert "logger.info(f\"POLYMARKET_API_KEY={" not in source_code, (
            "Full API key is still logged at INFO level"
        )
        assert "logger.info(f\"POLYMARKET_PASSPHRASE={" not in source_code, (
            "Full passphrase is still logged at INFO level"
        )

        # Must contain truncated debug logging
        assert "logger.debug(f\"POLYMARKET_API_KEY={" in source_code or \
               "logger.debug(f\"POLYMARKET_API_KEY=" in source_code, (
            "API key should be logged at DEBUG level"
        )
        assert "[:8]" in source_code, (
            "Credentials should be truncated to first 8 chars"
        )

    def test_no_full_credentials_at_info(self):
        """Ensure no line logs full credential values at INFO."""
        import polymarket_mcp.server as server_module
        import inspect
        lines = inspect.getsource(server_module).splitlines()

        for i, line in enumerate(lines):
            stripped = line.strip()
            if "logger.info" in stripped:
                assert "api_key)" not in stripped and "api_passphrase)" not in stripped, (
                    f"Line {i+1} logs full credential at INFO: {stripped}"
                )


# ---------------------------------------------------------------------------
# Issue #6 — fastapi dependency compatibility
# ---------------------------------------------------------------------------

class TestDependencyCompatibility:
    """Verify fastapi version constraint is compatible with mcp/anyio."""

    def test_fastapi_version_constraint(self):
        """fastapi must be pinned >=0.115.0 to support anyio>=4.5."""
        import tomllib
        import pathlib

        pyproject = pathlib.Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)

        deps = data["project"]["dependencies"]
        fastapi_dep = [d for d in deps if d.startswith("fastapi")]
        assert len(fastapi_dep) == 1, "Expected exactly one fastapi dependency"

        dep = fastapi_dep[0]
        # Extract minimum version
        assert ">=0.115.0" in dep or ">=0.115" in dep, (
            f"fastapi must be >=0.115.0, got: {dep}"
        )

    def test_no_old_fastapi_constraint(self):
        """Ensure old >=0.104.0 constraint is gone."""
        import pathlib

        pyproject = pathlib.Path(__file__).parent.parent / "pyproject.toml"
        content = pyproject.read_text()
        assert "fastapi>=0.104.0" not in content, (
            "Old fastapi>=0.104.0 constraint still present"
        )

    def test_pip_dry_run_install(self):
        """Verify pip can resolve dependencies without conflict."""
        import subprocess
        import sys
        import pathlib

        project_root = pathlib.Path(__file__).parent.parent
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--dry-run", "."],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        # pip dry-run should not report an error about dependency conflict
        assert "ResolutionImpossible" not in result.stderr, (
            f"Dependency resolution failed:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Issue #2 — Stale / closed market filtering
# ---------------------------------------------------------------------------

class TestMarketFiltering:
    """Verify that market discovery functions filter out old/closed markets."""

    @pytest.mark.asyncio
    async def test_search_markets_uses_public_search_endpoint(self):
        """search_markets must use Gamma's public search endpoint."""
        from polymarket_mcp.tools import market_discovery

        with patch.object(market_discovery, "_search_gamma_markets", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            await market_discovery.search_markets("test", limit=5)

            mock_fetch.assert_awaited_once_with("test", {}, 5)

    def test_public_search_flattens_event_markets(self):
        """public-search event results should be returned as a flat market list."""
        from polymarket_mcp.tools import market_discovery

        data = {
            "events": [
                {"title": "Bitcoin", "markets": [{"question": "BTC above 100k?"}]},
                {"title": "Ethereum", "markets": [{"question": "ETH above 4k?"}]},
            ]
        }

        results = market_discovery._flatten_public_search_markets(data, limit=1)

        assert results == [{"question": "BTC above 100k?"}]

    @pytest.mark.asyncio
    async def test_get_trending_markets_sends_active_and_closed_params(self):
        """get_trending_markets must include active=true and closed=false."""
        from polymarket_mcp.tools import market_discovery

        with patch.object(market_discovery, "_fetch_gamma_markets", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            await market_discovery.get_trending_markets(limit=5)

            mock_fetch.assert_called_once()
            call_args = mock_fetch.call_args
            params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
            assert params.get("active") == "true"
            assert params.get("closed") == "false"

    @pytest.mark.asyncio
    async def test_trending_markets_filters_expired_end_dates(self):
        """get_trending_markets must exclude markets whose end_date_iso is in the past."""
        from polymarket_mcp.tools import market_discovery

        past_date = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
        future_date = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"

        mock_markets = [
            {"question": "Old market", "end_date_iso": past_date, "volume24hr": "1000"},
            {"question": "Current market", "end_date_iso": future_date, "volume24hr": "500"},
            {"question": "No end date", "volume24hr": "200"},
        ]

        with patch.object(market_discovery, "_fetch_gamma_markets", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_markets
            results = await market_discovery.get_trending_markets(limit=10)

            # Old market should be filtered out
            questions = [m["question"] for m in results]
            assert "Old market" not in questions, "Expired market should be filtered out"
            assert "Current market" in questions
            assert "No end date" in questions

    @pytest.mark.asyncio
    async def test_featured_markets_filters_expired_end_dates(self):
        """get_featured_markets must exclude markets whose end_date_iso is in the past."""
        from polymarket_mcp.tools import market_discovery

        past_date = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
        future_date = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"

        mock_markets = [
            {"question": "Old featured", "end_date_iso": past_date, "volume24hr": "1000"},
            {"question": "Active featured", "end_date_iso": future_date, "volume24hr": "500"},
        ]

        with patch.object(market_discovery, "_fetch_gamma_markets", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_markets
            results = await market_discovery.get_featured_markets(limit=10)

            questions = [m["question"] for m in results]
            assert "Old featured" not in questions, "Expired featured market should be filtered out"
            assert "Active featured" in questions

    @pytest.mark.asyncio
    async def test_filter_by_category_sends_closed_false(self):
        """filter_markets_by_category must include closed=false."""
        from polymarket_mcp.tools import market_discovery

        with patch.object(market_discovery, "_fetch_gamma_markets", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            await market_discovery.filter_markets_by_category("Politics", active_only=True, limit=5)

            call_args = mock_fetch.call_args
            params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
            assert params.get("closed") == "false"
            assert params.get("active") == "true"

    @pytest.mark.asyncio
    async def test_closing_soon_sends_closed_false(self):
        """get_closing_soon_markets must include closed=false."""
        from polymarket_mcp.tools import market_discovery

        with patch.object(market_discovery, "_fetch_gamma_markets", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            await market_discovery.get_closing_soon_markets(hours=24, limit=5)

            call_args = mock_fetch.call_args
            params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
            assert params.get("closed") == "false"

    @pytest.mark.asyncio
    async def test_sports_markets_sends_closed_false(self):
        """get_sports_markets must include closed=false."""
        from polymarket_mcp.tools import market_discovery

        with patch.object(market_discovery, "_fetch_gamma_markets", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            await market_discovery.get_sports_markets(limit=5)

            call_args = mock_fetch.call_args
            params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
            assert params.get("closed") == "false"

    @pytest.mark.asyncio
    async def test_crypto_markets_sends_closed_false(self):
        """get_crypto_markets must include closed=false."""
        from polymarket_mcp.tools import market_discovery

        with patch.object(market_discovery, "_fetch_gamma_markets", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            await market_discovery.get_crypto_markets(limit=5)

            call_args = mock_fetch.call_args
            params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
            assert params.get("closed") == "false"

    @pytest.mark.asyncio
    async def test_featured_sends_closed_false(self):
        """get_featured_markets must include closed=false in params."""
        from polymarket_mcp.tools import market_discovery

        with patch.object(market_discovery, "_fetch_gamma_markets", new_callable=AsyncMock) as mock_fetch:
            # Return a market so fallback to trending isn't triggered
            mock_fetch.return_value = [{"question": "test", "end_date_iso": (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"}]
            await market_discovery.get_featured_markets(limit=5)

            call_args = mock_fetch.call_args
            params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
            assert params.get("closed") == "false"
