#!/bin/bash
cd /home/vic/polymarket-mcp-server

./.final-env/bin/python -c "
import sys
# Only filter out dist-packages, keep stdlib
sys.path = [p for p in sys.path if not ('/usr/lib/python3/dist-packages' in p)]
# Insert src directory first
sys.path.insert(0, '/home/vic/polymarket-mcp-server/src')
from polymarket_mcp.server import main
main()
" "$@"
