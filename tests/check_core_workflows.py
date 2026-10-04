"""Core tests: end-to-end workflows through a real, offscreen MainWindow. Editing through the Edit
dialog, bulk status, delete, Close File, Save (sidecar failures included), Save As, Export,
Import, Restore from Backup and autosave, each ending in a saved file judged by the oracle. Every
modal is answered by core_support.patched_modals().

Run:  python tests/check_core_workflows.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import hashlib
import json
import os
import sys
import unittest
import zipfile
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from unittest import mock

from PySide6.QtCore import QEventLoop, QItemSelection, QItemSelectionModel, QMimeData, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox, QStyle, QStyleOptionButton

jte = cs.jte

DEFAULT_ISO = "2025-02-01"   # cs.DEFAULT_DATE as the sidecar stores it
PAIRS = {"Save": "Guardar", "Cancel": "Cancelar", "Open": "Abrir"}
META = {name: ("Complete", "Jane", DEFAULT_ISO) for name in PAIRS}
NAMES = list(PAIRS)
TODAY = jte.format_date_for_storage(date.today())


def _reread(path: Path) -> List["jte.StringEntry"]:
    """The entries a fresh load of *path* (and its sidecar) gives."""
    return jte.load_translation_file(path).entries


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

    def load(self, pairs: Dict[str, str] = PAIRS,
             meta: Optional[Dict[str, Tuple[str, str, str]]] = META, name: str = "es") -> Path:
        path = cs.write_pair(cs.temp_dir(), name, pairs, meta=meta)
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
        _edit(self.win, 1, text="Anular")
        self.win._save()
        expected = jte.StringEntry(name="Cancel", translator="Anna", status="Complete",
                                   modify_date=TODAY, text="Anular", position=2)
        self.assertEqual(_reread(path)[1], expected)

    def test_translation_edit_saves_an_intact_file(self):
        path = self.load()
        _edit(self.win, 1, text="Anular")
        self.win._save()
        cs.assert_json_intact(self, path, NAMES)

    def test_metadata_edit_survives_save_and_reopen(self):
        path = self.load()
        _edit(self.win, 0, status="Review", translator="Bob")
        self.win._save()
        expected = jte.StringEntry(name="Save", translator="Bob", status="Review",
                                   modify_date=cs.DEFAULT_DATE, text="Guardar", position=1)
        self.assertEqual(_reread(path)[0], expected)

    def test_metadata_edit_saves_an_intact_file(self):
        path = self.load()
        _edit(self.win, 0, status="Review", translator="Bob")
        self.win._save()
        cs.assert_json_intact(self, path, NAMES)

    def test_file_with_a_sidecar_opens_unmodified(self):
        self.load()
        self.assertFalse(self.win.is_modified)


def _browse(win, row: int, change=None) -> None:
    """Open the Edit dialog on visible *row* with exec() replaced: apply *change(dlg)* if given,
    move to the next entry and press Save there without touching it."""
    def fake_exec(dlg):
        if change is not None:
            change(dlg)
        dlg._navigate(1)
        dlg._save()
        return QDialog.Accepted
    with mock.patch.object(jte.EditDialog, "exec", fake_exec):
        win._edit_row(win.model.index(row, 0))


class EditDateTests(WindowTestCase):
    """The date field cannot be blank, so an undated entry shows today: only a date the user
    picks may be stored, never the one the field merely shows."""

    def _load_undated(self, meta: Optional[Dict[str, Tuple[str, str, str]]] = None) -> Path:
        return self.load(meta=meta if meta is not None else {})

    def test_browsing_past_an_undated_entry_keeps_it_undated(self):
        self._load_undated()
        _browse(self.win, 0)
        self.assertEqual(self.win.entries[0].modify_date, "")

    def test_browsing_past_an_undated_entry_leaves_the_file_unmodified(self):
        self._load_undated()
        _browse(self.win, 0)
        self.assertFalse(self.win.is_modified)

    def test_browsing_past_an_unreadable_date_keeps_it(self):
        self._load_undated({"Save": ("Review", "Jo", "foo")})
        _browse(self.win, 0)
        self.assertEqual(self.win.entries[0].modify_date, "foo")

    def test_picked_date_on_an_undated_entry_is_stored(self):
        picked = jte.QDate.currentDate().addDays(-3)   # not today: the field already shows today
        self._load_undated()
        _browse(self.win, 0, lambda dlg: dlg.date_edit.setDate(picked))
        self.assertEqual(self.win.entries[0].modify_date, jte.format_date_for_storage(picked))

    def test_status_change_on_an_undated_entry_keeps_it_undated(self):
        self._load_undated()
        _browse(self.win, 0, lambda dlg: dlg.status_combo.setCurrentText("Review"))
        self.assertEqual((self.win.entries[0].status, self.win.entries[0].modify_date),
                         ("Review", ""))

    def test_text_change_on_an_undated_entry_stamps_today(self):
        self._load_undated()
        _browse(self.win, 0, lambda dlg: dlg.trans_edit.setPlainText("Guardar ya"))
        self.assertEqual(self.win.entries[0].modify_date, TODAY)


MIXED ={"Save": "Guardar", "Cancel": "Cancel", "Open": "Abrir"}   # Cancel untranslated
MARK_DATE = date(2026, 10, 4)


def _sidecar_entries(path: Path) -> dict:
    return json.loads(jte.meta_path_for(path).read_bytes())["entries"]


class InitialSidecarTests(WindowTestCase):
    """A translated file opened without a sidecar: the Mark Translated Strings question."""

    def _open_without_sidecar(self, pairs: Dict[str, str] = MIXED, **choice) -> Path:
        self.modals.answers["initial_meta"] = choice
        return self.load(pairs, meta=None)

    def _messages(self) -> List[Tuple[str, str]]:
        return [(n.text, n.level) for n in self.win._notice_history]

    def test_translated_file_without_a_sidecar_asks(self):
        self._open_without_sidecar()
        self.assertEqual(self.modals.titles("initial_meta"), ["Mark Translated Strings"])

    def test_apply_lists_only_the_translated_keys(self):
        path = self._open_without_sidecar(apply=True)
        bare = {"status": "Complete", "translator": "", "modified": ""}
        self.assertEqual(_sidecar_entries(path), {"Save": bare, "Open": bare})

    def test_apply_with_the_chosen_status(self):
        path = self._open_without_sidecar(apply=True, status="Review")
        self.assertEqual(_sidecar_entries(path)["Save"]["status"], "Review")

    def test_apply_with_translator_and_date(self):
        path = self._open_without_sidecar(apply=True, translator="Unknown",
                                          date=jte.QDate(2026, 10, 4))
        self.assertEqual(_sidecar_entries(path)["Save"],
                         {"status": "Complete", "translator": "Unknown", "modified": "2026-10-04"})

    def test_apply_translator_without_status_keeps_new(self):
        path = self._open_without_sidecar(apply=True, status=None, translator="Unknown")
        self.assertEqual(_sidecar_entries(path)["Save"],
                         {"status": "New", "translator": "Unknown", "modified": ""})

    def test_applied_statuses_show_in_the_window(self):
        self._open_without_sidecar(apply=True)
        self.assertEqual([e.status for e in self.win.entries], ["Complete", "New", "Complete"])

    def test_skip_writes_a_sidecar_with_no_entries(self):
        path = self._open_without_sidecar()
        self.assertEqual(_sidecar_entries(path), {})

    def test_apply_with_nothing_ticked_writes_a_sidecar_with_no_entries(self):
        path = self._open_without_sidecar(apply=True, status=None)
        self.assertEqual(_sidecar_entries(path), {})

    def test_language_file_is_not_touched(self):
        path = cs.write_pair(cs.temp_dir(), "es", MIXED)
        before = path.read_bytes()
        self.modals.answers["initial_meta"] = {"apply": True}
        self.win._load(path)
        self.assertEqual(path.read_bytes(), before)

    def test_file_opens_unmodified(self):
        self._open_without_sidecar(apply=True)
        self.assertFalse(self.win.is_modified)

    def test_reopening_does_not_ask_again(self):
        path = self._open_without_sidecar(apply=True)
        self.modals.shown.clear()
        self.win._load(path)
        self.assertEqual(self.modals.titles("initial_meta"), [])

    def test_no_question_for_an_untranslated_file(self):
        self._open_without_sidecar({"Save": "Save", "Open": "Open"})
        self.assertEqual(self.modals.titles("initial_meta"), [])

    def test_no_sidecar_for_an_untranslated_file(self):
        path = self._open_without_sidecar({"Save": "Save", "Open": "Open"})
        self.assertFalse(jte.meta_path_for(path).exists())

    def test_no_question_when_a_sidecar_exists(self):
        self.load(MIXED, meta={})
        self.assertEqual(self.modals.titles("initial_meta"), [])

    def test_no_question_when_the_sidecar_is_damaged(self):
        path = cs.write_pair(cs.temp_dir(), "es", MIXED)
        cs.write_exact(jte.meta_path_for(path), b"{")
        self.win._load(path)
        self.assertEqual(self.modals.titles("initial_meta"), [])

    def test_message_names_the_count_and_status(self):
        self._open_without_sidecar(apply=True)
        self.assertIn(("Metadata: created es.json.meta — 2 strings set (Complete)", "info"),
                      self._messages())

    def test_message_names_every_applied_option(self):
        self._open_without_sidecar(apply=True, status="Review", translator="Unknown",
                                   date=jte.QDate(2026, 10, 4))
        shown = jte.format_date_for_storage(MARK_DATE)
        self.assertIn((f"Metadata: created es.json.meta — 2 strings set "
                       f"(Review, translator Unknown, {shown})", "info"), self._messages())

    def test_message_for_skip(self):
        self._open_without_sidecar()
        self.assertIn(("Metadata: created es.json.meta — all strings New", "info"), self._messages())

    def test_no_question_while_closing(self):
        self.win._is_closing = True
        self.addCleanup(setattr, self.win, "_is_closing", False)
        self._open_without_sidecar()
        self.assertEqual(self.modals.titles("initial_meta"), [])

    def _open_with_failing_write(self) -> Path:
        with mock.patch.object(jte, "_atomic_write_bytes", side_effect=OSError("disk full")):
            return self._open_without_sidecar(apply=True)

    def test_failed_write_marks_the_file_modified(self):
        self._open_with_failing_write()
        self.assertTrue(self.win.is_modified)

    def test_failed_write_is_an_error_message(self):
        self._open_with_failing_write()
        self.assertIn(("Metadata: es.json.meta could not be created — Save to retry", "error"),
                      self._messages())

    def test_save_after_a_failed_write_stores_the_statuses(self):
        path = self._open_with_failing_write()
        self.win._save()
        self.assertEqual(set(_sidecar_entries(path)), {"Save", "Open"})

    def test_save_after_a_failed_write_keeps_the_file_intact(self):
        path = self._open_with_failing_write()
        self.win._save()
        cs.assert_json_intact(self, path, list(MIXED))


class InitialSidecarStartupTests(unittest.TestCase):
    """A file given on the command line is loaded before the window is shown (main()): the question
    must wait for the startup prompts (settings recovery, translator name), which come first."""

    def _startup(self, load) -> List[str]:
        """Build the window the way main() does with a file argument: *load(win)* before show().
        The translator prompt spins a real nested event loop, as the real dialog's exec() does; that
        loop is what ran an earlier zero-delay timer while the prompt was still open."""
        order: List[str] = []

        def ask(win):
            order.append("translator open")
            loop = QEventLoop()
            QTimer.singleShot(50, loop.quit)
            loop.exec()
            order.append("translator closed")

        def initial_meta(dlg):
            order.append("initial meta")
            dlg.done(QDialog.Rejected)
            return QDialog.Rejected

        settings_path = cs.temp_dir() / "json_translation_editor_settings.json"
        with cs.patched_modals(), mock.patch.object(jte, "SETTINGS_FILE", settings_path),                 mock.patch.object(jte.MainWindow, "_ask_translator_name", ask),                 mock.patch.object(jte.InitialMetadataDialog, "exec", initial_meta):
            win = jte.MainWindow()
            win.settings.data.setdefault("backup", {})["enabled"] = False
            load(win)
            win.show()
            cs.pump(10)
            win.is_modified = False
            win.close()
            cs.pump()
        return order

    def test_question_comes_after_the_startup_prompts(self):
        path = cs.write_pair(cs.temp_dir(), "es", MIXED)
        self.assertEqual(self._startup(lambda win: win._load(path)),
                         ["translator open", "translator closed", "initial meta"])

    def test_no_question_for_a_file_no_longer_open(self):
        first = cs.write_pair(cs.temp_dir(), "es", MIXED)
        second = cs.write_pair(cs.temp_dir(), "it", MIXED, meta={})
        order = self._startup(lambda win: (win._load(first), win._load(second)))
        self.assertNotIn("initial meta", order)


class InitialMetadataDialogTests(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.dlg = jte.InitialMetadataDialog("es.json", 2, 3, parent=self.win)

    def tearDown(self):
        self.dlg.close()
        cs.pump()

    def test_only_status_starts_ticked(self):
        self.assertEqual((self.dlg._status_chk.isChecked(), self.dlg._translator_chk.isChecked(),
                          self.dlg._date_chk.isChecked()), (True, False, False))

    def test_status_defaults_to_complete(self):
        self.assertEqual(self.dlg._status_combo.currentText(), "Complete")

    def test_status_offers_every_status(self):
        combo = self.dlg._status_combo
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], jte.STATUSES)

    def test_status_combo_widens_its_popup(self):
        self.assertIsInstance(self.dlg._status_combo, jte._WidePopupComboBox)

    def test_translator_defaults_to_unknown(self):
        self.assertEqual(self.dlg._translator_edit.text(), "Unknown")

    def test_date_defaults_to_today(self):
        self.assertEqual(self.dlg._date_field.date(), jte.QDate.currentDate())

    def test_fields_follow_their_check_boxes(self):
        boxes = (self.dlg._status_chk, self.dlg._translator_chk, self.dlg._date_chk)
        fields = (self.dlg._status_combo, self.dlg._translator_edit, self.dlg._date_field)
        before = [f.isEnabled() for f in fields]
        for box in boxes:
            box.toggle()
        after = [f.isEnabled() for f in fields]
        self.assertEqual((before, after), ([True, False, False], [False, True, True]))

    def test_default_apply_gives_complete_only(self):
        self.dlg.done(QDialog.Accepted)
        self.assertEqual((self.dlg.status(), self.dlg.translator(), self.dlg.modify_date()),
                         ("Complete", "", ""))

    def test_ticked_options_give_their_values(self):
        self.dlg._status_combo.setCurrentText("Review")
        self.dlg._translator_chk.setChecked(True)
        self.dlg._date_chk.setChecked(True)
        self.dlg._date_field.setDate(jte.QDate(2026, 10, 4))
        self.dlg.done(QDialog.Accepted)
        self.assertEqual((self.dlg.status(), self.dlg.translator(), self.dlg.modify_date()),
                         ("Review", "Unknown", jte.format_date_for_storage(MARK_DATE)))

    def test_unticked_status_gives_none(self):
        self.dlg._status_chk.setChecked(False)
        self.dlg.done(QDialog.Accepted)
        self.assertEqual(self.dlg.status(), "")

    def test_blank_translator_means_none(self):
        self.dlg._translator_chk.setChecked(True)
        self.dlg._translator_edit.setText("   ")
        self.dlg.done(QDialog.Accepted)
        self.assertEqual(self.dlg.translator(), "")

    def test_skip_gives_nothing(self):
        self.dlg._translator_chk.setChecked(True)
        self.dlg.done(QDialog.Rejected)
        self.assertEqual((self.dlg.status(), self.dlg.translator(), self.dlg.modify_date()),
                         ("", "", ""))

    def test_escape_skips(self):
        self.dlg.show()
        cs.pump()
        QTest.keyClick(self.dlg, Qt.Key_Escape)
        self.assertEqual(self.dlg.status(), "")

    def test_message_names_the_counts(self):
        self.assertIn("2 of 3 strings", self.dlg._intro.text())

    def test_intro_wraps_rather_than_widening_the_window(self):
        self.dlg.show()
        cs.pump()
        one_line = self.dlg._intro.fontMetrics().horizontalAdvance(self.dlg._intro.text())
        self.assertLess(self.dlg.width(), one_line)

    def test_fields_share_one_width(self):
        self.dlg.show()
        cs.pump()
        widths = {f.width() for f in (self.dlg._status_combo, self.dlg._translator_edit,
                                      self.dlg._date_field)}
        self.assertEqual(len(widths), 1)


MULTILINE_SOURCE = ("Line one of the source.\n\nLine three of the source.\nLine four of the source.\n"
                    "Line five of the source.")


class EditLayoutTests(WindowTestCase):
    """The Edit window's source box shows a multi-line source whole and grows with the window.
    It used to be capped at 100 px: at a large UI font a second paragraph was cut mid-line, and
    a taller window only added empty space around the box."""

    def _dialog(self, pt: int) -> "jte.EditDialog":
        self.load({MULTILINE_SOURCE: "Texto"}, meta=None)
        font = self.win.settings.get_font()
        font.setPointSize(pt)
        dlg = jte.EditDialog(self.win.model, 0, font, parent=self.win)
        dlg.show()
        cs.pump()
        self.addCleanup(dlg.close)
        return dlg

    def test_multiline_source_is_shown_whole(self):
        for pt in (8, 10, 16):
            with self.subTest(pt=pt):
                dlg = self._dialog(pt)
                self.assertEqual(dlg.src_view.verticalScrollBar().maximum(), 0)

    def test_source_box_grows_with_the_window(self):
        dlg = self._dialog(10)
        before = dlg.src_view.height()
        dlg.resize(dlg.width(), dlg.height() + 300)
        cs.pump()
        self.assertGreater(dlg.src_view.height(), before + 100)


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
        self.assertEqual([e.status for e in _reread(path)],
                         ["Review", "Complete", "Review"])

    def test_bulk_status_saves_an_intact_file(self):
        path = self.load()
        _select_rows(self.win, [0, 2])
        self.win._bulk_status("Review")
        self.win._save()
        cs.assert_json_intact(self, path, NAMES)


class DeleteTests(WindowTestCase):
    def test_deleting_one_row_saves_an_intact_file_without_it(self):
        path = self.load()
        self.modals.answers["question"] = QMessageBox.Yes
        self.win._delete_entries([self.win.entries[1]])
        self.win._save()
        cs.assert_json_intact(self, path, ["Save", "Open"])

    def test_deleting_several_rows_saves_an_intact_file_without_them(self):
        path = self.load()
        self.modals.answers["question"] = QMessageBox.Yes
        self.win._delete_entries([self.win.entries[0], self.win.entries[2]])
        self.win._save()
        cs.assert_json_intact(self, path, ["Cancel"])

    def test_declining_the_confirmation_deletes_nothing(self):
        self.load()
        self.modals.answers["question"] = QMessageBox.No
        self.win._delete_entries([self.win.entries[1]])
        self.assertEqual([e.name for e in self.win.entries], NAMES)

    def _lines_after_deleting(self, row: int) -> Tuple[List[str], List[str]]:
        """(lines before, lines after) deleting entry *row* and saving. Line 0 is the '{'."""
        path = self.load()
        before = path.read_bytes().decode("utf-8").splitlines(keepends=True)
        self.modals.answers["question"] = QMessageBox.Yes
        self.win._delete_entries([self.win.entries[row]])
        self.win._save()
        return before, path.read_bytes().decode("utf-8").splitlines(keepends=True)

    def test_deleting_a_middle_row_changes_only_its_line(self):
        before, after = self._lines_after_deleting(1)
        self.assertEqual(after, before[:2] + before[3:])

    def test_deleting_the_last_row_also_drops_the_comma_before_it(self):
        before, after = self._lines_after_deleting(2)
        self.assertEqual(after, before[:2] + [before[2].replace('",\n', '"\n')] + before[4:])


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
        self.assertEqual(_reread(path)[0].text, "Changed")

    def test_close_with_save_saves_an_intact_file(self):
        path, _ = self._load_modified()
        self.modals.answers["question"] = QMessageBox.Save
        self.win._close_file()
        cs.assert_json_intact(self, path, NAMES)

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
        self.assertEqual(self.win.current_file, path.resolve())

    def test_failed_save_keeps_the_file_open(self):
        path, _ = self._load_modified()
        self.modals.answers["question"] = QMessageBox.Save
        with mock.patch.object(jte, "save_translation_file", side_effect=OSError("locked")):
            self.win._close_file()
        self.assertEqual(self.win.current_file, path.resolve())

    def test_failed_sidecar_save_keeps_the_file_open(self):
        path, _ = self._load_modified()
        self.modals.answers["question"] = QMessageBox.Save
        with mock.patch.object(jte, "save_translation_file",
                               side_effect=jte.MetadataWriteError("locked")):
            self.win._close_file()
        self.assertEqual(self.win.current_file, path.resolve())


class SaveTests(WindowTestCase):
    def _save_with_sidecar_blocked(self) -> Path:
        """Load, edit, make the sidecar path a folder (so its write fails) and Save."""
        path = self.load()
        self.win.entries[0].text = "Changed"
        self.win.is_modified = True
        jte.meta_path_for(path).unlink()
        jte.meta_path_for(path).mkdir()
        self.win._save()
        return path

    def test_sidecar_failure_keeps_the_file_modified(self):
        self._save_with_sidecar_blocked()
        self.assertTrue(self.win.is_modified)

    def test_sidecar_failure_shows_a_save_error(self):
        self._save_with_sidecar_blocked()
        self.assertEqual(self.modals.titles("critical"), ["Save Error"])

    def test_sidecar_failure_still_saves_an_intact_language_file(self):
        path = self._save_with_sidecar_blocked()
        cs.assert_json_intact(self, path, NAMES)

    def _load_with_unreadable_sidecar(self) -> Path:
        """Load a file whose sidecar is a folder: reading it fails, so it must not be overwritten."""
        path = cs.write_pair(cs.temp_dir(), "es", PAIRS)
        jte.meta_path_for(path).mkdir()
        self.win.is_modified = False
        self.win._load(path)
        self.win.entries[0].text = "Changed"
        self.win.is_modified = True
        return path

    def test_unreadable_sidecar_is_skipped_on_save(self):
        self._load_with_unreadable_sidecar()
        self.win._save()
        self.assertFalse(self.win.is_modified)

    def test_unreadable_sidecar_is_left_untouched_by_save(self):
        path = self._load_with_unreadable_sidecar()
        self.win._save()
        self.assertTrue(jte.meta_path_for(path).is_dir())

    def _last_notice(self):
        return self.win._notice_history[-1]

    def test_save_with_an_unreadable_sidecar_warns_that_metadata_was_not_saved(self):
        self._load_with_unreadable_sidecar()
        self.win._save()
        notice = self._last_notice()
        self.assertEqual((notice.level, "metadata not saved" in notice.text), ("warning", True))

    def test_autosave_with_an_unreadable_sidecar_warns_that_metadata_was_not_saved(self):
        self._load_with_unreadable_sidecar()
        self.win._autosave_tick()
        notice = self._last_notice()
        self.assertEqual((notice.level, "metadata not saved" in notice.text), ("warning", True))

    def test_ordinary_save_is_not_a_warning(self):
        self.load()
        self.win.is_modified = True
        self.win._save()
        self.assertEqual(self._last_notice().level, "info")

    def test_unreadable_sidecar_still_saves_an_intact_language_file(self):
        path = self._load_with_unreadable_sidecar()
        self.win._save()
        cs.assert_json_intact(self, path, NAMES)

    def test_save_as_after_an_unreadable_sidecar_writes_the_new_sidecar(self):
        path = self._load_with_unreadable_sidecar()
        copy = path.parent / "Copy.json"
        self.modals.answers["save_path"] = str(copy)
        self.win._save_as()
        self.assertTrue(jte.meta_path_for(copy).is_file())


class SaveAsTests(WindowTestCase):
    def test_save_as_rederives_the_glossary(self):
        path = self.load()
        copy = path.parent / "Copy.json"
        jte.write_glossary(jte.glossary_path_for(copy), [jte.GlossaryEntry("Lane", "Carril")])
        self.modals.answers["save_path"] = str(copy)
        self.win._save_as()
        self.assertEqual([g.term for g in self.win.glossary], ["Lane"])

    def test_save_as_writes_an_intact_file(self):
        path = self.load()
        copy = path.parent / "Copy.json"
        self.modals.answers["save_path"] = str(copy)
        self.win._save_as()
        cs.assert_json_intact(self, copy, NAMES)


def _export_as(mode: str):
    """ExportDialog.exec() replaced: pick *mode* and press Export."""
    def fake_exec(dlg):
        (dlg._json_radio if mode == "json" else dlg._zip_radio).setChecked(True)
        dlg.done(QDialog.Accepted)
        return QDialog.Accepted
    return mock.patch.object(jte.ExportDialog, "exec", fake_exec)


class ExportWorkflowTests(WindowTestCase):
    def _export(self, path: Path, mode: str = "zip", target: Optional[Path] = None) -> Path:
        target = target or cs.temp_dir() / ("out.zip" if mode == "zip" else "out.json")
        self.modals.answers["save_path"] = str(target)
        with _export_as(mode):
            self.win._export()
        return target

    def _edit_and_export(self, answer) -> Tuple[Path, Path]:
        path = self.load()
        _edit(self.win, 0, text="Guardar ya")
        self.modals.answers["question"] = answer
        return path, self._export(path)

    def test_zip_holds_the_language_file_as_on_disk(self):
        path = self.load()
        target = self._export(path)
        with zipfile.ZipFile(target) as zf:
            self.assertEqual(zf.read("es.json"), path.read_bytes())

    def test_json_export_is_the_language_file(self):
        path = self.load()
        target = self._export(path, mode="json")
        self.assertEqual(target.read_bytes(), path.read_bytes())

    def test_unsaved_changes_are_saved_into_the_package(self):
        _path, target = self._edit_and_export(QMessageBox.Save)
        with zipfile.ZipFile(target) as zf:
            pairs, _style = jte.parse_json_bytes(zf.read("es.json"))
        self.assertEqual(pairs[0], ("Save", "Guardar ya"))

    def test_file_saved_before_export_is_intact(self):
        path, _target = self._edit_and_export(QMessageBox.Save)
        cs.assert_json_intact(self, path, NAMES)

    def test_cancel_at_the_save_prompt_writes_nothing(self):
        _path, target = self._edit_and_export(QMessageBox.Cancel)
        self.assertFalse(target.exists())

    def test_cancel_at_the_save_prompt_keeps_the_changes(self):
        self._edit_and_export(QMessageBox.Cancel)
        self.assertTrue(self.win.is_modified)

    def test_export_over_the_open_file_is_refused(self):
        path = self.load()
        before = path.read_bytes()
        self._export(path, mode="json", target=path)
        self.assertEqual((self.modals.titles("warning"), path.read_bytes()), (["Export"], before))

    def test_choice_is_remembered(self):
        path = self.load()
        self._export(path, mode="json")
        self.assertEqual(self.win.settings.get("export", {}).get("mode"), "json")

    def test_message_counts_the_files(self):
        path = self.load()   # a sidecar, no glossary
        self._export(path)
        self.assertIn(("Exported: out.zip  (2 files, no glossary)", "info"),
                      [(n.text, n.level) for n in self.win._notice_history])

    def test_failed_write_is_an_error_message(self):
        path = self.load()
        with mock.patch.object(jte, "_atomic_write_bytes", side_effect=OSError("disk full")):
            self._export(path)
        self.assertIn(("Export failed — out.zip could not be written", "error"),
                      [(n.text, n.level) for n in self.win._notice_history])

    def test_no_file_open_warns(self):
        self.load()
        self.win._close_file()
        with _export_as("zip"):
            self.win._export()
        self.assertEqual(self.modals.titles("warning"), ["Export"])

    def test_choice_radios_use_the_prominent_font_sized_indicator(self):
        dlg = jte.ExportDialog("zip", parent=self.win)
        dlg.show()
        cs.pump()
        pt = self.win.settings.get_font().pointSize()
        sizes = []
        for radio in (dlg._zip_radio, dlg._json_radio):
            opt = QStyleOptionButton()
            radio.initStyleOption(opt)
            sizes.append(radio.style().subElementRect(QStyle.SE_RadioButtonIndicator, opt,
                                                      radio).width())
        dlg.close()
        want = jte._indicator_px(pt) + 2 * jte._INDICATOR_BORDER_PX
        self.assertEqual(sizes, [want, want])


class FilterBarIndicatorTests(WindowTestCase):
    def test_filter_bar_check_boxes_keep_the_larger_indicator(self):
        pt = self.win.settings.get_font().pointSize()
        sizes = []
        for box in (self.win.filter_panel.date_from_chk, self.win.filter_panel.date_to_chk):
            opt = QStyleOptionButton()
            box.initStyleOption(opt)
            sizes.append(box.style().subElementRect(QStyle.SE_CheckBoxIndicator, opt, box).width())
        want = (jte._indicator_px(pt, jte._FILTER_BAR_INDICATOR_SCALE)
                + 2 * jte._INDICATOR_BORDER_PX)
        self.assertEqual(sizes, [want, want])


class FileMenuTests(WindowTestCase):
    def test_file_menu_is_grouped(self):
        menu = next(a.menu() for a in self.win.menuBar().actions() if a.text() == "&File")
        labels = ["-" if a.isSeparator() else a.text() for a in menu.actions()]
        self.assertEqual(labels, ["Open…", "New Language…", "-",
                                  "Save", "Save As…", "Restore from Backup…", "-",
                                  "Import…", "Export…", "Sync Keys from File…", "-",
                                  "Properties…", "-",
                                  "Close File", "Exit"])


def _accept_merge_defaults(dlg) -> int:
    """MergeConflictDialog.exec() replaced: accept every row's preselected choice."""
    dlg.done(QDialog.Accepted)
    return QDialog.Accepted


