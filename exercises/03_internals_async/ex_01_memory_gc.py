#!/usr/bin/env python3
"""Упражнение 01: Модель памяти CPython, подсчет ссылок, GC и Weakref.

Тема: Внутреннее устройство PyObject, sys.getrefcount, обнаружение циклов gc,
слабые ссылки через weakref.WeakValueDictionary.

Запуск тестов:
    python3 exercises/03_internals_async/ex_01_memory_gc.py
    или из корня:
    python3 run_all_tests.py
"""

from __future__ import annotations

import gc
import sys
import unittest
import weakref
from dataclasses import dataclass
from typing import Any, Generic, Optional, TypeVar

K = TypeVar("K")
V = TypeVar("V", bound=object)


# =====================================================================
# ЗАДАНИЕ 1: Интроспекция PyObject
# =====================================================================

@dataclass(frozen=True)
class PyObjectInfo:
    """Метаданные объекта на уровне интерпретатора CPython."""
    type_name: str
    refcount: int
    size_bytes: int
    is_gc_tracked: bool
    referents_count: int


def inspect_pyobject(obj: Any) -> PyObjectInfo:
    """Анализирует объект CPython.

    Вычисляет:
    - type_name: имя типа объекта (obj.__class__.__name__)
    - refcount: реальное число ссылок на объект (с поправкой на временную
      ссылку внутри sys.getrefcount)
    - size_bytes: размер объекта в байтах через sys.getsizeof
    - is_gc_tracked: отслеживается ли объект циклическим сборщиком мусора
    - referents_count: количество объектов, на которые непосредственно ссылается данный
    """
    # sys.getrefcount(obj) создает 1 временную ссылку при передаче аргумента
    raw_refs = sys.getrefcount(obj)
    # Корректируем на 1 для получения чистого числа ссылок во внешнем контексте
    clean_refcount = max(1, raw_refs - 1)

    return PyObjectInfo(
        type_name=type(obj).__name__,
        refcount=clean_refcount,
        size_bytes=sys.getsizeof(obj),
        is_gc_tracked=gc.is_tracked(obj),
        referents_count=len(gc.get_referents(obj)),
    )


# =====================================================================
# ЗАДАНИЕ 2: Управление циклическими ссылками
# =====================================================================

class CycleNode:
    """Узел двусвязного графа для моделирования циклических ссылок."""

    def __init__(self, name: str) -> None:
        self.name: str = name
        self.peer: Optional[CycleNode] = None

    def link(self, other: CycleNode) -> None:
        self.peer = other
        other.peer = self

    def unlink(self) -> None:
        if self.peer is not None:
            self.peer.peer = None
            self.peer = None


class RefCycleDetector:
    """Утилита для обнаружения и разрыва циклических ссылок."""

    @staticmethod
    def create_isolated_cycle(name_a: str = "A", name_b: str = "B") -> None:
        """Создает два взаимно связанных объекта и удаляет ссылки на них из стека.

        Объекты остаются в памяти только из-за взаимного цикла!
        """
        node_a = CycleNode(name_a)
        node_b = CycleNode(name_b)
        node_a.link(node_b)
        # При выходе из функции локальные node_a и node_b уничтожаются,
        # но взаимные ссылки удерживают объекты в поколении GC 0.

    @staticmethod
    def force_collect() -> int:
        """Принудительно запускает полный сборщик мусора во всех 3 поколениях."""
        return gc.collect()


# =====================================================================
# ЗАДАНИЕ 3: Потокобезопасный WeakCache на WeakValueDictionary
# =====================================================================

