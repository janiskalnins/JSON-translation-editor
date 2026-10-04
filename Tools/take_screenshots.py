"""Render the app's windows/dialogs to PNGs for the User Guide.

Uses a scratch copy of tests/data/es.json and its es.json.meta as sample data -- never real
user data, never the root es.json. Runs on
Qt's native (non-offscreen) platform deliberately: Qt's "offscreen" platform
plugin has zero font families registered on this machine (QFontDatabase.families()
returns []), so every screenshot came out as tofu boxes under it. The native
Windows platform has the system's real fonts (682 families), so windows are
briefly shown on-screen during capture -- acceptable for a one-off doc tool.
Nothing touches the real json_translation_editor_settings.json (cwd is redirected to
this script's own directory via sys.argv[0]).

Usage: python Tools/take_screenshots.py [dark|light]
Output: Tools/screenshots/<name>_<theme>.png
Every window is captured at a FONT_PT UI font, set before any dialog is built.
"""
import dataclasses
import json
import os
import shutil
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
OUT = TOOLS / "screenshots"
OUT.mkdir(exist_ok=True)

# Run from a scratch cwd so settings/backups never touch the repo -- point
# sys.argv[0] there too, since the app derives its backup root from it.
SCRATCH = TOOLS / "_scratch"
SCRATCH.mkdir(exist_ok=True)
os.chdir(SCRATCH)
sys.path.insert(0, str(REPO))
sys.argv[0] = str(SCRATCH / "take_screenshots.py")
# The sample lives in its own folder so "next to file" and "root" backups land
# in different places, as they do for a real user; both trees start empty so
# the Restore figure shows one tidy slot per location.
SAMPLE_DIR = SCRATCH / "Translations"
SAMPLE_DIR.mkdir(exist_ok=True)
for backups in (SCRATCH / "JSON_Translation_file_Backups",
                SAMPLE_DIR / "JSON_Translation_file_Backups"):
    shutil.rmtree(backups, ignore_errors=True)
SAMPLE = SAMPLE_DIR / "es.json"
shutil.copy(REPO / "tests" / "data" / "es.json", SAMPLE)
shutil.copy(REPO / "tests" / "data" / "es.json.meta", SAMPLE_DIR / "es.json.meta")
shutil.copy(REPO / "tests" / "data" / "es.glossary.csv", SAMPLE_DIR / "es.glossary.csv")

# The frozen sidecar marks three entries; the screenshots need a believable mix of statuses, so
# the scratch copy (never the frozen one) gets more.
_meta_path = SAMPLE_DIR / "es.json.meta"
_meta = json.loads(_meta_path.read_text(encoding="utf-8"))
_names = list(json.loads(SAMPLE.read_text(encoding="utf-8")))
_demo = [("Complete", "Jane", "2026-09-30"), ("Review", "Jo", "2026-09-12"),
         ("Complete", "Jane", "2026-08-21"), ("Complete", "Mara", "2026-07-02")]
for i, key in enumerate(_names[3:40]):
    if i % 3 == 2:
        continue                       # leave every third entry New
    status, translator, modified = _demo[i % len(_demo)]
    _meta["entries"].setdefault(key, {"status": status, "translator": translator, "modified": modified})
_meta_path.write_text(json.dumps(_meta, ensure_ascii=False, indent=1) + chr(10), encoding="utf-8")

theme = sys.argv[1] if len(sys.argv) > 1 else "dark"
FONT_PT = 13

import json_translation_editor as m  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setStyle("Fusion")
m.QMessageBox.warning = staticmethod(lambda *a, **k: 0)
m.TranslatorNameDialog.exec = lambda self: 0


def snap(widget, name):
    widget.show()
    for _ in range(5):
        app.processEvents()
    out = OUT / f"{name}_{theme}.png"
    widget.grab().save(str(out))
    print("saved", out.name, widget.width(), "x", widget.height())


win = m.MainWindow()
win.settings.set("theme", theme)
win.settings.set("font_size", FONT_PT)
win._apply_palette()
win._apply_app_font()   # also re-applies the theme stylesheet at the new size
win.resize(1500, 850)
win.show()
for _ in range(5):
    app.processEvents()
snap(win, "welcome")   # no file open yet -- Welcome screen

win._load(SAMPLE)
for t in list(win._backup_threads):
    t.wait(8000)
# Let the startup messages (translator, Loaded, Backup) play out so the
# info bar shows its resting state instead of whichever message is mid-queue.
deadline = time.monotonic() + 60
while win._notice_current is not None and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.05)
snap(win, "main")

