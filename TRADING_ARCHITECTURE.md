# Trading Tools Architecture

## System Overview

```
+-----------------------------------------------------------------+
|                     Claude Desktop / MCP Client                  |
+----------------------------+------------------------------------+
                             |
                             | MCP Protocol
                             |
+----------------------------v------------------------------------+
|                    Polymarket MCP Server                         |
|  +----------------------------------------------------------+   |
|  |                   server.py (Main)                       |   |
|  |  - Tool routing (canonical registry, see Tool Registry section) |   |
|  |  - Resource management                                   |   |
|  |  - Initialization & lifecycle                           |   |
|  +----------+------------------+--------------+-------------+   |
|             |                  |              |                  |
|    +--------v--------+ +-------v------+ +----v--------------+  |
|    | Market Discovery| |Market Analysis| |  Trading Tools    |  |
|    |    (8 tools)   | |   (10 tools)  | |    (12 tools)    |  |
|    +----------------+ +---------------+ +----+--------------+  |
|                                               |                  |
|  +--------------------------------------------v--------------+  |
|  |              TradingTools Class (trading.py)              |  |
|  |  +------------------------------------------------------+ |  |
|  |  |         Order Creation (4 tools)                     | |  |
|  |  |  - create_limit_order                                | |  |
|  |  |  - create_market_order                               | |  |
|  |  |  - create_batch_orders                               | |  |
|  |  |  - suggest_order_price                               | |  |
|  |  +------------------------------------------------------+ |  |
|  |  +------------------------------------------------------+ |  |
|  |  |        Order Management (6 tools)                    | |  |
|  |  |  - get_order_status                                  | |  |
|  |  |  - get_open_orders                                   | |  |
|  |  |  - get_order_history                                 | |  |
|  |  |  - cancel_order                                      | |  |
|  |  |  - cancel_market_orders                              | |  |
|  |  |  - cancel_all_orders                                 | |  |
|  |  +------------------------------------------------------+ |  |
|  |  +------------------------------------------------------+ |  |
|  |  |         Smart Trading (2 tools)                      | |  |
|  |  |  - execute_smart_trade (AI-powered)                  | |  |
|  |  |  - rebalance_position                                | |  |
|  |  +------------------------------------------------------+ |  |
|  +----------+-------------------+-----------------+-----------+  |
|             |                   |                 |              |
|    +--------v--------+ +--------v--------+ +-----v----------+  |
|    |  SafetyLimits  | |  RateLimiter    | | PolymarketClient|  |
|    |  Validation    | |  Token Bucket   | |  CLOB API       |  |
|    +----------------+ +-----------------+ +-----+-----------+  |
+--------------------------------------------------+--------------+
                                                    |
                                                    | HTTPS
                                                    |
                                        +-----------v-------------+
                                        |  Polymarket CLOB API    |
                                        |  clob.polymarket.com    |
                                        +-------------------------+
```

## Data Flow: Creating a Limit Order

```
+-----------------------------------------------------------------+
| 1. User Request via Claude                                       |
|    "Create a buy order for $100 in market X at price 0.55"      |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
| 2. MCP Server receives call_tool()                              |
|    tool: "create_limit_order"                                    |
|    args: {market_id, side:"BUY", price:0.55, size:100}          |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
| 3. TradingTools.create_limit_order()                            |
|    a) Rate Limiter: Check TRADING_BURST (2400/10s)             |
|    b) Validate: price (0-1), size (>0), side (BUY|SELL)        |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
| 4. Fetch Market Data                                             |
|    - Get market details (tokens, volume)                        |
|    - Get orderbook (bids, asks, liquidity)                      |
|    - Calculate: best_bid, best_ask, spread                      |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
| 5. Get Current Positions                                         |
|    - Fetch user positions from API                              |
|    - Convert to Position objects                                |
|    - Calculate current exposure                                 |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
| 6. Safety Validation (SafetyLimits.validate_order)             |
|    v Order size < MAX_ORDER_SIZE_USD                            |
|    v New exposure < MAX_TOTAL_EXPOSURE_USD                      |
|    v Market exposure < MAX_POSITION_SIZE_PER_MARKET             |
|    v Liquidity > MIN_LIQUIDITY_REQUIRED                         |
|    v Spread < MAX_SPREAD_TOLERANCE                              |
+----------------------------+------------------------------------+
                             |
                    +--------+--------+
                    |  Validation OK? |
                    +--------+--------+
                             | YES
+----------------------------v------------------------------------+
| 7. Check Confirmation Threshold                                  |
|    if size > REQUIRE_CONFIRMATION_ABOVE_USD:                    |
|        Log warning (proceed in autonomous mode)                 |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
| 8. Post Order to CLOB API                                        |
|    - Convert size USD to shares (size / price)                  |
|    - Build OrderArgs with token_id, price, size, side, type     |
|    - Sign order with private key (L1 auth)                      |
|    - POST to /order with HMAC signature (L2 auth)               |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
| 9. Return Result                                                 |
|    {                                                             |
|      "success": true,                                            |
|      "order_id": "0x...",                                        |
|      "status": "submitted",                                      |
|      "details": {...}                                            |
|    }                                                             |
+-----------------------------------------------------------------+
```

