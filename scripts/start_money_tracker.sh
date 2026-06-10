#!/usr/bin/env bash
# Start the dashboard using production data on Google Drive. Opens browser on Windows (WSL) or Linux.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_common.sh"

PORT="${MONEY_TRACKER_PORT:-8050}"
HOST="${MONEY_TRACKER_HOST:-127.0.0.1}"
URL="http://127.0.0.1:${PORT}"
HEALTH_URL="${URL}/health"
WAIT_SECONDS="${MONEY_TRACKER_STARTUP_WAIT_S:-180}"

cleanup() {
  if [[ -n "${DASH_PID:-}" ]] && kill -0 "${DASH_PID}" 2>/dev/null; then
    echo "Stopping dashboard (pid ${DASH_PID})..."
    kill "${DASH_PID}" 2>/dev/null || true
    wait "${DASH_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "${REPO_ROOT}"
activate_conda_env_if_configured
echo "Data dir: ${MONEY_TRACKER_DATA_DIR}"
echo "CSV dir:  ${MONEY_TRACKER_CSV_DIR}"
if [[ -n "${MONEY_TRACKER_DATA_DIR_LOCAL:-}" ]]; then
  echo "Local data (WSL): ${MONEY_TRACKER_DATA_DIR_LOCAL}"
fi
if [[ -n "${MONEY_TRACKER_CSV_DIR_LOCAL:-}" ]]; then
  echo "Local CSV (WSL):  ${MONEY_TRACKER_CSV_DIR_LOCAL}"
fi
if [[ -n "${MONEY_TRACKER_CONDA_ENV:-}" ]]; then
  echo "Python:   $(which python) (conda: ${MONEY_TRACKER_CONDA_ENV})"
fi
echo "Starting dashboard at ${URL} (Ctrl+C to stop)..."
echo "Loading CSV data first, then starting server (local ~10s, Drive may take 2–3 min)..."

stop_dashboard_on_port "${PORT}"

python -m money_tracker.dashboard &
DASH_PID=$!

ready=0
for ((i = 1; i <= WAIT_SECONDS * 2; i++)); do
  if ! kill -0 "${DASH_PID}" 2>/dev/null; then
    echo "Error: dashboard process exited before the server was ready." >&2
    wait "${DASH_PID}" 2>/dev/null || true
    exit 1
  fi
  if curl -sf "${HEALTH_URL}" >/dev/null 2>&1; then
    ready=1
    break
  fi
  if (( i % 10 == 0 )); then
    echo "  Still waiting for server... ($((i / 2))s)"
  fi
  sleep 0.5
done

if (( ready == 0 )); then
  echo "Error: server did not respond at ${HEALTH_URL} within ${WAIT_SECONDS}s." >&2
  echo "Check the terminal for Python errors. Try opening ${URL} manually once you see 'Running on'." >&2
  wait "${DASH_PID}"
  exit 1
fi

echo "Server ready at ${URL}"

if command -v cmd.exe >/dev/null 2>&1; then
  cmd.exe /c start "" "${URL}" 2>/dev/null || true
elif command -v open >/dev/null 2>&1; then
  open "${URL}" || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "${URL}" >/dev/null 2>&1 || true
fi

wait "${DASH_PID}"
