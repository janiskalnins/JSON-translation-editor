"""Geometry + glyph check for the shared QScrollBar QSS (`_scrollbar_qss`).

Offscreen, no MainWindow. For both themes and several UI font sizes it builds a
very long table (vertical bar), a very wide one (horizontal bar) and a short
text box (100 px, the height the Edit dialog's source box was once capped at) and
checks, at scroll min/mid/max:

  * the handle never overlaps the arrow buttons (the original bug: at the ends
    the handle sat on top of the up/down arrow),
  * the handle is long enough to grab -- 4x the bar thickness on tables, where
    thousands of rows shrink it to nothing, 2x elsewhere (the "tiny pill" bug),
  * the handle can still MOVE: a fixed minimum must not fill a short bar's whole
    groove, or it looks like nothing is hidden and cannot be dragged,
  * an arrow glyph is actually painted on each button (styling the buttons makes
    Qt stop drawing its own glyph, so a missing image leaves them blank).

Also checks the arrow files' failure handling: an unwritable or failing cache
folder must leave correctly placed (blank) buttons and never raise, a corrupt
or planted file is repaired, and losing a write race to another instance is not
a failure. The cache folder must not be under the shared temp root.

Run:  python tests/check_scrollbar.py      (exit code 0 = all passed)
"""

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider, QTableWidget, QTextEdit

import json_translation_editor as jte

ROWS, COLS = 11000, 2000
FONT_PTS = (7, 10, 12, 14)
POSITIONS = ("min", "mid", "max")
LIST_HANDLE_FACTOR = 4     # tables / trees
SHORT_HANDLE_FACTOR = 2    # text boxes and any other short bar
GLYPH_MIN_DIFF = 90        # summed |dR|+|dG|+|dB| vs the button background
TEXT_BOX_HEIGHT = 100      # EditDialog caps its source box at this height


def _rects(sb):
    opt = QStyleOptionSlider()
    sb.initStyleOption(opt)
    style = sb.style()

    def rect(sc):
        return style.subControlRect(QStyle.CC_ScrollBar, opt, sc, sb)
    return (rect(QStyle.SC_ScrollBarSlider),
            rect(QStyle.SC_ScrollBarSubLine),
            rect(QStyle.SC_ScrollBarAddLine))


def _span(rect, vertical):
    """(start, end) of *rect* along the bar's own axis."""
    return (rect.top(), rect.bottom() + 1) if vertical else (rect.left(), rect.right() + 1)


def _has_glyph(image, rect, background):
    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            c = QColor(image.pixel(x, y))
            diff = (abs(c.red() - background.red()) + abs(c.green() - background.green())
                    + abs(c.blue() - background.blue()))
            if diff >= GLYPH_MIN_DIFF:
                return True
    return False


def _position_value(sb, position):
    return {"min": sb.minimum(), "mid": (sb.minimum() + sb.maximum()) // 2,
            "max": sb.maximum()}[position]


def check_bar(app, sb, vertical, t, px, min_factor, expect_glyphs, label):
    """Return a list of failure strings for one scrollbar."""
    failures = []
    background = QColor(t["bg3"])
    starts = {}
    for position in POSITIONS:
        sb.setValue(_position_value(sb, position))
        app.processEvents()
        slider, sub, add = _rects(sb)
        where = f"{label} {'vertical' if vertical else 'horizontal'} @{position}"
        s0, s1 = _span(slider, vertical)
        starts[position] = s0
        sub_end = _span(sub, vertical)[1]
        add_start = _span(add, vertical)[0]
        if s0 < sub_end:
            failures.append(f"{where}: handle starts at {s0}, inside the sub-line button (ends {sub_end})")
        if s1 > add_start:
            failures.append(f"{where}: handle ends at {s1}, inside the add-line button (starts {add_start})")
        if s1 - s0 < px * min_factor:
            failures.append(f"{where}: handle is {s1 - s0}px, minimum is {px * min_factor}px")
        if expect_glyphs:
            image = sb.grab().toImage()
            for name, button in (("sub-line", sub), ("add-line", add)):
                if not _has_glyph(image, button, background):
                    failures.append(f"{where}: no arrow glyph painted on the {name} button")
    travel = starts["max"] - starts["min"]
    if travel < px:
        failures.append(f"{label} {'vertical' if vertical else 'horizontal'}: handle travels only "
                        f"{travel}px between min and max (fills its groove)")
    return failures


def _text_box():
    edit = QTextEdit()
    edit.setPlainText("\n".join(f"line {i}" for i in range(300)))
    edit.setFixedSize(400, TEXT_BOX_HEIGHT)
    return edit


