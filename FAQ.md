# ❓ Frequently Asked Questions (FAQ)

Complete answers to common questions about Polymarket MCP Server.

---

## 📑 Table of Contents

- [General Questions](#general-questions)
- [Installation & Setup](#installation--setup)
- [Wallet & Security](#wallet--security)
- [Configuration](#configuration)
- [Trading](#trading)
- [Errors & Troubleshooting](#errors--troubleshooting)
- [Safety & Risk Management](#safety--risk-management)
- [Performance](#performance)
- [Advanced Usage](#advanced-usage)
- [Contributing](#contributing)

---

## General Questions

### Q: What is Polymarket MCP Server?

A: Polymarket MCP Server is an integration that enables Claude (Anthropic's AI assistant) to autonomously trade, analyze, and manage positions on Polymarket prediction markets. It provides 45 comprehensive tools across market discovery, analysis, trading, portfolio management, and real-time monitoring.

---

### Q: What can I do with this server?

A: You can:
- Discover and search prediction markets
- Analyze market data, prices, and orderbooks
- Execute trades (limit orders, market orders)
- Manage your portfolio and track P&L
- Monitor markets in real-time via WebSocket
- Get AI-powered trading recommendations
- Set safety limits and risk management rules

---

### Q: Do I need to know how to code?

A: No! While the server is written in Python, you can use it entirely through natural language conversations with Claude Desktop. The GUI setup wizard makes installation point-and-click simple.

---

### Q: Is this safe to use?

A: The server includes enterprise-grade safety features:
- Configurable order size limits
- Total exposure caps
- Per-market position limits
- Liquidity validation
- Spread tolerance checks
- User confirmation for large orders

However, trading always carries risk. Only trade what you can afford to lose.

---

### Q: How much does it cost?

A: The server is 100% free and open source (MIT License). You only pay:
- Gas fees on Polygon (minimal, ~$0.01 per transaction)
- Trading fees to Polymarket (typically 2% on profits)

---

### Q: What's the difference between Demo Mode and Full Mode?

A:

**Demo Mode:**
- Read-only access
- Market discovery and analysis
- No wallet required
- Cannot place trades
- Perfect for learning

**Full Mode:**
- Complete functionality
- Requires Polygon wallet
- Can place real trades
- Full portfolio management
- For active traders

---

## Installation & Setup

### Q: What are the system requirements?

A: Minimum requirements:
- Python 3.10 or higher
- 2GB RAM
- 500MB disk space
- macOS, Windows 10+, or Linux
- Internet connection
- Claude Desktop (for GUI integration)

---

### Q: Which installation method should I use?

A: Recommendations:

- **Beginners**: Use the GUI Setup Wizard (`python setup_wizard.py`)
- **Terminal users**: Use the automated script (`./install.sh`)
- **Docker users**: Use Docker Compose (`docker-compose up`)
- **Advanced users**: Manual installation for customization

See [VISUAL_INSTALL_GUIDE.md](VISUAL_INSTALL_GUIDE.md) for detailed instructions.

---

### Q: How long does installation take?

A:
- GUI Wizard: ~5 minutes
- Automated Script: ~3 minutes
- Docker: ~2 minutes
- Manual: ~10 minutes

---

### Q: Do I need to install anything on Claude Desktop?

A: No separate installation needed on Claude Desktop. You just need to:
1. Edit the Claude Desktop config file
2. Add the MCP server configuration
3. Restart Claude Desktop

The setup wizard can do this automatically for you.

---

### Q: Where is the Claude Desktop config file?

A:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

---

### Q: Can I use this without Claude Desktop?

A: The server is designed for Claude Desktop integration, but you can use the underlying Python tools programmatically. See [TOOLS_REFERENCE.md](TOOLS_REFERENCE.md) for the API documentation.

---

## Wallet & Security

### Q: How do I get a Polygon wallet?

A: Options:

1. **MetaMask** (recommended):
   - Install from https://metamask.io
   - Create new wallet or import existing
   - Switch to Polygon network

2. **Other wallets**:
   - Trust Wallet
   - Coinbase Wallet
   - Rainbow Wallet

See the "Wallet Setup Guide" section in [VISUAL_INSTALL_GUIDE.md](VISUAL_INSTALL_GUIDE.md).

---

### Q: Is my private key safe?

A: Security measures:

**What we do:**
- Store keys only in `.env` file (never uploaded)
- `.env` is in `.gitignore` (never committed to Git)
- Keys are masked in logs and error messages
- No keys sent to external services (only to Polymarket)

**What you should do:**
- Never share your private key
- Never commit `.env` to version control
- Use a dedicated wallet with limited funds
- Consider hardware wallet for large amounts
- Regular security audits of your setup

---

### Q: What if I lose my private key?

A: If you lose your private key:
1. You cannot access funds in that wallet
2. Create a new wallet
3. Transfer remaining funds (if you can access old wallet)
4. Update `.env` with new credentials
5. Restart MCP server

**Prevention**: Back up your seed phrase securely offline.

---

### Q: How do I get USDC on Polygon?

A: Methods:

1. **Bridge from Ethereum**:
   - Use Polygon Bridge (bridge.polygon.technology)
   - Takes ~7 minutes
   - Costs Ethereum gas fees

2. **Buy on exchange**:
   - Binance, Coinbase, Kraken
   - Withdraw directly to Polygon network
   - Usually cheapest method

3. **Fiat on-ramp**:
   - Use Transak, Moonpay, or Ramp
   - Buy USDC with credit card
   - Slightly higher fees

4. **Swap on Polygon**:
   - Already have other tokens on Polygon?
   - Use Uniswap or QuickSwap
   - Swap for USDC

---

### Q: Can I use a hardware wallet?

A: Not directly. Hardware wallets don't export private keys. Workarounds:

1. **Recommended**: Use a dedicated software wallet for trading
2. **Advanced**: Use hardware wallet for storage, software wallet for active trading
3. **Manual**: Sign transactions with hardware wallet and broadcast separately (complex)

---

## Configuration

### Q: Where do I put my configuration?

A: Two places:

1. **`.env` file** in project root:
   ```env
   POLYGON_PRIVATE_KEY=abc123...
   POLYGON_ADDRESS=0x123...
   MAX_ORDER_SIZE_USD=1000
   ```

2. **Claude Desktop config** file:
   ```json
   {
     "mcpServers": {
       "polymarket": {
         "env": {
           "POLYGON_PRIVATE_KEY": "abc123...",
           "POLYGON_ADDRESS": "0x123..."
         }
       }
     }
   }
   ```

The setup wizard creates both automatically.

---

### Q: What are recommended safety limits?

A: Depends on your risk tolerance:

**Conservative** (beginners):
```env
MAX_ORDER_SIZE_USD=500
MAX_TOTAL_EXPOSURE_USD=2000
MAX_POSITION_SIZE_PER_MARKET=1000
REQUIRE_CONFIRMATION_ABOVE_USD=100
```

**Moderate** (intermediate):
```env
MAX_ORDER_SIZE_USD=1000
MAX_TOTAL_EXPOSURE_USD=5000
MAX_POSITION_SIZE_PER_MARKET=2000
REQUIRE_CONFIRMATION_ABOVE_USD=500
```

**Aggressive** (experienced):
```env
MAX_ORDER_SIZE_USD=5000
MAX_TOTAL_EXPOSURE_USD=20000
MAX_POSITION_SIZE_PER_MARKET=10000
REQUIRE_CONFIRMATION_ABOVE_USD=2000
```

---

### Q: Can I change configuration without reinstalling?

A: Yes! Just:
1. Edit `.env` file
2. Restart Claude Desktop
3. Changes apply immediately

For Claude config changes, also edit `claude_desktop_config.json`.

---

### Q: What does each configuration option do?

A: Key options:

- `MAX_ORDER_SIZE_USD`: Maximum dollars per single order
- `MAX_TOTAL_EXPOSURE_USD`: Maximum total value across all positions
- `MAX_POSITION_SIZE_PER_MARKET`: Maximum dollars in one market
- `MIN_LIQUIDITY_REQUIRED`: Minimum market liquidity to trade
- `MAX_SPREAD_TOLERANCE`: Maximum bid-ask spread (0.05 = 5%)
- `REQUIRE_CONFIRMATION_ABOVE_USD`: Ask before orders over this amount
- `ENABLE_AUTONOMOUS_TRADING`: Allow trading without confirmation

See [config.py](src/polymarket_mcp/config.py) for complete list.

---

## Trading

### Q: How do I place my first trade?

A: In Claude Desktop, try:

```
"Buy $50 of YES tokens in [market_id] at $0.65"
```

The server will:
1. Validate your request
2. Check safety limits
3. Calculate optimal order parameters
4. Ask for confirmation (if above threshold)
5. Execute the trade
6. Return order ID and status

---

### Q: What types of orders can I place?

A: Supported order types:

1. **Market Orders**: Immediate execution at current price
2. **Limit Orders**: Execute only at specified price or better
   - GTC (Good-Til-Cancelled)
   - GTD (Good-Til-Date)
   - FOK (Fill-Or-Kill)
   - FAK (Fill-And-Kill)

---

### Q: How do I cancel an order?

A: Ask Claude:

```
"Cancel order [order_id]"
"Cancel all my open orders in [market_id]"
"Cancel all my open orders"
```

---

### Q: Can I see my open orders?

A: Yes:

```
"Show me all my open orders"
"Show my open orders in [market_id]"
```

---

### Q: How do I check my positions?

A:

```
"Show me all my current positions"
"What's my position in [market_id]?"
"What's my total portfolio value?"
```

---

### Q: What's the minimum trade size?

A: Polymarket's minimum is typically:
- $0.10 per order
- Must be economically viable (cover gas fees)

Recommended minimum: $10 to make fees worthwhile.

---

### Q: How long do trades take?

A:
- **Market orders**: ~2-10 seconds
- **Limit orders**: Instant placement, filled when price reached
- Polygon transactions: ~2-3 second confirmation

---

### Q: Do I pay gas fees?

A: Yes, but minimal:
- Polygon gas fees: ~$0.001-0.01 per transaction
- Much cheaper than Ethereum
- Paid in MATIC (server handles this)

---

## Errors & Troubleshooting

### Q: Error: "ModuleNotFoundError: No module named 'polymarket_mcp'"

A: Solution:
```bash
# Make sure you installed the package
pip install -e .

# Verify
pip list | grep polymarket
```

---

### Q: Error: "POLYGON_PRIVATE_KEY is required"

A: Check:
1. `.env` file exists: `ls -la .env`
2. Variable is set: `cat .env | grep POLYGON`
3. No spaces around `=`: `KEY=value` not `KEY = value`
4. File is in project root directory

---

### Q: Error: "Private key must be 64 hex characters"

A: Fix:
1. Remove `0x` prefix if present
2. Check length: `echo -n "yourkey" | wc -c` should be 64
3. Only use characters: 0-9, a-f, A-F

---

### Q: Claude Desktop doesn't see the MCP server

A: Checklist:
1. Is `claude_desktop_config.json` valid JSON? (Use jsonlint.com)
2. Is Python path correct? (`which python` on macOS/Linux)
3. Did you restart Claude Desktop? (Quit completely, then reopen)
4. Check Claude logs (see log locations in [VISUAL_INSTALL_GUIDE.md](VISUAL_INSTALL_GUIDE.md))

---

### Q: Error: "Rate limit exceeded"

A: The server respects Polymarket API limits. If you see this:
1. Wait 60 seconds
2. Reduce request frequency
3. Avoid parallel requests

Rate limits reset every minute.

---

### Q: Error: "Insufficient funds"

A: Solutions:
1. Check USDC balance on Polygonscan
2. Get more USDC (see wallet questions above)
3. Check you're on Polygon network (Chain ID 137)
4. Ensure you have MATIC for gas fees

---

### Q: Trading is slow or timing out

A: Possible causes:
1. **Network congestion**: Wait and retry
2. **API downtime**: Check Polymarket status
3. **Rate limiting**: Space out requests
4. **Large order**: May take longer to fill

---

### Q: Orders not filling

A: Reasons:
1. **Limit price not reached**: Market hasn't hit your price
2. **Low liquidity**: Not enough counterparty orders
3. **Large order**: Breaking into smaller chunks may help
4. **Spread too wide**: Adjust your limit price

Check with: `"Show me the orderbook for [token_id]"`

---

## Safety & Risk Management

### Q: How do I set appropriate risk limits?

A: Guidelines:

1. **Start small**: Test with $50-100 first
2. **Max exposure**: Never exceed 20% of trading capital
3. **Per-market limit**: Diversify across multiple markets
4. **Order size**: Keep individual orders small
5. **Liquidity check**: Only trade liquid markets (>$10k)

---

### Q: Can the server trade without my permission?

A: Depends on configuration:

- `ENABLE_AUTONOMOUS_TRADING=true`: Yes, within safety limits
- `REQUIRE_CONFIRMATION_ABOVE_USD=X`: Asks for orders over $X
- `ENABLE_AUTONOMOUS_TRADING=false`: Always asks before trading

For beginners: Set `REQUIRE_CONFIRMATION_ABOVE_USD=100` to review all significant trades.

---

### Q: What happens if I exceed a safety limit?

A: The server will:
1. Block the order
2. Return error message explaining which limit was exceeded
3. Suggest reducing order size or adjusting limits
4. Not execute any part of the trade

Safety limits are hard blocks - there's no way to bypass them except updating configuration.

---

### Q: How do I monitor my risk exposure?

A: Use portfolio tools:

```
"Analyze my portfolio risk"
"What's my total exposure?"
"Show me my position concentrations"
```

The server will report:
- Total exposure
- Per-market concentrations
- Liquidity risk
- Diversification score

---

### Q: Should I use the same wallet I use for other trading?

A: **No, not recommended.** Best practices:

1. **Dedicated wallet**: Create a wallet just for Polymarket MCP
2. **Limited funds**: Only keep what you need for active trading
3. **Regular transfers**: Move profits to cold storage
4. **Separate high-value assets**: Don't store NFTs or large amounts

---

## Performance

### Q: How many requests can I make per minute?

A: The server implements rate limiting matching Polymarket's limits:

- **Market data**: 20 requests/minute
- **Trading**: 10 orders/minute
- **WebSocket**: Unlimited (persistent connection)

These are automatically enforced by the token bucket algorithm.

---

### Q: Can I run multiple instances?

A: Yes, but:
- Each instance needs its own wallet
- Rate limits are per wallet, not per instance
- Claude Desktop typically runs one MCP server at a time

---

### Q: Does the server cache data?

A: Partially:
- Market metadata is cached briefly (1 minute)
- Orderbook data is always fresh (no cache)
- Historical data is cached for the session

This balances performance with accuracy.

---

### Q: How much data does it use?

A: Typical usage:
- Market discovery: ~1KB per request
- Orderbook: ~5-10KB per request
- WebSocket: ~1-5KB/second when active
- Negligible for most internet connections

---

## Advanced Usage

### Q: Can I use this programmatically (not through Claude)?

A: Yes! The tools are Python functions you can import:

```python
from polymarket_mcp.tools.market_discovery import search_markets

results = await search_markets(query="Trump", limit=10)
```

See [TOOLS_REFERENCE.md](TOOLS_REFERENCE.md) for complete API docs.

---

### Q: Can I add custom trading strategies?

A: Yes! Create a new Python file:

```python
# my_strategy.py
from polymarket_mcp.tools.market_discovery import get_trending_markets

async def my_strategy():
    # Get trending markets
    markets = await get_trending_markets(limit=10)

    # Your logic here
    for market in markets:
        if meets_my_criteria(market):
            await place_order(...)
```

Run with: `python my_strategy.py`

---

### Q: How do I backtest a strategy?

A: Current version doesn't include backtesting, but you can:

1. Use `get_price_history` to fetch historical data
2. Implement your strategy logic in Python
3. Simulate trades without executing
4. Calculate hypothetical P&L

Backtesting tools are planned for a future release.

---

### Q: Can I integrate with other systems?

A: Yes! The MCP server uses standard protocols:
- MCP (Model Context Protocol) for AI integration
- REST APIs for programmatic access
- WebSocket for real-time data
- Python SDK for custom integrations

---

### Q: How do I contribute to development?

A: We welcome contributions!

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

---

## Contributing

### Q: How can I report a bug?

A: Please create a GitHub issue with:
- Operating system and version
- Python version (`python --version`)
- Error message (full traceback)
- Steps to reproduce
- Expected vs actual behavior

---

### Q: How can I request a feature?

A: Open a GitHub issue with:
- Clear description of the feature
- Use case / why it's needed
- Example of how it would work
- Any relevant links or references

---

### Q: Can I contribute without coding?

A: Absolutely! Non-code contributions:
- Improve documentation
- Report bugs
- Suggest features
- Help other users
- Create tutorials or videos
- Translate to other languages

---

### Q: How do I get in touch?

A: Multiple channels:

- **GitHub Issues**: Bug reports and features
- **GitHub Discussions**: General questions
- **Telegram**: Renda Cripto community
- **Discord**: Yield Hacker community
- **Twitter**: @caiovicentino
- **Email**: Through GitHub profile

---

## Additional Resources

### Q: Where can I learn more about Polymarket?

A: Resources:
- Official site: https://polymarket.com
- Documentation: https://docs.polymarket.com
- Blog: https://polymarket.com/blog
- API docs: https://docs.polymarket.com/api

---

### Q: Where can I learn more about prediction markets?

A: Educational resources:
- "The Wisdom of Crowds" by James Surowiecki
- Polymarket Knowledge Base
- Prediction market research papers
- Economics of Information Markets

---

### Q: Are there video tutorials?

A: Coming soon! Planned videos:
- Complete installation walkthrough
- First trade tutorial
- Portfolio management guide
- Safety configuration best practices

Subscribe to our YouTube channel for updates.

---

### Q: How do I stay updated?

A: Follow:
- GitHub repository (watch for releases)
- Twitter: @caiovicentino
- Communities: Yield Hacker, Renda Cripto, Cultura Builder
- GitHub Discussions

---

## Still Have Questions?

If your question isn't answered here:

1. **Check other docs**:
   - [README.md](README.md)
   - [VISUAL_INSTALL_GUIDE.md](VISUAL_INSTALL_GUIDE.md)
   - [TOOLS_REFERENCE.md](TOOLS_REFERENCE.md)

2. **Search GitHub Issues**: Someone may have asked before

3. **Ask the community**:
   - GitHub Discussions
   - Telegram/Discord

4. **Create an issue**: We'll add it to this FAQ!

---

**Made with ❤️ by [Caio Vicentino](https://github.com/caiovicentino)**

*Happy trading on Polymarket!* 📈
