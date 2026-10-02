"""Glyph and popup check for the drop-downs (`_combobox_qss`): every QComboBox and the filter bar's
QDateEdit pickers.

A `QComboBox { background / border / padding }` rule moves the widget to style-sheet rendering,
where the unstyled drop-down keeps a 6 px speck of an arrow in a separated strip with a bevel
artefact, and the popup is drawn in Fusion's menu style, which ignores `::item` rules -- the hovered
row is a barely-there grey (dark) or a white row with a grey outline (light). Offscreen, under the
same Fusion style and theme palette `main()` sets, for both themes, this checks:

  * every real surface that has a combo box or date picker (main window filter bar, Choose UI Font,
    Autosave & Backup, Translation Settings, Merge, Edit) shows an arrow of a usable size, clearly
    lighter/darker than the field (>= 4.5:1), and a dimmed one when the control is disabled,
  * the popup is a list: a selected row is filled with the theme's selection colour, rows are at
    least twice the UI font tall, and the popup is as wide as its widest item (a list popup is only
    as wide as the combo unless `_WidePopupComboBox` widens it, and would elide longer items),
  * the helper never changes a control's height (the Merge dialog's per-row combos sit in a dense
    table and must not make its rows taller) and never takes text room from it (the Backup location
    combo showed "(recommended)" without its closing bracket once the drop-down strip grew),
  * the fallback: with the glyph cache folder unusable `_combobox_qss` must not raise, must carry
    no image rule, and must still style the drop-down.

(Whether the popup text is legible, and the hovered-row highlight -- it needs a real cursor -- cannot
be checked here: offscreen Qt has no fonts and no pointer. See "Testing" in CLAUDE.md for the manual
checks.) The real surfaces are built at the default UI font and at 14 pt, where the filter bar's fixed
widths get tight. The main window runs from a throwaway folder (removed afterwards) with its startup
modals patched, so the real settings file and backups are never touched.

Run:  python tests/check_combobox.py      (exit code 0 = all passed)
"""

import os
import shutil
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parent.parent
SCRATCH = Path(tempfile.mkdtemp(prefix="xte_combobox_"))
# The app derives its settings file and backup root from the working directory / argv[0].
os.chdir(SCRATCH)
sys.argv[0] = str(SCRATCH / "check_combobox.py")
sys.path.insert(0, str(REPO))
shutil.copy(Path(__file__).resolve().parent / "data" / "Latvian.xml", SCRATCH / "Latvian.xml")

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QComboBox, QDateEdit, QFontComboBox, QStyle,
                               QStyleOptionComboBox)

import json_translation_editor as jte

FONT_PTS = (8, 10, 14)
REAL_FONT_PTS = (10, 14)  # the default, and the size where the filter bar's fixed widths get tight
INSET = 1               # stay clear of the drop-down's own edge
GLYPH_MIN_DIFF = 90      # summed |dR|+|dG|+|dB| against the field fill
MIN_GLYPH_WIDTH = 8      # the broken arrow was 6 px wide
MIN_GLYPH_HEIGHT = 4
MAX_GLYPH_HEIGHT = 10    # a downward triangle is wider than tall; a taller shape is a separator
MIN_CONTRAST = 4.5
DIMMED_TOLERANCE = 30
SELECTION_TOLERANCE = 30
TEXT_ROOM_TOLERANCE = 1  # px; the arrow may need a pixel more at the largest UI font

BASE_RULES = """
    QComboBox {{ background: {bg4}; color: {fg}; border: 1px solid {border2};
                 border-radius: 3px; padding: 3px 6px; }}
    QDateEdit {{ background: {bg4}; color: {fg}; border: 1px solid {border2};
                 border-radius: 3px; padding: 2px 4px; }}
"""


def _luminance(color):
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color.red()) + 0.7152 * channel(color.green()) + 0.0722 * channel(color.blue())


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _diff(a, b):
    return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())


def _pump(app):
    for _ in range(6):
        app.processEvents()


