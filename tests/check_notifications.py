"""Offscreen check for the info bar's message queue, levels and message history
(MainWindow._show_message(), MessageHistoryPopup):

  * queue: a lone message shows at once and clears after its time; a burst plays in order, the
    waiting ones with shortened turns and the last one with its full time; a message arriving
    after the current one has been up past the minimum takes over at once; "+N" while messages
    wait; the fallback to "Unsaved changes"; duplicates not queued but in the history; the queue
    and history limits; ms <= 0 and an unknown level;
  * levels: the label's colour per level in both themes, recoloured by a theme switch; escaping
    and the tooltip.
  * button and pop-up: the icon's lines and dot; the button's place and tooltip; the unread dot
    (none for info, amber, red, red kept, cleared on open); the pop-up's placeholder, dlg_bg
    surface, newest-first order with times, escaping, place above the button inside the screen,
    width limits, Escape, a second press on the button (no replay), widgets freed; both themes at
    10 and 14 pt with a long history that scrolls.
  * call sites: opening a file with a legacy and an unparseable date gives separate Loaded, Dates
    normalized and Dates unrecognized messages (both warnings), then Backup; a merge with date
    problems gives the same split; no message holds a "  |  " join.
  * file messages: _file_label(); Loaded, Saved (after a Properties-style version change),
    Autosaved, Closed, Restored and Restored and reloaded name the header version, and a file
    without one reads "(no version)".
  * settings: a missing settings file gives a warning; a damaged one an error plus a warning
    (restored from the backup, or defaults in use); an unreadable one an error; a valid one
    nothing. At startup these play after the recovery dialog, which is still shown, and before
    the translator message.

A real MainWindow from a throwaway folder on a 1920 x 1080 offscreen screen, with the startup
modals patched and the glyph cache isolated. Timing tests patch NOTIFY_MIN_TURN_MS to 100 ms.

Run:  python tests/check_notifications.py      (exit code 0 = all passed)
"""