class MergeWorkflowTests(WindowTestCase):
    OPEN_PAIRS = {"Save": "Guardar", "Cancel": "Cancelar", "Old": "Viejo"}
    OPEN_META = {"Save": ("Complete", "Jane", DEFAULT_ISO),
                 "Cancel": ("Complete", "Jane", "2024-01-01"),
                 "Old": ("Complete", "Jane", DEFAULT_ISO)}
    INCOMING_PAIRS = {"Save": "Guardar", "Cancel": "Anular", "New": "Nuevo"}
    INCOMING_META = {"Save": ("Complete", "Jane", DEFAULT_ISO),
                     "Cancel": ("Complete", "Jane", "2025-06-01"),
                     "New": ("Complete", "Jane", DEFAULT_ISO)}

    def _merge_defaults(self, incoming_sidecar: Optional[bytes] = None) -> Tuple[Path, Path]:
        """Import es.json from another folder with every default choice, and save. Returns the open
        file and the incoming one. *incoming_sidecar* replaces the incoming sidecar's bytes."""
        path = self.load(self.OPEN_PAIRS, self.OPEN_META)
        incoming = cs.write_pair(cs.temp_dir(), "es", self.INCOMING_PAIRS, meta=self.INCOMING_META)
        if incoming_sidecar is not None:
            cs.write_exact(jte.meta_path_for(incoming), incoming_sidecar)
        self.modals.answers["open_path"] = str(incoming)
        with mock.patch.object(jte.MergeConflictDialog, "exec", _accept_merge_defaults):
            self.win._import()
        self.win._save()
        return path, incoming

    def test_full_merge_saves_an_intact_file(self):
        path, _ = self._merge_defaults()
        cs.assert_json_intact(self, path, ["Save", "Cancel", "Old", "New"])

    def test_full_merge_takes_the_newer_conflicting_text(self):
        path, _ = self._merge_defaults()
        self.assertEqual(_reread(path)[1].text, "Anular")

    def test_damaged_incoming_sidecar_is_left_in_place(self):
        _, incoming = self._merge_defaults(incoming_sidecar=b"{")
        self.assertEqual(jte.meta_path_for(incoming).read_bytes(), b"{")

    def test_damaged_incoming_sidecar_is_reported(self):
        self._merge_defaults(incoming_sidecar=b"{")
        self.assertIn(("Incoming file: Metadata: es.json.meta is damaged — statuses shown as New",
                       "error"),
                      [(n.text, n.level) for n in self.win._notice_history])


