#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 5 ]; then
  cat <<'EOF'
Usage:
  ./bootstrap_and_run_scenario.sh PROGRAM_NAME INSTANCE_KEY CONTEXT SUBCONTEXT SECRET_VALUE

Environment:
  PYTHON_BIN  Python interpreter to use (default: python3.12)
EOF
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PROGRAM_NAME=$1
INSTANCE_KEY=$2
CONTEXT=$3
SUBCONTEXT=$4
SECRET_VALUE=$5
PYTHON_BIN=${PYTHON_BIN:-python3.12}

"$SCRIPT_DIR/bootstrap_program_secret.sh" \
  "$PROGRAM_NAME" \
  "$SCRIPT_DIR/test/scenario/scenario_program_using_verifier.py" \
  "$INSTANCE_KEY" \
  "$CONTEXT" \
  "$SUBCONTEXT" \
  "$SECRET_VALUE"

"$PYTHON_BIN" "$SCRIPT_DIR/test/scenario/scenario_program_using_verifier.py" "$PROGRAM_NAME" "$INSTANCE_KEY"
