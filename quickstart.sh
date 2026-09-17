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

# -----------------------------------------------------------------------------
# Prompt safety (T-0224): every interactive prompt reads from the CONTROLLING
# TERMINAL (/dev/tty), never from stdin. Under `curl ... | bash`, stdin IS the
# script stream itself — a stdin read consumes (or is starved by) the very
# bytes bash is parsing (proven pre-fix: the bare `read` swallowed the next
# script line and the `read -n 1` stole a byte, killing the script with
# "cho: command not found" on a fresh machine); under `bash quickstart.sh <
# /dev/null` (CI) a bare `read` dies on EOF under `set -e`. /dev/tty reaches
# the human in both cases. When no controlling terminal exists (curl|bash
# without a ctty, CI, cron, headless), each prompt falls back to a SAFE
# default instead of dying:
#   - install confirmation: proceed (DEMO mode, read-only trading);
#   - "remove and reinstall?": NO — `rm -rf` NEVER runs non-interactively.
# -----------------------------------------------------------------------------

# has_controlling_tty: succeeds iff /dev/tty can be opened right now. The
# probe runs in a subshell so it never touches the caller's stdin.
has_controlling_tty() {
    ( : 2>/dev/null < /dev/tty )
}

# tty_read_line: read one line from /dev/tty into REPLY. Without a TTY,
# print the non-interactive banner and continue with an empty REPLY.
tty_read_line() {
    if has_controlling_tty; then
        read -r REPLY < /dev/tty
    else
        echo "non-interactive: proceeding with installation"
        REPLY=""
    fi
}

# tty_read_yn: read a single y/n character from /dev/tty into REPLY.
# Without a TTY, default to "n" so the destructive `rm -rf` below NEVER
# runs non-interactively (the existing directory is kept and reused).
tty_read_yn() {
    if has_controlling_tty; then
        printf '%s' "$1"
        local reply
        read -r -n 1 reply < /dev/tty
        REPLY="$reply"
    else
        echo "non-interactive: keeping existing installation directory"
        REPLY="n"
    fi
}

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
tty_read_line

# Check if we're in the repo directory
if [ ! -f "pyproject.toml" ]; then
    echo "Cloning repository..."
    REPO_URL="https://github.com/caiovicentino/polymarket-mcp-server.git"
    INSTALL_DIR="$HOME/polymarket-mcp-server"

    if [ -d "$INSTALL_DIR" ]; then
        echo "Directory already exists: $INSTALL_DIR"
        tty_read_yn "Remove and reinstall? (y/n): "
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