GLOSSARY_LANE = "term,translation,note\r\nLane,Carril,\r\n".encode("utf-8-sig")


def _package(pairs: Dict[str, str] = PAIRS, meta=META, glossary: Optional[bytes] = None,
             stem: str = "es") -> Path:
    """A real export of <stem>.json (with *meta* and *glossary*) as a ZIP in a folder of its own."""
    source = cs.write_pair(cs.temp_dir(), stem, pairs, meta=meta)
    if glossary is not None:
        cs.write_exact(jte.glossary_path_for(source), glossary)
    data, _ = jte.build_export_zip(source, jte.read_file_header(source))
    return cs.write_exact(cs.temp_dir() / f"{stem}_package.zip", data)


def _choose_glossary(change_choice: str):
    """MergeConflictDialog.exec() replaced: set every changed term to *change_choice*, apply."""
    def fake_exec(dlg):
        for combo in dlg._gl_change_combos:
            combo.setCurrentText(change_choice)
        dlg.done(QDialog.Accepted)
        return QDialog.Accepted
    return mock.patch.object(jte.MergeConflictDialog, "exec", fake_exec)


class ImportWorkflowTests(WindowTestCase):
    EXTRA = dict(PAIRS, New="Nuevo")

    def _import(self, package: Path, exec_patch=None) -> None:
        self.modals.answers["open_path"] = str(package)
        with exec_patch or mock.patch.object(jte.MergeConflictDialog, "exec", _accept_merge_defaults):
            self.win._import()

    def _notices(self) -> List[Tuple[str, str]]:
        return [(n.text, n.level) for n in self.win._notice_history]

    def _open_italian(self) -> Path:
        """Open it.json whose sidecar says "it", so an "es" package goes the folder route."""
        path = cs.write_pair(cs.temp_dir(), "it", PAIRS, meta=META, header={"language": "it"})
        self.win.is_modified = False
        self.win._load(path)
        return path

    # into the open file
    def test_same_language_merges_into_the_open_file(self):
        path = self.load()
        self._import(_package(self.EXTRA))
        self.win._save()
        cs.assert_json_intact(self, path, NAMES + ["New"])

    def test_same_language_asks_for_no_folder(self):
        self.load()
        self._import(_package(self.EXTRA))
        self.assertEqual(self.modals.titles("folder"), [])

    def test_new_glossary_terms_are_appended(self):
        path = self.load()
        jte.write_glossary(jte.glossary_path_for(path), [jte.GlossaryEntry("Lane", "Carril")])
        self.win._load(path)
        self._import(_package(glossary="term,translation,note\r\nLane,Carril,\r\nRoad,Vía,\r\n"
                                       .encode("utf-8-sig")))
        self.assertEqual([g.term for g in jte.parse_glossary(jte.glossary_path_for(path))[0]],
                         ["Lane", "Road"])

    def test_changed_term_keeps_the_open_translation_by_default(self):
        path = self.load()
        jte.write_glossary(jte.glossary_path_for(path), [jte.GlossaryEntry("Lane", "Calle")])
        self.win._load(path)
        self._import(_package(glossary=GLOSSARY_LANE), _choose_glossary("Keep open"))
        self.assertEqual(jte.parse_glossary(jte.glossary_path_for(path))[0][0].translation, "Calle")

    def test_changed_term_takes_keep_incoming(self):
        path = self.load()
        jte.write_glossary(jte.glossary_path_for(path), [jte.GlossaryEntry("Lane", "Calle")])
        self.win._load(path)
        self._import(_package(glossary=GLOSSARY_LANE), _choose_glossary("Keep incoming"))
        self.assertEqual(jte.parse_glossary(jte.glossary_path_for(path))[0][0].translation, "Carril")

    def test_glossary_edited_outside_after_open_keeps_its_new_terms(self):
        path = self.load()
        glossary = jte.glossary_path_for(path)
        jte.write_glossary(glossary, [jte.GlossaryEntry("Lane", "Carril")])
        self.win._load(path)
        jte.write_glossary(glossary, [jte.GlossaryEntry("Lane", "Carril"),
                                      jte.GlossaryEntry("Bridge", "Puente")])
        self._import(_package(glossary="term,translation,note\r\nRoad,Vía,\r\n".encode("utf-8-sig")))
        self.assertEqual([g.term for g in jte.parse_glossary(glossary)[0]],
                         ["Lane", "Bridge", "Road"])

    def test_unreadable_glossary_is_not_imported_into(self):
        path = self.load()
        glossary = cs.write_exact(jte.glossary_path_for(path), GLOSSARY_LANE)
        real_parse = jte.parse_glossary

        def parse(p):
            if p.resolve() == glossary.resolve():   # _load() resolves the 8.3 temp path
                return [], ["glossary unreadable (locked); treated as empty"]
            return real_parse(p)
        with mock.patch.object(jte, "parse_glossary", parse):
            self.win._load(path)
            self._import(_package(glossary="term,translation,note\r\nRoad,Vía,\r\n"
                                           .encode("utf-8-sig")))
        self.assertEqual((glossary.read_bytes(),
                          ("Glossary: not imported — es.glossary.csv could not be read", "error")
                          in self._notices()),
                         (GLOSSARY_LANE, True))

    def test_glossary_only_import_leaves_the_strings_saved(self):
        self.load()
        self._import(_package(glossary=GLOSSARY_LANE))
        self.assertFalse(self.win.is_modified)

    def test_glossary_message(self):
        self.load()
        self._import(_package(glossary=GLOSSARY_LANE))
        self.assertIn(("Glossary: 1 added, 0 updated", "info"), self._notices())

    def test_nothing_to_import(self):
        path = self.load()
        package = cs.write_exact(cs.temp_dir() / "same.zip",
                                 jte.build_export_zip(path, jte.read_file_header(path))[0])
        opened = []
        with mock.patch.object(jte.MergeConflictDialog, "exec", lambda d: opened.append(d) or 0):
            self.modals.answers["open_path"] = str(package)
            self.win._import()
        self.assertEqual((opened, self.win.is_modified,
                          ("Nothing to import — es.json already matches", "info") in self._notices()),
                         ([], False, True))

    def test_nothing_to_import_still_reports_the_incoming_sidecar(self):
        self.load()
        loose = cs.write_pair(cs.temp_dir(), "es", PAIRS)
        cs.write_exact(jte.meta_path_for(loose), b"{")
        self._import(loose)
        notices = self._notices()
        self.assertEqual(
            [("Incoming file: Metadata: es.json.meta is damaged — statuses shown as New", "error")
             in notices, ("Nothing to import — es.json already matches", "info") in notices],
            [True, True])

    def test_plain_json_merges_into_the_open_file(self):
        path = self.load()
        loose = cs.write_pair(cs.temp_dir(), "es", self.EXTRA, meta=META)
        self._import(loose)
        self.win._save()
        cs.assert_json_intact(self, path, NAMES + ["New"])

    # into a folder
    def test_other_language_into_a_folder_holding_the_file_merges_there(self):
        self._open_italian()
        folder = cs.temp_dir()
        target = cs.write_pair(folder, "es", PAIRS, meta=META)
        self.modals.answers["folder"] = str(folder)
        self._import(_package(self.EXTRA))
        self.win._save()
        cs.assert_json_intact(self, target, NAMES + ["New"])

    def test_into_an_empty_folder_unpacks_and_opens(self):
        self._open_italian()
        folder = cs.temp_dir()
        self.modals.answers["folder"] = str(folder)
        self._import(_package(self.EXTRA, glossary=GLOSSARY_LANE))
        self.assertEqual(sorted(p.name for p in folder.iterdir()) + [self.win.current_file.name],
                         ["es.glossary.csv", "es.json", "es.json.meta", "es.json"])

    def test_unpacked_file_is_intact(self):
        self._open_italian()
        folder = cs.temp_dir()
        self.modals.answers["folder"] = str(folder)
        self._import(_package(self.EXTRA))
        cs.assert_json_intact(self, folder / "es.json", NAMES + ["New"])

    def test_unpack_message(self):
        self._open_italian()
        folder = cs.temp_dir()
        self.modals.answers["folder"] = str(folder)
        self._import(_package(self.EXTRA))
        self.assertIn((f"Imported: es.json  v1.0.0  (4 strings) into {folder.name}", "info"),
                      self._notices())

    def test_stray_companions_are_replaced_or_removed_after_yes(self):
        self._open_italian()
        folder = cs.temp_dir()
        cs.write_exact(folder / "es.json.meta", b"stray")
        cs.write_exact(folder / "es.glossary.csv", b"stray")
        self.modals.answers.update(folder=str(folder), question=QMessageBox.Yes)
        package = _package(self.EXTRA)   # a sidecar, no glossary
        self._import(package)
        self.assertEqual(((folder / "es.json.meta").read_bytes() != b"stray",
                          (folder / "es.glossary.csv").exists(), self.modals.titles("question")),
                         (True, False, ["Replace Files"]))

    def test_stray_companions_replaced_after_yes_leave_an_intact_file(self):
        self._open_italian()
        folder = cs.temp_dir()
        cs.write_exact(folder / "es.json.meta", b"stray")
        cs.write_exact(folder / "es.glossary.csv", b"stray")
        self.modals.answers.update(folder=str(folder), question=QMessageBox.Yes)
        self._import(_package(self.EXTRA))
        cs.assert_json_intact(self, folder / "es.json", NAMES + ["New"])

    def test_stray_companions_declined_writes_nothing(self):
        self._open_italian()
        folder = cs.temp_dir()
        cs.write_exact(folder / "es.json.meta", b"stray")
        self.modals.answers.update(folder=str(folder), question=QMessageBox.No)
        self._import(_package(self.EXTRA))
        self.assertEqual(((folder / "es.json").exists(), (folder / "es.json.meta").read_bytes()),
                         (False, b"stray"))

    def test_cancel_at_the_unsaved_prompt_writes_nothing(self):
        self._open_italian()
        _edit(self.win, 0, text="Salva")
        folder = cs.temp_dir()
        self.modals.answers.update(folder=str(folder), question=QMessageBox.Cancel)
        self._import(_package(self.EXTRA))
        self.assertEqual(list(folder.iterdir()), [])

    # refusals
    def test_checksum_mismatch_declined_changes_nothing(self):
        self.load()
        with zipfile.ZipFile(_package(self.EXTRA)) as zf:
            files = {n: zf.read(n) for n in zf.namelist()}
        files["es.json"] = cs.json_doc(dict(self.EXTRA, Extra="Más"))
        bad = cs.temp_dir() / "bad.zip"
        with zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, raw in files.items():
                zf.writestr(name, raw)
        self.modals.answers["question"] = QMessageBox.No
        self._import(bad)
        self.assertEqual((self.modals.titles("question"), [e.name for e in self.win.entries]),
                         (["Checksum Mismatch"], NAMES))

    def test_not_a_package_is_an_import_error(self):
        self.load()
        bad = cs.temp_dir() / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("readme.txt", b"x")
        self._import(bad)
        self.assertEqual(self.modals.titles("critical"), ["Import Error"])

    def test_no_temporary_folder_is_an_error_message(self):
        self.load()
        package = _package(self.EXTRA)
        with mock.patch.object(jte.tempfile, "mkdtemp", side_effect=OSError("no space")):
            self._import(package)
        self.assertIn(("Import failed — no temporary folder could be created", "error"),
                      self._notices())

    def test_package_without_checksums_says_so(self):
        self.load()
        bad = cs.temp_dir() / "plain.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("es.json", cs.json_doc(self.EXTRA))
        self._import(bad)
        self.assertIn(("No checksums in this package — files not verified", "info"), self._notices())


