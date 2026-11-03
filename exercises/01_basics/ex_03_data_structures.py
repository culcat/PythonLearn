#!/usr/bin/env python3
"""Практические задания к Главе 03: Структуры данных и алгоритмическая сложность.

Запуск тестов:
    python3 exercises/01_basics/ex_03_data_structures.py

Задания:
1. analyze_word_frequencies:
   Очистка текста и подсчет частотности N наиболее употребляемых слов с помощью `collections.Counter`.
2. group_transactions_by_category:
   Группировка потока финансовых транзакций по категориям с помощью `collections.defaultdict`.
3. sliding_window_maximum:
   Вычисление максимума в скользящем окне размера K за оптимальное время O(N)
   с использованием монотонной двусвязной очереди `collections.deque`.
4. compute_set_metrics:
   Вычисление реляционных метрик множеств (объединение, пересечение, разность, индекс Жаккара).
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
import re
import unittest


# =====================================================================
# ЗАДАНИЕ 1: Анализ частотности слов через Counter
# =====================================================================
def analyze_word_frequencies(text: str, top_n: int = 5) -> list[tuple[str, int]]:
    """Приводит текст к нижнему регистру, извлекает слова и возвращает топ-N частотных слов.

    Словами считаются последовательности букв и цифр [a-zA-Zа-яА-Я0-9_]+.
    Знаки пунктуации и спецсимволы игнорируются.

    Выбрасывает:
        ValueError: если top_n <= 0.
    """
    if top_n <= 0:
        raise ValueError("Параметр top_n должен быть положительным числом.")

    words = re.findall(r"\b\w+\b", text.lower())
    counter = Counter(words)
    return counter.most_common(top_n)


# =====================================================================
# ЗАДАНИЕ 2: Группировка транзакций через defaultdict
# =====================================================================
def group_transactions_by_category(
    transactions: list[tuple[str, float]],
) -> dict[str, list[float]]:
    """Группирует список кортежей (категория, сумма) в словарь {категория: [суммы]}.

    Использует `defaultdict(list)` для избежания ручных проверок `if category not in dict`.
    Возвращает стандартный словарь dict.
    """
    grouped: defaultdict[str, list[float]] = defaultdict(list)
    for category, amount in transactions:
        clean_cat = category.strip()
        grouped[clean_cat].append(float(amount))

    return dict(grouped)


# =====================================================================
# ЗАДАНИЕ 3: Максимум в скользящем окне за O(N) через deque
# =====================================================================
def sliding_window_maximum(numbers: list[int], k: int) -> list[int]:
    """Находит максимальный элемент в каждом скользящем окне размера k за время O(N).

    Алгоритм использует монотонно убывающую очередь `deque`, хранящую индексы элементов:
    - Индексы за пределами текущего окна удаляются слева (popleft).
    - Элементы, меньшие текущего добавляемого, удаляются справа (pop),
      так как они больше никогда не смогут быть максимумом в текущем или будущих окнах.

    Выбрасывает:
        ValueError: если список numbers пуст, или k < 1, или k > len(numbers).
    """
    n = len(numbers)
    if n == 0:
        raise ValueError("Список чисел не может быть пустым.")
    if k < 1 or k > n:
        raise ValueError(f"Размер окна k={k} должен быть в диапазоне [1, {n}].")

    d: deque[int] = deque()
    result: list[int] = []

    for i in range(n):
        # 1. Удаляем элементы, вышедшие за пределы левой границы окна [i - k + 1, i]
        while d and d[0] <= i - k:
            d.popleft()

        # 2. Поддерживаем монотонность: удаляем индексы меньших элементов справа
        while d and numbers[d[-1]] <= numbers[i]:
            d.pop()

        d.append(i)

        # 3. Как только окно заполнилось до размера k, записываем максимум (находится в d[0])
        if i >= k - 1:
            result.append(numbers[d[0]])

    return result


# =====================================================================
# ЗАДАНИЕ 4: Метрики и операции над множествами
# =====================================================================
def compute_set_metrics(
    cohort_a: set[int],
    cohort_b: set[int],
) -> dict[str, set[int] | float]:
    """Вычисляет теоретико-множественные операции и коэффициент сходства Жаккара.

    Ключи возвращаемого словаря:
    - 'union': A | B
    - 'intersection': A & B
    - 'only_a': A - B
    - 'only_b': B - A
    - 'symmetric_diff': A ^ B
    - 'jaccard_similarity': |A & B| / |A | B| (если оба пусты, возвращается 0.0)
    """
    union_set = cohort_a | cohort_b
    intersection_set = cohort_a & cohort_b

    if not union_set:
        jaccard = 0.0
    else:
        jaccard = len(intersection_set) / len(union_set)

    return {
        "union": union_set,
        "intersection": intersection_set,
        "only_a": cohort_a - cohort_b,
        "only_b": cohort_b - cohort_a,
        "symmetric_diff": cohort_a ^ cohort_b,
        "jaccard_similarity": round(jaccard, 4),
    }


# =====================================================================
# МОДУЛЬНЫЕ ТЕСТЫ (UNIT TESTS)
# =====================================================================
class TestDataStructures(unittest.TestCase):
    def test_word_frequencies_normal(self) -> None:
        text = "FastAPI is fast. Python is great, and FastAPI is modern!"
        res = analyze_word_frequencies(text, top_n=2)
        expected = [("is", 3), ("fastapi", 2)]
        self.assertEqual(res, expected)

    def test_word_frequencies_invalid_top_n(self) -> None:
        with self.assertRaises(ValueError):
            analyze_word_frequencies("test", top_n=0)

    def test_group_transactions(self) -> None:
        txs = [
            ("food", 15.5),
            ("transport", 3.0),
            ("food", 42.0),
            ("entertainment", 100.0),
            ("transport", 2.5),
        ]
        res = group_transactions_by_category(txs)
        self.assertEqual(res["food"], [15.5, 42.0])
        self.assertEqual(res["transport"], [3.0, 2.5])
        self.assertEqual(res["entertainment"], [100.0])

    def test_group_transactions_empty(self) -> None:
        self.assertEqual(group_transactions_by_category([]), {})

    def test_sliding_window_maximum_standard(self) -> None:
        nums = [1, 3, -1, -3, 5, 3, 6, 7]
        k = 3
        # Окна: [1,3,-1]->3, [3,-1,-3]->3, [-1,-3,5]->5, [-3,5,3]->5, [5,3,6]->6, [3,6,7]->7
        expected = [3, 3, 5, 5, 6, 7]
        self.assertEqual(sliding_window_maximum(nums, k), expected)

    def test_sliding_window_maximum_k_equals_one(self) -> None:
        nums = [4, 2, 7, 1]
        self.assertEqual(sliding_window_maximum(nums, 1), [4, 2, 7, 1])

    def test_sliding_window_maximum_k_equals_len(self) -> None:
        nums = [4, 2, 9, 1]
        self.assertEqual(sliding_window_maximum(nums, 4), [9])

    def test_sliding_window_maximum_invalid_k(self) -> None:
        with self.assertRaises(ValueError):
            sliding_window_maximum([1, 2, 3], 0)
        with self.assertRaises(ValueError):
            sliding_window_maximum([1, 2, 3], 4)
        with self.assertRaises(ValueError):
            sliding_window_maximum([], 1)

    def test_compute_set_metrics(self) -> None:
        a = {1, 2, 3, 4}
        b = {3, 4, 5, 6}
        res = compute_set_metrics(a, b)
        self.assertEqual(res["union"], {1, 2, 3, 4, 5, 6})
        self.assertEqual(res["intersection"], {3, 4})
        self.assertEqual(res["only_a"], {1, 2})
        self.assertEqual(res["only_b"], {5, 6})
        self.assertEqual(res["symmetric_diff"], {1, 2, 5, 6})
        # 2 / 6 = 0.3333
        self.assertEqual(res["jaccard_similarity"], 0.3333)

    def test_compute_set_metrics_empty(self) -> None:
        res = compute_set_metrics(set(), set())
        self.assertEqual(res["jaccard_similarity"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
