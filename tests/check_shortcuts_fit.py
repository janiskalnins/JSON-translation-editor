"""Check that the Keyboard Shortcuts dialog's buttons and delay box fit their text at any UI font.

Record... (90 px), Reset (70 px) and the Robo-translate delay spin box (90 px) had fixed widths,
so their text was cut from 12 pt ("ecord." and "Rese" at 16 pt). This builds a real MainWindow
at several UI font sizes in both themes, opens View -> Keyboard Shortcuts, and checks that every
Record.../Reset button and the delay spin box is at least as wide as its own size hint (the width
the style needs for its text, padding and font), also for a Record button while it shows "Cancel"
during recording. A Record.../Reset button may not be more than BLOAT_TOLERANCE_PX wider than
that either: spare width goes to the label column, not to one section's buttons. The shortcut
texts must start at one x in all three sections (each section is its own grid), and the
delay box with them.

Runs offscreen by default; set QT_QPA_PLATFORM=windows beforehand to run it on real fonts
(windows show briefly).

Run:  python tests/check_shortcuts_fit.py      (exit code 0 = all passed)
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parent.parent
SCRATCH = Path(tempfile.mkdtemp(prefix="xte_shortcuts_"))
# The app derives its settings file and backup root from the working directory / argv[0].
os.chdir(SCRATCH)
sys.argv[0] = str(SCRATCH / "check_shortcuts_fit.py")
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtWidgets import QApplication, QPushButton, QSpinBox, QStyle

import json_translation_editor as jte

FONT_PTS = (10, 12, 14, 18, 24)
BLOAT_TOLERANCE_PX = 1
ALIGN_TOLERANCE_PX = 1


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


def _fit_failures(widget, where):
    need = widget.sizeHint().width()
    if widget.width() < need:
        label = widget.text() if isinstance(widget, QPushButton) else str(widget.value())
        return [f"{where}: '{label}' is {widget.width()} px wide, its text needs {need}"]
    return []


def _bloat_failures(widget, where):
    # Spare dialog width belongs to the label column; a button that takes it is twice as wide
    # as its text in one section and not in the others.
    need = widget.sizeHint().width()
    if widget.width() > need + BLOAT_TOLERANCE_PX:
        return [f"{where}: '{widget.text()}' is {widget.width()} px wide, its text needs only {need}"]
    return []


def _text_left(label, dlg):
    """Where the label's text starts, in dialog coordinates -- placed the way QLabel places it,
    so offscreen (text drawn as boxes) measures the same thing as a native run."""
    fm = label.fontMetrics()
    text_size = QSize(fm.horizontalAdvance(label.text()), fm.height())
    rect = QStyle.alignedRect(Qt.LeftToRight, label.alignment(), text_size, label.contentsRect())
    return label.mapTo(dlg, rect.topLeft()).x()


def _column_failures(dlg, where):
    """The shortcut column starts at one x in all three sections, and the delay box with it."""
    starts = {slot: _text_left(w["lbl_seq"], dlg) for slot, w in dlg._row_widgets.items()}
    failures = []
    if max(starts.values()) - min(starts.values()) > ALIGN_TOLERANCE_PX:
        failures.append(f"{where}: shortcut texts start at different x: {starts}")
    spin_left = dlg.findChildren(QSpinBox)[0].mapTo(dlg, QPoint(0, 0)).x()
    if abs(spin_left - min(starts.values())) > ALIGN_TOLERANCE_PX:
        failures.append(f"{where}: the delay box starts at x={spin_left}, the shortcuts at "
                        f"x={min(starts.values())}")
    return failures


def _dialog_failures(app, dlg, where):
    failures = _column_failures(dlg, where)
    for btn in dlg.findChildren(QPushButton):
        if btn.text() in ("Record…", "Reset"):
            failures += _fit_failures(btn, where)
            failures += _bloat_failures(btn, where)
    for spin in dlg.findChildren(QSpinBox):
        failures += _fit_failures(spin, where)
    slot = next(iter(dlg._row_widgets))
    dlg._start_recording(slot)
    _pump(app)
    failures += _fit_failures(dlg._row_widgets[slot]["btn_record"], f"{where} (recording)")
    dlg._cancel_recording()
    return failures


def check_dialog(app):
    failures = []
    for theme in jte.THEMES:
        for pt in FONT_PTS:
            win = _window(app, theme, pt)
            try:
                dlg = jte.ShortcutsDialog(win.settings, parent=win)
                dlg.show()
                _pump(app)
                failures += _dialog_failures(app, dlg, f"{theme} {pt}pt")
                dlg.close()
                _pump(app)
            finally:
                win.close()
                _pump(app)
    return failures


def _create_app():
    """QApplication; offscreen, on a 4096 x 2160 screen. The default offscreen screen is 800 px
    wide, and offscreen text is drawn as boxes far wider than real glyphs (the dialog wants
    2 934 px at 24 pt), so Qt clamped the window to the screen and squeezed every button -- a
    squeeze no real monitor produces at these sizes. Qt splits the platform string on ':', so
    the config path must not hold a drive letter: it is passed relative, from its own folder."""
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
