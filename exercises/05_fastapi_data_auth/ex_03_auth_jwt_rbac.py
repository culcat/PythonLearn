#!/usr/bin/env python3
"""Практическое задание к Главе 03: Безопасность, Хеширование, JWT и RBAC.

Данный модуль содержит чистую криптографическую реализацию компонентов авторизации:
1. PasswordHasher: Хеширование PBKDF2-HMAC-SHA256 со случайной солью и защитой от timing-атак.
2. JWTHandler: Реализация RFC 7519 (HS256) с валидацией подписи, exp/iat/nbf и защитой от alg=none.
3. TokenManager: Двухтокенная схема (Access + Refresh), ротация и выявление кражи (Reuse Detection).
4. PermissionChecker: Ролевая модель доступа (RBAC) с проверкой конкретных разрешений.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any


class AuthenticationError(Exception):
    """Ошибка аутентификации (HTTP 401)."""


class PermissionDeniedError(Exception):
    """Ошибка авторизации / недостаточно прав (HTTP 403)."""


class PasswordHasher:
    """Безопасное хеширование паролей на базе PBKDF2-HMAC-SHA256."""

    ITERATIONS = 100_000

    @classmethod
    def hash_password(cls, password: str) -> str:
        salt = secrets.token_bytes(16)
        pwd_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, cls.ITERATIONS
        )
        # Формат: $pbkdf2$iterations$salt_hex$hash_hex
        return f"$pbkdf2${cls.ITERATIONS}${salt.hex()}${pwd_hash.hex()}"

    @classmethod
    def verify_password(cls, password: str, hashed_str: str) -> bool:
        parts = hashed_str.split("$")
        if len(parts) != 5 or parts[1] != "pbkdf2":
            return False
        iterations = int(parts[2])
        salt = bytes.fromhex(parts[3])
        expected_hash = bytes.fromhex(parts[4])

        actual_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        # Защита от timing-атак через constant-time сравнение
        return hmac.compare_digest(actual_hash, expected_hash)


class JWTHandler:
    """Криптографический обработчик JWT (HS256) в соответствии со стандартом RFC 7519."""

    @staticmethod
    def _b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

    @staticmethod
    def _b64url_decode(segment: str) -> bytes:
        rem = len(segment) % 4
        if rem > 0:
            segment += "=" * (4 - rem)
        return base64.urlsafe_b64decode(segment.encode("utf-8"))

    @classmethod
    def encode(cls, payload: dict[str, Any], secret_key: str) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        header_b64 = cls._b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_b64 = cls._b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        signature = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
        sig_b64 = cls._b64url_encode(signature)

        return f"{header_b64}.{payload_b64}.{sig_b64}"

    @classmethod
    def decode(cls, token: str, secret_key: str) -> dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthenticationError("Некорректный формат JWT токена (ожидается 3 сегмента).")

        header_b64, payload_b64, sig_b64 = parts

        # Проверка и декодирование заголовка
        try:
            header = json.loads(cls._b64url_decode(header_b64).decode("utf-8"))
        except Exception as exc:
            raise AuthenticationError("Ошибка декодирования заголовка JWT.") from exc

        # Защита от атаки alg: none
        if header.get("alg") != "HS256":
            raise AuthenticationError(f"Неподдерживаемый или небезопасный алгоритм: {header.get('alg')}")

        # Проверка криптографической подписи HMAC-SHA256
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        expected_sig = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual_sig = cls._b64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            raise AuthenticationError("Недействительная подпись токена (Signature verification failed).")

        # Декодирование полезной нагрузки
        try:
            payload = json.loads(cls._b64url_decode(payload_b64).decode("utf-8"))
        except Exception as exc:
            raise AuthenticationError("Ошибка декодирования полезной нагрузки JWT.") from exc

        # Валидация стандартных клеймов
        now = int(time.time())
        if "exp" in payload and now >= payload["exp"]:
            raise AuthenticationError("Срок действия токена истек (Token expired).")
        if "nbf" in payload and now < payload["nbf"]:
            raise AuthenticationError("Токен еще не активен (Token not active yet).")

        return payload


class TokenManager:
    """Менеджер двухтокенной схемы, ротации и защиты от кражи (Reuse Detection)."""

    def __init__(self, secret_key: str) -> None:
        self.secret_key = secret_key
        # Хранилище активных и отозванных refresh токенов: {family_id: {"active": jti, "invalidated": set()}}
        self._families: dict[str, dict[str, Any]] = {}

    def issue_token_pair(
        self, user_id: str, role: str, permissions: list[str], family_id: str | None = None
    ) -> tuple[str, str]:
        now = int(time.time())
        if family_id is None:
            family_id = secrets.token_hex(8)
            self._families[family_id] = {"active": None, "revoked": set()}

        access_jti = secrets.token_hex(8)
        refresh_jti = secrets.token_hex(8)

        access_payload = {
            "sub": user_id,
            "role": role,
            "permissions": permissions,
            "type": "access",
            "jti": access_jti,
            "iat": now,
            "exp": now + 900,  # 15 минут
        }

        refresh_payload = {
            "sub": user_id,
            "role": role,
            "type": "refresh",
            "family_id": family_id,
            "jti": refresh_jti,
            "iat": now,
            "exp": now + 86400 * 7,  # 7 дней
        }

        self._families[family_id]["active"] = refresh_jti

        access_token = JWTHandler.encode(access_payload, self.secret_key)
        refresh_token = JWTHandler.encode(refresh_payload, self.secret_key)
        return access_token, refresh_token

    def rotate_refresh_token(
        self, refresh_token: str, permissions: list[str]
    ) -> tuple[str, str]:
        payload = JWTHandler.decode(refresh_token, self.secret_key)
        if payload.get("type") != "refresh":
            raise AuthenticationError("Ожидался токен типа refresh.")

        family_id = payload.get("family_id")
        jti = payload.get("jti")

        if not family_id or family_id not in self._families:
            raise AuthenticationError("Неизвестное семейство токенов.")

        family = self._families[family_id]

        # Обнаружение повторного использования (Token Reuse Detection)
        if jti in family["revoked"]:
            # Взлом! Аннулируем всё семейство токенов пользователя
            del self._families[family_id]
            raise AuthenticationError("Обнаружена попытка повторного использования токена! Сессия аннулирована.")

        if family["active"] != jti:
            raise AuthenticationError("Недействительный refresh токен.")

        # Помечаем текущий jti как использованный
        family["revoked"].add(jti)

        # Выпускаем новую пару в рамках того же семейства
        return self.issue_token_pair(
            user_id=payload["sub"],
            role=payload["role"],
            permissions=permissions,
            family_id=family_id,
        )


@dataclass
class UserContext:
    user_id: str
    role: str
    permissions: list[str] = field(default_factory=list)


class PermissionChecker:
    """Проверка прав доступа (RBAC)."""

    def __init__(self, required_permissions: list[str]) -> None:
        self.required_permissions = set(required_permissions)

    def check(self, user: UserContext) -> None:
        if user.role == "superadmin":
            return

        missing = self.required_permissions - set(user.permissions)
        if missing:
            raise PermissionDeniedError(
                f"Доступ запрещен. Отсутствуют обязательные права: {sorted(missing)}"
            )


# ---------------------------------------------------------------------------
# Модульные тесты
# ---------------------------------------------------------------------------
import unittest


class TestAuthAndSecurity(unittest.TestCase):
    def setUp(self) -> None:
        self.secret = "ultra-secret-test-key-32-chars-long!"
        self.token_manager = TokenManager(self.secret)

    def test_password_hasher_verify(self) -> None:
        """Хеширование пароля и успешная проверка."""
        hashed = PasswordHasher.hash_password("SuperSecureP@ssw0rd")
        self.assertTrue(hashed.startswith("$pbkdf2$100000$"))
        self.assertTrue(PasswordHasher.verify_password("SuperSecureP@ssw0rd", hashed))
        self.assertFalse(PasswordHasher.verify_password("WrongPassword", hashed))

    def test_jwt_encode_decode_success(self) -> None:
        """Кодирование и декодирование валидного JWT токена."""
        payload = {"sub": "user_123", "role": "admin", "exp": int(time.time()) + 300}
        token = JWTHandler.encode(payload, self.secret)
        decoded = JWTHandler.decode(token, self.secret)
        self.assertEqual(decoded["sub"], "user_123")
        self.assertEqual(decoded["role"], "admin")

    def test_jwt_tampered_signature_rejected(self) -> None:
        """Попытка подделки полезной нагрузки должна приводить к ошибке подписи."""
        payload = {"sub": "user_123", "role": "viewer", "exp": int(time.time()) + 300}
        token = JWTHandler.encode(payload, self.secret)

        parts = token.split(".")
        # Меняем роль на 'admin' в base64
        fake_payload = {"sub": "user_123", "role": "admin", "exp": int(time.time()) + 300}
        parts[1] = JWTHandler._b64url_encode(json.dumps(fake_payload).encode("utf-8"))
        tampered_token = ".".join(parts)

        with self.assertRaises(AuthenticationError) as ctx:
            JWTHandler.decode(tampered_token, self.secret)
        self.assertIn("подпись", str(ctx.exception).lower())

    def test_jwt_expired_token_rejected(self) -> None:
        """Истекший токен отклоняется."""
        payload = {"sub": "user_123", "exp": int(time.time()) - 10}
        token = JWTHandler.encode(payload, self.secret)
        with self.assertRaises(AuthenticationError) as ctx:
            JWTHandler.decode(token, self.secret)
        self.assertIn("истек", str(ctx.exception).lower())

    def test_jwt_alg_none_rejected(self) -> None:
        """Защита от уязвимости alg: none."""
        header = {"alg": "none", "typ": "JWT"}
        payload = {"sub": "attacker"}
        h_b64 = JWTHandler._b64url_encode(json.dumps(header).encode("utf-8"))
        p_b64 = JWTHandler._b64url_encode(json.dumps(payload).encode("utf-8"))
        none_token = f"{h_b64}.{p_b64}."

        with self.assertRaises(AuthenticationError):
            JWTHandler.decode(none_token, self.secret)

    def test_refresh_token_rotation_and_reuse_detection(self) -> None:
        """Ротация refresh-токена и обнаружение повторного использования (Reuse Detection)."""
        _, refresh_1 = self.token_manager.issue_token_pair(
            "user_42", "manager", ["reports:read"]
        )

        # 1-я ротация: успешна, выдает refresh_2
        _, refresh_2 = self.token_manager.rotate_refresh_token(
            refresh_1, ["reports:read"]
        )
        self.assertNotEqual(refresh_1, refresh_2)

        # Повторная попытка использовать уже отработанный refresh_1 (симуляция кражи)
        with self.assertRaises(AuthenticationError) as ctx:
            self.token_manager.rotate_refresh_token(refresh_1, ["reports:read"])
        self.assertIn("повторного использования", str(ctx.exception))

        # После обнаружения атаки даже refresh_2 должен быть аннулирован
        with self.assertRaises(AuthenticationError):
            self.token_manager.rotate_refresh_token(refresh_2, ["reports:read"])

    def test_rbac_permission_checker(self) -> None:
        """Проверка прав RBAC."""
        editor = UserContext("1", role="editor", permissions=["article:write", "article:read"])
        viewer = UserContext("2", role="viewer", permissions=["article:read"])
        admin = UserContext("3", role="superadmin", permissions=[])

        checker = PermissionChecker(["article:write"])

        # Editor имеет разрешение -> проходит без исключений
        checker.check(editor)

        # Viewer не имеет article:write -> PermissionDeniedError
        with self.assertRaises(PermissionDeniedError):
            checker.check(viewer)

        # Superadmin имеет полный доступ ко всем ресурсам
        checker.check(admin)


if __name__ == "__main__":
    unittest.main()
