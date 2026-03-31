# Installation Guide

Complete installation guide for the Polymarket MCP Server with automated scripts.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Installation Methods](#installation-methods)
- [DEMO Mode](#demo-mode)
- [Full Trading Mode](#full-trading-mode)
- [Uninstallation](#uninstallation)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements

- **Python**: 3.10 or higher
- **OS**: macOS, Linux, or Windows (with WSL)
- **Claude Desktop**: Latest version installed
- **Internet**: Active connection for API access

### For Full Trading Mode

- **Polygon Wallet**: With private key
- **USDC**: Funds for trading (start small, e.g., $50-100)
- **MetaMask**: Recommended wallet (optional)

---

## Quick Start

### Fastest Way to Get Started

```bash
# One command - installs DEMO mode automatically
curl -sSL https://raw.githubusercontent.com/joe67-67/polymarket-mcp-server/main/quickstart.sh | bash
```

This will:
1. Clone the repository to `~/polymarket-mcp-server`
2. Install in DEMO mode (no wallet needed)
3. Configure Claude Desktop
4. Be ready to use in ~60 seconds

**Then:** Restart Claude Desktop and ask:
```
"Show me trending Polymarket markets"
```

---

## Installation Methods

### Method 1: Automated Installer (Recommended)

#### macOS/Linux

```bash
# Clone repository
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server

# Run installer
./install.sh
```

**Interactive Options:**
- Choose DEMO mode or full trading mode
- Configure safety limits
- Set up Claude Desktop automatically

#### Windows

```batch
REM Clone repository
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server

REM Run installer
install.bat
```

### Method 2: Quick Start Script

```bash
# Downloads and installs automatically in DEMO mode
./quickstart.sh
```

### Method 3: Manual Installation

```bash
# 1. Clone repository
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -e .

# 4. Configure environment
cp .env.example .env
nano .env  # Edit configuration

# 5. Add to Claude Desktop config manually
# See "Manual Claude Desktop Setup" below
```

---

## DEMO Mode

### What is DEMO Mode?

DEMO mode lets you explore Polymarket MCP Server **without a wallet**:

- ✅ **Market Discovery**: Search and browse markets
- ✅ **Market Analysis**: AI-powered insights and analysis
- ✅ **Price Monitoring**: Real-time price tracking
- ✅ **Orderbook Analysis**: View market depth
- ❌ **Trading**: Disabled (read-only)

### Installing in DEMO Mode

```bash
# Option 1: Quick Start
./quickstart.sh

# Option 2: Automated installer with --demo flag
./install.sh --demo

# Option 3: Manual - edit .env
echo "DEMO_MODE=true" >> .env
```

### DEMO Mode Configuration

Your `.env` file should contain:
```env
DEMO_MODE=true

# No need to provide:
# POLYGON_PRIVATE_KEY (auto-set to safe demo value)
# POLYGON_ADDRESS (auto-set to safe demo value)
```

The system automatically uses safe demo credentials when `DEMO_MODE=true`.

### Switching from DEMO to Full Mode

```bash
# Method 1: Reinstall
./uninstall.sh
./install.sh  # Choose "yes" when asked about wallet

# Method 2: Edit .env manually
nano .env
# Change DEMO_MODE=true to DEMO_MODE=false
# Add your wallet credentials
```

---

## Full Trading Mode

### Prerequisites

1. **Polygon Wallet** with private key
2. **USDC funds** on Polygon network
3. **Understanding** of prediction markets

### Getting Your Wallet Credentials

#### From MetaMask

1. Open MetaMask browser extension
2. Click account icon → Settings → Security & Privacy
3. Click "Reveal Secret Recovery Phrase"
4. Copy your private key (64 hex characters)
5. Copy your wallet address (starts with 0x)

**Security Warning:** Never share your private key! Keep it secure!

### Installation Steps

```bash
# Run installer
./install.sh

# Follow prompts:
# 1. "Do you have a Polygon wallet?" → y
# 2. Enter private key (64 hex chars, no 0x prefix)
# 3. Enter wallet address (42 chars, with 0x prefix)
# 4. Configure safety limits (recommended)
```

### Configuration

Your `.env` file should look like:

```env
# Full trading mode
DEMO_MODE=false

# Your wallet credentials
POLYGON_PRIVATE_KEY=abcd1234...  # 64 hex characters
POLYGON_ADDRESS=0x1234...         # 42 characters

# Safety limits (recommended)
MAX_ORDER_SIZE_USD=1000
MAX_TOTAL_EXPOSURE_USD=5000
MAX_POSITION_SIZE_PER_MARKET=2000
MIN_LIQUIDITY_REQUIRED=10000
MAX_SPREAD_TOLERANCE=0.05

# Trading controls
ENABLE_AUTONOMOUS_TRADING=true
REQUIRE_CONFIRMATION_ABOVE_USD=500
```

### Safety Recommendations

**Start Small:**
- Begin with $50-100 to learn the system
- Test with small orders first
- Understand markets before trading

**Configure Limits:**
- Set conservative `MAX_ORDER_SIZE_USD` initially
- Use `REQUIRE_CONFIRMATION_ABOVE_USD` for safety
- Monitor positions regularly

**Security:**
- Never commit `.env` to git
- Keep private key secure
- Use environment variables in production

---

## Claude Desktop Integration

### Automatic Configuration

The installer automatically configures Claude Desktop for you.

**Config Location:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

**After Installation:**
1. Restart Claude Desktop
2. Look for "polymarket" in server list
3. Start asking Claude about Polymarket!

### Manual Claude Desktop Setup

If you need to configure manually:

```json
{
  "mcpServers": {
    "polymarket": {
      "command": "/path/to/venv/bin/python",
      "args": ["-m", "polymarket_mcp.server"],
      "cwd": "/path/to/polymarket-mcp-server",
      "env": {
        "DEMO_MODE": "true"
      }
    }
  }
}
```

**For full trading mode**, replace `"DEMO_MODE": "true"` with:
```json
"env": {
  "POLYGON_PRIVATE_KEY": "your_private_key",
  "POLYGON_ADDRESS": "0xYourAddress"
}
```

### Verifying Installation

In Claude Desktop, ask:
```
Show me the top trending Polymarket markets
```

Expected response:
- Claude retrieves real Polymarket data
- Shows market names, prices, volumes
- No authentication errors

---

## Uninstallation

### Automated Uninstall

```bash
# Interactive uninstall
./uninstall.sh

# Force uninstall (no confirmation)
./uninstall.sh --force
```

**What Gets Removed:**
- ✓ Virtual environment
- ✓ .env file (backed up to .env.backup)
- ✓ Claude Desktop config entry (backed up)
- ✓ Cache files and build artifacts

**What Stays:**
- ✓ Source code
- ✓ Documentation
- ✓ Your backup files

### Manual Uninstall

```bash
# Remove virtual environment
rm -rf venv/

# Backup and remove .env
mv .env .env.backup

# Remove from Claude Desktop config manually
# Edit: ~/Library/Application Support/Claude/claude_desktop_config.json
# Remove "polymarket" entry

# Clean cache
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
```

---

## Troubleshooting

### Common Issues

#### 1. "Python not found"

**Solution:**
```bash
# macOS
brew install python@3.12

# Linux (Ubuntu/Debian)
sudo apt update
sudo apt install python3.12

# Windows
# Download from python.org and install
# Make sure to check "Add Python to PATH"
```

#### 2. "Permission denied: ./install.sh"

**Solution:**
```bash
chmod +x install.sh
./install.sh
```

#### 3. "Invalid private key format"

**Solution:**
- Remove `0x` prefix from private key
- Must be exactly 64 hex characters
- Only use characters: 0-9, a-f, A-F

#### 4. "Claude Desktop config not found"

**Solution:**
```bash
# Create config directory
mkdir -p ~/Library/Application\ Support/Claude  # macOS
mkdir -p ~/.config/Claude                       # Linux

# Run installer again
./install.sh
```

#### 5. "Module not found: polymarket_mcp"

**Solution:**
```bash
# Activate virtual environment
source venv/bin/activate

# Reinstall package
pip install -e .
```

#### 6. "Could not reach Polymarket API"

**Solution:**
- Check internet connection
- Verify firewall settings
- Try again in a few minutes
- API might be temporarily down

#### 7. DEMO mode not working

**Solution:**
```bash
# Check .env file
cat .env | grep DEMO_MODE
# Should show: DEMO_MODE=true

# If not, add it:
echo "DEMO_MODE=true" >> .env

# Test config loads:
source venv/bin/activate
python -c "from polymarket_mcp.config import load_config; print(load_config().DEMO_MODE)"
```

### Getting Help

**Check Documentation:**
- [README.md](README.md) - Project overview
- [SETUP_GUIDE.md](SETUP_GUIDE.md) - Detailed setup
- [TEST_INSTALLATION.md](TEST_INSTALLATION.md) - Testing guide

**Report Issues:**
- GitHub Issues: https://github.com/joe67-67/polymarket-mcp-server/issues
- Include error messages and system info

**Community Support:**
- GitHub Discussions
- Telegram communities (see README)

---

## Next Steps

After successful installation:

1. **Restart Claude Desktop**
2. **Try Example Queries:**
   ```
   Show me trending Polymarket markets
   Analyze crypto prediction markets
   What markets are closing soon?
   ```
3. **Read Documentation:**
   - [Usage Examples](USAGE_EXAMPLES.py)
   - [Tools Reference](TOOLS_REFERENCE.md)
   - [Trading Architecture](TRADING_ARCHITECTURE.md)

4. **Start Trading** (Full mode only):
   ```
   Buy $50 of YES in [market_id]
   Show my current positions
   What's my portfolio value?
   ```

---

## Security Best Practices

### Protecting Your Private Key

- ✅ Never commit `.env` to git (it's in `.gitignore`)
- ✅ Never share your private key
- ✅ Use environment variables in production
- ✅ Keep backups secure
- ✅ Rotate keys if compromised

### Safe Trading Practices

- ✅ Start with small amounts
- ✅ Understand markets before trading
- ✅ Set conservative safety limits
- ✅ Monitor positions regularly
- ✅ Never risk more than you can afford to lose

### Environment Security

```bash
# Set restrictive permissions on .env
chmod 600 .env

# Never expose credentials
# Bad:  export POLYGON_PRIVATE_KEY=abc123
# Good: Use .env file with proper permissions
```

---

## Upgrade Guide

To upgrade to the latest version:

```bash
# 1. Backup your configuration
cp .env .env.backup

# 2. Pull latest changes
git pull origin main

# 3. Reinstall dependencies
source venv/bin/activate
pip install -e . --upgrade

# 4. Restore configuration
cp .env.backup .env

# 5. Restart Claude Desktop
```

---

**Installation Complete!** 🎉

You're now ready to use Claude for Polymarket trading and analysis.

Happy trading! 🚀
