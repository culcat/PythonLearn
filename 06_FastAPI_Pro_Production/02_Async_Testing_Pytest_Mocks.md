---
title: "02. Асинхронное тестирование: Pytest, httpx, фикстуры, изоляция БД и моки"
aliases:
  - "Async Testing FastAPI"
  - "Pytest FastAPI"
  - "Database Test Isolation Savepoint"
tags:
  - testing
  - pytest
  - async
  - httpx
  - mocks
  - fastapi
module: "06_FastAPI_Pro_Production"
created: 2026-11-03
status: complete
---

# 02. Асинхронное тестирование: Pytest, httpx, фикстуры, изоляция БД и моки

Тестирование асинхронных веб-приложений на FastAPI требует принципиально иного подхода по сравнению с классическими синхронными фреймворками (Django/Flask). Ошибки в управлении событийным циклом (`Event Loop`), зависшие корутины, протекание данных между тестами в базе данных и некорректное мокирование внешних HTTP-запросов могут превратить тестовый набор в нестабильный и медленный кошмар («flaky tests»).

В этой главе мы разберем построение надежной пирамиды тестирования, высокопроизводительную изоляцию базы данных через транзакционные точки сохранения (`SAVEPOINT`), мокирование с помощью `respx` и управление зависимостями в тестах.

---

## 1. Пирамида тестирования для FastAPI

```mermaid
flowchart TD
    E2E["E2E / Functional Tests (10%)<br/><i>Полные сценарии через реальный API и БД</i>"]
    Integration["Integration Tests (30%)<br/><i>Репозитории, транзакции БД, интеграции с внешними API через respx</i>"]
    Unit["Unit Tests (60%)<br/><i>Чистая бизнес-логика (Domain, Value Objects, Use Cases на in-memory)</i>"]

    Unit --> Integration
    Integration --> E2E

    style Unit fill:#2e3440,stroke:#a3be8c,stroke-width:2px,color:#eceff4
    style Integration fill:#2e3440,stroke:#ebcb8b,stroke-width:2px,color:#eceff4
    style E2E fill:#2e3440,stroke:#bf616a,stroke-width:2px,color:#eceff4
```

| Уровень тестов | Что проверяется | Скорость выполнения | Изоляция |
|---|---|---|---|
| **Unit** | Доменные правила, инварианты сущностей, формулы скидок, сценарии Use Cases. | 1-5 мс на тест | Полная (без I/O, чистая память). |
| **Integration** | SQL-запросы в репозиториях, транзакции, сериализация Pydantic DTO, Middleware. | 10-50 мс на тест | Транзакционный откат (`SAVEPOINT`). |
| **E2E / API** | Сквозные HTTP-маршруты, коды ответов, валидация заголовков, авторизация. | 50-200 мс на тест | Внутрипроцессный `ASGITransport`. |

---

## 2. Настройка `pytest` и `pytest-asyncio`

Для чистого запуска асинхронных тестов в современных версиях `pytest-asyncio` (версии 0.23+) рекомендуется строгая автоматическая конфигурация.

### Конфигурация в `pyproject.toml`

```toml
[tool.pytest.ini_options]
minversion = "8.0"
addopts = "-ra -q --strict-markers --strict-config"
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

> [!NOTE] `asyncio_mode = "auto"`
> Режим `auto` избавляет от необходимости ставить декоратор `@pytest.mark.asyncio` над каждым асинхронным тестовым методом. Любая функция `async def test_*` автоматически выполняется внутри асинхронного цикла событий.

---

## 3. Асинхронный клиент: почему не `TestClient`?

Классический `starlette.testclient.TestClient` использует под капотом библиотеку `requests`. Он выполняет асинхронное приложение FastAPI в **отдельном потоке** через синхронный вызов.

### Проблемы `TestClient`:
1. Разные потоки для теста и приложения ломают `contextvars` (например, контекст сессии БД или `Correlation-ID`).
2. Невозможно тестировать асинхронные генераторы и WebSockets без блокировок.

### Решение: `httpx.AsyncClient` с `ASGITransport`

Библиотека `httpx` позволяет выполнять запросы напрямую к ASGI-интерфейсу FastAPI в том же самом потоке и событийном цикле без открытия реальных TCP-сокетов:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from main import app

@pytest.fixture
async def api_client():
    # ASGITransport перенаправляет HTTP-вызовы напрямую в ASGI callable
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

async def test_health_check(api_client: AsyncClient):
    response = await api_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

---

## 4. Изоляция тестов БД через `SAVEPOINT`

Наивная очистка тестовой БД через `TRUNCATE table` или пересоздание схемы `Base.metadata.create_all()` перед каждым тестом катастрофически замедляет прогон (до минут при сотнях тестов).

### Механика паттерна Transactional Rollback (Savepoint)

1. В начале тестовой сессии схема базы данных создается **один раз** (Session scope).
2. Для каждого отдельного теста открывается транзакция соединения, внутри которой создается точка сохранения (`SAVEPOINT` / `nested_transaction`).
3. Приложение выполняет `INSERT`, `UPDATE`, `DELETE` внутри этого savepoint.
4. По завершении теста выполняется **ROLLBACK TO SAVEPOINT**.
5. База данных мгновенно возвращается в исходное состояние без дисковых операций очистки таблиц!

```mermaid
sequenceDiagram
    autonumber
    participant Engine as AsyncEngine
    participant Conn as AsyncConnection
    participant Test as Test Case
    participant DB as PostgreSQL

    Note over Engine,DB: Setup сессии: создание таблиц (один раз)
    Test->>Conn: Открытие соединения и внешней транзакции
    Conn->>DB: BEGIN
    Test->>Conn: Создание вложенной транзакции (Savepoint)
    Conn->>DB: SAVEPOINT test_savepoint
    
    Test->>DB: INSERT INTO users ... (Тестовые данные)
    Test->>DB: SELECT / UPDATE
    
    Note over Test: Выполнение проверок assert
    
    Test->>Conn: Teardown: Откат точки сохранения
    Conn->>DB: ROLLBACK TO SAVEPOINT test_savepoint
    Conn->>DB: ROLLBACK (Закрытие внешней транзакции)
