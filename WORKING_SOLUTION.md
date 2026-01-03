# WORKING SOLUTION - Polymarket MCP Server

## Summary of the Fix

The polymarket-mcp-server was failing to start due to TWO critical issues:

### Problem 1: Fixed - Dependency Conflict ✅

**Issue**: `fastapi>=0.104.0` required `anyio<4.0.0`, but MCP required `anyio>=4.5`

**Solution**: Updated `pyproject.toml` dependencies:
```toml
 dependencies = [
-    "fastapi>=0.104.0",    # Required anyio<4.0.0 ❌
+    "fastapi>=0.109.0",    # Compatible with anyio>=4.5 ✅
-    "pydantic>=2.9.0,<2.10.0",
+    "pydantic>=2.9.0",
 ]
```

**PR**: https://github.com/caiovicentino/polymarket-mcp-server/pull/5

---

### Problem 2: Working - Python Import Pollution (dist-packages) ✅

**Issue**: Python venv always adds `/usr/lib/python3/dist-packages` to `sys.path`, loading conflicting system packages (e.g., `typing_extensions==4.10.0` vs required `4.15.0`)

**Solution**: Filter dist-packages from `sys.path` **BEFORE any imports** using a wrapper script.

---

## Final Working Solution

### Method 1: Inline Isolation (Recommended)

Run the server with the isolation wrapper inlined:

```bash
cd /home/vic/polymarket-mcp-server

/home/vic/.pyenv/versions/3.13.5/bin/python -c "
import sys
sys.path = [p for p in sys.path if 'dist-packages' not in p]
sys.path.insert(0, './src')
import os
os.environ['DEMO_MODE'] = 'true'
from polymarket_mcp.server import run
run()
"
```

**Status**: ✅ Server initializes successfully in READ-ONLY mode
- Configuration loaded
- Client initialized
- Safety limits initialized
- Rate limiter initialized
- WebSocket manager initialized
- Available: 25 tools (8 Discovery + 10 Analysis + 7 Real-time)
- Trading & Portfolio tools require API credentials

---

### Method 2: Create run_isolated_mcp.py wrapper

```bash
cd /home/vic/polymarket-mcp-server

cat > run_isolated_mcp.py << 'EOF'
#!/usr/bin/env python3
"""
Isolated MCP server runner.
Filters out /usr/lib/python3/dist-packages from sys.path BEFORE any imports.
"""
import sys
import os

# Step 1: Remove dist-packages from sys.path BEFORE any other imports
original_dist_count = len([p for p in sys.path if "dist-packages" in p])
sys.path = [p for p in sys.path if "dist-packages" not in p]
filtered_dist_count = len([p for p in sys.path if "dist-packages" in p])

print(f"[filtered out {original_dist_count} dist-packages path(s), {filtered_dist_count} remaining")

# Step 2: Add the src directory to sys.path
src_dir = os.path.join(os.path.dirname(__file__), "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
    print(f"[added {src_dir} to sys.path")

# Step 3: Set environment for demo mode
os.environ['DEMO_MODE'] = 'true'

# Step 4: Now import and run the MCP server
try:
    from polymarket_mcp.server import run
    print("[starting MCP server...")
    run()
except Exception as e:
    print(f"[run_isolated_mcp] Failed to start MCP server: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
EOF

chmod +x run_isolated_mcp.py

# Run it
/home/vic/.pyenv/versions/3.13.5/bin/python run_isolated_mcp.py
```

---

## Install Environment

### 1. Update pyproject.toml (already fixed in PR)

```bash
cd /home/vic/polymarket-mcp-server
pip install -e .
```

### 2. Check installed packages

```bash
.venv/bin/pip show mcp anyio typing_extensions fastapi
```

Expected:
- `mcp==1.25.0`
- `anyio==4.12.0`
- `typing_extensions==4.15.0`
- `fastapi==0.128.0`

---

## For opencode.json

```json
{
  "mcpServers": {
    "polymarket": {
      "command": [
        "/home/vic/.pyenv/versions/3.13.5/bin/python",
        "-c",
        "import sys; sys.path = [p for p in sys.path if 'dist-packages' not in p]; sys.path.insert(0, './src'); import os; os.environ['DEMO_MODE'] = 'true'; from polymarket_mcp.server import run; run()"
      ],
      "env": {
        "DEMO_MODE": "true"
      }
    }
  }
}
```

OR use the wrapper script:

```json
{
  "mcpServers": {
    "polymarket": {
      "command": [
        "/home/vic/.pyenv/versions/3.13.5/bin/python",
        "/home/vic/polymarket-mcp-server/run_isolated_mcp.py"
      ],
      "env": {
        "DEMO_MODE": "true"
      }
    }
  }
}
```

---

## Testing the Server

```bash
cd /home/vic/polymarket-mcp-server

# Method 1: Inline isolation
/home/vic/.pyenv/versions/3.13.5/bin/python -c "
import sys
sys.path = [p for p in sys.path if 'dist-packages' not in p]
sys.path.insert(0, './src')
import os
os.environ['DEMO_MODE'] = 'true'
from polymarket_mcp.server import run
run()
"

# Or use the wrapper
/home/vic/.pyenv/versions/3.13.5/bin/python run_isolated_mcp.py
```

---

## Key Files

- **pyproject.toml**: Updated FastAPI version (fixed in PR #5)
- **.venv/**: Virtual environment with correct dependencies
- **run_isolated_mcp.py**: Wrapper script to filter dist-packages

---

## Root Cause Analysis

The `dist-packages` issue is a well-known problem on Debian/Ubuntu systems:

```bash
# This ALWAYS includes dist-packages despite venv flags
/usr/bin/python3 -m venv myenv
cat myenv/pyvenv.cfg
# include-system-site-packages = false

python -c "import sys; print([p for p in sys.path if 'dist-packages' in p])"
# ['/usr/lib/python3/dist-packages']  # Still there!
```

**Why**: Debian/Ubuntu Python patches `site.py` to always add dist-packages to the import path for platform compatibility.

**Our Fix**: Manually filter it out in a wrapper BEFORE any imports:
```python
sys.path = [p for p in sys.path if 'dist-packages' not in p]
```

---

## Next Steps for Full Trading Mode

The server currently runs in **READ-ONLY mode**. To enable trading:

1. Create a funded Polymarket wallet on Polygon
2. Generate API credentials via Polymarket
3. Create `.env` file:
   ```
   POLYGON_ADDRESS=0xYourAddress
   POLYGON_PRIVATE_KEY=0xYourPrivateKey
   POLYMARKET_API_KEY=YourApiKey
   POLYMARKET_PASSPHRASE=YourPassphrase
   POLYMARKET_CHAIN_ID=137
   ```
4. Restart server - trading tools will be available (45 tools total)

---

## Status

✅ Dependency conflict fixed (PR #5)
✅ Python import pollution solution found
✅ Server initialization works
✅ READ-ONLY mode functional (25 tools)
⚠️ Trading mode requires API credentials (provides 45 tools total)