"""
Performance tests for Polymarket MCP Server.

Benchmarks:
- API response times
- Rate limiter performance
- Memory usage
- Concurrent request handling
- WebSocket message throughput
"""
import asyncio
import time
import pytest
import httpx
import psutil
import os
import sys
from pathlib import Path
from typing import List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from polymarket_mcp.utils.rate_limiter import EndpointCategory


# Test markers
pytestmark = pytest.mark.performance


@pytest.fixture
def performance_config():
    """Performance test configuration."""
    return {
        "gamma_api_url": "https://gamma-api.polymarket.com",
        "clob_api_url": "https://clob.polymarket.com",
        "concurrent_requests": 10,
        "stress_requests": 50,
    }


class TestAPIPerformance:
    """Test API response time performance."""

    def test_market_search_latency(self, performance_config, benchmark):
        """Benchmark market search latency."""
        async def search_markets():
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{performance_config['gamma_api_url']}/markets",
                    params={"limit": 10}
                )
                return response

        # Benchmark
        result = benchmark(lambda: asyncio.run(search_markets()))
        assert result.status_code == 200

    def test_market_details_latency(self, performance_config, benchmark):
        """Benchmark market details retrieval."""
        # First get a market ID
        async def fetch_market_id():
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{performance_config['gamma_api_url']}/markets",
                    params={"limit": 1}
                )
                return response.json()

        markets = asyncio.run(fetch_market_id())
        if len(markets) == 0:
            pytest.skip("No markets available")

        market_id = markets[0]["id"]

        async def get_details():
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{performance_config['gamma_api_url']}/markets/{market_id}"
                )
                return response

        result = benchmark(lambda: asyncio.run(get_details()))
        assert result.status_code == 200

    def test_clob_api_latency(self, performance_config, benchmark):
        """Benchmark CLOB API response time."""
        async def ping_clob():
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{performance_config['clob_api_url']}/ok"
                )
                return response

        result = benchmark(lambda: asyncio.run(ping_clob()))
        assert result.status_code == 200


class TestConcurrentPerformance:
    """Test concurrent request handling."""

    @pytest.mark.asyncio
    async def test_concurrent_market_searches(self, performance_config):
        """Test handling concurrent market searches."""
        async with httpx.AsyncClient() as client:
            url = f"{performance_config['gamma_api_url']}/markets"

            # Create concurrent requests
            start_time = time.time()
            tasks = [
                client.get(url, params={"limit": 5})
                for _ in range(performance_config['concurrent_requests'])
            ]

            responses = await asyncio.gather(*tasks)
            duration = time.time() - start_time

            # All should succeed
            success_count = sum(1 for r in responses if r.status_code == 200)

            print(f"\nConcurrent performance:")
            print(f"  Requests: {performance_config['concurrent_requests']}")
            print(f"  Duration: {duration:.2f}s")
            print(f"  Success: {success_count}/{len(responses)}")
            print(f"  Throughput: {len(responses)/duration:.2f} req/s")

            assert success_count >= performance_config['concurrent_requests'] * 0.8

    @pytest.mark.asyncio
    async def test_concurrent_different_endpoints(self, performance_config):
        """Test concurrent requests to different endpoints."""
        async with httpx.AsyncClient() as client:
            start_time = time.time()

            tasks = [
                client.get(f"{performance_config['gamma_api_url']}/markets", params={"limit": 1}),
                client.get(f"{performance_config['clob_api_url']}/ok"),
                client.get(f"{performance_config['gamma_api_url']}/markets", params={"limit": 5}),
            ]

            responses = await asyncio.gather(*tasks)
            duration = time.time() - start_time

            success_count = sum(1 for r in responses if r.status_code == 200)

            print(f"\nMixed endpoint performance:")
            print(f"  Requests: {len(tasks)}")
            print(f"  Duration: {duration:.2f}s")
            print(f"  Success: {success_count}/{len(responses)}")

            assert success_count == len(tasks)


class TestRateLimiterPerformance:
    """Test rate limiter performance."""

    def test_rate_limiter_overhead(self, benchmark):
        """Benchmark rate limiter overhead."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.utils import RateLimiter

        rate_limiter = RateLimiter()

        def check_rate_limit():
            return asyncio.run(rate_limiter.acquire(EndpointCategory.MARKET_DATA))

        # acquire() returns the seconds it waited, so 0.0 is the fast path.
        result = benchmark(check_rate_limit)
        assert isinstance(result, (int, float))
        assert result >= 0

    @pytest.mark.asyncio
    async def test_rate_limiter_concurrent(self):
        """Test rate limiter with concurrent requests."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.utils import RateLimiter

        rate_limiter = RateLimiter()

        async def check_limit():
            return await rate_limiter.acquire(EndpointCategory.MARKET_DATA)

        start_time = time.time()
        results = await asyncio.gather(*[check_limit() for _ in range(100)])
        duration = time.time() - start_time

        success_count = sum(1 for r in results if r)

        print(f"\nRate limiter concurrent performance:")
        print(f"  Checks: 100")
        print(f"  Duration: {duration:.4f}s")
        print(f"  Throughput: {100/duration:.0f} checks/s")
        print(f"  Success: {success_count}/100")

        # Should handle all checks quickly
        assert duration < 1.0  # Should be very fast


