# Quick Reference Card

One-page reference for Polymarket MCP Server installation and usage.

## Installation (Choose One)

```bash
# Fastest: One-command DEMO mode
curl -sSL https://raw.githubusercontent.com/joe67-67/polymarket-mcp-server/main/quickstart.sh | bash

# DEMO mode (local)
./install.sh --demo

# Full trading mode
./install.sh

# Windows
install.bat
```

## First Use

After installation:
1. Restart Claude Desktop
2. Ask: "Show me trending Polymarket markets"

## DEMO vs Full Mode

| Feature | DEMO | Full |
|---------|------|------|
| Market Search | ✓ | ✓ |
| Analysis | ✓ | ✓ |
| Trading | ✗ | ✓ |
| Portfolio | ✗ | ✓ |

## Common Commands

```bash
# Install
./install.sh              # Interactive
./install.sh --demo       # DEMO mode
./install.sh --skip-claude  # Skip Claude config

# Uninstall
./uninstall.sh            # Interactive
./uninstall.sh --force    # No confirmation

# Upgrade
git pull origin main
pip install -e . --upgrade
```

## Example Queries

### Market Discovery
```
Show me trending markets
Find crypto prediction markets
What markets close in 24 hours?
```

### Market Analysis
```
Analyze the [market name] opportunity
Compare these 3 markets
What's the orderbook for [token_id]?
```

### Trading (Full Mode Only)
```
Buy $100 YES in [market_id]
Show my positions
What's my portfolio value?
Cancel all open orders
```

## Configuration

### DEMO Mode
```env
DEMO_MODE=true
```

### Full Mode
```env
DEMO_MODE=false
POLYGON_PRIVATE_KEY=your_key_without_0x
POLYGON_ADDRESS=0xYourAddress
MAX_ORDER_SIZE_USD=1000
```

## Troubleshooting

### Python Not Found
```bash
# macOS
brew install python@3.12

# Linux
sudo apt install python3.12
```

### Permission Denied
```bash
chmod +x install.sh
./install.sh
```

### Module Not Found
```bash
source venv/bin/activate
pip install -e .
```

### Claude Not Connecting
1. Check config: `~/Library/Application Support/Claude/claude_desktop_config.json`
2. Restart Claude Desktop
3. Look for "polymarket" in server list

## File Locations

| File | Location |
|------|----------|
| Config (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Config (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Config (Linux) | `~/.config/Claude/claude_desktop_config.json` |
| Environment | `.env` (project root) |
| Virtual Env | `venv/` (project root) |

## Safety Limits

Default safe limits:
```env
MAX_ORDER_SIZE_USD=1000          # Per order
MAX_TOTAL_EXPOSURE_USD=5000      # Total
MAX_POSITION_SIZE_PER_MARKET=2000  # Per market
REQUIRE_CONFIRMATION_ABOVE_USD=500  # Confirm first
```

## Support

- Issues: https://github.com/joe67-67/polymarket-mcp-server/issues
- Docs: [INSTALLATION.md](INSTALLATION.md)
- Tests: [TEST_INSTALLATION.md](TEST_INSTALLATION.md)

## Security

- Never commit `.env` to git
- Keep private key secure
- Start with small amounts
- Monitor positions regularly
- Never risk more than you can lose

---

**Installation time:** 30-60 seconds | **First query time:** <2 minutes

Print this card for quick reference!