def _glyph(widget):
    """(width, height, colour of the strongest glyph pixel, drop-down fill colour) of what is drawn
    inside the style's own drop-down rectangle of *widget* (the text is left out: offscreen Qt draws
    it as tofu boxes that would be mistaken for a glyph); width and height are 0 when nothing but
    the fill is there."""
    opt = QStyleOptionComboBox()
    opt.initFrom(widget)
    rect = widget.style().subControlRect(QStyle.CC_ComboBox, opt, QStyle.SC_ComboBoxArrow, widget)
    rect = rect.adjusted(INSET, INSET, -INSET, -INSET)
    image = widget.grab().toImage()
    pixels = [(x, y, QColor(image.pixel(x, y)))
              for y in range(rect.top(), rect.bottom() + 1)
              for x in range(rect.left(), rect.right() + 1)]
    fill = QColor(Counter(c.name() for _, _, c in pixels).most_common(1)[0][0])
    strongest = max((c for _, _, c in pixels), key=lambda c: _diff(c, fill))
    if _diff(strongest, fill) < GLYPH_MIN_DIFF:
        return 0, 0, fill, fill
    # A quarter of the glyph's own peak contrast: the size then means the same for a dim disabled
    # arrow as for a vivid one, whose faint antialiased edges would otherwise inflate it -- yet an
    # 8 px arrow at 8 pt, drawn on a half pixel, has edge pixels just under half of the peak.
    edge = _diff(strongest, fill) / 4
    hits = [(x, y) for x, y, c in pixels if _diff(c, fill) >= edge]
    xs, ys = [h[0] for h in hits], [h[1] for h in hits]
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1, strongest, fill


def _arrow_failures(widget, theme, where):
    """Failures for the arrow of one shown widget, judged by its current enabled state."""
    t = jte.THEMES[theme]
    width, height, color, fill = _glyph(widget)
    if width < MIN_GLYPH_WIDTH or height < MIN_GLYPH_HEIGHT:
        return [f"{theme} {where}: arrow is {width}x{height}px, "
                f"needs at least {MIN_GLYPH_WIDTH}x{MIN_GLYPH_HEIGHT}"]
    if height > MAX_GLYPH_HEIGHT:
        return [f"{theme} {where}: the drop-down holds a {width}x{height}px shape, not just an "
                f"arrow (a separator or bevel line inside the strip?)"]
    if widget.isEnabled() and _contrast(color, fill) < MIN_CONTRAST:
        return [f"{theme} {where}: arrow contrast {_contrast(color, fill):.1f}:1, "
                f"needs {MIN_CONTRAST}:1"]
    if not widget.isEnabled() and _diff(color, QColor(t["dlg_btn_dis_fg"])) > DIMMED_TOLERANCE:
        return [f"{theme} {where}: disabled arrow {color.name()} is not the "
                f"dimmed {t['dlg_btn_dis_fg']}"]
    return []


def _popup_failures(app, combo, theme, pt, where):
    """The popup is a list: a selected row is filled with the selection colour, and rows are tall
    enough to click comfortably. Under Fusion's menu-style popup neither holds."""
    t = jte.THEMES[theme]
    combo.showPopup()
    _pump(app)
    view = combo.view()
    index = view.model().index(1, 0)
    view.setCurrentIndex(index)
    view.selectionModel().select(index, QItemSelectionModel.ClearAndSelect)
    _pump(app)
    row = view.visualRect(index)
    image = view.viewport().grab().toImage()
    popup_width = view.window().width()
    widest_item = view.sizeHintForColumn(0) + 2 * view.frameWidth()
    if view.verticalScrollBar().isVisible():
        widest_item += view.verticalScrollBar().width()
    # Away from the text, where only the row's own background is painted. A row's rectangle can
    # be wider than the viewport, so the columns are clamped to the image.
    right = min(row.right(), image.width() - 1)
    sample = [QColor(image.pixel(x, y))
              for x in range(right - 12, right - 2)
              for y in range(row.top() + 3, row.bottom() - 2)]
    combo.hidePopup()
    _pump(app)
    if not sample:
        return [f"{theme} {where}: the popup's selected row could not be sampled"]
    fill = QColor(Counter(c.name() for c in sample).most_common(1)[0][0])
    failures = []
    if popup_width < widest_item:
        failures.append(f"{theme} {where}: popup is {popup_width}px wide, its widest item needs "
                        f"{widest_item}px (it would be elided)")
    if _diff(fill, QColor(t["sel_bg"])) > SELECTION_TOLERANCE:
        failures.append(f"{theme} {where}: selected popup row is {fill.name()}, "
                        f"not the selection colour {t['sel_bg']}")
    if row.height() < 2 * pt:
        failures.append(f"{theme} {where}: popup rows are {row.height()}px, "
                        f"needs at least {2 * pt}px")
    return failures


def _date_edit():
    """A picker like the filter bar's: with the calendar popup on it draws a combo-style drop-down
    instead of spin-box buttons."""
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    return edit


