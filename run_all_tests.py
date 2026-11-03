#!/usr/bin/env python3
"""Единый раннер для проверки всех практических заданий учебника Python & FastAPI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    exercises_dir = root / "exercises"
    if not exercises_dir.exists():
        print("Папка exercises/ не найдена.")
        return 1

    py_files = sorted(exercises_dir.rglob("ex_*.py"))
    if not py_files:
        print("Файлы упражнений ex_*.py не найдены.")
        return 1

    print(f"Найдено файлов с практическими заданиями и тестами: {len(py_files)}\n")
    failed: list[Path] = []

    for py_file in py_files:
        rel_path = py_file.relative_to(root)
        result = subprocess.run(
            [sys.executable, str(py_file)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            print(f"[PASS] {rel_path}")
        else:
            print(f"[FAIL] {rel_path}")
            print(result.stdout)
            print(result.stderr)
            failed.append(rel_path)

    print("-" * 60)
    if failed:
        print(f"Ошибки в {len(failed)} из {len(py_files)} файлов.")
        return 1

    print(f"Успешно пройдены все {len(py_files)} наборов тестов!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