def run_theme_font(app, theme, pt, expect_glyphs=True):
    t = jte.THEMES[theme]
    px = max(12, pt + 5)
    qss = f"QWidget {{ background: {t['bg']}; color: {t['fg']}; }}\n" + jte._scrollbar_qss(t, px)
    label = f"{theme}/{pt}pt"
    failures = []
    cases = (
        ("table", lambda: QTableWidget(ROWS, 3), True, LIST_HANDLE_FACTOR),
        ("wide table", lambda: QTableWidget(3, COLS), False, LIST_HANDLE_FACTOR),
        ("text box", _text_box, True, SHORT_HANDLE_FACTOR),
    )
    for name, factory, vertical, min_factor in cases:
        widget = factory()
        widget.setStyleSheet(qss)
        if name != "text box":
            widget.resize(600, 700)
        widget.show()
        app.processEvents()
        sb = widget.verticalScrollBar() if vertical else widget.horizontalScrollBar()
        failures += check_bar(app, sb, vertical, t, px, min_factor, expect_glyphs, f"{label} {name}")
        widget.close()
    return failures


def run_all(app, expect_glyphs=True):
    failures = []
    for theme in jte.THEMES:
        for pt in FONT_PTS:
            failures += run_theme_font(app, theme, pt, expect_glyphs)
    return failures


@contextmanager
def _patched(name, value):
    real = getattr(jte, name)
    setattr(jte, name, value)
    try:
        yield
    finally:
        setattr(jte, name, real)


@contextmanager
def _isolated_arrow_dir():
    """Point the arrow cache at a throwaway folder so a run never touches the user's real one."""
    with tempfile.TemporaryDirectory() as tmp:
        with _patched("_glyph_cache_dir", lambda: Path(tmp) / "arrows"):
            yield Path(tmp) / "arrows"


def check_cache_dir_not_under_shared_temp():
    directory = jte._glyph_cache_dir().resolve()
    shared_temp = Path(tempfile.gettempdir()).resolve()
    if directory == shared_temp or shared_temp in directory.parents:
        return [f"arrow cache {directory} is under the shared temp root {shared_temp}"]
    return []


def check_unwritable_dir_falls_back(app):
    """Arrow folder unusable -> no image rules, but geometry must still be right."""
    with tempfile.NamedTemporaryFile() as blocker:
        with _patched("_glyph_cache_dir", lambda: Path(blocker.name) / "arrows"):  # parent is a file
            failures = run_all(app, expect_glyphs=False)
            if "image:" in jte._scrollbar_qss(jte.THEMES["dark"], 15):
                failures.append("fallback: qss still references arrow images although none could be written")
    return failures


def check_failures_are_contained():
    """Best-effort cosmetic work: nothing raised here may stop the app from starting."""
    failures = []
    for label, error in (("cache folder lookup fails", OSError("no cache folder")),
                         ("unexpected error", ValueError("boom"))):
        def fail(error=error):
            raise error
        with _patched("_glyph_cache_dir", fail):
            try:
                result = jte._write_scrollbar_arrows("#9a9a9a", 15)
            except Exception as e:
                failures.append(f"{label}: {type(e).__name__} escaped _write_scrollbar_arrows")
                continue
        if result is not None:
            failures.append(f"{label}: expected None, got {result!r}")

    def failing_renderer(*args):
        raise ValueError("render boom")
    with _patched("_render_scrollbar_arrow_png", failing_renderer):
        try:
            result = jte._write_scrollbar_arrows("#9a9a9a", 15)
        except Exception as e:
            failures.append(f"failing renderer: {type(e).__name__} escaped _write_scrollbar_arrows")
        else:
            if result is not None:
                failures.append(f"failing renderer: expected None, got {result!r}")
    return failures


def check_corrupt_file_is_repaired():
    with _isolated_arrow_dir():
        first = jte._write_scrollbar_arrows("#9a9a9a", 15)
        target = Path(next(iter(first.values())))
        good = target.read_bytes()
        target.write_bytes(b"not a png")
        jte._write_scrollbar_arrows("#9a9a9a", 15)
        return [] if target.read_bytes() == good else ["a corrupt arrow file was not repaired"]


def check_lost_write_race_is_not_a_failure():
    with _isolated_arrow_dir():
        real_write = jte._atomic_write_bytes

        def other_instance_wins(path, data):
            real_write(path, data)
            raise PermissionError("os.replace lost the race")
        with _patched("_atomic_write_bytes", other_instance_wins):
            result = jte._write_scrollbar_arrows("#9a9a9a", 15)
    return [] if result is not None else ["losing the write race to another instance discarded the arrows"]


def main():
    app = QApplication.instance() or QApplication([])
    failures = check_cache_dir_not_under_shared_temp()
    with _isolated_arrow_dir():
        failures += run_all(app)
    failures += check_unwritable_dir_falls_back(app)
    failures += check_failures_are_contained()
    failures += check_corrupt_file_is_repaired()
    failures += check_lost_write_race_is_not_a_failure()
    for f in failures:
        print("FAIL", f)
    print(f"{'FAILED' if failures else 'PASSED'}: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