def _themed(app, widget, theme, pt, with_helper):
    t = jte.THEMES[theme]
    qss = BASE_RULES.format(**t) + (jte._combobox_qss(t, pt) if with_helper else "")
    widget.setStyleSheet(qss)
    widget.show()
    _pump(app)
    return widget


def check_helper(app):
    failures = []
    for theme in jte.THEMES:
        for pt in FONT_PTS:
            for kind, make in (("combo", QComboBox), ("date edit", _date_edit)):
                widget = _themed(app, make(), theme, pt, with_helper=True)
                where = f"{pt}pt {kind}"
                failures += _arrow_failures(widget, theme, where)
                widget.setEnabled(False)
                _pump(app)
                failures += _arrow_failures(widget, theme, f"{where} (disabled)")
                widget.close()
            # Narrower than its longest item, so a popup that is only as wide as the combo elides it.
            combo = _themed(app, jte._WidePopupComboBox(), theme, pt, with_helper=True)
            combo.addItems(["Alpha", "Beta", "Gamma", "A considerably longer item than the combo"])
            combo.setFixedWidth(90)
            failures += _popup_failures(app, combo, theme, pt, f"{pt}pt popup")
            combo.close()
            # More rows than fit: the popup's scrollbar then takes width from the items.
            many = _themed(app, jte._WidePopupComboBox(), theme, pt, with_helper=True)
            many.addItems([f"Item number {n} with a long label" for n in range(many.maxVisibleItems() + 5)])
            many.setFixedWidth(90)
            failures += _popup_failures(app, many, theme, pt, f"{pt}pt popup with a scrollbar")
            many.close()
    return failures


def _text_room(widget):
    opt = QStyleOptionComboBox()
    opt.initFrom(widget)
    return widget.style().subControlRect(QStyle.CC_ComboBox, opt, QStyle.SC_ComboBoxEditField,
                                         widget).width()


def check_size_unchanged(app):
    """The helper must neither make a control taller nor take text room from it: the Backup
    location combo and the filter bar's date pickers are fixed-width and already tight."""
    failures = []
    for theme in jte.THEMES:
        for pt in FONT_PTS:
            for kind, make in (("combo", QComboBox), ("date edit", _date_edit)):
                plain = _themed(app, make(), theme, pt, with_helper=False)
                styled = _themed(app, make(), theme, pt, with_helper=True)
                for widget in (plain, styled):
                    widget.setFixedWidth(130)
                _pump(app)
                if styled.sizeHint().height() != plain.sizeHint().height():
                    failures.append(f"{theme} {pt}pt {kind}: the helper changes the height from "
                                    f"{plain.sizeHint().height()}px to {styled.sizeHint().height()}px")
                if _text_room(styled) < _text_room(plain) - TEXT_ROOM_TOLERANCE:
                    failures.append(f"{theme} {pt}pt {kind}: the helper cuts the text room from "
                                    f"{_text_room(plain)}px to {_text_room(styled)}px")
                plain.close()
                styled.close()
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
    win._load(SCRATCH / "Latvian.xml")
    for thread in list(win._backup_threads):
        thread.wait(8000)
    _pump(app)
    return win


def _surfaces(win):
    """(name, widget, dialog to close afterwards or None) for every real drop-down in the app. A
    dialog rides on its last widget: closing deletes it (WA_DeleteOnClose), and with it the rest."""
    E = jte.StringEntry
    adds = [E("Add one", "Jane", "New", "01.01.2026", "false", "Pievienot")]
    confs = [(E("Conflict src", "A", "Review", "01.01.2025", "false", "Vecais"),
              E("Conflict src", "B", "Complete", "02.02.2026", "false", "Jaunais"))]
    dels = [E("Delete me", "C", "Complete", "03.03.2024", "false", "Dzest")]
    fp = win.filter_panel
    yield "filter bar status combo", fp.status_combo, None
    yield "filter bar mode combo", fp.mode_combo, None
    yield "filter bar field combo", fp.field_combo, None
    yield "filter bar date from", fp.date_from, None
    yield "filter bar date to", fp.date_to, None
    font = jte.FontSettingsDialog(win.settings.get_font(), parent=win)
    font.show()
    yield "Choose UI Font family", font._family_combo, font
    backup = jte.AutosaveBackupDialog(win.settings, parent=win)
    backup.show()
    yield "Autosave & Backup location", backup._bk_location_combo, backup
    transl = jte.TranslationSettingsDialog(win.settings, parent=win)
    transl.show()
    yield "Translation Settings engine", transl._engine_combo, None
    transl._engine_combo.setCurrentIndex(transl._engine_combo.findData("claude"))
    yield "Translation Settings Claude model", transl._claude_model, None
    transl._engine_combo.setCurrentIndex(transl._engine_combo.findData("claude_subscription"))
    yield "Translation Settings subscription model", transl._claude_sub_model, transl
    merge = jte.MergeConflictDialog(adds, confs, dels, parent=win)
    merge.show()
    yield "Merge addition row", merge._addition_combos[0], None
    yield "Merge conflict row", merge._conflict_combos[0], None
    yield "Merge deletion row", merge._deletion_combos[0], merge
    edit = jte.EditDialog(win.model, 0, win.settings.get_font(),
                          shortcuts=win.settings.get("shortcuts", {}),
                          target_culture=win.target_culture,
                          transl_cfg=win.settings.get("translation", {}), parent=win)
    edit.show()
    yield "Edit status", edit.status_combo, None
    yield "Edit date", edit.date_edit, edit


