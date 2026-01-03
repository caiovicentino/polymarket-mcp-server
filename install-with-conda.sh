#!/bin/bash
set -e

POLYMARKET_DIR="$HOME/polymarket-mcp-server"
export PATH="/home/vic/polymarket-mcp-server/.venv/bin:$PATH"

cd "$POLYMARKET_DIR"

echo "🔍 Detecting Python installation method..."

if command -v conda &>/dev/null; then
    echo "✓ Using conda"
    rm -rf .venv
    conda create -y -n polymarket-mcp python=3.13
    conda run -n polymarket-mcp pip install -e .
    echo ""
    echo "✅ Installation complete!"
    echo ""
    echo "📝 Update your opencode.json command to:"
    echo '  "command": ["conda", "run", "-n", "polymarket-mcp", "-m", "polymarket_mcp.server"]'
else
    echo "❌ No conda found"
    echo ""
    echo "The issue is that pyenv venv includes system packages, causing conflicts."
    echo ""
    echo "SOLUTION: Install conda and run this script again"
    echo ""
    echo "Install conda:"
    echo "  wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
    echo "  bash Miniconda3-latest-Linux-x86_64.sh"
    echo "  source ~/miniconda3/bin/activate"
    echo ""
    echo "Then run: bash install-with-conda.sh"
    exit 1
fi
