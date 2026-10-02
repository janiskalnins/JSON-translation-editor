"""Core tests on real-world files: every *.json in tests/data/real/ (gitignored, local only), with
its .json.meta sidecar when one sits beside it, goes through load, unchanged save, one-entry edit,
one-entry delete and a merge into itself, each on a copy in a temporary folder, so the files
themselves are never changed. Keys are read by an independent parser (the json module) as well as
the app. A file that does not round-trip in its own style is noted, and skipped by the
byte-identical test. An empty or missing folder is skipped with a note.

Prints one 'NOTE <file>: ...' line per file (strings, load and save time), which tests/run_all.py
puts in the report's Notes section.

Run:  python tests/check_core_corpus.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import json
import shutil
import sys
import time
import unittest
from pathlib import Path
from typing import List, Tuple

jte = cs.jte

REAL = cs.DATA / "real"
FILES = sorted(REAL.glob("*.json")) if REAL.is_dir() else []


def _copy(source: Path) -> Path:
    """A copy of *source* (and its sidecar, if any) in a fresh temporary folder: the only files a
    test may change."""
    folder = cs.temp_dir()
    meta = jte.meta_path_for(source)
    if meta.is_file():
        shutil.copy2(meta, folder / meta.name)
    return Path(shutil.copy2(source, folder / source.name))


def _load(path: Path) -> "jte.LoadedFile":
    # keep_damaged=False: a damaged sidecar beside a real file must never be moved aside.
    return jte.load_translation_file(path, keep_damaged=False)


def _save(path: Path, loaded: "jte.LoadedFile", entries: List["jte.StringEntry"]) -> None:
    jte.save_translation_file(path, entries, loaded.style, loaded.header)


def _json_keys(path: Path) -> List[str]:
    return [k for k, _v in json.loads(path.read_bytes().decode("utf-8-sig"), object_pairs_hook=list)]


def _lines(path: Path) -> List[str]:
    return path.read_bytes().decode("utf-8-sig").splitlines(keepends=True)


def _print_notes() -> None:
    if not FILES:
        print(f"NOTE no real-world files in {REAL.relative_to(cs.REPO)} — skipped", flush=True)
    for source in FILES:
        path = _copy(source)
        start = time.monotonic()
        try:
            loaded = _load(path)
        except jte.JsonFormatError as e:
            print(f"NOTE {source.name}: refused — {e}", flush=True)
            continue
        load_s = time.monotonic() - start
        start = time.monotonic()
        _save(path, loaded, loaded.entries)
        save_s = time.monotonic() - start
        print(f"NOTE {source.name}: {len(loaded.entries)} strings, load {load_s:.2f} s, "
              f"save {save_s:.2f} s", flush=True)
        if not loaded.round_trips:
            print(f"NOTE {source.name}: does not round-trip; save would reformat", flush=True)


class CorpusTests(unittest.TestCase):
    """Each test runs once per file, as a subTest named after it."""

    def test_app_and_json_module_find_the_same_keys(self):
        for source in FILES:
            with self.subTest(file=source.name):
                self.assertEqual([e.name for e in _load(source).entries], _json_keys(source))

    def test_unchanged_save_is_byte_identical(self):
        for source in FILES:
            with self.subTest(file=source.name):
                path = _copy(source)
                loaded = _load(path)
                if not loaded.round_trips:
                    self.skipTest("does not round-trip in its own style (noted)")
                _save(path, loaded, loaded.entries)
                self.assertEqual(path.read_bytes(), source.read_bytes())

    def test_editing_one_entry_changes_only_its_line(self):
        for source in FILES:
            with self.subTest(file=source.name):
                path = _copy(source)
                loaded = _load(path)
                if loaded.style.indent is None or not loaded.entries:
                    self.skipTest("compact file or no entries: no line per entry")
                # Measured against an unchanged save, so a file that does not round-trip counts
                # only the edit, not its one-time reformat.
                _save(path, loaded, loaded.entries)
                before = _lines(path)
                middle = len(loaded.entries) // 2
                loaded.entries[middle].text += " (edited)"
                _save(path, loaded, loaded.entries)
                after = _lines(path)
                changed = [i for i, (old, new) in enumerate(zip(before, after)) if old != new]
                self.assertEqual((len(after), changed), (len(before), [middle + 1]))

    def _delete_middle_entry(self, source: Path) -> Tuple[Path, str]:
        """Delete the middle entry of a copy of *source* and save; returns (copy, deleted key)."""
        path = _copy(source)
        loaded = _load(path)
        if not loaded.entries:
            self.skipTest("no entries")
        entry = loaded.entries[len(loaded.entries) // 2]
        _save(path, loaded, [e for e in loaded.entries if e is not entry])
        return path, entry.name

    def test_deleting_an_entry_leaves_exactly_the_other_keys(self):
        for source in FILES:
            with self.subTest(file=source.name):
                path, deleted = self._delete_middle_entry(source)
                expected = _json_keys(source)
                expected.remove(deleted)
                cs.assert_json_intact(self, path, expected)

    def test_merging_the_file_into_itself_changes_nothing(self):
        for source in FILES:
            with self.subTest(file=source.name):
                path = _copy(source)
                loaded = _load(path)
                unchanged = jte.dump_json(loaded.entries, loaded.style)
                diff = jte.compute_merge_diff(loaded.entries, _load(source).entries)
                _save(path, loaded, loaded.entries + diff.additions)
                self.assertEqual(path.read_bytes(), unchanged)


if __name__ == "__main__":
    _print_notes()
    sys.exit(cs.run_suite(sys.modules[__name__]))
