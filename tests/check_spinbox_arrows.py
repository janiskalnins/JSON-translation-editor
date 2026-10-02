"""Glyph check for the up/down arrows of the dialogs' themed spin boxes (`_spinbox_qss`).

A `QSpinBox { background / border / padding }` rule moves the widget to style-sheet rendering,
where its up/down buttons and arrows, left unstyled, collapse to a 14 px strip holding a 3-4 px
speck in a colour that barely differs from the field ("the arrows are barely visible" in the
Choose UI Font dialog; Autosave & Backup has the identical rule). Offscreen, under the same Fusion
style and theme palette `main()` sets, for both themes and several UI font sizes, this builds the
real Choose UI Font, Autosave & Backup and File Properties dialogs and checks each button of a spin box for:

  * enabled:  an arrow of a usable size, clearly lighter/darker than the button fill
              (>= 4.5:1, the app's text-contrast floor),
  * disabled: a dimmed arrow (dlg_btn_dis_fg) so the control still reads as a spin box.

(Whether the value text still fits beside the buttons cannot be checked here: offscreen Qt has no
fonts, so text metrics are meaningless -- see "Testing" in CLAUDE.md for the manual check.)

Also checks the fallback: with the glyph cache folder unusable `_spinbox_qss` must not raise, must
carry no image rule, and must still style the buttons.

Run:  python tests/check_spinbox_arrows.py      (exit code 0 = all passed)
"""

import os
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSpinBox, QWidget

import json_translation_editor as jte

FONT_PTS = (8, 10, 14)
INSET = 1                # stay clear of a button's own edge
GLYPH_MIN_DIFF = 90      # summed |dR|+|dG|+|dB| against the button fill
MIN_GLYPH_WIDTH = 8      # the broken arrow was 3-4 px wide
MIN_GLYPH_HEIGHT = 4
MIN_CONTRAST = 4.5
DIMMED_TOLERANCE = 30


class _StubSettings:
    """Just enough of Settings for the two dialogs; every read falls back to its default."""

    def __init__(self, pt):
        self._pt = pt
        self.data = {}

    def get(self, key, default=None):
        return default

    def get_font(self):
        return QFont("Segoe UI", self._pt)


class _StubMain(QWidget):
    """Stands in for MainWindow: the dialogs only ask their parent for the theme."""

    def __init__(self, theme, pt):
        super().__init__()
        self._theme = theme
        self.settings = _StubSettings(pt)

    def _get_theme(self):
        return jte.THEMES[self._theme]


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


def _glyph(spin, sub_control):
    """(width, height, colour of the strongest glyph pixel, button fill colour) of what is drawn
    inside one button; width and height are 0 when nothing but the fill is there."""
    opt = QStyleOptionSpinBox()
    spin.initStyleOption(opt)
    rect = spin.style().subControlRect(QStyle.CC_SpinBox, opt, sub_control, spin)
    rect = rect.adjusted(INSET, INSET, -INSET, -INSET)
    image = spin.grab().toImage()
    pixels = [(x, y, QColor(image.pixel(x, y)))
              for y in range(rect.top(), rect.bottom() + 1)
              for x in range(rect.left(), rect.right() + 1)]
    fill = QColor(Counter(c.name() for _, _, c in pixels).most_common(1)[0][0])
    strongest = max((c for _, _, c in pixels), key=lambda c: _diff(c, fill))
    if _diff(strongest, fill) < GLYPH_MIN_DIFF:
        return 0, 0, fill, fill
    # Half of the glyph's own peak contrast: the size then means the same for a dim disabled arrow
    # as for a vivid one, whose faint antialiased edges would otherwise inflate it.
    edge = _diff(strongest, fill) / 2
    hits = [(x, y) for x, y, c in pixels if _diff(c, fill) >= edge]
    xs, ys = [h[0] for h in hits], [h[1] for h in hits]
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1, strongest, fill


