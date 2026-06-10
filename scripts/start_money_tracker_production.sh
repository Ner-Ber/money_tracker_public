#!/usr/bin/env bash
# Start dashboard using Drive paths only (no MONEY_TRACKER_*_LOCAL overrides).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/local_config.env"

unset MONEY_TRACKER_DATA_DIR_LOCAL
unset MONEY_TRACKER_CSV_DIR_LOCAL
export MONEY_TRACKER_DATA_DIR
export MONEY_TRACKER_CSV_DIR
export MONEY_TRACKER_DRIVE_ROOT
export MONEY_TRACKER_CONDA_ENV

echo "Production mode: Drive paths only"
exec bash "${SCRIPT_DIR}/start_money_tracker.sh"
