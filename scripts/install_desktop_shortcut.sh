#!/usr/bin/env bash
# Create a "Money Tracker.bat" shortcut on the Windows Desktop (WSL + Drive production setup).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

win_user=""
if command -v cmd.exe >/dev/null 2>&1; then
  win_user="$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r\n')"
fi
if [[ -z "${win_user}" ]]; then
  echo "Could not detect Windows username. Create the shortcut manually from scripts/start_money_tracker.bat" >&2
  exit 1
fi

DESKTOP="/mnt/c/Users/${win_user}/Desktop"
if [[ ! -d "${DESKTOP}" ]]; then
  DESKTOP="/mnt/c/Users/${win_user}/OneDrive/Desktop"
fi
if [[ ! -d "${DESKTOP}" ]]; then
  echo "Desktop folder not found under /mnt/c/Users/${win_user}/" >&2
  exit 1
fi

WSL_DISTRO="${WSL_DISTRO_NAME:-Ubuntu}"
BAT_PATH="${DESKTOP}/Money Tracker.bat"

cat > "${BAT_PATH}" << EOF
@echo off
title Money Tracker
REM Close this window to stop the app.
wsl -d ${WSL_DISTRO} -e bash -lc "cd '${REPO_ROOT}' && bash scripts/start_money_tracker.sh"
if errorlevel 1 pause
EOF

echo "Created: ${BAT_PATH}"
echo "Double-click \"Money Tracker\" on your Windows Desktop to start the app."
