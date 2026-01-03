#!/usr/bin/env python3
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from polymarket_mcp.server import initialize_server

async def test_server():
    try:
        await initialize_server()
        print("✓ Server initialization successful!")
        print("✓ Polymarket MCP server is ready")
        return True
    except Exception as e:
        print(f"✗ Server initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_server())
    sys.exit(0 if success else 1)