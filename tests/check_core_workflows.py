"""Core tests: end-to-end workflows through a real, offscreen MainWindow. Editing through the Edit
dialog, legacy dates, bulk status, delete, Close File, Save As, Merge from File, Restore from
Backup and autosave, each ending in a saved file judged by the oracle. Every modal is answered by
core_support.patched_modals().

Run:  python tests/check_core_workflows.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import hashlib
import json
import sys
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple
from unittest import mock

from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

jte = cs.jte

ROWS = [cs.row("Save", "Saglabāt"), cs.row("Cancel", "Atcelt"), cs.row("Open", "Atvērt")]
NAMES = ["Save", "Cancel", "Open"]
TODAY = jte.format_date_for_storage(date.today())
OLD = jte.format_date_for_storage(date(2024, 1, 1))
NEW = jte.format_date_for_storage(date(2025, 6, 1))


class WindowTestCase(unittest.TestCase):
    """One real MainWindow per test class; each test loads its own copy of a file."""
    backup = False

    @classmethod
    def setUpClass(cls):
        cls._stack = ExitStack()
        cls.win, cls.modals = cls._stack.enter_context(cs.open_window(backup=cls.backup))

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    def setUp(self):
        self.modals.answers.clear()
        self.modals.shown.clear()
        self.win.session_translator = ""

    def load(self, rows: List[str] = ROWS, name: str = "Latvian.xml") -> Path:
        path = cs.write_exact(cs.temp_dir() / name, cs.xml_doc(rows))
        self.win.is_modified = False
        self.win._load(path)
        cs.pump()
        return path


def _edit(win, row: int, **fields) -> None:
    """Open the Edit dialog on visible *row* with exec() replaced: set the given fields (text,
    status, translator), then press Save."""
    def fake_exec(dlg):
        if "text" in fields:
            dlg.trans_edit.setPlainText(fields["text"])
        if "status" in fields:
            dlg.status_combo.setCurrentText(fields["status"])
        if "translator" in fields:
            dlg.user_edit.setText(fields["translator"])
        dlg._save()
        return QDialog.Accepted
    with mock.patch.object(jte.EditDialog, "exec", fake_exec):
        win._edit_row(win.model.index(row, 0))


def _select_rows(win, rows: List[int]) -> None:
    selection = QItemSelection()
    for r in rows:
        selection.select(win.model.index(r, 0), win.model.index(r, len(jte.HEADERS) - 1))
    win.table.selectionModel().select(
        selection, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)


class EditTests(WindowTestCase):
    def test_translation_edit_survives_save_and_reopen(self):
        path = self.load()
        self.win.session_translator = "Anna"
        _edit(self.win, 1, text="Atsaukt")
        self.win._save()
        expected = jte.StringEntry("Cancel", "Anna", "Complete", TODAY, "false", "Atsaukt", seg_idx=3)
        self.assertEqual(jte.parse_file(path)[1][1], expected)

    def test_translation_edit_saves_an_intact_file(self):
        path = self.load()
        _edit(self.win, 1, text="Atsaukt")
        self.win._save()
        cs.assert_xml_intact(self, path, NAMES)

    def test_metadata_edit_survives_save_and_reopen(self):
        path = self.load()
        _edit(self.win, 0, status="Review", translator="Bob")
        self.win._save()
        expected = jte.StringEntry("Save", "Bob", "Review", cs.DEFAULT_DATE, "false", "Saglabāt",
                                   seg_idx=1)
        self.assertEqual(jte.parse_file(path)[1][0], expected)

    def test_file_with_legacy_dates_opens_modified(self):
        self.load([cs.row(n, t, modify_date="2016-05-06") for n, t in (("A", "a"), ("B", "b"))])
        self.assertTrue(self.win.is_modified)

    def test_save_writes_canonical_dates(self):
        path = self.load([cs.row(n, t, modify_date="2016-05-06") for n, t in (("A", "a"), ("B", "b"))])
        self.win._save()
        canonical = jte.format_date_for_storage(date(2016, 5, 6))
        self.assertEqual([e.modify_date for e in jte.parse_file(path)[1]], [canonical, canonical])

    def test_save_with_canonical_dates_saves_an_intact_file(self):
        path = self.load([cs.row(n, t, modify_date="2016-05-06") for n, t in (("A", "a"), ("B", "b"))])
        self.win._save()
        cs.assert_xml_intact(self, path, ["A", "B"])


class EditShortcutTests(WindowTestCase):
    """The read-only Source Text box takes Alt+Left/Alt+Right as its own cursor keys, and the
    dialog opens with focus in it, so Previous/Next did nothing until the translation box was
    clicked. Real key events, since the bug is in which widget gets them."""

    def row_after_key_in_source_box(self, key) -> int:
        self.load()
        dlg = jte.EditDialog(self.win.model, 1, self.win.settings.get_font(),
                             shortcuts=self.win.settings.get("shortcuts", {}),
                             target_culture=self.win.target_culture,
                             transl_cfg=self.win.settings.get("translation", {}), parent=self.win)
        dlg.show()
        dlg.src_view.setFocus()
        cs.pump()
        QTest.keyClick(dlg.src_view, key, Qt.AltModifier)
        cs.pump()
        row = dlg._row
        dlg.close()
        cs.pump()
        return row

    def test_navigation_keys_work_from_the_source_box(self):
        for key, expected in ((Qt.Key_Right, 2), (Qt.Key_Left, 0)):
            with self.subTest(key=key):
                self.assertEqual(self.row_after_key_in_source_box(key), expected)


class BulkStatusTests(WindowTestCase):
    def test_bulk_status_changes_only_the_selected_rows(self):
        path = self.load()
        _select_rows(self.win, [0, 2])
        self.win._bulk_status("Review")
        self.win._save()
        self.assertEqual([e.status for e in jte.parse_file(path)[1]],
                         ["Review", "Complete", "Review"])

    def test_bulk_status_saves_an_intact_file(self):
        path = self.load()
        _select_rows(self.win, [0, 2])
        self.win._bulk_status("Review")
        self.win._save()
        cs.assert_xml_intact(self, path, NAMES)


class DeleteTests(WindowTestCase):
    def test_deleting_one_row_saves_an_intact_file_without_it(self):
        path = self.load()
        self.modals.answers["question"] = QMessageBox.Yes
        self.win._delete_entries([self.win.entries[1]])
        self.win._save()
        cs.assert_xml_intact(self, path, ["Save", "Open"])

    def test_deleting_several_rows_saves_an_intact_file_without_them(self):
        path = self.load()
        self.modals.answers["question"] = QMessageBox.Yes
        self.win._delete_entries([self.win.entries[0], self.win.entries[2]])
        self.win._save()
        cs.assert_xml_intact(self, path, ["Cancel"])

    def test_declining_the_confirmation_deletes_nothing(self):
        self.load()
        self.modals.answers["question"] = QMessageBox.No
        self.win._delete_entries([self.win.entries[1]])
        self.assertEqual([e.name for e in self.win.entries], NAMES)

    def test_deleting_a_row_leaves_no_blank_line(self):
        path = self.load()
        self.modals.answers["question"] = QMessageBox.Yes
        self.win._delete_entries([self.win.entries[1]])
        self.win._save()
        self.assertEqual(path.read_bytes(), cs.xml_doc([ROWS[0], ROWS[2]]).encode("utf-8"))


class CloseFileTests(WindowTestCase):
    def _load_modified(self) -> Tuple[Path, bytes]:
        path = self.load()
        original = path.read_bytes()
        self.win.entries[0].text = "Changed"
        self.win.is_modified = True
        return path, original

    def test_close_with_save_writes_the_change(self):
        path, _ = self._load_modified()
        self.modals.answers["question"] = QMessageBox.Save
        self.win._close_file()
        self.assertEqual(jte.parse_file(path)[1][0].text, "Changed")

    def test_close_with_save_saves_an_intact_file(self):
        path, _ = self._load_modified()
        self.modals.answers["question"] = QMessageBox.Save
        self.win._close_file()
        cs.assert_xml_intact(self, path, NAMES)

    def test_close_with_save_closes_the_file(self):
        self._load_modified()
        self.modals.answers["question"] = QMessageBox.Save
        self.win._close_file()
        self.assertIsNone(self.win.current_file)

    def test_close_with_discard_leaves_the_file_unchanged(self):
        path, original = self._load_modified()
        self.modals.answers["question"] = QMessageBox.Discard
        self.win._close_file()
        self.assertEqual(path.read_bytes(), original)

    def test_close_with_cancel_keeps_the_file_open(self):
        path, _ = self._load_modified()
        self.modals.answers["question"] = QMessageBox.Cancel
        self.win._close_file()
        self.assertEqual(self.win.current_file, path)

    def test_failed_save_keeps_the_file_open(self):
        path, _ = self._load_modified()
        self.modals.answers["question"] = QMessageBox.Save
        with mock.patch.object(jte, "save_file", side_effect=OSError("locked")):
            self.win._close_file()
        self.assertEqual(self.win.current_file, path)


class SaveAsTests(WindowTestCase):
    def test_save_as_rederives_the_glossary(self):
        path = self.load()
        copy = path.parent / "Copy.xml"
        jte.write_glossary(jte.glossary_path_for(copy), [jte.GlossaryEntry("Lane", "Celiņš")])
        self.modals.answers["save_path"] = str(copy)
        self.win._save_as()
        self.assertEqual([g.term for g in self.win.glossary], ["Lane"])

    def test_save_as_writes_an_intact_file(self):
        path = self.load()
        copy = path.parent / "Copy.xml"
        self.modals.answers["save_path"] = str(copy)
        self.win._save_as()
        cs.assert_xml_intact(self, copy, NAMES)


def _accept_merge_defaults(dlg) -> int:
    """MergeConflictDialog.exec() replaced: accept every row's preselected choice."""
    dlg.done(QDialog.Accepted)
    return QDialog.Accepted


