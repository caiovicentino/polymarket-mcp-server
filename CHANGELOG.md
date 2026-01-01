# Changelog

All notable changes to the Polymarket MCP Server will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] - 2026-07-29

### Breaking Changes

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

### Initial Public Release

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

### Fixed

- **Safety layer hardened**: `validate_order` now requires an explicit
  `BUY`/`SELL` side, over-sell quantities are treated as a short position (not
  silently accepted), and NaN/inf sizes or prices are rejected before reaching
  the exchange (PR #56).
- **`get_orderbook` compatibility with py-clob-client**: the `OrderBookSummary`
  dataclass is converted to a dict and normalized best-first (bids ascending,
  asks descending); `market_analysis.get_orderbook` sorts before slicing to
  `depth`. Previously live book data raised `AttributeError`, and best bid/ask
  read the worst levels of the book (PR #60).
- **Realtime tools reachable via MCP again**: tool routing now awaits
  `realtime.handle_tool_call` (the previously referenced `handle_tool` did not
  exist) and `initialize_server` registers the websocket manager, so all 7
  realtime tools answer through MCP instead of an error envelope (lote PR #53).
- **Credential redaction in startup error logs**: errors surfaced by
  `initialize_server` are sanitized before logging (lote PR #53).
- **Python 3.12 deprecation warnings removed**: `datetime.utcnow()` migrated in
  `market_discovery` and `market_analysis` factories (naive semantics
  preserved) (lote PR #53).
- **Web dashboard XSS hardening**: external data is HTML-escaped before
  interpolation, market actions use event delegation with data attributes,
  confidence values are numerically clamped, and market-id fetch URLs are
  encoded (PR #61).
- **Web dashboard security**: `X-Frame-Options`, `X-Content-Type-Options` and
  `Referrer-Policy` headers added; `POST /api/config` validates fields (NaN and
  out-of-range values rejected) before persisting `.env` (PR #63).
- **`test-docker.sh` reliability**: the script now runs the full suite to its
  summary instead of dying at the first failing test, arithmetic footguns are
  fixed, and a trap cleans up `.env.test` and the test image (PR #64).
- **Makefile backup/restore targets**: both targets resolved a nonexistent
  data-volume name (silently producing empty backups and restoring into the
  wrong volume); they now resolve the volume via `docker compose config` and
  fail loudly when it cannot be determined (PR #69).
- **Kubernetes manifests aligned with the real config**: configmap/secret now
  expose all 22 config variables (5 were unreachable, including
  `POLYMARKET_API_SECRET`), the dead `RATE_LIMIT_ENABLED` key was removed,
  stale version labels dropped, divergent limit values corrected, and the
  README namespace instructions fixed (PR #70).
- **DOCKER.md production deploy**: the documented standalone
  `docker compose -f docker-compose.prod.yml up -d` started with zero config
  variables; the doc now uses the base+override pair and the prod example
  declares `env_file` (PR #72).
- **Installation and setup docs accuracy**: QUICKSTART_GUIDE and
  INSTALLATION_COMPARISON no longer teach `pip install tk` (which installs
  TensorKit, not tkinter) nor the nonexistent `--upgrade-to-full` flag
  (PR #78); WEB_DASHBOARD now documents the loopback-default host and a
  no-auth warning (PR #79); SETUP_GUIDE entry name aligned with the installer
  and author paths removed (PR #80); WEBSOCKET_INTEGRATION testing block uses
  the offline selection plus explicit live commands (PR #81); author paths
  removed from four root docs (PR #82); volatile line/count claims removed
  from DOCKER_INFRASTRUCTURE_COMPLETE and PROJECT_COMPLETE (PR #83).
- **Uninstall reliability**: `uninstall.sh` no longer aborts mid-run with a
  syntax error, and its embedded Python helper receives the config path
  argument, so the `polymarket` entry is removed from the Claude Desktop
  config while other MCP servers are preserved (PR #86).
- **Install safety**: `install.sh` no longer overwrites an existing
  `claude_desktop_config.json` (a Python merge preserves other MCP
  servers), pre-existing `.env` files are backed up before any write and
  restored on rollback, and interactive prompts fail loudly on closed
  stdin instead of dying silently (PR #95).
- **Web dashboard launcher**: `start_web_dashboard.sh` refuses ancient
  Python interpreters up front and installs the package when the
  `polymarket-web` console script is missing, instead of dying with
  `command not found` on fresh checkouts (PR #90).
- **Console entry point**: `polymarket-mcp` now resolves the synchronous
  `run` wrapper instead of the bare async `main`, so the server starts
  instead of exiting silently with a coroutine warning (PR #94).
- **Docker startup template**: the `docker-start.sh` fallback `.env`
  template matches `.env.example` (all 22 variables), address validation
  accepts the template's placeholder, and prompts fail loudly on closed
  stdin instead of killing the script mid-run (PR #98).
- **docker-compose environment**: the compose file declares `env_file`
  (required: false) so all 22 config variables reach the container,
  closing the gap that left `POLYMARKET_API_SECRET` and other settings
  unreachable in Docker deployments (PR #99).
- **Windows CI suite**: target files are read with an explicit UTF-8
  encoding and the Kubernetes suite hardens its reads, unblocking the
  Comprehensive Tests workflow on windows runners (PR #100); the
  architecture/CHANGELOG and Kubernetes manifest targets are ASCII-safe
  so reads without an explicit encoding cannot crash the CI either
  (PR #110).
- **Setup/testing docs claims**: TEST_SUMMARY and TESTING no longer carry
  volatile test, line, or hook counts or unstated live-API assumptions;
  commands follow the canonical offline selection (PR #101).
- **Tick-size aware pricing**: `suggest_order_price` aligns suggested
  prices to the market tick size using Decimal arithmetic from wire
  strings, and `create_limit_order` fails loudly on prices the exchange
  would reject instead of silently crossing the spread (PR #103).
- **Realtime wire compatibility**: CLOB WebSocket handlers parse the
  production frames (event_type discriminator, `book` event, dict levels,
  ms-epoch timestamps, `price_changes` list, array envelopes) so market
  subscriptions deliver data (PR #104).
- **Quickstart non-interactive safety**: `quickstart.sh` reads prompts
  from `/dev/tty` when available and falls back to safe defaults without
  a TTY; the reinstall path never runs `rm -rf` unattended (PR #105).

- **Dashboard market fields**: dashboard cards now read the wire keys the
  Gamma API actually provides, so volume, outcome prices and spread render
  real values instead of $0, N/A and 0% for every market (PR #111).
- **Connection test honesty**: a tool error envelope (200 with ``error``) no
  longer reports "Connection successful"; the dashboard test-connection
  route surfaces the real error (PR #134).
- **Dashboard wiring**: the closing-soon button fetches a real
  ``/api/markets/closing-soon`` route, the category filter sets the query
  before searching, and error envelopes plus HTTP failures are surfaced in
  every panel instead of rendering as empty lists (PR #131).
- **Rate limit backoff (trading)**: 429 responses received by order
  submission, order status and cancellation paths now arm the rate limiter's
  exponential backoff for the right endpoint category (PR #132).
- **Rate limit backoff (portfolio)**: 429 responses received by the CLOB
  read surfaces (positions, P&L, orderbook fallbacks) arm the exponential
  backoff (PR #135).
- **Gamma pagination**: listing markets no longer truncates silently after
  the wire's 100-row cap; follow-up pages are fetched with offset (PR #120).
- **WebSocket dashboard crash**: the dashboard /ws endpoint no longer
  crashes on the first send with a non-JSON-serializable uptime datetime
  (PR #119).
- **Windows install compatibility**: install output uses printf so CRLF
  paths from Windows checkouts no longer corrupt messages (PR #115).
- **Windows docker-test guard**: the executable-bit check of test-docker.sh
  is skipped on MSYS/MINGW/CYGWIN checkouts where the bit is absent by
  design (PR #116).
- **FAQ code samples**: the import example no longer raises NameError under
  ``import *`` and the stale backtesting claim reflects the shipped release
  (PR #133).
- **MCP resources/read fixed**: the AnyUrl == str comparison always failed,
  so every documented resource URI answered "Unknown resource"; reads now
  resolve for all 3 URIs, covered by an end-to-end stdio suite (PR #137).
- **Dashboard configuration UX**: the 422 validation detail renders the
  actual message instead of "[object Object]", and the six range sliders
  are now number inputs that no longer clamp out-of-domain values (PR #138).
- **Tool input validation**: get_orderbook.depth and
  get_market_holders.limit reject 0 and negatives up front
  (minimum: 1), preventing empty-slice reads against the exchange (PR #139).
- **docker-compose defaults**: interpolation fallbacks for
  MAX_TOTAL_EXPOSURE_USD and REQUIRE_CONFIRMATION_ABOVE_USD match the
  server defaults (5000.0 / 500.0) instead of divergent values (PR #141).
- **Rate limit backoff (gamma/CLOB reads)**: 429 responses received by the
  market discovery and market analysis fetchers arm the rate limiter's
  exponential backoff (PR #143).
- **Docs accuracy**: SETUP_GUIDE drops the missing IMPLEMENTATION_SUMMARY
  reference and the stale 45-tool count, AGENT_INTEGRATION_GUIDE fixes the
  POLYGON_CHAIN_ID typo, and DOCKER.md removes the examples/ link (PR #145).
- **Version claims**: four root docs updated from 0.1.0 to 0.2.0 and the
  INSTALLATION_SUMMARY volatile line-count column removed (PR #147).
- **Dashboard market envelopes**: /api/markets/trending and
  /api/markets/search now return the {"markets": [...]} envelope the
  dashboard consumes, so panels render real rows instead of empty (PR #150).
- Rate-limit backoff wired into the order-submission path: a real 429
  from the CLOB now arms the exponential backoff (or the server's
  Retry-After) instead of hammering the API with immediate retries
  (PR #154).
- `suggest_portfolio_actions` paginates the Data-API positions feed
  across all pages instead of truncating at the first page (PR #156).
- Per-market over-sell quantities are counted as short exposure in the
  per-market cap of `validate_order`, so a sell order larger than the
  current position is bounded instead of silently accepted (PR #158).
- Rate-limit backoff wired into the Data-API read surface
  (positions/trades/activity and the pagination helper via opt-in
  kwargs), so a real 429 arms the backoff on read paths too (PR #160).
- The stdio server child process now inherits the OS environment on
  Windows, fixing `WinError 10106` (WSAStartup) that made the whole
  stdio test tier fail on `windows-latest` (PR #162).
- `install.sh` fails loudly with a clear message when the input stream
  ends before the wallet prompts are answered, instead of dying silently
  mid-setup (PR #164).
- The server-provided `Retry-After` hint on a 429 is now clamped to the
  same 60-second ceiling the exponential backoff uses, so an untrusted
  or errant header value can no longer arm an unbounded backoff
  (PR #166).
- `parse_tick_size` now treats non-finite tick sizes ('nan', 'inf') as
  unusable and returns None (the documented no-alignment behavior)
  instead of raising a cryptic `decimal.InvalidOperation` from the
  comparison or accepting an infinite tick that passes the positivity
  check (PR #167).
- The install-script test harness now feeds stdin as bytes and invokes
  bash by absolute path, so the fail-loud EOF guard works again on
  `windows-latest` where text-mode translation turned newlines into
  CR-prefixed input that looped the wallet prompt (PR #168).
- SIGTERM/SIGINT now wake the event loop (`loop.add_signal_handler` plus
  a scheduled shutdown-and-exit task) instead of only setting an event an
  idle kqueue never delivered, so the stdio server runs the graceful
  shutdown and exits promptly on a signal instead of hanging until
  SIGKILL (PR #170).
- The 429-backoff wiring now reaches follow-up pages: all 8
  `fetch_all_pages` call sites (7 in the portfolio tools, 1 in the auth
  client) pass the opt-in `rate_limiter`/`category` kwargs, so a 429 on
  page 2 or later arms the backoff instead of only the first page
  (PR #176).
- **Exception log redaction**: the seven residual log sites in `server.py`
  that interpolated raw exceptions now sanitize hex-bearing secrets through
  the shared redaction helper; messages without secrets stay byte-identical
  (PR #184).
- **Signal-path hardening**: a one-shot scheduling flag guarantees one
  shutdown task per signal (double dispatch scheduled two concurrent exit
  tasks), and the forced-exit helper wraps shutdown in try/finally so a
  raised exception cannot leave the process hanging (PR #192).
- **Dashboard route inventory**: WEB_DASHBOARD and DASHBOARD_SUMMARY now
  list the live `/api/markets/closing-soon` route (it was undocumented), and
  the root route-inventory script covers all 14 registered routes (PR #194).
- **CI documentation claims**: CONTRIBUTING no longer claims the live-API
  jobs are informational when they still gate the run, the stale unit-step
  claim is corrected, and WEB_DASHBOARD drops the last author-path
  reference (PR #196).
- **User-capped tool contracts**: `get_trade_history` and
  `get_activity_log` declare `maximum: 500` on `limit` (matching the wire's
  hard cap on /positions and /activity) and the pagination docstring no
  longer claims /trades is capped at 500 - the endpoint honors limits up to
  10000 (PR #199).
- **Dashboard error surfacing**: the five data routes (trending, search,
  closing-soon, market detail, analysis) propagate tool error envelopes as
  HTTP 500 with a JSON `detail` body instead of raw 200 payloads, so panels
  surface real errors (PR #200).
- **Schema bounds r3**: the tool registry declares the missing bounds - six
  Gamma pagination tools cap each call at `maximum: 1000` rows (derived from
  the module constants), `compare_markets` requires 2-10 markets, and the
  `hours`, `min_value` and `max_actions` parameters gain minimums (PR #203).
- **Batch order schema honesty**: the `create_batch_orders` item schema now
  declares the same `order_type` enum (`GTC`/`GTD`/`FOK`/`FAK`) as
  `create_limit_order`, mirroring the runtime validator that each entry
  already enforces, via a module-level constant shared by both schemas
  (PR #204).
- **Batch item bounds**: the `create_batch_orders` item gains the same
  declarative price/size bounds as the single order (`price` 0.01-0.99,
  `size` minimum 1), derived from the same module-level constants
  (single-source anti-drift) (PR #206).

### Added

- **`py.typed` marker (PEP 561)**: the wheel now ships typing metadata so type
  checkers in consuming projects see the package annotations (PR #73).
- **Production compose file**: `docker-compose.prod.yml` ships with the
  repository, matching the production example documented in DOCKER.md
  (PR #107).
- **`server/discover` MCP method**: connection-agnostic capability discovery
  via a pre-handshake stream interceptor (lote PR #49).

- **Data-API pagination**: ``fetch_all_pages`` follows offset pagination for
  positions/trades/activity so large wallets are no longer silently
  truncated at one page (PR #113).
- **Community directory**: the README links the project in the Awesome Agent
  Trading directory (PR #114).
- **Confirmation flow reference**: TOOLS_REFERENCE documents which tools
  require explicit confirmation (PR #117).
- **Markets closing soon panel**: the dashboard index page fetches
  `/api/markets/closing-soon` and renders the next markets to expire, with
  error envelopes and HTTP failures surfaced (PR #190).

### Changed

- **Pre-commit hook hygiene**: the broken `poetry-check` hook (which required
  a `[tool.poetry]` section this hatchling project never had) was removed and
  root-script lint debt closed (PR #76).
- **Build context hygiene**: `.dockerignore` and `.gitignore` exclude
  dot-prefixed virtual environments and caches (`.venv/`, `.worktrees/`,
  `.mypy_cache/`), shrinking the Docker build context by roughly 2GB
  (PR #106).
- **Pre-commit pytest-fast hook**: the fast hook excludes the performance
  tier so benchmarks no longer hit live APIs on every commit (PR #112).
- **Dependency pins**: ``mcp`` and ``eth-account`` requirements are pinned to
  ranges verified for the trading path (PR #121).
- **Makefile hygiene**: the Makefile derives the package version from the
  source of truth and completes its ``.PHONY`` target list (PR #130).
- **Frozen requirements**: a pinned snapshot of the dev environment is
  committed and the venv pip is upgraded past vulnerable releases (PR #136).
- **Internal 429-note consolidation**: the seven duplicated `_note_*`
  helpers of the 429 backoff wiring now live in
  `utils/rate_limit_note.py` with thin per-module delegates; call sites
  and test behavior are unchanged (PR #173).
- **Root-script lint hygiene**: the five zero-semantic findings in the
  root example scripts (unused imports, dead assignments) are fixed,
  while the remaining 26 findings stay with documented justification
  (F401 probe imports, E722 Ctrl+C handlers, F841 scaffolding)
  (PR #177).
- **CI tier alignment**: the demo and coverage steps run the canonical
  offline selection (live tiers excluded from matrix jobs) and the
  integration/e2e jobs are informational (job-level continue-on-error);
  the merge gate stays on the offline jobs (PR #187).

### Planned Features
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
