#!/usr/bin/env python3
"""Практическое задание 03: Декораторы с параметрами, итераторы, генераторы и itertools.

Инструкция по запуску:
    python3 exercises/02_oop_typing/ex_03_decorators_generators.py

Цели задания:
    1. Создать параметризованный декоратор @retry с сохранением метаданных через functools.wraps.
    2. Реализовать декоратор кэширования результатов функций с временем жизни (@memoize_with_ttl).
    3. Разработать ленивый генератор пакетов данных chunked на базе itertools.islice.
    4. Создать генераторную корутину moving_average с двусторонней передачей через .send().
    5. Реализовать рекурсивный генератор flatten_nested с конструкцией yield from.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable
import functools
import itertools
import time
from typing import Any, TypeVar

T = TypeVar("T")
R = TypeVar("R")


# ============================================================================
# ЗАДАНИЕ 1: Параметризованный декоратор @retry
# ============================================================================

def retry(
    max_retries: int = 3,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    delay: float = 0.0,
) -> Callable[[Callable[..., R]], Callable[..., R]]:
    """Фабрика декоратора для повторного выполнения функции при возникновении ошибок.

    Аргументы:
        max_retries: максимальное количество попыток (>= 1).
        exceptions: кортеж перехватываемых типов исключений.
        delay: задержка в секундах между попытками.
    """
    if max_retries < 1:
        raise ValueError("max_retries должен быть >= 1")

    def decorator(func: Callable[..., R]) -> Callable[..., R]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> R:
            attempts = 0
            while True:
                try:
                    attempts += 1
                    return func(*args, **kwargs)
                except exceptions as err:
                    if attempts >= max_retries:
                        raise RuntimeError(
                            f"Функция {func.__name__} завершилась ошибкой после {attempts} попыток"
                        ) from err
                    if delay > 0:
                        time.sleep(delay)

        return wrapper

    return decorator


# ============================================================================
# ЗАДАНИЕ 2: Декоратор кэширования с TTL (@memoize_with_ttl)
# ============================================================================

def memoize_with_ttl(
    ttl_seconds: float = 1.0,
) -> Callable[[Callable[..., R]], Callable[..., R]]:
    """Декоратор кэширования результатов вызова функции по аргументам с TTL."""

    def decorator(func: Callable[..., R]) -> Callable[..., R]:
        cache: dict[tuple[Any, ...], tuple[R, float]] = {}

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> R:
            # Преобразуем kwargs в отсортированный кортеж для хешируемости ключа кэша
            cache_key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()

            if cache_key in cache:
                val, expires_at = cache[cache_key]
                if now < expires_at:
                    return val

            result = func(*args, **kwargs)
            cache[cache_key] = (result, now + ttl_seconds)
            return result

        def clear_cache() -> None:
            """Сброс кэша декоратора."""
            cache.clear()

        # Прикрепляем функцию очистки к обертке
        setattr(wrapper, "clear_cache", clear_cache)
        return wrapper

    return decorator


# ============================================================================
# ЗАДАНИЕ 3: Ленивый генератор пакетов chunked
# ============================================================================

def chunked(iterable: Iterable[T], chunk_size: int) -> Generator[list[T], None, None]:
    """Разбивает любой итерируемый объект на пачки размером chunk_size.

    Не загружает всю коллекцию в память, а итерируется лениво через itertools.islice.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size должен быть >= 1")

    iterator = iter(iterable)
    while True:
        chunk = list(itertools.islice(iterator, chunk_size))
        if not chunk:
            break
        yield chunk


# ============================================================================
# ЗАДАНИЕ 4: Корутина скользящего среднего на базе .send()
# ============================================================================

def moving_average() -> Generator[float, float, None]:
    """Генераторная корутина: вычисляет накопительное скользящее среднее.

    Использование:
        coro = moving_average()
        next(coro)             # Инициализация до первого yield
        avg = coro.send(10.0)  # 10.0
        avg = coro.send(20.0)  # 15.0
        coro.close()
    """
    total = 0.0
    count = 0
    current_avg = 0.0

    while True:
        value = yield current_avg
        total += value
        count += 1
        current_avg = total / count


# ============================================================================
# ЗАДАНИЕ 5: Рекурсивный генератор flatten_nested с yield from
# ============================================================================