def _dialogs(app, theme, pt):
    """The real dialogs, built under the app's own style/palette/font. The Autosave & Backup one
    gives both states from its defaults: autosave off disables `_as_spin`, backup on enables the
    others."""
    app.setFont(QFont("Segoe UI", pt))
    stub = _StubMain(theme, pt)
    jte.MainWindow._apply_palette(stub)
    font_dlg = jte.FontSettingsDialog(QFont("Segoe UI", pt), stub)
    backup_dlg = jte.AutosaveBackupDialog(stub.settings, stub)
    facts = jte.FileFacts(file_name="Latvian.xml", folder="C:/x", size_bytes=1, modified=0.0,
                          total=0, by_status={}, untranslated=0, tablet=0)
    props_dlg = jte.FilePropertiesDialog("lv-LV", "Latviešu", "4.1.1220", facts, False, stub)
    for dlg in (font_dlg, backup_dlg, props_dlg):
        dlg.show()
    app.processEvents()
    return stub, font_dlg, backup_dlg, props_dlg


def check_arrows(app):
    failures = []
    for theme, t in jte.THEMES.items():
        for pt in FONT_PTS:
            stub, font_dlg, backup_dlg, props_dlg = _dialogs(app, theme, pt)
            cases = [("Choose UI Font size", font_dlg._size_spin, True),
                     ("Autosave interval", backup_dlg._as_spin, False),
                     ("Backup count", backup_dlg._bk_spin, True),
                     ("Backup skip window", backup_dlg._bk_min_interval_spin, True)]
            cases += [(f"File Properties version part {i + 1}", spin, True)
                      for i, spin in enumerate(props_dlg._version_spins)]
            for name, spin, enabled in cases:
                if spin.isEnabled() != enabled:
                    failures.append(f"{theme} {pt}pt {name}: test setup expected enabled={enabled}")
                    continue
                for label, sub in (("up", QStyle.SC_SpinBoxUp), ("down", QStyle.SC_SpinBoxDown)):
                    width, height, color, fill = _glyph(spin, sub)
                    where = f"{theme} {pt}pt {name} {label}"
                    if width < MIN_GLYPH_WIDTH or height < MIN_GLYPH_HEIGHT:
                        failures.append(f"{where}: arrow is {width}x{height}px, "
                                        f"needs at least {MIN_GLYPH_WIDTH}x{MIN_GLYPH_HEIGHT}")
                    elif enabled and _contrast(color, fill) < MIN_CONTRAST:
                        failures.append(f"{where}: arrow contrast {_contrast(color, fill):.1f}:1, "
                                        f"needs {MIN_CONTRAST}:1")
                    elif not enabled and _diff(color, QColor(t["dlg_btn_dis_fg"])) > DIMMED_TOLERANCE:
                        failures.append(f"{where}: disabled arrow {color.name()} is not the "
                                        f"dimmed {t['dlg_btn_dis_fg']}")
            for dlg in (font_dlg, backup_dlg, props_dlg):
                dlg.close()
            stub.close()
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


def check_unwritable_folder_falls_back():
    failures = []
    with tempfile.NamedTemporaryFile() as blocker:
        with _patched("_glyph_cache_dir", lambda: Path(blocker.name) / "glyphs"):  # parent is a file
            for theme, t in jte.THEMES.items():
                try:
                    qss = jte._spinbox_qss(t, 10)
                except Exception as e:
                    failures.append(f"{theme}: {type(e).__name__} escaped _spinbox_qss")
                    continue
                if "image:" in qss:
                    failures.append(f"{theme}: qss references an arrow image although none could be written")
                if "::up-button" not in qss:
                    failures.append(f"{theme}: the fallback lost the button rules")
    return failures


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")     # what main() does; the platform default draws spin boxes differently
    with _isolated_glyph_dir():
        failures = check_arrows(app)
    failures += check_unwritable_folder_falls_back()
    for f in failures:
        print("FAIL", f)
    print(f"{'FAILED' if failures else 'PASSED'}: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
