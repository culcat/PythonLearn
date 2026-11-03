#!/usr/bin/env python3
"""Упражнение 02: Метаклассы, __init_subclass__ и продвинутый contextlib.

Тема: Метакласс ValidatedMeta с контролем дубликатов (__prepare__) и контракта (__new__),
система плагинов через __init_subclass__ и транзакционный менеджер ресурсов на ExitStack.

Запуск тестов:
    python3 exercises/03_internals_async/ex_02_metaclasses_context.py
    или из корня:
    python3 run_all_tests.py
"""

from __future__ import annotations

import contextlib
import unittest
from typing import Any, Callable, ClassVar, Dict, List, Optional, Type


# =====================================================================
# ЗАДАНИЕ 1: Метакласс с валидацией контракта и пространства имен
# =====================================================================

class DuplicateCheckingDict(dict[str, Any]):
    """Словарь пространства имен, запрещающий повторное объявление атрибутов."""

    def __setitem__(self, key: str, value: Any) -> None:
        # Игнорируем dunder-атрибуты вроде __module__, __qualname__
        if not (key.startswith("__") and key.endswith("__")):
            if key in self:
                raise TypeError(f"Дублирование атрибута: '{key}' уже определен в классе!")
        super().__setitem__(key, value)


class ValidatedMeta(type):
    """Метакласс для валидации сервисных классов.

    - Через __prepare__ запрещает дублирование методов и атрибутов.
    - Через __new__ требует от производных классов наличие docstring и метода 'execute'.
    """

    @classmethod
    def __prepare__(
        metacls, name: str, bases: tuple[type, ...], **kwargs: Any
    ) -> DuplicateCheckingDict:
        return DuplicateCheckingDict()

    def __new__(
        mcs, name: str, bases: tuple[type, ...], namespace: dict[str, Any], **kwargs: Any
    ) -> type:
        cls = super().__new__(mcs, name, bases, namespace)

        # Базовый класс BaseService не обязан иметь execute и docstring
        if name != "BaseService":
            doc = namespace.get("__doc__")
            if not doc or not doc.strip():
                raise TypeError(f"Класс '{name}' обязан содержать непустой docstring!")

            execute_attr = namespace.get("execute")
            if not callable(execute_attr):
                raise TypeError(f"Класс '{name}' обязан реализовывать callable-метод 'execute'!")

        return cls


class BaseService(metaclass=ValidatedMeta):
    """Базовый абстрактный сервис."""
    pass


# =====================================================================
# ЗАДАНИЕ 2: Реестр плагинов через __init_subclass__
# =====================================================================

class PluginRegistry:
    """Базовый класс реестра плагинов на базе __init_subclass__ (PEP 487)."""

    _registry: ClassVar[Dict[str, Type[PluginRegistry]]] = {}
    _versions: ClassVar[Dict[str, int]] = {}

    plugin_name: ClassVar[str]
    plugin_version: ClassVar[int]

    def __init_subclass__(
        cls, plugin_name: str, version: int = 1, **kwargs: Any
    ) -> None:
        super().__init_subclass__(**kwargs)
        if not plugin_name:
            raise ValueError("Имя плагина 'plugin_name' не может быть пустым!")

        if plugin_name in cls._registry:
            raise ValueError(f"Плагин '{plugin_name}' уже зарегистрирован!")

        cls.plugin_name = plugin_name
        cls.plugin_version = version
        cls._registry[plugin_name] = cls
        cls._versions[plugin_name] = version

    @classmethod
    def get_plugin(cls, name: str) -> Type[PluginRegistry]:
        """Возвращает класс плагина по имени."""
        if name not in cls._registry:
            raise KeyError(f"Плагин '{name}' не найден в реестре.")
        return cls._registry[name]

    @classmethod
    def list_plugins(cls) -> List[str]:
        """Возвращает список всех зарегистрированных имен плагинов."""
        return sorted(cls._registry.keys())

    @classmethod
    def clear_registry(cls) -> None:
        """Служебный метод для очистки реестра перед тестами."""
        cls._registry.clear()
        cls._versions.clear()

    def execute(self, payload: dict[str, Any]) -> str:
        raise NotImplementedError


# =====================================================================
# ЗАДАНИЕ 3: Транзакционный менеджер с откатом на ExitStack
# =====================================================================

class TransactionalContext:
    """Контекстный менеджер транзакций с поддержкой отката (Rollback).

    - Регистрирует компенсирующие действия через add_rollback.
    - При успешном выходе и вызове commit() действия отката не запускаются.
    - При возникновении исключения или отсутствии вызова commit()
      все зарегистрированные действия отката выполняются в порядке LIFO.
    """

    def __init__(self) -> None:
        self._stack = contextlib.ExitStack()
        self._rollbacks: List[Callable[[], None]] = []
        self._committed: bool = False

    def add_rollback(self, action: Callable[[], None]) -> None:
        """Добавляет действие отката, которое выполнится при сбое."""
        self._rollbacks.append(action)

    def commit(self) -> None:
        """Фиксирует транзакцию. После этого откат не будет выполнен."""
        self._committed = True

    def __enter__(self) -> "TransactionalContext":
        self._stack.__enter__()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> bool:
        try:
            # Если возникло исключение или не было коммита — выполняем откаты
            if exc_type is not None or not self._committed:
                for rollback_fn in reversed(self._rollbacks):
                    try:
                        rollback_fn()
                    except Exception:
                        pass
        finally:
            self._stack.__exit__(exc_type, exc_val, exc_tb)

        # Не подавляем исключение — пробрасываем его наружу
        return False


