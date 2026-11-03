#!/usr/bin/env python3
"""Практическое задание к Главе 02: Миграции Alembic, Паттерны Repository и Unit of Work.

Данный модуль содержит эталонную реализацию корпоративных паттернов:
1. Generic AbstractRepository и асинхронный SQLiteRepository.
2. Unit of Work (UoW) с контекстным менеджером и автоматическим откатом при ошибках.
3. Keyset (Cursor-based) пагинация по составному ключу (created_at, id).
4. Оптимистичная блокировка с проверкой версии сущности (OptimisticLockError).
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
import sqlite3
from types import TracebackType
from typing import Any, Generic, Self, TypeVar
import uuid


class OptimisticLockError(RuntimeError):
    """Вызывается при обнаружении конфликта конкурентного обновления версии."""


@dataclass
class AccountModel:
    id: int
    owner: str
    balance: float
    version: int = 1
    created_at: int = 0  # Unix timestamp в секундах


T = TypeVar("T")
ID = TypeVar("ID")


class AbstractRepository(ABC, Generic[T, ID]):
    """Абстрактный интерфейс паттерна Репозиторий."""

    @abstractmethod
    async def get_by_id(self, entity_id: ID) -> T | None:
        raise NotImplementedError

    @abstractmethod
    async def add(self, entity: T) -> T:
        raise NotImplementedError

    @abstractmethod
    async def update_with_optimistic_lock(self, entity: T) -> T:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, entity_id: ID) -> bool:
        raise NotImplementedError


class SQLiteAccountRepository(AbstractRepository[AccountModel, int]):
    """Конкретная реализация репозитория для сущности Account."""

    def __init__(self, raw_conn: sqlite3.Connection, lock: asyncio.Lock) -> None:
        self.conn = raw_conn
        self.lock = lock

    async def get_by_id(self, entity_id: int) -> AccountModel | None:
        async with self.lock:
            cursor = await asyncio.to_thread(
                self.conn.execute,
                "SELECT id, owner, balance, version, created_at FROM accounts WHERE id = ?",
                (entity_id,),
            )
            row = await asyncio.to_thread(cursor.fetchone)
            if row is None:
                return None
            return AccountModel(
                id=row["id"],
                owner=row["owner"],
                balance=row["balance"],
                version=row["version"],
                created_at=row["created_at"],
            )

    async def add(self, entity: AccountModel) -> AccountModel:
        async with self.lock:
            cursor = await asyncio.to_thread(
                self.conn.execute,
                """
                INSERT INTO accounts (id, owner, balance, version, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    entity.id,
                    entity.owner,
                    entity.balance,
                    entity.version,
                    entity.created_at,
                ),
            )
            if entity.id is None:
                entity.id = cursor.lastrowid or 0
            return entity

    async def update_with_optimistic_lock(self, entity: AccountModel) -> AccountModel:
        """Обновление записи с проверкой версии (Optimistic Locking)."""
        async with self.lock:
            new_version = entity.version + 1
            cursor = await asyncio.to_thread(
                self.conn.execute,
                """
                UPDATE accounts
                SET owner = ?, balance = ?, version = ?
                WHERE id = ? AND version = ?
                """,
                (
                    entity.owner,
                    entity.balance,
                    new_version,
                    entity.id,
                    entity.version,
                ),
            )
            rows_affected = cursor.rowcount
            if rows_affected == 0:
                raise OptimisticLockError(
                    f"Конфликт версий для Account(id={entity.id})! "
                    f"Ожидалась версия {entity.version}, но запись была изменена параллельной транзакцией."
                )
            entity.version = new_version
            return entity

    async def delete(self, entity_id: int) -> bool:
        async with self.lock:
            cursor = await asyncio.to_thread(
                self.conn.execute,
                "DELETE FROM accounts WHERE id = ?",
                (entity_id,),
            )
            return cursor.rowcount > 0

    async def get_keyset_page(
        self,
        limit: int = 10,
        after_created_at: int | None = None,
        after_id: int | None = None,
    ) -> list[AccountModel]:
        """Keyset / Cursor-based пагинация по составному индексу (created_at DESC, id DESC)."""
        async with self.lock:
            if after_created_at is not None and after_id is not None:
                query = """
                    SELECT id, owner, balance, version, created_at
                    FROM accounts
                    WHERE (created_at < ?) OR (created_at = ? AND id < ?)
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                """
                params = (after_created_at, after_created_at, after_id, limit)
            else:
                query = """
                    SELECT id, owner, balance, version, created_at
                    FROM accounts
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                """
                params = (limit,)

            cursor = await asyncio.to_thread(self.conn.execute, query, params)
            rows = await asyncio.to_thread(cursor.fetchall)
            return [
                AccountModel(
                    id=r["id"],
                    owner=r["owner"],
                    balance=r["balance"],
                    version=r["version"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]


class AbstractUnitOfWork(ABC):
    """Интерфейс паттерна Unit of Work."""

    accounts: AbstractRepository[AccountModel, int]

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()

    @abstractmethod
    async def commit(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def rollback(self) -> None:
        raise NotImplementedError


class SQLiteUnitOfWork(AbstractUnitOfWork):
    """Асинхронная реализация Unit of Work для SQLite."""

    def __init__(self, db_uri: str, lock: asyncio.Lock) -> None:
        self.db_uri = db_uri
        self.lock = lock
        self.conn: sqlite3.Connection | None = None

    async def __aenter__(self) -> Self:
        self.conn = sqlite3.connect(self.db_uri, uri=True, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.accounts = SQLiteAccountRepository(self.conn, self.lock)
        return await super().__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            await super().__aexit__(exc_type, exc_val, exc_tb)
        finally:
            if self.conn is not None:
                async with self.lock:
                    await asyncio.to_thread(self.conn.close)
                self.conn = None

    async def commit(self) -> None:
        if self.conn is not None:
            async with self.lock:
                await asyncio.to_thread(self.conn.commit)

    async def rollback(self) -> None:
        if self.conn is not None:
            async with self.lock:
                await asyncio.to_thread(self.conn.rollback)


# ---------------------------------------------------------------------------
# Модульные тесты
# ---------------------------------------------------------------------------
import unittest


class TestRepositoriesAndUnitOfWork(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db_uri = f"file:uow_test_{uuid.uuid4().hex}?mode=memory&cache=shared"
        self.lock = asyncio.Lock()

        # Создаем постоянный коннект для сохранения shared in-memory DB
        self.keepalive = sqlite3.connect(self.db_uri, uri=True, check_same_thread=False)
        self.keepalive.execute(
            """
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY,
                owner TEXT NOT NULL,
                balance REAL NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            );
            """
        )
        self.keepalive.commit()

    async def asyncTearDown(self) -> None:
        self.keepalive.close()

    async def test_uow_atomic_success_transaction(self) -> None:
        """Успешная атомарная транзакция перевода средств между счетами."""
        # Начальные данные
        uow = SQLiteUnitOfWork(self.db_uri, self.lock)
        async with uow:
            await uow.accounts.add(AccountModel(id=1, owner="Alice", balance=1000.0, created_at=100))
            await uow.accounts.add(AccountModel(id=2, owner="Bob", balance=500.0, created_at=105))

        # Перевод средств
        async with SQLiteUnitOfWork(self.db_uri, self.lock) as tx:
            acc1 = await tx.accounts.get_by_id(1)
            acc2 = await tx.accounts.get_by_id(2)
            self.assertIsNotNone(acc1)
            self.assertIsNotNone(acc2)

            acc1.balance -= 300.0
            acc2.balance += 300.0

            await tx.accounts.update_with_optimistic_lock(acc1)
            await tx.accounts.update_with_optimistic_lock(acc2)

        # Проверка балансов
        async with SQLiteUnitOfWork(self.db_uri, self.lock) as verify_tx:
            acc1_after = await verify_tx.accounts.get_by_id(1)
            acc2_after = await verify_tx.accounts.get_by_id(2)
            self.assertEqual(acc1_after.balance, 700.0)
            self.assertEqual(acc2_after.balance, 800.0)
            self.assertEqual(acc1_after.version, 2)
            self.assertEqual(acc2_after.version, 2)

    async def test_uow_auto_rollback_on_exception(self) -> None:
        """Автоматический откат изменений при возникновении ошибки внутри UoW."""
        # Создаем счет
        async with SQLiteUnitOfWork(self.db_uri, self.lock) as uow:
            await uow.accounts.add(AccountModel(id=10, owner="Charlie", balance=500.0, created_at=100))

        # Попытка операции с аварийным исключением
        with self.assertRaises(ValueError):
            async with SQLiteUnitOfWork(self.db_uri, self.lock) as failing_tx:
                acc = await failing_tx.accounts.get_by_id(10)
                acc.balance += 1000.0
                await failing_tx.accounts.update_with_optimistic_lock(acc)
                raise ValueError("Неожиданный сбой в середине бизнес-логики!")

        # Баланс и версия не должны были измениться
        async with SQLiteUnitOfWork(self.db_uri, self.lock) as verify_tx:
            acc = await verify_tx.accounts.get_by_id(10)
            self.assertEqual(acc.balance, 500.0)
            self.assertEqual(acc.version, 1)

    async def test_optimistic_locking_conflict_detection(self) -> None:
        """Обнаружение конкурентной гонки через версионирование (OptimisticLockError)."""
        async with SQLiteUnitOfWork(self.db_uri, self.lock) as uow:
            await uow.accounts.add(AccountModel(id=20, owner="David", balance=200.0, version=1, created_at=100))

        # Транзакция 1 и Транзакция 2 читают одну и ту же версию записи (v1)
        async with SQLiteUnitOfWork(self.db_uri, self.lock) as tx1:
            tx1_model = await tx1.accounts.get_by_id(20)

        async with SQLiteUnitOfWork(self.db_uri, self.lock) as tx2:
            tx2_model = await tx2.accounts.get_by_id(20)

        # Транзакция 1 успешно обновляет запись (версия становится v2)
        async with SQLiteUnitOfWork(self.db_uri, self.lock) as tx1_write:
            tx1_model.balance += 50.0
            await tx1_write.accounts.update_with_optimistic_lock(tx1_model)

        # Транзакция 2 пытается обновить устаревшую версию v1 -> должна получить OptimisticLockError
        with self.assertRaises(OptimisticLockError):
            async with SQLiteUnitOfWork(self.db_uri, self.lock) as tx2_write:
                tx2_model.balance += 100.0
                await tx2_write.accounts.update_with_optimistic_lock(tx2_model)

    async def test_keyset_cursor_pagination(self) -> None:
        """Проверка Keyset/Cursor пагинации без пропусков и дубликатов."""
        async with SQLiteUnitOfWork(self.db_uri, self.lock) as uow:
            for i in range(1, 11):
                await uow.accounts.add(
                    AccountModel(id=i, owner=f"User_{i}", balance=float(i * 10), created_at=1000 + i)
                )

        async with SQLiteUnitOfWork(self.db_uri, self.lock) as uow:
            repo: SQLiteAccountRepository = uow.accounts  # type: ignore

            # Страница 1: первые 4 элемента (самые свежие)
            page_1 = await repo.get_keyset_page(limit=4)
            self.assertEqual(len(page_1), 4)
            self.assertEqual([a.id for a in page_1], [10, 9, 8, 7])

            # Страница 2: следующие 4 элемента по курсору последнего элемента страницы 1
            last_item = page_1[-1]
            page_2 = await repo.get_keyset_page(
                limit=4,
                after_created_at=last_item.created_at,
                after_id=last_item.id,
            )
            self.assertEqual(len(page_2), 4)
            self.assertEqual([a.id for a in page_2], [6, 5, 4, 3])

            # Страница 3: оставшиеся 2 элемента
            last_item_2 = page_2[-1]
            page_3 = await repo.get_keyset_page(
                limit=4,
                after_created_at=last_item_2.created_at,
                after_id=last_item_2.id,
            )
            self.assertEqual(len(page_3), 2)
            self.assertEqual([a.id for a in page_3], [2, 1])


if __name__ == "__main__":
    unittest.main()
