#!/usr/bin/env bash
# Mac: double-click "Money Tracker" in Finder (partner or any Mac user with partner_local_config.env).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "${ROOT}"
exec python3 scripts/start_money_tracker_partner.py
