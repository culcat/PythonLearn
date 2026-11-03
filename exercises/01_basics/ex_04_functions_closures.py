#!/usr/bin/env python3
"""Практические задания к Главе 04: Функции, области видимости (LEGB) и замыкания.

Запуск тестов:
    python3 exercises/01_basics/ex_04_functions_closures.py

Задания:
1. build_query_endpoint:
   Конструирование эндпоинта с разделителями позиционных (/) и именованных (*) аргументов,
   безопасным значением mutable-аргумента по умолчанию и валидацией.
2. make_token_bucket_limiter:
   Реализация алгоритма Token Bucket Rate Limiter на базе замыканий и ключевого слова `nonlocal`.
3. compose_pipeline:
   Композиция функций высшего порядка: объединение N функций f1, f2, ..., fn в единый пайплайн.
4. make_safe_accumulator:
   Инкапсуляция накапливаемого состояния в объекте ячейки замыкания (__closure__).
"""

from __future__ import annotations

import time
from typing import Callable
import unittest


# =====================================================================
# ЗАДАНИЕ 1: Сигнатуры функций (/, *), immutable defaults и **kwargs
# =====================================================================
def build_query_endpoint(
    path: str,
    /,
    method: str = "GET",
    *,
    timeout: int = 30,
    tags: list[str] | None = None,
    **extra_params: str,
) -> dict[str, object]:
    """Формирует конфигурацию HTTP-эндпоинта.

    Параметры:
    - path: строго позиционный (до /)
    - method: стандартный (позиционный или именованный), по умолчанию 'GET'
    - timeout: строго именованный (после *), целое число > 0, по умолчанию 30
    - tags: список тегов. Значение по умолчанию — None (не изменяемый список!).
      Если None, внутри создается новый пустой список.
    - extra_params: произвольные строковые параметры запроса.

    Выбрасывает:
        ValueError: если path не начинается со слэша '/' или timeout <= 0.
    """
    if not path or not path.startswith("/"):
        raise ValueError(f"Path должен начинаться со слэша '/', получено: '{path}'")

    if timeout <= 0:
        raise ValueError(f"Timeout должен быть положительным числом, получено: {timeout}")

    actual_tags = list(tags) if tags is not None else []

    return {
        "path": path,
        "method": method.upper(),
        "timeout": timeout,
        "tags": actual_tags,
        "params": extra_params,
    }


# =====================================================================
# ЗАДАНИЕ 2: Token Bucket Rate Limiter на замыкании и nonlocal
# =====================================================================
def make_token_bucket_limiter(
    capacity: int,
    refill_rate_per_sec: float,
) -> tuple[Callable[[], bool], Callable[[], None], Callable[[], float]]:
    """Создает алгоритм ограничения частоты запросов Token Bucket на базе замыкания.

    Параметры:
    - capacity: максимальное количество токенов в корзине (burst capacity)
    - refill_rate_per_sec: скорость пополнения корзины (токенов в секунду)

    Возвращает кортеж из 3 функций:
    1. acquire() -> bool:
       Пополняет корзину на основе прошедшего времени time.monotonic(),
       но не более capacity. Если доступен хотя бы 1 токен, списывает 1 токен
       и возвращает True. Иначе возвращает False.
    2. reset() -> None:
       Сбрасывает токены к полному capacity и обновляет время.
    3. get_tokens() -> float:
       Возвращает текущее количество токенов с учетом пополнения за прошедшее время.

    Выбрасывает:
        ValueError: если capacity <= 0 или refill_rate_per_sec <= 0.
    """
    if capacity <= 0:
        raise ValueError("Capacity должно быть положительным числом.")
    if refill_rate_per_sec <= 0.0:
        raise ValueError("Скорость refill_rate_per_sec должна быть > 0.")

    tokens = float(capacity)
    last_check = time.monotonic()

    def _refill() -> None:
        nonlocal tokens, last_check
        now = time.monotonic()
        elapsed = now - last_check
        last_check = now
        tokens = min(float(capacity), tokens + elapsed * refill_rate_per_sec)

    def acquire() -> bool:
        nonlocal tokens
        _refill()
        if tokens >= 1.0:
            tokens -= 1.0
            return True
        return False

    def reset() -> None:
        nonlocal tokens, last_check
        tokens = float(capacity)
        last_check = time.monotonic()

    def get_tokens() -> float:
        _refill()
        return tokens

    return acquire, reset, get_tokens


