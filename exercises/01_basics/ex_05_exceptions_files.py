#!/usr/bin/env python3
"""Практические задания к Главе 05: Исключения, файлы и контекстные менеджеры.

Запуск тестов:
    python3 exercises/01_basics/ex_05_exceptions_files.py

Задания:
1. Иерархия доменных исключений и цепочки ошибок (Exception Chaining):
   Классы AppBaseError, ValidationError, EntityNotFoundError.
   Функция parse_and_validate_user_age с явным пробросом `from err` и `from None`.
2. atomic_file_writer:
   Атомарная запись файла через pathlib.Path и замену во избежание повреждения данных при сбоях.
3. ManagedContextResource:
   Полнофункциональный класс контекстного менеджера (__enter__ / __exit__) с аудитом и избирательным подавлением исключений.
4. categorize_exception_group:
   Анализ и агрегация параллельных ошибок ExceptionGroup (Python 3.11+).
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
from types import TracebackType
from typing import Type
import unittest


# =====================================================================
# ЗАДАНИЕ 1: Иерархия исключений и цепочки (Chaining)
# =====================================================================
class AppBaseError(Exception):
    """Базовое исключение предметной области приложения."""
    def __init__(self, message: str, error_code: str = "APP_ERROR"):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class ValidationError(AppBaseError):
    """Ошибка валидации пользовательских данных."""
    def __init__(self, field: str, detail: str):
        super().__init__(f"Validation failed for field '{field}': {detail}", error_code="VALIDATION_ERROR")
        self.field = field
        self.detail = detail


class EntityNotFoundError(AppBaseError):
    """Сущность не найдена в системе."""
    def __init__(self, entity: str, entity_id: str | int):
        super().__init__(f"{entity} with id={entity_id} not found", error_code="ENTITY_NOT_FOUND")
        self.entity = entity
        self.entity_id = entity_id


def parse_and_validate_user_age(raw_age: str) -> int:
    """Парсит строковый возраст и проверяет диапазон [1, 150].

    Требования к обработке ошибок:
    - Если raw_age не преобразуется в int: выбрасывается ValidationError с цепочкой `from err`
      (сохраняется исходный ValueError в __cause__).
    - Если возраст < 1 или > 150: выбрасывается ValidationError с подавлением контекста `from None`
      (в __cause__ устанавливается None).
    """
    try:
        age = int(raw_age)
    except ValueError as err:
        raise ValidationError("age", "Must be a valid integer string") from err

    if age < 1 or age > 150:
        raise ValidationError("age", f"Age must be between 1 and 150, got {age}") from None

    return age


# =====================================================================
# ЗАДАНИЕ 2: Атомарная запись файла через Pathlib
# =====================================================================
def atomic_file_writer(filepath: Path, content: str) -> int:
    """Записывает контент в файл атомарно.

    Алгоритм:
    1. Создает родительские директории, если они отсутствуют.
    2. Записывает данные во временный файл-близнец ({filepath}.tmp).
    3. Атомарно заменяет целевой файл временным через os.replace().
    4. В блоке finally удаляет временный файл, если замена не состоялась.
    5. Возвращает количество записанных байт.

    Выбрасывает:
        ValueError: если filepath указывает на существующую директорию.
    """
    if filepath.is_dir():
        raise ValueError(f"Путь '{filepath}' является директорией, а не файлом.")

    filepath.parent.mkdir(parents=True, exist_ok=True)
    temp_file = filepath.with_name(f"{filepath.name}.tmp.{os.getpid()}")

    try:
        encoded_data = content.encode("utf-8")
        temp_file.write_bytes(encoded_data)
        temp_file.replace(filepath)
        return len(encoded_data)
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass


# =====================================================================
# ЗАДАНИЕ 3: Протокол контекстного менеджера (__enter__ / __exit__)
# =====================================================================
class ManagedContextResource:
    """Контекстный менеджер для управления ресурсом с аудитом и подавлением ошибок."""

    def __init__(
        self,
        name: str,
        suppress_types: tuple[Type[BaseException], ...] = (),
    ) -> None:
        self.name = name
        self.suppress_types = suppress_types
        self.is_active = False
        self.events: list[str] = []
        self.elapsed_seconds: float = 0.0
        self._start_time: float = 0.0

    def log(self, message: str) -> None:
        """Записывает событие во внутренний журнал ресурса."""
        self.events.append(f"[{self.name}] {message}")

    def __enter__(self) -> "ManagedContextResource":
        self.is_active = True
        self._start_time = time.perf_counter()
        self.log("ENTERED")
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        self.elapsed_seconds = time.perf_counter() - self._start_time
        self.is_active = False
        self.log(f"EXITED (elapsed={self.elapsed_seconds:.4f}s)")

        if exc_type is not None:
            self.log(f"ERROR: {exc_type.__name__}: {exc_val}")
            # Проверяем, входит ли тип возникшего исключения в список подавляемых
            if issubclass(exc_type, self.suppress_types):
                return True  # Подавляем исключение

        return False  # Пропускаем исключение дальше


# =====================================================================
# ЗАДАНИЕ 4: Анализ групп исключений (ExceptionGroup)
# =====================================================================
def categorize_exception_group(group: ExceptionGroup[Exception]) -> dict[str, int]:
    """Подсчитывает количество исключений по категориям внутри ExceptionGroup.

    Категории:
    - 'validation': количество исключений ValidationError
    - 'not_found': количество исключений EntityNotFoundError
    - 'other': количество любых других исключений
    """
    counts = {
        "validation": 0,
        "not_found": 0,
        "other": 0,
    }

    for exc in group.exceptions:
        if isinstance(exc, ValidationError):
            counts["validation"] += 1
        elif isinstance(exc, EntityNotFoundError):
            counts["not_found"] += 1
        else:
            counts["other"] += 1

    return counts


# =====================================================================
# МОДУЛЬНЫЕ ТЕСТЫ (UNIT TESTS)
# =====================================================================
class TestExceptionsFilesContext(unittest.TestCase):
    def test_parse_age_valid(self) -> None:
        self.assertEqual(parse_and_validate_user_age("25"), 25)
        self.assertEqual(parse_and_validate_user_age("1"), 1)
        self.assertEqual(parse_and_validate_user_age("150"), 150)

    def test_parse_age_chaining_cause_retained(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            parse_and_validate_user_age("not_a_number")
        self.assertIsInstance(ctx.exception.__cause__, ValueError)
        self.assertEqual(ctx.exception.field, "age")

    def test_parse_age_out_of_bounds_cause_suppressed(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            parse_and_validate_user_age("200")
        self.assertIsNone(ctx.exception.__cause__)
        self.assertIn("between 1 and 150", ctx.exception.detail)

    def test_atomic_file_writer_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "nested" / "sub" / "output.txt"
            written_bytes = atomic_file_writer(target, "Hello, CPython!")
            self.assertEqual(written_bytes, len("Hello, CPython!".encode("utf-8")))
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "Hello, CPython!")

    def test_atomic_file_writer_directory_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dir_path = Path(tmpdir)
            with self.assertRaises(ValueError):
                atomic_file_writer(dir_path, "fail")

    def test_context_manager_normal_execution(self) -> None:
        with ManagedContextResource("db_session") as res:
            self.assertTrue(res.is_active)
            res.log("Running query")
        self.assertFalse(res.is_active)
        self.assertEqual(len(res.events), 3)  # ENTERED, Running query, EXITED

    def test_context_manager_suppress_specified_exception(self) -> None:
        # Подавляем ValueError
        with ManagedContextResource("api_client", suppress_types=(ValueError,)) as res:
            res.log("Attempting call")
            raise ValueError("Controlled error")
        # Исключение подавлено, выполнение продолжается
        self.assertFalse(res.is_active)
        self.assertTrue(any("Controlled error" in ev for ev in res.events))

    def test_context_manager_propagates_unsuppressed_exception(self) -> None:
        # Не подавляем KeyError
        with self.assertRaises(KeyError):
            with ManagedContextResource("api_client", suppress_types=(ValueError,)):
                raise KeyError("Unsuppressed key error")

    def test_categorize_exception_group(self) -> None:
        errors: list[Exception] = [
            ValidationError("email", "Bad format"),
            ValidationError("name", "Too short"),
            EntityNotFoundError("User", 42),
            RuntimeError("Unexpected DB disconnect"),
        ]
        group = ExceptionGroup("Batch tasks failed", errors)
        res = categorize_exception_group(group)
        self.assertEqual(res["validation"], 2)
        self.assertEqual(res["not_found"], 1)
        self.assertEqual(res["other"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
