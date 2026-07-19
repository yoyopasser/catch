#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/cache/history data/exports .codespace
PID_FILE=".codespace/server.pid"; LOG_FILE=".codespace/server.log"
if [[ -f "$PID_FILE" ]]; then pid="$(cat "$PID_FILE" 2>/dev/null || true)"; if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then echo "台股決策工具已在執行（PID $pid）"; exit 0; fi; fi
pkill -f "uvicorn server:app --host 0.0.0.0 --port 8501" 2>/dev/null || true
nohup uvicorn server:app --host 0.0.0.0 --port 8501 >"$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "台股決策工具已啟動：http://localhost:8501"
