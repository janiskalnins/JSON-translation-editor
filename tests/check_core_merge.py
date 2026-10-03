"""Core tests: Merge (Import's merge path). The pure diff (compute_merge_diff, _pick_newer_entry), then
whole-file merges: open and incoming language files with sidecars, every combination of choices
applied through MainWindow._apply_merge_diff(), saved, and judged by the oracle. No choice may
lose an entry or create a duplicate.

Run:  python tests/check_core_merge.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import itertools
import json
import sys
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QDialog

jte = cs.jte

OLD = jte.format_date_for_storage(date(2024, 1, 1))
NEW = jte.format_date_for_storage(date(2025, 6, 1))


def _entry(name: str, text: str, modify_date: str = cs.DEFAULT_DATE, **fields):
    return cs.make_entry(name=name, text=text, modify_date=modify_date, **fields)


class DiffTests(unittest.TestCase):
    def test_name_only_in_incoming_is_an_addition(self):
        diff = jte.compute_merge_diff([_entry("A", "a")], [_entry("A", "a"), _entry("B", "b")])
        self.assertEqual([e.name for e in diff.additions], ["B"])

    def test_different_text_is_a_conflict(self):
        diff = jte.compute_merge_diff([_entry("A", "a")], [_entry("A", "b")])
        self.assertEqual([(o.text, i.text) for o, i in diff.conflicts], [("a", "b")])

    def test_name_only_in_open_is_a_deletion(self):
        diff = jte.compute_merge_diff([_entry("A", "a"), _entry("B", "b")], [_entry("A", "a")])
        self.assertEqual([e.name for e in diff.deletions], ["B"])

    def test_metadata_difference_with_newer_incoming_is_auto_updated(self):
        diff = jte.compute_merge_diff([_entry("A", "a", OLD, translator="x")],
                                      [_entry("A", "a", NEW, translator="y")])
        self.assertEqual([e.translator for e in diff.auto_updated], ["y"])

    def test_metadata_difference_with_newer_open_is_not_recorded(self):
        diff = jte.compute_merge_diff([_entry("A", "a", NEW, translator="x")],
                                      [_entry("A", "a", OLD, translator="y")])
        self.assertEqual(diff.auto_updated, [])

    def test_metadata_difference_with_equal_dates_is_not_recorded(self):
        diff = jte.compute_merge_diff([_entry("A", "a", NEW, translator="x")],
                                      [_entry("A", "a", NEW, translator="y")])
        self.assertEqual(diff.auto_updated, [])

    def test_metadata_difference_with_a_missing_date_is_not_recorded(self):
        diff = jte.compute_merge_diff([_entry("A", "a", NEW, translator="x")],
                                      [_entry("A", "a", "", translator="y")])
        self.assertEqual(diff.auto_updated, [])

    def test_identical_files_give_an_empty_diff(self):
        diff = jte.compute_merge_diff([_entry("A", "a")], [_entry("A", "a")])
        self.assertEqual(diff, jte.MergeDiff([], [], [], []))

    def test_duplicate_in_the_incoming_file_raises(self):
        with self.assertRaises(ValueError):
            jte.compute_merge_diff([_entry("A", "a")], [_entry("A", "a"), _entry("A", "b")])


class PickNewerTests(unittest.TestCase):
    def test_untranslated_open_loses_to_an_older_translated_incoming(self):
        incoming = _entry("A", "a", OLD)
        self.assertIs(jte._pick_newer_entry(_entry("A", "A", NEW), incoming), incoming)

    def test_untranslated_incoming_loses_to_an_older_translated_open(self):
        self.assertIsNone(jte._pick_newer_entry(_entry("A", "a", OLD), _entry("A", "A", NEW)))

    def test_newer_incoming_wins(self):
        incoming = _entry("A", "b", NEW)
        self.assertIs(jte._pick_newer_entry(_entry("A", "a", OLD), incoming), incoming)

    def test_unparseable_date_keeps_the_open_side(self):
        self.assertIsNone(jte._pick_newer_entry(_entry("A", "a", "later"), _entry("A", "b", NEW)))


OLD_ISO, NEW_ISO, DEFAULT_ISO = "2024-01-01", "2025-06-01", "2025-02-01"
OPEN_PAIRS = {"Save": "Guardar", "Cancel": "Cancelar", "Old": "Viejo"}
OPEN_META = {"Save": ("Complete", "Jane", DEFAULT_ISO), "Cancel": ("Complete", "Jane", OLD_ISO),
             "Old": ("Complete", "Jane", DEFAULT_ISO)}
INCOMING_PAIRS = {"Save": "Guardar", "Cancel": "Anular", "New": "Nuevo"}
INCOMING_META = {"Save": ("Complete", "Jane", DEFAULT_ISO), "Cancel": ("Complete", "Jane", NEW_ISO),
                 "New": ("Complete", "Jane", DEFAULT_ISO)}


class FileMergeTests(unittest.TestCase):
    """Whole-file merges through a real MainWindow's _apply_merge_diff()."""

    @classmethod
    def setUpClass(cls):
        cls._stack = ExitStack()
        cls.win, cls.modals = cls._stack.enter_context(cs.open_window())

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    def _open_pair(self):
        """A fresh open file and incoming file in a folder of their own; the open one loaded."""
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", OPEN_PAIRS, meta=OPEN_META)
        incoming = cs.write_pair(folder, "incoming", INCOMING_PAIRS, meta=INCOMING_META)
        self.win._load(path)
        return path, jte.load_translation_file(incoming).entries

    def _merge(self, accept_addition: bool, keep_incoming: bool, delete: bool) -> Path:
        """Merge INCOMING_PAIRS into OPEN_PAIRS with the given choice for the addition ("New"), the
        conflict ("Cancel") and the deletion ("Old"), save, and return the saved path."""
        path, incoming_entries = self._open_pair()
        diff = jte.compute_merge_diff(self.win.entries, incoming_entries)
        additions = diff.additions if accept_addition else []
        resolutions = [inc if keep_incoming else op for op, inc in diff.conflicts]
        deletions = diff.deletions if delete else []
        self.win._apply_merge_diff(diff, additions, resolutions, deletions)
        self.win._write(path)
        return path

    def _add(self, names):
        """Apply additions named *names* to a freshly loaded open file; returns (path, additions)."""
        path, _incoming = self._open_pair()
        additions = [_entry(name, name.lower(), position=9) for name in names]
        diff = jte.MergeDiff(additions=additions, conflicts=[], deletions=[], auto_updated=[])
        self.win._apply_merge_diff(diff, additions, [], [])
        return path, additions

    def test_additions_are_appended(self):
        self._add(["New", "Newer"])
        self.assertEqual([e.name for e in self.win.entries][-2:], ["New", "Newer"])

    def test_added_entries_take_the_next_positions(self):
        self._add(["New", "Newer"])
        self.assertEqual([e.position for e in self.win.entries], [1, 2, 3, 4, 5])

    def test_incoming_entries_are_not_changed(self):
        _path, additions = self._add(["New", "Newer"])
        self.assertEqual([e.position for e in additions], [9, 9])

    def test_saved_file_with_additions_is_intact(self):
        path, _additions = self._add(["New", "Newer"])
        self.win._write(path)
        cs.assert_json_intact(self, path, ["Save", "Cancel", "Old", "New", "Newer"])

    def test_every_choice_combination_saves_the_expected_entries(self):
        for accept, keep_incoming, delete in itertools.product((True, False), repeat=3):
            with self.subTest(accept=accept, keep_incoming=keep_incoming, delete=delete):
                path = self._merge(accept, keep_incoming, delete)
                expected = (["Save", "Cancel"] + ([] if delete else ["Old"])
                            + (["New"] if accept else []))
                cs.assert_json_intact(self, path, expected)

    def test_keep_incoming_writes_the_incoming_text(self):
        path = self._merge(accept_addition=False, keep_incoming=True, delete=False)
        self.assertEqual(jte.load_translation_file(path).entries[1].text, "Anular")

    def test_keep_incoming_writes_the_incoming_date_to_the_sidecar(self):
        path = self._merge(accept_addition=False, keep_incoming=True, delete=False)
        meta = json.loads(jte.meta_path_for(path).read_bytes())
        self.assertEqual(meta["entries"]["Cancel"]["modified"], NEW_ISO)

    def test_keep_open_keeps_the_open_text(self):
        path = self._merge(accept_addition=False, keep_incoming=False, delete=False)
        self.assertEqual(jte.load_translation_file(path).entries[1].text, "Cancelar")

    def test_merging_the_same_file_again_adds_nothing(self):
        path = self._merge(accept_addition=True, keep_incoming=False, delete=False)
        incoming_entries = jte.load_translation_file(path.parent / "incoming.json").entries
        diff = jte.compute_merge_diff(self.win.entries, incoming_entries)
        self.win._apply_merge_diff(diff, diff.additions, [op for op, _ in diff.conflicts], [])
        self.win._write(path)
        cs.assert_json_intact(self, path, ["Save", "Cancel", "Old", "New"])

    def test_merging_a_file_into_itself_changes_nothing(self):
        path = cs.write_pair(cs.temp_dir(), "es", OPEN_PAIRS, meta=OPEN_META)
        before = (path.read_bytes(), jte.meta_path_for(path).read_bytes())
        self.win._load(path)
        same_entries = jte.load_translation_file(path).entries
        diff = jte.compute_merge_diff(self.win.entries, same_entries)
        self.win._apply_merge_diff(diff, diff.additions, [op for op, _ in diff.conflicts],
                                   diff.deletions)
        self.win._write(path)
        self.assertEqual((path.read_bytes(), jte.meta_path_for(path).read_bytes()), before)

    def test_merge_deletion_drops_only_that_entry(self):
        path = self._merge(accept_addition=False, keep_incoming=False, delete=True)
        self.assertEqual(path.read_bytes(), cs.json_doc({"Save": "Guardar", "Cancel": "Cancelar"}))


