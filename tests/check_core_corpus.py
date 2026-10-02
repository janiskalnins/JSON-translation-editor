"""Core tests on real-world files: every *.xml in tests/data/real/ (gitignored, local only) goes
through load, unchanged save, one-row edit, one-row delete and a merge into itself, each on a copy
in a temporary folder, so the files themselves are never changed. Rows are counted by an
independent parser (xml.etree) as well as the app. Duplicates a file already holds are reported,
not failed; no operation may add one. An empty or missing folder is skipped with a note.

Prints one 'NOTE <file>: ...' line per file (strings, duplicate groups, load and save time), which
tests/run_all.py puts in the report's Notes section.

Run:  python tests/check_core_corpus.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import re
import shutil
import sys
import time
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import List, Tuple

xte = cs.xte

REAL = cs.DATA / "real"
FILES = sorted(REAL.glob("*.xml")) if REAL.is_dir() else []
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\r?\n")


def _copy(source: Path) -> Path:
    """A copy of *source* in a fresh temporary folder: the only file a test may change."""
    return Path(shutil.copy2(source, cs.temp_dir() / source.name))


def _etree_names(path: Path) -> List[str]:
    return [el.get("name") for el in ET.parse(str(path)).getroot().iter("string")]


def _parse(path: Path) -> Tuple[list, list]:
    segments, entries, *_ = xte.parse_file(path)
    return segments, entries


def _duplicate_groups(entries) -> int:
    return sum(1 for count in Counter(e.name for e in entries).values() if count > 1)


def _print_notes() -> None:
    if not FILES:
        print(f"NOTE no real-world files in {REAL.relative_to(cs.REPO)} — skipped", flush=True)
    for source in FILES:
        path = _copy(source)
        start = time.monotonic()
        segments, entries = _parse(path)
        loaded = time.monotonic() - start
        start = time.monotonic()
        xte.save_file(path, segments, entries)
        saved = time.monotonic() - start
        print(f"NOTE {source.name}: {len(entries)} strings, {_duplicate_groups(entries)} duplicate "
              f"group(s), load {loaded:.2f} s, save {saved:.2f} s", flush=True)


class CorpusTests(unittest.TestCase):
    """Each test runs once per file, as a subTest named after it."""

    def test_app_and_xml_parser_find_the_same_rows(self):
        for source in FILES:
            with self.subTest(file=source.name):
                self.assertEqual([e.name for e in _parse(source)[1]], _etree_names(source))

    def test_unchanged_save_is_byte_identical(self):
        for source in FILES:
            with self.subTest(file=source.name):
                path = _copy(source)
                xte.save_file(path, *_parse(path))
                self.assertEqual(path.read_bytes(), source.read_bytes())

    def test_editing_one_row_changes_only_that_row(self):
        for source in FILES:
            with self.subTest(file=source.name):
                path = _copy(source)
                segments, entries = _parse(path)
                if not entries:
                    self.skipTest("no rows")
                entry = entries[len(entries) // 2]
                entry.text += " (edited)"
                xte.save_file(path, segments, entries)
                new_segments = _parse(path)[0]
                changed = [i for i, (old, new) in enumerate(zip(segments, new_segments)) if old != new]
                self.assertEqual((len(new_segments), changed), (len(segments), [entry.seg_idx]))

    def _delete_middle_row(self, source: Path) -> Tuple[Path, str]:
        """Delete the middle row of a copy of *source* and save; returns (copy, deleted name)."""
        path = _copy(source)
        segments, entries = _parse(path)
        if not entries:
            self.skipTest("no rows")
        entry = entries[len(entries) // 2]
        xte._remove_entry_segment(segments, entry.seg_idx)
        xte.save_file(path, segments, [e for e in entries if e is not entry])
        return path, entry.name

    def test_deleting_a_row_leaves_exactly_the_other_rows(self):
        for source in FILES:
            with self.subTest(file=source.name):
                path, deleted = self._delete_middle_row(source)
                expected = _etree_names(source)
                expected.remove(deleted)
                self.assertEqual(_etree_names(path), expected)

    def test_deleting_a_row_adds_no_blank_line(self):
        for source in FILES:
            with self.subTest(file=source.name):
                path, _ = self._delete_middle_row(source)
                before = len(_BLANK_LINE_RE.findall(source.read_bytes().decode("utf-8")))
                self.assertEqual(len(_BLANK_LINE_RE.findall(path.read_bytes().decode("utf-8"))),
                                 before)

    def test_merging_the_file_into_itself_changes_nothing(self):
        for source in FILES:
            with self.subTest(file=source.name):
                path = _copy(source)
                segments, entries = _parse(path)
                if _duplicate_groups(entries):
                    self.skipTest("the file has duplicates, so Merge refuses it")
                diff = xte.compute_merge_diff(entries, _parse(source)[1])
                segments, entries = xte.insert_additions(segments, entries, diff.additions)
                xte.save_file(path, segments, entries)
                self.assertEqual(path.read_bytes(), source.read_bytes())


if __name__ == "__main__":
    _print_notes()
    sys.exit(cs.run_suite(sys.modules[__name__]))
