#!/bin/bash
set -e

POLYMARKET_DIR="$HOME/polymarket-mcp-server"
cd "$POLYMARKET_DIR"

export PATH="$HOME:$PATH"

echo "Creating clean micromamba environment..."
rm -rf micromamba-env
micromamba create -y -p ./micromamba-env -c conda-forge python=3.13

echo "Installing polymarket-mcp..."
micromamba run -p ./micromamba-env pip install --upgrade pip setuptools wheel
micromamba run -p ./micromamba-env pip install -e .

echo ""
echo "✅ Installation complete!"
echo ""
echo "📝 Test it:"
echo "  micromamba run -p ./micromamba-env python -c 'import polymarket_mcp.server'"
echo ""
echo "📝 Update opencode.json:"
echo '  "command": ["/home/vic/micromamba", "run", "-p", "/home/vic/polymarket-mcp-server/micromamba-env", "-m", "polymarket_mcp.server"],'
