# 📖 Polymarket MCP Server - Visual Installation Guide

Complete step-by-step installation guide with diagrams and troubleshooting.

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation Methods](#installation-methods)
3. [Method 1: GUI Wizard (Easiest)](#method-1-gui-wizard-easiest)
4. [Method 2: Automated Script](#method-2-automated-script)
5. [Method 3: Docker](#method-3-docker)
6. [Method 4: Manual Installation](#method-4-manual-installation)
7. [Wallet Setup Guide](#wallet-setup-guide)
8. [Claude Desktop Integration](#claude-desktop-integration)
9. [Testing Your Setup](#testing-your-setup)
10. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

```
┌─────────────────────────────────────────────────────────┐
│                    REQUIREMENTS                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ✓ Python 3.10 or higher                              │
│    Download: https://python.org/downloads              │
│                                                         │
│  ✓ Claude Desktop                                      │
│    Download: https://claude.ai/download                │
│                                                         │
│  ✓ Git (optional, for cloning)                        │
│    Download: https://git-scm.com/downloads             │
│                                                         │
│  ✓ Polygon Wallet (for trading)                       │
│    - MetaMask or similar                               │
│    - Must have USDC on Polygon network                 │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### System Requirements

- Operating System: macOS, Windows 10+, or Linux
- RAM: 2GB minimum
- Disk Space: 500MB for installation
- Internet connection

---

## Installation Methods

```
┌──────────────────────────────────────────────────────────────┐
│              CHOOSE YOUR INSTALLATION METHOD                 │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. GUI Wizard (RECOMMENDED)                                │
│     ⏱️  5 minutes  │  ⭐ Easiest  │  🎯 Best for beginners │
│                                                              │
│  2. Automated Script                                        │
│     ⏱️  3 minutes  │  ⭐ Easy  │  🎯 For terminal users   │
│                                                              │
│  3. Docker                                                  │
│     ⏱️  2 minutes  │  ⭐ Medium  │  🎯 For Docker users   │
│                                                              │
│  4. Manual Installation                                     │
│     ⏱️  10 minutes │  ⭐ Advanced │  🎯 For customization │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## Method 1: GUI Wizard (Easiest)

### Step 1: Download the Project

```bash
# Clone the repository
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server
```

Or download ZIP from GitHub and extract.

### Step 2: Install Dependencies

```bash
# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate  # macOS/Linux
# OR
venv\Scripts\activate     # Windows

# Install the package
pip install -e .
```

### Step 3: Run Setup Wizard

```bash
python setup_wizard.py
```

### Step 4: Follow the Wizard

```
┌─────────────────────────────────────────────────┐
│          SETUP WIZARD FLOW                      │
└─────────────────────────────────────────────────┘

    ┌─────────────┐
    │  Welcome    │
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │ Choose Mode │ ◄─── Demo or Full?
    └──────┬──────┘
           │
           ▼
    ┌──────────────┐
    │   Wallet     │ ◄─── Full mode only
    │   Config     │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │   Safety     │ ◄─── Set limits
    │   Limits     │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │   Claude     │ ◄─── Auto-configure
    │   Desktop    │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │   Finish!    │
    └──────────────┘
```

### Screenshots (Placeholders)

**Welcome Screen:**
```
[Screenshot: Welcome screen with project logo and start button]
```

**Wallet Configuration:**
```
[Screenshot: Wallet config screen with masked private key input]
```

**Safety Limits:**
```
[Screenshot: Sliders for configuring risk limits]
```

**Success:**
```
[Screenshot: Completion screen with restart reminder]
```

---

## Method 2: Automated Script

### For macOS/Linux:

```bash
# Clone repository
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server

# Run install script
chmod +x install.sh
./install.sh
```

The script will:
1. Check Python version
2. Create virtual environment
3. Install dependencies
4. Guide you through configuration
5. Set up Claude Desktop integration

### For Windows:

```powershell
# Clone repository
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server

# Run install script
.\install.ps1
```

---

## Method 3: Docker

### Quick Start with Docker Compose

```bash
# Clone repository
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
nano .env  # or use any text editor

# Start with Docker Compose
docker-compose up -d
```

### Docker Architecture

```
┌─────────────────────────────────────────────────┐
│             DOCKER SETUP                        │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────┐         ┌─────────────┐     │
│  │ Claude       │         │ Polymarket  │     │
│  │ Desktop      │◄────────┤ MCP         │     │
│  │              │  stdio  │ Container   │     │
│  └──────────────┘         └──────┬──────┘     │
│                                   │             │
│                                   ▼             │
│                            ┌─────────────┐     │
│                            │ Polymarket  │     │
│                            │ API         │     │
│                            └─────────────┘     │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## Method 4: Manual Installation

### Step 1: Clone Repository

```bash
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server
```

### Step 2: Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
# OR
venv\Scripts\activate     # Windows
```

### Step 3: Install Dependencies

```bash
pip install -e .
```

### Step 4: Configure Environment

```bash
# Copy template
cp .env.example .env

# Edit with your values
nano .env
```

**Required variables:**
```env
POLYGON_PRIVATE_KEY=your_key_here_without_0x
POLYGON_ADDRESS=0xYourAddressHere
```

**Optional (recommended):**
```env
MAX_ORDER_SIZE_USD=1000
MAX_TOTAL_EXPOSURE_USD=5000
MAX_POSITION_SIZE_PER_MARKET=2000
```

### Step 5: Configure Claude Desktop

Edit Claude Desktop config file:

**macOS:**
```bash
nano ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Windows:**
```powershell
notepad %APPDATA%\Claude\claude_desktop_config.json
```

**Linux:**
```bash
nano ~/.config/Claude/claude_desktop_config.json
```

Add configuration:
```json
{
  "mcpServers": {
    "polymarket": {
      "command": "/path/to/your/venv/bin/python",
      "args": ["-m", "polymarket_mcp.server"],
      "cwd": "/path/to/polymarket-mcp-server",
      "env": {
        "POLYGON_PRIVATE_KEY": "your_key",
        "POLYGON_ADDRESS": "0xYourAddress"
      }
    }
  }
}
```

### Step 6: Restart Claude Desktop

Close and reopen Claude Desktop to load the MCP server.

---

## Wallet Setup Guide

### Option 1: MetaMask

```
┌─────────────────────────────────────────────────┐
│         METAMASK WALLET SETUP                   │
├─────────────────────────────────────────────────┤
│                                                 │
│  1. Install MetaMask                            │
│     https://metamask.io                         │
│                                                 │
│  2. Create or Import Wallet                     │
│                                                 │
│  3. Switch to Polygon Network                   │
│     Network Name: Polygon Mainnet               │
│     RPC URL: https://polygon-rpc.com            │
│     Chain ID: 137                               │
│     Symbol: MATIC                               │
│                                                 │
│  4. Add USDC Token                              │
│     Contract: 0x2791Bca1f2de4661ED88A30C99A... │
│                                                 │
│  5. Get USDC on Polygon                         │
│     - Bridge from Ethereum                      │
│     - Buy on exchange (Binance, Coinbase)       │
│     - Use fiat on-ramp                          │
│                                                 │
│  6. Export Private Key                          │
│     ⚠️  Keep this SAFE and PRIVATE!            │
│                                                 │
└─────────────────────────────────────────────────┘
```

### Exporting Private Key from MetaMask

```
Step 1: Click on account icon (top right)
Step 2: Account Details
Step 3: Export Private Key
Step 4: Enter password
Step 5: Copy the key (without 0x prefix)
```

**Security Warning:**
```
┌─────────────────────────────────────────────────┐
│  ⚠️  CRITICAL SECURITY WARNINGS                 │
├─────────────────────────────────────────────────┤
│                                                 │
│  ✗ NEVER share your private key                │
│  ✗ NEVER commit it to Git                      │
│  ✗ NEVER store it in cloud storage             │
│  ✗ NEVER send it in messages                   │
│                                                 │
│  ✓ Store in .env file (gitignored)             │
│  ✓ Use environment variables                   │
│  ✓ Consider using a dedicated wallet           │
│  ✓ Start with small amounts                    │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## Claude Desktop Integration

### Configuration File Locations

```
Operating System  │  Config File Location
─────────────────┼──────────────────────────────────────────────
macOS            │  ~/Library/Application Support/Claude/
                 │  claude_desktop_config.json
─────────────────┼──────────────────────────────────────────────
Windows          │  %APPDATA%\Claude\
                 │  claude_desktop_config.json
─────────────────┼──────────────────────────────────────────────
Linux            │  ~/.config/Claude/
                 │  claude_desktop_config.json
```

### Configuration Example

```json
{
  "mcpServers": {
    "polymarket": {
      "command": "/Users/you/polymarket-mcp/venv/bin/python",
      "args": ["-m", "polymarket_mcp.server"],
      "cwd": "/Users/you/polymarket-mcp",
      "env": {
        "POLYGON_PRIVATE_KEY": "abc123...",
        "POLYGON_ADDRESS": "0x123...",
        "MAX_ORDER_SIZE_USD": "1000",
        "MAX_TOTAL_EXPOSURE_USD": "5000"
      }
    }
  }
}
```

### Integration Flow

```
┌─────────────────────────────────────────────────┐
│      CLAUDE DESKTOP INTEGRATION                 │
└─────────────────────────────────────────────────┘

    ┌──────────────┐
    │   Claude     │
    │   Desktop    │
    └──────┬───────┘
           │ Loads config.json
           ▼
    ┌──────────────┐
    │  MCP Server  │
    │  (Python)    │
    └──────┬───────┘
           │ Connects to
           ▼
    ┌──────────────┐
    │  Polymarket  │
    │  API         │
    └──────────────┘
```

---

## Testing Your Setup

### Quick Test

Open Claude Desktop and try:

```
"Show me the top 5 trending markets on Polymarket"
```

Expected response:
```
✓ Server connected
✓ API accessible
✓ Returns market data
```

### Full Test Suite

```bash
# Activate virtual environment
source venv/bin/activate

# Run tests
pytest tests/ -v

# Run demo
python demo_mcp_tools.py
```

### Test Checklist

```
┌─────────────────────────────────────────────────┐
│           TEST CHECKLIST                        │
├─────────────────────────────────────────────────┤
│                                                 │
│  □ Python version 3.10+                        │
│  □ Virtual environment activated                │
│  □ Dependencies installed                       │
│  □ .env file configured                        │
│  □ Claude Desktop config updated                │
│  □ Claude Desktop restarted                     │
│  □ MCP server appears in Claude                 │
│  □ Can fetch market data                        │
│  □ (Full mode) Wallet validated                │
│  □ (Full mode) Can create test order           │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## Troubleshooting

### Common Errors and Solutions

#### Error: "ModuleNotFoundError: No module named 'polymarket_mcp'"

**Solution:**
```bash
# Make sure you installed the package
pip install -e .

# Verify installation
pip list | grep polymarket
```

---

#### Error: "POLYGON_PRIVATE_KEY is required"

**Solution:**
```bash
# Check .env file exists
ls -la .env

# Check it has the key
cat .env | grep POLYGON_PRIVATE_KEY

# Make sure no spaces around =
POLYGON_PRIVATE_KEY=abc123  # ✓ Correct
POLYGON_PRIVATE_KEY = abc123  # ✗ Wrong
```

---

#### Error: "Private key must be 64 hex characters"

**Solution:**
```
1. Remove 0x prefix if present
   Wrong: 0xabc123...
   Right: abc123...

2. Check length is exactly 64 characters

3. Check only hex characters (0-9, a-f)
```

---

#### Error: "Claude Desktop not detecting MCP server"

**Solution Flowchart:**
```
┌─────────────────────────┐
│ Server not detected?    │
└───────┬─────────────────┘
        │
        ▼
┌─────────────────────────┐
│ Is config.json valid?   │
│ Use JSONLint.com        │
└───────┬─────────────────┘
        │ Yes
        ▼
┌─────────────────────────┐
│ Is Python path correct? │
│ Check with: which python│
└───────┬─────────────────┘
        │ Yes
        ▼
┌─────────────────────────┐
│ Did you restart Claude? │
│ Restart = Quit + Open   │
└───────┬─────────────────┘
        │ Yes
        ▼
┌─────────────────────────┐
│ Check Claude logs       │
│ See log locations below │
└─────────────────────────┘
```

**Claude Desktop Log Locations:**
- macOS: `~/Library/Logs/Claude/`
- Windows: `%APPDATA%\Claude\logs\`
- Linux: `~/.config/Claude/logs/`

---

#### Error: "Rate limit exceeded"

**Solution:**
```
The server has built-in rate limiting that respects Polymarket's API limits.

If you see this error:
1. Wait 60 seconds
2. Reduce request frequency
3. Check if you're making parallel requests
```

---

#### Error: "Insufficient funds"

**Solution:**
```
1. Check USDC balance on Polygon:
   https://polygonscan.com/address/YOUR_ADDRESS

2. Get more USDC:
   - Bridge from Ethereum
   - Buy on exchange
   - Use fiat on-ramp

3. Check you're on Polygon network (Chain ID 137)
```

---

### Installation Decision Tree

```
┌────────────────────────────────────────────────────┐
│         INSTALLATION TROUBLESHOOTER                │
└────────────────────────────────────────────────────┘

Start here
    │
    ▼
Are you on macOS/Linux/Windows?
    │
    ├─ macOS/Linux ──► Use install.sh
    │                  OR GUI wizard
    │
    └─ Windows ──────► Use install.ps1
                       OR GUI wizard

    │
    ▼
Do you have Python 3.10+?
    │
    ├─ Yes ──────────► Continue
    │
    └─ No ───────────► Install Python
                       https://python.org

    │
    ▼
Do you have a Polygon wallet?
    │
    ├─ Yes ──────────► Full installation
    │
    └─ No ───────────► Demo mode
                       OR Create wallet first

    │
    ▼
Are you comfortable with terminal?
    │
    ├─ Yes ──────────► Use automated script
    │
    └─ No ───────────► Use GUI wizard

    │
    ▼
Installation complete!
```

---

## Video Tutorials

### Coming Soon

- 🎥 Complete installation walkthrough (10 minutes)
- 🎥 Wallet setup guide (5 minutes)
- 🎥 First trade tutorial (8 minutes)
- 🎥 Safety configuration best practices (6 minutes)

**Subscribe for updates:**
- YouTube: [Placeholder]
- Twitter: @caiovicentino

---

## Getting Help

### Support Channels

```
┌─────────────────────────────────────────────────┐
│              GET HELP                           │
├─────────────────────────────────────────────────┤
│                                                 │
│  📖 Documentation                               │
│     - README.md                                 │
│     - FAQ.md                                    │
│     - TOOLS_REFERENCE.md                        │
│                                                 │
│  💬 Community                                   │
│     - GitHub Discussions                        │
│     - Telegram (Renda Cripto)                   │
│     - Discord (Yield Hacker)                    │
│                                                 │
│  🐛 Bug Reports                                 │
│     - GitHub Issues                             │
│     - Include: OS, Python version, error log    │
│                                                 │
│  ✉️  Direct Support                            │
│     - GitHub: @caiovicentino                    │
│     - Email: support@example.com                │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## Next Steps

After successful installation:

1. **Read the FAQ** - Common questions answered
2. **Review TOOLS_REFERENCE.md** - Learn all 45 tools
3. **Check USAGE_EXAMPLES.py** - See example code
4. **Join the community** - Connect with other users
5. **Start small** - Test with small amounts first
6. **Provide feedback** - Help us improve!

---

## Quick Reference

### Essential Commands

```bash
# Start virtual environment
source venv/bin/activate

# Update package
pip install -e . --upgrade

# Run tests
pytest

# Check configuration
python -c "from polymarket_mcp.config import load_config; print(load_config().to_dict())"

# View logs
tail -f ~/.config/Claude/logs/mcp*.log
```

### Important Files

```
polymarket-mcp/
├── .env                    # Your configuration
├── setup_wizard.py         # GUI setup tool
├── README.md              # Main documentation
├── FAQ.md                 # Common questions
├── VISUAL_INSTALL_GUIDE.md # This file
└── src/
    └── polymarket_mcp/
        ├── server.py       # MCP server
        └── config.py       # Configuration
```

---

**Made with ❤️ by [Caio Vicentino](https://github.com/caiovicentino)**

*Ready to trade prediction markets with AI!* 🚀