def _entries(*names):
    return [cs.bare_entry(n, text=f"{n}!") for n in names]


class SyncDiffTests(unittest.TestCase):
    def test_additions_are_the_reference_keys_this_file_lacks(self):
        diff = jte.compute_sync_diff(_entries("a", "c"), _entries("a", "b", "c", "d"))
        self.assertEqual([e.name for e in diff.additions], ["b", "d"])

    def test_additions_are_untranslated_and_new(self):
        diff = jte.compute_sync_diff(_entries("a"), _entries("a", "b"))
        self.assertEqual((diff.additions[0].text, diff.additions[0].status), ("b", "New"))

    def test_deletions_are_the_keys_the_reference_lacks(self):
        diff = jte.compute_sync_diff(_entries("a", "x", "c"), _entries("a", "c"))
        self.assertEqual([e.name for e in diff.deletions], ["x"])

    def test_values_are_never_compared(self):
        diff = jte.compute_sync_diff([cs.bare_entry("a", "uno")], [cs.bare_entry("a", "one")])
        self.assertEqual((diff.additions, diff.deletions), ([], []))


class InsertSyncedTests(unittest.TestCase):
    def test_insertion_positions(self):
        cases = {
            "between": (("a", "c"), ("a", "b", "c"), ["a", "b", "c"]),
            "at the start": (("b",), ("a", "b"), ["a", "b"]),
            "at the end": (("a",), ("a", "b"), ["a", "b"]),
            "two in a row": (("a", "d"), ("a", "b", "c", "d"), ["a", "b", "c", "d"]),
            "after a key the reference moved": (("c", "a"), ("a", "b", "c"), ["c", "a", "b"]),
        }
        for label, (open_names, ref_names, expected) in cases.items():
            with self.subTest(label):
                open_entries, reference = _entries(*open_names), _entries(*ref_names)
                additions = jte.compute_sync_diff(open_entries, reference).additions
                result = jte.insert_synced(open_entries, reference, additions)
                self.assertEqual([e.name for e in result], expected)

    def test_positions_are_renumbered(self):
        open_entries, reference = _entries("a", "c"), _entries("a", "b", "c")
        additions = jte.compute_sync_diff(open_entries, reference).additions
        self.assertEqual([e.position for e in jte.insert_synced(open_entries, reference, additions)],
                         [1, 2, 3])


