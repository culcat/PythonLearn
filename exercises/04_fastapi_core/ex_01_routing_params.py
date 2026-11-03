#!/usr/bin/env python3
"""Практическое задание к теме 01: ASGI, модульная маршрутизация и типизированные параметры.

В реальном FastAPI этот функционал реализуется через:
```python
from typing import Annotated
from fastapi import FastAPI, APIRouter, Path, Query, status

router = APIRouter(prefix="/api/v1", tags=["Items"])

@router.get("/items/me")
async def get_my_items():
    return {"user": "current", "items": []}

@router.get("/items/{item_id}")
async def get_item_by_id(
    item_id: Annotated[int, Path(ge=1)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query()] = None,
):
    return {"item_id": item_id, "limit": limit, "search": search}
```

Ниже представлена автономная реализация ядра ASGI-роутера на стандартной библиотеке Python 3.14:
- Поддержка типизированных параметров пути `{param:int}`, `{param:str}`, `{param:float}`
- Гарантированный порядок сопоставления маршрутов (First-Match, специфичные перед шаблонными)
- Парсинг и приведение Query-параметров
- Асинхронный ASGI 3.0 интерфейс `async def __call__(self, scope, receive, send)`
- Автогенерация схемы OpenAPI 3.1
"""

from __future__ import annotations

import inspect
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine
import unittest


@dataclass
class Route:
    path: str
    method: str
    handler: Callable[..., Any]
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    regex: re.Pattern = field(init=False)
    param_converters: dict[str, type] = field(init=False)

    def __post_init__(self) -> None:
        self.param_converters = {}
        # Заменяем {param:type} или {param} на regex группы
        pattern = "^"
        segments = [s for s in self.path.split("/") if s]
        if not segments and self.path == "/":
            pattern += "/"
        for seg in segments:
            pattern += "/"
            if seg.startswith("{") and seg.endswith("}"):
                inner = seg[1:-1]
                if ":" in inner:
                    name, type_str = inner.split(":", 1)
                else:
                    name, type_str = inner, "str"
                
                if type_str == "int":
                    self.param_converters[name] = int
                    pattern += f"(?P<{name}>\\d+)"
                elif type_str == "float":
                    self.param_converters[name] = float
                    pattern += f"(?P<{name}>\\d+(?:\\.\\d+)?)"
                else:
                    self.param_converters[name] = str
                    pattern += f"(?P<{name}>[^/]+)"
            else:
                pattern += re.escape(seg)
        pattern += "$"
        self.regex = re.compile(pattern)

    def match(self, path: str) -> dict[str, Any] | None:
        m = self.regex.match(path)
        if not m:
            return None
        raw_params = m.groupdict()
        typed_params: dict[str, Any] = {}
        for k, v in raw_params.items():
            conv = self.param_converters.get(k, str)
            typed_params[k] = conv(v)
        return typed_params


class ASGIRouter:
    def __init__(self, prefix: str = "", tags: list[str] | None = None) -> None:
        self.prefix = prefix.rstrip("/")
        self.tags = tags or []
        self.routes: list[Route] = []

    def add_route(
        self,
        path: str,
        method: str,
        handler: Callable[..., Any],
        summary: str = "",
        tags: list[str] | None = None,
    ) -> None:
        full_path = self.prefix + ("/" + path.lstrip("/") if path else "")
        if not full_path:
            full_path = "/"
        combined_tags = list(self.tags) + (tags or [])
        route = Route(
            path=full_path,
            method=method.upper(),
            handler=handler,
            summary=summary,
            tags=combined_tags,
        )
        self.routes.append(route)

    def get(self, path: str, summary: str = "", tags: list[str] | None = None) -> Callable:
        def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
            self.add_route(path, "GET", handler, summary=summary, tags=tags)
            return handler
        return decorator

    def post(self, path: str, summary: str = "", tags: list[str] | None = None) -> Callable:
        def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
            self.add_route(path, "POST", handler, summary=summary, tags=tags)
            return handler
        return decorator

    def parse_query_string(self, qs_bytes: bytes) -> dict[str, Any]:
        if not qs_bytes:
            return {}
        qs_str = qs_bytes.decode("latin-1")
        parsed = urllib.parse.parse_qs(qs_str, keep_blank_values=True)
        # Упрощаем одиночные значения
        result: dict[str, Any] = {}
        for k, v in parsed.items():
            result[k] = v[0] if len(v) == 1 else v
        return result

    def generate_openapi(self, title: str = "FastAPI stdlib", version: str = "1.0.0") -> dict[str, Any]:
        openapi = {
            "openapi": "3.1.0",
            "info": {"title": title, "version": version},
            "paths": {},
        }
        for route in self.routes:
            path_key = route.path
            # Заменяем {param:type} на {param} для OpenAPI стандарта
            openapi_path = re.sub(r"\{(\w+):[a-z]+\}", r"{\1}", path_key)
            if openapi_path not in openapi["paths"]:
                openapi["paths"][openapi_path] = {}

            method_lower = route.method.lower()
            parameters = []
            for param_name, p_type in route.param_converters.items():
                type_name = "integer" if p_type is int else ("number" if p_type is float else "string")
                parameters.append({
                    "name": param_name,
                    "in": "path",
                    "required": True,
                    "schema": {"type": type_name},
                })

            openapi["paths"][openapi_path][method_lower] = {
                "summary": route.summary or f"{route.method} {openapi_path}",
                "tags": route.tags,
                "parameters": parameters,
                "responses": {
                    "200": {"description": "Успешный ответ"},
                },
            }
        return openapi

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        assert scope["type"] == "http"
        request_path = scope.get("path", "/")
        request_method = scope.get("method", "GET").upper()

        matched_route: Route | None = None
        path_params: dict[str, Any] = {}
        method_not_allowed = False

        for route in self.routes:
            params = route.match(request_path)
            if params is not None:
                if route.method == request_method:
                    matched_route = route
                    path_params = params
                    break
                else:
                    method_not_allowed = True

        if matched_route is None:
            status_code = 405 if method_not_allowed else 404
            detail_msg = "Method Not Allowed" if method_not_allowed else "Not Found"
            body_bytes = json.dumps({"detail": detail_msg}).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": status_code,
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
            return

        # Парсинг query-параметров
        qs_bytes = scope.get("query_string", b"")
        query_params = self.parse_query_string(qs_bytes)

        # Вызов хендлера с передачей path и query параметров
        sig = inspect.signature(matched_route.handler)
        handler_kwargs: dict[str, Any] = {}
        for param_name, param_obj in sig.parameters.items():
            if param_name in path_params:
                handler_kwargs[param_name] = path_params[param_name]
            elif param_name in query_params:
                val = query_params[param_name]
                # Приведение типа, если в аннотации указан int/float/bool
                if param_obj.annotation is int or param_obj.annotation == "int":
                    val = int(val)
                elif param_obj.annotation is float or param_obj.annotation == "float":
                    val = float(val)
                elif param_obj.annotation is bool or param_obj.annotation == "bool":
                    val = str(val).lower() in ("true", "1", "yes")
                handler_kwargs[param_name] = val
            elif param_obj.default is not inspect.Parameter.empty:
                handler_kwargs[param_name] = param_obj.default

        if inspect.iscoroutinefunction(matched_route.handler):
            result = await matched_route.handler(**handler_kwargs)
        else:
            result = matched_route.handler(**handler_kwargs)

        body_bytes = json.dumps(result).encode("utf-8")
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


