#!/usr/bin/env python3
"""Практическое задание 02: Наследование, MRO (C3-линеаризация), миксины и ABC.

Инструкция по запуску:
    python3 exercises/02_oop_typing/ex_02_inheritance_abc.py

Цели задания:
    1. Освоить проектирование контрактов через Abstract Base Classes (модуль abc).
    2. Реализовать независимые переиспользуемые миксины (Mixins) с кооперативным super().
    3. Разобрать проблему ромба (Diamond Problem) и подтвердить работу C3-линеаризации.
    4. Создать конкретную реализацию репозитория, объединяющую абстрактный контракт и миксины.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
from typing import Any, Generic, TypeVar

T = TypeVar("T")


# ============================================================================
# ЗАДАНИЕ 1: Абстрактный базовый контракт репозитория
# ============================================================================

class BaseRepository(ABC, Generic[T]):
    """Абстрактный класс репозитория, определяющий CRUD-контракт."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    @property
    @abstractmethod
    def entity_name(self) -> str:
        """Имя доменной сущности (например, 'User', 'Product')."""
        pass

    @abstractmethod
    def get(self, entity_id: int) -> T | None:
        """Получить сущность по ID."""
        pass

    @abstractmethod
    def add(self, entity: T) -> int:
        """Сохранить сущность и вернуть присвоенный ID."""
        pass

    @abstractmethod
    def delete(self, entity_id: int) -> bool:
        """Удалить сущность по ID. Возвращает True, если запись была удалена."""
        pass


# ============================================================================
# ЗАДАНИЕ 2: Миксины функциональности (Mixins)
# ============================================================================

class AuditLogMixin:
    """Миксин для ведения журнала аудита операций в сущности."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)  # Передаем kwargs дальше по цепочке MRO!
        self.audit_log: list[str] = []

    def log_audit(self, action: str, details: str) -> None:
        """Запись события аудита."""
        self.audit_log.append(f"[{action}] {details}")


class JsonExportMixin:
    """Миксин для сериализации внутренних данных в JSON."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def get_export_data(self) -> Any:
        """Метод-хук: возвращает данные для сериализации.

        Если класс имеет _storage, возвращаем его значения, иначе __dict__.
        """
        if hasattr(self, "_storage"):
            return getattr(self, "_storage")
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def to_json(self, indent: int = 2) -> str:
        """Сериализация данных в формат JSON."""
        return json.dumps(self.get_export_data(), indent=indent, default=str)


# ============================================================================
# ЗАДАНИЕ 3: Разрешение ромбовидного наследования и кооперативный super()
# ============================================================================

class BasePlugin:
    """Корневой базовый плагин."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.execution_order: list[str] = []

    def bootstrap(self) -> None:
        self.execution_order.append("BasePlugin")


class AuthPlugin(BasePlugin):
    """Плагин аутентификации."""

    def bootstrap(self) -> None:
        self.execution_order.append("AuthPlugin")
        super().bootstrap()


class LoggingPlugin(BasePlugin):
    """Плагин логирования."""

    def bootstrap(self) -> None:
        self.execution_order.append("LoggingPlugin")
        super().bootstrap()


class FullAppPlugin(AuthPlugin, LoggingPlugin):
    """Композитный плагин приложения с ромбовидным наследованием.

    Ожидаемый MRO: FullAppPlugin -> AuthPlugin -> LoggingPlugin -> BasePlugin -> object
    """

    def bootstrap(self) -> None:
        self.execution_order.append("FullAppPlugin")
        super().bootstrap()


# ============================================================================
# ЗАДАНИЕ 4: Конкретная реализация репозитория
# ============================================================================

class InMemoryUserRepository(
    AuditLogMixin,
    JsonExportMixin,
    BaseRepository[dict[str, Any]],
):
    """Конкретный in-memory репозиторий пользователей с аудитом и экспортом."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._storage: dict[int, dict[str, Any]] = {}
        self._id_counter: int = 1

    @property
    def entity_name(self) -> str:
        return "User"

    def get(self, entity_id: int) -> dict[str, Any] | None:
        data = self._storage.get(entity_id)
        if data is None:
            return None
        return dict(data)  # Возвращаем копию для безопасности

    def add(self, entity: dict[str, Any]) -> int:
        record_id = self._id_counter
        self._id_counter += 1

        record = dict(entity)
        record["id"] = record_id
        self._storage[record_id] = record

        self.log_audit("ADD", f"{self.entity_name} #{record_id} ({record.get('username')})")
        return record_id

    def delete(self, entity_id: int) -> bool:
        if entity_id in self._storage:
            deleted_user = self._storage.pop(entity_id)
            self.log_audit(
                "DELETE",
                f"{self.entity_name} #{entity_id} ({deleted_user.get('username')})",
            )
            return True
        return False


