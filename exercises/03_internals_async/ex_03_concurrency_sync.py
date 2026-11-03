#!/usr/bin/env python3
"""Упражнение 03: Многопоточность, синхронизация и concurrent.futures.

Тема: Потокобезопасный счетчик ThreadSafeCounter с защитой от Race Condition,
ограниченный пул воркеров BoundedWorkerPool на Semaphore и Event,
параллельный вычислитель parallel_compute с сбором ошибок на concurrent.futures.

Запуск тестов:
    python3 exercises/03_internals_async/ex_03_concurrency_sync.py
    или из корня:
    python3 run_all_tests.py
"""

from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import Executor, Future, ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, TypeVar

T = TypeVar("T")
R = TypeVar("R")


# =====================================================================
# ЗАДАНИЕ 1: Потокобезопасный счетчик
# =====================================================================

class ThreadSafeCounter:
    """Счетчик с потокобезопасной инкрементацией на базе threading.Lock."""

    def __init__(self, initial_value: int = 0) -> None:
        self._value: int = initial_value
        self._lock = threading.Lock()

    def increment(self, step: int = 1) -> int:
        """Атомарно увеличивает счетчик на шаг step и возвращает новое значение."""
        with self._lock:
            self._value += step
            return self._value

    def decrement(self, step: int = 1) -> int:
        """Атомарно уменьшает счетчик на шаг step и возвращает новое значение."""
        with self._lock:
            self._value -= step
            return self._value

    @property
    def value(self) -> int:
        """Возвращает текущее значение счетчика под блокировкой."""
        with self._lock:
            return self._value


class UnsafeCounter:
    """Незащищенный счетчик для демонстрации состояния гонки (Race Condition)."""

    def __init__(self, initial_value: int = 0) -> None:
        self.value: int = initial_value

    def increment(self, step: int = 1) -> None:
        current = self.value
        # Небольшая пауза провоцирует переключение потока
        time.sleep(0.000001)
        self.value = current + step


# =====================================================================
# ЗАДАНИЕ 2: BoundedWorkerPool с ограничением параллелизма
# =====================================================================

class BoundedWorkerPool:
    """Пул воркеров с жестким ограничением параллелизма на Semaphore.

    - Ограничивает число одновременно работающих потоков через Semaphore.
    - Отслеживает текущее число активных воркеров и пиковую нагрузку.
    - Управляет сигнализацией остановки через Event.
    """

    def __init__(self, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency должен быть >= 1")

        self.max_concurrency = max_concurrency
        self._semaphore = threading.BoundedSemaphore(max_concurrency)
        self._shutdown_event = threading.Event()

        self._active_count: int = 0
        self._peak_count: int = 0
        self._metrics_lock = threading.Lock()

    def run_task(self, task: Callable[[], T]) -> T:
        """Выполняет задачу с гарантией ограничения параллелизма."""
        if self._shutdown_event.is_set():
            raise RuntimeError("Пул находится в состоянии shutdown!")

        acquired = self._semaphore.acquire(timeout=5.0)
        if not acquired:
            raise TimeoutError("Не удалось получить слот в пуле за отведенное время.")

        try:
            with self._metrics_lock:
                self._active_count += 1
                if self._active_count > self._peak_count:
                    self._peak_count = self._active_count

            return task()
        finally:
            with self._metrics_lock:
                self._active_count -= 1
            self._semaphore.release()

    def shutdown(self) -> None:
        """Устанавливает флаг остановки."""
        self._shutdown_event.set()

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown_event.is_set()

    @property
    def peak_concurrency(self) -> int:
        with self._metrics_lock:
            return self._peak_count

    @property
    def active_workers(self) -> int:
        with self._metrics_lock:
            return self._active_count


# =====================================================================
# ЗАДАНИЕ 3: Отказоустойчивый параллельный вычислитель
# =====================================================================

def parallel_compute(
    tasks: List[Callable[[], R]],
    max_workers: int = 4,
    timeout: Optional[float] = 5.0,
    executor_cls: type[Executor] = ThreadPoolExecutor,
) -> Dict[int, Any]:
    """Параллельно выполняет список задач через Executor и as_completed.

    Возвращает словарь:
        {task_index: result_or_exception}

    Если задача выбросила исключение, в словаре сохраняется сам объект исключения,
    а не происходит прерывание всей функции.
    """
    results: Dict[int, Any] = {}

    with executor_cls(max_workers=max_workers) as executor:
        future_to_index: Dict[Future[R], int] = {
            executor.submit(task): idx
            for idx, task in enumerate(tasks)
        }

        for future in as_completed(future_to_index, timeout=timeout):
            idx = future_to_index[future]
            try:
                res = future.result()
                results[idx] = res
            except Exception as exc:
                results[idx] = exc

    return results


# =====================================================================
# МОДУЛЬНЫЕ ТЕСТЫ
# =====================================================================

class TestConcurrencyAndSync(unittest.TestCase):
    def test_thread_safe_counter(self) -> None:
        """Проверка безопасного инкремента из множества параллельных потоков."""
        counter = ThreadSafeCounter()
        threads_count = 10
        increments_per_thread = 500

        def worker() -> None:
            for _ in range(increments_per_thread):
                counter.increment()

        threads = [threading.Thread(target=worker) for _ in range(threads_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Итоговое значение должно быть строго равно 10 * 500 = 5000
        self.assertEqual(counter.value, threads_count * increments_per_thread)

    def test_thread_safe_counter_decrement(self) -> None:
        """Проверка безопасного декремента."""
        counter = ThreadSafeCounter(100)
        counter.decrement(30)
        self.assertEqual(counter.value, 70)

    def test_bounded_worker_pool_concurrency_limit(self) -> None:
        """Проверка жесткого ограничения параллелизма через Semaphore."""
        max_allowed = 3
        pool = BoundedWorkerPool(max_concurrency=max_allowed)
        total_tasks = 10

        def sleep_task() -> str:
            time.sleep(0.05)
            return "done"

        results: List[str] = []
        threads: List[threading.Thread] = []

        def runner() -> None:
            res = pool.run_task(sleep_task)
            results.append(res)

        for _ in range(total_tasks):
            t = threading.Thread(target=runner)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(results), total_tasks)
        # Пиковое количество активных потоков не должно превышать лимит семафора!
        self.assertLessEqual(pool.peak_concurrency, max_allowed)
        self.assertEqual(pool.active_workers, 0)

    def test_bounded_worker_pool_shutdown(self) -> None:
        """Проверка невозможности запуска задач после shutdown."""
        pool = BoundedWorkerPool(max_concurrency=2)
        pool.shutdown()
        self.assertTrue(pool.is_shutdown)

        with self.assertRaises(RuntimeError) as ctx:
            pool.run_task(lambda: "never")
        self.assertIn("shutdown", str(ctx.exception))

    def test_parallel_compute_success_and_errors(self) -> None:
        """Проверка parallel_compute со смешанными успешными задачами и исключениями."""
        def good_task_1() -> int:
            return 10 + 20

        def bad_task_2() -> int:
            raise ZeroDivisionError("Деление на ноль!")

        def good_task_3() -> str:
            return "hello"

        tasks: List[Callable[[], Any]] = [good_task_1, bad_task_2, good_task_3]
        results = parallel_compute(tasks, max_workers=2)

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0], 30)
        self.assertIsInstance(results[1], ZeroDivisionError)
        self.assertEqual(results[2], "hello")


if __name__ == "__main__":
    unittest.main(verbosity=2)
