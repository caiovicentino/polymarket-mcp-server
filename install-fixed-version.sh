#!/bin/bash
set -e

echo "📦 Installing Polymarket MCP Server with Dependency Fixes"
echo "======================================================"

# Ask user for installation directory
read -p "Enter installation directory (default: ~/polymarket-mcp-server-fix): " INSTALL_DIR
INSTALL_DIR=${INSTALL_DIR:-$HOME/polymarket-mcp-server-fix}

echo ""
echo "📁 Installation directory: $INSTALL_DIR"

# Clone or update repository
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "🔄 Updating existing repository..."
    cd "$INSTALL_DIR"
    git fetch
    git checkout fix/dependency-conflict-fastapi-anyio
    git pull
else
    echo "📥 Cloning repository..."
    git clone https://github.com/vicmuchina/polymarket-mcp-server-fix.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    git checkout fix/dependency-conflict-fastapi-anyio
fi

echo ""
echo "🔧 Creating virtual environment..."
python3 -m venv .venv --clear

echo "📦 Installing dependencies..."
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -e .

echo ""
echo "✅ Installation Complete!"
echo "========================"
echo ""
echo "Repository: $(pwd)"
echo "Branch: $(git rev-parse --abbrev-ref HEAD)"
echo "Commit: $(git rev-parse --short HEAD)"
echo ""
echo "To activate the environment:"
echo "  cd $INSTALL_DIR"
echo "  source .venv/bin/activate"
echo ""
echo "To run the server:"
echo "  source .venv/bin/activate"
echo "  polymarket-mcp"
echo ""
echo "✅ All dependency conflicts resolved!"
