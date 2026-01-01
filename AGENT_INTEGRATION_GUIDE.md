# Agent Integration Guide

Quick reference for agents implementing Phases 2-5.

## Base Infrastructure Available

All core infrastructure from Phase 1 is ready:

### Import Statements

```python
# Configuration
from polymarket_mcp.config import load_config, PolymarketConfig

# Authentication & Client
from polymarket_mcp.auth import (
    PolymarketClient,
    create_polymarket_client,
    OrderSigner,
    SignatureType
)

# Rate Limiting
from polymarket_mcp.utils import (
    RateLimiter,
    EndpointCategory,
    get_rate_limiter
)

# Safety Limits
from polymarket_mcp.utils import (
    SafetyLimits,
    OrderRequest,
    Position,
    MarketData,
    create_safety_limits_from_config
)

# MCP Server
from polymarket_mcp.server import server, config, polymarket_client, safety_limits
```

## Accessing Global Instances

The server.py module exports these global instances:

```python
from polymarket_mcp.server import (
    config,              # PolymarketConfig - loaded configuration
    polymarket_client,   # PolymarketClient - authenticated client
    safety_limits        # SafetyLimits - risk management
)
```

## Rate Limiting Pattern

Always wrap API calls with rate limiting:

```python
from polymarket_mcp.utils import get_rate_limiter, EndpointCategory

rate_limiter = get_rate_limiter()

# Before making API call
await rate_limiter.acquire(EndpointCategory.MARKET_DATA)

# Make API call
result = await polymarket_client.get_markets()

# Handle 429 errors
try:
    result = await polymarket_client.get_orderbook(token_id)
except Exception as e:
    if "429" in str(e):
        await rate_limiter.handle_429_error(EndpointCategory.MARKET_DATA)
```

## Safety Validation Pattern

Validate orders before posting:

```python
from polymarket_mcp.utils import OrderRequest

# Create order request
order = OrderRequest(
    token_id="12345",
    price=0.55,
    size=100.0,
    side="BUY",
    market_id="market_xyz"
)

# Get current positions
positions = await polymarket_client.get_positions()

# Get market data
orderbook = await polymarket_client.get_orderbook(order.token_id)
market_data = MarketData(
    market_id=order.market_id,
    token_id=order.token_id,
    best_bid=orderbook["bids"][0]["price"],
    best_ask=orderbook["asks"][0]["price"],
    bid_liquidity=orderbook["bids"][0]["size"] * orderbook["bids"][0]["price"],
    ask_liquidity=orderbook["asks"][0]["size"] * orderbook["asks"][0]["price"],
    total_volume=orderbook.get("volume", 0)
)

# Validate
is_valid, error_msg = safety_limits.validate_order(order, positions, market_data)

if not is_valid:
    return {"error": error_msg}

# Post order
result = await polymarket_client.post_order(
    token_id=order.token_id,
    price=order.price,
    size=order.size,
    side=order.side
)
```

## Registering MCP Tools

Add tools to server.py:

```python
@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Handle tool calls"""

    if name == "your_tool_name":
        # Your tool implementation
        result = await your_tool_function(**arguments)

        return [
            types.TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )
        ]

    # ... other tools
```

Register in list_tools():

```python
@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="your_tool_name",
            description="What your tool does",
            inputSchema={
                "type": "object",
                "properties": {
                    "param1": {
                        "type": "string",
                        "description": "Parameter description"
                    }
                },
                "required": ["param1"]
            }
        ),
        # ... other tools
    ]
```

## Registering MCP Resources

Add resources in resources/ directory and register:

```python
@server.list_resources()
async def list_resources() -> list[types.Resource]:
    resources = [
        # ... existing resources
        types.Resource(
            uri="polymarket://your-resource",
            name="Your Resource Name",
            description="What this resource provides",
            mimeType="application/json"
        )
    ]
    return resources

@server.read_resource()
async def read_resource(uri: str) -> str:
    # ... existing resources

    if uri == "polymarket://your-resource":
        data = await get_your_resource_data()
        return json.dumps(data, indent=2)
```

## Error Handling Pattern

Standard error handling:

