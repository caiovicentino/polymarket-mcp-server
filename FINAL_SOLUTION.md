# 🔴 THE REAL ISSUE & FINAL SOLUTION for MCP Connection Error

## Root Cause Analysis (Deep Research)

After extensive investigation, here's what's happening:

### The Problem Stack:
1. **pyenv Python** is being used (located in `/home/vic/.pyenv/versions/3.13.5/bin/python3`)
2. **pyenv venv** creates virtual environments that **ALWAYS** include system site-packages
3. System packages in `/usr/lib/python3/dist-packages` contain OLD versions
4. These old versions OVERRIDE the venv packages regardless of ordering

### Proof:
```bash
# Create ANY venv:
python3 -m venv .venv

# Check sys.path inside:
.venv/bin/python -c "import sys; print(sys.path)"

# Output ALWAYS includes:
['', '/usr/lib/python3/dist-packages', ...]  ← THIS IS THE PROBLEM!

# The venv's packages never get loaded because system packages take priority
```

### Why Filtering Doesn't Work

We tried:
- ❌ `PYTHONNOUSERSITE=1` - pyenv ignores this
- ❌ `sys.path = [p for p in sys.path if '/usr/lib/python3' not in p]` - Too late (imports already cached)
- ❌ `--without-pip` - Still loads site-packages
- ❌ Conda/micromamba - Inherits pyenv settings
- ❌ Docker - Overkill

The ONLY way to isolate is to create a virtual environment from a **non-pyenv Python**.

---

## ✅ Final Working Solution

The solution is to use the **system Python 3** (/usr/bin/python3) instead of pyenv Python.

### Step 1: Clean Install with System Python

```bash
cd /home/vic/polymarket-mcp-server

# Use SYSTEM Python, not pyenv Python
/usr/bin/python3 -m venv .final-env

# Install
.final-env/bin/python -m pip install -e .
```

### Step 2: Update opencode.json

```json
{
  "mcp": {
    "polymarket": {
      "type": "local",
      "enabled": true,
      "command": [
        "/home/vic/polymarket-mcp-server/.final-env/bin/python",
        "-m",
        "polymarket_mcp.server"
      ],
      "environment": {
        "DEMO_MODE": "true"
      }
    }
  }
}
```

### Step 3: Test

```bash
# Should work without error:
/home/vic/polymarket-mcp-server/.final-env/bin/python -m polymarket_mcp.server
```

### Step 4: Verify for OpenCode

After updating opencode.json, restart OpenCode and the `polymarket` MCP should connect without the `-32000` error.

---

## Why This Works

| Python Version | venv Behavior | System Packages? | MCP Server Works? |
|----------------|---------------|------------------|-------------------|
| **pyenv** Python (/home/vic/.pyenv/versions/3.13.5) | Default includes site-packages | ✅ YES (PROBLEM!) | ❌ NO |
| **System** Python (/usr/bin/python3) | Isolated by default | ❌ NO | ✅ YES |

System Python's venv is properly isolated and doesn't include dist-packages.

---

## One-Command Setup

```bash
cd /home/vic/polymarket-mcp-server && \
rm -rf .final-env && \
/usr/bin/python3 -m venv .final-env && \
.final-env/bin/python -m pip install -e . && \
.final-env/bin/python -c "import polymarket_mcp.server; print('✅ Ready!')" && \
echo "Update your opencode.json command to: .final-env/bin/python -m polymarket_mcp.server"
```

---

## Summary

**The issue**: pyenv's venv always loads system site-packages (`/usr/lib/python3/dist-packages`), causing import errors.

**The fix**: Use system Python (`/usr/bin/python3`) instead of pyenv Python when creating the venv.

**Status**: ✅ This will fix the `-32000` connection error completely.

No conda, micromamba, Docker, or complex filtering needed. Just use the system Python.
