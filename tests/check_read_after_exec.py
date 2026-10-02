"""Offscreen check that a WA_DeleteOnClose dialog's results are still readable after exec().

QDialog.exec() deletes a dialog that has WA_DeleteOnClose -- and every child widget with it --
before it returns, so a result accessor that reads a widget (a combo's text, a checkbox's state)
after exec() raises "Internal C++ object ... already deleted". Covered, through a real exec()
closed by a zero-delay timer:

  * MergeConflictDialog: accepted_additions(), resolved_conflicts(), deletions_to_remove(), with a
    choice changed from its default in each category, after Apply & Close (accept);
  * RestoreFromBackupDialog: restore_glossary_requested() after accept, with the box ticked and
    with it cleared;
  * both dialogs are really deleted afterwards (the fix must not drop WA_DeleteOnClose).

Runs from a throwaway folder with the startup modals patched (like check_file_properties.py).

Run:  python tests/check_read_after_exec.py      (exit code 0 = all passed)
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parent.parent
SCRATCH = Path(tempfile.mkdtemp(prefix="xte_read_after_exec_"))
os.chdir(SCRATCH)
sys.argv[0] = str(SCRATCH / "check_read_after_exec.py")
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog
from shiboken6 import isValid

import xml_translation_editor as xte


def check(failures, label, ok, detail=""):
    if not ok:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def _e(name, text):
    return xte.StringEntry(name, "x", "Review", "", "false", text)


def _exec_then(dlg, before_accept):
    """Run dlg.exec() for real; once its loop is running, apply *before_accept* and accept."""
    def finish():
        before_accept(dlg)
        dlg.accept()
    QTimer.singleShot(0, finish)
    return dlg.exec()


def check_merge(failures, win):
    addition, kept_addition = _e("Add", "Pievieno"), _e("Keep add", "Paliek")
    conflict = (_e("A", "a"), _e("A", "b"))
    deletion = _e("Del", "Dzēst")
    dlg = xte.MergeConflictDialog([addition, kept_addition], [conflict], [deletion], parent=win)

    def choose(d):
        d._addition_combos[0].setCurrentText("Reject")
        d._conflict_combos[0].setCurrentText("Keep incoming")
        d._deletion_combos[0].setCurrentText("Delete")

    result = _exec_then(dlg, choose)
    check(failures, "merge: accepted", result == QDialog.Accepted, str(result))
    check(failures, "merge: dialog deleted after exec()", not isValid(dlg))
    try:
        check(failures, "merge: accepted_additions", dlg.accepted_additions() == [kept_addition],
              repr([e.name for e in dlg.accepted_additions()]))
        check(failures, "merge: resolved_conflicts", dlg.resolved_conflicts() == [conflict[1]],
              repr([e.text for e in dlg.resolved_conflicts()]))
        check(failures, "merge: deletions_to_remove", dlg.deletions_to_remove() == [deletion],
              repr([e.name for e in dlg.deletions_to_remove()]))
    except RuntimeError as e:
        failures.append(f"merge: reading choices after exec(): {e}")


def check_restore(failures, win):
    for ticked in (True, False):
        dlg = xte.RestoreFromBackupDialog(SCRATCH, parent=win)
        result = _exec_then(dlg, lambda d: d._restore_glossary_chk.setChecked(ticked))
        check(failures, f"restore ({ticked}): accepted", result == QDialog.Accepted, str(result))
        check(failures, f"restore ({ticked}): dialog deleted after exec()", not isValid(dlg))
        try:
            got = dlg.restore_glossary_requested()
            check(failures, f"restore ({ticked}): restore_glossary_requested", got is ticked, repr(got))
        except RuntimeError as e:
            failures.append(f"restore ({ticked}): reading after exec(): {e}")


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    failures = []
    # The startup modals block forever with nobody to click them (see the offscreen-smoke-test pitfall).
    xte.QMessageBox.warning = staticmethod(lambda *a, **k: 0)
    xte.TranslatorNameDialog.exec = lambda self: 0
    win = xte.MainWindow()
    win.settings.data.setdefault("backup", {})["enabled"] = False
    win.show()
    app.processEvents()
    for step in (check_merge, check_restore):
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
