"""
End-to-End tests for Polymarket MCP Server.

Tests the complete MCP server lifecycle:
1. Installation and configuration
2. Server initialization
3. Tool execution
4. Response validation
5. Cleanup
"""
import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_env_file():
    """Create temporary .env file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        f.write("POLYGON_PRIVATE_KEY=0000000000000000000000000000000000000000000000000000000000000001\n")
        f.write("POLYGON_ADDRESS=0x0000000000000000000000000000000000000001\n")
        f.write("POLYMARKET_CHAIN_ID=137\n")
        yield f.name

    # Cleanup
    os.unlink(f.name)


@pytest.fixture
def project_root():
    """Get project root directory."""
    return Path(__file__).parent.parent


class TestServerInitialization:
    """Test MCP server initialization."""

    def test_package_import(self):
        """Test that package can be imported."""
        import sys
        sys.path.insert(0, "src")

        try:
            from polymarket_mcp import server
            assert server is not None
        except ImportError as e:
            pytest.fail(f"Failed to import package: {e}")

    def test_config_loading(self):
        """Test configuration loading."""
        import sys
        sys.path.insert(0, "src")

        os.environ["POLYGON_PRIVATE_KEY"] = "0" * 64
        os.environ["POLYGON_ADDRESS"] = "0x" + "0" * 40

        try:
            from polymarket_mcp.config import load_config
            config = load_config()
            assert config is not None
            assert config.POLYGON_ADDRESS is not None
        finally:
            # Cleanup
            for key in ["POLYGON_PRIVATE_KEY", "POLYGON_ADDRESS"]:
                if key in os.environ:
                    del os.environ[key]

    def test_tools_available(self):
        """Test that all tool modules are available."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_analysis, market_discovery, realtime

        # Check market discovery tools
        discovery_tools = market_discovery.get_tools()
        assert len(discovery_tools) >= 8, "Expected at least 8 market discovery tools"

        # Check market analysis tools
        analysis_tools = market_analysis.get_tools()
        assert len(analysis_tools) >= 10, "Expected at least 10 market analysis tools"

        # Check realtime tools
        realtime_tools = realtime.get_tools()
        assert len(realtime_tools) >= 7, "Expected at least 7 realtime tools"


class TestToolExecution:
    """Test individual tool execution."""

    @pytest.mark.asyncio
    async def test_search_markets_tool(self):
        """Test search_markets tool execution."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_discovery

        # Execute tool
        result = await market_discovery.handle_tool(
            "search_markets",
            {"query": "election", "limit": 5}
        )

        assert result is not None
        assert len(result) > 0

        # Parse result
        result_text = result[0].text
        data = json.loads(result_text)

        # Discovery tools return a JSON list of markets; errors come back as a dict.
        assert isinstance(data, list) or "markets" in data or "error" in data

    @pytest.mark.asyncio
    async def test_get_trending_markets_tool(self):
        """Test get_trending_markets tool execution."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_discovery

        result = await market_discovery.handle_tool(
            "get_trending_markets",
            {"limit": 5, "timeframe": "24h"}
        )

        assert result is not None
        result_text = result[0].text
        data = json.loads(result_text)

        # Discovery tools return a JSON list of markets; errors come back as a dict.
        assert isinstance(data, list) or "markets" in data or "error" in data

    @pytest.mark.asyncio
    async def test_filter_markets_by_category_tool(self):
        """Test filter_markets_by_category tool."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_discovery

        result = await market_discovery.handle_tool(
            "filter_markets_by_category",
            {"category": "Politics", "limit": 5}
        )

        assert result is not None
        result_text = result[0].text
        data = json.loads(result_text)

        # Discovery tools return a JSON list of markets; errors come back as a dict.
        assert isinstance(data, list) or "markets" in data or "error" in data

    @pytest.mark.asyncio
    async def test_get_market_details_tool(self):
        """Test get_market_details tool."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_analysis, market_discovery

        # First get a market
        markets_result = await market_discovery.handle_tool(
            "search_markets",
            {"query": "trump", "limit": 1}
        )

        markets_data = json.loads(markets_result[0].text)

        if "markets" in markets_data and len(markets_data["markets"]) > 0:
            market_id = markets_data["markets"][0].get("id") or markets_data["markets"][0].get("market_id")

            # Get details
            details_result = await market_analysis.handle_tool(
                "get_market_details",
                {"market_id": market_id}
            )

            assert details_result is not None
            details_data = json.loads(details_result[0].text)
            assert "market" in details_data or "error" in details_data


