---
title: "05. Production-деплой: Pydantic Settings, multi-stage Docker (uv), Graceful Shutdown, тюнинг и CI/CD"
aliases:
  - "Docker FastAPI uv"
  - "Production FastAPI Deploy"
  - "Graceful Shutdown FastAPI"
  - "Performance Tuning FastAPI"
tags:
  - docker
  - uv
  - ci-cd
  - pydantic-settings
  - graceful-shutdown
  - performance
  - production
module: "06_FastAPI_Pro_Production"
created: 2026-11-03
status: complete
---

# 05. Production-деплой: Pydantic Settings, multi-stage Docker (uv), Graceful Shutdown, тюнинг и CI/CD

Написание чистого и протестированного кода — лишь половина пути. В промышленной эксплуатации сервис должен безопасно конфигурироваться по стандарту **12-Factor App**, упаковываться в минималистичные защищенные Docker-контейнеры, корректно завершать активные транзакции при деплое (**Graceful Shutdown**) и проходить автоматические проверки в CI/CD пайплайне.

В этой главе мы разберем полный цикл вывода FastAPI в Production: типизацию настроек со `SecretStr`, многоэтапную сборку образов с ультрабыстрым пакетным менеджером `uv`, настройку воркеров, обработку `SIGTERM`, тюнинг производительности (`uvloop`, `orjson`, connection pooling) и готовый пайплайн GitHub Actions.

---

## 1. Конфигурация по принципам 12-Factor App (`pydantic-settings`)

Согласно методологии **12-Factor App**, конфигурация сервиса должна строго отделяться от исполняемого кода и передаваться через переменные окружения (`Environment Variables`).

### Защита секретов и вложенные структуры

Библиотека `pydantic-settings` обеспечивает строгую типизацию, валидацию при старте и сокрытие паролей через тип `SecretStr` (предотвращает случайную утечку токенов в логи или Sentry):

```python
from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class DatabaseSettings(BaseSettings):
    url: PostgresDsn = Field(
        default="postgresql+asyncpg://user:pass@localhost:5432/production_db",
        alias="DATABASE_URL",
    )
    pool_size: int = Field(default=20, ge=5, le=100)
    max_overflow: int = Field(default=10, ge=0, le=50)

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )
    
    app_env: str = Field(default="production", alias="APP_ENV")
    debug: bool = Field(default=False, alias="DEBUG")
    secret_key: SecretStr = Field(alias="SECRET_KEY")
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)

# Инициализация (валидируется при старте приложения)
settings = AppSettings()
```

> [!IMPORTANT] Преимущества `SecretStr`
> При вызове `print(settings.secret_key)` или выводе в лог отобразится безопасная строка: `**********`.
> Для получения реального значения необходимо явно вызвать метод `.get_secret_value()`.

---

## 2. Производственная упаковка в Docker: Multi-stage сборка с `uv`

Менеджер пакетов **`uv`** (написанный на Rust) выполняет установку зависимостей в 10–50 раз быстрее `pip`. 

### Стандарты промышленного `Dockerfile`:
1. **Multi-stage сборка**: Инструменты сборки (компиляторы C/Rust, пакетный менеджер) остаются на сборочном этапе и не попадают в итоговый образ.
2. **Кэширование слоев**: Зависимости (`pyproject.toml`, `uv.lock`) копируются и устанавливаются до копирования исходного кода приложения.
3. **Безопасность (Non-root user)**: Приложение запускается под системным пользователем без прав суперпользователя (`appuser` с UID 10001).

```mermaid
flowchart TD
    subgraph Builder["Этап 1: Builder (ghcr.io/astral-sh/uv + python:3.12-slim)"]
        B1["Установка системных зависимостей (gcc, libpq-dev)"]
        B2["Копирование pyproject.toml и uv.lock"]
        B3["uv sync --frozen --no-dev (создание /app/.venv)"]
        B1 --> B2 --> B3
    end

    subgraph Runtime["Этап 2: Runtime (python:3.12-slim)"]
        R1["Создание непривилегированного пользователя appuser (UID 10001)"]
        R2["Копирование виртуального окружения /app/.venv из Builder"]
        R3["Копирование исходного кода src/"]
        R4["USER appuser: запуск gunicorn / uvicorn"]
        R1 --> R2 --> R3 --> R4
    end

    B3 -.->|Копирование .venv| R2

    style Builder fill:#2e3440,stroke:#88c0d0,stroke-width:2px,color:#eceff4
    style Runtime fill:#3b4252,stroke:#a3be8c,stroke-width:2px,color:#eceff4
```

### Эталонный производственный `Dockerfile`:

