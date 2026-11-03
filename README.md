<div align="center">

# 🐍⚡ Python & FastAPI: От 0 до Pro (Obsidian Vault)

**Фундаментальный интерактивный учебник и практикум по современному Python (3.12–3.14+) и продакшен-разработке на FastAPI**

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%20%7C%203.13%20%7C%203.14-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Modern%20ASGI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2%20(Rust%20Core)-E92063?style=for-the-badge&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![SQLAlchemy 2.0](https://img.shields.io/badge/SQLAlchemy-2.0%20Async-D71F00?style=for-the-badge&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![Obsidian Vault](https://img.shields.io/badge/Obsidian-Knowledge%20Vault-7C3AED?style=for-the-badge&logo=obsidian&logoColor=white)](https://obsidian.md/)
[![Tests](https://img.shields.io/badge/Unit%20Tests-200%20Passed%20(30%20Suites)-10B981?style=for-the-badge&logo=pytest&logoColor=white)](#-%D0%BF%D1%80%D0%B0%D0%BA%D1%82%D0%B8%D0%BA%D0%B0-%D0%B8-%D0%B0%D0%B2%D1%82%D0%BE%D1%82%D0%B5%D1%81%D1%82%D1%8B)

---

[**🗺️ Главная карта знаний (00_Index_MOC.md)**](./00_Index_MOC.md) • [**📖 Техническая документация**](./DOCUMENTATION.md) • [**🧪 Запустить все тесты**](#-%D0%B1%D1%8B%D1%81%D1%82%D1%80%D1%8B%D0%B9-%D1%81%D1%82%D0%B0%D1%80%D1%82)

</div>

---

## 🎯 О проекте

Этот репозиторий — **готовая база знаний (Obsidian Vault)** и **инженерный тренажёр**, который проводит разработчика от внутреннего устройства объектов в памяти CPython до проектирования высоконагруженных асинхронных микросервисов на **FastAPI** с использованием **Clean Architecture**, **DDD**, **SQLAlchemy 2.0 Async** и **Transactional Outbox**.

### ✨ Ключевые особенности
* 🧠 **Формат Obsidian Vault («Второй мозг»)** — все 30 глав и 7 индексных карт (MOC) связаны двусторонними `[[wikilinks]]`, снабжены YAML-метаданными, тегами, блоками акцентов (`> [!IMPORTANT]`, `> [!WARNING]`, `> [!TIP]`) и архитектурными `Mermaid`-диаграммами.
* 🔬 **Глубина «под капотом»** — разбор структур `PyObject`, `GIL` и `Free-Threaded Python (PEP 703)`, хеш-таблиц `dict`, алгоритма `C3 MRO`, дескрипторов, конечных автоматов корутин и `Event Loop`.
* 🏗️ **Продакшен-паттерны FastAPI** — никаких «игрушечных» примеров: только `Pydantic v2`, `Annotated` Dependency Injection, стандарт ошибок `RFC 9457 (Problem Details)`, `Unit of Work`, ротация `JWT Refresh`-токенов, защита от `Cache Stampede`, `Token Bucket` и `Clean Architecture`.
* 🧪 **30 практических `.py` полигонов (200 автотестов)** — в конце каждой главы находится ссылка на `.py` файл с практическими задачами и встроенным набором модульных тестов (`unittest` / `pytest`), работающим **из коробки на стандартной библиотеке Python** без необходимости разворачивать внешние контейнеры.

---

## 🗺️ Архитектура обучения (Roadmap)

```mermaid
flowchart LR
    M1["01. Основы Python\nПамять • Типы • Структуры"] --> M2["02. ООП и Типизация\nDunder • MRO • Generics"]
    M2 --> M3["03. Internals & Asyncio\nGIL • GC • Event Loop"]
    M3 --> M4["04. Ядро FastAPI\nASGI • Pydantic v2 • DI"]
    M4 --> M5["05. Данные и Auth\nSQLAlchemy 2.0 • JWT • Redis"]
    M5 --> M6["06. Production & Pro\nClean Arch • Outbox • Observability"]
```

---

## 📚 Полное оглавление и практикумы

### 🟢 Модуль 01: Основы Python ([Обзор модуля](./01_Python_Basics/00_Module_01_MOC.md))
| № | Тема главы | Ключевые концепции | Практика и тесты |
| :-: | :--- | :--- | :--- |
| **01** | [**Синтаксис, переменные и типы**](./01_Python_Basics/01_Syntax_Types_Variables.md) | `PyObject`, мутабельность, интернирование, `IEEE 754` vs `Decimal`, `UTF-8`, `:=` | [`ex_01_syntax_types.py`](./exercises/01_basics/ex_01_syntax_types.py) |
| **02** | [**Управляющие конструкции и циклы**](./01_Python_Basics/02_Control_Flow_Loops.md) | Truthy/Falsy, short-circuit, Structural Pattern Matching (`match/case`), `for/else`, `zip(strict=True)` | [`ex_02_control_flow.py`](./exercises/01_basics/ex_02_control_flow.py) |
| **03** | [**Структуры данных и Big-O**](./01_Python_Basics/03_Data_Structures.md) | Over-allocation в `list`, компактный `dict`, коллизии хешей, `set`, срезы, `collections` | [`ex_03_data_structures.py`](./exercises/01_basics/ex_03_data_structures.py) |
| **04** | [**Функции, LEGB и замыкания**](./01_Python_Basics/04_Functions_Closures.md) | First-class functions, `/` и `*`, ловушка дефолтных аргументов, `nonlocal`, `__closure__`, `partial` | [`ex_04_functions_closures.py`](./exercises/01_basics/ex_04_functions_closures.py) |
| **05** | [**Исключения, файлы и контекст**](./01_Python_Basics/05_Exceptions_Files_Context.md) | Иерархия `BaseException`, `raise ... from`, `ExceptionGroup` и `except*`, `pathlib`, `__enter__`/`__exit__` | [`ex_05_exceptions_files.py`](./exercises/01_basics/ex_05_exceptions_files.py) |

### 🔵 Модуль 02: ООП, Декораторы и Строгая типизация ([Обзор модуля](./02_Python_OOP_Typing/00_Module_02_MOC.md))
| № | Тема главы | Ключевые концепции | Практика и тесты |
| :-: | :--- | :--- | :--- |
| **01** | [**Классы, `__slots__` и Магические методы**](./02_Python_OOP_Typing/01_Classes_Magic_Methods.md) | `__new__` vs `__init__`, `__dict__`, `__slots__`, `@property`, контракт `__eq__` и `__hash__`, `@total_ordering` | [`ex_01_classes_magic.py`](./exercises/02_oop_typing/ex_01_classes_magic.py) |
| **02** | [**Наследование, MRO и ABC**](./02_Python_OOP_Typing/02_Inheritance_MRO_ABCs.md) | Проблема ромба, C3-линеаризация (`__mro__`), кооперативный `super()`, Mixins, `abc.ABC` | [`ex_02_inheritance_abc.py`](./exercises/02_oop_typing/ex_02_inheritance_abc.py) |
| **03** | [**Декораторы, Итераторы и Генераторы**](./02_Python_OOP_Typing/03_Decorators_Generators.md) | Параметризованные декораторы, `@wraps`, протокол итератора, `yield from`, `.send()`, `itertools` | [`ex_03_decorators_generators.py`](./exercises/02_oop_typing/ex_03_decorators_generators.py) |
| **04** | [**Dataclasses, Enum и Дескрипторы**](./02_Python_OOP_Typing/04_Dataclasses_Enums_Descriptors.md) | `@dataclass(frozen=True, slots=True)`, `StrEnum`, `Flag`, Data vs Non-Data дескрипторы (`__set_name__`) | [`ex_04_dataclasses_descriptors.py`](./exercises/02_oop_typing/ex_04_dataclasses_descriptors.py) |
| **05** | [**Продвинутая типизация и Протоколы**](./02_Python_OOP_Typing/05_Type_Hints_Protocols_Generics.md) | Синтаксис PEP 695 (`class Box[T]`), вариантность, `Protocol`, `TypedDict`, `Annotated`, `TypeGuard`, `ParamSpec` | [`ex_05_typing_protocols.py`](./exercises/02_oop_typing/ex_05_typing_protocols.py) |

### 🟣 Модуль 03: Внутреннее устройство CPython и Asyncio ([Обзор модуля](./03_Python_Internals_Async/00_Module_03_MOC.md))
| № | Тема главы | Ключевые концепции | Практика и тесты |
| :-: | :--- | :--- | :--- |
| **01** | [**Модель памяти, GC и GIL**](./03_Python_Internals_Async/01_Memory_Model_GIL_GC.md) | Подсчет ссылок, циклические ссылки, 3 поколения GC, `weakref`, устройство GIL и Free-Threading (PEP 703) | [`ex_01_memory_gc.py`](./exercises/03_internals_async/ex_01_memory_gc.py) |
| **02** | [**Метаклассы и `contextlib`**](./03_Python_Internals_Async/02_Metaclasses_ContextManagers.md) | Цепочка `__prepare__` → `__new__` → `__init__`, `__init_subclass__`, `ExitStack`, `AsyncExitStack` | [`ex_02_metaclasses_context.py`](./exercises/03_internals_async/ex_02_metaclasses_context.py) |
| **03** | [**Threading и Multiprocessing**](./03_Python_Internals_Async/03_Threading_Multiprocessing.md) | Race Conditions, Deadlocks, `Lock`, `RLock`, `Semaphore`, `Event`, IPC, `SharedMemory`, `concurrent.futures` | [`ex_03_concurrency_sync.py`](./exercises/03_internals_async/ex_03_concurrency_sync.py) |
| **04** | [**Event Loop, Корутины и TaskGroup**](./03_Python_Internals_Async/04_Asyncio_Event_Loop_Coroutines.md) | Неблокирующий I/O (`epoll`/`kqueue`), `Future` vs `Task`, структурная конкурентность `asyncio.TaskGroup`, `to_thread` | [`ex_04_asyncio_coroutines.py`](./exercises/03_internals_async/ex_04_asyncio_coroutines.py) |
| **05** | [**Асинхронные паттерны и Стримы**](./03_Python_Internals_Async/05_Async_Patterns_Queues_Streams.md) | `async for` / `async with`, Producer–Consumer на `asyncio.Queue`, Backpressure, `contextvars.ContextVar` | [`ex_05_async_patterns.py`](./exercises/03_internals_async/ex_05_async_patterns.py) |

### 🟠 Модуль 04: Ядро FastAPI и Pydantic v2 ([Обзор модуля](./04_FastAPI_Core/00_Module_04_MOC.md))
| № | Тема главы | Ключевые концепции | Практика и тесты |
| :-: | :--- | :--- | :--- |
| **01** | [**Стандарт ASGI и Маршрутизация**](./04_FastAPI_Core/01_ASGI_Routing_Parameters.md) | `scope / receive / send`, Starlette + Uvicorn, `APIRouter`, `Annotated[T, Path/Query/Header/Cookie]`, OpenAPI 3.1 | [`ex_01_routing_params.py`](./exercises/04_fastapi_core/ex_01_routing_params.py) |
| **02** | [**Глубокое погружение в Pydantic v2**](./04_FastAPI_Core/02_Pydantic_v2_Models_Validation.md) | Ядро `pydantic-core`, `Field`, `@field_validator`, `@model_validator`, `@computed_field`, `ConfigDict`, DTO | [`ex_02_pydantic_v2.py`](./exercises/04_fastapi_core/ex_02_pydantic_v2.py) |
| **03** | [**Запросы, Ответы и Ошибки (RFC 9457)**](./04_FastAPI_Core/03_Requests_Responses_Status_Errors.md) | `UploadFile`, фильтрация `response_model`, `ORJSONResponse`, `HTTPException`, стандарт `application/problem+json` | [`ex_03_requests_errors.py`](./exercises/04_fastapi_core/ex_03_requests_errors.py) |
| **04** | [**Система Dependency Injection (`Depends`)**](./04_FastAPI_Core/04_Dependency_Injection_System.md) | DAG-граф зависимостей, кэширование в запросе, ресурсные зависимости с `yield`, `dependency_overrides` | [`ex_04_dependency_injection.py`](./exercises/04_fastapi_core/ex_04_dependency_injection.py) |
| **05** | [**ASGI Middleware, Lifespan и Background**](./04_FastAPI_Core/05_Middleware_Lifespan_Background.md) | Onion-конвейер, `BaseHTTPMiddleware` vs Pure ASGI Middleware, `CORS`, `@asynccontextmanager lifespan`, `BackgroundTasks` | [`ex_05_middleware_lifespan.py`](./exercises/04_fastapi_core/ex_05_middleware_lifespan.py) |

### 🔴 Модуль 05: Базы данных, Безопасность и Real-time ([Обзор модуля](./05_FastAPI_Data_Auth/00_Module_05_MOC.md))
| № | Тема главы | Ключевые концепции | Практика и тесты |
| :-: | :--- | :--- | :--- |
| **01** | [**SQLAlchemy 2.0 Async и Сессии**](./05_FastAPI_Data_Auth/01_SQLAlchemy2_Async_Sessions.md) | `AsyncEngine`, пул соединений, `expire_on_commit=False`, `Mapped[T]`, запрет lazy loading, `selectinload`/`joinedload` | [`ex_01_sqlalchemy_async.py`](./exercises/05_fastapi_data_auth/ex_01_sqlalchemy_async.py) |
| **02** | [**Alembic, Repository и Unit of Work**](./05_FastAPI_Data_Auth/02_Migrations_Alembic_Repositories.md) | Zero-downtime миграции, паттерн `Unit of Work`, Keyset (Cursor) пагинация, `SELECT FOR UPDATE`, Optimistic Locking | [`ex_02_repositories_uow.py`](./exercises/05_fastapi_data_auth/ex_02_repositories_uow.py) |
| **03** | [**Безопасность: OAuth2, JWT и RBAC**](./05_FastAPI_Data_Auth/03_Auth_OAuth2_JWT_Security.md) | Хеширование паролей (`Argon2`/`PBKDF2`), защита от timing-атак, Access + Refresh ротация, JTI Blacklist, RBAC | [`ex_03_auth_jwt_rbac.py`](./exercises/05_fastapi_data_auth/ex_03_auth_jwt_rbac.py) |
| **04** | [**Redis, Кэширование и Rate Limiting**](./05_FastAPI_Data_Auth/04_Caching_Redis_RateLimiting.md) | Cache-Aside, защита от Cache Stampede (Singleflight Lock), `Idempotency-Key`, алгоритмы Token Bucket и Sliding Window | [`ex_04_caching_ratelimit.py`](./exercises/05_fastapi_data_auth/ex_04_caching_ratelimit.py) |
| **05** | [**WebSockets, SSE и Стриминг**](./05_FastAPI_Data_Auth/05_WebSockets_SSE_Streaming.md) | `ConnectionManager` для комнат, масштабирование через Redis Pub/Sub, Server-Sent Events (SSE), `StreamingResponse` | [`ex_05_websockets_sse.py`](./exercises/05_fastapi_data_auth/ex_05_websockets_sse.py) |

### 🏆 Модуль 06: Production, Архитектура, Тестирование и Деплой ([Обзор модуля](./06_FastAPI_Pro_Production/00_Module_06_MOC.md))
| № | Тема главы | Ключевые концепции | Практика и тесты |
| :-: | :--- | :--- | :--- |
| **01** | [**Clean Architecture и тактический DDD**](./06_FastAPI_Pro_Production/01_Clean_Architecture_DDD.md) | Hexagonal Ports & Adapters, слои `Domain / Application / Infrastructure / API`, Value Objects, Aggregates, Dishka DI | [`ex_01_clean_architecture.py`](./exercises/06_fastapi_pro/ex_01_clean_architecture.py) |
| **02** | [**Асинхронное тестирование и Моки**](./06_FastAPI_Pro_Production/02_Async_Testing_Pytest_Mocks.md) | `pytest-asyncio`, `AsyncClient` + `ASGITransport`, изоляция БД через `SAVEPOINT`, фабрики данных, фейки и моки | [`ex_02_async_testing.py`](./exercises/06_fastapi_pro/ex_02_async_testing.py) |
| **03** | [**Очереди задач и Transactional Outbox**](./06_FastAPI_Pro_Production/03_Task_Queues_Celery_Taskiq_Broker.md) | `Taskiq` vs `Celery`, `FastStream`, идемпотентность воркеров, Exponential Backoff + Jitter, DLQ, паттерн Outbox | [`ex_03_task_queues_outbox.py`](./exercises/06_fastapi_pro/ex_03_task_queues_outbox.py) |
| **04** | [**Observability: Логи, Метрики, Трейсы**](./06_FastAPI_Pro_Production/04_Observability_Logging_Prometheus.md) | Структурный JSON (`structlog`), сквозной `X-Correlation-ID`, метрики Prometheus (`Counter`, `Histogram`), OpenTelemetry | [`ex_04_observability_metrics.py`](./exercises/06_fastapi_pro/ex_04_observability_metrics.py) |
| **05** | [**Docker, CI/CD и Оптимизация в Prod**](./06_FastAPI_Pro_Production/05_Docker_CI_CD_Performance_Pro.md) | `pydantic-settings`, Multi-stage Docker с `uv`, Gunicorn/Uvicorn воркеры, `SIGTERM` Graceful Shutdown, профилирование | [`ex_05_production_config.py`](./exercises/06_fastapi_pro/ex_05_production_config.py) |

---

## 🚀 Быстрый старт

### 1. Клонирование репозитория
```bash
git clone git@github.com:culcat/PythonLearn.git
cd PythonLearn
```

### 2. Открытие базы знаний в Obsidian
1. Запустите [**Obsidian**](https://obsidian.md/).
2. Нажмите **Open folder as vault** («Открыть папку как хранилище») и выберите папку `PythonLearn`.
3. Откройте корневую карту знаний [**`00_Index_MOC.md`**](./00_Index_MOC.md) и нажмите `Cmd/Ctrl + G`, чтобы открыть интерактивный граф связей между темами и практическими заданиями.

### 3. 🧪 Практика и автотесты
Каждое из 30 упражнений находится в папке `exercises/` и снабжено встроенными модульными тестами.

Запустить **все 30 наборов тестов (200 unit-тестов)** одной командой:
```bash
python3 run_all_tests.py
```

Запустить тесты конкретной темы с подробным отчетом:
```bash
python3 exercises/04_fastapi_core/ex_04_dependency_injection.py
```

---

## 🗂️ Структура репозитория

```text
PythonLearn/
├── .obsidian/                      # Настройки графа, отображения и плагинов Obsidian
├── 00_Index_MOC.md                 # 🧭 Главная карта знаний (точка входа в учебник)
├── DOCUMENTATION.md                # 📘 Техническая документация и статистика модулей
├── README.md                       # 📄 Обзор репозитория
├── run_all_tests.py                # 🧪 Единый раннер для проверки всех 30 тестовых наборов
├── 01_Python_Basics/               # 📗 Модуль 1: Основы Python (MOC + 5 глав)
├── 02_Python_OOP_Typing/           # 📘 Модуль 2: ООП, декораторы, типизация (MOC + 5 глав)
├── 03_Python_Internals_Async/      # 📙 Модуль 3: CPython Internals & Asyncio (MOC + 5 глав)
├── 04_FastAPI_Core/                # 📒 Модуль 4: Ядро FastAPI и Pydantic v2 (MOC + 5 глав)
├── 05_FastAPI_Data_Auth/           # 📕 Модуль 5: SQLAlchemy 2.0, JWT, Redis, WS (MOC + 5 глав)
├── 06_FastAPI_Pro_Production/      # 📓 Модуль 6: Clean Arch, Тесты, Outbox, Prod (MOC + 5 глав)
└── exercises/                      # 💻 30 практических .py файлов с 200 автотестами
    ├── 01_basics/
    ├── 02_oop_typing/
    ├── 03_internals_async/
    ├── 04_fastapi_core/
    ├── 05_fastapi_data_auth/
    └── 06_fastapi_pro/
```
