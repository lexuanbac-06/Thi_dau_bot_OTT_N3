#!/usr/bin/env bash
# Khởi chạy FastAPI Backend
echo "Khởi chạy OTT Arena FastAPI Backend trên cổng 8000..."
.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
