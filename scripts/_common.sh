#!/usr/bin/env bash
# Shared helpers for money_tracker scripts. Source from other scripts, do not run directly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f "${SCRIPT_DIR}/local_config.env" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/local_config.env"
fi

if [[ -z "${MONEY_TRACKER_DATA_DIR:-}" ]]; then
  echo "Error: MONEY_TRACKER_DATA_DIR is not set." >&2
  echo "Copy scripts/local_config.env.example to scripts/local_config.env and edit paths." >&2
  exit 1
fi

export MONEY_TRACKER_DATA_DIR

if [[ -z "${MONEY_TRACKER_CSV_DIR:-}" ]]; then
  echo "Error: MONEY_TRACKER_CSV_DIR is not set." >&2
  echo "Set it in scripts/local_config.env (e.g. .../data_files)." >&2
  exit 1
fi

export MONEY_TRACKER_CSV_DIR

if [[ -n "${MONEY_TRACKER_DATA_DIR_LOCAL:-}" ]]; then
  export MONEY_TRACKER_DATA_DIR_LOCAL
fi

if [[ -n "${MONEY_TRACKER_CSV_DIR_LOCAL:-}" ]]; then
  export MONEY_TRACKER_CSV_DIR_LOCAL
fi

activate_conda_env_if_configured() {
  local env_name="${MONEY_TRACKER_CONDA_ENV:-}"
  if [[ -z "${env_name}" ]]; then
    return 0
  fi
  local conda_base
  if ! conda_base="$(conda info --base 2>/dev/null)"; then
    echo "Error: MONEY_TRACKER_CONDA_ENV is set but conda was not found." >&2
    exit 1
  fi
  set +u
  # shellcheck disable=SC1091
  source "${conda_base}/etc/profile.d/conda.sh"
  conda activate "${env_name}"
  set -u
}

stop_dashboard_on_port() {
  local port="${1:-8050}"
  local pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -ti ":${port}" 2>/dev/null || true)"
  elif command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
    return 0
  fi
  if [[ -n "${pids}" ]]; then
    echo "Port ${port} in use — stopping previous Money Tracker (pid: ${pids//$'\n'/ })..."
    # shellcheck disable=SC2086
    kill ${pids} 2>/dev/null || true
    sleep 1
  fi
}
