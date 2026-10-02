"""Size check for the Translation Settings dialog when the engine changes.

Switching the engine shows one engine's settings group and hides the others. The dialog used to
grow when a bigger group appeared and never shrink back, so after Claude (Subscription) a small
engine sat in a tall window with the leftover height spread as gaps between the groups. Offscreen,
under the same Fusion style `main()` sets, for both themes and two UI font sizes, this checks:

  * every fresh dialog has the same width, whatever engine it opens on (sized once, to the widest
    engine group),
  * switching through every engine -- including to Claude (Subscription) and back -- never changes
    the width, and leaves the height equal to a fresh dialog opened on that engine (it shrinks),
  * the height is never below what the content needs at that width (nothing clipped),
  * a width the user set by dragging is kept across a switch,
  * each visible word-wrapped hint is given only the height its text needs at its width (a
    QFormLayout row with no label widget sized it at the wrong width, leaving a blank band above
    and below the hint),
  * a switch resizes the window once, straight to its final size, and never moves it. Qt's own
    automatic grow used to run first, overshooting (it sized for the 500 px minimum width); on
    Windows at 150 % scaling and a 14 pt font, Windows moved that grow 62 px up, so the dialog
    walked up the screen with every switch. Offscreen cannot show that move, only the overshoot,
  * the minimum size keeps the content unclipped: dragging the window to its minimum width, or a
    long Test Connection error, still leaves every row its full height.

(Offscreen Qt has no fonts, so the real look -- wrapped hints, spacing -- stays a manual item.)

Run:  python tests/check_translation_settings_size.py      (exit code 0 = all passed)
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget

import xml_translation_editor as xte

FONT_PTS = (10, 14, 18, 24)
TOLERANCE_PX = 1
# Claude (Subscription) sits between two small groups so the "grow, then fail to shrink" path runs.
SWITCH_ORDER = ("google_dt", "claude_subscription", "google_dt", "deepl", "none", "claude",
                "libretranslate", "mymemory_dt", "microsoft_dt", "claude_subscription", "none")


class _StubSettings:
    """Just enough of Settings for the dialog: the engine to open on, defaults for the rest."""

    DEFAULTS = xte.Settings.DEFAULTS

    def __init__(self, pt, engine):
        self._pt = pt
        self._engine = engine

    def get(self, key, default=None):
        if key == "translation":
            return {"engine": self._engine}
        return default

    def get_font(self):
        return QFont("Segoe UI", self._pt)


class _StubMain(QWidget):
    """Stands in for MainWindow: the dialog only asks its parent for the theme."""

    def __init__(self, theme):
        super().__init__()
        self._theme = theme
        self.target_culture = ""
        self.claude_session = None

    def _get_theme(self):
        return xte.THEMES[self._theme]


class _GeometrySpy(QObject):
    """Records every size and position the dialog passes through."""

    def __init__(self):
        super().__init__()
        self.sizes = []
        self.moves = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self.sizes.append(event.size().toTuple())
        elif event.type() == QEvent.Move:
            self.moves.append(event.pos().toTuple())
        return False


def _open(main, pt, engine):
    dlg = xte.TranslationSettingsDialog(_StubSettings(pt, engine), parent=main)
    dlg.show()
    QApplication.processEvents()
    return dlg


def _select(dlg, engine):
    dlg._engine_combo.setCurrentIndex(dlg._engine_combo.findData(engine))
    QApplication.processEvents()


def _needed_height(dlg):
    lay = dlg.layout()
    if lay.hasHeightForWidth():
        return lay.heightForWidth(dlg.width())
    return lay.sizeHint().height()


def _visible_hints(dlg):
    hints = (dlg._claude_hint, dlg._claude_sub_hint, dlg._deepl_hint, dlg._libre_hint,
             dlg._google_hint, dlg._mymemory_hint, dlg._microsoft_hint)
    return [h for h in hints if h.isVisibleTo(dlg)]


def _run_case(theme, pt, failures):
    tag = f"{theme} {pt}pt"
    main = _StubMain(theme)
    engines = [k for k in SWITCH_ORDER if k]

    fresh = {}
    for engine in dict.fromkeys(engines):
        dlg = _open(main, pt, engine)
        fresh[engine] = (dlg.width(), dlg.height())
        dlg.close()
        dlg.deleteLater()
    widths = {w for w, _ in fresh.values()}
    if max(widths) - min(widths) > TOLERANCE_PX:
        failures.append(f"{tag}: fresh widths differ by engine: {fresh}")

    dlg = _open(main, pt, SWITCH_ORDER[0])
    start_width = dlg.width()
    for engine in SWITCH_ORDER[1:]:
        spy = _GeometrySpy()
        dlg.installEventFilter(spy)
        _select(dlg, engine)
        dlg.removeEventFilter(spy)
        width, height = dlg.width(), dlg.height()
        passed_through = [s for s in spy.sizes if s != (width, height)]
        if passed_through:
            failures.append(f"{tag}: switch to {engine} passed through {passed_through} "
                            f"before settling at {(width, height)}")
        if spy.moves:
            failures.append(f"{tag}: switch to {engine} moved the window to {spy.moves}")
        if dlg.minimumHeight() < _needed_height(dlg) - TOLERANCE_PX:
            failures.append(f"{tag}: on {engine} the minimum height {dlg.minimumHeight()} "
                            f"lets a drag clip content (needs {_needed_height(dlg)})")
        if dlg.minimumWidth() < dlg.layout().minimumSize().width():
            failures.append(f"{tag}: on {engine} the minimum width {dlg.minimumWidth()} is below "
                            f"the content's {dlg.layout().minimumSize().width()}")
        if abs(width - start_width) > TOLERANCE_PX:
            failures.append(f"{tag}: width changed to {width} (was {start_width}) on {engine}")
        ref_height = fresh[engine][1]
        if abs(height - ref_height) > TOLERANCE_PX:
            failures.append(f"{tag}: height {height} on {engine}, a fresh dialog has {ref_height}")
        if height < _needed_height(dlg) - TOLERANCE_PX:
            failures.append(f"{tag}: height {height} on {engine} clips content "
                            f"(needs {_needed_height(dlg)})")
        for hint in _visible_hints(dlg):
            needed = hint.heightForWidth(hint.width())
            if abs(hint.height() - needed) > TOLERANCE_PX:
                failures.append(f"{tag}: hint on {engine} is {hint.height()} px tall, "
                                f"its text needs {needed}")

    dragged_width = start_width + 120
    dlg.resize(dragged_width, dlg.height())
    QApplication.processEvents()
    _select(dlg, "claude_subscription")
    _select(dlg, "google_dt")
    if abs(dlg.width() - dragged_width) > TOLERANCE_PX:
        failures.append(f"{tag}: user width {dragged_width} not kept (now {dlg.width()})")
    if dlg.height() < _needed_height(dlg) - TOLERANCE_PX:
        failures.append(f"{tag}: height {dlg.height()} clips content after a drag")

    _select(dlg, "deepl")
    dlg.resize(dlg.minimumWidth(), dlg.height())
    QApplication.processEvents()
    if dlg.height() < _needed_height(dlg) - TOLERANCE_PX:
        failures.append(f"{tag}: at the minimum width {dlg.width()} the height {dlg.height()} "
                        f"clips content (needs {_needed_height(dlg)})")

    dlg._on_test_fail("connection refused " * 12)
    QApplication.processEvents()
    if dlg.height() < _needed_height(dlg) - TOLERANCE_PX:
        failures.append(f"{tag}: a long test error leaves the height {dlg.height()} clipping "
                        f"content (needs {_needed_height(dlg)})")
    dlg.close()
    dlg.deleteLater()
    main.deleteLater()
    QApplication.processEvents()


def _create_app():
    """Offscreen QApplication on a 1920 x 1080 screen. The default offscreen screen is 800 px
    wide, and offscreen text is drawn as boxes wider than real glyphs, so DeepL's long checkbox
    would need more than the dialog's screen-capped width and squeeze the layout below its minimum
    -- a squeeze no real monitor produces. Qt splits the platform string on ':', so the config
    path must not hold a drive letter: it is passed relative, from inside its own folder."""
    cfg_dir = tempfile.mkdtemp(prefix="xte_screen_")
    screen = {"name": "check", "x": 0, "y": 0, "width": 1920, "height": 1080,
              "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}
    Path(cfg_dir, "screen.json").write_text(json.dumps({"screens": [screen]}), encoding="utf-8")
    os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=screen.json"
    prev_cwd = os.getcwd()
    os.chdir(cfg_dir)
    try:
        app = QApplication(sys.argv)
    finally:
        os.chdir(prev_cwd)
        shutil.rmtree(cfg_dir, ignore_errors=True)
    return app


def main() -> int:
    app = _create_app()
    app.setStyle("Fusion")
    failures = []
    for theme in ("dark", "light"):
        for pt in FONT_PTS:
            _run_case(theme, pt, failures)
    for f in failures:
        print("FAIL:", f)
    print(f"{'PASSED' if not failures else 'FAILED'}: {len(failures)} failure(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
