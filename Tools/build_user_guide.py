"""Build Resources/User_Guide.pdf from the screenshots in Tools/screenshots/.

Three-stage pipeline:
  1. Qt (QTextDocument.print_) renders the cover + Contents + 12 sections as ONE
     document, so internal `<a href="#sec">`/`<a name="sec">` anchors become
     real PDF /Link annotations -- this still works when the <a> is nested
     inside a table cell, which the TOC styling below relies on.
  2. reportlab draws a footer (title + separator rule left, "Page N of M" right)
     onto its own blank page per content page, and pypdf merges that overlay onto
     each of Qt's output pages (skipping the cover). QTextDocument has no
     per-page footer hook when printed the simple way above, so this overlay
     step is what adds page numbers.
  3. Every link's /Dest is rewritten from a name (resolved via Qt's own
     /Root/Names/Dests tree) to a literal [page_ref, mode, *args] array. Qt's
     tree stores full /GoTo action dictionaries as its values, not the plain
     destination arrays the PDF spec calls for there -- pypdf and PyMuPDF both
     tolerate this and report working links, but Edge (PDFium) did not. See
     the "PDF's internal links can validate... and still fail in Edge" pitfall
     in CLAUDE.md before assuming a pypdf/fitz check is sufficient proof a
     link structure is sound.

Run: python Tools/build_user_guide.py
Requires Tools/screenshots/*_dark.png (see take_screenshots.py) and pypdf +
reportlab + pillow (pip install pypdf reportlab pillow -- doc-tooling only,
never a runtime dependency of json_translation_editor.py itself).
"""
import base64
import io
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
SHOTS = TOOLS / "screenshots"
LOGO_PATH = REPO / "Resources" / "json_translation_editor.png"
OUT_PDF = REPO / "Resources" / "User_Guide.pdf"

sys.path.insert(0, str(REPO))
import json_translation_editor as appmod  # noqa: E402
APP_VERSION = appmod.APP_VERSION

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QTextDocument, QPageLayout, QPageSize  # noqa: E402
from PySide6.QtPrintSupport import QPrinter  # noqa: E402
from PySide6.QtCore import QMarginsF, QSizeF  # noqa: E402

from reportlab.pdfgen import canvas as rl_canvas  # noqa: E402
from reportlab.lib.pagesizes import A4 as RL_A4  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402
from pypdf.generic import ArrayObject, NameObject  # noqa: E402

# Colour palette. ACCENT is sampled directly from the app's own UI (the Save
# button in font_dark.png, pixel (493, 291) -> rgb(14, 99, 156)) so the guide's
# headings/tables read as the same product, not a generic document theme.
ACCENT = "#0E639C"
ACCENT_LIGHT = "#EAF1F8"   # table zebra stripe
GRAY_TEXT = "#555555"
GRAY_LINE = "#DDDDDD"
# Left/right widened from an earlier 10mm pass that read as "bit small" once
# reviewed side by side with the 18mm original ("terribly large"). Top/bottom
# stay at 10mm -- that axis was never actually about the page margin, see the
# `h1 { margin-top: 0 }` pitfall in CLAUDE.md, and re-widening it here would
# undo that fix. Measured directly (PyMuPDF text/image block bounding boxes
# vs. page width) that left and right were already equal within ~0.1mm at
# 10mm/10mm -- not a real asymmetry -- so this only changes the value, not an
# asymmetry fix; MARGIN_LEFT_MM and MARGIN_RIGHT_MM stay one shared constant
# on purpose so the two can never drift apart by editing only one.
MARGIN_LEFT_MM = MARGIN_RIGHT_MM = 16
MARGIN_TOP_MM = 10
# The footer's rule is drawn 18 mm above the page edge (add_footers()), so the
# bottom margin must clear it: at 10 mm Qt laid text down to 287 mm and a
# paragraph ran through the rule and the page number.
MARGIN_BOTTOM_MM = 24


