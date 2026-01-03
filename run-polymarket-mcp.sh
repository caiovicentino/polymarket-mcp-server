#!/bin/bash
POLYMARKET_MCP_DIR="$HOME/polymarket-mcp-server"
VENV_DIR="$POLYMARKET_MCP_DIR/.venv"
PYTHON_CMD="$VENV_DIR/bin/python"
cd "$POLYMARKET_MCP_DIR"
exec "$PYTHON_CMD" -m polymarket_mcp.server