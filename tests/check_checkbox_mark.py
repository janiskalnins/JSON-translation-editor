"""Check that a prominent checkbox shows its tick and a prominent radio button its dot
(`_prominent_checkbox_qss`), and that both indicators are sized from the UI font.

The tick used to be an inline SVG data: URI, which Qt's style sheets render as
nothing: a checked box was a plain accent-coloured square. Offscreen, for both
themes and for QCheckBox and QRadioButton alike, this checks the inside of the
indicator for:

  * checked:            a white mark (tick / dot) on the accent fill,
  * checked + disabled: a dimmed mark (dlg_btn_dis_fg) and NO white one, or the
                        indicator would look enabled,
  * unchecked:          one flat colour, no mark.

The indicator's side is `_indicator_px(pt)` plus its 2 px border each side, and it
grows with the font from 8 to 16 pt; it used to be a fixed 24 px at every size.

Also checks the fallback: with the glyph cache folder unusable the style sheet
must carry no image rule, must not raise, and a checked box must still fill.

Run:  python tests/check_checkbox_mark.py      (exit code 0 = all passed)
"""

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QCheckBox, QRadioButton, QStyle,
                               QStyleOptionButton)

import json_translation_editor as jte

MIN_TICK_PIXELS = 20   # a real tick is well over a hundred; anything under this is noise
INSET = 5              # stay clear of the indicator's own border
DIMMED_TOLERANCE = 30  # summed |dR|+|dG|+|dB|
BORDER_PX = 2          # the indicator's border, each side
KINDS = (QCheckBox, QRadioButton)
SIZES_PT = (8, 10, 12, 16)
# Offscreen Qt has no fonts and measures a point size smaller than Windows does (10 pt gives an
# 18 px indicator, not 24), so the mark checks run at the size whose offscreen indicator matches
# the 24 px the thresholds above were tuned for.
STATE_PT = 14


def _indicator_rect(button):
    opt = QStyleOptionButton()
    button.initStyleOption(opt)
    element = (QStyle.SE_RadioButtonIndicator if isinstance(button, QRadioButton)
               else QStyle.SE_CheckBoxIndicator)
    return button.style().subElementRect(element, opt, button)


def _interior_pixels(button):
    """The indicator's inside. A radio button's circle leaves its corners showing the background,
    so only its central square is taken."""
    rect = _indicator_rect(button)
    inset = round(rect.width() * 0.3) if isinstance(button, QRadioButton) else INSET
    rect = rect.adjusted(inset, inset, -inset, -inset)
    image = button.grab().toImage()
    return [QColor(image.pixel(x, y))
            for y in range(rect.top(), rect.bottom() + 1)
            for x in range(rect.left(), rect.right() + 1)]


def _is_white(color):
    return not min(color.red(), color.green(), color.blue()) < 235


def _is_close(color, other, tolerance):
    return (abs(color.red() - other.red()) + abs(color.green() - other.green())
            + abs(color.blue() - other.blue())) < tolerance


def _box(app, t, checked, enabled, kind=QCheckBox, pt=STATE_PT):
    button = kind("Option")
    button.setProperty("filterChk", True)
    button.setChecked(checked)
    button.setEnabled(enabled)
    button.setStyleSheet(f"{kind.__name__} {{ background: {t['bg']}; color: {t['fg']}; "
                         f"font-size: {pt}pt; }}\n" + jte._prominent_checkbox_qss(t, pt))
    button.show()
    app.processEvents()
    return button


def check_states(app):
    failures = []
    for theme, t in jte.THEMES.items():
        for kind in KINDS:
            tag = f"{theme} {kind.__name__}"
            checked = _interior_pixels(_box(app, t, True, True, kind))
            if sum(1 for p in checked if _is_white(p)) < MIN_TICK_PIXELS:
                failures.append(f"{tag}: checked shows no white mark")

            disabled = _interior_pixels(_box(app, t, True, False, kind))
            dimmed = QColor(t["dlg_btn_dis_fg"])
            if sum(1 for p in disabled if _is_close(p, dimmed, DIMMED_TOLERANCE)) < MIN_TICK_PIXELS:
                failures.append(f"{tag}: checked + disabled shows no dimmed mark")
            if any(_is_white(p) for p in disabled):
                failures.append(f"{tag}: checked + disabled still shows the enabled white mark")

            unchecked = _interior_pixels(_box(app, t, False, True, kind))
            if len({p.rgb() for p in unchecked}) != 1:
                failures.append(f"{tag}: unchecked is not one flat colour")
    return failures


def check_size_tracks_font(app):
    """The indicator is _indicator_px(pt) plus its border, and grows with the font."""
    failures = []
    t = jte.THEMES["dark"]
    for kind in KINDS:
        widths = []
        for pt in SIZES_PT:
            rect = _indicator_rect(_box(app, t, False, True, kind, pt))
            want = jte._indicator_px(pt) + 2 * BORDER_PX
            if (rect.width(), rect.height()) != (want, want):
                failures.append(f"{kind.__name__} {pt}pt: indicator {rect.width()}x{rect.height()}, "
                                f"want {want}x{want}")
            widths.append(rect.width())
        if widths != sorted(set(widths)):
            failures.append(f"{kind.__name__}: indicator does not grow with the font {widths}")
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
def _isolated_glyph_dir():
    """Point the glyph cache at a throwaway folder so a run never touches the user's real one."""
    with tempfile.TemporaryDirectory() as tmp:
        with _patched("_glyph_cache_dir", lambda: Path(tmp) / "glyphs"):
            yield


def check_unwritable_folder_falls_back(app):
    failures = []
    with tempfile.NamedTemporaryFile() as blocker:
        with _patched("_glyph_cache_dir", lambda: Path(blocker.name) / "glyphs"):  # parent is a file
            for theme, t in jte.THEMES.items():
                try:
                    qss = jte._prominent_checkbox_qss(t, 10)
                except Exception as e:
                    failures.append(f"{theme}: {type(e).__name__} escaped _prominent_checkbox_qss")
                    continue
                if "image:" in qss:
                    failures.append(f"{theme}: qss references a tick image although none could be written")
                fill = QColor(t["accent"]).rgb()
                if not any(p.rgb() == fill for p in _interior_pixels(_box(app, t, True, True))):
                    failures.append(f"{theme}: checked box lost its accent fill in the fallback")
    return failures


def main():
    app = QApplication.instance() or QApplication([])
    with _isolated_glyph_dir():
        failures = check_states(app)
        failures += check_size_tracks_font(app)
    failures += check_unwritable_folder_falls_back(app)
    for f in failures:
        print("FAIL", f)
    print(f"{'FAILED' if failures else 'PASSED'}: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
