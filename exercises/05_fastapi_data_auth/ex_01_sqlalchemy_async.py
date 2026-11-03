#!/usr/bin/env python3
"""Практическое задание к Главе 01: SQLAlchemy 2.0 Async, Сессии и Стратегии загрузки.

Данный модуль содержит эталонную реализацию архитектурных компонентов асинхронной работы с БД:
1. AsyncEngine и AsyncSession с поддержкой транзакций (commit / rollback).
2. Поддержку флага expire_on_commit (поведение по умолчанию в FastAPI vs стандартное).
3. Защиту от неявного lazy loading в асинхронном контексте (MissingAsyncLoadError).
4. Пакетную стратегию предварительной загрузки связанных сущностей (selectinload).
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Callable


class DetachedInstanceError(RuntimeError):
    """Вызывается при обращении к атрибутам выгруженного из сессии объекта."""


class MissingAsyncLoadError(RuntimeError):
    """Вызывается при попытке неявной ленивой загрузки (lazy load) в асинхронном контексте."""


@dataclass
class OrderModel:
    id: int
    user_id: int
    total_amount: float
    description: str


@dataclass
class UserModel:
    id: int
    username: str
    email: str
    is_active: bool = True
    orders: list[OrderModel] = field(default_factory=list)
    _loaded_relations: set[str] = field(default_factory=set)
    _is_expired: bool = False

    def get_orders(self) -> list[OrderModel]:
        if self._is_expired:
            raise DetachedInstanceError(f"Объект User(id={self.id}) протух (expired). Сессия закрыта.")
        if "orders" not in self._loaded_relations:
            raise MissingAsyncLoadError(
                "Неявный lazy loading запрещен в асинхронном режиме! "
                "Используйте стратегию 'selectinload' для загрузки связанных заказов."
            )
        return self.orders


class AsyncConnection:
    """Асинхронная обертка над соединением SQLite."""

    def __init__(self, raw_conn: sqlite3.Connection) -> None:
        self._raw_conn = raw_conn
        self._lock = asyncio.Lock()
        self._is_closed = False

    async def execute(self, query: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        if self._is_closed:
            raise ConnectionError("Соединение закрыто.")
        async with self._lock:
            return await asyncio.to_thread(self._raw_conn.execute, query, params)

    async def commit(self) -> None:
        if self._is_closed:
            raise ConnectionError("Соединение закрыто.")
        async with self._lock:
            await asyncio.to_thread(self._raw_conn.commit)

    async def rollback(self) -> None:
        if self._is_closed:
            raise ConnectionError("Соединение закрыто.")
        async with self._lock:
            await asyncio.to_thread(self._raw_conn.rollback)

    async def close(self) -> None:
        if not self._is_closed:
            self._is_closed = True
            async with self._lock:
                await asyncio.to_thread(self._raw_conn.close)


class AsyncEngine:
    """Асинхронный движок подключения к базе данных с поддержкой пула соединений."""

    def __init__(self, db_path: str | None = None, pool_pre_ping: bool = True) -> None:
        if db_path is None or db_path == ":memory:":
            # Используем разделяемый in-memory URI для устойчивости соединений
            self.db_path = f"file:memdb_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self.is_uri = True
        else:
            self.db_path = db_path
            self.is_uri = False

        self.pool_pre_ping = pool_pre_ping
        self._is_alive = True
        # Держим корневой коннект, чтобы разделяемая in-memory база SQLite не уничтожалась
        self._keepalive_conn = sqlite3.connect(
            self.db_path, uri=self.is_uri, check_same_thread=False
        )

    async def connect(self) -> AsyncConnection:
        if not self._is_alive:
            raise ConnectionError("AsyncEngine остановлен (disposed).")

        raw_conn = sqlite3.connect(
            self.db_path, uri=self.is_uri, check_same_thread=False
        )
        raw_conn.row_factory = sqlite3.Row
        conn = AsyncConnection(raw_conn)

        if self.pool_pre_ping:
            cursor = await conn.execute("SELECT 1")
            row = await asyncio.to_thread(cursor.fetchone)
            if row is None or row[0] != 1:
                await conn.close()
                raise ConnectionError("Проверка pool_pre_ping завершилась ошибкой.")

        return conn

    async def dispose(self) -> None:
        self._is_alive = False
        await asyncio.to_thread(self._keepalive_conn.close)


class AsyncSession:
    """Асинхронная сессия (Identity Map и управление транзакцией)."""

    def __init__(
        self,
        connection: AsyncConnection,
        expire_on_commit: bool = False,
    ) -> None:
        self.connection = connection
        self.expire_on_commit = expire_on_commit
        self._identity_map: dict[type, dict[int, Any]] = {}
        self._new: list[Any] = []
        self._in_transaction = True

    async def __aenter__(self) -> AsyncSession:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            if exc_type is not None:
                await self.rollback()
            else:
                await self.commit()
        finally:
            await self.close()

    def add(self, instance: Any) -> None:
        self._new.append(instance)

    async def commit(self) -> None:
        if not self._in_transaction:
            return
        await self.connection.commit()
        if self.expire_on_commit:
            for entity_dict in self._identity_map.values():
                for entity in entity_dict.values():
                    if hasattr(entity, "_is_expired"):
                        entity._is_expired = True

    async def rollback(self) -> None:
        if not self._in_transaction:
            return
        await self.connection.rollback()
        self._new.clear()
        self._identity_map.clear()

    async def close(self) -> None:
        if self._in_transaction:
            self._in_transaction = False
            await self.connection.close()

    async def get_user_with_strategy(
        self,
        user_id: int,
        strategy: str | None = None,
    ) -> UserModel | None:
        """Получение пользователя с поддержкой стратегий загрузки."""
        cursor = await self.connection.execute(
            "SELECT id, username, email, is_active FROM users WHERE id = ?",
            (user_id,),
        )
        row = await asyncio.to_thread(cursor.fetchone)
        if row is None:
            return None

        user = UserModel(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            is_active=bool(row["is_active"]),
        )

        if strategy == "selectinload":
            # Выполняем второй независимый запрос для связанных заказов
            order_cursor = await self.connection.execute(
                "SELECT id, user_id, total_amount, description FROM orders WHERE user_id = ?",
                (user_id,),
            )
            order_rows = await asyncio.to_thread(order_cursor.fetchall)
            user.orders = [
                OrderModel(
                    id=o["id"],
                    user_id=o["user_id"],
                    total_amount=o["total_amount"],
                    description=o["description"],
                )
                for o in order_rows
            ]
            user._loaded_relations.add("orders")

        # Сохранение в identity map
        user_map = self._identity_map.setdefault(UserModel, {})
        user_map[user.id] = user
        return user


def async_sessionmaker(
    engine: AsyncEngine,
    expire_on_commit: bool = False,
) -> Callable[[], Any]:
    """Фабрика сессий, возвращающая объект сессии."""

    async def create_session() -> AsyncSession:
        conn = await engine.connect()
        return AsyncSession(conn, expire_on_commit=expire_on_commit)

    return create_session


# ---------------------------------------------------------------------------
# Модульные тесты
# ---------------------------------------------------------------------------
import unittest


class TestAsyncSQLAlchemyCore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = AsyncEngine(pool_pre_ping=True)
        # Инициализируем схему таблиц
        conn = await self.engine.connect()
        await conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            );
            """
        )
        await conn.execute(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                total_amount REAL NOT NULL,
                description TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
        )
        # Наполняем тестовыми данными
        await conn.execute(
            "INSERT INTO users (id, username, email) VALUES (1, 'alice', 'alice@example.com')"
        )
        await conn.execute(
            "INSERT INTO orders (id, user_id, total_amount, description) VALUES (101, 1, 1500.0, 'Заказ 1')"
        )
        await conn.execute(
            "INSERT INTO orders (id, user_id, total_amount, description) VALUES (102, 1, 350.5, 'Заказ 2')"
        )
        await conn.commit()
        await conn.close()

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_session_fetch_user_without_preloading(self) -> None:
        """Проверка получения пользователя без связей."""
        conn = await self.engine.connect()
        session = AsyncSession(conn, expire_on_commit=False)
        user = await session.get_user_with_strategy(1)
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "alice")
        await session.close()

    async def test_missing_async_lazy_load_raises_error(self) -> None:
        """Попытка неявного чтения связей в асинхронном режиме должна приводить к ошибке."""
        conn = await self.engine.connect()
        session = AsyncSession(conn, expire_on_commit=False)
        user = await session.get_user_with_strategy(1)
        self.assertIsNotNone(user)

        with self.assertRaises(MissingAsyncLoadError) as ctx:
            user.get_orders()

        self.assertIn("selectinload", str(ctx.exception))
        await session.close()

    async def test_selectinload_preloads_relationships_successfully(self) -> None:
        """Стратегия selectinload предзагружает связанные заказы."""
        conn = await self.engine.connect()
        session = AsyncSession(conn, expire_on_commit=False)
        user = await session.get_user_with_strategy(1, strategy="selectinload")
        self.assertIsNotNone(user)

        orders = user.get_orders()
        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0].id, 101)
        self.assertEqual(orders[1].total_amount, 350.5)
        await session.close()

    async def test_expire_on_commit_behavior(self) -> None:
        """При expire_on_commit=True объекты протухают после коммита."""
        conn = await self.engine.connect()
        session = AsyncSession(conn, expire_on_commit=True)
        user = await session.get_user_with_strategy(1, strategy="selectinload")
        await session.commit()

        # При попытке чтения из expired объекта должно выбрасываться DetachedInstanceError
        with self.assertRaises(DetachedInstanceError):
            user.get_orders()
        await session.close()

    async def test_expire_on_commit_false_keeps_attributes(self) -> None:
        """При expire_on_commit=False (стандарт FastAPI) атрибуты остаются доступными после коммита."""
        conn = await self.engine.connect()
        session = AsyncSession(conn, expire_on_commit=False)
        user = await session.get_user_with_strategy(1, strategy="selectinload")
        await session.commit()

        # Данные доступны для Pydantic/FastAPI
        orders = user.get_orders()
        self.assertEqual(len(orders), 2)
        await session.close()

    async def test_sessionmaker_context_manager_commits(self) -> None:
        """Проверка контекстного менеджера сессии и автокоммита."""
        session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        session = await session_factory()

        async with session:
            await session.connection.execute(
                "INSERT INTO users (id, username, email) VALUES (2, 'bob', 'bob@example.com')"
            )

        # Проверяем, что запись зафиксирована
        check_conn = await self.engine.connect()
        cursor = await check_conn.execute("SELECT username FROM users WHERE id = 2")
        row = await asyncio.to_thread(cursor.fetchone)
        self.assertIsNotNone(row)
        self.assertEqual(row["username"], "bob")
        await check_conn.close()


if __name__ == "__main__":
    unittest.main()