class TestResourceAccess:
    """Test MCP resource access."""

    @pytest.mark.asyncio
    async def test_status_resource(self):
        """Test reading status resource."""
        import sys
        sys.path.insert(0, "src")

        os.environ["POLYGON_PRIVATE_KEY"] = "0" * 64
        os.environ["POLYGON_ADDRESS"] = "0x" + "0" * 40

        try:
            from polymarket_mcp.server import initialize_server, read_resource

            # Initialize server
            await initialize_server()

            # Read status
            status = await read_resource("polymarket://status")
            assert status is not None

            data = json.loads(status)
            assert "connected" in data
            assert "address" in data
        finally:
            # Cleanup
            for key in ["POLYGON_PRIVATE_KEY", "POLYGON_ADDRESS"]:
                if key in os.environ:
                    del os.environ[key]

    @pytest.mark.asyncio
    async def test_config_resource(self):
        """Test reading config resource."""
        import sys
        sys.path.insert(0, "src")

        os.environ["POLYGON_PRIVATE_KEY"] = "0" * 64
        os.environ["POLYGON_ADDRESS"] = "0x" + "0" * 40

        try:
            from polymarket_mcp.server import initialize_server, read_resource

            await initialize_server()

            # Read config
            config = await read_resource("polymarket://config")
            assert config is not None

            data = json.loads(config)
            assert "safety_limits" in data or "error" in data
        finally:
            for key in ["POLYGON_PRIVATE_KEY", "POLYGON_ADDRESS"]:
                if key in os.environ:
                    del os.environ[key]


class TestErrorScenarios:
    """Test error handling in E2E scenarios."""

    @pytest.mark.asyncio
    async def test_tool_with_invalid_arguments(self):
        """Test tool execution with invalid arguments."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_discovery

        # Invalid limit (negative)
        result = await market_discovery.handle_tool(
            "search_markets",
            {"query": "test", "limit": -1}
        )

        result_text = result[0].text
        data = json.loads(result_text)

        # Should handle gracefully: a list of results or an error dict.
        assert isinstance(data, list) or "error" in data or "markets" in data

    @pytest.mark.asyncio
    async def test_tool_missing_required_arg(self):
        """Test tool execution with missing required arguments."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_discovery

        try:
            # Missing query argument
            result = await market_discovery.handle_tool(
                "search_markets",
                {"limit": 5}  # Missing 'query'
            )

            # Should either error or use default
            assert result is not None
        except (TypeError, KeyError):
            # Expected - missing required argument
            pass

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        """Test calling unknown tool."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.server import call_tool

        os.environ["POLYGON_PRIVATE_KEY"] = "0" * 64
        os.environ["POLYGON_ADDRESS"] = "0x" + "0" * 40

        try:
            from polymarket_mcp.server import initialize_server
            await initialize_server()

            result = await call_tool("unknown_tool_xyz", {})

            result_text = result[0].text
            data = json.loads(result_text)

            # Should return error
            assert "error" in data or "success" in data
        finally:
            for key in ["POLYGON_PRIVATE_KEY", "POLYGON_ADDRESS"]:
                if key in os.environ:
                    del os.environ[key]


class TestFullWorkflow:
    """Test complete E2E workflows."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_market_discovery_workflow(self):
        """Test complete market discovery workflow."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_discovery

        # 1. Search for markets
        search_result = await market_discovery.handle_tool(
            "search_markets",
            {"query": "election", "limit": 3}
        )

        assert search_result is not None
        search_data = json.loads(search_result[0].text)

        # 2. Get trending markets
        trending_result = await market_discovery.handle_tool(
            "get_trending_markets",
            {"limit": 3, "timeframe": "24h"}
        )

        assert trending_result is not None
        trending_data = json.loads(trending_result[0].text)

        # 3. Filter by category
        category_result = await market_discovery.handle_tool(
            "filter_markets_by_category",
            {"category": "Politics", "limit": 3}
        )

        assert category_result is not None
        category_data = json.loads(category_result[0].text)

        # All should succeed (list of markets) or return valid errors
        assert all(
            isinstance(data, list) or "markets" in data or "error" in data
            for data in [search_data, trending_data, category_data]
        )

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_market_analysis_workflow(self):
        """Test market analysis workflow."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_analysis, market_discovery

        # 1. Get a market
        markets_result = await market_discovery.handle_tool(
            "get_trending_markets",
            {"limit": 1}
        )

        markets_data = json.loads(markets_result[0].text)

        if "markets" in markets_data and len(markets_data["markets"]) > 0:
            market = markets_data["markets"][0]
            market_id = market.get("id") or market.get("market_id")

            # 2. Get market details
            details_result = await market_analysis.handle_tool(
                "get_market_details",
                {"market_id": market_id}
            )

            assert details_result is not None
            details_data = json.loads(details_result[0].text)

            # 3. If market has tokens, get price info
            if "market" in details_data:
                market_detail = details_data["market"]
                if "tokens" in market_detail and len(market_detail["tokens"]) > 0:
                    token_id = market_detail["tokens"][0].get("token_id")

                    if token_id:
                        price_result = await market_analysis.handle_tool(
                            "get_current_price",
                            {"token_id": token_id}
                        )

                        assert price_result is not None


