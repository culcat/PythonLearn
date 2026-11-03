#!/usr/bin/env python3
"""Упражнение 02: Асинхронное тестирование, транзакционная изоляция БД и моки.

В этом задании реализуются ключевые инструменты для тестирования асинхронных сервисов:
1. AsyncDatabaseConnection с поддержкой SAVEPOINT (вложенных транзакций)
2. TransactionalTestSession: контекстный менеджер для мгновенного отката состояния БД после теста
3. AsyncMockHttpClient: эмулятор HTTP-клиента (respx / httpx.AsyncClient)
4. DependencyContainer: контейнер зависимостей с поддержкой dependency_overrides
5. Комплексные асинхронные тесты на базе unittest.IsolatedAsyncioTestCase
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar
import unittest


# ============================================================================
# 1. АСИНХРОННАЯ БАЗА ДАННЫХ С ПОДДЕРЖКОЙ SAVEPOINT
# ============================================================================

class AsyncDatabaseConnection:
    """Имитация асинхронного соединения с реляционной базой данных.
    
    Поддерживает транзакции и точки сохранения (SAVEPOINT) через стек снимков состояния.
    """

    def __init__(self) -> None:
        self._storage: dict[str, str] = {}
        self._savepoints: dict[str, dict[str, str]] = {}
        self._in_transaction: bool = False

    async def begin(self) -> None:
        self._in_transaction = True
        self._savepoints["__root__"] = dict(self._storage)

    async def commit(self) -> None:
        self._savepoints.clear()
        self._in_transaction = False

    async def rollback(self) -> None:
        if "__root__" in self._savepoints:
            self._storage = dict(self._savepoints["__root__"])
        self._savepoints.clear()
        self._in_transaction = False

    async def create_savepoint(self, name: str) -> None:
        """Создает точку сохранения (SAVEPOINT) с текущим снимком данных."""
        self._savepoints[name] = dict(self._storage)

    async def rollback_to_savepoint(self, name: str) -> None:
        """Откатывает состояние хранилища к указанной точке сохранения."""
        if name not in self._savepoints:
            raise ValueError(f"Точка сохранения '{name}' не найдена")
        self._storage = dict(self._savepoints[name])
        # Точки сохранения, созданные после данной, удаляются
        del self._savepoints[name]

    async def set_value(self, key: str, value: str) -> None:
        self._storage[key] = value

    async def get_value(self, key: str) -> str | None:
        return self._storage.get(key)


class TransactionalTestSession:
    """Асинхронный контекстный менеджер изоляции теста.
    
    Перед тестом создает SAVEPOINT, а при завершении (независимо от успеха
    или исключения) производит откат к SAVEPOINT, сохраняя исходную БД чистой.
    """

    def __init__(self, connection: AsyncDatabaseConnection, savepoint_name: str = "test_sp") -> None:
        self._connection = connection
        self._savepoint_name = savepoint_name

    async def __aenter__(self) -> TransactionalTestSession:
        await self._connection.create_savepoint(self._savepoint_name)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self._connection.rollback_to_savepoint(self._savepoint_name)


# ============================================================================
# 2. ЭМУЛЯТОР АСИНХРОННОГО HTTP-КЛИЕНТА (RESPX / HTTPX)
# ============================================================================

@dataclass(frozen=True, slots=True)
class MockResponse:
    status_code: int
    data: dict[str, object]

    def json(self) -> dict[str, object]:
        return self.data


@dataclass
class RecordedRequest:
    method: str
    url: str


class AsyncMockHttpClient:
    """Эмулятор httpx.AsyncClient с поддержкой перехвата маршрутов в стиле respx."""

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], MockResponse] = {}
        self.recorded_requests: list[RecordedRequest] = []

    def add_route(self, method: str, url: str, status_code: int, json_data: dict[str, object]) -> None:
        self._routes[(method.upper(), url)] = MockResponse(status_code=status_code, data=json_data)

    async def get(self, url: str) -> MockResponse:
        return await self._dispatch("GET", url)

    async def post(self, url: str) -> MockResponse:
        return await self._dispatch("POST", url)

    async def _dispatch(self, method: str, url: str) -> MockResponse:
        req_key = (method.upper(), url)
        self.recorded_requests.append(RecordedRequest(method=method.upper(), url=url))

        if req_key not in self._routes:
            raise ConnectionError(f"Не зарегистрирован мок для запроса: {method} {url}")

        return self._routes[req_key]

    @property
    def call_count(self) -> int:
        return len(self.recorded_requests)


# ============================================================================
# 3. КОНТЕЙНЕР ЗАВИСИМОСТЕЙ С ПОДДЕРЖКОЙ DEPENDENCY_OVERRIDES
# ============================================================================

T = TypeVar("T")


class DependencyContainer:
    """Контейнер зависимостей, эмулирующий FastAPI.dependency_overrides."""

    def __init__(self) -> None:
        self._providers: dict[type, Any] = {}
        self.dependency_overrides: dict[type, Any] = {}

    def register(self, dependency_type: type[T], provider: Any) -> None:
        self._providers[dependency_type] = provider

    def resolve(self, dependency_type: type[T]) -> T:
        # Приоритет отдается переопределениям для тестов
        if dependency_type in self.dependency_overrides:
            candidate = self.dependency_overrides[dependency_type]
            return candidate() if callable(candidate) and not isinstance(candidate, type) else candidate

        if dependency_type in self._providers:
            candidate = self._providers[dependency_type]
            return candidate() if callable(candidate) and not isinstance(candidate, type) else candidate

        raise LookupError(f"Зависимость {dependency_type.__name__} не зарегистрирована")

    def clear_overrides(self) -> None:
        self.dependency_overrides.clear()


# ============================================================================
# 4. ТЕСТЫ НА BAZЕ UNITTEST
# ============================================================================

class TestTransactionalIsolation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = AsyncDatabaseConnection()
        await self.db.begin()
        # Базовые данные, существующие до тестов
        await self.db.set_value("user:1", "Alice")
        await self.db.set_value("user:2", "Bob")

    async def test_savepoint_rollback_cleans_test_modifications(self) -> None:
        # До теста: Alice и Bob в базе
        self.assertEqual(await self.db.get_value("user:1"), "Alice")

        # Внутри контекста теста модифицируем базу и добавляем данные
        async with TransactionalTestSession(self.db, savepoint_name="test_1"):
            await self.db.set_value("user:1", "Alice_Modified")
            await self.db.set_value("user:3", "Charlie_New")
            self.assertEqual(await self.db.get_value("user:1"), "Alice_Modified")
            self.assertEqual(await self.db.get_value("user:3"), "Charlie_New")

        # После выхода из контекста теста:
        # Изменения Alice откатились, а Charlie удален!
        self.assertEqual(await self.db.get_value("user:1"), "Alice")
        self.assertIsNone(await self.db.get_value("user:3"))

    async def test_savepoint_rollback_on_exception(self) -> None:
        try:
            async with TransactionalTestSession(self.db, savepoint_name="test_error"):
                await self.db.set_value("user:1", "Crash_Test")
                raise RuntimeError("Внезапная ошибка бизнес-логики")
        except RuntimeError:
            pass

        # База осталась целостной
        self.assertEqual(await self.db.get_value("user:1"), "Alice")


class TestAsyncMockHttpClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.client = AsyncMockHttpClient()
        self.client.add_route(
            method="GET",
            url="https://api.stripe.com/v1/customers/1",
            status_code=200,
            json_data={"id": "cust_1", "email": "test@stripe.com"},
        )

    async def test_route_intercept_success(self) -> None:
        response = await self.client.get("https://api.stripe.com/v1/customers/1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "test@stripe.com")
        self.assertEqual(self.client.call_count, 1)

    async def test_unregistered_route_raises_error(self) -> None:
        with self.assertRaises(ConnectionError):
            await self.client.get("https://unknown-domain.org/data")


class AuthService(Protocol):
    def get_role(self) -> str:
        ...


class RealAuthService:
    def get_role(self) -> str:
        return "USER"


class MockAdminAuthService:
    def get_role(self) -> str:
        return "SUPERADMIN"


class TestDependencyOverrides(unittest.TestCase):
    def setUp(self) -> None:
        self.container = DependencyContainer()
        self.container.register(AuthService, RealAuthService())

    def test_default_resolution(self) -> None:
        service = self.container.resolve(AuthService)
        self.assertEqual(service.get_role(), "USER")

    def test_override_resolution_and_cleanup(self) -> None:
        # 1. Переопределяем моком
        self.container.dependency_overrides[AuthService] = MockAdminAuthService()
        mocked_service = self.container.resolve(AuthService)
        self.assertEqual(mocked_service.get_role(), "SUPERADMIN")

        # 2. Очищаем переопределение
        self.container.clear_overrides()
        restored_service = self.container.resolve(AuthService)
        self.assertEqual(restored_service.get_role(), "USER")


if __name__ == "__main__":
    unittest.main()
