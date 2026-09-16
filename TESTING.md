# Testing Guide

Comprehensive testing documentation for the Polymarket MCP Server.

## Table of Contents

- [Overview](#overview)
- [Test Categories](#test-categories)
- [Running Tests](#running-tests)
- [Writing Tests](#writing-tests)
- [CI/CD Pipeline](#cicd-pipeline)
- [Coverage Reports](#coverage-reports)
- [Performance Benchmarks](#performance-benchmarks)

## Overview

The Polymarket MCP Server uses a comprehensive testing strategy with multiple test categories:

- **Offline (Unit) Tests**: Fast, isolated tests of individual components using deterministic fakes (hermetic — no network)
- **Integration Tests**: Tests with real API interactions (marked `integration`)
- **End-to-End Tests**: Complete workflow testing
- **Performance Tests**: Benchmarks and stress testing
- **Smoke Tests**: Quick validation of basic functionality

### Test Philosophy

**Layered strategy** - The suite is organized in tiers:

- **Offline tier (default)**: every test file without a tier marker is hermetic —
  deterministic fakes at module seams (fail-loud stubs, `httpx.MockTransport`,
  fake clocks) instead of live calls. Most are named `tests/test_*_offline.py`.
  This is the tier day-to-day development runs (see [Unit Tests](#unit-tests-offline-tier)).
- **Real-API tiers**: tests marked `integration`, `real_api`, or `performance`
  exercise the live Polymarket APIs (Gamma, CLOB, WebSocket) and run only when
  credentials/network are available — they are excluded from the offline selection.
- **Wallet-dependent tests**: modules listed in `CREDENTIAL_ONLY_MODULES` and tests
  marked `@pytest.mark.requires_credentials` are skipped automatically when
  `POLYGON_PRIVATE_KEY`/`POLYGON_ADDRESS` are not set (see
  `pytest_collection_modifyitems` in `tests/conftest.py`).

This ensures offline tests are fast, deterministic, and network-free, while the
real-API tiers catch actual behavior changes early.

## Test Categories

### Unit Tests (Offline Tier)

Fast tests of individual functions and classes.

```bash
# Run the offline tier (default for day-to-day development)
pytest tests/ -m "not integration and not slow and not real_api and not performance"

# Run with parallel execution
pytest tests/ -m "not integration and not slow and not real_api and not performance" -n auto
```

**Characteristics:**
- Execution time: <1 second per test
- Hermetic: deterministic fakes at module seams — fail-loud stubs, `httpx.MockTransport`, fake clocks; no network access
- Test individual functions/classes
- Most offline suites are named `tests/test_*_offline.py`

### Integration Tests

Tests with real API calls to Polymarket services.

```bash
# Run integration tests
pytest tests/ -m integration

# Run with verbose output
pytest tests/test_integration.py -v
```

**What they test:**
- API connectivity (Gamma API, CLOB API)
- Market discovery tools
- Market analysis tools
- Error handling
- Rate limiting behavior

**Test markers:**
- `@pytest.mark.integration` - Integration test
- `@pytest.mark.real_api` - Requires real API access
- `@pytest.mark.slow` - Takes >5 seconds

### End-to-End Tests

Complete workflow testing from initialization to cleanup.

```bash
# Run E2E tests
pytest tests/test_e2e.py -v

# With detailed output
pytest tests/test_e2e.py -v -s
```

**Test scenarios:**
1. Server initialization
2. Configuration loading
3. Tool execution
4. Response validation
5. Resource access
6. Error handling
7. Complete workflows

### Performance Tests

Benchmarks and performance validation.

```bash
# Run performance tests
pytest tests/test_performance.py --benchmark-only

# Save results to JSON
pytest tests/test_performance.py --benchmark-json=results.json

# Compare with baseline
pytest tests/test_performance.py --benchmark-compare=baseline.json
```

**Metrics tested:**
- API response times
- Concurrent request handling
- Memory usage
- Rate limiter overhead
- Tool execution speed
- WebSocket performance

### Smoke Tests

Quick validation of basic functionality (runs in ~10 seconds).

```bash
# Run smoke test
python smoke_test.py

# Returns: PASS/FAIL with details
```

**What it checks:**
- Package imports
- Configuration loading
- API connectivity
- Basic tool execution

## Running Tests

### Quick Start

```bash
# Install test dependencies
pip install -e ".[dev]"

# Run the offline tier (default for day-to-day development)
pytest tests/ -m "not integration and not slow and not real_api and not performance"

# Run everything except slow tests (note: this still includes the
# integration, real_api, and performance tiers — they hit the live API)
pytest tests/ -m "not slow"

# Run with coverage
pytest tests/ -m "not integration and not slow and not real_api and not performance" --cov=src/polymarket_mcp --cov-report=html
```

### Common Commands

```bash
# Run specific test file (offline suite)
pytest tests/test_trading_offline.py

# Run specific test function (offline suite)
pytest tests/test_trading_offline.py::test_market_order_uses_best_ask_for_buy

# Run with specific markers
pytest -m integration  # Only integration tests (network — hits the live API)
pytest -m "not slow"   # Excludes slow tests; still includes the integration, real_api, and performance tiers — they hit the live API
pytest -m "real_api"   # Only tests requiring API (network — hits the live API)

# Parallel execution (faster)
pytest tests/ -m "not integration and not slow and not real_api and not performance" -n auto

# Stop on first failure
pytest tests/ -m "not integration and not slow and not real_api and not performance" -x

# Show print statements
pytest tests/ -m "not integration and not slow and not real_api and not performance" -s

# Verbose output
pytest tests/ -m "not integration and not slow and not real_api and not performance" -v

# Extra verbose (show test names)
pytest tests/ -m "not integration and not slow and not real_api and not performance" -vv
```

### Test Markers

Available test markers (registered in `pyproject.toml` and `tests/conftest.py`):

```python
@pytest.mark.integration  # Integration test with real API
@pytest.mark.slow         # Test takes >5 seconds
@pytest.mark.real_api     # Requires real API access
@pytest.mark.performance  # Performance benchmark
@pytest.mark.requires_credentials  # Needs a funded wallet (POLYGON_PRIVATE_KEY)
```

Filter tests:

```bash
# Only integration tests
pytest -m integration  # network — hits the live API

# Offline tier (default): excludes all real-API/benchmark tiers
pytest -m "not integration and not slow and not real_api and not performance"

# Exclude slow tests
pytest -m "not slow"  # still includes the integration, real_api, and performance tiers — they hit the live API

# Integration but not slow
pytest -m "integration and not slow"  # network — hits the live API
```

Wallet-dependent tests — modules listed in `CREDENTIAL_ONLY_MODULES` and tests
marked `@pytest.mark.requires_credentials` — are skipped automatically when
`POLYGON_PRIVATE_KEY` and `POLYGON_ADDRESS` are not set (see
`pytest_collection_modifyitems` in `tests/conftest.py`).

### Environment Variables

Set these for testing:

```bash
# Minimum required
export POLYGON_PRIVATE_KEY="0000...0001"
export POLYGON_ADDRESS="0x0000...0001"

# Optional
export POLYMARKET_CHAIN_ID="137"
export POLYMARKET_DEMO_MODE="true"  # For demo mode tests
```

Or use a `.env` file:

```bash
# Copy example
cp .env.example .env

# Edit with your values
# Then tests will load automatically
```

## Writing Tests

### Test Structure

```python
# tests/test_example.py
import pytest

# Mark as integration test
@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_call():
    """Test description."""
    # Arrange
    client = setup_client()

    # Act
    result = await client.get_data()

    # Assert
    assert result is not None
    assert result.status_code == 200
```

### Best Practices

1. **Use descriptive names**
   ```python
   def test_search_markets_returns_valid_data()  # Good
   def test_search()  # Bad
   ```

2. **Test one thing per test**
   ```python
   def test_market_search_success():
       # Only test successful search
       pass

   def test_market_search_invalid_query():
       # Test error handling separately
       pass
   ```

3. **Use fixtures for setup**
   ```python
   @pytest.fixture
   def api_client():
       return create_client()

   def test_with_client(api_client):
       result = api_client.get_data()
       assert result is not None
   ```

4. **Add markers for categorization**
   ```python
   @pytest.mark.integration
   @pytest.mark.slow
   async def test_slow_integration():
       pass
   ```

5. **Pick the right tier: fakes for offline tests, real APIs for integration tests**
   ```python
   # Offline test (default tier) - deterministic fake at the module seam,
   # fail-loud: an unexpected endpoint raises AssertionError instead of
   # falling back to the real network
   class FakeGamma:
       """Synthetic stand-in for market_analysis._fetch_gamma_api."""

       def __init__(self, markets):
           self.markets = markets  # {market_id: payload}
           self.calls = []

       async def __call__(self, endpoint, params=None):
           market_id = endpoint.removeprefix("/markets/")
           if market_id not in self.markets:
               raise AssertionError(f"no synthetic gamma payload for {market_id!r}")
           self.calls.append((endpoint, params))
           return self.markets[market_id]

   async def test_get_market_details(monkeypatch):
       gamma = FakeGamma(markets={"m2": {"question": "Will it pass?"}})
       monkeypatch.setattr(market_analysis, "_fetch_gamma_api", gamma)
       details = await market_analysis.get_market_details(market_id="m2")
       assert details["question"] == "Will it pass?"
       assert gamma.calls == [("/markets/m2", {})]

   # Real-API test - explicitly marked, runs outside the offline selection
   @pytest.mark.integration
   async def test_real_api():
       async with httpx.AsyncClient() as client:
           response = await client.get(
               "https://gamma-api.polymarket.com/markets?limit=1"
           )
           assert response.status_code == 200
   ```

### Async Tests

Use `@pytest.mark.asyncio` for async tests:

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result is not None
```

### Parametrized Tests

Test multiple inputs:

```python
@pytest.mark.parametrize("category,expected", [
    ("Politics", 200),
    ("Sports", 200),
    ("Crypto", 200),
])
async def test_category_filter(category, expected):
    result = await filter_by_category(category)
    assert result.status_code == expected
```

## CI/CD Pipeline

### GitHub Actions Workflows

#### Main Test Workflow

Runs on every push and PR:

```yaml
# .github/workflows/tests.yml
- Smoke test (quick validation)
- Lint (ruff, black, mypy, bandit)
- Unit tests (matrix: Python 3.10-3.12, OS: Ubuntu/Mac/Windows)
- Coverage (with 80% minimum)
- Integration tests (real API)
- E2E tests (complete workflows)
- Performance tests (benchmarks)
- Docker build & test
- Tool verification
```

#### Release Workflow

Runs on version tags:

```yaml
# .github/workflows/release.yml
- Run full test suite
- Build Python package
- Build Docker image
- Generate changelog
- Create GitHub release
- Publish to PyPI
- Update documentation
```

### Pre-commit Hooks

Automatically run before commits:

```bash
# Install
pip install pre-commit
pre-commit install

# Run manually
pre-commit run --all-files

# Skip for quick commits
SKIP=pytest-fast git commit -m "message"
```

Hooks include:
- Code formatting (black, isort)
- Linting (ruff)
- Type checking (mypy)
- Security (bandit, detect-secrets)
- Fast unit tests

## Coverage Reports

### Generate Coverage

```bash
# HTML report
pytest tests/ -m "not integration and not slow and not real_api and not performance" --cov=src/polymarket_mcp --cov-report=html

# Open in browser
open htmlcov/index.html

# Terminal report
pytest tests/ -m "not integration and not slow and not real_api and not performance" --cov=src/polymarket_mcp --cov-report=term-missing

# XML report (for CI)
pytest tests/ -m "not integration and not slow and not real_api and not performance" --cov=src/polymarket_mcp --cov-report=xml
```

### Coverage Requirements

- **Minimum**: 80% overall coverage
- **Target**: 90%+ for core modules
- **CI Enforcement**: Fails if <80%

### Viewing Coverage

After running tests with coverage:

```bash
# HTML report
open htmlcov/index.html

# Shows:
# - Overall coverage percentage
# - Per-file coverage
# - Line-by-line coverage
# - Missing lines highlighted
```

### Coverage Configuration

In `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["src/polymarket_mcp"]
omit = ["*/tests/*", "*/venv/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise NotImplementedError",
]
```

## Performance Benchmarks

### Running Benchmarks

```bash
# Run all benchmarks
pytest tests/test_performance.py --benchmark-only

# Save results
pytest tests/test_performance.py --benchmark-json=results.json

# Compare with baseline
pytest tests/test_performance.py --benchmark-compare=baseline.json

# Auto-save baseline
pytest tests/test_performance.py --benchmark-autosave
```

### Benchmark Metrics

The performance tests track:

1. **API Latency**
   - Market search: Target <500ms
   - Market details: Target <300ms
   - CLOB ping: Target <200ms

2. **Concurrent Performance**
   - 10 concurrent requests
   - Target: 80%+ success rate
   - Throughput: >10 req/s

3. **Memory Usage**
   - Tool execution: <50MB increase
   - Concurrent execution: <100MB increase

4. **Rate Limiter**
   - Overhead: <1ms per check
   - Throughput: >1000 checks/s

5. **Tool Performance**
   - Search: <1s
   - Trending: <1s
   - Filter: <1s

### Benchmark Results

Results are saved to `benchmark.json`:

```json
{
  "benchmarks": [
    {
      "name": "test_market_search_latency",
      "stats": {
        "min": 0.234,
        "max": 0.456,
        "mean": 0.345,
        "stddev": 0.045
      }
    }
  ]
}
```

## Continuous Testing

### Local Development

```bash
# Watch mode - rerun on changes
pytest-watch tests/ -m "not integration and not slow and not real_api and not performance"

# Or use pytest-xdist
pytest tests/ -m "not integration and not slow and not real_api and not performance" -f  # Fail fast mode
```

### Pre-Push Checklist

Before pushing code:

```bash
# 1. Run smoke test
python smoke_test.py

# 2. Run fast tests
pytest tests/ -m "not slow" --maxfail=3  # includes the integration, real_api, and performance tiers — they hit the live API

# 3. Run linting
ruff check src/
black --check src/

# 4. Check coverage
pytest tests/ -m "not integration and not slow and not real_api and not performance" --cov=src/polymarket_mcp --cov-fail-under=80
```

### Daily Testing

Scheduled tests run daily to catch API changes:

```yaml
schedule:
  - cron: '0 2 * * *'  # 2 AM UTC daily
```

## Troubleshooting

### Common Issues

**Tests failing with API errors:**
```bash
# Check API connectivity
curl https://gamma-api.polymarket.com/markets?limit=1

# Check environment variables
echo $POLYGON_PRIVATE_KEY
echo $POLYGON_ADDRESS
```

**Import errors:**
```bash
# Reinstall in development mode
pip install -e .

# Or add to path
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
```

**Slow tests:**
```bash
# Skip slow tests
pytest tests/ -m "not slow"  # still includes the integration, real_api, and performance tiers — they hit the live API

# Or use parallel execution
pytest tests/ -m "not integration and not slow and not real_api and not performance" -n auto
```

**Coverage too low:**
```bash
# See what's missing
pytest tests/ -m "not integration and not slow and not real_api and not performance" --cov=src/polymarket_mcp --cov-report=term-missing

# Focus on specific module
pytest tests/ -m "not integration and not slow and not real_api and not performance" --cov=src/polymarket_mcp/tools
```

### Debug Mode

Run tests with debugging:

```bash
# Show all output
pytest tests/ -m "not integration and not slow and not real_api and not performance" -v -s

# Stop on first failure
pytest tests/ -m "not integration and not slow and not real_api and not performance" -x

# Drop into debugger on failure
pytest tests/ -m "not integration and not slow and not real_api and not performance" --pdb

# Show locals on failure
pytest tests/ -m "not integration and not slow and not real_api and not performance" -l
```

## Resources

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [pytest-benchmark](https://pytest-benchmark.readthedocs.io/)
- [Coverage.py](https://coverage.readthedocs.io/)

## Support

For testing questions:
- Check existing tests in `tests/` directory
- Review CI logs in GitHub Actions
- Open an issue with test failure details