# ============================================================================
# МОДУЛЬНЫЕ ТЕСТЫ (unittest)
# ============================================================================

import unittest


class TestInheritanceMroAndABC(unittest.TestCase):
    """Тестирование ABC, MRO, ромбовидного наследования и миксинов."""

    def test_cannot_instantiate_abstract_base_class(self) -> None:
        """Убеждаемся, что абстрактный класс нельзя инстанцировать."""
        with self.assertRaises(TypeError):
            BaseRepository()  # type: ignore[abstract]

    def test_incomplete_subclass_raises_error(self) -> None:
        """Подкласс, не реализовавший все абстрактные методы, не может быть создан."""
        class IncompleteRepo(BaseRepository[dict[str, Any]]):
            @property
            def entity_name(self) -> str:
                return "Incomplete"
            # Не реализованы get, add, delete!

        with self.assertRaises(TypeError):
            IncompleteRepo()  # type: ignore[abstract]

    def test_user_repository_crud(self) -> None:
        """Проверяем базовые CRUD операции репозитория."""
        repo = InMemoryUserRepository()
        self.assertEqual(repo.entity_name, "User")

        # Добавление
        u1_id = repo.add({"username": "alex", "email": "alex@corp.com"})
        u2_id = repo.add({"username": "maria", "email": "maria@corp.com"})

        self.assertEqual(u1_id, 1)
        self.assertEqual(u2_id, 2)

        # Получение
        user = repo.get(u1_id)
        self.assertIsNotNone(user)
        assert user is not None
        self.assertEqual(user["username"], "alex")

        # Удаление
        self.assertTrue(repo.delete(u1_id))
        self.assertFalse(repo.delete(999))  # Несуществующий ID
        self.assertIsNone(repo.get(u1_id))

    def test_audit_log_mixin(self) -> None:
        """Проверяем, что AuditLogMixin корректно протоколирует операции."""
        repo = InMemoryUserRepository()
        repo.add({"username": "dmitry"})
        repo.delete(1)

        self.assertEqual(len(repo.audit_log), 2)
        self.assertIn("[ADD] User #1 (dmitry)", repo.audit_log[0])
        self.assertIn("[DELETE] User #1 (dmitry)", repo.audit_log[1])

    def test_json_export_mixin(self) -> None:
        """Проверяем, что JsonExportMixin сериализует хранилище в валидный JSON."""
        repo = InMemoryUserRepository()
        repo.add({"username": "elena", "role": "admin"})

        json_str = repo.to_json()
        parsed = json.loads(json_str)
        # Ключи в JSON строковые: "1"
        self.assertIn("1", parsed)
        self.assertEqual(parsed["1"]["username"], "elena")
        self.assertEqual(parsed["1"]["role"], "admin")

    def test_diamond_c3_linearization_order(self) -> None:
        """Проверяем строгое совпадение MRO с формулой C3-линеаризации."""
        expected_mro = (
            FullAppPlugin,
            AuthPlugin,
            LoggingPlugin,
            BasePlugin,
            object,
        )
        self.assertEqual(FullAppPlugin.__mro__, expected_mro)

    def test_cooperative_super_bootstrap_execution(self) -> None:
        """Проверяем, что super() в ромбе обходит все классы ровно один раз в порядке MRO."""
        plugin = FullAppPlugin()
        plugin.bootstrap()

        # Порядок вызовов super().bootstrap() от вершины к базовому классу:
        expected_order = ["FullAppPlugin", "AuthPlugin", "LoggingPlugin", "BasePlugin"]
        self.assertEqual(plugin.execution_order, expected_order)


if __name__ == "__main__":
    unittest.main(verbosity=2)
