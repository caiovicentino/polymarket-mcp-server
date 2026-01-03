# 🤖 Polymarket MCP Server

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![MCP Protocol](https://img.shields.io/badge/MCP-1.0-purple.svg)](https://modelcontextprotocol.io)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](#testing)

**Complete AI-Powered Trading Platform for Polymarket Prediction Markets**

Enable Claude to autonomously trade, analyze, and manage positions on Polymarket with 45 comprehensive tools, real-time WebSocket monitoring, and enterprise-grade safety features.

---

## 👨‍💻 Created By

**[Caio Vicentino](https://github.com/caiovicentino)**

Developed in collaboration with:
- 🌾 **[Yield Hacker](https://opensea.io/collection/yield-hacker-pass-yhp)** - DeFi Innovation Community
- 💰 **[Renda Cripto](https://rendacripto.com.br/)** - Crypto Trading Community
- 🏗️ **[Cultura Builder](https://culturabuilder.com/)** - Builder Culture Community

Powered by **[Claude Code](https://claude.ai/code)** from Anthropic

---

## ⭐ Key Features

### 🎯 45 Comprehensive Tools Across 5 Categories

<table>
<tr>
<td width="20%" align="center"><b>🔍<br/>Market Discovery</b><br/>8 tools</td>
<td width="20%" align="center"><b>📊<br/>Market Analysis</b><br/>10 tools</td>
<td width="20%" align="center"><b>💼<br/>Trading</b><br/>12 tools</td>
<td width="20%" align="center"><b>📈<br/>Portfolio</b><br/>8 tools</td>
<td width="20%" align="center"><b>⚡<br/>Real-time</b><br/>7 tools</td>
</tr>
</table>

#### 🔍 Market Discovery (8 tools)
- Search and filter markets by keywords, categories, events
- Trending markets by volume (24h, 7d, 30d)
- Category-specific markets (Politics, Sports, Crypto)
- Markets closing soon alerts
- Featured and promoted markets
- Sports markets (NBA, NFL, etc.)
- Crypto prediction markets

#### 📊 Market Analysis (10 tools)
- Real-time prices and spreads
- Complete orderbook depth analysis
- Liquidity and volume metrics
- Historical price data
- **AI-powered opportunity analysis** with BUY/SELL/HOLD recommendations
- Multi-market comparison
- Top holders analysis
- Risk assessment and scoring
- Spread calculation and monitoring

#### 💼 Trading (12 tools)
- **Limit orders** (GTC, GTD, FOK, FAK)
- **Market orders** (immediate execution)
- Batch order submission
- **AI-suggested pricing** (aggressive/passive/mid strategies)
- Order status tracking and history
- Open orders management
- Single and bulk order cancellation
- **Smart trade execution** (natural language → automated strategy)
- **Position rebalancing** with slippage protection
- Order book integration

#### 📈 Portfolio Management (8 tools)
- Real-time position tracking
- P&L calculation (realized/unrealized)
- Portfolio value aggregation
- **Risk analysis** (concentration, liquidity, diversification)
- Trade history with filters
- On-chain activity log
- Performance metrics
- **AI-powered portfolio optimization** (conservative/balanced/aggressive)

#### ⚡ Real-time Monitoring (7 tools)
- Live price updates via WebSocket
- Orderbook depth streaming
- User order status notifications
- Trade execution alerts
- Market resolution notifications
- Subscription management
- System health monitoring
- Auto-reconnect with exponential backoff

### 🛡️ Enterprise-Grade Safety & Risk Management

- ✅ **Order Size Limits** - Configurable maximum per order
- ✅ **Exposure Caps** - Total portfolio exposure limits
- ✅ **Position Limits** - Per-market position caps
- ✅ **Liquidity Validation** - Minimum liquidity requirements
- ✅ **Spread Tolerance** - Maximum spread checks before execution
- ✅ **Confirmation Flow** - User confirmation for large orders
- ✅ **Pre-trade Validation** - Comprehensive safety checks

### ⚙️ Production-Ready Infrastructure

- ✅ **L1 & L2 Authentication** - Wallet (private key) + API key auth
- ✅ **Advanced Rate Limiting** - Token bucket algorithm respecting all Polymarket API limits
- ✅ **EIP-712 Signing** - Secure order signatures
- ✅ **Auto-reconnect WebSockets** - Resilient real-time connections
- ✅ **Comprehensive Error Handling** - User-friendly error messages
- ✅ **No Mocks** - Real Polymarket API integration throughout
- ✅ **Full Test Coverage** - Production-grade testing with real APIs

---

## 🌐 Web Dashboard

**NEW**: Manage and monitor your Polymarket MCP Server with a modern web interface!

```bash
# Start the web dashboard
polymarket-web

# Or use the quick start script
./start_web_dashboard.sh
```

Access at: **http://localhost:8080**

### Dashboard Features

- **Real-time Monitoring**: Live MCP status, WebSocket connection, and statistics
- **Configuration Management**: Visual sliders for safety limits and trading controls
- **Market Discovery**: Search, filter, and browse markets with live updates
- **Market Analysis**: AI-powered analysis with recommendations and risk assessment
- **System Monitoring**: Performance charts, rate limits, and activity logs
- **Dark Theme**: Professional UI optimized for extended use

See [WEB_DASHBOARD.md](WEB_DASHBOARD.md) for complete documentation.

---

## 🚀 Quick Start

### One-Command Installation (Recommended)

**Try DEMO mode first** (no wallet needed):
```bash
# macOS/Linux
curl -sSL https://raw.githubusercontent.com/caiovicentino/polymarket-mcp-server/main/quickstart.sh | bash

# Or clone and run locally
git clone https://github.com/caiovicentino/polymarket-mcp-server.git
cd polymarket-mcp-server
./quickstart.sh
```

**Full installation** (with trading):
```bash
# macOS/Linux
./install.sh

# Windows
install.bat
```

The automated installer will:
- ✓ Check Python version (3.10+)
- ✓ Create virtual environment
- ✓ Install all dependencies
- ✓ Configure environment
- ✓ Set up Claude Desktop integration
- ✓ Test the installation

### Installation Options

| Method | Command | Best For |
|--------|---------|----------|
| **Quick Start** | `./quickstart.sh` | First-time users, testing |
| **DEMO Mode** | `./install.sh --demo` | No wallet, read-only access |
| **Full Install** | `./install.sh` | Production trading setup |
| **Windows** | `install.bat` | Windows users |

### DEMO Mode vs Full Mode

**DEMO Mode** (No wallet required):
- ✅ Market discovery and search
- ✅ Real-time market analysis
- ✅ AI-powered insights
- ✅ Price monitoring
- ❌ Trading disabled (read-only)

**Full Mode** (Requires Polygon wallet):
- ✅ Everything in DEMO mode
- ✅ Place orders and execute trades
- ✅ Portfolio management
- ✅ Position tracking
- ✅ Real-time trade notifications

### Manual Installation

If you prefer manual setup:

```bash
# Clone the repository
git clone https://github.com/caiovicentino/polymarket-mcp-server.git
cd polymarket-mcp-server

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install the package
pip install -e .
```

---

## ⚠️ Critical Installation Guide (Read This First!)

### Important Compatibility Notes

This section addresses critical installation issues that users may encounter. Please read carefully to avoid common problems.

### 🚨 Known Issues & Solutions

#### Issue 1: FastAPI/MCP Dependency Conflict

**Error:**
```
ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/latest/topics/dependency-resolution/#dealing-with-dependency-conflicts

The conflict is caused by:
    fastapi 0.104.0 depends on anyio<4.0.0 and >=3.7.1
    mcp 1.25.0 depends on anyio>=4.5
```

**Solution:** This issue has been fixed in the latest version. Ensure you're using the updated code with FastAPI >=0.109.0.

#### Issue 2: typing_extensions System Package Conflict

**Error:**
```
ERROR: Cannot install polymarket-mcp-0.1.0
- typing-extensions 4.10.0 (system)
  conflicts with required: typing_extensions>=4.12.2 (package)
```

**Root Cause:** On WSL2 Ubuntu 24.04 and some Linux distributions, Python 3.12.3 comes with `typing_extensions-4.10.0` bundled in `/usr/lib/python3/dist-packages/`. pip cannot override system packages inside virtualenv.

**Solution:**

```bash
# Create clean virtualenv with Python 3.12.3
python3.12 -m venv /home/vic/polymarket-clean-venv

# Activate virtualenv
source /home/vic/polymarket-clean-venv/bin/activate

# Upgrade typing_extensions
pip install --upgrade typing_extensions

# Verify version (should be 4.15.0 or higher)
python -c "import importlib.metadata; print(importlib.metadata.version('typing_extensions'))"

# Install with PYTHONPATH override
export PYTHONPATH=/home/vic/polymarket-clean-venv/lib/python3.12/site-packages:$PYTHONPATH
pip install -e .
```

#### Issue 3: Python Path Priority

**Problem:** System packages are loaded before virtualenv packages, causing version conflicts.

**Solution:** Use the provided helper script `run_with_env.sh` which sets PYTHONPATH correctly.

```bash
# Create helper script
cat > /home/vic/polymarket-mcp-server/run_with_env.sh << 'EOF'
#!/bin/bash

cd /home/vic/polymarket-mcp-server
source /home/vic/polymarket-clean-venv/bin/activate
export PYTHONPATH=/home/vic/polymarket-clean-venv/lib/python3.12/site-packages:$PYTHONPATH
"$@"
EOF

# Make executable
chmod +x /home/vic/polymarket-mcp-server/run_with_env.sh

# Use helper script for all commands
./run_with_env.sh python3 your_script.py
```

---

## 🔧 Complete Installation Procedure

### Step 1: Create Virtual Environment

```bash
# Create virtualenv with Python 3.12.3 (recommended)
python3.12 -m venv /home/vic/polymarket-clean-venv

# Activate virtualenv
source /home/vic/polymarket-clean-venv/bin/activate

# Verify Python version
python --version  # Should be 3.12.3
```

**⚠️ Important:** Always use Python 3.12.3, NOT 3.13.5 or system Python.

### Step 2: Upgrade typing_extensions

```bash
pip install --upgrade typing_extensions

# Verify version
python -c "import importlib.metadata; print(importlib.metadata.version('typing_extensions'))"
# Should be 4.15.0 or higher
```

### Step 3: Clone Repository

```bash
cd /home/vic
git clone https://github.com/caiovicentino/polymarket-mcp-server.git
cd polymarket-mcp-server
```

### Step 4: Install Package

```bash
# Set PYTHONPATH to prioritize virtualenv
export PYTHONPATH=/home/vic/polymarket-clean-venv/lib/python3.12/site-packages:$PYTHONPATH

# Install package
pip install -e .
```

### Step 5: Create Configuration

```bash
# Copy example configuration
cp .env.example .env

# Edit configuration (optional - demo mode works out of the box)
nano .env
```

### Step 6: Create Helper Script

```bash
cat > /home/vic/polymarket-mcp-server/run_with_env.sh << 'EOF'
#!/bin/bash

cd /home/vic/polymarket-mcp-server
source /home/vic/polymarket-clean-venv/bin/activate
export PYTHONPATH=/home/vic/polymarket-clean-venv/lib/python3.12/site-packages:$PYTHONPATH
"$@"
EOF

# Make executable
chmod +x /home/vic/polymarket-mcp-server/run_with_env.sh
```

### Step 7: Validate Installation

```bash
# Run smoke tests
/home/vic/polymarket-mcp-server/run_with_env.sh python3 smoke_test.py

# Test server initialization
/home/vic/polymarket-mcp-server/run_with_env.sh python3 test_server_init.py
```

---

## 🔌 OpenCode Integration

### Step 1: Update OpenCode Configuration

Edit `~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "polymarket": {
      "type": "local",
      "enabled": true,
      "command": [
        "/home/vic/polymarket-mcp-server/run_with_env.sh",
        "python3",
        "/home/vic/polymarket-mcp-server/run_opencode_mcp.py"
      ],
      "environment": {
        "DEMO_MODE": "true"
      }
    }
  }
}
```

### Step 2: Restart OpenCode

Restart OpenCode to load the new configuration.

### Step 3: Verify Integration

OpenCode should now show the Polymarket MCP with 25 tools available in demo mode.

---

## 🎯 Quick Start Commands

### Test Server

```bash
cd /home/vic/polymarket-mcp-server
./run_with_env.sh python3 test_server_init.py
```

### Run Smoke Tests

```bash
./run_with_env.sh python3 smoke_test.py
```

### Start MCP Server

```bash
./run_with_env.sh python3 run_opencode_mcp.py
```

---

## ⚠️ Critical Points - Avoid Common Issues

### 1. **ALWAYS use Python 3.12.3**
- ❌ NOT Python 3.13.5
- ❌ NOT system Python
- ✅ Use: `python3.12 -m venv`

### 2. **ALWAYS use the helper script**
- ❌ NOT direct python command
- ❌ NOT system python path
- ✅ Use: `./run_with_env.sh python3`

### 3. **typing_extensions MUST be 4.12.2+**
- ❌ NOT 4.10.0 (system)
- ✅ Upgrade: `pip install --upgrade typing_extensions`

### 4. **PYTHONPATH MUST prioritize virtualenv**
- ❌ NOT system packages first
- ✅ Use: `export PYTHONPATH=/path/to/venv/site-packages:$PYTHONPATH`

### 5. **OpenCode config MUST use helper script**
- ❌ NOT direct Python path
- ✅ Use: `["run_with_env.sh", "python3", "run_opencode_mcp.py"]`

---

## ❌ What to Avoid

- ❌ Using system Python
- ❌ Using Python 3.13.5
- ❌ Installing without virtualenv
- ❌ Not upgrading typing_extensions
- ❌ Direct Python path in OpenCode config
- ❌ Skipping smoke tests
- ❌ Not setting PYTHONPATH
- ❌ Not using helper script

---

## ✅ Best Practices

- ✅ Always use `run_with_env.sh`
- ✅ Always use Python 3.12.3 virtualenv
- ✅ Always verify installation with smoke tests
- ✅ Always test server initialization
- ✅ Always check Python path priority
- ✅ Always use helper script in OpenCode config

---

## 🧪 Troubleshooting

### Import Errors

**Problem:** `ModuleNotFoundError` or import errors

**Solution:** Always use the helper script:
```bash
./run_with_env.sh python3 your_script.py
```

### typing_extensions Version Conflict

**Problem:** Version mismatch errors

**Solution:**
```bash
source /home/vic/polymarket-clean-venv/bin/activate
pip install --upgrade typing_extensions
python -c "import importlib.metadata; print(importlib.metadata.version('typing_extensions'))"
```

### Server Won't Start

**Problem:** Server initialization fails

**Solution:**
```bash
./run_with_env.sh python3 test_server_init.py
```

Check the output for specific error messages.

### OpenCode Not Loading MCP

**Problem:** Polymarket MCP not showing in OpenCode

**Solution:**
1. Check `~/.config/opencode/opencode.json` is correct
2. Verify the helper script path is correct
3. Restart OpenCode
4. Check OpenCode logs for errors

---

## 📚 Additional Documentation

- **[Complete Installation Guide](COMPLETE_INSTALLATION_GUIDE.md)** - Comprehensive guide with all issues and solutions
- **[Installation Complete](INSTALLATION_COMPLETE.md)** - Quick reference for successful installation
- **[FAQ](FAQ.md)** - Frequently asked questions and troubleshooting
- **[Setup Guide](SETUP_GUIDE.md)** - Detailed configuration instructions

### Configuration

**Option 1: DEMO Mode** (easiest)
```bash
cp .env.example .env
# Edit .env and set:
DEMO_MODE=true
```

**Option 2: Full Trading Mode**
```bash
cp .env.example .env
# Edit with your Polygon wallet credentials
nano .env
```

**Required credentials (Full Mode):**
```env
POLYGON_PRIVATE_KEY=your_private_key_without_0x_prefix
POLYGON_ADDRESS=0xYourPolygonAddress
```

**Recommended Safety Limits:**
```env
MAX_ORDER_SIZE_USD=1000
MAX_TOTAL_EXPOSURE_USD=5000
MAX_POSITION_SIZE_PER_MARKET=2000
MIN_LIQUIDITY_REQUIRED=10000
MAX_SPREAD_TOLERANCE=0.05
ENABLE_AUTONOMOUS_TRADING=true
REQUIRE_CONFIRMATION_ABOVE_USD=500
```

### Claude Desktop Integration

Add to your Claude Desktop configuration file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "polymarket": {
      "command": "/path/to/your/venv/bin/python",
      "args": ["-m", "polymarket_mcp.server"],
      "cwd": "/path/to/polymarket-mcp-server",
      "env": {
        "POLYGON_PRIVATE_KEY": "your_private_key",
        "POLYGON_ADDRESS": "0xYourAddress"
      }
    }
  }
}
```

**Restart Claude Desktop** and you're ready to trade! 🎉

---

## 📖 Documentation

### Getting Started
- **[Visual Installation Guide](VISUAL_INSTALL_GUIDE.md)** - Step-by-step with diagrams and screenshots
- **[FAQ](FAQ.md)** - Frequently asked questions and troubleshooting
- **[Setup Guide](SETUP_GUIDE.md)** - Detailed configuration instructions
- **[Demo Video Script](DEMO_VIDEO_SCRIPT.md)** - Video tutorial scripts

### Developer Resources
- **[Tools Reference](TOOLS_REFERENCE.md)** - Complete API documentation for all 45 tools
- **[Agent Integration Guide](AGENT_INTEGRATION_GUIDE.md)** - How to integrate with your agents
- **[Trading Architecture](TRADING_ARCHITECTURE.md)** - System design and architecture
- **[WebSocket Integration](WEBSOCKET_INTEGRATION.md)** - Real-time data setup

### Examples & Guides
- **[Usage Examples](USAGE_EXAMPLES.py)** - Code examples for all tools
- **[Test Examples](TEST_EXAMPLES.py)** - Example test implementations
- **[Market Analysis Scripts](analyze_top_markets.py)** - Advanced analysis examples

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    POLYMARKET MCP SERVER                    │
└─────────────────────────────────────────────────────────────┘

    ┌──────────────┐
    │   Claude     │
    │   Desktop    │ (Natural language interface)
    └──────┬───────┘
           │ MCP Protocol
           ▼
    ┌──────────────────────────────────────────────┐
    │           MCP Server (Python)                │
    ├──────────────────────────────────────────────┤
    │  ┌────────────┐  ┌──────────────────────┐   │
    │  │  Market    │  │  Trading             │   │
    │  │  Discovery │  │  Engine              │   │
    │  │  (8 tools) │  │  (12 tools)          │   │
    │  └────────────┘  └──────────────────────┘   │
    │                                              │
    │  ┌────────────┐  ┌──────────────────────┐   │
    │  │  Market    │  │  Portfolio           │   │
    │  │  Analysis  │  │  Manager             │   │
    │  │  (10 tools)│  │  (8 tools)           │   │
    │  └────────────┘  └──────────────────────┘   │
    │                                              │
    │  ┌──────────────────────────────────────┐   │
    │  │  Real-time WebSocket (7 tools)       │   │
    │  └──────────────────────────────────────┘   │
    └──────────────┬───────────────────────────────┘
                   │
                   ▼
    ┌──────────────────────────────────────────────┐
    │         Polymarket Infrastructure            │
    ├──────────────────────────────────────────────┤
    │  • CLOB API (Order placement & management)   │
    │  • Gamma API (Market data & analytics)       │
    │  • WebSocket (Real-time price feeds)         │
    │  • Polygon Chain (Settlement & execution)    │
    └──────────────────────────────────────────────┘
```

---

## 💡 Usage Examples

### Market Discovery
Ask Claude:
```
"Show me the top 10 trending markets on Polymarket in the last 24 hours"
"Find all crypto markets about Bitcoin"
"What sports markets are closing in the next 12 hours?"
"Search for markets about Trump"
```

### Market Analysis
```
"Analyze the trading opportunity for the government shutdown market"
"Compare these three markets and tell me which has the best risk/reward"
"What's the current spread on the Eagles vs Packers market?"
"Show me the orderbook depth for token ID xyz"
```

### Autonomous Trading
```
"Buy $100 of YES tokens in [market_id] at $0.65"
"Place a limit order: sell 200 NO at $0.40 in [market]"
"Execute a smart trade: buy YES up to $500 in [market] using best strategy"
"Cancel all my open orders in the government shutdown market"
"Rebalance my position in [market] to $1000 with max 2% slippage"
```

### Portfolio Management
```
"Show me all my current positions"
"What's my total portfolio value?"
"Analyze my portfolio risk and suggest improvements"
"What's my P&L for the last 30 days?"
"Which are my best and worst performing markets?"
"Suggest portfolio optimizations for a conservative strategy"
```

### Real-time Monitoring
```
"Subscribe to price changes for the government shutdown markets"
"Monitor my order status in real-time"
"Alert me when the Eagles vs Packers market moves more than 10%"
"Show me real-time orderbook updates for [token_id]"
```

---

## 🧪 Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run specific test suite
pytest tests/test_trading_tools.py -v

# Run with coverage
pytest --cov=polymarket_mcp --cov-report=html

# Run market analysis demo
python demo_mcp_tools.py
```

**Note:** All tests use real Polymarket APIs - NO MOCKS!

---

## 🛡️ Safety & Security

### ⚠️ Important Security Considerations

- **Private Key Protection**: Never share or commit your private key
- **Start Small**: Begin with small amounts ($50-100) to test
- **Understand Markets**: Only trade in markets you understand
- **Monitor Positions**: Check your positions regularly
- **Use Safety Limits**: Configure appropriate limits for your risk tolerance
- **Never Risk More**: Than you can afford to lose

### Default Safety Limits

```env
MAX_ORDER_SIZE_USD=1000              # Maximum $1,000 per order
MAX_TOTAL_EXPOSURE_USD=5000          # Maximum $5,000 total exposure
MAX_POSITION_SIZE_PER_MARKET=2000    # Maximum $2,000 per market
MIN_LIQUIDITY_REQUIRED=10000         # Minimum $10,000 market liquidity
MAX_SPREAD_TOLERANCE=0.05            # Maximum 5% spread
REQUIRE_CONFIRMATION_ABOVE_USD=500   # Confirm orders over $500
```

These can be customized in your `.env` file or Claude Desktop config.

---

## 🤝 Contributing

Contributions are welcome! We appreciate your help making this project better.

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on:
- How to report bugs
- How to suggest features
- Code standards and guidelines
- Pull request process

### Quick Contribution Guide

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📊 Project Stats

- **Lines of Code**: ~10,000+ (Python)
- **Tools**: 45 comprehensive tools
- **Test Coverage**: High (real API integration)
- **Documentation**: Comprehensive (multiple guides)
- **Dependencies**: Modern Python packages (MCP, httpx, websockets, eth-account)

---

## 🌐 Community

### Join Our Communities

- 🌾 **[Yield Hacker](https://opensea.io/collection/yield-hacker-pass-yhp)** - DeFi Innovation & Yield Farming
- 💰 **[Renda Cripto](https://rendacripto.com.br/)** - Crypto Trading & Investments
- 🏗️ **[Cultura Builder](https://culturabuilder.com/)** - Builder Culture & Development

### Get Support

- **GitHub Issues**: [Report bugs or request features](https://github.com/caiovicentino/polymarket-mcp-server/issues)
- **GitHub Discussions**: [Ask questions and share ideas](https://github.com/caiovicentino/polymarket-mcp-server/discussions)
- **Telegram Communities**: Get help from the community

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

This project was made possible by:

- **Caio Vicentino** - Creator and lead developer
- **Yield Hacker Community** - DeFi expertise and testing
- **Renda Cripto Community** - Trading insights and validation
- **Cultura Builder Community** - Builder culture and support
- **[Polymarket](https://polymarket.com)** - Amazing prediction market platform
- **[Anthropic](https://anthropic.com)** - Claude and the MCP protocol
- **[py-clob-client](https://github.com/Polymarket/py-clob-client)** - Official Polymarket SDK

Special thanks to all contributors and community members who have helped improve this project!

---

## ⚠️ Disclaimer

This software is provided for educational and research purposes. Trading prediction markets involves financial risk.

**Important Reminders:**
- Cryptocurrency trading carries significant risk
- Only invest what you can afford to lose
- Past performance does not guarantee future results
- This is not financial advice
- Always do your own research (DYOR)
- Start with small amounts to learn the system
- Understand the markets you're trading
- Monitor your positions regularly

The authors and contributors are not responsible for any financial losses incurred through the use of this software.

---

## 🔗 Links

- **GitHub Repository**: [github.com/caiovicentino/polymarket-mcp-server](https://github.com/caiovicentino/polymarket-mcp-server)
- **Polymarket**: [polymarket.com](https://polymarket.com)
- **Polymarket Docs**: [docs.polymarket.com](https://docs.polymarket.com)
- **MCP Protocol**: [modelcontextprotocol.io](https://modelcontextprotocol.io)
- **Claude Code**: [claude.ai/code](https://claude.ai/code)

---

## 📈 Roadmap

### Current Version (v0.1.0)
- ✅ 45 comprehensive tools
- ✅ Real-time WebSocket monitoring
- ✅ Safety limits and risk management
- ✅ Complete test suite
- ✅ Comprehensive documentation

### Planned Features
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Enhanced AI analysis tools
- [ ] Portfolio strategy templates
- [ ] Market alerts and notifications
- [ ] Performance analytics dashboard
- [ ] Multi-wallet support
- [ ] Advanced order types
- [ ] Historical backtesting

---

<div align="center">

**Built with ❤️ for autonomous AI trading on Polymarket**

*Ready to make Claude your personal prediction market trader!* 🚀

[⭐ Star this repo](https://github.com/caiovicentino/polymarket-mcp-server) | [🐛 Report Bug](https://github.com/caiovicentino/polymarket-mcp-server/issues) | [✨ Request Feature](https://github.com/caiovicentino/polymarket-mcp-server/issues)

</div>
