#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import os
import random
import re
import string
import subprocess
import sys
import time
from datetime import datetime


def print_err(str):
    print(f"stderr: {str}", file=sys.stderr)


def run_cmd(cmd, cwd=None, verbose=0):
    # Uruchamia komende i zwraca wynik procesu
    if verbose == 1:
        print_err(f"Uruchamiam: {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    if verbose == 1:
        print_err(f"rc={proc.returncode}")
        if proc.stdout:
            print_err(f"stdout={proc.stdout.strip()}")
        if proc.stderr:
            print_err(f"stderr={proc.stderr.strip()}")
    return proc


def rand_suffix(n=8):
    # Generuje losowy sufiks do nazw testowych
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))


def parse_authorized_at(output, program_name, instance_key):
    # Wyciaga authorized_at dla wskazanego programu z wyjscia --list-progs
    pattern = re.compile(
        r"name='{}', instance_key='{}', authorized_at='([^']+)'".format(
            re.escape(program_name),
            re.escape(instance_key),
        )
    )
    match = pattern.search(output)
    if not match:
        return None
    return match.group(1)


def parse_ts(ts):
    # Konwertuje timestamp SQL na obiekt datetime
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def assert_contains(text, needle, msg):
    # Sprawdza czy tekst zawiera oczekiwany fragment
    if needle not in text:
        raise AssertionError(msg)


def main():
    parser = argparse.ArgumentParser(
        description="Testuje authorized_at i idempotencje create-db w verifier_cli.py"
    )
    parser.add_argument("--python-bin", default="python3.12", help="Interpreter Pythona")
    parser.add_argument("--cli-path", default="./verifier_cli.py", help="Sciezka do verifier_cli.py")
    parser.add_argument("--program-path", default="./test/unit/test_program.py", help="Sciezka do test/unit/test_program.py")
    parser.add_argument("--repo-dir", default=".", help="Katalog roboczy repo")
    parser.add_argument("--sleep-seconds", type=int, default=2, help="Odstep miedzy authorize, aby timestamp mial szanse sie zmienic")
    parser.add_argument("--verbose", type=int, default=0, help="1 = dodatkowe logi")
    args = parser.parse_args()

    repo_dir = os.path.abspath(args.repo_dir)
    cli_path = args.cli_path
    program_path = args.program_path
    python_bin = args.python_bin

    uniq = f"authat_{int(time.time())}_{rand_suffix()}"
    program_name = f"test_program_{uniq}"
    instance_key = uniq

    print("=== START TESTU AUTHORIZED_AT W CLI ===")
    print(f"repo_dir       : {repo_dir}")
    print(f"cli_path       : {cli_path}")
    print(f"program_path   : {program_path}")
    print(f"program_name   : {program_name}")
    print(f"instance_key   : {instance_key}")

    # Krok 1: create-db powinno byc idempotentne
    proc_create_1 = run_cmd(
        [python_bin, cli_path, "--create-db"],
        cwd=repo_dir,
        verbose=args.verbose
    )
    if proc_create_1.returncode != 0:
        raise SystemExit(f"[ERROR] Pierwsze --create-db nie powiodlo sie:\n{proc_create_1.stdout}\n{proc_create_1.stderr}")
    assert_contains(proc_create_1.stdout, "[OK] Database created or already existed.", "Brak potwierdzenia po pierwszym --create-db")

    proc_create_2 = run_cmd(
        [python_bin, cli_path, "--create-db"],
        cwd=repo_dir,
        verbose=args.verbose
    )
    if proc_create_2.returncode != 0:
        raise SystemExit(f"[ERROR] Drugie --create-db nie powiodlo sie:\n{proc_create_2.stdout}\n{proc_create_2.stderr}")
    assert_contains(proc_create_2.stdout, "[OK] Database created or already existed.", "Brak potwierdzenia po drugim --create-db")

    # Krok 2: pierwsza autoryzacja
    proc_auth_1 = run_cmd(
        [python_bin, cli_path, "--authorize", program_name, program_path, instance_key],
        cwd=repo_dir,
        verbose=args.verbose
    )
    if proc_auth_1.returncode != 0:
        raise SystemExit(f"[ERROR] Pierwsze --authorize nie powiodlo sie:\n{proc_auth_1.stdout}\n{proc_auth_1.stderr}")

    # Krok 3: list-progs i odczyt authorized_at
    proc_list_1 = run_cmd(
        [python_bin, cli_path, "--list-progs"],
        cwd=repo_dir,
        verbose=args.verbose
    )
    if proc_list_1.returncode != 0:
        raise SystemExit(f"[ERROR] Pierwsze --list-progs nie powiodlo sie:\n{proc_list_1.stdout}\n{proc_list_1.stderr}")

    ts1 = parse_authorized_at(proc_list_1.stdout, program_name, instance_key)
    if ts1 is None:
        raise AssertionError("Nie znaleziono authorized_at po pierwszym authorize")

    # Krok 4: odczekanie i ponowna autoryzacja tej samej pary
    time.sleep(args.sleep_seconds)

    proc_auth_2 = run_cmd(
        [python_bin, cli_path, "--authorize", program_name, program_path, instance_key],
        cwd=repo_dir,
        verbose=args.verbose
    )
    if proc_auth_2.returncode != 0:
        raise SystemExit(f"[ERROR] Drugie --authorize nie powiodlo sie:\n{proc_auth_2.stdout}\n{proc_auth_2.stderr}")

    proc_list_2 = run_cmd(
        [python_bin, cli_path, "--list-progs"],
        cwd=repo_dir,
        verbose=args.verbose
    )
    if proc_list_2.returncode != 0:
        raise SystemExit(f"[ERROR] Drugie --list-progs nie powiodlo sie:\n{proc_list_2.stdout}\n{proc_list_2.stderr}")

    ts2 = parse_authorized_at(proc_list_2.stdout, program_name, instance_key)
    if ts2 is None:
        raise AssertionError("Nie znaleziono authorized_at po drugim authorize")

    dt1 = parse_ts(ts1)
    dt2 = parse_ts(ts2)

    if dt2 < dt1:
        raise AssertionError(f"authorized_at cofnal sie w czasie: ts1={ts1}, ts2={ts2}")

    if dt2 == dt1:
        raise AssertionError(
            f"authorized_at nie zostal zaktualizowany po ponownym authorize: ts1={ts1}, ts2={ts2}"
        )

    print("")
    print("=== PODSUMOWANIE ===")
    print("[OK] --create-db jest idempotentne")
    print("[OK] authorized_at jest widoczne w --list-progs")
    print("[OK] ponowne --authorize aktualizuje authorized_at")
    print(f"[INFO] authorized_at przed : {ts1}")
    print(f"[INFO] authorized_at po    : {ts2}")
    print("[OK] Test zakonczony powodzeniem")


if __name__ == "__main__":
    main()