def check_real_surfaces(app):
    failures = []
    for theme in jte.THEMES:
        for pt in REAL_FONT_PTS:
            win = _window(app, theme, pt)
            try:
                for name, widget, dialog in _surfaces(win):
                    _pump(app)
                    where = f"{name} at {pt}pt"
                    failures += _arrow_failures(widget, theme, where)
                    # Offscreen Qt has no fonts, so the font-family combo is empty: nothing to select.
                    if isinstance(widget, QComboBox) and not isinstance(widget, QFontComboBox):
                        failures += _popup_failures(app, widget, theme, pt, f"{where} popup")
                    if dialog is not None:
                        dialog.close()
                backup = jte.AutosaveBackupDialog(win.settings, parent=win)
                backup.show()
                backup._bk_enable.setChecked(False)
                _pump(app)
                failures += _arrow_failures(backup._bk_location_combo, theme,
                                            f"Autosave & Backup location (disabled) at {pt}pt")
                backup.close()
            finally:
                # Loading the sample file normalizes its dates on a machine whose short-date format
                # differs, which marks the window modified and makes close() ask to discard.
                win.is_modified = False
                win.close()
                _pump(app)
    return failures


@contextmanager
def _patched(name, value):
    real = getattr(jte, name)
    setattr(jte, name, value)
    try:
        yield
    finally:
        setattr(jte, name, real)


def check_unwritable_folder_falls_back():
    failures = []
    with tempfile.NamedTemporaryFile() as blocker:
        with _patched("_glyph_cache_dir", lambda: Path(blocker.name) / "glyphs"):  # parent is a file
            for theme, t in jte.THEMES.items():
                try:
                    qss = jte._combobox_qss(t, 10)
                except Exception as e:
                    failures.append(f"{theme}: {type(e).__name__} escaped _combobox_qss")
                    continue
                if "image:" in qss:
                    failures.append(f"{theme}: qss references an arrow image although none could be written")
                if "::drop-down" not in qss:
                    failures.append(f"{theme}: the fallback lost the drop-down rules")
    return failures


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")     # what main() does
    # The startup modals block forever with nobody to click them (see the offscreen-smoke-test pitfall).
    jte.QMessageBox.warning = staticmethod(lambda *a, **k: 0)
    jte.TranslatorNameDialog.exec = lambda self: 0
    failures = []
    with tempfile.TemporaryDirectory() as glyphs:
        with _patched("_glyph_cache_dir", lambda: Path(glyphs)):
            for check in (check_real_surfaces, check_helper, check_size_unchanged):
                try:
                    failures += check(app)
                except Exception as e:
                    failures.append(f"{check.__name__}: {type(e).__name__}: {e}")
    try:
        failures += check_unwritable_folder_falls_back()
    except Exception as e:
        failures.append(f"check_unwritable_folder_falls_back: {type(e).__name__}: {e}")
    for f in failures:
        print("FAIL", f)
    print(f"{'FAILED' if failures else 'PASSED'}: {len(failures)} failure(s)")
    # Leave the folder first: Windows will not delete the working directory, and nothing may write
    # to the repo's.
    os.chdir(tempfile.gettempdir())
    shutil.rmtree(SCRATCH, ignore_errors=True)
    # Return, never os._exit(): skipping Python's and Qt's teardown with a real MainWindow's objects
    # still alive crashes the process (access violation, exit code 139) even though every result is
    # already printed. A normal exit is clean.
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
