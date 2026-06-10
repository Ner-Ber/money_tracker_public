@echo off
REM Windows: double-click to start (requires partner_local_config.env — see docs/partner-setup.md).
setlocal
cd /d "%~dp0\.."
python scripts\start_money_tracker_partner.py
if errorlevel 1 pause
endlocal