def flatten_nested(nested: Iterable[Any]) -> Generator[Any, None, None]:
    """Рекурсивно разворачивает глубоко вложенные списки и кортежи."""
    for item in nested:
        if isinstance(item, (list, tuple)):
            yield from flatten_nested(item)
        else:
            yield item


# ============================================================================
# МОДУЛЬНЫЕ ТЕСТЫ (unittest)
# ============================================================================

import unittest


class TestDecoratorsAndGenerators(unittest.TestCase):
    """Набор тестов для проверки декораторов, итераторов и генераторов."""

    def test_retry_decorator_success_after_retries(self) -> None:
        """Проверяем, что @retry успешно завершается, если ошибка исчезает до исчерпания попыток."""
        call_counter = 0

        @retry(max_retries=3, exceptions=(ValueError,))
        def flaky_service() -> str:
            nonlocal call_counter
            call_counter += 1
            if call_counter < 3:
                raise ValueError("Временный сбой")
            return "OK"

        result = flaky_service()
        self.assertEqual(result, "OK")
        self.assertEqual(call_counter, 3)

    def test_retry_decorator_exhausted(self) -> None:
        """Проверяем, что @retry выбрасывает RuntimeError при превышении лимита попыток."""
        @retry(max_retries=2, exceptions=(KeyError,))
        def always_failing() -> None:
            raise KeyError("Ключ не найден")

        with self.assertRaises(RuntimeError) as ctx:
            always_failing()
        self.assertIn("завершилась ошибкой после 2 попыток", str(ctx.exception))

    def test_decorator_metadata_preservation(self) -> None:
        """Проверяем, что functools.wraps сохраняет имя и документацию функции."""
        @retry(max_retries=1)
        def documented_function(x: int) -> int:
            """Важная документация функции."""
            return x * 2

        self.assertEqual(documented_function.__name__, "documented_function")
        self.assertEqual(documented_function.__doc__, "Важная документация функции.")

    def test_memoize_with_ttl(self) -> None:
        """Проверяем работу кэша, сброс кэша и истечение TTL."""
        calc_count = 0

        @memoize_with_ttl(ttl_seconds=0.1)
        def expensive_calc(a: int, b: int) -> int:
            nonlocal calc_count
            calc_count += 1
            return a + b

        # 1. Первый вызов вычисляет
        self.assertEqual(expensive_calc(2, 3), 5)
        self.assertEqual(calc_count, 1)

        # 2. Повторный вызов берет из кэша
        self.assertEqual(expensive_calc(2, 3), 5)
        self.assertEqual(calc_count, 1)

        # 3. Ручной сброс кэша
        expensive_calc.clear_cache()  # type: ignore[attr-defined]
        self.assertEqual(expensive_calc(2, 3), 5)
        self.assertEqual(calc_count, 2)

        # 4. Истечение TTL
        time.sleep(0.12)
        self.assertEqual(expensive_calc(2, 3), 5)
        self.assertEqual(calc_count, 3)

    def test_chunked_generator(self) -> None:
        """Проверяем ленивую разбивку на пакеты."""
        data = list(range(10))
        chunks = list(chunked(data, 3))
        expected = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]]
        self.assertEqual(chunks, expected)

        # Пустой список
        self.assertEqual(list(chunked([], 5)), [])

    def test_moving_average_coroutine(self) -> None:
        """Проверяем работу корутины .send() для вычисления среднего значения."""
        coro = moving_average()
        initial = next(coro)
        self.assertEqual(initial, 0.0)

        self.assertAlmostEqual(coro.send(10.0), 10.0)
        self.assertAlmostEqual(coro.send(20.0), 15.0)
        self.assertAlmostEqual(coro.send(30.0), 20.0)
        coro.close()

    def test_flatten_nested_yield_from(self) -> None:
        """Проверяем рекурсивное разворачивание yield from на сложной иерархии."""
        tree = [1, [2, 3], [[4, [5, 6]], 7], (8, 9)]
        flat = list(flatten_nested(tree))
        self.assertEqual(flat, [1, 2, 3, 4, 5, 6, 7, 8, 9])


if __name__ == "__main__":
    unittest.main(verbosity=2)
