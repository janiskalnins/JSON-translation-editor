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

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QMimeData, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

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
        path = self.load(meta=None)
        self.win.entries[0].text = "Changed"
        self.win.is_modified = True
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
        path = self.load()
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
        path = self.load(meta=None)
        self.win.entries[0].text = "Changed"
        self.win.is_modified = True
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
