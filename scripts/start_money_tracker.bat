@echo off
REM Double-click to start Money Tracker (WSL dev install + Drive production data).
setlocal
set "WSL_DISTRO=%WSL_DISTRO_NAME%"
if "%WSL_DISTRO%"=="" set "WSL_DISTRO=Ubuntu"
wsl -d %WSL_DISTRO% -e bash -lc "cd /home/neriberman/REPOS/money_tracker && bash scripts/start_money_tracker.sh"
endlocal
