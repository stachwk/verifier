# Verifier

Verifier is a small system for attaching passwords and credentials to specific programs.
The program is identified by two values:

- the file `hash`
- the `instance_key`

That means the same file can have multiple independent instances, and each instance
can have its own ephemeral password and its own linked credentials.

## Purpose

Verifier solves a practical problem: how to bind a secret to a specific program in a way
that does not rely on a file name, a directory, or a manually entered identifier.

The program first proves its identity through its file hash. Then it proves which
instance it is, because the same code may run in multiple environments at the same time.
Only after that can it fetch its assigned credential.

This gives three important properties:

- the secret is attached to the real program file, not to its name
- multiple instances of the same program can have different passwords and credentials
- each successful authorization can refresh the key, so old state is not valid forever

In practice, Verifier is a lightweight mechanism for:

program identity + instance identity + linked secret

## How It Works

1. Run `--create-db` to create the database tables.
2. Run `--authorize` with a program name, a file path, and an `instance_key`.
3. The CLI stores:
   - the program hash in the database
   - the ephemeral password for that instance
   - a `<program_name>.hash` file
   - a `<program_name>_<instance_key>.key` file
4. You can create a credential, for example a database password.
5. You then link that credential to a specific program instance.
6. The test program, when started for the same instance, can:
   - read the previous key from disk
   - confirm authorization
   - generate a new password and replace the key file
   - fetch the credential linked to that program

## Important Rule

A program hash alone is not enough.
To fetch a credential, the program must be:

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

This is not a full enterprise-grade secret manager.
It is a small, understandable mechanism for cases where a program should prove its
identity and then receive only the data assigned to it.

## What the Program Should Look Like

A program that uses Verifier should follow a simple structure:

1. Read `instance_key` from the command line.
2. Open `test_program_<instance_key>.key` and read the stored old password.
3. Create `Verifier(__file__)` so the program hashes itself.
4. Call `authenticate_and_regenerate(old_pass, instance_key)`.
5. If authorization succeeds, call `get_context_password(...)`.
6. The new password written by Verifier replaces the old key file.

Minimal skeleton:

```python
from verifier import Verifier
import sys

def main():
    instance_key = sys.argv[1]
    key_file = f"test_program_{instance_key}.key"

    with open(key_file, "r") as f:
        old_pass = f.read().strip()

    verifier = Verifier(__file__)
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
- The same file, started with a different `instance_key`, is treated as a separate instance.
- Credentials are returned only after successful authorization.
- If the program file changes, the hash changes and the existing record will no longer match.

## Example Flow

```bash
python3.12 verifier_cli.py --create-db
python3.12 verifier_cli.py --authorize test_program ./test_program.py 1
python3.12 verifier_cli.py --add-pwd-cmd ./test_program.py database read_only Secret123 1
python3.12 test_program.py 1
```

Result:

- the program is recognized by hash and `instance_key`
- the old password is verified
- a new password is generated after successful authorization
- the `database/read_only` credential is fetched from the database

## Main Files

- `verifier.py` - database, encryption, and authorization logic
- `verifier_cli.py` - CLI for database setup, authorization, and credential management
- `test_program.py` - example program that uses the assigned key

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

This project is licensed under the MIT License. See [LICENSE](/media/wojtek/virtdata/home/wojtek/git/verifier/LICENSE) for the full text.

## Configuration

The `config.ini` file should contain at least:

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

That lets you distinguish, for example, `database/read_only` from `database/read_write`.

## Error Handling

The project uses simple, readable error handling:

- a missing configuration file stops initialization
- a missing program file means the hash cannot be computed
- an invalid `instance_key` will not match a database record
- a wrong old password prevents authorization
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
