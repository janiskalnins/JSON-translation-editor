"""Shared helpers for the tests/check_core_*.py suites. Not a check itself: tests/run_all.py only
runs files named check_*.py.

Import it first in every core check (import core_support as cs). The import switches Qt to the
offscreen platform, moves the working folder and sys.argv[0] (the app's backup root) into a scratch
folder, points the glyph cache there and creates the one QApplication, so no test can touch the
real settings file, backups or cache.
"""

import html
import os
import shutil
import sys
import tempfile
import time
import traceback
import unittest
import xml.etree.ElementTree as ET
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "data"
SCRATCH = Path(tempfile.mkdtemp(prefix="xte_core_"))
os.chdir(SCRATCH)
sys.argv[0] = str(SCRATCH / "check_core.py")
sys.path.insert(0, str(REPO))

from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox  # noqa: E402

import json_translation_editor as jte  # noqa: E402

APP = QApplication.instance() or QApplication([])
jte._glyph_cache_dir = lambda: SCRATCH / "glyphs"


def temp_dir() -> Path:
    """A fresh folder of the test's own, removed with SCRATCH when the suite ends."""
    return Path(tempfile.mkdtemp(dir=SCRATCH))


# ── Builders ────────────────────────────────────────────────────────────────

DEFAULT_DATE = jte.format_date_for_storage(date(2025, 2, 1))
HEADER = ('<?xml version="1.0" encoding="utf-8"?>\n'
          '<TRNExportImportModel Culture="lv-LV" DisplayLanguage="Latviešu" Version="4.1.1140">\n'
          '  <resources>\n')
FOOTER = '  </resources>\n</TRNExportImportModel>\n'


def row(name: str, text: str, translator: str = "Jane", status: str = "Complete",
        modify_date: str = DEFAULT_DATE, istablet: str = "false") -> str:
    """One <string> line, indented and ending in a newline, escaped exactly as the app writes it."""
    attrs = (f'name="{jte._escape_attr_value(name)}" '
             f'translator="{jte._escape_attr_value(translator)}" status="{status}" '
             f'modifyDate="{modify_date}" istablet="{istablet}"')
    return f'    <string {attrs}>{html.escape(text, quote=False)}</string>\n'


def xml_doc(rows: List[str], header: str = HEADER, newline: str = "\n", bom: bool = False) -> str:
    """A whole translation file as text, every newline written as *newline*."""
    text = (header + "".join(rows) + FOOTER).replace("\n", newline)
    return "\ufeff" + text if bom else text


def write_exact(path: Path, data: Union[str, bytes]) -> Path:
    """Write *data* byte for byte (a str as UTF-8, no newline translation); returns *path*."""
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return path


def make_entry(**fields: Any) -> "jte.StringEntry":
    values = dict(name="Save", translator="Jane", status="Complete", modify_date=DEFAULT_DATE,
                  istablet="false", text="Saglabāt", seg_idx=1)
    values.update(fields)
    return jte.StringEntry(**values)


# ── The oracle ──────────────────────────────────────────────────────────────

def assert_xml_intact(tc: unittest.TestCase, path: Path, expected_names: List[str]) -> None:
    """The independent judge of a saved file: xml.etree (not the app's regex parser) must find a
    well-formed file holding exactly *expected_names* as <string name> values, in order, none
    twice."""
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as e:
        tc.fail(f"{path.name} is not well-formed XML: {e}")
    names = [el.get("name") for el in root.iter("string")]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    tc.assertEqual(duplicates, [], f"{path.name} holds a name twice")
    tc.assertEqual(names, list(expected_names))


# ── Qt helpers ──────────────────────────────────────────────────────────────

def app() -> QApplication:
    return APP


def pump(times: int = 3) -> None:
    for _ in range(times):
        APP.processEvents()


def wait_until(condition: Callable[[], bool], timeout_s: float = 10.0) -> bool:
    """Process events until *condition* holds or the time runs out; returns the condition."""
    deadline = time.monotonic() + timeout_s
    while not condition() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.01)
    return condition()


@dataclass
class Modals:
    """What patched_modals() answers and what it was shown. A test may change *answers* at any
    time; a list value is used up one item per call."""
    answers: Dict[str, Any]
    shown: List[Tuple[str, str]] = field(default_factory=list)   # (kind, window title)

    def answer(self, key: str, default: Any) -> Any:
        value = self.answers.get(key, default)
        if isinstance(value, list):
            return value.pop(0) if value else default
        return value

    def titles(self, kind: str) -> List[str]:
        return [title for shown_kind, title in self.shown if shown_kind == kind]