```

### Реализация фикстуры в `conftest.py`

```python
import pytest
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from main import app, get_db_session

TEST_DATABASE_URL = "postgresql+asyncpg://postgres:pass@localhost:5432/test_db"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)

@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with engine.connect() as connection:
        # Открываем внешнюю транзакцию
        transaction = await connection.begin()
        
        # Начинаем вложенную транзакцию (Savepoint)
        nested = await connection.begin_nested()
        
        session_factory = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        
        async with session_factory() as session:
            # Подменяем зависимость сессии в приложении FastAPI
            app.dependency_overrides[get_db_session] = lambda: session
            
            yield session
            
            # Очищаем переопределение зависимостей
            app.dependency_overrides.clear()
            
        # Откатываем все изменения теста
        if nested.is_active:
            await nested.rollback()
        await transaction.rollback()
```

---

## 5. Генерация тестовых данных: `polyfactory`

Хардкод моковых данных приводит к хрупкости: изменение обязательного поля ломает сотни тестов. Библиотека **`polyfactory`** (от авторов Litestar) автоматически генерирует данные для Pydantic v2 моделей, Dataclasses и SQLAlchemy моделей.

```python
from pydantic import BaseModel, EmailStr
from polyfactory.factories.pydantic_factory import ModelFactory
from decimal import Decimal

class UserProfileDTO(BaseModel):
    id: int
    email: EmailStr
    username: str
    balance: Decimal
    is_active: bool

class UserProfileFactory(ModelFactory[UserProfileDTO]):
    __model__ = UserProfileDTO

# Использование в тестах
def test_user_creation():
    # Генерирует полностью валидный объект со случайными реалистичными данными
    fake_user = UserProfileFactory.build(balance=Decimal("150.00"))
    assert fake_user.balance == Decimal("150.00")
    assert "@" in fake_user.email
```

---

## 6. Мокирование внешних HTTP-сервисов: `respx`

При интеграции с внешними API (платежные шлюзы, CRM, внешние OAuth-провайдеры) сетевые запросы в тестах строго запрещены. Для клиентов на `httpx` стандартом является библиотека **`respx`**:

```python
import pytest
import respx
import httpx
from services.payment import StripeClient

@pytest.mark.asyncio
@respx.mock
async def test_payment_charge_success():
    # 1. Задаем мок внешнего URL с нужным статусом и телом
    stripe_route = respx.post("https://api.stripe.com/v1/charges").mock(
        return_value=httpx.Response(
            status_code=200,
            json={"id": "ch_12345", "status": "succeeded", "paid": True},
        )
    )

    # 2. Вызываем наш рабочий сервис
    client = StripeClient(api_key="sk_test_fake")
    result = await client.charge(amount=1000, currency="usd")

    # 3. Проверяем результат и факт вызова внешнего эндпоинта
    assert result.success is True
    assert result.charge_id == "ch_12345"
    assert stripe_route.called
    assert stripe_route.call_count == 1
```

---

## 7. Переопределение зависимостей (`dependency_overrides`)

В FastAPI внедрение зависимостей (`Depends`) спроектировано с поддержкой прямого переопределения в тестах через словарь `app.dependency_overrides`:

```python
from unittest.mock import AsyncMock
from main import app, get_current_user
from domain.user import User

async def test_admin_dashboard_access(api_client: AsyncClient):
    # Мок пользователя-администратора
    mock_admin = User(id=1, email="admin@example.com", is_superuser=True)
    
    # Подмена реальной аутентификации на мок
    app.dependency_overrides[get_current_user] = lambda: mock_admin

    try:
        response = await api_client.get("/admin/metrics")
        assert response.status_code == 200
    finally:
        # Критически важно очистить переопределение после теста!
        app.dependency_overrides.clear()
```

> [!TIP] Очистка зависимостей в фикстуре
> Всегда оборачивайте очистку `app.dependency_overrides.clear()` в `try...finally` блока фикстуры `yield`, чтобы падение теста не повлияло на следующие проверки.

---

## Резюме

1. Используйте **`httpx.AsyncClient` с `ASGITransport`** вместо синхронного `TestClient` для изоляции потоков и поддержки `contextvars`.
2. Паттерн **Savepoint Rollback** позволяет выполнять интеграционные тесты с реальной базой данных со скоростью юнит-тестов.
3. Мокируйте внешние вызовы на уровне HTTP-транспорта с помощью **`respx`**, чтобы проверять реальные сетевые сериализаторы.
4. Используйте **`dependency_overrides`** для контролируемой подмены внешних адаптеров.

---

## Практическое задание

Реализуйте и протестируйте асинхронный тестовый раннер с поддержкой транзакционных точек сохранения (`SAVEPOINT`), мокированием HTTP-клиента и динамическим переопределением зависимостей:

👉 **Файл с заданием и тестами:** [[ex_02_async_testing.py]]

Запуск проверки:
```bash
python3 exercises/06_fastapi_pro/ex_02_async_testing.py
```
