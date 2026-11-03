#!/usr/bin/env python3
"""Упражнение 04: Асинхронный Event Loop, корутины, задачи и TaskGroup.

Тема: Безопасный таймаут fetch_with_timeout через asyncio.timeout,
пакетный обработчик ConcurrentBatchProcessor на базе TaskGroup,
кастомный объект CustomDelayAwaitable, реализующий протокол __await__.

Запуск тестов:
    python3 exercises/03_internals_async/ex_04_asyncio_coroutines.py
    или из корня:
    python3 run_all_tests.py
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Coroutine, Generator, Generic, List, TypeVar
import unittest

T = TypeVar("T")
R = TypeVar("R")


# =====================================================================
# ЗАДАНИЕ 1: Асинхронный таймаут через asyncio.timeout
# =====================================================================

async def fetch_with_timeout(coro: Awaitable[T], timeout_seconds: float) -> T:
    """Ожидает выполнение awaitable-объекта с жестким ограничением времени.

    - Использует контекстный менеджер asyncio.timeout (Python 3.11+).
    - При превышении лимита времени выбрасывает TimeoutError.
    - Корректно обрабатывает и повторно пробрасывает asyncio.CancelledError.
    """
    try:
        async with asyncio.timeout(timeout_seconds):
            return await coro
    except TimeoutError:
        raise
    except asyncio.CancelledError:
        # Критическое правило asyncio: никогда не подавлять CancelledError
        raise


# =====================================================================
# ЗАДАНИЕ 2: Пакетный обработчик на базе TaskGroup (Структурная конкурентность)
# =====================================================================

class BatchResult(Generic[R]):
    """Результат выполнения пакета задач."""

    def __init__(self, successes: List[R], errors: List[Exception]) -> None:
        self.successes: List[R] = successes
        self.errors: List[Exception] = errors

    @property
    def total_count(self) -> int:
        return len(self.successes) + len(self.errors)


class ConcurrentBatchProcessor(Generic[T, R]):
    """Процессор пакетной обработки задач с использованием asyncio.TaskGroup.

    - Запускает обработку каждого элемента в отдельной задаче TaskGroup.
    - Изолирует ошибки отдельных элементов, чтобы одна неудача не прерывала остальные.
    - Разделяет результаты на успешные и ошибочные.
    """

    def __init__(self, worker_func: Callable[[T], Coroutine[Any, Any, R]]) -> None:
        self.worker_func = worker_func

    async def _safe_execute(
        self, item: T, successes: List[R], errors: List[Exception]
    ) -> None:
        try:
            res = await self.worker_func(item)
            successes.append(res)
        except Exception as exc:
            errors.append(exc)

    async def process_batch(self, items: List[T]) -> BatchResult[R]:
        """Обрабатывает список элементов параллельно через TaskGroup."""
        successes: List[R] = []
        errors: List[Exception] = []

        async with asyncio.TaskGroup() as tg:
            for item in items:
                tg.create_task(self._safe_execute(item, successes, errors))

        return BatchResult(successes=successes, errors=errors)


# =====================================================================
# ЗАДАНИЕ 3: Кастомный Awaitable-объект
# =====================================================================

class CustomDelayAwaitable(Generic[T]):
    """Объект, реализующий протокол Awaitable (__await__).

    Позволяет писать:
        val = await CustomDelayAwaitable("result_data", delay=0.05)
    """

    def __init__(self, value: T, delay: float = 0.01) -> None:
        self.value: T = value
        self.delay: float = delay

    def __await__(self) -> Generator[Any, None, T]:
        # Делегируем шаг ожидания асинхронному sleep, возвращая итоговое значение
        yield from asyncio.sleep(self.delay).__await__()
        return self.value


# =====================================================================
# МОДУЛЬНЫЕ ТЕСТЫ (IsolatedAsyncioTestCase)
# =====================================================================

class TestAsyncioCoroutines(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_with_timeout_success(self) -> None:
        """Успешное выполнение до истечения таймаута."""
        async def fast_task() -> str:
            await asyncio.sleep(0.02)
            return "ready"

        result = await fetch_with_timeout(fast_task(), timeout_seconds=0.2)
        self.assertEqual(result, "ready")

    async def test_fetch_with_timeout_exceeded(self) -> None:
        """Превышение лимита времени выбрасывает TimeoutError."""
        async def slow_task() -> str:
            await asyncio.sleep(0.3)
            return "late"

        with self.assertRaises(TimeoutError):
            await fetch_with_timeout(slow_task(), timeout_seconds=0.05)

    async def test_fetch_with_timeout_cancellation(self) -> None:
        """Внешняя отмена задачи вызывает CancelledError."""
        async def eternal_task() -> None:
            await asyncio.sleep(10.0)

        task = asyncio.create_task(fetch_with_timeout(eternal_task(), timeout_seconds=5.0))
        # Даем задаче запуститься
        await asyncio.sleep(0.01)
        # Отменяем
        task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_batch_processor_mixed_results(self) -> None:
        """TaskGroup обрабатывает все элементы, изолируя сбои."""
        async def worker(num: int) -> int:
            await asyncio.sleep(0.01)
            if num < 0:
                raise ValueError(f"Отрицательное число: {num}")
            return num * 10

        processor = ConcurrentBatchProcessor(worker)
        inputs = [1, -5, 2, -10, 3]

        batch_res = await processor.process_batch(inputs)

        self.assertEqual(batch_res.total_count, 5)
        self.assertEqual(sorted(batch_res.successes), [10, 20, 30])
        self.assertEqual(len(batch_res.errors), 2)
        for err in batch_res.errors:
            self.assertIsInstance(err, ValueError)

    async def test_custom_delay_awaitable(self) -> None:
        """Проверка работы протокола __await__ в CustomDelayAwaitable."""
        awaitable_obj = CustomDelayAwaitable("payload_data", delay=0.02)

        # Проверяем синтаксис await
        result = await awaitable_obj
        self.assertEqual(result, "payload_data")


if __name__ == "__main__":
    unittest.main(verbosity=2)