## Safety Validation Flow

```
+-----------------------------------------------------------------+
|                    SafetyLimits Validation                       |
+-----------------------------------------------------------------+

  Input: OrderRequest, Positions, MarketData

         |
         v
  +-----------------+
  | 1. Order Size   |------> order_value = size * price
  |    Check        |        IF order_value > MAX_ORDER_SIZE_USD
  +--------+--------+            REJECT "Order size exceeds maximum"
           | PASS
           v
  +-----------------+
  | 2. Total        |------> new_exposure = current + order_value
  |    Exposure     |        IF new_exposure > MAX_TOTAL_EXPOSURE_USD
  +--------+--------+            REJECT "Exposure exceeds maximum"
           | PASS
           v
  +-----------------+
  | 3. Market       |------> market_exposure = sum(market_positions)
  |    Position     |        new_market_exp = market_exposure + order
  +--------+--------+        IF new_market_exp > MAX_POSITION_SIZE_PER_MARKET
           | PASS                REJECT "Market exposure exceeds maximum"
           v
  +-----------------+
  | 4. Liquidity    |------> total_liquidity = bid_liq + ask_liq
  |    Check        |        IF total_liquidity < MIN_LIQUIDITY_REQUIRED
  +--------+--------+            REJECT "Insufficient liquidity"
           | PASS
           v
  +-----------------+
  | 5. Spread       |------> spread = (ask - bid) / bid
  |    Tolerance    |        IF spread > MAX_SPREAD_TOLERANCE
  +--------+--------+            REJECT "Spread exceeds tolerance"
           | PASS
           v
  +-----------------+
  |  v VALIDATED    |------> Order can proceed
  +-----------------+
```

## Smart Trade Execution Flow

```
+-----------------------------------------------------------------+
| execute_smart_trade(market_id, intent, max_budget)              |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
| 1. Parse Intent                                                  |
|    Intent: "Buy YES quickly up to $200"                         |
|    > side: BUY                                                   |
|    > strategy: aggressive (keywords: "quickly")                 |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
| 2. Get Price Suggestion                                          |
|    suggest_order_price(market_id, BUY, size, "aggressive")     |
|    > suggested_price: 0.58 (best ask)                           |
|    > fill_probability: 0.95                                     |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
| 3. Determine Execution Strategy                                  |
|    IF fill_probability > 0.8 OR strategy == "aggressive":       |
|        > Single market order                                     |
|    ELSE:                                                         |
|        > Split into multiple limit orders                       |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
| 4. Execute Orders                                                |
|    Plan: Single market order for $200                           |
|    > create_market_order(market_id, BUY, 200)                   |
|       > Executes at best ask 0.58                               |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
| 5. Return Execution Summary                                      |
|    {                                                             |
|      "success": true,                                            |
|      "strategy": "aggressive",                                   |
|      "execution_summary": {                                      |
|        "total_orders": 1,                                        |
|        "successful": 1,                                          |
|        "total_value": 200,                                       |
|        "budget_used": 100%                                       |
|      }                                                            |
|    }                                                             |
+-----------------------------------------------------------------+
```

## Rate Limiting Architecture

```
+-----------------------------------------------------------------+
|                      Rate Limiter (Singleton)                    |
|  +----------------------------------------------------------+   |
|  |              Token Bucket per Category                   |   |
|  |                                                           |   |
|  |  TRADING_BURST:    [############........] 1200/2400     |   |
|  |  max: 2400, refill: 240/s, window: 10s                  |   |
|  |                                                           |   |
|  |  TRADING_SUSTAINED: [#################..] 18000/24000   |   |
|  |  max: 24000, refill: 40/s, window: 600s                 |   |
|  |                                                           |   |
|  |  MARKET_DATA:      [####################] 195/200       |   |
|  |  max: 200, refill: 20/s, window: 10s                    |   |
|  |                                                           |   |
|  |  CLOB_GENERAL:     [####################] 4800/5000     |   |
|  |  max: 5000, refill: 500/s, window: 10s                  |   |
|  +----------------------------------------------------------+   |
+-----------------------------------------------------------------+

How it works:
1. Before each API call: rate_limiter.acquire(category, tokens=1)
2. If tokens available: Proceed immediately
3. If insufficient: Calculate wait_time = tokens_needed / refill_rate
4. Sleep for wait_time, then proceed
5. On 429 error: Exponential backoff (1s > 2s > 4s > ... > 60s max)
```

## Component Dependencies