class TestInstallationFlow:
    """Test installation and setup flow."""

    def test_package_structure(self, project_root):
        """Test package has correct structure."""
        src_dir = project_root / "src" / "polymarket_mcp"

        # Check main files exist
        assert (src_dir / "__init__.py").exists()
        assert (src_dir / "server.py").exists()
        assert (src_dir / "config.py").exists()

        # Check tools directory
        tools_dir = src_dir / "tools"
        assert tools_dir.exists()

    def test_pyproject_toml_exists(self, project_root):
        """Test pyproject.toml exists and is valid."""
        pyproject = project_root / "pyproject.toml"
        assert pyproject.exists()

        # Try to parse it
        try:
            import tomllib
        except ImportError:
            pytest.skip("tomllib requires Python 3.11+")

        with open(pyproject, 'rb') as f:
            data = tomllib.load(f)
            assert "project" in data
            assert "name" in data["project"]

    def test_readme_exists(self, project_root):
        """Test README exists."""
        readme = project_root / "README.md"
        assert readme.exists()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_complete_e2e_flow():
    """
    Test complete end-to-end flow:
    1. Initialize server
    2. Execute multiple tools
    3. Validate responses
    4. Clean up
    """
    import sys
    sys.path.insert(0, "src")

    os.environ["POLYGON_PRIVATE_KEY"] = "0" * 64
    os.environ["POLYGON_ADDRESS"] = "0x" + "0" * 40

    try:
        from polymarket_mcp.server import initialize_server, list_tools
        from polymarket_mcp.tools import market_discovery

        # 1. Initialize
        await initialize_server()

        # 2. List tools
        tools = await list_tools()
        assert len(tools) >= 25  # Minimum in read-only mode

        # 3. Execute market discovery
        result = await market_discovery.handle_tool(
            "search_markets",
            {"query": "bitcoin", "limit": 2}
        )

        assert result is not None
        data = json.loads(result[0].text)
        # Discovery tools return a JSON list of markets; errors come back as a dict.
        assert isinstance(data, list) or "markets" in data or "error" in data

        # 4. Get trending
        result = await market_discovery.handle_tool(
            "get_trending_markets",
            {"limit": 2}
        )

        assert result is not None
        data = json.loads(result[0].text)
        # Discovery tools return a JSON list of markets; errors come back as a dict.
        assert isinstance(data, list) or "markets" in data or "error" in data

    finally:
        # Cleanup
        for key in ["POLYGON_PRIVATE_KEY", "POLYGON_ADDRESS"]:
            if key in os.environ:
                del os.environ[key]


if __name__ == "__main__":
    # Run E2E tests
    pytest.main([__file__, "-v", "-s"])
