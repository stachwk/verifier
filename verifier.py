#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-

import os
import hashlib
import secrets
import configparser
import logging
from cryptography.fernet import Fernet, InvalidToken
from pysqlcipher3 import dbapi2 as sqlite3

class Verifier:
    """
    The Verifier class encapsulates:
      - loading configuration and keys,
      - communication with the SQLCipher database,
      - encrypting and decrypting data,
      - program authorization and credential operations.
      
    The log_or_print() helper either prints messages or writes them to a log file,
    depending on the LOG option in config.ini (section [main]).
    
    Note: get_context_password is only available after successful authorization
    via authenticate_and_regenerate.
    """
    def __init__(self, program_path: str):
        self.program_path = program_path
        self.instance_key = None
        self.config_file = "config.ini"
        # Load configuration
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Configuration file not found: {self.config_file}")
            self.config = configparser.ConfigParser()
            self.config.read(self.config_file)
            self.DB_NAME = self.config["paths"]["DB_NAME"]
            self.DB_KEY_FILE = self.config["paths"]["DB_KEY_FILE"]
            self.SECRET_KEY_FILE = self.config["paths"]["SECRET_KEY_FILE"]
        except Exception as e:
            raise Exception(f"Error while loading configuration: {e}")

        # Set up logger if [main] LOG=1
        self.logger = None
        if self.config.has_option("main", "LOG") and self.config.get("main", "LOG") == "1":
            self.logger = logging.getLogger("VerifierLogger")
            self.logger.setLevel(logging.ERROR)
            if not self.logger.handlers:
                fh = logging.FileHandler("verifier.log")
                fh.setLevel(logging.ERROR)
                formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
                fh.setFormatter(formatter)
                self.logger.addHandler(fh)

        # Load keys and compute program hash
        try:
            self.db_key = self._load_db_key()
            self.secret_cipher = self._load_secret_cipher()
            self.program_hash = self.hash_program(self.program_path)
            if self.program_hash is None:
                raise FileNotFoundError(f"Cannot read file: {self.program_path}")
        except Exception as e:
            self.log_or_print(f"Initialization error: {e}", "ERROR")
            raise Exception(f"Initialization error: {e}")

        self.authenticated = False

    def log_or_print(self, message: str, level: str = "INFO"):
        """
        If config.ini has LOG=1 in section [main], the message is written to the logger.
        Otherwise it is printed to stdout.
        """
        if self.logger:
            lvl = level.upper()
            if lvl == "INFO":
                self.logger.info(message)
            elif lvl == "WARNING":
                self.logger.warning(message)
            elif lvl == "ERROR":
                self.logger.error(message)
            else:
                self.logger.info(message)
        else:
            print(message)

    def _load_db_key(self) -> str:
        """Load or generate the SQLCipher key."""
        try:
            if not os.path.exists(self.DB_KEY_FILE):
                db_key = Fernet.generate_key()
                with open(self.DB_KEY_FILE, "wb") as f:
                    f.write(db_key)
                os.chmod(self.DB_KEY_FILE, 0o600)
            else:
                with open(self.DB_KEY_FILE, "rb") as f:
                    db_key = f.read()
            return db_key.decode()
        except Exception as e:
            self.log_or_print(f"Error loading DB key: {e}", "ERROR")
            raise Exception(f"Error loading DB key: {e}")

    def _load_secret_cipher(self) -> Fernet:
        """Load or generate the Fernet key used for column encryption."""
        try:
            if not os.path.exists(self.SECRET_KEY_FILE):
                key = Fernet.generate_key()
                with open(self.SECRET_KEY_FILE, "wb") as f:
                    f.write(key)
                os.chmod(self.SECRET_KEY_FILE, 0o600)
            else:
                with open(self.SECRET_KEY_FILE, "rb") as f:
                    key = f.read()
            return Fernet(key)
        except Exception as e:
            self.log_or_print(f"Error loading secret key: {e}", "ERROR")
            raise Exception(f"Error loading secret key: {e}")

    def get_db_connection(self):
        """Open a connection to the encrypted SQLCipher database."""
        try:
            conn = sqlite3.connect(self.DB_NAME)
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA key = '{self.db_key}'")
            cursor.execute("PRAGMA foreign_keys = ON")
            return conn, cursor
        except Exception as e:
            self.log_or_print(f"Error connecting to database: {e}", "ERROR")
            raise Exception(f"Error connecting to database: {e}")

    def commit_and_close(self, conn):
        """Commit and close the database connection."""
        try:
            conn.commit()
        except Exception as e:
            self.log_or_print(f"Error committing to database: {e}", "ERROR")
            raise Exception(f"Error committing to database: {e}")
        finally:
            try:
                conn.close()
            except Exception as e:
                self.log_or_print(f"Error closing database connection: {e}", "ERROR")
                raise Exception(f"Error closing database connection: {e}")

    def encrypt_col_value(self, plain_text: str) -> bytes:
        """Encrypt a text value."""
        try:
            return self.secret_cipher.encrypt(plain_text.encode())
        except Exception as e:
            self.log_or_print(f"Error encrypting data: {e}", "ERROR")
            raise Exception(f"Error encrypting data: {e}")

    def decrypt_col_value(self, encrypted: bytes) -> str:
        """Decrypt an encrypted value."""
        try:
            return self.secret_cipher.decrypt(encrypted).decode()
        except InvalidToken as it:
            self.log_or_print(f"Invalid encryption token: {it}", "ERROR")
            raise Exception(f"Invalid encryption token: {it}")
        except Exception as e:
            self.log_or_print(f"Error decrypting data: {e}", "ERROR")
            raise Exception(f"Error decrypting data: {e}")

    def hash_program(self, file_path: str) -> str | None:
        """Compute SHA-256 for a file."""
        sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    sha256.update(chunk)
            return sha256.hexdigest()
        except FileNotFoundError:
            return None
        except Exception as e:
            self.log_or_print(f"Error computing hash: {e}", "ERROR")
            raise Exception(f"Error computing hash: {e}")

    def generate_random_password(self, length: int = 12) -> str:
        """Generate a random password."""
        try:
            alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()_-+="
            return "".join(secrets.choice(alphabet) for _ in range(length))
        except Exception as e:
            self.log_or_print(f"Error generating password: {e}", "ERROR")
            raise Exception(f"Error generating password: {e}")

    def get_program(self, program_hash: str, instance_key: str):
        """
        Fetch a program record from the database by hash and instance key.
        Returns (program_hash, program_name, decrypted_password, instance_key) or None.
        """
        try:
            conn, cursor = self.get_db_connection()
            cursor.execute("""
                SELECT program_hash, program_name, program_password, instance_key
                FROM programs
                WHERE program_hash = ? AND instance_key = ?
            """, (program_hash, instance_key))
            row = cursor.fetchone()
            if not row:
                self.commit_and_close(conn)
                return None
            dec_pass = self.decrypt_col_value(row[2]) if row[2] else None
            result = (row[0], row[1], dec_pass, row[3])
            self.instance_key = instance_key
            self.commit_and_close(conn)
            return result
        except Exception as e:
            self.log_or_print(f"Error fetching program: {e}", "ERROR")
            raise Exception(f"Error fetching program: {e}")

    def update_program_password(self, program_hash: str, instance_key: str, new_pass: str):
        """Update the ephemeral program password for a given (program_hash, instance_key)."""
        try:
            enc = self.encrypt_col_value(new_pass)
            conn, cursor = self.get_db_connection()
            cursor.execute("""
                UPDATE programs
                SET program_password = ?
                WHERE program_hash = ? AND instance_key = ?
            """, (enc, program_hash, instance_key))
            self.commit_and_close(conn)
        except Exception as e:
            self.log_or_print(f"Error updating program password: {e}", "ERROR")
            raise Exception(f"Error updating program password: {e}")

    def authenticate_and_regenerate(self, old_pass: str, instance_key: str) -> tuple[bool, str | None]:
        """
        Authorize a program using the old password and instance key.
        On success, generate a new password, update the database record, and set self.authenticated to True.

        If a record exists for the given instance_key but the current file hash does not match
        the stored one, the method raises an exception.
        """
        try:
            row = self.get_program(self.program_hash, instance_key)
            if not row:
                # Check whether any record exists for this instance_key, ignoring the hash.
                conn, cursor = self.get_db_connection()
                cursor.execute("SELECT program_hash FROM programs WHERE instance_key = ?", (instance_key,))
                any_row = cursor.fetchone()
                self.commit_and_close(conn)
                if any_row is not None:
                    raise Exception("Hash mismatch: the program contents have changed.")
                else:
                    raise Exception("This program has not been authorized for this instance yet.")
            if row[2] != old_pass:
                raise Exception("The provided old password is incorrect.")
            new_pass = self.generate_random_password(12)
            self.update_program_password(self.program_hash, instance_key, new_pass)
            self.instance_key = instance_key
            self.authenticated = True
            return (True, new_pass)
        except Exception as e:
            self.log_or_print(f"Error in authenticate_and_regenerate: {e}", "ERROR")
            raise Exception(f"Error in authenticate_and_regenerate: {e}")

    def get_program_credentials(self, program_hash: str, instance_key: str | None = None) -> list[tuple[int, str, str, str]]:
        """Fetch all credentials linked to a program instance."""
        try:
            conn, cursor = self.get_db_connection()
            if instance_key is None:
                instance_key = self.instance_key
            if instance_key is None:
                raise Exception("Missing instance_key for fetching program credentials.")
            cursor.execute("""
                SELECT c.cred_id, c.context, c.subcontext, c.credential_data
                FROM credentials c
                JOIN program_credentials pc ON c.cred_id = pc.cred_id
                WHERE pc.program_hash = ? AND pc.instance_key = ?
            """, (program_hash, instance_key))
            rows = cursor.fetchall()
            self.commit_and_close(conn)
            results = []
            for cid, ctx, sctx, enc_val in rows:
                dec = self.decrypt_col_value(enc_val)
                results.append((cid, ctx, sctx, dec))
            return results
        except Exception as e:
            self.log_or_print(f"Error fetching program credentials: {e}", "ERROR")
            raise Exception(f"Error fetching program credentials: {e}")

    def get_context_password(self, context: str, subcontext: str) -> str | None:
        """
        Fetch the decrypted password for a given context and subcontext.
        Access is only allowed after successful authorization.
        """
        try:
            if not self.authenticated:
                raise Exception("Access denied. Run authenticate_and_regenerate first.")
            creds = self.get_program_credentials(self.program_hash, self.instance_key)
            for cid, ctx, sctx, dec_pass in creds:
                if ctx == context and sctx == subcontext:
                    return dec_pass
            return None
        except Exception as e:
            self.log_or_print(f"Error fetching context password: {e}", "ERROR")
            raise Exception(f"Error fetching context password: {e}")

    def create_credential(self, context: str, subcontext: str, plain_pass: str) -> int:
        """Create a new credential in the database and return its id."""
        try:
            enc = self.encrypt_col_value(plain_pass)
            conn, cursor = self.get_db_connection()
            cursor.execute("""
                INSERT INTO credentials (context, subcontext, credential_data)
                VALUES (?, ?, ?)
            """, (context, subcontext, enc))
            new_id = cursor.lastrowid
            self.commit_and_close(conn)
            return new_id
        except Exception as e:
            self.log_or_print(f"Error creating credential: {e}", "ERROR")
            raise Exception(f"Error creating credential: {e}")

    def get_credential(self, cred_id: int):
        """
        Fetch a credential by id.
        Returns (cred_id, context, subcontext, decrypted_data) or None.
        """
        try:
            conn, cursor = self.get_db_connection()
            cursor.execute("""
                SELECT cred_id, context, subcontext, credential_data
                FROM credentials
                WHERE cred_id = ?
            """, (cred_id,))
            row = cursor.fetchone()
            self.commit_and_close(conn)
            if not row:
                return None
            dec = self.decrypt_col_value(row[3]) if row[3] else None
            return (row[0], row[1], row[2], dec)
        except Exception as e:
            self.log_or_print(f"Error fetching credential id {cred_id}: {e}", "ERROR")
            raise Exception(f"Error fetching credential id {cred_id}: {e}")

    def link_program_to_credential(self, cred_id: int, instance_key: str | None = None):
        """Link the current program to a credential for a specific instance."""
        try:
            if instance_key is None:
                instance_key = self.instance_key
            if instance_key is None:
                raise Exception("Missing instance_key for linking a credential to a program.")
            conn, cursor = self.get_db_connection()
            cursor.execute("""
                INSERT OR IGNORE INTO program_credentials (program_hash, instance_key, cred_id)
                VALUES (?, ?, ?)
            """, (self.program_hash, instance_key, cred_id))
            self.commit_and_close(conn)
        except Exception as e:
            self.log_or_print(f"Error linking program to credential: {e}", "ERROR")
            raise Exception(f"Error linking program to credential: {e}")

    def get_credential_programs(self, cred_id: int) -> list[tuple[str, str]]:
        """Return a list of (program_hash, instance_key) pairs linked to a credential."""
        try:
            conn, cursor = self.get_db_connection()
            cursor.execute("""
                SELECT program_hash, instance_key
                FROM program_credentials
                WHERE cred_id = ?
            """, (cred_id,))
            rows = cursor.fetchall()
            self.commit_and_close(conn)
            return [(r[0], r[1]) for r in rows]
        except Exception as e:
            self.log_or_print(f"Error fetching programs for credential {cred_id}: {e}", "ERROR")
            raise Exception(f"Error fetching programs for credential {cred_id}: {e}")

# Example module usage when verifier.py is run directly
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: verifier.py <program_path> <old_password> [INSTANCE_KEY]")
        sys.exit(1)
    prog_path = sys.argv[1]
    old_password = sys.argv[2]
    try:
        verifier_instance = Verifier(prog_path)
        instance_key = sys.argv[3] if len(sys.argv) > 3 else "default"
        success, new_pass = verifier_instance.authenticate_and_regenerate(old_password, instance_key)
        if success:
            verifier_instance.log_or_print(f"[OK] Authorization complete, new password: {new_pass}", "INFO")
            try:
                ctx_pwd = verifier_instance.get_context_password("database", "read_only")
                if ctx_pwd:
                    verifier_instance.log_or_print(f"[INFO] Password for context 'database' / 'read_only': {ctx_pwd}", "INFO")
                else:
                    verifier_instance.log_or_print("[INFO] No password for the requested context.", "INFO")
            except Exception as e:
                verifier_instance.log_or_print(f"[ERROR] {e}", "ERROR")
        else:
            verifier_instance.log_or_print("[ERROR] Authorization failed.", "ERROR")
    except Exception as e:
        print(f"[ERROR] An error occurred: {e}")
