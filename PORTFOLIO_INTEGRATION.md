# Portfolio Tools Integration Guide

This guide explains how to integrate the 8 portfolio management tools into `server.py`.

## Implementation Complete

The portfolio tools are fully implemented in `/src/polymarket_mcp/tools/portfolio.py` with 8 tools:

### Position Tools (4)
1. `get_all_positions` - All user positions with filtering/sorting
2. `get_position_details` - Detailed view of specific position
3. `get_portfolio_value` - Total portfolio value with breakdown
4. `get_pnl_summary` - Profit/loss summary by timeframe

### Activity Tools (2)
5. `get_trade_history` - Historical trades with filters
6. `get_activity_log` - On-chain activity (trades, splits, merges, redeems)

### Analysis Tools (2)
7. `analyze_portfolio_risk` - Risk assessment and metrics
8. `suggest_portfolio_actions` - AI-powered optimization suggestions

## Integration Steps

### Step 1: Import Portfolio Integration

Add this import to `server.py` (line 18, after existing imports):

```python
from .tools.portfolio_integration import get_portfolio_tool_definitions, call_portfolio_tool
```

### Step 2: Update list_tools()

Modify the `list_tools()` function (around line 34) to include portfolio tools:

```python
@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """
    List available tools.

    Returns:
        List of tools:
        - 12 Trading tools (order creation, management, smart trading)
        - 8 Market Discovery tools (search, filter, trending, etc.)
        - 10 Market Analysis tools (price, volume, liquidity, analysis, etc.)
        - 8 Portfolio tools (positions, P&L, risk analysis, suggestions)
    """
    tools = []

    # Add trading tools
    tools.extend(get_tool_definitions())

    # Add market discovery tools
    tools.extend(market_discovery.get_tools())

    # Add market analysis tools
    tools.extend(market_analysis.get_tools())

    # Add portfolio tools
    tools.extend(get_portfolio_tool_definitions())

    return tools
```

### Step 3: Update call_tool()

Modify the `call_tool()` function (around line 155) to handle portfolio tools:

```python
@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> list[types.TextContent]:
    """
    Handle tool calls from Claude.

    Args:
        name: Tool name
        arguments: Tool arguments

    Returns:
        List of TextContent with tool results
    """
    import json

    if not trading_tools:
        raise RuntimeError("Trading tools not initialized")

    try:
        # Portfolio tools
        portfolio_tool_names = [
            'get_all_positions', 'get_position_details', 'get_portfolio_value',
            'get_pnl_summary', 'get_trade_history', 'get_activity_log',
            'analyze_portfolio_risk', 'suggest_portfolio_actions'
        ]

        if name in portfolio_tool_names:
            # Call portfolio tool
            result = await call_portfolio_tool(
                name=name,
                arguments=arguments,
                polymarket_client=polymarket_client,
                rate_limiter=get_rate_limiter(),
                config=config
            )
            return result

        # Trading tools (existing code)
        if name == "create_limit_order":
            result = await trading_tools.create_limit_order(**arguments)
        elif name == "create_market_order":
            result = await trading_tools.create_market_order(**arguments)
        # ... rest of trading tools ...
        else:
            raise ValueError(f"Unknown tool: {name}")

        # Return result as JSON (for trading tools)
        return [
            types.TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )
        ]

    except Exception as e:
        logger.error(f"Tool call failed: {name} - {e}")
        error_result = {
            "success": False,
            "error": str(e),
            "tool": name,
            "arguments": arguments
        }
        return [
            types.TextContent(
                type="text",
                text=json.dumps(error_result, indent=2)
            )
        ]
```

### Step 4: Update initialize_server()

Update the log message in `initialize_server()` (around line 287):

```python
logger.info("Server initialization complete!")
logger.info(f"Ready to trade on chain ID {config.POLYMARKET_CHAIN_ID}")
logger.info("Available tools: 12 Trading, 8 Market Discovery, 10 Market Analysis, 8 Portfolio")
```

## Tool Details

### Tool Arguments

#### get_all_positions
- `include_closed` (bool, default: false)
- `min_value` (number, default: 1.0)
- `sort_by` (enum: "value"|"pnl"|"size", default: "value")

#### get_position_details
- `market_id` (string, required)

#### get_portfolio_value
- `include_breakdown` (bool, default: true)

#### get_pnl_summary
- `timeframe` (enum: "24h"|"7d"|"30d"|"all", default: "all")

#### get_trade_history
- `market_id` (string, optional)
- `start_date` (string ISO, optional)
- `end_date` (string ISO, optional)
- `limit` (number, default: 100)
- `side` (enum: "BUY"|"SELL"|"BOTH", default: "BOTH")

#### get_activity_log
- `activity_type` (enum: "trades"|"splits"|"merges"|"redeems"|"all", default: "all")
- `start_date` (string ISO, optional)
- `end_date` (string ISO, optional)
- `limit` (number, default: 100)

#### analyze_portfolio_risk
- No arguments

#### suggest_portfolio_actions
- `goal` (enum: "balanced"|"aggressive"|"conservative", default: "balanced")
- `max_actions` (number, default: 5)

## Rate Limiting

All portfolio tools use `EndpointCategory.DATA_API` (200 requests per 10 seconds).

Position data is cached for 30 seconds to reduce API calls.

## Error Handling

Tools handle:
- No positions found
- Invalid market IDs
- API errors
- Network timeouts
- Data inconsistencies

## Testing

Run tests with:

```bash
cd polymarket-mcp-server
source venv/bin/activate
# NOTE: this suite is real_api-marked -- it hits REAL Polymarket APIs (L2 credentials required)
pytest tests/test_portfolio_tools.py -m "real_api" -v
```

## Example Usage

From Claude Desktop:

```
Get my positions sorted by P&L:
get_all_positions(sort_by="pnl")

Analyze portfolio risk:
analyze_portfolio_risk()

Get optimization suggestions:
suggest_portfolio_actions(goal="balanced", max_actions=5)
```
