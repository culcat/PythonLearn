---
title: "04. Система внедрения зависимостей (Dependency Injection)"
module: "04_FastAPI_Core"
topic_number: 4
difficulty: "advanced"
tags:
  - fastapi
  - dependency-injection
  - ioc
  - depends
  - yield
  - testing
prerequisites:
  - "[[00_Index_MOC]]"
  - "[[04_Functions_Closures]]"
  - "[[05_Exceptions_Files_Context]]"
  - "[[01_ASGI_Routing_Parameters]]"
created: 2026-11-03
status: complete
---

# 04. Система внедрения зависимостей (Dependency Injection)

Система **внедрения зависимостей (Dependency Injection, DI)** — архитектурная жемчужина FastAPI. В отличие от тяжеловесных фреймворков в других языках программирования, требующих громоздких XML-конфигураций или сложных контейнеров, DI в FastAPI элегантен, декларативен и опирается на инспекцию стандартных сигнатур Python и `Annotated`.

В этой главе мы подробно разберем, как строится и разрешается направленный ациклический граф (DAG) зависимостей, изучим зависимости-функции и параметризуемые классы, поймем механизм кэширования `use_cache=True`, освоим безопасное управление ресурсами через генераторы с `yield` и научимся подменять зависимости в тестах через `app.dependency_overrides`.

---

## 1. Концепция Inversion of Control (IoC) и граф зависимостей (DAG)

В классическом монолитном коде функции сами создают ресурсы, которые им требуются:
```python
# ❌ Проблема: жесткая связанность (Hard Coupling) и невозможность тестирования
async def get_orders_bad():
    db = PostgresDatabaseConnection("postgresql://prod_user:secret@db.internal/prod")
    auth_service = OAuth2RemoteClient("https://auth.company.com")
    # Логика эндпоинта...
```
При таком подходе невозможно протестировать эндпоинт без поднятия боевой базы данных или изменения исходного кода.

**Инверсия управления (IoC)** меняет вектор ответственности: эндпоинт лишь *декларирует*, какие ресурсы ему нужны для работы, а внешний контейнер (FastAPI) берет на себя их поиск, создание, передачу в эндпоинт и последующую корректную утилизацию.

```mermaid
flowchart TD
    subgraph Dependency_DAG["Направленный ациклический граф (DAG)"]
        Req["HTTP Запрос"]
        Token["get_token_from_header<br>(Извлечение Bearer токена)"]
        DBSession["get_db_session<br>(yield сессия SQLAlchemy)"]
        CurrentUser["get_current_user<br>(Декодирование токена + поиск в БД)"]
        AdminRole["verify_admin_role<br>(Проверка прав суперпользователя)"]
        AuditLog["write_audit_log<br>(Фиксация действия админа)"]
        Endpoint["Эндпоинт: DELETE /api/v1/users/{id}"]
        
        Req --> Token
        Req --> DBSession
        Token --> CurrentUser
        DBSession --> CurrentUser
        CurrentUser --> AdminRole
        AdminRole --> AuditLog
        DBSession --> AuditLog
        AuditLog --> Endpoint
    end
```

### Как FastAPI разрешает зависимости:
1. При старте приложения FastAPI инспектирует сигнатуру функции через `inspect.signature` и находит все вызовы `Depends(...)`.
2. Строится **направленный ациклический граф (DAG)**. Если обнаруживается циклическая зависимость (A зависит от B, а B зависит от A), приложение немедленно выбрасывает исключение.
3. При поступлении запроса контейнер разрешает граф от листьев к корню: сначала извлекаются токены и создаются подключения к БД, затем создаются составные сервисы, и только в самом конце вызывается функция обработчика эндпоинта.

---

## 2. Разновидности провайдеров зависимостей

Зависимостью в FastAPI может быть **любой вызываемый объект (Callable)**: обычная функция, асинхронная корутина, класс или объект, реализующий магический метод `__call__`.

### А. Функции-зависимости (Function Dependencies)

Простейший и наиболее частый вариант:

```python
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, status

router = APIRouter(prefix="/secure", tags=["Защищенные ресурсы"])

async def get_api_key(
    x_api_key: Annotated[str, Header(description="Секретный ключ API")],
) -> str:
    """Функция-зависимость для проверки API-токена."""
    if x_api_key != "secret-corporate-production-key":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Предоставлен недействительный X-API-Key",
        )
    return x_api_key

@router.get("/metrics")
async def read_system_metrics(
    # Внедрение результата функции get_api_key
    api_key: Annotated[str, Depends(get_api_key)],
):
    return {"status": "ok", "auth_by": api_key, "cpu_load": "12%"}
```

---

### Б. Параметризуемые классы-зависимости (`__init__` и `__call__`)

Классы позволяют инкапсулировать параметры конфигурации и повторно использовать логику.

