#!/usr/bin/env python3
"""Упражнение 01: Чистая архитектура (Clean Architecture) и тактический DDD.

В этом задании реализуется полноценная архитектура доменной модели интернет-магазина
на чистом Python 3.14 (без сторонних фреймворков):
1. Value Objects: Email, Money, OrderId
2. Entities & Aggregate Root: OrderItem, Order с защитой бизнес-инвариантов
3. Domain Events: OrderPaidEvent
4. Ports (абстрактные интерфейсы): OrderRepositoryPort, NotificationServicePort
5. Use Cases (Application Layer): CreateOrderUseCase, PayOrderUseCase
6. Adapters (Infrastructure Layer): InMemoryOrderRepository, MockNotificationService
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import re
import unittest
from uuid import uuid4


# ============================================================================
# 1. DOMAIN LAYER: Value Objects
# ============================================================================

@dataclass(frozen=True, slots=True)
class OrderId:
    value: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.value or not isinstance(self.value, str):
            raise ValueError("OrderId не может быть пустой строкой")


@dataclass(frozen=True, slots=True)
class Email:
    value: str

    def __post_init__(self) -> None:
        pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(pattern, self.value):
            raise ValueError(f"Некорректный адрес электронной почты: '{self.value}'")


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str = "RUB"

    def __post_init__(self) -> None:
        if self.amount < Decimal("0.00"):
            raise ValueError(f"Сумма денег не может быть отрицательной: {self.amount}")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise ValueError(f"Некорректный код валюты: '{self.currency}'")

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"Нельзя сложить разные валюты: {self.currency} и {other.currency}")
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"Нельзя вычесть разные валюты: {self.currency} и {other.currency}")
        return Money(self.amount - other.amount, self.currency)

    def multiply(self, factor: int) -> Money:
        if factor < 0:
            raise ValueError("Множитель не может быть отрицательным")
        return Money(self.amount * Decimal(factor), self.currency)


# ============================================================================
# 2. DOMAIN LAYER: Events, Entities & Aggregate Root
# ============================================================================

class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class OrderPaidEvent:
    order_id: str
    customer_email: str
    total_amount: Decimal
    currency: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class OrderItem:
    item_id: str
    title: str
    price: Money
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Количество товара должно быть больше 0, получено: {self.quantity}")
        if not self.title.strip():
            raise ValueError("Название товара не может быть пустым")

    @property
    def subtotal(self) -> Money:
        return self.price.multiply(self.quantity)


class Order:
    """Корень агрегата (Aggregate Root) заказа.
    
    Инкапсулирует бизнес-инварианты:
    - Заказ нельзя оплатить, если он пуст.
    - Заказ нельзя оплатить повторно или после отмены.
    - Нельзя добавлять товары в оплаченный или отмененный заказ.
    """

    def __init__(
        self,
        order_id: OrderId,
        customer_email: Email,
        items: list[OrderItem] | None = None,
        status: OrderStatus = OrderStatus.DRAFT,
    ) -> None:
        self.id = order_id
        self.customer_email = customer_email
        self._status = status
        self._items: list[OrderItem] = list(items) if items else []
        self._domain_events: list[object] = []

    @property
    def status(self) -> OrderStatus:
        return self._status

    @property
    def items(self) -> tuple[OrderItem, ...]:
        return tuple(self._items)

    @property
    def total_cost(self) -> Money:
        if not self._items:
            return Money(Decimal("0.00"))
        total = self._items[0].subtotal
        for item in self._items[1:]:
            total = total + item.subtotal
        return total

    def add_item(self, item: OrderItem) -> None:
        if self._status != OrderStatus.DRAFT:
            raise ValueError(f"Нельзя добавлять позиции в заказ со статусом {self._status.value}")
        self._items.append(item)

    def cancel(self) -> None:
        if self._status == OrderStatus.PAID:
            raise ValueError("Нельзя отменить уже оплаченный заказ")
        if self._status == OrderStatus.CANCELLED:
            raise ValueError("Заказ уже отменен")
        self._status = OrderStatus.CANCELLED

    def pay(self) -> None:
        if self._status == OrderStatus.PAID:
            raise ValueError("Заказ уже оплачен")
        if self._status == OrderStatus.CANCELLED:
            raise ValueError("Нельзя оплатить отмененный заказ")
        if not self._items:
            raise ValueError("Невозможно оплатить пустой заказ")

        self._status = OrderStatus.PAID
        total = self.total_cost
        event = OrderPaidEvent(
            order_id=self.id.value,
            customer_email=self.customer_email.value,
            total_amount=total.amount,
            currency=total.currency,
        )
        self._domain_events.append(event)

    def pull_events(self) -> list[object]:
        """Возвращает накопленные доменные события и очищает внутренний список."""
        events = list(self._domain_events)
        self._domain_events.clear()
        return events


# ============================================================================
# 3. APPLICATION LAYER: Ports & Use Cases
# ============================================================================

class OrderRepositoryPort(ABC):
    @abstractmethod
    async def get_by_id(self, order_id: str) -> Order | None:
        """Получить агрегат заказа по его строковому ID."""

    @abstractmethod
    async def save(self, order: Order) -> None:
        """Сохранить или обновить агрегат заказа."""


class NotificationServicePort(ABC):
    @abstractmethod
    async def send_order_receipt(self, email: str, order_id: str, amount: Decimal) -> None:
        """Отправить чек об оплате клиенту."""


class CreateOrderUseCase:
    def __init__(self, order_repository: OrderRepositoryPort) -> None:
        self._order_repository = order_repository

    async def execute(self, customer_email: str) -> Order:
        email = Email(customer_email)
        order = Order(order_id=OrderId(), customer_email=email)
        await self._order_repository.save(order)
        return order


class PayOrderUseCase:
    def __init__(
        self,
        order_repository: OrderRepositoryPort,
        notification_service: NotificationServicePort,
    ) -> None:
        self._order_repository = order_repository
        self._notification_service = notification_service

    async def execute(self, order_id_str: str) -> Order:
        order = await self._order_repository.get_by_id(order_id_str)
        if order is None:
            raise LookupError(f"Заказ с идентификатором {order_id_str} не найден")

        # Доменная бизнес-операция
        order.pay()

        # Сохранение обновленного агрегата
        await self._order_repository.save(order)

        # Диспетчеризация доменных событий
        for event in order.pull_events():
            if isinstance(event, OrderPaidEvent):
                await self._notification_service.send_order_receipt(
                    email=event.customer_email,
                    order_id=event.order_id,
                    amount=event.total_amount,
                )

        return order


# ============================================================================
# 4. INFRASTRUCTURE LAYER: In-Memory Adapters
# ============================================================================

class InMemoryOrderRepository(OrderRepositoryPort):
    def __init__(self) -> None:
        self._storage: dict[str, Order] = {}

    async def get_by_id(self, order_id: str) -> Order | None:
        return self._storage.get(order_id)

    async def save(self, order: Order) -> None:
        self._storage[order.id.value] = order


@dataclass
class SentNotification:
    email: str
    order_id: str
    amount: Decimal


class MockNotificationService(NotificationServicePort):
    def __init__(self) -> None:
        self.sent_notifications: list[SentNotification] = []

    async def send_order_receipt(self, email: str, order_id: str, amount: Decimal) -> None:
        self.sent_notifications.append(
            SentNotification(email=email, order_id=order_id, amount=amount)
        )


# ============================================================================
# 5. UNIT & INTEGRATION TESTS
# ============================================================================

class TestValueObjects(unittest.TestCase):
    def test_email_valid(self) -> None:
        email = Email("user@example.com")
        self.assertEqual(email.value, "user@example.com")

    def test_email_invalid_raises_error(self) -> None:
        with self.assertRaises(ValueError):
            Email("invalid-email-address")

    def test_money_addition_and_validation(self) -> None:
        m1 = Money(Decimal("100.50"), "RUB")
        m2 = Money(Decimal("50.25"), "RUB")
        total = m1 + m2
        self.assertEqual(total.amount, Decimal("150.75"))
        self.assertEqual(total.currency, "RUB")

    def test_money_different_currencies_raises_error(self) -> None:
        m1 = Money(Decimal("100.00"), "RUB")
        m2 = Money(Decimal("10.00"), "USD")
        with self.assertRaises(ValueError):
            _ = m1 + m2

    def test_money_negative_raises_error(self) -> None:
        with self.assertRaises(ValueError):
            Money(Decimal("-0.01"), "RUB")


class TestOrderAggregate(unittest.TestCase):
    def setUp(self) -> None:
        self.email = Email("customer@test.com")
        self.order = Order(order_id=OrderId(), customer_email=self.email)

    def test_empty_order_total_is_zero(self) -> None:
        self.assertEqual(self.order.total_cost.amount, Decimal("0.00"))

    def test_cannot_pay_empty_order(self) -> None:
        with self.assertRaises(ValueError):
            self.order.pay()

    def test_add_items_and_calculate_total(self) -> None:
        item1 = OrderItem(
            item_id="i1",
            title="Книга по FastAPI",
            price=Money(Decimal("1200.00"), "RUB"),
            quantity=2,
        )
        item2 = OrderItem(
            item_id="i2",
            title="Блокнот",
            price=Money(Decimal("300.00"), "RUB"),
            quantity=1,
        )
        self.order.add_item(item1)
        self.order.add_item(item2)

        self.assertEqual(self.order.total_cost.amount, Decimal("2700.00"))

    def test_successful_pay_emits_event(self) -> None:
        item = OrderItem(
            item_id="i1",
            title="Товар",
            price=Money(Decimal("500.00"), "RUB"),
            quantity=1,
        )
        self.order.add_item(item)
        self.order.pay()

        self.assertEqual(self.order.status, OrderStatus.PAID)
        events = self.order.pull_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertIsInstance(event, OrderPaidEvent)
        if isinstance(event, OrderPaidEvent):
            self.assertEqual(event.total_amount, Decimal("500.00"))
            self.assertEqual(event.customer_email, "customer@test.com")

        # Вторичный вызов pull_events должен вернуть пустой список
        self.assertEqual(len(self.order.pull_events()), 0)

    def test_cannot_add_item_to_paid_order(self) -> None:
        item = OrderItem("i1", "Товар", Money(Decimal("100.00")), 1)
        self.order.add_item(item)
        self.order.pay()

        with self.assertRaises(ValueError):
            self.order.add_item(OrderItem("i2", "Еще товар", Money(Decimal("50.00")), 1))

    def test_cannot_pay_cancelled_order(self) -> None:
        item = OrderItem("i1", "Товар", Money(Decimal("100.00")), 1)
        self.order.add_item(item)
        self.order.cancel()

        with self.assertRaises(ValueError):
            self.order.pay()


class TestUseCases(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repo = InMemoryOrderRepository()
        self.notifier = MockNotificationService()
        self.create_use_case = CreateOrderUseCase(self.repo)
        self.pay_use_case = PayOrderUseCase(self.repo, self.notifier)

    async def test_full_order_checkout_flow(self) -> None:
        # 1. Создание заказа
        order = await self.create_use_case.execute("buyer@domain.com")
        self.assertEqual(order.status, OrderStatus.DRAFT)

        # 2. Добавление товаров
        order.add_item(
            OrderItem("prod-1", "Курс Python Pro", Money(Decimal("4990.00")), 1)
        )
        await self.repo.save(order)

        # 3. Оплата через Use Case
        paid_order = await self.pay_use_case.execute(order.id.value)
        self.assertEqual(paid_order.status, OrderStatus.PAID)

        # 4. Проверка нотификации
        self.assertEqual(len(self.notifier.sent_notifications), 1)
        notif = self.notifier.sent_notifications[0]
        self.assertEqual(notif.email, "buyer@domain.com")
        self.assertEqual(notif.order_id, order.id.value)
        self.assertEqual(notif.amount, Decimal("4990.00"))

    async def test_pay_nonexistent_order_raises_lookup_error(self) -> None:
        with self.assertRaises(LookupError):
            await self.pay_use_case.execute("non-existent-order-id")


if __name__ == "__main__":
    unittest.main()