class MergeWorkflowTests(WindowTestCase):
    OPEN_ROWS = [cs.row("Save", "Saglabāt"), cs.row("Cancel", "Atcelt", modify_date=OLD),
                 cs.row("Old", "Vecs")]
    INCOMING_ROWS = [cs.row("Save", "Saglabāt"), cs.row("Cancel", "Atsaukt", modify_date=NEW),
                     cs.row("New", "Jauns")]

    def _merge_defaults(self) -> Path:
        path = self.load(self.OPEN_ROWS)
        incoming = cs.write_exact(path.parent / "incoming.xml", cs.xml_doc(self.INCOMING_ROWS))
        self.modals.answers["open_path"] = str(incoming)
        with mock.patch.object(jte.MergeConflictDialog, "exec", _accept_merge_defaults):
            self.win._merge_from_file()
        self.win._save()
        return path

    def test_full_merge_saves_an_intact_file(self):
        path = self._merge_defaults()
        cs.assert_xml_intact(self, path, ["Save", "Cancel", "Old", "New"])

    def test_full_merge_takes_the_newer_conflicting_text(self):
        path = self._merge_defaults()
        self.assertEqual(jte.parse_file(path)[1][1].text, "Atsaukt")


def _backup_manifests(folder: Path) -> List[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in (folder / jte.BACKUP_DIR_NAME).rglob("backup_info.json")]


