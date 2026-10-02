"""Check for the date pickers: _DatePickerField (the closed field), _DateDrumPopup (its pop-up) and
_DrumColumn (one wheel of the pop-up), plus _date_format_hint() and _date_section_order().

The field shows the date and changes it only through the pop-up, so a stray wheel notch or key
press can never change a date. Offscreen, this checks the format helpers, a drum column's keys,
wheel, clicks and drag, the pop-up's column order, day clamping, year range, confirm and cancel and
placement, and the closed field's inertness and open gestures, then the real pickers of a real
MainWindow. (The look of the fading rows, momentum on a real drag, touchpad scrolling and a second
monitor need the native platform and a real pointer: see "Testing" in CLAUDE.md. The drop-down
arrow's size and contrast are checked by check_combobox.py.) The main window runs from a throwaway
folder (removed afterwards) with its startup modals patched, so the real settings file and backups
are never touched.

Run:  python tests/check_date_picker.py      (exit code 0 = all passed)
"""

import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parent.parent
SCRATCH = Path(tempfile.mkdtemp(prefix="xte_date_picker_"))
# The app derives its settings file and backup root from the working directory / argv[0].
os.chdir(SCRATCH)
sys.argv[0] = str(SCRATCH / "check_date_picker.py")
sys.path.insert(0, str(REPO))
shutil.copy(Path(__file__).resolve().parent / "data" / "Latvian.xml", SCRATCH / "Latvian.xml")

from PySide6.QtCore import QDate, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

import json_translation_editor as jte

FILL_TOLERANCE = 12
REAL_FONT_PTS = (10, 14)


def _pump(app):
    for _ in range(6):
        app.processEvents()


def _qdate(text):
    day, month, year = (int(p) for p in text.split("."))
    return QDate(year, month, day)


def _show(d):
    return d.toString("dd.MM.yyyy")


# ── Format helpers ───────────────────────────────────────────────────────────

# (what, Qt format, expected hint, expected column order)
FORMAT_CASES = [
    ("day first, dots", "dd.MM.yyyy", "Format: dd.mm.yyyy", ["d", "M", "y"]),
    ("single-letter tokens", "d.M.yyyy", "Format: dd.mm.yyyy", ["d", "M", "y"]),
    ("month first, US", "M/d/yyyy", "Format: mm/dd/yyyy", ["M", "d", "y"]),
    ("year first, trailing dot", "yyyy.MM.dd.", "Format: yyyy.mm.dd.", ["y", "M", "d"]),
    ("two-digit year", "dd-MM-yy", "Format: dd-mm-yy", ["d", "M", "y"]),
]


def check_format_helpers(app):
    failures = []
    for what, fmt, hint, order in FORMAT_CASES:
        got_hint = jte._date_format_hint(fmt)
        if got_hint != hint:
            failures.append(f"hint, {what}: {fmt!r} gave {got_hint!r}, expected {hint!r}")
        got_order = jte._date_section_order(fmt)
        if got_order != order:
            failures.append(f"order, {what}: {fmt!r} gave {got_order}, expected {order}")
    return failures


# ── Drum column ──────────────────────────────────────────────────────────────

THEME = jte.THEMES["dark"]
DAYS = list(range(1, 32))
MONTHS = list(range(1, 13))
YEARS = list(range(2000, 2101))


def _column(app, values, current, wraps):
    column = jte._DrumColumn(values, current, wraps, QFont("Segoe UI", 10), THEME)
    column.show()
    _pump(app)
    return column