# =====================================================================
# Набор тестов (unittest / pytest compatible)
# =====================================================================

class TestASGIRouterAndParameters(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.router = ASGIRouter(prefix="/api/v1", tags=["V1"])

        # Важно: специфичный статический маршрут объявляется ПЕРЕД динамическим
        @self.router.get("/users/me", summary="Get Current User")
        async def get_current_user() -> dict:
            return {"user_id": "current_logged_in_user", "is_self": True}

        @self.router.get("/users/{user_id:int}", summary="Get User By ID")
        async def get_user_by_id(user_id: int, include_extra: bool = False) -> dict:
            return {"user_id": user_id, "include_extra": include_extra}

        @self.router.post("/items", summary="Create Item")
        def create_item() -> dict:
            return {"status": "created"}

    async def _simulate_asgi(self, scope: dict) -> tuple[int, dict[str, str], dict]:
        messages_sent: list[dict] = []

        async def fake_receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def fake_send(message: dict) -> None:
            messages_sent.append(message)

        await self.router(scope, fake_receive, fake_send)

        start_event = messages_sent[0]
        body_event = messages_sent[1]
        status = start_event["status"]
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in start_event.get("headers", [])}
        body = json.loads(body_event["body"].decode("utf-8"))
        return status, headers, body

    async def test_static_route_priority_over_dynamic_parameter(self) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/users/me",
            "query_string": b"",
        }
        status, headers, body = await self._simulate_asgi(scope)
        self.assertEqual(status, 200)
        self.assertEqual(body["user_id"], "current_logged_in_user")
        self.assertTrue(body["is_self"])

    async def test_typed_path_parameter_parsing(self) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/users/42",
            "query_string": b"include_extra=true",
        }
        status, headers, body = await self._simulate_asgi(scope)
        self.assertEqual(status, 200)
        self.assertEqual(body["user_id"], 42)
        self.assertIsInstance(body["user_id"], int)
        self.assertTrue(body["include_extra"])

    async def test_query_param_default_value(self) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/users/100",
            "query_string": b"",
        }
        status, _, body = await self._simulate_asgi(scope)
        self.assertEqual(status, 200)
        self.assertEqual(body["user_id"], 100)
        self.assertFalse(body["include_extra"])

    async def test_not_found_404(self) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/unknown-endpoint",
            "query_string": b"",
        }
        status, _, body = await self._simulate_asgi(scope)
        self.assertEqual(status, 404)
        self.assertEqual(body["detail"], "Not Found")

    async def test_method_not_allowed_405(self) -> None:
        scope = {
            "type": "http",
            "method": "DELETE",
            "path": "/api/v1/items",
            "query_string": b"",
        }
        status, _, body = await self._simulate_asgi(scope)
        self.assertEqual(status, 405)
        self.assertEqual(body["detail"], "Method Not Allowed")

    def test_openapi_schema_generation(self) -> None:
        schema = self.router.generate_openapi(title="E-Commerce API", version="2.0.0")
        self.assertEqual(schema["openapi"], "3.1.0")
        self.assertEqual(schema["info"]["title"], "E-Commerce API")
        paths = schema["paths"]
        self.assertIn("/api/v1/users/me", paths)
        self.assertIn("/api/v1/users/{user_id}", paths)
        user_id_param = paths["api/v1/users/{user_id}"]["get"]["parameters"][0] if "api/v1/users/{user_id}" in paths else paths["/api/v1/users/{user_id}"]["get"]["parameters"][0]
        self.assertEqual(user_id_param["name"], "user_id")
        self.assertEqual(user_id_param["schema"]["type"], "integer")


if __name__ == "__main__":
    unittest.main()
