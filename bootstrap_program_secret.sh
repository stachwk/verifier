#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 6 ]; then
  cat <<'EOF'
Usage:
  ./bootstrap_program_secret.sh PROGRAM_NAME PROGRAM_PATH INSTANCE_KEY CONTEXT SUBCONTEXT SECRET_VALUE

Environment:
  PYTHON_BIN  Python interpreter to use (default: python3.12)
  CLI_PATH    Path to verifier_cli.py (default: ./verifier_cli.py)
EOF
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PROGRAM_NAME=$1
PROGRAM_PATH=$2
INSTANCE_KEY=$3
CONTEXT=$4
SUBCONTEXT=$5
SECRET_VALUE=$6
PYTHON_BIN=${PYTHON_BIN:-python3.12}
CLI_PATH=${CLI_PATH:-./verifier_cli.py}
CONFIG_FILE="$SCRIPT_DIR/verifier_cfg.ini"

"$PYTHON_BIN" "$CLI_PATH" --config "$CONFIG_FILE" --create-db
authorize_output="$("$PYTHON_BIN" "$CLI_PATH" --config "$CONFIG_FILE" --authorize "$PROGRAM_NAME" "$PROGRAM_PATH" "$INSTANCE_KEY")"
printf '%s\n' "$authorize_output"

session_password="$(printf '%s\n' "$authorize_output" | sed -n 's/^\[SESSION\] session_password=//p' | tail -n 1)"
if [ -z "$session_password" ]; then
  echo "[ERROR] Session password not found in authorize output." >&2
  exit 1
fi

printf '[INFO] session_password=%s\n' "$session_password"

"$PYTHON_BIN" "$CLI_PATH" --config "$CONFIG_FILE" --add-pwd-cmd "$PROGRAM_PATH" "$CONTEXT" "$SUBCONTEXT" "$SECRET_VALUE" "$INSTANCE_KEY"
