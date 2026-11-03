#!/usr/bin/env python3
"""Упражнение 03: Распределенные очереди задач, паттерн Transactional Outbox и DLQ.

В этом задании реализуется архитектура надежной асинхронной обработки событий:
1. Transactional Outbox: атомарное сохранение сущности и события
2. OutboxWorker: фоновый процессинг с повторными попытками
3. Exponential Backoff со случайным шумом (Jitter)
4. Dead Letter Queue (DLQ) для отравленных сообщений
5. Идемпотентный консьюмер для защиты от повторной доставки (At-Least-Once)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import random
import time
from typing import Any
import unittest
from uuid import uuid4


# ============================================================================
# 1. МОДЕЛИ СОБЫТИЙ И ПАТТЕРН TRANSACTIONAL OUTBOX
# ============================================================================

class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    DLQ = "DLQ"


@dataclass
class OutboxEvent:
    id: str = field(default_factory=lambda: str(uuid4()))
    event_type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    status: OutboxStatus = OutboxStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    processed_at: float | None = None


class OutboxRepository:
    """Хранилище, эмулирующее атомарную транзакцию БД для бизнес-сущности и Outbox."""

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.events: dict[str, OutboxEvent] = {}

    async def save_order_with_outbox(
        self,
        order_id: str,
        order_data: dict[str, Any],
        event: OutboxEvent,
    ) -> None:
        # Атомарная фиксация обоих объектов
        self.orders[order_id] = order_data
        self.events[event.id] = event

    async def get_pending_events(self) -> list[OutboxEvent]:
        return [
            event for event in self.events.values()
            if event.status in (OutboxStatus.PENDING, OutboxStatus.FAILED)
        ]

    async def update_event(self, event: OutboxEvent) -> None:
        self.events[event.id] = event


# ============================================================================
# 2. ЭМУЛЯТОР БРОКЕРА СООБЩЕНИЙ И DLQ
# ============================================================================

class MockMessageBroker:
    """Брокер сообщений с поддержкой симуляции сетевых сбоев и Dead Letter Queue."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []
        self.dlq: list[OutboxEvent] = []
        self._failures_remaining: int = 0

    def simulate_transient_failure(self, count: int) -> None:
        self._failures_remaining = count

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._failures_remaining > 0:
            self._failures_remaining -= 1
            raise ConnectionResetError("Сеть недоступна: ошибка подключения к брокеру")

        self.published.append((event_type, payload))

    async def route_to_dlq(self, event: OutboxEvent) -> None:
        self.dlq.append(event)


# ============================================================================
# 3. EXPONENTIAL BACKOFF + JITTER И ФОНОВЫЙ OUTBOX WORKER
# ============================================================================

def calculate_backoff_delay(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: float = 0.1,
) -> float:
    """Вычисляет задержку по формуле: min(max_delay, base_delay * 2^attempt) + jitter."""
    calculated = min(max_delay, base_delay * (2 ** attempt))
    jitter_offset = random.uniform(-jitter, jitter)
    return max(0.0, calculated + jitter_offset)


class OutboxWorker:
    """Воркер, вычитывающий события из Outbox и публикующий их в брокер."""

    def __init__(self, repository: OutboxRepository, broker: MockMessageBroker) -> None:
        self._repo = repository
        self._broker = broker

    async def process_pending_events(self) -> int:
        events = await self._repo.get_pending_events()
        processed_count = 0

        for event in events:
            try:
                await self._broker.publish(event.event_type, event.payload)
                event.status = OutboxStatus.PUBLISHED
                event.processed_at = time.time()
                await self._repo.update_event(event)
                processed_count += 1
            except Exception:
                event.retry_count += 1
                if event.retry_count >= event.max_retries:
                    event.status = OutboxStatus.DLQ
                    await self._broker.route_to_dlq(event)
                else:
                    event.status = OutboxStatus.FAILED
                await self._repo.update_event(event)

        return processed_count


# ============================================================================
# 4. ИДЕМПОТЕНТНЫЙ КОНСЬЮМЕР (IDEMPOTENT CONSUMER)
# ============================================================================

class IdempotentConsumer:
    """Консьюмер, гарантирующий однократную обработку при доставке At-Least-Once."""

    def __init__(self) -> None:
        self.processed_ids: set[str] = set()
        self.consumed_events: list[dict[str, Any]] = []

    async def handle_message(self, event_id: str, payload: dict[str, Any]) -> bool:
        if event_id in self.processed_ids:
            # Игнорируем дубликат сообщения
            return False

        # Выполняем бизнес-логику
        self.consumed_events.append(payload)
        self.processed_ids.add(event_id)
        return True


# ============================================================================
# 5. UNIT & INTEGRATION TESTS
# ============================================================================