def _backup_manifests(folder: Path) -> List[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in (folder / jte.BACKUP_DIR_NAME).rglob("backup_info.json")]


class RestoreTests(WindowTestCase):
    backup = True
    OLD_TEXT = cs.json_doc({"Old": "Viejo"})
    GLOSSARY = "term,translation,note\r\nLane,Carril,\r\n".encode("utf-8-sig")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.win.settings.data["backup"].update(location_mode="next_to_file", min_interval_minutes=0)

    def tearDown(self):
        cs.wait_until(lambda: not self.win._backup_threads)

    def _slot(self, source: Path, glossary: Optional[bytes] = None,
              md5: Optional[str] = None, meta: Optional[bytes] = None) -> Tuple[Path, dict]:
        """A backup slot of OLD_TEXT for *source*, in a backup root of its own."""
        slot = jte._write_backup_slot(
            root_dir=cs.temp_dir() / "bk", location_id="root", backup_key=source.stem,
            ts="2025-01-01_00-00-00", source_path=source, raw_bytes=self.OLD_TEXT,
            md5=md5 or hashlib.md5(self.OLD_TEXT).hexdigest(),
            glossary_source=jte.glossary_path_for(source) if glossary is not None else None,
            glossary_bytes=glossary,
            glossary_md5=hashlib.md5(glossary).hexdigest() if glossary is not None else None,
            meta_source=jte.meta_path_for(source) if meta is not None else None,
            meta_bytes=meta,
            meta_md5=hashlib.md5(meta).hexdigest() if meta is not None else None,
            compress=True, max_count=5, trigger="file_open", culture="es",
            display_language="Español", version="4.1.1140", is_fallback=False)
        return slot, json.loads((slot / "backup_info.json").read_text(encoding="utf-8"))

    META = cs.sidecar_doc({"Old": ("Review", "Jo", "2026-10-02")})

    def test_copy_restore_restores_the_sidecar_with_it(self):
        path = self.load()
        slot, info = self._slot(path, meta=self.META)
        self.modals.answers.update(button="Save as copy", question=QMessageBox.No)
        self.win._do_restore(slot, info)
        copy = next(path.parent.glob("es_restored_*.json"))
        self.assertEqual(jte.meta_path_for(copy).read_bytes(), self.META)

    def test_overwrite_restore_brings_back_the_sidecar(self):
        path = self.load()
        slot, info = self._slot(path, meta=self.META)
        self.modals.answers["button"] = "Overwrite original"
        self.win._do_restore(slot, info)
        meta = jte.meta_path_for(path)
        cs.wait_until(lambda: meta.exists() and meta.read_bytes() == self.META)
        cs.wait_until(lambda: not self.win._backup_threads)
        self.assertEqual(meta.read_bytes(), self.META)

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
        copies = sorted(path.parent.glob("es_restored_*.json"))
        self.assertEqual([c.read_bytes() for c in copies], [self.OLD_TEXT])

    def test_copy_restore_restores_the_glossary_with_it(self):
        path = self.load()
        slot, info = self._slot(path, glossary=self.GLOSSARY)
        self.modals.answers.update(button="Save as copy", question=QMessageBox.No)
        self.win._do_restore(slot, info, restore_glossary=True)
        copy = next(path.parent.glob("es_restored_*.json"))
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
        self.assertEqual(_reread(path)[0].text, "Guardar")

    def test_autosave_tick_saves_a_modified_file(self):
        path = self.load()
        self.win.entries[0].text = "Changed"
        self.win.is_modified = True
        self.win._autosave_tick()
        self.assertEqual(_reread(path)[0].text, "Changed")

    def test_autosave_tick_saves_an_intact_file(self):
        path = self.load()
        self.win.entries[0].text = "Changed"
        self.win.is_modified = True
        self.win._autosave_tick()
        cs.assert_json_intact(self, path, NAMES)

    def test_autosave_tick_clears_the_modified_flag(self):
        self.load()
        self.win.entries[0].text = "Changed"
        self.win.is_modified = True
        self.win._autosave_tick()
        self.assertFalse(self.win.is_modified)

    def _autosave_with_sidecar_blocked(self) -> Path:
        path = self.load()
        self.win.entries[0].text = "Changed"
        self.win.is_modified = True
        jte.meta_path_for(path).unlink()
        jte.meta_path_for(path).mkdir()
        self.win._autosave_tick()
        return path

    def test_autosave_sidecar_failure_keeps_the_file_modified(self):
        self._autosave_with_sidecar_blocked()
        self.assertTrue(self.win.is_modified)

    def test_autosave_sidecar_failure_still_saves_an_intact_language_file(self):
        path = self._autosave_with_sidecar_blocked()
        cs.assert_json_intact(self, path, NAMES)


