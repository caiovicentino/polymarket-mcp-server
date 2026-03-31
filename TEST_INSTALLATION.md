# Installation Testing Guide

Complete guide for testing the Polymarket MCP Server installation scripts.

## Quick Reference

### Installation Methods

| Method | Command | Use Case |
|--------|---------|----------|
| **Full Interactive** | `./install.sh` | Production setup with wallet |
| **DEMO Mode** | `./install.sh --demo` | Testing without wallet |
| **Quick Start** | `./quickstart.sh` | One-click DEMO installation |
| **Windows** | `install.bat` | Windows users |
| **Uninstall** | `./uninstall.sh` | Clean removal |

---

## Test Plan

### 1. Fresh Installation Test (macOS/Linux)

**Objective:** Verify clean installation from scratch

**Steps:**
```bash
# 1. Clone repository (or use existing)
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server

# 2. Run installer
./install.sh --demo

# Expected output:
# [1/7] Checking Python version... ✓ Python 3.12 found
# [2/7] Creating virtual environment... ✓ Created
# [3/7] Installing dependencies... ✓ Installed (X packages)
# [4/7] Configuration... ✓ DEMO mode configured
# [5/7] Configuring Claude Desktop... ✓ Config updated
# [6/7] Testing installation... ✓ Package import works
# [7/7] Installation complete!
```

**Verification:**
```bash
# Check files created
ls -la venv/          # Virtual environment exists
ls -la .env           # Environment file created
cat .env | grep DEMO  # DEMO_MODE=true present

# Check Claude Desktop config
cat ~/Library/Application\ Support/Claude/claude_desktop_config.json
# Should contain "polymarket" server entry

# Test Python import
source venv/bin/activate
python -c "import polymarket_mcp; print('✓ Import successful')"
```

**Expected Results:**
- ✅ Virtual environment created
- ✅ All dependencies installed
- ✅ .env file created with DEMO_MODE=true
- ✅ Claude Desktop config updated
- ✅ Package imports successfully

---

### 2. Full Installation Test (with Wallet)

**Objective:** Test production installation with credentials

**Steps:**
```bash
# Clean previous installation
./uninstall.sh --force

# Run full installation
./install.sh

# Follow prompts:
# - "Do you have a Polygon wallet?" → y
# - Enter private key (64 hex chars)
# - Enter wallet address (0x...)
# - Configure safety limits → y
# - Set limits as desired
```

**Verification:**
```bash
# Check .env contains real credentials
cat .env | grep -E "POLYGON_PRIVATE_KEY|POLYGON_ADDRESS"
# Should show your actual credentials (not demo values)

# Check DEMO_MODE is false or absent
cat .env | grep DEMO
# Should not show DEMO_MODE=true

# Check safety limits
cat .env | grep MAX_ORDER_SIZE_USD
```

**Expected Results:**
- ✅ .env contains real wallet credentials
- ✅ Safety limits configured
- ✅ DEMO_MODE not enabled
- ✅ Trading functions available

---

### 3. Windows Installation Test

**Objective:** Verify Windows batch script works

**Steps (on Windows):**
```batch
REM Download repository
git clone https://github.com/joe67-67/polymarket-mcp-server.git
cd polymarket-mcp-server

REM Run installer in DEMO mode
install.bat /demo

REM Expected flow:
REM [1/7] Checking Python version...
REM [2/7] Creating virtual environment...
REM [3/7] Installing dependencies...
REM [4/7] Configuration...
REM [5/7] Configuring Claude Desktop...
REM [6/7] Testing installation...
REM [7/7] Installation complete!
```

**Verification:**
```batch
REM Check files
dir venv
dir .env
type .env | findstr DEMO

REM Check Claude config
type %APPDATA%\Claude\claude_desktop_config.json

REM Test import
venv\Scripts\activate
python -c "import polymarket_mcp"
```

**Expected Results:**
- ✅ Windows batch script completes successfully
- ✅ Virtual environment created
- ✅ .env configured for DEMO mode
- ✅ Claude Desktop config updated (Windows path)

---

### 4. Quick Start Test

**Objective:** Verify one-liner installation

**Steps:**
```bash
# Method 1: Download and run
curl -sSL https://raw.githubusercontent.com/joe67-67/polymarket-mcp-server/main/quickstart.sh | bash

# Method 2: Local run
./quickstart.sh
```

**Verification:**
```bash
# Check installation completed
cd ~/polymarket-mcp-server  # Default location
source venv/bin/activate
python -c "import polymarket_mcp; print('✓ Quick start successful')"
```