class RestoreTests(WindowTestCase):
    backup = True
    OLD_TEXT = cs.xml_doc([cs.row("Old", "Vecs")]).encode("utf-8")
    GLOSSARY = "term,translation,note\r\nLane,Celiņš,\r\n".encode("utf-8-sig")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.win.settings.data["backup"].update(location_mode="next_to_file", min_interval_minutes=0)

    def tearDown(self):
        cs.wait_until(lambda: not self.win._backup_threads)

    def _slot(self, source: Path, glossary: Optional[bytes] = None,
              md5: Optional[str] = None) -> Tuple[Path, dict]:
        """A backup slot of OLD_TEXT for *source*, in a backup root of its own."""
        slot = jte._write_backup_slot(
            root_dir=cs.temp_dir() / "bk", location_id="root", backup_key=source.stem,
            ts="2025-01-01_00-00-00", source_path=source, raw_bytes=self.OLD_TEXT,
            md5=md5 or hashlib.md5(self.OLD_TEXT).hexdigest(),
            glossary_source=jte.glossary_path_for(source) if glossary is not None else None,
            glossary_bytes=glossary,
            glossary_md5=hashlib.md5(glossary).hexdigest() if glossary is not None else None,
            compress=True, max_count=5, trigger="file_open", culture="lv-LV",
            display_language="Latviešu", version="4.1.1140", is_fallback=False)
        return slot, json.loads((slot / "backup_info.json").read_text(encoding="utf-8"))

    def _overwrite_restore(self) -> Tuple[Path, bytes]:
        path = self.load()
        original = path.read_bytes()
        slot, info = self._slot(path)
        self.modals.answers["button"] = "Overwrite original"
        self.win._do_restore(slot, info)
        cs.wait_until(lambda: path.read_bytes() == self.OLD_TEXT)
        cs.wait_until(lambda: not self.win._backup_threads)
        return path, original

    def test_overwrite_restore_writes_the_backup(self):
        path, _ = self._overwrite_restore()
        self.assertEqual(path.read_bytes(), self.OLD_TEXT)

    def test_overwrite_restore_reloads_the_open_file(self):
        self._overwrite_restore()
        self.assertEqual([e.name for e in self.win.entries], ["Old"])

    def test_overwrite_restore_backs_up_the_overwritten_file_first(self):
        path, original = self._overwrite_restore()
        safety = [m["md5_checksum"] for m in _backup_manifests(path.parent)
                  if m["trigger"] == "pre_restore_safety"]
        self.assertEqual(safety, [hashlib.md5(original).hexdigest()])

    def test_copy_restore_writes_a_restored_copy(self):
        path = self.load()
        slot, info = self._slot(path)
        self.modals.answers.update(button="Save as copy", question=QMessageBox.No)
        self.win._do_restore(slot, info)
        copies = sorted(path.parent.glob("Latvian_restored_*.xml"))
        self.assertEqual([c.read_bytes() for c in copies], [self.OLD_TEXT])

    def test_copy_restore_restores_the_glossary_with_it(self):
        path = self.load()
        slot, info = self._slot(path, glossary=self.GLOSSARY)
        self.modals.answers.update(button="Save as copy", question=QMessageBox.No)
        self.win._do_restore(slot, info, restore_glossary=True)
        copy = next(path.parent.glob("Latvian_restored_*.xml"))
        self.assertEqual(jte.glossary_path_for(copy).read_bytes(), self.GLOSSARY)

    def test_checksum_mismatch_warns(self):
        path = self.load()
        slot, info = self._slot(path, md5="0" * 32)
        self.modals.answers["warning"] = QMessageBox.No
        self.win._do_restore(slot, info)
        self.assertIn("Checksum Mismatch", self.modals.titles("warning"))


class AutosaveTests(WindowTestCase):
    def test_autosave_tick_skips_an_unmodified_file(self):
        path = self.load()
        self.win.entries[0].text = "Changed"
        self.win.is_modified = False
        self.win._autosave_tick()
        self.assertEqual(jte.parse_file(path)[1][0].text, "Saglabāt")

    def test_autosave_tick_saves_a_modified_file(self):
        path = self.load()
        self.win.entries[0].text = "Changed"
        self.win.is_modified = True
        self.win._autosave_tick()
        self.assertEqual(jte.parse_file(path)[1][0].text, "Changed")

    def test_autosave_tick_saves_an_intact_file(self):
        path = self.load()
        self.win.entries[0].text = "Changed"
        self.win.is_modified = True
        self.win._autosave_tick()
        cs.assert_xml_intact(self, path, NAMES)

    def test_autosave_tick_clears_the_modified_flag(self):
        self.load()
        self.win.entries[0].text = "Changed"
        self.win.is_modified = True
        self.win._autosave_tick()
        self.assertFalse(self.win.is_modified)


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))