ODD = b'{\n "Save":"Guardar",\n "Open":"Abrir"\n}\n'   # no space after the colons: does not round-trip


class ReformatTests(unittest.TestCase):
    def _open_odd(self, **answers):
        path = cs.write_exact(cs.temp_dir() / "es.json", ODD)
        return path, cs.open_window(path, **answers)

    def test_declined_reformat_leaves_the_file_unchanged(self):
        path, ctx = self._open_odd(question=QMessageBox.No)
        with ctx as (win, _modals):
            win.entries[0].text = "Guardar ya"
            win.is_modified = True
            win._save()
        self.assertEqual(path.read_bytes(), ODD)

    def test_reformat_is_asked_once(self):
        path, ctx = self._open_odd(question=QMessageBox.Yes)
        with ctx as (win, modals):
            win.is_modified = True
            win._save()
            win.is_modified = True
            win._save()
        self.assertEqual(modals.titles("question"), ["Reformat File"])

    def test_accepted_reformat_saves_an_intact_file(self):
        path, ctx = self._open_odd(question=QMessageBox.Yes)
        with ctx as (win, _modals):
            win.is_modified = True
            win._save()
        cs.assert_json_intact(self, path, ["Save", "Open"])

    def test_autosave_skips_a_file_that_would_be_reformatted(self):
        path, ctx = self._open_odd()
        with ctx as (win, _modals):
            win.is_modified = True
            win._autosave_tick()
        self.assertEqual(path.read_bytes(), ODD)


