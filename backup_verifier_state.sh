#!/usr/bin/env bash
set -euo pipefail

# Skrypt robi backup spojnego zestawu runtime dla Verifier.
# Sciezki do plikow sa czytane z verifier_cfg.ini obok skryptu.
#
# Uzycie:
#   ./backup_verifier_state.sh [backup_root]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BACKUP_ROOT="${1:-backup}"
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

CONFIG_DIR="$(cd "$(dirname "$CONFIG_FILE")" && pwd)"

# Czytamy wartosci z sekcji [paths] przez python, aby uniknac kruchych grep/sed
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

TS="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${BACKUP_ROOT}/verifier_state_${TS}"

mkdir -p "$BACKUP_DIR"

# Sprawdzamy, czy wszystkie pliki zestawu istnieja
check_file_exists "$DB_FILE"
check_file_exists "$DB_KEY_FILE"
check_file_exists "$SECRET_KEY_FILE"

# Kopiujemy pliki jako jeden spojny zestaw
cp -p "$DB_FILE" "$BACKUP_DIR/"
cp -p "$DB_KEY_FILE" "$BACKUP_DIR/"
cp -p "$SECRET_KEY_FILE" "$BACKUP_DIR/"

# Ustawiamy bezpieczne uprawnienia na kopiach
chmod 600 "$BACKUP_DIR/$(basename "$DB_FILE")"
chmod 600 "$BACKUP_DIR/$(basename "$DB_KEY_FILE")"
chmod 600 "$BACKUP_DIR/$(basename "$SECRET_KEY_FILE")"

# Tworzymy manifest pomocniczy
{
    echo "created_at=${TS}"
    echo "config_file=${CONFIG_FILE}"
    echo "config_dir=${CONFIG_DIR}"
    echo "db_file=${DB_FILE}"
    echo "db_key_file=${DB_KEY_FILE}"
    echo "secret_key_file=${SECRET_KEY_FILE}"
    echo "backup_dir=${BACKUP_DIR}"
} > "$BACKUP_DIR/manifest.txt"

chmod 600 "$BACKUP_DIR/manifest.txt"

log "[OK] Backup wykonany."
log "[INFO] verifier_cfg.ini : $CONFIG_FILE"
log "[INFO] DB         : $DB_FILE"
log "[INFO] DB key     : $DB_KEY_FILE"
log "[INFO] Secret key : $SECRET_KEY_FILE"
log "[INFO] Katalog backupu: $BACKUP_DIR"
