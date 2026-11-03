#!/usr/bin/env python3
"""Практическое задание к Главе 04: Кэширование, Идемпотентность и Rate Limiting.

Данный модуль содержит эталонную реализацию архитектурных компонентов:
1. AsyncCacheStore: In-memory кэш с TTL и сериализацией.
2. CacheStampedeLock: Распределенная блокировка для предотвращения одновременных запросов в БД.
3. IdempotencyManager: Обработка заголовка Idempotency-Key (PENDING / COMPLETED).
4. TokenBucketRateLimiter: Ограничение запросов методом "Корзина токенов" с поддержкой всплесков.
5. SlidingWindowRateLimiter: Ограничение запросов методом скользящего окна логов.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import dataclass
from typing import Any, Callable


class IdempotencyConflictError(Exception):
    """Идентичный запрос уже находится в процессе обработки (HTTP 409)."""


class RateLimitExceededError(Exception):
    """Превышен лимит запросов (HTTP 429)."""


class AsyncCacheStore:
    """Асинхронное In-Memory хранилище кэша с поддержкой TTL."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            if key not in self._data:
                return None
            raw_val, expires_at = self._data[key]
            if expires_at is not None and time.monotonic() > expires_at:
                del self._data[key]
                return None
            return json.loads(raw_val)

    async def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        async with self._lock:
            expires_at = (time.monotonic() + ttl_seconds) if ttl_seconds is not None else None
            self._data[key] = (json.dumps(value), expires_at)

    async def delete(self, key: str) -> bool:
        async with self._lock:
            return self._data.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        return (await self.get(key)) is not None


class CacheStampedeProtector:
    """Защита от эффекта стампиды (dog-piling) через механизм мьютексов."""

    def __init__(self, cache: AsyncCacheStore) -> None:
        self.cache = cache
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def _get_key_lock(self, key: str) -> asyncio.Lock:
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    async def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], Any],
        ttl_seconds: float = 60.0,
    ) -> Any:
        # Быстрый путь: чтение из кэша
        cached = await self.cache.get(key)
        if cached is not None:
            return cached

        # Захват блокировки для конкретного ключа: только один вызов идет в compute_fn
        key_lock = await self._get_key_lock(key)
        async with key_lock:
            # Повторная проверка (double-checked locking)
            cached = await self.cache.get(key)
            if cached is not None:
                return cached

            # Вычисление тяжелого результата
            computed = await compute_fn() if inspect.iscoroutinefunction(compute_fn) else compute_fn()
            await self.cache.set(key, computed, ttl_seconds=ttl_seconds)
            return computed


@dataclass
class IdempotencyRecord:
    status: str  # "PENDING" или "COMPLETED"
    status_code: int = 200
    response_body: Any = None


class IdempotencyManager:
    """Менеджер идемпотентности для предотвращения дублирования операций."""

    def __init__(self, cache: AsyncCacheStore) -> None:
        self.cache = cache

    async def process_idempotent_request(
        self,
        key: str,
        handler_fn: Callable[[], Any],
        ttl_seconds: float = 300.0,
    ) -> tuple[int, Any]:
        cache_key = f"idempotency:{key}"
        existing = await self.cache.get(cache_key)

        if existing is not None:
            if existing["status"] == "PENDING":
                raise IdempotencyConflictError("Запрос с данным Idempotency-Key уже выполняется.")
            # Возвращаем сохраненный ответ
            return existing["status_code"], existing["response_body"]

        # Помечаем ключ как PENDING
        await self.cache.set(
            cache_key,
            {"status": "PENDING", "status_code": 0, "response_body": None},
            ttl_seconds=ttl_seconds,
        )

        try:
            status_code, body = (
                await handler_fn() if inspect.iscoroutinefunction(handler_fn) else handler_fn()
            )
            # Сохраняем финальный результат
            await self.cache.set(
                cache_key,
                {"status": "COMPLETED", "status_code": status_code, "response_body": body},
                ttl_seconds=ttl_seconds,
            )
            return status_code, body
        except Exception:
            # При ошибке сбрасываем статус, позволяя клиенту повторить
            await self.cache.delete(cache_key)
            raise


class TokenBucketRateLimiter:
    """Алгоритм ограничения Token Bucket: поддерживает всплески трафика."""

    def __init__(self, capacity: int, refill_rate_per_sec: float) -> None:
        self.capacity = float(capacity)
        self.refill_rate = refill_rate_per_sec
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.last_refill = now

            # Пополнение токенов за прошедшее время
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


