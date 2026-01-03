#!/usr/bin/env python3
"""
Isolated MCP server runner for OpenCode.
Filters out /usr/lib/python3/dist-packages from sys.path BEFORE any imports.
This prevents version conflicts with system packages.
"""
import sys
import os

# Step 1: Clear PYTHONPATH environment variable BEFORE sys.path is built
# This prevents system packages from being added to sys.path
if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

# Step 2: Change to the polymarket-mcp-server directory first
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Step 3: Remove dist-packages from sys.path BEFORE any other imports
original_dist_count = len([p for p in sys.path if "dist-packages" in p])
sys.path = [p for p in sys.path if "dist-packages" not in p]
filtered_dist_count = len([p for p in sys.path if "dist-packages" in p])

# Step 3: Add the src directory to sys.path
src_dir = os.path.join(script_dir, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# Step 4: Set environment for demo mode
os.environ['DEMO_MODE'] = 'true'

# Step 5: Now import and run the MCP server
try:
    from polymarket_mcp.server import run
    run()
except Exception as e:
    print(f"[run_isolated_mcp] Failed to start MCP server: {type(e).__name__}: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)