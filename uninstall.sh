#!/bin/bash

################################################################################
# Polymarket MCP Server - Uninstall Script
#
# Safely removes the Polymarket MCP Server installation
#
# Usage:
#   ./uninstall.sh           # Interactive uninstall
#   ./uninstall.sh --force   # Uninstall without confirmation
#
# Author: Caio Vicentino
# GitHub: https://github.com/caiovicentino/polymarket-mcp-server
################################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

FORCE_MODE=false
INSTALL_DIR=$(pwd)
VENV_DIR="$INSTALL_DIR/venv"

print_header() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${CYAN}ℹ${NC} $1"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --force)
            FORCE_MODE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: ./uninstall.sh [--force]"
            exit 1
            ;;
    esac
done

# Detect OS
case "$OSTYPE" in
    darwin*)
        OS="macOS"
        CONFIG_DIR="$HOME/Library/Application Support/Claude"
        ;;
    linux*)
        OS="Linux"
        CONFIG_DIR="$HOME/.config/Claude"
        ;;
    msys*|cygwin*)
        OS="Windows"
        CONFIG_DIR="$APPDATA/Claude"
        ;;
    *)
        OS="Unknown"
        CONFIG_DIR=""
        ;;
esac

CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"

# Show banner
clear
print_header "Polymarket MCP Server - Uninstall"

echo "This will remove:"
echo "  • Virtual environment ($VENV_DIR)"
echo "  • Environment file (.env)"
echo "  • Claude Desktop configuration (polymarket entry)"
echo "  • Cached Python files (__pycache__, *.pyc)"
echo ""
echo -e "${YELLOW}Note: This will NOT remove:${NC}"
echo "  • Source code files"
echo "  • Documentation"
echo "  • Your wallet or private keys"
echo ""

if [ "$FORCE_MODE" != true ]; then
    read -p "Continue with uninstallation? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Uninstallation cancelled."
        exit 0
    fi
    echo ""
fi

# Step 1: Remove virtual environment
echo "Removing virtual environment..."
if [ -d "$VENV_DIR" ]; then
    rm -rf "$VENV_DIR"
    print_success "Virtual environment removed"
else
    print_info "Virtual environment not found (already removed?)"
fi

# Step 2: Remove .env file
echo "Removing environment file..."
if [ -f ".env" ]; then
    # Backup before removing
    if [ -f ".env.backup" ]; then
        mv .env.backup ".env.backup.$(date +%s)"
    fi
    mv .env .env.backup
    print_success "Environment file backed up to .env.backup"
else
    print_info "Environment file not found (already removed?)"
fi

# Step 3: Remove Claude Desktop config
echo "Removing Claude Desktop configuration..."
if [ -f "$CONFIG_FILE" ]; then
    # Backup config
    cp "$CONFIG_FILE" "${CONFIG_FILE}.backup"

    # Remove polymarket entry using Python
    python3 - "$CONFIG_FILE" << 'PYEOF' || true
import json
import sys

config_file = sys.argv[1]

try:
    with open(config_file, 'r') as f:
        config = json.load(f)

    if 'mcpServers' in config and 'polymarket' in config['mcpServers']:
        del config['mcpServers']['polymarket']

        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)

        print("✓ Removed polymarket from Claude Desktop config")
    else:
        print("ℹ Polymarket not found in Claude Desktop config")

except Exception as e:
    print(f"⚠ Could not modify config: {e}")
    sys.exit(0)
PYEOF

    print_info "Config backup saved to ${CONFIG_FILE}.backup"
else
    print_info "Claude Desktop config not found"
fi

# Step 4: Clean Python cache
echo "Cleaning Python cache files..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type f -name "*.pyo" -delete 2>/dev/null || true
find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
print_success "Cache files removed"

# Step 5: Remove build artifacts
echo "Removing build artifacts..."
if [ -d "build" ]; then
    rm -rf build
fi
if [ -d "dist" ]; then
    rm -rf dist
fi
if [ -d ".pytest_cache" ]; then
    rm -rf .pytest_cache
fi
print_success "Build artifacts removed"

# Summary
echo ""
print_header "✓ Uninstallation Complete"

echo "Removed components:"
echo "  ✓ Virtual environment"
echo "  ✓ Environment configuration"
echo "  ✓ Claude Desktop integration"
echo "  ✓ Cache files"
echo ""

echo "Backup files created:"
if [ -f ".env.backup" ]; then
    echo "  • .env.backup"
fi
if [ -f "${CONFIG_FILE}.backup" ]; then
    echo "  • ${CONFIG_FILE}.backup"
fi
echo ""

echo -e "${CYAN}To reinstall:${NC}"
echo "  ./install.sh              # Full installation"
echo "  ./install.sh --demo       # DEMO mode"
echo ""

echo -e "${CYAN}To completely remove the project:${NC}"
echo "  cd .. && rm -rf $(basename $INSTALL_DIR)"
echo ""

echo -e "${YELLOW}Don't forget to restart Claude Desktop!${NC}"
echo ""
