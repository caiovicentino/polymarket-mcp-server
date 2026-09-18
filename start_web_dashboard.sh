#!/bin/bash
#
# Polymarket MCP Web Dashboard Launcher
# Quick start script for the web dashboard
#

set -e

# Requires Python >= 3.10 (pyproject requires-python)
if ! python3 -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then
    echo "ERROR: Python >= 3.10 required (found: $(python3 --version 2>&1))."
    echo "Install a newer Python and ensure 'python3' points to it."
    exit 1
fi

echo "=================================="
echo "Polymarket MCP Web Dashboard"
echo "=================================="
echo ""

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "WARNING: Virtual environment not found at ./venv"
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found!"
    echo "Please copy .env.example to .env and configure your credentials."
    exit 1
fi

# Ensure the package (and its polymarket-web console script) is installed
if ! command -v polymarket-web > /dev/null 2>&1; then
    echo "Installing polymarket-mcp package (editable)..."
    pip install --upgrade pip || true
    pip install -e .
fi

echo "Starting web dashboard..."
echo "URL: http://localhost:8080"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Start the web dashboard
polymarket-web
