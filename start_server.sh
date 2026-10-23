#!/usr/bin/env bash
# ============================================================
#  start_server.sh — Khởi động server vòng online trên macOS/Linux
# ============================================================

set -e
cd "$(dirname "$0")"

if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

python3 serve.py
