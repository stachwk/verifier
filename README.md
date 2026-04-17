# Verifier

Verifier is a small system for attaching session keys and credentials to specific
programs. Each program instance is identified by:

- the file `hash`
- the `instance_key`

The same file can therefore have multiple independent instances, and each instance
can have its own session key and its own linked credentials.

## Purpose

Verifier solves a practical problem: how to bind a secret to a specific program
without relying on a file name, a directory, or a manually entered identifier.

First the program proves its identity through its file hash. Then it proves which
instance it is, because the same code may run in multiple environments at the same
time. Only after that can it fetch its assigned credential.

That gives three important properties:

- the secret is attached to the real program file, not to its name
- multiple instances of the same program can have different session keys and
  credentials
- each successful authorization can refresh the session key, so old state is not
  valid forever

In practice, Verifier combines program identity, instance identity, and a linked
secret.

## End-to-End Quickstart

The easiest way to understand Verifier is to run the whole flow once.

### 1. Prepare configuration

Make sure `verifier_cfg.ini` points to your database and key files:

```ini
[paths]
DB_NAME = verifier.db
DB_KEY_FILE = verifier-db_key.key
SECRET_KEY_FILE = verifier-secret.key
```

If you want log files, enable them:

```ini
[main]
LOG = 1
```

### 2. Create the database

```bash
python3.12 verifier_cli.py --config ./verifier_cfg.ini --create-db
```

This creates the tables needed for programs, credentials, and the links between
them.

### 3. Authorize a program instance

```bash
python3.12 verifier_cli.py --config ./verifier_cfg.ini --authorize test_program ./test/unit/test_program.py 1
```

This command does four things:

- computes the hash of `./test/unit/test_program.py`
- stores the program name, hash, and `instance_key`
- generates a session key for that exact instance
- writes `test_program_1.key` next to the program file

If `cert.pem` and `key.pem` are present, they must be a valid administrator pair.

### 4. Create and link a credential

```bash
python3.12 verifier_cli.py --config ./verifier_cfg.ini --add-pwd-cmd ./test/unit/test_program.py database read_only Secret123 1
```

This creates a credential with:

- `context = database`
- `subcontext = read_only`
- credential password `Secret123`

Then it links that credential to the same program hash and the same `instance_key`.

### 5. Run the program

```bash
python3.12 test/unit/test_program.py 1 ./verifier_cfg.ini
```

The program then:

- reads the old key from `test_program_1.key`
- authenticates against the database
- gets a new session key
- rotates the key file
- reads the linked `database/read_only` credential

### 6. What success looks like

If the flow is correct, the output shows:

- the program was recognized by hash and `instance_key`
- the old session key was accepted
- a new session key was generated
- the key file was updated
- the linked credential was returned

## Full Example

```bash
python3.12 verifier_cli.py --config ./verifier_cfg.ini --create-db
python3.12 verifier_cli.py --config ./verifier_cfg.ini --authorize test_program ./test/unit/test_program.py 1
python3.12 verifier_cli.py --config ./verifier_cfg.ini --add-pwd-cmd ./test/unit/test_program.py database read_only Secret123 1
python3.12 test/unit/test_program.py 1 ./verifier_cfg.ini
```

For a faster bootstrap, you can also use:

```bash
./bootstrap_program_secret.sh example_program ./test/scenario/scenario_program_using_verifier.py 1 database read_only Secret123
```

Or bootstrap and run the scenario in one step:

```bash
./bootstrap_and_run_scenario.sh example_program 1 database read_only Secret123
```

## How It Works

1. Run `--create-db` to create the database tables.
2. Run `--authorize` with a program name, a file path, and an `instance_key`.
   This command requires a valid administrator `cert.pem` / `key.pem` pair.
3. The CLI stores:
   - the program hash in the database
   - the session key for that instance
   - a `<program_name>_<instance_key>.key` file
