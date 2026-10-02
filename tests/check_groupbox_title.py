"""Check that every group box's title sits on its border line and clear of its first row.

The group-box rule used fixed pixels (`margin-top: 6px; padding-top: 4px`), so the border line
stayed 6 px from the top of the box and the first row 9 px from it at every UI font size, while
the title grew with the font (17 px tall at 10 pt, 26 px at 14 pt). At 14 pt the line ran along
the top of the title instead of through it, and the title hung into the first row ("Header"
touching "Language name" in File Properties). Offscreen, under the same Fusion style and theme
palette `main()` sets, this builds a real MainWindow at 10, 12 and 14 pt in both themes, opens
every dialog that has group boxes -- Keyboard Shortcuts, Translation Settings, File Properties,
Edit, Autosave & Backup -- and checks each visible group box for:

  * a painted title,
  * the border line crossing the middle of the title's capitals, taken from the box's own font
    metrics (within LINE_TOLERANCE_PX),
  * the first row starting at least MIN_GAP_PX below the title's bottom edge.

Offscreen Qt has no fonts and draws text as boxes, which is why the capitals' middle comes from
the font metrics rather than from the ink. The script also runs on the native platform with real
fonts (windows are shown briefly): set QT_QPA_PLATFORM=windows before running it.

Run:  python tests/check_groupbox_title.py      (exit code 0 = all passed)
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parent.parent
SCRATCH = Path(tempfile.mkdtemp(prefix="xte_groupbox_"))
# The app derives its settings file and backup root from the working directory / argv[0].
os.chdir(SCRATCH)
sys.argv[0] = str(SCRATCH / "check_groupbox_title.py")
sys.path.insert(0, str(REPO))
for _name in ("es.json", "es.json.meta"):
    shutil.copy(Path(__file__).resolve().parent / "data" / _name, SCRATCH / _name)

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QGroupBox, QStyle, QStyleOptionGroupBox)

import json_translation_editor as jte

FONT_PTS = (10, 12, 14, 18, 24)
LINE_TOLERANCE_PX = 2
MIN_GAP_PX = 2
INK_MIN_DIFF = 120       # summed |dR|+|dG|+|dB| against the dialog surface
BORDER_MAX_DIFF = 40     # a pixel this close to the border colour belongs to the line


def _pump(app):
    for _ in range(3):
        app.processEvents()


def _diff(a, b):
    return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())


def _title_rect(box):
    opt = QStyleOptionGroupBox()
    box.initStyleOption(opt)
    return box.style().subControlRect(QStyle.CC_GroupBox, opt, QStyle.SC_GroupBoxLabel, box)


def _box_failures(dialog, box, theme, where):
    t = jte.THEMES[theme]
    surface, border = QColor(t["dlg_bg"]), QColor(t["border"])
    origin = box.mapTo(dialog, QPoint(0, 0))
    img = dialog.grab(QRect(origin, box.size())).toImage()
    scale = img.width() / max(1, box.width())
    title = _title_rect(box)
    name = f"{where} '{box.title()}'"

    x = int(6 * scale)   # left of the title (it starts at 8 px), past the 4 px corner radius
    line_y = next((y for y in range(img.height())
                   if _diff(img.pixelColor(x, y), border) <= BORDER_MAX_DIFF), None)
    if line_y is None:
        return [f"{name}: no border line found"]
    line_y /= scale

    failures = []
    has_ink = any(_diff(img.pixelColor(px, y), surface) >= INK_MIN_DIFF
                  and _diff(img.pixelColor(px, y), border) > BORDER_MAX_DIFF
                  for y in range(int(title.top() * scale), int((title.bottom() + 1) * scale))
                  for px in range(int(title.left() * scale), int((title.right() + 1) * scale)))
    if not has_ink:
        failures.append(f"{name}: no title painted in {title.getRect()}")
    # The middle of the capitals, from the box's own font. Offscreen text is drawn as boxes that
    # start at the top of the title's rectangle, so measuring the ink would find the line "in the
    # middle" whatever the rule says; natively the capitals start this far down.
    fm = box.fontMetrics()
    cap_mid = title.top() + fm.ascent() - fm.capHeight() / 2
    if abs(line_y - cap_mid) > LINE_TOLERANCE_PX:
        failures.append(f"{name}: border line at y={line_y:.1f}, the title's capitals are "
                        f"centred at y={cap_mid:.1f}")
    children = [w for w in box.findChildren(object) if hasattr(w, "isVisibleTo")
                and w.parent() is box and w.isVisibleTo(box)]
    if children:
        first_top = min(w.geometry().top() for w in children)
        if first_top < title.bottom() + 1 + MIN_GAP_PX:
            failures.append(f"{name}: first row starts at y={first_top}, the title ends at "
                            f"y={title.bottom() + 1}")
    return failures


def _window(app, theme, pt):
    win = jte.MainWindow()
    win.settings.data["font_size"] = pt
    win.settings.set("theme", theme)
    win._apply_palette()
    win._apply_app_font()
    win._apply_theme()
    win.resize(1500, 850)
    win.show()
    _pump(app)
    win._load(SCRATCH / "es.json")
    for thread in list(win._backup_threads):
        thread.wait(8000)
    _pump(app)
    return win


def _dialogs(win):
    """(name, dialog) for every dialog with group boxes; the caller closes each."""
    yield "Keyboard Shortcuts", jte.ShortcutsDialog(win.settings, parent=win)
    transl = jte.TranslationSettingsDialog(win.settings, parent=win)
    transl._engine_combo.setCurrentIndex(transl._engine_combo.findData("deepl"))
    yield "Translation Settings", transl
    yield "File Properties", jte.FilePropertiesDialog(
        win.target_culture, win.display_language, win.file_version,
        jte.compute_file_facts(win.entries, win.current_file), win.is_modified, parent=win)
    yield "Edit", jte.EditDialog(win.model, 0, win.settings.get_font(),
                                 shortcuts=win.settings.get("shortcuts", {}),
                                 target_culture=win.target_culture,
                                 transl_cfg=win.settings.get("translation", {}), parent=win)
    yield "Autosave & Backup", jte.AutosaveBackupDialog(win.settings, parent=win)


def check_real_dialogs(app):
    failures = []
    for theme in jte.THEMES:
        for pt in FONT_PTS:
            win = _window(app, theme, pt)
            try:
                for name, dialog in _dialogs(win):
                    dialog.show()
                    _pump(app)
                    boxes = [b for b in dialog.findChildren(QGroupBox) if b.isVisibleTo(dialog)]
                    if not boxes:
                        failures.append(f"{name} at {pt}pt {theme}: no visible group box")
                    for box in boxes:
                        failures += _box_failures(dialog, box, theme, f"{name} at {pt}pt {theme}")
                    dialog.close()
                    _pump(app)
            finally:
                # Loading the sample file normalizes its dates on a machine whose short-date format
                # differs, which marks the window modified and makes close() ask to discard.
                win.is_modified = False
                win.close()
                _pump(app)
    return failures


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")     # what main() does
    # The startup modals block forever with nobody to click them (see the offscreen-smoke-test pitfall).
    jte.QMessageBox.warning = staticmethod(lambda *a, **k: 0)
    jte.TranslatorNameDialog.exec = lambda self: 0
    failures = []
    try:
        failures += check_real_dialogs(app)
    except Exception as e:
        failures.append(f"check_real_dialogs: {type(e).__name__}: {e}")
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