# =====================================================================
# ЗАДАНИЕ 3: Композиция функций высшего порядка
# =====================================================================
def compose_pipeline(*functions: Callable[[int], int]) -> Callable[[int], int]:
    """Создает пайплайн обработки, выполняя переданные функции слева направо.

    compose_pipeline(f1, f2, f3)(x) == f3(f2(f1(x)))
    Если функции не переданы, возвращает функцию identity (lambda x: x).
    """
    funcs = list(functions)

    def pipeline(initial: int) -> int:
        acc = initial
        for fn in funcs:
            acc = fn(acc)
        return acc

    return pipeline


# =====================================================================
# ЗАДАНИЕ 4: Безопасный аккумулятор состояния (Cell Objects)
# =====================================================================
def make_safe_accumulator(
    initial_value: int = 0,
) -> tuple[Callable[[int], int], Callable[[], int]]:
    """Создает пару функций для закрытого накопления суммы без использования глобальных переменных.

    Возвращает:
    1. add(delta: int) -> int: прибавляет delta к сумме и возвращает новое значение.
    2. get_total() -> int: возвращает текущую сумму.
    """
    current_sum = initial_value

    def add(delta: int) -> int:
        nonlocal current_sum
        current_sum += delta
        return current_sum

    def get_total() -> int:
        return current_sum

    return add, get_total


# =====================================================================
# МОДУЛЬНЫЕ ТЕСТЫ (UNIT TESTS)
# =====================================================================
class TestFunctionsClosures(unittest.TestCase):
    def test_build_query_endpoint_valid(self) -> None:
        endpoint = build_query_endpoint(
            "/api/v1/users",
            "post",
            timeout=15,
            tags=["users", "auth"],
            filter="active",
        )
        self.assertEqual(endpoint["path"], "/api/v1/users")
        self.assertEqual(endpoint["method"], "POST")
        self.assertEqual(endpoint["timeout"], 15)
        self.assertEqual(endpoint["tags"], ["users", "auth"])
        self.assertEqual(endpoint["params"], {"filter": "active"})

    def test_build_query_endpoint_mutable_defaults_do_not_leak(self) -> None:
        ep1 = build_query_endpoint("/first")
        ep1_tags = ep1["tags"]
        self.assertIsInstance(ep1_tags, list)
        if isinstance(ep1_tags, list):
            ep1_tags.append("mutated")

        ep2 = build_query_endpoint("/second")
        # Второе создание не должно содержать 'mutated'!
        self.assertEqual(ep2["tags"], [])

    def test_build_query_endpoint_invalid_params(self) -> None:
        with self.assertRaises(ValueError):
            build_query_endpoint("invalid_path_no_slash")

        with self.assertRaises(ValueError):
            build_query_endpoint("/valid", timeout=0)

    def test_token_bucket_limiter_burst_and_exhaustion(self) -> None:
        acquire, reset, get_tokens = make_token_bucket_limiter(capacity=2, refill_rate_per_sec=100.0)
        self.assertTrue(acquire())  # 2 -> 1
        self.assertTrue(acquire())  # 1 -> 0
        self.assertFalse(acquire())  # исчерпано

        reset()
        self.assertTrue(acquire())

    def test_token_bucket_limiter_validation(self) -> None:
        with self.assertRaises(ValueError):
            make_token_bucket_limiter(capacity=0, refill_rate_per_sec=1.0)
        with self.assertRaises(ValueError):
            make_token_bucket_limiter(capacity=10, refill_rate_per_sec=-0.5)

    def test_compose_pipeline_execution(self) -> None:
        add_two = lambda x: x + 2
        square = lambda x: x * x
        double = lambda x: x * 2

        # (5 + 2) = 7 -> 7 * 7 = 49 -> 49 * 2 = 98
        pipe = compose_pipeline(add_two, square, double)
        self.assertEqual(pipe(5), 98)

    def test_compose_pipeline_empty(self) -> None:
        identity = compose_pipeline()
        self.assertEqual(identity(42), 42)

    def test_safe_accumulator_state_isolation(self) -> None:
        add1, get1 = make_safe_accumulator(10)
        add2, get2 = make_safe_accumulator(100)

        self.assertEqual(add1(5), 15)
        self.assertEqual(add1(3), 18)
        self.assertEqual(get1(), 18)

        # Проверяем, что второй аккумулятор полностью изолирован
        self.assertEqual(get2(), 100)
        self.assertEqual(add2(50), 150)
        self.assertEqual(get1(), 18)


if __name__ == "__main__":
    unittest.main(verbosity=2)