**Expected Results:**
- ✅ Repository cloned to ~/polymarket-mcp-server
- ✅ Installation runs automatically in DEMO mode
- ✅ Ready to use without manual configuration

---

### 5. Uninstall Test

**Objective:** Verify clean uninstallation

**Steps:**
```bash
# Run uninstall
./uninstall.sh

# Confirm when prompted
# y
```

**Verification:**
```bash
# Check files removed
ls -la venv/          # Should not exist
ls -la .env           # Should not exist (backup created)
ls -la .env.backup    # Backup should exist

# Check Claude config
cat ~/Library/Application\ Support/Claude/claude_desktop_config.json
# "polymarket" entry should be removed

# Check backup exists
ls -la ~/Library/Application\ Support/Claude/claude_desktop_config.json.backup
```

**Expected Results:**
- ✅ Virtual environment removed
- ✅ .env backed up to .env.backup
- ✅ Claude Desktop config cleaned (with backup)
- ✅ Cache files removed
- ✅ Source code preserved

---

### 6. Reinstallation Test

**Objective:** Verify installation after uninstall

**Steps:**
```bash
# Uninstall
./uninstall.sh --force

# Reinstall
./install.sh --demo

# Should work without errors
```

**Expected Results:**
- ✅ Clean reinstallation works
- ✅ No conflicts from previous installation
- ✅ All components recreated successfully

---

### 7. DEMO Mode Functionality Test

**Objective:** Verify DEMO mode works correctly

**Steps:**
```bash
# Install in DEMO mode
./install.sh --demo

# Activate environment
source venv/bin/activate

# Test DEMO mode config loads
python << 'PYEOF'
from polymarket_mcp.config import load_config

config = load_config()
print(f"DEMO_MODE: {config.DEMO_MODE}")
print(f"Address: {config.POLYGON_ADDRESS}")
print(f"Key (first 10 chars): {config.POLYGON_PRIVATE_KEY[:10]}")

assert config.DEMO_MODE == True, "DEMO_MODE should be True"
assert config.POLYGON_ADDRESS == "0x0000000000000000000000000000000000000001", "Should use demo address"
print("✓ DEMO mode configuration valid")
PYEOF
```

**Expected Results:**
- ✅ DEMO_MODE=True
- ✅ Demo wallet address used
- ✅ No validation errors
- ✅ Config loads successfully

---

### 8. Claude Desktop Integration Test

**Objective:** Verify MCP server works in Claude Desktop

**Prerequisites:**
- Claude Desktop installed
- Installation completed

**Steps:**

1. **Restart Claude Desktop**
   ```bash
   # macOS
   killall "Claude Desktop" 2>/dev/null || true
   open -a "Claude Desktop"
   ```

2. **Check MCP Server Status in Claude**
   - Open Claude Desktop
   - Look for connection indicators
   - Check developer tools for errors (if available)

3. **Test Market Discovery**

   Ask Claude:
   ```
   Show me the top 5 trending Polymarket markets in the last 24 hours
   ```

   Expected response:
   - ✅ Claude accesses Polymarket data
   - ✅ Returns market information
   - ✅ No authentication errors

4. **Test Market Analysis**

   Ask Claude:
   ```
   Analyze market opportunities in crypto prediction markets
   ```

   Expected response:
   - ✅ AI-powered analysis runs
   - ✅ Market data retrieved
   - ✅ Recommendations provided

5. **Test DEMO Mode Restrictions** (if in DEMO mode)

   Ask Claude:
   ```
   Buy $100 of YES tokens in market xyz
   ```

   Expected response:
   - ✅ Claude explains trading is disabled in DEMO mode
   - ✅ Suggests switching to full mode
   - ✅ No attempt to execute trade

**Expected Results:**
- ✅ MCP server connects to Claude Desktop
- ✅ Market discovery tools work
- ✅ Analysis tools work
- ✅ Trading restrictions enforced in DEMO mode

---

### 9. Error Handling Test

**Objective:** Verify installer handles errors gracefully

**Test Cases:**

#### Test 9.1: Invalid Python Version
```bash
# If you have Python 3.9 or older
python3.9 -m venv test_venv
./install.sh
# Should error with: "Python X.X found, but 3.10+ required"
```

#### Test 9.2: Invalid Private Key
```bash
./install.sh
# When prompted for private key, enter invalid value:
# "invalid"
# Should error: "Invalid private key format (must be 64 hex characters)"
```

#### Test 9.3: Invalid Wallet Address
```bash
./install.sh
# Enter valid private key
# Enter invalid address: "0xinvalid"
# Should error: "Invalid address format"
```

