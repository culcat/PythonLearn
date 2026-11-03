---
title: "01. SQLAlchemy 2.0 Async: Сессии, Драйверы, Declarative Mapping и Loading Strategies"
aliases:
  - "SQLAlchemy 2.0 Async"
  - "Async SQLAlchemy Sessions"
  - "SQLAlchemy Declarative Base"
tags:
  - python
  - fastapi
  - sqlalchemy
  - database
  - async
  - orm
module: 5
chapter: 1
status: complete
created: 2026-11-03
---

# 01. SQLAlchemy 2.0 Async: Сессии, Драйверы, Declarative Mapping и Loading Strategies

[[00_Module_05_MOC|← Назад к Модулю 05]] | [[02_Migrations_Alembic_Repositories|Следующая глава: Миграции Alembic и Репозитории →]]

Реляционные базы данных остаются основой корпоративных систем. Долгие годы Python ORM работали исключительно в синхронном блокирующем режиме. С появлением стандарта **ASGI** и фреймворка **FastAPI** блокировка системного потока базы данных стала главным узким местом высоконагруженных API. Релиз **SQLAlchemy 2.0** полностью переосмыслил работу с ORM: библиотека получила нативную поддержку асинхронности (`async/await`), строгую типизацию через `Mapped[T]` и унифицированный синтаксис запросов.

В этой главе мы подробно разберем внутреннее устройство асинхронного SQLAlchemy 2.0, настройку пула соединений, жизненный цикл сессий в FastAPI и критически важные аспекты загрузки связанных данных.

---

## 1. Архитектура SQLAlchemy 2.0: Core vs ORM

SQLAlchemy состоит из двух фундаментальных уровней абстракции:

1. **SQLAlchemy Core**:
   - Предоставляет абстракцию над диалектами SQL (`Engine`, `Connection`, `MetaData`, `Table`, `Column`).
   - Отвечает за компиляцию Python-выражений (`select()`, `insert()`, `update()`) в параметризованный SQL конкретной СУБД (PostgreSQL, SQLite, MySQL) и управление пулом соединений (`ConnectionPool`).
   - Работает напрямую со строками в виде `Row` (кортежи с доступом по именам полей).
2. **SQLAlchemy ORM (Object-Relational Mapping)**:
   - Надстройка над Core, связывающая реляционные таблицы с классами Python.
   - Управляет состоянием объектов с помощью паттерна **Identity Map** и **Unit of Work** внутри объекта `Session`.
   - В SQLAlchemy 1.x запросы строились через устаревший метод `session.query(User).filter(...)`. В SQLAlchemy 2.0 этот API удален: теперь запросы формулируются декларативно через функцию `select()` из Core и передаются на исполнение сессии: `session.execute(select(User))`.

```mermaid
flowchart TD
    subgraph ORM_Layer["ORM Layer (SQLAlchemy ORM)"]
        MappedModels["Декларативные модели (DeclarativeBase, Mapped[T])"]
        AsyncSession["AsyncSession (Identity Map & Unit of Work)"]
        ORMSelect["select(User).options(selectinload(User.orders))"]
    end

    subgraph Core_Layer["Core Layer (SQLAlchemy Core)"]
        SQLCompiler["SQL Compiler (Компиляция AST в сырой SQL)"]
        AsyncEngine["AsyncEngine (Управление пулом соединений)"]
        Pool["QueuePool / NullPool"]
    end

    subgraph Driver_Layer["Драйверы СУБД (DBAPI / Async Driver)"]
        Asyncpg["asyncpg (PostgreSQL)"]
        Aiosqlite["aiosqlite (SQLite)"]
    end

    MappedModels --> AsyncSession
    ORMSelect --> AsyncSession
    AsyncSession --> SQLCompiler
    SQLCompiler --> AsyncEngine
    AsyncEngine --> Pool
    Pool --> Asyncpg
    Pool --> Aiosqlite
```

---

## 2. Асинхронные драйверы: asyncpg и aiosqlite

Стандартный синхронный интерфейс Python DBAPI (PEP 249) не поддерживает `async/await`. Для асинхронной работы требуются специализированные драйверы:

| Параметр | `asyncpg` (PostgreSQL) | `aiosqlite` (SQLite) |
|---|---|---|
| **Принцип работы** | Нативный бинарный протокол PostgreSQL поверх асинхронных сокетов `asyncio` | Обертка над системным блокирующим `sqlite3`, исполняющая запросы в отдельном пуле потоков (`ThreadPoolExecutor`) |
| **Строка подключения (URL)** | `postgresql+asyncpg://user:pass@host:5432/dbname` | `sqlite+aiosqlite:///./test.db` |
| **Производительность** | Экстремально высокая (быстрее `psycopg2` в 2–4 раза за счет кастомного парсера) | Умеренная (отлично подходит для локальной разработки и модульных тестов) |
| **Режим транзакций** | Автоматическая изоляция транзакций на уровне сервера | Блокировка файла БД (File Lock), осторожно при конкурентной записи |

