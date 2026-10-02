"""Offscreen check for the Merge row compare pop-up (MergeCompareDialog) and its helpers.

Covers, first without a MainWindow:

  * merge_row_reason(): every phrase of the spec's table, including an unparseable date and a tie;
  * merge_diff_html(): identical texts untinted, a changed word tinted on both sides, an inserted
    word only on the incoming side, <, > and & escaped, newlines kept as <br>, double spaces kept;

then through a real MainWindow, run from a throwaway folder with the startup modals patched (the
app derives its settings file and backup root from the working directory / argv[0], so the real
ones are never touched), on a 1920 x 1080 offscreen screen:

  * the MergeConflictDialog row accessors and the shared tint rules;
  * the pop-up's header, panes, metadata, buttons, Back/Forward, auto-resolve;
  * keys, opening by double-click, and cleanup after Close;
  * sizes in both themes at 10 and 14 pt.

Run:  python tests/check_merge_compare.py      (exit code 0 = all passed)
"""

import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRATCH = Path(tempfile.mkdtemp(prefix="xte_merge_compare_"))
# A 1920 x 1080 offscreen screen: the default 800 px one, with offscreen text drawn as boxes wider
# than real glyphs, would squeeze the dialogs. Qt splits the platform string on ':', so the config
# path is relative: the script runs from SCRATCH.
(SCRATCH / "screen.json").write_text(json.dumps({"screens": [{
    "name": "check", "x": 0, "y": 0, "width": 1920, "height": 1080,
    "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}), encoding="utf-8")
os.chdir(SCRATCH)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=screen.json"
sys.argv[0] = str(SCRATCH / "check_merge_compare.py")
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel
from shiboken6 import isValid

import json_translation_editor as jte

D_OLD = jte.format_date_for_storage(date(2025, 2, 3))
D_NEW = jte.format_date_for_storage(date(2026, 9, 12))
TINT = "#aabbcc"
SPAN = f'<span style="background-color: {TINT}">'


def check(failures, label, ok, detail=""):
    if not ok:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def _e(name, text, translator="x", status="Review", when=D_OLD):
    return jte.StringEntry(name=name, translator=translator, status=status, modify_date=when,
                           text=text)


def check_reason(failures):
    cases = [
        ("addition", None, _e("A", "a"), "only in the incoming file"),
        ("deletion", _e("A", "a"), None, "only in the open file"),
        ("conflict", _e("Lane", "Lane", when=D_NEW), _e("Lane", "Josla", when=D_OLD), "open is untranslated"),
        ("conflict", _e("Lane", "Josla", when=D_OLD), _e("Lane", "Lane", when=D_NEW), "incoming is untranslated"),
        ("conflict", _e("A", "a", when=""), _e("A", "b", when=D_NEW), "date missing"),
        ("conflict", _e("A", "a", when="not a date"), _e("A", "b", when=D_NEW), "date missing"),
        ("conflict", _e("A", "a", when=D_OLD), _e("A", "b", when=D_NEW), "incoming is newer"),
        ("conflict", _e("A", "a", when=D_NEW), _e("A", "b", when=D_OLD), "open is newer"),
        ("conflict", _e("A", "a", when=D_OLD), _e("A", "b", when=D_OLD), "same date"),
    ]
    for kind, open_entry, incoming_entry, want in cases:
        got = jte.merge_row_reason(kind, open_entry, incoming_entry)
        check(failures, f"reason for {want!r}", got == want, repr(got))


def check_diff(failures):
    wrap = '<div style="white-space: pre-wrap">'
    open_html, incoming_html = jte.merge_diff_html("Joslas platums", "Joslas platums", TINT)
    check(failures, "identical texts are not tinted", SPAN not in open_html and SPAN not in incoming_html)
    check(failures, "pane HTML is a pre-wrap div", open_html == f"{wrap}Joslas platums</div>", open_html)

    open_html, incoming_html = jte.merge_diff_html("ir pārāq mazs", "ir nepietiekams mazs", TINT)
    check(failures, "changed word tinted on the open side", f"{SPAN}pārāq</span>" in open_html, open_html)
    check(failures, "changed word tinted on the incoming side",
          f"{SPAN}nepietiekams</span>" in incoming_html, incoming_html)
    check(failures, "equal words stay plain", open_html.startswith(f"{wrap}ir "), open_html)

    open_html, incoming_html = jte.merge_diff_html("a b", "a new b", TINT)
    check(failures, "an insertion is tinted on the incoming side only",
          SPAN in incoming_html and "new" in incoming_html and SPAN not in open_html,
          f"{open_html} | {incoming_html}")

    open_html, _ = jte.merge_diff_html("x < y & z > w", "x < y & z > v", TINT)
    check(failures, "<, > and & are escaped", "x &lt; y &amp; z &gt; " in open_html, open_html)

    open_html, _ = jte.merge_diff_html("line1\nline2", "line1\nline3", TINT)
    check(failures, "a newline becomes <br>", "line1<br>" in open_html, open_html)

    open_html, _ = jte.merge_diff_html("a  b", "a  c", TINT)
    check(failures, "double spaces are kept", f"{wrap}a  " in open_html, open_html)

    check(failures, "_blend_hex mixes at alpha", jte._blend_hex("#ffffff", "#000000", 0.5) == "#808080",
          jte._blend_hex("#ffffff", "#000000", 0.5))


@contextmanager
def _isolated_glyph_dir():
    real = jte._glyph_cache_dir
    with tempfile.TemporaryDirectory() as tmp:
        jte._glyph_cache_dir = lambda: Path(tmp) / "glyphs"
        try:
            yield
        finally:
            jte._glyph_cache_dir = real


def _fixture():
    """Row 0 addition; rows 1-2 conflicts (row 1: incoming newer, row 2: open untranslated);
    row 3 deletion. Both conflicts default to Keep incoming."""
    additions = [_e("Add me", "Pievieno mani", "Pēteris", "New")]
    conflicts = [
        (_e("Lane width is too small", "Joslas platums ir pārāq mazs", "Jane", "Review", D_OLD),
         _e("Lane width is too small", "Joslas platums ir nepietiekams", "Pēteris", "Complete", D_NEW)),
        (_e("Save", "Save", "Jane", "New", D_NEW),
         _e("Save", "Saglabāt", "Jane", "New", D_OLD)),
    ]
    deletions = [_e("Old string", "Vecā virkne")]
    return additions, conflicts, deletions


def _set_look(win, theme, pt):
    win.settings.set("font_size", pt)
    win._apply_app_font()
    win._set_theme(theme)
    QApplication.processEvents()


def _merge_dialog(win):
    additions, conflicts, deletions = _fixture()
    mdlg = jte.MergeConflictDialog(additions, conflicts, deletions, parent=win)
    mdlg.show()
    QApplication.processEvents()
    return mdlg, (additions, conflicts, deletions)


def _close(dlg):
    """Close a WA_DeleteOnClose dialog and let its deferred deletion run."""
    if isValid(dlg):
        dlg.close()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()


def check_row_accessors(failures, win):
    _set_look(win, "dark", 10)
    mdlg, (additions, conflicts, deletions) = _merge_dialog(win)
    check(failures, "row_count", mdlg.row_count() == 4, str(mdlg.row_count()))
    info = mdlg.row_info(0)
    check(failures, "row 0 is the addition",
          info.kind == "addition" and info.open_entry is None and info.incoming_entry is additions[0])
    info = mdlg.row_info(2)
    check(failures, "row 2 is the second conflict",
          info.kind == "conflict" and info.open_entry is conflicts[1][0]
          and info.incoming_entry is conflicts[1][1])
    info = mdlg.row_info(3)
    check(failures, "row 3 is the deletion",
          info.kind == "deletion" and info.open_entry is deletions[0] and info.incoming_entry is None)
    check(failures, "row_info's combo is the table's",
          mdlg.row_info(1).combo is mdlg._table.cellWidget(1, mdlg.COL_RESOLUTION))

    mdlg._table.selectAll()
    mdlg.show_row(2)
    rows = sorted({i.row() for i in mdlg._table.selectionModel().selectedRows()})
    check(failures, "show_row selects that row alone", rows == [2], str(rows))

    check(failures, "auto-resolve off", not mdlg.is_auto_resolving())
    mdlg._auto_chk.setChecked(True)
    check(failures, "auto-resolve on", mdlg.is_auto_resolving())
    mdlg._auto_chk.setChecked(False)

    theme, is_dark, pt = mdlg.theme_and_font()
    check(failures, "theme_and_font", theme is mdlg._theme and is_dark and pt == 10, repr((is_dark, pt)))
    check(failures, "shortcut defaults", mdlg.shortcuts()["edit_prev"] == "Alt+Left")
    saved = dict(win.settings.data.get("shortcuts", {}))
    win.settings.data["shortcuts"] = {**saved, "edit_next": "Ctrl+J"}
    check(failures, "shortcuts follow settings", mdlg.shortcuts()["edit_next"] == "Ctrl+J")
    win.settings.data["shortcuts"] = saved

    tint_qss = jte._merge_tint_qss(theme, is_dark, max(8, pt - 1))
    check(failures, "the toolbar uses the shared tint rules", tint_qss in mdlg.styleSheet())
    check(failures, "the shared tint rules style the current choice", '[current="true"]' in tint_qss)
    _close(mdlg)


def _compare(mdlg, row):
    dlg = jte.MergeCompareDialog(mdlg, row)
    dlg.show()
    QApplication.processEvents()
    return dlg


def _has_color(widget, hex_color, tolerance=12):
    """True if any pixel of *widget* is within *tolerance* per channel of *hex_color*
    (offscreen text is drawn as solid boxes in the text colour)."""
    target = QColor(hex_color)
    image = widget.grab().toImage()
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if (abs(c.red() - target.red()) <= tolerance and abs(c.green() - target.green()) <= tolerance
                    and abs(c.blue() - target.blue()) <= tolerance):
                return True
    return False


def _selected_rows(mdlg):
    return sorted({i.row() for i in mdlg._table.selectionModel().selectedRows()})


def check_show_row_single_selection(failures, win):
    """Fix A: MergeCompareDialog's Back/Forward keys fire the user-configurable edit_prev/
    edit_next slots. Under ExtendedSelection, QTableView.selectRow() with no originating event
    derives its selection command from whatever QGuiApplication.keyboardModifiers() reports at
    the moment it runs -- Ctrl/Shift ADD to the selection instead of replacing it. Rebind
    edit_next to a Ctrl combo and hold Ctrl while stepping twice: the Merge table's selection
    must still be exactly the row the pop-up landed on, not the accumulated set of rows visited."""
    _set_look(win, "dark", 10)
    mdlg, _ = _merge_dialog(win)
    saved = dict(win.settings.data.get("shortcuts", {}))
    win.settings.data["shortcuts"] = {**saved, "edit_next": "Ctrl+J"}
    try:
        dlg = _compare(mdlg, 0)
        QTest.keyClick(dlg.focusWidget(), Qt.Key_J, Qt.ControlModifier)
        QTest.keyClick(dlg.focusWidget(), Qt.Key_J, Qt.ControlModifier)
        QApplication.processEvents()
        rows = _selected_rows(mdlg)
        check(failures, "show_row under a held Ctrl modifier selects exactly one row",
              rows == [2], str(rows))
        _close(dlg)
    finally:
        win.settings.data["shortcuts"] = saved
    _close(mdlg)


def check_last_row_focus_with_auto_resolve(failures, win):
    """Fix B: with auto-resolve ticked, a conflict as the last row disables both choice buttons.
    Enter-stepping must never land on Close -- one more Enter would close the pop-up, returning
    focus to the Merge table, where the very next Enter triggers Apply & Close."""
    _set_look(win, "dark", 10)
    additions, conflicts, _ = _fixture()
    mdlg = jte.MergeConflictDialog(additions, conflicts, [], parent=win)
    mdlg.show()
    QApplication.processEvents()
    mdlg._auto_chk.setChecked(True)
    last_row = mdlg.row_count() - 1
    dlg = _compare(mdlg, last_row)
    check(failures, "last row with auto-resolve focuses Back, not Close",
          dlg.focusWidget() is dlg._btn_back, repr(dlg.focusWidget()))
    _close(dlg)
    _close(mdlg)


def check_content(failures, win):
    _set_look(win, "dark", 10)
    mdlg, (additions, conflicts, deletions) = _merge_dialog(win)
    t = mdlg._theme

    dlg = _compare(mdlg, 1)
    check(failures, "conflict header kind", dlg._kind_lbl.text() == "⇄ Conflict", dlg._kind_lbl.text())
    check(failures, "conflict header reason", dlg._reason_lbl.text() == "· incoming is newer",
          dlg._reason_lbl.text())
    check(failures, "position", dlg._pos_lbl.text() == "Row 2 of 4", dlg._pos_lbl.text())
    check(failures, "source pane", dlg._source_pane.toPlainText() == "Lane width is too small")
    check(failures, "open pane", dlg._open_pane.toPlainText() == conflicts[0][0].text,
          dlg._open_pane.toPlainText())
    check(failures, "incoming pane", dlg._incoming_pane.toPlainText() == conflicts[0][1].text,
          dlg._incoming_pane.toPlainText())
    tint = jte._blend_hex(t["dlg_count_warn"], t["bg2"], jte.MergeCompareDialog._DIFF_TINT_ALPHA)
    check(failures, "diff tint in the open pane", tint in dlg._open_pane.toHtml().lower())
    for pane in dlg._panes:
        before = pane.toPlainText()
        QTest.keyClicks(pane, "zz")
        check(failures, "pane is read-only", pane.isReadOnly() and pane.toPlainText() == before)
    translator = dlg._meta_labels["Translator"]
    check(failures, "translator values", (translator[0].text(), translator[1].text()) == ("Jane", "Pēteris"))
    check(failures, "differing translator marked", translator[0].property("differs") is True
          and translator[1].property("differs") is True)
    check(failures, "differing value drawn in text_warn", _has_color(translator[1], t["text_warn"]))
    length = dlg._meta_labels["Length"]
    check(failures, "length",
          length[0].text() == str(len(conflicts[0][0].text))
          and length[1].text() == str(len(conflicts[0][1].text)), length[0].text())
    check(failures, "conflict buttons",
          [b.text() for b in dlg._choice_btns] == ["Keep open", "✓ Keep incoming"],
          repr([b.text() for b in dlg._choice_btns]))
    check(failures, "conflict buttons tinted warn", all(b.property("tint") == "warn" for b in dlg._choice_btns))
    check(failures, "current choice marked", dlg._choice_btns[1].property("current") == "true"
          and dlg._choice_btns[0].property("current") == "false")
    check(failures, "tooltip names the key", dlg._choice_btns[0].toolTip() == "Keep open  [Alt+1]",
          dlg._choice_btns[0].toolTip())
    check(failures, "Back/Forward in the middle", dlg._btn_back.isEnabled() and dlg._btn_forward.isEnabled())
    check(failures, "focus on the current choice", dlg.focusWidget() is dlg._choice_btns[1],
          repr(dlg.focusWidget()))
    check(failures, "table follows the pop-up", _selected_rows(mdlg) == [1], str(_selected_rows(mdlg)))
    _close(dlg)

    dlg = _compare(mdlg, 2)
    same = dlg._meta_labels["Translator"]
    check(failures, "equal values not marked", same[0].property("differs") is False)
    check(failures, "equal value not drawn in text_warn", not _has_color(same[0], t["text_warn"]))
    check(failures, "untranslated reason", dlg._reason_lbl.text() == "· open is untranslated",
          dlg._reason_lbl.text())
    _close(dlg)

    dlg = _compare(mdlg, 0)
    check(failures, "addition header", dlg._kind_lbl.text() == "+ Addition"
          and dlg._reason_lbl.text() == "· only in the incoming file")
    check(failures, "addition open placeholder", dlg._open_pane.toPlainText() == "Not in the open file",
          dlg._open_pane.toPlainText())
    check(failures, "addition incoming pane", dlg._incoming_pane.toPlainText() == "Pievieno mani")
    missing = dlg._meta_labels["Translator"]
    check(failures, "missing side shows a dash", missing[0].text() == "—" and missing[1].text() == "Pēteris")
    check(failures, "missing side not marked", missing[1].property("differs") is False)
    check(failures, "addition buttons", [b.text() for b in dlg._choice_btns] == ["✓ Accept", "Reject"])
    check(failures, "Back disabled on the first row", not dlg._btn_back.isEnabled())
    _close(dlg)

    dlg = _compare(mdlg, 3)
    check(failures, "deletion incoming placeholder",
          dlg._incoming_pane.toPlainText() == "Not in the incoming file")
    check(failures, "deletion buttons", [b.text() for b in dlg._choice_btns] == ["✓ Keep", "Delete"])
    check(failures, "Forward disabled on the last row", not dlg._btn_forward.isEnabled())
    _close(dlg)

    mdlg._auto_chk.setChecked(True)
    dlg = _compare(mdlg, 1)
    check(failures, "auto-resolve disables conflict buttons",
          not any(b.isEnabled() for b in dlg._choice_btns))
    check(failures, "auto-resolve named in the header", dlg._reason_lbl.text().endswith("· auto-resolved"),
          dlg._reason_lbl.text())
    check(failures, "auto-resolve focus goes to Forward", dlg.focusWidget() is dlg._btn_forward)
    _close(dlg)
    mdlg._auto_chk.setChecked(False)

    dlg = _compare(mdlg, 1)
    full = jte.MergeConflictDialog._TINT_ALPHA_DARK["dlg_count_warn"]
    faint = jte.MergeConflictDialog._TINT_ALPHA_DARK_FAINT["dlg_count_warn"]
    alpha = mdlg._table.item(1, mdlg.COL_SOURCE).background().color().alpha()
    check(failures, "row 1 starts full-strength", alpha == full, str(alpha))
    dlg._choice_btns[0].click()
    QApplication.processEvents()
    check(failures, "button sets the combo", mdlg.row_info(1).combo.currentText() == "Keep open")
    alpha = mdlg._table.item(1, mdlg.COL_SOURCE).background().color().alpha()
    check(failures, "row re-tinted", alpha == faint, str(alpha))
    check(failures, "button advances", dlg._row == 2, str(dlg._row))
    check(failures, "table selection follows", _selected_rows(mdlg) == [2], str(_selected_rows(mdlg)))
    dlg._btn_back.click()
    check(failures, "Back returns", dlg._row == 1 and dlg._choice_btns[0].text() == "✓ Keep open")
    dlg._btn_forward.click()
    dlg._btn_forward.click()
    check(failures, "Forward to the last row", dlg._row == 3)
    dlg._choice_btns[1].click()
    check(failures, "last row: combo set", mdlg.row_info(3).combo.currentText() == "Delete")
    check(failures, "last row: stays", dlg._row == 3 and dlg._choice_btns[1].text() == "✓ Delete")
    _close(dlg)
    _close(mdlg)


def _key(widget, key, modifier=Qt.NoModifier):
    QTest.keyClick(widget, key, modifier)
    QApplication.processEvents()


def _is_closed(dlg):
    return not isValid(dlg) or not dlg.isVisible()


def check_keys_and_opening(failures, win):
    _set_look(win, "dark", 10)
    mdlg, _ = _merge_dialog(win)

    def combo(row):
        return mdlg.row_info(row).combo.currentText()


    dlg = _compare(mdlg, 1)
    # The keys are QShortcuts, which Qt fires only in the active window.
    check(failures, "pop-up is the active window", QApplication.activeWindow() is dlg,
          repr(QApplication.activeWindow()))
    _key(dlg.focusWidget(), Qt.Key_Right, Qt.AltModifier)
    check(failures, "Alt+Right: next row", dlg._row == 2, str(dlg._row))
    _key(dlg.focusWidget(), Qt.Key_Left, Qt.AltModifier)
    check(failures, "Alt+Left: previous row", dlg._row == 1, str(dlg._row))
    _key(dlg._open_pane, Qt.Key_Right, Qt.AltModifier)
    check(failures, "keys work from a text pane", dlg._row == 2, str(dlg._row))
    _key(dlg._open_pane, Qt.Key_Left, Qt.AltModifier)
    _key(dlg.focusWidget(), Qt.Key_1, Qt.AltModifier)
    check(failures, "Alt+1: first choice", combo(1) == "Keep open" and dlg._row == 2, combo(1))
    _key(dlg.focusWidget(), Qt.Key_2, Qt.AltModifier)
    check(failures, "Alt+2: second choice", combo(2) == "Keep incoming" and dlg._row == 3, combo(2))

    dlg._step(-2)
    focus = dlg.focusWidget()
    check(failures, "focus on the ✓ button", focus is dlg._choice_btns[0], repr(focus))
    _key(focus, Qt.Key_Return)
    check(failures, "Enter on ✓ advances", dlg._row == 2, str(dlg._row))
    check(failures, "Enter on ✓ keeps the choice", combo(1) == "Keep open", combo(1))
    dlg._open_pane.setFocus()
    QApplication.processEvents()
    check(failures, "a pane can take focus", dlg._open_pane.hasFocus())
    _key(dlg._open_pane, Qt.Key_Return)
    check(failures, "Enter from a pane closes", _is_closed(dlg))
    _close(dlg)

    dlg = _compare(mdlg, 1)
    _key(dlg.focusWidget(), Qt.Key_Escape)
    check(failures, "Escape closes", _is_closed(dlg))
    _close(dlg)

    opened = []
    real_exec = jte.MergeCompareDialog.exec

    def fake_exec(d):
        opened.append(d._row)
        d.deleteLater()
        return 0

    jte.MergeCompareDialog.exec = fake_exec
    try:
        table = mdlg._table
        rect = table.visualRect(table.model().index(2, mdlg.COL_SOURCE))
        # A real double-click is press, release, double-click, release; QTest.mouseDClick() alone
        # synthesizes only the bare double-click, with no leading press to prime pressedIndex.
        QTest.mouseClick(table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
        QTest.mouseDClick(table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
        header = table.verticalHeader()
        y = header.sectionViewportPosition(3) + header.sectionSize(3) // 2
        QTest.mouseDClick(header.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(header.width() // 2, y))
        QApplication.processEvents()
    finally:
        jte.MergeCompareDialog.exec = real_exec
    check(failures, "double-click opens on that row (cell, then row header)", opened == [2, 3], repr(opened))
    texts = [label.text() for label in mdlg.findChildren(QLabel)]
    check(failures, "status bar hint", any(text.endswith("Double-click a row to compare.") for text in texts))

    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()
    baseline = len(QApplication.allWidgets())
    _close(_compare(mdlg, 1))
    after = len(QApplication.allWidgets())
    check(failures, "Close frees every widget", after == baseline, f"{baseline} -> {after}")
    _close(mdlg)


def check_sizes(failures, win):
    for theme in ("dark", "light"):
        for pt in (10, 14):
            _set_look(win, theme, pt)
            mdlg, _ = _merge_dialog(win)
            for row in range(mdlg.row_count()):
                dlg = _compare(mdlg, row)
                tag = f"{theme} {pt}pt row {row}"
                for btn in (dlg._btn_back, dlg._btn_forward, *dlg._choice_btns, dlg._btn_close):
                    check(failures, f"{tag}: {btn.text()!r} fits", btn.width() >= btn.sizeHint().width(),
                          f"{btn.width()} < {btn.sizeHint().width()}")
                for lbl in (dlg._kind_lbl, dlg._reason_lbl, dlg._pos_lbl):
                    check(failures, f"{tag}: header {lbl.text()!r} fits",
                          lbl.width() >= lbl.sizeHint().width(), f"{lbl.width()} < {lbl.sizeHint().width()}")
                for pane in dlg._panes:
                    lines = 4 * pane.fontMetrics().lineSpacing()
                    check(failures, f"{tag}: pane at least 4 lines", pane.height() >= lines,
                          f"{pane.height()} < {lines}")
                check(failures, f"{tag}: at least the minimum size",
                      dlg.width() >= 680 and dlg.height() >= 420, f"{dlg.width()} x {dlg.height()}")
                wanted = max(dlg.minimumWidth(), dlg.sizeHint().width())
                check(failures, f"{tag}: opens at its size hint", abs(dlg.width() - wanted) <= 2,
                      f"{dlg.width()} vs {wanted}")
                size = dlg.size()
                dlg._step(1 if row == 0 else -1)
                QApplication.processEvents()
                check(failures, f"{tag}: moving to another row keeps the size", dlg.size() == size,
                      f"{size} -> {dlg.size()}")
                _close(dlg)
            _close(mdlg)
    _set_look(win, "dark", 10)


PURE_STEPS = [check_reason, check_diff]
def check_sync_mode(failures, win):
    sync_dlg = jte.MergeConflictDialog([_e("b", "b")], [], [_e("x", "lama")], parent=win,
                                       sync_mode=True)
    check(failures, "sync mode has no conflicts column",
          not hasattr(sync_dlg, "_auto_chk") or sync_dlg._auto_chk.isHidden(), "auto-resolve shown")
    check(failures, "sync mode names the reference file", sync_dlg.other_side_name() == "reference",
          repr(sync_dlg.other_side_name()))
    sync_dlg.reject()


WINDOW_STEPS = [check_row_accessors, check_show_row_single_selection,
                check_last_row_focus_with_auto_resolve, check_content, check_keys_and_opening,
                check_sizes, check_sync_mode]


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    failures = []
    for step in PURE_STEPS:
        try:
            step(failures)
        except Exception as e:
            failures.append(f"{step.__name__}: {type(e).__name__}: {e}")
    # The startup modals block forever with nobody to click them (see the offscreen-smoke-test pitfall).
    jte.QMessageBox.warning = staticmethod(lambda *a, **k: 0)
    jte.TranslatorNameDialog.exec = lambda self: 0
    with _isolated_glyph_dir():
        win = jte.MainWindow()
        win.settings.data.setdefault("backup", {})["enabled"] = False
        win.show()
        app.processEvents()   # runs the pending startup prompts while the patches are active
        for step in WINDOW_STEPS:
            try:
                step(failures, win)
            except Exception as e:
                failures.append(f"{step.__name__}: {type(e).__name__}: {e}")
        win.is_modified = False
        win.close()
        app.processEvents()
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
