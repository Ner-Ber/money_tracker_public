#!/usr/bin/env bash
# Run the dashboard from the repo only — no Google Drive paths.
# Use this to verify local CSVs and config before using start_money_tracker.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Optional: pick up conda env name from local_config.env without Drive paths.
if [[ -f "${SCRIPT_DIR}/local_config.env" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/local_config.env"
fi

unset MONEY_TRACKER_DRIVE_ROOT
unset MONEY_TRACKER_DATA_DIR
unset MONEY_TRACKER_CSV_DIR
unset MONEY_TRACKER_DATA_DIR_LOCAL
unset MONEY_TRACKER_CSV_DIR_LOCAL

PORT="${MONEY_TRACKER_PORT:-8050}"
URL="http://127.0.0.1:${PORT}"
HEALTH_URL="${URL}/health"

if [[ -n "${MONEY_TRACKER_CONDA_ENV:-}" ]]; then
  conda_base="$(conda info --base 2>/dev/null)" || {
    echo "Error: MONEY_TRACKER_CONDA_ENV is set but conda was not found." >&2
    exit 1
  }
  set +u
  # shellcheck disable=SC1091
  source "${conda_base}/etc/profile.d/conda.sh"
  conda activate "${MONEY_TRACKER_CONDA_ENV}"
  set -u
fi

cleanup() {
  if [[ -n "${DASH_PID:-}" ]] && kill -0 "${DASH_PID}" 2>/dev/null; then
    echo "Stopping dashboard (pid ${DASH_PID})..."
    kill "${DASH_PID}" 2>/dev/null || true
    wait "${DASH_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "${REPO_ROOT}"
echo "Local dev mode (repo only, no Drive paths)"
echo "Data dir: ${REPO_ROOT}"
echo "CSV dir:  ${REPO_ROOT}/csv_files"
if command -v python >/dev/null 2>&1; then
  echo "Python:   $(which python)"
fi
echo "Starting dashboard at ${URL} (Ctrl+C to stop)..."

stop_dashboard_on_port() {
  local port="${1:-8050}"
  local pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -ti ":${port}" 2>/dev/null || true)"
  fi
  if [[ -n "${pids}" ]]; then
    echo "Port ${port} in use — stopping previous dashboard (pid: ${pids//$'\n'/ })..."
    # shellcheck disable=SC2086
    kill ${pids} 2>/dev/null || true
    sleep 1
  fi
}

stop_dashboard_on_port "${PORT}"

python -m money_tracker.dashboard &
DASH_PID=$!

ready=0
for ((i = 1; i <= 240; i++)); do
  if ! kill -0 "${DASH_PID}" 2>/dev/null; then
    echo "Error: dashboard exited before the server was ready." >&2
    wait "${DASH_PID}" 2>/dev/null || true
    exit 1
  fi
  if curl -sf "${HEALTH_URL}" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.5
done

if (( ready == 0 )); then
  echo "Error: server did not respond at ${HEALTH_URL}." >&2
  wait "${DASH_PID}"
  exit 1
fi

echo "Server ready at ${URL}"

if command -v cmd.exe >/dev/null 2>&1; then
  cmd.exe /c start "" "${URL}" 2>/dev/null || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "${URL}" >/dev/null 2>&1 || true
fi

wait "${DASH_PID}"
