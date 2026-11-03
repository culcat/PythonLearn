#!/usr/bin/env python3
"""Упражнение 04: Наблюдаемость (Observability) — логирование, метрики и Health Checks.

В этом задании реализуются компоненты телеметрии корпоративного уровня:
1. StructuredJsonLogger: структурированный JSON-логгер с привязкой Correlation-ID через ContextVar
2. Prometheus Metrics: классы Counter и Histogram с вычислением перцентилей (p50, p95, p99)
3. HealthCheckAggregator: агрегатор зондов Liveness (/healthz) и Readiness (/readyz)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import math
from typing import Any
import unittest


# ============================================================================
# 1. СТРУКТУРИРОВАННОЕ JSON-ЛОГИРОВАНИЕ И CORRELATION-ID
# ============================================================================

CORRELATION_ID_CTX: ContextVar[str] = ContextVar("correlation_id", default="")


class StructuredJsonLogger:
    """Генератор структурированных логов в формате JSON.
    
    Автоматически обогащает каждую запись таймстемпом ISO 8601 и Correlation-ID
    из текущего асинхронного контекста contextvars.
    """

    def __init__(self) -> None:
        self.logs_buffer: list[dict[str, Any]] = []

    def log(self, level: str, message: str, **kwargs: Any) -> str:
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level.upper(),
            "message": message,
            "correlation_id": CORRELATION_ID_CTX.get() or "none",
        }
        record.update(kwargs)
        self.logs_buffer.append(record)
        return json.dumps(record, ensure_ascii=False)

    def info(self, message: str, **kwargs: Any) -> str:
        return self.log("INFO", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> str:
        return self.log("ERROR", message, **kwargs)


# ============================================================================
# 2. МЕТРИКИ PROMETHEUS: COUNTER И HISTOGRAM
# ============================================================================

class Counter:
    """Монотонно возрастающая числовая метрика Prometheus с поддержкой лейблов."""

    def __init__(self, name: str, description: str, label_names: tuple[str, ...] = ()) -> None:
        self.name = name
        self.description = description
        self.label_names = sorted(label_names)
        self._values: dict[tuple[tuple[str, str], ...], float] = {}

    def _normalize_labels(self, labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((k, str(v)) for k, v in labels.items() if k in self.label_names))

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        if amount < 0:
            raise ValueError("Счетчик Counter не может уменьшаться")
        key = self._normalize_labels(labels)
        self._values[key] = self._values.get(key, 0.0) + amount

    def get_value(self, **labels: str) -> float:
        key = self._normalize_labels(labels)
        return self._values.get(key, 0.0)


class Histogram:
    """Метрика распределения значений (задержек) с расчетом процентилей (p50, p95, p99)."""

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description
        self.observations: list[float] = []

    def observe(self, value: float) -> None:
        self.observations.append(value)

    @property
    def count(self) -> int:
        return len(self.observations)

    @property
    def total_sum(self) -> float:
        return sum(self.observations)

    def percentile(self, p: float) -> float:
        """Вычисляет перцентиль p (0 <= p <= 100) по собранным наблюдениям."""
        if not self.observations:
            return 0.0
        if not (0.0 <= p <= 100.0):
            raise ValueError("Перцентиль должен быть в диапазоне от 0 до 100")

        sorted_obs = sorted(self.observations)
        k = (len(sorted_obs) - 1) * (p / 100.0)
        floor_index = math.floor(k)
        ceil_index = math.ceil(k)

        if floor_index == ceil_index:
            return sorted_obs[int(k)]

        d0 = sorted_obs[floor_index] * (ceil_index - k)
        d1 = sorted_obs[ceil_index] * (k - floor_index)
        return d0 + d1


# ============================================================================
# 3. АГРЕГАТОР HEALTH CHECKS: LIVENESS (/healthz) И READINESS (/readyz)
# ============================================================================

class HealthStatus(str, Enum):
    UP = "UP"
    DOWN = "DOWN"


@dataclass
class HealthCheckResult:
    status: HealthStatus
    details: dict[str, str] = field(default_factory=dict)


class HealthCheckAggregator:
    """Диспетчер зондов Liveness и Readiness."""

    def __init__(self) -> None:
        self._probes: dict[str, Callable[[], Awaitable[bool]]] = {}

    def register_readiness_probe(self, name: str, probe: Callable[[], Awaitable[bool]]) -> None:
        self._probes[name] = probe

    async def check_liveness(self) -> HealthCheckResult:
        """Liveness probe: процесс жив, базовый цикл событий отвечает."""
        return HealthCheckResult(status=HealthStatus.UP, details={"process": "alive"})

    async def check_readiness(self) -> HealthCheckResult:
        """Readiness probe: опрашивает все зарегистрированные внешние сервисы."""
        details: dict[str, str] = {}
        all_ok = True

        for name, probe in self._probes.items():
            try:
                is_ready = await probe()
                if is_ready:
                    details[name] = "UP"
                else:
                    details[name] = "DOWN"
                    all_ok = False
            except Exception:
                details[name] = "DOWN"
                all_ok = False

        status = HealthStatus.UP if all_ok else HealthStatus.DOWN
        return HealthCheckResult(status=status, details=details)


# ============================================================================
# 4. ТЕСТЫ НА BAZЕ UNITTEST
# ============================================================================

class TestStructuredLogging(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = StructuredJsonLogger()

    def test_log_output_with_contextvar_correlation_id(self) -> None:
        token = CORRELATION_ID_CTX.set("trace-abc-123")
        try:
            json_str = self.logger.info("Заказ оформлен", order_id=42, amount=999.0)
            data = json.loads(json_str)

            self.assertEqual(data["level"], "INFO")
            self.assertEqual(data["message"], "Заказ оформлен")
            self.assertEqual(data["correlation_id"], "trace-abc-123")
            self.assertEqual(data["order_id"], 42)
            self.assertEqual(data["amount"], 999.0)
            self.assertIn("timestamp", data)
        finally:
            CORRELATION_ID_CTX.reset(token)

    def test_log_without_correlation_id_defaults_to_none(self) -> None:
        json_str = self.logger.error("Критический сбой")
        data = json.loads(json_str)
        self.assertEqual(data["correlation_id"], "none")
        self.assertEqual(data["level"], "ERROR")


class TestPrometheusMetrics(unittest.TestCase):
    def test_counter_increments_with_labels(self) -> None:
        counter = Counter(
            name="http_requests_total",
            description="Total requests",
            label_names=("method", "status"),
        )
        counter.inc(1, method="GET", status="200")
        counter.inc(2, method="GET", status="200")
        counter.inc(1, method="POST", status="500")

        self.assertEqual(counter.get_value(method="GET", status="200"), 3.0)
        self.assertEqual(counter.get_value(method="POST", status="500"), 1.0)
        self.assertEqual(counter.get_value(method="GET", status="404"), 0.0)

    def test_histogram_percentiles(self) -> None:
        hist = Histogram("http_duration", "Request duration in seconds")
        # Добавляем 100 значений от 0.01 до 1.00
        for i in range(1, 101):
            hist.observe(i * 0.01)

        self.assertEqual(hist.count, 100)
        self.assertAlmostEqual(hist.percentile(50), 0.505, places=2)   # p50 (медиана)
        self.assertAlmostEqual(hist.percentile(95), 0.9505, places=2)  # p95
        self.assertAlmostEqual(hist.percentile(99), 0.9901, places=2)  # p99


class TestHealthChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.aggregator = HealthCheckAggregator()

    async def test_liveness_always_up(self) -> None:
        res = await self.aggregator.check_liveness()
        self.assertEqual(res.status, HealthStatus.UP)
        self.assertEqual(res.details["process"], "alive")

    async def test_readiness_all_dependencies_up(self) -> None:
        async def check_db() -> bool:
            return True

        async def check_redis() -> bool:
            return True

        self.aggregator.register_readiness_probe("postgres", check_db)
        self.aggregator.register_readiness_probe("redis", check_redis)

        res = await self.aggregator.check_readiness()
        self.assertEqual(res.status, HealthStatus.UP)
        self.assertEqual(res.details["postgres"], "UP")
        self.assertEqual(res.details["redis"], "UP")

    async def test_readiness_fails_when_one_dependency_down(self) -> None:
        async def check_db() -> bool:
            return True

        async def check_failing_broker() -> bool:
            raise ConnectionError("RabbitMQ недоступен")

        self.aggregator.register_readiness_probe("postgres", check_db)
        self.aggregator.register_readiness_probe("rabbitmq", check_failing_broker)

        res = await self.aggregator.check_readiness()
        self.assertEqual(res.status, HealthStatus.DOWN)
        self.assertEqual(res.details["postgres"], "UP")
        self.assertEqual(res.details["rabbitmq"], "DOWN")


if __name__ == "__main__":
    unittest.main()
