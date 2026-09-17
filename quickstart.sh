#!/bin/bash

################################################################################
# Polymarket MCP Server - Quick Start Script
#
# One-liner to get started with Polymarket MCP Server in DEMO mode
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/caiovicentino/polymarket-mcp-server/main/quickstart.sh | bash
#
# Or download and run locally:
#   ./quickstart.sh
#
# Author: Caio Vicentino
# GitHub: https://github.com/caiovicentino/polymarket-mcp-server
################################################################################

set -e

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${CYAN}"
cat << "EOF"
  ____        _                          _        _
 |  _ \ ___ | |_   _ _ __ ___   __ _ _ __| | _____| |_
 | |_) / _ \| | | | | '_ ` _ \ / _` | '__| |/ / _ \ __|
 |  __/ (_) | | |_| | | | | | | (_| | |  |   <  __/ |_
 |_|   \___/|_|\__, |_| |_| |_|\__,_|_|  |_|\_\___|\__|
               |___/
  __  __  ____ ____    ____
 |  \/  |/ ___|  _ \  / ___|  ___ _ ____   _____ _ __
 | |\/| | |   | |_) | \___ \ / _ \ '__\ \ / / _ \ '__|
 | |  | | |___|  __/   ___) |  __/ |   \ V /  __/ |
 |_|  |_|\____|_|     |____/ \___|_|    \_/ \___|_|

EOF
echo -e "${NC}"

echo -e "${CYAN}Quick Start - DEMO Mode Installation${NC}"
echo ""
echo "This will install Polymarket MCP Server in DEMO mode:"
echo "  ✓ Market discovery and analysis"
echo "  ✓ Real-time monitoring"
echo "  ✗ Trading (read-only mode)"
echo ""
echo -e "${YELLOW}Press Ctrl+C to cancel, or Enter to continue...${NC}"
read

# Check if we're in the repo directory
if [ ! -f "pyproject.toml" ]; then
    echo "Cloning repository..."
    REPO_URL="https://github.com/caiovicentino/polymarket-mcp-server.git"
    INSTALL_DIR="$HOME/polymarket-mcp-server"

    if [ -d "$INSTALL_DIR" ]; then
        echo "Directory already exists: $INSTALL_DIR"
        read -p "Remove and reinstall? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$INSTALL_DIR"
        else
            cd "$INSTALL_DIR"
        fi
    fi

    if [ ! -d "$INSTALL_DIR" ]; then
        git clone "$REPO_URL" "$INSTALL_DIR"
        cd "$INSTALL_DIR"
    fi
else
    echo "Using current directory..."
fi

# Make install script executable if needed
if [ ! -x "install.sh" ]; then
    chmod +x install.sh
fi

# Run installation in DEMO mode
echo ""
echo -e "${GREEN}Starting installation...${NC}"
echo ""

./install.sh --demo

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Quick Start Complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "Next: Restart Claude Desktop and try:"
echo "  'Show me trending Polymarket markets'"
echo ""
