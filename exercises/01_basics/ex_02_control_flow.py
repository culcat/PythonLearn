#!/usr/bin/env python3
"""Практические задания к Главе 02: Управляющие конструкции, Pattern Matching и циклы.

Запуск тестов:
    python3 exercises/01_basics/ex_02_control_flow.py

Задания:
1. evaluate_access_permission:
   Проверка прав доступа с использованием short-circuit evaluation и truthy/falsy проверок.
2. process_telemetry_event:
   Обработка полиморфных событий телеметрии через Structural Pattern Matching (match/case)
   с сопоставлением классов (dataclass), словарей, последовательностей и guards.
3. safe_paired_batch:
   Безопасное параллельное объединение коллекций с `zip(strict=True)` и нумерацией `enumerate`.
4. find_first_prime_with_else:
   Поиск первого простого числа с идиоматичным использованием конструкции `for ... else`.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import unittest


@dataclass
class TelemetryPoint:
    sensor_id: str
    value: float


# =====================================================================
# ЗАДАНИЕ 1: Short-Circuit проверка прав доступа
# =====================================================================
def evaluate_access_permission(
    role: str | None,
    is_active: bool,
    is_superuser: bool = False,
) -> tuple[bool, str]:
    """Оценивает доступ пользователя на основе активности, роли и флага суперпользователя.

    Правила:
    1. Неактивный пользователь (not is_active) ВСЕГДА блокируется: (False, "User account is inactive").
    2. Суперпользователь (is_superuser is True) ВСЕГДА получает доступ: (True, "Superuser access granted").
    3. При пустой роли (None или пустая строка) доступ отклоняется: (False, "Access denied: missing role").
    4. Роли 'admin' -> (True, "Admin access granted").
       Роли 'moderator' -> (True, "Moderator access granted").
       Роли 'user' -> (True, "Standard access granted").
    5. Любая иная неизвестная роль -> (False, f"Access denied: unknown role '{role}'").
    """
    if not is_active:
        return False, "User account is inactive"

    if is_superuser:
        return True, "Superuser access granted"

    clean_role = (role or "").strip().lower()
    if not clean_role:
        return False, "Access denied: missing role"

    match clean_role:
        case "admin":
            return True, "Admin access granted"
        case "moderator":
            return True, "Moderator access granted"
        case "user":
            return True, "Standard access granted"
        case _:
            return False, f"Access denied: unknown role '{role}'"


# =====================================================================
# ЗАДАНИЕ 2: Structural Pattern Matching (match/case)
# =====================================================================
def process_telemetry_event(event: object) -> str:
    """Маршрутизирует и форматирует события телеметрии с помощью match/case.

    Поддерживаемые паттерны:
    - TelemetryPoint с value > 100.0:
        "CRITICAL_ALARM: Sensor {sensor_id} exceeded threshold ({value:.1f})"
    - TelemetryPoint с обычным value:
        "NORMAL: Sensor {sensor_id} value {value:.1f}"
    - Словарь {"type": "status", "code": 200}:
        "STATUS_OK"
    - Словарь {"type": "status", "code": (404 | 500) as c}:
        "STATUS_ERROR_{c}"
    - Список/кортеж ["ping", str(host), int(port)]:
        "PING: {host}:{port}"
    - Все остальное (wildcard _):
        "UNKNOWN_EVENT"
    """
    match event:
        case TelemetryPoint(sensor_id=s, value=v) if v > 100.0:
            return f"CRITICAL_ALARM: Sensor {s} exceeded threshold ({v:.1f})"
        case TelemetryPoint(sensor_id=s, value=v):
            return f"NORMAL: Sensor {s} value {v:.1f}"
        case {"type": "status", "code": 200}:
            return "STATUS_OK"
        case {"type": "status", "code": (404 | 500) as c}:
            return f"STATUS_ERROR_{c}"
        case ["ping", str(host), int(port)]:
            return f"PING: {host}:{port}"
        case _:
            return "UNKNOWN_EVENT"


# =====================================================================
# ЗАДАНИЕ 3: Безопасное объединение с zip(strict=True) и enumerate
# =====================================================================
def safe_paired_batch(
    names: list[str],
    scores: list[int],
    max_items: int = 100,
) -> list[tuple[int, str, int]]:
    """Объединяет имена и баллы в ранжированный список кортежей (ранг, имя, балл).

    Ранг начинается с 1 (через enumerate(..., start=1)).
    Использует zip(..., strict=True) для гарантированного совпадения длин коллекций.
    Ограничивает результирующий список до max_items.

    Выбрасывает:
        ValueError: если длины списков names и scores не совпадают.
    """
    if max_items < 0:
        raise ValueError("max_items не может быть отрицательным.")

    try:
        pairs = list(zip(names, scores, strict=True))
    except ValueError as err:
        raise ValueError("Mismatched data lengths for batch processing") from err

    result: list[tuple[int, str, int]] = []
    for rank, (name, score) in enumerate(pairs[:max_items], start=1):
        result.append((rank, name, score))

    return result


# =====================================================================
# ЗАДАНИЕ 4: Поиск первого простого числа с for ... else
# =====================================================================
def find_first_prime_with_else(numbers: list[int]) -> int | None:
    """Находит первое простое число в списке целых чисел, используя конструкцию `for ... else`.

    Если простое число не найдено, возвращает None.
    Число считается простым, если оно >= 2 и не имеет делителей кроме 1 и себя.
    """
    for n in numbers:
        if n < 2:
            continue
        # Проверяем делители до sqrt(n)
        for d in range(2, math.isqrt(n) + 1):
            if n % d == 0:
                break
        else:
            # Срабатывает, если внутренний цикл завершился БЕЗ break
            return n

    return None


# =====================================================================
# МОДУЛЬНЫЕ ТЕСТЫ (UNIT TESTS)
# =====================================================================
class TestControlFlowLoops(unittest.TestCase):
    def test_permission_inactive_user(self) -> None:
        allowed, msg = evaluate_access_permission("admin", is_active=False)
        self.assertFalse(allowed)
        self.assertEqual(msg, "User account is inactive")

    def test_permission_superuser(self) -> None:
        allowed, msg = evaluate_access_permission(None, is_active=True, is_superuser=True)
        self.assertTrue(allowed)
        self.assertEqual(msg, "Superuser access granted")

    def test_permission_roles(self) -> None:
        self.assertTrue(evaluate_access_permission("admin", is_active=True)[0])
        self.assertTrue(evaluate_access_permission("moderator", is_active=True)[0])
        self.assertTrue(evaluate_access_permission("user", is_active=True)[0])
        self.assertFalse(evaluate_access_permission("hacker", is_active=True)[0])
        self.assertFalse(evaluate_access_permission(None, is_active=True)[0])

    def test_pattern_matching_telemetry_point(self) -> None:
        normal = TelemetryPoint("sensor_alpha", 42.5)
        self.assertEqual(
            process_telemetry_event(normal),
            "NORMAL: Sensor sensor_alpha value 42.5",
        )

        critical = TelemetryPoint("sensor_beta", 105.78)
        self.assertEqual(
            process_telemetry_event(critical),
            "CRITICAL_ALARM: Sensor sensor_beta exceeded threshold (105.8)",
        )

    def test_pattern_matching_mappings_and_sequences(self) -> None:
        self.assertEqual(process_telemetry_event({"type": "status", "code": 200}), "STATUS_OK")
        self.assertEqual(process_telemetry_event({"type": "status", "code": 404}), "STATUS_ERROR_404")
        self.assertEqual(process_telemetry_event({"type": "status", "code": 500}), "STATUS_ERROR_500")
        self.assertEqual(process_telemetry_event(["ping", "127.0.0.1", 8080]), "PING: 127.0.0.1:8080")
        self.assertEqual(process_telemetry_event(12345), "UNKNOWN_EVENT")

    def test_safe_paired_batch_success(self) -> None:
        names = ["Alice", "Bob", "Charlie"]
        scores = [100, 95, 80]
        res = safe_paired_batch(names, scores, max_items=2)
        expected = [(1, "Alice", 100), (2, "Bob", 95)]
        self.assertEqual(res, expected)

    def test_safe_paired_batch_mismatch_raises(self) -> None:
        names = ["Alice", "Bob"]
        scores = [100]
        with self.assertRaises(ValueError) as ctx:
            safe_paired_batch(names, scores)
        self.assertIn("Mismatched data lengths", str(ctx.exception))

    def test_find_first_prime_found(self) -> None:
        nums = [0, 1, 4, 6, 8, 9, 11, 15]
        self.assertEqual(find_first_prime_with_else(nums), 11)

    def test_find_first_prime_none_found(self) -> None:
        nums = [-5, 0, 1, 4, 6, 8, 9, 10]
        self.assertIsNone(find_first_prime_with_else(nums))


if __name__ == "__main__":
    unittest.main(verbosity=2)
