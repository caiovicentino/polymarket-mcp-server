#!/usr/bin/env python3
"""
Isolated MCP server runner.
Filters out /usr/lib/python3/dist-packages from sys.path BEFORE any imports.
This prevents version conflicts with system packages.
"""
import sys
import os

# Step 1: Remove dist-packages from sys.path BEFORE any other imports
original_dist_count = len([p for p in sys.path if "dist-packages" in p])
sys.path = [p for p in sys.path if "dist-packages" not in p]
filtered_dist_count = len([p for p in sys.path if "dist-packages" in p])

print(f"[run_isolated_mcp] Filtered {original_dist_count} dist-packages path(s), {filtered_dist_count} remaining")

# Step 2: Add the src directory to sys.path
src_dir = os.path.join(os.path.dirname(__file__), "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
    print(f"[run_isolated_mcp] Added {src_dir} to sys.path")

# Step 3: Set environment for demo mode
os.environ['DEMO_MODE'] = 'true'

# Step 4: Now import and run the MCP server
try:
    from polymarket_mcp.server import run
    print("[run_isolated_mcp] Starting MCP server...")
    run()
except Exception as e:
    print(f"[run_isolated_mcp] Failed to start MCP server: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
