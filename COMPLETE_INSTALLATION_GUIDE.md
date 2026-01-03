# Complete Installation Guide - All Issues Resolved

## Overview

This document provides a comprehensive guide to installing and configuring the Polymarket MCP Server, including all compatibility issues encountered and their solutions.

---

## Critical Issues Encountered & Solutions

### Issue 1: System Package Conflict - typing_extensions

**Problem:**
```
ERROR: Cannot install polymarket-mcp-0.1.0
- typing-extensions 4.10.0 (system)
  conflicts with required: typing_extensions>=4.12.2 (package)
```

**Root Cause:**
- WSL2 Ubuntu 24.04 Python 3.12.3 comes with `typing_extensions-4.10.0` bundled in `/usr/lib/python3/dist-packages/`
- pip cannot override system packages inside virtualenv
- System packages are read-only to pip

**Solution:**
1. Create a clean virtualenv with Python 3.12.3
2. Upgrade typing_extensions to 4.15.0 in the virtualenv
3. Use PYTHONPATH override to prioritize virtualenv packages

**Commands:**
```bash
# Create clean virtualenv
python3.12 -m venv /home/vic/polymarket-clean-venv

# Activate virtualenv
source /home/vic/polymarket-clean-venv/bin/activate

# Upgrade typing_extensions
pip install --upgrade typing_extensions

# Install with PYTHONPATH override
PYTHONPATH=/home/vic/polymarket-clean-venv/lib/python3.12/site-packages:$PYTHONPATH pip install -e .
```

**Alternative Solution (requires sudo):**
```bash
sudo rm -rf /usr/lib/python3/dist-packages/typing_extensions*
```

---

### Issue 2: Python Path Priority

**Problem:**
System packages were being loaded before virtualenv packages, causing version conflicts.

**Root Cause:**
Python's sys.path had `/usr/lib/python3/dist-packages` before the virtualenv site-packages.

**Solution:**
Create a helper script that sets PYTHONPATH to prioritize virtualenv packages.

**Helper Script (`run_with_env.sh`):**
```bash
#!/bin/bash

cd /home/vic/polymarket-mcp-server
source /home/vic/polymarket-clean-venv/bin/activate
export PYTHONPATH=/home/vic/polymarket-clean-venv/lib/python3.12/site-packages:$PYTHONPATH
"$@"
```

---

### Issue 3: OpenCode Integration

**Problem:**
OpenCode configuration was using wrong Python interpreter path.

**Root Cause:**
Configuration pointed to Python 3.13.5 instead of the virtualenv with Python 3.12.3.

**Solution:**
Update `~/.config/opencode/opencode.json` to use the helper script.

**Before:**
```json
"polymarket": {
  "type": "local",
  "enabled": true,
  "command": [
    "/home/vic/.pyenv/versions/3.13.5/bin/python",
    "/home/vic/polymarket-mcp-server/run_opencode_mcp.py"
  ]
}
```

**After:**
```json
"polymarket": {
  "type": "local",
  "enabled": true,
  "command": [
    "/home/vic/polymarket-mcp-server/run_with_env.sh",
    "python3",
    "/home/vic/polymarket-mcp-server/run_opencode_mcp.py"
  ]
}
```

---

### Issue 4: Installation Timeout

**Problem:**
Full installation with dependencies timed out due to large package downloads.

**Solution:**
Install in two steps:
1. Install package without dependencies
2. Install dependencies separately

**Commands:**
```bash
# Install package without dependencies
pip install --no-deps -e .

# Install dependencies
pip install eth-account fastapi httpx jinja2 mcp py-clob-client pydantic-settings pydantic python-dotenv uvicorn websockets
```

---

## Complete Installation Procedure

### Step 1: Create Virtual Environment

```bash
# Create virtualenv with Python 3.12.3
python3.12 -m venv /home/vic/polymarket-clean-venv

# Activate virtualenv
source /home/vic/polymarket-clean-venv/bin/activate

# Verify Python version
python --version  # Should be 3.12.3
```

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
git clone https://github.com/vicmuchina/polymarket-mcp-server-fix.git
cd polymarket-mcp-server-fix
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

## OpenCode Integration

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

OpenCode should now show the Polymarket MCP with 25 tools available.

---

## Quick Start Commands

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

### Interactive Python

```bash
./run_with_env.sh python3
```

---

## Configuration Options

### Demo Mode (Read-Only)

Default configuration works out of the box:
- No API credentials required
- No wallet required
- 25 tools available (Discovery, Analysis, Real-time)

### Full Trading Mode

To enable trading and portfolio management:

1. Get a real Polygon wallet funded with USDC
2. Create API credentials at https://polymarket.com/settings/api
3. Update `.env` file:

```
DEMO_MODE=false
POLYGON_PRIVATE_KEY=your_private_key
POLYGON_ADDRESS=your_wallet_address
POLYMARKET_API_KEY=your_api_key
POLYMARKET_PASSPHRASE=your_passphrase
POLYMARKET_API_KEY_NAME=your_key_name
```

4. Restart server

---

## Troubleshooting

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

## File Structure

```
/home/vic/polymarket-mcp-server/
├── src/polymarket_mcp/
│   ├── server.py              # Main MCP server
│   ├── config.py              # Configuration management
│   ├── auth/                  # Authentication & client
│   ├── tools/                 # MCP tools
│   ├── utils/                 # Utilities
│   └── web/                   # Web dashboard
├── .env                       # Environment configuration
├── .env.example               # Example configuration
├── run_with_env.sh            # Helper script (NEW)
├── run_opencode_mcp.py        # Server entry point
├── test_server_init.py        # Initialization test (NEW)
├── smoke_test.py              # Validation tests
└── COMPLETE_INSTALLATION_GUIDE.md  # This file
```

---

## Environment Variables

### Required for Demo Mode

```
DEMO_MODE=true
```

### Required for Full Trading Mode

```
DEMO_MODE=false
POLYGON_PRIVATE_KEY=your_private_key
POLYGON_ADDRESS=your_wallet_address
POLYMARKET_API_KEY=your_api_key
POLYMARKET_PASSPHRASE=your_passphrase
POLYMARKET_API_KEY_NAME=your_key_name
```

### Optional Configuration

```
MAX_ORDER_SIZE_USD=1000
MAX_TOTAL_EXPOSURE_USD=5000
MAX_POSITION_SIZE_PER_MARKET=2000
MIN_LIQUIDITY_REQUIRED=10000
MAX_SPREAD_TOLERANCE=0.05
ENABLE_AUTONOMOUS_TRADING=false
REQUIRE_CONFIRMATION_ABOVE_USD=500
AUTO_CANCEL_ON_LARGE_SPREAD=true
LOG_LEVEL=INFO
```

---

## Available Tools

### Market Discovery (8 tools)
- Search markets
- Get market details
- List active markets
- Filter by category
- Sort by liquidity/volume
- Get market prices
- Get market odds
- Get market metadata

### Market Analysis (10 tools)
- Analyze market trends
- Get price history
- Calculate implied probability
- Get order book
- Get trade history
- Analyze liquidity
- Get market statistics
- Compare markets
- Get market depth
- Analyze spread

### Real-time (7 tools)
- Subscribe to market updates
- Get live prices
- Monitor order book changes
- Track trade activity
- Get WebSocket status
- Manage subscriptions
- Get real-time statistics

### Trading (12 tools) - Requires API Credentials
- Place orders
- Cancel orders
- Get order status
- Get order history
- Manage positions
- Get portfolio value
- Get profit/loss
- Get trading statistics

### Portfolio Management (8 tools) - Requires API Credentials
- Get portfolio overview
- Get position details
- Get transaction history
- Get balance
- Get performance metrics
- Get risk analysis
- Get allocation
- Get recommendations

---

## Summary

### Critical Points

1. **Always use Python 3.12.3** - Not 3.13.5 or system Python
2. **Always use the helper script** - `run_with_env.sh`
3. **typing_extensions must be 4.12.2+** - Upgrade if needed
4. **PYTHONPATH must prioritize virtualenv** - Use helper script
5. **OpenCode config must use helper script** - Not direct Python path

### What to Avoid

❌ Using system Python
❌ Using Python 3.13.5
❌ Installing without virtualenv
❌ Not upgrading typing_extensions
❌ Direct Python path in OpenCode config
❌ Skipping smoke tests

### Best Practices

✅ Always use `run_with_env.sh`
✅ Always use Python 3.12.3 virtualenv
✅ Always verify installation with smoke tests
✅ Always test server initialization
✅ Always check Python path priority
✅ Always use helper script in OpenCode config

---

## Support

- **Documentation**: See README.md in project directory
- **Issues**: Check GitHub repository
- **API Docs**: https://docs.polymarket.com

---

## Version Information

- **Polymarket MCP Server**: v0.1.0
- **Python**: 3.12.3
- **typing_extensions**: 4.15.0
- **mcp**: 1.25.0
- **fastapi**: 0.128.0

---

**Last Updated**: January 3, 2026
**Installation Status**: ✅ Complete and Operational