def _wheel(column, delta):
    point = QPointF(column.width() / 2, column.height() / 2)
    event = QWheelEvent(point, QPointF(column.mapToGlobal(point.toPoint())), QPoint(0, 0),
                        QPoint(0, delta), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(column, event)


# (what, values, start, wraps, key, expected value)
KEY_CASES = [
    ("Down moves to the next value", DAYS, 10, True, Qt.Key_Down, 11),
    ("Up moves to the previous value", DAYS, 10, True, Qt.Key_Up, 9),
    ("PageDown moves five", DAYS, 10, True, Qt.Key_PageDown, 15),
    ("PageUp moves five back", DAYS, 10, True, Qt.Key_PageUp, 5),
    ("Home goes to the first value", DAYS, 17, True, Qt.Key_Home, 1),
    ("End goes to the last value", DAYS, 17, True, Qt.Key_End, 31),
    ("the day wraps forward", DAYS, 31, True, Qt.Key_Down, 1),
    ("the month wraps back", MONTHS, 1, True, Qt.Key_Up, 12),
    ("the month wraps forward", MONTHS, 12, True, Qt.Key_Down, 1),
    ("the year stops at the last", YEARS, 2100, False, Qt.Key_Down, 2100),
    ("the year stops at the first", YEARS, 2000, False, Qt.Key_Up, 2000),
    ("PageDown on the year stops at the last", YEARS, 2098, False, Qt.Key_PageDown, 2100),
]


def check_column_keys(app):
    failures = []
    for what, values, start, wraps, key, expected in KEY_CASES:
        column = _column(app, values, start, wraps)
        QTest.keyClick(column, key)
        if column.value() != expected:
            failures.append(f"column key, {what}: {start} gave {column.value()}, expected {expected}")
        column.close()
    return failures


def check_column_wheel(app):
    failures = []
    column = _column(app, DAYS, 10, True)
    _wheel(column, 120)
    if column.value() != 9:
        failures.append(f"one wheel notch up on 10 gave {column.value()}, expected 9")
    _wheel(column, -120)
    _wheel(column, -120)
    if column.value() != 11:
        failures.append(f"two wheel notches down on 9 gave {column.value()}, expected 11")
    _wheel(column, 60)
    if column.value() != 11:
        failures.append(f"half a notch moved the column to {column.value()}")
    _wheel(column, 60)
    if column.value() != 10:
        failures.append(f"two half notches on 11 gave {column.value()}, expected 10")
    column.close()
    return failures


def check_column_clicks(app):
    failures = []
    column = _column(app, DAYS, 10, True)
    clicked = []
    column.middle_clicked.connect(lambda: clicked.append(1))
    x, mid, row = column.width() // 2, column.height() // 2, column.row_height()
    QTest.mouseClick(column, Qt.LeftButton, pos=QPoint(x, mid - row))
    if column.value() != 9:
        failures.append(f"a click on the row above 10 gave {column.value()}, expected 9")
    if clicked:
        failures.append("a click on the row above the middle counted as a middle click")
    QTest.qWait(column.SNAP_MS + 100)
    QTest.mouseClick(column, Qt.LeftButton, pos=QPoint(x, mid))
    if len(clicked) != 1:
        failures.append(f"a click on the middle row gave {len(clicked)} middle clicks, expected 1")
    if column.value() != 9:
        failures.append(f"a click on the middle row moved the column to {column.value()}")
    column.close()
    return failures


def check_column_drag(app):
    failures = []
    column = _column(app, DAYS, 10, True)
    x, mid, row = column.width() // 2, column.height() // 2, column.row_height()
    QTest.mousePress(column, Qt.LeftButton, pos=QPoint(x, mid))
    QTest.mouseMove(column, QPoint(x, mid - 2 * row))
    QTest.qWait(200)   # the pointer rests, so the release carries no momentum
    QTest.mouseRelease(column, Qt.LeftButton, pos=QPoint(x, mid - 2 * row))
    if column.value() != 12:
        failures.append(f"dragging 10 up by two rows gave {column.value()}, expected 12")
    column.close()
    return failures


def check_column_signal_and_values(app):
    failures = []
    column = _column(app, DAYS, 31, True)
    emitted = []
    column.value_changed.connect(emitted.append)
    column.step(1)
    if emitted != [1]:
        failures.append(f"stepping 31 by one emitted {emitted}, expected [1]")
    column.step(0)
    if emitted != [1]:
        failures.append(f"a zero step emitted again: {emitted}")
    column.set_values(list(range(1, 31)), 31)
    if column.value() != 30 or len(column.values()) != 30:
        failures.append(f"set_values(1..30, 31) gave value {column.value()} with "
                        f"{len(column.values())} values, expected 30 and 30")
    if emitted != [1]:
        failures.append(f"set_values emitted value_changed: {emitted}")
    column.close()
    return failures


def check_column_paint(app):
    """The middle band is painted in bg3, and a hidden-from-view paint does not raise."""
    column = _column(app, DAYS, 10, True)
    image = column.grab().toImage()
    band = QColor(image.pixel(2, column.height() // 2 - column.row_height() // 2 + 3))
    column.close()
    if band.name() != QColor(THEME["bg3"]).name():
        return [f"the middle band is {band.name()}, expected {THEME['bg3']}"]
    return []


# ── Pop-up ───────────────────────────────────────────────────────────────────

PLACEMENT_TOLERANCE_PX = 3   # the offscreen platform gives every top-level window a 2 px frame margin that a frameless Qt.Popup on a real display does not have


def _holder_field(app, start, field_class=None):
    """A date field inside a plain top-level widget, with the app's display format."""
    holder = QWidget()
    holder.resize(320, 60)
    field = (field_class or jte.QDateEdit)(holder)
    field.setDisplayFormat(jte.DATE_FMT_QT)
    field.setDate(_qdate(start))
    field.setGeometry(10, 10, 200, 30)
    holder.show()
    _pump(app)
    return holder, field


def _popup(app, start):
    holder, field = _holder_field(app, start)
    changes = []
    field.dateChanged.connect(changes.append)
    popup = jte._DateDrumPopup(field)
    popup.show_at_field()
    _pump(app)
    return holder, field, popup, changes


def _no_popup_open(app):
    _pump(app)
    return QApplication.activePopupWidget() is None


def check_popup_columns(app):
    failures = []
    holder, field, popup, _ = _popup(app, "31.01.2025")
    expected = jte._date_section_order(jte.DATE_FMT_QT)
    if popup.order != expected or list(popup.columns()) != expected:
        failures.append(f"column order {popup.order} / {list(popup.columns())}, expected {expected}")
    xs = [popup.columns()[part].x() for part in popup.order]
    if xs != sorted(xs):
        failures.append(f"columns are not laid out left to right in order: x = {xs}")
    got = {part: col.value() for part, col in popup.columns().items()}
    if got != {"d": 31, "M": 1, "y": 2025}:
        failures.append(f"opened on 31.01.2025 the columns show {got}")
    hints = [label.text() for label in popup.findChildren(QLabel)]
    if hints != [jte._date_format_hint(jte.DATE_FMT_QT)]:
        failures.append(f"format hint labels {hints}, expected [{jte._date_format_hint(jte.DATE_FMT_QT)!r}]")
    popup.close()
    holder.close()
    return failures


# (what, start, column, steps, expected day, expected number of days)
CLAMP_CASES = [
    ("31 January -> April", "31.01.2025", "M", 3, 30, 30),
    ("29 February 2024 -> 2025", "29.02.2024", "y", 1, 28, 28),
    ("30 April -> May keeps 30", "30.04.2025", "M", 1, 30, 31),
]


def check_popup_day_clamp(app):
    failures = []
    for what, start, part, steps, day, days in CLAMP_CASES:
        holder, field, popup, _ = _popup(app, start)
        popup.columns()[part].step(steps)
        column = popup.columns()["d"]
        if column.value() != day or len(column.values()) != days:
            failures.append(f"{what}: day {column.value()} of {len(column.values())}, "
                            f"expected {day} of {days}")
        popup.close()
        holder.close()
    return failures


def check_popup_years(app):
    failures = []
    holder, field, popup, changes = _popup(app, "05.05.1998")
    years = popup.columns()["y"].values()
    if years[:2] != [1998, 2000] or years[-1] != 2100:
        failures.append(f"opened on 1998 the years run {years[:2]}...{years[-1]}, "
                        f"expected [1998, 2000]...2100")
    popup.confirm()
    if _show(field.date()) != "05.05.1998" or changes:
        failures.append(f"confirming 05.05.1998 unchanged gave {_show(field.date())} "
                        f"with {len(changes)} dateChanged")
    holder.close()
    holder, field, popup, _ = _popup(app, "05.05.2105")
    years = popup.columns()["y"].values()
    if years[0] != 2000 or years[-2:] != [2100, 2105]:
        failures.append(f"opened on 2105 the years run {years[0]}...{years[-2:]}, "
                        f"expected 2000...[2100, 2105]")
    popup.close()
    holder.close()
    return failures


def check_popup_confirm_and_cancel(app):
    failures = []
    # Enter confirms.
    holder, field, popup, changes = _popup(app, "10.06.2025")
    day = popup.columns()["d"]
    day.step(2)
    QTest.keyClick(day, Qt.Key_Return)
    if _show(field.date()) != "12.06.2025" or len(changes) != 1:
        failures.append(f"Enter gave {_show(field.date())} with {len(changes)} dateChanged, "
                        f"expected 12.06.2025 with 1")
    if not _no_popup_open(app):
        failures.append("the pop-up is still open after Enter")
    holder.close()
    # A click on the middle row confirms.
    holder, field, popup, changes = _popup(app, "10.06.2025")
    month = popup.columns()["M"]
    month.step(1)
    QTest.qWait(month.SNAP_MS + 100)
    QTest.mouseClick(month, Qt.LeftButton, pos=QPoint(month.width() // 2, month.height() // 2))
    if _show(field.date()) != "10.07.2025" or len(changes) != 1:
        failures.append(f"a middle click gave {_show(field.date())} with {len(changes)} "
                        f"dateChanged, expected 10.07.2025 with 1")
    if not _no_popup_open(app):
        failures.append("the pop-up is still open after a middle click")
    holder.close()
    # Escape cancels.
    holder, field, popup, changes = _popup(app, "10.06.2025")
    day = popup.columns()["d"]
    day.step(2)
    QTest.keyClick(day, Qt.Key_Escape)
    if _show(field.date()) != "10.06.2025" or changes:
        failures.append(f"Escape changed the date to {_show(field.date())} "
                        f"({len(changes)} dateChanged)")
    if not _no_popup_open(app):
        failures.append("the pop-up is still open after Escape")
    holder.close()
    # Closing without confirming (what a click outside does) cancels.
    holder, field, popup, changes = _popup(app, "10.06.2025")
    popup.columns()["y"].step(1)
    popup.close()
    if _show(field.date()) != "10.06.2025" or changes:
        failures.append(f"closing without confirming changed the date to {_show(field.date())}")
    holder.close()
    return failures


def check_popup_focus_keys(app):
    failures = []
    holder, field, popup, _ = _popup(app, "10.06.2025")
    first, second = (popup.columns()[part] for part in popup.order[:2])
    if popup.focusWidget() is not popup.columns()["d"]:
        failures.append("the day column does not have the initial focus")
    first.setFocus()
    QTest.keyClick(first, Qt.Key_Right)
    if popup.focusWidget() is not second:
        failures.append("Right did not move the focus to the next column")
    QTest.keyClick(second, Qt.Key_Left)
    if popup.focusWidget() is not first:
        failures.append("Left did not move the focus back")
    popup.close()
    holder.close()
    return failures


def check_popup_placement(app):
    failures = []
    holder, field, popup, _ = _popup(app, "10.06.2025")
    below = field.mapToGlobal(QPoint(0, field.height())).y()
    if abs(popup.y() - below) > PLACEMENT_TOLERANCE_PX:
        failures.append(f"the pop-up opens at y={popup.y()}, expected just under the field ({below})")
    popup.close()
    holder.close()
    holder, field = _holder_field(app, "10.06.2025")
    avail = field.screen().availableGeometry()
    holder.move(avail.left(), avail.bottom() - 60)
    _pump(app)
    popup = jte._DateDrumPopup(field)
    popup.show_at_field()
    _pump(app)
    top = field.mapToGlobal(QPoint(0, 0)).y()
    if popup.y() + popup.height() > top + PLACEMENT_TOLERANCE_PX:
        failures.append(f"near the screen's bottom the pop-up spans y={popup.y()}.."
                        f"{popup.y() + popup.height()}, expected it above the field (top {top})")
    popup.close()
    holder.close()
    return failures


# ── Closed field ─────────────────────────────────────────────────────────────

def _field(app, start):
    return _holder_field(app, start, jte._DatePickerField)


def check_field_is_inert(app):
    """The wheel, arrow keys and typing leave the date alone and open nothing."""
    failures = []
    holder, field = _field(app, "31.01.2025")
    changes = []
    field.dateChanged.connect(changes.append)
    for target in (field, field.lineEdit()):
        point = QPointF(20, 15)
        for delta in (120, -120):
            QApplication.sendEvent(target, QWheelEvent(
                point, QPointF(target.mapToGlobal(point.toPoint())), QPoint(0, 0),
                QPoint(0, delta), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    field.setFocus()
    for key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_5, Qt.Key_Delete):
        QTest.keyClick(field, key)
    _pump(app)
    if changes or _show(field.date()) != "31.01.2025":
        failures.append(f"wheel/keys changed the closed field to {_show(field.date())}")
    if not _no_popup_open(app):
        failures.append("wheel/keys on the closed field opened a pop-up")
    if not field.lineEdit().isReadOnly():
        failures.append("the field's text is editable")
    if field.toolTip() != jte._date_format_hint(jte.DATE_FMT_QT):
        failures.append(f"the field's tooltip is {field.toolTip()!r}")
    holder.close()
    return failures


def check_field_opens(app):
    failures = []
    holder, field = _field(app, "31.01.2025")
    gestures = [
        ("click on the text", lambda: QTest.mouseClick(field.lineEdit(), Qt.LeftButton,
                                                       pos=QPoint(10, 10))),
        ("click on the arrow", lambda: QTest.mouseClick(field, Qt.LeftButton,
                                                        pos=QPoint(field.width() - 8, 15))),
        ("Return", lambda: QTest.keyClick(field, Qt.Key_Return)),
        ("Enter", lambda: QTest.keyClick(field, Qt.Key_Enter)),
        ("Space", lambda: QTest.keyClick(field, Qt.Key_Space)),
        ("F4", lambda: QTest.keyClick(field, Qt.Key_F4)),
        ("Alt+Down", lambda: QTest.keyClick(field, Qt.Key_Down, Qt.AltModifier)),
    ]
    for name, gesture in gestures:
        field.setFocus()
        gesture()
        _pump(app)
        popup = QApplication.activePopupWidget()
        if not isinstance(popup, jte._DateDrumPopup):
            failures.append(f"{name} opened {type(popup).__name__ if popup else 'nothing'}, "
                            f"expected the drum pop-up")
        if field.calendarWidget() is not None and field.calendarWidget().isVisible():
            failures.append(f"{name} showed Qt's own calendar")
        if popup is not None:
            popup.close()
            _pump(app)
    holder.close()
    return failures


def check_field_second_click_closes(app):
    """A second click on the field (e.g. its arrow strip), while its pop-up is open, must
    close the pop-up rather than reopen it. In real Qt, the outside press is delivered to the
    pop-up first (it holds the grab); unless it sets Qt.WA_NoMouseReplay, Qt then replays that
    same press to the field underneath, whose own mousePressEvent calls open_popup() again.
    QTest.mouseClick(field, ...) a second time bypasses that grab entirely and always reopens
    -- verified directly, unconditionally, on both the fixed and the unfixed code -- and the
    offscreen platform does not perform the cross-window replay either (verified directly: the
    field's mousePressEvent is never re-invoked, fixed or not), so this instead drives the
    pop-up the way Qt's grab would -- a press delivered straight to the pop-up, at the field's
    own screen position -- and checks its direct, observable effect: WA_NoMouseReplay is set
    exactly when that press lands on the field, which is the one thing standing between "closes"
    and "closes-then-reopens" once a real replay is in play. The full reopen/no-reopen behavior
    itself needs the native platform and a real pointer, like the rest of this file's manual-only
    items."""
    failures = []
    holder, field = _field(app, "31.01.2025")
    pos = QPoint(field.width() - 8, 15)
    QTest.mouseClick(field, Qt.LeftButton, pos=pos)
    _pump(app)
    popup = QApplication.activePopupWidget()
    if not isinstance(popup, jte._DateDrumPopup):
        failures.append(f"first click opened {type(popup).__name__ if popup else 'nothing'}, "
                        f"expected the drum pop-up")
        holder.close()
        return failures
    local_in_popup = popup.mapFromGlobal(field.mapToGlobal(pos))
    QTest.mousePress(popup, Qt.LeftButton, pos=local_in_popup)
    if not popup.testAttribute(Qt.WA_NoMouseReplay):
        failures.append("a press landing on the field's own rectangle did not set "
                        "WA_NoMouseReplay -- Qt would replay it to the field and reopen the "
                        "pop-up")
    _pump(app)
    if not _no_popup_open(app):
        failures.append("the pop-up is still open after the second click")
    if _show(field.date()) != "31.01.2025":
        failures.append(f"the second click changed the date to {_show(field.date())}")
    holder.close()
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


def _edit_dialog(win, row):
    return jte.EditDialog(win.model, row, win.settings.get_font(),
                          shortcuts=win.settings.get("shortcuts", {}),
                          target_culture=win.target_culture,
                          transl_cfg=win.settings.get("translation", {}), parent=win)


def check_real_pickers(app):
    failures = []
    widest_date = QDate(2088, 12, 28).toString(jte.DATE_FMT_QT)
    for theme in jte.THEMES:
        t = jte.THEMES[theme]
        for pt in REAL_FONT_PTS:
            win = _window(app, theme, pt)
            try:
                edit = _edit_dialog(win, 0)
                edit.show()
                _pump(app)
                for name, picker in (("filter bar date from", win.filter_panel.date_from),
                                     ("filter bar date to", win.filter_panel.date_to),
                                     ("Edit date", edit.date_edit)):
                    where = f"{theme} {name} at {pt}pt"
                    if not isinstance(picker, jte._DatePickerField):
                        failures.append(f"{where}: is a {type(picker).__name__}")
                        continue
                    image = picker.grab().toImage()
                    fill = QColor(image.pixel(3, image.height() // 2))
                    if abs(fill.red() - QColor(t["bg4"]).red()) + abs(fill.green() - QColor(t["bg4"]).green()) \
                            + abs(fill.blue() - QColor(t["bg4"]).blue()) > FILL_TOLERANCE:
                        failures.append(f"{where}: field fill {fill.name()}, expected {t['bg4']}")
                    needed = jte._width_for_text(picker, QFontMetrics(picker.font()), [widest_date])
                    if picker.width() < needed:
                        failures.append(f"{where}: {picker.width()}px wide, needs {needed}px")
                    popup = picker.open_popup()
                    _pump(app)
                    if popup.styleSheet().count(t["dlg_bg"]) != 1:
                        failures.append(f"{where}: the pop-up is not on the {theme} dialog surface")
                    popup.close()
                    _pump(app)
                edit.close()
            finally:
                # Loading the sample file normalizes its dates on a machine whose short-date format
                # differs, which marks the window modified and makes close() ask to discard.
                win.is_modified = False
                win.close()
                _pump(app)
    return failures


def check_edit_keeps_old_date(app):
    """An entry dated before 2000: open and cancel the pop-up, change only the status, Save -- the
    stored date must be unchanged (clamping the field would rewrite it)."""
    failures = []
    win = _window(app, "dark", 10)
    try:
        entry = win.model.get_entry(0)
        entry.modify_date = jte.format_date_for_storage(date(1998, 5, 5))
        stored = entry.modify_date
        edit = _edit_dialog(win, 0)
        edit.show()
        _pump(app)
        if _show(edit.date_edit.date()) != "05.05.1998":
            failures.append(f"the Edit dialog shows {_show(edit.date_edit.date())} for 05.05.1998")
        popup = edit.date_edit.open_popup()
        _pump(app)
        popup.close()
        _pump(app)
        edit.status_combo.setCurrentIndex((edit.status_combo.currentIndex() + 1)
                                          % edit.status_combo.count())
        edit._save()
        _pump(app)
        if entry.modify_date != stored:
            failures.append(f"Save rewrote the 1998 date {stored!r} to {entry.modify_date!r}")
    finally:
        win.is_modified = False
        win.close()
        _pump(app)
    return failures


CHECKS = [check_format_helpers, check_column_keys, check_column_wheel, check_column_clicks,
          check_column_drag, check_column_signal_and_values, check_column_paint,
          check_popup_columns, check_popup_day_clamp, check_popup_years,
          check_popup_confirm_and_cancel, check_popup_focus_keys, check_popup_placement,
          check_field_is_inert, check_field_opens, check_field_second_click_closes,
          check_real_pickers, check_edit_keeps_old_date]



@contextmanager
def _patched(name, value):
    real = getattr(jte, name)
    setattr(jte, name, value)
    try:
        yield
    finally:
        setattr(jte, name, real)


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")     # what main() does
    # The startup modals block forever with nobody to click them (see the offscreen-smoke-test pitfall).
    jte.QMessageBox.warning = staticmethod(lambda *a, **k: 0)
    jte.TranslatorNameDialog.exec = lambda self: 0
    failures = []
    with tempfile.TemporaryDirectory() as glyphs:
        with _patched("_glyph_cache_dir", lambda: Path(glyphs)):
            for check in CHECKS:
                try:
                    failures += check(app)
                except Exception as e:
                    failures.append(f"{check.__name__}: {type(e).__name__}: {e}")
    for f in failures:
        print("FAIL", f)
    print(f"{'FAILED' if failures else 'PASSED'}: {len(failures)} failure(s)")
    # Leave the folder first: Windows will not delete the working directory, and nothing may write
    # to the repo's.
    os.chdir(tempfile.gettempdir())
    shutil.rmtree(SCRATCH, ignore_errors=True)
    # Return, never os._exit(): see check_combobox.py -- a real MainWindow's teardown must run.
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
