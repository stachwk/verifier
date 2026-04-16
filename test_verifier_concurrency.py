#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import multiprocessing
import os
import subprocess
import sys
import time
from typing import Any

def print_err(str):
    print(f"stderr: {str}", file=sys.stderr)

def worker(proc_no: int, instance_key: str, python_bin: str, program_path: str, verbose: int) -> dict[str, Any]:
    # Funkcja uruchamia pojedynczy proces testowy
    # Kazdy proces probuje wykonac autoryzacje dla tej samej instancji
    cmd = [python_bin, program_path, instance_key]

    # Zapisujemy czas startu, aby latwiej ocenic opoznienia
    started = time.time()

    try:
        # Uruchamiamy proces potomny i zbieramy stdout/stderr
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        ended = time.time()

        if verbose == 1:
            print_err(
                f"proc_no={proc_no} rc={proc.returncode} elapsed={ended - started:.3f}s"
            )

        return {
            "proc_no": proc_no,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "elapsed": round(ended - started, 3),
        }
    except Exception as e:
        ended = time.time()
        if verbose == 1:
            print_err(f"proc_no={proc_no} exception={e}")

        return {
            "proc_no": proc_no,
            "returncode": 999,
            "stdout": "",
            "stderr": str(e),
            "elapsed": round(ended - started, 3),
        }

def main():
    parser = argparse.ArgumentParser(
        description="Prosty test wspolbieznosci dla verifier/test_program.py"
    )
    parser.add_argument("--instance-key", required=True, help="Instance key do testu")
    parser.add_argument("--workers", type=int, default=20, help="Liczba procesow")
    parser.add_argument("--python-bin", default=sys.executable, help="Interpreter Python")
    parser.add_argument("--program-path", default="./test_program.py", help="Sciezka do test_program.py")
    parser.add_argument("--verbose", type=int, default=0, help="1 = wiecej logow na stderr")
    args = parser.parse_args()

    # Wstepna walidacja pliku programu
    if not os.path.exists(args.program_path):
        print(f"[ERROR] Nie znaleziono pliku: {args.program_path}")
        sys.exit(1)

    # Informacje startowe
    print("=== START TESTU WSPOLBIEZNOSCI ===")
    print(f"program_path : {args.program_path}")
    print(f"instance_key : {args.instance_key}")
    print(f"workers      : {args.workers}")
    print(f"python_bin   : {args.python_bin}")

    # Tworzymy pulle procesow
    # Uzywamy multiprocessing.Pool, aby wystartowac wiele rownoleglych prob
    pool = multiprocessing.Pool(processes=args.workers)

    try:
        jobs = []
        for i in range(args.workers):
            jobs.append(
                pool.apply_async(
                    worker,
                    (i + 1, args.instance_key, args.python_bin, args.program_path, args.verbose),
                )
            )

        pool.close()
        results = [job.get() for job in jobs]
        pool.join()
    finally:
        try:
            pool.terminate()
        except Exception:
            pass

    # Agregacja wynikow
    ok_count = 0
    err_count = 0
    locked_count = 0
    concurrent_count = 0
    wrong_old_pass_count = 0

    # Wypisujemy szczegoly kazdego procesu
    print("")
    print("=== WYNIKI SZCZEGOLOWE ===")
    for row in sorted(results, key=lambda x: x["proc_no"]):
        stdout_short = (row["stdout"] or "").strip().replace("\n", " | ")
        stderr_short = (row["stderr"] or "").strip().replace("\n", " | ")

        if row["returncode"] == 0:
            ok_count += 1
        else:
            err_count += 1

        text_all = f"{stdout_short} {stderr_short}".lower()

        if "database is locked" in text_all:
            locked_count += 1
        if "concurrent update detected" in text_all:
            concurrent_count += 1
        if "old password is incorrect" in text_all:
            wrong_old_pass_count += 1

        print(
            f"proc={row['proc_no']:02d} rc={row['returncode']} "
            f"elapsed={row['elapsed']}s "
            f"stdout={stdout_short!r} stderr={stderr_short!r}"
        )

    # Podsumowanie
    print("")
    print("=== PODSUMOWANIE ===")
    print(f"sukcesy                    : {ok_count}")
    print(f"bledy                      : {err_count}")
    print(f"wykryte 'database is locked': {locked_count}")
    print(f"wykryte 'concurrent update': {concurrent_count}")
    print(f"wykryte 'old password is incorrect': {wrong_old_pass_count}")

    # Heurystyka oceny
    print("")
    print("=== INTERPRETACJA ===")
    if ok_count == 1 and concurrent_count + wrong_old_pass_count >= 1 and locked_count == 0:
        print("[OK] Wyglada dobrze: jedna sesja przeszla, pozostale odpadly kontrolowanie.")
    elif ok_count >= 2:
        print("[UWAGA] Wiecej niz jedna sesja przeszla sukcesem. To moze wskazywac na dalszy wyscig.")
    elif locked_count > 0:
        print("[UWAGA] Wystapily blokady bazy. Mozna rozwazyc wiekszy busy_timeout lub mniejsza liczbe zapisow.")
    else:
        print("[INFO] Wynik jest niejednoznaczny. Warto uruchomic test kilka razy.")

if __name__ == "__main__":
    main()