# =====================================================================
# МОДУЛЬНЫЕ ТЕСТЫ
# =====================================================================

class TestMetaclassesAndContext(unittest.TestCase):
    def setUp(self) -> None:
        PluginRegistry.clear_registry()

    def test_validated_meta_success(self) -> None:
        """Корректный класс с docstring и методом execute создается без ошибок."""
        class GoodWorker(BaseService):
            """Рабочий сервис."""

            def execute(self, *args: Any, **kwargs: Any) -> str:
                return "success"

        worker = GoodWorker()
        self.assertEqual(worker.execute(), "success")

    def test_validated_meta_missing_docstring(self) -> None:
        """Отсутствие docstring вызывает TypeError при определении класса."""
        with self.assertRaises(TypeError) as ctx:
            class NoDocWorker(BaseService):
                def execute(self) -> None:
                    pass

        self.assertIn("обязан содержать непустой docstring", str(ctx.exception))

    def test_validated_meta_missing_execute(self) -> None:
        """Отсутствие метода execute вызывает TypeError."""
        with self.assertRaises(TypeError) as ctx:
            class NoExecuteWorker(BaseService):
                """Сервис без execute."""
                pass

        self.assertIn("обязан реализовывать callable-метод 'execute'", str(ctx.exception))

    def test_validated_meta_duplicate_attribute(self) -> None:
        """Повторное объявление атрибута в теле класса вызывает TypeError из __prepare__."""
        with self.assertRaises(TypeError) as ctx:
            class DuplicateAttrWorker(BaseService):
                """Сервис с дубликатом."""
                foo = 1
                foo = 2  # Дубликат!

                def execute(self) -> None:
                    pass

        self.assertIn("Дублирование атрибута", str(ctx.exception))

    def test_plugin_registry_init_subclass(self) -> None:
        """Регистрация плагинов через __init_subclass__."""
        class PaymentPlugin(PluginRegistry, plugin_name="stripe", version=2):
            def execute(self, payload: dict[str, Any]) -> str:
                return f"stripe: {payload}"

        class AuthPlugin(PluginRegistry, plugin_name="jwt", version=1):
            def execute(self, payload: dict[str, Any]) -> str:
                return f"jwt: {payload}"

        self.assertEqual(PluginRegistry.list_plugins(), ["jwt", "stripe"])
        self.assertIs(PluginRegistry.get_plugin("stripe"), PaymentPlugin)
        self.assertEqual(PaymentPlugin.plugin_version, 2)

    def test_plugin_registry_duplicate_name(self) -> None:
        """Повторная регистрация плагина с тем же именем вызывает ValueError."""
        class InitialPlugin(PluginRegistry, plugin_name="crypto"):
            pass

        with self.assertRaises(ValueError) as ctx:
            class DuplicatePlugin(PluginRegistry, plugin_name="crypto"):
                pass

        self.assertIn("уже зарегистрирован", str(ctx.exception))

    def test_transactional_context_success_commit(self) -> None:
        """При успешном commit() действия отката не запускаются."""
        side_effects: List[str] = []

        with TransactionalContext() as tx:
            side_effects.append("create_record")
            tx.add_rollback(lambda: side_effects.remove("create_record"))
            tx.commit()

        # Запись осталась в side_effects
        self.assertEqual(side_effects, ["create_record"])

    def test_transactional_context_rollback_on_exception(self) -> None:
        """При исключении вызываются все откаты в обратном порядке (LIFO)."""
        actions_log: List[str] = []

        with self.assertRaises(RuntimeError):
            with TransactionalContext() as tx:
                actions_log.append("step1")
                tx.add_rollback(lambda: actions_log.append("undo_step1"))

                actions_log.append("step2")
                tx.add_rollback(lambda: actions_log.append("undo_step2"))

                # Сбой до вызова tx.commit()!
                raise RuntimeError("Внезапная ошибка БД!")

        # Проверяем, что откаты вызвались в обратном порядке: undo_step2, затем undo_step1
        self.assertEqual(actions_log, ["step1", "step2", "undo_step2", "undo_step1"])

    def test_transactional_context_rollback_without_commit(self) -> None:
        """Если исключения не было, но commit() не вызван — происходит откат."""
        state = {"balance": 100}

        with TransactionalContext() as tx:
            original = state["balance"]
            state["balance"] += 50
            tx.add_rollback(lambda: state.__setitem__("balance", original))
            # Забыли вызвать tx.commit()!

        # Баланс вернулся к исходному значению
        self.assertEqual(state["balance"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
