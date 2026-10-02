"""Core tests: the per-file glossary. parse_glossary()'s recovery (encodings, delimiters, headers,
bad rows), the write/parse round trip, _match_glossary()'s whole-word and plural matching, and
glossary_path_for().

Run:  python tests/check_core_glossary.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import sys
import unittest
from pathlib import Path
from typing import List, Tuple

jte = cs.jte
G = jte.GlossaryEntry

LANE = G("Lane", "Celiņš", "x")
LANE_BARE = G("Lane", "Celiņš")
BALL = G("Ball", "Bumba")


def _parse(data: bytes) -> Tuple[list, List[str]]:
    return jte.parse_glossary(cs.write_exact(cs.temp_dir() / "es.glossary.csv", data))


class ParseGlossaryTests(unittest.TestCase):
    def test_utf8_with_bom_is_read(self):
        entries, _ = _parse("\ufeffterm,translation,note\nLane,Celiņš,x\n".encode("utf-8"))
        self.assertEqual(entries, [LANE])

    def test_clean_utf8_file_gives_no_warnings(self):
        _, warnings = _parse("\ufeffterm,translation,note\nLane,Celiņš,x\n".encode("utf-8"))
        self.assertEqual(warnings, [])

    def test_cp1257_file_keeps_latvian_letters(self):
        entries, _ = _parse("term;translation;note\nLane;Celiņš;x\n".encode("cp1257"))
        self.assertEqual(entries, [LANE])

    def test_cp1257_file_warns_about_the_encoding(self):
        _, warnings = _parse("term;translation;note\nLane;Celiņš;x\n".encode("cp1257"))
        self.assertTrue(any("not valid UTF-8" in w for w in warnings), warnings)

    def test_delimiters_are_detected(self):
        for delimiter in (",", ";", "\t"):
            with self.subTest(delimiter=repr(delimiter)):
                text = delimiter.join(["term", "translation"]) + "\n" + \
                    delimiter.join(["Lane", "Celiņš"]) + "\n" + delimiter.join(["Ball", "Bumba"]) + "\n"
                self.assertEqual(_parse(text.encode("utf-8"))[0], [LANE_BARE, BALL])

    def test_non_comma_delimiter_warns(self):
        for delimiter in (";", "\t"):
            with self.subTest(delimiter=repr(delimiter)):
                text = f"term{delimiter}translation\nLane{delimiter}Celiņš\nBall{delimiter}Bumba\n"
                _, warnings = _parse(text.encode("utf-8"))
                self.assertTrue(any("field separator" in w for w in warnings), warnings)

    def test_header_aliases_case_and_order_are_understood(self):
        entries, _ = _parse("Notes,Translation,TERM\nn,Celiņš,Lane\n".encode("utf-8"))
        self.assertEqual(entries, [G("Lane", "Celiņš", "n")])

    def test_file_without_a_header_is_read_by_position(self):
        entries, _ = _parse("Lane,Celiņš\nBall,Bumba\n".encode("utf-8"))
        self.assertEqual(entries, [LANE_BARE, BALL])

    def test_file_without_a_header_warns(self):
        _, warnings = _parse("Lane,Celiņš\nBall,Bumba\n".encode("utf-8"))
        self.assertTrue(any("no recognized header" in w for w in warnings), warnings)

    def test_short_and_blank_rows_are_skipped(self):
        entries, _ = _parse("term,translation\nLane,Celiņš\n\nBall\n".encode("utf-8"))
        self.assertEqual(entries, [LANE_BARE])

    def test_skipped_rows_are_reported(self):
        _, warnings = _parse("term,translation\nLane,Celiņš\n\nBall\n".encode("utf-8"))
        self.assertEqual(warnings, ["skipped 2 row(s) missing a term or translation"])

    def test_missing_file_is_empty_without_warnings(self):
        self.assertEqual(jte.parse_glossary(cs.temp_dir() / "none.glossary.csv"), ([], []))

    def test_empty_file_is_empty_without_warnings(self):
        self.assertEqual(_parse(b""), ([], []))


class WriteGlossaryTests(unittest.TestCase):
    ENTRIES = [G("Lane", "Celiņš", 'a "note", with comma'), G("Pin setter", "Ķegļu cēlājs")]

    def test_write_then_parse_round_trips(self):
        path = cs.temp_dir() / "es.glossary.csv"
        jte.write_glossary(path, self.ENTRIES)
        self.assertEqual(jte.parse_glossary(path), (self.ENTRIES, []))

    def test_written_file_has_a_bom_and_the_canonical_header(self):
        path = cs.temp_dir() / "es.glossary.csv"
        jte.write_glossary(path, self.ENTRIES)
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbfterm,translation,note"))


GLOSSARY = [G("Lane", "Celiņš"), G("box", "kaste"), G("pin setter", "ķegļu cēlājs")]


def _matched(text: str) -> List[str]:
    return [g.term for g in jte._match_glossary(text, GLOSSARY)]


class MatchGlossaryTests(unittest.TestCase):
    def test_whole_word_matches(self):
        self.assertEqual(_matched("Open lane 3"), ["Lane"])

    def test_match_ignores_case(self):
        self.assertEqual(_matched("LANE"), ["Lane"])

    def test_plural_with_s_matches(self):
        self.assertEqual(_matched("Lanes"), ["Lane"])

    def test_plural_with_es_matches(self):
        self.assertEqual(_matched("Boxes"), ["box"])

    def test_term_inside_a_word_does_not_match(self):
        self.assertEqual(_matched("inbox planet"), [])

    def test_phrase_matches(self):
        self.assertEqual(_matched("the Pin Setter"), ["pin setter"])

    def test_every_matching_term_is_returned(self):
        self.assertEqual(_matched("Lane and pin setter"), ["Lane", "pin setter"])


class GlossaryPathTests(unittest.TestCase):
    def test_glossary_sits_next_to_the_language_file(self):
        self.assertEqual(jte.glossary_path_for(Path("C:/work/es.json")),
                         Path("C:/work/es.glossary.csv"))


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))