```python
import logging

logger = logging.getLogger(__name__)

async def your_function():
    try:
        # API call
        result = await polymarket_client.some_method()
        return {"success": True, "data": result}

    except ValueError as e:
        # Validation error
        logger.warning(f"Validation error: {e}")
        return {"error": str(e), "type": "validation"}

    except RuntimeError as e:
        # Authentication error
        logger.error(f"Auth error: {e}")
        return {"error": str(e), "type": "authentication"}

    except Exception as e:
        # Unexpected error
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {"error": "Internal error", "type": "internal"}
```

## Client Methods Reference

### Market Data
- `get_markets(next_cursor, limit)` - List markets
- `get_market(condition_id)` - Single market
- `get_orderbook(token_id)` - Order book
- `get_price(token_id, side)` - Current price

### Trading
- `post_order(token_id, price, size, side, order_type, expiration)` - Post order
- `cancel_order(order_id)` - Cancel order
- `cancel_all_orders()` - Cancel all

### Account
- `get_orders(market, asset_id)` - Open orders
- `get_positions()` - Positions
- `get_balance()` - USDC balance

### Authentication
- `create_api_credentials()` - Create L2 credentials
- `has_api_credentials()` - Check if credentials exist

## Rate Limit Categories

Use appropriate category for each endpoint:

```python
EndpointCategory.CLOB_GENERAL      # General CLOB endpoints
EndpointCategory.MARKET_DATA       # /book, /price
EndpointCategory.BATCH_OPS         # Batch operations
EndpointCategory.TRADING_BURST     # Trading (burst)
EndpointCategory.TRADING_SUSTAINED # Trading (sustained)
EndpointCategory.GAMMA_API         # Gamma API
EndpointCategory.DATA_API          # Data API
```

## Testing Without Full Server

Test your code independently:

```python
import asyncio
from polymarket_mcp.config import load_config
from polymarket_mcp.auth import create_polymarket_client
from polymarket_mcp.utils import create_safety_limits_from_config

async def test():
    # Load config
    config = load_config()

    # Create client
    client = create_polymarket_client(
        private_key=config.POLYGON_PRIVATE_KEY,
        address=config.POLYGON_ADDRESS,
        chain_id=config.POLYMARKET_CHAIN_ID
    )

    # Test your function
    result = await your_function(client)
    print(result)

if __name__ == "__main__":
    asyncio.run(test())
```

## Constants

```python
# From config
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF_EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
CONDITIONAL_TOKEN_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
POLYMARKET_CHAIN_ID = 137

# Order sides
SIDE_BUY = "BUY"
SIDE_SELL = "SELL"

# Order types
ORDER_TYPE_GTC = "GTC"  # Good Till Cancel
ORDER_TYPE_FOK = "FOK"  # Fill Or Kill
ORDER_TYPE_GTD = "GTD"  # Good Till Date
```

## File Locations

Base: `polymarket-mcp-server/`

Add your files:
- Tools: `src/polymarket_mcp/tools/your_tool.py`
- Resources: `src/polymarket_mcp/resources/your_resource.py`

Import in __init__.py files to make them available.

## Documentation

Document your tools in docstrings:

```python
async def your_tool(param1: str, param2: float) -> dict:
    """
    Brief description of what the tool does.

    Args:
        param1: Description of param1
        param2: Description of param2

    Returns:
        Dictionary with:
        - success: bool indicating success
        - data: Result data
        - error: Error message if failed

    Raises:
        ValueError: If validation fails
        RuntimeError: If API call fails
    """
```

## Phase-Specific Guidelines

### Phase 2: Market Discovery
- Focus on read-only operations
- Use `EndpointCategory.MARKET_DATA` for rate limiting
- Return structured market data
- Include liquidity metrics

### Phase 3: Trading
- Always validate with `SafetyLimits` first
- Check `should_require_confirmation()` for large orders
- Use `EndpointCategory.TRADING_BURST` for rate limiting
- Return order IDs and status

### Phase 4: Position Management
- Calculate PnL accurately
- Track position sizes
- Monitor exposure limits
- Provide summary statistics

### Phase 5: Advanced Resources
- Implement caching for frequently accessed data
- Use WebSockets for real-time updates
- Provide aggregated analytics
- Monitor system health

## Questions?

Refer to:
- `polymarket-mcp-server/README.md` - Full documentation
- `polymarket-mcp-server/.env.example` - Configuration options

All infrastructure is production-ready and tested. Build your phase on top!
