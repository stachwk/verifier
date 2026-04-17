#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-

import os
import sys


def add_repo_paths(file_path: str) -> tuple[str, str]:
    script_dir = os.path.dirname(os.path.abspath(file_path))
    test_dir = os.path.dirname(script_dir)
    repo_root = os.path.dirname(test_dir)

    for path in (repo_root, test_dir):
        if path not in sys.path:
            sys.path.insert(0, path)

    return repo_root, test_dir


def program_path_from_file(file_path: str) -> str:
    return os.path.abspath(file_path)


def key_path_for(program_path: str, program_name: str, instance_key: str) -> str:
    program_dir = os.path.dirname(os.path.abspath(program_path))
    return os.path.join(program_dir, f"{program_name}_{instance_key}.key")


def read_key_file(key_path: str) -> str:
    with open(key_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def write_key_file_atomic(key_path: str, content: str) -> None:
    tmp_path = f"{key_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content + "\n")
    os.replace(tmp_path, key_path)
