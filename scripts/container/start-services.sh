#!/usr/bin/env bash
set -euo pipefail

WEB_PORT="${AXON_WEB_PORT:-5000}"
DASHBOARD_PORT="${AXON_DASHBOARD_PORT:-8501}"

python run_trader.py --schedule &
SCHEDULER_PID=$!

python run_web.py --host 0.0.0.0 --port "$WEB_PORT" &
WEB_PID=$!

streamlit run dashboard/app.py \
  --server.address 0.0.0.0 \
  --server.port "$DASHBOARD_PORT" \
  --server.headless true &
DASHBOARD_PID=$!

cleanup() {
  kill "$SCHEDULER_PID" "$WEB_PID" "$DASHBOARD_PID" 2>/dev/null || true
  wait "$SCHEDULER_PID" "$WEB_PID" "$DASHBOARD_PID" 2>/dev/null || true
}

trap cleanup SIGINT SIGTERM

wait -n "$SCHEDULER_PID" "$WEB_PID" "$DASHBOARD_PID"
exit_code=$?
cleanup
exit "$exit_code"