#### Test 9.4: No Internet Connection
```bash
# Disconnect from internet
./install.sh --demo
# Should warn: "Could not reach Polymarket API (check internet connection)"
# But installation should still complete
```

**Expected Results:**
- ✅ Clear error messages
- ✅ Validation prevents invalid input
- ✅ Rollback on critical errors
- ✅ Helpful suggestions for fixes

---

### 10. Multiple Installation Test

**Objective:** Test multiple simultaneous installations

**Steps:**
```bash
# Install in multiple directories
mkdir ~/poly-test-1
cd ~/poly-test-1
git clone https://github.com/joe67-67/polymarket-mcp-server.git .
./install.sh --demo

mkdir ~/poly-test-2
cd ~/poly-test-2
git clone https://github.com/joe67-67/polymarket-mcp-server.git .
./install.sh --demo
```

**Expected Results:**
- ✅ Both installations work independently
- ✅ Claude Desktop config contains both entries (or overwrites)
- ✅ No conflicts between installations

---

## Common Issues and Solutions

### Issue 1: Permission Denied
```bash
# Error: ./install.sh: Permission denied
# Fix:
chmod +x install.sh
./install.sh
```

### Issue 2: Python Not Found
```bash
# Error: Python not found
# Fix (macOS):
brew install python@3.12

# Fix (Linux):
sudo apt update
sudo apt install python3.12
```

### Issue 3: Claude Desktop Config Not Updated
```bash
# Check if config file exists
ls -la ~/Library/Application\ Support/Claude/claude_desktop_config.json

# If not, Claude Desktop might not be installed
# Or config directory doesn't exist
mkdir -p ~/Library/Application\ Support/Claude
```

### Issue 4: Module Import Fails
```bash
# Error: ModuleNotFoundError: No module named 'polymarket_mcp'
# Fix: Ensure virtual environment is activated
source venv/bin/activate

# Reinstall package
pip install -e .
```

### Issue 5: DEMO Mode Not Working
```bash
# Check .env file
cat .env | grep DEMO_MODE

# Should show: DEMO_MODE=true
# If not, edit .env and add it manually
echo "DEMO_MODE=true" >> .env
```

---

## Automation Testing Script

Create a comprehensive test runner:

```bash
#!/bin/bash
# test_installation.sh - Automated installation testing

echo "Running installation tests..."

# Test 1: DEMO installation
echo "[Test 1] DEMO installation..."
./install.sh --demo
if [ $? -eq 0 ]; then echo "✓ PASSED"; else echo "✗ FAILED"; fi

# Test 2: Uninstall
echo "[Test 2] Uninstall..."
./uninstall.sh --force
if [ $? -eq 0 ]; then echo "✓ PASSED"; else echo "✗ FAILED"; fi

# Test 3: Reinstall
echo "[Test 3] Reinstall..."
./install.sh --demo
if [ $? -eq 0 ]; then echo "✓ PASSED"; else echo "✗ FAILED"; fi

# Test 4: Config validation
echo "[Test 4] Config validation..."
source venv/bin/activate
python -c "from polymarket_mcp.config import load_config; load_config()"
if [ $? -eq 0 ]; then echo "✓ PASSED"; else echo "✗ FAILED"; fi

echo "All tests completed!"
```

---

## Performance Benchmarks

Expected installation times:

| Platform | Installation Type | Time |
|----------|------------------|------|
| macOS M1 | DEMO mode | ~30s |
| macOS Intel | DEMO mode | ~45s |
| Linux Ubuntu | DEMO mode | ~40s |
| Windows 11 | DEMO mode | ~60s |
| macOS M1 | Full + config | ~45s |

---

## Checklist for Release

Before releasing installation scripts:

- [ ] Test on macOS (Intel & Apple Silicon)
- [ ] Test on Linux (Ubuntu 22.04+)
- [ ] Test on Windows (10/11)
- [ ] Test with Python 3.10, 3.11, 3.12
- [ ] Test DEMO mode
- [ ] Test full installation with wallet
- [ ] Test uninstall and reinstall
- [ ] Test Claude Desktop integration
- [ ] Test error handling
- [ ] Update documentation
- [ ] Create video walkthrough (optional)

---

## Support

If tests fail:

1. Check Python version: `python --version`
2. Check permissions: `ls -la install.sh`
3. Check internet connection: `curl -I https://pypi.org`
4. Check logs: Review terminal output
5. Report issue: https://github.com/joe67-67/polymarket-mcp-server/issues

---

**Testing Status:** ✅ Ready for Testing

Last Updated: 2025-01-11