```dockerfile
# ==========================================
# Этап 1: Сборка зависимостей (Builder)
# ==========================================
FROM ghcr.io/astral-sh/uv:0.4-python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Кэширование слоев: сначала зависимости
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# ==========================================
# Этап 2: Финальный образ (Runtime)
# ==========================================
FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

# Создание безопасного непривилегированного пользователя
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /sbin/nologin -d /app appuser

# Копируем готовое виртуальное окружение из builder
COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --chown=appuser:appgroup . /app

# Переменные среды окружения
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 3. Запуск в продакшене и Graceful Shutdown (`SIGTERM`)

### Gunicorn + `UvicornWorker` vs Kubernetes

- **На виртуальных машинах (Bare-Metal / VPS):**
  Используется процесс-менеджер **Gunicorn** с воркерами `UvicornWorker`.
  Формула количества процессов:
  $$N_{\text{workers}} = 2 \times \text{CPUs} + 1$$
  Gunicorn следит за падением воркеров и автоматически перезапускает их.

- **В оркестраторе Kubernetes:**
  Рекомендуется подход: **1 контейнер = 1 процесс Uvicorn**.
  Масштабирование выполняется на уровне пода через **Horizontal Pod Autoscaler (HPA)** по метрикам CPU и latency.

### Механика Graceful Shutdown (Корректное завершение)

При деплое новой версии Kubernetes отправляет поду сигнал `SIGTERM`. По умолчанию дается `terminationGracePeriodSeconds` (обычно 30 секунд):

```mermaid
sequenceDiagram
    autonumber
    participant K8s as Kubernetes / OS
    participant App as FastAPI App (Lifespan)
    participant Pool as DB Pool / Clients
    participant InFlight as In-Flight HTTP Requests

    K8s->>App: Сигнал SIGTERM (Начало остановки)
    App->>App: Перевод /readyz в статус DOWN (Снятие входящего трафика)
    App->>InFlight: Дожидаемся завершения активных запросов (до таймаута)
    InFlight-->>App: Все запросы выполнены (HTTP 200)
    App->>Pool: Закрытие соединений с PostgreSQL и Redis
    Pool-->>App: Соединения закрыты
    App->>K8s: Успешный выход с кодом 0
```

### Реализация в `lifespan` FastAPI:

```python
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI
import asyncio
import logging

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # --- Startup logic ---
    logger.info("Запуск приложения: инициализация пула БД...")
    db_pool = await init_db_pool()
    app.state.db_pool = db_pool
    
    yield  # Приложение принимает запросы
    
    # --- Shutdown logic (вызывается при SIGTERM / SIGINT) ---
    logger.info("Получен сигнал завершения. Остановка приема новых задач...")
    # Даем 5 секунд на завершение фоновых транзакций
    await asyncio.sleep(1)
    
    logger.info("Закрытие пула соединений с БД...")
    await db_pool.close()
    logger.info("Graceful shutdown завершен успешно.")

app = FastAPI(lifespan=lifespan)
```

---

## 4. Тюнинг производительности

### 1. `uvloop`: Сверхбыстрый асинхронный цикл событий
`uvloop` — это замена стандартного `asyncio.EventLoop`, написанная на Cython поверх библиотеки `libuv` (на которой работает Node.js). Она ускоряет сетевой ввод-вывод в 2–4 раза.
```python
import uvloop
uvloop.install()
```

### 2. `orjson`: Быстрая сериализация JSON
Стандартный модуль `json` и сериализатор FastAPI работают на чистом Python. Библиотека `orjson` написана на Rust и сериализует даты, UUID и Pydantic-модели в 5–10 раз быстрее.
```python
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

app = FastAPI(default_response_class=ORJSONResponse)
```

### 3. Тюнинг пула соединений SQLAlchemy (asyncpg)
```python
engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,           # Количество постоянных открытых соединений
    max_overflow=10,        # Максимальный всплеск дополнительных соединений
    pool_timeout=30,        # Таймаут ожидания свободного соединения из пула
    pool_recycle=1800,      # Пересоздание соединения каждые 30 минут (защита от сетевых обрывов)
    pool_pre_ping=True,     # Проверка живости соединения перед отдачей приложению (SELECT 1)
)
```

### 4. Профилирование с `py-spy`
`py-spy` — это профилировщик выборки (sampling profiler), который подключается к работающему процессу Python без остановки его работы и не влияя на скорость:
```bash
# Генерация интерактивного Flamegraph работающего сервиса
py-spy record -o profile.svg --pid 12345 --duration 60
```

---

## 5. Промышленный CI/CD пайплайн (GitHub Actions)

Создайте файл `.github/workflows/ci.yml`:

```yaml
name: CI/CD Production Pipeline

on:
  push:
    branches: [main, release/*]
  pull_request:
    branches: [main]

jobs:
  lint-and-typecheck:
    name: Code Quality (Ruff & Mypy)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true

      - name: Set up Python
        run: uv python install 3.12

      - name: Run Ruff Linter
        run: uv run ruff check .

      - name: Run Ruff Formatter Check
        run: uv run ruff format --check .

      - name: Run Mypy Static Type Analysis
        run: uv run mypy --strict src/

  test:
    name: Automated Tests (Pytest)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3

      - name: Run Pytest with Coverage
        run: uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=85

  docker-build:
    name: Build & Push Docker Image
    needs: [lint-and-typecheck, test]
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and Push Image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ghcr.io/${{ github.repository }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

---

## Резюме

1. Храните настройки строго в переменных окружения с валидацией через **`pydantic-settings`** и скрывайте токены с помощью **`SecretStr`**.
2. Собирайте контейнеры в **Multi-stage режиме с `uv`** и запускайте сервис от **непривилегированного пользователя (Non-root)**.
3. Корректно перехватывайте сигнал **`SIGTERM`** и реализуйте **Graceful Shutdown** в `lifespan` для защиты активных транзакций пользователей.
4. Ускоряйте сетевой I/O с помощью **`uvloop`** и **`orjson`**, и контролируйте пулы соединений базы данных.
5. Автоматизируйте все проверки качества в **GitHub Actions** (`ruff`, `mypy`, `pytest`).

---

## Практическое задание

Реализуйте и протестируйте модули для производственного деплоя: типизированный загрузчик конфигурации окружения с валидацией типов и маскировкой `SecretStr`, а также диспетчер жизненного цикла Graceful Shutdown с поддержкой таймаута и очередности остановки ресурсов:

👉 **Файл с заданием и тестами:** [[ex_05_production_config.py]]

Запуск проверки:
```bash
python3 exercises/06_fastapi_pro/ex_05_production_config.py
```
