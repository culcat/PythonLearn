#!/usr/bin/env python3
"""Упражнение 05: Типизированная конфигурация окружения и Graceful Shutdown.

В этом задании реализуются ключевые компоненты для подготовки сервиса к Production:
1. SecretStr: класс безопасного хранения секретов (предотвращает утечки в логи)
2. TypedSettings: декларативный парсер переменных окружения с автоприведением типов (12-Factor App)
3. GracefulShutdownManager: диспетчер корректного завершения работы при сигнале SIGTERM
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import os
from typing import Any, get_type_hints
import unittest


# ============================================================================
# 1. ЗАЩИТА СЕКРЕТОВ: SecretStr
# ============================================================================

class SecretStr:
    """Обертка над строковым секретом, скрывающая значение при выводе в логи."""

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"Значение секрета должно быть строкой, получено: {type(value).__name__}")
        self._secret_value = value

    def get_secret_value(self) -> str:
        return self._secret_value

    def __repr__(self) -> str:
        return "SecretStr('**********')"

    def __str__(self) -> str:
        return "**********"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretStr):
            return self._secret_value == other._secret_value
        if isinstance(other, str):
            return self._secret_value == other
        return False


# ============================================================================
# 2. ДЕКЛАРАТИВНЫЙ ПАРСЕР ОКРУЖЕНИЯ (12-Factor App)
# ============================================================================

class TypedSettings:
    """Базовый класс типизированных настроек приложения из переменных окружения.
    
    Поддерживает строгую типизацию по аннотациям: int, str, bool, SecretStr, list[str].
    """

    prefix: str = ""

    def __init__(self, env_dict: dict[str, str] | None = None) -> None:
        source_env = os.environ if env_dict is None else env_dict
        type_hints = get_type_hints(self.__class__)
        missing_fields: list[str] = []

        for field_name, expected_type in type_hints.items():
            if field_name.startswith("_") or field_name == "prefix":
                continue

            env_key = f"{self.prefix}{field_name.upper()}"
            has_default = hasattr(self.__class__, field_name)
            default_val = getattr(self.__class__, field_name) if has_default else None

            if env_key in source_env:
                raw_val = source_env[env_key]
                converted_val = self._convert_value(raw_val, expected_type)
                setattr(self, field_name, converted_val)
            elif has_default:
                setattr(self, field_name, default_val)
            else:
                missing_fields.append(f"{field_name} (требуется переменная {env_key})")

        if missing_fields:
            raise ValueError(
                f"Отсутствуют обязательные переменные конфигурации: {', '.join(missing_fields)}"
            )

    @classmethod
    def _convert_value(cls, raw: str, target_type: Any) -> Any:
        if target_type is SecretStr:
            return SecretStr(raw)

        if target_type is bool:
            clean = raw.strip().lower()
            if clean in ("true", "1", "yes", "t"):
                return True
            if clean in ("false", "0", "no", "f"):
                return False
            raise ValueError(f"Невозможно преобразовать '{raw}' в bool")

        if target_type is int:
            return int(raw)

        if target_type is str:
            return raw

        # Поддержка list[str]
        origin = getattr(target_type, "__origin__", None)
        if origin is list:
            return [part.strip() for part in raw.split(",") if part.strip()]

        return raw


# ============================================================================
# 3. ДИСПЕТЧЕР GRACEFUL SHUTDOWN
# ============================================================================

@dataclass(order=True)
class _PrioritizedHook:
    priority: int
    name: str = field(compare=False)
    callback: Callable[[], Awaitable[None]] = field(compare=False)


class GracefulShutdownManager:
    """Управляет корректной остановкой сервиса при получении сигнала SIGTERM.
    
    Выполняет зарегистрированные хуки очистки ресурсов в порядке их приоритета
    (меньшее число = выше приоритет).
    """

    def __init__(self) -> None:
        self.is_shutting_down: bool = False
        self._hooks: list[_PrioritizedHook] = []
        self.executed_hooks: list[str] = []

    def register_hook(
        self,
        name: str,
        callback: Callable[[], Awaitable[None]],
        priority: int = 100,
    ) -> None:
        self._hooks.append(_PrioritizedHook(priority=priority, name=name, callback=callback))
        self._hooks.sort()

    async def shutdown(self, timeout: float = 5.0) -> bool:
        """Инициирует процесс остановки с ограничением по времени."""
        self.is_shutting_down = True

        async def _run_all() -> None:
            for hook in self._hooks:
                await hook.callback()
                self.executed_hooks.append(hook.name)

        try:
            await asyncio.wait_for(_run_all(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


# ============================================================================
# 4. ТЕСТЫ НА BAZЕ UNITTEST
# ============================================================================

class AppTestSettings(TypedSettings):
    prefix: str = "APP_"
    app_env: str = "production"
    port: int = 8000
    debug: bool = False
    secret_key: SecretStr
    allowed_hosts: list[str] = ["localhost"]


class TestSecretStr(unittest.TestCase):
    def test_secret_is_masked(self) -> None:
        secret = SecretStr("my-super-secret-password")
        self.assertEqual(str(secret), "**********")
        self.assertIn("**********", repr(secret))
        self.assertNotIn("my-super-secret-password", repr(secret))
        self.assertEqual(secret.get_secret_value(), "my-super-secret-password")

    def test_equality(self) -> None:
        s1 = SecretStr("token")
        s2 = SecretStr("token")
        self.assertEqual(s1, s2)
        self.assertEqual(s1, "token")


class TestTypedSettings(unittest.TestCase):
    def test_successful_parsing_with_defaults(self) -> None:
        env = {
            "APP_SECRET_KEY": "super_secret_jwt_key",
            "APP_PORT": "9090",
            "APP_DEBUG": "true",
            "APP_ALLOWED_HOSTS": "api.domain.com, web.domain.com",
        }
        config = AppTestSettings(env)
        self.assertEqual(config.app_env, "production")  # Значение по умолчанию
        self.assertEqual(config.port, 9090)
        self.assertTrue(config.debug)
        self.assertEqual(config.secret_key.get_secret_value(), "super_secret_jwt_key")
        self.assertEqual(config.allowed_hosts, ["api.domain.com", "web.domain.com"])

    def test_missing_required_field_raises_value_error(self) -> None:
        env = {"APP_PORT": "8080"}  # Не передан обязательный secret_key
        with self.assertRaises(ValueError) as ctx:
            AppTestSettings(env)
        self.assertIn("secret_key", str(ctx.exception))


class TestGracefulShutdown(unittest.IsolatedAsyncioTestCase):
    async def test_hooks_executed_in_priority_order(self) -> None:
        manager = GracefulShutdownManager()
        execution_order: list[str] = []

        async def stop_http_listeners() -> None:
            execution_order.append("http")

        async def flush_metrics() -> None:
            execution_order.append("metrics")

        async def close_db_pool() -> None:
            execution_order.append("database")

        # Регистрируем в произвольном порядке с явным приоритетом
        manager.register_hook("database", close_db_pool, priority=30)
        manager.register_hook("http", stop_http_listeners, priority=10)
        manager.register_hook("metrics", flush_metrics, priority=20)

        success = await manager.shutdown(timeout=2.0)
        self.assertTrue(success)
        self.assertTrue(manager.is_shutting_down)
        # Ожидаемый порядок: 10 -> 20 -> 30
        self.assertEqual(execution_order, ["http", "metrics", "database"])
        self.assertEqual(manager.executed_hooks, ["http", "metrics", "database"])

    async def test_shutdown_timeout_handling(self) -> None:
        manager = GracefulShutdownManager()

        async def hanging_hook() -> None:
            await asyncio.sleep(1.0)

        manager.register_hook("hanging", hanging_hook, priority=1)
        # Устанавливаем короткий таймаут 0.05 сек
        success = await manager.shutdown(timeout=0.05)
        self.assertFalse(success)


if __name__ == "__main__":
    unittest.main()
