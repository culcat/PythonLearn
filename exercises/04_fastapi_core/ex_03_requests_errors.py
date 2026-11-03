#!/usr/bin/env python3
"""Практическое задание к теме 03: Обработка запросов, кастомные ответы и ошибки по стандарту RFC 9457.

В реальном FastAPI этот функционал реализуется так:
```python
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI()

class UserOut(BaseModel):
    id: int
    email: str

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    problem = {
        "type": "https://api.example.com/errors/validation-error",
        "title": "Ошибка валидации параметров",
        "status": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "detail": str(exc),
        "instance": str(request.url),
    }
    return JSONResponse(status_code=422, content=problem, media_type="application/problem+json")

@app.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: int, response: Response):
    response.set_cookie("trace_id", "xyz123", httponly=True, secure=True, samesite="lax")
    return {"id": user_id, "email": "dev@test.ru", "hashed_password": "ultra-secret-hash"}
```

Ниже представлена автономная реализация конвейера обработки запросов, фильтрации ответов
и обработки исключений в соответствии со стандартом RFC 9457 на стандартной библиотеке Python 3.14:
- Класс `Response` с установкой заголовков и Cookie (`httponly`, `secure`, `samesite`, `max_age`)
- Механизм проекции/фильтрации выходных данных `response_model_filter`
- Иерархия исключений `HTTPException`, `RequestValidationError`
- Стандартизированный формат ошибок RFC 9457 (Problem Details for HTTP APIs, `application/problem+json`)
- Диспетчер исключений `@exception_handler`
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any, Callable, Sequence
import unittest


class HTTPException(Exception):
    def __init__(
        self,
        status_code: int,
        detail: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.headers = headers or {}
        super().__init__(detail)


class RequestValidationError(Exception):
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = errors
        super().__init__(str(errors))


class Response:
    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        media_type: str = "application/json",
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}
        self.media_type = media_type
        self.cookies: list[str] = []

    def set_cookie(
        self,
        key: str,
        value: str,
        max_age: int | None = None,
        httponly: bool = False,
        secure: bool = False,
        samesite: str = "lax",
    ) -> None:
        cookie_parts = [f"{key}={value}"]
        if max_age is not None:
            cookie_parts.append(f"Max-Age={max_age}")
        if httponly:
            cookie_parts.append("HttpOnly")
        if secure:
            cookie_parts.append("Secure")
        if samesite:
            cookie_parts.append(f"SameSite={samesite.capitalize()}")
        self.cookies.append("; ".join(cookie_parts))


def filter_response_model(
    data: Any,
    allowed_fields: set[str],
    exclude_unset: bool = False,
) -> dict[str, Any]:
    """Проекция и фильтрация выходных полей (аналог response_model в FastAPI)."""
    if hasattr(data, "__dict__"):
        raw_dict = data.__dict__
    elif isinstance(data, dict):
        raw_dict = data
    else:
        raise ValueError("Данные должны быть объектом или словарем")

    filtered: dict[str, Any] = {}
    for key in allowed_fields:
        if key in raw_dict:
            val = raw_dict[key]
            if exclude_unset and val is None:
                continue
            filtered[key] = val
    return filtered


def format_rfc9457_problem(
    status_code: int,
    title: str,
    detail: str,
    instance: str,
    problem_type: str = "about:blank",
    invalid_params: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Генерация словаря в соответствии со спецификацией RFC 9457 Problem Details."""
    doc = {
        "type": problem_type,
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": instance,
    }
    if invalid_params is not None:
        doc["invalid_params"] = invalid_params
    return doc


class RequestDispatcher:
    def __init__(self) -> None:
        self.exception_handlers: dict[type[Exception], Callable] = {}
        # Стандартные обработчики
        self.register_handler(HTTPException, self._default_http_exception_handler)
        self.register_handler(RequestValidationError, self._default_validation_exception_handler)

    def register_handler(self, exc_class: type[Exception], handler: Callable) -> None:
        self.exception_handlers[exc_class] = handler

    def exception_handler(self, exc_class: type[Exception]) -> Callable:
        def decorator(handler: Callable) -> Callable:
            self.register_handler(exc_class, handler)
            return handler
        return decorator

    def _default_http_exception_handler(self, request_url: str, exc: HTTPException) -> Response:
        try:
            http_title = HTTPStatus(exc.status_code).phrase
        except ValueError:
            http_title = "HTTP Error"

        problem = format_rfc9457_problem(
            status_code=exc.status_code,
            title=http_title,
            detail=exc.detail,
            instance=request_url,
            problem_type=f"https://httpstatuses.io/{exc.status_code}",
        )
        headers = dict(exc.headers)
        headers["content-type"] = "application/problem+json"
        return Response(
            content=problem,
            status_code=exc.status_code,
            headers=headers,
            media_type="application/problem+json",
        )

    def _default_validation_exception_handler(self, request_url: str, exc: RequestValidationError) -> Response:
        problem = format_rfc9457_problem(
            status_code=422,
            title="Unprocessable Entity",
            detail="Входные параметры запроса содержат ошибки валидации",
            instance=request_url,
            problem_type="https://api.example.com/errors/validation-error",
            invalid_params=exc.errors,
        )
        return Response(
            content=problem,
            status_code=422,
            headers={"content-type": "application/problem+json"},
            media_type="application/problem+json",
        )

    def handle_request(
        self,
        request_url: str,
        handler: Callable[..., Any],
        *args: Any,
        response_model_fields: set[str] | None = None,
        **kwargs: Any,
    ) -> Response:
        response_obj = Response()
        try:
            # Если хендлер принимает response_obj
            result = handler(*args, response=response_obj, **kwargs)
            if isinstance(result, Response):
                response_obj = result
            elif response_model_fields is not None:
                response_obj.content = filter_response_model(result, response_model_fields)
            else:
                response_obj.content = result
            return response_obj
        except Exception as exc:
            for exc_type, h_func in self.exception_handlers.items():
                if isinstance(exc, exc_type):
                    return h_func(request_url, exc)
            # Внутренняя ошибка сервера (500)
            problem = format_rfc9457_problem(
                status_code=500,
                title="Internal Server Error",
                detail="Произошла непредвиденная ошибка на стороне сервера",
                instance=request_url,
            )
            return Response(
                content=problem,
                status_code=500,
                headers={"content-type": "application/problem+json"},
                media_type="application/problem+json",
            )