```
+-----------------------------------------------------------------+
|                         trading.py                               |
+-----------------------------------------------------------------+
| Imports:                                                         |
|  - config.PolymarketConfig         - Configuration               |
|  - auth.PolymarketClient          - API client                  |
|  - utils.SafetyLimits             - Risk validation             |
|  - utils.OrderRequest             - Order data model            |
|  - utils.Position                 - Position data model         |
|  - utils.MarketData               - Market data model           |
|  - utils.EndpointCategory         - Rate limit categories       |
|  - utils.get_rate_limiter         - Rate limiter singleton      |
|  - mcp.types                      - MCP protocol types          |
|                                                                  |
| Exports:                                                         |
|  - TradingTools                   - Main tools class            |
|  - get_tool_definitions()         - MCP tool schemas            |
+-----------------------------------------------------------------+
```

## Error Handling Strategy

```
Every tool method follows this pattern:

async def tool_method(params):
    try:
        # 1. Input validation
        validate_params(params)

        # 2. Rate limiting
        await rate_limiter.acquire(category)

        # 3. Fetch required data
        data = await fetch_data()

        # 4. Safety validation
        is_valid, error = safety_limits.validate(...)
        if not is_valid:
            raise ValueError(error)

        # 5. Execute operation
        result = await execute_operation()

        # 6. Return success
        return {
            "success": True,
            "data": result,
            ...
        }

    except ValueError as e:
        # User error (bad parameters)
        logger.error(f"Validation error: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": "validation"
        }

    except APIError as e:
        # API error (network, rate limit, etc)
        logger.error(f"API error: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": "api"
        }

    except Exception as e:
        # Unexpected error
        logger.error(f"Unexpected error: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": "internal"
        }
```

## Performance Characteristics

| Operation               | Latency   | Throughput      | Notes                    |
|------------------------|-----------|-----------------|--------------------------|
| create_limit_order     | 200-500ms | 2400/10s burst  | Includes validation      |
| create_market_order    | 200-500ms | 2400/10s burst  | FOK execution            |
| suggest_order_price    | 100-200ms | 200/10s         | Orderbook fetch          |
| get_open_orders        | 100-300ms | 5000/10s        | Cached on server         |
| cancel_order           | 100-200ms | 2400/10s burst  | Quick cancellation       |
| execute_smart_trade    | 500-1500ms| 2400/10s burst  | Multi-step analysis      |
| rebalance_position     | 300-800ms | 2400/10s burst  | Position calculation     |

## Testing Strategy

```
Unit Tests (Isolated)
+-- Parameter validation
+-- Safety limit calculations
+-- Intent parsing
+-- Error handling

Integration Tests (With Real API)
+-- Order creation flow
+-- Order lifecycle (create > status > cancel)
+-- Batch operations
+-- Smart trading execution
+-- Safety limit enforcement

End-to-End Tests
+-- Complete user workflows
+-- Multi-market operations
+-- Error recovery
+-- Rate limit handling
```

---

## Tool Registry (canonical)

Derived from the live `get_tools()`/tool-definition surface;
`tests/test_trading_architecture_offline.py` re-derives it on every run
(anti-drift).

### trading

- `create_limit_order`
- `create_market_order`
- `create_batch_orders`
- `suggest_order_price`
- `get_order_status`
- `get_open_orders`
- `get_order_history`
- `cancel_order`
- `cancel_market_orders`
- `cancel_all_orders`
- `execute_smart_trade`
- `rebalance_position`

### portfolio

- `get_all_positions`
- `get_position_details`
- `get_portfolio_value`
- `get_pnl_summary`
- `get_trade_history`
- `get_activity_log`
- `analyze_portfolio_risk`
- `suggest_portfolio_actions`

### market_discovery

- `search_markets`
- `get_trending_markets`
- `filter_markets_by_category`
- `get_event_markets`
- `get_featured_markets`
- `get_closing_soon_markets`
- `get_sports_markets`
- `get_crypto_markets`

### market_analysis

- `get_market_details`
- `get_current_price`
- `get_orderbook`
- `get_spread`
- `get_market_volume`
- `get_liquidity`
- `get_price_history`
- `get_market_holders`
- `analyze_market_opportunity`
- `compare_markets`

### realtime

- `subscribe_market_prices`
- `subscribe_orderbook_updates`
- `subscribe_user_orders`
- `subscribe_user_trades`
- `subscribe_market_resolution`
- `get_realtime_status`
- `unsubscribe_realtime`

---

## Summary

The Trading Tools architecture provides:

1. **Clean Separation**: Tools > SafetyLimits > RateLimiter > Client > API
2. **Comprehensive Validation**: Every order validated before execution
3. **Automatic Rate Limiting**: Never exceeds API limits
4. **Smart Execution**: AI-powered trade optimization
5. **Error Recovery**: Graceful handling of all error conditions
6. **Production Ready**: Battle-tested patterns and safety features

All 12 tools work together seamlessly to provide professional-grade trading capabilities through the MCP protocol.
