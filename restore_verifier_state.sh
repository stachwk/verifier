#!/usr/bin/env bash
set -euo pipefail

# Skrypt odtwarza caly spojny zestaw runtime dla Verifier.
# Sciezki docelowe sa czytane z verifier_cfg.ini obok skryptu.
#
# Uzycie:
#   ./restore_verifier_state.sh /sciezka/do/katalogu_backupu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BACKUP_DIR="${1:-}"
CONFIG_FILE="$SCRIPT_DIR/verifier_cfg.ini"

log() {
    printf '%s\n' "$*"
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

check_file_exists() {
    local f="$1"
    [ -f "$f" ] || die "Brak pliku: $f"
}

[ -f "$CONFIG_FILE" ] || die "Nie istnieje plik verifier_cfg.ini: $CONFIG_FILE"

[ -n "$BACKUP_DIR" ] || die "Podaj katalog backupu jako drugi argument"
[ -d "$BACKUP_DIR" ] || die "Katalog backupu nie istnieje: $BACKUP_DIR"

CONFIG_DIR="$(cd "$(dirname "$CONFIG_FILE")" && pwd)"

read_config_value() {
    local key="$1"
    python3 - "$CONFIG_FILE" "$key" <<'PY'
import configparser
import sys

config_file = sys.argv[1]
key = sys.argv[2]

cfg = configparser.ConfigParser()
read_ok = cfg.read(config_file)
if not read_ok:
    raise SystemExit(f"Nie mozna odczytac verifier_cfg.ini: {config_file}")

if "paths" not in cfg:
    raise SystemExit("Brak sekcji [paths] w verifier_cfg.ini")

if key not in cfg["paths"]:
    raise SystemExit(f"Brak klucza {key} w sekcji [paths]")

print(cfg["paths"][key])
PY
}

resolve_path() {
    local raw_path="$1"
    python3 - "$CONFIG_DIR" "$raw_path" <<'PY'
import os
import sys

base_dir = sys.argv[1]
raw_path = sys.argv[2]

if os.path.isabs(raw_path):
    print(raw_path)
else:
    print(os.path.abspath(os.path.join(base_dir, raw_path)))
PY
}

DB_NAME_RAW="$(read_config_value "DB_NAME")"
DB_KEY_FILE_RAW="$(read_config_value "DB_KEY_FILE")"
SECRET_KEY_FILE_RAW="$(read_config_value "SECRET_KEY_FILE")"

DB_FILE="$(resolve_path "$DB_NAME_RAW")"
DB_KEY_FILE="$(resolve_path "$DB_KEY_FILE_RAW")"
SECRET_KEY_FILE="$(resolve_path "$SECRET_KEY_FILE_RAW")"

BACKUP_DB_FILE="$BACKUP_DIR/$(basename "$DB_FILE")"
BACKUP_DB_KEY_FILE="$BACKUP_DIR/$(basename "$DB_KEY_FILE")"
BACKUP_SECRET_KEY_FILE="$BACKUP_DIR/$(basename "$SECRET_KEY_FILE")"

# Sprawdzamy komplet zestawu w backupie
check_file_exists "$BACKUP_DB_FILE"
check_file_exists "$BACKUP_DB_KEY_FILE"
check_file_exists "$BACKUP_SECRET_KEY_FILE"

# Tworzymy katalogi docelowe, jesli ich nie ma
mkdir -p "$(dirname "$DB_FILE")"
mkdir -p "$(dirname "$DB_KEY_FILE")"
mkdir -p "$(dirname "$SECRET_KEY_FILE")"

# Odtwarzamy caly zestaw
cp -f "$BACKUP_DB_FILE" "$DB_FILE"
cp -f "$BACKUP_DB_KEY_FILE" "$DB_KEY_FILE"
cp -f "$BACKUP_SECRET_KEY_FILE" "$SECRET_KEY_FILE"

# Ustawiamy bezpieczne uprawnienia po restore
chmod 600 "$DB_FILE"
chmod 600 "$DB_KEY_FILE"
chmod 600 "$SECRET_KEY_FILE"

log "[OK] Restore wykonany."
log "[INFO] verifier_cfg.ini : $CONFIG_FILE"
log "[INFO] Zrodlo restore : $BACKUP_DIR"
log "[INFO] DB         : $DB_FILE"
log "[INFO] DB key     : $DB_KEY_FILE"
log "[INFO] Secret key : $SECRET_KEY_FILE"
