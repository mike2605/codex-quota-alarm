#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${CODEX_QUOTA_APP_DIR:-$HOME/.codex/codex-quota-alert}"

if [ -x "$APP_DIR/bin/check_quota.py" ]; then
  python3 "$APP_DIR/bin/check_quota.py" uninstall
else
  launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.codex-quota-alarm.monitor.plist" >/dev/null 2>&1 || true
  rm -f "$HOME/Library/LaunchAgents/com.codex-quota-alarm.monitor.plist"
fi

echo "Uninstalled monitor. Local config remains at: $APP_DIR"
