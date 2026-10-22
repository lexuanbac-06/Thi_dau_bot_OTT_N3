#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/../.."
exec python -m uvicorn servers.scoring.module:app \
  --host 127.0.0.1 \
  --port "${OTT_SCORING_PORT:-8110}" \
  --workers 1
