#!/bin/bash

cd /home/vic/polymarket-mcp-server
source /home/vic/polymarket-clean-venv/bin/activate
export PYTHONPATH=/home/vic/polymarket-clean-venv/lib/python3.12/site-packages:$PYTHONPATH
"$@"