class RelativePathTests(unittest.TestCase):
    def test_save_as_onto_the_open_file_still_asks_before_reformatting(self):
        folder = cs.temp_dir()
        cs.write_exact(folder / "es.json", ODD)
        before = Path.cwd()
        try:
            os.chdir(folder)
            with cs.open_window(question=QMessageBox.No) as (win, modals):
                win._load(Path("es.json"))
                modals.answers["save_path"] = str(folder / "es.json")
                win._save_as()
                asked = modals.titles("question")
        finally:
            os.chdir(before)
        self.assertEqual(asked, ["Reformat File"])


class RoboSkipTests(unittest.TestCase):
    def test_chain_translates_only_new_untranslated_entries(self):
        path = cs.write_pair(cs.temp_dir(), "es",
                             {"A": "A", "B": "Be", "C": "C", "D": "D"},
                             meta={"C": ("Review", "Jo", "2026-10-02")})
        with cs.open_window(path) as (win, _modals):
            dlg = jte.EditDialog(win.model, 0, win.settings.get_font(), shortcuts={},
                                 target_culture="es", transl_cfg={}, parent=win)
            started = []
            dlg._start_translation = lambda: started.append(dlg.entry.name)
            dlg._robo_active = True
            dlg._robo_advance()
            dlg.reject()
        self.assertEqual(started, ["D"])