4. You can create a credential, for example a database credential password.
5. You then link that credential to a specific program instance.
6. The test program, when started for the same instance, can:
   - read the previous key from the program directory
   - confirm authorization
   - generate a new session key and replace the key file
   - fetch the credential linked to that program

## Important Rule

A program hash alone is not enough. To fetch a credential, the program must be:

- authorized in the database for the exact `instance_key`
- linked to a credential
- started with the correct key file

## Why It Is Built This Way

This structure protects against a few common problems:

- a file name alone is easy to copy
- a hash alone does not distinguish runtime environments
- one shared secret for all instances becomes inconvenient quickly
- storing passwords manually in files without control leads to drift and mistakes

Verifier offers a simple compromise:

- the database stores encrypted data
- the program has a local key file that can be refreshed
- credential assignment is explicit and tied to a concrete instance

This is not a full enterprise-grade secret manager. It is a small, understandable
mechanism for cases where a program should prove its identity and then receive only
the data assigned to it.

## What the Program Should Look Like

A program that uses Verifier should follow this structure:

1. Read `instance_key` from the command line.
2. Build `key_path` from the program directory and read the stored old session key.
3. Create `Verifier(program_path, config_file="/path/to/verifier_cfg.ini")` so the
   program hashes itself.
4. Call `authenticate_and_regenerate(old_pass, instance_key)`.
5. If authorization succeeds, call `get_context_password(...)`.
6. The new session key written by Verifier replaces the old key file.

Minimal skeleton:

```python
from verifier import Verifier
import sys
import os

def main():
    instance_key = sys.argv[1]
    program_path = os.path.abspath(__file__)
    key_path = os.path.join(os.path.dirname(program_path), f"test_program_{instance_key}.key")

    with open(key_path, "r") as f:
        old_pass = f.read().strip()

    verifier = Verifier(program_path, config_file="/path/to/verifier_cfg.ini")
    success, new_pass = verifier.authenticate_and_regenerate(old_pass, instance_key)
    if not success:
        return

    db_password = verifier.get_context_password("database", "read_only")
    print(db_password)

if __name__ == "__main__":
    main()
```

Important:

- `Verifier(__file__)` means the hash is computed from the current program file.
- `config_file` lets you point Verifier at a different `verifier_cfg.ini` location.
- The same file, started with a different `instance_key`, is treated as a separate
  instance.
- Credentials are returned only after successful authorization.
- If the program file changes, the hash changes and the existing record will no
  longer match.

## Main Files

- `verifier.py` - database, encryption, and authorization logic
- `verifier_cli.py` - CLI for database setup, authorization, and credential management
- `test/runtime_utils.py` - shared helpers for test, example, and scenario scripts
- `test/unit/test_program.py` - example program that uses the assigned key
- `bootstrap_program_secret.sh` - simple shell bootstrap for authorizing a program
  and linking a secret
- `bootstrap_and_run_scenario.sh` - bootstrap plus immediate scenario execution
- `test/example/example_program_using_verifier.py` - Python example that authenticates
  and reads a linked secret
- `test/scenario/scenario_program_using_verifier.py` - Python scenario that rotates
  the session key and then reads a linked secret
- `test/README.md` - overview of the test, example, and scenario layout

## Requirements

- Python 3.12 (the project was tested on Python 3.12.x)
- `cryptography`
- `pysqlcipher3`
- `cffi` as a helper dependency for `cryptography`

Example installation:

```bash
python3.12 -m pip install cryptography pysqlcipher3 cffi
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for the full
text.

## Configuration

The `verifier_cfg.ini` file should contain at least:

```ini
[paths]
DB_NAME = verifier.db
DB_KEY_FILE = verifier-db_key.key
SECRET_KEY_FILE = verifier-secret.key
```

To enable file logging, add:

```ini
[main]
LOG = 1
```

With `LOG = 0`, messages are printed to standard output.

The CLI accepts `--config /path/to/verifier_cfg.ini`, and the Python API accepts
`Verifier(..., config_file="/path/to/verifier_cfg.ini")`.

## TLS Material Guard

If `cert.pem` and `key.pem` are present in the project directory, Verifier treats
them as an additional identity condition for admin-only operations.

Verifier checks that:

- both files exist together
- the certificate and private key form a matching pair
- both files have owner-only permissions

Sensitive operations should fail if this validation does not pass.

Typical admin operations include:

- `--authorize`
- `--cleanup-progs`
- `--cleanup-progs-exec`

If the files are not present, the project can still operate in its normal mode.
If they are present, they are treated as an extra guard and must remain valid.

Plaintext secret access is not exposed by CLI list commands. Stored passwords and
session secrets should be read only through the authenticated program API after
`authenticate_and_regenerate`.

Recommended permissions:

```bash
chmod 600 cert.pem
chmod 600 key.pem
chmod 600 verifier.db verifier-db_key.key verifier-secret.key
```

## Database and Key Files

The following files must be treated as one consistent set:

- `verifier.db`
- `verifier-db_key.key`
- `verifier-secret.key`

Do not replace only one of them.

Important consequences:

- replacing `verifier-db_key.key` without the matching database will make SQLCipher
  report errors such as `file is not a database`
- replacing `verifier-secret.key` without the matching database may break decryption
  of encrypted column values
- restoring the database from backup should always restore the matching key files too

In practice, these three files should be backed up and restored together.

## Access Model

There are two separate access paths:

- administrator path: manage programs, instances, and authorization records
- program path: authenticate with the session key and read assigned secrets

These paths are intentionally not interchangeable.

## Backup and Restore

The project includes helper scripts that read paths from `verifier_cfg.ini`
located next to the scripts:

- `backup_verifier_state.sh`
- `restore_verifier_state.sh`

Usage:

```bash
./backup_verifier_state.sh
./backup_verifier_state.sh backup
./restore_verifier_state.sh backup/verifier_state_YYYYMMDD_HHMMSS
```

Behavior:

- the backup always includes the full runtime set
- restore requires the full set to be present in the backup directory
- relative paths from the config file are resolved against the directory of that file
- restored files are normalized to owner-only permissions

## Authorized Timestamp

The `programs` table stores `authorized_at`.

This value is used to:

- show when a program instance was last authorized
- confirm that repeated `--authorize` updates the active record
- simplify diagnostics and auditing

The `--create-db` command is expected to be idempotent, and repeated runs should not
break existing databases.

## Credential Management

The CLI supports two main workflows:

- creating a credential
- linking a credential to a program and instance

Key commands:

- `--create-cred` or `--create-cred-cmd`
- `--link-prog-cred` or `--link-prog-cred-cmd`
- `--list-prog-creds` or `--list-prog-creds-cmd`
- `--list-cred-progs` or `--list-cred-progs-cmd`
- `--list-creds`
- `--add-pwd-cmd`

A credential consists of:

- `context`
- `subcontext`
- encrypted password data

That lets you distinguish, for example, `database/read_only` from
`database/read_write`.

## Secret Visibility in CLI

By default, list-style CLI commands should not reveal decrypted secrets.

Typical behavior:

- `--list-progs` hides the session key
- `--list-prog-creds` and `--list-prog-creds-cmd` hide linked credential passwords
- plaintext is available only through the authenticated program API

This reduces accidental leakage to:

- terminal history
- scrollback buffers
- screenshots
- copied logs

## Error Handling

The project uses simple, readable error handling:

- a missing configuration file stops initialization
- a missing program file means the hash cannot be computed
- an invalid `instance_key` will not match a database record
- a wrong old session key prevents authorization
- a missing credential returns `None`

The error messages are meant to tell you immediately whether the problem is:

- configuration
- program file
- database
- instance key
- credential

## Summary

Verifier enables:

- encrypted storage of credentials
- linking those credentials to a specific program
- separating instances of the same program
- refreshing the key after each authorization

It is a lightweight, understandable mechanism for situations where a program should
prove its identity first and only then receive the data assigned to it.