class TestMemoryUsage:
    """Test memory usage patterns."""

    @pytest.mark.asyncio
    async def test_tool_execution_memory(self):
        """Test memory usage during tool execution."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_discovery

        process = psutil.Process(os.getpid())

        # Get baseline memory
        baseline_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Execute tool multiple times
        for _ in range(10):
            await market_discovery.handle_tool(
                "search_markets",
                {"query": "test", "limit": 5}
            )

        # Get final memory
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - baseline_memory

        print(f"\nMemory usage:")
        print(f"  Baseline: {baseline_memory:.2f} MB")
        print(f"  Final: {final_memory:.2f} MB")
        print(f"  Increase: {memory_increase:.2f} MB")

        # Should not leak significant memory (allow 50MB increase)
        assert memory_increase < 50

    @pytest.mark.asyncio
    async def test_concurrent_execution_memory(self):
        """Test memory usage with concurrent execution."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_discovery

        process = psutil.Process(os.getpid())
        baseline_memory = process.memory_info().rss / 1024 / 1024

        # Execute many tools concurrently
        tasks = [
            market_discovery.handle_tool("search_markets", {"query": f"test{i}", "limit": 5})
            for i in range(20)
        ]

        await asyncio.gather(*tasks)

        final_memory = process.memory_info().rss / 1024 / 1024
        memory_increase = final_memory - baseline_memory

        print(f"\nConcurrent memory usage:")
        print(f"  Baseline: {baseline_memory:.2f} MB")
        print(f"  Final: {final_memory:.2f} MB")
        print(f"  Increase: {memory_increase:.2f} MB")

        # Allow more memory for concurrent execution
        assert memory_increase < 100


class TestToolPerformance:
    """Test individual tool performance."""

    def test_search_tool_performance(self, benchmark):
        """Benchmark search_markets tool."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_discovery

        async def search():
            return await market_discovery.handle_tool(
                "search_markets",
                {"query": "election", "limit": 10}
            )

        result = benchmark(lambda: asyncio.run(search()))
        assert result is not None

    def test_trending_tool_performance(self, benchmark):
        """Benchmark get_trending_markets tool."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_discovery

        async def get_trending():
            return await market_discovery.handle_tool(
                "get_trending_markets",
                {"limit": 10}
            )

        result = benchmark(lambda: asyncio.run(get_trending()))
        assert result is not None

    def test_filter_tool_performance(self, benchmark):
        """Benchmark filter_markets_by_category tool."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_discovery

        async def filter_markets():
            return await market_discovery.handle_tool(
                "filter_markets_by_category",
                {"category": "Politics", "limit": 10}
            )

        result = benchmark(lambda: asyncio.run(filter_markets()))
        assert result is not None


class TestStressScenarios:
    """Stress testing scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_rapid_tool_execution(self):
        """Test rapid tool execution."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_discovery

        start_time = time.time()

        # Execute 50 tool calls rapidly
        tasks = [
            market_discovery.handle_tool("search_markets", {"query": f"test{i}", "limit": 1})
            for i in range(50)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        duration = time.time() - start_time

        success_count = sum(1 for r in results if not isinstance(r, Exception))

        print(f"\nStress test results:")
        print(f"  Total requests: 50")
        print(f"  Duration: {duration:.2f}s")
        print(f"  Success: {success_count}/50")
        print(f"  Throughput: {50/duration:.2f} req/s")

        # Should handle at least 80% successfully
        assert success_count >= 40

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_sustained_load(self):
        """Test sustained load over time."""
        import sys
        sys.path.insert(0, "src")

        from polymarket_mcp.tools import market_discovery

        duration = 10  # seconds
        request_count = 0
        errors = 0

        start_time = time.time()
        end_time = start_time + duration

        while time.time() < end_time:
            try:
                await market_discovery.handle_tool(
                    "search_markets",
                    {"query": "test", "limit": 1}
                )
                request_count += 1
            except Exception as e:
                errors += 1

            # Small delay between requests
            await asyncio.sleep(0.1)

        actual_duration = time.time() - start_time

        print(f"\nSustained load test:")
        print(f"  Duration: {actual_duration:.2f}s")
        print(f"  Requests: {request_count}")
        print(f"  Errors: {errors}")
        print(f"  Throughput: {request_count/actual_duration:.2f} req/s")

        # Each iteration costs a 0.1s sleep plus a live round trip, so the rate
        # is network-bound. Assert a floor of 1.5 req/s, which still catches a
        # stall without failing on normal API latency.
        assert request_count > actual_duration * 1.5, (
            f"Only {request_count} requests in {actual_duration:.1f}s"
        )
        assert errors < request_count * 0.1  # Less than 10% errors


class TestWebSocketPerformance:
    """Test WebSocket performance."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_websocket_connection_time(self):
        """Benchmark WebSocket connection time."""
        import websockets

        ws_url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

        start_time = time.time()

        try:
            async with websockets.connect(ws_url, ping_timeout=10) as websocket:
                connection_time = time.time() - start_time

                print(f"\nWebSocket connection:")
                print(f"  Time: {connection_time:.3f}s")

                assert connection_time < 5.0  # Should connect within 5 seconds
        except Exception as e:
            pytest.skip(f"WebSocket connection failed: {e}")


def test_benchmark_summary(benchmark):
    """Summary of benchmark results."""
    # This will show benchmark comparison
    pass


if __name__ == "__main__":
    # Run performance tests with benchmarking
    pytest.main([
        __file__,
        "-v",
        "--benchmark-only",
        "--benchmark-json=benchmark_results.json"
    ])