class SlidingWindowRateLimiter:
    """Алгоритм ограничения Sliding Window Log (скользящее окно)."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_seconds

            # Очистка устаревших записей
            self._timestamps = [ts for ts in self._timestamps if ts > cutoff]

            if len(self._timestamps) < self.limit:
                self._timestamps.append(now)
                return True
            return False


# ---------------------------------------------------------------------------
# Модульные тесты
# ---------------------------------------------------------------------------
import unittest


class TestCachingAndRateLimiting(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.cache = AsyncCacheStore()

    async def test_cache_set_get_and_expiration(self) -> None:
        """Базовые операции кэша и учет TTL."""
        await self.cache.set("user:1", {"name": "Alice"}, ttl_seconds=0.1)
        cached = await self.cache.get("user:1")
        self.assertEqual(cached, {"name": "Alice"})

        # Ждем истечения TTL
        await asyncio.sleep(0.15)
        expired = await self.cache.get("user:1")
        self.assertIsNone(expired)

    async def test_cache_stampede_protection(self) -> None:
        """Защита от стампиды: при 10 одновременных запросах тяжелая функция вычисляется ровно 1 раз."""
        protector = CacheStampedeProtector(self.cache)
        compute_counter = 0

        async def heavy_db_query() -> dict[str, str]:
            nonlocal compute_counter
            compute_counter += 1
            await asyncio.sleep(0.05)  # Имитация долгого ответа базы данных
            return {"data": "heavy_payload"}

        # Запускаем 10 параллельных конкурентных корутин
        tasks = [
            protector.get_or_compute("heavy_key", heavy_db_query, ttl_seconds=5.0)
            for _ in range(10)
        ]
        results = await asyncio.gather(*tasks)

        # Все 10 корутин получили корректные данные
        for res in results:
            self.assertEqual(res, {"data": "heavy_payload"})

        # Но функция БД вызвана ровно ОДИН раз
        self.assertEqual(compute_counter, 1)

    async def test_idempotency_workflow(self) -> None:
        """Проверка работы менеджера идемпотентности."""
        manager = IdempotencyManager(self.cache)
        execution_count = 0

        async def charge_payment() -> tuple[int, dict[str, str]]:
            nonlocal execution_count
            execution_count += 1
            await asyncio.sleep(0.02)
            return 201, {"tx_id": "tx_999", "status": "paid"}

        # Первый вызов: успешно отрабатывает
        code_1, body_1 = await manager.process_idempotent_request("key_123", charge_payment)
        self.assertEqual(code_1, 201)
        self.assertEqual(body_1["status"], "paid")
        self.assertEqual(execution_count, 1)

        # Второй вызов с тем же ключом: возвращает кэшированный ответ БЕЗ повторного исполнения
        code_2, body_2 = await manager.process_idempotent_request("key_123", charge_payment)
        self.assertEqual(code_2, 201)
        self.assertEqual(body_2["tx_id"], "tx_999")
        self.assertEqual(execution_count, 1)

    async def test_idempotency_conflict_when_pending(self) -> None:
        """Если первый запрос еще не завершился, второй отклоняется с ошибкой конфликта."""
        manager = IdempotencyManager(self.cache)

        async def slow_operation() -> tuple[int, dict[str, str]]:
            await asyncio.sleep(0.1)
            return 200, {"ok": True}

        # Стартуем фоновую медленную операцию
        t1 = asyncio.create_task(
            manager.process_idempotent_request("concurrent_key", slow_operation)
        )
        await asyncio.sleep(0.02)  # Даем первой задаче перейти в статус PENDING

        # Вторая попытка в то же время
        with self.assertRaises(IdempotencyConflictError):
            await manager.process_idempotent_request("concurrent_key", slow_operation)

        await t1

    async def test_token_bucket_limiter(self) -> None:
        """Проверка алгоритма Token Bucket: вместимость и восполнение."""
        limiter = TokenBucketRateLimiter(capacity=3, refill_rate_per_sec=10.0)

        # Снимаем доступные 3 токена (burst)
        self.assertTrue(await limiter.acquire())
        self.assertTrue(await limiter.acquire())
        self.assertTrue(await limiter.acquire())

        # Корзина пуста
        self.assertFalse(await limiter.acquire())

        # Ждем 0.11 секунды (должно восполниться ~1 токен)
        await asyncio.sleep(0.12)
        self.assertTrue(await limiter.acquire())

    async def test_sliding_window_limiter(self) -> None:
        """Проверка алгоритма Sliding Window Log."""
        limiter = SlidingWindowRateLimiter(limit=2, window_seconds=0.1)

        self.assertTrue(await limiter.acquire())
        self.assertTrue(await limiter.acquire())
        # Лимит 2 исчерпан
        self.assertFalse(await limiter.acquire())

        # Ждем выхода старых меток времени из окна
        await asyncio.sleep(0.12)
        self.assertTrue(await limiter.acquire())


if __name__ == "__main__":
    unittest.main()