import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRATCH = Path(tempfile.mkdtemp(prefix="xte_notifications_"))
# A 1920 x 1080 offscreen screen: on the default 800 x 600 one the 1280 x 760 main window, and
# with it the history button, would reach below the screen. Qt splits the platform string on
# ':', so the config path is relative: the script runs from SCRATCH.
(SCRATCH / "screen.json").write_text(json.dumps({"screens": [{
    "name": "check", "x": 0, "y": 0, "width": 1920, "height": 1080,
    "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}), encoding="utf-8")
os.chdir(SCRATCH)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=screen.json"
sys.argv[0] = str(SCRATCH / "check_notifications.py")
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

import json_translation_editor as jte


def check(failures, label, ok, detail=""):
    if not ok:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def _reset(win):
    """Empty the notifier (the startup prompt has already queued a message) and clear the mod
    status, so every step starts from a quiet info bar."""
    win._notify_timer.stop()
    win._notice_current = None
    win._notice_queue.clear()
    win._notice_history.clear()
    win.is_modified = False
    win._update_title()
    win._history_unseen_level = ""
    win._refresh_history_icon()


def _current(win):
    return win._notice_current.text if win._notice_current is not None else None


def _close(popup):
    """Close a WA_DeleteOnClose pop-up and let its deferred deletion run."""
    if isValid(popup):
        popup.close()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()


def _set_look(win, theme, pt):
    win.settings.set("font_size", pt)
    win._apply_app_font()
    win._set_theme(theme)
    QApplication.processEvents()


LEGACY_XML = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<TRNExportImportModel Culture="lv-LV" DisplayLanguage="Latviešu" Version="4.1.1140">\n'
    '  <resources>\n'
    '    <string name="A" translator="x" status="New" modifyDate="{good}" istablet="false">A</string>\n'
    '    <string name="B" translator="x" status="New" modifyDate="{legacy}" istablet="false">B</string>\n'
    '    <string name="C" translator="x" status="New" modifyDate="foo" istablet="false">C</string>\n'
    '  </resources>\n'
    '</TRNExportImportModel>\n')


def check_queue(failures, win):
    label = win._dynamic_label
    real_min = jte.NOTIFY_MIN_TURN_MS
    jte.NOTIFY_MIN_TURN_MS = 100
    try:
        _reset(win)
        win._show_message("lone", 200)
        check(failures, "lone: shown at once", _current(win) == "lone", repr(_current(win)))
        QTest.qWait(300)
        check(failures, "lone: cleared after its time", _current(win) is None, repr(_current(win)))
        check(failures, "lone: label empty afterwards", label.text() == "", repr(label.text()))

        _reset(win)
        for name in ("A", "B", "C"):
            win._show_message(name, 400)
        check(failures, "burst: first shown at once", _current(win) == "A", repr(_current(win)))
        check(failures, "burst: two waiting", len(win._notice_queue) == 2, str(len(win._notice_queue)))
        check(failures, "burst: +2 shown", "+2" in label.text(), repr(label.text()))
        QTest.qWait(150)   # A was cut to the 100 ms minimum
        check(failures, "burst: second after the minimum", _current(win) == "B", repr(_current(win)))
        check(failures, "burst: +1 shown", "+1" in label.text(), repr(label.text()))
        QTest.qWait(150)   # t = 300: B's shortened 100 ms turn ended at ~200
        check(failures, "burst: third after a shortened turn", _current(win) == "C", repr(_current(win)))
        check(failures, "burst: no count on the last", "+" not in label.text(), repr(label.text()))
        QTest.qWait(150)   # t = 450: C, the last, has its full 400 ms, until ~600
        check(failures, "burst: last keeps its full time", _current(win) == "C", repr(_current(win)))
        QTest.qWait(300)   # t = 750
        check(failures, "burst: cleared at the end", _current(win) is None, repr(_current(win)))

        _reset(win)
        win._show_message("old", 2000)
        QTest.qWait(200)   # past the 100 ms minimum
        win._show_message("new", 300)
        QTest.qWait(40)
        check(failures, "takeover once the minimum has passed", _current(win) == "new", repr(_current(win)))

        _reset(win)
        win.is_modified = True
        win._update_title()
        win._show_message("brief", 100)
        QTest.qWait(250)
        check(failures, "fallback to the mod status", label.text() == "Unsaved changes", repr(label.text()))
    finally:
        jte.NOTIFY_MIN_TURN_MS = real_min
        _reset(win)


def check_guards(failures, win):
    _reset(win)
    win._show_message("same", 5000)
    win._show_message("same", 5000)
    check(failures, "duplicate of the current: not queued", len(win._notice_queue) == 0)
    check(failures, "duplicate of the current: in the history", len(win._notice_history) == 2)
    win._show_message("other", 5000)
    win._show_message("other", 5000)
    check(failures, "duplicate of the last waiting: not queued", len(win._notice_queue) == 1)
    win._show_message("same", 5000)
    check(failures, "duplicate of the current behind a waiting one: not queued",
          len(win._notice_queue) == 1)
    win._show_message("same", 5000, "warning")
    check(failures, "same text at another level: queued", len(win._notice_queue) == 2)

    _reset(win)
    for i in range(7):
        win._show_message(f"m{i}", 5000)
    waiting = [n.text for n in win._notice_queue]
    check(failures, "limit: five waiting", len(waiting) == jte.NOTIFY_QUEUE_MAX == 5, repr(waiting))
    check(failures, "limit: the oldest waiting one dropped",
          waiting == ["m2", "m3", "m4", "m5", "m6"], repr(waiting))
    check(failures, "limit: all seven in the history", len(win._notice_history) == 7)

    _reset(win)
    for i in range(jte.NOTIFY_HISTORY_MAX + 5):
        win._show_message(f"h{i}", 5000)
    history = [n.text for n in win._notice_history]
    check(failures, "history: stops at its maximum", len(history) == jte.NOTIFY_HISTORY_MAX == 200,
          str(len(history)))
    check(failures, "history: keeps the newest", (history[0], history[-1]) == ("h5", "h204"),
          repr((history[0], history[-1])))

    _reset(win)
    win._show_message("zero", 0)
    check(failures, "ms 0 treated as the default",
          win._notify_timer.interval() == jte.NOTIFY_DEFAULT_MS == 4000,
          str(win._notify_timer.interval()))
    win._show_message("bogus level", 5000, "bogus")
    check(failures, "unknown level treated as info", win._notice_queue[-1].level == "info",
          win._notice_queue[-1].level)
    _reset(win)


def check_levels(failures, win):
    label = win._dynamic_label
    for theme in ("dark", "light"):
        win._set_theme(theme)
        t = jte.THEMES[theme]
        for level, key in (("info", "fg_dim"), ("warning", "text_warn"), ("error", "text_bad")):
            _reset(win)
            win._show_message(f"{level} text", 5000, level)
            check(failures, f"{theme} {level}: label colour", t[key] in label.styleSheet(),
                  label.styleSheet())
    win._set_theme("dark")
    _reset(win)
    win._show_message("warn", 5000, "warning")
    win._set_theme("light")
    check(failures, "theme switch recolours a shown warning",
          jte.THEMES["light"]["text_warn"] in label.styleSheet(), label.styleSheet())
    win._set_theme("dark")

    _reset(win)
    raw = "R&D <x>  done"
    win._show_message(raw, 5000)
    check(failures, "text escaped in the label", "R&amp;D &lt;x&gt;" in label.text(), repr(label.text()))
    check(failures, "tooltip is the plain text", label.toolTip() == raw, repr(label.toolTip()))
    _reset(win)
    check(failures, "tooltip cleared with the message", label.toolTip() == "", repr(label.toolTip()))


def check_icon(failures):
    plain = jte._render_history_icon("#ffffff", 64)
    dotted = jte._render_history_icon("#ffffff", 64, "#ff0000")
    check(failures, "icon: lines drawn", plain.pixelColor(32, 32).alpha() > 200,
          str(plain.pixelColor(32, 32).alpha()))
    check(failures, "icon: no dot by default", plain.pixelColor(52, 12).alpha() == 0,
          str(plain.pixelColor(52, 12).alpha()))
    dot = dotted.pixelColor(52, 12)
    check(failures, "icon: dot in its colour", (dot.red(), dot.green(), dot.blue(), dot.alpha())
          == (255, 0, 0, 255), dot.name())


def check_button(failures, win):
    btn = win._history_btn
    check(failures, "button: tooltip", btn.toolTip() == "Message history", repr(btn.toolTip()))
    check(failures, "button: accessible name", btn.accessibleName() == "Message history",
          repr(btn.accessibleName()))
    check(failures, "button: between the message and the language",
          win._dynamic_label.geometry().right() < btn.geometry().left()
          < win._sb_lang_label.geometry().left(),
          f"{win._dynamic_label.geometry()} {btn.geometry()} {win._sb_lang_label.geometry()}")

    _reset(win)
    QTest.mouseClick(btn, Qt.LeftButton)
    popup = QApplication.activePopupWidget()
    if not isinstance(popup, jte.MessageHistoryPopup):
        found = btn.findChildren(jte.MessageHistoryPopup)
        popup = found[0] if found else None
    check(failures, "button: a click opens the history",
          isinstance(popup, jte.MessageHistoryPopup), repr(popup))
    _close(popup)
    _reset(win)

    win._show_message("info", 5000)
    check(failures, "dot: none for info", win._history_unseen_level == "")
    win._show_message("warn", 5000, "warning")
    check(failures, "dot: amber for a warning", win._history_unseen_level == "warning")
    win._show_message("err", 5000, "error")
    check(failures, "dot: red for an error", win._history_unseen_level == "error")
    win._show_message("warn 2", 5000, "warning")
    check(failures, "dot: a warning after an error keeps red", win._history_unseen_level == "error")
    popup = win._open_message_history()
    check(failures, "dot: opening the history clears it", win._history_unseen_level == "")
    _close(popup)
    _reset(win)


def check_popup(failures, win):
    btn = win._history_btn
    _reset(win)
    popup = win._open_message_history()
    check(failures, "empty: placeholder", "No messages yet" in popup.browser.toPlainText(),
          repr(popup.browser.toPlainText()))
    image = popup.grab().toImage()
    corner = image.pixelColor(image.width() - 8, image.height() - 8).name()
    check(failures, "surface is dlg_bg", corner == win._get_theme()["dlg_bg"].lower(), corner)
    _close(popup)

    win._show_message("first", 5000)
    win._show_message("R&D <x>", 5000, "warning")
    popup = win._open_message_history()
    text = popup.browser.toPlainText()
    check(failures, "newest first", "R&D <x>" in text and "first" in text
          and text.index("R&D <x>") < text.index("first"), repr(text))
    check(failures, "times shown", re.search(r"\d\d:\d\d:\d\d", text) is not None, repr(text))
    geo = popup.geometry()
    check(failures, "inside the screen", btn.screen().availableGeometry().contains(geo), str(geo))
    check(failures, "above the button", geo.bottom() < btn.mapToGlobal(QPoint(0, 0)).y(),
          f"{geo} vs {btn.mapToGlobal(QPoint(0, 0))}")
    check(failures, "right edges aligned",
          abs(geo.right() - btn.mapToGlobal(QPoint(btn.width() - 1, 0)).x()) <= 1, str(geo))
    check(failures, "width within limits", 420 <= geo.width() <= 720, str(geo.width()))
    QTest.keyClick(popup.browser, Qt.Key_Escape)
    check(failures, "Escape closes", not popup.isVisible())
    _close(popup)

    popup = win._open_message_history()
    QTest.mousePress(popup, Qt.LeftButton, Qt.NoModifier,
                     popup.mapFromGlobal(btn.mapToGlobal(btn.rect().center())))
    check(failures, "a press on the button closes", not popup.isVisible())
    check(failures, "that press is not replayed to the button", popup.testAttribute(Qt.WA_NoMouseReplay))
    _close(popup)

    baseline = len(QApplication.allWidgets())
    _close(win._open_message_history())
    after = len(QApplication.allWidgets())
    check(failures, "closing frees every widget", after == baseline, f"{baseline} -> {after}")
    _reset(win)


def check_popup_sizes(failures, win):
    for theme in ("dark", "light"):
        for pt in (10, 14):
            _set_look(win, theme, pt)
            _reset(win)
            for i in range(30):
                win._show_message(f"message {i}  with some words to wrap " * 3, 5000)
            popup = win._open_message_history()
            QApplication.processEvents()   # lets the browser lay out and set its scrollbar range
            geo = popup.geometry()
            tag = f"{theme} {pt}pt"
            check(failures, f"{tag}: inside the screen",
                  win._history_btn.screen().availableGeometry().contains(geo), str(geo))
            check(failures, f"{tag}: width within limits", 420 <= geo.width() <= 720, str(geo.width()))
            check(failures, f"{tag}: long history scrolls",
                  popup.browser.verticalScrollBar().maximum() > 0)
            _close(popup)
    _set_look(win, "dark", 10)
    _reset(win)


def check_load_messages(failures, win):
    canonical = jte.format_date_for_storage(date(2016, 5, 6))
    legacy = "2016-05-06" if canonical != "2016-05-06" else "06.05.2016"
    path = SCRATCH / "legacy.xml"
    path.write_text(LEGACY_XML.format(good=jte.format_date_for_storage(date(2025, 1, 1)), legacy=legacy),
                    encoding="utf-8")
    _reset(win)
    win._load(path)
    for _ in range(100):   # the backup thread reports within a few hundred ms
        if any(n.text.startswith("Backup") for n in win._notice_history):
            break
        QTest.qWait(50)
    messages = [(n.text, n.level) for n in win._notice_history]
    check(failures, "load: Loaded first",
          messages[:1] == [("Loaded: legacy.xml  v4.1.1140  (3 strings)", "info")], repr(messages))
    check(failures, "load: normalized dates as a warning",
          messages[1:2] == [("Dates: 1 normalized", "warning")], repr(messages))
    check(failures, "load: unrecognized dates as a warning",
          len(messages) > 2 and messages[2][0].startswith("Dates: 1 unrecognized (e.g. 'foo')")
          and messages[2][1] == "warning", repr(messages))
    # The default location mode is "both": one message per location follows.
    check(failures, "load: one backup message per location follows",
          [(text.split(":")[0], level) for text, level in messages[3:]]
          == [("Backup next to file", "info"), ("Backup in root", "info")], repr(messages))
    check(failures, "load: no joined line", not any("  |  " in text for text, _ in messages),
          repr(messages))
    win.is_modified = False
    win._update_title()


def check_merge_messages(failures, win):
    # Needs the file check_load_messages opened.
    _reset(win)
    win._apply_merge_diff(jte.MergeDiff([], [], [], []), [], [], [], 2, ["bad"])
    messages = [(n.text, n.level) for n in win._notice_history]
    check(failures, "merge: summary first",
          len(messages) == 3 and messages[0][0].startswith("Merged: 0 added") and messages[0][1] == "info",
          repr(messages))
    check(failures, "merge: normalized dates as a warning",
          messages[1:2] == [("Dates: 2 normalized in incoming file", "warning")], repr(messages))
    check(failures, "merge: unrecognized dates as a warning",
          messages[2:3] == [("Dates: 1 unrecognized in incoming file (e.g. 'bad')", "warning")],
          repr(messages))
    win.is_modified = False
    win._update_title()
    _reset(win)


def check_settings_notices(failures):
    """Settings.load()'s startup notices, on a settings file in a folder of its own."""
    real = jte.SETTINGS_FILE
    folder = SCRATCH / "settings_case"
    folder.mkdir()
    path = folder / "json_translation_editor_settings.json"
    jte.SETTINGS_FILE = path
    damaged = ("Settings file was damaged and could not be read "
               "(kept as json_translation_editor_settings.json.corrupt-")
    try:
        s = jte.Settings()
        check(failures, "settings missing: one warning",
              s.startup_notices == [("Settings file not found — default settings in use", "warning")],
              repr(s.startup_notices))
        check(failures, "settings missing: no recovery dialog", s.recovery_notice == "")

        path.write_text(json.dumps({"theme": "light"}), encoding="utf-8")
        s = jte.Settings()
        check(failures, "settings valid: no notices", s.startup_notices == [], repr(s.startup_notices))

        jte.backup_settings_daily(path)
        path.write_text('{"theme": "li', encoding="utf-8")
        s = jte.Settings()
        notices = s.startup_notices
        check(failures, "settings restored: damaged as an error",
              len(notices) == 2 and notices[0][0].startswith(damaged) and notices[0][1] == "error",
              repr(notices))
        check(failures, "settings restored: restore as a warning",
              len(notices) == 2 and notices[1][0].startswith("Settings restored from the backup of ")
              and notices[1][1] == "warning", repr(notices))
        check(failures, "settings restored: dialog kept", s.recovery_notice != "")

        jte._settings_archive_path(path).unlink()
        path.write_text('{"theme": "li', encoding="utf-8")
        s = jte.Settings()
        notices = s.startup_notices
        check(failures, "settings no backup: damaged as an error",
              len(notices) == 2 and notices[0][0].startswith(damaged) and notices[0][1] == "error",
              repr(notices))
        check(failures, "settings no backup: defaults as a warning",
              notices[1:] == [("Default settings in use — API keys and preferences need to be set again",
                               "warning")], repr(notices))

        shutil.rmtree(folder)
        path.mkdir(parents=True)   # exists, but reading it raises an OSError, like a locked file
        s = jte.Settings()
        check(failures, "settings unreadable: one error",
              s.startup_notices == [("Settings file could not be read — default settings in use "
                                     "for this session", "error")], repr(s.startup_notices))
    finally:
        jte.SETTINGS_FILE = real


def check_backup_messages(failures):
    """BackupThread's per-location messages, run synchronously in a folder of its own."""
    case = SCRATCH / "backup_case"
    docs, app = case / "docs", case / "app"
    docs.mkdir(parents=True)
    app.mkdir()
    source = docs / "sample.xml"
    source.write_text(LEGACY_XML.format(good="01.01.2025", legacy="01.01.2025"), encoding="utf-8")
    (docs / "sample.glossary.csv").write_text("term,translation,note\nA,Ā,\n", encoding="utf-8-sig")
    ntf_dir = docs / jte.BACKUP_DIR_NAME
    root_dir = app / jte.BACKUP_DIR_NAME

    def run(mode, interval, path=source):
        got = []
        thread = jte.BackupThread(path, "file_open", {"location_mode": mode, "compress": True,
                                  "max_count": 5, "min_interval_minutes": interval}, app)
        thread.finished.connect(lambda notices, root: got.append((notices, root)))
        thread.run()   # synchronously, so the signal is delivered at once
        return got[0] if got else ([], None)

    saved = r"saved at \d\d:\d\d:\d\d  \(compressed, \+glossary\)"
    skipped = r"skipped — backed up .+  \(min interval 5 min\)"
    failed = "failed — could not write the backup folder"

    def matches(notices, expected):
        return (len(notices) == len(expected)
                and all(level == want_level and re.fullmatch(pattern, text)
                        for (text, level), (pattern, want_level) in zip(notices, expected)))

    notices, root = run("both", 0)
    check(failures, "backup both: one info per location, next to file first",
          matches(notices, [(f"Backup next to file: {saved}", "info"), (f"Backup in root: {saved}", "info")]),
          repr(notices))
    check(failures, "backup both: next-to-file root reported", root == ntf_dir, repr(root))

    shutil.rmtree(ntf_dir)
    notices, _ = run("both", 5)
    check(failures, "backup root skipped: saved + skipped, both info",
          matches(notices, [(f"Backup next to file: {saved}", "info"), (f"Backup in root: {skipped}", "info")]),
          repr(notices))

    notices, root = run("both", 5)
    check(failures, "backup all skipped: one skipped message per location",
          matches(notices, [(f"Backup next to file: {skipped}", "info"), (f"Backup in root: {skipped}", "info")]),
          repr(notices))
    check(failures, "backup all skipped: no root to remember", root is None, repr(root))

    shutil.rmtree(ntf_dir)
    ntf_dir.write_text("not a folder", encoding="utf-8")   # blocks the next-to-file write
    notices, root = run("both", 0)
    check(failures, "backup next to file fails: error, then root saved",
          matches(notices, [(f"Backup next to file: {failed}", "error"), (f"Backup in root: {saved}", "info")]),
          repr(notices))
    check(failures, "backup next to file fails: no next-to-file root", root is None, repr(root))

    notices, _ = run("next_to_file", 0)
    check(failures, "backup fallback: error, then the fallback as a warning",
          matches(notices, [(f"Backup next to file: {failed}", "error"),
                            (rf"Backup in root \(fallback\): {saved}", "warning")]), repr(notices))

    shutil.rmtree(root_dir)
    root_dir.write_text("not a folder", encoding="utf-8")
    notices, _ = run("both", 0)
    check(failures, "backup both fail: two errors",
          matches(notices, [(f"Backup next to file: {failed}", "error"), (f"Backup in root: {failed}", "error")]),
          repr(notices))

    notices, _ = run("both", 0, docs / "missing.xml")
    check(failures, "backup source unreadable: one error",
          notices == [("Backup failed — could not read source file", "error")], repr(notices))


def check_startup_order(failures, win):
    """Settings notices play after the startup dialogs and before the translator message."""
    shown = []
    real_warning = jte.QMessageBox.warning
    jte.QMessageBox.warning = staticmethod(lambda *a, **k: shown.append(a) or 0)
    try:
        _reset(win)
        win.settings.recovery_notice = "restored"
        win.settings.startup_notices = [("damaged", "error"), ("restored", "warning")]
        win._run_startup_prompts()
    finally:
        jte.QMessageBox.warning = real_warning
        win.settings.recovery_notice = ""
        win.settings.startup_notices = []
    messages = [(n.text, n.level) for n in win._notice_history]
    check(failures, "startup: recovery dialog still shown", len(shown) == 1, repr(shown))
    check(failures, "startup: settings notices first, then the translator message",
          messages[:2] == [("damaged", "error"), ("restored", "warning")] and len(messages) == 3
          and messages[2][1] == "info", repr(messages))
    check(failures, "startup: red dot", win._history_unseen_level == "error", win._history_unseen_level)
    _reset(win)


def check_file_label(failures):
    check(failures, "file label: with a version",
          jte._file_label("Latvian.xml", "4.1.1140") == "Latvian.xml  v4.1.1140",
          repr(jte._file_label("Latvian.xml", "4.1.1140")))
    check(failures, "file label: without a version",
          jte._file_label("Latvian.xml", "") == "Latvian.xml  (no version)",
          repr(jte._file_label("Latvian.xml", "")))


def _texts(win):
    return [n.text for n in win._notice_history]


def check_file_messages(failures, win):
    """Saved, Autosaved, Closed, Restored and a version-less Loaded name the header's version."""
    good = jte.format_date_for_storage(date(2025, 1, 1))
    path = SCRATCH / "files.xml"
    path.write_text(LEGACY_XML.format(good=good, legacy=good).replace('"foo"', f'"{good}"'),
                    encoding="utf-8")
    win._load(path)
    # A version changed the way File -> Properties does, then saved.
    win.segments[0] = jte.build_header_xml(win.segments[0], None, "4.1.1141")
    win.xml_version = "4.1.1141"
    _reset(win)
    win._write(path)
    check(failures, "save: version after a Properties change",
          _texts(win) == ["Saved: files.xml  v4.1.1141"], repr(_texts(win)))

    _reset(win)
    win.is_modified = True
    win._autosave_tick()
    check(failures, "autosave: version before the time",
          len(_texts(win)) == 1 and _texts(win)[0].startswith("Autosaved: files.xml  v4.1.1141  ("),
          repr(_texts(win)))

    _reset(win)
    win._close_file()
    check(failures, "close: version of the closed file",
          _texts(win) == ["Closed: files.xml  v4.1.1141"], repr(_texts(win)))

    bare = SCRATCH / "bare.xml"
    bare.write_text(path.read_text(encoding="utf-8").replace(' Version="4.1.1141"', ""),
                    encoding="utf-8")
    _reset(win)
    win._load(bare)
    check(failures, "load: a missing version is named",
          _texts(win)[:1] == ["Loaded: bare.xml  (no version)  (3 strings)"], repr(_texts(win)))

    # Restored to a file that is not open, answering No to "Open the restored file now?".
    slot = SCRATCH / "slot" / "2026-01-01_00-00-00"
    slot.mkdir(parents=True)
    dest = SCRATCH / "restored.xml"
    raw = path.read_bytes().replace(b'Version="4.1.1141"', b'Version="4.0.900"')
    real_question = jte.QMessageBox.question
    jte.QMessageBox.question = staticmethod(lambda *a, **k: jte.QMessageBox.No)
    try:
        _reset(win)
        win._do_restore_after_backup(slot, {}, False, dest, raw, None, None, "", True)
    finally:
        jte.QMessageBox.question = real_question
    check(failures, "restore: version of the restored content",
          _texts(win) == ["Restored: restored.xml  v4.0.900"], repr(_texts(win)))

    # Restored over the open file: reloaded, the Loaded message and the Restored one both name it.
    for _ in range(100):   # let bare.xml's backup report first
        if any(t.startswith("Backup") for t in _texts(win)):
            break
        QTest.qWait(50)
    _reset(win)
    win._do_restore_after_backup(slot, {}, False, bare, raw, None, None, "", True)
    texts = _texts(win)
    check(failures, "restore and reload: Loaded and Restored name the version",
          texts[:1] == ["Loaded: bare.xml  v4.0.900  (3 strings)"]
          and "Restored and reloaded: bare.xml  v4.0.900" in texts, repr(texts))
    for _ in range(100):   # the reload's backup thread must finish before the next step
        if any(t.startswith("Backup") for t in _texts(win)):
            break
        QTest.qWait(50)
    win.is_modified = False
    win._update_title()


def check_window_title(failures, win):
    check(failures, "window title names the JSON editor",
          win.windowTitle().startswith("JSON Translation Editor v1 — "),
          repr(win.windowTitle()))


STEPS = [check_window_title, check_queue, check_guards, check_levels, check_button, check_popup, check_popup_sizes,
         check_load_messages, check_merge_messages, check_file_messages, check_startup_order]


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
    # The startup modals block forever with nobody to click them (see the offscreen-smoke-test pitfall).
    jte.QMessageBox.warning = staticmethod(lambda *a, **k: 0)
    jte.TranslatorNameDialog.exec = lambda self: 0
    for step in (check_icon, check_file_label, check_settings_notices, check_backup_messages):
        try:
            step(failures)
        except Exception as e:
            failures.append(f"{step.__name__}: {type(e).__name__}: {e}")
    with _isolated_glyph_dir():
        win = jte.MainWindow()
        win.show()
        app.processEvents()   # runs the startup prompts while the patches are active
        for step in STEPS:
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
