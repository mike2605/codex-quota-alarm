#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${CODEX_QUOTA_APP_DIR:-$HOME/.codex/codex-quota-alert}"
SCRIPT="$APP_DIR/bin/check_quota.py"

if [ ! -x "$SCRIPT" ]; then
  echo "Not installed yet. Run ./install.sh first." >&2
  exit 1
fi

if [ "${1:-}" = "" ]; then
  echo "Usage: ./configure.sh '+8613800000000'" >&2
  exit 1
fi

python3 "$SCRIPT" set-imessage "$1"
python3 "$SCRIPT" notify-current
