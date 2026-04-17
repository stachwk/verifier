#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.dirname(TEST_DIR)
for path in (REPO_ROOT, TEST_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from verifier import Verifier
from runtime_utils import key_path_for, program_path_from_file


def main():
    if len(sys.argv) < 3:
        print("Usage: ./test/example/example_program_using_verifier.py <PROGRAM_NAME> <INSTANCE_KEY> [CONFIG_FILE]")
        sys.exit(1)

    program_name = sys.argv[1]
    instance_key = sys.argv[2]
    config_file = sys.argv[3] if len(sys.argv) > 3 else "verifier_cfg.ini"
    program_path = program_path_from_file(__file__)
    key_path = key_path_for(program_path, program_name, instance_key)

    try:
        with open(key_path, "r", encoding="utf-8") as f:
            old_pass = f.read().strip()
    except FileNotFoundError:
        print(f"[ERROR] Password file '{key_path}' not found.")
        sys.exit(1)

    verifier = Verifier(program_path, config_file=config_file)
    try:
        success, new_pass = verifier.authenticate_and_regenerate(old_pass, instance_key)
        if not success:
            print("[ERROR] Authorization failed.")
            sys.exit(1)

        print("[OK] Program authorized.")
        print(f"[INFO] New session key: {new_pass}")
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    try:
        db_password = verifier.get_context_password("database", "read_only")
        if db_password:
            print(f"[INFO] Credential password for database/read_only = {db_password}")
        else:
            print("[INFO] No credential password found for database/read_only.")
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