class PlaceholderLabelTests(unittest.TestCase):
    def _dialog(self, win):
        return jte.EditDialog(win.model, 0, win.settings.get_font(), shortcuts={},
                              target_culture="es", transl_cfg={}, parent=win)

    def test_label_shows_a_missing_placeholder(self):
        path = cs.write_pair(cs.temp_dir(), "es", {"{name} saved": "{name} guardado"})
        with cs.open_window(path) as (win, _modals):
            dlg = self._dialog(win)
            dlg.trans_edit.setPlainText("guardado")
            text = dlg._placeholder_label.text()
            dlg.reject()
        self.assertEqual(text, "Missing: {name}")

    def test_label_is_hidden_when_placeholders_match(self):
        path = cs.write_pair(cs.temp_dir(), "es", {"{name} saved": "{name} guardado"})
        with cs.open_window(path) as (win, _modals):
            dlg = self._dialog(win)
            hidden = dlg._placeholder_label.isHidden()
            dlg.reject()
        self.assertTrue(hidden)


class NewLanguageTests(unittest.TestCase):
    def test_new_entries_are_untranslated_and_new(self):
        source = [cs.make_entry(name="Save", text="Guardar", position=1),
                  cs.make_entry(name="Open", text="Abrir", position=2)]
        self.assertEqual([(e.name, e.text, e.status, e.translator, e.modify_date)
                          for e in jte.new_language_entries(source)],
                         [("Save", "Save", "New", "", ""), ("Open", "Open", "New", "", "")])

    def test_new_file_holds_every_key_with_its_english_text(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar", "Open": "Abrir"})
        with cs.open_window(path, text="lv", save_path=str(folder / "lv.json")) as (win, _m):
            win._new_language()
        self.assertEqual(json.loads((folder / "lv.json").read_bytes()), {"Save": "Save", "Open": "Open"})

    def test_new_file_is_intact(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar", "Open": "Abrir"})
        with cs.open_window(path, text="lv", save_path=str(folder / "lv.json")) as (win, _m):
            win._new_language()
        cs.assert_json_intact(self, folder / "lv.json", ["Save", "Open"])

    def test_new_file_records_its_language(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar"})
        with cs.open_window(path, text="lv-LV", save_path=str(folder / "lv.json")) as (win, _m):
            win._new_language()
        self.assertEqual(jte.read_file_header(folder / "lv.json").language, "lv-LV")

    def test_new_file_is_opened(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar"})
        with cs.open_window(path, text="lv", save_path=str(folder / "lv.json")) as (win, _m):
            win._new_language()
            opened = win.current_file
        self.assertEqual(opened, (folder / "lv.json").resolve())

    def test_cancelled_code_writes_nothing(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar"})
        with cs.open_window(path, text_ok=False, save_path=str(folder / "lv.json")) as (win, _m):
            win._new_language()
        self.assertFalse((folder / "lv.json").exists())

    def test_invalid_code_is_asked_again(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar"})
        with cs.open_window(path, text=["not a code!", "lv"],
                            save_path=str(folder / "lv.json")) as (win, modals):
            win._new_language()
        self.assertEqual(modals.titles("warning"), ["New Language"])

    def _modified_window(self, folder, **answers):
        path = cs.write_pair(folder, "es", {"Save": "Guardar", "Open": "Abrir"})
        return path, cs.open_window(path, text="lv", save_path=str(folder / "lv.json"), **answers)

    def test_discard_creates_the_file_from_the_keys_on_disk(self):
        folder = cs.temp_dir()
        _path, window = self._modified_window(folder, question=[QMessageBox.Yes, QMessageBox.Discard])
        with window as (win, _m):
            win._delete_entries([win.entries[1]])
            win._new_language()
        self.assertEqual(list(json.loads((folder / "lv.json").read_bytes())), ["Save", "Open"])

    def test_save_writes_the_open_file_first(self):
        folder = cs.temp_dir()
        path, window = self._modified_window(folder, question=QMessageBox.Save)
        with window as (win, _m):
            win.entries[0].text = "Changed"
            win.is_modified = True
            win._new_language()
        self.assertEqual(json.loads(path.read_bytes())["Save"], "Changed")

    def test_cancel_at_the_prompt_writes_nothing(self):
        folder = cs.temp_dir()
        _path, window = self._modified_window(folder, question=QMessageBox.Cancel)
        with window as (win, _m):
            win.is_modified = True
            win._new_language()
        self.assertFalse((folder / "lv.json").exists())

    def test_new_file_follows_the_open_files_style(self):
        folder = cs.temp_dir()
        path = cs.write_exact(folder / "es.json", cs.json_doc({"Save": "Guardar"}, indent="    "))
        with cs.open_window(path, text="lv", save_path=str(folder / "lv.json")) as (win, _m):
            win._new_language()
        self.assertIn(b'    "Save": "Save"', (folder / "lv.json").read_bytes().splitlines())

    def test_new_sidecar_lists_no_entries(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar"})
        with cs.open_window(path, text="lv", save_path=str(folder / "lv.json")) as (win, _m):
            win._new_language()
        self.assertEqual(json.loads((folder / "lv.json.meta").read_bytes())["entries"], {})

    def test_choosing_the_open_file_writes_nothing(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar"})
        before = path.read_bytes()
        with cs.open_window(path, text="lv", save_path=str(path)) as (win, _m):
            win._new_language()
        self.assertEqual(path.read_bytes(), before)

    def test_choosing_the_open_file_warns(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar"})
        with cs.open_window(path, text="lv", save_path=str(path)) as (win, modals):
            win._new_language()
        self.assertEqual(modals.titles("warning"), ["New Language"])


class TrimmedPasteTests(unittest.TestCase):
    def test_trimmed_paste_is_noted_when_the_source_has_outer_spaces(self):
        path = cs.write_pair(cs.temp_dir(), "es", {" (copy)": " (copia)"})
        with cs.open_window(path) as (win, _modals):
            dlg = jte.EditDialog(win.model, 0, win.settings.get_font(), shortcuts={},
                                 target_culture="es", transl_cfg={}, parent=win)
            mime = QMimeData()
            mime.setText(" (copia) ")
            dlg.trans_edit.insertFromMimeData(mime)
            status = dlg._transl_status.text()
            dlg.reject()
        self.assertIn("trimmed", status)


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))
