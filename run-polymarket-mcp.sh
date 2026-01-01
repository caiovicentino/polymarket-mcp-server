#!/bin/bash
POLYMARKET_MCP_DIR="$HOME/polymarket-mcp-server"
VENV_DIR="$POLYMARKET_MCP_DIR/.venv"
PYTHON_CMD="$VENV_DIR/bin/python"

if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found. Creating..."
    cd "$POLYMARKET_MCP_DIR"
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip setuptools wheel
    pip install pydantic==2.9.2
    pip install mcp==1.25.0
    pip install -e .
fi

echo "Starting Polymarket MCP Server..."
cd "$POLYMARKET_MCP_DIR"
"$PYTHON_CMD" -m polymarket_mcp.server