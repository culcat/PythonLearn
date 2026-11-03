#!/usr/bin/env python3
"""Практическое задание к теме 04: Система внедрения зависимостей (Dependency Injection).

В реальном FastAPI этот функционал реализуется так:
```python
from typing import Annotated
from fastapi import FastAPI, Depends

app = FastAPI()

async def get_db_session():
    session = DBSession()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

async def get_current_user(session = Depends(get_db_session)):
    return {"user_id": 1, "session": session}

@app.get("/profile")
async def profile(user = Depends(get_current_user)):
    return user

# В тестах:
app.dependency_overrides[get_db_session] = mock_get_test_db
```

Ниже представлена автономная асинхронная реализация графа Dependency Injection (DI)
на стандартной библиотеке Python 3.14:
- Маркер `Depends` с поддержкой `use_cache=True`
- Рекурсивное построение и разрешение направленного ациклического графа (DAG) зависимостей
- Кэширование экземпляров зависимостей в пределах одного контекста запроса
- Поддержка ресурсных зависимостей с генератором `yield` и гарантированной финализацией в LIFO порядке
- Проброс исключений в генератор через `gen.throw(exc)`
- Словарь переопределения зависимостей в тестах `dependency_overrides`
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Generator, get_args, get_origin
import unittest


@dataclass(frozen=True)
class DependencyMarker:
    dependency: Callable[..., Any]
    use_cache: bool = True


def Depends(dependency: Callable[..., Any], *, use_cache: bool = True) -> DependencyMarker:
    return DependencyMarker(dependency=dependency, use_cache=use_cache)


class DIContext:
    def __init__(self) -> None:
        self.cache: dict[Callable, Any] = {}
        self.sync_generators: list[Generator] = []
        self.async_generators: list[AsyncGenerator] = []


class DIContainer:
    def __init__(self) -> None:
        self.dependency_overrides: dict[Callable, Callable] = {}

    def _extract_dependency(self, param: inspect.Parameter) -> DependencyMarker | None:
        # 1. Проверяем default значение: param: Type = Depends(...)
        if isinstance(param.default, DependencyMarker):
            return param.default

        # 2. Проверяем Annotated[Type, Depends(...)]
        origin = get_origin(param.annotation)
        # В Python Annotated имеет origin typing.Annotated
        if origin is not None and getattr(origin, "_name", "") == "Annotated":
            args = get_args(param.annotation)
            for arg in args[1:]:
                if isinstance(arg, DependencyMarker):
                    return arg

        return None

    async def _resolve_node(
        self,
        target_callable: Callable[..., Any],
        context: DIContext,
        use_cache: bool = True,
    ) -> Any:
        # Проверяем наличие переопределения в тестах
        actual_callable = self.dependency_overrides.get(target_callable, target_callable)

        # Проверяем кэш запроса
        if use_cache and actual_callable in context.cache:
            return context.cache[actual_callable]

        # Рекурсивно разрешаем параметры actual_callable
        sig = inspect.signature(actual_callable)
        resolved_kwargs: dict[str, Any] = {}

        for p_name, p_obj in sig.parameters.items():
            dep_marker = self._extract_dependency(p_obj)
            if dep_marker is not None:
                resolved_kwargs[p_name] = await self._resolve_node(
                    dep_marker.dependency,
                    context,
                    use_cache=dep_marker.use_cache,
                )

        # Вызываем actual_callable
        if inspect.isgeneratorfunction(actual_callable):
            gen = actual_callable(**resolved_kwargs)
            context.sync_generators.append(gen)
            value = next(gen)
        elif inspect.isasyncgenfunction(actual_callable):
            agen = actual_callable(**resolved_kwargs)
            context.async_generators.append(agen)
            value = await anext(agen)
        elif inspect.iscoroutinefunction(actual_callable):
            value = await actual_callable(**resolved_kwargs)
        else:
            value = actual_callable(**resolved_kwargs)

        if use_cache:
            context.cache[actual_callable] = value

        return value

    async def execute(self, endpoint: Callable[..., Any], **explicit_kwargs: Any) -> Any:
        context = DIContext()
        error_to_raise: BaseException | None = None
        result: Any = None

        try:
            # Разрешаем зависимости самого эндпоинта
            sig = inspect.signature(endpoint)
            final_kwargs = dict(explicit_kwargs)

            for p_name, p_obj in sig.parameters.items():
                if p_name in final_kwargs:
                    continue
                dep_marker = self._extract_dependency(p_obj)
                if dep_marker is not None:
                    final_kwargs[p_name] = await self._resolve_node(
                        dep_marker.dependency,
                        context,
                        use_cache=dep_marker.use_cache,
                    )

            if inspect.iscoroutinefunction(endpoint):
                result = await endpoint(**final_kwargs)
            else:
                result = endpoint(**final_kwargs)

            return result
        except BaseException as exc:
            error_to_raise = exc
            raise
        finally:
            # Финализация в обратном порядке (LIFO)
            # 1. Синхронные генераторы
            while context.sync_generators:
                gen = context.sync_generators.pop()
                try:
                    if error_to_raise is not None:
                        try:
                            gen.throw(error_to_raise)
                        except StopIteration:
                            pass
                    else:
                        next(gen, None)
                except (StopIteration, Exception):
                    pass

            # 2. Асинхронные генераторы
            while context.async_generators:
                agen = context.async_generators.pop()
                try:
                    if error_to_raise is not None:
                        try:
                            await agen.athrow(error_to_raise)
                        except StopAsyncIteration:
                            pass
                    else:
                        await anext(agen, None)
                except (StopAsyncIteration, Exception):
                    pass


# =====================================================================
# Набор тестов (unittest / pytest compatible)
# =====================================================================

class TestDependencyInjectionSystem(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.container = DIContainer()

    async def test_hierarchical_sub_dependencies(self) -> None:
        def get_auth_token() -> str:
            return "bearer-xyz-secret-token"

        def get_current_user(token: str = Depends(get_auth_token)) -> dict:
            return {"user_id": 10, "token": token}

        async def get_user_profile(user: dict = Depends(get_current_user)) -> dict:
            return {"profile": "User profile", "owner": user}

        result = await self.container.execute(get_user_profile)
        self.assertEqual(result["profile"], "User profile")
        self.assertEqual(result["owner"]["user_id"], 10)
        self.assertEqual(result["owner"]["token"], "bearer-xyz-secret-token")

    async def test_dependency_caching_within_request(self) -> None:
        call_count = 0

        def create_expensive_resource() -> dict:
            nonlocal call_count
            call_count += 1
            return {"id": call_count}

        def dep_a(res: dict = Depends(create_expensive_resource, use_cache=True)) -> dict:
            return res

        def dep_b(res: dict = Depends(create_expensive_resource, use_cache=True)) -> dict:
            return res

        async def endpoint(
            a: dict = Depends(dep_a),
            b: dict = Depends(dep_b),
        ) -> dict:
            return {"a": a, "b": b}

        result = await self.container.execute(endpoint)
        # create_expensive_resource должен быть вызван ровно 1 раз благодаря кэшированию
        self.assertEqual(call_count, 1)
        self.assertIs(result["a"], result["b"])

    async def test_dependency_no_cache(self) -> None:
        call_count = 0

        def create_unique_id() -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        async def endpoint(
            id1: int = Depends(create_unique_id, use_cache=False),
            id2: int = Depends(create_unique_id, use_cache=False),
        ) -> dict:
            return {"id1": id1, "id2": id2}

        result = await self.container.execute(endpoint)
        self.assertEqual(call_count, 2)
        self.assertEqual(result["id1"], 1)
        self.assertEqual(result["id2"], 2)

    async def test_resource_yield_lifecycle(self) -> None:
        events: list[str] = []

        def get_db_session() -> Generator[dict, None, None]:
            events.append("open_session")
            session = {"status": "active"}
            try:
                yield session
                events.append("commit_session")
            finally:
                events.append("close_session")

        async def endpoint(db: dict = Depends(get_db_session)) -> str:
            events.append("execute_query")
            self.assertEqual(db["status"], "active")
            return "done"

        res = await self.container.execute(endpoint)
        self.assertEqual(res, "done")
        self.assertEqual(events, ["open_session", "execute_query", "commit_session", "close_session"])

    async def test_resource_yield_with_exception_rollback(self) -> None:
        events: list[str] = []

        def get_db_session() -> Generator[dict, None, None]:
            events.append("open_session")
            session = {"status": "active"}
            try:
                yield session
                events.append("commit_session")
            except ValueError:
                events.append("rollback_session")
            finally:
                events.append("close_session")

        async def failing_endpoint(db: dict = Depends(get_db_session)) -> None:
            events.append("fail_operation")
            raise ValueError("Ошибка бизнес-логики")

        with self.assertRaises(ValueError):
            await self.container.execute(failing_endpoint)

        self.assertEqual(events, ["open_session", "fail_operation", "rollback_session", "close_session"])

    async def test_dependency_overrides(self) -> None:
        def get_real_db() -> str:
            raise RuntimeError("Боевая БД недоступна в тестах")

        async def endpoint(db: str = Depends(get_real_db)) -> dict:
            return {"database": db}

        # Переопределяем зависимость на mock
        def mock_db() -> str:
            return "in-memory-sqlite-test"

        self.container.dependency_overrides[get_real_db] = mock_db
        res = await self.container.execute(endpoint)
        self.assertEqual(res["database"], "in-memory-sqlite-test")

        # Очищаем переопределения
        self.container.dependency_overrides.clear()
        with self.assertRaises(RuntimeError):
            await self.container.execute(endpoint)


if __name__ == "__main__":
    unittest.main()