def _make_printer(out_path: str) -> QPrinter:
    """QPrinter.pageRect(DevicePixel) depends on more than the resolution mode
    argument -- verified directly: identical QPrinter(ScreenResolution)
    instances reported 986px/144dpi with no output format set, vs. 657px/96dpi
    once setOutputFormat(PdfFormat) was set (Qt falls back to the native
    printer driver's DPI until the PDF engine is selected). Every printer this
    script creates must go through here so the page width used to size images
    always matches the page width actually used to print them."""
    printer = QPrinter(QPrinter.ScreenResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(out_path)
    printer.setPageSize(QPageSize(QPageSize.A4))
    printer.setPageMargins(QMarginsF(MARGIN_LEFT_MM, MARGIN_TOP_MM,
                                      MARGIN_RIGHT_MM, MARGIN_BOTTOM_MM),
                            QPageLayout.Millimeter)
    return printer


# Never used after construction -- QPrinter/QPageSize need a live QApplication
# to exist at all, and this measurement happens at import time (PAGE_WIDTH_PX
# below is a module-level constant every section body's fig()/table() calls
# need while SECTIONS is being built), before main() would otherwise create one.
_APP_FOR_MEASURE = QApplication.instance() or QApplication(sys.argv)
PAGE_WIDTH_PX = _make_printer(str(TOOLS / "_measure.pdf")).pageRect(QPrinter.DevicePixel).width()


def _b64_file(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def img_b64(name: str) -> str:
    return _b64_file(SHOTS / f"{name}_dark.png")


# QTextDocument renders <img> noticeably wider than the width attribute asks
# for -- verified directly: a 1380x720 screenshot placed at width="657" (=
# PAGE_WIDTH_PX, the full printable width) overflowed the page and clipped
# its right ~30%, and this reproduced identically whether the oversized
# dimensions came from the HTML width/height attributes or from pre-resizing
# the source PNG with PIL to that exact pixel size first -- so it isn't a
# scaling-quality issue, Qt's layout genuinely allocates more than the
# requested box. 90% was verified to make that same image fit with room to
# spare; 93% was tried to keep images larger but still clipped the Merge
# figure's Resolution column and Cancel button, so this must stay at the
# verified-safe value, not creep upward -- applied on top of each call's own
# width_pct so every figure gets the same safety factor without hand-tuning
# each one.
_WIDTH_SAFETY = 0.90


def fig(name: str, caption: str, width_pct: int = 100) -> str:
    src_path = SHOTS / f"{name}_dark.png"
    iw, ih = Image.open(src_path).size
    target_w = int(PAGE_WIDTH_PX * width_pct / 100 * _WIDTH_SAFETY)
    target_h = int(target_w * ih / iw)
    return (
        f'<p style="text-align:center;margin-top:10px;">'
        f'<img src="data:image/png;base64,{img_b64(name)}" '
        f'width="{target_w}" height="{target_h}">'
        f"</p>"
        f'<p style="text-align:center;font-size:9pt;color:{GRAY_TEXT};margin-top:2px;">'
        f"{caption}</p>"
    )


def table(headers, rows) -> str:
    """A two-or-more-column table styled like the app itself: a solid accent
    header row with white text, and alternating (zebra) row backgrounds for
    the body -- confirmed to render correctly under QTextDocument's HTML/CSS
    subset (background-color, text-align and padding on <th>/<td> all work,
    unlike the percentage-width <img> quirk noted above)."""
    thead = "".join(
        f'<th style="background-color:{ACCENT}; color:#FFFFFF; text-align:left; '
        f'padding:6px 8px; font-size:10.5pt;">{h}</th>'
        for h in headers
    )
    body = []
    for i, row in enumerate(rows):
        bg = "#FFFFFF" if i % 2 == 0 else ACCENT_LIGHT
        cells = "".join(
            f'<td style="padding:6px 8px; background-color:{bg}; '
            f'border-bottom:1px solid {GRAY_LINE}; vertical-align:top;">{c}</td>'
            for c in row
        )
        body.append(f"<tr>{cells}</tr>")
    return (
        f'<table cellpadding="0" cellspacing="0" width="100%" '
        f'style="margin-top:8px; margin-bottom:10px;">'
        f"<tr>{thead}</tr>{''.join(body)}</table>"
    )


# ---------------------------------------------------------------------------
# Section content -- (anchor, toc_title, body_html). Screenshots are taken at a 13 pt
# UI font, and the text follows docs/FEATURES.md. Sections start on a new page; a
# PAGE_BREAK inside a section keeps a figure together with the text about it.
# ---------------------------------------------------------------------------
PAGE_BREAK = '<div style="page-break-before: always;"></div>'

SECTIONS = [
    ("sec1", "Getting Started", f"""
<h1>1. Getting Started</h1>
<p>The JSON Translation Editor is a desktop tool for reviewing and editing the text
strings in a JSON language file. Each file is one flat JSON object: the key is
the source string (usually English) and the value is its translation. The editor
adds a status (New, Review, or Complete), the name of the translator, and the date
of the last change to every string.</p>
<p>Those three things cannot live in the JSON without changing what your program
reads, so they are kept in a small companion file with the same name plus
<code>.meta</code> &mdash; <code>es.json</code> has <code>es.json.meta</code>.
The language file is written back exactly the way it was found (indent, line
endings, accents), so only the strings you changed differ. A file with no
<code>.meta</code> opens with every string New.</p>
<p>When you launch the app, it asks for your name. This is used only to fill in
the Translator field automatically when you change a translation &mdash; it is
never written anywhere else and is forgotten when you close the app. Click
<b>Skip</b> if you would rather not enter one. You can set or change the name at
any time with <b>View &rarr; Set Translator Name&hellip;</b>, and the startup
question can be switched off under <b>View &rarr; Translation
Settings&hellip;</b> (&ldquo;Skip translator name prompt on startup&rdquo;).</p>
<p>With no file open, you will see the Welcome screen:</p>
{fig("welcome", "Figure 1 &mdash; The Welcome screen, shown when no file is open.", width_pct=75)}
<p>Click <b>Open File&hellip;</b>, use <b>File &rarr; Open&hellip;</b>
(<b>Ctrl+O</b>), or simply drag a <b>.json</b> file onto the window to open
it. The app also remembers the last folder you opened a file from.
<b>File &rarr; Close File</b> (<b>Ctrl+W</b>) returns to the Welcome screen
without quitting; if there are unsaved changes you can Save, Discard or
Cancel.</p>
<p>The <b>File</b> menu is grouped by what the commands do:</p>
{table(
    ["Group", "Commands"],
    [
        ["Start", "<b>Open&hellip;</b>, <b>New Language&hellip;</b> (section 9)"],
        ["Save and go back", "<b>Save</b>, <b>Save As&hellip;</b>, <b>Restore from Backup&hellip;</b> (section 6)"],
        ["Content in and out", "<b>Import&hellip;</b>, <b>Export&hellip;</b> (section 8), <b>Sync Keys from File&hellip;</b> (section 9)"],
        ["About the file", "<b>Properties&hellip;</b> (section 7)"],
        ["Finish", "<b>Close File</b>, <b>Exit</b>"],
    ],
)}
"""),
    ("sec2", "The Main Window", f"""
<h1>2. The Main Window</h1>
<p>Once a file is open, the window shows the filter panel, the table of
strings, and an information bar at the bottom:</p>
{fig("main", "Figure 2 &mdash; The main window: filter panel, translation table, and information bar.")}
<p>The table has one row per string in the file:</p>
{table(
    ["Column", "Description"],
    [
        ["#", "The string's position in the language file. Stays fixed even when a filter hides other rows."],
        ["Source Text", "The original text, shown for reference. Read-only."],
        ["Translated Text", "The translation, as it will be saved."],
        ["Status", "New, Review, or Complete &mdash; shown as a coloured pill."],
        ["Translator", "Who (or which auto-translation engine) last changed the row."],
        ["Date", "When the row was last changed."],
    ],
)}
<p>Right-click a row for quick status changes and <b>Delete Selected</b>. The
title bar shows a <b>&#9679;</b> while there are unsaved changes.</p>
{PAGE_BREAK}
<p><b>The information bar.</b> From left to right it shows:</p>
{table(
    ["Part", "What it shows"],
    [
        ["Counts", "How many rows are visible out of the total, and how many are in Review and Complete."],
        ["F5 &mdash; Refresh Filter", "Appears while a filter is active, as a reminder to refresh the list after edits so it reflects any status changes."],
        ["Messages", "Short messages such as <i>Loaded</i>, <i>Saved</i>, <i>Autosaved</i> or <i>Backup</i>. Messages that arrive together are shown one after another, with a dim <b>+N</b> while more are waiting. Warnings are amber and errors red. With no message showing, the save status appears instead: <i>Unsaved changes</i> in amber or <i>Autosaved at HH:MM:SS</i> in green."],
        ["Message history", "The small list button next to the messages. A dot on it marks a warning (amber) or error (red) you haven't looked at yet."],
        ["Language &middot; Version", "The file's language name and version, always at the far right."],
    ],
)}
<p>Click the message history button to see every message of this session,
newest first, with the time. Text can be selected and copied; Escape or a
click outside closes it.</p>
{fig("history", "Figure 3 &mdash; The message history, opened from the information bar.", width_pct=75)}
<p>Messages about a file name the file and its version, for example
<i>Loaded: es.json&nbsp;&nbsp;v1.0.0&nbsp;&nbsp;(2460 strings)</i>. If the
<code>.meta</code> file has a problem (a damaged file, an entry for a string that
is no longer there), the app says so in amber or red when the file is opened.</p>
"""),
    ("sec3", "Filtering and Searching", f"""
<h1>3. Filtering and Searching</h1>
<p>The filter panel at the top narrows down the table in real time. All the
filters apply together:</p>
{table(
    ["Filter", "What it does"],
    [
        ["Search", "Free-text search across the source, the translation, or both (the <b>In:</b> dropdown)."],
        ["Status", "Show only New, Review, Complete, or everything."],
        ["Translator", "Show only rows changed by a particular person or engine (partial match)."],
        ["Date range", "Show only rows changed within a date range &mdash; tick <b>From</b> and/or <b>To</b> to use each bound."],
        ["Check", "Show only strings whose <code>{{placeholders}}</code> differ between the source and the translation."],
    ],
)}
<p><b>Search modes.</b> The <b>Mode</b> dropdown next to the search box controls
how your search text is matched:</p>
<ul>
<li><b>Starts with</b> (the default) matches whole words that begin with what
you typed. Searching "tab" finds "Tablet" or "data-tablet", but not
"database".</li>
<li><b>Contains</b> matches your text anywhere &mdash; searching "tab" also
finds "database".</li>
</ul>
<p>Both modes ignore upper/lower case, and the chosen mode and field are
remembered for next time. Use the <b>Reset All</b> button to clear every filter
at once. An active filter is marked with an accent border on its field and a
small dot after its caption, so it's always clear at a glance what is
currently narrowing the table. If a filter matches nothing, the table area
shows "No entries match your filter" instead of an empty grid.</p>
<p><b>Picking a date.</b> Click a date field (or press Enter or Space on it) to
open a small pop-up of scrolling columns, like a phone's date wheel:</p>
{fig("date_popup", "Figure 4 &mdash; The date pop-up.", width_pct=25)}
<p>Scroll or drag each column, or use the arrow keys, then press <b>Enter</b> or
click the highlighted middle row to apply the date. <b>Escape</b> or a click
outside closes the pop-up without changing anything. The line under the
columns shows the date format in use, and the columns follow the same order.
The mouse wheel and keys do nothing on the closed field, so a date can never
change by accident. The Edit window's Date field works the same way.</p>
"""),
    ("sec4", "Editing a Translation", f"""
<h1>4. Editing a Translation</h1>
<p>Double-clicking a row (or selecting it and pressing Enter) opens the Edit
window:</p>
{fig("edit", "Figure 5 &mdash; The Edit window, showing source text, translation, and metadata.")}
<p>The <b>Source Text</b> box is read-only, shown purely for reference. Type
your translation into the <b>Translated Text</b> box below it. Pasted text is
always inserted as plain text, with spaces at the start and end trimmed; if the
source itself starts or ends with a space, the line under the box tells you the
paste lost it.</p>
<p>The Source Text box is tall enough to show a source of up to six lines in
full; a longer one scrolls. Drag the window taller or wider and both boxes grow
with it.</p>
<p>The small counter on the right (<i>Source: N &middot; Translated: M</i>)
turns amber, then red, if your translation runs noticeably longer than the
source &mdash; a useful early warning for interfaces with limited space, like
buttons.</p>
<p>The <b>Status</b>, <b>Translator</b> and <b>Date</b>
fields make up the metadata row underneath.</p>
<p>Many strings contain <code>{{placeholders}}</code> such as <code>{{name}}</code>
that the program fills in later. If the translation drops or misspells one, an
amber line under the text box says what is missing or extra (<i>Missing: {{n}}
&middot; Extra: {{m}}</i>, as in the figure). It never blocks saving; the filter
bar's <b>Check</b> filter lists every affected string.</p>
<p>As soon as you change the translated text, the app automatically sets the
status to <b>Complete</b>, stamps today's date, and fills in the Translator
field with your session name. To record a different name, tick the
<b>Override</b> checkbox next to the Translator field (it ticks itself when you
type another name there). If you only change the metadata (for example, marking
a row Review without touching the text), those fields are saved exactly as you
set them. If nothing changed, nothing is written.</p>
<p>Use <b>Alt+Left</b> / <b>Alt+Right</b> to move to the previous or next row
without leaving the Edit window &mdash; each step saves the current row first
&mdash; or <b>Ctrl+Delete</b> (with focus outside the text fields) to remove the
row you're currently editing. Deleting, here or in the main table, always asks
for confirmation and, like every edit, is only written to disk when you
save.</p>
"""),
    ("sec5", "Auto-Translation and the Glossary", f"""
<h1>5. Auto-Translation and the Glossary</h1>
<p>The <b>Auto-translate</b> button in the Edit window sends the source text
to a translation engine and fills the result into the Translated Text box for
you to review and adjust &mdash; it never saves automatically. The target
language is the file's language code (from its <code>.meta</code> file, or
guessed from the file name, so <code>pt-BR.json</code> is <code>pt-BR</code>). Choose an
engine under <b>View &rarr; Translation Settings&hellip;</b>:</p>
{fig("transl_settings", "Figure 6 &mdash; The Translation Settings dialog.", width_pct=75)}
{table(
    ["Engine", "Notes"],
    [
        ["Claude / Claude (Subscription)", "Best quality; understands UI context and placeholders. Choose a model: Haiku 4.5 (fast, low cost), Sonnet 5 or Opus 5. The Subscription option reuses a Claude Pro/Max sign-in instead of a paid API key."],
        ["DeepL", "Excellent quality; needs a free or paid API key."],
        ["Google Translate", "Good quality, free, no setup required."],
        ["MyMemory", "Good quality, free, small daily limit (larger with an email address)."],
        ["LibreTranslate / Microsoft Translator", "Good to excellent quality; need a server URL or API key respectively."],
    ],
)}
<p>Click <b>Test Connection</b> to translate the word "Hello" with the values as
currently entered, before saving them.</p>
<p><b>Robo-Translate.</b> Shift-click the Auto-translate button (or press
<b>Shift+Alt+A</b>) to translate the current row, wait a few seconds, move to
the next untouched row, and repeat automatically &mdash; handy for clearing a
long list of new strings. Only rows that are New and still show the source text
as their translation are filled in; anything already translated is skipped.
Stop it at any time by pressing the same shortcut again, or Escape. The delay
is set under <b>View &rarr; Keyboard Shortcuts&hellip;</b>.</p>
{PAGE_BREAK}
<p><b>The Glossary.</b> Some words need a specific, consistent translation
that a general engine would not know to use &mdash; brand names, or terms
specific to your product. Open <b>View &rarr; Glossary&hellip;</b> to maintain
a list of terms and their required translations for this file:</p>
{fig("glossary", "Figure 7 &mdash; The Glossary editor for the currently open file.")}
<p>Whenever a source string contains a glossary term, that translation is
passed along with the request so the Claude engines use your required wording
instead of guessing. A regular English plural is matched too, so a "Lane" entry
also covers "Lanes". This only affects the Claude and Claude (Subscription)
engines, which are the only ones that accept this kind of extra context; it can
be switched off in Translation Settings.</p>
<p>The glossary is saved as <b>&lt;file name&gt;.glossary.csv</b> next to the
language file, so it can also be edited in Excel or Notepad. Files saved by Excel with a
semicolon separator or a non-UTF-8 encoding are recognized, and the Glossary
window explains any correction before you save.</p>
"""),
    ("sec6", "Autosave and Backup", f"""
<h1>6. Autosave and Backup</h1>
<p><b>Autosave</b> periodically saves your open file automatically, so a
crash or an accidental close never costs you more than a few minutes of work.
Turn it on and choose an interval under
<b>View &rarr; Autosave &amp; Backup&hellip;</b>:</p>
{fig("autosave", "Figure 8 &mdash; The Autosave &amp; Backup settings dialog.", width_pct=70)}
<p><b>Backup</b> keeps timestamped, compressed copies of a file every time it
is opened &mdash; completely separate from autosave. <b>Backup location</b>
chooses where they are kept: next to the language file, in the editor's own folder,
or both (the default &mdash; each place keeps its own complete history).
<b>Keep last</b> sets how many copies are kept per file, and <b>Skip if backed
up within</b> avoids a second copy when the file was backed up only minutes ago
(set it to 0, "Always back up", to back up on every open). The information bar
reports each location on its own line.</p>
{PAGE_BREAK}
<p>To go back to an earlier version, use <b>File &rarr; Restore from
Backup&hellip;</b>:</p>
{fig("restore", "Figure 9 &mdash; Restore from Backup: backups grouped by file and version.")}
<p>Select a backup and click <b>Restore Selected</b>, then choose to overwrite
the original file or save a copy beside it. A safety backup of the current
file is always taken automatically before a restore overwrites anything, so
restoring the wrong snapshot by mistake is never a dead end. If the backup
includes the file's glossary, tick <b>Also restore glossary</b> to restore it
too. The file's <code>.meta</code> file is backed up and restored together with
the language file, so statuses always match the translations. <b>Delete Selected</b> removes a backup you no longer need, after a
confirmation.</p>
"""),
    ("sec7", "File Properties", f"""
<h1>7. File Properties</h1>
<p><b>File &rarr; Properties&hellip;</b> shows the open file's language details
and a few facts about it. They are stored in its <code>.meta</code> file:</p>
{fig("file_properties", "Figure 10 &mdash; The File Properties dialog.", width_pct=50)}
<ul>
<li><b>Language code</b> &mdash; e.g. <b>es</b> or <b>es-AR</b>, with the
language in words beside it. It is the target language for auto-translation. A
code guessed from the file name is shown here and stored only if you change it.</li>
<li><b>Language name</b> &mdash; the name shown in the information bar, e.g.
<i>Espa&ntilde;ol</i>. Required, up to 64 characters. If the file has none yet,
it is filled in from the code in the language's own words (<b>it</b> gives
<i>Italiano</i>, <b>es-AR</b> <i>Espa&ntilde;ol (Argentina)</i>) and follows the
code as you change it, until you type a name of your own. A name you typed or
one already stored is never replaced.</li>
<li><b>Version</b> &mdash; three boxes, e.g. 1 . 0 . 0. Use the arrows, the
mouse wheel, or type the numbers; pressing <b>.</b> (or the keypad's decimal
key) moves to the next box. The version is optional: <b>0 . 0 . 0</b> means no
version, and is what a file without one shows.</li>
<li><b>About this file</b> &mdash; file name, folder, size, last change, the
number of strings, how many are New, Review and Complete, how many are still
untranslated. The counts include unsaved
changes.</li>
</ul>
<p><b>OK</b> applies the changes like any other edit; save the file to keep
them (only the <code>.meta</code> file changes). Backups are grouped by version, so after a version change the next backup
starts a new group in Restore from Backup.</p>
"""),
    ("sec8", "Export and Import", f"""
<h1>8. Export and Import</h1>
<p>To hand a translation to someone else, move it to another computer or
deliver it to the program that uses it, use <b>File &rarr; Export&hellip;</b>.
A small window asks which:</p>
{fig("export", "Figure 11 &mdash; Choosing what to export.", width_pct=40)}
<ul>
<li><b>Package for another computer (ZIP)</b> (the default) &mdash; the language
file, its <code>.meta</code> file and its glossary, whichever exist, in one ZIP
named like <code>es_v1.0.0_2026-10-02.zip</code>. The ZIP also holds a small
<code>export_info.json</code> with each file's size and checksum, so Import can
tell whether anything changed on the way.</li>
<li><b>Translation file only</b> &mdash; just <code>es.json</code>, for the
program that reads it.</li>
</ul>
<p>Export takes the files from disk, so with unsaved changes you are asked to
save first. Your choice and the folder are remembered for next time, and the
information bar says what was written, for example <i>Exported:
es_v1.0.0_2026-10-02.zip&nbsp;&nbsp;(3 files)</i>.</p>
<p><b>Import.</b> <b>File &rarr; Import&hellip;</b> brings such a package back
in, or a plain <code>.json</code> with its <code>.meta</code> and glossary beside
it. Before anything is changed:</p>
<ul>
<li>A ZIP may hold only the one language file, its <code>.meta</code>, its
glossary and <code>export_info.json</code> (at most 10&nbsp;MB). Anything else is
refused as <i>Not a translation package</i>, and nothing is written.</li>
<li>If a file's checksum does not match, you are asked whether to import anyway
(<b>No</b> is the default). A ZIP without checksums is imported with a note that
the files were not verified.</li>
</ul>
<p><b>Where it goes.</b> If the open file has the same language, the import is
merged into it (below). Otherwise you pick a folder: if a file of that name is
already there, it is opened and the import is merged into it; if not, the
package is unpacked there and opened, ready to work on. A stray
<code>.meta</code> or glossary already in that folder is named in a question
before it is replaced.</p>
{PAGE_BREAK}
<p><b>Reviewing a merge.</b> Strings are matched by their source text. If the
incoming file differs, the review window opens:</p>
{fig("merge", "Figure 12 &mdash; Reviewing an import: an addition, a conflict and a deletion.")}
<p>It sorts what it finds into three kinds of rows, each with its own Resolution
dropdown:</p>
<ul>
<li><b>Additions</b> &mdash; new strings found only in the incoming file. Set
to <b>Accept</b> by default; switch any you don't want to <b>Reject</b>.</li>
<li><b>Conflicts</b> &mdash; the same string translated differently on each
side. Choose <b>Keep open</b> or <b>Keep incoming</b> for each one; the
checkbox in the footer can auto-resolve every conflict at once by whichever
side was edited more recently.</li>
<li><b>Deletions</b> &mdash; a string that exists in your open file but is
missing from the incoming one. Defaults to <b>Keep</b>; nothing is removed
unless you explicitly switch a row to <b>Delete</b>.</li>
</ul>
<p>Rows are tinted by their current choice: green for a string that will be
added, amber for one that will change, red for one that will be deleted. The
toolbar above the table selects and resolves rows of one kind at a time (for
example, <b>Accept</b> every addition in one click). Rows where only the
translator, status or date differ are resolved automatically using whichever
side is newer &mdash; there is nothing to review for those. If nothing differs
at all, the app says <i>Nothing to import</i> and no window opens.</p>
{PAGE_BREAK}
<p><b>Comparing a row.</b> Double-click a row to see it side by side:</p>
{fig("merge_compare", "Figure 13 &mdash; Comparing one row: the words that differ are highlighted.", width_pct=85)}
<p>The pop-up shows the source text, the open file's text and the incoming
file's text, with the differing words highlighted, plus translator, status,
modify date and length for both sides; values that differ are
amber. The header says why the default was chosen (for example, "incoming is
newer"). The two buttons at the bottom resolve the row and move on to the
next one; the current choice is marked with &#10003;, so pressing <b>Enter</b>
keeps it and moves on. <b>&#9664;</b> / <b>&#9654;</b> (or <b>Alt+Left</b> /
<b>Alt+Right</b>) step through the rows, <b>Alt+1</b> / <b>Alt+2</b> press the
two buttons, and <b>Escape</b> closes the pop-up.</p>
{PAGE_BREAK}
<p><b>The Glossary tab.</b> When the incoming glossary has terms yours lacks, or
the same term with a different translation or note, a <b>Glossary</b> tab sits
beside <b>Strings</b>; the tab you are on is the blue one:</p>
{fig("merge_glossary", "Figure 14 &mdash; The Glossary tab: new and changed terms.")}
<p>New terms default to <b>Accept</b>; changed terms default to <b>Keep
open</b>. Terms only in your glossary are always kept. Your glossary file is
read again at this point, so terms you added in Excel since opening the file are
not lost.</p>
<p>Click <b>Apply &amp; Close</b> once you are happy with your choices. The
glossary is written at once (<i>Glossary: 2 added, 1 updated</i>); the strings
change in memory, so save the file as usual to keep them. Accepted additions go
at the end of the file, and the open file keeps its own language name and
version. <b>Cancel</b> leaves everything unchanged.</p>
"""),
    ("sec9", "Syncing Keys and New Languages", f"""
<h1>9. Syncing Keys and New Languages</h1>
<p><b>Syncing keys.</b> <b>File &rarr; Sync Keys from File&hellip;</b> brings
your file's <i>keys</i> in line with a reference file, which can be in any
language (typically the English master). Missing keys are added right after
their neighbours in the reference, untranslated and New; keys the reference no
longer has are offered for deletion and default to Keep. Translations are never
copied or compared. The review uses the same window as Import, without the
Conflicts column:</p>
{fig("sync_keys", "Figure 15 &mdash; Sync Keys: additions and deletions only.")}
<p>A renamed key appears as one addition plus one deletion; nothing pairs them,
so copy the old translation across by hand (a deletion row shows its current
text). If the keys already match, the app says so and no window opens.</p>
<p><b>New languages.</b> <b>File &rarr; New Language&hellip;</b> asks for a language
code such as <b>lv</b> or <b>pt-BR</b>, proposes <code>&lt;code&gt;.json</code>
beside the open file, and writes a new file with the same keys in the same
order and layout, every string equal to its source and New. The new file then
opens, ready to translate (Robo-Translate fills in exactly these strings). If
the open file has unsaved changes, you are asked to save or discard them
first; after Discard, the new file takes its keys from the file as saved on
disk.</p>
"""),
    ("sec10", "Keyboard Shortcuts", f"""
<h1>10. Keyboard Shortcuts</h1>
<p>The Edit window and Selected Rows shortcuts below can be reassigned under
<b>View &rarr; Keyboard Shortcuts&hellip;</b>: click <b>Record&hellip;</b>, press
the new combination, or <b>Reset</b> to go back to the default.</p>
{fig("shortcuts", "Figure 16 &mdash; The Keyboard Shortcuts dialog.", width_pct=50)}
{table(
    ["Action", "Default"],
    [
        ["Open file", "Ctrl+O"],
        ["Save", "Ctrl+S"],
        ["Save As", "Ctrl+Shift+S"],
        ["Close file", "Ctrl+W"],
        ["Exit", "Ctrl+Q"],
        ["Edit selected row", "Enter"],
        ["Refresh filter", "F5"],
        ["Mark selected as New / Review / Complete", "Alt+N / Alt+R / Alt+C"],
        ["Delete selected", "Ctrl+Del"],
        ["Edit window: Previous / Next entry", "Alt+Left / Alt+Right"],
        ["Edit window: Save / Cancel", "Alt+S / Escape"],
        ["Edit window: Auto-translate", "Alt+A"],
        ["Edit window: Robo-Translate", "Shift+Alt+A"],
        ["Merge compare pop-up: the two choices", "Alt+1 / Alt+2"],
    ],
)}
"""),
    ("sec11", "Customizing the App", f"""
<h1>11. Customizing the App</h1>
<p><b>Theme.</b> Switch between Dark and Light under
<b>View &rarr; Theme</b>. Your choice is remembered for next time.</p>
<p><b>Font.</b> Choose the interface font and size under
<b>View &rarr; Choose UI Font&hellip;</b>, with a live preview of your
selection. Dialogs, hints, check boxes and scrollbars grow with the chosen
size:</p>
{fig("font", "Figure 17 &mdash; The Choose UI Font dialog.", width_pct=60)}
<p><b>Column widths.</b> Drag a column's edge to resize it &mdash; the new
width is remembered automatically.</p>
<p>All of your preferences &mdash; theme, font, shortcuts, filter settings,
and translation engine setup &mdash; are stored automatically in a small
settings file next to the application, and do not need to be configured again
after restarting.</p>
<p><b>Settings backup.</b> Because the settings file holds your API keys, the
app keeps a copy of it once a day in
<b>json_translation_editor_settings.backups.zip</b> beside it (the newest 10 days).
If the settings file is ever damaged, the app restores the newest good copy
automatically at startup and tells you so. Deleting the settings file is still
the way to reset everything to defaults.</p>
"""),
    ("sec12", "Troubleshooting", f"""
<h1>12. Troubleshooting</h1>
{table(
    ["Problem", "What to do"],
    [
        ["The date picker shows the wrong format", "The app follows your Windows regional date setting. Change it under Control Panel &rarr; Region &rarr; Short date, then restart the app."],
        ["Autosave shows a \"File Locked\" message", "Another program has the file open. Choose <b>Save As&hellip;</b> to save a copy elsewhere, or <b>Skip</b> to try again at the next interval &mdash; no changes are lost either way."],
        ["No backups are being created", "Check the Backup messages in the information bar or its message history: each location is reported separately, and a failed one shows in red. \"Skipped&hellip;\" means a recent backup already exists &mdash; lower \"Skip if backed up within\" under <b>View &rarr; Autosave &amp; Backup&hellip;</b> if you want one every time."],
        ["A message went by too quickly", "Click the message history button in the information bar to read every message of this session."],
        ["A file is refused when opened", "The message names the problem: invalid JSON (with line and column), a top level that is not an object, a value that is not text, or the same key twice. Fix the file in a text editor and open it again."],
        ["\"Reformat File\" appears on the first save", "The file's layout (indent, spacing) is not one the app reproduces exactly, so saving will tidy it. Only whitespace changes, never the translations. Answer Yes once; later saves ask nothing. Autosave waits until you have done this."],
        ["Import says \"Not a translation package\"", "The ZIP holds a subfolder, an extra file, two language files, is over 10&nbsp;MB unpacked, or is damaged. Export it again with <b>File &rarr; Export&hellip;</b>."],
        ["Import asks about files that do not match their checksums", "A file in the package changed after it was exported, or the ZIP was damaged on the way. Answer No and ask for a fresh export unless you know why it changed."],
        ["Everything shows as New","The file's <code>.meta</code> file is missing or was damaged. A damaged one is kept as <code>.meta.corrupt-&lt;time&gt;</code> and the app says so; restore it from a backup or repair the kept copy."],
        ["A keyboard shortcut stopped working", "Check its binding under <b>View &rarr; Keyboard Shortcuts&hellip;</b> &mdash; it may have been reassigned, or another application may be using the same combination."],
        ["Auto-translate says \"No target language\"", "The target language is the file's language code. If the file name is not a code (for example <code>strings.json</code>), set it under <b>File &rarr; Properties&hellip;</b>."],
        ["Google Translate says it is rate-limiting this network", "Google limits how many free requests one network may send. Wait a while, raise the Robo-Translate delay, or switch to another engine in Translation Settings."],
        ["A settings recovery message appears at startup", "The settings file was damaged (for example by a crash) and was restored from the newest daily copy. Check your translation settings and API keys; if no copy existed, enter them again."],
    ],
)}
"""),
]

TOC_ROWS = "".join(
    f'<tr><td style="padding:7px 2px; border-bottom:1px solid {GRAY_LINE};">'
    f'<a href="#{anchor}" style="color:{ACCENT}; text-decoration:none; font-size:11.5pt;">'
    f"{i}.&nbsp;&nbsp;{title}</a></td></tr>"
    for i, (anchor, title, _body) in enumerate(SECTIONS, start=1)
)
TOC_TABLE = f'<table cellpadding="0" cellspacing="0" width="100%">{TOC_ROWS}</table>'

_logo_w = 110
_logo_iw, _logo_ih = Image.open(LOGO_PATH).size
_logo_h = int(_logo_w * _logo_ih / _logo_iw)


def _bar(width_pct: int = 55, height_px: int = 7) -> str:
    """A solid accent-coloured horizontal bar, centered, framing the cover
    title -- background-color on a table cell is the one styling mechanism
    already verified to render correctly under QTextDocument's HTML subset
    (see `table()`); a plain <hr> or a <div> border was not tested and the
    percentage-width <img> quirk elsewhere in this file is reason enough not
    to assume an untested CSS shortcut just works."""
    return (
        f'<table width="{width_pct}%" align="center" cellpadding="0" cellspacing="0">'
        f'<tr><td style="background-color:{ACCENT}; height:{height_px}px; '
        f'font-size:1px; line-height:1px;">&nbsp;</td></tr></table>'
    )


COVER = f"""
<div style="text-align:center; margin-top:70px;">
<img src="data:image/png;base64,{_b64_file(LOGO_PATH)}" width="{_logo_w}" height="{_logo_h}">
<p style="margin-top:18px; margin-bottom:0;">{_bar()}</p>
<h1 style="font-size:25pt; color:{ACCENT}; margin-top:16px; margin-bottom:2px;">JSON Translation Editor</h1>
<p style="font-size:15pt; color:#444444; margin-top:2px; margin-bottom:16px;">User Guide</p>
<p style="margin-top:0; margin-bottom:0;">{_bar()}</p>
<p style="font-size:11pt; color:#888888; margin-top:16px;">Version {APP_VERSION}</p>
<p style="font-size:10.5pt; color:{GRAY_TEXT}; margin-top:50px;">A guide for translators using the JSON Translation Editor<br>
to review, edit, and manage localization strings.</p>
</div>
"""

FULL_HTML = f"""
<html><head><style>
h1 {{ color: {ACCENT}; margin-top: 0; margin-bottom: 10px; }}
</style></head>
<body style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5pt; color: #202020;">

{COVER}

{PAGE_BREAK}
<a name="toc"></a>
<h1>Contents</h1>
{TOC_TABLE}

{"".join(PAGE_BREAK + f'<a name="{anchor}"></a>' + body for anchor, _title, body in SECTIONS)}

</body></html>
"""


def build_base_pdf(tmp_path: Path):
    app = QApplication.instance() or QApplication(sys.argv)
    doc = QTextDocument()
    doc.setHtml(FULL_HTML)

    printer = _make_printer(str(tmp_path))
    page_rect = printer.pageRect(QPrinter.DevicePixel)
    assert page_rect.width() == PAGE_WIDTH_PX, \
        "measurement printer and output printer disagree on page width"
    # doc.setTextWidth() alone (width only, no height) leaves QTextDocument
    # unaware of the actual page height, and print_() then falls back to its
    # own default multi-page behaviour, which silently draws a bare page
    # number ("1", "2", ...) at the bottom of every page -- verified directly
    # by printing a plain 2-page document and finding "1"/"2" appended to
    # each page's extracted text with zero HTML asking for it. That number is
    # separate from (and stacks with, doubling up) the "Page N of M" footer
    # add_footers() draws below, and appears on the cover too since print_()
    # doesn't know to skip page 1. Passing setPageSize() the real page
    # height, not just setTextWidth()'s width, was verified to suppress it
    # entirely -- the same 2-page test then extracts with no stray digit.
    doc.setTextWidth(PAGE_WIDTH_PX)
    doc.setPageSize(QSizeF(page_rect.width(), page_rect.height()))
    doc.print_(printer)
    return app


def _named_dest_page_map(reader: PdfReader) -> dict:
    """Map each `<a name="secN">` anchor to (page_index, mode, args), read from
    Qt's own /Root/Names/Dests name tree before that tree gets left behind by
    the page-copying below.

    Qt does not store plain destination arrays here -- pikepdf (an independent,
    qpdf-based parser, not another lenient pure-Python one like pypdf itself)
    showed each entry is a full /GoTo *action* dictionary
    (`{"/D": [page, "/FitH", y], "/S": "/GoTo"}`), which is the shape a link's
    own `/A` uses, not the shape ISO 32000 12.3.2.3 specifies for a Names-tree
    *destination* value (a bare array, or `{"/D": [...]}` with no `/S`). pypdf
    and MuPDF both resolve it anyway and report correct target pages, which is
    exactly the trap: two lenient/complete implementations tolerating a
    non-canonical structure proves nothing about a strict one. Since Edge
    (PDFium) was reported working on an earlier build and broken on this
    pipeline's later output with no HTML/anchor changes in between, this
    structure -- present since the very first build, not something a recent
    edit introduced -- is the prime suspect, and the fix below sidesteps it
    entirely rather than trying to persuade Qt to emit a different shape."""
    dest_map = {}
    names = reader.trailer["/Root"].get("/Names")
    if names is None:
        return dest_map
    dests = names.get_object().get("/Dests")
    if dests is None:
        return dest_map
    names_list = dests.get_object()["/Names"]
    page_index_by_ref = {p.indirect_reference: i for i, p in enumerate(reader.pages)}
    for i in range(0, len(names_list), 2):
        name = str(names_list[i])
        dest_obj = names_list[i + 1].get_object()
        d_array = dest_obj["/D"] if "/D" in dest_obj else dest_obj
        page_idx = page_index_by_ref.get(d_array[0])
        if page_idx is not None:
            dest_map[name] = (page_idx, d_array[1], list(d_array[2:]))
    return dest_map


def add_footers(base_path: Path, out_path: Path):
    reader = PdfReader(str(base_path))
    dest_map = _named_dest_page_map(reader)
    writer = PdfWriter()
    n_content_pages = len(reader.pages) - 1  # every page except the cover
    footer_num = 0
    accent_rgb = tuple(int(ACCENT[i:i + 2], 16) / 255 for i in (1, 3, 5))
    for i, page in enumerate(reader.pages):
        if i > 0:
            footer_num += 1
            buf = io.BytesIO()
            c = rl_canvas.Canvas(buf, pagesize=RL_A4)
            left_x = MARGIN_LEFT_MM * 2.83465
            right_x = (210 - MARGIN_RIGHT_MM) * 2.83465
            rule_y = 18 * 2.83465
            text_y = 12 * 2.83465
            c.setStrokeColorRGB(*accent_rgb)
            c.setLineWidth(0.75)
            c.line(left_x, rule_y, right_x, rule_y)
            c.setFont("Helvetica", 8)
            c.setFillColorRGB(0.4, 0.4, 0.4)
            c.drawString(left_x, text_y, "JSON Translation Editor — User Guide")
            c.drawRightString(right_x, text_y, f"Page {footer_num} of {n_content_pages}")
            c.save()
            buf.seek(0)
            page.merge_page(PdfReader(buf).pages[0])
        writer.add_page(page)

    # Rewrite every TOC link's /Dest from a named lookup (into the
    # possibly-non-canonical tree above) to a literal destination array
    # pointing straight at the target page -- the simplest, most universally
    # supported link mechanism, with nothing left for a strict engine to
    # refuse to resolve. Must run as its own pass, after every page is in
    # `writer.pages`, since a link on an early page can target a later one
    # that doesn't have a writer-side page object yet while pages are still
    # being added.
    for page in writer.pages:
        annots = page.get("/Annots")
        if not annots:
            continue
        for annot_ref in annots:
            annot = annot_ref.get_object()
            dest = annot.get("/Dest")
            if not isinstance(dest, str) or str(dest) not in dest_map:
                continue
            target_idx, mode, args = dest_map[str(dest)]
            annot[NameObject("/Dest")] = ArrayObject(
                [writer.pages[target_idx].indirect_reference, NameObject(mode), *args]
            )

    writer.add_metadata({
        "/Title": "JSON Translation Editor — User Guide",
        "/Producer": "Qt + reportlab (Tools/build_user_guide.py)",
    })
    with open(out_path, "wb") as f:
        writer.write(f)


def main():
    missing = [n for n in ("welcome", "main", "history", "date_popup", "edit",
                            "transl_settings", "glossary", "autosave", "restore",
                            "file_properties", "export", "merge", "merge_compare",
                            "merge_glossary", "sync_keys", "shortcuts", "font")
               if not (SHOTS / f"{n}_dark.png").exists()]
    if missing:
        print("Missing screenshots, run take_screenshots.py first:", missing)
        sys.exit(1)

    tmp = TOOLS / "_base.pdf"
    build_base_pdf(tmp)
    add_footers(tmp, OUT_PDF)
    tmp.unlink()

    r = PdfReader(str(OUT_PDF))
    print(f"Wrote {OUT_PDF} ({len(r.pages)} pages)")


if __name__ == "__main__":
    main()