# =====================================================================
# Набор тестов (unittest / pytest compatible)
# =====================================================================

class TestRequestsResponsesAndErrors(unittest.TestCase):
    def setUp(self) -> None:
        self.dispatcher = RequestDispatcher()

    def test_response_cookie_and_headers(self) -> None:
        def login_handler(response: Response) -> dict[str, str]:
            response.set_cookie("session_id", "token_abc123", max_age=3600, httponly=True, secure=True, samesite="strict")
            response.headers["X-Server-Version"] = "2.4"
            return {"status": "authenticated"}

        resp = self.dispatcher.handle_request("/api/login", login_handler)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, {"status": "authenticated"})
        self.assertEqual(resp.headers["X-Server-Version"], "2.4")
        self.assertEqual(len(resp.cookies), 1)
        self.assertIn("session_id=token_abc123", resp.cookies[0])
        self.assertIn("HttpOnly", resp.cookies[0])
        self.assertIn("Secure", resp.cookies[0])
        self.assertIn("SameSite=Strict", resp.cookies[0])
        self.assertIn("Max-Age=3600", resp.cookies[0])

    def test_response_model_field_filtering(self) -> None:
        # Имитируем возврат внутренней сущности БД с приватными полями
        raw_db_user = {
            "id": 42,
            "email": "user@domain.com",
            "hashed_password": "$2b$12$eX4mpleHashSecretPass",
            "admin_notes": "internal company note",
        }

        def get_user_handler(response: Response) -> dict:
            return raw_db_user

        # response_model_fields содержит только публичные поля
        allowed_public_fields = {"id", "email"}
        resp = self.dispatcher.handle_request(
            "/api/users/42",
            get_user_handler,
            response_model_fields=allowed_public_fields,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, {"id": 42, "email": "user@domain.com"})
        self.assertNotIn("hashed_password", resp.content)
        self.assertNotIn("admin_notes", resp.content)

    def test_http_exception_rfc9457_format(self) -> None:
        def not_found_handler(response: Response) -> None:
            raise HTTPException(status_code=404, detail="Запрашиваемый заказ #999 не существует")

        resp = self.dispatcher.handle_request("/api/orders/999", not_found_handler)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.headers["content-type"], "application/problem+json")
        self.assertEqual(resp.content["status"], 404)
        self.assertEqual(resp.content["title"], "Not Found")
        self.assertEqual(resp.content["detail"], "Запрашиваемый заказ #999 не существует")
        self.assertEqual(resp.content["instance"], "/api/orders/999")

    def test_request_validation_error_rfc9457(self) -> None:
        def invalid_handler(response: Response) -> None:
            raise RequestValidationError(errors=[
                {"name": "body -> price", "reason": "Цена должна быть положительным числом"},
                {"name": "body -> sku", "reason": "Неверный формат артикула"},
            ])

        resp = self.dispatcher.handle_request("/api/products", invalid_handler)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.headers["content-type"], "application/problem+json")
        self.assertEqual(resp.content["status"], 422)
        self.assertEqual(resp.content["title"], "Unprocessable Entity")
        self.assertEqual(len(resp.content["invalid_params"]), 2)
        self.assertEqual(resp.content["invalid_params"][0]["name"], "body -> price")

    def test_custom_exception_handler(self) -> None:
        class InsufficientFundsError(Exception):
            def __init__(self, missing_amount: float) -> None:
                self.missing_amount = missing_amount

        @self.dispatcher.exception_handler(InsufficientFundsError)
        def handle_insufficient_funds(url: str, exc: InsufficientFundsError) -> Response:
            problem = format_rfc9457_problem(
                status_code=400,
                title="Недостаточно средств",
                detail=f"Для завершения транзакции не хватает {exc.missing_amount:.2f} руб.",
                instance=url,
                problem_type="https://bank.example.com/errors/insufficient-funds",
            )
            return Response(content=problem, status_code=400, headers={"content-type": "application/problem+json"})

        def payment_handler(response: Response) -> None:
            raise InsufficientFundsError(missing_amount=150.50)

        resp = self.dispatcher.handle_request("/api/pay", payment_handler)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.content["title"], "Недостаточно средств")
        self.assertIn("150.50", resp.content["detail"])


if __name__ == "__main__":
    unittest.main()