#### Вариант 1: Класс как контейнер параметров запроса
```python
from typing import Annotated
from fastapi import Depends, Query

class PaginationParams:
    """Извлекает и валидирует параметры пагинации из Query-параметров."""
    def __init__(
        self,
        page: Annotated[int, Query(ge=1, description="Номер страницы")] = 1,
        limit: Annotated[int, Query(ge=1, le=100, description="Записей на странице")] = 20,
    ):
        self.page = page
        self.limit = limit
        self.offset = (page - 1) * limit

@router.get("/products")
async def list_products(
    # FastAPI инспектирует __init__ класса PaginationParams!
    pagination: Annotated[PaginationParams, Depends(PaginationParams)],
):
    return {
        "page": pagination.page,
        "limit": pagination.limit,
        "offset": pagination.offset,
    }
```

> [!TIP] Сокращенный синтаксис `Depends()`
> Если класс или функция указаны в аннотации типа, аргумент `Depends()` можно оставить пустым:
> `pagination: Annotated[PaginationParams, Depends()]` — FastAPI автоматически использует тип `PaginationParams`!

#### Вариант 2: Вызываемый экземпляр класса (Callable Instance с `__call__`)
Этот паттерн идеален для ролевой модели (RBAC), когда логику проверки нужно параметризовать допустимыми ролями:

```python
from typing import Annotated
from fastapi import Depends, HTTPException, status

class RoleChecker:
    """Параметризуемый верификатор ролей пользователя."""
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(
        self,
        # Зависимость может внедрять другие зависимости!
        current_user: Annotated[dict, Depends(lambda: {"username": "alice", "role": "admin"})],
    ) -> dict:
        user_role = current_user.get("role")
        if user_role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Доступ запрещен. Требуются роли: {self.allowed_roles}",
            )
        return current_user

# Создаем многократно переиспользуемые экземпляры-провайдеры
allow_admin_only = RoleChecker(allowed_roles=["admin", "superadmin"])
allow_moderator_or_admin = RoleChecker(allowed_roles=["admin", "moderator"])

@router.delete("/system/cache")
async def clear_cache(user: Annotated[dict, Depends(allow_admin_only)]):
    return {"message": "Кэш очищен администратором", "user": user["username"]}
```

---

## 3. Кэширование зависимостей в рамках запроса (`use_cache=True`)

По умолчанию в вызове `Depends(dependency, use_cache=True)` включено кэширование. 

Что это значит? Если в рамках **одного входящего HTTP-запроса** функция-зависимость `get_current_user` или `get_db_session` требуется пяти разным компонентам графа, FastAPI выполнит ее **ровно один раз** при первом обращении, сохранит результат во внутреннем словаре контекста запроса и мгновенно вернет сохраненный объект всем остальным зависимостям.

```mermaid
flowchart TD
    Req["HTTP Запрос к эндпоинту"] --> D1["Зависимость А -> Depends(get_db, use_cache=True)"]
    Req --> D2["Зависимость Б -> Depends(get_db, use_cache=True)"]
    Req --> D3["Сам эндпоинт -> Depends(get_db, use_cache=True)"]
    
    D1 --> FirstCall["1-й вызов get_db(): Создание сессии в БД (ID: 0x7FA3)"]
    FirstCall --> Cache[("Внутренний кэш запроса")]
    
    D2 -.->|Чтение из кэша без вызова функции| Cache
    D3 -.->|Чтение из кэша без вызова функции| Cache
```

> [!NOTE] Когда следует отключать кэширование (`use_cache=False`)?
> Если вам требуется генерация уникального значения при каждом внедрении (например, генерация случайных одноразовых nonce, уникальных UUID подзапросов или создание независимых транзакционных контекстов):
> ```python
> fresh_id: Annotated[str, Depends(generate_fresh_uuid, use_cache=False)]
> ```

---

## 4. Ресурсные зависимости с `yield` и порядок финализации

Одной из самых мощных концепций FastAPI является использование генераторов (`yield`). Это аналог контекстных менеджеров `with` (см. [[05_Exceptions_Files_Context]]), адаптированный под асинхронный конвейер веб-запроса.

```mermaid
sequenceDiagram
    autonumber
    participant Server as FastAPI DI Engine
    participant Dep as Ресурсная зависимость (yield)
    participant Route as Код эндпоинта
    
    Server->>Dep: Вход в генератор: выделение ресурса (connect)
    Note over Dep: try-блок: открытие транзакции
    Dep->>Server: yield db_session
    Server->>Route: Передача session в аргументы эндпоинта
    Route->>Route: Выполнение бизнес-логики и возврат ответа
    Route->>Server: Готовый Response
    Server->>Dep: Возврат управления в генератор (после yield)
    Note over Dep: commit() транзакции или rollback() при ошибке
    Note over Dep: finally-блок: закрытие соединения session.close()
    Dep->>Server: Завершение работы генератора
    Server->>Client: Отправка HTTP-ответа клиенту
```

### Паттерн безопасной сессии базы данных с транзакцией:

```python
from collections.abc import AsyncGenerator
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status

class FakeAsyncSession:
    """Имитация асинхронной сессии SQLAlchemy 2.0."""
    def __init__(self):
        self.is_open = True
        self.is_committed = False
        self.is_rolled_back = False

    async def commit(self):
        self.is_committed = True

    async def rollback(self):
        self.is_rolled_back = True

    async def close(self):
        self.is_open = False

async def get_db_session() -> AsyncGenerator[FakeAsyncSession, None]:
    """
    Провайдер сессии базы данных с гарантированной очисткой.
    Все, что ДО yield — выполняется ДО вызова эндпоинта.
    Все, что ПОСЛЕ yield — выполняется ПОСЛЕ отправки ответа клиенту.
    """
    session = FakeAsyncSession()
    try:
        yield session
        # Если эндпоинт завершился успешно без исключений — фиксируем транзакцию
        await session.commit()
    except Exception as exc:
        # При возникновении любой ошибки — откатываем транзакцию
        await session.rollback()
        raise exc
    finally:
        # Гарантированное закрытие соединения и возврат его в connection pool
        await session.close()
```

> [!CAUTION] Важное поведение исключений в зависимостях с `yield`
> Код после `yield` выполняется внутри блока обработки ответа. Если в эндпоинте возникнет исключение (например, `HTTPException`), оно будет проброшено в точку вызова `yield` внутри генератора!
> Именно поэтому блок `finally:` выполнится **всегда**, даже если клиент отвалился по таймауту или сервер выбросил ошибку 500.

---

## 5. Области видимости зависимостей (Scopes)

В FastAPI зависимости можно регистрировать на трех уровнях:

1. **Уровень эндпоинта**: результат передается в аргумент конкретной функции.
   ```python
   @router.get("/items")
   async def get_items(db: Annotated[FakeAsyncSession, Depends(get_db_session)]): ...
   ```

2. **Уровень маршрутизатора (`APIRouter`)**: применяется ко **всем** маршрутам данного роутера. Если значение зависимости не нужно в аргументах функций, передавайте ее в список `dependencies=[...]`:
   ```python
   admin_router = APIRouter(
       prefix="/admin",
       dependencies=[Depends(allow_admin_only), Depends(write_audit_log)],
   )
   ```

3. **Глобальный уровень приложения (`FastAPI`)**: применяется ко всем эндпоинтам всей системы:
   ```python
   app = FastAPI(
       dependencies=[Depends(global_rate_limiter), Depends(verify_tenant_active)]
   )
   ```

---

## 6. Тестирование и подмена зависимостей: `app.dependency_overrides`

Главное архитектурное преимущество DI — легкость написания тестов. Вам больше не нужно использовать тяжелые `unittest.mock.patch` на приватные модули. FastAPI предоставляет официальный механизм подмены: словарь `app.dependency_overrides`.

```python
import pytest
from fastapi import FastAPI, Depends, status
from fastapi.testclient import TestClient

app = FastAPI()

# Боевая зависимость: обращается к внешнему платному сервису
async def get_payment_gateway():
    raise RuntimeError("Нельзя вызывать реальный платежный шлюз в тестах!")

@app.post("/pay")
async def process_payment(gateway=Depends(get_payment_gateway)):
    return {"status": "paid"}

# --- ТЕСТОВЫЙ КОД ---

# Создаем тестовую заглушку (Mock/Stub)
async def mock_fake_payment_gateway():
    return {"gateway": "sandbox_fake_mode", "status": "approved"}

def test_payment_endpoint():
    # 1. Подменяем боевую зависимость на тестовую
    app.dependency_overrides[get_payment_gateway] = mock_fake_payment_gateway

    client = TestClient(app)
    response = client.post("/pay")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "paid"}

    # 2. Обязательно очищаем переопределения после теста!
    app.dependency_overrides.clear()
```

---

## Резюме

1. **Dependency Injection (DI)** в FastAPI строит направленный ациклический граф (DAG) и управляет жизненным циклом компонентов за вас.
2. Провайдерами зависимостей могут выступать как функции, так и классы (через `__init__` параметров запроса или `__call__` экземпляра).
3. По умолчанию зависимости кэшируются в пределах одного HTTP-запроса (**`use_cache=True`**), что экономит ресурсы при повторном использовании.
4. Конструкция с **`yield`** в зависимостях позволяет реализовать идеальное управление контекстом: открытие сессий до эндпоинта и гарантированный `commit`/`close` в блоке `finally` после завершения обработки.
5. Для изолированного и чистого модульного тестирования используйте **`app.dependency_overrides`**.

---

## Практическое задание

В практическом файле [[ex_04_dependency_injection.py]] реализован полноценный контейнер внедрения зависимостей с поддержкой графа подзависимостей, кэшированием вызовов в контексте запроса, гарантированной финализацией ресурсов с `yield` и поддержкой `dependency_overrides`.

Запустите тесты для проверки реализации:
```bash
python3 exercises/04_fastapi_core/ex_04_dependency_injection.py
```
