"""Offscreen check for File -> Properties (FilePropertiesDialog and its helpers).

Covers, first without a MainWindow:

  * a save_translation_file() -> read_file_header() round trip of the sidecar header, including a
    name with & and " in it, leaving the language file itself unchanged;
  * parse_version_parts()/format_version(): N.N.N within 99.99.99999, no zero padding added;
  * describe_culture(): known, region-less, unknown and empty codes;
  * compute_file_facts(): status/untranslated counts, and a file gone from disk;
  * the dialog: spin-box limits, a stored version loads unpadded, OK disabled for a blank name,
    an invalid stored version blocks OK until a box changes, '.' jumps to the next box.

then through a real MainWindow on a copy of es.json and its sidecar, run from a throwaway folder
with the startup modals patched (the app derives its settings file and backup root from the
working directory / argv[0], so the real ones are never touched):

  * OK with changes: the header, info bar, title bullet, is_modified; Save + reopen persists them
    in the sidecar and leaves the language file byte for byte as it was;
  * OK with nothing changed, and Cancel: no change, file not marked modified;
  * no file open: a warning, no dialog.

Run:  python tests/check_file_properties.py      (exit code 0 = all passed)
"""

import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parent.parent
SCRATCH = Path(tempfile.mkdtemp(prefix="xte_file_properties_"))
os.chdir(SCRATCH)
sys.argv[0] = str(SCRATCH / "check_file_properties.py")
sys.path.insert(0, str(REPO))
for _name in ("es.json", "es.json.meta"):
    shutil.copy(Path(__file__).resolve().parent / "data" / _name, SCRATCH / _name)

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget

import json_translation_editor as jte

PAIRS = {"A": "A", "B": "Bē", "C": "Cē", "D": "D"}
SIDECAR = {"format": 1, "language": "es", "language_name": "Español", "version": "4.1.1140",
           "entries": {"B": {"status": "Complete", "translator": "x", "modified": "2025-01-01"},
                       "C": {"status": "Review", "translator": "x", "modified": "2025-01-01"},
                       "D": {"status": "Complete", "translator": "x", "modified": "2025-01-01"}}}


