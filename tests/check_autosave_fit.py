"""Check that the Autosave & Backup dialog's spin boxes and location combo fit their text.

The three spin boxes (Interval, Keep last, Skip if backed up within) were a fixed 130 px and the
Backup location combo a fixed 230 px, so their text was cut from 12 pt ("ays back up" and
"Next to file + Root (recc" at 14 pt). This builds a real MainWindow at several UI font sizes in
both themes, opens View -> Autosave & Backup, and checks, with "Skip if backed up within" showing
"Always back up" and again at its maximum value:

  * every spin box and the combo is at least as wide as its own size hint (the width the style
    needs for its widest text, suffix, arrows and font),
  * the three spin boxes are one width (within TOLERANCE_PX), so they still form one column,
  * the combo is no more than TOLERANCE_PX wider than its size hint: spare dialog width goes to
    the empty third grid column, not to the fields.

Runs offscreen by default; set QT_QPA_PLATFORM=windows beforehand to run it on real fonts
(windows show briefly).

Run:  python tests/check_autosave_fit.py      (exit code 0 = all passed)
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parent.parent
SCRATCH = Path(tempfile.mkdtemp(prefix="xte_autosave_"))
# The app derives its settings file and backup root from the working directory / argv[0].
os.chdir(SCRATCH)
sys.argv[0] = str(SCRATCH / "check_autosave_fit.py")
sys.path.insert(0, str(REPO))

from PySide6.QtWidgets import QApplication, QComboBox, QSpinBox

import json_translation_editor as jte

FONT_PTS = (10, 12, 14, 18, 24)
TOLERANCE_PX = 1


def _pump(app):
    for _ in range(3):
        app.processEvents()


def _window(app, theme, pt):
    win = jte.MainWindow()
    win.settings.data["font_size"] = pt
    win.settings.set("theme", theme)
    win._apply_palette()
    win._apply_app_font()
    win._apply_theme()
    win.show()
    _pump(app)
    return win


def _text(widget):
    return widget.currentText() if isinstance(widget, QComboBox) else widget.text()


def _dialog_failures(dlg, where):
    failures = []
    spins = dlg.findChildren(QSpinBox)
    combo = dlg._bk_location_combo
    for widget in spins + [combo]:
        need = widget.sizeHint().width()
        if widget.width() < need:
            failures.append(f"{where}: '{_text(widget)}' is {widget.width()} px wide, "
                            f"its text needs {need}")
    widths = [s.width() for s in spins]
    if max(widths) - min(widths) > TOLERANCE_PX:
        failures.append(f"{where}: the spin boxes differ in width: {widths}")
    if combo.width() - combo.sizeHint().width() > TOLERANCE_PX:
        failures.append(f"{where}: the location combo is {combo.width()} px wide, its text "
                        f"needs only {combo.sizeHint().width()}")
    return failures


def check_dialog(app):
    failures = []
    for theme in jte.THEMES:
        for pt in FONT_PTS:
            win = _window(app, theme, pt)
            try:
                dlg = jte.AutosaveBackupDialog(win.settings, parent=win)
                interval = dlg._bk_min_interval_spin
                interval.setValue(interval.minimum())    # "Always back up"
                dlg.show()
                _pump(app)
                failures += _dialog_failures(dlg, f"{theme} {pt}pt")
                interval.setValue(interval.maximum())
                _pump(app)
                failures += _dialog_failures(dlg, f"{theme} {pt}pt (maximum)")
                dlg.close()
                _pump(app)
            finally:
                win.close()
                _pump(app)
    return failures


def _create_app():
    """QApplication; offscreen, on a 4096 x 2160 screen. The default offscreen screen is 800 px
    wide, and offscreen text is drawn as boxes far wider than real glyphs, so Qt would clamp the
    dialog to the screen at large fonts and squeeze every field -- a squeeze no real monitor
    produces at these sizes. Qt splits the platform string on ':', so the config path must not
    hold a drive letter: it is passed relative, from its own folder."""
    if os.environ["QT_QPA_PLATFORM"] != "offscreen":
        return QApplication([])
    cfg_dir = tempfile.mkdtemp(prefix="xte_screen_")
    screen = {"name": "check", "x": 0, "y": 0, "width": 4096, "height": 2160,
              "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}
    Path(cfg_dir, "screen.json").write_text(json.dumps({"screens": [screen]}), encoding="utf-8")
    os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=screen.json"
    prev_cwd = os.getcwd()
    os.chdir(cfg_dir)
    try:
        app = QApplication([])
    finally:
        os.chdir(prev_cwd)
        shutil.rmtree(cfg_dir, ignore_errors=True)
    return app


def main():
    app = _create_app()
    app.setStyle("Fusion")     # what main() does
    # The startup modals block forever with nobody to click them (see the offscreen-smoke-test pitfall).
    jte.QMessageBox.warning = staticmethod(lambda *a, **k: 0)
    jte.TranslatorNameDialog.exec = lambda self: 0
    try:
        failures = check_dialog(app)
    except Exception as e:
        failures = [f"check_dialog: {type(e).__name__}: {e}"]
    for f in failures:
        print("FAIL", f)
    print(f"{'FAILED' if failures else 'PASSED'}: {len(failures)} failure(s)")
    # Leave the folder first: Windows will not delete the working directory.
    os.chdir(tempfile.gettempdir())
    shutil.rmtree(SCRATCH, ignore_errors=True)
    # Return, never os._exit(): with a real MainWindow's objects still alive that crashes the
    # process (exit code 139) -- see check_combobox.py.
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