class TestTransactionalOutbox(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repo = OutboxRepository()
        self.broker = MockMessageBroker()
        self.worker = OutboxWorker(self.repo, self.broker)

    async def test_atomic_order_and_outbox_event_creation(self) -> None:
        event = OutboxEvent(
            event_type="order.created",
            payload={"order_id": "ord-101", "amount": 1500},
        )
        await self.repo.save_order_with_outbox(
            order_id="ord-101",
            order_data={"status": "NEW", "total": 1500},
            event=event,
        )

        self.assertIn("ord-101", self.repo.orders)
        self.assertIn(event.id, self.repo.events)
        pending = await self.repo.get_pending_events()
        self.assertEqual(len(pending), 1)

    async def test_worker_publishes_event_successfully(self) -> None:
        event = OutboxEvent(
            event_type="order.created",
            payload={"order_id": "ord-1"},
        )
        await self.repo.save_order_with_outbox("ord-1", {}, event)

        published_count = await self.worker.process_pending_events()
        self.assertEqual(published_count, 1)

        # Проверка состояния события и брокера
        self.assertEqual(self.repo.events[event.id].status, OutboxStatus.PUBLISHED)
        self.assertEqual(len(self.broker.published), 1)
        self.assertEqual(self.broker.published[0][0], "order.created")

    async def test_worker_retries_transient_failure(self) -> None:
        event = OutboxEvent(
            event_type="order.created",
            payload={"order_id": "ord-retry"},
        )
        await self.repo.save_order_with_outbox("ord-retry", {}, event)

        # Симулируем 1 временный сбой
        self.broker.simulate_transient_failure(1)

        # Первый запуск воркера — падение
        first_count = await self.worker.process_pending_events()
        self.assertEqual(first_count, 0)
        self.assertEqual(self.repo.events[event.id].status, OutboxStatus.FAILED)
        self.assertEqual(self.repo.events[event.id].retry_count, 1)

        # Второй запуск воркера — брокер восстановился, событие опубликовано
        second_count = await self.worker.process_pending_events()
        self.assertEqual(second_count, 1)
        self.assertEqual(self.repo.events[event.id].status, OutboxStatus.PUBLISHED)

    async def test_worker_routes_to_dlq_after_max_retries(self) -> None:
        event = OutboxEvent(
            event_type="order.poison_pill",
            payload={"broken": True},
            max_retries=2,
        )
        await self.repo.save_order_with_outbox("ord-poison", {}, event)

        # Симулируем постоянный отказ брокера
        self.broker.simulate_transient_failure(10)

        # Попытка 1
        await self.worker.process_pending_events()
        self.assertEqual(self.repo.events[event.id].retry_count, 1)
        self.assertEqual(self.repo.events[event.id].status, OutboxStatus.FAILED)

        # Попытка 2 -> Превышение лимита -> Отправка в DLQ
        await self.worker.process_pending_events()
        self.assertEqual(self.repo.events[event.id].retry_count, 2)
        self.assertEqual(self.repo.events[event.id].status, OutboxStatus.DLQ)
        self.assertEqual(len(self.broker.dlq), 1)
        self.assertEqual(self.broker.dlq[0].id, event.id)


class TestBackoffAndIdempotency(unittest.IsolatedAsyncioTestCase):
    def test_exponential_backoff_calculation(self) -> None:
        # Без случайного шума (jitter=0)
        d0 = calculate_backoff_delay(0, base_delay=1.0, max_delay=10.0, jitter=0.0)
        d1 = calculate_backoff_delay(1, base_delay=1.0, max_delay=10.0, jitter=0.0)
        d2 = calculate_backoff_delay(2, base_delay=1.0, max_delay=10.0, jitter=0.0)
        d10 = calculate_backoff_delay(10, base_delay=1.0, max_delay=10.0, jitter=0.0)

        self.assertEqual(d0, 1.0)
        self.assertEqual(d1, 2.0)
        self.assertEqual(d2, 4.0)
        self.assertEqual(d10, 10.0)  # Ограничение max_delay

    async def test_idempotent_consumer_skips_duplicate(self) -> None:
        consumer = IdempotentConsumer()
        event_id = "evt-unique-123"
        payload = {"order_id": "1", "amount": 100}

        # Первое получение — обработка успешна
        first_call = await consumer.handle_message(event_id, payload)
        self.assertTrue(first_call)
        self.assertEqual(len(consumer.consumed_events), 1)

        # Повторное получение (дубликат сети) — пропуск без дублирования
        second_call = await consumer.handle_message(event_id, payload)
        self.assertFalse(second_call)
        self.assertEqual(len(consumer.consumed_events), 1)


if __name__ == "__main__":
    unittest.main()
