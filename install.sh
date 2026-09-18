#!/bin/bash

################################################################################
# Polymarket MCP Server - Automated Installation Script
#
# This script automates the installation and configuration of the Polymarket
# MCP Server for Claude Desktop integration.
#
# Usage:
#   ./install.sh              # Interactive installation
#   ./install.sh --demo       # Install in DEMO mode (no wallet required)
#   ./install.sh --help       # Show help message
#
# Author: Caio Vicentino
# GitHub: https://github.com/caiovicentino/polymarket-mcp-server
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Installation settings
DEMO_MODE=false
SKIP_CLAUDE_CONFIG=false
INSTALL_DIR=$(pwd)
VENV_DIR="$INSTALL_DIR/venv"
PYTHON_MIN_VERSION="3.10"

################################################################################
# Helper Functions
################################################################################

print_header() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo ""
}

print_step() {
    echo -e "${BLUE}[$1/7]${NC} $2"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${CYAN}ℹ${NC} $1"
}

show_help() {
    cat << EOF
Polymarket MCP Server - Installation Script

Usage:
  ./install.sh [OPTIONS]

Options:
  --demo              Install in DEMO mode (read-only, no wallet required)
  --skip-claude       Skip Claude Desktop configuration
  --help              Show this help message

Examples:
  ./install.sh                    # Full interactive installation
  ./install.sh --demo             # DEMO mode installation
  ./install.sh --skip-claude      # Install without Claude Desktop config

EOF
    exit 0
}

check_os() {
    case "$OSTYPE" in
        darwin*)  OS="macOS" ;;
        linux*)   OS="Linux" ;;
        msys*|cygwin*) OS="Windows" ;;
        *)
            print_error "Unsupported OS: $OSTYPE"
            echo "This script supports macOS, Linux, and Windows WSL."
            exit 1
            ;;
    esac
}

check_python() {
    print_step 1 "Checking Python version..."

    # Try different Python commands
    for cmd in python3 python python3.12 python3.11 python3.10; do
        if command -v $cmd &> /dev/null; then
            PYTHON_CMD=$cmd
            PYTHON_VERSION=$($cmd --version 2>&1 | awk '{print $2}')
            break
        fi
    done

    if [ -z "$PYTHON_CMD" ]; then
        print_error "Python not found"
        echo ""
        echo "Please install Python ${PYTHON_MIN_VERSION} or higher:"
        echo "  macOS: brew install python@3.12"
        echo "  Linux: sudo apt install python3.12"
        exit 1
    fi

    # Check version
    REQUIRED_VERSION=$(echo $PYTHON_MIN_VERSION | sed 's/\.//')
    CURRENT_VERSION=$(echo $PYTHON_VERSION | cut -d. -f1,2 | sed 's/\.//')

    if [ "$CURRENT_VERSION" -lt "$REQUIRED_VERSION" ]; then
        print_error "Python ${PYTHON_VERSION} found, but ${PYTHON_MIN_VERSION}+ required"
        exit 1
    fi

    print_success "Python ${PYTHON_VERSION} found ($PYTHON_CMD)"
}

create_virtualenv() {
    print_step 2 "Creating virtual environment..."

    if [ -d "$VENV_DIR" ]; then
        print_warning "Virtual environment already exists"
        read -p "Remove and recreate? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$VENV_DIR"
        else
            print_info "Using existing virtual environment"
            return
        fi
    fi

    $PYTHON_CMD -m venv "$VENV_DIR"
    print_success "Virtual environment created"
}

activate_virtualenv() {
    if [ -f "$VENV_DIR/bin/activate" ]; then
        source "$VENV_DIR/bin/activate"
    elif [ -f "$VENV_DIR/Scripts/activate" ]; then
        source "$VENV_DIR/Scripts/activate"
    else
        print_error "Could not find venv activation script"
        exit 1
    fi
}

install_dependencies() {
    print_step 3 "Installing dependencies..."

    # Upgrade pip first
    pip install --quiet --upgrade pip

    # Install package in editable mode
    pip install --quiet -e .

    # Count installed packages
    PKG_COUNT=$(pip list --format=freeze | wc -l)
    print_success "Installed ($PKG_COUNT packages)"
}