win.glossary = [
    m.GlossaryEntry("Lane", "Carril", "road lane"),
    m.GlossaryEntry("Path", "Trazado", "not 'ruta'"),
    m.GlossaryEntry("Guide point", "Punto guía", ""),
]
snap(m.GlossaryDialog(win, parent=win), "glossary")
snap(m.RestoreFromBackupDialog(SCRATCH, parent=win), "restore")

E = m.StringEntry
adds = [E("Add one", "Jane", "New", "01.01.2026", "Añadir uno")]
confs = [(E("Conflict src", "A", "Review", "01.01.2025", "Antiguo"),
          E("Conflict src", "B", "Complete", "02.02.2026", "Nuevo"))]
dels = [E("Delete me", "C", "Complete", "03.03.2024", "Eliminar")]
# An Import whose glossary differs too, so the review window has its Strings and Glossary tabs.
G = m.GlossaryEntry
gl_diff = m.GlossaryDiff(
    additions=[G("Guide line", "Línea guía", ""), G("Terrain profile", "Perfil del terreno", "")],
    changes=[(G("Path", "Trazado", "not 'ruta'"), G("Path", "Recorrido", "since v1.1"))],
    warnings=[])
merge_dlg = m.MergeConflictDialog(adds, confs, dels, parent=win, glossary_diff=gl_diff)
snap(merge_dlg, "merge")
merge_dlg._tabs.setCurrentIndex(1)
snap(merge_dlg, "merge_glossary")
merge_dlg._tabs.setCurrentIndex(0)
conflict_row = next(r for r in range(merge_dlg.row_count())
                    if merge_dlg.row_info(r).kind == "conflict")
compare = m.MergeCompareDialog(merge_dlg, conflict_row)
snap(compare, "merge_compare")
compare.close()
merge_dlg.close()
snap(m.ExportDialog("zip", parent=win), "export")

sync_dlg = m.MergeConflictDialog([E("Fit to page", "", "New", "", "Fit to page")], [], dels,
                                 parent=win, sync_mode=True)
snap(sync_dlg, "sync_keys")
sync_dlg.close()

# The Edit window on an entry whose translation lost its {placeholder}, so the amber line shows.
placeholder_entry = next(e for e in win.entries if e.name == "Path {n}")
placeholder_entry.text = "Trazado {m}"
placeholder_row = win.entries.index(placeholder_entry)
snap(m.EditDialog(win.model, placeholder_row, win.settings.get_font(),
                  shortcuts=win.settings.get("shortcuts", {}),
                  target_culture=win.target_culture,
                  transl_cfg=win.settings.get("translation", {}), parent=win), "edit")
snap(m.AutosaveBackupDialog(win.settings, parent=win), "autosave")
# Pre-select an engine so the screenshot shows the populated Claude
# Subscription panel instead of the default "Disabled" state (an empty
# dialog with just an engine dropdown is not a useful figure for the guide).
win.settings.data["translation"] = {"engine": "claude_subscription"}
snap(m.TranslationSettingsDialog(win.settings, parent=win), "transl_settings")
snap(m.ShortcutsDialog(win.settings, parent=win), "shortcuts")
snap(m.FontSettingsDialog(win.settings.get_font(), parent=win), "font")
# A neutral sample folder instead of this script's scratch path.
facts = dataclasses.replace(m.compute_file_facts(win.entries, win.current_file),
                            folder=r"C:\Translations")
snap(m.FilePropertiesDialog(win.target_culture, win.display_language, win.file_version,
                            facts, win.is_modified, parent=win), "file_properties")

# The two widgets this fork added to existing surfaces, at 10 and 14 pt (named *_pt<size>) for
# a clipping check by eye: File Properties' language-code field and the filter bar's Check column.
for pt in (10, 14):
    win.settings.set("font_size", pt)
    win._apply_app_font()
    for _ in range(5):
        app.processEvents()
    snap(win.filter_panel, f"filter_bar_pt{pt}")
    snap(m.FilePropertiesDialog(win.target_culture, win.display_language, win.file_version,
                                facts, win.is_modified, parent=win), f"file_properties_pt{pt}")
win.settings.set("font_size", FONT_PT)
win._apply_app_font()
for _ in range(5):
    app.processEvents()

# Qt.Popup windows: each is closed after its capture so it can't swallow the
# next one's mouse/keyboard grab.
popup = win.filter_panel.date_from.open_popup()
snap(popup, "date_popup")
popup.close()
popup = win._open_message_history()
snap(popup, "history")
popup.close()
# os._exit(0), not a normal return: this process reliably segfaults on
# ordinary interpreter shutdown (Qt offscreen-vs-native teardown quirk, not a
# script bug), but only *after* every snap() above has already written its
# PNG to disk -- verified repeatedly across every rebuild in this session, so
# a segfault here is expected and does not mean the screenshots are missing.
os._exit(0)
