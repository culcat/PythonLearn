#!/usr/bin/env python3
"""Упражнение 05: Асинхронные паттерны: очереди, семафоры и contextvars.

Тема: AsyncRateLimiter на базе asyncio.Semaphore,
конвейер AsyncPipeline с очередью, backpressure и graceful shutdown через Sentinel,
управление контекстом запроса RequestContext на базе contextvars.ContextVar.

Запуск тестов:
    python3 exercises/03_internals_async/ex_05_async_patterns.py
    или из корня:
    python3 run_all_tests.py
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from typing import Any, Callable, Coroutine, Generic, List, Optional, TypeVar
import unittest

T = TypeVar("T")
R = TypeVar("R")


# =====================================================================
# ЗАДАНИЕ 1: Ограничитель параллелизма AsyncRateLimiter на Semaphore
# =====================================================================

class AsyncRateLimiter:
    """Асинхронный контекстный менеджер ограничения числа одновременных операций."""

    def __init__(self, max_concurrent: int) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent должен быть >= 1")
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_count: int = 0
        self._peak_count: int = 0
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self._semaphore.acquire()
        async with self._lock:
            self._active_count += 1
            if self._active_count > self._peak_count:
                self._peak_count = self._active_count
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        try:
            async with self._lock:
                self._active_count -= 1
        finally:
            self._semaphore.release()

    @property
    def peak_concurrency(self) -> int:
        return self._peak_count

    @property
    def active_count(self) -> int:
        return self._active_count


# =====================================================================
# ЗАДАНИЕ 2: Конвейер Producer-Consumer с очередью и Backpressure
# =====================================================================

_SENTINEL = object()


class AsyncPipeline(Generic[T, R]):
    """Асинхронный конвейер обработки данных на базе asyncio.Queue.

    - maxsize реализует противодавление (Backpressure).
    - Воркеры обрабатывают элементы и корректно останавливаются при получении Sentinel.
    """

    def __init__(self, maxsize: int = 5) -> None:
        self.maxsize = maxsize
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self._workers: List[asyncio.Task[None]] = []
        self._results: List[R] = []
        self._results_lock = asyncio.Lock()

    async def put(self, item: T) -> None:
        """Помещает элемент в конвейер. При заполнении буфера корутина засыпает."""
        await self._queue.put(item)

    async def _worker_loop(
        self, worker_func: Callable[[T], Coroutine[Any, Any, R]]
    ) -> None:
        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                self._queue.task_done()
                break

            try:
                res = await worker_func(item)
                async with self._results_lock:
                    self._results.append(res)
            finally:
                self._queue.task_done()

    def start_workers(
        self, num_workers: int, worker_func: Callable[[T], Coroutine[Any, Any, R]]
    ) -> None:
        """Запускает указанное количество фоновых задач-обработчиков."""
        for _ in range(num_workers):
            task = asyncio.create_task(self._worker_loop(worker_func))
            self._workers.append(task)

    async def join_and_stop(self) -> List[R]:
        """Ожидает обработки всех элементов в очереди и останавливает воркеров."""
        # 1. Дожидаемся обработки всех задач
        await self._queue.join()

        # 2. Отправляем Sentinel-значение каждому воркеру
        for _ in self._workers:
            await self._queue.put(_SENTINEL)

        # 3. Ожидаем завершения всех задач воркеров
        await asyncio.gather(*self._workers)

        return list(self._results)


# =====================================================================
# ЗАДАНИЕ 3: Изолированный контекст запроса с contextvars
# =====================================================================

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="anonymous")
_user_ctx: ContextVar[Optional[str]] = ContextVar("current_user", default=None)


def get_current_request_id() -> str:
    """Возвращает request_id для текущей корутины/контекста."""
    return _request_id_ctx.get()


def get_current_user() -> Optional[str]:
    """Возвращает текущего пользователя из контекста."""
    return _user_ctx.get()


class RequestScope:
    """Асинхронный контекстный менеджер для установки контекста запроса."""

    def __init__(self, request_id: str, user: Optional[str] = None) -> None:
        self.request_id = request_id
        self.user = user
        self._tokens: List[Token[Any]] = []

    async def __aenter__(self) -> "RequestScope":
        self._tokens.append(_request_id_ctx.set(self.request_id))
        self._tokens.append(_user_ctx.set(self.user))
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        # Восстанавливаем токен пользователя
        _user_ctx.reset(self._tokens.pop())
        # Восстанавливаем токен request_id
        _request_id_ctx.reset(self._tokens.pop())


# =====================================================================
# МОДУЛЬНЫЕ ТЕСТЫ (IsolatedAsyncioTestCase)
# =====================================================================

class TestAsyncPatterns(unittest.IsolatedAsyncioTestCase):
    async def test_async_rate_limiter_limit(self) -> None:
        """Семафор строго держит лимит одновременных задач."""
        max_allowed = 3
        limiter = AsyncRateLimiter(max_concurrent=max_allowed)
        total_tasks = 9

        async def worker() -> str:
            async with limiter:
                await asyncio.sleep(0.04)
                return "ok"

        results = await asyncio.gather(*(worker() for _ in range(total_tasks)))

        self.assertEqual(len(results), total_tasks)
        self.assertLessEqual(limiter.peak_concurrency, max_allowed)
        self.assertEqual(limiter.active_count, 0)

    async def test_async_pipeline_processing(self) -> None:
        """Конвейер передает данные через очередь и корректно завершает воркеров."""
        pipeline: AsyncPipeline[int, int] = AsyncPipeline(maxsize=3)

        async def double_worker(val: int) -> int:
            await asyncio.sleep(0.01)
            return val * 2

        pipeline.start_workers(num_workers=3, worker_func=double_worker)

        # Кладем элементы в конвейер
        for item in [1, 2, 3, 4, 5]:
            await pipeline.put(item)

        results = await pipeline.join_and_stop()

        self.assertEqual(sorted(results), [2, 4, 6, 8, 10])

    async def test_request_scope_isolation(self) -> None:
        """ContextVar изолирует данные между независимыми конкурентными корутинами."""
        # Значение по умолчанию
        self.assertEqual(get_current_request_id(), "anonymous")
        self.assertIsNone(get_current_user())

        async def request_handler(req_id: str, username: str) -> tuple[str, Optional[str]]:
            async with RequestScope(request_id=req_id, user=username):
                # Имитация работы
                await asyncio.sleep(0.02)
                # Проверяем, что контекст не затерт другим запросом!
                return (get_current_request_id(), get_current_user())

        res1, res2 = await asyncio.gather(
            request_handler("req-111", "Alice"),
            request_handler("req-222", "Bob"),
        )

        self.assertEqual(res1, ("req-111", "Alice"))
        self.assertEqual(res2, ("req-222", "Bob"))

        # После выхода из контекстов глобальное состояние восстановилось
        self.assertEqual(get_current_request_id(), "anonymous")
        self.assertIsNone(get_current_user())


if __name__ == "__main__":
    unittest.main(verbosity=2)
