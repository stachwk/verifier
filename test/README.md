# Test Layout

This directory is split by role:

- `unit/` - automated CLI tests and concurrency checks
- `example/` - small examples that authenticate and read linked secrets
- `scenario/` - end-to-end scenario scripts that rotate session passwords

Shared helpers live in:

- `runtime_utils.py`

Notes:

- program files are run by absolute or repo-relative path
- session key files are stored next to the program file
- the unit tests default to `test/unit/test_program.py`
- example and scenario scripts use the same `runtime_utils.py` helpers for path handling
