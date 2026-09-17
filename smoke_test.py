#!/usr/bin/env python3
"""
Smoke Test for Polymarket MCP Server

Quick validation of basic functionality (runs in ~10 seconds):
- Package imports
- Configuration loading
- API connectivity
- Basic tool execution

Returns: PASS/FAIL with details

Usage:
    python smoke_test.py
"""
import asyncio
import os
import sys
import time
from pathlib import Path

# Color codes for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


class SmokeTest:
    """Smoke test runner."""

    def __init__(self):
        self.tests_passed = 0
        self.tests_failed = 0
        self.start_time = time.time()

    def print_header(self):
        """Print test header."""
        print(f"\n{BLUE}{'='*60}")
        print("Polymarket MCP Server - Smoke Test")
        print(f"{'='*60}{RESET}\n")

    def print_test(self, name: str):
        """Print test name."""
        print(f"{BLUE}[TEST]{RESET} {name}...", end=" ", flush=True)

    def print_pass(self, message: str = ""):
        """Print test pass."""
        self.tests_passed += 1
        msg = f"{GREEN}✓ PASS{RESET}"
        if message:
            msg += f" - {message}"
        print(msg)

    def print_fail(self, message: str = ""):
        """Print test fail."""
        self.tests_failed += 1
        msg = f"{RED}✗ FAIL{RESET}"
        if message:
            msg += f" - {message}"
        print(msg)

    def print_skip(self, message: str = ""):
        """Print test skip."""
        msg = f"{YELLOW}⊘ SKIP{RESET}"
        if message:
            msg += f" - {message}"
        print(msg)

    def print_summary(self):
        """Print test summary."""
        duration = time.time() - self.start_time
        total = self.tests_passed + self.tests_failed

        print(f"\n{BLUE}{'='*60}")
        print("Test Summary")
        print(f"{'='*60}{RESET}")
        print(f"Total Tests: {total}")
        print(f"{GREEN}Passed: {self.tests_passed}{RESET}")
        print(f"{RED}Failed: {self.tests_failed}{RESET}")
        print(f"Duration: {duration:.2f}s")

        if self.tests_failed == 0:
            print(f"\n{GREEN}{'='*60}")
            print("ALL TESTS PASSED")
            print(f"{'='*60}{RESET}\n")
            return 0
        else:
            print(f"\n{RED}{'='*60}")
            print("TESTS FAILED")
            print(f"{'='*60}{RESET}\n")
            return 1

    def test_imports(self) -> bool:
        """Test package imports."""
        self.print_test("Package imports")

        try:
            # Add src to path
            sys.path.insert(0, str(Path(__file__).parent / "src"))

            # Try main imports
            from polymarket_mcp import config, server
            from polymarket_mcp.tools import market_analysis, market_discovery, realtime
            from polymarket_mcp.utils import RateLimiter, SafetyLimits

            self.print_pass("All modules imported")
            return True

        except ImportError as e:
            self.print_fail(f"Import error: {e}")
            return False

    def test_config_loading(self) -> bool:
        """Test configuration loading."""
        self.print_test("Configuration loading")

        try:
            # Set minimal env vars
            os.environ["POLYGON_PRIVATE_KEY"] = "0" * 64
            os.environ["POLYGON_ADDRESS"] = "0x" + "0" * 40

            from polymarket_mcp.config import load_config

            config = load_config()

            if config is None:
                self.print_fail("Config is None")
                return False

            if not config.POLYGON_ADDRESS:
                self.print_fail("Missing POLYGON_ADDRESS")
                return False

            self.print_pass("Config loaded successfully")
            return True

        except Exception as e:
            self.print_fail(f"Config error: {e}")
            return False
        finally:
            # Cleanup
            for key in ["POLYGON_PRIVATE_KEY", "POLYGON_ADDRESS"]:
                if key in os.environ:
                    del os.environ[key]

    def test_api_connectivity(self) -> bool:
        """Test API connectivity."""
        self.print_test("API connectivity")

        try:
            import httpx

            async def check_apis():
                async with httpx.AsyncClient(timeout=5.0) as client:
                    # Test Gamma API
                    gamma_response = await client.get(
                        "https://gamma-api.polymarket.com/markets",
                        params={"limit": 1}
                    )

                    if gamma_response.status_code != 200:
                        return False, f"Gamma API returned {gamma_response.status_code}"

                    return True, "Gamma API reachable"

            success, message = asyncio.run(check_apis())

            if success:
                self.print_pass(message)
                return True
            else:
                self.print_fail(message)
                return False

        except Exception as e:
            self.print_fail(f"API error: {e}")
            return False

    def test_tool_initialization(self) -> bool:
        """Test tool initialization."""
        self.print_test("Tool initialization")

        try:
            from polymarket_mcp.tools import market_analysis, market_discovery, realtime

            # Get tools
            discovery_tools = market_discovery.get_tools()
            analysis_tools = market_analysis.get_tools()
            realtime_tools = realtime.get_tools()

            # Verify counts
            if len(discovery_tools) < 8:
                self.print_fail(f"Expected >=8 discovery tools, got {len(discovery_tools)}")
                return False

            if len(analysis_tools) < 10:
                self.print_fail(f"Expected >=10 analysis tools, got {len(analysis_tools)}")
                return False

            if len(realtime_tools) < 7:
                self.print_fail(f"Expected >=7 realtime tools, got {len(realtime_tools)}")
                return False

            total = len(discovery_tools) + len(analysis_tools) + len(realtime_tools)
            self.print_pass(f"{total} tools available")
            return True

        except Exception as e:
            self.print_fail(f"Tool error: {e}")
            return False

    def test_basic_tool_execution(self) -> bool:
        """Test basic tool execution."""
        self.print_test("Basic tool execution")

        try:
            from polymarket_mcp.tools import market_discovery

            async def test_search():
                result = await market_discovery.handle_tool(
                    "search_markets",
                    {"query": "test", "limit": 1}
                )
                return result is not None

            success = asyncio.run(test_search())

            if success:
                self.print_pass("Tool executed successfully")
                return True
            else:
                self.print_fail("Tool returned None")
                return False

        except Exception as e:
            self.print_fail(f"Execution error: {e}")
            return False

    def test_rate_limiter(self) -> bool:
        """Test rate limiter."""
        self.print_test("Rate limiter")

        try:
            from polymarket_mcp.utils import EndpointCategory, RateLimiter

            limiter = RateLimiter()

            # Get status (synchronous method)
            status = limiter.get_status()

            if status and len(status) > 0:
                self.print_pass("Rate limiter working")
                return True
            else:
                self.print_fail("Rate limit status empty")
                return False

        except Exception as e:
            self.print_fail(f"Rate limiter error: {e}")
            return False

    def test_safety_limits(self) -> bool:
        """Test safety limits."""
        self.print_test("Safety limits")

        try:
            from polymarket_mcp.utils import SafetyLimits

            limits = SafetyLimits(
                max_order_size_usd=100.0,
                max_total_exposure_usd=1000.0,
                max_position_size_per_market=50.0,
                min_liquidity_required=500.0,
                max_spread_tolerance=0.05,
                require_confirmation_above_usd=50.0,
            )

            if limits.max_order_size_usd != 100.0:
                self.print_fail("Safety limits not set correctly")
                return False

            self.print_pass("Safety limits initialized")
            return True

        except Exception as e:
            self.print_fail(f"Safety limits error: {e}")
            return False

    def test_project_structure(self) -> bool:
        """Test project structure."""
        self.print_test("Project structure")

        try:
            project_root = Path(__file__).parent

            required_files = [
                "pyproject.toml",
                "README.md",
                "src/polymarket_mcp/__init__.py",
                "src/polymarket_mcp/server.py",
                "src/polymarket_mcp/config.py",
            ]

            missing = []
            for file_path in required_files:
                if not (project_root / file_path).exists():
                    missing.append(file_path)

            if missing:
                self.print_fail(f"Missing files: {', '.join(missing)}")
                return False

            self.print_pass("All required files present")
            return True

        except Exception as e:
            self.print_fail(f"Structure error: {e}")
            return False

    def run(self) -> int:
        """Run all smoke tests."""
        self.print_header()

        # Run tests
        self.test_project_structure()
        self.test_imports()
        self.test_config_loading()
        self.test_api_connectivity()
        self.test_tool_initialization()
        self.test_basic_tool_execution()
        self.test_rate_limiter()
        self.test_safety_limits()

        # Print summary
        return self.print_summary()


def main():
    """Main entry point."""
    runner = SmokeTest()
    exit_code = runner.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
