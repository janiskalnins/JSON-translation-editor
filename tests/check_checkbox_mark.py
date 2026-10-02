"""Check that a prominent checkbox actually shows its tick (`_prominent_checkbox_qss`).

The tick used to be an inline SVG data: URI, which Qt's style sheets render as
nothing: a checked box was a plain accent-coloured square. Offscreen, for both
themes, this checks the inside of the indicator for:

  * checked:            a white tick on the accent fill,
  * checked + disabled: a dimmed tick (dlg_btn_dis_fg) and NO white one, or the
                        box would look enabled,
  * unchecked:          one flat colour, no tick.

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
from PySide6.QtWidgets import QApplication, QCheckBox, QStyle, QStyleOptionButton

import xml_translation_editor as xte

MIN_TICK_PIXELS = 20   # a real tick is well over a hundred; anything under this is noise
INSET = 5              # stay clear of the indicator's own border
DIMMED_TOLERANCE = 30  # summed |dR|+|dG|+|dB|


def _interior_pixels(checkbox):
    opt = QStyleOptionButton()
    checkbox.initStyleOption(opt)
    rect = checkbox.style().subElementRect(QStyle.SE_CheckBoxIndicator, opt, checkbox)
    rect = rect.adjusted(INSET, INSET, -INSET, -INSET)
    image = checkbox.grab().toImage()
    return [QColor(image.pixel(x, y))
            for y in range(rect.top(), rect.bottom() + 1)
            for x in range(rect.left(), rect.right() + 1)]


def _is_white(color):
    return not min(color.red(), color.green(), color.blue()) < 235


def _is_close(color, other, tolerance):
    return (abs(color.red() - other.red()) + abs(color.green() - other.green())
            + abs(color.blue() - other.blue())) < tolerance


def _box(app, t, checked, enabled):
    checkbox = QCheckBox("Option")
    checkbox.setProperty("filterChk", True)
    checkbox.setChecked(checked)
    checkbox.setEnabled(enabled)
    checkbox.setStyleSheet(f"QCheckBox {{ background: {t['bg']}; color: {t['fg']}; }}\n"
                           + xte._prominent_checkbox_qss(t))
    checkbox.show()
    app.processEvents()
    return checkbox


def check_states(app):
    failures = []
    for theme, t in xte.THEMES.items():
        checked = _interior_pixels(_box(app, t, True, True))
        if sum(1 for p in checked if _is_white(p)) < MIN_TICK_PIXELS:
            failures.append(f"{theme}: checked box shows no white tick")

        disabled = _interior_pixels(_box(app, t, True, False))
        dimmed = QColor(t["dlg_btn_dis_fg"])
        if sum(1 for p in disabled if _is_close(p, dimmed, DIMMED_TOLERANCE)) < MIN_TICK_PIXELS:
            failures.append(f"{theme}: checked + disabled box shows no dimmed tick")
        if any(_is_white(p) for p in disabled):
            failures.append(f"{theme}: checked + disabled box still shows the enabled white tick")

        unchecked = _interior_pixels(_box(app, t, False, True))
        if len({p.rgb() for p in unchecked}) != 1:
            failures.append(f"{theme}: unchecked box is not one flat colour")
    return failures


@contextmanager
def _patched(name, value):
    real = getattr(xte, name)
    setattr(xte, name, value)
    try:
        yield
    finally:
        setattr(xte, name, real)


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
            for theme, t in xte.THEMES.items():
                try:
                    qss = xte._prominent_checkbox_qss(t)
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
    failures += check_unwritable_folder_falls_back(app)
    for f in failures:
        print("FAIL", f)
    print(f"{'FAILED' if failures else 'PASSED'}: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