> [!WARNING] Нюанс под капотом: Greenlet
> Поскольку исторически внутренние обработчики SQLAlchemy ORM написаны в синхронном стиле, асинхронный слой `sqlalchemy.ext.asyncio` использует микропотоки **`greenlet`** для переключения между синхронными колбэками ORM и асинхронным сокетом. Драйвер `asyncpg` требует наличия библиотеки `greenlet` в виртуальном окружении.

---

## 3. Настройка `create_async_engine` и управление Connection Pool

Создание движка — это инициализация фабрики подключений. Создавать движок нужно **один раз** при старте приложения (обычно в модуле конфигурации или `lifespan` FastAPI).

```python
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

DATABASE_URL = "postgresql+asyncpg://postgres:secret@localhost:5432/prod_db"

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Логирование сырых SQL-запросов (включать только для локальной отладки)
    future=True, # Обязательно для стиля 2.0
    poolclass=AsyncAdaptedQueuePool,
    pool_size=20,          # Базовое количество постоянно открытых постоянных соединений
    max_overflow=10,       # Максимальное количество временных соединений при пиковой нагрузке
    pool_timeout=30.0,     # Секунды ожидания свободного соединения из пула перед ошибкой TimeoutError
    pool_recycle=1800,     # Переоткрытие соединений каждые 30 минут (защита от разрыва со стороны firewall/DB)
    pool_pre_ping=True,    # Проверка "живости" соединения (SELECT 1) перед выдачей клиенту
)
```

### Параметры пула: почему важен `pool_pre_ping`?

Если сеть между FastAPI и PostgreSQL мигнула, или база данных была перезагружена администратором, соединения в пуле становятся «мертвыми» (stale/broken). Без `pool_pre_ping=True` первый запрос клиента упадет с ошибкой `ConnectionResetError` или `asyncpg.exceptions.ConnectionDoesNotExistError`. 

Параметр `pool_pre_ping=True` заставляет пул перед отдачей соединения выполнить легковесный пинг (`SELECT 1`). Если сокет мертв, пул прозрачно отбрасывает его и открывает новое соединение.

> [!TIP] Тестирование и NullPool
> В модульных тестах или при работе с serverless-функциями (AWS Lambda) используйте `poolclass=NullPool`. В этом режиме пул не удерживает соединения открытыми, предотвращая исчерпание лимита коннектов к базе.

---

## 4. Жизненный цикл сессии в FastAPI: `async_sessionmaker` и `expire_on_commit`

Сессия в SQLAlchemy (`AsyncSession`) представляет собой логическую транзакцию и локальный кэш загруженных объектов (Identity Map). Она **не потокобезопасна** и должна быть строго изолирована в рамках одного входящего HTTP-запроса.

```python
from collections.abc import AsyncGenerator
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Фабрика сессий
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,  # КРИТИЧЕСКИ ВАЖНО для FastAPI!
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI зависимость: выдает сессию на время обработки одного HTTP-запроса."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### Почему `expire_on_commit=False` критичен?

По умолчанию в синхронном SQLAlchemy `expire_on_commit=True`. Это означает, что после вызова `session.commit()` все атрибуты сохраненных моделей «инвалидируются». При следующей попытке прочитать атрибут (например, `user.email`) ORM неявно идет в базу данных через lazy loading, чтобы обновить значение.

В **асинхронном режиме неявный ввод-вывод запрещен**! Если оставить `expire_on_commit=True`, попытка вернуть модель из FastAPI роутера приведет к ошибке:
`sqlalchemy.orm.exc.DetachedInstanceError: Instance <User at ...> is not bound to a Session; attribute refresh operation cannot proceed`

Установка `expire_on_commit=False` гарантирует, что все атрибуты объекта останутся в оперативной памяти после коммита и Pydantic сможет без проблем сериализовать их в HTTP-ответ.

---

## 5. Современный Declarative Mapping: `DeclarativeBase` и `Mapped[T]`

В SQLAlchemy 2.0 отброшен устаревший подход с `declarative_base()`. Теперь используется наследование от базового класса `DeclarativeBase` со строгой статической типизацией Mypy / Pyright:

```python
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Базовый класс для всех моделей проекта
class Base(DeclarativeBase):
    pass

# Type Aliases (Custom Annotated Types) для чистоты кода
int_pk = Annotated[int, mapped_column(primary_key=True, autoincrement=True)]
created_at_col = Annotated[datetime, mapped_column(server_default=func.now())]
str_255 = Annotated[str, mapped_column(String(255))]

