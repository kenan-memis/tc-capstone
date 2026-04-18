#!/usr/bin/env bash
# Cloud Run sets PORT; default matches Cloud Run's common default.
set -euo pipefail

PORT="${PORT:-8080}"

echo "[entrypoint] Starting PlanMyBerlin (Streamlit) on 0.0.0.0:${PORT}"

exec streamlit run planmyberlin/ui/app.py \
  --server.address=0.0.0.0 \
  --server.port="${PORT}" \
  --server.headless=true \
  --browser.gatherUsageStats=false