@contextmanager
def patched_modals(**answers: Any) -> Iterator[Modals]:
    """Answer every modal the app can open from *answers* and record it: the QMessageBox static
    helpers (question/warning/critical/information), a QMessageBox built by hand (exec() records
    its title, clickedButton() returns the button whose text is answers["button"]), both file
    dialogs, and the startup translator-name prompt (always rejected)."""
    modals = Modals(answers=dict(answers))

    def static(kind: str, default: Any):
        def fake(parent, title, *args, **kwargs):
            modals.shown.append((kind, title))
            return modals.answer(kind, default)
        return staticmethod(fake)

    def fake_exec(box) -> int:
        modals.shown.append(("box", box.windowTitle()))
        return 0

    def fake_clicked(box):
        wanted = modals.answer("button", "")
        return next((b for b in box.buttons() if b.text() == wanted), None)

    patches = [
        (QMessageBox, "question", static("question", QMessageBox.Yes)),
        (QMessageBox, "warning", static("warning", QMessageBox.Ok)),
        (QMessageBox, "critical", static("critical", QMessageBox.Ok)),
        (QMessageBox, "information", static("information", QMessageBox.Ok)),
        (QMessageBox, "exec", fake_exec),
        (QMessageBox, "clickedButton", fake_clicked),
        (QFileDialog, "getOpenFileName",
         staticmethod(lambda *a, **k: (modals.answer("open_path", ""), ""))),
        (QFileDialog, "getSaveFileName",
         staticmethod(lambda *a, **k: (modals.answer("save_path", ""), ""))),
        (jte.TranslatorNameDialog, "exec", lambda dlg: QDialog.Rejected),
    ]
    with ExitStack() as stack:
        for owner, name, value in patches:
            stack.enter_context(mock.patch.object(owner, name, value))
        yield modals


@contextmanager
def open_window(path: Optional[Path] = None, backup: bool = False,
                **answers: Any) -> Iterator[Tuple["jte.MainWindow", Modals]]:
    """A real MainWindow inside patched_modals(**answers), with its settings file in a folder of
    its own, backups off unless *backup*, and *path* loaded when given. The startup prompts run
    inside the patches: closing the window processes events, and an unpatched startup modal would
    then block forever (the CLAUDE.md startup-modals pitfall)."""
    settings_path = temp_dir() / "json_translation_editor_settings.json"
    with patched_modals(**answers) as modals, \
            mock.patch.object(jte, "SETTINGS_FILE", settings_path):
        win = jte.MainWindow()
        win.settings.data.setdefault("backup", {})["enabled"] = backup
        win.show()
        pump()
        if path is not None:
            win._load(path)
            pump()
        try:
            yield win, modals
        finally:
            win.is_modified = False
            win.close()
            pump()


# ── Running a suite ─────────────────────────────────────────────────────────

class _Result(unittest.TestResult):
    """Prints 'FAIL <Class.test>: <first line>' for every failure and error as it happens: the
    line tests/run_all.py shows. An error (not a failed assertion) also prints its traceback,
    indented, so the runner's summary stays one line per failure."""

    def _report(self, test, err, is_error: bool) -> None:
        name = test.id().replace("__main__.", "")
        message = str(err[1]).strip().splitlines()
        print(f"FAIL {name}: {message[0] if message else err[0].__name__}", flush=True)
        if is_error:
            for line in "".join(traceback.format_exception(*err)).splitlines():
                print("    " + line)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._report(test, err, is_error=False)

    def addError(self, test, err):
        super().addError(test, err)
        self._report(test, err, is_error=True)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._report(subtest, err, is_error=not issubclass(err[0], test.failureException))


def run_suite(module) -> int:
    """Run *module*'s tests and print the FAIL lines, then 'PASSED: 0 failure(s)' or 'FAILED: N
    failure(s)' last. Returns the exit code: 0 when all passed, else 1."""
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = _Result()
    suite.run(result)
    failures = len(result.failures) + len(result.errors)
    if result.testsRun == 0:
        print("FAIL no tests found", flush=True)
        failures = 1
    print(f"{result.testsRun} test(s) run")
    print(f"{'FAILED' if failures else 'PASSED'}: {failures} failure(s)")
    # Leave the folder first: Windows will not delete the working directory.
    os.chdir(tempfile.gettempdir())
    shutil.rmtree(SCRATCH, ignore_errors=True)
    return 1 if failures else 0
