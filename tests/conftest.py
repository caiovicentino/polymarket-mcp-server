"""
Pytest configuration and fixtures for Polymarket MCP Server tests.

This file is automatically loaded by pytest and provides:
- Custom markers
- Shared fixtures
- Test configuration
"""
import os
from pathlib import Path

import pytest

# Test modules that place real orders with a funded wallet. Without credentials
# they error out at fixture setup, which is what made CI red on every run.
CREDENTIAL_ONLY_MODULES = {
    "test_trading_tools.py",
    "test_portfolio_tools.py",
}


def pytest_configure(config):
    """Configure custom markers."""
    config.addinivalue_line(
        "markers", "integration: Integration tests with real API"
    )
    config.addinivalue_line(
        "markers", "slow: Slow tests (>5 seconds)"
    )
    config.addinivalue_line(
        "markers", "real_api: Tests requiring real API access"
    )
    config.addinivalue_line(
        "markers", "performance: Performance benchmarks"
    )
    config.addinivalue_line(
        "markers", "requires_credentials: Needs a funded wallet (POLYGON_PRIVATE_KEY)"
    )


def _has_wallet_credentials() -> bool:
    return bool(os.environ.get("POLYGON_PRIVATE_KEY")) and bool(
        os.environ.get("POLYGON_ADDRESS")
    )


def pytest_collection_modifyitems(config, items):
    """Skip wallet-dependent tests when no credentials are configured."""
    if _has_wallet_credentials():
        return

    skip_marker = pytest.mark.skip(
        reason="requires POLYGON_PRIVATE_KEY and POLYGON_ADDRESS (funded wallet)"
    )
    for item in items:
        module_name = Path(str(item.fspath)).name
        if module_name in CREDENTIAL_ONLY_MODULES or "requires_credentials" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def test_env_vars():
    """Set up test environment variables."""
    original_env = {}

    # Store original values
    for key in ["POLYGON_PRIVATE_KEY", "POLYGON_ADDRESS", "POLYMARKET_CHAIN_ID"]:
        original_env[key] = os.environ.get(key)

    # Set test values if not already set
    if not os.environ.get("POLYGON_PRIVATE_KEY"):
        os.environ["POLYGON_PRIVATE_KEY"] = "0" * 64

    if not os.environ.get("POLYGON_ADDRESS"):
        os.environ["POLYGON_ADDRESS"] = "0x" + "0" * 40

    if not os.environ.get("POLYMARKET_CHAIN_ID"):
        os.environ["POLYMARKET_CHAIN_ID"] = "137"

    yield

    # Restore original values
    for key, value in original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def clean_env():
    """Provide clean environment for each test."""
    import sys

    # Store original sys.path
    original_path = sys.path.copy()

    # Add src to path
    import pathlib
    src_path = str(pathlib.Path(__file__).parent.parent / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    yield

    # Restore sys.path
    sys.path = original_path


@pytest.fixture
def api_config():
    """API configuration for tests."""
    return {
        "gamma_api_url": "https://gamma-api.polymarket.com",
        "clob_api_url": "https://clob.polymarket.com",
        "ws_url": "wss://ws-subscriptions-clob.polymarket.com/ws/market",
    }


@pytest.fixture
async def async_cleanup():
    """Cleanup after async tests."""
    yield
    # Cleanup code here
    import asyncio
    # Cancel any remaining tasks
    tasks = [t for t in asyncio.all_tasks() if not t.done()]
    for task in tasks:
        task.cancel()


# Configure pytest-benchmark
def pytest_benchmark_update_json(config, benchmarks, output_json):
    """Customize benchmark JSON output."""
    output_json["environment"] = {
        "python_version": os.sys.version,
        "platform": os.sys.platform,
    }
