#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import os
import random
import shutil
import string
import subprocess
import sys
import tempfile
import time


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


def assert_contains(text, needle, msg):
    # Sprawdza czy tekst zawiera oczekiwany fragment
    if needle not in text:
        raise AssertionError(msg)


def assert_not_contains(text, needle, msg):
    # Sprawdza czy tekst nie zawiera niechcianego fragmentu
    if needle in text:
        raise AssertionError(msg)


def count_occurrences(text, needle):
    # Zlicza wystapienia fragmentu w tekscie
    return text.count(needle)


def main():
    parser = argparse.ArgumentParser(
        description="Testuje cleanup starych hashy w verifier_cli.py"
    )
    parser.add_argument("--python-bin", default="python3.12", help="Interpreter Pythona")
    parser.add_argument("--cli-path", default="./verifier_cli.py", help="Sciezka do verifier_cli.py")
    parser.add_argument("--program-path", default="./test_program.py", help="Sciezka do testowego programu")
    parser.add_argument("--repo-dir", default=".", help="Katalog roboczy repo")
    parser.add_argument("--verbose", type=int, default=0, help="1 = dodatkowe logi")
    args = parser.parse_args()

    repo_dir = os.path.abspath(args.repo_dir)
    cli_path = args.cli_path
    program_path = os.path.abspath(os.path.join(repo_dir, args.program_path))
    python_bin = args.python_bin

    uniq = f"cleanup_{int(time.time())}_{rand_suffix()}"
    program_name = f"test_program_{uniq}"
    instance_key = uniq

    print("=== START TESTU CLEANUP HASHY W CLI ===")
    print(f"repo_dir       : {repo_dir}")
    print(f"cli_path       : {cli_path}")
    print(f"program_path   : {program_path}")
    print(f"program_name   : {program_name}")
    print(f"instance_key   : {instance_key}")

    # Tworzymy tymczasowa kopie programu, aby latwo zmienic hash bez ruszania oryginalu
    tmp_dir = tempfile.mkdtemp(prefix="verifier_cleanup_")
    tmp_program = os.path.join(tmp_dir, "test_program_temp.py")
    shutil.copy2(program_path, tmp_program)

    try:
        # Krok 1: autoryzacja pierwszej wersji programu
        proc_auth_v1 = run_cmd(
            [python_bin, cli_path, "--authorize", program_name, tmp_program, instance_key],
            cwd=repo_dir,
            verbose=args.verbose
        )
        if proc_auth_v1.returncode != 0:
            raise SystemExit(f"[ERROR] Pierwsze --authorize nie powiodlo sie:\n{proc_auth_v1.stdout}\n{proc_auth_v1.stderr}")

        # Krok 2: zmieniamy plik, aby powstal nowy hash
        with open(tmp_program, "a", encoding="utf-8") as f:
            f.write(f"\n# test cleanup marker {uniq}\n")

        # Krok 3: autoryzacja drugiej wersji programu z tym samym program_name i instance_key
        proc_auth_v2 = run_cmd(
            [python_bin, cli_path, "--authorize", program_name, tmp_program, instance_key],
            cwd=repo_dir,
            verbose=args.verbose
        )
        if proc_auth_v2.returncode != 0:
            raise SystemExit(f"[ERROR] Drugie --authorize nie powiodlo sie:\n{proc_auth_v2.stdout}\n{proc_auth_v2.stderr}")

        # Krok 4: sprawdzamy wpisy w bazie przez --list-progs
        proc_list_before = run_cmd(
            [python_bin, cli_path, "--list-progs"],
            cwd=repo_dir,
            verbose=args.verbose
        )
        if proc_list_before.returncode != 0:
            raise SystemExit(f"[ERROR] --list-progs nie powiodlo sie:\n{proc_list_before.stdout}\n{proc_list_before.stderr}")

        # Obecna logika authorize powinna juz zostawic tylko jeden aktualny wpis
        key_fragment = f"name='{program_name}', instance_key='{instance_key}'"
        count_before = count_occurrences(proc_list_before.stdout, key_fragment)
        if count_before != 1:
            raise AssertionError(
                f"Oczekiwano 1 wpisu po reauthorize dla {program_name}/{instance_key}, a znaleziono {count_before}"
            )

        # Krok 5: dry-run cleanup
        proc_cleanup_dry = run_cmd(
            [python_bin, cli_path, "--cleanup-progs", program_name, tmp_program, instance_key],
            cwd=repo_dir,
            verbose=args.verbose
        )
        if proc_cleanup_dry.returncode != 0:
            raise SystemExit(f"[ERROR] --cleanup-progs nie powiodlo sie:\n{proc_cleanup_dry.stdout}\n{proc_cleanup_dry.stderr}")

        assert_contains(
            proc_cleanup_dry.stdout,
            "=== PODSUMOWANIE ===",
            "Brak podsumowania w --cleanup-progs"
        )
        assert_contains(
            proc_cleanup_dry.stdout,
            "tryb         : DRY-RUN",
            "Brak trybu DRY-RUN w --cleanup-progs"
        )
        assert_contains(
            proc_cleanup_dry.stdout,
            "do_usuniecia  : 0",
            "Przy obecnej logice authorize cleanup powinien miec 0 do usuniecia"
        )

        # Krok 6: execute cleanup
        proc_cleanup_exec = run_cmd(
            [python_bin, cli_path, "--cleanup-progs-exec", program_name, tmp_program, instance_key],
            cwd=repo_dir,
            verbose=args.verbose
        )
        if proc_cleanup_exec.returncode != 0:
            raise SystemExit(f"[ERROR] --cleanup-progs-exec nie powiodlo sie:\n{proc_cleanup_exec.stdout}\n{proc_cleanup_exec.stderr}")

        assert_contains(
            proc_cleanup_exec.stdout,
            "[OK] Usuwanie wykonane.",
            "Brak potwierdzenia wykonania cleanup"
        )

        # Krok 7: ponowna lista po cleanup
        proc_list_after = run_cmd(
            [python_bin, cli_path, "--list-progs"],
            cwd=repo_dir,
            verbose=args.verbose
        )
        if proc_list_after.returncode != 0:
            raise SystemExit(f"[ERROR] Drugie --list-progs nie powiodlo sie:\n{proc_list_after.stdout}\n{proc_list_after.stderr}")

        count_after = count_occurrences(proc_list_after.stdout, key_fragment)
        if count_after != 1:
            raise AssertionError(
                f"Po cleanup oczekiwano 1 wpisu dla {program_name}/{instance_key}, a znaleziono {count_after}"
            )

        print("")
        print("=== PODSUMOWANIE ===")
        print("[OK] Reauthorize dla tej samej pary program_name/instance_key nie tworzy duplikatow")
        print("[OK] --cleanup-progs dziala w trybie DRY-RUN")
        print("[OK] --cleanup-progs-exec wykonuje sie poprawnie")
        print("[OK] Po cleanup pozostaje tylko jeden aktualny wpis")
        print("[OK] Test zakonczony powodzeniem")

    finally:
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass


if __name__ == "__main__":
    main()
