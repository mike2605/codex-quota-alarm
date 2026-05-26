#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${CODEX_QUOTA_APP_DIR:-$HOME/.codex/codex-quota-alert}"
BIN_DIR="$APP_DIR/bin"

mkdir -p "$BIN_DIR"
cp "$ROOT_DIR/scripts/check_quota.py" "$BIN_DIR/check_quota.py"
chmod +x "$BIN_DIR/check_quota.py"

python3 "$BIN_DIR/check_quota.py" install

cat <<'EOF'

Installed.

Next:
1. Open Chrome and log in to ChatGPT/Codex.
2. In Chrome, enable: View > Developer > Allow JavaScript from Apple Events.
3. Optional: run ./configure.sh "+8613800000000" to enable iMessage.
4. Test with: codex-quota-alarm/check
EOF
