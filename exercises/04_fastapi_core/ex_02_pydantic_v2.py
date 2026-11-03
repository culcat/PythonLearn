#!/usr/bin/env python3
"""Практическое задание к теме 02: Pydantic v2 — Модели, валидаторы и сериализация.

В реальном FastAPI с Pydantic v2 этот функционал реализуется так:
```python
from datetime import datetime, timezone
from typing import Self
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator, computed_field

class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=20)
    email: str
    password: str = Field(min_length=8)
    confirm_password: str

    @field_validator("email", mode="after")
    @classmethod
    def validate_email_domain(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Некорректный email адрес")
        return v.lower()

    @model_validator(mode="after")
    def passwords_match(self) -> Self:
        if self.password != self.confirm_password:
            raise ValueError("Пароли не совпадают")
        return self

class UserRead(BaseModel):
    id: int
    username: str
    email: str

    @computed_field
    def display_name(self) -> str:
        return f"@{self.username}"
```

Ниже представлена автономная реализация декларативной валидационной системы моделей данных
на стандартной библиотеке Python 3.14:
- Декларативный `Field` с числовыми, строковыми ограничениями, regex и `default_factory`
- Механизм `BaseModel` с поддержкой `ConfigDict` (`extra="forbid"`, `str_strip_whitespace=True`)
- Валидаторы `@field_validator` (`mode="before"` и `mode="after"`)
- Кросс-валидация всей модели `@model_validator(mode="after")`
- Вычисляемые поля `@computed_field` и экспорт через `.model_dump()`
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Self
import unittest


class ValidationError(Exception):
    """Исключение, выбрасываемое при ошибке валидации данных модели."""
    def __init__(self, errors: list[dict[str, Any]] | str) -> None:
        if isinstance(errors, str):
            self.errors = [{"msg": errors}]
            super().__init__(errors)
        else:
            self.errors = errors
            super().__init__(str(errors))


class FieldInfo:
    def __init__(
        self,
        default: Any = ...,
        *,
        default_factory: Callable[[], Any] | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
        gt: float | int | None = None,
        ge: float | int | None = None,
        lt: float | int | None = None,
        le: float | int | None = None,
        pattern: str | None = None,
        description: str = "",
        alias: str | None = None,
    ) -> None:
        self.default = default
        self.default_factory = default_factory
        self.min_length = min_length
        self.max_length = max_length
        self.gt = gt
        self.ge = ge
        self.lt = lt
        self.le = le
        self.pattern = re.compile(pattern) if pattern else None
        self.description = description
        self.alias = alias

    def validate(self, field_name: str, value: Any) -> Any:
        # Валидация строк
        if isinstance(value, str):
            if self.min_length is not None and len(value) < self.min_length:
                raise ValueError(f"Поле '{field_name}': длина строки меньше минимальной ({self.min_length})")
            if self.max_length is not None and len(value) > self.max_length:
                raise ValueError(f"Поле '{field_name}': длина строки больше максимальной ({self.max_length})")
            if self.pattern and not self.pattern.match(value):
                raise ValueError(f"Поле '{field_name}': строка не соответствует формату (pattern)")

        # Валидация чисел
        if isinstance(value, (int, float)):
            if self.gt is not None and value <= self.gt:
                raise ValueError(f"Поле '{field_name}': значение должно быть строго больше {self.gt}")
            if self.ge is not None and value < self.ge:
                raise ValueError(f"Поле '{field_name}': значение должно быть больше или равно {self.ge}")
            if self.lt is not None and value >= self.lt:
                raise ValueError(f"Поле '{field_name}': значение должно быть строго меньше {self.lt}")
            if self.le is not None and value > self.le:
                raise ValueError(f"Поле '{field_name}': значение должно быть меньше или равно {self.le}")

        return value


def Field(
    default: Any = ...,
    *,
    default_factory: Callable[[], Any] | None = None,
    min_length: int | None = None,
    max_length: int | None = None,
    gt: float | int | None = None,
    ge: float | int | None = None,
    lt: float | int | None = None,
    le: float | int | None = None,
    pattern: str | None = None,
    description: str = "",
    alias: str | None = None,
) -> FieldInfo:
    return FieldInfo(
        default=default,
        default_factory=default_factory,
        min_length=min_length,
        max_length=max_length,
        gt=gt,
        ge=ge,
        lt=lt,
        le=le,
        pattern=pattern,
        description=description,
        alias=alias,
    )


def field_validator(*fields: str, mode: str = "after") -> Callable:
    def decorator(fn: Callable) -> Callable:
        fn.__field_validator_info__ = {"fields": fields, "mode": mode}
        return fn
    return decorator


def model_validator(mode: str = "after") -> Callable:
    def decorator(fn: Callable) -> Callable:
        fn.__model_validator_info__ = {"mode": mode}
        return fn
    return decorator


def computed_field(fn: Callable) -> Callable:
    fn.__is_computed_field__ = True
    return fn


class ModelMetaclass(type):
    def __new__(mcs, name: str, bases: tuple[type, ...], namespace: dict[str, Any]):
        fields: dict[str, FieldInfo] = {}
        type_annotations: dict[str, Any] = namespace.get("__annotations__", {})

        # Наследуем поля от базовых классов
        for base in bases:
            if hasattr(base, "__model_fields__"):
                fields.update(base.__model_fields__)

        # Инициализируем поля из namespace
        for attr_name, attr_type in type_annotations.items():
            if attr_name.startswith("_") or attr_name == "model_config":
                continue
            val = namespace.get(attr_name, ...)
            if isinstance(val, FieldInfo):
                fields[attr_name] = val
            else:
                fields[attr_name] = FieldInfo(default=val)

        namespace["__model_fields__"] = fields

        # Регистрируем валидаторы и computed_fields
        field_validators_before: dict[str, list[Callable]] = {}
        field_validators_after: dict[str, list[Callable]] = {}
        model_validators_before: list[Callable] = []
        model_validators_after: list[Callable] = []
        computed_fields_list: list[str] = []

        for key, val in namespace.items():
            if hasattr(val, "__field_validator_info__"):
                info = val.__field_validator_info__
                target_dict = field_validators_before if info["mode"] == "before" else field_validators_after
                for f_name in info["fields"]:
                    target_dict.setdefault(f_name, []).append(val)
            elif hasattr(val, "__model_validator_info__"):
                info = val.__model_validator_info__
                if info["mode"] == "before":
                    model_validators_before.append(val)
                else:
                    model_validators_after.append(val)
            elif hasattr(val, "__is_computed_field__"):
                computed_fields_list.append(key)

        namespace["__fv_before__"] = field_validators_before
        namespace["__fv_after__"] = field_validators_after
        namespace["__mv_before__"] = model_validators_before
        namespace["__mv_after__"] = model_validators_after
        namespace["__computed_fields__"] = computed_fields_list

        return super().__new__(mcs, name, bases, namespace)


class BaseModel(metaclass=ModelMetaclass):
    model_config: dict[str, Any] = {}

    def __init__(self, **data: Any) -> None:
        config = self.model_config
        extra_policy = config.get("extra", "ignore")
        strip_whitespace = config.get("str_strip_whitespace", False)

        # Вызов model_validator(mode="before")
        raw_data = dict(data)
        for mv in self.__mv_before__:
            func = mv.__func__ if isinstance(mv, classmethod) else mv
            raw_data = func(self.__class__, raw_data)

        validated_values: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []

        # Проверка неизвестных полей при extra="forbid"
        known_aliases = {
            f_info.alias or f_name: f_name
            for f_name, f_info in self.__model_fields__.items()
        }
        known_names = set(self.__model_fields__.keys())

        if extra_policy == "forbid":
            for input_key in raw_data:
                if input_key not in known_names and input_key not in known_aliases:
                    errors.append({
                        "field": input_key,
                        "msg": f"Неизвестное поле '{input_key}' запрещено конфигурацией extra='forbid'",
                    })

        if errors:
            raise ValidationError(errors)

        for field_name, field_info in self.__model_fields__.items():
            lookup_key = field_info.alias if field_info.alias and field_info.alias in raw_data else field_name

            if lookup_key in raw_data:
                val = raw_data[lookup_key]
            elif field_info.default_factory is not None:
                val = field_info.default_factory()
            elif field_info.default is not ...:
                val = field_info.default
            else:
                errors.append({"field": field_name, "msg": f"Обязательное поле '{field_name}' отсутствует"})
                continue

            # Стрип пробелов
            if strip_whitespace and isinstance(val, str):
                val = val.strip()

            # field_validator(mode="before")
            if field_name in self.__fv_before__:
                for fv in self.__fv_before__[field_name]:
                    try:
                        func = fv.__func__ if isinstance(fv, classmethod) else fv
                        val = func(self.__class__, val)
                    except Exception as e:
                        errors.append({"field": field_name, "msg": str(e)})

            # Базовая валидация FieldInfo
            try:
                val = field_info.validate(field_name, val)
            except ValueError as e:
                errors.append({"field": field_name, "msg": str(e)})

            # field_validator(mode="after")
            if field_name in self.__fv_after__:
                for fv in self.__fv_after__[field_name]:
                    try:
                        func = fv.__func__ if isinstance(fv, classmethod) else fv
                        val = func(self.__class__, val)
                    except Exception as e:
                        errors.append({"field": field_name, "msg": str(e)})

            validated_values[field_name] = val

        if errors:
            raise ValidationError(errors)

        for k, v in validated_values.items():
            setattr(self, k, v)

        # Вызов model_validator(mode="after")
        for mv in self.__mv_after__:
            func = mv.__func__ if isinstance(mv, classmethod) else mv
            try:
                func(self)
            except Exception as e:
                raise ValidationError([{"field": "__all__", "msg": str(e)}]) from e

    def model_dump(self) -> dict[str, Any]:
        result = {}
        for field_name in self.__model_fields__:
            val = getattr(self, field_name)
            if isinstance(val, BaseModel):
                result[field_name] = val.model_dump()
            else:
                result[field_name] = val

        # Добавляем @computed_field
        for cf_name in self.__computed_fields__:
            func = getattr(self.__class__, cf_name)
            result[cf_name] = func(self)

        return result

    def model_dump_json(self) -> str:
        return json.dumps(self.model_dump(), default=str, ensure_ascii=False)

    @classmethod
    def model_validate(cls, data: dict[str, Any]) -> Self:
        return cls(**data)


# =====================================================================
# Набор тестов (unittest / pytest compatible)
# =====================================================================

class TestPydanticV2Engine(unittest.TestCase):
    def test_basic_validation_and_constraints(self) -> None:
        class ProductModel(BaseModel):
            sku: str = Field(pattern=r"^[A-Z]{3}-\d{3}$")
            price: float = Field(gt=0.0)
            stock: int = Field(ge=0, le=1000)

        # Корректные данные
        p = ProductModel(sku="ABC-123", price=19.99, stock=50)
        self.assertEqual(p.sku, "ABC-123")
        self.assertEqual(p.price, 19.99)
        self.assertEqual(p.stock, 50)

        # Некорректный SKU
        with self.assertRaises(ValidationError):
            ProductModel(sku="bad-sku", price=10.0, stock=10)

        # Отрицательная цена
        with self.assertRaises(ValidationError):
            ProductModel(sku="ABC-123", price=-5.0, stock=10)

    def test_field_validator_before_and_after(self) -> None:
        class RegistrationSchema(BaseModel):
            username: str = Field(min_length=3)
            email: str

            @field_validator("username", mode="before")
            @classmethod
            def clean_username(cls, v: str) -> str:
                return v.strip().lower()

            @field_validator("email", mode="after")
            @classmethod
            def check_domain(cls, v: str) -> str:
                if not v.endswith("@company.com"):
                    raise ValueError("Разрешены только корпоративные адреса @company.com")
                return v

        obj = RegistrationSchema(username="  JohnDoe  ", email="alice@company.com")
        self.assertEqual(obj.username, "johndoe")
        self.assertEqual(obj.email, "alice@company.com")

        # Недопустимый домен
        with self.assertRaises(ValidationError):
            RegistrationSchema(username="validuser", email="hacker@gmail.com")

    def test_model_validator_cross_field(self) -> None:
        class DateRangeBooking(BaseModel):
            start_day: int = Field(ge=1, le=31)
            end_day: int = Field(ge=1, le=31)

            @model_validator(mode="after")
            def check_order(self) -> Self:
                if self.end_day <= self.start_day:
                    raise ValueError("День окончания должен быть строго позже дня начала")
                return self

        # Успешный интервал
        b = DateRangeBooking(start_day=5, end_day=10)
        self.assertEqual(b.start_day, 5)

        # Ошибка: дата окончания раньше даты начала
        with self.assertRaises(ValidationError):
            DateRangeBooking(start_day=15, end_day=10)

    def test_computed_field_and_serialization(self) -> None:
        class CartItem(BaseModel):
            title: str
            unit_price: float
            quantity: int = 1

            @computed_field
            def total(self) -> float:
                return round(self.unit_price * self.quantity, 2)

        item = CartItem(title="Книга по FastAPI", unit_price=45.5, quantity=3)
        dump = item.model_dump()
        self.assertEqual(dump["title"], "Книга по FastAPI")
        self.assertEqual(dump["total"], 136.5)
        self.assertIn('"total": 136.5', item.model_dump_json())

    def test_config_extra_forbid(self) -> None:
        class StrictEntity(BaseModel):
            model_config = {"extra": "forbid"}
            allowed_prop: str

        with self.assertRaises(ValidationError):
            StrictEntity(allowed_prop="ok", malicious_field="injected")

    def test_dto_separation_pattern(self) -> None:
        class UserBase(BaseModel):
            email: str

        class UserCreate(UserBase):
            raw_password: str = Field(min_length=6)

        class UserRead(UserBase):
            id: int
            is_active: bool = True

        dto_in = UserCreate(email="user@site.ru", raw_password="secretpassword")
        # Имитируем сохранение в БД и создание ответа
        dto_out = UserRead(id=1, email=dto_in.email)
        out_dict = dto_out.model_dump()

        self.assertIn("id", out_dict)
        self.assertIn("email", out_dict)
        self.assertNotIn("raw_password", out_dict)


if __name__ == "__main__":
    unittest.main()
