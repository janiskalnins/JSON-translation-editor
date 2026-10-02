"""
JSON Translation Editor
A PySide6 desktop app for viewing, filtering, and editing JSON translation files.
"""

import sys
import os
import re
import json
import math
import html
import gzip
import shutil
import hashlib
import asyncio
import concurrent.futures
import threading
import subprocess
import csv
import difflib
import io
import tempfile
import time
import zipfile
import zlib
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, date
from pathlib import Path
from typing import Callable, Optional, List, Tuple, Dict, Deque

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QTableView, QHeaderView, QAbstractItemView,
    QToolBar, QStatusBar, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLayout, QLayoutItem,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QDialog, QDialogButtonBox, QTextEdit, QPlainTextEdit,
    QGroupBox, QFrame, QSizePolicy, QDateEdit,
    QCheckBox, QSpinBox, QFontComboBox, QMenu, QScrollArea,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle,
    QStyleOptionComboBox, QStyleOptionSpinBox,
    QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QStackedWidget, QToolButton, QTextBrowser
)
from PySide6.QtGui import (
    QAction, QFont, QColor, QPainter, QPen, QBrush,
    QPalette, QIcon, QKeySequence, QPixmap, QLinearGradient,
    QTextCharFormat, QTextCursor, QFontMetrics, QShortcut,
    QImage, QPolygonF
)
from PySide6.QtCore import (
    Qt, Signal, QDate, QModelIndex, QAbstractTableModel,
    QTimer, QEvent, QThread, QItemSelection, QItemSelectionModel,
    QRect, QRectF, QPoint, QPointF, QSize, QBuffer, QIODevice, QStandardPaths,
    QLocale, QDateTime, QVariantAnimation, QEasingCurve
)


# ══════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════

SETTINGS_FILE = Path("json_translation_editor_settings.json")
STATUSES = ["New", "Review", "Complete"]

_ERROR_LOG_FILE = Path("error_log.txt")

SETTINGS_BACKUP_MAX = 10   # daily snapshots kept in the settings archive

APP_VERSION = "1"    # plain integer, matches the GitHub release tag scheme (v1, v2, ...) -- bump manually before tagging a release
APP_NAME = "JSON Translation Editor"


def _resource_path(*parts: str) -> Path:
    """Resolve a bundled resource, honoring PyInstaller onefile extraction (_MEIPASS)."""
    base = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent)
    return base.joinpath(*parts)


APP_ICON_PATH = _resource_path("Resources", "xml_translation_editor.ico")
APP_LOGO_PATH = _resource_path("Resources", "xml_translation_editor.png")


def _log_error(context: str, exc: BaseException) -> None:
    """Best-effort diagnostic log for failures that would otherwise vanish
    silently in the --windowed build (no console is attached, so print()
    output has nowhere to go). Never raises -- this is the last line of
    defense, so a logging failure must never mask or replace the original
    error's own handling at the call site.
    """
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with _ERROR_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {context}: {exc}\n")
    except Exception:
        pass


# ── System date format ─────────────────────────────────────────────────────

def _get_windows_short_date_format() -> str:
    """Read the short-date picture string from Windows regional settings.

    Returns a Windows picture string such as 'dd/MM/yyyy' or 'M/d/yyyy'.
    Falls back to 'dd.MM.yyyy' if not on Windows or if the call fails.
    """
    try:
        import ctypes
        import ctypes.wintypes
        # GetLocaleInfoEx with LOCALE_SSHORTDATE (0x001F) returns the
        # short-date picture (e.g. 'dd/MM/yyyy', 'M/d/yyyy', 'yyyy-MM-dd')
        LOCALE_SSHORTDATE = 0x001F
        buf = ctypes.create_unicode_buffer(256)
        # Pass NULL locale name -> use the current user default locale
        n = ctypes.windll.kernel32.GetLocaleInfoEx(
            None, LOCALE_SSHORTDATE, buf, 256
        )
        if n > 0:
            return buf.value.strip()
    except Exception:
        pass
    return 'dd.MM.yyyy'   # safe fallback


def _win_to_qt_date_fmt(win_fmt: str) -> str:
    """Convert a Windows short-date picture to a Qt date-format string.

    Windows uses single/double letter codes (d dd M MM yy yyyy).
    Qt uses the same conventions, so the mapping is 1-to-1.
    The only adjustment needed is that Windows sometimes uses a single
    letter (e.g. 'd' meaning 'no leading zero') which Qt also supports.
    """
    return win_fmt  # Windows and Qt share the same picture-string syntax


def _win_to_python_date_fmt(win_fmt: str) -> str:
    """Convert a Windows short-date picture to a Python strftime format.

    Windows picture -> Python directive:
      d   -> %-d  (day, no leading zero; %d on Windows via strftime)
      dd  -> %d   (day, zero-padded)
      M   -> %-m  (month, no leading zero)
      MM  -> %m   (month, zero-padded)
      yy  -> %y   (2-digit year)
      yyyy-> %Y   (4-digit year)

    We build a list of token replacements from longest to shortest so
    that 'yyyy' is matched before 'yy', 'dd' before 'd', 'MM' before 'M'.
    Non-letter separators (/ . - space) are kept as-is.
    """
    import re as _re
    # Tokenise: split into runs of letters vs. runs of non-letters
    tokens = _re.findall(r'[A-Za-z]+|[^A-Za-z]+', win_fmt)
    mapping = {
        'yyyy': '%Y',
        'yy':   '%y',
        'MMMM': '%B',
        'MMM':  '%b',
        'MM':   '%m',
        'M':    '%m',   # Python has no 'no-leading-zero' directive on all platforms
        'dddd': '%A',
        'ddd':  '%a',
        'dd':   '%d',
        'd':    '%d',   # same caveat as 'M' above
    }
    return ''.join(mapping.get(tok, tok) for tok in tokens)


# Resolve at import time so the rest of the module uses plain constants.
_WIN_DATE_FMT    = _get_windows_short_date_format()     # e.g. 'dd/MM/yyyy'
DATE_FMT_QT      = _win_to_qt_date_fmt(_WIN_DATE_FMT)   # Qt display format
DATE_FMT         = _win_to_python_date_fmt(_WIN_DATE_FMT)  # Python strftime/strptime


# Whether this machine's own short-date convention puts the day before the
# month (e.g. "dd.MM.yyyy") or the month before the day (e.g. "M/d/yyyy").
# Used below to break the tie for ambiguous slash-separated dates like
# "06/05/2016", where both candidate day/month values are <= 12 and the
# format string alone can't disambiguate them.
_LOCALE_DAY_FIRST = _WIN_DATE_FMT.lower().find('d') < _WIN_DATE_FMT.lower().find('m')

# Common fallback formats tried when the primary parse fails.
# Covers legacy dd.mm.yyyy files and other regional variants. Dot-separated
# formats are unambiguous regardless of order -- a 4-digit year can never
# satisfy a 2-digit day/month slot -- so only the slash-separated pairs need
# a locale-aware tiebreak.
if _LOCALE_DAY_FIRST:
    _DATE_FALLBACKS = [
        "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y",
        "%Y-%m-%d", "%Y.%m.%d", "%d-%m-%Y",
        "%d.%m.%y", "%d/%m/%y", "%m/%d/%y",
    ]
else:
    _DATE_FALLBACKS = [
        "%d.%m.%Y", "%m/%d/%Y", "%d/%m/%Y",
        "%Y-%m-%d", "%Y.%m.%d", "%d-%m-%Y",
        "%d.%m.%y", "%m/%d/%y", "%d/%m/%y",
    ]


def parse_date(date_str: str):
    """Parse *date_str* using the system DATE_FMT first, then common fallbacks.

    Strips a trailing run of periods/spaces before matching, so the
    traditional Latvian/Baltic short-date picture (e.g. "yyyy.MM.dd.",
    producing values like "2016.05.06.") parses the same as its undotted
    equivalent.

    Returns a ``datetime.date`` object, or ``None`` if all formats fail.
    """
    cleaned = date_str.strip().rstrip('. ')
    for fmt in [DATE_FMT] + _DATE_FALLBACKS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    return None


def format_date_for_storage(d) -> str:
    """Format a ``datetime.date`` or ``QDate`` using the system DATE_FMT.

    Accepts either a Python ``datetime.date`` or a ``QDate``.
    """
    if hasattr(d, "year") and callable(d.year):  # QDate
        d = __import__("datetime").date(d.year(), d.month(), d.day())
    return d.strftime(DATE_FMT)


# Per-theme status badge colours (bg, fg)
STATUS_COLORS = {
    "dark": {
        "New":      ("#3a3a3a", "#d4d4d4"),
        "Review":   ("#5f4200", "#FFCA28"),
        "Complete": ("#1a4a26", "#7ED482"),
    },
    "light": {
        "New":      ("#e0e0e0", "#444444"),
        "Review":   ("#fff3cd", "#7a5500"),
        "Complete": ("#d4edda", "#1a6b2a"),
    },
}

COL_IDX   = 0
COL_SRC   = 1
COL_TRANS = 2
COL_STATUS = 3
COL_USER  = 4
COL_DATE  = 5

HEADERS = ["#", "Source Text", "Translated Text", "Status", "Translator", "Date"]


# ══════════════════════════════════════════════════════════════
#  DATA CLASSES
# ══════════════════════════════════════════════════════════════

@dataclass
class StringEntry:
    name: str          # source text (the JSON key)
    translator: str
    status: str        # New / Review / Complete
    modify_date: str   # shown and edited in the system short-date format; ISO in the sidecar
    text: str          # translated text (the JSON value)
    position: int = 0  # 1-based place in the file when it was loaded; the # column

    def clone(self) -> "StringEntry":
        return deepcopy(self)


@dataclass
class GlossaryEntry:
    """One glossary row: a source term and the translation the AI engines
    must use when that term appears in a string being translated."""
    term:        str
    translation: str
    note:        str = ""


# ══════════════════════════════════════════════════════════════
#  THEME DEFINITIONS
# ══════════════════════════════════════════════════════════════

THEMES = {
    "dark": {
        # QPalette
        "pal_window":         "#1e1e1e",
        "pal_window_text":    "#d4d4d4",
        "pal_base":           "#252526",
        "pal_alt_base":       "#2d2d2d",
        "pal_text":           "#d4d4d4",
        "pal_button":         "#3c3c3c",
        "pal_button_text":    "#d4d4d4",
        "pal_highlight":      "#094771",
        "pal_hl_text":        "#ffffff",
        "pal_tooltip_base":   "#252526",
        "pal_tooltip_text":   "#d4d4d4",
        # Main window QSS
        "bg":                 "#1e1e1e",
        "bg2":                "#252526",
        "bg3":                "#2d2d2d",
        "bg4":                "#3c3c3c",
        "fg":                 "#d4d4d4",
        "fg_dim":             "#9a9a9a",
        "border":             "#3a3a3a",
        "border2":            "#555555",
        "accent":             "#007acc",
        "sel_bg":             "#094771",
        "sel_fg":             "#ffffff",
        "header_fg":          "#9cdcfe",
        "grid":               "#2d2d2d",
        "sb_bg":              "#007acc",
        "sb_fg":              "#ffffff",
        "sep":                "#3a3a3a",
        # Bands, row hover and AA-safe text colours (spec 2026-09-21-ui-ux-refresh)
        "bar_border":         "#4a4a4a",
        "hover_row":          "#34343a",
        "text_ok":            "#4CAF50",
        "text_warn":          "#FFB300",
        "text_bad":           "#FF8A80",
        # EditDialog QSS
        "dlg_bg":             "#252526",
        "dlg_src_bg":         "#1a1a2e",
        "dlg_src_fg":         "#aaaaaa",
        "dlg_edit_bg":        "#1e1e1e",
        "dlg_btn_bg":         "#0e639c",
        "dlg_btn_hover":      "#1177bb",
        "dlg_btn_dis":        "#3a3a3a",
        "dlg_btn_dis_fg":     "#666666",
        "dlg_nav_bg":         "#2d2d2d",
        "dlg_nav_hover":      "#3a3a3a",
        "dlg_nav_dis":        "#1e1e1e",
        "dlg_nav_dis_fg":     "#444444",
        "dlg_nav_dis_bdr":    "#333333",
        "dlg_nav_border":     "#555555",
        "dlg_nav_accent":     "#9cdcfe",
        "dlg_info_fg":        "#9a9a9a",
        "dlg_nav_fg":         "#9cdcfe",
        # Character-count indicator (traffic light)
        "dlg_count_ok":       "#4CAF50",
        "dlg_count_warn":     "#FFB300",
        "dlg_count_concern":  "#E53935",
    },
    "light": {
        # QPalette
        "pal_window":         "#f0f0f0",
        "pal_window_text":    "#1e1e1e",
        "pal_base":           "#ffffff",
        "pal_alt_base":       "#f5f5f5",
        "pal_text":           "#1e1e1e",
        "pal_button":         "#e0e0e0",
        "pal_button_text":    "#1e1e1e",
        "pal_highlight":      "#0078d4",
        "pal_hl_text":        "#ffffff",
        "pal_tooltip_base":   "#fffbcc",
        "pal_tooltip_text":   "#1e1e1e",
        # Main window QSS
        "bg":                 "#f0f0f0",
        "bg2":                "#ffffff",
        "bg3":                "#e8e8e8",
        "bg4":                "#ffffff",
        "fg":                 "#1e1e1e",
        "fg_dim":             "#666666",
        "border":             "#cccccc",
        "border2":            "#aaaaaa",
        "accent":             "#0078d4",
        "sel_bg":             "#0078d4",
        "sel_fg":             "#ffffff",
        "header_fg":          "#0050a0",
        "grid":               "#dddddd",
        "sb_bg":              "#0078d4",
        "sb_fg":              "#ffffff",
        "sep":                "#cccccc",
        # Bands, row hover and AA-safe text colours (spec 2026-09-21-ui-ux-refresh)
        "bar_border":         "#b8b8b8",
        "hover_row":          "#dbe7f5",
        "text_ok":            "#256B2A",
        "text_warn":          "#8A5A00",
        "text_bad":           "#C62828",
        # EditDialog QSS
        "dlg_bg":             "#f5f5f5",
        "dlg_src_bg":         "#e8eaf6",
        "dlg_src_fg":         "#555555",
        "dlg_edit_bg":        "#ffffff",
        "dlg_btn_bg":         "#0078d4",
        "dlg_btn_hover":      "#106ebe",
        "dlg_btn_dis":        "#c8c8c8",
        "dlg_btn_dis_fg":     "#888888",
        "dlg_nav_bg":         "#e8e8e8",
        "dlg_nav_hover":      "#d0d0d0",
        "dlg_nav_dis":        "#f0f0f0",
        "dlg_nav_dis_fg":     "#aaaaaa",
        "dlg_nav_dis_bdr":    "#dddddd",
        "dlg_nav_border":     "#aaaaaa",
        "dlg_nav_accent":     "#0050a0",
        "dlg_info_fg":        "#666666",
        "dlg_nav_fg":         "#0050a0",
        # Character-count indicator (traffic light)
        "dlg_count_ok":       "#2E7D32",
        "dlg_count_warn":     "#E68A00",
        "dlg_count_concern":  "#C62828",
    },
}


_CHECKBOX_INDICATOR_PX = 24


def _prominent_checkbox_qss(t: dict) -> str:
    """QSS for the large accent-colored 'prominent' checkbox indicator,
    selected via the filterChk dynamic property. Shared by MainWindow and
    every dialog that opts a checkbox into this style. The tick is a PNG file
    (see _write_glyph_pngs): the inline SVG data: URI it used to be renders
    nothing in a style sheet, which left a checked box a plain accent square. A
    checked, disabled box gets its own dimmed tick, or the white one would
    persist on the grey disabled fill and make the box look enabled. If the
    files can't be written the box degrades to that plain square."""
    px = _CHECKBOX_INDICATOR_PX
    marks = _write_glyph_pngs(lambda: {
        "check": _render_check_mark_png(t["sel_fg"], px * _GLYPH_SUPERSAMPLE),
        "check_disabled": _render_check_mark_png(t["dlg_btn_dis_fg"], px * _GLYPH_SUPERSAMPLE)})
    mark_rules = "" if marks is None else f"""
        QCheckBox[filterChk="true"]::indicator:checked {{ image: url("{marks['check']}"); }}
        QCheckBox[filterChk="true"]::indicator:checked:disabled {{
            image: url("{marks['check_disabled']}"); }}
    """
    return f"""
        QCheckBox[filterChk="true"]::indicator {{
            width: {px}px; height: {px}px;
            border: 2px solid {t['border2']};
            border-radius: 4px;
            background: {t['bg4']};
        }}
        QCheckBox[filterChk="true"]::indicator:hover,
        QCheckBox[filterChk="true"]::indicator:focus {{
            border-color: {t['accent']};
        }}
        QCheckBox[filterChk="true"]::indicator:checked {{
            background: {t['accent']};
            border-color: {t['accent']};
        }}
        QCheckBox[filterChk="true"]::indicator:checked:focus {{
            border-color: {t['fg']};
        }}
        QCheckBox[filterChk="true"]::indicator:disabled {{
            background: {t['dlg_btn_dis']}; border-color: {t['border']};
        }}
        {mark_rules}
    """


def _table_qss(t: dict, pt: int, gridline: Optional[str] = None) -> str:
    """QSS for data grids -- the main table and the table/tree of every data dialog -- so they
    share one look: bg2 rows, bg3 alternate rows and header, the selection colours, and header
    rules that also colour the empty part of the header rows and the table corner (left
    unstyled, those fall through to the window canvas colour as near-black strips). Dialogs pass
    gridline=t['border'] while the main table uses t['grid'] -- a spec-mandated difference, not
    an inconsistency."""
    grid = gridline or t["grid"]
    return f"""
        QTableView, QTableWidget, QTreeWidget {{
            background: {t['bg2']}; color: {t['fg']};
            alternate-background-color: {t['bg3']};
            selection-background-color: {t['sel_bg']};
            selection-color: {t['sel_fg']};
            gridline-color: {grid}; border: none; }}
        QHeaderView {{ background: {t['bg3']}; }}
        QHeaderView::section {{ background: {t['bg3']}; color: {t['header_fg']};
                                border: none; border-right: 1px solid {t['border']};
                                padding: 5px; font-weight: bold; font-size: {pt}pt; }}
        QTableCornerButton::section {{ background: {t['bg3']}; border: none; }}
    """


def _band_qss(t: dict, pt_small: int) -> str:
    """QSS for the bands that frame data: the main window's filter bar and the header, footer and
    status bands of the data dialogs. All sit on the canvas colour (bg) with a bar_border line; the
    filter bar and header band add a 2 px accent line on top. Also the filter bar's captions,
    dividers and the accent border on a field whose filter is active. The slim padding on the
    bar's buttons keeps the bar compact; the shared 5px 14px button padding would make it taller."""
    return f"""
        QFrame#filterBar, QFrame#dlgHeaderBand {{
            background: {t['bg']}; border: none;
            border-top: 2px solid {t['accent']};
            border-bottom: 1px solid {t['bar_border']}; }}
        QFrame#dlgFooterBand, QFrame#dlgStatusBar {{
            background: {t['bg']}; border: none;
            border-top: 1px solid {t['bar_border']}; }}
        QFrame#dlgStatusBar QLabel {{ color: {t['fg_dim']}; font-size: {pt_small}pt; }}
        QFrame#filterDivider {{ color: {t['bar_border']}; }}
        QFrame#filterBar QPushButton {{ padding: 4px 12px; }}
        QLabel[filterCaption="true"] {{ color: {t['header_fg']}; font-size: {pt_small}pt; }}
        QLabel#filterActiveDot {{ color: {t['accent']}; font-size: {pt_small}pt; }}
        QLineEdit[active="true"], QComboBox[active="true"], QDateEdit[active="true"] {{
            border: 1px solid {t['accent']}; }}
    """


def _button_qss(t: dict, pt: int) -> str:
    """Shared QPushButton look for the main window and every dialog: neutral by default,
    role="primary" (filled blue) and role="danger" (red outline) through a dynamic property, the
    same way filterChk selects the prominent checkbox. Every state keeps a 1 px border so a
    button never changes size, and every variant shows keyboard focus with its own border
    colour: accent on neutral and danger buttons, sel_fg on primary, whose fill is already
    accent blue (identical to the accent in the light theme). Each role needs its own :focus
    rule: a [role] rule ties with plain :focus on specificity and is declared after it, so it
    would otherwise win the border."""
    return f"""
        QPushButton {{ background: {t['bg4']}; color: {t['fg']};
                       border: 1px solid {t['border2']}; border-radius: 3px;
                       padding: 5px 14px; font-size: {pt}pt; }}
        QPushButton:hover {{ background: {t['dlg_nav_hover']}; border-color: {t['accent']}; }}
        QPushButton:pressed {{ background: {t['accent']}; color: {t['sel_fg']}; }}
        QPushButton:focus {{ border: 1px solid {t['accent']}; }}
        QPushButton:disabled {{ background: {t['dlg_btn_dis']}; color: {t['dlg_btn_dis_fg']};
                                border: 1px solid {t['border']}; }}
        QPushButton[role="primary"] {{ background: {t['dlg_btn_bg']}; color: {t['sel_fg']};
                                       border: 1px solid {t['dlg_btn_bg']}; }}
        QPushButton[role="primary"]:hover {{ background: {t['dlg_btn_hover']};
                                             border: 1px solid {t['dlg_btn_hover']}; }}
        QPushButton[role="primary"]:focus {{ border: 1px solid {t['sel_fg']}; }}
        QPushButton[role="primary"]:pressed {{ background: {t['dlg_btn_hover']}; color: {t['sel_fg']};
                                               border: 1px solid {t['dlg_btn_hover']}; }}
        QPushButton[role="primary"]:disabled {{ background: {t['dlg_btn_dis']};
                                                color: {t['dlg_btn_dis_fg']};
                                                border: 1px solid {t['border']}; }}
        QPushButton[role="danger"] {{ color: {t['text_bad']};
                                      border: 1px solid {t['dlg_count_concern']}; }}
        QPushButton[role="danger"]:hover {{ background: {t['text_bad']}; color: {t['bg']};
                                            border: 1px solid {t['text_bad']}; }}
        QPushButton[role="danger"]:focus {{ border: 1px solid {t['accent']}; }}
        QPushButton[role="danger"]:pressed  {{ background: {t['text_bad']}; color: {t['bg']};
                                               border: 1px solid {t['text_bad']}; }}
        QPushButton[role="danger"]:disabled {{ background: {t['dlg_btn_dis']};
                                               color: {t['dlg_btn_dis_fg']};
                                               border: 1px solid {t['border']}; }}
    """


def _field_state_qss(t: dict) -> str:
    """Focus ring and disabled look for inputs, interpolated AFTER each surface's own base input
    rules so every dialog and the main window behave the same. A widget's own stylesheet beats an
    inherited one, so these cannot live only in the main window's stylesheet. There is no
    QSpinBox:focus rule on purpose: a spin box with no base rule of its own (Shortcuts' delay box)
    is drawn natively, and matching it while focused switches it to style-sheet rendering, which
    drops its arrow glyphs."""
    return f"""
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
        QDateEdit:focus {{ border: 1px solid {t['accent']}; }}
        QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled {{
            background: {t['dlg_btn_dis']}; color: {t['dlg_btn_dis_fg']};
            border: 1px solid {t['border']}; }}
        QCheckBox:disabled {{ color: {t['dlg_btn_dis_fg']}; }}
    """


def _groupbox_qss(t: dict, pt: int) -> str:
    """Group-box frame and title, measured from the UI font at `pt`. The title sits in the box's
    top margin from y = 0, one font height tall; the border line is drawn at y = margin-top, so
    margin-top puts it through the middle of the title's capitals, and padding-top starts the
    contents under the title (the box's layout margin adds the gap). Fixed pixels (margin 6,
    padding 4) put the line along the top of a 14 pt title and let the title hang into the first
    row."""
    font = QFont(QApplication.font())
    font.setPointSize(pt)
    fm = QFontMetrics(font)
    margin_top = round(fm.ascent() - fm.capHeight() / 2)
    padding_top = max(0, fm.height() - margin_top - 1)   # 1 = the border line itself
    return f"""
        QGroupBox {{ color: {t['header_fg']}; border: 1px solid {t['border']};
                     border-radius: 4px; margin-top: {margin_top}px;
                     padding-top: {padding_top}px; font-size: {pt}pt; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 8px; }}
    """


_SCROLLBAR_ARROW_ROTATIONS = {"up": 0, "right": 90, "down": 180, "left": 270}
# A glyph is drawn 4x larger than the box it fills and scaled down by the style sheet, which keeps
# it crisp on a display scaled above 100 % (a 1x image is bilinear-upscaled and visibly soft).
_GLYPH_SUPERSAMPLE = 4
# Minimum handle length in multiples of the bar thickness: a short bar (the Edit dialog's 100 px
# source box) cannot afford more than 2x -- at UI fonts of 12 pt and up a 4x handle filled the
# whole groove and could not move -- but thousands of table rows shrink the handle to a sliver,
# so item views get 4x.
_SCROLLBAR_HANDLE_FACTOR = 2
_SCROLLBAR_LIST_HANDLE_FACTOR = 4


def _glyph_cache_dir() -> Path:
    """Per-user cache folder for the glyph PNGs that style sheets reference (scrollbar arrows,
    check marks), deliberately not under %TEMP%: TEMP can point at a shared, writable folder, and
    what is written here is handed to Qt's image decoder."""
    base = QStandardPaths.writableLocation(QStandardPaths.GenericCacheLocation)
    if not base:
        raise OSError("no per-user cache location")
    return Path(base) / "JSONTranslationEditor" / "glyphs"


def _encode_png(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise OSError("could not encode glyph PNG")
    return bytes(buffer.data())


def _render_check_mark_png(color: str, px: int) -> bytes:
    """One px x px PNG of a check mark: a three-point polyline on a 16-unit grid (3,8.5 6.5,12
    13,4), 1.4 units wide with round caps and joins -- about the stroke of the filter bar's ✕
    (2.5 units read as heavy next to it)."""
    image = QImage(px, px, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    scale = px / 16
    pen = QPen(QColor(color), 1.4 * scale)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(pen)
    painter.drawPolyline(QPolygonF([QPointF(3 * scale, 8.5 * scale), QPointF(6.5 * scale, 12 * scale),
                                    QPointF(13 * scale, 4 * scale)]))
    painter.end()
    return _encode_png(image)


def _render_reset_icon(color: str, px: int) -> QImage:
    """A clockwise circular arrow on a 16-unit grid: an arc of radius 5.5 around (8,8) running
    300 degrees clockwise from 20 degrees, with the check mark's 1.4-unit stroke, and a filled
    arrowhead where it ends at the top. Painted rather than the ⟳ character, which Segoe UI lacks:
    Windows substitutes a symbol font that draws it smaller and lower than the label beside it."""
    image = QImage(px, px, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    scale = px / 16
    radius = 5.5
    pen = QPen(QColor(color), 1.4 * scale)
    pen.setCapStyle(Qt.FlatCap)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(pen)
    painter.drawArc(QRectF((8 - radius) * scale, (8 - radius) * scale,
                           2 * radius * scale, 2 * radius * scale), 20 * 16, -300 * 16)
    end = math.radians(80)
    arc_x, arc_y = 8 + radius * math.cos(end), 8 - radius * math.sin(end)
    ahead_x, ahead_y = math.sin(end), math.cos(end)       # clockwise tangent, screen coordinates
    out_x, out_y = math.cos(end), -math.sin(end)          # radial, pointing away from the centre
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPolygon(QPolygonF([
        QPointF((arc_x + 2.6 * ahead_x) * scale, (arc_y + 2.6 * ahead_y) * scale),
        QPointF((arc_x + 2.2 * out_x - 0.4 * ahead_x) * scale, (arc_y + 2.2 * out_y - 0.4 * ahead_y) * scale),
        QPointF((arc_x - 2.2 * out_x - 0.4 * ahead_x) * scale, (arc_y - 2.2 * out_y - 0.4 * ahead_y) * scale),
    ]))
    painter.end()
    return image


def _render_history_icon(color: str, px: int, dot: Optional[str] = None) -> QImage:
    """The info bar's message-history glyph on a 16-unit grid: three lines (y 4.5, 8 and 11.5,
    x 3 to 13) with the check mark's 1.4-unit stroke. With *dot*, a filled circle of that colour
    (radius 2.5 at 13,3) marks an unseen warning or error; a transparent ring cut around it keeps
    it clear of the top line."""
    image = QImage(px, px, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    scale = px / 16
    pen = QPen(QColor(color), 1.4 * scale)
    pen.setCapStyle(Qt.RoundCap)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(pen)
    for y in (4.5, 8, 11.5):
        painter.drawLine(QPointF(3 * scale, y * scale), QPointF(13 * scale, y * scale))
    if dot:
        centre = QPointF(13 * scale, 3 * scale)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))   # any opaque brush: Clear only uses its shape
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.drawEllipse(centre, 3.6 * scale, 3.6 * scale)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setBrush(QColor(dot))
        painter.drawEllipse(centre, 2.5 * scale, 2.5 * scale)
    painter.end()
    return image


def _render_scrollbar_arrow_png(angle: int, color: str, px: int, fill: float = 0.27) -> bytes:
    """One px x px PNG of an up-pointing triangle rotated by *angle* degrees; *fill* is its
    half-width as a fraction of px. Shared by the scrollbar and spin-box arrows."""
    image = QImage(px, px, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    half = px * fill
    mid = px / 2
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.translate(mid, mid)
    painter.rotate(angle)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPolygon(QPolygonF([QPointF(-half, half / 2), QPointF(half, half / 2),
                                   QPointF(0, -half / 2)]))
    painter.end()
    return _encode_png(image)


def _file_holds(path: Path, data: bytes) -> bool:
    return path.is_file() and path.read_bytes() == data


def _write_glyph_pngs(render: Callable[[], Dict[str, bytes]]) -> Optional[Dict[str, str]]:
    """Write the PNGs *render* returns ({name: PNG bytes}) to the glyph cache folder and return
    {name: QSS-ready path}, or None if they can't be produced. QSS cannot draw a glyph itself: a
    data: URI renders nothing, and a border-triangle renders as a solid square. The file name
    carries a hash of the PNG bytes, so a changed colour, size or drawing gets a new file. An
    existing file is rewritten only when its bytes differ (a corrupt or planted one), so a healthy
    file that another running instance may be reading is never touched -- and losing the
    os.replace() race to such an instance is not a failure, its file is identical."""
    # Any failure here -- disk, permissions, a PySide API change -- only costs blank arrow buttons
    # or a tick-less checkbox, so none may stop the app starting.
    try:
        pngs = render()
        directory = _glyph_cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        paths = {}
        for name, data in pngs.items():
            digest = hashlib.md5(data, usedforsecurity=False).hexdigest()[:12]
            path = directory / f"{name}_{digest}.png"
            if not _file_holds(path, data):
                try:
                    _atomic_write_bytes(path, data)
                except OSError:
                    if not _file_holds(path, data):
                        raise
            paths[name] = path.as_posix()
        return paths
    except Exception as e:
        _log_error("glyph images", e)
        return None


def _write_scrollbar_arrows(color: str, px: int) -> Optional[Dict[str, str]]:
    """Paths of the four arrow glyphs keyed arrow_up/arrow_down/arrow_left/arrow_right."""
    return _write_glyph_pngs(lambda: {
        f"arrow_{name}": _render_scrollbar_arrow_png(angle, color, px * _GLYPH_SUPERSAMPLE)
        for name, angle in _SCROLLBAR_ARROW_ROTATIONS.items()})


def _scrollbar_qss(t: dict, px: int) -> str:
    """The one QScrollBar look, inherited by every window. The bar reserves *px* of margin at
    both ends for the arrow buttons and the buttons are positioned explicitly: without that the
    style sheet lays the handle out over the whole bar, so at either end it sat on top of the
    arrow. Styling the buttons also stops Qt drawing its own glyphs, hence the arrow images. If
    they can't be written the buttons stay (correctly placed) but blank. The handle has a
    minimum length in both directions so it stays grabbable on a very long table; see
    _SCROLLBAR_HANDLE_FACTOR for why item views get a larger one."""
    handle_min = px * _SCROLLBAR_HANDLE_FACTOR
    list_handle_min = px * _SCROLLBAR_LIST_HANDLE_FACTOR
    arrows = _write_scrollbar_arrows(t["fg_dim"], px)
    arrow_rules = "" if arrows is None else "\n".join(
        f'QScrollBar::{name}-arrow:{orientation} {{ image: url("{arrows["arrow_" + name]}");'
        f' width: {px}px; height: {px}px; }}'
        for name, orientation in (("up", "vertical"), ("down", "vertical"),
                                  ("left", "horizontal"), ("right", "horizontal")))
    return f"""
        QScrollBar:vertical   {{ background: {t['bg3']}; width: {px}px; margin: {px}px 0 {px}px 0; }}
        QScrollBar:horizontal {{ background: {t['bg3']}; height: {px}px; margin: 0 {px}px 0 {px}px; }}
        QScrollBar::handle:vertical   {{ background: {t['border2']}; border-radius: {px // 2}px;
                                         min-height: {handle_min}px; }}
        QScrollBar::handle:horizontal {{ background: {t['border2']}; border-radius: {px // 2}px;
                                         min-width: {handle_min}px; }}
        QAbstractItemView QScrollBar::handle:vertical   {{ min-height: {list_handle_min}px; }}
        QAbstractItemView QScrollBar::handle:horizontal {{ min-width: {list_handle_min}px; }}
        QScrollBar::add-line:vertical   {{ background: {t['bg3']}; border: none; height: {px}px;
                                           subcontrol-position: bottom; subcontrol-origin: margin; }}
        QScrollBar::sub-line:vertical   {{ background: {t['bg3']}; border: none; height: {px}px;
                                           subcontrol-position: top; subcontrol-origin: margin; }}
        QScrollBar::add-line:horizontal {{ background: {t['bg3']}; border: none; width: {px}px;
                                           subcontrol-position: right; subcontrol-origin: margin; }}
        QScrollBar::sub-line:horizontal {{ background: {t['bg3']}; border: none; width: {px}px;
                                           subcontrol-position: left; subcontrol-origin: margin; }}
        {arrow_rules}
    """


# Half-width of a spin-box arrow as a fraction of its image box: 0.4 makes the triangle 80 % of the
# box wide, against the scrollbar's 54 %, because a spin button is the only cue the control has.
_SPIN_ARROW_FILL = 0.4


def _write_spin_arrows(color: str, disabled_color: str, px: int) -> Optional[Dict[str, str]]:
    """Paths of the spin-box arrows keyed up/down/up_disabled/down_disabled."""
    return _write_glyph_pngs(lambda: {
        f"spin_{name}{suffix}": _render_scrollbar_arrow_png(
            angle, tint, px * _GLYPH_SUPERSAMPLE, _SPIN_ARROW_FILL)
        for name, angle in (("up", 0), ("down", 180))
        for suffix, tint in (("", color), ("_disabled", disabled_color))})


def _spinbox_qss(t: dict, pt: int) -> str:
    """Up/down buttons and arrows for a QSpinBox that has a base rule of its own (background,
    border, padding). Such a rule moves the whole widget to style-sheet rendering, where the
    unstyled buttons collapse to a 14 px strip holding a 3-4 px speck of an arrow that barely
    differs from the field. Interpolate it right after that base rule. A style sheet cannot draw the
    arrow itself, hence the PNGs (see _write_glyph_pngs); if they can't be written the buttons stay
    (correctly placed) but blank. The sizes follow the UI font like the scrollbar's do."""
    px = max(10, pt + 2)
    arrows = _write_spin_arrows(t["fg"], t["dlg_btn_dis_fg"], px)
    arrow_rules = "" if arrows is None else "\n".join(
        f'QSpinBox::{name}-arrow{state} {{ image: url("{arrows["spin_" + name + suffix]}");'
        f' width: {px}px; height: {px}px; }}'
        for name in ("up", "down")
        for state, suffix in (("", ""), (":disabled", "_disabled")))
    return f"""
        QSpinBox::up-button, QSpinBox::down-button {{
            background: {t['bg3']}; border: none; width: {px + 2}px;
            subcontrol-origin: padding; }}
        QSpinBox::up-button   {{ subcontrol-position: top right;
                                 border-top-right-radius: 2px; }}
        QSpinBox::down-button {{ subcontrol-position: bottom right;
                                 border-bottom-right-radius: 2px; }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {t['border2']}; }}
        QSpinBox::up-button:disabled, QSpinBox::down-button:disabled {{
            background: {t['dlg_btn_dis']}; }}
        {arrow_rules}
    """


def _write_combo_arrows(color: str, disabled_color: str, px: int) -> Optional[Dict[str, str]]:
    """Paths of the drop-down arrows keyed combo_down/combo_down_disabled -- the same triangle as
    the spin boxes' (_SPIN_ARROW_FILL)."""
    return _write_glyph_pngs(lambda: {
        f"combo_down{suffix}": _render_scrollbar_arrow_png(
            180, tint, px * _GLYPH_SUPERSAMPLE, _SPIN_ARROW_FILL)
        for suffix, tint in (("", color), ("_disabled", disabled_color))})


def _combobox_qss(t: dict, pt: int) -> str:
    """Drop-down arrow and popup for a QComboBox that has a base rule of its own (background,
    border, padding), plus the arrow of the filter bar's QDateEdit pickers. Such a rule moves the
    widget to style-sheet rendering, where the unstyled drop-down keeps a 6 px speck of an arrow in
    a separated strip with a bevel artefact. The popup has its own defect: Fusion draws a styled
    combo's popup in menu style, which ignores `::item` rules, so the hovered row was a faint grey
    (dark) or a white row with a grey outline (light). `combobox-popup: 0` makes it a plain list,
    whose rows can then take the selection colour -- but a list popup is only as wide as its combo,
    hence _WidePopupComboBox, which every combo in the app must be (bar the QFontComboBox).
    Interpolate it right after the base rule. A style sheet cannot draw the arrow itself, hence the
    PNGs (see _write_glyph_pngs); if they can't be written the drop-down stays (correctly placed)
    but blank. The arrow follows the UI font. The strip is Fusion's own 16 px wide, growing only
    when the arrow needs more, because its width comes out of the field's text room and the Backup
    location combo and the filter bar's date pickers are already tight."""
    px = max(10, pt + 2)
    strip = max(16, round(2 * _SPIN_ARROW_FILL * px) + 4)
    arrows = _write_combo_arrows(t["fg"], t["dlg_btn_dis_fg"], px)
    arrow_rules = "" if arrows is None else "\n".join(
        f'{widget}::down-arrow{state} {{ image: url("{arrows["combo_down" + suffix]}");'
        f' width: {px}px; height: {px}px; }}'
        for widget in ("QComboBox", "QDateEdit")
        for state, suffix in (("", ""), (":disabled", "_disabled")))
    return f"""
        QComboBox {{ combobox-popup: 0; }}
        QComboBox::drop-down, QDateEdit::drop-down {{
            subcontrol-origin: padding; subcontrol-position: center right;
            width: {strip}px; border: none; }}
        QComboBox QAbstractItemView {{ border: 1px solid {t['border2']}; outline: 0; }}
        QComboBox QAbstractItemView::item {{ min-height: {pt * 2 + 4}px; padding: 0 8px; }}
        QComboBox QAbstractItemView::item:hover,
        QComboBox QAbstractItemView::item:selected {{
            background: {t['sel_bg']}; color: {t['sel_fg']}; }}
        {arrow_rules}
    """


# ══════════════════════════════════════════════════════════════
#  SETTINGS BACKUP
# ══════════════════════════════════════════════════════════════

# Archive entries end in a timestamp; the date group is what the
# once-a-day rule compares.
_SETTINGS_SNAPSHOT_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}-\d{2}\.json$")


def _parse_settings_bytes(raw: bytes) -> dict:
    """Decode *raw* as a settings file. Raises ValueError (JSONDecodeError and
    UnicodeDecodeError are both subclasses) unless it holds a JSON object.
    utf-8-sig so a hand-edit saved with a BOM still loads.
    """
    loaded = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(loaded, dict):
        raise ValueError("settings file is not a JSON object")
    return loaded


def _settings_archive_path(settings_path: Path) -> Path:
    return settings_path.resolve().with_suffix(".backups.zip")


def _read_settings_archive(archive_path: Path) -> List[Tuple[str, bytes]]:
    """Snapshots as (entry_name, raw_bytes) in the order they were written,
    oldest first. A missing archive is []. A damaged one is moved aside as
    <name>.corrupt -- kept for inspection, but it must never stop new backups --
    and also reads as [].
    """
    if not archive_path.exists():
        return []
    try:
        with zipfile.ZipFile(archive_path) as zf:
            # Write order, not name order: it stays chronological even if the
            # clock briefly ran wrong and left a future-dated entry behind.
            names = [n for n in zf.namelist() if _SETTINGS_SNAPSHOT_RE.search(n)]
            return [(n, zf.read(n)) for n in names]
    # Corruption, or an entry re-saved by another tool with encryption or an
    # unsupported compression method. Not OSError: a transient lock must not
    # trigger the move-aside.
    except (zipfile.BadZipFile, zlib.error, EOFError,
            NotImplementedError, RuntimeError) as e:
        _log_error("settings archive damaged", e)
        try:
            os.replace(archive_path, archive_path.with_name(archive_path.name + ".corrupt"))
        except OSError as move_error:
            # Can't keep it either; the next successful write replaces it
            # anyway, and a stuck .corrupt file must not stop backups.
            _log_error("settings archive: keep damaged copy", move_error)
        return []


def _write_settings_archive(archive_path: Path, snapshots: List[Tuple[str, bytes]]) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, raw in snapshots:
            zf.writestr(name, raw)
    _atomic_write_bytes(archive_path, buf.getvalue())


def _newest_valid_settings_snapshot(archive_path: Path) -> Optional[Tuple[str, bytes, dict]]:
    """Newest archived snapshot that still parses, as (name, raw, parsed)."""
    for name, raw in reversed(_read_settings_archive(archive_path)):
        try:
            return name, raw, _parse_settings_bytes(raw)
        except ValueError:
            continue
    return None


def backup_settings_daily(settings_path: Path, now: Optional[datetime] = None) -> None:
    """Add a snapshot of *settings_path* to the .backups.zip beside it, unless
    one already exists for today's date, keeping the newest SETTINGS_BACKUP_MAX.
    Entries are the file's exact bytes, so restoring one by hand is an
    extract-and-rename. A file that doesn't parse is never archived, so damage
    can't push good snapshots out. Best-effort: logs and returns on any
    failure, so it can never block startup.
    """
    now = now or datetime.now()
    try:
        if not settings_path.exists():
            return
        raw = settings_path.read_bytes()
        _parse_settings_bytes(raw)
        archive_path = _settings_archive_path(settings_path)
        snapshots = _read_settings_archive(archive_path)
        # Any entry, not just the newest: a future-dated one (clock briefly
        # wrong) would otherwise hide today's snapshot forever and each launch
        # would add another, pruning the real history.
        today = f"{now:%Y-%m-%d}"
        if any(_SETTINGS_SNAPSHOT_RE.search(name).group(1) == today
               for name, _ in snapshots):
            return
        snapshots.append((f"{settings_path.stem}_{now:%Y-%m-%d_%H-%M-%S}.json", raw))
        _write_settings_archive(archive_path, snapshots[-SETTINGS_BACKUP_MAX:])
    except Exception as e:
        _log_error("backup_settings_daily", e)


class Settings:
    DEFAULTS = {
        "font_family": "Segoe UI",
        "font_size": 10,
        "last_directory": "",
        "window_geometry": None,
        "theme": "dark",
        "skip_translator_prompt": False,  # skip TranslatorNameDialog on startup
        "shortcuts": {
            "edit_prev":      "Alt+Left",
            "edit_next":      "Alt+Right",
            "edit_cancel":    "Escape",
            "edit_save":      "Alt+S",
            "auto_translate": "Alt+A",
            "robo_translate": "Shift+Alt+A",
            "mark_new":       "Alt+N",
            "mark_review":    "Alt+R",
            "mark_complete":  "Alt+C",
            "delete_entries": "Ctrl+Del",
        },
        "filter_from_date": "01.01.2025",  # persisted From-date for the filter panel
        "search": {
            "mode":         "starts_with",  # "contains" | "starts_with"
            "field":        "both",         # "both" | "source" | "translated"
            "debounce_ms":  150,            # ms after the last keystroke in the
                                             # search/translator boxes before
                                             # re-filtering; no dedicated UI —
                                             # hand-edit this file to change
        },
        "translation": {
            "engine":              "none",   # "none" | "claude" | "claude_subscription" | "deepl" | "libretranslate" | "google_dt" | "mymemory_dt" | "microsoft_dt"
            "claude_api_key":      "",
            "claude_model":        "claude-haiku-4-5-20251001",
            "claude_subscription_token": "",
            "deepl_api_key":       "",
            "deepl_free":          True,     # True = api-free.deepl.com, False = api.deepl.com
            "libretranslate_url":  "https://libretranslate.com",
            "libretranslate_key":  "",
            "mymemory_email":      "",
            "microsoft_api_key":   "",
            "microsoft_region":    "",
            "glossary_enabled":    True,   # apply the per-file glossary to Claude engines
        },
        # Robo-Translate: auto-translate-and-advance chain (EditDialog).
        "robo_translate": {
            "delay_seconds": 10,   # seconds to wait after a translate before advancing
        },
        # Character-count length indicator (EditDialog).  Two-zone piecewise:
        # short sources (<= short_text_max) use the short_* percentages with
        # min_warn / min_concern as absolute floors; long sources use the
        # long_* percentages.  Indicator only triggers when translation length
        # exceeds source length (delta > 0).
        "char_count": {
            "enabled":            True,
            "short_text_max":     30,    # boundary in chars between short and long zones
            "short_warn_pct":     0.13,  # short-zone warning  threshold (fraction of src)
            "short_concern_pct":  0.30,  # short-zone concern  threshold
            "long_warn_pct":      0.10,  # long-zone  warning  threshold
            "long_concern_pct":   0.25,  # long-zone  concern  threshold
            "min_warn":           1,     # absolute floor for very short sources
            "min_concern":        2,     # absolute floor for very short sources
        },
        # Column widths keyed by str(column_index).
        # COL_SRC (1) and COL_TRANS (2) use Stretch mode; their saved
        # width is applied as an initial hint before stretch kicks in.
        "column_widths": {
            "0":  45,    # #  (index)
            "1": 280,    # Source Text
            "2": 280,    # Translated Text
            "3":  90,    # Status
            "4": 120,    # Translator
            "5":  95,    # Date
        },
        # NOTE: "autosave" and "backup" settings dicts are managed entirely
        # by AutosaveBackupDialog via inline literal defaults (e.g.
        # bk_cfg.get("enabled", True)) rather than through this DEFAULTS
        # dict -- this single key follows that same pattern in the dialog
        # itself; it's listed here only for discoverability.
        "backup": {
            "restore_glossary_default": False,
            "location_mode":            "both",  # "next_to_file" | "root" | "both"
            "known_next_to_file_dirs":  [],       # discoverability only; see _remember_next_to_file_backup_dir
            "min_interval_minutes":     5,        # 0 = back up on every open
        },
    }

    def __init__(self):
        self.data: dict = {}
        # Set by load() when it had to replace an unreadable settings file;
        # MainWindow shows it once at startup.
        self.recovery_notice: str = ""
        # (text, level) info-bar messages about how the file was loaded; MainWindow posts them
        # after the startup dialogs, so they also land in the message history.
        self.startup_notices: List[Tuple[str, str]] = []
        self.load()

    def load(self):
        self.data = deepcopy(self.DEFAULTS)
        if not SETTINGS_FILE.exists():
            # Deleting the file is the documented reset, so this is no error; a first launch
            # shows it too.
            self.startup_notices.append(("Settings file not found — default settings in use", "warning"))
            return
        try:
            loaded = _parse_settings_bytes(SETTINGS_FILE.read_bytes())
        except ValueError as e:
            # Unparseable content is real damage. An OSError (locked file,
            # permissions) is not -- the content may be fine -- so it takes
            # the log-and-defaults path below instead of being moved aside.
            _log_error("Settings.load", e)
            loaded = self._recover_from_archive()
            if loaded is None:
                return
        except Exception as e:
            _log_error("Settings.load", e)
            self.startup_notices.append(
                ("Settings file could not be read — default settings in use for this session", "error"))
            return
        # One-level merge per top-level key: a nested-dict setting (e.g.
        # "search") keeps any DEFAULTS sub-key the loaded file doesn't have
        # (e.g. debounce_ms added by a later version) instead of the loaded
        # sub-dict wholesale-replacing it. Loaded values still always win
        # over defaults. Non-dict values replace as before.
        upgraded = False
        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(self.data.get(key), dict):
                merged = dict(self.data[key])
                merged.update(value)
                if merged != value:
                    upgraded = True
                self.data[key] = merged
            else:
                self.data[key] = value
        if upgraded:
            self.save()

    @staticmethod
    def _keep_damaged_file(aside: Path) -> bool:
        """Get the damaged settings file out of the next save's way by moving it
        to *aside*. A move fails while another process holds the file open, so
        fall back to a copy, which needs only read access. Returns True if the
        damaged content now exists at *aside*.
        """
        try:
            os.replace(SETTINGS_FILE, aside)
            return True
        except OSError as e:
            _log_error("Settings.load: move damaged file aside", e)
        try:
            shutil.copy2(SETTINGS_FILE, aside)
            return True
        except OSError as e:
            _log_error("Settings.load: copy damaged file aside", e)
            return False

    def _recover_from_archive(self) -> Optional[dict]:
        """SETTINGS_FILE exists but doesn't parse. Keep the damaged content as
        <name>.corrupt-<time> so a later save can't destroy it, then restore the
        newest archived snapshot that still parses. Returns the restored
        settings, or None when defaults must be used. Always sets
        recovery_notice, since damage was found either way.
        """
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        aside = SETTINGS_FILE.with_name(f"{SETTINGS_FILE.name}.corrupt-{stamp}")
        was_kept = self._keep_damaged_file(aside)
        kept = (f"The damaged file was kept as {aside.name}." if was_kept
                else "The damaged file could not be kept.")
        self.startup_notices.append((
            "Settings file was damaged and could not be read "
            + (f"(kept as {aside.name})" if was_kept else "(the damaged file could not be kept)"),
            "error"))
        try:
            snapshot = _newest_valid_settings_snapshot(_settings_archive_path(SETTINGS_FILE))
        except Exception as e:
            _log_error("Settings.load: read backup archive", e)
            snapshot = None
        if snapshot is None:
            self.recovery_notice = (
                "Your settings file could not be read and no backup was available, "
                f"so default settings are in use.\n\n{kept}")
            self.startup_notices.append(
                ("Default settings in use — API keys and preferences need to be set again", "warning"))
            return None
        name, raw, loaded = snapshot
        try:
            _atomic_write_bytes(SETTINGS_FILE, raw)
        except OSError as e:
            _log_error("Settings.load: write restored settings", e)
        backup_date = _SETTINGS_SNAPSHOT_RE.search(name).group(1)
        self.recovery_notice = (
            "Your settings file could not be read, so it was restored from the "
            f"backup of {backup_date}.\n\n{kept}")
        self.startup_notices.append((f"Settings restored from the backup of {backup_date}", "warning"))
        return loaded

    def save(self):
        # Atomic so a crash mid-write can't leave a truncated file, which
        # load() would then discard as damaged.
        try:
            _atomic_write_bytes(
                SETTINGS_FILE,
                json.dumps(self.data, indent=2, ensure_ascii=False).encode("utf-8"),
            )
        except Exception as e:
            _log_error("Settings.save", e)

    def get(self, key: str, default=None):
        return self.data.get(key, default if default is not None else self.DEFAULTS.get(key))

    def set(self, key: str, value):
        self.data[key] = value

    def get_font(self) -> QFont:
        f = QFont(self.get("font_family"), self.get("font_size"))
        return f


# ══════════════════════════════════════════════════════════════
#  FILE PROPERTIES
# ══════════════════════════════════════════════════════════════

# Each part as the version has always held it (e.g. 4.1.1140); File -> Properties edits them in
# spin boxes limited to the same digit counts.
_VERSION_PARTS_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{1,5})$")
VERSION_PART_MAXIMA = (99, 99, 99999)
DISPLAY_LANGUAGE_MAX_LEN = 64   # keeps the info bar and title readable


def parse_version_parts(text: str) -> Optional[Tuple[int, int, int]]:
    """(major, minor, build) of a major.minor.build version, or None when *text* is not one."""
    m = _VERSION_PARTS_RE.match(text)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def format_version(parts: Tuple[int, int, int]) -> str:
    return ".".join(str(p) for p in parts)


def _file_label(name: str, version: str) -> str:
    """File name plus header version for info-bar messages. A missing version is named, since
    the file's backups then go under the plain, unversioned key."""
    return f"{name}  v{version}" if version else f"{name}  (no version)"


def describe_culture(culture: str) -> str:
    """'Latvian (Latvia)' for 'lv-LV' or 'lv_LV', 'Latvian' for a code with no region, '' for a
    code Qt does not know. A region-less code gets no territory because QLocale would guess one."""
    locale = QLocale(culture)
    if locale.language() == QLocale.C:
        return ""
    language = QLocale.languageToString(locale.language())
    if "-" not in culture and "_" not in culture:
        return language
    return f"{language} ({QLocale.territoryToString(locale.territory())})"


# ══════════════════════════════════════════════════════════════
#  JSON LANGUAGE FILE
# ══════════════════════════════════════════════════════════════

_BOM = b"\xef\xbb\xbf"
_FIRST_KEY_INDENT_RE = re.compile(r'\{\r?\n([ \t]+)"')
# A \uXXXX escape of a non-ASCII character (\u0080 and up), as json.dumps(ensure_ascii=True) writes.
_ESCAPED_NON_ASCII_RE = re.compile(r'\\u(?!00[0-7][0-9a-fA-F])[0-9a-fA-F]{4}')


@dataclass(frozen=True)
class JsonStyle:
    """How a language file is laid out, so a save writes it back the way it was found."""
    indent: Optional[str]   # one indent level; None = the whole object on one line
    newline: str            # "\n" or "\r\n"
    bom: bool
    trailing_newline: bool
    ensure_ascii: bool      # non-ASCII text written as \uXXXX escapes


DEFAULT_JSON_STYLE = JsonStyle(indent=" ", newline="\n", bom=False, trailing_newline=True,
                               ensure_ascii=False)


class JsonFormatError(ValueError):
    """A language file that is not one flat JSON object of text keys and text values. The message
    is shown to the user as is."""


class _JsonPairs(list):
    """The (key, value) pairs of one JSON object, in file order. A subclass, so a top-level JSON
    array (a plain list) is not mistaken for an object."""


def _pairs_without_duplicates(pairs: List[Tuple[str, object]]) -> "_JsonPairs":
    seen = set()
    for key, _value in pairs:
        if key in seen:
            raise JsonFormatError(f"Duplicate key: {key!r}")
        seen.add(key)
    return _JsonPairs(pairs)


def detect_json_style(text: str, bom: bool) -> JsonStyle:
    m = _FIRST_KEY_INDENT_RE.match(text)
    return JsonStyle(
        indent=m.group(1) if m else None,
        newline="\r\n" if "\r\n" in text else "\n",
        bom=bom,
        trailing_newline=text.endswith("\n"),
        ensure_ascii=text.isascii() and bool(_ESCAPED_NON_ASCII_RE.search(text)),
    )


def parse_json_bytes(raw: bytes) -> Tuple[List[Tuple[str, str]], JsonStyle]:
    """The file's (key, value) pairs in file order and its layout. Raises JsonFormatError for
    anything but one flat object of text values with unique keys -- json.loads alone would keep
    the last of two duplicate keys without a word."""
    bom = raw.startswith(_BOM)
    try:
        text = (raw[len(_BOM):] if bom else raw).decode("utf-8")
    except UnicodeDecodeError:
        raise JsonFormatError("The file is not UTF-8 text.") from None
    try:
        data = json.loads(text, object_pairs_hook=_pairs_without_duplicates)
    except json.JSONDecodeError as e:
        raise JsonFormatError(f"Not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}") from None
    if not isinstance(data, _JsonPairs):
        raise JsonFormatError('The file must hold one JSON object of "source": "translation" pairs.')
    for key, value in data:
        if not isinstance(value, str):
            raise JsonFormatError(f"The value of {key!r} is not text.")
    return list(data), detect_json_style(text, bom)


def dump_json_pairs(pairs: List[Tuple[str, str]], style: JsonStyle) -> bytes:
    """The language file as bytes in *style*. Raises ValueError when two pairs share a key, which
    would silently drop one of them."""
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("two entries share a key")
    text = json.dumps(obj, ensure_ascii=style.ensure_ascii, indent=style.indent)
    if style.trailing_newline:
        text += "\n"
    # json.dumps writes a line break inside a value as \n, so every raw newline here is layout.
    data = text.replace("\n", style.newline).encode("utf-8")
    return _BOM + data if style.bom else data


# ══════════════════════════════════════════════════════════════
#  SIDECAR  (<name>.json.meta: per-string status, translator, date, plus the file's header)
# ══════════════════════════════════════════════════════════════

META_SUFFIX = ".meta"   # not ".json": a program that loads every *.json in the folder must not see it
META_FORMAT = 1
LANGUAGE_CODE_RE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$")
# Stricter than the validator: a file name like es_restored_2026-... must not be read as a language.
_GUESSABLE_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,4})*$")


@dataclass
class FileHeader:
    """The sidecar's header: the language code ("" = guess it from the file name), its
    human-readable name and the file's version."""
    language: str = ""
    language_name: str = ""
    version: str = ""


class SidecarError(ValueError):
    """A sidecar that cannot be read as the metadata object."""


def meta_path_for(json_path: Path) -> Path:
    return json_path.with_name(json_path.name + META_SUFFIX)


def guess_language(json_path: Path) -> str:
    """'es' for es.json, 'pt-BR' for pt-BR.json, '' when the name is not a language code."""
    stem = json_path.stem
    return stem if _GUESSABLE_LANGUAGE_RE.match(stem) else ""


def effective_language(header: FileHeader, json_path: Optional[Path]) -> str:
    if header.language:
        return header.language
    return guess_language(json_path) if json_path is not None else ""


def parse_sidecar_bytes(raw: bytes) -> Tuple[FileHeader, Dict[str, Dict[str, str]]]:
    """The header and the per-key metadata, as stored. Raises SidecarError for anything else."""
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SidecarError(f"not readable as JSON ({e})") from None
    if not isinstance(data, dict):
        raise SidecarError("not a JSON object")
    if data.get("format", META_FORMAT) != META_FORMAT:
        raise SidecarError(f"format {data.get('format')!r} is not {META_FORMAT}")
    header_values = {}
    for key in ("language", "language_name", "version"):
        value = data.get(key, "")
        if not isinstance(value, str):
            raise SidecarError(f"{key} is not text")
        header_values[key] = value
    entries = data.get("entries", {})
    if not isinstance(entries, dict):
        raise SidecarError("entries is not an object")
    meta: Dict[str, Dict[str, str]] = {}
    for key, fields in entries.items():
        if not isinstance(fields, dict) or not all(isinstance(v, str) for v in fields.values()):
            raise SidecarError(f"the entry for {key!r} is not an object of text values")
        meta[key] = fields
    return FileHeader(**header_values), meta


def _date_from_sidecar(raw: str, bad_dates: List[str]) -> str:
    """An ISO date as this machine's short date; anything else kept as stored and recorded."""
    if not raw:
        return ""
    try:
        return format_date_for_storage(date.fromisoformat(raw))
    except ValueError:
        bad_dates.append(raw)
        return raw


def _date_to_sidecar(shown: str) -> str:
    if not shown:
        return ""
    parsed = parse_date(shown)
    return parsed.isoformat() if parsed is not None else shown


def apply_sidecar_meta(entries: List[StringEntry], meta: Dict[str, Dict[str, str]]) -> List[str]:
    """Give each entry listed in *meta* its status, translator and date (shown format). Returns the
    warning texts for the info bar."""
    names = set()
    unknown_status = 0
    bad_dates: List[str] = []
    for entry in entries:
        names.add(entry.name)
        fields = meta.get(entry.name)
        if fields is None:
            continue
        status = fields.get("status", "New")
        if status not in STATUSES:
            unknown_status += 1
            status = "New"
        entry.status = status
        entry.translator = fields.get("translator", "")
        entry.modify_date = _date_from_sidecar(fields.get("modified", ""), bad_dates)
    orphans = sum(1 for key in meta if key not in names)
    warnings = []
    if orphans:
        warnings.append(f"Metadata: {orphans} entries for keys no longer in the file")
    if unknown_status:
        warnings.append(f"Metadata: {unknown_status} unknown status value(s) read as New")
    if bad_dates:
        warnings.append(f"Metadata: {len(bad_dates)} unrecognized date(s) (e.g. {bad_dates[0]!r})")
    return warnings


def build_sidecar_bytes(entries: List[StringEntry], header: FileHeader) -> bytes:
    """The sidecar for *entries*: only entries whose metadata differs from a fresh one (New, no
    translator, no date) are listed, in file order, so its diffs line up with the language file's."""
    listed = {}
    for e in entries:
        if e.status != "New" or e.translator or e.modify_date:
            listed[e.name] = {"status": e.status, "translator": e.translator,
                              "modified": _date_to_sidecar(e.modify_date)}
    data = {"format": META_FORMAT, "language": header.language,
            "language_name": header.language_name, "version": header.version, "entries": listed}
    return (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def read_file_header(json_path: Path) -> FileHeader:
    """The sidecar's header, best-effort: a missing, unreadable or damaged sidecar gives an empty
    header. For backup manifests and messages about a file that may not be the open one."""
    try:
        header, _meta = parse_sidecar_bytes(meta_path_for(json_path).read_bytes())
        return header
    except (OSError, SidecarError):
        return FileHeader()


def entries_from_pairs(pairs: List[Tuple[str, str]]) -> List[StringEntry]:
    """Fresh entries for a language file's pairs: New, no translator, no date."""
    return [StringEntry(name=key, translator="", status="New", modify_date="", text=value,
                        position=i) for i, (key, value) in enumerate(pairs, start=1)]


def dump_json(entries: List[StringEntry], style: JsonStyle) -> bytes:
    return dump_json_pairs([(e.name, e.text) for e in entries], style)


@dataclass
class LoadedFile:
    entries: List[StringEntry]
    style: JsonStyle
    round_trips: bool                 # writing it back unchanged reproduces its bytes
    header: FileHeader
    notices: List[Tuple[str, str]]    # (text, level) for the info bar, in order
    meta_blocked: bool                # the sidecar exists but could not be read: never overwrite it


class MetadataWriteError(Exception):
    """The language file was saved but its sidecar was not."""


def _keep_damaged_sidecar(meta_path: Path) -> Optional[Path]:
    """Move a damaged sidecar aside so the next save cannot overwrite it; copy it when another
    process holds it (os.replace fails on a lock, a copy needs only read access). None if both fail."""
    aside = meta_path.with_name(f"{meta_path.name}.corrupt-{datetime.now():%Y-%m-%d_%H-%M-%S}")
    try:
        os.replace(meta_path, aside)
        return aside
    except OSError:
        try:
            shutil.copy2(meta_path, aside)
            return aside
        except OSError as e:
            _log_error(f"keeping damaged sidecar {meta_path}", e)
            return None


def load_translation_file(path: Path, keep_damaged: bool = True) -> LoadedFile:
    """Read a language file and its sidecar. Raises JsonFormatError or OSError for the language
    file itself; a missing sidecar means everything is New, a damaged one is moved aside (unless
    *keep_damaged* is False, as for a file merged from) and reported in the notices."""
    raw = path.read_bytes()
    pairs, style = parse_json_bytes(raw)
    entries = entries_from_pairs(pairs)
    round_trips = dump_json(entries, style) == raw
    header = FileHeader()
    notices: List[Tuple[str, str]] = []
    blocked = False
    meta_path = meta_path_for(path)
    try:
        meta_raw: Optional[bytes] = meta_path.read_bytes()
    except FileNotFoundError:
        meta_raw = None
    except OSError as e:
        _log_error(f"reading {meta_path}", e)
        notices.append((f"Metadata: {meta_path.name} could not be read — statuses shown as New, "
                        "and it will not be overwritten", "error"))
        meta_raw, blocked = None, True
    if meta_raw is not None:
        try:
            header, meta = parse_sidecar_bytes(meta_raw)
            notices.extend((w, "warning") for w in apply_sidecar_meta(entries, meta))
        except SidecarError as e:
            _log_error(f"damaged sidecar {meta_path}", e)
            if not keep_damaged:
                notices.append((f"Metadata: {meta_path.name} is damaged — statuses shown as New",
                                "error"))
            else:
                aside = _keep_damaged_sidecar(meta_path)
                if aside is None:
                    blocked = True
                    notices.append((f"Metadata: {meta_path.name} is damaged and could not be kept "
                                    "aside — statuses shown as New, and it will not be overwritten",
                                    "error"))
                else:
                    notices.append((f"Metadata: {meta_path.name} was damaged (kept as {aside.name}) "
                                    "— statuses shown as New", "error"))
    return LoadedFile(entries, style, round_trips, header, notices, blocked)


def save_translation_file(path: Path, entries: List[StringEntry], style: JsonStyle,
                          header: FileHeader, write_meta: bool = True) -> None:
    """Write the language file, then its sidecar, each atomically. A failed language-file write
    raises before the sidecar is touched, so the pair never splits that way; a failed sidecar write
    raises MetadataWriteError after the language file is already saved."""
    _atomic_write_bytes(path, dump_json(entries, style))
    if not write_meta:
        return
    try:
        _atomic_write_bytes(meta_path_for(path), build_sidecar_bytes(entries, header))
    except Exception as e:
        raise MetadataWriteError(str(e)) from e


@dataclass
class FileFacts:
    file_name:    str
    folder:       str
    size_bytes:   Optional[int]     # None when the file is no longer on disk
    modified:     Optional[float]   # st_mtime, None when the file is no longer on disk
    total:        int
    by_status:    Dict[str, int]
    untranslated: int


def compute_file_facts(entries: List[StringEntry], path: Path) -> FileFacts:
    """Read-only facts for File -> Properties. Counts come from *entries* (so they include
    unsaved edits); size and modified time from the file on disk."""
    try:
        stat = path.stat()
        size_bytes, modified = stat.st_size, stat.st_mtime
    except OSError:
        size_bytes, modified = None, None
    by_status = {s: 0 for s in STATUSES}
    for e in entries:
        if e.status in by_status:
            by_status[e.status] += 1
    return FileFacts(
        file_name    = path.name,
        folder       = str(path.parent),
        size_bytes   = size_bytes,
        modified     = modified,
        total        = len(entries),
        by_status    = by_status,
        # Same definition as _pick_newer_entry(): the translation is still the source text.
        untranslated = sum(1 for e in entries if e.text == e.name),
    )


# ══════════════════════════════════════════════════════════════
#  MERGE FROM FILE
# ══════════════════════════════════════════════════════════════

@dataclass
class MergeDiff:
    additions:    List[StringEntry]
    conflicts:    List[Tuple[StringEntry, StringEntry]]  # (open, incoming)
    deletions:    List[StringEntry]
    auto_updated: List[StringEntry]


@dataclass
class MergeRowInfo:
    """One row of MergeConflictDialog as MergeCompareDialog reads it. An addition has no open
    entry and a deletion no incoming entry. `combo` is the row's Resolution combo, the only place
    the row's choice is kept."""
    kind:           str                     # "addition" | "conflict" | "deletion"
    open_entry:     Optional[StringEntry]
    incoming_entry: Optional[StringEntry]
    combo:          QComboBox


def _pick_newer_entry(open_entry: StringEntry, incoming_entry: StringEntry) -> Optional[StringEntry]:
    """Return incoming_entry if it should win, else None (open file's version wins).

    An untranslated entry (translation text identical to its own source name)
    always loses to a genuinely translated entry on the other side, regardless
    of modify_date — an untranslated placeholder should never outrank an actual
    translation. Within a real conflict at most one side can be untranslated
    (equal texts on both sides would mean no conflict), so this check is
    unambiguous. Otherwise, falls through to date comparison: a strictly newer
    modify_date wins; ties, unparseable, or missing dates on either side all
    default to the open file per the merge design spec.

    "Untranslated" is a heuristic (text == name), not a guarantee — it can
    misfire on cognates, acronyms, or proper nouns that are legitimately
    identical to the source (e.g. "Email", "USB"). Acceptable here because
    this only picks a *default*: the result only ever seeds a pre-selected
    combo-box value in MergeConflictDialog, which the user reviews and can
    override with one click before anything is applied.
    """
    open_untranslated     = open_entry.text == open_entry.name
    incoming_untranslated = incoming_entry.text == incoming_entry.name
    if open_untranslated and not incoming_untranslated:
        return incoming_entry
    if incoming_untranslated and not open_untranslated:
        return None

    open_date     = parse_date(open_entry.modify_date)
    incoming_date = parse_date(incoming_entry.modify_date)
    if open_date is not None and incoming_date is not None and incoming_date > open_date:
        return incoming_entry
    return None


def compute_merge_diff(open_entries: List[StringEntry], incoming_entries: List[StringEntry]) -> MergeDiff:
    """Classify every source string found in either list.

    Raises ValueError if incoming_entries contains a duplicated `name` —
    the open file's own uniqueness invariant is assumed already true and is
    not re-checked here.
    """
    incoming_by_name: dict = {}
    for entry in incoming_entries:
        if entry.name in incoming_by_name:
            raise ValueError(f"Duplicate source text in incoming file: {entry.name!r}")
        incoming_by_name[entry.name] = entry

    open_by_name = {entry.name: entry for entry in open_entries}

    additions:    List[StringEntry] = []
    conflicts:    List[Tuple[StringEntry, StringEntry]] = []
    auto_updated: List[StringEntry] = []

    for incoming in incoming_entries:
        current = open_by_name.get(incoming.name)
        if current is None:
            additions.append(incoming)
            continue

        if current.text != incoming.text:
            conflicts.append((current, incoming))
            continue

        metadata_differs = (
            current.translator  != incoming.translator or
            current.status      != incoming.status or
            current.modify_date != incoming.modify_date
        )
        if metadata_differs:
            winner = _pick_newer_entry(current, incoming)
            if winner is not None:
                auto_updated.append(winner)

    deletions = [entry for entry in open_entries if entry.name not in incoming_by_name]

    return MergeDiff(
        additions=additions,
        conflicts=conflicts,
        deletions=deletions,
        auto_updated=auto_updated,
    )


def merge_row_reason(kind: str, open_entry: Optional[StringEntry],
                     incoming_entry: Optional[StringEntry]) -> str:
    """Short phrase saying why a Merge row exists and, for a conflict, which rule picked its
    default. Checks in _pick_newer_entry()'s order, so the phrase always names the rule that
    decided. MergeCompareDialog shows it in its header."""
    if kind == "addition":
        return "only in the incoming file"
    if kind == "deletion":
        return "only in the open file"
    open_untranslated     = open_entry.text == open_entry.name
    incoming_untranslated = incoming_entry.text == incoming_entry.name
    if open_untranslated and not incoming_untranslated:
        return "open is untranslated"
    if incoming_untranslated and not open_untranslated:
        return "incoming is untranslated"
    open_date     = parse_date(open_entry.modify_date)
    incoming_date = parse_date(incoming_entry.modify_date)
    if open_date is None or incoming_date is None:
        return "date missing"
    if incoming_date > open_date:
        return "incoming is newer"
    if open_date > incoming_date:
        return "open is newer"
    return "same date"


def _escape_pane_text(text: str) -> str:
    """Plain text as HTML for a read-only QTextEdit: escaped, newlines kept as <br>."""
    return html.escape(text, quote=False).replace("\n", "<br>")


def _pane_html(inner: str) -> str:
    """Wrap pane HTML so runs of spaces are kept; QTextDocument collapses them otherwise."""
    return f'<div style="white-space: pre-wrap">{inner}</div>'


# Words, whitespace runs and single punctuation characters: a changed word is marked whole, a
# changed comma alone. Together the three alternatives match every character of the text.
_DIFF_TOKEN_RE = re.compile(r"\w+|\s+|[^\w\s]")


def _diff_run_html(tokens: List[str], tint_hex: Optional[str]) -> str:
    text = _escape_pane_text("".join(tokens))
    if tint_hex and text:
        return f'<span style="background-color: {tint_hex}">{text}</span>'
    return text


def merge_diff_html(open_text: str, incoming_text: str, tint_hex: str) -> Tuple[str, str]:
    """Both sides of a Merge conflict as pane HTML, with the tokens that differ tinted: removed or
    replaced ones on the open side, inserted or replacing ones on the incoming side. tint_hex must
    be an opaque #rrggbb -- QTextDocument's CSS subset does not reliably take rgba()."""
    open_tokens     = _DIFF_TOKEN_RE.findall(open_text)
    incoming_tokens = _DIFF_TOKEN_RE.findall(incoming_text)
    open_parts: List[str] = []
    incoming_parts: List[str] = []
    matcher = difflib.SequenceMatcher(None, open_tokens, incoming_tokens, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        tint = None if tag == "equal" else tint_hex
        open_parts.append(_diff_run_html(open_tokens[i1:i2], tint))
        incoming_parts.append(_diff_run_html(incoming_tokens[j1:j2], tint))
    return _pane_html("".join(open_parts)), _pane_html("".join(incoming_parts))


def _blend_hex(top_hex: str, bottom_hex: str, alpha: float) -> str:
    """top_hex laid over bottom_hex at *alpha*, as an opaque #rrggbb."""
    top, bottom = QColor(top_hex), QColor(bottom_hex)
    return QColor(round(top.red() * alpha + bottom.red() * (1 - alpha)),
                  round(top.green() * alpha + bottom.green() * (1 - alpha)),
                  round(top.blue() * alpha + bottom.blue() * (1 - alpha))).name()


# ══════════════════════════════════════════════════════════════
#  GLOSSARY FILE I/O
# ══════════════════════════════════════════════════════════════

_GLOSSARY_HEADER_ALIASES = {
    "term":        {"term"},
    "translation": {"translation"},
    "note":        {"note", "notes", "comment", "comments"},
}


def glossary_path_for(json_path: Path) -> Path:
    """Return the glossary CSV path paired with a JSON language file.

    e.g. es.json -> es.glossary.csv, in the same directory.
    """
    return json_path.parent / f"{json_path.stem}.glossary.csv"


def _sniff_glossary_delimiter(sample: str) -> str:
    """Detect the CSV delimiter used in *sample* (comma/semicolon/tab),
    falling back to comma when detection isn't possible (e.g. too few
    rows to sniff reliably). Handles the common case of European-locale
    Excel (including Latvian) defaulting to semicolon-separated CSV on a
    plain Ctrl+S."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        return ","


def _resolve_glossary_columns(header_row: List[str]) -> Optional[dict]:
    """Map a header row to {field: column_index} by name, case-insensitive
    and alias-tolerant (see _GLOSSARY_HEADER_ALIASES). Returns None if no
    recognized term/translation columns are found at all, so the caller
    can fall back to positional order."""
    normalized = [cell.strip().lower() for cell in header_row]
    columns: dict = {}
    for field, aliases in _GLOSSARY_HEADER_ALIASES.items():
        for i, name in enumerate(normalized):
            if name in aliases:
                columns[field] = i
                break
    if "term" not in columns or "translation" not in columns:
        return None
    return columns


def _glossary_cell(row: List[str], columns: dict, field: str) -> str:
    idx = columns.get(field)
    return row[idx].strip() if idx is not None and idx < len(row) else ""


def parse_glossary(path: Path) -> Tuple[List[GlossaryEntry], List[str]]:
    """Parse a glossary CSV file into (entries, warnings).

    Tolerant of the corruption an external editor is likely to introduce:
    wrong delimiter (e.g. semicolon from a European-locale Excel save),
    wrong encoding (e.g. Windows ANSI instead of UTF-8), and a missing,
    reordered, or renamed header. A missing file returns ([], []) -- the
    normal "no glossary yet" case, not a warning. Never raises: any
    unrecoverable problem is reported through the warnings list instead,
    so a corrupted glossary file can never crash a plain file-open.
    """
    if not path.exists():
        return [], []

    try:
        raw_bytes = path.read_bytes()
        warnings: List[str] = []

        try:
            text = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw_bytes.decode("cp1257")
            warnings.append(
                "file was not valid UTF-8 -- decoded as Windows ANSI; some "
                "characters may be wrong. Re-save via View → Glossary… to fix."
            )

        if not text.strip():
            return [], warnings

        delimiter = _sniff_glossary_delimiter(text[:2048])
        if delimiter != ",":
            shown = "tab" if delimiter == "\t" else delimiter
            warnings.append(
                f"detected '{shown}' as the field separator instead of ',' "
                "-- auto-corrected"
            )

        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        if not rows:
            return [], warnings

        columns = _resolve_glossary_columns(rows[0])
        if columns is not None:
            data_rows = rows[1:]
        else:
            columns = {"term": 0, "translation": 1, "note": 2}
            data_rows = rows
            warnings.append(
                "no recognized header row found -- assumed column order "
                "term, translation, note"
            )

        entries: List[GlossaryEntry] = []
        skipped = 0
        for row in data_rows:
            term        = _glossary_cell(row, columns, "term")
            translation = _glossary_cell(row, columns, "translation")
            note        = _glossary_cell(row, columns, "note")
            if not term or not translation:
                skipped += 1
                continue
            entries.append(GlossaryEntry(term=term, translation=translation, note=note))

        if skipped:
            warnings.append(f"skipped {skipped} row(s) missing a term or translation")

        return entries, warnings

    except Exception as e:
        return [], [f"glossary unreadable ({e}); treated as empty"]


def write_glossary(path: Path, entries: List[GlossaryEntry]):
    """Write glossary entries to *path* as UTF-8-with-BOM CSV (utf-8-sig),
    so accented/non-Latin translation text renders correctly when the file
    is opened directly in Excel on Windows."""
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["term", "translation", "note"])
        for e in entries:
            writer.writerow([e.term, e.translation, e.note])


# ══════════════════════════════════════════════════════════════
#  TABLE MODEL
# ══════════════════════════════════════════════════════════════

class TranslationModel(QAbstractTableModel):
    def __init__(self, theme_fn=None, parent=None):
        super().__init__(parent)
        self._all: List[StringEntry]  = []
        self._vis: List[StringEntry]  = []  # visible (filtered) entries
        # Callable that returns the active theme name ("dark"/"light").
        # Set by MainWindow after construction.
        self._theme_fn = theme_fn or (lambda: "dark")

    def load(self, entries: List[StringEntry]):
        self.beginResetModel()
        self._all = entries
        self._vis = list(entries)
        self.endResetModel()

    def apply_filters(self, visible: List[StringEntry]):
        self.beginResetModel()
        self._vis = visible
        self.endResetModel()

    def get_entry(self, row: int) -> Optional[StringEntry]:
        if 0 <= row < len(self._vis):
            return self._vis[row]
        return None

    def all_entries(self) -> List[StringEntry]:
        return self._all

    def visible_entries(self) -> List[StringEntry]:
        return self._vis

    # ── QAbstractTableModel interface ──
    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._vis)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return HEADERS[section]

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        entry = self._vis[row]

        if role == Qt.DisplayRole:
            if col == COL_IDX:    return str(entry.position)
            if col == COL_SRC:    return entry.name
            if col == COL_TRANS:  return entry.text
            if col == COL_STATUS: return entry.status
            if col == COL_USER:   return entry.translator
            if col == COL_DATE:   return entry.modify_date

        if role == Qt.ForegroundRole:
            return None   # let QSS colour apply

        if role == Qt.TextAlignmentRole:
            if col in (COL_IDX, COL_STATUS):
                return Qt.AlignCenter
            return Qt.AlignVCenter | Qt.AlignLeft

        if role == Qt.ToolTipRole:
            if col == COL_SRC:   return entry.name
            if col == COL_TRANS: return entry.text

        return None

    def flags(self, index: QModelIndex):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable


# ══════════════════════════════════════════════════════════════
#  FILTER ENGINE
# ══════════════════════════════════════════════════════════════

class FilterEngine:
    def __init__(self):
        self.search_text = ""
        self.search_field = "both"          # "source", "translated", "both"
        self.search_mode  = "starts_with"   # "starts_with" | "contains"
        self.status = "All"
        self.translator = ""
        self.date_from: Optional[date] = None
        self.date_to:   Optional[date] = None

    def compiled_search_pattern(self) -> Optional[re.Pattern]:
        """Compile the 'starts with' search regex once, or return None if
        search_text is empty or the mode is 'contains' (which needs no
        compiled pattern). A caller that scans many entries in one pass
        (e.g. MainWindow._apply_filters) should call this once and pass the
        result into matches() instead of letting it compile once per entry."""
        if self.search_text and self.search_mode == "starts_with":
            return re.compile(r"\b" + re.escape(self.search_text.lower()))
        return None

    def matches(self, entry: StringEntry, pattern: Optional[re.Pattern] = None) -> bool:
        # Search text
        if self.search_text:
            needle = self.search_text.lower()
            src    = entry.name.lower()
            tr     = entry.text.lower()
            if self.search_mode == "starts_with":
                # \b + escaped needle: matches at the start of any word.
                # Punctuation (hyphens, slashes, etc.) counts as a word boundary,
                # so e.g. needle "tab" matches "data-tablet". Accepts a
                # precompiled pattern (see compiled_search_pattern()) so a
                # caller scanning many entries compiles it once, not per call.
                pat    = pattern if pattern is not None else self.compiled_search_pattern()
                in_src = bool(pat.search(src))
                in_tr  = bool(pat.search(tr))
            else:  # "contains"
                in_src = needle in src
                in_tr  = needle in tr
            if self.search_field == "source"     and not in_src:  return False
            if self.search_field == "translated" and not in_tr:   return False
            if self.search_field == "both"       and not (in_src or in_tr): return False

        # Status
        if self.status != "All" and entry.status != self.status:
            return False

        # Translator
        if self.translator and self.translator.lower() not in entry.translator.lower():
            return False

        # Date range
        if self.date_from or self.date_to:
            try:
                d = parse_date(entry.modify_date)
                if d is not None:
                    if self.date_from and d < self.date_from: return False
                    if self.date_to   and d > self.date_to:   return False
            except Exception:
                pass  # malformed date — don't filter it out


        return True


class _WidePopupComboBox(QComboBox):
    """QComboBox whose popup is at least as wide as its widest item. _combobox_qss turns the popup
    into a plain list, which is exactly as wide as the combo and would elide longer items (the
    Backup location choices, or any item at a large UI font) -- unlike Fusion's menu-style popup,
    which widens to fit. Measured each time the popup opens, so a change of UI font is picked up.
    Not for QFontComboBox: it is editable, so Fusion already gives it a list popup, and measuring
    its column would walk every installed font on each open."""

    def showPopup(self):
        view = self.view()
        width = view.sizeHintForColumn(0) + 2 * view.frameWidth()
        if self.count() > self.maxVisibleItems():
            width += view.verticalScrollBar().sizeHint().width()
        view.setMinimumWidth(width)
        super().showPopup()


# ══════════════════════════════════════════════════════════════
#  FILTER PANEL
# ══════════════════════════════════════════════════════════════

# Room for the line edit's own inner margins and the text cursor, which the style's edit-field
# rectangle does not include.
_TEXT_FIT_SLACK_PX = 6


def _width_for_text(widget: QWidget, fm: QFontMetrics, texts: List[str]) -> int:
    """Width at which a combo box or spin box shows the widest of *texts* unclipped. The style's
    own edit-field rectangle gives the border, padding and drop-down strip, so this follows the
    stylesheet instead of guessing their sizes."""
    if isinstance(widget, QComboBox):
        opt = QStyleOptionComboBox()
        widget.initStyleOption(opt)
        field = widget.style().subControlRect(QStyle.CC_ComboBox, opt,
                                              QStyle.SC_ComboBoxEditField, widget)
    else:
        opt = QStyleOptionSpinBox()
        widget.initStyleOption(opt)
        field = widget.style().subControlRect(QStyle.CC_SpinBox, opt,
                                              QStyle.SC_SpinBoxEditField, widget)
    chrome = widget.width() - field.width()
    return max(fm.horizontalAdvance(s) for s in texts) + chrome + _TEXT_FIT_SLACK_PX


class FilterPanel(QFrame):
    filters_changed = Signal()

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.setObjectName("filterBar")
        self.setFrameShape(QFrame.NoFrame)   # the bar's lines come from QSS (_band_qss)
        self.engine    = FilterEngine()
        self._settings = settings  # may be None before MainWindow is ready

        # Debounce timer for free-text filter fields (search/translator boxes).
        # Combo/checkbox/date controls stay un-debounced -- they're discrete
        # clicks, not keystroke bursts, so debouncing them would only add
        # perceived lag for no benefit.
        self._filter_debounce = QTimer(self)
        self._filter_debounce.setSingleShot(True)
        self._filter_debounce.setInterval(self._debounce_ms())
        self._filter_debounce.timeout.connect(self._on_filter)

        self._build()

        # Restore persisted search mode / field from settings
        cfg  = self._settings.get("search", {}) if self._settings else {}
        mode = cfg.get("mode",  "starts_with")
        fld  = cfg.get("field", "both")
        self.mode_combo.blockSignals(True)
        self.field_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(0 if mode == "starts_with" else 1)
        self.field_combo.setCurrentIndex(
            {"both": 0, "source": 1, "translated": 2}.get(fld, 0))
        self.mode_combo.blockSignals(False)
        self.field_combo.blockSignals(False)
        self._on_filter()  # push initial state into the engine

    def _debounce_ms(self) -> int:
        """Clamped debounce interval (ms) for the search/translator text
        fields, read once from settings.json (search.debounce_ms). No
        dedicated UI control -- same precedent as EditDialog's char_count
        config (see CLAUDE.md). A hand-edited bad value falls back to the
        default rather than raising or disabling filtering."""
        cfg = self._settings.get("search", {}) if self._settings else {}
        try:
            ms = int(cfg.get("debounce_ms", 150))
        except (TypeError, ValueError):
            ms = 150
        return max(0, min(ms, 3000))

    def _build(self):
        # One grid for the whole bar: row 0 holds every caption, row 1 every control row, so the
        # captions line up with each other and every control sits in a same-height row. The
        # controls take a vertical Expanding policy (end of this method) and fill that row, so
        # their tops and bottoms match whatever their natural heights or the UI font -- there are
        # no fixed heights anywhere. The bar itself is Fixed vertically so it never grows to fill
        # the window.
        outer = QGridLayout(self)
        outer.setContentsMargins(0, 8, 0, 8)
        outer.setHorizontalSpacing(0)
        outer.setVerticalSpacing(3)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._bar_col = 0
        self._captions: Dict[str, QLabel] = {}
        self._active_dots: Dict[str, QLabel] = {}

        # ── Search column ────────────────────────
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Find text…")
        self.search_edit.setMinimumWidth(220)
        # Debounced -- see self._filter_debounce (constructed in __init__).
        # The lambda discards the emitted text; connecting textChanged(str)
        # straight to QTimer.start would pass that text positionally into
        # start(msec: int), which raises at call time.
        self.search_edit.textChanged.connect(lambda _: self._filter_debounce.start())
        self.clear_btn = QPushButton("✕")
        self.clear_btn.setToolTip("Clear search")
        self.clear_btn.clicked.connect(self._clear_search)
        self.mode_combo = _WidePopupComboBox()
        self.mode_combo.addItems(["Starts with", "Contains"])
        self.mode_combo.setItemData(
            0,
            "Match words that start with the search text "
            "(e.g. 'tab' matches 'tablet' but not 'database')",
            Qt.ToolTipRole,
        )
        self.mode_combo.setItemData(
            1,
            "Match the search text anywhere in the field",
            Qt.ToolTipRole,
        )
        self.mode_combo.currentIndexChanged.connect(self._on_filter)
        self.mode_combo.currentIndexChanged.connect(self._save_search_prefs)
        self.field_combo = _WidePopupComboBox()
        self.field_combo.addItems(["Both", "Source", "Translated"])
        self.field_combo.currentIndexChanged.connect(self._on_filter)
        self.field_combo.currentIndexChanged.connect(self._save_search_prefs)
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        search_row.addWidget(self.search_edit)
        search_row.addWidget(self.clear_btn)
        search_row.addWidget(QLabel("Mode:"))
        search_row.addWidget(self.mode_combo)
        search_row.addWidget(QLabel("In:"))
        search_row.addWidget(self.field_combo)
        self._add_column(outer, "search", "Search", search_row, stretch=3)

        # ── Status column ─────────────────────────
        self.status_combo = _WidePopupComboBox()
        self.status_combo.addItems(["All"] + STATUSES)
        self.status_combo.currentIndexChanged.connect(self._on_filter)
        status_row = QHBoxLayout()
        status_row.setSpacing(4)
        status_row.addWidget(self.status_combo)
        self._add_column(outer, "status", "Status", status_row)

        # ── Translator column ─────────────────────
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Filter by user…")
        self.user_edit.setMinimumWidth(140)
        # Debounced -- see search_edit above for why this is a lambda, not a
        # direct connection.
        self.user_edit.textChanged.connect(lambda _: self._filter_debounce.start())
        user_row = QHBoxLayout()
        user_row.setSpacing(4)
        user_row.addWidget(self.user_edit)
        self._add_column(outer, "translator", "Translator", user_row, stretch=1)

        # ── Date range column ─────────────────────
        self.date_from = _DatePickerField()
        self.date_from.setSpecialValueText(" ")
        # Load persisted From-date from settings; default to 01.01.2025
        _from_str  = (self._settings.get("filter_from_date", "01.01.2025")
                      if self._settings else "01.01.2025")
        _from_date = parse_date(_from_str) or __import__("datetime").date(2025, 1, 1)
        self.date_from.setDate(QDate(_from_date.year, _from_date.month, _from_date.day))
        self.date_from.setDisplayFormat(DATE_FMT_QT)
        self.date_to = _DatePickerField()
        self.date_to.setSpecialValueText(" ")
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setDisplayFormat(DATE_FMT_QT)
        self._date_from_active = False
        self._date_to_active   = False
        self.date_from_chk = QCheckBox("From")
        self.date_from_chk.setProperty("filterChk", True)
        self.date_to_chk   = QCheckBox("To")
        self.date_to_chk.setProperty("filterChk", True)
        self.date_from_chk.stateChanged.connect(self._on_filter)
        self.date_to_chk.stateChanged.connect(self._on_filter)
        # Debounced like the text boxes: a confirmed pop-up pick still routes through the
        # same delay before the filter is applied, even though it fires dateChanged only once.
        self.date_from.dateChanged.connect(self._on_from_date_changed)
        self.date_to.dateChanged.connect(lambda _: self._filter_debounce.start())
        date_row = QHBoxLayout()
        date_row.setSpacing(4)
        date_row.addWidget(self.date_from_chk)
        date_row.addWidget(self.date_from)
        date_row.addWidget(self.date_to_chk)
        date_row.addWidget(self.date_to)
        self._add_column(outer, "date", "Date range", date_row)

        # ── Reset column ──────────────────────────
        # Icon set by fit_to_font(). The leading space is the icon gap: Fusion leaves ~1 px, and a
        # space scales with the font.
        self.reset_btn = QPushButton(" Reset All")
        self.reset_btn.setToolTip("Clear all filters and show all entries")
        self.reset_btn.clicked.connect(self._reset_all)
        reset_row = QHBoxLayout()
        reset_row.addWidget(self.reset_btn)
        self._add_column(outer, "reset", "Filters", reset_row, has_dot=False)

        # Every control fills the shared control row (see the layout comment above): a vertical
        # Expanding policy makes the row's tallest natural height the height of all of them.
        for w in (self.search_edit, self.clear_btn, self.mode_combo, self.field_combo,
                  self.status_combo, self.user_edit, self.date_from, self.date_to,
                  self.reset_btn):
            policy = w.sizePolicy()
            policy.setVerticalPolicy(QSizePolicy.Expanding)
            w.setSizePolicy(policy)

    def fit_to_font(self, font: QFont, icon_color: str):
        """Size the combos and date pickers to the text they show and repaint the Reset icon.
        Called from MainWindow._apply_theme() after the stylesheet is set, so the style's
        padding and drop-down strip already match the new font. Fixed pixel widths
        clipped the dates from 12 pt up ("01.01.20") and left Mode 40-70 px wider than its text."""
        fm = QFontMetrics(font)
        for combo in (self.mode_combo, self.field_combo, self.status_combo):
            items = [combo.itemText(i) for i in range(combo.count())]
            combo.setFixedWidth(_width_for_text(combo, fm, items))
        for picker in (self.date_from, self.date_to):
            picker.fit_to_font(fm)
        icon_px = round(fm.capHeight() * 1.5)
        self.reset_btn.setIcon(QIcon(QPixmap.fromImage(
            _render_reset_icon(icon_color, icon_px * _GLYPH_SUPERSAMPLE))))
        self.reset_btn.setIconSize(QSize(icon_px, icon_px))

    def _add_column(self, outer: QGridLayout, key: str, caption: str, body: QLayout,
                    stretch: int = 0, has_dot: bool = True) -> None:
        """Place one filter-bar column in the shared grid: its caption (plus, for real filters, the
        'active' dot AFTER the caption text so the text never shifts) in row 0 and *body* in row 1,
        after a 1 px divider that spans both rows. Every column uses the same two rows, so captions
        line up and every control row has the same height."""
        col = self._bar_col
        if col > 0:
            divider = QFrame()
            divider.setObjectName("filterDivider")
            divider.setFrameShape(QFrame.VLine)
            outer.addWidget(divider, 0, col, 2, 1)
            col += 1
        head = QHBoxLayout()
        head.setContentsMargins(12, 0, 12, 0)
        head.setSpacing(4)
        cap = QLabel(caption)
        cap.setProperty("filterCaption", True)
        head.addWidget(cap)
        if has_dot:
            dot = QLabel("●")
            dot.setObjectName("filterActiveDot")
            dot.setVisible(False)
            # A hidden dot must keep its space, or the caption shifts when it appears at larger fonts.
            policy = dot.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            dot.setSizePolicy(policy)
            head.addWidget(dot)
            self._active_dots[key] = dot
        head.addStretch(1)
        body.setContentsMargins(12, 0, 12, 0)
        outer.addLayout(head, 0, col, Qt.AlignBottom)
        outer.addLayout(body, 1, col)
        outer.setColumnStretch(col, stretch)
        self._captions[key] = cap
        self._bar_col = col + 1

    def _on_from_date_changed(self):
        """Persist the new From-date to settings, then apply the filters through the debounce.
        Fires once per confirmed pop-up pick, not once per intermediate wheel/drag step."""
        if self._settings:
            d   = self.date_from.date()
            raw = format_date_for_storage(d)
            self._settings.set("filter_from_date", raw)
            self._settings.save()
        self._filter_debounce.start()

    def _clear_search(self):
        self._filter_debounce.stop()
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self._on_filter()

    def _reset_all(self):
        self._filter_debounce.stop()
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(0)   # "Starts with"
        self.mode_combo.blockSignals(False)
        self.field_combo.blockSignals(True)
        self.field_combo.setCurrentIndex(0)
        self.field_combo.blockSignals(False)
        self.status_combo.blockSignals(True)
        self.status_combo.setCurrentIndex(0)
        self.status_combo.blockSignals(False)
        self.user_edit.blockSignals(True)
        self.user_edit.clear()
        self.user_edit.blockSignals(False)
        self.date_from_chk.blockSignals(True)
        self.date_from_chk.setChecked(False)
        self.date_from_chk.blockSignals(False)
        self.date_to_chk.blockSignals(True)
        self.date_to_chk.setChecked(False)
        self.date_to_chk.blockSignals(False)
        self._on_filter()
        self._save_search_prefs()

    def _on_filter(self):
        e = self.engine
        e.search_text  = self.search_edit.text().strip()
        e.search_field = ["both", "source", "translated"][self.field_combo.currentIndex()]
        e.search_mode  = "starts_with" if self.mode_combo.currentIndex() == 0 else "contains"
        e.status       = self.status_combo.currentText()
        e.translator   = self.user_edit.text().strip()
        e.date_from    = (self.date_from.date().toPython() if self.date_from_chk.isChecked() else None)
        e.date_to      = (self.date_to.date().toPython()   if self.date_to_chk.isChecked()   else None)

        self._refresh_active_indicators()
        self.filters_changed.emit()

    def _refresh_active_indicators(self) -> None:
        """Mark the filters that are narrowing the table: an accent border on the field and a dot
        after the caption. Mode/In are options of Search, not filters, so they never count."""
        e = self.engine
        date_fields = [w for chk, w in ((self.date_from_chk, self.date_from),
                                        (self.date_to_chk, self.date_to)) if chk.isChecked()]
        state = {
            "search":     (bool(e.search_text), [self.search_edit]),
            "status":     (e.status != "All", [self.status_combo]),
            "translator": (bool(e.translator), [self.user_edit]),
            "date":       (bool(date_fields), date_fields),
        }
        marked = set()
        for key, (active, fields) in state.items():
            self._active_dots[key].setVisible(active)
            if active:
                marked.update(id(w) for w in fields)
        for w in (self.search_edit, self.status_combo, self.user_edit,
                  self.date_from, self.date_to):
            self._set_active(w, id(w) in marked)

    @staticmethod
    def _set_active(widget: QWidget, on: bool) -> None:
        """Set the dynamic 'active' property and re-polish so the QSS attribute selector applies."""
        if widget.property("active") is on:
            return
        widget.setProperty("active", on)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _save_search_prefs(self):
        """Persist search.mode/search.field. Wired only to mode_combo/
        field_combo -- the only two things this app actually reads back
        from settings.json -- so a plain keystroke in search_edit/user_edit
        never touches disk. Merges into the existing search sub-dict
        (setdefault) rather than replacing it outright, so a hand-edited
        search.debounce_ms survives this write instead of being silently
        dropped."""
        if not self._settings:
            return
        mode  = "starts_with" if self.mode_combo.currentIndex() == 0 else "contains"
        field = ["both", "source", "translated"][self.field_combo.currentIndex()]
        search_cfg = self._settings.data.setdefault("search", {})
        search_cfg["mode"]  = mode
        search_cfg["field"] = field
        self._settings.save()


# ══════════════════════════════════════════════════════════════
#  KEYBOARD SHORTCUTS DIALOG
# ══════════════════════════════════════════════════════════════

# Human-readable labels for each shortcut slot
SHORTCUT_LABELS = {
    "edit_prev":       "Edit window — Previous entry",
    "edit_next":       "Edit window — Next entry",
    "edit_cancel":     "Edit window — Cancel / close",
    "edit_save":       "Edit window — Save",
    "auto_translate":  "Edit window — Auto-translate",
    "robo_translate":  "Edit window — Robo-translate (auto-advance)",
    "mark_new":        "Mark as New",
    "mark_review":     "Mark as Review",
    "mark_complete":   "Mark as Complete",
    "delete_entries":  "Delete Selected",
}

SHORTCUT_DEFAULTS = {
    "edit_prev":       "Alt+Left",
    "edit_next":       "Alt+Right",
    "edit_cancel":     "Escape",
    "edit_save":       "Alt+S",
    "auto_translate":  "Alt+A",
    "robo_translate":  "Shift+Alt+A",
    "mark_new":        "Alt+N",
    "mark_review":     "Alt+R",
    "mark_complete":   "Alt+C",
    "delete_entries":  "Ctrl+Del",
}


class ShortcutsDialog(QDialog):
    """Dialog to view and reassign keyboard shortcuts.

    Each row shows the action name, the current key binding, and two
    buttons: [Record] (click then press any key combo) and [Reset].
    Changes are applied immediately to the settings object and saved.
    """

    def __init__(self, settings: "Settings", parent=None):
        super().__init__(parent)
        self._settings = settings
        self._recording: str | None = None   # slot key currently being recorded
        self._row_widgets: dict = {}          # slot -> {"btn_record": ..., "lbl": ...}
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumWidth(500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._build()
        self._apply_style()
        self._align_columns()

    def _align_columns(self):
        """Each section is its own grid, so each sized its action-label column to its own
        labels and the shortcut column started at a different x in every section. Give all
        three the widest label's width, measured after _apply_style() has set the font.
        Only single-column widgets in column 0 count: a row without one, a spanning widget
        or a nested layout there is skipped rather than raising."""
        widths = []
        for grid in self._grids:
            for i in range(grid.count()):
                _, col, _, col_span = grid.getItemPosition(i)
                widget = grid.itemAt(i).widget()
                if col == 0 and col_span == 1 and widget is not None:
                    widths.append(widget.sizeHint().width())
        width = max(widths, default=0)
        for grid in self._grids:
            grid.setColumnMinimumWidth(0, width)

    def _apply_style(self):
        mw = self.parent()
        t  = mw._get_theme() if mw and hasattr(mw, "_get_theme") else THEMES["dark"]
        pt = (mw.settings.get_font().pointSize() if mw and hasattr(mw, "settings") else 0) or 10
        self.setStyleSheet(f"""
            QDialog   {{ background: {t['dlg_bg']}; }}
            QLabel    {{ color: {t['fg']}; }}
            {_groupbox_qss(t, pt)}
            {_button_qss(t, pt)}
            {_field_state_qss(t)}
            QPushButton#recordingBtn {{ background: {t['dlg_btn_bg']};
                                        color: {t['sel_fg']}; border: none; }}
        """)
        self._note.setStyleSheet(f"color: {t['fg_dim']}; font-size: {max(8, pt - 1)}pt;")

    def _build(self):
        shortcuts = self._settings.get("shortcuts", {})

        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(16, 16, 16, 12)

        # ── Edit window shortcuts ──
        edit_slots = ["edit_prev", "edit_next", "edit_cancel", "edit_save"]
        grp = QGroupBox("Edit Window Navigation")
        grid = QGridLayout(grp)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        for row_idx, slot in enumerate(edit_slots):
            self._add_shortcut_row(grid, row_idx, slot, shortcuts)
        lay.addWidget(grp)

        # ── Edit window translation shortcuts ──
        grp_tr = QGroupBox("Edit Window Translation")
        grid_tr = QGridLayout(grp_tr)
        grid_tr.setHorizontalSpacing(12)
        grid_tr.setVerticalSpacing(8)
        grid_tr.setColumnStretch(1, 1)
        self._add_shortcut_row(grid_tr, 0, "auto_translate", shortcuts)
        self._add_shortcut_row(grid_tr, 1, "robo_translate", shortcuts)
        self._add_delay_row(grid_tr, 2)
        lay.addWidget(grp_tr)

        # ── Main window: shortcuts that act on selected rows ──
        mark_slots = ["mark_new", "mark_review", "mark_complete", "delete_entries"]
        grp2 = QGroupBox("Selected Rows Actions")
        grid2 = QGridLayout(grp2)
        grid2.setHorizontalSpacing(12)
        grid2.setVerticalSpacing(8)
        grid2.setColumnStretch(1, 1)
        # The labels used to say this inline, which made column 0 very wide.
        scope_tip = ("In the main table: acts on the selected rows.\n"
                     "In the Edit window: acts on the entry being edited.")
        for row_idx, slot in enumerate(mark_slots):
            self._add_shortcut_row(grid2, row_idx, slot, shortcuts, tooltip=scope_tip)
        lay.addWidget(grp2)
        self._grids = (grid, grid_tr, grid2)

        note = QLabel(
            "Click \"Record\" then press the desired key combination.\n"
            "Shortcuts are saved automatically and take effect next time "
            "the Edit window is opened."
        )
        note.setWordWrap(True)
        lay.addWidget(note)
        self._note = note

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setProperty("role", "primary")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

    def _add_shortcut_row(self, grid: QGridLayout, row_idx: int,
                          slot: str, shortcuts: dict, tooltip: str = ""):
        """Add one shortcut row (label + key display + Record + Reset) to *grid*."""
        label_text  = SHORTCUT_LABELS.get(slot, slot)
        current_seq = shortcuts.get(slot, SHORTCUT_DEFAULTS.get(slot, ""))

        lbl_action = QLabel(label_text)
        lbl_action.setToolTip(tooltip)
        lbl_seq    = QLabel(current_seq)
        lbl_seq.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lbl_seq.setFrameShape(QFrame.StyledPanel)
        lbl_seq.setMinimumWidth(130)

        btn_record = QPushButton("Record…")
        btn_record.clicked.connect(lambda _, s=slot: self._start_recording(s))

        btn_reset = QPushButton("Reset")
        btn_reset.clicked.connect(lambda _, s=slot: self._reset(s))

        grid.addWidget(lbl_action, row_idx, 0)
        grid.addWidget(lbl_seq,    row_idx, 1)
        grid.addWidget(btn_record, row_idx, 2)
        grid.addWidget(btn_reset,  row_idx, 3)

        self._row_widgets[slot] = {
            "lbl_seq":    lbl_seq,
            "btn_record": btn_record,
        }

    def _add_delay_row(self, grid: QGridLayout, row_idx: int):
        """Add the Robo-Translate advance-delay row (label + spinbox) to *grid*."""
        robo_cfg = dict(self._settings.get("robo_translate", {}) or {})
        delay = int(robo_cfg.get("delay_seconds", 10))

        lbl_action = QLabel("Robo-translate — advance delay (seconds)")
        spin = QSpinBox()
        spin.setRange(1, 120)
        spin.setValue(delay)
        spin.valueChanged.connect(self._on_delay_changed)

        grid.addWidget(lbl_action, row_idx, 0)
        # Aligned, it keeps its own width (which follows the UI font) without capping the
        # column: a fixed-size widget would stop column 1 taking the spare width, which then
        # went to this section's Record/Reset buttons.
        grid.addWidget(spin,       row_idx, 1, Qt.AlignLeft)

    def _on_delay_changed(self, value: int):
        """Persist the Robo-Translate delay immediately, mirroring shortcut edits."""
        robo_cfg = dict(self._settings.get("robo_translate", {}) or {})
        robo_cfg["delay_seconds"] = value
        self._settings.set("robo_translate", robo_cfg)
        self._settings.save()

    def _start_recording(self, slot: str):
        """Enter recording mode for *slot*."""
        # Cancel any previous recording
        if self._recording:
            self._cancel_recording()

        self._recording = slot
        w = self._row_widgets[slot]
        w["lbl_seq"].setText("Press keys…")
        w["btn_record"].setObjectName("recordingBtn")
        w["btn_record"].setText("Cancel")
        w["btn_record"].setStyleSheet("")   # force style re-evaluation
        self._apply_style()
        self.grabKeyboard()

    def _cancel_recording(self):
        if not self._recording:
            return
        slot = self._recording
        self._recording = None
        self.releaseKeyboard()
        # Restore current binding display
        current = self._settings.get("shortcuts", {}).get(slot, SHORTCUT_DEFAULTS[slot])
        w = self._row_widgets[slot]
        w["lbl_seq"].setText(current)
        w["btn_record"].setText("Record…")
        w["btn_record"].setObjectName("")
        self._apply_style()

    def _commit_recording(self, seq_str: str):
        """Save the recorded key sequence for the active slot."""
        slot = self._recording
        self._recording = None
        self.releaseKeyboard()

        shortcuts = dict(self._settings.get("shortcuts", {}))
        shortcuts[slot] = seq_str
        self._settings.set("shortcuts", shortcuts)
        self._settings.save()

        w = self._row_widgets[slot]
        w["lbl_seq"].setText(seq_str)
        w["btn_record"].setText("Record…")
        w["btn_record"].setObjectName("")
        self._apply_style()

    def _reset(self, slot: str):
        if self._recording == slot:
            self._cancel_recording()
        default = SHORTCUT_DEFAULTS[slot]
        shortcuts = dict(self._settings.get("shortcuts", {}))
        shortcuts[slot] = default
        self._settings.set("shortcuts", shortcuts)
        self._settings.save()
        self._row_widgets[slot]["lbl_seq"].setText(default)

    def keyPressEvent(self, event):
        if not self._recording:
            if event.key() == Qt.Key.Key_Escape:
                self.accept()
            else:
                super().keyPressEvent(event)
            return

        key  = event.key()
        mods = event.modifiers()

        # Ignore bare modifier keypresses — wait for the actual key
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift,
                   Qt.Key.Key_Alt, Qt.Key.Key_Meta,
                   Qt.Key.Key_unknown):
            return

        # Cancel recording if Escape pressed (don't record Escape itself here)
        if key == Qt.Key.Key_Escape:
            self._cancel_recording()
            return

        # Build a QKeySequence and convert to portable string
        # Use keyCombination() — the correct PySide6 API that avoids
        # TypeError from int()-casting KeyboardModifier enums directly.
        seq = QKeySequence(event.keyCombination())
        seq_str = seq.toString(QKeySequence.PortableText)
        if seq_str:
            self._commit_recording(seq_str)



# ══════════════════════════════════════════════════════════════════════════════
#  TRANSLATION ENGINE LAYER
# ══════════════════════════════════════════════════════════════════════════════

# (engine key, label in Translation Settings' engine combo), in combo order. "none" is Disabled.
_TRANSLATION_ENGINES = [
    ("none",                "Disabled"),
    ("claude",              "Claude (Anthropic)  — API key required"),
    ("claude_subscription", "Claude (Subscription)  — sign in with Pro/Max"),
    ("deepl",               "DeepL"),
    ("libretranslate",      "LibreTranslate (open-source)"),
    ("google_dt",           "Google Translate  — free, no key"),
    ("mymemory_dt",         "MyMemory  — free, no key"),
    ("microsoft_dt",        "Microsoft Translator  — API key required"),
]
# Engine key -> the translator credit a successful auto-translate writes. Every engine in
# _TRANSLATION_ENGINES except "none" needs one, or the credit falls back to "Auto-translate".
_ENGINE_LABELS = {
    "claude":              "Claude (AI)",
    "claude_subscription": "Claude Subscription (AI)",
    "deepl":               "DeepL (AI)",
    "libretranslate":      "LibreTranslate (AI)",
    "google_dt":           "Google Translate (AI)",
    "mymemory_dt":         "MyMemory (AI)",
    "microsoft_dt":        "Microsoft Translator (AI)",
}


def _culture_to_deepl(culture: str) -> str:
    """Convert a BCP-47 culture code to a DeepL target-language code.

    DeepL uses uppercase 2-letter codes for most languages, but has special
    variants for English and Portuguese.  Unknown codes are passed through
    uppercased so DeepL can accept or reject them itself.
    """
    # Explicit overrides for ambiguous codes
    overrides = {
        "en-us": "EN-US", "en-gb": "EN-GB",
        "pt-br": "PT-BR", "pt-pt": "PT-PT",
        "zh-hans": "ZH",  "zh-hant": "ZH",
    }
    lower = culture.lower()
    if lower in overrides:
        return overrides[lower]
    # Generic: take the first part (language subtag) and uppercase it
    return culture.split("-")[0].upper()


def _culture_to_bcp47(culture: str) -> str:
    """Return the plain BCP-47 language subtag (e.g. 'lv-LV' → 'lv')."""
    return culture.split("-")[0].lower() if culture else ""


def _match_glossary(text: str, glossary: List[GlossaryEntry]) -> List[GlossaryEntry]:
    """Return the glossary entries whose term appears as a whole word/phrase
    in *text*, case-insensitively. Mirrors the word-boundary technique
    already used by FilterEngine.matches for search, so multi-word terms
    (e.g. "pin setter") match correctly too.

    Tolerates a regular English plural suffix ("s" or "es") so a single
    singular entry (e.g. "Lane") also matches its plural ("Lanes") without
    requiring a second glossary row. This only covers the regular -s/-es
    pattern, not irregular plurals (e.g. "child"/"children") or other word
    forms (e.g. verb tense) -- those still need their own glossary row.
    """
    matched = []
    for g in glossary:
        pat = re.compile(r"\b" + re.escape(g.term) + r"(?:es|s)?\b", re.IGNORECASE)
        if pat.search(text):
            matched.append(g)
    return matched


def _format_glossary_prompt_block(matched: List[GlossaryEntry]) -> str:
    """Build the extra prompt text for matched glossary entries, or ''
    if nothing matched (so the prompt is byte-identical to today's when a
    string contains no glossary terms)."""
    if not matched:
        return ""
    lines = [
        "\n\nGlossary — use these exact translations for the listed terms "
        "if they appear in the text:"
    ]
    for g in matched:
        if g.note:
            lines.append(f'- "{g.term}" → "{g.translation}" ({g.note})')
        else:
            lines.append(f'- "{g.term}" → "{g.translation}"')
    return "\n".join(lines)


def _translate_claude(text: str, target_culture: str, api_key: str, model: str,
                       glossary: Optional[List[GlossaryEntry]] = None) -> str:
    """Translate *text* from English to *target_culture* using the Claude API.

    *glossary*, if given, is the list of GlossaryEntry rows already matched
    against *text* by the caller (see _match_glossary) — appended to the
    prompt so the model uses the required translation for those terms.
    """
    import urllib.request, json as _json

    lang_tag = target_culture  # pass the full culture code; Claude understands it
    prompt   = (
        f"Translate the following UI string from English to the language with "
        f"BCP-47 code '{lang_tag}'.  "
        f"Return ONLY the translated text — no explanation, no quotes, no commentary."
        f"{_format_glossary_prompt_block(glossary or [])}\n\n"
        f"{text}"
    )
    payload  = _json.dumps({
        "model":      model,
        "max_tokens": 512,
        "messages":   [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data    = payload,
        headers = {
            "Content-Type":      "application/json",
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
        },
        method = "POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(
            f"Claude API HTTP {e.code} {e.reason}\n{body[:300]}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Claude API: could not connect ({e.reason})") from e
    return data["content"][0]["text"].strip()


def _translate_deepl(text: str, target_culture: str,
                     api_key: str, use_free: bool) -> str:
    """Translate *text* using the DeepL REST API (v2).

    Authentication uses the ``Authorization: DeepL-Auth-Key`` header
    (the old ``auth_key`` form-field method was removed in the v2 API
    and returns HTTP 403).

    Free-tier keys always end with ``:fx``; if the key has that suffix
    we force ``api-free.deepl.com`` regardless of the *use_free* flag,
    because sending a free-tier key to ``api.deepl.com`` also gives 403.
    """
    import urllib.request, urllib.parse, json as _json

    # Auto-detect free tier from the key suffix
    is_free = use_free or api_key.strip().endswith(":fx")
    host    = "api-free.deepl.com" if is_free else "api.deepl.com"
    url     = f"https://{host}/v2/translate"
    payload = urllib.parse.urlencode({
        "text":        text,
        "source_lang": "EN",
        "target_lang": _culture_to_deepl(target_culture),
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    # DeepL v2 requires the key as a bearer-style Authorization header
    req.add_header("Authorization", f"DeepL-Auth-Key {api_key}")
    req.add_header("Content-Type",  "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(
            f"DeepL HTTP {e.code} {e.reason}\n"
            f"Host used: {host}\n"
            f"Response: {body[:300]}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"DeepL: could not connect ({e.reason})\nHost used: {host}") from e
    return data["translations"][0]["text"]


def _translate_libretranslate(text: str, target_culture: str,
                               base_url: str, api_key: str) -> str:
    """Translate *text* using a LibreTranslate endpoint."""
    import urllib.request, json as _json

    url     = base_url.rstrip("/") + "/translate"
    payload = _json.dumps({
        "q":      text,
        "source": "en",
        "target": _culture_to_bcp47(target_culture),
        "format": "text",
        "api_key": api_key,
    }).encode()
    req = urllib.request.Request(
        url,
        data    = payload,
        headers = {"Content-Type": "application/json"},
        method  = "POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"LibreTranslate HTTP {e.code} {e.reason}\n{body[:300]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"LibreTranslate: could not connect ({e.reason})") from e
    return data["translatedText"]


_GOOGLE_RETRY_DELAY_S = 3.0
_GOOGLE_RATE_LIMIT_MSG = ("Google is rate-limiting this network (HTTP 429). Wait a few minutes, "
                          "raise the Robo-Translate delay or switch engine.")


def _sleep_unless_cancelled(seconds: float, is_cancelled: Callable[[], bool]) -> bool:
    """Sleep in short steps; False as soon as *is_cancelled* reports True. App shutdown waits
    only 2 s for a translation thread, so a plain sleep could outlive it."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if is_cancelled():
            return False
        time.sleep(0.1)
    return not is_cancelled()


def _translate_google_dt(text: str, target_culture: str,
                         is_cancelled: Callable[[], bool] = lambda: False) -> str:
    """Translate *text* from English to *target_culture* using Google Translate
    (via the deep-translator library; free, no API key).

    The library scrapes Google's public web page, which answers HTTP 429 when it throttles an IP
    address. One retry after a short pause covers a brief burst. The library's own advice
    ("try the translate_batch function") does not help: translate_batch just calls translate()
    once per string, so it sends the same requests back to back."""
    from deep_translator import GoogleTranslator
    from deep_translator.exceptions import TooManyRequests

    try:
        translator = GoogleTranslator(source="en", target=_culture_to_bcp47(target_culture))
        try:
            result = translator.translate(text)
        except TooManyRequests:
            if not _sleep_unless_cancelled(_GOOGLE_RETRY_DELAY_S, is_cancelled):
                raise
            result = translator.translate(text)
    except TooManyRequests as exc:
        raise RuntimeError(_GOOGLE_RATE_LIMIT_MSG) from exc
    except Exception as exc:
        raise RuntimeError(str(exc)[:300]) from exc
    if not result:
        raise RuntimeError("Google Translate returned an empty response.")
    return result


def _translate_mymemory_dt(text: str, target_culture: str, email: str = "") -> str:
    """Translate *text* from English to *target_culture* using MyMemory
    (via the deep-translator library; free, no API key required).

    Passing *email* raises the free daily quota from 5,000 to 50,000 characters.
    """
    from deep_translator import MyMemoryTranslator

    # Normalize culture code casing: MyMemory is strict about region subtag casing (e.g. "de-DE" works, "de-de" fails)
    parts  = target_culture.split("-")
    target = f"{parts[0].lower()}-{parts[1].upper()}" if len(parts) >= 2 else target_culture

    kwargs = {"email": email.strip()} if email.strip() else {}
    try:
        result = MyMemoryTranslator(source="en-US", target=target, **kwargs).translate(text)
    except Exception as exc:
        raise RuntimeError(str(exc)[:300]) from exc
    if not result:
        raise RuntimeError("MyMemory returned an empty response.")
    return result


def _translate_microsoft_dt(text: str, target_culture: str,
                             api_key: str, region: str = "") -> str:
    """Translate *text* from English to *target_culture* using Microsoft
    Translator (via the deep-translator library; Azure API key required)."""
    from deep_translator import MicrosoftTranslator

    if not api_key.strip():
        raise ValueError("No Microsoft Translator API key configured.")
    target = _culture_to_bcp47(target_culture)
    kwargs = {"region": region.strip()} if region.strip() else {}
    try:
        result = MicrosoftTranslator(
            api_key=api_key.strip(), source="en", target=target, **kwargs
        ).translate(text)
    except Exception as exc:
        raise RuntimeError(str(exc)[:300]) from exc
    if not result:
        raise RuntimeError("Microsoft Translator returned an empty response.")
    return result


class TranslationThread(QThread):
    """Runs a translation call off the main thread.

    Signals
    -------
    finished(str)   — emitted with the translated text on success
    errored(str)    — emitted with an error message on failure
    """
    finished = Signal(str)
    errored  = Signal(str)

    def __init__(self, text: str, target_culture: str, cfg: dict, mw=None, parent=None):
        super().__init__(parent)
        self._text    = text
        self._culture = target_culture
        self._cfg     = cfg
        self._mw      = mw

    def run(self):
        try:
            engine = self._cfg.get("engine", "none")
            matched_glossary: List[GlossaryEntry] = []
            if (self._cfg.get("glossary_enabled", True)
                    and self._mw is not None
                    and engine in ("claude", "claude_subscription")):
                matched_glossary = _match_glossary(
                    self._text, getattr(self._mw, "glossary", []))
            if engine == "claude":
                key    = self._cfg.get("claude_api_key", "").strip()
                if not key:
                    raise ValueError("No Claude API key configured.")
                model  = self._cfg.get("claude_model", "claude-haiku-4-5-20251001")
                result = _translate_claude(self._text, self._culture, key, model,
                                            glossary=matched_glossary)
            elif engine == "claude_subscription":
                if self._mw is None:
                    raise RuntimeError(
                        "Claude subscription engine is unavailable in this context.")
                session = self._mw._get_claude_session()
                model   = self._cfg.get("claude_model", "claude-haiku-4-5-20251001")
                result  = session.translate(self._text, self._culture, model,
                                             glossary=matched_glossary)
            elif engine == "deepl":
                key    = self._cfg.get("deepl_api_key", "").strip()
                if not key:
                    raise ValueError("No DeepL API key configured.")
                result = _translate_deepl(
                    self._text, self._culture, key,
                    self._cfg.get("deepl_free", True)
                )
            elif engine == "libretranslate":
                base   = self._cfg.get("libretranslate_url",
                                       "https://libretranslate.com").strip()
                key    = self._cfg.get("libretranslate_key", "").strip()
                result = _translate_libretranslate(self._text, self._culture,
                                                   base, key)
            elif engine == "google_dt":
                result = _translate_google_dt(self._text, self._culture,
                                              self.isInterruptionRequested)
            elif engine == "mymemory_dt":
                result = _translate_mymemory_dt(
                    self._text, self._culture,
                    self._cfg.get("mymemory_email", "")
                )
            elif engine == "microsoft_dt":
                result = _translate_microsoft_dt(
                    self._text, self._culture,
                    self._cfg.get("microsoft_api_key", "").strip(),
                    self._cfg.get("microsoft_region", "")
                )
            else:
                raise ValueError("No translation engine configured.\n"
                                 "Open View → Translation Settings…")
            self.finished.emit(result)
        except Exception as exc:
            self.errored.emit(str(exc))


class _TranslationRequest:
    """One queued `translate()` call: the prompt to send, plus the
    `concurrent.futures.Future` the calling `TranslationThread` blocks on.

    `abandoned` means the caller has stopped waiting (navigated away, closed
    the dialog, or timed out).  The pump drains this request's response to
    completion regardless — see `ClaudeSubscriptionSession._pump()`.
    """
    __slots__ = ("prompt", "timeout", "future", "abandoned")

    def __init__(self, prompt: str, timeout: float):
        self.prompt    = prompt
        self.timeout   = timeout
        self.future: concurrent.futures.Future = concurrent.futures.Future()
        self.abandoned = False

    def settle(self, result: Optional[str] = None,
               exc: Optional[BaseException] = None) -> None:
        """Resolve the waiting caller, unless it is already resolved — an
        abandoned request's future is completed at abandon time, and the pump
        settles it again with the (discarded) real outcome later."""
        if self.future.done():
            return
        if exc is not None:
            self.future.set_exception(exc)
        else:
            self.future.set_result(result or "")


# The shipped exe is --windowed, so it has no console, and Windows opens a new console window
# for every console program it starts (the claude CLI): a near-full-screen terminal over the
# editor. CREATE_NO_WINDOW starts the child with no window. From source the launcher's console
# is inherited instead, which is why this only showed in the built exe.
_NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _install_no_window_process_spawn() -> None:
    """Make claude-agent-sdk start its processes with CREATE_NO_WINDOW on Windows.

    The SDK offers no option for it, but every process it starts (the CLI session and its
    `claude -v` version check) goes through `anyio.open_process`, which takes `creationflags`.
    Wrapping it is process-wide; flags a caller sets itself are left alone. Idempotent. If a
    later SDK stops using `anyio.open_process`, the window comes back but nothing breaks."""
    if not _NO_WINDOW_FLAGS:
        return
    import anyio
    original = anyio.open_process
    if getattr(original, "_xte_no_window", False):
        return

    async def open_process_without_window(*args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = _NO_WINDOW_FLAGS
        return await original(*args, **kwargs)

    open_process_without_window._xte_no_window = True
    anyio.open_process = open_process_without_window


class ClaudeSubscriptionSession:
    """Owns one persistent `claude` CLI subprocess (via claude-agent-sdk) for the
    app's lifetime.

    Created lazily on first use by MainWindow._get_claude_session() and reused
    for every subsequent translation, so no new OS process is spawned per
    string. All SDK calls happen on a dedicated background thread running its
    own asyncio event loop; translate() blocks the calling thread (a
    TranslationThread) until the result or an error is available.

    **The pump owns the client.** Requests are queued and executed strictly one
    at a time by a single long-lived `_pump()` coroutine, which always consumes
    each response through its `ResultMessage`.  Callers never touch the stream
    themselves.  This is not stylistic: the SDK's `receive_response()` has no
    query→response correlation — it yields whatever arrives next on one shared
    stream and stops at the first `ResultMessage` — so a consumer that walks
    away mid-response leaves the CLI's remaining messages buffered for whoever
    reads next, permanently shifting every later translation onto the previous
    one's answer.  See `_pump()` and `cancel_current()`.
    """

    def __init__(self, token: str, model: str):
        self._token   = token
        self._model   = model
        self._loop    = None   # asyncio.AbstractEventLoop, set on the loop thread
        self._thread  = None   # threading.Thread
        self._client  = None   # claude_agent_sdk.ClaudeSDKClient
        self._ready   = threading.Event()
        self._start_error = None
        self._start_lock = threading.Lock()  # makes start() genuinely idempotent
        self._queue     = None   # asyncio.Queue[_TranslationRequest], made on the loop
        self._pump_task = None   # asyncio.Task running _pump()
        self._current: Optional[_TranslationRequest] = None  # in-flight request
        self._req_lock  = threading.Lock()   # guards _current across threads

    @property
    def token(self) -> str:
        return self._token

    @property
    def model(self) -> str:
        return self._model

    def start(self):
        """Boot the background thread + event loop + SDK client + pump.
        Idempotent, and guarded by _start_lock so two callers racing to start
        the session for the first time can't both spawn a background thread.

        Every caller waits on _ready, including one that finds the thread
        already spawned: the request queue is created during boot, so a caller
        that skipped the wait could otherwise reach translate() while
        self._queue is still None."""
        with self._start_lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run_loop, daemon=True)
                self._thread.start()
            ready = self._ready.wait(timeout=30)
            if self._start_error:
                err = self._start_error
                self._thread = None
                self._start_error = None
                self._ready.clear()
                raise RuntimeError(err)
            if not ready:
                self._thread = None
                self._ready.clear()
                raise RuntimeError("Claude subscription session timed out while starting.")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._boot())
            self._ready.set()
            self._loop.run_forever()
        except Exception as exc:
            self._start_error = str(exc)[:300]
            self._ready.set()

    async def _boot(self):
        """Connect, then start the pump. The pump task stays pending when
        run_until_complete() returns and keeps running under run_forever()."""
        await self._connect()
        self._queue = asyncio.Queue()
        self._pump_task = asyncio.create_task(self._pump())

    async def _connect(self):
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        _install_no_window_process_spawn()
        options = ClaudeAgentOptions(
            model=self._model,
            env={"CLAUDE_CODE_OAUTH_TOKEN": self._token},
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()

    async def _reconnect(self):
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        await self._connect()

    async def _pump(self):
        """Run queued requests one at a time, always draining each response
        through its ResultMessage — including for a request whose caller has
        given up.  Abandoning a drain would desync the SDK's shared message
        stream (see the class docstring), so cancellation stops the *caller*
        waiting, never the drain."""
        while True:
            req = await self._queue.get()
            if req is None:
                return
            with self._req_lock:
                self._current = req
            try:
                text = await self._run_request(req)
            except asyncio.CancelledError:
                req.settle(exc=RuntimeError("Claude subscription session closed."))
                raise
            except Exception as exc:
                req.settle(exc=exc)
            else:
                req.settle(result=text)
            finally:
                with self._req_lock:
                    self._current = None

    async def _run_request(self, req: _TranslationRequest) -> str:
        """Drain one request, reconnecting and retrying once if the connection
        broke or the drain overran its own timeout."""
        try:
            return await asyncio.wait_for(self._drain(req.prompt),
                                          timeout=req.timeout)
        except asyncio.CancelledError:
            raise
        except Exception as first_exc:
            # Either the connection broke, or wait_for cancelled the drain
            # mid-response. Either way the stream's position is now unknown,
            # and reconnecting is the only way back to a known-good state —
            # a fresh subprocess starts with an empty stream.
            try:
                await self._reconnect()
            except Exception as reconnect_exc:
                raise RuntimeError(
                    "Claude subscription session lost and could not "
                    f"reconnect: {str(reconnect_exc)[:300]}") from reconnect_exc
            if req.abandoned:
                raise first_exc          # nobody is waiting; don't re-ask
            return await asyncio.wait_for(self._drain(req.prompt),
                                          timeout=req.timeout)

    async def _drain(self, prompt: str) -> str:
        from claude_agent_sdk import AssistantMessage, TextBlock
        await self._client.query(prompt)
        parts = []
        async for message in self._client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
        return "".join(parts).strip()

    def translate(self, text: str, target_culture: str, model: str,
                  glossary: Optional[List[GlossaryEntry]] = None,
                  timeout: float = 60.0) -> str:
        """Translate *text*, starting the session on first call. Blocks the
        calling thread until the pump reports back. A deliberate
        cancel_current() call raises concurrent.futures.CancelledError here."""
        self._model = model
        self.start()
        prompt = (
            f"Translate the following UI string from English to the language "
            f"with BCP-47 code '{target_culture}'.  "
            f"Return ONLY the translated text — no explanation, no quotes, no commentary."
            f"{_format_glossary_prompt_block(glossary or [])}\n\n"
            f"{text}"
        )
        req = _TranslationRequest(prompt, timeout)
        self._loop.call_soon_threadsafe(self._queue.put_nowait, req)
        try:
            return req.future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            # Stop waiting, but leave the pump draining so the stream stays in
            # lockstep; it reconnects on its own if the drain overruns too.
            self._abandon(req, concurrent.futures.CancelledError())
            raise RuntimeError("Claude subscription translation timed out.") from None

    def _abandon(self, req: _TranslationRequest, exc: BaseException) -> None:
        """Stop waiting on *req* without abandoning its place in the stream:
        settle the caller's future now and ask the CLI to end the turn early.
        The pump keeps draining this request's response either way."""
        req.abandoned = True
        req.settle(exc=exc)
        if self._loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._interrupt_current(), self._loop)
            except RuntimeError:
                pass          # loop already stopped (app closing)

    async def _interrupt_current(self):
        """Ask the CLI to end the current turn early. Best-effort: correctness
        never depends on this succeeding — the pump drains to the ResultMessage
        regardless — only on how soon the next translation can start."""
        if self._client is None:
            return
        try:
            await self._client.interrupt()
        except Exception:
            pass

    def cancel_current(self):
        """Stop waiting on whatever call is currently in flight, so the caller
        unblocks immediately instead of sitting out the full timeout. No-op if
        nothing is in flight.

        This deliberately does NOT cancel the coroutine consuming the response.
        The SDK multiplexes every query onto one shared, uncorrelated message
        stream, so a consumer that stops reading mid-response leaves the CLI's
        remaining messages buffered for the next reader — which then returns
        the *previous* entry's translation, and stays one behind for the rest
        of the session. The pump therefore always drains; only the waiter goes
        away. `_interrupt_current()` asks the CLI to cut the turn short so the
        drain finishes quickly."""
        with self._req_lock:
            req = self._current
        if req is None:
            return
        self._abandon(req, concurrent.futures.CancelledError())

    def close(self):
        """Tear down the client, stop the pump and event loop, join the thread."""
        if self._loop is None:
            return

        closed = RuntimeError("Claude subscription session closed.")

        async def _shutdown():
            # Settle anything still outstanding so no caller blocks until its
            # own timeout while the loop it is waiting on is being torn down.
            if self._queue is not None:
                while True:
                    try:
                        queued = self._queue.get_nowait()
                    except Exception:
                        break
                    if queued is not None:
                        queued.settle(exc=closed)
            with self._req_lock:
                current = self._current
            if current is not None:
                current.settle(exc=closed)
            if self._pump_task is not None:
                self._pump_task.cancel()
            if self._client is not None:
                try:
                    await self._client.disconnect()
                except Exception:
                    pass

        try:
            future = asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
            future.result(timeout=10)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=10)


# ══════════════════════════════════════════════════════════════════════════════
#  TRANSLATION SETTINGS DIALOG
# ══════════════════════════════════════════════════════════════════════════════

class ClaudeSetupTokenThread(QThread):
    """Runs `claude setup-token` in the background so the interactive browser
    login (triggered by the CLI) doesn't freeze the Translation Settings UI.
    """
    finished = Signal(str)   # captured OAuth token
    errored  = Signal(str)

    def run(self):
        claude_exe = shutil.which("claude")
        if claude_exe is None:
            self.errored.emit(
                "Claude CLI not found. Install Node.js and run "
                "'npm install -g @anthropic-ai/claude-code', then try again."
            )
            return
        try:
            proc = subprocess.run(
                [claude_exe, "setup-token"],
                capture_output=True, text=True, timeout=300,
                creationflags=_NO_WINDOW_FLAGS,
            )
        except FileNotFoundError:
            self.errored.emit(
                "Claude CLI not found. Install Node.js and run "
                "'npm install -g @anthropic-ai/claude-code', then try again."
            )
            return
        except subprocess.TimeoutExpired:
            self.errored.emit("Sign-in timed out. Please try again.")
            return
        if proc.returncode != 0:
            self.errored.emit((proc.stderr or "Sign-in failed.").strip()[:300])
            return
        # `claude setup-token` prints multi-line human-readable CLI output
        # (login instructions, confirmation text, possibly ANSI colour codes)
        # around the token, not just the bare token — extract it by its
        # documented `sk-ant-` prefix rather than trusting the whole blob.
        clean = re.sub(r"\x1b\[[0-9;]*m", "", proc.stdout)
        match = re.search(r"sk-ant-[A-Za-z0-9_\-\.]+", clean)
        if not match:
            self.errored.emit("Sign-in completed but no token was found in the CLI output.")
            return
        self.finished.emit(match.group(0))


class TranslationSettingsDialog(QDialog):
    """Configure which translation engine to use and store API keys."""

    _MIN_WIDTH = 500

    def __init__(self, settings: "Settings", parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Translation Settings")
        self.setMinimumWidth(self._MIN_WIDTH)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._build()
        self._apply_style()
        self._fit_to_content()

    def _theme(self) -> dict:
        mw = self.parent()
        return mw._get_theme() if mw and hasattr(mw, "_get_theme") else THEMES["dark"]

    def _fit_to_content(self):
        """Width once, to the widest engine group, so switching engines never moves the
        right edge; the height follows the selected engine (_fit_height)."""
        lay = self.layout()
        margins = lay.contentsMargins()
        widest = max(grp.sizeHint().width() for grp in self._engine_groups)
        width = max(lay.sizeHint().width(), widest + margins.left() + margins.right())
        screen = self.screen()
        if screen is not None:
            width = min(width, screen.availableGeometry().width() - 60)
        self.resize(width, self.height())
        self._fit_height()

    def _content_height(self, width: int) -> int:
        lay = self.layout()
        return lay.heightForWidth(width) if lay.hasHeightForWidth() else lay.sizeHint().height()

    def _fit_height(self):
        """Snap the height to the content at the current width, and make that the minimum
        so a drag cannot clip it. Qt grows a window whose content grows but never shrinks
        one, so without this a small engine inherited the height of the biggest group shown
        before it."""
        lay = self.layout()
        lay.activate()
        self.setMinimumWidth(max(self._MIN_WIDTH, lay.minimumSize().width()))
        height = self._content_height(self.width())
        self.setMinimumHeight(0)   # the old minimum would block a shrink
        self.resize(self.width(), height)
        self.setMinimumHeight(height)

    def event(self, event: QEvent) -> bool:
        # A child's size changed: an engine group shown or hidden, a long test result or
        # sign-in status. The layout no longer sizes the window itself (see _build), so refit.
        # Qt hands this event to the layout, which re-activates, before it reaches us.
        handled = super().event(event)
        if event.type() == QEvent.LayoutRequest:
            self._fit_height()
        return handled

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # A narrower window rewraps the hints; raise the minimum so they are never clipped.
        self.setMinimumHeight(self._content_height(self.width()))

    def _apply_style(self):
        t = self._theme()
        pt = self._settings.get_font().pointSize() or 10
        self.setStyleSheet(f"""
            QDialog   {{ background: {t['dlg_bg']}; }}
            QLabel    {{ color: {t['fg']}; }}
            {_groupbox_qss(t, pt)}
            QLineEdit {{ background: {t['dlg_edit_bg']}; color: {t['fg']};
                         border: 1px solid {t['border']}; border-radius: 3px;
                         padding: 4px 6px; }}
            QComboBox {{ background: {t['bg4']}; color: {t['fg']};
                         border: 1px solid {t['border2']}; border-radius: 3px;
                         padding: 3px 6px; }}
            QComboBox QAbstractItemView {{ background: {t['bg2']}; color: {t['fg']};
                                           selection-background-color: {t['sel_bg']};
                                           selection-color: {t['sel_fg']}; }}
            {_combobox_qss(t, pt)}
            QCheckBox {{ color: {t['fg']}; }}
            {_prominent_checkbox_qss(t)}
            {_button_qss(t, pt)}
            {_field_state_qss(t)}
        """)
        hint_style = f"color: {t['fg_dim']}; font-size: {max(8, pt - 1)}pt;"
        for hint_lbl in (self._claude_hint, self._claude_sub_hint, self._deepl_hint,
                         self._libre_hint, self._google_hint, self._mymemory_hint,
                         self._microsoft_hint):
            hint_lbl.setStyleSheet(hint_style)

    def _build(self):
        cfg = self._settings.get("translation", {})
        defaults = self._settings.DEFAULTS.get("translation", {})

        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(16, 16, 16, 12)
        # _fit_height() alone sizes the window. With the default constraint Qt also grew it
        # whenever a bigger engine group appeared, overshooting (it sizes for the minimum
        # width), and Windows moved that grow up the screen at 150 % scaling and a 14 pt
        # font, so the dialog walked upwards with every engine switch.
        lay.setSizeConstraint(QLayout.SetNoConstraint)

        # ── General ──
        general_grp = QGroupBox("General")
        gg = QFormLayout(general_grp)
        self._skip_translator_chk = QCheckBox("Skip translator name prompt on startup")
        self._skip_translator_chk.setProperty("filterChk", True)
        self._skip_translator_chk.setChecked(
            bool(self._settings.get("skip_translator_prompt", False)))
        gg.addRow("", self._skip_translator_chk)
        self._glossary_chk = QCheckBox("Use glossary for AI translation (Claude engines)")
        self._glossary_chk.setProperty("filterChk", True)
        self._glossary_chk.setChecked(
            bool(cfg.get("glossary_enabled", defaults.get("glossary_enabled", True))))
        gg.addRow("", self._glossary_chk)
        lay.addWidget(general_grp)

        # ── Engine selector ──
        engine_grp = QGroupBox("Translation Engine")
        eg = QFormLayout(engine_grp)
        self._engine_combo = _WidePopupComboBox()
        engines = _TRANSLATION_ENGINES
        for key, label in engines:
            self._engine_combo.addItem(label, key)
        cur_engine = cfg.get("engine", defaults.get("engine", "none"))
        idx = next((i for i, (k, _) in enumerate(engines) if k == cur_engine), 0)
        self._engine_combo.setCurrentIndex(idx)
        self._engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        eg.addRow("Engine:", self._engine_combo)
        lay.addWidget(engine_grp)

        # ── Claude settings ──
        self._claude_grp = QGroupBox("Claude API settings")
        cg = QFormLayout(self._claude_grp)
        self._claude_key = QLineEdit(cfg.get("claude_api_key",
                                             defaults.get("claude_api_key", "")))
        self._claude_key.setPlaceholderText("sk-ant-…")
        self._claude_key.setEchoMode(QLineEdit.Password)
        cg.addRow("API Key:", self._claude_key)
        self._claude_model = _WidePopupComboBox()
        claude_models = [
            ("claude-haiku-4-5-20251001", "Haiku 4.5 — fast, low cost"),
            ("claude-sonnet-5",           "Sonnet 5 — balanced"),
            ("claude-opus-5",             "Opus 5 — highest quality"),
        ]
        for model_id, label in claude_models:
            self._claude_model.addItem(label, model_id)
        cur_model = cfg.get("claude_model",
                            defaults.get("claude_model", "claude-haiku-4-5-20251001"))
        model_idx = next((i for i, (m, _) in enumerate(claude_models) if m == cur_model), 0)
        self._claude_model.setCurrentIndex(model_idx)
        cg.addRow("Model:", self._claude_model)
        self._claude_hint = QLabel(
            'Get a key at <a href="https://console.anthropic.com">console.anthropic.com</a>.'
        )
        self._claude_hint.setOpenExternalLinks(True)
        self._claude_hint.setWordWrap(True)
        # A blank QLabel, not "": a row with no label widget sizes a word-wrapped
        # hint at the wrong width and pads it with a blank band above and below.
        cg.addRow(QLabel(), self._claude_hint)
        lay.addWidget(self._claude_grp)

        # ── Claude Subscription settings ──
        self._claude_sub_grp = QGroupBox("Claude Subscription settings")
        csg = QFormLayout(self._claude_sub_grp)
        self._claude_sub_status = QLabel()
        csg.addRow("Status:", self._claude_sub_status)
        self._claude_sub_signin_btn = QPushButton("Sign in with Claude subscription")
        self._claude_sub_signin_btn.clicked.connect(self._on_claude_sub_signin_clicked)
        csg.addRow("", self._claude_sub_signin_btn)
        self._claude_sub_model = _WidePopupComboBox()
        for model_id, label in claude_models:
            self._claude_sub_model.addItem(label, model_id)
        self._claude_sub_model.setCurrentIndex(model_idx)
        csg.addRow("Model:", self._claude_sub_model)
        self._claude_sub_hint = QLabel(
            "Reuses your existing Claude Pro/Max subscription — no separate API "
            "billing. Requires Node.js and the Claude CLI "
            '(<a href="https://www.anthropic.com/claude-code">claude-code</a>); '
            "the launcher installs these automatically if missing."
        )
        self._claude_sub_hint.setOpenExternalLinks(True)
        self._claude_sub_hint.setWordWrap(True)
        csg.addRow(QLabel(), self._claude_sub_hint)
        lay.addWidget(self._claude_sub_grp)
        self._update_claude_sub_status()

        # ── DeepL settings ──
        self._deepl_grp = QGroupBox("DeepL API settings")
        dg = QFormLayout(self._deepl_grp)
        self._deepl_key = QLineEdit(cfg.get("deepl_api_key",
                                             defaults.get("deepl_api_key", "")))
        self._deepl_key.setPlaceholderText("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx:fx  (free key ends with :fx)")
        self._deepl_key.setEchoMode(QLineEdit.Password)
        dg.addRow("API Key:", self._deepl_key)
        self._deepl_free_chk = QCheckBox("Use DeepL Free tier  (api-free.deepl.com)  — auto-detected from :fx suffix")
        self._deepl_free_chk.setProperty("filterChk", True)
        self._deepl_free_chk.setChecked(cfg.get("deepl_free",
                                                  defaults.get("deepl_free", True)))
        dg.addRow("", self._deepl_free_chk)
        self._deepl_hint = QLabel(
            'Free tier: 500 000 characters/month.  '
            'Get a key at <a href="https://www.deepl.com/pro-api">deepl.com/pro-api</a>.'
        )
        self._deepl_hint.setOpenExternalLinks(True)
        self._deepl_hint.setWordWrap(True)
        dg.addRow(QLabel(), self._deepl_hint)
        lay.addWidget(self._deepl_grp)

        # ── LibreTranslate settings ──
        self._libre_grp = QGroupBox("LibreTranslate settings")
        lg = QFormLayout(self._libre_grp)
        self._libre_url = QLineEdit(cfg.get("libretranslate_url",
                                             defaults.get("libretranslate_url",
                                                          "https://libretranslate.com")))
        lg.addRow("Server URL:", self._libre_url)
        self._libre_key = QLineEdit(cfg.get("libretranslate_key",
                                             defaults.get("libretranslate_key", "")))
        self._libre_key.setPlaceholderText("Leave blank if server requires no key")
        self._libre_key.setEchoMode(QLineEdit.Password)
        lg.addRow("API Key:", self._libre_key)
        self._libre_hint = QLabel(
            "Use the public server above, or run your own: "
            '<a href="https://github.com/LibreTranslate/LibreTranslate">github.com/LibreTranslate</a>.'
        )
        self._libre_hint.setOpenExternalLinks(True)
        self._libre_hint.setWordWrap(True)
        lg.addRow(QLabel(), self._libre_hint)
        lay.addWidget(self._libre_grp)

        # ── Google Translate settings ──
        self._google_grp = QGroupBox("Google Translate settings")
        ggl = QFormLayout(self._google_grp)
        self._google_hint = QLabel(
            "Free, keyless translation via the unofficial Google Translate "
            "endpoint. No configuration needed."
        )
        self._google_hint.setWordWrap(True)
        ggl.addRow(QLabel(), self._google_hint)
        lay.addWidget(self._google_grp)

        # ── MyMemory settings ──
        self._mymemory_grp = QGroupBox("MyMemory settings")
        mmg = QFormLayout(self._mymemory_grp)
        self._mymemory_email = QLineEdit(cfg.get("mymemory_email",
                                                   defaults.get("mymemory_email", "")))
        self._mymemory_email.setPlaceholderText("you@example.com  (optional)")
        mmg.addRow("Email:", self._mymemory_email)
        self._mymemory_hint = QLabel(
            "Free tier: 5,000 characters/day.  Adding an email address "
            "raises the quota to 50,000 characters/day."
        )
        self._mymemory_hint.setWordWrap(True)
        mmg.addRow(QLabel(), self._mymemory_hint)
        lay.addWidget(self._mymemory_grp)

        # ── Microsoft Translator settings ──
        self._microsoft_grp = QGroupBox("Microsoft Translator settings")
        micg = QFormLayout(self._microsoft_grp)
        self._microsoft_key = QLineEdit(cfg.get("microsoft_api_key",
                                                  defaults.get("microsoft_api_key", "")))
        self._microsoft_key.setPlaceholderText("Azure Translator resource key")
        self._microsoft_key.setEchoMode(QLineEdit.Password)
        micg.addRow("API Key:", self._microsoft_key)
        self._microsoft_region = QLineEdit(cfg.get("microsoft_region",
                                                     defaults.get("microsoft_region", "")))
        self._microsoft_region.setPlaceholderText("e.g. westeurope  (leave blank for global resources)")
        micg.addRow("Region:", self._microsoft_region)
        self._microsoft_hint = QLabel(
            'Get a key at <a href="https://portal.azure.com">portal.azure.com</a> '
            "(create a Translator resource).  Region is required for "
            "regional (non-global) resources."
        )
        self._microsoft_hint.setOpenExternalLinks(True)
        self._microsoft_hint.setWordWrap(True)
        micg.addRow(QLabel(), self._microsoft_hint)
        lay.addWidget(self._microsoft_grp)
        self._engine_groups = (self._claude_grp, self._claude_sub_grp, self._deepl_grp,
                               self._libre_grp, self._google_grp, self._mymemory_grp,
                               self._microsoft_grp)
        # Extra height from a manual resize collects here, not as gaps between the groups.
        lay.addStretch(1)

        # ── Test + result ──
        test_row = QHBoxLayout()
        test_row.setSpacing(8)
        self._test_btn = QPushButton("🔗  Test Connection")
        self._test_btn.setToolTip(
            "Translates the word \"Hello\" with the current settings\n"
            "to verify the engine is reachable and the key is valid.\n"
            "Settings are NOT saved by this button.")
        self._test_btn.clicked.connect(self._run_test)
        self._test_result = QLabel("")
        self._test_result.setWordWrap(True)
        test_row.addWidget(self._test_btn)
        test_row.addWidget(self._test_result, 1)
        lay.addLayout(test_row)

        # ── Save / Cancel ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("Save")
        save_btn.setProperty("role", "primary")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)

        self._on_engine_changed()  # set initial visibility

    def _selected_claude_model(self) -> str:
        if self._engine_combo.currentData() == "claude_subscription":
            return self._claude_sub_model.currentData()
        return self._claude_model.currentData()

    def _current_cfg(self) -> dict:
        """Build a translation config dict from the current (unsaved) field values."""
        return {
            "engine":             self._engine_combo.currentData(),
            "claude_api_key":     self._claude_key.text().strip(),
            "claude_model":       self._selected_claude_model(),
            "claude_subscription_token": self._settings.get("translation", {}).get(
                                      "claude_subscription_token", ""),
            "deepl_api_key":      self._deepl_key.text().strip(),
            "deepl_free":         self._deepl_free_chk.isChecked(),
            "libretranslate_url": self._libre_url.text().strip(),
            "libretranslate_key": self._libre_key.text().strip(),
            "mymemory_email":     self._mymemory_email.text().strip(),
            "microsoft_api_key":  self._microsoft_key.text().strip(),
            "microsoft_region":   self._microsoft_region.text().strip(),
        }

    def _run_test(self):
        """Translate "Hello" with the current settings and display the result."""
        engine = self._engine_combo.currentData()
        if engine == "none":
            self._test_result.setText("⚠  Select an engine first.")
            self._test_result.setStyleSheet(f"color: {self._theme()['dlg_count_warn']};")
            return

        # Infer a test target language: use the loaded file culture if available,
        # otherwise fall back to German (a reliable DeepL / LibreTranslate target).
        mw = self.parent()
        test_culture = (
            mw.target_culture
            if mw and hasattr(mw, "target_culture") and mw.target_culture
            else "de-DE"
        )

        self._test_btn.setEnabled(False)
        self._test_result.setStyleSheet(f"color: {self._theme()['fg_dim']};")
        self._test_result.setText("Testing…")

        cfg = self._current_cfg()
        thread = TranslationThread(
            "Hello", test_culture, cfg, mw=mw, parent=mw
        )
        thread.finished.connect(self._on_test_ok)
        thread.errored.connect(self._on_test_fail)
        self._test_thread = thread
        can_register = mw is not None and hasattr(mw, "_register_translation_thread")
        if can_register and not mw._register_translation_thread(thread):
            return  # app is closing; a never-started thread needs no cleanup
        thread.start()

    def _on_test_ok(self, result: str):
        mw = self.parent()
        lang = mw.target_culture if mw and hasattr(mw, "target_culture") and mw.target_culture else "de-DE"
        self._test_result.setText(f'✓  "Hello" → "{result}"  ({lang})')
        self._test_result.setStyleSheet(f"color: {self._theme()['dlg_count_ok']};")
        self._test_btn.setEnabled(True)

    def _on_test_fail(self, msg: str):
        short = msg[:200] + ("…" if len(msg) > 200 else "")
        self._test_result.setText(f"✗  {short}")
        self._test_result.setStyleSheet(f"color: {self._theme()['dlg_count_concern']};")
        self._test_result.setToolTip(msg)
        self._test_btn.setEnabled(True)

    def _update_claude_sub_status(self):
        token = self._settings.get("translation", {}).get(
            "claude_subscription_token", "").strip()
        if token:
            self._claude_sub_status.setText("✓  Signed in")
            self._claude_sub_status.setStyleSheet(f"color: {self._theme()['dlg_count_ok']};")
        else:
            self._claude_sub_status.setText("Not signed in")
            self._claude_sub_status.setStyleSheet(f"color: {self._theme()['fg_dim']};")

    def _on_claude_sub_signin_clicked(self):
        self._claude_sub_signin_btn.setEnabled(False)
        self._claude_sub_status.setText("Signing in — check your browser…")
        self._claude_sub_status.setStyleSheet(f"color: {self._theme()['fg_dim']};")
        self._signin_thread = ClaudeSetupTokenThread(parent=self)
        self._signin_thread.finished.connect(self._on_claude_sub_signin_ok)
        self._signin_thread.errored.connect(self._on_claude_sub_signin_fail)
        self._signin_thread.start()

    def _on_claude_sub_signin_ok(self, token: str):
        cfg = dict(self._settings.get("translation",
                                      dict(self._settings.DEFAULTS["translation"])))
        cfg["claude_subscription_token"] = token
        self._settings.set("translation", cfg)
        self._settings.save()
        self._update_claude_sub_status()
        self._claude_sub_signin_btn.setEnabled(True)

    def _on_claude_sub_signin_fail(self, msg: str):
        self._claude_sub_status.setText(f"✗  {msg[:200]}")
        self._claude_sub_status.setStyleSheet(f"color: {self._theme()['dlg_count_concern']};")
        self._claude_sub_status.setToolTip(msg)
        self._claude_sub_signin_btn.setEnabled(True)

    def _on_engine_changed(self):
        engine = self._engine_combo.currentData()
        self._claude_grp.setVisible(engine == "claude")
        self._claude_sub_grp.setVisible(engine == "claude_subscription")
        self._deepl_grp.setVisible(engine  == "deepl")
        self._libre_grp.setVisible(engine  == "libretranslate")
        self._google_grp.setVisible(engine == "google_dt")
        self._mymemory_grp.setVisible(engine == "mymemory_dt")
        self._microsoft_grp.setVisible(engine == "microsoft_dt")
        if hasattr(self, "_test_result"):
            self._test_result.setText("")   # clear stale result on engine switch

    def _disconnect_background_threads(self):
        """Disconnect this dialog's own slots from any still-running
        background thread, so a late result can never reach a dismissed
        dialog -- called from both closeEvent() and _save(), since
        QDialog.accept() does not route through closeEvent(). If the
        abandoned _test_thread was itself a claude_subscription call, also
        cancels it so the caller unblocks instead of sitting out the full
        timeout and delaying the next real translation -- same reasoning as
        EditDialog._abandon_stale_translation()."""
        if getattr(self, "_signin_thread", None) is not None and self._signin_thread.isRunning():
            try:
                self._signin_thread.finished.disconnect(self._on_claude_sub_signin_ok)
                self._signin_thread.errored.disconnect(self._on_claude_sub_signin_fail)
            except (TypeError, RuntimeError):
                pass
        if getattr(self, "_test_thread", None) is not None and self._test_thread.isRunning():
            try:
                self._test_thread.finished.disconnect(self._on_test_ok)
                self._test_thread.errored.disconnect(self._on_test_fail)
            except (TypeError, RuntimeError):
                pass
            if self._test_thread._cfg.get("engine") == "claude_subscription":
                mw = self.parent()
                if mw is not None and mw.claude_session is not None:
                    mw.claude_session.cancel_current()

    def _save(self):
        self._disconnect_background_threads()
        self._settings.set("skip_translator_prompt",
                            self._skip_translator_chk.isChecked())
        cfg = dict(self._settings.get("translation",
                                      dict(self._settings.DEFAULTS["translation"])))
        cfg["engine"]             = self._engine_combo.currentData()
        cfg["claude_api_key"]     = self._claude_key.text().strip()
        cfg["claude_model"]       = self._selected_claude_model()
        cfg["deepl_api_key"]      = self._deepl_key.text().strip()
        cfg["deepl_free"]         = self._deepl_free_chk.isChecked()
        cfg["libretranslate_url"] = self._libre_url.text().strip()
        cfg["libretranslate_key"] = self._libre_key.text().strip()
        cfg["mymemory_email"]     = self._mymemory_email.text().strip()
        cfg["microsoft_api_key"]  = self._microsoft_key.text().strip()
        cfg["microsoft_region"]   = self._microsoft_region.text().strip()
        cfg["glossary_enabled"]   = self._glossary_chk.isChecked()
        self._settings.set("translation", cfg)
        self._settings.save()
        self.accept()

    def reject(self):
        self._disconnect_background_threads()
        super().reject()

    def closeEvent(self, event):
        self._disconnect_background_threads()
        super().closeEvent(event)

class TranslatorNameDialog(QDialog):
    """Modal dialog shown on startup to collect the session translator name."""

    def __init__(self, initial_name: str = "", parent=None, on_demand: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Translator Name")
        self.setMinimumWidth(380)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint
        )
        self._on_demand = on_demand
        self._build(initial_name)
        self._apply_style()

    def _apply_style(self):
        mw = self.parent()
        t  = mw._get_theme() if mw and hasattr(mw, "_get_theme") else THEMES["dark"]
        pt = (mw.settings.get_font().pointSize() if mw and hasattr(mw, "settings") else 0) or 10
        self.setStyleSheet(f"""
            QDialog   {{ background: {t['dlg_bg']}; }}
            QLabel    {{ color: {t['fg']}; }}
            QLineEdit {{ background: {t['dlg_edit_bg']}; color: {t['fg']};
                         border: 1px solid {t['border']}; border-radius: 3px;
                         padding: 4px 6px; }}
            {_button_qss(t, pt)}
            {_field_state_qss(t)}
        """)

    def _build(self, initial_name: str):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 16)

        intro = ("Change your name for the current session."
                  if self._on_demand else
                  "Enter your name as the translator for this session.")
        lay.addWidget(QLabel(
            f"{intro}\n"
            "It will be used automatically when you save a changed translation."
        ))

        self._name_edit = QLineEdit(initial_name)
        self._name_edit.setPlaceholderText("Your name…")
        self._name_edit.returnPressed.connect(self._accept)
        lay.addWidget(self._name_edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        skip_btn = QPushButton("Cancel" if self._on_demand else "Skip")
        skip_btn.setToolTip("Keep the current translator name"
                             if self._on_demand else
                             "Continue without a translator name")
        skip_btn.clicked.connect(self.reject)

        ok_btn = QPushButton("Continue")
        ok_btn.setDefault(True)
        ok_btn.setProperty("role", "primary")
        ok_btn.clicked.connect(self._accept)

        btn_row.addWidget(skip_btn)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        lay.addLayout(btn_row)

        self._name_edit.setFocus()
        self._name_edit.selectAll()

    def _accept(self):
        # Allow empty name (same as skipping)
        self.accept()

    def get_name(self) -> str:
        return self._name_edit.text().strip()


class FontSettingsDialog(QDialog):
    """View → Choose UI Font… Replaces QFontDialog.getFont() (View → Choose UI Font…), whose
    Effects and Writing System groups are pure clutter here -- the app only ever persists
    font_family/font_size (see Settings.DEFAULTS), never style/strikeout/underline/script. Same
    __init__ -> _build_ui() -> _load_values() shape as every other settings dialog; a form
    dialog like AutosaveBackupDialog or ShortcutsDialog, so no header/footer bands."""

    MIN_POINT_SIZE = 6
    MAX_POINT_SIZE = 36

    def __init__(self, current: QFont, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose UI Font")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._mw = parent
        self._current = current
        self._build_ui()
        self._load_values()
        self._apply_style()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 16)

        lay.addWidget(QLabel("Choose the font used throughout the app."))

        form = QFormLayout()
        form.setSpacing(8)
        self._family_combo = QFontComboBox()
        self._family_combo.currentFontChanged.connect(self._update_preview)
        form.addRow("Font:", self._family_combo)

        self._size_spin = QSpinBox()
        self._size_spin.setRange(self.MIN_POINT_SIZE, self.MAX_POINT_SIZE)
        self._size_spin.setSuffix(" pt")
        self._size_spin.valueChanged.connect(self._update_preview)
        form.addRow("Size:", self._size_spin)
        lay.addLayout(form)

        self._preview = QLabel("The quick brown fox jumps over the lazy dog")
        self._preview.setObjectName("font_preview")
        self._preview.setWordWrap(True)
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumHeight(48)
        lay.addWidget(self._preview)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.setProperty("role", "primary")
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)
        # setDefault(True) only registers once the button is inside the dialog's layout --
        # see the "Default-button registration" pitfall in CLAUDE.md.
        save_btn.setDefault(True)

    def _load_values(self):
        self._family_combo.setCurrentFont(self._current)
        size = self._current.pointSize()
        if size <= 0:
            size = 10
        self._size_spin.setValue(max(self.MIN_POINT_SIZE, min(self.MAX_POINT_SIZE, size)))
        self._update_preview()

    def _update_preview(self, *_args):
        # setFont() alone is unreliable once any ancestor has a stylesheet (see CLAUDE.md:
        # "a widget's own stylesheet beats an inherited one") -- the label's own local QSS is
        # what actually controls its rendered font here; setStyleSheet() only overrides the two
        # properties named, so the ancestor QLabel {{ color: ... }} rule still applies.
        family = self._family_combo.currentFont().family()
        size = self._size_spin.value()
        self._preview.setStyleSheet(f'font-family: "{family}"; font-size: {size}pt;')

    def _apply_style(self):
        t = self._mw._get_theme() if self._mw and hasattr(self._mw, "_get_theme") else THEMES["dark"]
        pt = (self._mw.settings.get_font().pointSize()
              if self._mw and hasattr(self._mw, "settings") else 0) or 10
        # #font_preview deliberately gets no rule of its own beyond the general QLabel one:
        # its whole job is to show the chosen family/size, set via setFont() in
        # _update_preview(). A QSS font-size on it would permanently pin the rendered size
        # regardless of what setFont() requests afterward.
        self.setStyleSheet(f"""
            QDialog {{ background: {t['dlg_bg']}; }}
            QLabel  {{ color: {t['fg']}; }}
            QComboBox, QSpinBox {{
                background: {t['dlg_edit_bg']}; color: {t['fg']};
                border: 1px solid {t['border']}; border-radius: 3px; padding: 3px 6px;
            }}
            {_spinbox_qss(t, pt)}
            {_combobox_qss(t, pt)}
            {_button_qss(t, pt)}
            {_field_state_qss(t)}
        """)
        # setStyleSheet() re-polishes every child, which resets an explicitly-set font back to
        # the cascaded/inherited one -- so the preview's setFont() from _load_values() (which ran
        # before this) needs re-applying now that the stylesheet has settled.
        self._update_preview()

    def get_font(self) -> QFont:
        return QFont(self._family_combo.currentFont().family(), self._size_spin.value())


class FilePropertiesDialog(QDialog):
    """File -> Properties…: edit the sidecar header's language name and version and show read-only
    facts about the open file. Culture is shown but never edited. A form dialog (no bands), same
    __init__ -> _build_ui() -> _load_values() shape as the other settings dialogs; the caller reads
    display_language()/version_parts() after exec() and applies them."""

    def __init__(self, culture: str, display_language: str, version: str, facts: FileFacts,
                 has_unsaved: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("File Properties")
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._mw = parent
        self._culture = culture
        self._stored_language = display_language
        self._stored_version = version
        self._stored_parts = parse_version_parts(version)
        self._facts = facts
        self._has_unsaved = has_unsaved
        self._version_touched = False
        self._build_ui()
        self._load_values()
        self._apply_style()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 16)

        header = QGroupBox("Header")
        form = QFormLayout(header)
        form.setSpacing(8)
        self._header_form = form
        culture_row = QHBoxLayout()
        culture_row.setSpacing(8)
        self._culture_label = QLabel()
        self._culture_code = QLabel()
        culture_row.addWidget(self._culture_label)
        culture_row.addWidget(self._culture_code)
        culture_row.addStretch()
        form.addRow("Culture:", culture_row)

        self._lang_edit = QLineEdit()
        self._lang_edit.setMaxLength(DISPLAY_LANGUAGE_MAX_LEN)
        self._lang_edit.setPlaceholderText("e.g. Español")
        self._lang_edit.textChanged.connect(self._validate)
        form.addRow("Language name:", self._lang_edit)

        version_row = QHBoxLayout()
        version_row.setSpacing(4)
        self._version_spins: List[QSpinBox] = []
        for maximum in VERSION_PART_MAXIMA:
            if self._version_spins:
                version_row.addWidget(QLabel("."))
            spin = QSpinBox()
            spin.setRange(0, maximum)
            spin.valueChanged.connect(self._on_version_edited)
            # Keys can reach either the spin box or its line edit, so both are watched for '.'.
            spin.installEventFilter(self)
            spin.lineEdit().installEventFilter(self)
            self._version_spins.append(spin)
            version_row.addWidget(spin)
        version_row.addStretch()
        form.addRow("Version:", version_row)

        self._version_warning = QLabel()
        self._version_warning.setWordWrap(True)
        form.addRow(self._version_warning)
        lay.addWidget(header)

        about = QGroupBox("About this file")
        facts_form = QFormLayout(about)
        facts_form.setSpacing(6)
        self._facts_form = facts_form
        self._fact_labels: Dict[str, QLabel] = {}
        for key, caption in (("file", "File:"), ("folder", "Folder:"), ("size", "Size:"),
                             ("modified", "Modified:"), ("strings", "Strings:"),
                             ("New", "New:"), ("Review", "Review:"), ("Complete", "Complete:"),
                             ("untranslated", "Untranslated:")):
            value = QLabel()
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._fact_labels[key] = value
            facts_form.addRow(caption, value)
        self._unsaved_note = QLabel("Counts include unsaved changes.")
        facts_form.addRow(self._unsaved_note)
        lay.addWidget(about)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        self._ok_btn = QPushButton("OK")
        self._ok_btn.setProperty("role", "primary")
        self._ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._ok_btn)
        lay.addLayout(btn_row)
        # setDefault(True) only registers once the button is inside the dialog's layout --
        # see the "Default-button registration" pitfall in CLAUDE.md.
        self._ok_btn.setDefault(True)

    def _load_values(self):
        name = describe_culture(self._culture)
        if name:
            self._culture_label.setText(name)
            self._culture_code.setText(self._culture)
        elif self._culture:
            self._culture_label.setText(self._culture)
            self._culture_code.setText("(unknown language)")
        else:
            self._culture_label.setText("—")

        self._lang_edit.setText(self._stored_language)
        for spin, value in zip(self._version_spins, self._stored_parts or (0, 0, 0)):
            spin.setValue(value)
        # Loading the stored value is not an edit.
        self._version_touched = False
        if not self._stored_version:
            self._version_warning.setText("The file has no version. Set one to continue.")
        else:
            self._version_warning.setText(
                f"Stored version '{self._stored_version}' is not in the major.minor.build "
                "format. Set a new one.")

        self._load_facts()
        self._validate()

    def _load_facts(self):
        f = self._facts
        loc = QLocale.system()
        labels = self._fact_labels
        labels["file"].setText(f.file_name)
        # A path has no spaces for word wrap to break at, so a zero-width space after each separator
        # lets a long folder wrap onto more lines and stay fully visible. The row is not selectable:
        # a copy would carry those invisible characters into whatever it is pasted into.
        labels["folder"].setText(f.folder.replace("\\", "\\​").replace("/", "/​"))
        labels["folder"].setWordWrap(True)
        labels["folder"].setTextInteractionFlags(Qt.NoTextInteraction)
        labels["size"].setText("—" if f.size_bytes is None else
                               loc.formattedDataSize(f.size_bytes, 1, QLocale.DataSizeTraditionalFormat))
        labels["modified"].setText(
            "—" if f.modified is None else
            loc.toString(QDateTime.fromSecsSinceEpoch(int(f.modified)), QLocale.ShortFormat))
        labels["strings"].setText(loc.toString(f.total))

        def with_share(n: int) -> str:
            if not f.total:
                return loc.toString(n)
            return f"{loc.toString(n)}  ({loc.toString(n * 100 / f.total, 'f', 1)}%)"

        for status in STATUSES:
            labels[status].setText(with_share(f.by_status.get(status, 0)))
        labels["untranslated"].setText(with_share(f.untranslated))
        self._unsaved_note.setVisible(self._has_unsaved)

    def _on_version_edited(self, _value: int):
        self._version_touched = True
        self._validate()

    def _validate(self, *_args):
        version_ok = self._stored_parts is not None or self._version_touched
        self._version_warning.setVisible(not version_ok)
        self._ok_btn.setEnabled(bool(self._lang_edit.text().strip()) and version_ok)

    def eventFilter(self, obj, event):
        # '.' moves on to the next part, so typing 4.1.1220 across the three boxes just works.
        # Comma too: a Latvian keyboard's numeric-keypad decimal key types ','.
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Period, Qt.Key_Comma):
            for i, spin in enumerate(self._version_spins):
                if obj is spin or obj is spin.lineEdit():
                    if i + 1 < len(self._version_spins):
                        nxt = self._version_spins[i + 1]
                        nxt.setFocus()
                        nxt.selectAll()
                    return True
        return super().eventFilter(obj, event)

    def _apply_style(self):
        t = self._mw._get_theme() if self._mw and hasattr(self._mw, "_get_theme") else THEMES["dark"]
        pt = (self._mw.settings.get_font().pointSize()
              if self._mw and hasattr(self._mw, "settings") else 0) or 10
        pt_small = max(8, pt - 1)
        self.setStyleSheet(f"""
            QDialog   {{ background: {t['dlg_bg']}; }}
            QLabel    {{ color: {t['fg']}; }}
            {_groupbox_qss(t, pt)}
            QLineEdit, QSpinBox {{
                background: {t['dlg_edit_bg']}; color: {t['fg']};
                border: 1px solid {t['border']}; border-radius: 3px; padding: 3px 6px;
            }}
            {_spinbox_qss(t, pt)}
            {_button_qss(t, pt)}
            {_field_state_qss(t)}
        """)
        dim = f"color: {t['fg_dim']}; font-size: {pt_small}pt;"
        self._culture_code.setStyleSheet(dim)
        self._unsaved_note.setStyleSheet(dim)
        self._version_warning.setStyleSheet(f"color: {t['text_warn']};")
        # One caption width for both group boxes, so their value columns line up.
        captions = [form.itemAt(row, QFormLayout.LabelRole).widget()
                    for form in (self._header_form, self._facts_form)
                    for row in range(form.rowCount())
                    if form.itemAt(row, QFormLayout.LabelRole)]
        width = max(c.sizeHint().width() for c in captions)
        for caption in captions:
            caption.setMinimumWidth(width)
        # Sized to the widest value plus the style's own arrow strip, so it follows the UI font.
        for spin, maximum in zip(self._version_spins, VERSION_PART_MAXIMA):
            spin.ensurePolished()
            spin.setFixedWidth(_width_for_text(spin, spin.fontMetrics(), [str(maximum)]))

    def display_language(self) -> str:
        return self._lang_edit.text().strip()

    def version_parts(self) -> Tuple[int, int, int]:
        return tuple(spin.value() for spin in self._version_spins)

    def version(self) -> str:
        return format_version(self.version_parts())


# ══════════════════════════════════════════════════════════════
#  DATE PICKER
#  A display-only field (_DatePickerField) that opens an iOS-style
#  pop-up of drum columns (_DateDrumPopup, _DrumColumn).
# ══════════════════════════════════════════════════════════════

# Years the drum pop-up offers. A stored date outside them is not clamped: its year is added at the
# matching end of the column, so opening and confirming the pop-up keeps it.
DRUM_YEAR_FIRST = 2000
DRUM_YEAR_LAST = 2100


def _date_format_hint(qt_fmt: str) -> str:
    """'Format: dd.mm.yyyy' for a Qt date format: every day token written dd, every month token mm,
    the year yyyy (yy for a 2-digit-year format), separators kept -- so a day-first date can be told
    from a month-first one."""
    def token(match) -> str:
        run = match.group(0)
        if run[0] == "d":
            return "dd"
        if run[0] == "M":
            return "mm"
        return "yy" if len(run) <= 2 else "yyyy"
    return "Format: " + re.sub(r"d+|M+|y+", token, qt_fmt)


def _date_section_order(qt_fmt: str) -> List[str]:
    """'d', 'M' and 'y' in the order the format shows them. A part the format lacks goes last, so
    the pop-up always has all three columns."""
    order = [ch for i, ch in enumerate(qt_fmt) if ch in "dMy" and ch not in qt_fmt[:i]]
    return order + [ch for ch in "dMy" if ch not in order]


class _DrumColumn(QWidget):
    """One wheel of the date pop-up: a list of numbers drawn as rows around a highlighted middle
    row, the nearer rows larger and brighter, like an iOS picker wheel. The wheel, a drag, the keys
    and a click on another row move it, always ending on a whole row; a click on the middle row
    emits middle_clicked. Toward the top of the list is the previous (smaller) value, as when
    scrolling any list. value() is the value the column is settling on, so it is right even while
    the snap animation still runs."""

    value_changed = Signal(int)
    middle_clicked = Signal()

    VISIBLE_ROWS = 5
    PAGE_ROWS = 5
    SNAP_MS = 150
    _COAST_MS = 300            # snap after a flicked drag
    _COAST_S = 0.25            # how far a flick keeps going, as seconds of its speed
    _CLICK_SLOP_PX = 4
    _VELOCITY_WINDOW_S = 0.1

    def __init__(self, values: List[int], current: int, wraps: bool, font: QFont, theme: dict,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self._wraps = wraps
        self._font = QFont(font)
        self._t = theme
        self._values: List[int] = []
        self._target = 0          # row the column settles on; may leave 0..n-1 while wrapping
        self._offset = 0.0        # row drawn in the middle right now
        self._press: Optional[Tuple[float, float]] = None   # (pointer y, offset) at the press
        self._max_move = 0.0      # largest |y - press y| reached since the press
        self._samples: List[Tuple[float, float]] = []       # (time, pointer y) while dragging
        self._wheel_rest = 0
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self._anim.finished.connect(self._on_anim_finished)
        fm = QFontMetrics(self._font)
        self._row_h = fm.height() + 10
        widest = "0000" if max(values) > 99 else "00"
        self.setFixedSize(fm.horizontalAdvance(widest) + 28, self._row_h * self.VISIBLE_ROWS)
        self.set_values(values, current)

    @staticmethod
    def _label(value: int) -> str:
        return f"{value:02d}"

    def row_height(self) -> int:
        return self._row_h

    def values(self) -> List[int]:
        return list(self._values)

    def value(self) -> int:
        return self._values[self._index(self._target)]

    def _index(self, row: int) -> int:
        n = len(self._values)
        return row % n if self._wraps else min(max(row, 0), n - 1)

    def set_values(self, values: List[int], current: int) -> None:
        """Replace the list -- the day column when the month changes -- without animating or
        signalling; *current* moves to the nearest value in the list (31 -> 30 for April)."""
        self._anim.stop()
        self._values = list(values)
        nearest = min(self._values, key=lambda v: abs(v - current))
        self._target = self._values.index(nearest)
        self._offset = float(self._target)
        self.update()

    def step(self, rows: int) -> None:
        self._go_to(self._target + rows)

    def _go_to(self, row: int, duration_ms: Optional[int] = None) -> None:
        if not self._wraps:
            row = min(max(row, 0), len(self._values) - 1)
        before = self.value()
        self._target = row
        self._anim.stop()
        self._anim.setDuration(self.SNAP_MS if duration_ms is None else duration_ms)
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(float(row))
        self._anim.start()
        if self.value() != before:
            self.value_changed.emit(self.value())

    def _on_anim(self, value) -> None:
        self._offset = float(value)
        self.update()

    def _on_anim_finished(self) -> None:
        # Keep a wrapping column's row numbers near its list, however far it has been spun.
        if self._wraps:
            shift = self._target - self._target % len(self._values)
            self._target -= shift
            self._offset -= shift

    def wheelEvent(self, event) -> None:
        # A touchpad sends fractions of a notch; they add up to whole rows.
        self._wheel_rest += event.angleDelta().y()
        rows = int(self._wheel_rest / 120)
        self._wheel_rest -= rows * 120
        if rows:
            self.step(-rows)
        event.accept()

    def keyPressEvent(self, event) -> None:
        moves = {Qt.Key_Up: -1, Qt.Key_Down: 1,
                 Qt.Key_PageUp: -self.PAGE_ROWS, Qt.Key_PageDown: self.PAGE_ROWS}
        key = event.key()
        if key in moves:
            self.step(moves[key])
        elif key == Qt.Key_Home:
            self.step(-self._index(self._target))
        elif key == Qt.Key_End:
            self.step(len(self._values) - 1 - self._index(self._target))
        else:
            event.ignore()     # Enter, Escape, Left, Right belong to the pop-up

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        self._anim.stop()
        y = event.position().y()
        self._press = (y, self._offset)
        self._max_move = 0.0
        self._samples = [(time.monotonic(), y)]

    def mouseMoveEvent(self, event) -> None:
        if self._press is None:
            return
        y = event.position().y()
        start_y, start_offset = self._press
        self._max_move = max(self._max_move, abs(y - start_y))
        offset = start_offset - (y - start_y) / self._row_h
        if not self._wraps:
            offset = min(max(offset, 0.0), len(self._values) - 1.0)
        self._offset = offset
        now = time.monotonic()
        self._samples = [s for s in self._samples if now - s[0] <= self._VELOCITY_WINDOW_S]
        self._samples.append((now, y))
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._press is None or event.button() != Qt.LeftButton:
            return
        y = event.position().y()
        start_y, _ = self._press
        # Use the largest distance reached during the drag, not just where it ended up --
        # a drag that wanders away and back within the slop must not count as a click.
        self._max_move = max(self._max_move, abs(y - start_y))
        self._press = None
        if self._max_move < self._CLICK_SLOP_PX:
            rows = round((y - self.height() / 2) / self._row_h)
            # From the row actually drawn in the middle: the press may have stopped a snap midway.
            self._go_to(round(self._offset) + rows)
            if rows == 0:
                self.middle_clicked.emit()
            return
        now = time.monotonic()
        recent = [s for s in self._samples if now - s[0] <= self._VELOCITY_WINDOW_S] + [(now, y)]
        speed = 0.0    # rows per second; positive = toward larger values
        if len(recent) >= 2 and recent[-1][0] > recent[0][0]:
            speed = -(recent[-1][1] - recent[0][1]) / (recent[-1][0] - recent[0][0]) / self._row_h
        self._go_to(round(self._offset + speed * self._COAST_S),
                    self._COAST_MS if speed else None)

    def focusInEvent(self, event) -> None:
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.update()
        super().focusOutEvent(event)

    def paintEvent(self, event) -> None:
        t = self._t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        mid = self.height() / 2
        band = QRectF(0, mid - self._row_h / 2, self.width(), self._row_h)
        p.fillRect(band, QColor(t["bg3"]))
        p.setPen(QPen(QColor(t["border2"]), 1))
        p.drawLine(band.topLeft(), band.topRight())
        p.drawLine(band.bottomLeft(), band.bottomRight())
        if self.hasFocus():
            p.fillRect(QRectF(6, band.bottom() - 2, self.width() - 12, 2), QColor(t["accent"]))
        fg, dim = QColor(t["fg"]), QColor(t["fg_dim"])
        base = math.floor(self._offset)
        for k in range(-3, 4):
            row = base + k
            if not self._wraps and not 0 <= row < len(self._values):
                continue
            dist = abs(row - self._offset)
            if dist > 2.6:
                continue
            font = QFont(self._font)
            scale = max(0.7, 1 - 0.15 * dist)
            if self._font.pointSizeF() > 0:
                font.setPointSizeF(self._font.pointSizeF() * scale)
            else:
                font.setPixelSize(max(1, round(self._font.pixelSize() * scale)))
            p.setFont(font)
            mix = min(dist, 1.0)
            p.setPen(QColor(round(fg.red() + (dim.red() - fg.red()) * mix),
                            round(fg.green() + (dim.green() - fg.green()) * mix),
                            round(fg.blue() + (dim.blue() - fg.blue()) * mix)))
            p.setOpacity(max(0.0, min(1.0, 1.9 - 0.75 * dist)))
            y = mid + (row - self._offset) * self._row_h
            p.drawText(QRectF(0, y - self._row_h / 2, self.width(), self._row_h), Qt.AlignCenter,
                       self._label(self._values[self._index(row)]))
        p.end()


def _theme_and_font(widget: QWidget) -> Tuple[dict, QFont]:
    """The active theme and UI font of the MainWindow above *widget* -- the dark theme and the
    application font when there is none (a bare test widget)."""
    w = widget
    while w is not None:
        if hasattr(w, "_get_theme") and hasattr(w, "settings"):
            return w._get_theme(), w.settings.get_font()
        w = w.parentWidget()
    return THEMES["dark"], QApplication.font()


class _DateDrumPopup(QFrame):
    """The date field's pop-up: a day, a month and a year _DrumColumn in the order of the system
    short-date format, and a format hint under them. Enter or a click on the middle row confirms
    (the field gets the date and the pop-up closes); Escape or a click outside -- Qt.Popup closes
    itself then -- cancels. Created per open, so it always takes the current theme and font."""

    def __init__(self, field: QDateEdit):
        super().__init__(field, Qt.Popup)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("dateDrumPopup")
        self._field = field
        t, font = _theme_and_font(field)
        d = field.date()
        years = list(range(DRUM_YEAR_FIRST, DRUM_YEAR_LAST + 1))
        if d.year() < DRUM_YEAR_FIRST:
            years.insert(0, d.year())
        elif d.year() > DRUM_YEAR_LAST:
            years.append(d.year())
        specs = {"d": (list(range(1, d.daysInMonth() + 1)), d.day(), True),
                 "M": (list(range(1, 13)), d.month(), True),
                 "y": (years, d.year(), False)}
        self.order: List[str] = _date_section_order(DATE_FMT_QT)
        self._columns: Dict[str, _DrumColumn] = {}
        row = QHBoxLayout()
        row.setSpacing(0)
        for part in self.order:
            values, current, wraps = specs[part]
            column = _DrumColumn(values, current, wraps, font, t, self)
            column.middle_clicked.connect(self.confirm)
            self._columns[part] = column
            row.addWidget(column)
        self._columns["M"].value_changed.connect(self._fit_days)
        self._columns["y"].value_changed.connect(self._fit_days)
        hint = QLabel(_date_format_hint(DATE_FMT_QT))
        hint.setAlignment(Qt.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(4)
        layout.addLayout(row)
        layout.addWidget(hint)
        pt = font.pointSize() if font.pointSize() > 0 else 10
        self.setStyleSheet(
            f"QFrame#dateDrumPopup {{ background: {t['dlg_bg']}; border: 1px solid {t['border2']}; }}"
            f"QLabel {{ color: {t['fg_dim']}; background: transparent;"
            f" font-size: {max(8, pt - 1)}pt; }}")

    def columns(self) -> Dict[str, _DrumColumn]:
        return dict(self._columns)

    def chosen_date(self) -> QDate:
        return QDate(self._columns["y"].value(), self._columns["M"].value(),
                     self._columns["d"].value())

    def _fit_days(self) -> None:
        days = QDate(self._columns["y"].value(), self._columns["M"].value(), 1).daysInMonth()
        day = self._columns["d"]
        if len(day.values()) != days:
            day.set_values(list(range(1, days + 1)), day.value())

    def confirm(self) -> None:
        self._field.setDate(self.chosen_date())
        self.close()

    def mousePressEvent(self, event) -> None:
        # Qt.Popup closes on any outside press and then replays that same press to
        # whatever is underneath -- the field -- whose own mousePressEvent would
        # otherwise reopen the pop-up it just closed (or double-open it on a
        # double click). Matches QComboBoxPrivateContainer/QCalendarPopup: only
        # suppress the replay when the closing press actually landed on the field.
        field_rect = QRect(self._field.mapToGlobal(QPoint(0, 0)), self._field.size())
        if field_rect.contains(event.globalPosition().toPoint()):
            self.setAttribute(Qt.WA_NoMouseReplay)
        super().mousePressEvent(event)

    def show_at_field(self) -> None:
        """Just under the field, left edges aligned; above it when there is no room below, and
        shifted left when it would leave the screen at the right."""
        self.adjustSize()
        field = self._field
        avail = field.screen().availableGeometry()
        pos = field.mapToGlobal(QPoint(0, field.height()))
        if pos.y() + self.height() > avail.bottom() + 1:
            pos.setY(field.mapToGlobal(QPoint(0, 0)).y() - self.height())
        pos.setX(max(avail.left(), min(pos.x(), avail.right() + 1 - self.width())))
        self.move(pos)
        self.show()
        self._columns["d"].setFocus()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.confirm()
        elif key == Qt.Key_Escape:
            self.close()
        elif key == Qt.Key_Left:
            self.focusPreviousChild()
        elif key == Qt.Key_Right:
            self.focusNextChild()
        else:
            super().keyPressEvent(event)


class _DatePickerField(QDateEdit):
    """A date field that shows the date and changes it only through _DateDrumPopup: a click, or
    Enter, Return, Space, F4 or Alt+Down while focused, opens the pop-up. The wheel, the arrow keys
    and typing do nothing, so a stray scroll or key press can never change a date.
    setCalendarPopup(True) is only for the drop-down arrow Qt then draws; the events that would open
    Qt's own calendar never reach QDateEdit. No minimum date: the Edit dialog writes the date back
    whenever its text differs from the stored one, so clamping an old (pre-2000) date would rewrite
    it on an unrelated Save."""

    _WIDEST_DATE = QDate(2088, 12, 28).toString(DATE_FMT_QT)
    _OPEN_KEYS = (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space, Qt.Key_F4)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.lineEdit().setReadOnly(True)
        # The text part is a child widget of its own and gets the clicks over the text.
        self.lineEdit().installEventFilter(self)
        self.setToolTip(_date_format_hint(DATE_FMT_QT))

    def fit_to_font(self, fm: QFontMetrics) -> None:
        """Keep the widest date unclipped at the current UI font, whatever else shares the row.
        Call it after the stylesheet is set, so the measured drop-down and padding are current."""
        self.setMinimumWidth(_width_for_text(self, fm, [self._WIDEST_DATE, self.text()]))

    def open_popup(self) -> "_DateDrumPopup":
        popup = _DateDrumPopup(self)
        popup.show_at_field()
        return popup

    def eventFilter(self, obj, event) -> bool:
        if obj is self.lineEdit():
            kind = event.type()
            if kind == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    self.open_popup()
                return True
            # A double click would select text; the spin box's context menu has Step up/down.
            if kind in (QEvent.MouseButtonDblClick, QEvent.ContextMenu):
                return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.open_popup()
        event.accept()

    def contextMenuEvent(self, event) -> None:
        event.accept()     # the base spin box's menu would offer Step up / Step down

    def wheelEvent(self, event) -> None:
        event.ignore()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in self._OPEN_KEYS or (key == Qt.Key_Down and event.modifiers() & Qt.AltModifier):
            self.open_popup()
        elif key in (Qt.Key_Tab, Qt.Key_Backtab):
            super().keyPressEvent(event)
        else:
            event.ignore()     # Escape and the rest still reach the dialog

# ════════════════════════════════════════════════════════════════
#  PLAIN-PASTE TEXT EDITOR
#  Subclass of QTextEdit that strips all formatting and leading/
#  trailing whitespace from anything pasted from the clipboard,
#  regardless of how the paste was triggered (Ctrl+V, Shift+Insert,
#  right-click Paste, or drag-and-drop).
# ════════════════════════════════════════════════════════════════

class PlainPasteTextEdit(QTextEdit):
    """QTextEdit that always pastes as plain text with trimmed whitespace."""

    def insertFromMimeData(self, source):
        """Strip rich text and surrounding whitespace from any paste."""
        text = source.text()
        text = text.strip()
        if text:
            self.insertPlainText(text)

class EditDialog(QDialog):
    def __init__(self, model, row_index: int, app_font: QFont,
                 shortcuts: Optional[dict] = None, target_culture: str = "",
                 transl_cfg: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self._model          = model
        self._row            = row_index          # current row in the visible list
        self.app_font        = app_font
        self._any_saved      = False              # True once at least one row was committed or deleted
        self._target_culture = target_culture or ""
        self._transl_cfg     = transl_cfg or {}
        self._transl_thread: Optional[TranslationThread] = None
        # Bumped whenever a translation starts, the dialog navigates to a
        # different entry, or the dialog is dismissed (Save, Cancel/Escape,
        # or close) -- lets a stale thread's finished/errored result (for an
        # entry the user has since moved away from) be detected and
        # discarded instead of silently overwriting whatever entry is now
        # displayed. See
        # docs/superpowers/specs/2026-09-03-translation-thread-lifecycle-design.md
        self._transl_generation = 0
        # Merge caller shortcuts with defaults so missing keys always have a value
        self._shortcuts = dict(SHORTCUT_DEFAULTS)
        if shortcuts:
            self._shortcuts.update(shortcuts)
        # Cache the character-count config from MainWindow.settings once so the
        # textChanged handler does not re-read JSON on every keystroke.
        mw_init = parent
        if mw_init and hasattr(mw_init, "settings"):
            self._char_cfg = dict(mw_init.settings.get("char_count", {}) or {})
            self._robo_cfg = dict(mw_init.settings.get("robo_translate", {}) or {})
        else:
            self._char_cfg = {}
            self._robo_cfg = {}
        self._mw = mw_init
        self._robo_cfg.setdefault("delay_seconds", 10)
        # Robo-Translate chain state (translate -> countdown -> advance -> repeat)
        self._robo_active     = False
        self._robo_timer: Optional[QTimer] = None
        self._robo_remaining  = 0
        self._robo_navigating = False   # True while a chain-driven _navigate is in flight
        self._robo_timer_generation: Optional[int] = None  # generation _robo_timer was scheduled under
        self.setWindowTitle("Edit Translation")
        self.setMinimumSize(680, 500)
        # Closing this dialog (Save, Cancel/Escape, or the window's close button)
        # must actually destroy it -- otherwise, like every dialog in this app
        # before the Merge dialog fix, it stays alive forever as a hidden child of
        # MainWindow. EditDialog is opened once per row edited, so a long session
        # accumulates one zombie dialog (plus its cached QTextEdit/QComboBox/etc.)
        # per edit. Safe with the claude_subscription session: every real dismissal
        # path (reject/closeEvent/_save/_navigate/_delete_current) already calls
        # _abandon_stale_translation() synchronously, which disconnects the old
        # thread's signals from this dialog before WA_DeleteOnClose's deferred
        # destruction could ever run -- see the "A dialog constructed with
        # parent=self..." pitfall in CLAUDE.md.
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._build()
        self._load_row(self._row)
        self._apply_style()
        self._init_override_state()
        # Auto-activate override when user manually edits the translator field
        self.user_edit.textChanged.connect(self._on_translator_typed)
        # Live character-count indicator
        self.trans_edit.textChanged.connect(self._update_char_count)
        self._update_char_count()

    # ------------------------------------------------------------------
    # Auto-translation helpers
    # ------------------------------------------------------------------

    def _on_translate_button_clicked(self):
        """Route a button click: Shift held toggles Robo-Translate, otherwise
        stop any running chain and perform a plain one-off translate."""
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._toggle_robo_chain()
            return
        if self._robo_active:
            self._stop_robo_chain()
        self._start_translation()

    def _toggle_robo_chain(self):
        """Start or stop the Robo-Translate auto-advance chain for this dialog."""
        if self._robo_active:
            self._stop_robo_chain()
            return
        # The Shift+Alt+A shortcut is not disabled while a plain (non-chain)
        # translate is already running in the background -- unlike the
        # button, which _start_translation disables for that duration.
        # Ignore the activation rather than starting a second, overlapping
        # TranslationThread.
        if self._transl_thread and self._transl_thread.isRunning():
            return
        self._robo_active = True
        self._start_translation()

    def _stop_robo_chain(self):
        """Cancel any pending countdown and clear the Robo-Translate state."""
        if self._robo_timer is not None:
            self._robo_timer.stop()
            self._robo_timer.deleteLater()
            self._robo_timer = None
            # A live countdown is being interrupted -- its "advancing in Xs..."
            # message is now stale, so clear it immediately rather than
            # leaving it frozen on screen until something else overwrites it.
            self._transl_status.setText("")
            self._transl_status.setToolTip("")
        self._robo_active = False

    def _abandon_stale_translation(self):
        """Detach the currently-running _transl_thread (if any) so its
        eventual result is ignored: disconnects its signals, best-effort
        cancels it if it's a claude_subscription call (so the caller unblocks
        immediately rather than sitting out the full timeout, while the
        session's pump keeps draining that response to keep the SDK message
        stream in lockstep), and lets it keep running to
        completion in the background -- its result is discarded via the
        generation check in _on_translation_done()/_on_translation_error()
        regardless. Clears self._transl_thread: the abandoned thread is no
        longer this dialog's concern, so a second, independent translation
        (including a fresh Robo-Translate chain) is always safe to start
        immediately afterward -- _toggle_robo_chain()'s isRunning() guard
        only ever sees a real, still-current thread, never a stale one."""
        old = self._transl_thread
        if old is None or not old.isRunning():
            return
        try:
            old.finished.disconnect(self._on_translation_done)
            old.errored.disconnect(self._on_translation_error)
        except (TypeError, RuntimeError):
            pass
        self._transl_thread = None
        self._transl_btn.setEnabled(True)
        self._transl_status.setText("")
        self._transl_status.setToolTip("")
        if (self._transl_cfg.get("engine") == "claude_subscription"
                and self._mw is not None
                and self._mw.claude_session is not None):
            self._mw.claude_session.cancel_current()

    def _start_translation(self):
        """Kick off an asynchronous translation of the source text."""
        source_text = self.src_view.toPlainText().strip()
        if not source_text:
            self._transl_status.setText("⚠  No source text to translate.")
            self._stop_robo_chain()
            return
        if not self._target_culture:
            self._transl_status.setText("⚠  No target language (open a file first).")
            self._stop_robo_chain()
            return
        engine = self._transl_cfg.get("engine", "none")
        if engine == "none":
            self._transl_status.setText(
                "⚠  No engine set.  Open View → Translation Settings…")
            self._stop_robo_chain()
            return
        self._abandon_stale_translation()
        self._transl_generation += 1

        self._transl_btn.setEnabled(False)
        self._transl_status.setText("Translating…")

        thread = TranslationThread(
            source_text, self._target_culture, self._transl_cfg,
            mw=self._mw, parent=self._mw
        )
        thread._generation = self._transl_generation
        thread.finished.connect(self._on_translation_done)
        thread.errored.connect(self._on_translation_error)
        self._transl_thread = thread
        can_register = self._mw is not None and hasattr(self._mw, "_register_translation_thread")
        if can_register and not self._mw._register_translation_thread(thread):
            return  # app is closing; a never-started thread needs no cleanup
        thread.start()

    def _on_translation_done(self, translated: str):
        """Insert the translated text, stamp the engine as translator, re-enable button.

        Discards the result if it came from a superseded generation (the
        user has since navigated to a different entry, started another
        translation, or closed the dialog) -- see self._transl_generation.
        """
        sender = self.sender()
        if getattr(sender, "_generation", None) != self._transl_generation:
            return
        self._transl_thread = None
        engine       = self._transl_cfg.get("engine", "none")
        engine_label = _ENGINE_LABELS.get(engine, "Auto-translate")

        self.trans_edit.setPlainText(translated)

        # Override session translator: activate the override checkbox and
        # fill the translator field with the engine name so the engine is
        # credited when the entry is saved.
        self.override_chk.setChecked(True)
        self.user_edit.blockSignals(True)   # prevent _on_translator_typed loop
        self.user_edit.setText(engine_label)
        self.user_edit.blockSignals(False)

        self._transl_btn.setEnabled(True)
        self._transl_status.setText(f"✓  Translated to {self._target_culture}")
        self.trans_edit.setFocus()

        if self._robo_active:
            self._robo_remaining = int(self._robo_cfg.get("delay_seconds", 10))
            self._transl_status.setText(
                f"✓  Translated — advancing in {self._robo_remaining}s…  "
                "(Shift+Alt+A to stop)")
            self._robo_timer = QTimer(self)
            self._robo_timer_generation = self._transl_generation
            self._robo_timer.timeout.connect(self._robo_tick)
            self._robo_timer.start(1000)

    def _robo_tick(self):
        """Countdown handler: update the status label once per second, advance at zero.

        Defense-in-depth: if the generation captured when this timer was
        scheduled (self._robo_timer_generation) is no longer current, the
        chain has been superseded by something that didn't already call
        _stop_robo_chain() -- stop cleanly instead of advancing on stale
        state. Every current call site that would bump the generation
        (_navigate, _start_translation, _save, reject/closeEvent) already
        stops the chain first, so this should not fire in practice today.
        """
        if getattr(self, "_robo_timer_generation", None) != self._transl_generation:
            self._stop_robo_chain()
            return
        self._robo_remaining -= 1
        if self._robo_remaining <= 0:
            self._robo_timer.stop()
            self._robo_timer.deleteLater()
            self._robo_timer = None
            self._robo_advance()
            return
        self._transl_status.setText(
            f"✓  Translated — advancing in {self._robo_remaining}s…  "
            "(Shift+Alt+A to stop)")

    def _robo_advance(self):
        """Move to the next entry and continue the chain, or stop at list end.

        Entries already translated (status Review/Complete) are skipped —
        the chain advances past them without touching their text — so an
        unattended run only fills in New entries. The entry the chain was
        *started* on is always translated regardless of its status, since
        that was an explicit user action.
        """
        if not self._robo_active:
            return
        while True:
            if self._row + 1 >= self._model.rowCount():
                self._stop_robo_chain()
                self._transl_status.setText(
                    "✓  Robo-Translate reached the end of the list.")
                return
            self._robo_navigating = True
            self._navigate(+1)
            self._robo_navigating = False
            if not self._robo_active:
                return
            if self.entry.status not in ("Review", "Complete"):
                break
        self._start_translation()

    def _on_translation_error(self, msg: str):
        """Show error, re-enable the button, and halt any running Robo-Translate chain.

        Discards the report if it came from a superseded generation -- see
        self._transl_generation. This also covers a deliberately cancelled
        claude_subscription call (cancel_current() surfaces as this same
        errored signal on the abandoned thread), which is exactly what
        should happen: the abandoned call's cancellation is silently
        ignored here, never shown to the user.
        """
        sender = self.sender()
        if getattr(sender, "_generation", None) != self._transl_generation:
            return
        self._transl_btn.setEnabled(True)
        self._stop_robo_chain()
        short = msg[:120] + ("…" if len(msg) > 120 else "")
        self._transl_status.setText(f"✗  {short}")
        self._transl_status.setToolTip(msg)   # full message on hover

    # ------------------------------------------------------------------
    # Session-translator override helpers
    # ------------------------------------------------------------------

    def _session_name(self) -> str:
        """Return the active session translator name, or empty string."""
        mw = self.parent()
        if mw and hasattr(mw, "session_translator"):
            return mw.session_translator or ""
        return ""

    def _init_override_state(self):
        """Set the override checkbox based on whether a session name is active.

        - Session name present  → checkbox UNCHECKED (session name will be used)
        - No session name       → checkbox CHECKED   (field is freely editable)
        The checkbox is hidden entirely when there is no session translator,
        because it would be meaningless.
        """
        sn = self._session_name()
        if sn:
            self.override_chk.setChecked(False)
            self.override_chk.setVisible(True)
            self.override_chk.setText(f"Override  [{sn}]")
        else:
            # No session translator — hide the checkbox, field is always free
            self.override_chk.setChecked(True)
            self.override_chk.setVisible(False)

    def _on_translator_typed(self, text: str):
        """Auto-enable the override when the user types in the translator field.

        If the typed text differs from the session name (or session name is
        empty), mark override as active so the session name is not injected
        on the next commit.
        """
        sn = self._session_name()
        if sn and text.strip() != sn:
            self.override_chk.setChecked(True)

    def _apply_style(self):
        # Inherit the theme from MainWindow if available, otherwise fall back to dark
        mw = self.parent()
        t  = mw._get_theme() if mw and hasattr(mw, "_get_theme") else THEMES["dark"]
        # Use the app font's point size so EditDialog widgets (nav buttons,
        # auto-translate row) scale with View → Choose UI Font…
        pt = self.app_font.pointSize()
        if pt <= 0:
            pt = self.font().pointSize() or 10
        self.setStyleSheet(f"""
            QDialog {{ background: {t['dlg_bg']}; }}
            QLabel  {{ color: {t['fg']}; }}
            {_groupbox_qss(t, pt)}
            QCheckBox {{ color: {t['fg']}; font-size: {pt}pt; }}
            {_prominent_checkbox_qss(t)}
            QTextEdit, QPlainTextEdit, QLineEdit {{
                background: {t['dlg_edit_bg']}; color: {t['fg']};
                border: 1px solid {t['border']}; border-radius: 3px; padding: 4px;
            }}
            QComboBox {{ background: {t['bg4']}; color: {t['fg']};
                         border: 1px solid {t['border2']}; border-radius: 3px;
                         padding: 3px 6px; }}
            QComboBox QAbstractItemView {{ background: {t['bg2']}; color: {t['fg']};
                                           selection-background-color: {t['sel_bg']};
                                           selection-color: {t['sel_fg']}; }}
            {_combobox_qss(t, pt)}
            {_button_qss(t, pt)}
            {_field_state_qss(t)}
            QPushButton#navBtn {{ background: {t['dlg_nav_bg']}; color: {t['fg']};
                                  border: 1px solid {t['dlg_nav_border']};
                                  border-radius: 3px; padding: 5px 14px; font-size: {pt}pt; }}
            QPushButton#navBtn:hover    {{ background: {t['dlg_nav_hover']};
                                           border-color: {t['dlg_nav_accent']}; }}
            QPushButton#navBtn:focus    {{ border: 1px solid {t['accent']}; }}
            QPushButton#navBtn:disabled {{ background: {t['dlg_nav_dis']};
                                           color: {t['dlg_nav_dis_fg']};
                                           border-color: {t['dlg_nav_dis_bdr']}; }}
        """)
        # Source-view and inline labels that are set directly (not via QSS cascade)
        # The transparent resting border keeps the text where it is when the focus border appears;
        # a bare "border: none" here would beat the inherited QTextEdit:focus rule.
        self.src_view.setStyleSheet(
            f"QTextEdit {{ background: {t['dlg_src_bg']}; color: {t['dlg_src_fg']};"
            f" border: 1px solid transparent; }}"
            f"QTextEdit:focus {{ border: 1px solid {t['accent']}; }}")
        self._nav_label.setStyleSheet(
            f"color: {t['dlg_nav_fg']}; min-width: 80px;")
        self.auto_date_info.setStyleSheet(
            f"color: {t['dlg_info_fg']}; padding: 2px 0;")
        self._transl_status.setStyleSheet(f"color: {t['fg_dim']};")
        self.date_edit.fit_to_font(QFontMetrics(self.app_font))
        # Re-color the character-count indicator on theme switch.
        if hasattr(self, "_char_count_label"):
            self._update_char_count()

    def _build(self):
        main = QVBoxLayout(self)
        main.setSpacing(10)

        # Source (read-only)
        src_grp = QGroupBox("Source Text  (read-only)")
        sg = QVBoxLayout(src_grp)
        self.src_view = QTextEdit()
        self.src_view.setReadOnly(True)
        self.src_view.setFont(self.app_font)
        self.src_view.setMaximumHeight(100)
        # Read-only, it still takes Alt+Left/Alt+Right as cursor keys, and the
        # dialog opens with focus here.
        self.src_view.installEventFilter(self)
        sg.addWidget(self.src_view)
        main.addWidget(src_grp)

        # Translation
        tr_grp = QGroupBox("Translated Text")
        tg = QVBoxLayout(tr_grp)
        self.trans_edit = PlainPasteTextEdit()
        self.trans_edit.setFont(self.app_font)
        self.trans_edit.setMinimumHeight(120)
        # Tab must navigate between dialog elements, not insert a tab character.
        self.trans_edit.installEventFilter(self)
        tg.addWidget(self.trans_edit)

        # Auto-translate toolbar (shown below the text area)
        tr_bar = QHBoxLayout()
        tr_bar.setSpacing(6)
        auto_translate_key = self._shortcuts.get("auto_translate", "Alt+A")
        robo_translate_key = self._shortcuts.get("robo_translate", "Shift+Alt+A")
        self._transl_btn = QPushButton("🌐  Auto-translate")
        self._transl_btn.setObjectName("navBtn")
        self._transl_btn.setShortcut(auto_translate_key)
        self._transl_btn.setToolTip(
            "Translate the Source Text into the target language using the\n"
            "configured engine (View → Translation Settings…).\n"
            f"The result is inserted into the translation field for review.  [{auto_translate_key}]\n"
            f"Shift+click (or {robo_translate_key}) starts Robo-Translate: translate, wait, "
            "advance, repeat.")
        self._transl_btn.clicked.connect(self._on_translate_button_clicked)
        # Robo-Translate toggle — fires regardless of which child widget has focus,
        # same WindowShortcut context the button's own shortcut relies on.
        self._robo_shortcut = QShortcut(QKeySequence(robo_translate_key), self)
        self._robo_shortcut.activated.connect(self._toggle_robo_chain)
        self._transl_status = QLabel("")
        # Inherit the app font so this label scales with View → Choose UI Font…
        self._transl_status.setFont(self.app_font)
        tr_bar.addWidget(self._transl_btn)
        tr_bar.addWidget(self._transl_status)
        tr_bar.addStretch()
        # Character-count length indicator — pinned to the right side of the bar.
        self._char_count_label = QLabel("")
        self._char_count_label.setObjectName("char_count_label")
        # Inherit the app font so this label scales with View → Choose UI Font…
        self._char_count_label.setFont(self.app_font)
        self._char_count_label.setToolTip(
            "Source vs translated character count.\n"
            "Green = within warning threshold.\n"
            "Amber = exceeds warning threshold.\n"
            "Red   = exceeds concern threshold.")
        tr_bar.addWidget(self._char_count_label)
        tg.addLayout(tr_bar)
        main.addWidget(tr_grp)

        # Meta row
        meta_grp = QGroupBox("Metadata")
        meta_layout = QGridLayout(meta_grp)
        meta_layout.setHorizontalSpacing(16)

        meta_layout.addWidget(QLabel("Status:"),     0, 0)
        self.status_combo = _WidePopupComboBox()
        self.status_combo.addItems(STATUSES)
        self.status_combo.setMinimumWidth(110)
        meta_layout.addWidget(self.status_combo,     0, 1)

        meta_layout.addWidget(QLabel("Translator:"), 0, 2)
        self.user_edit = QLineEdit()
        self.user_edit.setMinimumWidth(140)
        meta_layout.addWidget(self.user_edit,        0, 3)

        # Override checkbox — suppresses session-translator auto-fill
        self.override_chk = QCheckBox("Override")
        self.override_chk.setProperty("filterChk", True)
        self.override_chk.setToolTip(
            "When unchecked, the session translator name is used automatically\n"
            "whenever you change the translation text.\n"
            "Check this to use your own name instead.")
        meta_layout.addWidget(self.override_chk,    0, 4)

        meta_layout.addWidget(QLabel("Date:"),       0, 5)
        self.date_edit = _DatePickerField()
        self.date_edit.setDisplayFormat(DATE_FMT_QT)
        meta_layout.addWidget(self.date_edit,        0, 6)


        meta_layout.setColumnStretch(3, 1)
        main.addWidget(meta_grp)

        # Info label
        self.auto_date_info = QLabel(
            "ℹ  When Translated Text is changed, Status is set to Complete and Date to today automatically."
        )
        self.auto_date_info.setWordWrap(True)
        main.addWidget(self.auto_date_info)

        # ── Bottom bar: [◀ Prev]  [N / Total]  [Next ▶]  ──  [Save] [Cancel] ──
        bottom = QHBoxLayout()
        bottom.setSpacing(6)

        self._btn_prev = QPushButton("◀")
        self._btn_prev.setObjectName("navBtn")
        self._btn_prev.setToolTip("Previous entry")
        self._btn_prev.setFixedWidth(42)
        self._btn_prev.clicked.connect(lambda: self._navigate(-1))

        self._nav_label = QLabel()
        self._nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._nav_label.setMinimumWidth(80)

        self._btn_next = QPushButton("▶")
        self._btn_next.setObjectName("navBtn")
        self._btn_next.setToolTip("Next entry")
        self._btn_next.setFixedWidth(42)
        self._btn_next.clicked.connect(lambda: self._navigate(+1))

        bottom.addWidget(self._btn_prev)
        bottom.addWidget(self._nav_label)
        bottom.addWidget(self._btn_next)
        bottom.addStretch()

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        save_key = self._shortcuts.get("edit_save", "Alt+S")
        save_btn = btns.button(QDialogButtonBox.Save)
        save_btn.setProperty("role", "primary")
        save_btn.setShortcut(save_key)
        save_btn.setToolTip(f"Save changes and close  [{save_key}]")
        bottom.addWidget(btns)

        main.addLayout(bottom)

    # ------------------------------------------------------------------
    # Row loading / navigation helpers
    # ------------------------------------------------------------------
    def _load_row(self, row: int):
        """Load entry at *row* (visible index) into the form fields."""
        src_entry = self._model.get_entry(row)
        if src_entry is None:
            return
        self.entry = src_entry.clone()
        self._row  = row
        self._populate()   # fills trans_edit, date_edit, status_combo, etc.

        # Snapshot AFTER _populate so _original_text matches exactly what
        # toPlainText() will return later.  Qt normalises line endings and
        # trailing newlines during setPlainText(), so reading back here gives
        # us the same representation the comparison will use, eliminating
        # false text_changed hits that stamp today's date on mere open.
        self._original_text       = self.trans_edit.toPlainText()
        self._original_status     = self.status_combo.currentText()
        self._original_translator = self.user_edit.text()
        # Normalise to system format so comparison with new_date is consistent.
        # A date held in another format is converted to the current DATE_FMT.
        _parsed_orig = parse_date(src_entry.modify_date)
        self._original_date = (
            format_date_for_storage(_parsed_orig)
            if _parsed_orig is not None
            else src_entry.modify_date  # keep raw if unparseable
        )

        # Reset override checkbox for each new row so it reflects the session
        # state freshly rather than carrying over the previous row's state.
        self._init_override_state()
        self._update_nav()

    def _update_nav(self):
        """Refresh the row counter label, enable/disable buttons, and update tooltips."""
        total    = self._model.rowCount()
        prev_key = self._shortcuts.get('edit_prev', 'Alt+Left')
        next_key = self._shortcuts.get('edit_next', 'Alt+Right')
        self._nav_label.setText(f"{self._row + 1} / {total}")
        self._btn_prev.setEnabled(self._row > 0)
        self._btn_prev.setToolTip(f"Previous entry  [{prev_key}]  (saves current changes)")
        self._btn_next.setEnabled(self._row < total - 1)
        self._btn_next.setToolTip(f"Next entry  [{next_key}]  (saves current changes)")

    def _commit_current(self):
        """Write form fields back to the model entry, but only if something changed.

        Rules:
          - If translation TEXT changed  -> auto-set status=Complete, date=today.
          - If only metadata changed     -> write whatever the user set in the fields.
          - If nothing changed at all    -> skip write entirely (no model update,
                                           no file-modified flag, no date touched).
        """
        new_text       = self.trans_edit.toPlainText()
        new_status     = self.status_combo.currentText()
        new_translator = self.user_edit.text().strip()
        d              = self.date_edit.date()
        new_date       = format_date_for_storage(d)  # uses system DATE_FMT

        text_changed = new_text != self._original_text
        meta_changed = (
            new_status     != self._original_status
            or new_translator != self._original_translator.strip()
            or new_date       != self._original_date
        )

        if not text_changed and not meta_changed:
            return   # nothing to write — leave the entry and date completely untouched

        src_entry            = self._model.get_entry(self._row)
        src_entry.text       = new_text
        src_entry.translator = new_translator

        if text_changed:
            # Translation content modified: auto-advance status and stamp today
            src_entry.status      = "Complete"
            src_entry.modify_date = datetime.now().strftime(DATE_FMT)
            # Use the session translator name only when override is NOT active
            session_name = self._session_name()
            override_on  = self.override_chk.isChecked()
            if session_name and not override_on:
                src_entry.translator = session_name
                self.user_edit.blockSignals(True)
                self.user_edit.setText(session_name)  # reflect in the UI too
                self.user_edit.blockSignals(False)
        else:
            # Only metadata changed: respect whatever the user set in the fields
            src_entry.status      = new_status
            src_entry.modify_date = new_date

        # Notify the table view that this row changed
        tl = self._model.index(self._row, 0)
        br = self._model.index(self._row, len(HEADERS) - 1)
        self._model.dataChanged.emit(tl, br)
        self._any_saved = True

    def _navigate(self, delta: int):
        """Save the current row and move to row + delta."""
        if self._robo_active and not self._robo_navigating:
            self._stop_robo_chain()
        self._abandon_stale_translation()
        self._transl_generation += 1
        self._commit_current()
        self._load_row(self._row + delta)
        self.trans_edit.setFocus()

    def _populate(self):
        # A freshly-displayed entry starts with a blank translation-status
        # label -- any "Translating...", "Translated to...", or countdown
        # message belonged to whatever entry was showing before and must
        # not linger once the user has moved on.
        self._transl_status.setText("")
        self._transl_status.setToolTip("")
        self.src_view.setPlainText(self.entry.name)
        self.trans_edit.setPlainText(self.entry.text)
        idx = STATUSES.index(self.entry.status) if self.entry.status in STATUSES else 0
        self.status_combo.setCurrentIndex(idx)
        # Block textChanged so filling the field programmatically does NOT
        # trigger _on_translator_typed and falsely activate the override.
        self.user_edit.blockSignals(True)
        self.user_edit.setText(self.entry.translator)
        self.user_edit.blockSignals(False)
        parsed = parse_date(self.entry.modify_date)
        if parsed is not None:
            self.date_edit.setDate(QDate(parsed.year, parsed.month, parsed.day))
        else:
            self.date_edit.setDate(QDate.currentDate())
        # Refresh the character-count indicator when navigating between entries.
        # Guarded with hasattr because _populate may run before the label exists
        # the very first time _build() is called from __init__.
        if hasattr(self, "_char_count_label"):
            self._update_char_count()

    def _save(self):
        self._commit_current()
        self._stop_robo_chain()
        self._abandon_stale_translation()
        self._transl_generation += 1
        self.accept()

    def _delete_current(self):
        """Delete the entry currently open for editing, after confirmation.

        The actual removal is delegated to MainWindow (self._mw) -- this
        dialog doesn't own self.entries. After a confirmed
        delete, loads whichever entry now occupies the same visible
        position (like Next), or closes if none remain.
        """
        entry = self._model.get_entry(self._row)
        if entry is None or self._mw is None:
            return
        self._stop_robo_chain()
        self._abandon_stale_translation()
        self._transl_generation += 1
        if not self._mw._delete_entries([entry], parent_widget=self):
            return  # cancelled by the user
        self._any_saved = True
        if self._model.rowCount() == 0:
            self.reject()
            return
        self._load_row(min(self._row, self._model.rowCount() - 1))
        self.trans_edit.setFocus()

    # ------------------------------------------------------------------
    # Character-count length indicator
    # ------------------------------------------------------------------
    def _update_char_count(self):
        """Update the source-vs-translated character-count label.

        Two-zone piecewise threshold formula (parameters in self._char_cfg):
          short  (src <= short_text_max):
              warn    = max(min_warn,    ceil(src * short_warn_pct))
              concern = max(min_concern, ceil(src * short_concern_pct))
          long   (src >  short_text_max):
              warn    = ceil(src * long_warn_pct)
              concern = ceil(src * long_concern_pct)

        Color (theme-aware, falls back to dark theme if MainWindow missing):
            green  — delta <= warn
            amber  — warn < delta <= concern
            red    — delta > concern

        The indicator is silent (no "(+N)" suffix) when the translation is
        shorter than or equal to the source.
        """
        cfg = getattr(self, "_char_cfg", {}) or {}
        if not cfg.get("enabled", True):
            self._char_count_label.setVisible(False)
            return
        self._char_count_label.setVisible(True)

        src_len = len(getattr(self.entry, "name", "") or "")
        tr_len  = len(self.trans_edit.toPlainText())
        delta   = tr_len - src_len

        boundary = int(cfg.get("short_text_max", 30))
        if src_len <= boundary:
            warn = max(int(cfg.get("min_warn", 1)),
                       math.ceil(src_len * float(cfg.get("short_warn_pct", 0.13))))
            concern = max(int(cfg.get("min_concern", 2)),
                          math.ceil(src_len * float(cfg.get("short_concern_pct", 0.30))))
        else:
            warn    = math.ceil(src_len * float(cfg.get("long_warn_pct",    0.10)))
            concern = math.ceil(src_len * float(cfg.get("long_concern_pct", 0.25)))

        mw = self.parent()
        theme = mw._get_theme() if mw and hasattr(mw, "_get_theme") else THEMES["dark"]
        if delta <= warn:
            color = theme.get("dlg_count_ok",      "#4CAF50")
        elif delta <= concern:
            color = theme.get("dlg_count_warn",    "#FFB300")
        else:
            color = theme.get("dlg_count_concern", "#E53935")

        if delta > 0:
            text = f"Source: {src_len}  ·  Translated: {tr_len}  (+{delta})"
        else:
            text = f"Source: {src_len}  ·  Translated: {tr_len}"

        self._char_count_label.setText(text)
        self._char_count_label.setStyleSheet(
            f"color: {color}; font-weight: 600;")

    # ------------------------------------------------------------------
    # Event filter: intercept Tab and shortcuts on the two text boxes
    # ------------------------------------------------------------------
    def eventFilter(self, watched, event):
        # The type test comes first: src_view gets events (ParentChange) while
        # _build() runs, before self.trans_edit exists.
        if (event.type() == QEvent.Type.KeyPress
                and watched in (self.trans_edit, self.src_view)):
            key = event.key()

            # Tab / Shift+Tab: navigate focus between dialog controls
            if key == Qt.Key.Key_Tab:
                self.focusNextChild()
                return True
            if key == Qt.Key.Key_Backtab:
                self.focusPreviousChild()
                return True

            # ── Intercept all configured dialog shortcuts while either text
            #    box has focus.  QTextEdit consumes key events internally and
            #    never lets them bubble up to the dialog's keyPressEvent,
            #    so we must catch them here in the event filter instead.
            seq_str = QKeySequence(
                event.keyCombination()
            ).toString(QKeySequence.PortableText)

            if seq_str == self._shortcuts.get('edit_prev'):
                if self._btn_prev.isEnabled():
                    self._navigate(-1)
                return True

            if seq_str == self._shortcuts.get('edit_next'):
                if self._btn_next.isEnabled():
                    self._navigate(+1)
                return True

            if seq_str == self._shortcuts.get('edit_cancel'):
                self.reject()
                return True

            if seq_str == self._shortcuts.get('edit_save'):
                self._save()
                return True

            _mark_map = {
                'mark_new':      'New',
                'mark_review':   'Review',
                'mark_complete': 'Complete',
            }
            for slot, status in _mark_map.items():
                if seq_str == self._shortcuts.get(slot):
                    self.status_combo.setCurrentText(status)
                    return True

        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------
    # keyPressEvent: dialog-level shortcut handling
    # Alt+Left / Alt+Right navigate; Escape cancels.
    # We handle here (not in eventFilter) so the shortcuts work
    # regardless of which child widget has focus.
    # ------------------------------------------------------------------
    def keyPressEvent(self, event):
        seq = QKeySequence(event.keyCombination())
        seq_str = seq.toString(QKeySequence.PortableText)

        if seq_str == self._shortcuts.get('edit_prev'):
            if self._btn_prev.isEnabled():
                self._navigate(-1)
            return  # always consume so it doesn't propagate further

        if seq_str == self._shortcuts.get('edit_next'):
            if self._btn_next.isEnabled():
                self._navigate(+1)
            return

        if seq_str == self._shortcuts.get('edit_cancel'):
            self.reject()
            return

        if seq_str == self._shortcuts.get('edit_save'):
            self._save()
            return

        # Mark shortcuts — change the status combo for the current entry
        _mark_map = {
            'mark_new':      'New',
            'mark_review':   'Review',
            'mark_complete': 'Complete',
        }
        for slot, status in _mark_map.items():
            if seq_str == self._shortcuts.get(slot):
                self.status_combo.setCurrentText(status)
                return

        # Deliberately NOT added to eventFilter()'s trans_edit-focused
        # interception block above (unlike the mark_* shortcuts): Ctrl+Delete
        # is trans_edit's/user_edit's native "delete word forward" binding,
        # so it must keep working normally while the user is typing there.
        # It only reaches here (and deletes the entry) when focus is on a
        # non-text-consuming widget -- status combo, nav
        # buttons, etc. QLineEdit (user_edit) already consumes the key
        # itself the same way, so no separate exclusion is needed for it.
        if seq_str == self._shortcuts.get('delete_entries'):
            self._delete_current()
            return

        super().keyPressEvent(event)

    def was_modified(self) -> bool:
        """True if any row was committed (saved) or deleted during this dialog session."""
        return self._any_saved

    def reject(self):
        self._stop_robo_chain()
        self._abandon_stale_translation()
        self._transl_generation += 1
        super().reject()

    def closeEvent(self, event):
        self._stop_robo_chain()
        self._abandon_stale_translation()
        self._transl_generation += 1
        super().closeEvent(event)


# ══════════════════════════════════════════════════════════════
#  STATUS DELEGATE (color the Status column, track row hover)
# ══════════════════════════════════════════════════════════════

class StatusDelegate(QStyledItemDelegate):
    """Draws the status column as a rounded pill and highlights the hovered row. QSS ::item:hover
    is per cell, not per row, so the hovered row is tracked here (set_hover_row) instead."""

    PILL_PAD_X = 11     # horizontal padding inside the pill, px

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hover_row = -1

    def set_hover_row(self, row: int) -> None:
        if row == self.hover_row:
            return
        self.hover_row = row
        view = self.parent()
        if view is not None:
            view.viewport().update()

    @staticmethod
    def pill_rect(cell: QRect, fm: QFontMetrics, text: str) -> QRect:
        """The pill for *text*, centred in *cell* and kept 3 px inside it. Width is sized to the
        widest of the three real statuses, not *text* itself, so every pill in the column renders
        at the same width regardless of which status it shows."""
        height = min(cell.height() - 6, fm.height() + 4)
        widest = max(fm.horizontalAdvance(s) for s in STATUSES)
        width = min(cell.width() - 6, widest + 2 * StatusDelegate.PILL_PAD_X)
        rect = QRect(0, 0, width, height)
        rect.moveCenter(cell.center())
        return rect

    @staticmethod
    def _theme_name(index: QModelIndex) -> str:
        model = index.model()
        return model._theme_fn() if hasattr(model, "_theme_fn") else "dark"

    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex):
        super().initStyleOption(option, index)
        if index.row() == self.hover_row and not (option.state & QStyle.State_Selected):
            theme = THEMES.get(self._theme_name(index), THEMES["dark"])
            option.backgroundBrush = QBrush(QColor(theme["hover_row"]))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        if index.column() != COL_STATUS:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        status = opt.text
        colors = STATUS_COLORS.get(self._theme_name(index), STATUS_COLORS["dark"]).get(status)
        if colors is None:                       # unknown status: plain text
            super().paint(painter, option, index)
            return
        opt.text = ""                            # the style draws the row; the pill draws the text
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        pill = self.pill_rect(opt.rect, QFontMetrics(opt.font), status)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colors[0]))
        painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
        painter.setPen(QColor(colors[1]))
        painter.setFont(opt.font)
        painter.drawText(pill, Qt.AlignCenter, status)
        painter.restore()


# ══════════════════════════════════════════════════════════════
#  BACKUP & RESTORE HELPERS
# ══════════════════════════════════════════════════════════════

BACKUP_DIR_NAME = "JSON_Translation_file_Backups"
# Info-bar message prefixes per backup location; the names match the Restore dialog's Location column.
_BACKUP_LOCATION_LABELS = {"next_to_file": "Backup next to file", "root": "Backup in root"}

_WIN_ILLEGAL_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WIN_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}


def _sanitize_path_component(value: str, max_len: int = 60) -> str:
    """Make *value* safe to use as one Windows path component (a single
    folder or file name -- no separators survive this, so never pass a
    multi-segment path in).

    Replaces illegal characters with "_", strips trailing dots, spaces, and
    underscores (dots and spaces are silently rejected by Windows), guards against
    reserved device names, and truncates to *max_len*. Never returns "" for a
    non-empty input -- a value that sanitizes down to nothing becomes "_", so a
    present-but-odd value (e.g. "///") stays visually distinct from a genuinely
    empty one.
    """
    cleaned = _WIN_ILLEGAL_PATH_CHARS_RE.sub("_", value)
    cleaned = cleaned.rstrip(". _")
    if not cleaned:
        cleaned = "_"
    if cleaned.upper() in _WIN_RESERVED_NAMES:
        cleaned = "_" + cleaned
    cleaned = cleaned[:max_len].rstrip(". _") or "_"
    return cleaned


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write *data* to *path* atomically: write to a temp file in the same
    directory, fsync, then os.replace() into place. A crash or power loss
    mid-write can never leave *path* partially written -- it's either the
    old content or the new content, never a truncated mix. Raises on
    failure; callers decide whether that's fatal or best-effort.
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def _write_backup_slot(
    *,
    root_dir: Path,
    location_id: str,
    backup_key: str,
    ts: str,
    source_path: Path,
    raw_bytes: bytes,
    md5: str,
    glossary_source: Optional[Path],
    glossary_bytes: Optional[bytes],
    glossary_md5: Optional[str],
    compress: bool,
    max_count: int,
    trigger: str,
    culture: str,
    display_language: str,
    version: str,
    is_fallback: bool,
) -> Optional[Path]:
    """Write one complete, self-contained backup slot at
    <root_dir>/<backup_key>/<ts>/ and prune older slots for this key beyond
    *max_count*. Returns the slot dir on success, None on any failure --
    never raises; the caller decides how to report it.

    *ts* has 1-second granularity, and multiple backups for the same key can
    legitimately be written within the same second -- e.g. _do_restore()'s
    pre_restore_safety snapshot immediately followed by the reload's own
    file_open backup. Without disambiguation the second call's
    exist_ok=True mkdir would silently reuse the first call's directory,
    overwriting its backup_file and backup_info.json (including its
    trigger) and destroying the very safety snapshot it was meant to
    preserve. If *ts* is already taken, append "_001", "_002", ... until a
    free directory name is found, so every call gets its own untouched slot.
    Zero-padded to 3 digits so plain string sorting (used by both pruning
    here and the Restore dialog's newest-first ordering) stays correct past
    9 same-second collisions -- unpadded "_10" would sort between "_1" and
    "_2".
    """
    try:
        key_dir  = root_dir / backup_key
        slot_dir = key_dir / ts
        if slot_dir.exists():
            suffix = 1
            while (key_dir / f"{ts}_{suffix:03d}").exists():
                suffix += 1
            slot_dir = key_dir / f"{ts}_{suffix:03d}"
        slot_dir.mkdir(parents=True, exist_ok=True)

        if compress:
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
                gz.write(raw_bytes)
            dest = slot_dir / (source_path.name + ".gz")
            _atomic_write_bytes(dest, buf.getvalue())
        else:
            dest = slot_dir / source_path.name
            _atomic_write_bytes(dest, raw_bytes)

        info = {
            "original_path":       str(source_path),
            "backup_created":      datetime.now().isoformat(timespec="seconds"),
            "original_size_bytes": len(raw_bytes),
            "backup_file":         dest.name,
            "compressed":          compress,
            "md5_checksum":        md5,
            "version":             version,
            "culture":             culture,
            "display_language":    display_language,
            "location":            location_id,
            "backup_key":          backup_key,
            "trigger":             trigger,
            "is_fallback":         is_fallback,
        }

        glossary_backed_up = False
        if glossary_source is not None and glossary_bytes is not None:
            try:
                if compress:
                    gbuf = io.BytesIO()
                    with gzip.GzipFile(fileobj=gbuf, mode="wb", compresslevel=6) as gz:
                        gz.write(glossary_bytes)
                    glossary_dest = slot_dir / (glossary_source.name + ".gz")
                    _atomic_write_bytes(glossary_dest, gbuf.getvalue())
                else:
                    glossary_dest = slot_dir / glossary_source.name
                    _atomic_write_bytes(glossary_dest, glossary_bytes)
                info["glossary_file"]         = glossary_dest.name
                info["glossary_compressed"]   = compress
                info["glossary_md5_checksum"] = glossary_md5
                glossary_backed_up = True
            except Exception:
                pass  # glossary backup is best-effort; never blocks the language file's backup
        info["glossary_backed_up"] = glossary_backed_up

        _atomic_write_bytes(
            slot_dir / "backup_info.json",
            json.dumps(info, indent=2, ensure_ascii=False).encode("utf-8"),
        )

        # Prune: keep only the most recent max_count slots for this key
        try:
            slots = sorted(
                [d for d in key_dir.iterdir() if d.is_dir()],
                key=lambda d: d.name
            )
            while len(slots) > max_count:
                shutil.rmtree(slots.pop(0), ignore_errors=True)
        except Exception:
            pass

        return slot_dir
    except Exception:
        return None


# Serializes access to _write_backup_slot()'s same-second collision handling
# across concurrent BackupThreads -- but only between two backups that
# target the SAME key directory (e.g. a restore's pre_restore_safety
# snapshot landing in the same second as that file's own file_open
# backup). Backing up multiple files at once used to be impossible (every
# caller ran serialized on the UI thread); now that it isn't,
# _write_backup_slot()'s check-then-create slot-naming logic needs
# external serialization to stay race-free -- _write_backup_slot() itself
# is deliberately left unmodified (see its own docstring and the design
# spec's Non-goals). Keyed per resolved key_dir rather than a single
# global lock, so backups of *different* files still run fully
# concurrently -- only two backups of the *same* file actually contend.
# Only ever acquired from background BackupThread workers, never the UI
# thread, so this never reintroduces UI blocking. The lock dict grows for
# the app's lifetime (one entry per distinct key_dir ever backed up this
# session) -- the same accepted trade-off already on record for
# self._backup_threads (see the design spec's "Backward compatibility &
# accepted edge cases" section, "Thread objects accumulate in memory for
# the app's lifetime").
_key_dir_locks: Dict[Path, threading.Lock] = {}
_key_dir_locks_guard = threading.Lock()


def _lock_for_key_dir(key_dir: Path) -> threading.Lock:
    """Returns the same threading.Lock() for the same resolved key_dir on
    every call, creating it on first use. key_dir must already be resolved
    (see callers) so two different-looking paths to the same directory
    can't slip past each other and get separate locks."""
    with _key_dir_locks_guard:
        lock = _key_dir_locks.get(key_dir)
        if lock is None:
            lock = threading.Lock()
            _key_dir_locks[key_dir] = lock
        return lock


def _newest_slot_age_seconds(root_dir: Path, backup_key: str) -> Optional[float]:
    """Seconds elapsed since the newest existing backup slot for *backup_key*
    under *root_dir*, or None when there is nothing usable to measure against
    (no key directory, no parseable slot names, or the directory can't be
    read). None always means "nothing to throttle against" -- i.e. back up.
    Failing open is the safe direction: a throttle that can't read the disk
    must never silently suppress backups.

    The age comes from the slot directory NAME, not its mtime and not
    backup_info.json's "backup_created": the name is the same
    "%Y-%m-%d_%H-%M-%S" string that _write_backup_slot()'s pruning and the
    Restore dialog's ordering already treat as authoritative, it costs no
    file reads, and unlike mtime it survives the backup tree being copied or
    moved between drives. Only the first 19 characters are parsed, so a
    same-second collision suffix ("_001") is ignored.
    """
    try:
        newest: Optional[datetime] = None
        for d in (root_dir / backup_key).iterdir():
            if not d.is_dir():
                continue
            try:
                stamp = datetime.strptime(d.name[:19], "%Y-%m-%d_%H-%M-%S")
            except ValueError:
                continue  # a hand-created folder must not disable the throttle
            if newest is None or stamp > newest:
                newest = stamp
        if newest is None:
            return None
        return (datetime.now() - newest).total_seconds()
    except Exception:
        return None


def _format_slot_age(seconds: float) -> str:
    """Human-readable backup age for the "skipped" status message. A negative
    value (a future-dated slot, e.g. after a clock change) reads as the most
    recent bucket, which is the correct interpretation."""
    if seconds < 60:
        return "less than a minute ago"
    return f"{int(seconds // 60)} min ago"


class BackupThread(QThread):
    """Runs the file read, hashing, gzip compression, atomic write, and
    pruning that MainWindow._create_backup() used to do inline on the UI
    thread -- all pure I/O/CPU work with no Qt objects involved, so none of
    it needs to run there. Mirrors TranslationThread's signal-driven
    completion pattern (see TranslationThread above).

    Everything read from settings (cfg) is captured as a plain dict
    snapshot before the thread starts, so run() never touches MainWindow
    or Settings at all -- no cross-thread access to mutable shared state.

    Signals
    -------
    finished(list, object) -- emitted exactly once, with:
      - notices: (text, level) pairs for MainWindow._show_message(), one per
        location, next to file first (e.g. ("Backup in root: saved at
        14:30:00  (compressed)", "info")); a failure that involves no location
        (unreadable source file, unexpected error) is a single error
      - next_to_file_root: the resolved next-to-file backup directory (a
        Path) if that location succeeded, else None.
        MainWindow._remember_next_to_file_backup_dir() touches
        settings.data and must run on the main thread, so this thread only
        reports which root to remember -- it never calls it itself.
    """
    finished = Signal(list, object)

    def __init__(self, source_path: Path, trigger: str, cfg: dict,
                 app_dir: Path, parent=None):
        super().__init__(parent)
        self._source_path = source_path
        self._trigger     = trigger
        self._cfg         = cfg       # plain dict snapshot of settings.get("backup", {})
        self._app_dir     = app_dir

    def run(self):
        try:
            cfg           = self._cfg
            source_path   = self._source_path
            trigger       = self._trigger
            app_dir       = self._app_dir

            max_count     = int(cfg.get("max_count", 5))
            compress      = bool(cfg.get("compress", True))
            location_mode = cfg.get("location_mode", "both")
            if location_mode not in ("next_to_file", "root", "both"):
                location_mode = "both"
            try:
                min_interval = int(cfg.get("min_interval_minutes", 5))
            except (TypeError, ValueError):
                min_interval = 5
            if min_interval < 0:
                min_interval = 0
            # A pre_restore_safety snapshot is the only thing standing between
            # a wrong-slot restore and unrecoverable loss -- it ignores the
            # interval unconditionally.
            throttle_enabled = min_interval > 0 and trigger == "file_open"

            header           = read_file_header(source_path)
            culture          = effective_language(header, source_path)
            display_language = header.language_name
            version          = header.version
            sanitized_version = _sanitize_path_component(version) if version else ""
            backup_key = (f"{source_path.stem}__v{sanitized_version}"
                          if sanitized_version else source_path.stem)

            next_to_file_root = source_path.parent / BACKUP_DIR_NAME
            root_root         = app_dir / BACKUP_DIR_NAME

            def throttled_age(root_dir: Path) -> Optional[float]:
                """Age of root_dir's newest slot for this key when it falls
                inside the min-interval window (meaning: skip this location),
                else None."""
                if not throttle_enabled:
                    return None
                age = _newest_slot_age_seconds(root_dir, backup_key)
                return age if (age is not None and age < min_interval * 60) else None

            skip_ntf_age  = (throttled_age(next_to_file_root)
                             if location_mode in ("next_to_file", "both") else None)
            skip_root_age = (throttled_age(root_root)
                             if location_mode in ("root", "both") else None)

            skipped: Dict[str, float] = {}   # location id -> age of its newest slot
            if skip_ntf_age is not None:
                skipped["next_to_file"] = skip_ntf_age
            if skip_root_age is not None:
                skipped["root"] = skip_root_age

            def skipped_notice(location_id: str) -> Tuple[str, str]:
                return (f"{_BACKUP_LOCATION_LABELS[location_id]}: skipped — backed up "
                        f"{_format_slot_age(skipped[location_id])}  (min interval {min_interval} min)",
                        "info")

            will_write = (
                (location_mode in ("next_to_file", "both") and skip_ntf_age is None)
                or (location_mode in ("root", "both") and skip_root_age is None)
            )
            if skipped and not will_write:
                # Return before read_bytes/md5/gzip -- the point of the
                # throttle is that re-opening a file costs no file I/O.
                self.finished.emit([skipped_notice(loc) for loc in skipped], None)
                return

            try:
                raw_bytes = source_path.read_bytes()
            except Exception as e:
                _log_error(f"BackupThread: failed to read source file {source_path}", e)
                self.finished.emit([("Backup failed — could not read source file", "error")], None)
                return
            md5 = hashlib.md5(raw_bytes).hexdigest()

            glossary_source = glossary_path_for(source_path)
            glossary_bytes  = None
            glossary_md5    = None
            if glossary_source.exists():
                try:
                    glossary_bytes = glossary_source.read_bytes()
                    glossary_md5   = hashlib.md5(glossary_bytes).hexdigest()
                except Exception:
                    glossary_source = None  # best-effort; skip on read failure

            results: dict = {}
            next_to_file_root_ok: Optional[Path] = None
            now = datetime.now()
            ts = now.strftime("%Y-%m-%d_%H-%M-%S")

            def write_at(location_id: str, root_dir: Path, is_fallback: bool = False) -> Optional[Path]:
                # Locked per key_dir, not globally -- see _lock_for_key_dir.
                # Only two backups of the SAME file (same root_dir AND
                # backup_key) ever wait on each other here.
                try:
                    key_dir = (root_dir / backup_key).resolve()
                except OSError:
                    key_dir = root_dir / backup_key
                with _lock_for_key_dir(key_dir):
                    return _write_backup_slot(
                        root_dir=root_dir, location_id=location_id, backup_key=backup_key, ts=ts,
                        source_path=source_path, raw_bytes=raw_bytes, md5=md5,
                        glossary_source=glossary_source, glossary_bytes=glossary_bytes,
                        glossary_md5=glossary_md5, compress=compress, max_count=max_count,
                        trigger=trigger, culture=culture, display_language=display_language,
                        version=version, is_fallback=is_fallback,
                    )

            if location_mode in ("next_to_file", "both") and skip_ntf_age is None:
                results["next_to_file"] = write_at("next_to_file", next_to_file_root)
                if results["next_to_file"] is not None:
                    next_to_file_root_ok = next_to_file_root
            if location_mode in ("root", "both") and skip_root_age is None:
                results["root"] = write_at("root", root_root)

            # Fall back only after a location was actually ATTEMPTED and failed
            # -- a skip is not a failure -- and only when root isn't already
            # holding a slot inside the window, since there'd be nothing to
            # recover.
            if (location_mode == "next_to_file"
                    and skip_ntf_age is None
                    and results.get("next_to_file") is None
                    and throttled_age(root_root) is None):
                results["root (fallback)"] = write_at(
                    "root", root_root, is_fallback=True)

            label = "compressed" if compress else "plain"

            def written_notice(prefix: str, slot: Optional[Path], level: str) -> Tuple[str, str]:
                if slot is None:
                    return f"{prefix}: failed — could not write the backup folder", "error"
                glossary_note = ""
                try:
                    slot_info = json.loads((slot / "backup_info.json").read_text(encoding="utf-8"))
                    if slot_info.get("glossary_backed_up", False):
                        glossary_note = ", +glossary"
                except Exception:
                    pass
                return f"{prefix}: saved at {now:%H:%M:%S}  ({label}{glossary_note})", level

            notices: List[Tuple[str, str]] = []
            for location_id in ("next_to_file", "root"):
                if location_id in results:
                    notices.append(written_notice(
                        _BACKUP_LOCATION_LABELS[location_id], results[location_id], "info"))
                elif location_id in skipped:
                    notices.append(skipped_notice(location_id))
            if "root (fallback)" in results:
                # A warning: it worked, but not where the user chose.
                notices.append(written_notice(
                    "Backup in root (fallback)", results["root (fallback)"], "warning"))

            self.finished.emit(notices, next_to_file_root_ok)
        except Exception as exc:
            self.finished.emit([(f"Backup failed: {exc}", "error")], None)


# ══════════════════════════════════════════════════════════════
#  RESTORE FROM BACKUP DIALOG
# ══════════════════════════════════════════════════════════════

class RestoreFromBackupDialog(QDialog):
    """Browse all available backup slots and select one for restoration."""

    def __init__(self, app_dir: Path, parent=None):
        super().__init__(parent)
        self._app_dir = app_dir
        self._selected_slot_dir: Optional[Path] = None
        self._selected_info: Optional[dict] = None
        self._selected_location_id: Optional[str] = None
        self._restore_glossary = False   # the checkbox as it stood on close -- see done()
        self.setWindowTitle("Restore from Backup")
        self.setMinimumSize(860, 460)
        self.setModal(True)
        # See the "A dialog constructed with parent=self..." pitfall in CLAUDE.md:
        # without this, closing via accept()/reject() never actually destroys the
        # dialog. Safe here specifically because the real restore work
        # (_do_restore_after_backup(), the BackupThread interaction) runs on
        # MainWindow after this dialog has already been accept()-ed and hidden --
        # this dialog itself never holds a live background-thread reference.
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._build_ui()
        self._load_backups()
        self._apply_style()
        self._fit_to_content()

    def _fit_to_content(self):
        """Resize once, right after the tree is first populated, so all
        column content and backup-slot rows are visible without truncation
        or unnecessary scrolling -- but never larger than the screen's
        available space. Only called from __init__; later tree refreshes
        (e.g. after a delete) deliberately don't re-trigger this, so the
        window doesn't grow/shrink again mid-session.
        """
        tree_width = sum(self._tree.columnWidth(i) for i in range(self._tree.columnCount()))
        tree_width += self._tree.frameWidth() * 2 + 24  # frame + scrollbar allowance

        row_count = 0

        def _count_rows(item):
            nonlocal row_count
            row_count += 1
            for i in range(item.childCount()):
                _count_rows(item.child(i))

        for i in range(self._tree.topLevelItemCount()):
            _count_rows(self._tree.topLevelItem(i))

        row_height = self._tree.sizeHintForRow(0) if row_count > 0 else 20
        tree_height = (self._tree.header().height() + row_count * row_height
                       + self._tree.frameWidth() * 2)

        # Temporarily give the tree its real content size as a minimum so
        # the dialog's own QVBoxLayout sizes everything else (label, detail
        # bar, checkbox, button row) around it via Qt's own layout engine,
        # rather than this method hand-guessing their heights.
        self._tree.setMinimumSize(tree_width, tree_height)
        natural_size = self.layout().sizeHint()
        self._tree.setMinimumSize(0, 0)  # release the temporary floor --
                                          # stays freely resizable afterward

        screen = self.screen() or QApplication.primaryScreen()
        margin = 60
        if screen is not None:
            avail = screen.availableGeometry()
            max_w = max(self.minimumWidth(), avail.width() - margin)
            max_h = max(self.minimumHeight(), avail.height() - margin)
        else:
            max_w, max_h = natural_size.width(), natural_size.height()

        self.resize(min(natural_size.width(), max_w), min(natural_size.height(), max_h))

    def _apply_style(self):
        mw = self.parent()
        t  = mw._get_theme() if mw and hasattr(mw, "_get_theme") else THEMES["dark"]
        pt = (mw.settings.get_font().pointSize() if mw and hasattr(mw, "settings") else 0) or 10
        pt_small = max(8, pt - 1)
        self.setStyleSheet(f"""
            QDialog      {{ background: {t['dlg_bg']}; }}
            QLabel       {{ color: {t['fg']}; }}
            {_table_qss(t, pt, gridline=t['border'])}
            QCheckBox    {{ color: {t['fg']}; }}
            {_prominent_checkbox_qss(t)}
            {_button_qss(t, pt)}
            {_band_qss(t, pt_small)}
        """)
        self._detail_lbl.setStyleSheet(f"font-size: {pt_small}pt; color: {t['fg_dim']};")

    # ── Public API ────────────────────────────────────────────

    def selected_slot_dir(self) -> Optional[Path]:
        return self._selected_slot_dir

    def selected_info(self) -> Optional[dict]:
        return self._selected_info

    def restore_glossary_requested(self) -> bool:
        return self._restore_glossary

    def done(self, result: int):
        """Keep the glossary checkbox's state: QDialog.exec() deletes this WA_DeleteOnClose
        dialog, checkbox included, before it returns to MainWindow._open_restore_backup(),
        which asks for it."""
        self._restore_glossary = self._restore_glossary_chk.isChecked()
        super().done(result)

    # ── UI construction ───────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        header = QFrame()
        header.setObjectName("dlgHeaderBand")
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(12, 10, 12, 10)
        header_lay.addWidget(QLabel("Select a backup version to restore:"))
        lay.addWidget(header)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(5)
        self._tree.setHeaderLabels(
            ["File / Version / Backup Slot", "Date & Time", "Size", "Compressed", "Location"]
        )
        self._tree.setRootIsDecorated(True)
        self._tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        lay.addWidget(self._tree, 1)

        footer = QFrame()
        footer.setObjectName("dlgFooterBand")
        footer_lay = QVBoxLayout(footer)
        footer_lay.setContentsMargins(12, 8, 12, 8)
        footer_lay.setSpacing(6)

        self._detail_lbl = QLabel()
        self._detail_lbl.setWordWrap(True)
        footer_lay.addWidget(self._detail_lbl)

        self._restore_glossary_chk = QCheckBox("Also restore glossary")
        self._restore_glossary_chk.setProperty("filterChk", True)
        self._restore_glossary_chk.setVisible(False)
        footer_lay.addWidget(self._restore_glossary_chk)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._delete_btn = QPushButton("Delete Selected")
        self._delete_btn.setEnabled(False)
        self._delete_btn.setProperty("role", "danger")
        self._delete_btn.clicked.connect(self._on_delete)
        self._restore_btn = QPushButton("Restore Selected")
        self._restore_btn.setEnabled(False)
        self._restore_btn.setProperty("role", "primary")
        self._restore_btn.clicked.connect(self._on_restore)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._delete_btn)
        btn_row.addWidget(self._restore_btn)
        btn_row.addWidget(cancel_btn)
        footer_lay.addLayout(btn_row)
        lay.addWidget(footer)
        # After the footer joins the dialog: setDefault() registers the dialog default only once the button
        # has a QDialog ancestor, and a repeated call does nothing, so there must be no earlier call.
        self._restore_btn.setDefault(True)

    # ── Populate tree ─────────────────────────────────────────

    _KEY_VERSION_RE = re.compile(r"^(.*)__v(.+)$")
    # Matches the zero-padded disambiguation suffix _write_backup_slot()
    # appends to *ts* on a same-second collision, e.g. "..._001". \d+ (not
    # a fixed width) so it still matches if the counter ever grows past 999.
    _TS_COLLISION_SUFFIX_RE = re.compile(r"^(.*)_(\d+)$")

    def _scan_roots(self) -> List[Tuple[str, Path]]:
        """Every backup root to scan: the app-root tree, plus every
        remembered next-to-file tree that still exists on disk."""
        roots: List[Tuple[str, Path]] = [("root", self._app_dir / BACKUP_DIR_NAME)]
        mw = self.parent()
        known: List[str] = []
        if mw is not None and hasattr(mw, "settings"):
            raw = mw.settings.get("backup", {}).get("known_next_to_file_dirs", [])
            if isinstance(raw, list):
                known = raw
        seen = {str(roots[0][1].resolve())}
        for d in known:
            p = Path(d)
            if not p.is_dir():
                continue
            resolved = str(p.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            roots.append(("next_to_file", p))
        return roots

    def _format_slot_timestamp(self, ts: str) -> str:
        """Format a slot folder name (e.g. "2026-08-20_10-00-00", or after a
        same-second collision "2026-08-20_10-00-00_001") into a human-readable
        date/time string. A same-second collision (see _write_backup_slot)
        appends "_NNN" to ts, which strptime can't parse as-is -- strip it off,
        parse the base timestamp, and mark the result with "(#N)" instead of
        falling back to the raw folder name.

        Shared by both `_load_backups()`'s tree display and `_on_delete()`'s
        confirmation dialog -- keep them in sync by editing only here.
        """
        base_ts, collision_n = ts, None
        m = self._TS_COLLISION_SUFFIX_RE.match(ts)
        if m:
            base_ts, collision_n = m.group(1), m.group(2)
        try:
            dt = datetime.strptime(base_ts, "%Y-%m-%d_%H-%M-%S")
            dt_str = dt.strftime("%Y-%m-%d  %H:%M:%S")
            if collision_n is not None:
                dt_str += f"  (#{int(collision_n) + 1})"
        except ValueError:
            dt_str = ts
        return dt_str

    def _load_backups(self):
        scan_roots = self._scan_roots()

        # merged[stem][version_group] -> list of (slot_dir, info, location_id).
        # version_group is None for backups with no "__v" suffix in their key.
        merged: Dict[str, Dict[Optional[str], List[Tuple[Path, dict, str]]]] = {}

        for location_id, backup_root in scan_roots:
            if not backup_root.is_dir():
                continue
            for key_dir in backup_root.iterdir():
                if not key_dir.is_dir():
                    continue
                m = self._KEY_VERSION_RE.match(key_dir.name)
                stem, version_group = (m.group(1), m.group(2)) if m else (key_dir.name, None)

                for slot_dir in key_dir.iterdir():
                    if not slot_dir.is_dir():
                        continue
                    info_path = slot_dir / "backup_info.json"
                    if not info_path.exists():
                        continue
                    try:
                        info = json.loads(info_path.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    merged.setdefault(stem, {}).setdefault(version_group, []).append(
                        (slot_dir, info, location_id))

        if not merged:
            self._tree.addTopLevelItem(QTreeWidgetItem(["No backup slots found."]))
            return

        for stem in sorted(merged.keys()):
            stem_item = QTreeWidgetItem([stem])
            f = stem_item.font(0)
            f.setBold(True)
            stem_item.setFont(0, f)
            stem_item.setData(0, Qt.UserRole, None)
            stem_item.setFlags(stem_item.flags() & ~Qt.ItemIsSelectable)

            version_groups = merged[stem]
            ordered_versions = sorted(
                version_groups.keys(), key=lambda v: (v is not None, v or ""))
            for version_group in ordered_versions:
                version_item = QTreeWidgetItem(
                    [version_group if version_group is not None else "(unversioned)"])
                vf = version_item.font(0)
                vf.setItalic(True)
                version_item.setFont(0, vf)
                version_item.setData(0, Qt.UserRole, None)
                version_item.setFlags(version_item.flags() & ~Qt.ItemIsSelectable)

                slots = sorted(version_groups[version_group],
                                key=lambda t: t[0].name, reverse=True)
                for slot_dir, info, location_id in slots:
                    ts = slot_dir.name  # YYYY-MM-DD_HH-MM-SS[_NNN collision suffix]
                    dt_str = self._format_slot_timestamp(ts)

                    size_bytes = info.get("original_size_bytes", 0)
                    if size_bytes >= 1024 * 1024:
                        size_str = f"{size_bytes / (1024 * 1024):.2f} MB"
                    elif size_bytes >= 1024:
                        size_str = f"{size_bytes / 1024:.1f} KB"
                    else:
                        size_str = f"{size_bytes} B"

                    compressed_str = "Yes" if info.get("compressed", True) else "No"
                    location_str = "Next to file" if location_id == "next_to_file" else "Root"

                    slot_item = QTreeWidgetItem(
                        ["    " + ts, dt_str, size_str, compressed_str, location_str])
                    slot_item.setData(0, Qt.UserRole, (slot_dir, info, location_id))
                    version_item.addChild(slot_item)

                if version_item.childCount() > 0:
                    stem_item.addChild(version_item)

            if stem_item.childCount() > 0:
                self._tree.addTopLevelItem(stem_item)

        self._tree.expandAll()
        for col in range(5):
            self._tree.resizeColumnToContents(col)
        self._tree.setColumnWidth(0, max(self._tree.columnWidth(0), 280))

    # ── Slots ─────────────────────────────────────────────────

    def _on_selection_changed(self, current, _previous):
        if current is None:
            self._restore_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            self._selected_location_id = None
            self._detail_lbl.setText("")
            self._restore_glossary_chk.setVisible(False)
            return
        data = current.data(0, Qt.UserRole)
        if data is None:
            self._restore_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            self._selected_location_id = None
            self._detail_lbl.setText("")
            self._restore_glossary_chk.setVisible(False)
            return
        slot_dir, info, location_id = data
        self._selected_slot_dir = slot_dir
        self._selected_info = info
        self._selected_location_id = location_id
        self._restore_btn.setEnabled(True)
        self._delete_btn.setEnabled(True)
        orig    = info.get("original_path", "unknown")
        created = info.get("backup_created", "unknown")
        md5     = info.get("md5_checksum", "")
        self._detail_lbl.setText(
            f"Original path: {orig}     Created: {created}     MD5: {md5}"
        )
        if info.get("glossary_backed_up", False):
            orig_stem = Path(orig).stem if orig != "unknown" else ""
            display_name = f"{orig_stem}.glossary.csv" if orig_stem else "glossary.csv"
            self._restore_glossary_chk.setText(f"Also restore glossary ({display_name})")
            mw = self.parent()
            default_checked = False
            if mw is not None and hasattr(mw, "settings"):
                default_checked = bool(
                    mw.settings.get("backup", {}).get("restore_glossary_default", False))
            self._restore_glossary_chk.setChecked(default_checked)
            self._restore_glossary_chk.setVisible(True)
        else:
            self._restore_glossary_chk.setChecked(False)
            self._restore_glossary_chk.setVisible(False)

    def _on_double_click(self, item, _col):
        if item.data(0, Qt.UserRole) is not None:
            self._on_restore()

    def _on_restore(self):
        if self._selected_slot_dir is not None:
            self.accept()

    def _on_delete(self):
        if self._selected_slot_dir is None:
            return
        slot_dir = self._selected_slot_dir
        info     = self._selected_info

        try:
            remaining = len([d for d in slot_dir.parent.iterdir()
                              if d.is_dir() and d != slot_dir])
        except OSError:
            # Err toward the cautious "only backup remaining" warning rather
            # than under-warning about a destructive action.
            remaining = 0
        location_str = "Next to file" if self._selected_location_id == "next_to_file" else "Root"
        orig = info.get("original_path", "unknown")
        dt_str = self._format_slot_timestamp(slot_dir.name)

        msg = (f"Delete this backup?\n\n"
               f"{orig}\n"
               f"{dt_str}  —  {location_str}\n\n"
               f"This cannot be undone.")
        if remaining == 0:
            msg += "\n\nThis is the only backup remaining for this file at this location."

        r = QMessageBox.question(
            self, "Delete Backup", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if r != QMessageBox.Yes:
            return

        try:
            # Deliberately not ignore_errors=True (unlike automatic pruning) --
            # a user-confirmed delete should surface failure. A partial failure
            # (e.g. a locked file) can leave an orphaned, UI-invisible folder;
            # accepted as a low-probability, low-severity limitation rather
            # than adding retry/attribute-clearing complexity.
            shutil.rmtree(slot_dir)
        except Exception as e:
            _log_error(f"_on_delete: failed to delete backup slot {slot_dir}", e)
            QMessageBox.critical(self, "Delete Error", "Failed to delete backup.")

        self._tree.clear()
        self._selected_slot_dir = None
        self._selected_info = None
        self._selected_location_id = None
        self._restore_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        self._detail_lbl.setText("")
        self._restore_glossary_chk.setVisible(False)
        self._load_backups()


# ════════════════════════════════════════════════════════════════
#  AUTOSAVE & BACKUP SETTINGS DIALOG
# ════════════════════════════════════════════════════════════════

class AutosaveBackupDialog(QDialog):
    """Settings dialog for autosave and backup configuration."""

    _LOCATION_MODES = ["both", "next_to_file", "root"]

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Autosave & Backup Settings")
        self.setMinimumWidth(440)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._build_ui()
        self._load_values()
        self._apply_style()
        self._align_columns()

    def _align_columns(self):
        """The two sections are separate grids, so each sized its label column to its own
        labels and the spin boxes started at different x. Both grids get the widest label's
        width, and the three spin boxes the widest one's size hint, measured after
        _apply_style() has set the font: one column that grows with the UI font (a fixed
        130 px cut "Always back up" from 12 pt). A spin box's size hint covers its minimum,
        maximum and special text whatever its value. Fixed, not a column minimum: the location
        combo spans the spin boxes' column, and a wide combo would widen that column too."""
        grids = (self._as_grid, self._bk_grid)
        label_width = max(grid.itemAt(i).widget().sizeHint().width()
                          for grid in grids for i in range(grid.count())
                          if grid.getItemPosition(i)[1] == 0 and grid.getItemPosition(i)[3] == 1)
        for grid in grids:
            grid.setColumnMinimumWidth(0, label_width)
        spins = (self._as_spin, self._bk_spin, self._bk_min_interval_spin)
        spin_width = max(spin.sizeHint().width() for spin in spins)
        for spin in spins:
            spin.setFixedWidth(spin_width)

    def _apply_style(self):
        mw = self.parent()
        t  = mw._get_theme() if mw and hasattr(mw, "_get_theme") else THEMES["dark"]
        pt = self._settings.get_font().pointSize() or 10
        pt_small = max(8, pt - 1)
        self.setStyleSheet(f"""
            QDialog   {{ background: {t['dlg_bg']}; }}
            QLabel    {{ color: {t['fg']}; }}
            {_groupbox_qss(t, pt)}
            QSpinBox {{ background: {t['bg4']}; color: {t['fg']};
                        border: 1px solid {t['border2']}; border-radius: 3px;
                        padding: 3px 6px; }}
            {_spinbox_qss(t, pt)}
            QComboBox {{ background: {t['bg4']}; color: {t['fg']};
                         border: 1px solid {t['border2']}; border-radius: 3px;
                         padding: 3px 6px; }}
            QComboBox QAbstractItemView {{ background: {t['bg2']}; color: {t['fg']};
                                           selection-background-color: {t['sel_bg']};
                                           selection-color: {t['sel_fg']}; }}
            {_combobox_qss(t, pt)}
            QCheckBox {{ color: {t['fg']}; }}
            {_prominent_checkbox_qss(t)}
            {_button_qss(t, pt)}
            {_field_state_qss(t)}
        """)
        self._as_note.setStyleSheet(f"color: {t['fg_dim']}; font-size: {pt_small}pt;")
        self._bk_note.setStyleSheet(f"color: {t['fg_dim']}; font-size: {pt_small}pt;")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        as_grp = QGroupBox("Autosave")
        as_lay = QGridLayout(as_grp)
        as_lay.setColumnStretch(2, 1)   # spare width goes here, not to the fields
        self._as_grid = as_lay
        self._as_enable = QCheckBox("Enable autosave")
        self._as_enable.setProperty("filterChk", True)
        as_lay.addWidget(self._as_enable, 0, 0, 1, 3)
        as_lay.addWidget(QLabel("Interval:"), 1, 0)
        self._as_spin = QSpinBox()
        self._as_spin.setRange(1, 60)
        self._as_spin.setSuffix(" minutes")
        as_lay.addWidget(self._as_spin, 1, 1)
        self._as_note = QLabel("Saves silently to the current file (same as Ctrl+S)")
        as_lay.addWidget(self._as_note, 2, 0, 1, 3)
        layout.addWidget(as_grp)

        bk_grp = QGroupBox("Session Backup")
        bk_lay = QGridLayout(bk_grp)
        bk_lay.setColumnStretch(2, 1)
        self._bk_grid = bk_lay
        self._bk_enable = QCheckBox("Create backup when a file is opened")
        self._bk_enable.setProperty("filterChk", True)
        bk_lay.addWidget(self._bk_enable, 0, 0, 1, 3)
        bk_lay.addWidget(QLabel("Keep last:"), 1, 0)
        self._bk_spin = QSpinBox()
        self._bk_spin.setRange(1, 50)
        self._bk_spin.setSuffix(" backups")
        bk_lay.addWidget(self._bk_spin, 1, 1)
        bk_lay.addWidget(QLabel("Skip if backed up within:"), 2, 0)
        self._bk_min_interval_spin = QSpinBox()
        self._bk_min_interval_spin.setRange(0, 1440)
        self._bk_min_interval_spin.setSuffix(" minutes")
        self._bk_min_interval_spin.setSpecialValueText("Always back up")
        self._bk_min_interval_spin.setToolTip(
            "Re-opening the same file within this window reuses the existing\n"
            "backup instead of writing a new slot. Set to 0 to back up on\n"
            "every open. The safety backup taken before restoring over a file\n"
            "is never skipped.")
        bk_lay.addWidget(self._bk_min_interval_spin, 2, 1)
        self._bk_compress = QCheckBox(
            "Compress backups (.json.gz)  — saves ~70% disk space")
        self._bk_compress.setProperty("filterChk", True)
        bk_lay.addWidget(self._bk_compress, 3, 0, 1, 3)
        bk_lay.addWidget(QLabel("Backup location:"), 4, 0)
        self._bk_location_combo = _WidePopupComboBox()
        self._bk_location_combo.addItems([
            "Next to file + Root (recommended)",
            "Next to file only",
            "Root folder only",
        ])
        bk_lay.addWidget(self._bk_location_combo, 4, 1, 1, 2, Qt.AlignLeft)
        self._bk_restore_glossary = QCheckBox(
            "Restore glossary by default when restoring a backup")
        self._bk_restore_glossary.setProperty("filterChk", True)
        bk_lay.addWidget(self._bk_restore_glossary, 5, 0, 1, 3)
        self._bk_note = QLabel(
            "Location:  JSON_Translation_file_Backups / <filename> / <date-time> /\n"
            "Root: next to the app, or next to the file (or both) — see dropdown above.")
        bk_lay.addWidget(self._bk_note, 6, 0, 1, 3)
        layout.addWidget(bk_grp)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn   = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        save_btn.setDefault(True)
        save_btn.setProperty("role", "primary")
        save_btn.clicked.connect(self._save)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self._as_enable.toggled.connect(self._as_spin.setEnabled)
        self._bk_enable.toggled.connect(self._bk_spin.setEnabled)
        self._bk_enable.toggled.connect(self._bk_min_interval_spin.setEnabled)
        self._bk_enable.toggled.connect(self._bk_compress.setEnabled)
        self._bk_enable.toggled.connect(self._bk_location_combo.setEnabled)

    def _load_values(self):
        as_cfg = self._settings.get("autosave", {})
        bk_cfg = self._settings.get("backup",   {})
        self._as_enable.setChecked(as_cfg.get("enabled", False))
        self._as_spin.setValue(int(as_cfg.get("interval_minutes", 5)))
        self._as_spin.setEnabled(as_cfg.get("enabled", False))
        self._bk_enable.setChecked(bk_cfg.get("enabled", True))
        self._bk_spin.setValue(int(bk_cfg.get("max_count", 5)))
        self._bk_min_interval_spin.setValue(int(bk_cfg.get("min_interval_minutes", 5)))
        self._bk_compress.setChecked(bk_cfg.get("compress", True))
        location_mode = bk_cfg.get("location_mode", "both")
        idx = (self._LOCATION_MODES.index(location_mode)
               if location_mode in self._LOCATION_MODES else 0)
        self._bk_location_combo.setCurrentIndex(idx)
        self._bk_restore_glossary.setChecked(bk_cfg.get("restore_glossary_default", False))
        self._bk_spin.setEnabled(bk_cfg.get("enabled", True))
        self._bk_min_interval_spin.setEnabled(bk_cfg.get("enabled", True))
        self._bk_compress.setEnabled(bk_cfg.get("enabled", True))
        self._bk_location_combo.setEnabled(bk_cfg.get("enabled", True))

    def _save(self):
        self._settings.data["autosave"] = {
            "enabled":          self._as_enable.isChecked(),
            "interval_minutes": self._as_spin.value(),
        }
        # known_next_to_file_dirs is appended to at runtime by _create_backup,
        # outside this dialog -- must be carried forward, not wiped, whenever
        # this dialog's Save button is clicked.
        existing_known = self._settings.get("backup", {}).get("known_next_to_file_dirs", [])
        if not isinstance(existing_known, list):
            existing_known = []
        self._settings.data["backup"] = {
            "enabled":                  self._bk_enable.isChecked(),
            "max_count":                self._bk_spin.value(),
            "min_interval_minutes":     self._bk_min_interval_spin.value(),
            "compress":                 self._bk_compress.isChecked(),
            "restore_glossary_default": self._bk_restore_glossary.isChecked(),
            "location_mode":            self._LOCATION_MODES[self._bk_location_combo.currentIndex()],
            "known_next_to_file_dirs":  existing_known,
        }
        self._settings.save()
        self.accept()


# ══════════════════════════════════════════════════════════════
#  GLOSSARY DIALOG
# ══════════════════════════════════════════════════════════════

class GlossaryDialog(QDialog):
    """Table editor for the glossary CSV paired with the current language file."""

    def __init__(self, mw: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw = mw
        self.app_font = mw.settings.get_font()
        self.setWindowTitle(f"Glossary — {mw.glossary_path.name}")
        self.setMinimumSize(860, 460)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        # See the "A dialog constructed with parent=self..." pitfall in CLAUDE.md:
        # without this, closing via accept()/reject() never actually destroys the
        # dialog. Safe here trivially -- GlossaryDialog spawns no threads at all.
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._build_ui()
        self._load_values()
        self._apply_style()
        self._fit_to_content()

    def _fit_to_content(self):
        """Resize once, right after the table is first populated, so all
        column content and glossary rows are visible without truncation --
        but never larger than the screen's available space. Only called
        from __init__; later row changes (Add Row / Remove Selected Row)
        deliberately don't re-trigger this, so the window doesn't grow or
        shrink again mid-session.
        """
        table_width = sum(self.table.columnWidth(i) for i in range(self.table.columnCount()))
        table_width += self.table.frameWidth() * 2 + 24  # frame + scrollbar allowance

        row_count = self.table.rowCount()
        vheader = self.table.verticalHeader()
        row_height = vheader.sectionSize(0) if row_count > 0 else vheader.defaultSectionSize()
        table_height = (self.table.horizontalHeader().height() + row_count * row_height
                         + self.table.frameWidth() * 2)

        # Temporarily give the table its real content size as a minimum so
        # the dialog's own QVBoxLayout sizes everything else (hint label,
        # warning banner, button rows) around it via Qt's own layout engine,
        # rather than this method hand-guessing their heights.
        self.table.setMinimumSize(table_width, table_height)
        natural_size = self.layout().sizeHint()
        self.table.setMinimumSize(0, 0)  # release the temporary floor --
                                          # stays freely resizable afterward

        screen = self.screen() or QApplication.primaryScreen()
        margin = 60
        if screen is not None:
            avail = screen.availableGeometry()
            max_w = max(self.minimumWidth(), avail.width() - margin)
            # A glossary with many terms would otherwise grow this dialog to
            # nearly full screen height (the only prior cap was the same
            # screen-minus-margin bound RestoreFromBackupDialog uses, sized
            # for that dialog's usually-small backup-slot tree, not a
            # potentially long glossary). Capped at a proportion of the
            # screen, not a fixed pixel count, so it scales sensibly across
            # different monitor sizes; beyond this the table's own scrollbar
            # takes over rather than the whole window.
            max_h = max(self.minimumHeight(), min(avail.height() - margin,
                                                    int(avail.height() * 0.75)))
        else:
            max_w, max_h = natural_size.width(), natural_size.height()

        self.resize(min(natural_size.width(), max_w), min(natural_size.height(), max_h))

    def _apply_style(self):
        mw = self._mw
        t  = mw._get_theme() if mw and hasattr(mw, "_get_theme") else THEMES["dark"]
        pt = self.app_font.pointSize() or 10
        pt_small = max(8, pt - 1)
        self.setStyleSheet(f"""
            QDialog       {{ background: {t['dlg_bg']}; }}
            QLabel        {{ color: {t['fg']}; }}
            {_table_qss(t, pt, gridline=t['border'])}
            {_button_qss(t, pt)}
            {_band_qss(t, pt_small)}
            QLabel#warnBanner {{ color: {t['text_warn']};
                                  border: 1px solid {t['dlg_count_warn']};
                                  border-radius: 4px; padding: 6px 10px; }}
        """)
        self._hint.setStyleSheet(f"color: {t['fg_dim']}; font-size: {pt_small}pt;")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("dlgHeaderBand")
        header_lay = QVBoxLayout(header)
        header_lay.setContentsMargins(12, 10, 12, 10)
        header_lay.setSpacing(8)

        if self._mw.glossary_load_warnings:
            warn_lbl = QLabel(
                "This file needed automatic correction while loading:\n"
                + "\n".join(f"• {w}" for w in self._mw.glossary_load_warnings)
                + "\n\nSaving will rewrite it in canonical format (comma-"
                  "separated, UTF-8, term/translation/note header)."
            )
            warn_lbl.setObjectName("warnBanner")
            warn_lbl.setWordWrap(True)
            header_lay.addWidget(warn_lbl)

        self._hint = QLabel(
            "Terms here guide AI translation for this file's Claude engines "
            "only. Matching is case-insensitive, whole word/phrase."
        )
        self._hint.setWordWrap(True)
        header_lay.addWidget(self._hint)
        layout.addWidget(header)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Term", "Translation", "Note"])
        self.table.setFont(self.app_font)
        header_view = self.table.horizontalHeader()
        header_view.setFont(self.app_font)
        header_view.setSectionResizeMode(0, QHeaderView.Interactive)
        header_view.setSectionResizeMode(1, QHeaderView.Interactive)
        header_view.setStretchLastSection(True)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(1, 260)
        self.table.verticalHeader().setVisible(False)
        # Match the main entry table's font-driven row height (see
        # MainWindow._apply_app_font) so row height stays legible at any
        # configured UI font size, not just Qt's built-in default.
        row_h = max(24, self.app_font.pointSize() * 2 + 8)
        self.table.verticalHeader().setDefaultSectionSize(row_h)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.table, 1)

        footer = QFrame()
        footer.setObjectName("dlgFooterBand")
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(12, 9, 12, 9)
        footer_lay.setSpacing(8)
        add_btn = QPushButton("Add Row")
        add_btn.clicked.connect(self._add_row)
        dup_btn = QPushButton("Duplicate Row")
        dup_btn.clicked.connect(self._duplicate_selected_row)
        remove_btn = QPushButton("Remove Selected Row")
        remove_btn.clicked.connect(self._remove_selected_row)
        footer_lay.addWidget(add_btn)
        footer_lay.addWidget(dup_btn)
        footer_lay.addWidget(remove_btn)
        footer_lay.addStretch()
        save_btn = QPushButton("Save")
        save_btn.setProperty("role", "primary")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        footer_lay.addWidget(save_btn)
        footer_lay.addWidget(cancel_btn)
        layout.addWidget(footer)
        # After the footer joins the dialog: setDefault() registers the dialog default only once the button
        # has a QDialog ancestor, and a repeated call does nothing, so there must be no earlier call.
        save_btn.setDefault(True)

    def _load_values(self):
        for entry in self._mw.glossary:
            self._append_row(entry.term, entry.translation, entry.note)

    def _append_row(self, term: str = "", translation: str = "", note: str = ""):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(term))
        self.table.setItem(row, 1, QTableWidgetItem(translation))
        self.table.setItem(row, 2, QTableWidgetItem(note))

    def _add_row(self):
        self._append_row()
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)

    def _duplicate_selected_row(self):
        row = self.table.currentRow()
        if row < 0:
            return
        term_item  = self.table.item(row, 0)
        trans_item = self.table.item(row, 1)
        note_item  = self.table.item(row, 2)
        term        = term_item.text()  if term_item  else ""
        translation = trans_item.text() if trans_item else ""
        note        = note_item.text()  if note_item  else ""
        self.table.insertRow(row + 1)
        self.table.setItem(row + 1, 0, QTableWidgetItem(term))
        self.table.setItem(row + 1, 1, QTableWidgetItem(translation))
        self.table.setItem(row + 1, 2, QTableWidgetItem(note))
        self.table.setCurrentCell(row + 1, 0)

    def _remove_selected_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _save(self):
        entries: List[GlossaryEntry] = []
        for row in range(self.table.rowCount()):
            term_item  = self.table.item(row, 0)
            trans_item = self.table.item(row, 1)
            note_item  = self.table.item(row, 2)
            term        = term_item.text().strip()  if term_item  else ""
            translation = trans_item.text().strip() if trans_item else ""
            note        = note_item.text().strip()  if note_item  else ""
            if not term or not translation:
                QMessageBox.warning(
                    self, "Incomplete Row",
                    f"Row {row + 1} needs both a Term and a Translation."
                )
                return
            entries.append(GlossaryEntry(term=term, translation=translation, note=note))
        try:
            write_glossary(self._mw.glossary_path, entries)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save glossary:\n{e}")
            return
        self._mw.glossary, self._mw.glossary_load_warnings = parse_glossary(self._mw.glossary_path)
        self.accept()


# ════════════════════════════════════════════════════════════════
#  FLOW LAYOUT
# ════════════════════════════════════════════════════════════════

class FlowLayout(QLayout):
    """Left-to-right layout that wraps items onto additional rows once the
    current row runs out of horizontal space, instead of squeezing everything
    into one row. Used by MergeConflictDialog's toolbar so its button groups
    never truncate regardless of configured font size or screen width.
    Computed once per dialog open (see _fit_to_content) -- nothing in this
    dialog re-triggers a resize after construction, so live re-flow on a
    later manual resize is unused but comes for free via Qt's normal
    height-for-width contract.
    """

    def __init__(self, parent: Optional[QWidget] = None, margin: int = 0, spacing: int = 6):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._spacing = spacing
        self._items: List[QLayoutItem] = []

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QSize(left + right, top + bottom)

    def unwrapped_width(self) -> int:
        """Total width needed if every item were placed on a single row --
        used by MergeConflictDialog._wanted_width() to pick a target width
        before the actual wrap happens."""
        if not self._items:
            return 0
        left, top, right, bottom = self.getContentsMargins()
        # +1 offsets QRect.right()'s inclusive (x + width - 1) convention,
        # which _do_layout's wrap check compares against -- without it, a
        # widget resized to exactly this width wraps one row too early
        # (confirmed empirically).
        return (sum(item.sizeHint().width() for item in self._items)
                + self._spacing * (len(self._items) - 1) + left + right + 1)

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(left, top, -right, -bottom)
        x, y = effective.x(), effective.y()
        line_height = 0
        for item in self._items:
            next_x = x + item.sizeHint().width() + self._spacing
            if next_x - self._spacing > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + self._spacing
                next_x = x + item.sizeHint().width() + self._spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y() + bottom


# ════════════════════════════════════════════════════════════════
#  MERGE CONFLICT RESOLUTION DIALOG
# ════════════════════════════════════════════════════════════════

def _rgba_css(hex_color: str, alpha_fraction: float) -> str:
    """A '#RRGGBB' theme colour as a CSS rgba(...) string."""
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha_fraction})"


def _merge_tint_qss(t: dict, is_dark: bool, pt_small: int) -> str:
    """The Merge category colours: buttons with a 'tint' property (ok / warn / bad) and their
    hover, focus and disabled states, a stronger fill for the button of a row's current choice
    (current="true", MergeCompareDialog), and the category captions (mergeCaption). Shared by
    MergeConflictDialog's toolbar and MergeCompareDialog's resolution buttons. The [current] rule
    sits before :disabled, which has the same specificity, so a disabled button looks disabled."""
    # (fill, border, hover-fill) alpha per category, tuned per theme like the row tints.
    alphas = ({"ok": (0.16, 0.55, 0.30), "warn": (0.16, 0.55, 0.30), "bad": (0.18, 0.60, 0.32)}
              if is_dark else
              {"ok": (0.14, 0.55, 0.26), "warn": (0.18, 0.60, 0.30), "bad": (0.12, 0.55, 0.24)})
    tint_color = {"ok": t["dlg_count_ok"], "warn": t["dlg_count_warn"],
                  "bad": t["dlg_count_concern"]}
    qss = ""
    for kind, (fill, border, hover) in alphas.items():
        base = tint_color[kind]
        qss += f"""
        QPushButton[tint="{kind}"] {{ background: {_rgba_css(base, fill)};
                                      border: 1px solid {_rgba_css(base, border)}; }}
        QPushButton[tint="{kind}"]:hover {{ background: {_rgba_css(base, hover)}; }}
        QPushButton[tint="{kind}"][current="true"] {{ background: {_rgba_css(base, hover)}; }}
        QPushButton[tint="{kind}"]:focus {{ border: 1px solid {t['accent']}; }}
        QPushButton[tint="{kind}"]:disabled {{ background: {t['dlg_btn_dis']};
                                               color: {t['dlg_btn_dis_fg']};
                                               border: 1px solid {t['border']}; }}
        QLabel[mergeCaption="{kind}"] {{ color: {t['text_' + kind]};
                                         font-size: {pt_small}pt; }}
        """
    return qss


class MergeConflictDialog(QDialog):
    """Batch resolution table for Merge-from-File additions, conflicts, and
    deletions.

    Rows are additions (present only in the incoming file) followed by
    conflicts (differing text on both sides), followed by deletions
    (present only in the open file). Each row's Resolution widget defaults
    per the merge design spec: additions default to Accept;
    conflicts default to whichever side has the newer modify_date
    (ties/unparseable -> "Keep open"); deletions always default to "Keep".
    Row backgrounds are tinted live to reflect each row's current
    resolution state (see `_recolor_row`).
    """

    COL_SOURCE     = 0
    COL_TYPE       = 1
    COL_OPEN_VALUE = 2
    COL_INC_VALUE  = 3
    COL_RESOLUTION = 4

    # Row background tint alpha (0-255) per resolution-state theme color key,
    # tuned separately per theme so the tint reads at similar visual weight
    # against each theme's base surface color.
    _TINT_ALPHA_DARK  = {"dlg_count_ok": 51, "dlg_count_warn": 51, "dlg_count_concern": 56}
    _TINT_ALPHA_LIGHT = {"dlg_count_ok": 36, "dlg_count_warn": 41, "dlg_count_concern": 36}

    # Faint versions used for conflict/deletion rows still at their safe
    # ("Keep open" / "Keep") default -- always-visible category flagging,
    # roughly a third of the full-strength alpha above. Additions have no
    # faint tier: a rejected addition means nothing happens to that row at
    # all, so it stays untinted rather than faintly flagged.
    _TINT_ALPHA_DARK_FAINT  = {"dlg_count_warn": 17, "dlg_count_concern": 19}
    _TINT_ALPHA_LIGHT_FAINT = {"dlg_count_warn": 14, "dlg_count_concern": 12}

    def __init__(
        self,
        additions: List[StringEntry],
        conflicts: List[Tuple[StringEntry, StringEntry]],
        deletions: List[StringEntry],
        parent=None,
    ):
        super().__init__(parent)
        self._mw = parent
        self._additions = additions
        self._conflicts = conflicts
        self._deletions = deletions
        self._addition_combos: List[QComboBox] = []
        self._conflict_combos: List[QComboBox] = []
        self._deletion_combos: List[QComboBox] = []
        self._row_kind: List[str] = []   # "addition" | "conflict" | "deletion", per row
        # The choices as they stood when the dialog closed -- filled by done(), see there.
        self._accepted_additions:  List[StringEntry] = []
        self._resolved_conflicts:  List[StringEntry] = []
        self._deletions_to_remove: List[StringEntry] = []

        # Column widths (Type, Resolution only -- Source/Open/Incoming are Stretch, same
        # convention as the main table's own text columns) -- debounced the same way as
        # MainWindow._col_save_timer.
        self._col_save_timer = QTimer(self)
        self._col_save_timer.setSingleShot(True)
        self._col_save_timer.setInterval(400)
        self._col_save_timer.timeout.connect(self._persist_column_widths)

        # Resolve the active theme once up front — needed by _recolor_row,
        # which fires while rows are being built in _load_values(), before
        # _apply_style() would otherwise have run.
        theme_name = "dark"
        if parent is not None and hasattr(parent, "settings"):
            theme_name = parent.settings.get("theme", "dark")
        self._theme   = THEMES.get(theme_name, THEMES["dark"])
        self._is_dark = (theme_name != "light")
        self._pt = (parent.settings.get_font().pointSize()
                    if parent is not None and hasattr(parent, "settings") else 0) or 10

        self.setWindowTitle("Resolve Merge Conflicts")
        self.setWindowFlags(self.windowFlags()
                             | Qt.WindowMaximizeButtonHint
                             | Qt.WindowMinimizeButtonHint)
        self.setMinimumSize(920, 480)
        self.setModal(True)
        # Closing this dialog (Accept or Cancel) must actually destroy it -- otherwise it
        # stays alive as a hidden child of MainWindow forever (parent=self), and every one of
        # its per-row Resolution combos (as many as the incoming file has rows) keeps showing
        # up in QApplication.allWidgets(), which MainWindow._apply_app_font() walks explicitly
        # and MainWindow._apply_theme()'s stylesheet cascade reaches implicitly on every later
        # font or theme change. A large merge left uncleared turned a routine settings change
        # into a multi-second freeze. QDialog.exec() deletes the dialog, combos included, before
        # it returns, so done() keeps the choices that MainWindow._merge_from_file() reads after.
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._build_ui()
        self._load_values()
        self._apply_style()
        self._fit_to_content()
        # Defensive: with the default registered (see _build_ui) the dialog already starts on Apply &
        # Close. Initial focus in the table keeps Enter on open applying even if that registration were
        # ever broken (the autoDefault Select All button would otherwise take focus and become the
        # default). It also starts keyboard focus in the table.
        self._table.setTabKeyNavigation(False)   # the table is read-only; Tab must reach the toolbar and footer
        self._table.setFocus()

    # Cap on a Stretch text column's contribution to _table_natural_width, matching the main
    # table's own Source/Translated default width (Settings.DEFAULTS["column_widths"]). Without
    # it, a single long translation could size the dialog to (near) the full screen; a truncated
    # cell still shows its full text via the existing tooltip (see _item()).
    _STRETCH_COL_WIDTH_CAP = 280

    def _table_natural_width(self) -> int:
        """Width the table needs to show every column's content, capping the three Stretch text
        columns (Source, Open value, Incoming value) so one long string can't blow up the dialog.
        Stretch columns are sized by Qt to the view rather than to their contents, so the contents
        are measured directly here instead of being read back from the header."""
        table = self._table
        fm, header_fm = table.fontMetrics(), table.horizontalHeader().fontMetrics()
        stretch_cols = (self.COL_SOURCE, self.COL_OPEN_VALUE, self.COL_INC_VALUE)
        total = table.verticalHeader().sizeHint().width() + 24   # row numbers + scrollbar allowance
        for col in range(table.columnCount()):
            widest = header_fm.horizontalAdvance(table.horizontalHeaderItem(col).text())
            for row in range(table.rowCount()):
                item = table.item(row, col)
                if item is not None:
                    widest = max(widest, fm.horizontalAdvance(item.text()))
                cell_widget = table.cellWidget(row, col)
                if cell_widget is not None:
                    widest = max(widest, cell_widget.sizeHint().width())
            if col in stretch_cols:
                widest = min(widest, self._STRETCH_COL_WIDTH_CAP)
            total += widest + 24                                   # cell padding
        return total

    def _wanted_width(self) -> int:
        """The wider of the toolbar (unwrapped, plus the header band's side margins) and the
        table's natural width -- before the screen cap. With short button labels the toolbar
        alone is much narrower than it used to be, so the table decides for long strings."""
        margins = self._header_band.layout().contentsMargins()
        toolbar_w = self._toolbar.unwrapped_width() + margins.left() + margins.right()
        return max(toolbar_w, self._table_natural_width())

    def _fit_to_content(self):
        """Resize once, right after the toolbar and table are first built. Width-first: pick the
        wanted width (see _wanted_width), capped to the screen, then ask the layout how tall that
        makes the dialog via heightForWidth() -- clamping width and height independently doesn't
        work once height depends on width, which it does while the toolbar can wrap. Only called
        from __init__; nothing later changes the toolbar's or table's shape.
        """
        wanted_w = self._wanted_width()

        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            margin = 60
            max_w = max(self.minimumWidth(), avail.width() - margin)
            max_h = max(self.minimumHeight(), avail.height() - margin)
            target_w = max(self.minimumWidth(), min(wanted_w, max_w))
            target_h = max(self.minimumHeight(), min(self.layout().heightForWidth(target_w), max_h))
        else:
            target_w = max(self.minimumWidth(), wanted_w)
            target_h = max(self.minimumHeight(), self.layout().heightForWidth(target_w))

        self.resize(target_w, target_h)

    # ── Public API ────────────────────────────────────────────

    def done(self, result: int):
        """Every way of closing (Apply & Close, Cancel, Escape, the title bar) ends here. Read
        the choices out of the combos now: QDialog.exec() deletes this WA_DeleteOnClose dialog,
        combos included, before it returns to the caller that asks for them."""
        self._accepted_additions = [
            entry for entry, combo in zip(self._additions, self._addition_combos)
            if combo.currentText() == "Accept"]
        self._resolved_conflicts = [
            incoming_entry if combo.currentText() == "Keep incoming" else open_entry
            for (open_entry, incoming_entry), combo in zip(self._conflicts, self._conflict_combos)]
        self._deletions_to_remove = [
            entry for entry, combo in zip(self._deletions, self._deletion_combos)
            if combo.currentText() == "Delete"]
        super().done(result)

    def accepted_additions(self) -> List[StringEntry]:
        """The addition candidates set to "Accept" when the dialog closed."""
        return list(self._accepted_additions)

    def resolved_conflicts(self) -> List[StringEntry]:
        """Per conflict (same order as the input list), the entry chosen when the dialog closed."""
        return list(self._resolved_conflicts)

    def deletions_to_remove(self) -> List[StringEntry]:
        """The deletion candidates set to "Delete" when the dialog closed."""
        return list(self._deletions_to_remove)

    def row_count(self) -> int:
        return len(self._row_kind)

    def row_info(self, row: int) -> MergeRowInfo:
        """The entries behind table row *row* and its Resolution combo. Rows are additions, then
        conflicts, then deletions (see _load_values), so a row maps to its list by offset."""
        kind  = self._row_kind[row]
        combo = self._table.cellWidget(row, self.COL_RESOLUTION)
        index = row
        if kind == "addition":
            return MergeRowInfo(kind, None, self._additions[index], combo)
        index -= len(self._additions)
        if kind == "conflict":
            open_entry, incoming_entry = self._conflicts[index]
            return MergeRowInfo(kind, open_entry, incoming_entry, combo)
        index -= len(self._conflicts)
        return MergeRowInfo(kind, self._deletions[index], None, combo)

    def is_auto_resolving(self) -> bool:
        return self._auto_chk.isChecked()

    def show_row(self, row: int):
        """Select *row* alone and scroll it into view. MergeCompareDialog keeps the table on the
        row it shows, so Close lands where the review stopped."""
        # Not selectRow(): under ExtendedSelection, with no originating mouse/key event it derives
        # its selection command from QGuiApplication.keyboardModifiers() -- Ctrl/Shift held while
        # the pop-up's (user-rebindable) Back/Forward keys fire would ADD to the selection instead
        # of replacing it, accumulating rows a later toolbar bulk action would then act on.
        index = self._table.model().index(row, self.COL_SOURCE)
        self._table.selectionModel().setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        self._table.selectionModel().select(
            index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self._table.scrollToItem(self._table.item(row, self.COL_SOURCE))

    def theme_and_font(self) -> Tuple[dict, bool, int]:
        """The theme dict, whether it is the dark one, and the UI font size in pt."""
        return self._theme, self._is_dark, self._pt

    def shortcuts(self) -> dict:
        """The configured shortcuts merged over SHORTCUT_DEFAULTS."""
        merged = dict(SHORTCUT_DEFAULTS)
        if self._mw is not None and hasattr(self._mw, "settings"):
            merged.update(self._mw.settings.get("shortcuts", {}) or {})
        return merged

    # ── UI construction ───────────────────────────────────────

    @staticmethod
    def _item(text: str) -> QTableWidgetItem:
        """A QTableWidgetItem whose tooltip is its own full text, so text
        elided/truncated by column width is still readable on hover."""
        it = QTableWidgetItem(text)
        it.setToolTip(text)
        return it

    def _apply_style(self):
        t = self._theme
        pt_small = max(8, self._pt - 1)
        self.setStyleSheet(f"""
            QDialog       {{ background: {t['dlg_bg']}; }}
            QLabel        {{ color: {t['fg']}; }}
            QLabel[mergeCaption="neutral"] {{ color: {t['header_fg']}; font-size: {pt_small}pt; }}
            QCheckBox     {{ color: {t['fg']}; }}
            {_prominent_checkbox_qss(t)}
            {_table_qss(t, self._pt, gridline=t['border'])}
            QComboBox     {{ background: {t['bg4']}; color: {t['fg']};
                              border: 1px solid {t['border2']}; border-radius: 3px;
                              padding: 3px 6px; }}
            {_combobox_qss(t, self._pt)}
            {_button_qss(t, self._pt)}
            {_field_state_qss(t)}
            {_band_qss(t, pt_small)}
            QFrame#mergeCol, QFrame#mergeColFirst {{ background: transparent; border: none; }}
            QFrame#mergeCol {{ border-left: 1px solid {t['bar_border']}; }}
            {_merge_tint_qss(t, self._is_dark, pt_small)}
        """)

    def _make_button(self, attr: str, text: str, full_label: str, handler,
                     tint: Optional[str]) -> QPushButton:
        """A toolbar button: short *text* (the caption above it names the category), its previous
        full wording as tooltip and accessible name so the short label stays unambiguous, and a
        'tint' property that _apply_style() turns into the category colour."""
        btn = QPushButton(text)
        btn.setToolTip(full_label)
        btn.setAccessibleName(full_label)
        if tint:
            btn.setProperty("tint", tint)
        btn.clicked.connect(handler)
        setattr(self, attr, btn)
        return btn

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        total = len(self._additions) + len(self._conflicts) + len(self._deletions)

        # Header band: the toolbar only. Four columns (caption over a button row) in a
        # FlowLayout so they wrap if the dialog is made narrower than the toolbar.
        self._header_band = QFrame()
        self._header_band.setObjectName("dlgHeaderBand")
        header_lay = QVBoxLayout(self._header_band)
        header_lay.setContentsMargins(12, 6, 12, 6)
        toolbar = FlowLayout(spacing=0)
        self._toolbar = toolbar  # exposed for _wanted_width()'s call to unwrapped_width()

        select_all = self._make_button("_btn_select_all", "Select All", "Select All",
                                       self._select_all, None)
        columns = [
            ("mergeColFirst", "Selection", "neutral", [select_all]),
            ("mergeCol", "Additions", "ok", [
                self._make_button("_btn_select_additions", "Select", "Select Additions",
                                  lambda: self._select_kind("addition"), "ok"),
                self._make_button("_btn_accept_selected", "Accept", "Accept Selected",
                                  self._accept_selected, "ok"),
                self._make_button("_btn_reject_selected", "Reject", "Reject Selected",
                                  self._reject_selected, "ok")]),
            ("mergeCol", "Conflicts", "warn", [
                self._make_button("_btn_select_conflicts", "Select", "Select Conflicts",
                                  lambda: self._select_kind("conflict"), "warn"),
                self._make_button("_btn_keep_open", "Keep open", "Keep Open",
                                  self._keep_open_selected, "warn"),
                self._make_button("_btn_keep_incoming", "Keep incoming", "Keep Incoming",
                                  self._keep_incoming_selected, "warn")]),
            ("mergeCol", "Deletions", "bad", [
                self._make_button("_btn_select_deletions", "Select", "Select Deletions",
                                  lambda: self._select_kind("deletion"), "bad"),
                self._make_button("_btn_keep_selected", "Keep", "Keep Selected",
                                  self._keep_deletion_selected, "bad"),
                self._make_button("_btn_delete_selected", "Delete", "Delete Selected",
                                  self._delete_selected, "bad")]),
        ]
        for object_name, caption, kind, buttons in columns:
            column = QFrame()
            column.setObjectName(object_name)
            col_lay = QVBoxLayout(column)
            col_lay.setContentsMargins(0 if object_name == "mergeColFirst" else 12, 4, 12, 4)
            col_lay.setSpacing(3)
            cap = QLabel(caption)
            cap.setProperty("mergeCaption", kind)
            col_lay.addWidget(cap)
            row = QHBoxLayout()
            row.setSpacing(4)
            for btn in buttons:
                row.addWidget(btn)
            col_lay.addLayout(row)
            toolbar.addWidget(column)

        self._btn_select_additions.setEnabled(bool(self._additions))
        self._btn_select_conflicts.setEnabled(bool(self._conflicts))
        self._btn_select_deletions.setEnabled(bool(self._deletions))
        self._btn_accept_selected.setEnabled(bool(self._additions))
        self._btn_reject_selected.setEnabled(bool(self._additions))
        self._btn_keep_open.setEnabled(bool(self._conflicts))
        self._btn_keep_incoming.setEnabled(bool(self._conflicts))
        self._btn_delete_selected.setEnabled(bool(self._deletions))
        self._btn_keep_selected.setEnabled(bool(self._deletions))

        header_lay.addLayout(toolbar)
        lay.addWidget(self._header_band)

        self._table = QTableWidget(total, 5)
        self._table.setHorizontalHeaderLabels(
            ["Source text", "Type", "Open file value", "Incoming file value", "Resolution"]
        )
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(self.COL_SOURCE, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(self.COL_OPEN_VALUE, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(self.COL_INC_VALUE, QHeaderView.Stretch)
        # sectionResized fires for every pixel while dragging; debounce before saving (Type and
        # Resolution are the only Interactive columns -- see _persist_column_widths).
        self._table.horizontalHeader().sectionResized.connect(self._on_column_resized)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(True)
        self._table.setAlternatingRowColors(True)
        # A double-click on a text cell or a row number compares that row. The Resolution cell is
        # covered by its combo, so a double-click there still reaches the combo.
        self._table.cellDoubleClicked.connect(lambda row, _col: self._open_compare(row))
        self._table.verticalHeader().sectionDoubleClicked.connect(self._open_compare)
        lay.addWidget(self._table, 1)

        # Footer band: the auto-resolve mode on the left, the actions on the right.
        footer = QFrame()
        footer.setObjectName("dlgFooterBand")
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(12, 9, 12, 9)
        footer_lay.setSpacing(8)
        self._auto_chk = QCheckBox("Auto-resolve all conflicts using newest modify date")
        self._auto_chk.setProperty("filterChk", True)
        self._auto_chk.setToolTip(
            "When checked, resolves every conflict automatically: the side with the "
            "newer Modify Date wins. Ties, or a missing/unparseable date on either "
            "side, default to Keep Open. An untranslated side (translation identical "
            "to its source text) always loses to a genuinely translated side, "
            "regardless of date. Manual selection is disabled while this is checked."
        )
        self._auto_chk.toggled.connect(self._on_auto_toggled)
        footer_lay.addWidget(self._auto_chk)
        footer_lay.addStretch()
        # "&&" is a literal ampersand in a Qt button label; a lone "&" marks a mnemonic.
        self._btn_apply = QPushButton("Apply && Close")
        self._btn_apply.setProperty("role", "primary")
        cancel_btn = QPushButton("Cancel")
        self._btn_apply.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        footer_lay.addWidget(self._btn_apply)
        footer_lay.addWidget(cancel_btn)
        lay.addWidget(footer)
        # After the footer joins the dialog: setDefault() only registers the dialog's main default
        # once the button has a QDialog ancestor, and that registration is what gives the default
        # back to Apply & Close when a focused toolbar button loses focus.
        self._btn_apply.setDefault(True)

        # Status bar: the bottom-most strip, like the main window's info bar.
        status = QFrame()
        status.setObjectName("dlgStatusBar")
        status_lay = QHBoxLayout(status)
        status_lay.setContentsMargins(12, 4, 12, 4)
        status_lay.addWidget(QLabel(
            f"{len(self._additions)} addition(s), {len(self._conflicts)} conflict(s), "
            f"{len(self._deletions)} deletion(s) need your review ({total} row(s) total). "
            f"Double-click a row to compare."
        ))
        lay.addWidget(status)

    def _load_values(self):
        row = 0

        for entry in self._additions:
            self._table.setItem(row, self.COL_SOURCE, self._item(entry.name))
            self._table.setItem(row, self.COL_TYPE, QTableWidgetItem("+ Addition"))
            self._table.setItem(row, self.COL_OPEN_VALUE, self._item(""))
            self._table.setItem(row, self.COL_INC_VALUE, self._item(entry.text))

            combo = _WidePopupComboBox()
            combo.addItems(["Accept", "Reject"])
            combo.currentTextChanged.connect(lambda _text, r=row: self._recolor_row(r))
            self._table.setCellWidget(row, self.COL_RESOLUTION, combo)
            self._addition_combos.append(combo)
            self._row_kind.append("addition")
            row += 1

        for open_entry, incoming_entry in self._conflicts:
            self._table.setItem(row, self.COL_SOURCE, self._item(open_entry.name))
            self._table.setItem(row, self.COL_TYPE, QTableWidgetItem("⇄ Conflict"))
            self._table.setItem(row, self.COL_OPEN_VALUE, self._item(open_entry.text))
            self._table.setItem(row, self.COL_INC_VALUE, self._item(incoming_entry.text))

            combo = _WidePopupComboBox()
            combo.addItems(["Keep open", "Keep incoming"])
            default_winner = _pick_newer_entry(open_entry, incoming_entry)
            combo.setCurrentText("Keep incoming" if default_winner is incoming_entry else "Keep open")
            combo.currentTextChanged.connect(lambda _text, r=row: self._recolor_row(r))
            self._table.setCellWidget(row, self.COL_RESOLUTION, combo)
            self._conflict_combos.append(combo)
            self._row_kind.append("conflict")
            row += 1

        for entry in self._deletions:
            self._table.setItem(row, self.COL_SOURCE, self._item(entry.name))
            self._table.setItem(row, self.COL_TYPE, QTableWidgetItem("× Deletion"))
            self._table.setItem(row, self.COL_OPEN_VALUE, self._item(entry.text))
            self._table.setItem(row, self.COL_INC_VALUE, self._item(""))

            combo = _WidePopupComboBox()
            combo.addItems(["Keep", "Delete"])
            combo.setCurrentText("Keep")
            combo.currentTextChanged.connect(lambda _text, r=row: self._recolor_row(r))
            self._table.setCellWidget(row, self.COL_RESOLUTION, combo)
            self._deletion_combos.append(combo)
            self._row_kind.append("deletion")
            row += 1

        # A blank item under each cell widget so _recolor_row can tint the Resolution column too.
        for r in range(row):
            self._table.setItem(r, self.COL_RESOLUTION, QTableWidgetItem(""))
        self._table.resizeColumnsToContents()
        self._apply_saved_column_widths()
        for r in range(row):
            self._recolor_row(r)

    # ── Column widths ────────────────────────────────────────
    # Only Type and Resolution are Interactive (Source/Open/Incoming are Stretch, same
    # convention as the main table's own text columns -- see _table_natural_width), so
    # those are the only two whose width is worth remembering across sessions.

    _PERSISTED_COLUMNS = ("COL_TYPE", "COL_RESOLUTION")

    def _apply_saved_column_widths(self):
        """Override resizeColumnsToContents()'s auto-sized Type/Resolution widths with
        whatever the user last dragged them to, if anything was ever saved."""
        if self._mw is None or not hasattr(self._mw, "settings"):
            return
        saved = self._mw.settings.get("merge", {}).get("column_widths", {})
        for attr in self._PERSISTED_COLUMNS:
            col = getattr(self, attr)
            w = saved.get(str(col))
            if w:
                self._table.setColumnWidth(col, int(w))

    def _on_column_resized(self, logical_index: int, old_size: int, new_size: int):
        """Called on every sectionResized signal -- starts the debounce timer, same pattern
        as MainWindow._on_column_resized."""
        if not self.isVisible():   # ignore programmatic resizes during __init__, before show()
            return
        self._col_save_timer.start()

    def _persist_column_widths(self):
        """Read Type's and Resolution's current widths and write them to settings."""
        if self._mw is None or not hasattr(self._mw, "settings"):
            return
        header = self._table.horizontalHeader()
        widths = {
            str(getattr(self, attr)): header.sectionSize(getattr(self, attr))
            for attr in self._PERSISTED_COLUMNS
        }
        merge_cfg = dict(self._mw.settings.get("merge", {}))
        merge_cfg["column_widths"] = widths
        self._mw.settings.set("merge", merge_cfg)
        self._mw.settings.save()

    # ── Row coloring ──────────────────────────────────────────

    def _recolor_row(self, row: int):
        """Tint row *row* to reflect its current resolution state. Called
        after every checkbox/combo change and after every bulk-toolbar
        action, so color always matches what will actually happen on
        Apply. The Resolution column is tinted too: its blank item paints
        the background behind the (transparent) checkbox, while a combo
        box keeps its own opaque background.

        Conflict and deletion rows are always tinted -- faint for the
        non-destructive choice ("Keep open" / "Keep"), full-strength for the
        choice that overwrites/removes existing data ("Keep incoming" /
        "Delete") -- regardless of which one a given row started on (a
        conflict's own preset default can be either one; the tint tracks
        the *current* choice, not "is this row still on its initial
        value"). This way every conflict and deletion stays visually
        flagged, not just the ones the user has touched. Addition rows are
        unchanged: full tint when Accept is checked, no tint when rejected
        (nothing happens to that row)."""
        kind   = self._row_kind[row]
        widget = self._table.cellWidget(row, self.COL_RESOLUTION)

        color_key = None
        faint = False
        if kind == "addition" and widget.currentText() == "Accept":
            color_key = "dlg_count_ok"
        elif kind == "conflict":
            color_key = "dlg_count_warn"
            faint = widget.currentText() != "Keep incoming"
        elif kind == "deletion":
            color_key = "dlg_count_concern"
            faint = widget.currentText() != "Delete"

        if color_key:
            if faint:
                alpha_map = self._TINT_ALPHA_DARK_FAINT if self._is_dark else self._TINT_ALPHA_LIGHT_FAINT
            else:
                alpha_map = self._TINT_ALPHA_DARK if self._is_dark else self._TINT_ALPHA_LIGHT
            color = QColor(self._theme[color_key])
            color.setAlpha(alpha_map[color_key])
            brush = QBrush(color)
        else:
            brush = QBrush()  # clears any custom background

        for col in (self.COL_SOURCE, self.COL_TYPE, self.COL_OPEN_VALUE, self.COL_INC_VALUE,
                    self.COL_RESOLUTION):
            item = self._table.item(row, col)
            if item is not None:
                item.setBackground(brush)

    # ── Selection ─────────────────────────────────────────────

    def _selected_rows(self) -> List[int]:
        return sorted({idx.row() for idx in self._table.selectionModel().selectedRows()})

    def _select_all(self):
        self._table.selectAll()

    def _select_kind(self, kind: str):
        rows = [row for row, row_kind in enumerate(self._row_kind) if row_kind == kind]
        self._table.clearSelection()
        if not rows:
            return
        last_col = self._table.columnCount() - 1
        selection = QItemSelection()
        for row in rows:
            left = self._table.model().index(row, 0)
            right = self._table.model().index(row, last_col)
            selection.select(left, right)
        self._table.selectionModel().select(
            selection, QItemSelectionModel.Select | QItemSelectionModel.Rows
        )

    def _open_compare(self, row: int):
        """Compare *row* in MergeCompareDialog. Modal; it writes its choices straight into this
        table's combos, so nothing is read back after it closes."""
        if 0 <= row < self.row_count():
            MergeCompareDialog(self, row).exec()

    # ── Bulk resolution actions ──────────────────────────────

    def _accept_selected(self):
        for row in self._selected_rows():
            if self._row_kind[row] == "addition":
                self._table.cellWidget(row, self.COL_RESOLUTION).setCurrentText("Accept")
                self._recolor_row(row)

    def _reject_selected(self):
        for row in self._selected_rows():
            if self._row_kind[row] == "addition":
                self._table.cellWidget(row, self.COL_RESOLUTION).setCurrentText("Reject")
                self._recolor_row(row)

    def _keep_open_selected(self):
        for row in self._selected_rows():
            if self._row_kind[row] == "conflict":
                self._table.cellWidget(row, self.COL_RESOLUTION).setCurrentText("Keep open")
                self._recolor_row(row)

    def _keep_incoming_selected(self):
        for row in self._selected_rows():
            if self._row_kind[row] == "conflict":
                self._table.cellWidget(row, self.COL_RESOLUTION).setCurrentText("Keep incoming")
                self._recolor_row(row)

    def _delete_selected(self):
        for row in self._selected_rows():
            if self._row_kind[row] == "deletion":
                self._table.cellWidget(row, self.COL_RESOLUTION).setCurrentText("Delete")
                self._recolor_row(row)

    def _keep_deletion_selected(self):
        for row in self._selected_rows():
            if self._row_kind[row] == "deletion":
                self._table.cellWidget(row, self.COL_RESOLUTION).setCurrentText("Keep")
                self._recolor_row(row)

    # ── Behaviour ─────────────────────────────────────────────

    def _on_auto_toggled(self, checked: bool):
        for (open_entry, incoming_entry), combo in zip(self._conflicts, self._conflict_combos):
            combo.setEnabled(not checked)
            if checked:
                default_winner = _pick_newer_entry(open_entry, incoming_entry)
                combo.setCurrentText("Keep incoming" if default_winner is incoming_entry else "Keep open")
        # Deletion rows always remain manual — no date-based signal exists for them.


class MergeCompareDialog(QDialog):
    """One MergeConflictDialog row side by side: source, open and incoming text (read-only,
    wrapped, changed words tinted on a conflict), both sides' metadata, and the row's two
    resolution choices. Keeps no state of its own: a choice goes straight into the Merge table's
    Resolution combo, whose own signal re-tints the row, and the dialog moves to the next row."""

    _KIND_LABEL = {"addition": "+ Addition", "conflict": "⇄ Conflict", "deletion": "× Deletion"}
    _KIND_TINT  = {"addition": "ok", "conflict": "warn", "deletion": "bad"}
    # The combo's own items, so setCurrentText() takes a button's label as it is.
    _CHOICES = {"addition": ("Accept", "Reject"), "conflict": ("Keep open", "Keep incoming"),
                "deletion": ("Keep", "Delete")}
    _CHOICE_KEYS = ("Alt+1", "Alt+2")
    _META_FIELDS = ("Translator", "Status", "Modified", "Length")
    _DIFF_TINT_ALPHA = 0.35
    _PANE_LINES = 4

    def __init__(self, merge_dlg: "MergeConflictDialog", row: int):
        super().__init__(merge_dlg)
        self._merge = merge_dlg
        self._row = row
        self._theme, self._is_dark, self._pt = merge_dlg.theme_and_font()
        self._shortcuts = merge_dlg.shortcuts()
        self._panes: List[QTextEdit] = []
        self._meta_labels: Dict[str, Tuple[QLabel, QLabel]] = {}
        self.setWindowTitle("Compare Merge Row")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self.setMinimumSize(680, 420)
        self.setModal(True)
        # Opened once per double-click: without this every closed one would stay alive as a
        # hidden child of the Merge dialog (see the WA_DeleteOnClose pitfall in CLAUDE.md).
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._build_ui()
        # Styled before the first row is filled: _update_choice_buttons() measures styled buttons.
        self._apply_style()
        self._load_values()
        self._fit_to_content()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_header())
        lay.addWidget(self._build_body(), 1)
        lay.addWidget(self._build_footer())
        # After the footer joins the dialog: setDefault() only registers once the button has a
        # QDialog ancestor (see the "Default-button registration" pitfall in CLAUDE.md).
        self._btn_close.setDefault(True)
        self._bind_keys()

    def _build_header(self) -> QFrame:
        band = QFrame()
        band.setObjectName("dlgHeaderBand")
        row = QHBoxLayout(band)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(6)
        self._kind_lbl = QLabel()
        self._reason_lbl = QLabel()
        self._reason_lbl.setProperty("compareDim", True)
        self._pos_lbl = QLabel()
        self._pos_lbl.setProperty("compareDim", True)
        row.addWidget(self._kind_lbl)
        row.addWidget(self._reason_lbl)
        row.addStretch()
        row.addWidget(self._pos_lbl)
        return band

    def _build_body(self) -> QWidget:
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        for col, caption in enumerate(("Source text", "Open file", "Incoming file")):
            cap = QLabel(caption)
            cap.setProperty("compareCaption", True)
            grid.addWidget(cap, 0, col)
            pane = QTextEdit()
            pane.setReadOnly(True)
            pane.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            pane.setLineWrapMode(QTextEdit.WidgetWidth)
            grid.addWidget(pane, 1, col)
            grid.setColumnStretch(col, 1)
            self._panes.append(pane)
        self._source_pane, self._open_pane, self._incoming_pane = self._panes
        grid.setRowStretch(1, 1)
        for i, field in enumerate(self._META_FIELDS):
            name = QLabel(field)
            name.setProperty("compareDim", True)
            grid.addWidget(name, 2 + i, 0)
            pair = (QLabel(), QLabel())
            grid.addWidget(pair[0], 2 + i, 1)
            grid.addWidget(pair[1], 2 + i, 2)
            self._meta_labels[field] = pair
        return body

    def _build_footer(self) -> QFrame:
        band = QFrame()
        band.setObjectName("dlgFooterBand")
        row = QHBoxLayout(band)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(8)
        self._btn_back = QPushButton("◀")
        self._btn_forward = QPushButton("▶")
        self._btn_back.setToolTip(f"Previous row  [{self._shortcuts['edit_prev']}]")
        self._btn_forward.setToolTip(f"Next row  [{self._shortcuts['edit_next']}]")
        self._btn_back.setAccessibleName("Previous row")
        self._btn_forward.setAccessibleName("Next row")
        self._btn_back.clicked.connect(lambda: self._step(-1))
        self._btn_forward.clicked.connect(lambda: self._step(+1))
        row.addWidget(self._btn_back)
        row.addWidget(self._btn_forward)
        row.addStretch()
        self._choice_btns = (QPushButton(), QPushButton())
        for index, btn in enumerate(self._choice_btns):
            btn.clicked.connect(lambda _checked=False, i=index: self._choose(i))
            row.addWidget(btn)
        self._btn_close = QPushButton("Close")
        self._btn_close.clicked.connect(self.reject)
        row.addWidget(self._btn_close)
        return band

    def _apply_style(self):
        t, pt = self._theme, self._pt
        pt_small = max(8, pt - 1)
        kinds = "".join(f'QLabel[compareKind="{k}"] {{ color: {t["text_" + k]}; }}\n'
                        for k in ("ok", "warn", "bad"))
        self.setStyleSheet(f"""
            QDialog {{ background: {t['dlg_bg']}; }}
            QLabel  {{ color: {t['fg']}; font-size: {pt}pt; }}
            QLabel[compareCaption="true"] {{ color: {t['header_fg']}; font-size: {pt_small}pt; }}
            QLabel[compareDim="true"]     {{ color: {t['fg_dim']}; }}
            QLabel[differs="true"]        {{ color: {t['text_warn']}; }}
            {kinds}
            QTextEdit {{ background: {t['bg2']}; color: {t['fg']};
                         border: 1px solid {t['border2']}; border-radius: 3px;
                         font-size: {pt}pt; }}
            {_button_qss(t, pt)}
            {_field_state_qss(t)}
            {_band_qss(t, pt_small)}
            {_merge_tint_qss(t, self._is_dark, pt_small)}
        """)
        # From the font itself, not pane.fontMetrics(): a stylesheet font only reaches the widget
        # once it is shown (see the setFont() pitfall in CLAUDE.md).
        font = QFont(QApplication.font())
        font.setPointSize(pt)
        line = QFontMetrics(font).lineSpacing()
        for pane in self._panes:
            margin = 2 * pane.frameWidth() + 2 * round(pane.document().documentMargin())
            pane.setMinimumHeight(line * self._PANE_LINES + margin)

    def _fit_to_content(self):
        """Open at the layout's size hint, within the minimum and the screen. Once only: moving
        to another row never resizes, so the buttons stay put and a long text scrolls in its pane."""
        self.ensurePolished()   # polishes the children too, so the hint includes the stylesheet
        hint = self.sizeHint()
        width = max(self.minimumWidth(), hint.width())
        height = max(self.minimumHeight(), hint.height())
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            width = min(width, avail.width() - 60)
            height = min(height, avail.height() - 60)
        self.resize(width, height)

    def showEvent(self, event):
        super().showEvent(event)
        self._focus_current()

    @staticmethod
    def _set_prop(widget: QWidget, name: str, value) -> None:
        """Set a dynamic property and re-polish, so a QSS attribute selector on it applies."""
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _load_values(self):
        self._show_row(self._row)

    def _show_row(self, row: int):
        self._row = row
        self._info = self._merge.row_info(row)
        kind = self._info.kind
        self._kind_lbl.setText(self._KIND_LABEL[kind])
        self._set_prop(self._kind_lbl, "compareKind", self._KIND_TINT[kind])
        reason = merge_row_reason(kind, self._info.open_entry, self._info.incoming_entry)
        if kind == "conflict" and self._merge.is_auto_resolving():
            reason += " · auto-resolved"
        self._reason_lbl.setText(f"· {reason}")
        self._pos_lbl.setText(f"Row {row + 1} of {self._merge.row_count()}")
        self._fill_panes()
        self._fill_metadata()
        self._update_choice_buttons()
        self._btn_back.setEnabled(row > 0)
        self._btn_forward.setEnabled(row < self._merge.row_count() - 1)
        self._merge.show_row(row)
        self._focus_current()

    def _fill_panes(self):
        info, t = self._info, self._theme
        source = (info.open_entry or info.incoming_entry).name
        self._source_pane.setHtml(_pane_html(_escape_pane_text(source)))
        if info.open_entry is not None and info.incoming_entry is not None:
            tint = _blend_hex(t["dlg_count_warn"], t["bg2"], self._DIFF_TINT_ALPHA)
            open_html, incoming_html = merge_diff_html(info.open_entry.text,
                                                       info.incoming_entry.text, tint)
            self._open_pane.setHtml(open_html)
            self._incoming_pane.setHtml(incoming_html)
            return
        sides = ((self._open_pane, info.open_entry, "Not in the open file"),
                 (self._incoming_pane, info.incoming_entry, "Not in the incoming file"))
        for pane, entry, missing in sides:
            if entry is None:
                pane.setHtml(_pane_html(f'<i style="color: {t["fg_dim"]}">{missing}</i>'))
            else:
                pane.setHtml(_pane_html(_escape_pane_text(entry.text)))

    @staticmethod
    def _meta_values(entry: Optional[StringEntry]) -> Tuple[str, str, str, str]:
        if entry is None:
            return ("—", "—", "—", "—")
        return (entry.translator or "—", entry.status or "—", entry.modify_date or "—",
                str(len(entry.text)))

    def _fill_metadata(self):
        info = self._info
        open_values = self._meta_values(info.open_entry)
        incoming_values = self._meta_values(info.incoming_entry)
        both = info.open_entry is not None and info.incoming_entry is not None
        for field, open_value, incoming_value in zip(self._META_FIELDS, open_values, incoming_values):
            differs = both and open_value != incoming_value
            for label, value in zip(self._meta_labels[field], (open_value, incoming_value)):
                label.setText(value)
                self._set_prop(label, "differs", differs)

    def _update_choice_buttons(self):
        info = self._info
        current = info.combo.currentText()
        for btn, label, key in zip(self._choice_btns, self._CHOICES[info.kind], self._CHOICE_KEYS):
            btn.setProperty("tint", self._KIND_TINT[info.kind])
            self._set_prop(btn, "current", "true" if label == current else "false")
            # As wide as the ✓ form, so moving the ✓ never shifts the footer.
            btn.setText(f"✓ {label}")
            btn.setMinimumWidth(btn.sizeHint().width())
            btn.setText(f"✓ {label}" if label == current else label)
            btn.setToolTip(f"{label}  [{key}]")
            btn.setAccessibleName(label)
            # A conflict's combo is disabled while the Merge dialog auto-resolves conflicts.
            btn.setEnabled(info.combo.isEnabled())

    def _focus_current(self):
        """Focus the ✓ button, so Enter keeps the current choice and moves on; with the choice
        buttons disabled (auto-resolve), Forward, or Back on the last row, so Enter never reaches
        Close (which would otherwise let a second Enter -- now on the Merge table behind it --
        trigger Apply & Close)."""
        current = [b for b in self._choice_btns
                   if b.property("current") == "true" and b.isEnabled()]
        if current:
            current[0].setFocus()
        elif self._btn_forward.isEnabled():
            self._btn_forward.setFocus()
        elif self._btn_back.isEnabled():
            self._btn_back.setFocus()
        else:
            self._btn_close.setFocus()

    def _choose(self, index: int):
        """Write choice *index* into the row's combo (its own signal re-tints the row), then show
        the next row; on the last row, stay and move the ✓."""
        if not self._choice_btns[index].isEnabled():
            return
        self._info.combo.setCurrentText(self._CHOICES[self._info.kind][index])
        if self._row < self._merge.row_count() - 1:
            self._show_row(self._row + 1)
        else:
            self._update_choice_buttons()
            self._focus_current()

    def _step(self, delta: int):
        row = self._row + delta
        if 0 <= row < self._merge.row_count():
            self._show_row(row)

    def _bind_keys(self):
        """Back, Forward and the two choices as dialog-wide QShortcuts, which Qt fires whichever
        child has focus, a text pane included. Not a keyPressEvent override: a focused
        QAbstractButton spends Left/Right on moving focus, so Alt+Left/Right would never arrive.
        Not button shortcuts: QAbstractButton.setText() resets a button's shortcut, and the choice
        buttons' text changes on every row. Escape and Enter stay QDialog's own."""
        bindings = ((self._shortcuts["edit_prev"], lambda: self._step(-1)),
                    (self._shortcuts["edit_next"], lambda: self._step(+1)),
                    (self._CHOICE_KEYS[0], lambda: self._choose(0)),
                    (self._CHOICE_KEYS[1], lambda: self._choose(1)))
        for key, slot in bindings:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(slot)


# ══════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
#  INFO BAR NOTIFICATIONS
# ══════════════════════════════════════════════════════════════

# Read at call time, not bound as defaults, so tests can shorten them.
NOTIFY_MIN_TURN_MS = 3000   # a message stays up at least this long before a waiting one takes over,
                            # and a waiting message's turn is at most this long
NOTIFY_QUEUE_MAX   = 5      # messages waiting at most; past that the oldest waiting one is dropped
NOTIFY_HISTORY_MAX = 200    # messages kept for the history pop-up
NOTIFY_DEFAULT_MS  = 4000
NOTICE_LEVELS = ("info", "warning", "error")


@dataclass
class Notice:
    """One info-bar message, as queued and as kept in the session history."""
    text:  str
    ms:    int
    level: str        # one of NOTICE_LEVELS
    time:  datetime   # when it arrived


def _notice_color(t: dict, level: str) -> str:
    return {"warning": t["text_warn"], "error": t["text_bad"]}.get(level, t["fg_dim"])


def _notice_html(text: str) -> str:
    """*text* as rich text: escaped, and with the two-space separators the messages use kept
    (rich text would collapse them to one)."""
    return html.escape(text, quote=False).replace("  ", "&nbsp; ")


def _history_html(notices: List[Notice], t: dict) -> str:
    """The history pop-up's content: newest first, each row the time in fg_dim and the text in its
    level's colour. <font color> rather than CSS, the form QTextDocument is known to honour."""
    if not notices:
        return f'<font color="{t["fg_dim"]}">No messages yet</font>'
    rows = []
    for n in reversed(notices):
        rows.append(
            f'<tr><td valign="top"><font color="{t["fg_dim"]}">{n.time:%H:%M:%S}</font>&nbsp;&nbsp;</td>'
            f'<td><font color="{_notice_color(t, n.level)}">{_notice_html(n.text)}</font></td></tr>')
    return '<table cellspacing="0" cellpadding="2">' + "".join(rows) + "</table>"


class MessageHistoryPopup(QFrame):
    """The info bar's message history: this session's messages, newest first, each with its time
    and in its level's colour; text can be selected and copied. Created per open, so it takes the
    current theme and font, and it does not update while open. Closes on Escape or a click outside
    (Qt.Popup closes itself then)."""

    MIN_WIDTH = 420
    MAX_WIDTH = 720
    MAX_LINES = 12

    def __init__(self, button: QWidget, notices: List[Notice]):
        super().__init__(button, Qt.Popup)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("messageHistoryPopup")
        self._button = button
        t, self._font = _theme_and_font(button)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setFrameShape(QFrame.NoFrame)
        # QTextBrowser's own minimumSizeHint (a fixed ~75x75 floor, unrelated to its content)
        # would otherwise force the popup taller than show_above_button()'s own, content-based
        # height for a short history -- Ignored tells the layout to size this widget purely from
        # the geometry show_above_button() sets, never from the browser's built-in floor.
        self.browser.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.browser.document().setDefaultFont(self._font)
        self.browser.setHtml(_history_html(notices, t))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.addWidget(self.browser)
        # The viewport is a plain QWidget: without its own rule the main window's
        # "QWidget { background: bg }" would paint it a darker strip on the dlg_bg surface.
        self.setStyleSheet(
            f"QFrame#messageHistoryPopup {{ background: {t['dlg_bg']}; border: 1px solid {t['border2']}; }}"
            f"QTextBrowser, QWidget#qt_scrollarea_viewport {{ background: {t['dlg_bg']};"
            f" color: {t['fg']}; border: none; }}")

    def show_above_button(self) -> None:
        """Above the history button with right edges aligned, moved inside the button's screen."""
        button = self._button
        width = max(self.MIN_WIDTH, min(self.MAX_WIDTH, round(button.window().width() * 0.6)))
        doc = self.browser.document()
        doc.setTextWidth(width - 2)
        cap = self.MAX_LINES * QFontMetrics(self._font).lineSpacing() + 2 * math.ceil(doc.documentMargin())
        height = min(math.ceil(doc.size().height()), cap) + 4   # the 1 px border each side, 2 px slack
        avail = button.screen().availableGeometry()
        height = min(height, avail.height())
        right = button.mapToGlobal(QPoint(button.width(), 0))
        x = max(avail.left(), min(right.x() - width, avail.right() + 1 - width))
        y = max(avail.top(), right.y() - height)
        self.setGeometry(x, y, width, height)
        self.show()
        self.browser.setFocus()

    def mousePressEvent(self, event) -> None:
        # Qt.Popup closes on an outside press and replays it to whatever is underneath; on the
        # history button that replay would reopen the pop-up it just closed.
        button_rect = QRect(self._button.mapToGlobal(QPoint(0, 0)), self._button.size())
        if button_rect.contains(event.globalPosition().toPoint()):
            self.setAttribute(Qt.WA_NoMouseReplay)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


class WelcomeScreen(QWidget):
    """Empty-state screen shown in MainWindow's central stack when no file
    is open. MainWindow's menu bar and info bar stay visible around it --
    only the filter panel + table area is replaced, mirroring how Moji
    keeps its own toolbar and status bar visible behind its welcome view."""

    def __init__(self, mw: "MainWindow"):
        super().__init__()
        self._mw = mw
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)

        logo_lbl = QLabel()
        logo_lbl.setAlignment(Qt.AlignCenter)
        pix = QPixmap(str(APP_LOGO_PATH))
        if not pix.isNull():
            logo_lbl.setPixmap(pix.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        outer.addWidget(logo_lbl)
        outer.addSpacing(12)

        name_lbl = QLabel(APP_NAME)
        name_lbl.setObjectName("welcomeNameLbl")
        name_lbl.setAlignment(Qt.AlignCenter)
        outer.addWidget(name_lbl)

        version_lbl = QLabel(f"v{APP_VERSION}")
        version_lbl.setObjectName("welcomeVersionLbl")
        version_lbl.setAlignment(Qt.AlignCenter)
        outer.addWidget(version_lbl)

        tagline_lbl = QLabel("A structured editor for JSON translation files")
        tagline_lbl.setObjectName("welcomeTaglineLbl")
        tagline_lbl.setAlignment(Qt.AlignCenter)
        outer.addWidget(tagline_lbl)
        outer.addSpacing(20)

        open_btn = QPushButton("Open File…")
        open_btn.setObjectName("welcomeOpenBtn")
        open_btn.setProperty("role", "primary")
        open_btn.clicked.connect(self._mw._open)
        outer.addWidget(open_btn, alignment=Qt.AlignHCenter)
        outer.addSpacing(8)

        hint_lbl = QLabel("or drop a .json file anywhere in the main window area")
        hint_lbl.setObjectName("welcomeHintLbl")
        hint_lbl.setAlignment(Qt.AlignCenter)
        outer.addWidget(hint_lbl)

        self.attribution_lbl = QLabel()
        self.attribution_lbl.setObjectName("welcomeAttributionLbl")
        self.attribution_lbl.setAlignment(Qt.AlignCenter)
        self.attribution_lbl.setTextFormat(Qt.RichText)
        self.attribution_lbl.setOpenExternalLinks(True)
        outer.addSpacing(4)
        outer.addWidget(self.attribution_lbl)
        self.apply_link_color("#0078d4")  # placeholder; real colour set by MainWindow._apply_theme()

    def apply_link_color(self, color: str):
        """Rebuild the attribution label's HTML with the link coloured.

        Two more-obvious approaches were tried first and both verified, by
        sampling the actual rendered pixel colour, to have zero effect:
        (1) `QPalette.Link` set on the application palette in
        `MainWindow._apply_palette()`, and (2) an inline `style="color:...` on
        the `<a>` tag itself -- both left the link rendering as Qt/Windows'
        own default link blue (`#0078d4`) regardless of what was actually
        set. Same family of issue as the FontSettingsDialog preview's
        `setFont()`-vs-stylesheet pitfall elsewhere in this file: rich content
        silently ignoring a mechanism that looks like it should apply.
        The one thing verified to actually change the rendered colour is the
        older `<font color="...">` tag wrapping the link text (confirmed in
        isolation: a bare `<a href="..."><font color="#0050a0">...</font></a>`
        rendered as exactly `rgb(0, 80, 160)`) -- Qt's rich-text engine
        supports this HTML 4-era tag more completely than the CSS `style=`
        attribute on `<a>`. Must be re-called (from
        `MainWindow._apply_theme()`, matching every other directly-styled
        widget in this app) whenever the theme changes, since it has no
        stylesheet cascade to rely on."""
        self.attribution_lbl.setText(
            f'Icon by <a href="https://www.magnific.com">'
            f'<font color="{color}">Magnific</font></a>'
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1280, 760)
        self.setAcceptDrops(True)

        self.settings   = Settings()
        # After Settings() so a damaged file has already been recovered and
        # what gets archived is what is actually in use.
        backup_settings_daily(SETTINGS_FILE)
        self.entries:   List[StringEntry] = []
        self.model      = TranslationModel(
            theme_fn=lambda: self.settings.get("theme", "dark")
        )
        self.filter_eng = FilterEngine()
        self.current_file: Optional[Path] = None
        self.is_modified = False
        self.session_translator: str = ""  # in-memory only; not persisted
        self.claude_session: Optional["ClaudeSubscriptionSession"] = None
        self._backup_threads: List["BackupThread"] = []
        self._translation_threads: List["TranslationThread"] = []
        self._is_closing = False
        self.header:     FileHeader = FileHeader()          # the open file's sidecar header
        self.json_style: JsonStyle  = DEFAULT_JSON_STYLE    # layout to write the open file back in
        self.round_trips: bool      = True                  # Task 7 asks before reformatting when False
        self._meta_blocked: bool    = False                 # its sidecar could not be read: leave it alone
        self.glossary:               List[GlossaryEntry] = []   # parsed rows for the open file's glossary
        self.glossary_path:          Optional[Path]      = None # <stem>.glossary.csv next to current_file
        self.glossary_load_warnings: List[str]           = []   # corrections applied on the most recent load
        self._notice_current: Optional[Notice] = None       # on screen, or None
        self._notice_queue:   Deque[Notice]    = deque()    # waiting for their turn
        self._notice_history: Deque[Notice]    = deque(maxlen=NOTIFY_HISTORY_MAX)
        self._notice_shown_at: float           = 0.0        # time.monotonic() when _notice_current appeared
        self._history_unseen_level: str        = ""         # "" | "warning" | "error": the history button's dot
        self._mod_text:    str = ""   # persistent mod status: "Unsaved changes" / "Autosaved at …"
        self._mod_kind:    str = ""   # "" | "modified" | "autosaved": resolved to a theme colour when painted

        # Ends the current message's turn: _on_notify_expired() shows the next one or clears the label
        self._notify_timer = QTimer(self)
        self._notify_timer.setSingleShot(True)

        self._build_ui()
        self._build_menu()
        self._apply_palette()
        self._apply_theme(self.settings.get_font())
        self._apply_app_font()
        self._update_title()

        # Startup dialogs run after the main window is fully visible
        QTimer.singleShot(0, self._run_startup_prompts)

    # ── UI Construction ────────────────────────────────────────


    # ── Startup prompts ───────────────────────────────────────────────────────

    def _run_startup_prompts(self):
        """Startup dialogs, in order: the settings-recovery notice (only when
        Settings.load() had to replace a damaged file), then the translator-name
        prompt; then the settings load messages and the translator message. One
        deferred entry point so the order can't depend on timer scheduling. The
        messages come after the dialogs so their turns don't run out behind them."""
        if self.settings.recovery_notice:
            QMessageBox.warning(self, "Settings file recovered", self.settings.recovery_notice)
        self._ask_translator_name()
        for text, level in self.settings.startup_notices:
            self._show_message(text, 6000, level)
        self._update_translator_status()

    # ── Translator session ────────────────────────────────────────────────────

    def _ask_translator_name(self):
        """Show the translator-name dialog and store the result for this session.
        The caller shows the resulting translator message."""
        if self.settings.get("skip_translator_prompt", False):
            return
        dlg = TranslatorNameDialog(self.session_translator, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.session_translator = dlg.get_name()
        # If the user clicks Skip (reject), session_translator stays empty.

    def _set_translator_name(self):
        """Menu-triggered: change the session translator name at any point,
        independent of the skip_translator_prompt startup setting."""
        dlg = TranslatorNameDialog(self.session_translator, parent=self, on_demand=True)
        if dlg.exec() == QDialog.Accepted:
            self.session_translator = dlg.get_name()
            self._update_translator_status()
        # If the user clicks Cancel (reject), session_translator stays unchanged.

    def _get_claude_session(self) -> "ClaudeSubscriptionSession":
        """Return the app-lifetime Claude subscription session, creating it on
        first use and rebuilding it if the signed-in token or selected model
        has changed since it was created (e.g. after a re-sign-in or a model
        switch in Translation Settings). Raises ValueError if no subscription
        token is signed in — callers (TranslationThread) let this propagate as
        a normal engine config error, same as a missing API key on other
        engines."""
        cfg   = self.settings.get("translation", {})
        token = cfg.get("claude_subscription_token", "").strip()
        if not token:
            raise ValueError(
                "No Claude subscription signed in.\nOpen View → Translation Settings…")
        model = cfg.get("claude_model", "claude-haiku-4-5-20251001")
        if (self.claude_session is not None
                and (self.claude_session.token != token
                     or self.claude_session.model != model)):
            self.claude_session.close()
            self.claude_session = None
        if self.claude_session is None:
            self.claude_session = ClaudeSubscriptionSession(token, model)
        return self.claude_session

    def _register_translation_thread(self, thread: "TranslationThread") -> bool:
        """Track *thread* so closeEvent() can wait for it before the window
        is destroyed -- mirrors _create_backup()/_backup_threads. Callers
        (EditDialog, TranslationSettingsDialog) must NOT parent the thread to
        themselves; a dialog closing while an abandoned thread is still
        running must not risk destroying a live QThread.

        Returns False (and does not register) once closeEvent() has begun
        shutting the app down -- mirrors _create_backup()'s own _is_closing
        guard. Callers must not call thread.start() when this returns False;
        an unregistered, unstarted thread needs no further handling."""
        if self._is_closing:
            return False
        self._translation_threads.append(thread)
        thread.finished.connect(lambda *_: self._on_translation_thread_finished(thread))
        thread.errored.connect(lambda *_: self._on_translation_thread_finished(thread))
        return True

    def _on_translation_thread_finished(self, thread: "TranslationThread"):
        """Removes *thread* from self._translation_threads (the list
        closeEvent waits on) once it reports done, however it reports --
        mirrors _on_backup_finished's registry bookkeeping."""
        if thread in self._translation_threads:
            self._translation_threads.remove(thread)

    def _show_message(self, text: str, ms: int = NOTIFY_DEFAULT_MS, level: str = "info"):
        """Show *text* in the info bar for *ms* and record it in the message history. Messages that
        arrive while another is showing wait their turn instead of replacing it: the current one
        stays up at least NOTIFY_MIN_TURN_MS, a waiting one gets at most that long unless it is the
        last, which gets its full *ms*. *level* is "info", "warning" or "error"."""
        if ms <= 0:
            ms = NOTIFY_DEFAULT_MS
        if level not in NOTICE_LEVELS:
            level = "info"
        notice = Notice(text, ms, level, datetime.now())
        self._notice_history.append(notice)
        if level != "info":
            self._raise_unseen(level)
        last_waiting = self._notice_queue[-1] if self._notice_queue else None
        if any(n is not None and (n.text, n.level) == (text, level)
               for n in (self._notice_current, last_waiting)):
            return
        if self._notice_current is None:
            self._notice_current = notice
            self._notice_shown_at = time.monotonic()
            self._notify_timer.start(ms)
        else:
            if len(self._notice_queue) >= NOTIFY_QUEUE_MAX:
                self._notice_queue.popleft()
            self._notice_queue.append(notice)
            elapsed = int((time.monotonic() - self._notice_shown_at) * 1000)
            cut = max(0, NOTIFY_MIN_TURN_MS - elapsed)
            remaining = self._notify_timer.remainingTime()
            if remaining < 0 or cut < remaining:
                self._notify_timer.start(cut)
        self._update_dynamic_label()

    def _on_notify_expired(self):
        """Timer callback: the current message's turn is over. Show the next waiting one -- for a
        shortened turn while others still wait behind it -- or fall back to the mod status."""
        if self._notice_queue:
            notice = self._notice_queue.popleft()
            self._notice_current = notice
            self._notice_shown_at = time.monotonic()
            self._notify_timer.start(
                min(notice.ms, NOTIFY_MIN_TURN_MS) if self._notice_queue else notice.ms)
        else:
            self._notice_current = None
        self._update_dynamic_label()

    def _update_dynamic_label(self):
        """Apply current-message > mod-status priority to the single dynamic info-bar label."""
        t = self._get_theme()
        notice = self._notice_current
        if notice is not None:
            text = _notice_html(notice.text)
            if self._notice_queue:
                text += (f'<font color="{t["fg_dim"]}">&nbsp;&nbsp;&nbsp;'
                         f'+{len(self._notice_queue)}</font>')
            self._dynamic_label.setText(text)
            # A long message can be cut off in a narrow window.
            self._dynamic_label.setToolTip(notice.text)
            self._dynamic_label.setStyleSheet(f"color: {_notice_color(t, notice.level)};")
        elif self._mod_text:
            # Resolved here, not stored as a colour string, so a theme switch recolours it.
            color = {"modified": t["text_warn"], "autosaved": t["text_ok"]}.get(self._mod_kind, t["fg_dim"])
            self._dynamic_label.setText(self._mod_text)
            self._dynamic_label.setToolTip("")
            self._dynamic_label.setStyleSheet(f"color: {color};")
        else:
            self._dynamic_label.setText("")
            self._dynamic_label.setToolTip("")

    def _raise_unseen(self, level: str):
        """An error outranks a warning for the history button's dot; info never sets it."""
        rank = {"": 0, "warning": 1, "error": 2}
        if rank[level] > rank[self._history_unseen_level]:
            self._history_unseen_level = level
            self._refresh_history_icon()

    def _refresh_history_icon(self, font: Optional[QFont] = None):
        """Paint the history button's glyph in the current theme at the UI font's text height,
        with the dot of an unseen warning or error."""
        if font is None:
            font = self.settings.get_font()
        t = self._get_theme()
        px = round(QFontMetrics(font).height() * 0.9)
        dot = {"warning": t["text_warn"], "error": t["text_bad"]}.get(self._history_unseen_level)
        icon = QPixmap.fromImage(_render_history_icon(t["fg_dim"], px * _GLYPH_SUPERSAMPLE, dot))
        icon.setDevicePixelRatio(_GLYPH_SUPERSAMPLE)
        self._history_btn.setIcon(QIcon(icon))
        self._history_btn.setIconSize(QSize(px, px))

    def _open_message_history(self) -> "MessageHistoryPopup":
        """The history button's pop-up. Opening it marks every message as seen."""
        self._history_unseen_level = ""
        self._refresh_history_icon()
        popup = MessageHistoryPopup(self._history_btn, list(self._notice_history))
        popup.show_above_button()
        return popup

    def _update_translator_status(self):
        """Show the session translator name as a transient notification."""
        if self.session_translator:
            self._show_message(f"—  Translator: {self.session_translator}  —", 4000)
        else:
            self._show_message("Ready — open a JSON translation file", 4000)

    def _update_file_meta_labels(self):
        """Update the file metadata labels with language and version from the loaded file's sidecar."""
        self._sb_lang_label.setText(self.display_language or self.target_culture)
        self._sb_ver_label.setText(f"v{self.file_version}" if self.file_version else "")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Filter panel (settings passed so it can persist the From-date)
        self.filter_panel = FilterPanel(settings=self.settings)
        self.filter_panel.filters_changed.connect(self._apply_filters)

        # Table
        self.table = QTableView()
        self.table.setModel(self.model)
        self._status_delegate = StatusDelegate(self.table)
        self.table.setItemDelegate(self._status_delegate)
        # entered() only fires with mouse tracking; the viewport's Leave event clears the hover.
        self.table.setMouseTracking(True)
        self.table.entered.connect(lambda index: self._status_delegate.set_hover_row(index.row()))
        # Over blank viewport space Qt emits viewportEntered, not entered, so clear the hover there too.
        self.table.viewportEntered.connect(lambda: self._status_delegate.set_hover_row(-1))
        self.table.viewport().installEventFilter(self)
        self.model.modelReset.connect(lambda: self._status_delegate.set_hover_row(-1))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.doubleClicked.connect(self._edit_row)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)

        # Column widths — loaded from settings, falling back to defaults
        self._col_save_timer = QTimer(self)

        # Autosave timer
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave_tick)
        self._reconfigure_autosave()
        self._col_save_timer.setSingleShot(True)
        self._col_save_timer.setInterval(400)   # ms debounce
        self._col_save_timer.timeout.connect(self._persist_column_widths)

        self._apply_column_widths()
        self.table.horizontalHeader().setSectionResizeMode(COL_SRC,   QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_TRANS, QHeaderView.Stretch)
        # sectionResized fires for every pixel while dragging; debounce before saving
        self.table.horizontalHeader().sectionResized.connect(
            self._on_column_resized
        )
        self._empty_filter_label = QLabel("No entries match your filter")
        self._empty_filter_label.setAlignment(Qt.AlignCenter)

        self._table_stack = QStackedWidget()
        self._table_stack.addWidget(self.table)                # index 0: normal view
        self._table_stack.addWidget(self._empty_filter_label)  # index 1: empty state

        # Editor page: filter panel + table stack, shown once a file is open
        editor_page = QWidget()
        editor_layout = QVBoxLayout(editor_page)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)
        editor_layout.addWidget(self.filter_panel)
        editor_layout.addWidget(self._table_stack)

        # Outer stack: Welcome screen (no file open) <-> editor page (file open)
        self._welcome_screen = WelcomeScreen(self)
        self._main_stack = QStackedWidget()
        self._main_stack.addWidget(self._welcome_screen)  # index 0: no file
        self._main_stack.addWidget(editor_page)           # index 1: file open
        root.addWidget(self._main_stack)

        # Info bar — single unified bar (no Qt status bar used)
        info_bar = QHBoxLayout()
        info_bar.setContentsMargins(8, 3, 8, 3)
        self.count_label = QLabel("No file loaded")
        info_bar.addWidget(self.count_label)
        # The refresh hint is a divider, a painted icon (set in _apply_theme) and its text, shown
        # and hidden as one widget by _update_count() so the divider never stands alone.
        self._refresh_hint = QWidget()
        self._refresh_hint.setToolTip(
            "A filter is active — some entries are hidden.\n"
            "Press F5 (or Edit → Refresh Filter) to re-apply the\n"
            "current filter after editing entries.")
        hint_row = QHBoxLayout(self._refresh_hint)
        # ~12 px either side of the line: the right-hand spacing is smaller because the icon
        # image carries ~3 px of transparent margin of its own.
        hint_row.setContentsMargins(10, 0, 0, 0)
        hint_row.setSpacing(0)
        self._refresh_hint_divider = QFrame()
        self._refresh_hint_divider.setFrameShape(QFrame.VLine)
        hint_row.addWidget(self._refresh_hint_divider)
        hint_row.addSpacing(9)
        self._refresh_hint_icon = QLabel()
        hint_row.addWidget(self._refresh_hint_icon)
        hint_row.addSpacing(4)
        self.refresh_hint_label = QLabel("F5 — Refresh Filter")
        hint_row.addWidget(self.refresh_hint_label)
        self._refresh_hint.setVisible(False)
        info_bar.addWidget(self._refresh_hint)
        info_bar.addStretch()
        # Single dynamic label: transient notifications take priority over mod status
        self._dynamic_label = QLabel("")
        self._dynamic_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # Rich text so the "+N" of waiting messages can be dimmed while the text keeps its level's colour.
        self._dynamic_label.setTextFormat(Qt.RichText)
        self._notify_timer.timeout.connect(self._on_notify_expired)
        info_bar.addWidget(self._dynamic_label)
        # Message history: its icon (set in _apply_theme) carries a dot for an unseen warning or error.
        self._history_btn = QToolButton()
        self._history_btn.setObjectName("historyBtn")
        self._history_btn.setToolTip("Message history")
        self._history_btn.setAccessibleName("Message history")
        self._history_btn.setAutoRaise(True)
        self._history_btn.clicked.connect(self._open_message_history)
        info_bar.addWidget(self._history_btn)
        # File metadata: language and version from the loaded file's sidecar
        self._sb_lang_label = QLabel("")
        info_bar.addWidget(self._sb_lang_label)
        self._sb_ver_label = QLabel("")
        info_bar.addWidget(self._sb_ver_label)
        root.addLayout(info_bar)

    def _build_menu(self):
        mb = self.menuBar()

        # File
        fm = mb.addMenu("&File")
        self._act(fm, "Open…",               self._open,               "Ctrl+O")
        self._act(fm, "Save",                self._save,               "Ctrl+S")
        self._act(fm, "Save As…",            self._save_as,            "Ctrl+Shift+S")
        self._act(fm, "Close File",          self._close_file,         "Ctrl+W")
        self._act(fm, "Restore from Backup…", self._open_restore_backup, "")
        self._act(fm, "Merge from File…",     self._merge_from_file,     "")
        self._act(fm, "Properties…",          self._open_file_properties, "")
        fm.addSeparator()
        self._act(fm, "Exit",                self.close,               "Ctrl+Q")

        # Edit
        em = mb.addMenu("&Edit")
        self._act(em, "Edit Selected  (Enter)",  self._edit_selected, "Return")
        self._act(em, "Refresh Filter  (F5)",    self._refresh_filter, "F5")
        em.addSeparator()
        sc = self.settings.get("shortcuts", {})
        self._act_mark_new = self._act(
            em, "Mark Selected as New",
            lambda: self._bulk_status("New"),
            sc.get("mark_new", SHORTCUT_DEFAULTS["mark_new"]))
        self._act_mark_review = self._act(
            em, "Mark Selected as Review",
            lambda: self._bulk_status("Review"),
            sc.get("mark_review", SHORTCUT_DEFAULTS["mark_review"]))
        self._act_mark_complete = self._act(
            em, "Mark Selected as Complete",
            lambda: self._bulk_status("Complete"),
            sc.get("mark_complete", SHORTCUT_DEFAULTS["mark_complete"]))
        em.addSeparator()
        self._act_delete_entries = self._act(
            em, "Delete Selected",
            self._delete_selected,
            sc.get("delete_entries", SHORTCUT_DEFAULTS["delete_entries"]))
        # Ctrl+Delete is Qt's native "delete word forward" binding inside
        # QLineEdit/QTextEdit (e.g. the Search/Translator filter boxes) --
        # scoping this action's shortcut to the table (instead of the
        # default window-wide context the mark_* actions use) means the key
        # combo only fires with the table focused, never hijacking normal
        # text editing elsewhere in the window. The menu item and context
        # menu entry stay clickable regardless of focus.
        self._act_delete_entries.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.table.addAction(self._act_delete_entries)

        # View
        vm = mb.addMenu("&View")
        self._act(vm, "Choose UI Font\u2026",        self._choose_font, "")
        self._act(vm, "Keyboard Shortcuts\u2026",    self._open_shortcuts, "")
        self._act(vm, "Translation Settings\u2026",  self._open_translation_settings, "")
        self._act(vm, "Glossary\u2026",               self._open_glossary, "")
        self._act(vm, "Autosave & Backup\u2026",      self._open_autosave_backup, "")
        self._act(vm, "Set Translator Name\u2026",    self._set_translator_name, "")
        vm.addSeparator()
        # Theme submenu
        theme_menu = vm.addMenu("Theme")
        cur_theme = self.settings.get("theme", "dark")
        self._act_theme_dark  = QAction("Dark",  self, checkable=True)
        self._act_theme_light = QAction("Light", self, checkable=True)
        self._act_theme_dark.setChecked(cur_theme == "dark")
        self._act_theme_light.setChecked(cur_theme == "light")
        self._act_theme_dark.triggered.connect(lambda: self._set_theme("dark"))
        self._act_theme_light.triggered.connect(lambda: self._set_theme("light"))
        theme_menu.addAction(self._act_theme_dark)
        theme_menu.addAction(self._act_theme_light)

    def _act(self, menu, label, slot, shortcut=""):
        a = QAction(label, self)
        if shortcut:
            a.setShortcut(shortcut)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    # ── Theme ──────────────────────────────────────────────────

    def _get_theme(self) -> dict:
        """Return the active theme colour dict."""
        name = self.settings.get("theme", "dark")
        return THEMES.get(name, THEMES["dark"])

    @property
    def target_culture(self) -> str:
        """The language to translate into: the sidecar's code, else the file name's."""
        return effective_language(self.header, self.current_file)

    @property
    def display_language(self) -> str:
        return self.header.language_name

    @property
    def file_version(self) -> str:
        return self.header.version

    def _set_theme(self, name: str):
        """Switch theme, persist it, and refresh all styles."""
        self.settings.set("theme", name)
        self.settings.save()
        self._act_theme_dark.setChecked(name == "dark")
        self._act_theme_light.setChecked(name == "light")
        self._apply_palette()
        self._apply_theme()
        # Force the table to repaint all cells with new theme colours
        self.model.layoutChanged.emit()

    def _apply_palette(self):
        """Push a QPalette that matches the active theme onto the application."""
        t = self._get_theme()
        pal = QPalette()
        pal.setColor(QPalette.Window,          QColor(t["pal_window"]))
        pal.setColor(QPalette.WindowText,      QColor(t["pal_window_text"]))
        pal.setColor(QPalette.Base,            QColor(t["pal_base"]))
        pal.setColor(QPalette.AlternateBase,   QColor(t["pal_alt_base"]))
        pal.setColor(QPalette.ToolTipBase,     QColor(t["pal_tooltip_base"]))
        pal.setColor(QPalette.ToolTipText,     QColor(t["pal_tooltip_text"]))
        pal.setColor(QPalette.Text,            QColor(t["pal_text"]))
        pal.setColor(QPalette.Button,          QColor(t["pal_button"]))
        pal.setColor(QPalette.ButtonText,      QColor(t["pal_button_text"]))
        pal.setColor(QPalette.Highlight,       QColor(t["pal_highlight"]))
        pal.setColor(QPalette.HighlightedText, QColor(t["pal_hl_text"]))
        # Rich-text <a href> links are *documented* to render using this
        # palette role, and this app otherwise never set it -- it silently
        # fell back to Qt/Windows' system link-blue (#0078d4, the Windows
        # accent default), which gives only ~4.3:1 contrast against the light
        # theme's #f0f0f0 background (borderline AA) and isn't even
        # guaranteed to be that same shade for a user with a different
        # Windows accent colour. Set for correctness/robustness, but verified
        # NOT sufficient on its own: this had zero effect on
        # WelcomeScreen.attribution_lbl's rendered pixel colour (sampled
        # before/after, byte-identical) -- QLabel's rich text does not
        # reliably resolve <a> colour from QPalette.Link in practice. See
        # WelcomeScreen.apply_link_color() for the fix that actually works
        # (the old HTML 4 <font color="..."> tag -- an inline style="color:..."
        # on the <a> tag itself was also tried and also had no effect) and
        # the matching pitfall entry in CLAUDE.md.
        pal.setColor(QPalette.Link,            QColor(t["header_fg"]))
        QApplication.instance().setPalette(pal)

    def _apply_theme(self, font: Optional[QFont] = None):
        if font is None:
            font = self.settings.get_font()
        pt       = font.pointSize()
        pt_small = max(7, pt - 1)
        # Scales with the configured UI font like row height and hint text
        # elsewhere in this method, rather than a fixed px value -- the old
        # flat 10px read as "too thin" against a default 10pt font's own
        # rows/text, let alone a deliberately enlarged one. Qt6 always scales
        # logical-pixel QSS values by the OS display-scaling factor (no
        # explicit HighDpi handling exists in this app, nor is any needed),
        # so this stays correct across different monitor resolutions/DPI the
        # same way every other px value in this stylesheet already does.
        scrollbar_px = max(12, pt + 5)
        t        = self._get_theme()

        self.setStyleSheet(f"""
            QMainWindow, QWidget       {{ background: {t['bg']}; color: {t['fg']};
                                          font-family: "{font.family()}"; font-size: {pt}pt; }}
            QMenuBar                   {{ background: {t['bg3']}; color: {t['fg']}; }}
            QMenuBar::item:selected    {{ background: {t['sel_bg']}; color: {t['sel_fg']}; }}
            QMenu                      {{ background: {t['bg2']}; color: {t['fg']};
                                          border: 1px solid {t['border']}; }}
            QMenu::item:selected       {{ background: {t['sel_bg']}; color: {t['sel_fg']}; }}
            {_table_qss(t, pt)}
            {_groupbox_qss(t, pt)}
            QGroupBox                  {{ background: transparent; }}
            QLabel                     {{ color: {t['fg']}; font-size: {pt}pt;
                                          background: transparent; }}
            QLineEdit                  {{ background: {t['bg4']}; color: {t['fg']};
                                          border: 1px solid {t['border2']}; border-radius: 3px;
                                          padding: 3px 6px; font-size: {pt}pt; }}
            QComboBox                  {{ background: {t['bg4']}; color: {t['fg']};
                                          border: 1px solid {t['border2']}; border-radius: 3px;
                                          padding: 3px 6px; font-size: {pt}pt; }}
            QComboBox QAbstractItemView{{ background: {t['bg2']}; color: {t['fg']};
                                          selection-background-color: {t['sel_bg']};
                                          selection-color: {t['sel_fg']};
                                          font-size: {pt}pt; }}
            {_button_qss(t, pt)}
            QToolButton#historyBtn     {{ background: transparent; border: 1px solid transparent;
                                          border-radius: 3px; padding: 1px 3px; }}
            QToolButton#historyBtn:hover {{ background: {t['bg3']}; }}
            QToolButton#historyBtn:focus {{ border: 1px solid {t['accent']}; }}
            QCheckBox                  {{ color: {t['fg']}; font-size: {pt}pt;
                                          background: transparent; }}
            QCheckBox::indicator       {{ width: 14px; height: 14px; }}
            QCheckBox[filterChk="true"]              {{ font-size: {pt}pt; }}
            {_prominent_checkbox_qss(t)}
            QLabel#welcomeNameLbl      {{ color: {t['header_fg']}; font-size: {pt + 10}pt;
                                          font-weight: bold; }}
            QLabel#welcomeVersionLbl   {{ color: {t['fg_dim']}; font-size: {pt + 2}pt; }}
            QLabel#welcomeTaglineLbl   {{ color: {t['fg_dim']}; font-size: {pt}pt; }}
            QLabel#welcomeHintLbl      {{ color: {t['fg_dim']}; font-size: {pt_small}pt; }}
            QLabel#welcomeAttributionLbl {{ color: {t['fg_dim']}; font-size: {pt_small}pt; }}
            QPushButton#welcomeOpenBtn {{ border-radius: 4px;
                                          font-weight: bold; padding: 10px 28px;
                                          font-size: {pt + 1}pt; }}
            QDateEdit                  {{ background: {t['bg4']}; color: {t['fg']};
                                          border: 1px solid {t['border2']}; border-radius: 3px;
                                          padding: 2px 4px; font-size: {pt}pt; }}
            {_combobox_qss(t, pt)}
            QStatusBar                 {{ background: {t['sb_bg']}; color: {t['sb_fg']};
                                          font-size: {pt_small}pt; }}
            {_scrollbar_qss(t, scrollbar_px)}
            QFrame[frameShape="4"], QFrame[frameShape="5"] {{ color: {t['border']}; }}
            {_band_qss(t, pt_small)}
            {_field_state_qss(t)}
        """)
        # Per-widget overrides whose colour must survive a stylesheet rebuild
        self.count_label.setStyleSheet(f"color: {t['fg_dim']};")
        self.refresh_hint_label.setStyleSheet(f"color: {t['fg_dim']}; font-size: {pt_small}pt;")
        self._refresh_hint_divider.setStyleSheet(f"color: {t['bar_border']};")
        hint_px = round(QFontMetrics(QFont(font.family(), pt_small)).capHeight() * 1.5)
        hint_icon = QPixmap.fromImage(
            _render_reset_icon(t["fg_dim"], hint_px * _GLYPH_SUPERSAMPLE))
        hint_icon.setDevicePixelRatio(_GLYPH_SUPERSAMPLE)
        self._refresh_hint_icon.setPixmap(hint_icon)
        self._refresh_history_icon(font)
        self._empty_filter_label.setStyleSheet(f"color: {t['fg_dim']}; font-size: {pt + 2}pt;")
        self._dynamic_label.setStyleSheet(f"color: {t['fg_dim']};")
        self._update_dynamic_label()
        self._sb_lang_label.setStyleSheet(f"color: {t['fg_dim']}; padding: 0 6px;")
        self._sb_ver_label.setStyleSheet(f"color: {t['fg_dim']}; padding: 0 6px;")
        self._welcome_screen.apply_link_color(t["header_fg"])
        self.filter_panel.fit_to_font(font, t["fg"])
        fm = QFontMetrics(self._dynamic_label.font())
        self._dynamic_label.setMinimumWidth(
            fm.horizontalAdvance("Autosaved at 00:00:00") + 16
        )

    # -- Autosave ------------------------------------------------------

    def _reconfigure_autosave(self):
        """Start or stop the autosave timer to match current settings."""
        self._autosave_timer.stop()
        cfg = self.settings.get("autosave", {})
        if cfg.get("enabled", False) and self.current_file:
            mins = max(1, int(cfg.get("interval_minutes", 5)))
            self._autosave_timer.start(mins * 60 * 1000)

    def _autosave_tick(self):
        """Called by autosave timer; silently saves if the file is modified."""
        if not (self.current_file and self.is_modified):
            return

        try:
            self._write_files(self.current_file)

        except MetadataWriteError as e:
            _log_error(f"autosave: writing the sidecar of {self.current_file}", e)
            self._show_message("Autosave: translations saved, metadata not — Save to retry", 6000, "error")
            return

        except PermissionError as e:
            # File is locked by another process (common on Windows when the
            # file is open in another app).  Ask the user what to do.
            self._autosave_locked(e)
            return

        except OSError as e:
            # Other OS-level write failure (disk full, network share gone, …)
            self._autosave_locked(e)
            return

        except Exception as e:
            self._show_message(f"Autosave failed: {e}", 6000, "error")
            return

        # ── Success ───────────────────────────────────────────────────────
        self.is_modified = False
        self._update_title()   # clears mod_label and the title bullet

        # Override the now-empty mod_label with a green "Autosaved at …" note.
        # It stays visible until the next edit (which re-triggers _update_title
        # with "Unsaved changes").
        ts = datetime.now().strftime("%H:%M:%S")
        self._mod_kind = "autosaved"
        self._mod_text = f"Autosaved at {ts}"
        self._update_dynamic_label()
        self._show_message(f"Autosaved: {_file_label(self.current_file.name, self.file_version)}  ({ts})", 4000)

    def _autosave_locked(self, error: Exception):
        """Handle a failed autosave due to a locked or inaccessible file."""
        ts  = datetime.now().strftime("%H:%M:%S")
        msg = QMessageBox(self)
        msg.setWindowTitle("Autosave — File Locked")
        msg.setIcon(QMessageBox.Warning)
        msg.setText(
            f"<b>Autosave failed at {ts}</b><br><br>"
            f"The file could not be written:<br>"
            f"<tt>{self.current_file}</tt><br><br>"
            f"<i>{error}</i><br><br>"
            "This usually means another application has the file open.<br>"
            "You can save a copy to a different location, or skip this autosave."
        )
        save_as_btn = msg.addButton("Save As…",   QMessageBox.AcceptRole)
        msg.addButton(        "Skip",              QMessageBox.RejectRole)
        msg.exec()

        if msg.clickedButton() is save_as_btn:
            # Re-use the normal Save As flow so the current_file pointer
            # is updated if the user picks a new path.
            self._save_as()

    # -- Backup -------------------------------------------------------

    def _create_backup(self, source_path: Path, trigger: str = "file_open",
                        notify: bool = True) -> Optional["BackupThread"]:
        """
        Kick off a background backup of source_path -- see BackupThread for
        the actual file I/O, hashing, and compression work, which no longer
        runs on this (the UI) thread.

        Layout per enabled location::

            <location_root>/JSON_Translation_file_Backups/
                <stem>[__v<version>]/
                    2025-03-05_14-30-00/
                        es.json.gz
                        es.glossary.csv.gz
                        backup_info.json

        Each enabled location gets its own complete, independently
        restorable slot -- see
        docs/superpowers/specs/2026-08-18-backup-restore-hardening-design.md.

        Returns the running BackupThread, or None if backup is disabled in
        settings (nothing is started -- callers that need to know
        completion should treat None the same as an already-finished,
        no-op backup).

        Returns None unconditionally once closeEvent() has begun shutting the
        app down: closeEvent() waits only on the threads already in
        self._backup_threads, so a backup started after that (e.g. by a
        restore continuation delivered during its processEvents() flush)
        would still be running, parented to this window, when the window is
        destroyed -- which aborts the process instead of exiting cleanly.
        """
        if self._is_closing:
            return None
        cfg = self.settings.get("backup", {})
        if not cfg.get("enabled", True):
            return None
        app_dir = Path(sys.argv[0]).resolve().parent
        thread = BackupThread(source_path, trigger, dict(cfg), app_dir, parent=self)
        thread.finished.connect(
            lambda notices, ntf_dir, t=thread: self._on_backup_finished(t, notices, ntf_dir, notify)
        )
        self._backup_threads.append(thread)
        thread.start()
        return thread

    def _on_backup_finished(self, thread: "BackupThread", notices: List[Tuple[str, str]],
                             next_to_file_root, notify: bool):
        """Runs on the main thread via BackupThread.finished's queued
        connection. Removes the finished thread from self._backup_threads
        (the list closeEvent waits on), persists the next-to-file root if
        that location succeeded (settings.data access must happen here,
        not on the background thread), and shows the per-location messages
        when notify=True."""
        if thread in self._backup_threads:
            self._backup_threads.remove(thread)
        if next_to_file_root is not None:
            self._remember_next_to_file_backup_dir(next_to_file_root)
        if notify:
            for text, level in notices:
                self._show_message(text, 5000 if level == "info" else 6000, level)

    def _remember_next_to_file_backup_dir(self, root_dir: Path) -> None:
        """Record *root_dir* (a resolved '<folder>/JSON_Translation_file_Backups'
        path) in backup.known_next_to_file_dirs so RestoreFromBackupDialog can
        discover it later, even when no file from that folder is currently
        open. Writes back only when the folder isn't already known, to avoid
        a settings write on every single backup.
        """
        cfg = dict(self.settings.get("backup", {}))
        known = cfg.get("known_next_to_file_dirs", [])
        if not isinstance(known, list):
            known = []
        resolved = str(root_dir.resolve())
        if resolved in known:
            return
        cfg["known_next_to_file_dirs"] = known + [resolved]
        self.settings.data["backup"] = cfg
        self.settings.save()

    # -- Autosave & Backup settings dialog -----------------------------

    def _open_autosave_backup(self):
        dlg = AutosaveBackupDialog(self.settings, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._reconfigure_autosave()

    def _open_restore_backup(self):
        """Open the Restore from Backup browser dialog."""
        app_dir = Path(sys.argv[0]).resolve().parent
        dlg = RestoreFromBackupDialog(app_dir, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        slot_dir = dlg.selected_slot_dir()
        info     = dlg.selected_info()
        if slot_dir is None or info is None:
            return
        self._do_restore(slot_dir, info, dlg.restore_glossary_requested())

    def _do_restore(self, slot_dir: Path, info: dict, restore_glossary: bool = False):
        """Decompress, verify MD5, write, and log a backup restore."""
        backup_file_name = info.get("backup_file", "")
        compressed       = info.get("compressed", True)
        expected_md5     = info.get("md5_checksum", "")
        original_path    = Path(info.get("original_path", ""))

        backup_file = slot_dir / backup_file_name
        if not backup_file.exists():
            QMessageBox.critical(
                self, "Restore Error",
                f"Backup file not found:\n{backup_file}"
            )
            return

        # Read and decompress
        try:
            if compressed:
                with gzip.open(backup_file, "rb") as fh:
                    raw_bytes = fh.read()
            else:
                raw_bytes = backup_file.read_bytes()
        except Exception as e:
            QMessageBox.critical(self, "Restore Error",
                                 f"Failed to read backup:\n{e}")
            return

        # Verify MD5
        actual_md5 = hashlib.md5(raw_bytes).hexdigest()
        md5_ok     = (not expected_md5) or (actual_md5 == expected_md5)
        if not md5_ok:
            r = QMessageBox.warning(
                self, "Checksum Mismatch",
                f"MD5 mismatch — the backup file may be corrupted.\n\n"
                f"Expected : {expected_md5}\n"
                f"Actual   : {actual_md5}\n\n"
                "Continue anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                return

        # Ask: overwrite at original location, or save as copy?
        ts_now    = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        orig_name = original_path.name or "restored.json"

        msg = QMessageBox(self)
        msg.setWindowTitle("Restore — Choose Destination")
        msg.setText(
            f"Overwrite  <b>{orig_name}</b>  at its original location?"
        )
        msg.setInformativeText(str(original_path))
        overwrite_btn = msg.addButton("Overwrite original", QMessageBox.YesRole)
        copy_btn      = msg.addButton("Save as copy",       QMessageBox.NoRole)
        msg.addButton("Cancel",                             QMessageBox.RejectRole)
        msg.setDefaultButton(overwrite_btn)
        msg.exec()
        clicked = msg.clickedButton()

        if clicked is overwrite_btn:
            dest_path = original_path
        elif clicked is copy_btn:
            stem = original_path.stem or "restored"
            ext  = original_path.suffix or ".json"
            dest_path = original_path.parent / f"{stem}_restored_{ts_now}{ext}"
        else:
            return  # Cancel

        # If destination is the currently open file and it has unsaved changes,
        # ask before discarding them.
        if (self.current_file
                and dest_path.resolve() == self.current_file.resolve()
                and self.is_modified):
            if not self._confirm_discard():
                return

        # Read (and verify) the glossary backup now, before the pre-restore
        # safety backup below runs -- its pruning operates on the same
        # key_dir slot_dir lives under, so reading any later risks slot_dir
        # being pruned out from under it (see _read_glossary_backup). Only
        # the read happens here; the write is deferred until after the
        # safety backup so that backup still captures dest_path's true
        # pre-restore state -- including its own glossary companion --
        # rather than the glossary this restore is about to write.
        glossary_raw_bytes    = None
        glossary_md5_verified = None
        if restore_glossary and info.get("glossary_backed_up", False):
            glossary_raw_bytes, glossary_md5_verified = self._read_glossary_backup(
                slot_dir, info)

        # Snapshot whatever currently exists at dest_path before overwriting
        # it -- best-effort, backgrounded so it doesn't block the UI. The
        # write below must still wait for it to finish (success or failure)
        # -- see _do_restore_after_backup().
        if dest_path.exists():
            try:
                thread = self._create_backup(dest_path, trigger="pre_restore_safety", notify=False)
            except Exception:
                thread = None
            if thread is not None:
                # _on_backup_finished (connected inside _create_backup, i.e.
                # earlier) always runs before this lambda, so by the time it
                # fires the _backup_threads bookkeeping and any notification
                # for this backup have already been handled.
                thread.finished.connect(lambda *_: self._do_restore_after_backup(
                    slot_dir, info, restore_glossary, dest_path, raw_bytes,
                    glossary_raw_bytes, glossary_md5_verified, actual_md5, md5_ok,
                ))
                return

        self._do_restore_after_backup(
            slot_dir, info, restore_glossary, dest_path, raw_bytes,
            glossary_raw_bytes, glossary_md5_verified, actual_md5, md5_ok,
        )

    def _do_restore_after_backup(self, slot_dir: Path, info: dict, restore_glossary: bool,
                                  dest_path: Path, raw_bytes: bytes,
                                  glossary_raw_bytes, glossary_md5_verified,
                                  actual_md5: str, md5_ok: bool):
        """Write the restored file, restore its glossary, log, and
        reload/notify -- everything that must happen strictly after the
        pre-restore safety backup (if any) has finished. Split out of
        _do_restore() so that backup can run in the background without
        blocking the UI thread; see BackupThread. Called either directly
        (no safety backup was needed) or from a BackupThread.finished
        connection (see _do_restore() above) -- in the latter case this
        runs on the main thread via Qt's queued cross-thread signal
        delivery, not on the backup thread itself.
        """
        # Write restored file
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_bytes(dest_path, raw_bytes)
        except Exception as e:
            QMessageBox.critical(self, "Restore Error",
                                 f"Failed to write file:\n{e}")
            return

        # Write the glossary bytes read above, if any. A glossary-restore
        # failure never blocks or rolls back the language file restore above, which
        # has already completed successfully.
        restored_glossary_to = None
        if glossary_raw_bytes is not None:
            restored_glossary_to = self._write_restored_glossary(dest_path, glossary_raw_bytes)
            if restored_glossary_to is None:
                # A failed write means there's nothing to have verified,
                # regardless of the earlier read.
                glossary_md5_verified = None

        # Shown after the "Restored..." message (or the reload's own messages), in that order.
        glossary_msg: Optional[Tuple[str, str]] = None
        if restore_glossary and info.get("glossary_backed_up", False):
            glossary_msg = (("Glossary restored", "info") if restored_glossary_to is not None
                            else ("Glossary restore failed", "error"))

        # Log the operation in the language backup folder
        self._write_restore_log(
            slot_dir, info, dest_path, actual_md5, md5_ok,
            restored_glossary_to, glossary_md5_verified,
        )

        # Reload if we just overwrote the currently open file; otherwise offer
        was_open = (
            self.current_file is not None
            and dest_path.resolve() == self.current_file.resolve()
        )
        # Read from the written file, not the manifest: slots older than versioned backups have no "version".
        restored_label = _file_label(dest_path.name, read_file_header(dest_path).version)
        if was_open:
            self._load(dest_path)
            self._show_message(f"Restored and reloaded: {restored_label}", 6000)
        elif self._is_closing:
            # closeEvent()'s processEvents() flush can deliver a still-
            # pending safety backup's finished signal, reaching this branch
            # while the app is shutting down. The file is already written
            # at this point -- skip the prompt rather than block shutdown
            # on a modal asking whether to open a file the app is about to
            # close anyway.
            self._show_message(f"Restored: {restored_label}", 6000)
        else:
            r = QMessageBox.question(
                self, "Restore Complete",
                f"File restored to:\n{dest_path}\n\nOpen the restored file now?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if r == QMessageBox.Yes:
                if self._confirm_discard():
                    self._load(dest_path)
            else:
                self._show_message(f"Restored: {restored_label}", 6000)

        if glossary_msg is not None:
            self._show_message(glossary_msg[0], 6000, glossary_msg[1])

    def _read_glossary_backup(self, slot_dir: Path, info: dict):
        """Decompress and verify the glossary paired with a restored language
        file, without writing anything.

        Split out from the writing half (_write_restored_glossary) so
        _do_restore() can read every byte it needs from slot_dir before its
        pre-restore safety backup runs -- that backup's pruning operates on
        the same key_dir slot_dir lives under, so a read performed after it
        risks slot_dir being deleted out from under it (e.g. restoring the
        oldest of a full set of max_count slots).

        Returns (raw_bytes, md5_verified). raw_bytes is None on any failure
        (not found, read error, or declined after an MD5 mismatch);
        md5_verified is None unless a decline is the reason (then False),
        or the read succeeded (then the actual verify result).
        """
        glossary_file_name  = info.get("glossary_file", "")
        glossary_compressed = info.get("glossary_compressed", True)
        expected_md5        = info.get("glossary_md5_checksum", "")

        glossary_backup_file = slot_dir / glossary_file_name
        if not glossary_backup_file.exists():
            return None, None

        try:
            if glossary_compressed:
                with gzip.open(glossary_backup_file, "rb") as fh:
                    raw_bytes = fh.read()
            else:
                raw_bytes = glossary_backup_file.read_bytes()
        except Exception:
            return None, None

        actual_md5 = hashlib.md5(raw_bytes).hexdigest()
        md5_ok     = (not expected_md5) or (actual_md5 == expected_md5)
        if not md5_ok:
            r = QMessageBox.warning(
                self, "Glossary Checksum Mismatch",
                f"MD5 mismatch for the glossary backup — it may be corrupted.\n\n"
                f"Expected : {expected_md5}\n"
                f"Actual   : {actual_md5}\n\n"
                "Restore it anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                return None, False

        return raw_bytes, md5_ok

    def _write_restored_glossary(self, dest_path: Path, raw_bytes: bytes):
        """Write previously-read glossary backup bytes (from
        _read_glossary_backup) to the glossary companion of dest_path. A
        glossary-restore failure never blocks or rolls back the file restore
        in _do_restore(), which has already completed successfully by the
        time this runs. Any failure here is reported to the caller only via
        the return value; _do_restore_after_backup() shows it after its own
        "Restored..." message.

        Returns the destination path as a string on success, None on
        failure.
        """
        glossary_dest = glossary_path_for(dest_path)
        try:
            glossary_dest.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_bytes(glossary_dest, raw_bytes)
        except Exception as e:
            QMessageBox.critical(self, "Restore Error",
                                 f"Failed to write glossary file:\n{e}")
            return None

        return str(glossary_dest)

    def _write_restore_log(
        self,
        slot_dir:   Path,
        info:       dict,
        dest_path:  Path,
        actual_md5: str,
        md5_ok:     bool,
        restored_glossary_to:  Optional[str]  = None,
        glossary_md5_verified: Optional[bool] = None,
    ):
        """Append a restore record to restore_log.json in the language folder."""
        log_path = slot_dir.parent / "restore_log.json"
        try:
            if log_path.exists():
                existing = json.loads(log_path.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            else:
                existing = []
        except Exception:
            existing = []

        record = {
            "restore_time":         datetime.now().isoformat(timespec="seconds"),
            "restored_from_slot":   slot_dir.name,
            "backup_original_path": info.get("original_path", ""),
            "restored_to":          str(dest_path),
            "md5_checksum":         actual_md5,
            "md5_verified":         md5_ok,
        }
        if restored_glossary_to is not None:
            record["restored_glossary_to"]  = restored_glossary_to
            record["glossary_md5_verified"] = glossary_md5_verified
        existing.append(record)
        try:
            log_path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _open_file_properties(self):
        """Edit the sidecar's language name and version (File → Properties…). An in-memory edit
        like any other: nothing is written until Save."""
        if not self.current_file:
            QMessageBox.warning(self, "File Properties",
                                 "Open a file first before viewing its properties.")
            return
        dlg = FilePropertiesDialog(self.target_culture, self.display_language, self.file_version,
                                   compute_file_facts(self.entries, self.current_file),
                                   self.is_modified, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        language = dlg.display_language()
        parts = dlg.version_parts()
        language_changed = language != self.display_language
        # Compared as numbers, so a stored "04.1.1140" is not rewritten when nothing was changed.
        version_changed = parts != parse_version_parts(self.file_version)
        if not (language_changed or version_changed):
            return
        self.header = replace(
            self.header,
            language_name=language if language_changed else self.header.language_name,
            version=format_version(parts) if version_changed else self.header.version)
        self.is_modified = True
        self._update_title()
        self._update_file_meta_labels()
        self._show_message("File properties updated", 4000)

    def _merge_from_file(self):
        """Reconcile the open file with a second language file (File → Merge from File…)."""
        if not self.current_file:
            QMessageBox.warning(self, "Merge from File",
                                 "Open a file first before merging.")
            return

        start = self.settings.get("last_directory") or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select File to Merge From", start,
            "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return

        try:
            incoming = load_translation_file(Path(path), keep_damaged=False)
        except Exception as e:
            QMessageBox.critical(self, "Merge Error", f"Failed to read file:\n{e}")
            return
        incoming_culture = effective_language(incoming.header, Path(path))

        if incoming_culture and self.target_culture and incoming_culture != self.target_culture:
            r = QMessageBox.warning(
                self, "Language Mismatch",
                f"Open file is {self.target_culture}, selected file is "
                f"{incoming_culture} — continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                return

        try:
            diff = compute_merge_diff(self.entries, incoming.entries)
        except ValueError as e:
            QMessageBox.critical(self, "Merge Error", str(e))
            return

        additions_to_add:     List[StringEntry] = diff.additions
        conflict_resolutions: List[StringEntry] = []
        deletions_to_remove:  List[StringEntry] = []
        if diff.additions or diff.conflicts or diff.deletions:
            dlg = MergeConflictDialog(
                diff.additions, diff.conflicts, diff.deletions,
                parent=self,
            )
            if dlg.exec() != QDialog.Accepted:
                return
            additions_to_add     = dlg.accepted_additions()
            conflict_resolutions = dlg.resolved_conflicts()
            deletions_to_remove  = dlg.deletions_to_remove()

        self._apply_merge_diff(diff, additions_to_add, conflict_resolutions, deletions_to_remove)
        for text, level in incoming.notices:
            self._show_message(f"Incoming file: {text}", 6000, level)

    def _apply_merge_diff(
        self,
        diff: MergeDiff,
        additions_to_add: List[StringEntry],
        conflict_resolutions: List[StringEntry],
        deletions_to_remove: List[StringEntry],
    ):
        """Apply a resolved MergeDiff into self.entries."""
        entries_by_name = {entry.name: entry for entry in self.entries}
        updated_count = 0

        for winner in diff.auto_updated:
            target = entries_by_name.get(winner.name)
            if target is None:
                continue
            target.translator  = winner.translator
            target.status      = winner.status
            target.modify_date = winner.modify_date
            updated_count += 1

        resolved_count = 0
        for (open_entry, _incoming_entry), chosen in zip(diff.conflicts, conflict_resolutions):
            if chosen is open_entry:
                continue  # kept open's existing value — nothing to change
            target = entries_by_name.get(open_entry.name)
            if target is None:
                continue
            target.translator  = chosen.translator
            target.status      = chosen.status
            target.modify_date = chosen.modify_date
            target.text        = chosen.text
            resolved_count += 1

        delete_names = {entry.name for entry in deletions_to_remove}
        deleted_count = sum(1 for entry in self.entries if entry.name in delete_names)
        if delete_names:
            self.entries = [entry for entry in self.entries if entry.name not in delete_names]

        added_count = len(additions_to_add)
        if additions_to_add:
            next_position = max((e.position for e in self.entries), default=0) + 1
            self.entries = self.entries + [replace(entry, position=next_position + i)
                                           for i, entry in enumerate(additions_to_add)]

        self.is_modified = True
        self.model.load(self.entries)
        self._apply_filters()
        self._update_title()
        self._update_count()
        merge_msg = (
            f"Merged: {added_count} added, {updated_count} updated, "
            f"{resolved_count} conflict(s) resolved, {deleted_count} deleted."
        )
        self._show_message(merge_msg, 6000)

    def _open_shortcuts(self):
        """Open the keyboard shortcuts configuration dialog."""
        dlg = ShortcutsDialog(self.settings, parent=self)
        dlg.exec()
        # Re-apply mark shortcuts in case user changed them
        self._apply_mark_shortcuts()

    def _open_translation_settings(self):
        """Open the translation engine configuration dialog."""
        dlg = TranslationSettingsDialog(self.settings, parent=self)
        dlg.exec()

    def _open_glossary(self):
        """Open the glossary editor for the currently loaded language file."""
        if not self.current_file:
            self._show_message("Open a file first to edit its glossary.", 4000, "warning")
            return
        dlg = GlossaryDialog(self, parent=self)
        dlg.exec()


    def _apply_mark_shortcuts(self):
        """Update the Mark and Delete menu actions with the currently configured shortcuts."""
        sc = self.settings.get("shortcuts", {})
        self._act_mark_new.setShortcut(
            sc.get("mark_new", SHORTCUT_DEFAULTS["mark_new"]))
        self._act_mark_review.setShortcut(
            sc.get("mark_review", SHORTCUT_DEFAULTS["mark_review"]))
        self._act_mark_complete.setShortcut(
            sc.get("mark_complete", SHORTCUT_DEFAULTS["mark_complete"]))
        self._act_delete_entries.setShortcut(
            sc.get("delete_entries", SHORTCUT_DEFAULTS["delete_entries"]))


    # ── Column width persistence ───────────────────────────────────────

    def _apply_column_widths(self):
        """Set column widths from settings (or defaults if not yet saved)."""
        saved = self.settings.get("column_widths", {})
        defaults = self.settings.DEFAULTS["column_widths"]
        for col in range(len(HEADERS)):
            w = saved.get(str(col), defaults.get(str(col)))
            if w:
                self.table.setColumnWidth(col, int(w))

    def _on_column_resized(self, logical_index: int, old_size: int, new_size: int):
        """Called on every sectionResized signal — starts the debounce timer."""
        # Ignore programmatic resize events that happen during startup
        # (before the window is shown the header fires resizes we don't want to save).
        if not self.isVisible():
            return
        self._col_save_timer.start()   # restart; fires once dragging stops

    def _persist_column_widths(self):
        """Read all current column widths from the header and write to settings."""
        header = self.table.horizontalHeader()
        widths = {
            str(col): header.sectionSize(col)
            for col in range(len(HEADERS))
        }
        self.settings.set("column_widths", widths)
        self.settings.save()

    def _apply_app_font(self):
        font = self.settings.get_font()

        # Set application-wide font — this is the primary mechanism and
        # propagates to ALL widgets including menus, dialogs, and new windows.
        QApplication.instance().setFont(font)

        # Explicitly walk every visible widget and force the font, because
        # Qt does NOT re-propagate QApplication.setFont() to already-created
        # widgets when a stylesheet is active (stylesheet can freeze the font).
        for widget in QApplication.instance().allWidgets():
            widget.setFont(font)
            widget.update()

        # Keep table row height in sync with font size
        row_h = max(24, font.pointSize() * 2 + 8)
        self.table.verticalHeader().setDefaultSectionSize(row_h)
        self.table.horizontalHeader().setFont(font)

        # Re-apply the theme stylesheet so any hardcoded font-size values
        # in QSS are replaced with the current point size dynamically.
        self._apply_theme(font)

    # ── File Operations ────────────────────────────────────────

    def _open(self):
        if not self._confirm_discard(): return
        start = self.settings.get("last_directory") or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open JSON Translation File", start,
            "JSON Files (*.json);;All Files (*)"
        )
        if path:
            self._load(Path(path))

    def _load(self, path: Path):
        try:
            loaded = load_translation_file(path)
            self.entries      = loaded.entries
            self.json_style   = loaded.style
            self.round_trips  = loaded.round_trips
            self.header       = loaded.header
            self._meta_blocked = loaded.meta_blocked
            self.current_file = path
            self.is_modified  = False
            self.model.load(self.entries)
            self._apply_filters()
            self.glossary_path = glossary_path_for(path)
            try:
                self.glossary, self.glossary_load_warnings = parse_glossary(self.glossary_path)
            except Exception as e:
                self.glossary = []
                self.glossary_load_warnings = [f"glossary unreadable ({e}); treated as empty"]
            self.settings.set("last_directory", str(path.parent))
            self._reconfigure_autosave()
            self.settings.save()
            self._update_title()
            self._update_count()
            self._update_file_meta_labels()
            self._main_stack.setCurrentIndex(1)   # switch from Welcome to editor page
            self._show_message(
                f"Loaded: {_file_label(path.name, self.file_version)}  ({len(self.entries)} strings)", 5000)
            if self.glossary_load_warnings:
                self._show_message("Glossary: " + "; ".join(self.glossary_load_warnings), 5000, "warning")
            for text, level in loaded.notices:
                self._show_message(text, 5000, level)
            self._create_backup(path)
        except Exception as e:
            QMessageBox.critical(self, "Open Error", f"Failed to load file:\n{e}")

    def _save(self):
        if not self.current_file:
            self._save_as(); return
        self._write(self.current_file)

    def _save_as(self):
        start = str(self.current_file.parent) if self.current_file else self.settings.get("last_directory") or ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save JSON Translation File", start,
            "JSON Files (*.json);;All Files (*)"
        )
        if path:
            self._write(Path(path))

    def _write_files(self, path: Path) -> None:
        """Save the open entries to *path* and its sidecar. The sidecar is skipped only when it is
        the open file's own and could not be read on open (it would be overwritten with defaults)."""
        same_file = self.current_file is not None and path == self.current_file
        save_translation_file(path, self.entries, self.json_style, self.header,
                              write_meta=not (self._meta_blocked and same_file))

    def _write(self, path: Path):
        try:
            self._write_files(path)
        except MetadataWriteError as e:
            _log_error(f"writing the sidecar of {path}", e)
            self._after_write(path)
            self.is_modified = True
            self._update_title()
            QMessageBox.critical(
                self, "Save Error",
                f"{path.name} was saved, but its metadata file ({meta_path_for(path).name}) could "
                "not be written. Statuses, translators and dates are not saved yet; Save again to retry.")
            return
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save:\n{e}")
            return
        self._after_write(path)
        self._update_title()
        self._show_message(f"Saved: {_file_label(path.name, self.file_version)}", 4000)

    def _after_write(self, path: Path) -> None:
        """State after the language file reached disk (with or without its sidecar)."""
        if self.current_file is None or path != self.current_file:
            self._meta_blocked = False   # a new file's sidecar is ours to write
        self.current_file = path
        self.is_modified  = False
        self.round_trips  = True         # it is in our own style now
        # Save As can point current_file at a different file than the one that was open --
        # re-derive the paired glossary so GlossaryDialog and translations use the new one.
        self.glossary_path = glossary_path_for(path)
        try:
            self.glossary, self.glossary_load_warnings = parse_glossary(self.glossary_path)
        except Exception as e:
            self.glossary = []
            self.glossary_load_warnings = [f"glossary unreadable ({e}); treated as empty"]

    def _close_file(self):
        """Close the open file and return to the empty no-file state, so
        changes can be discarded without quitting the app (File → Close File)."""
        if not self.current_file:
            return          # nothing open; a dialog here would just be noise
        if not self._confirm_close_file():
            return
        closed_label = _file_label(self.current_file.name, self.file_version)
        self.entries  = []
        self.current_file = None
        self.is_modified  = False
        self.header       = FileHeader()
        self.json_style   = DEFAULT_JSON_STYLE
        self.round_trips  = True
        self._meta_blocked = False
        self.glossary = []
        self.glossary_path = None
        self.glossary_load_warnings = []
        self.model.load(self.entries)
        self._apply_filters()
        self._reconfigure_autosave()    # current_file is None -> timer stops
        self._update_title()
        self._update_count()
        self._update_file_meta_labels()
        self._main_stack.setCurrentIndex(0)   # back to Welcome screen
        self._show_message(f"Closed: {closed_label}", 4000)

    # ── Editing ────────────────────────────────────────────────

    def _edit_row(self, index: QModelIndex):
        entry = self.model.get_entry(index.row())
        if entry is None: return
        shortcuts    = self.settings.get("shortcuts", {})
        transl_cfg   = self.settings.get("translation", {})
        dlg = EditDialog(self.model, index.row(), self.settings.get_font(),
                         shortcuts=shortcuts,
                         target_culture=self.target_culture,
                         transl_cfg=transl_cfg,
                         parent=self)
        dlg.exec()
        # Navigation commits rows in-place and emits dataChanged as it goes.
        # We only need to refresh the file-modified state here.
        if dlg.was_modified():
            self.is_modified = True
            self._update_title()
            self._update_count()

    def _edit_selected(self):
        idxs = self.table.selectionModel().selectedRows()
        if idxs: self._edit_row(idxs[0])

    def _bulk_status(self, status: str):
        idxs = self.table.selectionModel().selectedRows()
        if not idxs: return
        for idx in idxs:
            entry = self.model.get_entry(idx.row())
            if entry:
                entry.status = status
                entry.modify_date = datetime.now().strftime(DATE_FMT)
        self.is_modified = True
        self.model.dataChanged.emit(
            self.model.index(0, 0),
            self.model.index(self.model.rowCount() - 1, len(HEADERS) - 1)
        )
        self._update_title()

    def _delete_entries(self, entries: List[StringEntry],
                         parent_widget: Optional[QWidget] = None) -> bool:
        """Delete *entries* from the loaded file. In-memory only -- a
        subsequent Save is required to persist it, same as any other edit.

        Entries are matched by object identity, not source text: unlike the
        Merge dialog's deletion handling (which matches entries across two
        independently parsed files by name, since it has no shared object
        identity to rely on), every entry passed here is already a live
        object out of self.entries, so identity comparison is simpler and
        stays correct even for entries that happen to share source text.

        Returns True if entries were actually removed, False if *entries*
        was empty or the user declined the confirmation.
        """
        if not entries:
            return False
        parent_widget = parent_widget or self
        if len(entries) == 1:
            msg = (f"Delete this string?\n\n{entries[0].name}\n\n"
                   "This removes it from the file. The change is not "
                   "written to disk until you Save.")
        else:
            msg = (f"Delete {len(entries)} selected strings?\n\n"
                   "This removes them from the file. The change is not "
                   "written to disk until you Save.")
        r = QMessageBox.question(
            parent_widget, "Delete Selected", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if r != QMessageBox.Yes:
            return False

        delete_ids = {id(e) for e in entries}
        self.entries = [e for e in self.entries if id(e) not in delete_ids]
        self.is_modified = True
        self.model.load(self.entries)
        self._apply_filters()
        self._update_title()
        self._update_count()
        return True

    def _delete_selected(self):
        idxs = self.table.selectionModel().selectedRows()
        if not idxs: return
        entries = [e for e in (self.model.get_entry(idx.row()) for idx in idxs) if e is not None]
        if not entries: return
        self._delete_entries(entries)

    # ── Context menu ───────────────────────────────────────────

    def _table_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid(): return
        menu = QMenu(self)
        menu.addAction("✏️  Edit",               lambda: self._edit_row(idx))
        menu.addSeparator()
        for s in STATUSES:
            menu.addAction(f"→ Mark as {s}", lambda st=s: self._bulk_status(st))
        menu.addSeparator()
        menu.addAction("🗑️  Delete Selected", self._delete_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ── Filters ────────────────────────────────────────────────

    def _apply_filters(self):
        eng = self.filter_panel.engine
        pattern = eng.compiled_search_pattern()
        visible = [e for e in self.entries if eng.matches(e, pattern)]
        self.model.apply_filters(visible)
        self._update_count()

    def _refresh_filter(self):
        """Re-apply the current filters — useful after edits change entry status."""
        self._apply_filters()
        self._show_message("Filter refreshed", 3000)

    # ── Font ───────────────────────────────────────────────────

    def _choose_font(self):
        current = self.settings.get_font()
        dlg = FontSettingsDialog(current, parent=self)
        if dlg.exec() == QDialog.Accepted:
            try:
                font = dlg.get_font()
                family = font.family()
                size   = font.pointSize()
                if not family:
                    raise ValueError("Empty font family returned")
                if size <= 0:
                    size = 10
                self.settings.set("font_family", family)
                self.settings.set("font_size",   size)
                self.settings.save()
                self._apply_app_font()
            except Exception as e:
                QMessageBox.warning(self, "Font Error", f"Could not apply font:\n{e}")

    # ── Helpers ────────────────────────────────────────────────

    def _confirm_discard(self) -> bool:
        if not self.is_modified: return True
        r = QMessageBox.question(
            self, "Unsaved Changes", "You have unsaved changes. Discard them?",
            QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel
        )
        return r == QMessageBox.Discard

    def _confirm_close_file(self) -> bool:
        """Save/Discard/Cancel prompt for File → Close File; True means proceed.

        Unlike _confirm_discard() (Discard/Cancel, used by Open and app exit),
        closing a file offers to save first, since the file stays reachable
        afterwards only through the filesystem."""
        if not self.is_modified: return True
        r = QMessageBox.question(
            self, "Unsaved Changes",
            "You have unsaved changes. Save them before closing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save
        )
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Save:
            self._save()
            # _write() leaves is_modified True and shows its own error dialog if
            # the save failed, so this is the honest "did it land?" check --
            # never close a file whose save just failed.
            return not self.is_modified
        return True

    def _update_title(self):
        name = self.current_file.name if self.current_file else "No file"
        mod  = " ●" if self.is_modified else ""
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} — {name}{mod}")
        if self.is_modified:
            self._mod_kind = "modified"
            self._mod_text = "Unsaved changes"
        else:
            self._mod_kind = ""
            self._mod_text = ""
        self._update_dynamic_label()

    def _update_count(self):
        total   = len(self.entries)
        visible = self.model.rowCount()
        by_status = {}
        for e in self.model.visible_entries():
            by_status[e.status] = by_status.get(e.status, 0) + 1
        parts = [f"Showing {visible}/{total}"]
        for s in STATUSES:
            if s in by_status:
                parts.append(f"{s}: {by_status[s]}")
        self.count_label.setText("   •   ".join(parts))
        self._refresh_hint.setVisible(total > 0 and visible < total)
        self._table_stack.setCurrentIndex(1 if (total > 0 and visible == 0) else 0)

    def eventFilter(self, watched, event):
        """Clear the table's row-hover highlight when the pointer leaves the viewport."""
        if watched is self.table.viewport() and event.type() == QEvent.Leave:
            self._status_delegate.set_hover_row(-1)
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if (len(urls) == 1 and urls[0].isLocalFile()
                and urls[0].toLocalFile().lower().endswith(".json")):
            event.acceptProposedAction()

    def dropEvent(self, event):
        event.acceptProposedAction()
        path = Path(event.mimeData().urls()[0].toLocalFile())
        if not self._confirm_discard():
            return
        self._load(path)

    def closeEvent(self, event):
        if self._confirm_discard():
            # Must be set before the processEvents() flush below: a delivered
            # restore continuation reaches _load() -> _create_backup(), and
            # any thread started there would never be waited on by the loop
            # that has already run. _create_backup() honours this flag.
            self._is_closing = True
            for t in list(self._backup_threads):
                if t.isRunning():
                    t.wait(2000)
            # Best-effort: cancel whatever claude_subscription call may still be
            # in flight before waiting, so its abandoned Task unwinds in ~1
            # event-loop tick instead of running out its up-to-90s timeout
            # budget (60s call + 30s reconnect fallback) against a 2s wait.
            if self.claude_session is not None:
                self.claude_session.cancel_current()
            for t in list(self._translation_threads):
                t.requestInterruption()   # ends a Google retry pause early
                if t.isRunning():
                    t.wait(2000)
            # QThread.wait() blocks until run() returns, but does not pump the
            # event loop that delivers a queued cross-thread signal to its slot
            # -- without this, a safety backup's finished signal could still be
            # sitting undelivered when the app exits, meaning
            # _do_restore_after_backup() (the code that actually writes the
            # restored file) never runs. A few processEvents() passes flush any
            # already-queued signal delivery before the window actually closes.
            for _ in range(5):
                QApplication.processEvents()
            if self.claude_session is not None:
                self.claude_session.close()
            self.settings.save()
            event.accept()
        else:
            event.ignore()


# ══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════

def main():
    if sys.platform == "win32":
        # Without an explicit AppUserModelID, Windows keys the taskbar button's
        # icon/grouping to python.exe itself rather than this window, so the
        # taskbar shows the generic Python icon even after setWindowIcon() below.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JSONTranslationEditor")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))

    win = MainWindow()

    # Open file from command line if given
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.exists():
            win._load(p)

    win.show()

    # pyi_splash only exists inside a frozen build made with PyInstaller's
    # --splash flag; closes the bootloader-level splash screen now that the
    # real window is visible, so there's no gap where nothing is on screen.
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
