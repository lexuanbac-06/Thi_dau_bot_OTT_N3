#!/usr/bin/env bash
# ============================================================
#  start_finals.sh — Khởi động backend chung kết trên macOS/Linux
# ============================================================

set -e
cd "$(dirname "$0")"

# Kích hoạt venv (nếu có .venv hoặc venv)
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

python3 -m finals.run_server
