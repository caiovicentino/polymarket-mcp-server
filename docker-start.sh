#!/bin/bash
# Polymarket MCP Server - Docker Start Script
# Easy startup with environment validation and monitoring

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print banner
echo -e "${BLUE}"
cat << "EOF"
╔═══════════════════════════════════════════════════╗
║                                                   ║
║          Polymarket MCP Server - Docker          ║
║                                                   ║
╚═══════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# Function to print colored messages
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed!"
    print_info "Install from: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is available
if ! docker compose version &> /dev/null; then
    print_error "Docker Compose is not available!"
    print_info "Install from: https://docs.docker.com/compose/install/"
    exit 1
fi

print_success "Docker and Docker Compose are installed"

# Check if .env file exists
if [ ! -f .env ]; then
    print_warning ".env file not found! Creating from template..."

    if [ -f .env.example ]; then
        cp .env.example .env
        print_info "Created .env from .env.example"
    else
        # Create minimal .env (byte-identical to .env.example)
        cat > .env << 'EOF'
# Polymarket MCP Server Configuration
# Copy this file to .env and fill in your values

# ============================================================================
# DEMO MODE - Run without real wallet credentials (read-only)
# ============================================================================
# Set to true for read-only access without needing a wallet
# Perfect for testing market discovery, analysis, and monitoring features
# Trading functions will be disabled in DEMO mode
#
# When DEMO_MODE=true, you don't need to provide:
#   - POLYGON_PRIVATE_KEY
#   - POLYGON_ADDRESS
#
# The system will use safe demo values automatically.
DEMO_MODE=false

# ============================================================================
# Polygon Wallet Configuration (REQUIRED unless DEMO_MODE=true)
# ============================================================================

# Your Polygon wallet private key (without 0x prefix)
# Get from: MetaMask > Settings > Security > Export Private Key
# IMPORTANT: Keep this secret! Never commit to git or share publicly
POLYGON_PRIVATE_KEY=your_private_key_here

# Your Polygon wallet address (with 0x prefix)
# Get from: Your wallet's public address
POLYGON_ADDRESS=0xYourAddressHere

# Polygon chain ID (137 for mainnet, 80002 for Amoy testnet)
POLYMARKET_CHAIN_ID=137

# ============================================================================
# Polymarket API Credentials (OPTIONAL - auto-created if not provided)
# ============================================================================

# L2 API credentials for authenticated requests.
# Leave empty to auto-generate on first run.
# Or get from: https://polymarket.com/settings/api
# API_SECRET and PASSPHRASE are DIFFERENT values - do not reuse one for both,
# or request signing will fail.
POLYMARKET_API_KEY=
POLYMARKET_API_SECRET=
POLYMARKET_PASSPHRASE=
POLYMARKET_API_KEY_NAME=

# ============================================================================
# Safety Limits - Risk Management
# ============================================================================

# Maximum size for a single order in USD
MAX_ORDER_SIZE_USD=1000

# Maximum total exposure across all positions in USD
MAX_TOTAL_EXPOSURE_USD=5000

# Maximum position size per market in USD
MAX_POSITION_SIZE_PER_MARKET=2000

# Minimum liquidity required in market before trading (USD)
MIN_LIQUIDITY_REQUIRED=10000

# Maximum spread tolerance (0.05 = 5%)
MAX_SPREAD_TOLERANCE=0.05

# ============================================================================
# Trading Controls
# ============================================================================

# Trade without per-order confirmation.
# SAFE DEFAULT: false -> every order requires confirm=true to be placed.
# When true, only orders above REQUIRE_CONFIRMATION_ABOVE_USD require confirm=true.
# WARNING: setting this to true lets an agent place orders on its own.
ENABLE_AUTONOMOUS_TRADING=false

# Require user confirmation for orders above this USD amount
REQUIRE_CONFIRMATION_ABOVE_USD=500

# Automatically cancel orders if spread exceeds MAX_SPREAD_TOLERANCE
AUTO_CANCEL_ON_LARGE_SPREAD=true

# ============================================================================
# API Endpoints (OPTIONAL - uses defaults if not set)
# ============================================================================

# Polymarket CLOB API endpoint
CLOB_API_URL=https://clob.polymarket.com

# Gamma API endpoint for market data
GAMMA_API_URL=https://gamma-api.polymarket.com

# ============================================================================
# Logging
# ============================================================================

# Log level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=INFO

# ============================================================================
# Advanced Configuration (typically no changes needed)
# ============================================================================

# USDC token address on Polygon
USDC_ADDRESS=0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174

# CTF Exchange contract address
CTF_EXCHANGE_ADDRESS=0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E

# Conditional Token contract address
CONDITIONAL_TOKEN_ADDRESS=0x4D97DCd97eC945f40cF65F87097ACe5EA0476045
EOF
        print_info "Created default .env file"
    fi

    print_warning "Please edit .env with your credentials before continuing!"
    print_info "Open .env in your text editor and add your POLYGON_PRIVATE_KEY and POLYGON_ADDRESS"
    read -p "Press Enter when ready to continue..." || true
fi

# Validate environment variables
print_info "Validating environment configuration..."

source .env

if [ -z "$POLYGON_PRIVATE_KEY" ] || [ "$POLYGON_PRIVATE_KEY" = "your_private_key_here" ]; then
    print_error "POLYGON_PRIVATE_KEY not set in .env!"
    print_info "Get your private key from your Polygon wallet"
    exit 1
fi

if [ -z "$POLYGON_ADDRESS" ] || [ "$POLYGON_ADDRESS" = "0xYourAddressHere" ]; then
    print_error "POLYGON_ADDRESS not set in .env!"
    print_info "Get your wallet address from your Polygon wallet"
    exit 1
fi

print_success "Environment configuration validated"

# Build Docker image
print_info "Building Docker image..."
docker compose build

print_success "Docker image built successfully"

# Start services
print_info "Starting Polymarket MCP Server..."
docker compose up -d

# Wait for container to be healthy
print_info "Waiting for server to start..."
sleep 3

# Check container status
if docker compose ps | grep -q "Up"; then
    print_success "Polymarket MCP Server is running!"

    # Show container info
    echo ""
    print_info "Container Status:"
    docker compose ps

    echo ""
    print_info "To view logs in real-time:"
    echo "  docker compose logs -f"

    echo ""
    print_info "To stop the server:"
    echo "  docker compose down"

    echo ""
    print_info "To restart the server:"
    echo "  docker compose restart"

    # Show recent logs
    echo ""
    print_info "Recent logs:"
    docker compose logs --tail=20

else
    print_error "Failed to start server!"
    print_info "Showing logs..."
    docker compose logs
    exit 1
fi

echo ""
print_success "Setup complete! Your Polymarket MCP Server is ready."