class User(Base):
    __tablename__ = "users"

    id: Mapped[int_pk]
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str_255] = mapped_column(unique=True)
    hashed_password: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[created_at_col]

    # Связь One-to-Many: один пользователь -> много заказов
    orders: Mapped[list["Order"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",  # Защита от случайного неявного lazy loading
    )

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    total_amount: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[created_at_col]

    # Обратная связь Many-to-One
    user: Mapped["User"] = relationship(back_populates="orders")
```

---

## 6. Связи моделей и проблема N+1

При проектировании связей выделяют:
1. **One-to-Many / Many-to-One**: Внешний ключ `ForeignKey` на дочерней таблице, `list[Child]` на родительской.
2. **Many-to-Many**: Требуется промежуточная ассоциативная таблица (`association_table`), связывающая две сущности составным первичным ключом.

### Проблема N+1 запросов

Классическая ошибка: получение списка из 100 пользователей и последующий проход по их заказам в цикле.
1. Первый запрос получает 100 пользователей: `SELECT * FROM users;` (1 запрос).
2. Для каждого пользователя выполняется отдельный запрос заказов: `SELECT * FROM orders WHERE user_id = ?;` ($N = 100$ запросов).
Итого: **101 запрос к базе данных**, порождающий катастрофическую деградацию производительности.

```mermaid
sequenceDiagram
    autonumber
    actor Client as FastAPI App
    participant DB as PostgreSQL

    Note over Client,DB: Проблема N+1 (Антипаттерн)
    Client->>DB: 1. SELECT * FROM users LIMIT 10;
    DB-->>Client: 10 строк пользователей
    loop Для каждого пользователя
        Client->>DB: 2..11. SELECT * FROM orders WHERE user_id = ?;
        DB-->>Client: Заказы пользователя
    end

    Note over Client,DB: Решение с selectinload (2 запроса суммарно)
    Client->>DB: 1. SELECT * FROM users LIMIT 10;
    DB-->>Client: 10 строк пользователей (ID: 1, 2, ..., 10)
    Client->>DB: 2. SELECT * FROM orders WHERE user_id IN (1, 2, ..., 10);
    DB-->>Client: Все заказы пачкой
```

---

## 7. Стратегии загрузки (Loading Strategies) в Async

В синхронном SQLAlchemy по умолчанию действует `lazy="select"`: атрибут загружается в момент первого обращения. В асинхронном режиме такое поведение **запрещено**: чтение атрибута — это синхронная операция, в которой нельзя сделать `await db.execute()`. Попытка прочитать незагруженное свойство приведет к ошибке:
`sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called; can't call P待 wait and no running greenlet`

Для управления выборкой связанных данных используются явные стратегии:

### 1. `selectinload` (Рекомендовано для коллекций `1-to-N` и `N-to-N`)
Выполняет второй независимый запрос с оператором `IN (...)`:
```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload

stmt = select(User).where(User.is_active == True).options(selectinload(User.orders))
result = await session.execute(stmt)
users = result.scalars().all()
# Теперь users[0].orders уже загружен в память и доступен без дополнительных запросов!
```

### 2. `joinedload` (Рекомендовано для связей `N-to-1` и `1-to-1`)
Выполняет `LEFT OUTER JOIN` в рамках одного SQL-запроса:
```python
from sqlalchemy.orm import joinedload

stmt = select(Order).options(joinedload(Order.user))
result = await session.execute(stmt)
orders = result.scalars().all()
```
> [!CAUTION] Опасность joinedload для коллекций
> Если применить `joinedload` к отношению `1-to-N`, база данных вернет декартово произведение строк (Cartesian Product). Например, пользователь с 20 заказами дублируется 20 раз в результирующем наборе данных. Это многократно увеличивает объем передаваемого трафика и нагрузку на память.

### 3. `raiseload` (Архитектурный предохранитель)
Установка `lazy="raise"` в объявлении `relationship` или в запросе гарантирует, что если разработчик забудет явно указать стратегию загрузки, ORM моментально выбросит понятное исключение во время выполнения запроса, а не в глубинах шаблонизатора или сериализатора Pydantic:
```python
from sqlalchemy.orm import raiseload

stmt = select(User).options(raiseload("*"))
```

---

## Практическое задание

Для закрепления работы с асинхронным движком, сессиями, транзакциями и стратегиями предзагрузки выполните упражнение:

👉 **[[ex_01_sqlalchemy_async.py]]**

В данном упражнении реализована чистая архитектурная модель асинхронной сессии поверх `asyncio` и `sqlite3`, воспроизводящая ключевые механики SQLAlchemy 2.0: жизненный цикл транзакции, `expire_on_commit`, обнаружение попыток неявного чтения связей и пакетную загрузку `selectinload`.

Запуск тестов:
```bash
python3 exercises/05_fastapi_data_auth/ex_01_sqlalchemy_async.py
```
