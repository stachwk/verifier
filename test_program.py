#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import configparser
import logging
import getpass
from verifier import Verifier

# Helper function for logging or printing messages
def log_or_print(message: str, level: str = "INFO"):
    config = configparser.ConfigParser()
    config.read("config.ini")
    if config.has_option("main", "LOG") and config.get("main", "LOG") == "1":
        logger = logging.getLogger("TestProgramLogger")
        logger.setLevel(logging.ERROR)
        if not logger.handlers:
            fh = logging.FileHandler("test_program.log")
            fh.setLevel(logging.ERROR)
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        lvl = level.upper()
        if lvl == "INFO":
            logger.info(message)
        elif lvl == "WARNING":
            logger.warning(message)
        elif lvl == "ERROR":
            logger.error(message)
        else:
            logger.info(message)
    else:
        print(message)

TEMP_SUFFIX = "_t"

def main():
    if len(sys.argv) < 2:
        log_or_print("Usage: ./test_program.py <INSTANCE_KEY>", "ERROR")
        sys.exit(1)
    instance_key = sys.argv[1]
    
    key_filename = f"test_program_{instance_key}.key"
    temp_filename = key_filename + TEMP_SUFFIX

    try:
        with open(key_filename, "r") as f:
            old_pass = f.read().strip()
    except FileNotFoundError:
        log_or_print(f"[ERROR] Password file '{key_filename}' not found.", "ERROR")
        sys.exit(1)

    verifier_instance = Verifier(__file__)
    try:
        success, new_pass = verifier_instance.authenticate_and_regenerate(old_pass, instance_key)
        if not success:
            log_or_print("[ERROR] Authorization failed (wrong password, program missing in the database, or invalid instance key).", "ERROR")
            sys.exit(1)
        log_or_print(f"[OK] Password is correct. The database accepted the authorization.", "INFO")
        log_or_print(f"[INFO] New password (in the database): {new_pass}", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] {e}", "ERROR")
        sys.exit(1)

    try:
        with open(temp_filename, "w") as tf:
            tf.write(new_pass + "\n")
        os.replace(temp_filename, key_filename)
        log_or_print(f"[OK] The key was regenerated and saved to: {key_filename}", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] Could not save the new key: {e}", "ERROR")
        sys.exit(1)

    try:
        db_pass = verifier_instance.get_context_password("database", "read_only")
        if db_pass:
            log_or_print(f"[INFO] Password for context 'database' / 'read_only': {db_pass}", "INFO")
        else:
            log_or_print("[INFO] No password for the requested context.", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] {e}", "ERROR")

if __name__ == "__main__":
    main()
