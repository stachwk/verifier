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


def print_err(str):
    print(f"stderr: {str}", file=sys.stderr)


def run_cmd(cmd, cwd=None, verbose=0):
    # Uruchamia komende i zwraca wynik
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
    # Generuje losowy sufiks do unikalnych nazw testowych
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


def main():
    parser = argparse.ArgumentParser(
        description="Testuje widocznosc hasel w verifier_cli.py"
    )
    parser.add_argument("--python-bin", default="python3.12", help="Interpreter Pythona")
    parser.add_argument("--cli-path", default="./verifier_cli.py", help="Sciezka do verifier_cli.py")
    parser.add_argument("--program-path", default="./test_program.py", help="Sciezka do testowego programu")
    parser.add_argument("--repo-dir", default=".", help="Katalog roboczy repo")
    parser.add_argument("--verbose", type=int, default=0, help="1 = dodatkowe logi")
    args = parser.parse_args()

    repo_dir = os.path.abspath(args.repo_dir)
    cli_path = args.cli_path
    program_path = args.program_path
    python_bin = args.python_bin

    # Unikalne dane testowe, aby nie mieszac z poprzednimi uruchomieniami
    uniq = f"cli_vis_{int(time.time())}_{rand_suffix()}"
    program_name = f"test_program_{uniq}"
    instance_key = uniq
    context = f"ctx_{uniq}"
    subcontext = f"sub_{uniq}"
    secret_password = f"Secret#{uniq}"

    print("=== START TESTU WIDOCZNOSCI HASEL W CLI ===")
    print(f"repo_dir       : {repo_dir}")
    print(f"cli_path       : {cli_path}")
    print(f"program_path   : {program_path}")
    print(f"program_name   : {program_name}")
    print(f"instance_key   : {instance_key}")
    print(f"context        : {context}")
    print(f"subcontext     : {subcontext}")

    # Krok 1: autoryzacja programu
    proc_auth = run_cmd(
        [python_bin, cli_path, "--authorize", program_name, program_path, instance_key],
        cwd=repo_dir,
        verbose=args.verbose
    )
    if proc_auth.returncode != 0:
        raise SystemExit(f"[ERROR] --authorize nie powiodlo sie:\n{proc_auth.stdout}\n{proc_auth.stderr}")

    session_match = re.search(r"\[SESSION\] session_password=([^\s]+)", proc_auth.stdout)
    if not session_match:
        raise AssertionError("Po --authorize powinno byc widoczne haslo sesji administratora")
    session_password = session_match.group(1)
    assert_contains(
        proc_auth.stdout,
        session_password,
        "Haslo sesji nie zostalo wypisane w odpowiedzi --authorize"
    )

    # Krok 2: dodanie credentiala i powiazanie z programem
    proc_add_pwd = run_cmd(
        [python_bin, cli_path, "--add-pwd-cmd", program_path, context, subcontext, secret_password, instance_key],
        cwd=repo_dir,
        verbose=args.verbose
    )
    if proc_add_pwd.returncode != 0:
        raise SystemExit(f"[ERROR] --add-pwd-cmd nie powiodlo sie:\n{proc_add_pwd.stdout}\n{proc_add_pwd.stderr}")

    # Krok 3: list-progs bez hasel
    proc_list_hidden = run_cmd(
        [python_bin, cli_path, "--list-progs"],
        cwd=repo_dir,
        verbose=args.verbose
    )
    if proc_list_hidden.returncode != 0:
        raise SystemExit(f"[ERROR] --list-progs nie powiodlo sie:\n{proc_list_hidden.stdout}\n{proc_list_hidden.stderr}")

    assert_contains(
        proc_list_hidden.stdout,
        f"name='{program_name}', instance_key='{instance_key}'",
        "Brak testowego programu w --list-progs"
    )
    assert_not_contains(
        proc_list_hidden.stdout,
        "ephemeral_password=",
        "Haslo nie powinno byc widoczne w --list-progs bez --show-passwords"
    )

    # Krok 4: list-progs z haslami
    proc_list_show = run_cmd(
        [python_bin, cli_path, "--list-progs", "--show-passwords"],
        cwd=repo_dir,
        verbose=args.verbose
    )
    if proc_list_show.returncode != 0:
        raise SystemExit(f"[ERROR] --list-progs --show-passwords nie powiodlo sie:\n{proc_list_show.stdout}\n{proc_list_show.stderr}")

    assert_contains(
        proc_list_show.stdout,
        f"name='{program_name}', instance_key='{instance_key}'",
        "Brak testowego programu w --list-progs --show-passwords"
    )
    assert_contains(
        proc_list_show.stdout,
        "ephemeral_password=",
        "Haslo powinno byc widoczne w --list-progs --show-passwords"
    )

    # Krok 5: list-prog-creds-cmd bez hasel
    proc_creds_hidden = run_cmd(
        [python_bin, cli_path, "--list-prog-creds-cmd", program_path, instance_key],
        cwd=repo_dir,
        verbose=args.verbose
    )
    if proc_creds_hidden.returncode != 0:
        raise SystemExit(f"[ERROR] --list-prog-creds-cmd nie powiodlo sie:\n{proc_creds_hidden.stdout}\n{proc_creds_hidden.stderr}")

    assert_contains(
        proc_creds_hidden.stdout,
        f"context='{context}', subcontext='{subcontext}', pass='<hidden>'",
        "Credential powinien byc ukryty w --list-prog-creds-cmd bez --show-passwords"
    )
    assert_not_contains(
        proc_creds_hidden.stdout,
        secret_password,
        "Jawne haslo nie powinno byc widoczne bez --show-passwords"
    )

    # Krok 6: list-prog-creds-cmd z haslami
    proc_creds_show = run_cmd(
        [python_bin, cli_path, "--list-prog-creds-cmd", program_path, instance_key, "--show-passwords"],
        cwd=repo_dir,
        verbose=args.verbose
    )
    if proc_creds_show.returncode != 0:
        raise SystemExit(f"[ERROR] --list-prog-creds-cmd --show-passwords nie powiodlo sie:\n{proc_creds_show.stdout}\n{proc_creds_show.stderr}")

    assert_contains(
        proc_creds_show.stdout,
        f"context='{context}', subcontext='{subcontext}', pass='{secret_password}'",
        "Credential powinien byc widoczny po --show-passwords"
    )

    print("")
    print("=== PODSUMOWANIE ===")
    print("[OK] --list-progs ukrywa hasla domyslnie")
    print("[OK] --list-progs --show-passwords pokazuje hasla")
    print("[OK] --list-prog-creds-cmd ukrywa hasla domyslnie")
    print("[OK] --list-prog-creds-cmd --show-passwords pokazuje hasla")
    print("[OK] Test zakonczony powodzeniem")


if __name__ == "__main__":
    main()
