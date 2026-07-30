# Changelog

All notable changes to the Polymarket MCP Server will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] - 2026-07-29

### ⚠️ Breaking Changes

- **`ENABLE_AUTONOMOUS_TRADING` now defaults to `false`.** Every order requires
  `confirm=true` unless you opt in. Previously it defaulted to `true` and, with
  the confirmation gate broken (below), a fresh install would place any order an
  agent asked for, bounded only by `MAX_ORDER_SIZE_USD`.
- **Orders needing confirmation are no longer placed automatically.** They come
  back as `status="confirmation_required"` with the resolved outcome and token;
  re-issue with `confirm=true` to place them.
- **`POLYMARKET_API_SECRET` is a new, separate setting.** The secret and the
  passphrase are distinct values issued by Polymarket; reusing the passphrase for
  both breaks request signing. Configs without it still load, with a warning.
- **Non-Yes/No markets now require an explicit `outcome`.** Sports and
  multi-outcome markets no longer silently default to the first token.

### Fixed

- Pinned `mcp<2.0.0`. SDK 2.0.0 removed the decorator API on `Server`, so
  `pip install` resolved to a version where the server could not even import.
- Outcome tokens are selected by their `outcome` label instead of `tokens[0]`,
  so an order on NO no longer trades the YES token (#14).
- Portfolio tools received `SafetyLimits` where a `RateLimiter` was expected and
  crashed on first use (#12).
- The WebSocket message loop is now started after connecting, so real-time
  subscriptions actually deliver events (#13).
- The CLOB WebSocket URL was missing its channel suffix and returned HTTP 404;
  it is now `/ws/market`.
- Connection checks used the `.closed` property that `websockets` 14 removed.
- The confirmation gate logged and then placed the order anyway.
- Each WebSocket channel now has its own reader. The loop previously awaited
  both with `FIRST_COMPLETED` and cancelled the loser every iteration, which
  starved the quieter channel and discarded whatever the cancelled `recv()` had
  already taken off the wire (#13).
- `execute_smart_trade` reported `success: true` even when every nested order
  was withheld for confirmation, and `create_batch_orders` counted a withheld
  order as failed.

### Security

- **The web dashboard now binds to `127.0.0.1`** instead of `0.0.0.0`. It has no
  authentication and `POST /api/config` rewrites the trading safety limits, so
  listening on every interface let anyone able to reach the port raise the order
  caps of a server holding a funded wallet. Override with `WEB_HOST` only on a
  trusted network.
- Added `SECURITY.md` with private vulnerability reporting and operator guidance.

### Changed

- The version now lives only in `src/polymarket_mcp/__init__.py`; packaging,
  the server, the dashboard and the Docker label all read from it.
- GitHub Actions updated (up to three majors behind, Node 20 deprecation) and
  Python 3.13 added to the test matrix.
- Repaired the test suite: collection had been aborting on a syntax error, and
  the nightly run had been failing for months.
- Fixed the CI itself, which had never fully run: the Windows legs used bash
  line continuations under PowerShell, `release.yml` was invalid since June
  (the `secrets` context is not available in `if`), the Docker job died at
  login when no registry credentials are configured, and the ruff rule set was
  unpinned so it drifted with each release.

## [0.1.0] - 2025-01-10

### 🎉 Initial Public Release

The first public release of Polymarket MCP Server - a complete AI-powered trading platform for Polymarket prediction markets.

### Added

#### Core Infrastructure
- Model Context Protocol (MCP) server implementation
- L1 authentication (Polygon wallet + EIP-712 signing)
- L2 authentication (API key + HMAC signatures)
- Auto-creation of API credentials
- Advanced token bucket rate limiter respecting all Polymarket API limits
- Configurable safety limits and risk management system
- Comprehensive error handling and logging

#### Market Discovery Tools (8 tools)
- `search_markets` - Search markets by keywords, slug, or filters
- `get_trending_markets` - Get markets with highest volume
- `filter_markets_by_category` - Filter by tags and categories
- `get_event_markets` - Get all markets for a specific event
- `get_featured_markets` - Get featured/promoted markets
- `get_closing_soon_markets` - Get markets closing within timeframe
- `get_sports_markets` - Get sports betting markets
- `get_crypto_markets` - Get cryptocurrency prediction markets

#### Market Analysis Tools (10 tools)
- `get_market_details` - Complete market information
- `get_current_price` - Current bid/ask prices
- `get_orderbook` - Full orderbook with depth
- `get_spread` - Calculate current spread
- `get_market_volume` - Volume statistics (24h, 7d, 30d)
- `get_liquidity` - Available liquidity in USD
- `get_price_history` - Historical price data
- `get_market_holders` - Top position holders
- `analyze_market_opportunity` - AI-powered analysis with recommendations
- `compare_markets` - Compare multiple markets side-by-side

#### Trading Tools (12 tools)
- `create_limit_order` - Create limit orders (GTC/GTD/FOK/FAK)
- `create_market_order` - Execute market orders
- `create_batch_orders` - Submit multiple orders efficiently
- `suggest_order_price` - AI-suggested optimal pricing
- `get_order_status` - Check specific order status
- `get_open_orders` - List all active orders
- `get_order_history` - Historical order data
- `cancel_order` - Cancel specific order
- `cancel_market_orders` - Cancel all orders in a market
- `cancel_all_orders` - Emergency cancel all orders
- `execute_smart_trade` - Natural language trading with intent parsing
- `rebalance_position` - Auto-adjust position to target size

#### Portfolio Management Tools (8 tools)
- `get_all_positions` - All user positions with filters
- `get_position_details` - Detailed position view
- `get_portfolio_value` - Total portfolio value calculation
- `get_pnl_summary` - Profit/loss overview
- `get_trade_history` - Historical trades with filters
- `get_activity_log` - On-chain activity tracking
- `analyze_portfolio_risk` - Risk assessment and scoring
- `suggest_portfolio_actions` - AI-powered optimization suggestions

#### Real-time Monitoring Tools (7 tools)
- `subscribe_market_prices` - Monitor price changes via WebSocket
- `subscribe_orderbook_updates` - Real-time orderbook updates
- `subscribe_user_orders` - User order status monitoring
- `subscribe_user_trades` - User trade execution alerts
- `subscribe_market_resolution` - Market resolution notifications
- `get_realtime_status` - WebSocket subscription status
- `unsubscribe_realtime` - Remove subscriptions

#### Safety & Risk Management
- Configurable order size limits
- Total portfolio exposure caps
- Per-market position limits
- Liquidity requirement validation
- Spread tolerance checks
- Confirmation thresholds for large orders
- Pre-trade safety validation

#### Infrastructure Features
- WebSocket manager with auto-reconnect
- Dual WebSocket connections (CLOB + Real-time)
- Token bucket rate limiting (all endpoint categories)
- HMAC authentication for WebSockets
- Event routing and notification system
- Subscription tracking and statistics

#### Testing
- Comprehensive test suite (1,900+ lines)
- Real API integration (NO MOCKS)
- Unit tests for all tools
- Integration tests for workflows
- Test runners and examples

#### Documentation
- Complete README with setup instructions
- Detailed SETUP_GUIDE.md
- Tools Reference (TOOLS_REFERENCE.md)
- Agent Integration Guide
- Trading Architecture documentation
- WebSocket Integration guide
- Usage examples and code samples
- CONTRIBUTING guidelines

### Technical Specifications

- **Python**: 3.10+
- **Total Lines of Code**: ~10,000+
- **Tools**: 45 comprehensive tools
- **API Integration**: CLOB API, Gamma API, Data API, WebSocket
- **Authentication**: L1 (EIP-712) + L2 (HMAC)
- **Rate Limiting**: Token bucket with exponential backoff
- **Dependencies**: MCP SDK, py-clob-client, websockets, eth-account, httpx, pydantic

### Credits

- **Created by**: Caio Vicentino
- **Communities**: Yield Hacker, Renda Cripto, Cultura Builder
- **Powered by**: Claude Code (Anthropic)

---

## [Unreleased]

### Planned Features
- CI/CD pipeline (GitHub Actions)
- Enhanced AI analysis tools
- Portfolio strategy templates
- Market alerts and notifications
- Performance analytics dashboard
- Multi-wallet support
- Advanced order types (trailing stop, OCO)
- Historical backtesting framework

---

## Release Notes Template

For future releases, use this template:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- New features

### Changed
- Changes to existing features

### Deprecated
- Features that will be removed

### Removed
- Removed features

### Fixed
- Bug fixes

### Security
- Security improvements
```

---

<div align="center">

**Maintained by Caio Vicentino and the Polymarket MCP community**

</div>
