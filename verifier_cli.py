#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-

import argparse
import sys
import getpass
import configparser
import logging
from verifier import Verifier
import os

# Helper function for logging or printing messages
def log_or_print(message: str, level: str = "INFO"):
    config = configparser.ConfigParser()
    config.read("config.ini")
    if config.has_option("main", "LOG") and config.get("main", "LOG") == "1":
        logger = logging.getLogger("CLI_Logger")
        logger.setLevel(logging.ERROR)
        if not logger.handlers:
            fh = logging.FileHandler("verifier_cli.log")
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

def create_database():
    """
    Create the database if needed with 3 tables:
      - programs (primary key: (program_hash, instance_key))
      - credentials
      - program_credentials

    If the programs table already exists without authorized_at, add that column.
    """
    try:
        verifier_instance = Verifier(sys.argv[0])
        conn, cursor = verifier_instance.get_db_connection()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS programs (
                program_hash TEXT,
                program_name TEXT,
                program_password BLOB,
                instance_key TEXT,
                authorized_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (program_hash, instance_key)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS credentials (
                cred_id INTEGER PRIMARY KEY AUTOINCREMENT,
                context TEXT,
                subcontext TEXT,
                credential_data BLOB
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS program_credentials (
                program_hash TEXT,
                instance_key TEXT,
                cred_id INTEGER,
                PRIMARY KEY (program_hash, instance_key, cred_id),
                FOREIGN KEY (program_hash, instance_key) REFERENCES programs(program_hash, instance_key)
                    ON DELETE CASCADE ON UPDATE CASCADE,
                FOREIGN KEY (cred_id) REFERENCES credentials(cred_id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            )
        """)

        # Migracja: dodaj authorized_at, jesli tabela programs jeszcze nie ma tej kolumny
        cursor.execute("PRAGMA table_info(programs)")
        program_columns = [str(row[1]).lower() for row in cursor.fetchall()]

        if "authorized_at" not in program_columns:
            try:
                cursor.execute("""
                    ALTER TABLE programs
                    ADD COLUMN authorized_at TEXT
                """)
            except Exception as e:
                if "duplicate column name" not in str(e).lower():
                    raise

            cursor.execute("""
                UPDATE programs
                SET authorized_at = CURRENT_TIMESTAMP
                WHERE authorized_at IS NULL
            """)

        cursor.execute("PRAGMA table_info(program_credentials)")
        columns = [row[1] for row in cursor.fetchall()]
        if columns and "instance_key" not in columns:
            cursor.execute("DROP TABLE IF EXISTS program_credentials_new")
            cursor.execute("""
                CREATE TABLE program_credentials_new (
                    program_hash TEXT,
                    instance_key TEXT,
                    cred_id INTEGER,
                    PRIMARY KEY (program_hash, instance_key, cred_id),
                    FOREIGN KEY (program_hash, instance_key) REFERENCES programs(program_hash, instance_key)
                        ON DELETE CASCADE ON UPDATE CASCADE,
                    FOREIGN KEY (cred_id) REFERENCES credentials(cred_id)
                        ON DELETE CASCADE ON UPDATE CASCADE
                )
            """)
            cursor.execute("""
                INSERT OR IGNORE INTO program_credentials_new (program_hash, instance_key, cred_id)
                SELECT pc.program_hash, p.instance_key, pc.cred_id
                FROM program_credentials pc
                JOIN (
                    SELECT program_hash, MIN(instance_key) AS instance_key
                    FROM programs
                    GROUP BY program_hash
                    HAVING COUNT(*) = 1
                ) p ON p.program_hash = pc.program_hash
            """)
            cursor.execute("DROP TABLE program_credentials")
            cursor.execute("ALTER TABLE program_credentials_new RENAME TO program_credentials")
        verifier_instance.commit_and_close(conn)
        log_or_print("[OK] Database created or already existed.", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] Error creating database: {e}", "ERROR")

def authorize_program(program_name: str, program_path: str, instance_key: str):
    """
    Add or update a program in the database and generate an ephemeral password.
    Also create:
      - <program_name>.hash (contains the program hash)
      - <program_name>_<instance_key>.key (contains the ephemeral password)

    For the same (program_name, instance_key), stale rows with old hashes are removed,
    so only the currently authorized file version remains active.
    """
    conn = None
    try:
        verifier_instance = Verifier(program_path)
        new_pass = verifier_instance.generate_random_password(12)
        conn, cursor = verifier_instance.get_db_connection()
        cursor.execute("BEGIN IMMEDIATE")

        # Usuwamy stare wpisy dla tej samej nazwy programu i tej samej instancji,
        # ale z innym hashem. To zapobiega narastaniu historycznych hashy.
        cursor.execute("""
            DELETE FROM programs
            WHERE program_name = ? AND instance_key = ? AND program_hash <> ?
        """, (program_name, instance_key, verifier_instance.program_hash))

        cursor.execute("""
            SELECT program_hash
            FROM programs
            WHERE program_hash = ? AND instance_key = ?
        """, (verifier_instance.program_hash, instance_key))
        row = cursor.fetchone()

        enc_pass = verifier_instance.encrypt_col_value(new_pass)

        if row:
            cursor.execute("""
                UPDATE programs
                SET program_name = ?, program_password = ?, authorized_at = CURRENT_TIMESTAMP
                WHERE program_hash = ? AND instance_key = ?
            """, (program_name, enc_pass, verifier_instance.program_hash, instance_key))
            conn.commit()
            log_or_print(
                f"[OK] Updated program '{program_name}' "
                f"(hash={verifier_instance.program_hash}, instance_key={instance_key}). "
                f"Password: {new_pass}",
                "INFO"
            )
        else:
            cursor.execute("""
                INSERT INTO programs (program_hash, program_name, program_password, instance_key, authorized_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (verifier_instance.program_hash, program_name, enc_pass, instance_key))
            conn.commit()
            log_or_print(
                f"[OK] Added new program '{program_name}' "
                f"(hash={verifier_instance.program_hash}, instance_key={instance_key}). "
                f"Password: {new_pass}",
                "INFO"
            )

        # Save the hash file
        hash_filename = f"{program_name}.hash"
        try:
            with open(hash_filename, "w") as f:
                f.write(verifier_instance.program_hash + "\n")
            log_or_print(f"[INFO] Created hash file: {hash_filename}", "INFO")
        except Exception as e:
            log_or_print(f"[ERROR] Could not save hash file: {e}", "ERROR")

        # Save the key file
        key_filename = f"{program_name}_{instance_key}.key"
        try:
            with open(key_filename, "w") as f:
                f.write(new_pass + "\n")
            log_or_print(f"[INFO] Created key file: {key_filename}", "INFO")
        except Exception as e:
            log_or_print(f"[ERROR] Could not save key file: {e}", "ERROR")

    except Exception as e:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        log_or_print(f"[ERROR] Error in authorize_program: {e}", "ERROR")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

def cleanup_stale_program_hashes(program_name: str, program_path: str, instance_key: str, execute: bool = False):
    """
    Show and optionally remove stale program hashes for the same (program_name, instance_key).
    The current hash is computed from program_path and is always preserved.
    """
    conn = None
    try:
        verifier_instance = Verifier(program_path)
        current_hash = verifier_instance.program_hash
        conn, cursor = verifier_instance.get_db_connection()
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute("""
            SELECT program_hash, program_name, instance_key
            FROM programs
            WHERE program_name = ? AND instance_key = ?
            ORDER BY program_hash
        """, (program_name, instance_key))
        rows = cursor.fetchall()

        log_or_print("=== ZNALEZIONE WPISY ===", "INFO")
        if not rows:
            conn.rollback()
            log_or_print("[INFO] Brak wpisow do analizy.", "INFO")
            return

        stale_hashes = []
        for program_hash, found_program_name, found_instance_key in rows:
            marker = "KEEP" if program_hash == current_hash else "DROP"
            if program_hash != current_hash:
                stale_hashes.append(program_hash)
            log_or_print(
                f"{marker} hash={program_hash} program_name={found_program_name} instance_key={found_instance_key}",
                "INFO"
            )

        log_or_print("=== PODSUMOWANIE ===", "INFO")
        log_or_print(f"aktualny_hash : {current_hash}", "INFO")
        log_or_print(f"liczba_wpisow : {len(rows)}", "INFO")
        log_or_print(f"do_usuniecia  : {len(stale_hashes)}", "INFO")
        log_or_print(f"tryb         : {'EXECUTE' if execute else 'DRY-RUN'}", "INFO")

        if not execute:
            conn.rollback()
            log_or_print("[INFO] To byl dry-run. Dodaj --cleanup-progs-exec, aby wykonac usuwanie.", "INFO")
            return

        cursor.execute("""
            DELETE FROM programs
            WHERE program_name = ? AND instance_key = ? AND program_hash <> ?
        """, (program_name, instance_key, current_hash))
        deleted = cursor.rowcount
        conn.commit()

        log_or_print("[OK] Usuwanie wykonane.", "INFO")
        log_or_print(f"[INFO] Usuniete wpisy: {deleted}", "INFO")
    except Exception as e:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        log_or_print(f"[ERROR] Error in cleanup_stale_program_hashes: {e}", "ERROR")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

def list_programs():
    """Display all programs in the database."""
    try:
        verifier_instance = Verifier(sys.argv[0])
        conn, cursor = verifier_instance.get_db_connection()
        cursor.execute("""
            SELECT program_hash, program_name, program_password, instance_key, authorized_at
            FROM programs
            ORDER BY program_name, instance_key, authorized_at DESC, program_hash
        """)
        rows = cursor.fetchall()
        verifier_instance.commit_and_close(conn)
        log_or_print("[INFO] Program list:", "INFO")
        for phash, pname, enc_pass, ikey, authorized_at in rows:
            dec_pass = verifier_instance.decrypt_col_value(enc_pass) if enc_pass else None
            log_or_print(
                f" - {phash} | name='{pname}', instance_key='{ikey}', "
                f"authorized_at='{authorized_at}', ephemeral_password='{dec_pass}'",
                "INFO"
            )
    except Exception as e:
        log_or_print(f"[ERROR] Error listing programs: {e}", "ERROR")

def list_credentials():
    """Display all credentials stored in the database."""
    try:
        verifier_instance = Verifier(sys.argv[0])
        conn, cursor = verifier_instance.get_db_connection()
        cursor.execute("""
            SELECT cred_id, context, subcontext, credential_data FROM credentials
        """)
        rows = cursor.fetchall()
        verifier_instance.commit_and_close(conn)
        log_or_print("[INFO] Credential list:", "INFO")
        for cred_id, context, subcontext, enc_data in rows:
            try:
                dec_data = verifier_instance.decrypt_col_value(enc_data)
            except Exception as e:
                dec_data = f"<decrypt error: {e}>"
            log_or_print(f" - cred_id: {cred_id}, context: {context}, subcontext: {subcontext}, data: {dec_data}", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] Error fetching credentials: {e}", "ERROR")

# Interactive versions of the functions:
def create_credential_cli():
    """Interactively create a new credential."""
    try:
        print("Enter context (for example 'database'):")
        context = input("> ").strip()
        print("Enter subcontext (for example 'read_write' or 'default'):")
        subctx = input("> ").strip()
        if not subctx:
            subctx = "default"
        pwd = getpass.getpass("Password to store: ")
        verifier_instance = Verifier(sys.argv[0])
        cid = verifier_instance.create_credential(context, subctx, pwd)
        log_or_print(f"[OK] Created credential id={cid}.", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] Error creating credential: {e}", "ERROR")

def link_program_credential_cli():
    """Interactively link a program with a credential."""
    try:
        print("Enter the program path:")
        prog_path = input("> ").strip()
        verifier_instance = Verifier(prog_path)
        instance_key = input("Enter instance_key: ").strip()
        row = verifier_instance.get_program(verifier_instance.program_hash, instance_key)
        if not row:
            log_or_print("[ERROR] Program does not exist in the database. Run --authorize first.", "ERROR")
            return
        print("Enter the cred_id to link:")
        cid_str = input("> ").strip()
        if not cid_str.isdigit():
            log_or_print("[ERROR] Invalid cred_id.", "ERROR")
            return
        cid = int(cid_str)
        cred_row = verifier_instance.get_credential(cid)
        if not cred_row:
            log_or_print("[ERROR] No such credential exists.", "ERROR")
            return
        verifier_instance.link_program_to_credential(cid, instance_key)
        log_or_print(f"[OK] Program {verifier_instance.program_hash} linked to cred_id={cid}.", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] Error linking credential to program: {e}", "ERROR")

def list_program_credentials_cli():
    """Interactively display credentials linked to a program."""
    try:
        print("Enter the program path:")
        prog_path = input("> ").strip()
        verifier_instance = Verifier(prog_path)
        instance_key = input("Enter instance_key: ").strip()
        row = verifier_instance.get_program(verifier_instance.program_hash, instance_key)
        if not row:
            log_or_print("[ERROR] Program does not exist in the database.", "ERROR")
            return
        creds = verifier_instance.get_program_credentials(verifier_instance.program_hash, instance_key)
        if creds:
            log_or_print(f"[INFO] Program {verifier_instance.program_hash} (instance_key={instance_key}) has linked credentials:", "INFO")
            for cid, ctx, sctx, pwd in creds:
                log_or_print(f"  cred_id={cid}, context='{ctx}', subcontext='{sctx}', pass='{pwd}'", "INFO")
        else:
            log_or_print("[INFO] No credentials are linked to this program.", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] Error listing program credentials: {e}", "ERROR")

def list_credential_programs_cli():
    """Interactively display programs linked to a credential."""
    try:
        print("Enter cred_id:")
        cid_str = input("> ").strip()
        if not cid_str.isdigit():
            log_or_print("[ERROR] Invalid cred_id.", "ERROR")
            return
        cid = int(cid_str)
        verifier_instance = Verifier(sys.argv[0])
        c_row = verifier_instance.get_credential(cid)
        if not c_row:
            log_or_print("[ERROR] No such credential exists in the database.", "ERROR")
            return
        progs = verifier_instance.get_credential_programs(cid)
        if progs:
            log_or_print(f"[INFO] Credential id={cid} (context='{c_row[1]}', subcontext='{c_row[2]}') is linked to programs:", "INFO")
            for program_hash, instance_key in progs:
                log_or_print(f" - {program_hash} (instance_key={instance_key})", "INFO")
        else:
            log_or_print("[INFO] No program is linked to this credential.", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] Error fetching programs for credential: {e}", "ERROR")

def add_pwd_cmd(program_path: str, context: str, subcontext: str, password: str, instance_key: str):
    """
    Non-interactive version: create a new credential for the given context/subcontext and link it to a program.
    """
    try:
        verifier_instance = Verifier(program_path)
        row = verifier_instance.get_program(verifier_instance.program_hash, instance_key)
        if not row:
            log_or_print(f"[ERROR] Program (hash={verifier_instance.program_hash}) is not in the database. Run --authorize first.", "ERROR")
            return
        cid = verifier_instance.create_credential(context, subcontext, password)
        log_or_print(f"[INFO] Created new credential (id={cid}) for (context={context}, subcontext={subcontext}).", "INFO")
        verifier_instance.link_program_to_credential(cid, instance_key)
        log_or_print(f"[OK] Program (hash={verifier_instance.program_hash}) linked to cred_id={cid}.", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] Error in add_pwd_cmd: {e}", "ERROR")

def add_pwd_interactive():
    """
    Interactive version: the user is prompted for:
      - program path
      - context
      - subcontext
      - password
      - instance_key
    Then the credential is created and linked to the program.
    """
    try:
        print("Enter the program path:")
        prog_path = input("> ").strip()
        print("Enter context (for example 'database'):")
        context = input("> ").strip()
        print("Enter subcontext (for example 'read_write' or 'default'):")
        subctx = input("> ").strip()
        if not subctx:
            subctx = "default"
        password = getpass.getpass("Enter the password to store: ")
        print("Enter instance_key:")
        instance_key = input("> ").strip()

        verifier_instance = Verifier(prog_path)
        row = verifier_instance.get_program(verifier_instance.program_hash, instance_key)
        if not row:
            log_or_print(f"[ERROR] Program (hash={verifier_instance.program_hash}) is not in the database. Run --authorize first.", "ERROR")
            return
        cid = verifier_instance.create_credential(context, subctx, password)
        log_or_print(f"[INFO] Created new credential (id={cid}) for (context={context}, subcontext={subctx}).", "INFO")
        verifier_instance.link_program_to_credential(cid, instance_key)
        log_or_print(f"[OK] Program (hash={verifier_instance.program_hash}) linked to cred_id={cid}.", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] Error in interactive add_pwd: {e}", "ERROR")

# CMD versions - non-interactive functions that take command-line parameters

def create_credential_cmd(context: str, subcontext: str, password: str):
    """
    Non-interactive credential creation.
    Takes CONTEXT, SUBCONTEXT, PASSWORD and prints the created identifier.
    """
    try:
        verifier_instance = Verifier(sys.argv[0])
        cid = verifier_instance.create_credential(context, subcontext, password)
        log_or_print(f"[OK] Stworzono credential (id={cid}) dla context='{context}', subcontext='{subcontext}'.", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] Error creating credential (cmd): {e}", "ERROR")

def link_prog_cred_cmd(program_path: str, instance_key: str, cred_id: str):
    """
    Non-interactive program-to-credential linking.
    Takes PROGRAM_PATH, INSTANCE_KEY and CRED_ID.
    """
    try:
        if not cred_id.isdigit():
            log_or_print("[ERROR] Invalid CRED_ID.", "ERROR")
            return
        cred_id_int = int(cred_id)
        verifier_instance = Verifier(program_path)
        row = verifier_instance.get_program(verifier_instance.program_hash, instance_key)
        if not row:
            log_or_print("[ERROR] Program does not exist in the database. Run --authorize first.", "ERROR")
            return
        cred_row = verifier_instance.get_credential(cred_id_int)
        if not cred_row:
            log_or_print("[ERROR] No such credential exists.", "ERROR")
            return
        verifier_instance.link_program_to_credential(cred_id_int, instance_key)
        log_or_print(f"[OK] Program {verifier_instance.program_hash} (instance_key={instance_key}) linked to cred_id={cred_id_int}.", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] Error linking (cmd): {e}", "ERROR")

def list_prog_creds_cmd(program_path: str, instance_key: str):
    """
    Non-interactive display of credentials linked to a program.
    Takes PROGRAM_PATH and INSTANCE_KEY.
    """
    try:
        verifier_instance = Verifier(program_path)
        row = verifier_instance.get_program(verifier_instance.program_hash, instance_key)
        if not row:
            log_or_print("[ERROR] Program does not exist in the database.", "ERROR")
            return
        creds = verifier_instance.get_program_credentials(verifier_instance.program_hash, instance_key)
        if creds:
            log_or_print(f"[INFO] Program {verifier_instance.program_hash} (instance_key={instance_key}) has linked credentials:", "INFO")
            for cid, ctx, sctx, pwd in creds:
                log_or_print(f"  cred_id={cid}, context='{ctx}', subcontext='{sctx}', pass='{pwd}'", "INFO")
        else:
            log_or_print("[INFO] No credentials are linked to this program.", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] Error listing credentials (cmd): {e}", "ERROR")

def list_cred_progs_cmd(cred_id: str):
    """
    Non-interactive display of programs linked to a credential.
    Takes CRED_ID.
    """
    try:
        if not cred_id.isdigit():
            log_or_print("[ERROR] Invalid CRED_ID.", "ERROR")
            return
        cred_id_int = int(cred_id)
        verifier_instance = Verifier(sys.argv[0])
        c_row = verifier_instance.get_credential(cred_id_int)
        if not c_row:
            log_or_print("[ERROR] No such credential exists in the database.", "ERROR")
            return
        progs = verifier_instance.get_credential_programs(cred_id_int)
        if progs:
            log_or_print(f"[INFO] Credential id={cred_id_int} (context='{c_row[1]}', subcontext='{c_row[2]}') is linked to programs:", "INFO")
            for program_hash, instance_key in progs:
                log_or_print(f" - {program_hash} (instance_key={instance_key})", "INFO")
        else:
            log_or_print("[INFO] No program is linked to this credential.", "INFO")
    except Exception as e:
        log_or_print(f"[ERROR] Error fetching programs for credential (cmd): {e}", "ERROR")

def main():
    try:
        parser = argparse.ArgumentParser(
            description="CLI for managing programs and credentials using the Verifier class."
        )
        parser.add_argument("--create-db", action="store_true", help="Create tables if they do not exist.")
        parser.add_argument("--authorize", nargs=3, metavar=("PROGRAM_NAME", "PROGRAM_PATH", "INSTANCE_KEY"),
                            help="Authorize a program (command mode) - provide name, path, and instance_key.")
        parser.add_argument("--list-progs", action="store_true", help="List programs in the database (command mode).")
        parser.add_argument("--cleanup-progs", nargs=3, metavar=("PROGRAM_NAME", "PROGRAM_PATH", "INSTANCE_KEY"),
                            help="Dry-run cleanup of stale hashes for a program and instance.")
        parser.add_argument("--cleanup-progs-exec", nargs=3, metavar=("PROGRAM_NAME", "PROGRAM_PATH", "INSTANCE_KEY"),
                            help="Execute cleanup of stale hashes for a program and instance.")
        # Interactive versions
        parser.add_argument("--create-cred", action="store_true", help="Interactively create a credential.")
        parser.add_argument("--link-prog-cred", action="store_true", help="Interactively link a program to a credential.")
        parser.add_argument("--list-prog-creds", action="store_true", help="Interactively show credentials for a program.")
        parser.add_argument("--list-cred-progs", action="store_true", help="Interactively show programs for a given cred_id.")
        parser.add_argument("--add-pwd", action="store_true", help="Interactively create a new credential and link it to a program.")
        # Non-interactive (cmd) versions
        parser.add_argument("--create-cred-cmd", nargs=3, metavar=("CONTEXT", "SUBCONTEXT", "PASSWORD"),
                            help="Create a new credential (command mode).")
        parser.add_argument("--link-prog-cred-cmd", nargs=3, metavar=("PROGRAM_PATH", "INSTANCE_KEY", "CRED_ID"),
                            help="Link a program to a credential (command mode).")
        parser.add_argument("--list-prog-creds-cmd", nargs=2, metavar=("PROGRAM_PATH", "INSTANCE_KEY"),
                            help="Show program credentials (command mode).")
        parser.add_argument("--list-cred-progs-cmd", nargs=1, metavar=("CRED_ID",),
                            help="Show programs for a given cred_id (command mode).")
        parser.add_argument("--add-pwd-cmd", nargs=5, metavar=("PROGRAM_PATH", "CONTEXT", "SUBCONTEXT", "PASSWORD", "INSTANCE_KEY"),
                            help="Create a new credential and link it to a program (command mode).")
        args = parser.parse_args()

        if args.create_db:
            create_database()
        elif args.authorize:
            prog_name, prog_path, inst_key = args.authorize
            authorize_program(prog_name, prog_path, inst_key)
        elif args.list_progs:
            list_programs()
        elif args.cleanup_progs:
            prog_name, prog_path, inst_key = args.cleanup_progs
            cleanup_stale_program_hashes(prog_name, prog_path, inst_key, execute=False)
        elif args.cleanup_progs_exec:
            prog_name, prog_path, inst_key = args.cleanup_progs_exec
            cleanup_stale_program_hashes(prog_name, prog_path, inst_key, execute=True)
        elif args.create_cred:
            create_credential_cli()
        elif args.link_prog_cred:
            link_program_credential_cli()
        elif args.list_prog_creds:
            list_program_credentials_cli()
        elif args.list_cred_progs:
            list_credential_programs_cli()
        elif args.add_pwd:
            add_pwd_interactive()
        elif args.create_cred_cmd:
            context, subctx, pwd = args.create_cred_cmd
            create_credential_cmd(context, subctx, pwd)
        elif args.link_prog_cred_cmd:
            prog_path, inst_key, cred_id = args.link_prog_cred_cmd
            link_prog_cred_cmd(prog_path, inst_key, cred_id)
        elif args.list_prog_creds_cmd:
            prog_path, inst_key = args.list_prog_creds_cmd
            list_prog_creds_cmd(prog_path, inst_key)
        elif args.list_cred_progs_cmd:
            (cred_id,) = args.list_cred_progs_cmd
            list_cred_progs_cmd(cred_id)
        elif args.add_pwd_cmd:
            prog_path, context, subctx, pwd, inst_key = args.add_pwd_cmd
            add_pwd_cmd(prog_path, context, subctx, pwd, inst_key)
        else:
            parser.print_help()
    except Exception as e:
        log_or_print(f"[ERROR] An unexpected error occurred: {e}", "ERROR")

if __name__ == "__main__":
    main()
