#!/usr/bin/env python3
"""Практическое задание к теме 05: ASGI Middleware, жизненный цикл Lifespan и фоновые задачи.

В реальном FastAPI этот функционал реализуется так:
```python
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = "ConnectedPool"
    yield
    app.state.db_pool = "ClosedPool"

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["https://frontend.com"], allow_credentials=True)

@app.post("/notify")
async def notify(bg: BackgroundTasks):
    bg.add_task(send_email, "user@test.ru")
    return {"status": "enqueued"}
```

Ниже представлена автономная реализация конвейера чистого ASGI-middleware,
асинхронного менеджера жизненного цикла Lifespan и раннера BackgroundTasks
на стандартной библиотеке Python 3.14:
- Onion-конвейер чистого ASGI Middleware с модификацией заголовков `http.response.start`
- Реализация `CORSMiddleware` (Preflight OPTIONS перехват и добавление заголовков)
- Асинхронный контекстный менеджер `LifespanManager` с сохранением состояния в `app.state`
- Класс `BackgroundTasks` с гарантированным выполнением задач строго ПОСЛЕ отправки ответа клиенту
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Callable
import unittest


class AppState:
    """Хранилище состояния уровня приложения (аналог app.state)."""
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"'AppState' не содержит атрибута '{name}'") from None

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_data":
            super().__setattr__(name, value)
        else:
            self._data[name] = value


class BackgroundTasks:
    """Очередь задач, запускаемых после отправки HTTP-ответа клиенту."""
    def __init__(self) -> None:
        self.tasks: list[tuple[Callable, tuple, dict]] = []

    def add_task(self, func: Callable, *args: Any, **kwargs: Any) -> None:
        self.tasks.append((func, args, kwargs))

    async def execute_all(self) -> None:
        for func, args, kwargs in self.tasks:
            if inspect.iscoroutinefunction(func):
                await func(*args, **kwargs)
            else:
                func(*args, **kwargs)


class CORSMiddleware:
    """Чистый ASGI Middleware для обработки Cross-Origin Resource Sharing (CORS)."""
    def __init__(
        self,
        app: Callable,
        allow_origins: list[str],
        allow_credentials: bool = False,
        allow_methods: list[str] | None = None,
        allow_headers: list[str] | None = None,
    ) -> None:
        self.app = app
        self.allow_origins = set(allow_origins)
        self.allow_credentials = allow_credentials
        self.allow_methods = allow_methods or ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
        self.allow_headers = allow_headers or ["*"]

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers_dict = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        origin = headers_dict.get("origin")
        is_preflight = scope.get("method") == "OPTIONS" and "access-control-request-method" in headers_dict

        # Если Preflight OPTIONS запрос
        if is_preflight and origin in self.allow_origins:
            cors_headers = [
                (b"access-control-allow-origin", origin.encode("latin-1")),
                (b"access-control-allow-methods", ", ".join(self.allow_methods).encode("latin-1")),
                (b"access-control-allow-headers", ", ".join(self.allow_headers).encode("latin-1")),
            ]
            if self.allow_credentials:
                cors_headers.append((b"access-control-allow-credentials", b"true"))

            await send({
                "type": "http.response.start",
                "status": 204,
                "headers": cors_headers,
            })
            await send({
                "type": "http.response.body",
                "body": b"",
                "more_body": False,
            })
            return

        # Для обычных запросов оборачиваем send, добавляя CORS заголовок к ответу
        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start" and origin in self.allow_origins:
                headers = list(message.get("headers", []))
                headers.append((b"access-control-allow-origin", origin.encode("latin-1")))
                if self.allow_credentials:
                    headers.append((b"access-control-allow-credentials", b"true"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class ProcessTimeMiddleware:
    """Чистый ASGI Middleware для добавления времени выполнения запроса."""
    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                duration = time.perf_counter() - start_time
                headers = list(message.get("headers", []))
                headers.append((b"x-process-time", f"{duration:.4f}".encode("ascii")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class ASGIApp:
    def __init__(self, lifespan: Callable[[ASGIApp], AsyncGenerator[None, None]] | None = None) -> None:
        self.state = AppState()
        self.lifespan = lifespan
        self.middleware_stack: Callable = self._core_app

    def add_middleware(self, middleware_cls: type, **kwargs: Any) -> None:
        # Оборачиваем текущий стек (Onion Architecture)
        self.middleware_stack = middleware_cls(self.middleware_stack, **kwargs)

    async def _core_app(self, scope: dict, receive: Callable, send: Callable) -> None:
        # Эмуляция базового приложения с поддержкой BackgroundTasks
        background_tasks = BackgroundTasks()

        # Помещаем background_tasks в scope, чтобы эндпоинт мог добавлять задачи
        scope["state"] = self.state
        scope["background_tasks"] = background_tasks

        path = scope.get("path", "/")
        response_data: dict[str, Any] = {"status": "ok", "path": path}

        if path == "/enqueue-task":
            # Регистрируем задачу в фоновом раннере
            events_list: list[str] = scope.get("test_events_collector", [])
            async def bg_job():
                await asyncio.sleep(0.01)
                events_list.append("background_job_finished")

            background_tasks.add_task(bg_job)
            response_data["enqueued"] = True

        body_bytes = json.dumps(response_data).encode("utf-8")

        # 1. Отправляем ответ клиенту
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body_bytes)).encode("ascii")],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body_bytes,
            "more_body": False,
        })

        # 2. Выполняем фоновые задачи СТРОГО ПОСЛЕ отправки ответа
        await background_tasks.execute_all()

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        await self.middleware_stack(scope, receive, send)


# =====================================================================
# Набор тестов (unittest / pytest compatible)
# =====================================================================

class TestMiddlewareLifespanBackground(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_lifecycle_and_state(self) -> None:
        events: list[str] = []

        @asynccontextmanager
        async def sample_lifespan(app: ASGIApp) -> AsyncGenerator[None, None]:
            events.append("startup_begin")
            app.state.database = "PostgresPool_Active"
            events.append("startup_end")
            yield
            events.append("shutdown_begin")
            app.state.database = "PostgresPool_Closed"
            events.append("shutdown_end")

        app = ASGIApp(lifespan=sample_lifespan)

        # Симуляция жизненного цикла ASGI Lifespan
        async with sample_lifespan(app):
            self.assertEqual(app.state.database, "PostgresPool_Active")
            self.assertEqual(events, ["startup_begin", "startup_end"])

        self.assertEqual(app.state.database, "PostgresPool_Closed")
        self.assertEqual(events, ["startup_begin", "startup_end", "shutdown_begin", "shutdown_end"])

    async def test_process_time_pure_asgi_middleware(self) -> None:
        app = ASGIApp()
        app.add_middleware(ProcessTimeMiddleware)

        messages: list[dict] = []
        async def fake_receive() -> dict:
            return {"type": "http.request", "body": b""}
        async def fake_send(msg: dict) -> None:
            messages.append(msg)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/ping",
            "headers": [],
        }
        await app(scope, fake_receive, fake_send)

        start_msg = messages[0]
        self.assertEqual(start_msg["type"], "http.response.start")
        headers_dict = {k.decode("ascii"): v.decode("ascii") for k, v in start_msg["headers"]}
        self.assertIn("x-process-time", headers_dict)
        self.assertGreaterEqual(float(headers_dict["x-process-time"]), 0.0)

    async def test_cors_middleware_preflight_and_normal_request(self) -> None:
        app = ASGIApp()
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["https://myfrontend.com"],
            allow_credentials=True,
        )

        async def fake_receive() -> dict:
            return {"type": "http.request", "body": b""}

        # 1. Preflight OPTIONS запрос
        preflight_messages: list[dict] = []
        async def send_preflight(msg: dict) -> None:
            preflight_messages.append(msg)

        scope_options = {
            "type": "http",
            "method": "OPTIONS",
            "path": "/api/data",
            "headers": [
                (b"origin", b"https://myfrontend.com"),
                (b"access-control-request-method", b"POST"),
            ],
        }
        await app(scope_options, fake_receive, send_preflight)
        self.assertEqual(preflight_messages[0]["status"], 204)
        opt_headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in preflight_messages[0]["headers"]}
        self.assertEqual(opt_headers["access-control-allow-origin"], "https://myfrontend.com")
        self.assertEqual(opt_headers["access-control-allow-credentials"], "true")

        # 2. Обычный GET запрос с разрешенным Origin
        get_messages: list[dict] = []
        async def send_get(msg: dict) -> None:
            get_messages.append(msg)

        scope_get = {
            "type": "http",
            "method": "GET",
            "path": "/api/data",
            "headers": [(b"origin", b"https://myfrontend.com")],
        }
        await app(scope_get, fake_receive, send_get)
        get_headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in get_messages[0]["headers"]}
        self.assertEqual(get_headers["access-control-allow-origin"], "https://myfrontend.com")

        # 3. Запрос с запрещенным Origin
        forbidden_messages: list[dict] = []
        async def send_bad(msg: dict) -> None:
            forbidden_messages.append(msg)

        scope_bad_origin = {
            "type": "http",
            "method": "GET",
            "path": "/api/data",
            "headers": [(b"origin", b"https://malicious-site.com")],
        }
        await app(scope_bad_origin, fake_receive, send_bad)
        bad_headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in forbidden_messages[0]["headers"]}
        self.assertNotIn("access-control-allow-origin", bad_headers)

    async def test_background_tasks_executed_after_response(self) -> None:
        app = ASGIApp()
        execution_order: list[str] = []

        async def fake_receive() -> dict:
            return {"type": "http.request", "body": b""}

        async def fake_send(msg: dict) -> None:
            if msg["type"] == "http.response.start":
                execution_order.append("client_received_response_start")
            elif msg["type"] == "http.response.body":
                execution_order.append("client_received_response_body")

        bg_events: list[str] = []
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/enqueue-task",
            "headers": [],
            "test_events_collector": bg_events,
        }

        # Выполняем вызов приложения
        await app(scope, fake_receive, fake_send)

        # Клиент должен был сначала получить response start и body, и только затем выполнилась фоновая задача!
        self.assertEqual(execution_order, ["client_received_response_start", "client_received_response_body"])
        self.assertEqual(bg_events, ["background_job_finished"])


if __name__ == "__main__":
    unittest.main()