validate_private_key() {
    local key=$1
    # Remove 0x prefix if present
    key=${key#0x}
    # Check if 64 hex characters
    if [[ ${#key} -eq 64 ]] && [[ $key =~ ^[0-9a-fA-F]+$ ]]; then
        return 0
    fi
    return 1
}

validate_address() {
    local addr=$1
    # Check if starts with 0x and is 42 characters
    if [[ ${#addr} -eq 42 ]] && [[ $addr =~ ^0x[0-9a-fA-F]+$ ]]; then
        return 0
    fi
    return 1
}

configure_env() {
    print_step 4 "Configuration..."

    if [ "$DEMO_MODE" = true ]; then
        print_info "Running in DEMO mode (read-only, no trading)"
        cat > .env << EOF
# DEMO MODE - Read-only access, no wallet required
DEMO_MODE=true

# Demo wallet (no real funds)
POLYGON_PRIVATE_KEY=0000000000000000000000000000000000000000000000000000000000000001
POLYGON_ADDRESS=0x0000000000000000000000000000000000000001

# Safety Limits (demo defaults)
MAX_ORDER_SIZE_USD=100
MAX_TOTAL_EXPOSURE_USD=500
ENABLE_AUTONOMOUS_TRADING=false
LOG_LEVEL=INFO
EOF
        print_success "DEMO mode configured"
        return
    fi

    # Interactive wallet configuration
    echo ""
    echo "Do you have a Polygon wallet with private key? (needed for trading)"
    read -p "(y/n): " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_warning "No wallet provided - switching to DEMO mode"
        DEMO_MODE=true
        configure_env
        return
    fi

    # Get private key
    while true; do
        echo ""
        echo -e "${YELLOW}Enter your Polygon wallet private key:${NC}"
        echo "(without 0x prefix, 64 hex characters)"
        read -r -s PRIVATE_KEY
        echo

        if validate_private_key "$PRIVATE_KEY"; then
            break
        else
            print_error "Invalid private key format (must be 64 hex characters)"
        fi
    done

    # Get wallet address
    while true; do
        echo ""
        echo -e "${YELLOW}Enter your Polygon wallet address:${NC}"
        echo "(0x followed by 40 hex characters)"
        read -r WALLET_ADDRESS

        if validate_address "$WALLET_ADDRESS"; then
            break
        else
            print_error "Invalid address format (must be 42 characters starting with 0x)"
        fi
    done

    # Ask about safety limits
    echo ""
    echo "Configure safety limits? (recommended for autonomous trading)"
    read -p "(y/n): " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        read -p "Max order size USD (default: 1000): " MAX_ORDER
        MAX_ORDER=${MAX_ORDER:-1000}

        read -p "Max total exposure USD (default: 5000): " MAX_EXPOSURE
        MAX_EXPOSURE=${MAX_EXPOSURE:-5000}

        read -p "Enable autonomous trading (y/n, default: y): " -n 1 -r AUTO_TRADE
        echo
        if [[ $AUTO_TRADE =~ ^[Nn]$ ]]; then
            AUTO_TRADE_VALUE="false"
        else
            AUTO_TRADE_VALUE="true"
        fi
    else
        MAX_ORDER=1000
        MAX_EXPOSURE=5000
        AUTO_TRADE_VALUE="true"
    fi

    # Write .env file
    cat > .env << EOF
# Polygon Wallet Configuration
POLYGON_PRIVATE_KEY=$PRIVATE_KEY
POLYGON_ADDRESS=$WALLET_ADDRESS
POLYMARKET_CHAIN_ID=137

# Safety Limits
MAX_ORDER_SIZE_USD=$MAX_ORDER
MAX_TOTAL_EXPOSURE_USD=$MAX_EXPOSURE
MAX_POSITION_SIZE_PER_MARKET=2000
MIN_LIQUIDITY_REQUIRED=10000
MAX_SPREAD_TOLERANCE=0.05

# Trading Controls
ENABLE_AUTONOMOUS_TRADING=$AUTO_TRADE_VALUE
REQUIRE_CONFIRMATION_ABOVE_USD=500
AUTO_CANCEL_ON_LARGE_SPREAD=true

# Logging
LOG_LEVEL=INFO
EOF

    print_success "Configuration saved to .env"
}

configure_claude_desktop() {
    if [ "$SKIP_CLAUDE_CONFIG" = true ]; then
        print_step 5 "Skipping Claude Desktop configuration..."
        return
    fi

    print_step 5 "Configuring Claude Desktop..."

    # Determine config path based on OS
    if [ "$OS" = "macOS" ]; then
        CONFIG_DIR="$HOME/Library/Application Support/Claude"
    elif [ "$OS" = "Linux" ]; then
        CONFIG_DIR="$HOME/.config/Claude"
    else
        print_warning "Claude Desktop config not supported on $OS"
        return
    fi

    CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"

    # Create directory if it doesn't exist
    mkdir -p "$CONFIG_DIR"

    # Get Python path
    PYTHON_PATH=$(which python)

    # Prepare env vars for config
    if [ "$DEMO_MODE" = true ]; then
        ENV_VARS='        "DEMO_MODE": "true"'
    else
        # Read from .env file
        PRIVATE_KEY=$(grep POLYGON_PRIVATE_KEY .env | cut -d= -f2)
        WALLET_ADDR=$(grep POLYGON_ADDRESS .env | cut -d= -f2)
        ENV_VARS=$(cat << ENVEOF
        "POLYGON_PRIVATE_KEY": "$PRIVATE_KEY",
        "POLYGON_ADDRESS": "$WALLET_ADDR"
ENVEOF
)
    fi

    # Check if config file exists
    if [ -f "$CONFIG_FILE" ]; then
        print_warning "Claude Desktop config already exists"
        echo "Backup will be created at: ${CONFIG_FILE}.backup"
        cp "$CONFIG_FILE" "${CONFIG_FILE}.backup"
    fi

    # Create or update config
    cat > "$CONFIG_FILE" << EOF
{
  "mcpServers": {
    "polymarket": {
      "command": "$PYTHON_PATH",
      "args": ["-m", "polymarket_mcp.server"],
      "cwd": "$INSTALL_DIR",
      "env": {
$ENV_VARS
      }
    }
  }
}
EOF

    print_success "Claude Desktop configured"
    print_info "Config location: $CONFIG_FILE"
}

test_installation() {
    print_step 6 "Testing installation..."

    # Test import
    if python -c "import polymarket_mcp" 2>/dev/null; then
        print_success "Package import works"
    else
        print_error "Package import failed"
        exit 1
    fi

    # Test API connectivity (simple check)
    if curl -s --max-time 5 https://gamma-api.polymarket.com/markets &> /dev/null; then
        print_success "Polymarket API accessible"
    else
        print_warning "Could not reach Polymarket API (check internet connection)"
    fi

    print_success "Installation test passed"
}

show_completion() {
    print_step 7 "Installation complete!"

    echo ""
    print_header "🎉 Installation Successful!"

    if [ "$DEMO_MODE" = true ]; then
        echo -e "${CYAN}Running in DEMO mode:${NC}"
        echo "  • Market discovery and analysis: ✓ Enabled"
        echo "  • Real-time monitoring: ✓ Enabled"
        echo "  • Trading functions: ✗ Disabled (read-only)"
        echo ""
        echo -e "${YELLOW}To enable trading:${NC}"
        echo "  1. Get a Polygon wallet with USDC"
        echo "  2. Run: ./install.sh (without --demo flag)"
        echo "  3. Enter your wallet credentials"
    else
        echo -e "${GREEN}Full trading mode enabled!${NC}"
        echo ""
        echo -e "${YELLOW}Safety Limits:${NC}"
        grep "MAX_ORDER_SIZE_USD\|MAX_TOTAL_EXPOSURE_USD\|ENABLE_AUTONOMOUS_TRADING" .env | sed 's/^/  /'
    fi

    echo ""
    echo -e "${CYAN}Next Steps:${NC}"
    echo "  1. Restart Claude Desktop application"
    echo "  2. Look for 'polymarket' in available MCP servers"
    echo "  3. Start asking Claude about Polymarket markets!"
    echo ""
    echo -e "${CYAN}Example queries:${NC}"
    echo "  • Show me trending markets on Polymarket"
    echo "  • Analyze the top crypto prediction markets"
    echo "  • What markets are closing in the next 24 hours?"

    if [ "$DEMO_MODE" != true ]; then
        echo "  • Buy \$100 of YES in [market_id]"
        echo "  • Show my current positions"
    fi

    echo ""
    echo -e "${CYAN}Documentation:${NC}"
    echo "  • Setup Guide: ${INSTALL_DIR}/SETUP_GUIDE.md"
    echo "  • Tools Reference: ${INSTALL_DIR}/TOOLS_REFERENCE.md"
    echo "  • Usage Examples: ${INSTALL_DIR}/USAGE_EXAMPLES.py"
    echo ""
    echo -e "${GREEN}Happy trading! 🚀${NC}"
    echo ""
}

rollback() {
    print_error "Installation failed!"
    echo ""
    echo "Cleaning up..."

    # Remove virtual environment if created
    if [ -d "$VENV_DIR" ]; then
        rm -rf "$VENV_DIR"
        print_info "Removed virtual environment"
    fi

    # Remove .env if created
    if [ -f ".env" ]; then
        rm .env
        print_info "Removed .env file"
    fi

    echo ""
    echo "Please check the error message above and try again."
    echo "For help, visit: https://github.com/caiovicentino/polymarket-mcp-server/issues"
    exit 1
}

################################################################################
# Main Installation Flow
################################################################################

main() {
    # Set error trap
    trap rollback ERR

    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --demo)
                DEMO_MODE=true
                shift
                ;;
            --skip-claude)
                SKIP_CLAUDE_CONFIG=true
                shift
                ;;
            --help)
                show_help
                ;;
            *)
                print_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done

    # Print banner
    clear
    print_header "Polymarket MCP Server - Automated Installer"

    echo -e "${CYAN}This script will:${NC}"
    echo "  • Check Python version (3.10+ required)"
    echo "  • Create virtual environment"
    echo "  • Install all dependencies"
    echo "  • Configure environment variables"
    echo "  • Set up Claude Desktop integration"
    echo "  • Test the installation"
    echo ""

    if [ "$DEMO_MODE" = true ]; then
        print_info "Installing in DEMO mode (read-only, no wallet required)"
    fi

    read -p "Press Enter to continue or Ctrl+C to cancel..."
    echo ""

    # Run installation steps
    check_os
    check_python
    create_virtualenv
    activate_virtualenv
    install_dependencies
    configure_env
    configure_claude_desktop
    test_installation
    show_completion
}

# Run main function
main "$@"
