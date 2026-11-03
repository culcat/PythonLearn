#!/usr/bin/env python3
"""Практическое задание 04: Dataclasses, Enum и протокол дескрипторов.

Инструкция по запуску:
    python3 exercises/02_oop_typing/ex_04_dataclasses_descriptors.py

Цели задания:
    1. Освоить декларативное проектирование неизменяемых моделей данных с @dataclass:
       - Использование frozen=True, slots=True, kw_only=True
       - Валидация инвариантов и пост-настройка в __post_init__
    2. Реализовать строгие перечисления StrEnum и битовые маски прав Flag.
    3. Создать кастомные валидирующие дескрипторы данных (Data Descriptors)
       с автоматическим связыванием имени через __set_name__.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, field
from enum import Flag, StrEnum, auto
from typing import Any


# ============================================================================
# ЗАДАНИЕ 1: Строгие перечисления (Enum и Flag)
# ============================================================================

class UserRole(StrEnum):
    """Строковое перечисление ролей пользователей системы."""

    ADMIN = "admin"
    MODERATOR = "moderator"
    USER = "user"


class Permission(Flag):
    """Битовые флаги прав доступа."""

    NONE = 0
    READ = auto()       # 1
    WRITE = auto()      # 2
    EXECUTE = auto()    # 4
    ADMIN = READ | WRITE | EXECUTE  # 7


# ============================================================================
# ЗАДАНИЕ 2: Датакласс с frozen=True, slots=True и валидацией в __post_init__
# ============================================================================

@dataclass(frozen=True, slots=True, kw_only=True)
class UserProfile:
    """Неизменяемый профиль пользователя системы."""

    id: int
    username: str
    role: UserRole = UserRole.USER
    permissions: Permission = Permission.READ
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        clean_name = self.username.strip()
        if len(clean_name) < 3:
            raise ValueError("Имя пользователя должно содержать минимум 3 символа!")

        # В frozen датаклассе атрибуты меняются через object.__setattr__
        object.__setattr__(self, "username", clean_name)

        # Инвариант: роль ADMIN гарантирует флаг прав Permission.ADMIN
        if self.role == UserRole.ADMIN and (Permission.ADMIN not in self.permissions):
            object.__setattr__(self, "permissions", self.permissions | Permission.ADMIN)


# ============================================================================
# ЗАДАНИЕ 3: Протокол дескрипторов (Data Descriptors)
# ============================================================================

class ValidatedString:
    """Дескриптор валидации строкового поля с контролем длины."""

    def __init__(self, min_length: int = 1, max_length: int = 255) -> None:
        self.min_length = min_length
        self.max_length = max_length
        self.storage_name: str = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.storage_name = f"_{name}"

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        if instance is None:
            return self
        return getattr(instance, self.storage_name, None)

    def __set__(self, instance: Any, value: Any) -> None:
        if not isinstance(value, str):
            raise TypeError(f"Ожидалась строка, получено {type(value).__name__}")

        cleaned = value.strip()
        if not (self.min_length <= len(cleaned) <= self.max_length):
            raise ValueError(
                f"Длина строки должна быть от {self.min_length} до {self.max_length} символов"
            )
        setattr(instance, self.storage_name, cleaned)


class BoundedNumber:
    """Дескриптор валидации числового диапазона."""

    def __init__(self, min_val: float | None = None, max_val: float | None = None) -> None:
        self.min_val = min_val
        self.max_val = max_val
        self.storage_name: str = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.storage_name = f"_{name}"

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        if instance is None:
            return self
        return getattr(instance, self.storage_name, None)

    def __set__(self, instance: Any, value: Any) -> None:
        if not isinstance(value, (int, float)):
            raise TypeError(f"Ожидалось число, получено {type(value).__name__}")

        num = float(value)
        if self.min_val is not None and num < self.min_val:
            raise ValueError(f"Число {num} меньше минимально допустимого {self.min_val}")
        if self.max_val is not None and num > self.max_val:
            raise ValueError(f"Число {num} больше максимально допустимого {self.max_val}")

        setattr(instance, self.storage_name, num)


class ProductModel:
    """Модель товара с полями, управляемыми дескрипторами."""

    title = ValidatedString(min_length=3, max_length=50)
    price = BoundedNumber(min_val=0.01, max_val=1_000_000.0)

    def __init__(self, title: str, price: float) -> None:
        self.title = title
        self.price = price


# ============================================================================
# МОДУЛЬНЫЕ ТЕСТЫ (unittest)
# ============================================================================

import unittest


class TestDataclassesEnumsDescriptors(unittest.TestCase):
    """Набор тестов для проверки датаклассов, enum и дескрипторов."""

    def test_user_profile_frozen_and_slots(self) -> None:
        """Проверяем неизменяемость frozen датакласса и отсутствие __dict__ (slots=True)."""
        profile = UserProfile(id=1, username="alex")
        self.assertFalse(hasattr(profile, "__dict__"))

        with self.assertRaises(FrozenInstanceError):
            profile.username = "new_name"  # type: ignore[misc]

    def test_user_profile_post_init_validation(self) -> None:
        """Проверяем валидацию длины имени и автоматическое добавление прав для ADMIN."""
        with self.assertRaises(ValueError):
            UserProfile(id=2, username="ab")  # Меньше 3 символов

        # Проверяем инвариант прав администратора
        admin = UserProfile(id=3, username="root_admin", role=UserRole.ADMIN)
        self.assertIn(Permission.READ, admin.permissions)
        self.assertIn(Permission.WRITE, admin.permissions)
        self.assertIn(Permission.EXECUTE, admin.permissions)
        self.assertIn(Permission.ADMIN, admin.permissions)

    def test_user_role_str_enum(self) -> None:
        """Проверяем совместимость StrEnum со строками."""
        self.assertEqual(UserRole.ADMIN, "admin")
        self.assertEqual(UserRole.USER, "user")
        self.assertIn(UserRole.MODERATOR, ["admin", "moderator", "user"])

    def test_permission_flags(self) -> None:
        """Проверяем битовые операции объединения и проверки прав Flag."""
        perms = Permission.READ | Permission.WRITE
        self.assertIn(Permission.READ, perms)
        self.assertIn(Permission.WRITE, perms)
        self.assertNotIn(Permission.EXECUTE, perms)

    def test_validated_string_descriptor(self) -> None:
        """Проверяем дескриптор ValidatedString: валидацию типов и длины."""
        prod = ProductModel("Ноутбук", 1500.0)
        self.assertEqual(prod.title, "Ноутбук")

        # Невалидный тип
        with self.assertRaises(TypeError):
            prod.title = 12345  # type: ignore[assignment]

        # Слишком короткая строка
        with self.assertRaises(ValueError):
            prod.title = "ab"

        # Слишком длинная строка (> 50 символов)
        with self.assertRaises(ValueError):
            prod.title = "A" * 51

    def test_bounded_number_descriptor(self) -> None:
        """Проверяем дескриптор BoundedNumber: нижнюю и верхнюю границы."""
        prod = ProductModel("Клавиатура", 100.0)
        self.assertEqual(prod.price, 100.0)

        with self.assertRaises(TypeError):
            prod.price = "100"  # type: ignore[assignment]

        with self.assertRaises(ValueError):
            prod.price = 0.0  # < 0.01

        with self.assertRaises(ValueError):
            prod.price = 2_000_000.0  # > 1_000_000

    def test_descriptors_instance_isolation(self) -> None:
        """Убеждаемся, что разные экземпляры класса хранят изолированные значения."""
        p1 = ProductModel("Товар 1", 10.0)
        p2 = ProductModel("Товар 2", 20.0)

        self.assertEqual(p1.title, "Товар 1")
        self.assertEqual(p2.title, "Товар 2")
        self.assertEqual(p1.price, 10.0)
        self.assertEqual(p2.price, 20.0)

        # Классовый доступ возвращает сам дескриптор
        self.assertIsInstance(ProductModel.title, ValidatedString)
        self.assertIsInstance(ProductModel.price, BoundedNumber)


if __name__ == "__main__":
    unittest.main(verbosity=2)
