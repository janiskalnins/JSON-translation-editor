"""Core tests: dates and filtering. parse_date() on every supported format,
format_date_for_storage() round trips, and FilterEngine's search modes, fields and filters.

Run:  python tests/check_core_dates_filter.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import sys
import unittest
from datetime import date
from typing import List

from PySide6.QtCore import QDate

jte = cs.jte

MAY_6 = date(2016, 5, 6)
SLASH_DATE = MAY_6 if jte._LOCALE_DAY_FIRST else date(2016, 6, 5)


def _stored(d: date) -> str:
    return jte.format_date_for_storage(d)


class ParseDateTests(unittest.TestCase):
    def test_supported_formats_parse(self):
        cases = {"06.05.2016": MAY_6, "2016-05-06": MAY_6, "06-05-2016": MAY_6, "06.05.16": MAY_6,
                 "2016.05.06": MAY_6, "2016.05.06.": MAY_6, "  06.05.2016 ": MAY_6,
                 "06/05/2016": SLASH_DATE, "06/05/16": SLASH_DATE}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(jte.parse_date(text), expected)

    def test_garbage_and_empty_parse_to_none(self):
        for text in ("foo", "", "32.13.2016", "2016"):
            with self.subTest(text=text):
                self.assertIsNone(jte.parse_date(text))

    def test_storage_format_round_trips(self):
        self.assertEqual(jte.parse_date(_stored(date(2025, 12, 31))), date(2025, 12, 31))

    def test_qdate_is_stored_like_a_date(self):
        self.assertEqual(jte.format_date_for_storage(QDate(2025, 12, 31)), _stored(date(2025, 12, 31)))


ENTRIES = [
    cs.make_entry(name="Tablet mode", text="Planšetes režīms", translator="Anna", status="Complete",
                  modify_date=_stored(date(2025, 1, 10))),
    cs.make_entry(name="Database", text="Datu bāze", translator="Bob", status="New",
                  modify_date=_stored(date(2025, 3, 1))),
    cs.make_entry(name="data-tablet (x)", text="Cits", translator="anna k", status="Review",
                  modify_date="nonsense"),
]


def _visible(**settings) -> List[str]:
    """Names of ENTRIES that a FilterEngine with *settings* lets through."""
    engine = jte.FilterEngine()
    for key, value in settings.items():
        setattr(engine, key, value)
    return [e.name for e in ENTRIES if engine.matches(e)]


class FilterEngineTests(unittest.TestCase):
    def test_starts_with_matches_at_word_starts_only(self):
        self.assertEqual(_visible(search_text="tab"), ["Tablet mode", "data-tablet (x)"])

    def test_contains_matches_inside_words(self):
        self.assertEqual(_visible(search_text="tab", search_mode="contains"),
                         ["Tablet mode", "Database", "data-tablet (x)"])

    def test_source_field_ignores_the_translation(self):
        self.assertEqual(_visible(search_text="datu", search_field="source"), [])

    def test_translated_field_ignores_the_source(self):
        self.assertEqual(_visible(search_text="datu", search_field="translated"), ["Database"])

    def test_regex_metacharacters_are_literal(self):
        self.assertEqual(_visible(search_text="d.t"), [])

    def test_parentheses_are_literal_in_contains_mode(self):
        self.assertEqual(_visible(search_text="(x)", search_mode="contains"), ["data-tablet (x)"])

    def test_search_ignores_case(self):
        self.assertEqual(_visible(search_text="TABLET"), ["Tablet mode", "data-tablet (x)"])

    def test_status_filter(self):
        self.assertEqual(_visible(status="New"), ["Database"])

    def test_translator_filter_is_a_case_insensitive_substring(self):
        self.assertEqual(_visible(translator="anna"), ["Tablet mode", "data-tablet (x)"])

    def test_date_from_keeps_later_and_unparseable_dates(self):
        self.assertEqual(_visible(date_from=date(2025, 2, 1)), ["Database", "data-tablet (x)"])

    def test_date_to_keeps_earlier_and_unparseable_dates(self):
        self.assertEqual(_visible(date_to=date(2025, 2, 1)), ["Tablet mode", "data-tablet (x)"])

    def test_date_range_keeps_dates_inside_it(self):
        self.assertEqual(_visible(date_from=date(2025, 1, 1), date_to=date(2025, 1, 31)),
                         ["Tablet mode", "data-tablet (x)"])

    def test_filters_combine(self):
        self.assertEqual(_visible(search_text="tab", status="Review"), ["data-tablet (x)"])

    def test_compiled_pattern_gives_the_same_result(self):
        engine = jte.FilterEngine()
        engine.search_text = "tab"
        pattern = engine.compiled_search_pattern()
        self.assertEqual([engine.matches(e, pattern) for e in ENTRIES],
                         [engine.matches(e) for e in ENTRIES])


class NoTabletColumnTests(unittest.TestCase):
    def test_table_has_no_tablet_column(self):
        self.assertNotIn("Tablet", jte.HEADERS)



class PlaceholderTests(unittest.TestCase):
    def test_warning_text(self):
        cases = {
            "same set": ("Path {n}", "Trazado {n}", ""),
            "missing": ("{name} saved", "guardado", "Missing: {name}"),
            "extra": ("saved", "{nme} guardado", "Extra: {nme}"),
            "both": ("{a} {b}", "{a} {c}", "Missing: {b} · Extra: {c}"),
            "order and repeats ignored": ("{a} {b}", "{b} {a} {a}", ""),
            "angle brackets are not placeholders": ("<path>", "<trazado>", ""),
            "empty braces count": ("{}", "", "Missing: {}"),
        }
        for label, (source, translation, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(jte.placeholder_warning(source, translation), expected)

    def test_filter_keeps_only_mismatches(self):
        engine = jte.FilterEngine()
        engine.check = "placeholders"
        entries = [cs.make_entry(name="{n} a", text="{n} b"), cs.make_entry(name="{n} c", text="d")]
        self.assertEqual([e.text for e in entries if engine.matches(e)], ["d"])


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))
