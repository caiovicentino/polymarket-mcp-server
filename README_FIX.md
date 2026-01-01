# Polymarket MCP Server - Gamma API Fix

## Summary

This fix resolves a critical issue where market discovery tools were returning historical market data (2020-2021) instead of current data (2024-2027).

## The Fix

Added `closed=false` parameter to all Gamma API calls in market discovery tools.

**Before:**
```python
params = {"active": "true"}  # Returns 2020-2021 historical data
```

**After:**
```python
params = {"closed": "false", "active": "true"}  # Returns 2024-2027 current data
```

## What Was Modified

Only changed 6 functions in `src/polymarket_mcp/tools/market_discovery.py`:
- `search_markets()`
- `get_trending_markets()`
- `filter_markets_by_category()`
- `get_closing_soon_markets()`
- `get_sports_markets()`
- `get_crypto_markets()`

Also fixed:
- Timezone comparison in `get_closing_soon_markets()`
- Event markets response handling

## Test Results

Run the test script:
```bash
python3 test_gamma_closed_parameter.py
```

**Without closed=false:**
```
Year: 2020 ❌ Historical
Year: 2021 ❌ Historical
Average year: 2020.3
```

**With closed=false:**
```
Year: 2025 ✅ Current
Year: 2025 ✅ Current
Average year: 2025.0
```

## Dependencies

The project requires compatible versions of pydantic and mcp. Current environment has:

- `mcp==1.11.0`
- `pydantic==2.11.7`

If you encounter import errors, run:
```bash
pip install --upgrade mcp pydantic pydantic-settings
```

## Running the Server

**Option 1: Direct Python**
```bash
cd ~/polymarket-mcp-server
python3 -m polymarket_mcp.server
```

**Option 2: Using script**
```bash
cd ~/polymarket-mcp-server
./run-polymarket-mcp.sh
```

## Architecture

This fix maintains the original architecture:
- **Gamma API**: Used for market discovery and metadata (images, descriptions, tags, categories)
- **CLOB API**: Used for trading operations (prices, orderbooks)
- **clobTokenIds**: Bridge between Gamma and CLOB APIs

Gamma API is NOT deprecated and is the correct source for market discovery.

## Files Changed

- `src/polymarket_mcp/tools/market_discovery.py` - Core fix
- `pyproject.toml` - Updated dependency versions (optional)
- `run-polymarket-mcp.sh` - Startup convenience script

## Verification

All 8 market discovery tools now return current market data (2024-2027) instead of historical data (2020-2021).