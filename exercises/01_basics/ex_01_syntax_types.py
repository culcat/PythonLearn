#!/usr/bin/env python3
"""Практические задания к Главе 01: Синтаксис, типы, переменные и модель памяти.

Запуск тестов:
    python3 exercises/01_basics/ex_01_syntax_types.py

Задания:
1. analyze_type_and_identity:
   Анализ двух объектов на равенство значений (==), идентичность в памяти (is),
   совпадение типов и признак мутабельности стандартных типов CPython.
2. calculate_financial_total:
   Точный финансовый расчет суммы с учетом налога с использованием `decimal.Decimal`
   и банковского/стандартного округления `ROUND_HALF_UP` до 2 знаков.
3. parse_and_format_user_info:
   Парсинг CSV-строки пользователя с валидацией через оператор моржа `:=`
   и форматирование в аккуратную визитную карточку через f-strings.
4. is_small_int_interned:
   Проверка попадания целого числа в диапазон интернирования CPython [-5; 256].
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import unittest


# =====================================================================
# ЗАДАНИЕ 1: Анализ идентичности и мутабельности объектов
# =====================================================================
def analyze_type_and_identity(a: object, b: object) -> dict[str, bool | str | int]:
    """Анализирует два объекта Python на равенство значений, адресов и мутабельность.

    Возвращает словарь со следующими ключами:
    - 'same_type': совпадает ли точный тип объектов
    - 'same_value': равны ли объекты по значению (==)
    - 'same_identity': ссылаются ли переменные на один объект в памяти (is)
    - 'a_id': целочисленный адрес объекта `a` (id)
    - 'b_id': целочисленный адрес объекта `b` (id)
    - 'a_type_name': строковое имя типа `a`
    - 'b_type_name': строковое имя типа `b`
    - 'a_is_mutable': является ли тип объекта `a` изменяемым (list, dict, set, bytearray)
    - 'b_is_mutable': является ли тип объекта `b` изменяемым
    """
    mutable_types = (list, dict, set, bytearray)
    return {
        "same_type": type(a) is type(b),
        "same_value": bool(a == b),
        "same_identity": a is b,
        "a_id": id(a),
        "b_id": id(b),
        "a_type_name": type(a).__name__,
        "b_type_name": type(b).__name__,
        "a_is_mutable": isinstance(a, mutable_types),
        "b_is_mutable": isinstance(b, mutable_types),
    }


# =====================================================================
# ЗАДАНИЕ 2: Финансовые расчеты повышенной точности (Decimal)
# =====================================================================
def calculate_financial_total(prices: list[str], tax_rate: str) -> str:
    """Вычисляет общую сумму цен с учетом ставки налога и возвращает строку с 2 знаками.

    Использует `decimal.Decimal` для предотвращения накопления погрешности IEEE 754.
    Округление производится методом `ROUND_HALF_UP`.

    Пример:
        calculate_financial_total(["10.25", "5.50"], "0.20") -> "18.90"
        (10.25 + 5.50 = 15.75; 15.75 * 1.20 = 18.90)

    Выбрасывает:
        ValueError: если передан пустой список цен или некорректная строка числа.
    """
    if not prices:
        raise ValueError("Список цен не может быть пустым.")

    try:
        tax = Decimal(tax_rate)
        if tax < Decimal("0"):
            raise ValueError("Налоговая ставка не может быть отрицательной.")

        subtotal = Decimal("0")
        for p in prices:
            price_val = Decimal(p)
            if price_val < Decimal("0"):
                raise ValueError("Цена не может быть отрицательной.")
            subtotal += price_val

        total = subtotal * (Decimal("1") + tax)
        quantized = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return str(quantized)
    except InvalidOperation as err:
        raise ValueError(f"Ошибка парсинга числа Decimal: {err}") from err


# =====================================================================
# ЗАДАНИЕ 3: Валидация и форматирование через Walrus и f-strings
# =====================================================================
def parse_and_format_user_info(raw_csv_line: str) -> str:
    """Парсит CSV-строку вида 'имя, возраст, баланс' и возвращает отформатированную строку.

    Пример входа:
        "  alice, 28 , 12500.5 "
    Пример выхода:
        "User: Alice | Age: 28 | Balance: $12,500.50"

    Требования:
    - Разбить строку по запятой, очистить пробелы.
    - Проверить, что ровно 3 поля.
    - Использовать оператор `:=` для валидации возраста и баланса.
    - Возраст — целое положительное число (int > 0).
    - Баланс — число с плавающей точкой/Decimal >= 0.
    - Имя форматируется через title().

    Выбрасывает:
        ValueError: при неверном формате строки или невалидных данных.
    """
    parts = [p.strip() for p in raw_csv_line.split(",")]
    if len(parts) != 3:
        raise ValueError(f"Ожидалось 3 поля, получено {len(parts)}: '{raw_csv_line}'")

    raw_name, raw_age, raw_balance = parts

    if not (clean_name := raw_name.strip()):
        raise ValueError("Имя пользователя не может быть пустым.")

    try:
        if (age := int(raw_age)) <= 0:
            raise ValueError("Возраст должен быть положительным числом.")
    except ValueError as err:
        raise ValueError(f"Некорректный возраст '{raw_age}': {err}") from err

    try:
        if (balance := float(raw_balance)) < 0.0:
            raise ValueError("Баланс не может быть отрицательным.")
    except ValueError as err:
        raise ValueError(f"Некорректный баланс '{raw_balance}': {err}") from err

    return f"User: {clean_name.title()} | Age: {age} | Balance: ${balance:,.2f}"


# =====================================================================
# ЗАДАНИЕ 4: Определение интернирования целых чисел
# =====================================================================
def is_small_int_interned(val: int) -> bool:
    """Проверяет, входит ли целое число в диапазон интернирования CPython [-5, 256]."""
    return -5 <= val <= 256


# =====================================================================
# МОДУЛЬНЫЕ ТЕСТЫ (UNIT TESTS)
# =====================================================================
class TestSyntaxTypesVariables(unittest.TestCase):
    def test_analyze_identical_lists(self) -> None:
        lst1 = [1, 2, 3]
        lst2 = lst1
        res = analyze_type_and_identity(lst1, lst2)
        self.assertTrue(res["same_type"])
        self.assertTrue(res["same_value"])
        self.assertTrue(res["same_identity"])
        self.assertTrue(res["a_is_mutable"])
        self.assertEqual(res["a_type_name"], "list")

    def test_analyze_equal_different_lists(self) -> None:
        lst1 = [1, 2, 3]
        lst2 = [1, 2, 3]
        res = analyze_type_and_identity(lst1, lst2)
        self.assertTrue(res["same_type"])
        self.assertTrue(res["same_value"])
        self.assertFalse(res["same_identity"])  # Разные объекты в куче
        self.assertNotEqual(res["a_id"], res["b_id"])

    def test_analyze_immutable_types(self) -> None:
        s1 = "hello"
        t1 = (1, 2)
        res = analyze_type_and_identity(s1, t1)
        self.assertFalse(res["same_type"])
        self.assertFalse(res["a_is_mutable"])
        self.assertFalse(res["b_is_mutable"])

    def test_calculate_financial_total_success(self) -> None:
        prices = ["10.25", "5.50", "4.25"]  # 20.00
        tax = "0.20"  # 20.00 * 1.2 = 24.00
        total = calculate_financial_total(prices, tax)
        self.assertEqual(total, "24.00")

    def test_calculate_financial_total_rounding(self) -> None:
        # 10.005 * 1.0 = 10.01 при ROUND_HALF_UP
        prices = ["10.005"]
        tax = "0.0"
        total = calculate_financial_total(prices, tax)
        self.assertEqual(total, "10.01")

    def test_calculate_financial_total_invalid_input(self) -> None:
        with self.assertRaises(ValueError):
            calculate_financial_total([], "0.20")

        with self.assertRaises(ValueError):
            calculate_financial_total(["10.00", "invalid_price"], "0.20")

        with self.assertRaises(ValueError):
            calculate_financial_total(["-10.00"], "0.20")

    def test_parse_and_format_user_info_valid(self) -> None:
        raw = "  john doe , 30 , 1250000.75 "
        expected = "User: John Doe | Age: 30 | Balance: $1,250,000.75"
        self.assertEqual(parse_and_format_user_info(raw), expected)

    def test_parse_and_format_user_info_invalid_fields(self) -> None:
        with self.assertRaises(ValueError):
            parse_and_format_user_info("only, two_fields")

        with self.assertRaises(ValueError):
            parse_and_format_user_info("john, -5, 100")

        with self.assertRaises(ValueError):
            parse_and_format_user_info("  , 25, 100")

    def test_small_int_interning_boundary(self) -> None:
        self.assertTrue(is_small_int_interned(-5))
        self.assertTrue(is_small_int_interned(0))
        self.assertTrue(is_small_int_interned(256))
        self.assertFalse(is_small_int_interned(-6))
        self.assertFalse(is_small_int_interned(257))


if __name__ == "__main__":
    unittest.main(verbosity=2)
