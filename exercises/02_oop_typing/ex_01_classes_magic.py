#!/usr/bin/env python3
"""Практическое задание 01: Классы, атрибуты, __slots__ и Dunder-методы.

Инструкция по запуску:
    python3 exercises/02_oop_typing/ex_01_classes_magic.py

Цели задания:
    1. Освоить оптимизацию памяти объектов с помощью __slots__.
    2. Реализовать полный цикл магических методов для класса Money:
       - Строковые представления: __repr__, __str__
       - Сравнение и хеширование: __eq__, __hash__, @total_ordering, __lt__
       - Арифметика: __add__, __sub__, __mul__, __rmul__, __truediv__, __neg__, __abs__
       - Логический контекст: __bool__
    3. Создать потокобезопасный Singleton на базе __new__ с блокировкой threading.Lock.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from functools import total_ordering
import threading
from typing import Any, Self


class CurrencyMismatchError(ValueError):
    """Исключение при попытке сложить или сравнить несовместимые валюты."""
    pass


# ============================================================================
# ЗАДАНИЕ 1: Класс Money с оптимизацией __slots__ и dunder-методами
# ============================================================================

@total_ordering
class Money:
    """Неизменяемый (Value Object) класс денежной суммы с валютой.

    Особенности:
        - Использование __slots__ исключает создание __dict__, экономя память.
        - Сумма округляется до 2 знаков после запятой с помощью Decimal.
        - Реализован полный интерфейс арифметики и сравнения.
    """

    __slots__ = ("_amount", "_currency")

    def __init__(self, amount: Decimal | float | int | str, currency: str = "USD") -> None:
        if isinstance(amount, float):
            dec_amount = Decimal(str(amount))
        elif isinstance(amount, Decimal):
            dec_amount = amount
        else:
            dec_amount = Decimal(str(amount))

        # Округляем до 2 знаков (банковское округление до сотых)
        self._amount: Decimal = dec_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self._currency: str = currency.strip().upper()

    @property
    def amount(self) -> Decimal:
        """Сумма денег в формате Decimal."""
        return self._amount

    @property
    def currency(self) -> str:
        """Код валюты (в верхнем регистре, например 'USD', 'RUB')."""
        return self._currency

    # ------------------------------------------------------------------------
    # Альтернативные конструкторы (фабричные методы)
    # ------------------------------------------------------------------------

    @classmethod
    def from_float(cls, amount: float, currency: str = "USD") -> Self:
        """Создание экземпляра из вещественного числа."""
        return cls(amount=amount, currency=currency)

    @classmethod
    def usd(cls, amount: Decimal | float | int | str) -> Self:
        """Фабрика для долларов США."""
        return cls(amount=amount, currency="USD")

    @classmethod
    def rub(cls, amount: Decimal | float | int | str) -> Self:
        """Фабрика для российских рублей."""
        return cls(amount=amount, currency="RUB")

    @classmethod
    def eur(cls, amount: Decimal | float | int | str) -> Self:
        """Фабрика для евро."""
        return cls(amount=amount, currency="EUR")

    # ------------------------------------------------------------------------
    # Строковые представления
    # ------------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Money({self._amount!r}, {self._currency!r})"

    def __str__(self) -> str:
        return f"{self._amount:.2f} {self._currency}"

    # ------------------------------------------------------------------------
    # Сравнение и хеширование
    # ------------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._amount == other._amount and self._currency == other._currency

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self._currency != other._currency:
            raise CurrencyMismatchError(
                f"Невозможно сравнить разные валюты: {self._currency} и {other._currency}"
            )
        return self._amount < other._amount

    def __hash__(self) -> int:
        return hash((self._amount, self._currency))

    def __bool__(self) -> bool:
        return self._amount != Decimal("0.00")

    # ------------------------------------------------------------------------
    # Арифметические операторы
    # ------------------------------------------------------------------------

    def __add__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self._currency != other._currency:
            raise CurrencyMismatchError(
                f"Нельзя складывать разные валюты: {self._currency} и {other._currency}"
            )
        return Money(self._amount + other._amount, self._currency)

    def __sub__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self._currency != other._currency:
            raise CurrencyMismatchError(
                f"Нельзя вычитать разные валюты: {self._currency} и {other._currency}"
            )
        return Money(self._amount - other._amount, self._currency)

    def __mul__(self, scalar: int | float | Decimal) -> Money:
        if isinstance(scalar, (int, float, Decimal)):
            mult = Decimal(str(scalar))
            return Money(self._amount * mult, self._currency)
        return NotImplemented

    def __rmul__(self, scalar: int | float | Decimal) -> Money:
        return self.__mul__(scalar)

    def __truediv__(self, divisor: int | float | Decimal) -> Money:
        if isinstance(divisor, (int, float, Decimal)):
            div = Decimal(str(divisor))
            if div == Decimal(0):
                raise ZeroDivisionError("Деление денежной суммы на ноль!")
            return Money(self._amount / div, self._currency)
        return NotImplemented

    def __neg__(self) -> Money:
        return Money(-self._amount, self._currency)

    def __abs__(self) -> Money:
        return Money(abs(self._amount), self._currency)


# ============================================================================
# ЗАДАНИЕ 2: Потокобезопасный Singleton на базе __new__
# ============================================================================

class ThreadSafeConfig:
    """Потокобезопасный синглтон конфигурации приложения."""

    _instance: ThreadSafeConfig | None = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> ThreadSafeConfig:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        # Инициализируем только при первом вызове
        if not hasattr(self, "_initialized"):
            with self._lock:
                if not hasattr(self, "_initialized"):
                    self.settings: dict[str, Any] = dict(settings or {})
                    self._initialized: bool = True

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.settings[key] = value


# ============================================================================
# МОДУЛЬНЫЕ ТЕСТЫ (unittest)
# ============================================================================

import unittest


class TestClassesAndMagicMethods(unittest.TestCase):
    """Набор тестов для проверки классов, slots, dunder-методов и синглтона."""

    def test_slots_memory_optimization(self) -> None:
        """Проверяем, что у Money отсутствует __dict__ благодаря __slots__."""
        m = Money(100, "USD")
        self.assertFalse(hasattr(m, "__dict__"))
        with self.assertRaises(AttributeError):
            m.custom_attr = "leak"  # type: ignore[attr-defined]

    def test_properties_and_factories(self) -> None:
        """Проверяем геттеры и фабричные методы."""
        m_usd = Money.usd(50)
        m_rub = Money.rub("100.50")
        m_eur = Money.eur(10.25)
        m_float = Money.from_float(99.99, "GBP")

        self.assertEqual(m_usd.currency, "USD")
        self.assertEqual(m_rub.amount, Decimal("100.50"))
        self.assertEqual(m_rub.currency, "RUB")
        self.assertEqual(m_eur.currency, "EUR")
        self.assertEqual(m_float.currency, "GBP")

        # Проверяем неизменяемость свойств
        with self.assertRaises(AttributeError):
            m_usd.amount = Decimal("200")  # type: ignore[misc]

    def test_string_representations(self) -> None:
        """Проверяем работу __repr__ и __str__."""
        m = Money(42.5, "USD")
        self.assertEqual(repr(m), "Money(Decimal('42.50'), 'USD')")
        self.assertEqual(str(m), "42.50 USD")

    def test_equality_and_hashing(self) -> None:
        """Проверяем равенство и использование в качестве ключа словаря/множества."""
        m1 = Money(100, "USD")
        m2 = Money("100.00", "USD")
        m3 = Money(100, "EUR")

        self.assertEqual(m1, m2)
        self.assertNotEqual(m1, m3)
        self.assertNotEqual(m1, 100)

        # Хеширование
        s = {m1, m2, m3}
        self.assertEqual(len(s), 2)  # m1 и m2 склеились в один элемент
        d = {m1: "First"}
        self.assertEqual(d[m2], "First")

    def test_ordering_and_currency_mismatch(self) -> None:
        """Проверяем упорядочивание (@total_ordering) и исключение при несовпадении валют."""
        m_small = Money(10, "USD")
        m_big = Money(50, "USD")
        m_other = Money(10, "EUR")

        self.assertTrue(m_small < m_big)
        self.assertTrue(m_small <= m_big)
        self.assertTrue(m_big > m_small)
        self.assertTrue(m_big >= m_small)

        with self.assertRaises(CurrencyMismatchError):
            _ = m_small < m_other

    def test_arithmetic_operations(self) -> None:
        """Проверяем сложение, вычитание, умножение, деление и унарные операторы."""
        m1 = Money(100, "USD")
        m2 = Money(30, "USD")

        # Сложение и вычитание
        self.assertEqual(m1 + m2, Money(130, "USD"))
        self.assertEqual(m1 - m2, Money(70, "USD"))

        # Умножение (прямое и отраженное)
        self.assertEqual(m1 * 2, Money(200, "USD"))
        self.assertEqual(2.5 * m1, Money(250, "USD"))

        # Деление
        self.assertEqual(m1 / 2, Money(50, "USD"))
        with self.assertRaises(ZeroDivisionError):
            _ = m1 / 0

        # Унарные операторы
        self.assertEqual(-m1, Money(-100, "USD"))
        self.assertEqual(abs(-m1), Money(100, "USD"))

        # Ошибка при сложении разных валют
        m_rub = Money(100, "RUB")
        with self.assertRaises(CurrencyMismatchError):
            _ = m1 + m_rub

    def test_boolean_context(self) -> None:
        """Проверяем логический контекст (__bool__)."""
        self.assertTrue(bool(Money(10, "USD")))
        self.assertTrue(bool(Money(-5, "USD")))
        self.assertFalse(bool(Money(0, "USD")))
        self.assertFalse(bool(Money("0.00", "USD")))

    def test_thread_safe_singleton(self) -> None:
        """Проверяем единственность экземпляра ThreadSafeConfig в памяти."""
        cfg1 = ThreadSafeConfig({"app": "test", "version": 1})
        cfg2 = ThreadSafeConfig({"app": "overwrite", "version": 2})

        self.assertIs(cfg1, cfg2)
        self.assertEqual(cfg1.get("app"), "test")  # Второй вызов не переписал начальное состояние!
        cfg1.set("debug", True)
        self.assertTrue(cfg2.get("debug"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
