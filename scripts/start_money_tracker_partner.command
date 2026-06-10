#!/bin/bash
# Mac: double-click in Finder to start Money Tracker (requires Step 3 in docs/partner-setup.md).
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 scripts/start_money_tracker_partner.py