def _write_sample(folder: Path) -> Path:
    """es.json from PAIRS plus its sidecar, written with the json module (not the app)."""
    path = folder / "es.json"
    path.write_bytes((json.dumps(PAIRS, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    (folder / "es.json.meta").write_bytes(
        (json.dumps(SIDECAR, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return path


def check(failures, label, ok, detail=""):
    if not ok:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def check_round_trip(failures):
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_sample(Path(tmp))
        before = path.read_bytes()
        loaded = jte.load_translation_file(path)
        header = jte.FileHeader(loaded.header.language, 'Español & "Co"', "4.1.1220")
        jte.save_translation_file(path, loaded.entries, loaded.style, header)
        header2 = jte.read_file_header(path)
        check(failures, "round trip language", header2.language_name == 'Español & "Co"',
              repr(header2.language_name))
        check(failures, "round trip version", header2.version == "4.1.1220", repr(header2.version))
        check(failures, "round trip culture", header2.language == "es", repr(header2.language))
        check(failures, "round trip entries",
              [e.text for e in jte.load_translation_file(path).entries] == list(PAIRS.values()))
        check(failures, "only the sidecar changed", path.read_bytes() == before)


def check_version_helpers(failures):
    cases = {"4.1.1220": (4, 1, 1220), "99.99.99999": (99, 99, 99999), "0.0.0": (0, 0, 0),
             "04.1.1140": (4, 1, 1140), "4.1": None, "4.1.1140.2": None, "100.1.1": None,
             "1.1.100000": None, "": None, "a.b.c": None, " 4.1.1": None}
    for text, want in cases.items():
        got = jte.parse_version_parts(text)
        check(failures, f"parse_version_parts({text!r})", got == want, repr(got))
    check(failures, "format_version pads nothing", jte.format_version((4, 1, 1220)) == "4.1.1220")
    check(failures, "format_version zeros", jte.format_version((0, 0, 0)) == "0.0.0")


def check_culture(failures):
    cases = {"lv-LV": "Latvian (Latvia)", "lv_LV": "Latvian (Latvia)", "lv": "Latvian",
             "pt-BR": "Portuguese (Brazil)", "xx-YY": "", "": ""}
    for code, want in cases.items():
        got = jte.describe_culture(code)
        check(failures, f"describe_culture({code!r})", got == want, repr(got))


def check_facts(failures):
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_sample(Path(tmp))
        entries = jte.load_translation_file(path).entries
        facts = jte.compute_file_facts(entries, path)
        check(failures, "facts total", facts.total == 4, repr(facts.total))
        check(failures, "facts by status",
              facts.by_status == {"New": 1, "Review": 1, "Complete": 2}, repr(facts.by_status))
        check(failures, "facts untranslated", facts.untranslated == 2, repr(facts.untranslated))
        check(failures, "FileFacts has no tablet count",
              "tablet" not in jte.FileFacts.__dataclass_fields__,
              repr(list(jte.FileFacts.__dataclass_fields__)))
        check(failures, "facts size", facts.size_bytes == path.stat().st_size, repr(facts.size_bytes))
        check(failures, "facts modified", facts.modified == path.stat().st_mtime, repr(facts.modified))
        check(failures, "facts name/folder", (facts.file_name, facts.folder) == (path.name, str(path.parent)))
        path.unlink()
        gone = jte.compute_file_facts(entries, path)
        check(failures, "file gone: size None", gone.size_bytes is None)
        check(failures, "file gone: modified None", gone.modified is None)
        check(failures, "file gone: counts still there", gone.total == 4)
    empty = jte.compute_file_facts([], Path("nowhere.json"))
    check(failures, "empty file facts", (empty.total, empty.by_status) == (0, {"New": 0, "Review": 0, "Complete": 0}))


class _StubSettings:
    def __init__(self, pt):
        self._pt = pt
        self.data = {}

    def get(self, key, default=None):
        return default

    def get_font(self):
        return QFont("Segoe UI", self._pt)


class _StubMain(QWidget):
    def __init__(self, theme="dark", pt=10):
        super().__init__()
        self._theme = theme
        self.settings = _StubSettings(pt)

    def _get_theme(self):
        return jte.THEMES[self._theme]


def _facts():
    return jte.FileFacts(file_name="es.json",
                         folder="C:\\Users\\translator\\Documents\\Localization\\Projects\\2026\\"
                                "Release 4.1\\Spanish\\Incoming from customer\\Reviewed",
                         size_bytes=1234, modified=0.0,
                         total=4, by_status={"New": 1, "Review": 1, "Complete": 2},
                         untranslated=2)


def _dialog(stub, lang="Español", version="4.1.1220", culture="es"):
    dlg = jte.FilePropertiesDialog(culture, lang, version, _facts(), False, stub)
    dlg.show()
    QApplication.processEvents()
    return dlg


def check_dialog(failures):
    for theme in jte.THEMES:
        stub = _StubMain(theme)
        dlg = _dialog(stub)
        spins = dlg._version_spins
        check(failures, f"{theme}: three version boxes", len(spins) == 3)
        check(failures, f"{theme}: box maxima",
              [s.maximum() for s in spins] == [99, 99, 99999], repr([s.maximum() for s in spins]))
        check(failures, f"{theme}: box minima", [s.minimum() for s in spins] == [0, 0, 0])
        check(failures, f"{theme}: stored version loads unpadded",
              [s.text() for s in spins] == ["4", "1", "1220"], repr([s.text() for s in spins]))
        check(failures, f"{theme}: version() unpadded", dlg.version() == "4.1.1220", dlg.version())
        check(failures, f"{theme}: OK enabled for a valid file", dlg._ok_btn.isEnabled())
        check(failures, f"{theme}: OK is the primary button", dlg._ok_btn.property("role") == "primary")
        check(failures, f"{theme}: warning hidden for a valid version", not dlg._version_warning.isVisible())
        folder = dlg._fact_labels["folder"]
        check(failures, f"{theme}: folder shown in full, not elided",
              folder.text().replace("​", "") == _facts().folder, repr(folder.text()))
        check(failures, f"{theme}: folder wraps", folder.wordWrap())

        dlg._lang_edit.setText("   ")
        check(failures, f"{theme}: OK disabled for a blank name", not dlg._ok_btn.isEnabled())
        dlg._lang_edit.setText("  Español  ")
        check(failures, f"{theme}: OK back for a name", dlg._ok_btn.isEnabled())
        check(failures, f"{theme}: name trimmed", dlg.display_language() == "Español")
        check(failures, f"{theme}: name capped", dlg._lang_edit.maxLength() == 64)

        spins[2].lineEdit().selectAll()
        QTest.keyClicks(spins[2].lineEdit(), "123456")
        check(failures, f"{theme}: build box takes at most 5 digits", spins[2].value() == 12345,
              repr(spins[2].value()))

        spins[0].setFocus()
        spins[0].lineEdit().selectAll()
        QTest.keyClicks(spins[0].lineEdit(), "7")
        QTest.keyClick(spins[0], Qt.Key_Period)
        QApplication.processEvents()
        check(failures, f"{theme}: '.' jumps to the next box", spins[1].hasFocus())
        dlg.close()

        bad = _dialog(stub, version="4.1.1140.2")
        check(failures, f"{theme}: invalid stored version opens at 0.0.0",
              [s.value() for s in bad._version_spins] == [0, 0, 0])
        check(failures, f"{theme}: invalid stored version shows the warning", bad._version_warning.isVisible())
        check(failures, f"{theme}: warning names the stored value", "4.1.1140.2" in bad._version_warning.text())
        check(failures, f"{theme}: invalid stored version blocks OK", not bad._ok_btn.isEnabled())
        bad._version_spins[2].setValue(1)
        check(failures, f"{theme}: a changed box unblocks OK", bad._ok_btn.isEnabled())
        bad.close()

        missing = _dialog(stub, lang="", version="", culture="")
        check(failures, f"{theme}: missing everything blocks OK", not missing._ok_btn.isEnabled())
        check(failures, f"{theme}: empty culture shows a dash", missing._culture_label.text() == "—",
              missing._culture_label.text())
        missing.close()
        stub.close()


def _run_dialog(win, language=None, parts=None, accept=True):
    """Open File -> Properties on *win* with exec() replaced: set the fields, then accept/cancel."""
    real_exec = jte.FilePropertiesDialog.exec
    seen = []

    def fake_exec(dlg):
        seen.append(dlg)
        if language is not None:
            dlg._lang_edit.setText(language)
        if parts is not None:
            for spin, value in zip(dlg._version_spins, parts):
                spin.setValue(value)
        return QDialog.Accepted if accept else QDialog.Rejected

    jte.FilePropertiesDialog.exec = fake_exec
    try:
        win._open_file_properties()
    finally:
        jte.FilePropertiesDialog.exec = real_exec
    return seen


def check_main_window(failures):
    app = QApplication.instance()
    path = SCRATCH / "es.json"
    meta_path = jte.meta_path_for(path)
    original = path.read_bytes()
    original_meta = meta_path.read_text(encoding="utf-8")
    win = jte.MainWindow()
    win.settings.data.setdefault("backup", {})["enabled"] = False
    win.show()
    app.processEvents()

    warned = []
    real_warning = jte.QMessageBox.warning
    jte.QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a) or 0)
    try:
        seen = _run_dialog(win)
    finally:
        jte.QMessageBox.warning = real_warning
    check(failures, "no file: warning shown", len(warned) == 1)
    check(failures, "no file: no dialog", not seen)

    win._load(path)
    app.processEvents()
    lang, version = win.display_language, win.file_version
    check(failures, "loaded header", (lang, version) == ("Español", "1.0.0"), repr((lang, version)))
    win.is_modified = False
    win._update_title()
    header_before = win.header

    _run_dialog(win, accept=False, language="Other", parts=(9, 9, 9))
    check(failures, "cancel: header unchanged", win.header == header_before)
    check(failures, "cancel: not modified", not win.is_modified)

    _run_dialog(win)
    check(failures, "unchanged OK: header unchanged", win.header == header_before)
    check(failures, "unchanged OK: not modified", not win.is_modified)

    _run_dialog(win, language="Español de España", parts=(4, 2, 7))
    check(failures, "OK: header rewritten",
          win.header == jte.FileHeader("es", "Español de España", "4.2.7"), repr(win.header))
    check(failures, "OK: state updated",
          (win.display_language, win.file_version) == ("Español de España", "4.2.7"))
    check(failures, "OK: modified", win.is_modified)
    check(failures, "OK: title bullet", win.windowTitle().endswith("●"), win.windowTitle())
    check(failures, "OK: info bar language", win._sb_lang_label.text() == "Español de España")
    check(failures, "OK: info bar version", win._sb_ver_label.text() == "v4.2.7")

    win._save()
    check(failures, "save cleared modified", not win.is_modified)
    check(failures, "save left the language file as it was", path.read_bytes() == original)
    check(failures, "save wrote only the two header fields",
          meta_path.read_text(encoding="utf-8")
          == original_meta.replace('"language_name": "Español"', '"language_name": "Español de España"')
                          .replace('"version": "1.0.0"', '"version": "4.2.7"'))
    header2 = jte.read_file_header(path)
    check(failures, "reopen",
          (header2.language, header2.language_name, header2.version) == ("es", "Español de España", "4.2.7"),
          repr(header2))

    win.is_modified = False
    win.close()
    app.processEvents()


@contextmanager
def _isolated_glyph_dir():
    real = jte._glyph_cache_dir
    with tempfile.TemporaryDirectory() as tmp:
        jte._glyph_cache_dir = lambda: Path(tmp) / "glyphs"
        try:
            yield
        finally:
            jte._glyph_cache_dir = real


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    failures = []
    for step in (check_round_trip, check_version_helpers, check_culture, check_facts):
        try:
            step(failures)
        except Exception as e:
            failures.append(f"{step.__name__}: {type(e).__name__}: {e}")
    # The startup modals block forever with nobody to click them (see the offscreen-smoke-test pitfall).
    jte.QMessageBox.warning = staticmethod(lambda *a, **k: 0)
    jte.TranslatorNameDialog.exec = lambda self: 0
    with _isolated_glyph_dir():
        for step in (check_dialog, check_main_window):
            try:
                step(failures)
            except Exception as e:
                failures.append(f"{step.__name__}: {type(e).__name__}: {e}")
    for f in failures:
        print("FAIL", f)
    print(f"{'FAILED' if failures else 'PASSED'}: {len(failures)} failure(s)")
    # Leave the folder first: Windows will not delete the working directory.
    os.chdir(tempfile.gettempdir())
    shutil.rmtree(SCRATCH, ignore_errors=True)
    # Return, never os._exit(): with a real MainWindow built that crashes (exit code 139).
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
