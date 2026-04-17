#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-

import os
import hashlib
import secrets
import configparser
import logging
from cryptography import x509
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pysqlcipher3 import dbapi2 as sqlite3

class Verifier:
    """
    The Verifier class encapsulates:
      - loading configuration and keys,
      - communication with the SQLCipher database,
      - encrypting and decrypting data,
      - program authorization and credential operations.

    The log_or_print() helper either prints messages or writes them to a log file,
    depending on the LOG option in the configured ini file (section [main]).

    Note: get_context_password is only available after successful authorization
    via authenticate_and_regenerate.
    """
    def __init__(self, program_path: str, config_file: str | None = None):
        self.program_path = program_path
        self.instance_key = None
        self.config_file = config_file or "verifier_cfg.ini"
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
            self.logger.setLevel(logging.INFO)
            if not self.logger.handlers:
                fh = logging.FileHandler("verifier.log")
                fh.setLevel(logging.INFO)
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
        self.cert_file = "cert.pem"
        self.key_file = "key.pem"
        self._tls_pair_checked = False
        self._tls_pair_available = False

    def log_or_print(self, message: str, level: str = "INFO"):
        """
        If the configured ini file has LOG=1 in section [main], the message is written to the logger.
        In every case, the message is also printed to stdout so CLI users can see the result.
        """
        lvl = level.upper()
        if self.logger:
            if lvl == "INFO":
                self.logger.info(message)
            elif lvl == "WARNING":
                self.logger.warning(message)
            elif lvl == "ERROR":
                self.logger.error(message)
            else:
                self.logger.info(message)
        print(message)


    def _verify_file_owner_only_permissions(self, file_path: str):
        """Ensure that a sensitive file is not group/world accessible."""
        try:
            st_mode = os.stat(file_path).st_mode & 0o777
            if st_mode & 0o077:
                raise Exception(
                    f"Insecure permissions on '{file_path}'. Expected owner-only access, got mode {oct(st_mode)}."
                )
        except Exception as e:
            self.log_or_print(f"Error checking permissions for {file_path}: {e}", "ERROR")
            raise Exception(f"Error checking permissions for {file_path}: {e}")

    def verify_tls_pair_if_present(self) -> bool:
        """
        Validate cert.pem/key.pem if they are available in the working directory.

        Rules:
          - if neither file exists, return False and allow the caller to continue,
          - if only one exists, raise an exception,
          - if both exist, verify owner-only permissions and confirm they match.
        """
        try:
            cert_exists = os.path.exists(self.cert_file)
            key_exists = os.path.exists(self.key_file)

            if not cert_exists and not key_exists:
                self._tls_pair_checked = True
                self._tls_pair_available = False
                return False

            if cert_exists != key_exists:
                raise Exception(
                    "Incomplete TLS material set: both cert.pem and key.pem must be present together."
                )

            self._verify_file_owner_only_permissions(self.cert_file)
            self._verify_file_owner_only_permissions(self.key_file)

            with open(self.cert_file, "rb") as f:
                cert_data = f.read()
            with open(self.key_file, "rb") as f:
                key_data = f.read()

            cert_obj = x509.load_pem_x509_certificate(cert_data)
            key_obj = load_pem_private_key(key_data, password=None)

            cert_numbers = cert_obj.public_key().public_numbers()
            key_numbers = key_obj.public_key().public_numbers()

            if cert_numbers != key_numbers:
                raise Exception("cert.pem and key.pem do not match.")

            self._tls_pair_checked = True
            self._tls_pair_available = True
            return True
        except Exception as e:
            self.log_or_print(f"Error verifying TLS material: {e}", "ERROR")
            raise Exception(f"Error verifying TLS material: {e}")

    def require_tls_pair_for_sensitive_operation(self, operation_name: str):
        """
        If cert.pem/key.pem are available, require them to be a valid pair before
        allowing a sensitive operation to continue.
        """
        try:
            tls_available = self.verify_tls_pair_if_present()
            if tls_available:
                self.log_or_print(
                    f"[INFO] TLS material verified for sensitive operation: {operation_name}",
                    "INFO"
                )
        except Exception as e:
            self.log_or_print(
                f"Sensitive operation '{operation_name}' blocked by TLS verification error: {e}",
                "ERROR"
            )
            raise Exception(
                f"Sensitive operation '{operation_name}' blocked by TLS verification error: {e}"
            )

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
            conn = sqlite3.connect(self.DB_NAME, timeout=10)
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA key = '{self.db_key}'")
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA busy_timeout = 10000")
            try:
                cursor.execute("PRAGMA journal_mode = WAL")
            except Exception:
                pass
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
        """Generate a random secret."""
        try:
            alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()_-+="
            return "".join(secrets.choice(alphabet) for _ in range(length))
        except Exception as e:
            self.log_or_print(f"Error generating secret: {e}", "ERROR")
            raise Exception(f"Error generating secret: {e}")

    def get_program(self, program_hash: str, instance_key: str):
        """
        Fetch a program record from the database by hash and instance key.
        Returns (program_hash, program_name, decrypted_session_key, instance_key) or None.
        """
        try:
            self.require_tls_pair_for_sensitive_operation("get_program")
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
        """Update the ephemeral program session key for a given (program_hash, instance_key)."""
        try:
            self.require_tls_pair_for_sensitive_operation("update_program_password")
            enc = self.encrypt_col_value(new_pass)
            conn, cursor = self.get_db_connection()
            cursor.execute("""
                UPDATE programs
                SET program_password = ?
                WHERE program_hash = ? AND instance_key = ?
            """, (enc, program_hash, instance_key))
            self.commit_and_close(conn)
        except Exception as e:
            self.log_or_print(f"Error updating program session key: {e}", "ERROR")
            raise Exception(f"Error updating program session key: {e}")

    def authenticate_and_regenerate(self, old_pass: str, instance_key: str) -> tuple[bool, str | None]:
        """
        Authorize a program using the old session key and instance key.
        On success, generate a new session key and atomically update the record in one transaction.

        If a record exists for the given instance_key but the current file hash does not match
        the stored one, the method raises an exception.
        """
        conn = None
        try:
            self.require_tls_pair_for_sensitive_operation("authenticate_and_regenerate")
            conn, cursor = self.get_db_connection()

            # Bierzemy blokade zapisu od razu, aby uniknac wyscigu miedzy sesjami
            cursor.execute("BEGIN IMMEDIATE")

            cursor.execute("""
                SELECT program_hash, program_name, program_password, instance_key
                FROM programs
                WHERE program_hash = ? AND instance_key = ?
            """, (self.program_hash, instance_key))
            row = cursor.fetchone()

            if not row:
                # Sprawdzamy, czy instance_key istnieje dla innego hasha
                cursor.execute("SELECT program_hash FROM programs WHERE instance_key = ?", (instance_key,))
                any_row = cursor.fetchone()
                conn.rollback()
                if any_row is not None:
                    raise Exception("Hash mismatch: the program contents have changed.")
                raise Exception("This program has not been authorized for this instance yet.")

            current_pass = self.decrypt_col_value(row[2]) if row[2] else None
            if current_pass != old_pass:
                conn.rollback()
                raise Exception("The provided old session key is incorrect.")

            new_pass = self.generate_random_password(12)
            new_enc = self.encrypt_col_value(new_pass)

            # Warunkowy update - tylko jesli rekord nadal ma poprzednia wartosc
            cursor.execute("""
                UPDATE programs
                SET program_password = ?
                WHERE program_hash = ? AND instance_key = ? AND program_password = ?
            """, (new_enc, self.program_hash, instance_key, row[2]))

            if cursor.rowcount != 1:
                conn.rollback()
                raise Exception("Concurrent update detected. Please retry authentication.")

            conn.commit()
            self.instance_key = instance_key
            self.authenticated = True
            return (True, new_pass)
        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            self.log_or_print(f"Error in authenticate_and_regenerate: {e}", "ERROR")
            raise Exception(f"Error in authenticate_and_regenerate: {e}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def get_program_credentials(self, program_hash: str, instance_key: str | None = None) -> list[tuple[int, str, str, str]]:
        """Fetch all credentials linked to a program instance."""
        try:
            self.require_tls_pair_for_sensitive_operation("get_program_credentials")
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
        Fetch the decrypted credential password for a given context and subcontext.
        Access is only allowed after successful authorization.
        """
        try:
            self.require_tls_pair_for_sensitive_operation("get_context_password")
            if not self.authenticated:
                raise Exception("Access denied. Run authenticate_and_regenerate first.")
            creds = self.get_program_credentials(self.program_hash, self.instance_key)
            for cid, ctx, sctx, dec_pass in creds:
                if ctx == context and sctx == subcontext:
                    return dec_pass
            return None
        except Exception as e:
            self.log_or_print(f"Error fetching context credential password: {e}", "ERROR")
            raise Exception(f"Error fetching context credential password: {e}")

    def create_credential(self, context: str, subcontext: str, plain_pass: str) -> int:
        """Create a new credential in the database and return its id."""
        try:
            self.require_tls_pair_for_sensitive_operation("create_credential")
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
            self.require_tls_pair_for_sensitive_operation("get_credential")
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
            self.require_tls_pair_for_sensitive_operation("link_program_to_credential")
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
        print("Usage: verifier.py <program_path> <old_session_key> [INSTANCE_KEY]")
        sys.exit(1)
    prog_path = sys.argv[1]
    old_session_key = sys.argv[2]
    try:
        verifier_instance = Verifier(prog_path)
        instance_key = sys.argv[3] if len(sys.argv) > 3 else "default"
        success, new_pass = verifier_instance.authenticate_and_regenerate(old_session_key, instance_key)
        if success:
            verifier_instance.log_or_print(f"[OK] Authorization complete, new session key: {new_pass}", "INFO")
            try:
                ctx_pwd = verifier_instance.get_context_password("database", "read_only")
                if ctx_pwd:
                    verifier_instance.log_or_print(f"[INFO] Credential password for context 'database' / 'read_only': {ctx_pwd}", "INFO")
                else:
                    verifier_instance.log_or_print("[INFO] No credential password for the requested context.", "INFO")
            except Exception as e:
                verifier_instance.log_or_print(f"[ERROR] {e}", "ERROR")
        else:
            verifier_instance.log_or_print("[ERROR] Authorization failed.", "ERROR")
    except Exception as e:
        print(f"[ERROR] An error occurred: {e}")