class WeakCache(Generic[K, V]):
    """Кэш со слабыми ссылками на значения.

    Если на объект значения V не остается сильных внешних ссылок,
    он автоматически деаллоцируется и исчезает из кэша.
    """

    def __init__(self) -> None:
        self._data: weakref.WeakValueDictionary[K, V] = weakref.WeakValueDictionary()
        self._hits: int = 0
        self._misses: int = 0
        self._total_sets: int = 0

    def set(self, key: K, value: V) -> None:
        """Сохраняет значение по ключу."""
        self._data[key] = value
        self._total_sets += 1

    def get(self, key: K) -> Optional[V]:
        """Возвращает значение или None при промахе/исчезновении объекта."""
        val = self._data.get(key)
        if val is not None:
            self._hits += 1
            return val
        self._misses += 1
        return None

    def contains(self, key: K) -> bool:
        """Проверяет наличие активного ключа в кэше."""
        return key in self._data

    def __len__(self) -> int:
        """Возвращает текущее количество живых объектов в кэше."""
        return len(self._data)

    @property
    def stats(self) -> dict[str, int]:
        """Статистика попаданий и промахов."""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_sets": self._total_sets,
            "active_items": len(self._data),
        }


# =====================================================================
# МОДУЛЬНЫЕ ТЕСТЫ
# =====================================================================

class TestMemoryAndGC(unittest.TestCase):
    def test_inspect_pyobject_scalar(self) -> None:
        """Проверка интроспекции простых скалярных объектов."""
        num = 123456789
        info = inspect_pyobject(num)
        self.assertEqual(info.type_name, "int")
        self.assertGreater(info.size_bytes, 0)
        # Скалярные int не отслеживаются циклическим GC
        self.assertFalse(info.is_gc_tracked)

    def test_inspect_pyobject_container(self) -> None:
        """Проверка интроспекции составных объектов-контейнеров."""
        sub_obj = {"nested": 1}
        container = [sub_obj, sub_obj]
        info = inspect_pyobject(container)

        self.assertEqual(info.type_name, "list")
        self.assertTrue(info.is_gc_tracked)
        # Список ссылается на свои элементы
        self.assertGreaterEqual(info.referents_count, 1)

    def test_cycle_creation_and_collection(self) -> None:
        """Проверка обнаружения и сборки циклических ссылок через GC."""
        # Убедимся, что сборщик включен
        gc.enable()
        # Чистим перед тестом
        gc.collect()

        # Создаем изолированный цикл, который не может быть освобожден refcnt
        RefCycleDetector.create_isolated_cycle("Alpha", "Beta")

        # Принудительная сборка должна найти и уничтожить циклы
        unreachable = RefCycleDetector.force_collect()
        self.assertGreaterEqual(unreachable, 2)

    def test_manual_cycle_break(self) -> None:
        """Проверка ручного разрыва циклов без участия GC."""
        node1 = CycleNode("One")
        node2 = CycleNode("Two")
        node1.link(node2)

        self.assertIs(node1.peer, node2)
        self.assertIs(node2.peer, node1)

        # Ручной разрыв цикла
        node1.unlink()
        self.assertIsNone(node1.peer)
        self.assertIsNone(node2.peer)

    def test_weak_cache_lifecycle(self) -> None:
        """Проверка автоматической очистки кэша при уничтожении сильных ссылок."""
        class Session:
            def __init__(self, user: str) -> None:
                self.user = user

        cache: WeakCache[str, Session] = WeakCache()

        sess1: Optional[Session] = Session("Alice")
        sess2: Optional[Session] = Session("Bob")

        cache.set("alice", sess1)
        cache.set("bob", sess2)

        self.assertEqual(len(cache), 2)
        self.assertTrue(cache.contains("alice"))

        # Проверка попадания в кэш (Hit)
        val = cache.get("alice")
        self.assertIsNotNone(val)
        self.assertEqual(val.user, "Alice")
        self.assertEqual(cache.stats["hits"], 1)

        # Удаляем обе сильные ссылки (sess1 и локальную val)
        del val
        del sess1

        # Объект должен автоматически исчезнуть из кэша!
        self.assertFalse(cache.contains("alice"))
        self.assertIsNone(cache.get("alice"))
        self.assertEqual(cache.stats["misses"], 1)
        self.assertEqual(len(cache), 1)

        # sess2 все еще жив
        self.assertTrue(cache.contains("bob"))
        del sess2
        self.assertEqual(len(cache), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
