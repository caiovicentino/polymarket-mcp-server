#!/bin/bash
set -e

cd /home/vic/polymarket-mcp-server

export PYTHONPATH="/home/vic/polymarket-mcp-server/src/micromamba-env/lib/python3.13/site-packages:/home/vic/polymarket-mcp-server/src:$PYTHONPATH"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
export NO_SITE_PACKAGES=1

exec /home/vic/micromamba run -p ./micromamba-env python -m polymarket_mcp.server "$@"
