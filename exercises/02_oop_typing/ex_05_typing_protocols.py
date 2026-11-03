#!/usr/bin/env python3
"""Практическое задание 05: Продвинутая типизация: Generics, Protocol, TypeVar, Annotated.

Инструкция по запуску:
    python3 exercises/02_oop_typing/ex_05_typing_protocols.py

Цели задания:
    1. Освоить статическую утиную типизацию через typing.Protocol и @runtime_checkable.
    2. Реализовать обобщенный стек элементов (Generic Stack[T]).
    3. Применить TypedDict и Literal для структурирования входных DTO.
    4. Исследовать метаданные Annotated (основа Depends и Query в FastAPI).
    5. Создать предикат сужения типов TypeGuard.
    6. Написать строго типизированный декоратор с ParamSpec, сохраняющий точную сигнатуру.
"""

from __future__ import annotations

from collections.abc import Callable
import functools
from typing import (
    Annotated,
    Any,
    Literal,
    Protocol,
    TypeGuard,
    TypedDict,
    get_args,
    get_origin,
    runtime_checkable,
)


# ============================================================================
# ЗАДАНИЕ 1: Структурная типизация через Protocol
# ============================================================================

@runtime_checkable
class Serializable(Protocol):
    """Протокол сериализуемого объекта."""

    def serialize(self) -> dict[str, Any]:
        """Возвращает словарное представление объекта."""
        ...


class Article:
    """Класс статьи, реализующий протокол Serializable БЕЗ явного наследования."""

    def __init__(self, title: str, author: str, views: int = 0) -> None:
        self.title = title
        self.author = author
        self.views = views

    def serialize(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "author": self.author,
            "views": self.views,
        }


# ============================================================================
# ЗАДАНИЕ 2: Обобщенный Generic Stack[T] (PEP 695)
# ============================================================================

class Stack[T]:
    """Обобщенная структура данных LIFO (Стек)."""

    def __init__(self) -> None:
        self._items: list[T] = []

    def push(self, item: T) -> None:
        """Добавить элемент на вершину стека."""
        self._items.append(item)

    def pop(self) -> T:
        """Извлечь верхний элемент. Выбрасывает IndexError, если стек пуст."""
        if not self._items:
            raise IndexError("Попытка извлечь элемент из пустого стека")
        return self._items.pop()

    def peek(self) -> T | None:
        """Посмотреть на верхний элемент без удаления."""
        return self._items[-1] if self._items else None

    def is_empty(self) -> bool:
        """Проверить, пуст ли стек."""
        return len(self._items) == 0

    def __len__(self) -> int:
        return len(self._items)


# ============================================================================
# ЗАДАНИЕ 3: TypedDict и Literal
# ============================================================================

SortOrder = Literal["asc", "desc"]


class PaginationQuery(TypedDict, total=False):
    """Типизированный словарь параметров пагинации и сортировки."""

    page: int
    per_page: int
    sort_by: str
    order: SortOrder


# ============================================================================
# ЗАДАНИЕ 4: Метаданные типов Annotated
# ============================================================================

# Определение типа с валидационными метаданными
QueryLimit = Annotated[int, "ge=1", "le=100"]


def extract_annotated_metadata(annotation: Any) -> tuple[Any, tuple[Any, ...]]:
    """Извлекает базовый тип и кортеж метаданных из Annotated."""
    origin = get_origin(annotation)
    if origin is not Annotated:
        raise TypeError(f"{annotation} не является типом Annotated!")

    args = get_args(annotation)
    base_type = args[0]
    metadata = args[1:]
    return base_type, metadata


# ============================================================================
# ЗАДАНИЕ 5: Предикат сужения типов TypeGuard
# ============================================================================

def is_string_list(items: list[Any]) -> TypeGuard[list[str]]:
    """Проверяет, что переданный список состоит строго из строк."""
    return isinstance(items, list) and all(isinstance(x, str) for x in items)


# ============================================================================
# ЗАДАНИЕ 6: Типобезопасный декоратор с ParamSpec (PEP 612 / PEP 695)
# ============================================================================

def audit_tracer[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Декоратор, отслеживающий количество вызовов и сохраняющий точную сигнатуру."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        wrapper.call_count += 1  # type: ignore[attr-defined]
        return func(*args, **kwargs)

    wrapper.call_count = 0  # type: ignore[attr-defined]
    return wrapper


# ============================================================================
# МОДУЛЬНЫЕ ТЕСТЫ (unittest)
# ============================================================================

import unittest


class TestTypingProtocolsGenerics(unittest.TestCase):
    """Набор тестов для проверки Protocol, Generics, Annotated, TypeGuard и ParamSpec."""

    def test_protocol_structural_typing(self) -> None:
        """Проверяем, что Article удовлетворяет протоколу Serializable без явного наследования."""
        art = Article(title="Python Typing", author="Guido", views=100)
        self.assertTrue(isinstance(art, Serializable))

        # Объект без serialize() НЕ удовлетворяет протоколу
        class Dummy:
            pass

        self.assertFalse(isinstance(Dummy(), Serializable))

        # Проверяем работу самого метода serialize
        payload = art.serialize()
        self.assertEqual(payload["title"], "Python Typing")
        self.assertEqual(payload["views"], 100)

    def test_generic_stack(self) -> None:
        """Проверяем работу обобщенного стека Stack[T]."""
        stack: Stack[int] = Stack()
        self.assertTrue(stack.is_empty())
        self.assertEqual(len(stack), 0)
        self.assertIsNone(stack.peek())

        stack.push(10)
        stack.push(20)
        self.assertEqual(len(stack), 2)
        self.assertEqual(stack.peek(), 20)

        self.assertEqual(stack.pop(), 20)
        self.assertEqual(stack.pop(), 10)
        self.assertTrue(stack.is_empty())

        with self.assertRaises(IndexError):
            stack.pop()

    def test_typed_dict(self) -> None:
        """Проверяем создание и манипуляции с TypedDict."""
        query: PaginationQuery = {
            "page": 1,
            "per_page": 25,
            "sort_by": "created_at",
            "order": "desc",
        }
        self.assertEqual(query["page"], 1)
        self.assertEqual(query["order"], "desc")

    def test_annotated_metadata_extraction(self) -> None:
        """Проверяем извлечение метаданных из типа Annotated."""
        base_type, metadata = extract_annotated_metadata(QueryLimit)
        self.assertIs(base_type, int)
        self.assertEqual(metadata, ("ge=1", "le=100"))

        with self.assertRaises(TypeError):
            extract_annotated_metadata(int)

    def test_type_guard(self) -> None:
        """Проверяем предикат сужения типа is_string_list."""
        self.assertTrue(is_string_list(["a", "b", "c"]))
        self.assertTrue(is_string_list([]))
        self.assertFalse(is_string_list(["a", 1, "c"]))
        self.assertFalse(is_string_list([None]))  # type: ignore[list-item]

    def test_paramspec_decorator_preserves_behavior(self) -> None:
        """Проверяем, что audit_tracer корректно считает вызовы и не ломает результат."""
        @audit_tracer
        def multiply(x: int, factor: int = 2) -> int:
            return x * factor

        self.assertEqual(multiply(5), 10)
        self.assertEqual(multiply(5, factor=3), 15)
        self.assertEqual(multiply.call_count, 2)  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main(verbosity=2)
