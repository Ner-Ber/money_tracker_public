@echo off
title Money Tracker
REM Windows: double-click to start (partner — needs partner_local_config.env).
cd /d "%~dp0"
python scripts\start_money_tracker_partner.py
if errorlevel 1 (
  echo.
  echo Setup: see docs/partner-setup.md
  pause
)