class SyncWindowTests(unittest.TestCase):
    def _sync(self, open_pairs, ref_pairs):
        """Sync id.json from es.json, accepting the dialog's defaults, then save. Returns the path
        and how many times the review dialog was opened."""
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "id", open_pairs)
        ref = cs.write_pair(folder, "es", ref_pairs)
        opened = []

        def fake_exec(dlg):
            opened.append(dlg.windowTitle())
            dlg.done(QDialog.Accepted)   # stores the default choices, as a real Apply & Close does
            return QDialog.Accepted

        with cs.open_window(path, open_path=str(ref)) as (win, _modals):
            with mock.patch.object(jte.MergeConflictDialog, "exec", fake_exec):
                win._sync_keys_from_file()
            win._save()
        return path, opened

    def test_synced_file_gains_the_missing_key_untranslated(self):
        path, _o = self._sync({"a": "satu", "c": "tiga"}, {"a": "uno", "b": "dos", "c": "tres"})
        self.assertEqual(json.loads(path.read_bytes()), {"a": "satu", "b": "b", "c": "tiga"})

    def test_synced_file_is_intact(self):
        path, _o = self._sync({"a": "satu", "c": "tiga"}, {"a": "uno", "b": "dos", "c": "tres"})
        cs.assert_json_intact(self, path, ["a", "b", "c"])

    def test_extra_keys_are_kept_by_default(self):
        path, _o = self._sync({"a": "satu", "x": "lama"}, {"a": "uno"})
        self.assertIn("x", json.loads(path.read_bytes()))

    def test_review_dialog_is_titled_sync_keys(self):
        _path, opened = self._sync({"a": "satu"}, {"a": "uno", "b": "dos"})
        self.assertEqual(opened, ["Sync Keys"])

    def test_matching_keys_open_no_dialog(self):
        _path, opened = self._sync({"a": "satu"}, {"a": "uno"})
        self.assertEqual(opened, [])


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))
