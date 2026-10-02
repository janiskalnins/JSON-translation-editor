"""Core tests: Merge from File. The pure diff (compute_merge_diff, _pick_newer_entry,
insert_additions), then whole-file merges: open and incoming files, every combination of choices
applied through MainWindow._apply_merge_diff(), saved, and judged by the oracle. No choice may
lose a row or create a duplicate.

Run:  python tests/check_core_merge.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import itertools
import sys
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path

xte = cs.xte

OLD = xte.format_date_for_storage(date(2024, 1, 1))
NEW = xte.format_date_for_storage(date(2025, 6, 1))


def _entry(name: str, text: str, modify_date: str = cs.DEFAULT_DATE, **fields):
    return cs.make_entry(name=name, text=text, modify_date=modify_date, **fields)


class DiffTests(unittest.TestCase):
    def test_name_only_in_incoming_is_an_addition(self):
        diff = xte.compute_merge_diff([_entry("A", "a")], [_entry("A", "a"), _entry("B", "b")])
        self.assertEqual([e.name for e in diff.additions], ["B"])

    def test_different_text_is_a_conflict(self):
        diff = xte.compute_merge_diff([_entry("A", "a")], [_entry("A", "b")])
        self.assertEqual([(o.text, i.text) for o, i in diff.conflicts], [("a", "b")])

    def test_name_only_in_open_is_a_deletion(self):
        diff = xte.compute_merge_diff([_entry("A", "a"), _entry("B", "b")], [_entry("A", "a")])
        self.assertEqual([e.name for e in diff.deletions], ["B"])

    def test_metadata_difference_with_newer_incoming_is_auto_updated(self):
        diff = xte.compute_merge_diff([_entry("A", "a", OLD, translator="x")],
                                      [_entry("A", "a", NEW, translator="y")])
        self.assertEqual([e.translator for e in diff.auto_updated], ["y"])

    def test_metadata_difference_with_newer_open_is_not_recorded(self):
        diff = xte.compute_merge_diff([_entry("A", "a", NEW, translator="x")],
                                      [_entry("A", "a", OLD, translator="y")])
        self.assertEqual(diff.auto_updated, [])

    def test_metadata_difference_with_equal_dates_is_not_recorded(self):
        diff = xte.compute_merge_diff([_entry("A", "a", NEW, translator="x")],
                                      [_entry("A", "a", NEW, translator="y")])
        self.assertEqual(diff.auto_updated, [])

    def test_metadata_difference_with_a_missing_date_is_not_recorded(self):
        diff = xte.compute_merge_diff([_entry("A", "a", NEW, translator="x")],
                                      [_entry("A", "a", "", translator="y")])
        self.assertEqual(diff.auto_updated, [])

    def test_identical_files_give_an_empty_diff(self):
        diff = xte.compute_merge_diff([_entry("A", "a")], [_entry("A", "a")])
        self.assertEqual(diff, xte.MergeDiff([], [], [], []))

    def test_duplicate_in_the_incoming_file_raises(self):
        with self.assertRaises(ValueError):
            xte.compute_merge_diff([_entry("A", "a")], [_entry("A", "a"), _entry("A", "b")])


class PickNewerTests(unittest.TestCase):
    def test_untranslated_open_loses_to_an_older_translated_incoming(self):
        incoming = _entry("A", "a", OLD)
        self.assertIs(xte._pick_newer_entry(_entry("A", "A", NEW), incoming), incoming)

    def test_untranslated_incoming_loses_to_an_older_translated_open(self):
        self.assertIsNone(xte._pick_newer_entry(_entry("A", "a", OLD), _entry("A", "A", NEW)))

    def test_newer_incoming_wins(self):
        incoming = _entry("A", "b", NEW)
        self.assertIs(xte._pick_newer_entry(_entry("A", "a", OLD), incoming), incoming)

    def test_unparseable_date_keeps_the_open_side(self):
        self.assertIsNone(xte._pick_newer_entry(_entry("A", "a", "later"), _entry("A", "b", NEW)))


OPEN_ROWS = [cs.row("Save", "Saglabāt"), cs.row("Cancel", "Atcelt", modify_date=OLD),
             cs.row("Old", "Vecs")]
INCOMING_ROWS = [cs.row("Save", "Saglabāt"), cs.row("Cancel", "Atsaukt", modify_date=NEW),
                 cs.row("New", "Jauns")]


class InsertAdditionsTests(unittest.TestCase):
    def setUp(self):
        self.path = cs.write_exact(cs.temp_dir() / "open.xml", cs.xml_doc(OPEN_ROWS))
        self.segments, self.entries, *_ = xte.parse_file(self.path)
        self.additions = [_entry("New", "Jauns"), _entry("Newer", "Jaunāks")]

    def test_additions_land_before_the_closing_resources_tag(self):
        segments, _ = xte.insert_additions(self.segments, self.entries, self.additions)
        text = "".join(segments)
        self.assertLess(text.index('name="Newer"'), text.index("</resources>"))

    def test_added_rows_have_odd_seg_idx(self):
        _, entries = xte.insert_additions(self.segments, self.entries, self.additions)
        self.assertEqual([e.seg_idx % 2 for e in entries], [1] * 5)

    def test_added_entries_point_at_their_own_rows(self):
        segments, entries = xte.insert_additions(self.segments, self.entries, self.additions)
        self.assertEqual([xte._get_attr(segments[e.seg_idx], "name") for e in entries],
                         ["Save", "Cancel", "Old", "New", "Newer"])

    def test_input_lists_are_not_mutated(self):
        before = (list(self.segments), list(self.entries))
        xte.insert_additions(self.segments, self.entries, self.additions)
        self.assertEqual((self.segments, self.entries), before)

    def test_missing_closing_resources_tag_raises(self):
        self.segments[-1] = "\n</TRNExportImportModel>\n"
        with self.assertRaises(ValueError):
            xte.insert_additions(self.segments, self.entries, self.additions)

    def test_saved_file_with_additions_is_intact(self):
        segments, entries = xte.insert_additions(self.segments, self.entries, self.additions)
        xte.save_file(self.path, segments, entries)
        cs.assert_xml_intact(self, self.path, ["Save", "Cancel", "Old", "New", "Newer"])


class FileMergeTests(unittest.TestCase):
    """Whole-file merges through a real MainWindow's _apply_merge_diff()."""

    @classmethod
    def setUpClass(cls):
        cls._stack = ExitStack()
        cls.win, cls.modals = cls._stack.enter_context(cs.open_window())

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    def _merge(self, accept_addition: bool, keep_incoming: bool, delete: bool) -> Path:
        """Merge INCOMING_ROWS into OPEN_ROWS with the given choice for the addition ("New"), the
        conflict ("Cancel") and the deletion ("Old"), save, and return the saved path."""
        folder = cs.temp_dir()
        path = cs.write_exact(folder / "open.xml", cs.xml_doc(OPEN_ROWS))
        incoming = cs.write_exact(folder / "incoming.xml", cs.xml_doc(INCOMING_ROWS))
        self.win._load(path)
        _, incoming_entries, *_ = xte.parse_file(incoming)
        diff = xte.compute_merge_diff(self.win.entries, incoming_entries)
        additions = diff.additions if accept_addition else []
        resolutions = [inc if keep_incoming else op for op, inc in diff.conflicts]
        deletions = diff.deletions if delete else []
        self.win._apply_merge_diff(diff, additions, resolutions, deletions, 0, [])
        self.win._write(path)
        return path

    def test_every_choice_combination_saves_the_expected_rows(self):
        for accept, keep_incoming, delete in itertools.product((True, False), repeat=3):
            with self.subTest(accept=accept, keep_incoming=keep_incoming, delete=delete):
                path = self._merge(accept, keep_incoming, delete)
                expected = (["Save", "Cancel"] + ([] if delete else ["Old"])
                            + (["New"] if accept else []))
                cs.assert_xml_intact(self, path, expected)

    def test_keep_incoming_writes_the_incoming_text(self):
        path = self._merge(accept_addition=False, keep_incoming=True, delete=False)
        self.assertEqual(xte.parse_file(path)[1][1].text, "Atsaukt")

    def test_keep_open_keeps_the_open_text(self):
        path = self._merge(accept_addition=False, keep_incoming=False, delete=False)
        self.assertEqual(xte.parse_file(path)[1][1].text, "Atcelt")

    def test_merging_the_same_file_again_adds_nothing(self):
        path = self._merge(accept_addition=True, keep_incoming=False, delete=False)
        _, incoming_entries, *_ = xte.parse_file(path.parent / "incoming.xml")
        diff = xte.compute_merge_diff(self.win.entries, incoming_entries)
        self.win._apply_merge_diff(diff, diff.additions, [op for op, _ in diff.conflicts], [], 0, [])
        self.win._write(path)
        cs.assert_xml_intact(self, path, ["Save", "Cancel", "Old", "New"])

    def test_merging_a_file_into_itself_changes_nothing(self):
        text = cs.xml_doc(OPEN_ROWS)
        path = cs.write_exact(cs.temp_dir() / "open.xml", text)
        self.win._load(path)
        _, same_entries, *_ = xte.parse_file(path)
        diff = xte.compute_merge_diff(self.win.entries, same_entries)
        self.win._apply_merge_diff(diff, diff.additions, [op for op, _ in diff.conflicts],
                                   diff.deletions, 0, [])
        self.win._write(path)
        self.assertEqual(path.read_bytes(), text.encode("utf-8"))

    def test_merge_deletion_leaves_no_blank_line(self):
        path = self._merge(accept_addition=False, keep_incoming=False, delete=True)
        self.assertEqual(path.read_bytes(), cs.xml_doc(OPEN_ROWS[:2]).encode("utf-8"))


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))
