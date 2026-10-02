# Tests

Automatic checks for XML Translation Editor. They run without showing any window, take about
half a minute in total, and run by themselves before every commit that changes the app or the
tests.

## Quick start

```bash
python tests/run_all.py                         # run every check
python tests/run_all.py core_xml merge_compare  # run only these (with or without check_ / .py)
python tests/check_core_xml.py                  # run one check on its own
```

Each check prints one line, `PASS`, `FAIL` or `TIMEOUT`, with its time. Under a failed check you
see the lines that say what went wrong. The last lines are the summary and the report path:

```
PASS      0.5s  check_core_xml
FAIL      0.7s  check_scrollbar
        FAIL handle overlaps the down arrow at 14 pt
22 passed, 1 failed (26.1 s)
Report: tests\reports\run_2026-09-27_14-05-33.md
```

The exit code is 0 when everything passed, 1 when something failed, and 2 for an unknown check
name.

## What the tests protect

- **Your files.** Opening and saving never corrupts a translation file, never loses or merges a
  row, and never creates a duplicate. An unchanged save gives back the file byte for byte, and a
  change touches only the rows you edited, so a diff stays clean.
- **The features.** Editing, bulk status, delete, Close File, Save As, Merge from File,
  Restore from Backup, autosave, backups, settings recovery, dates and filters, the glossary and
  every translation engine (with the network faked, so no request leaves your machine).
- **The look.** Scrollbars, check boxes, spin boxes, drop-downs, date pickers, group-box titles
  and dialog sizes are correct in both themes and at small and large UI fonts.

Every check works in its own temporary folder, so it never touches your settings, backups or
files.

## The checks

**Core suites**: `unittest`, one behaviour per test, built on `core_support.py`.

| Check | Tests | Time | What it covers |
|---|---:|---:|---|
| `check_core_xml` | 54 | 0.5 s | Reading and saving files: attributes, escaping, header, corruption guards (self-closing rows, `>` inside an attribute, edits to missing attributes), line endings, BOM, unchanged rows kept byte for byte, atomic save, row removal |
| `check_core_merge` | 25 | 0.5 s | Merge from File: what counts as an addition, conflict or deletion, which side wins, adding rows, and whole-file merges for every combination of choices |
| `check_core_workflows` | 33 | 1.3 s | A real main window: Edit dialog, legacy dates, bulk status, delete, Close File, Save As, Merge from File, Restore from Backup, autosave |
| `check_core_dates_filter` | 24 | 0.3 s | Date formats and normalization, and every filter-bar option |
| `check_core_glossary` | 23 | 0.3 s | Glossary files in any encoding, separator and header layout; bad rows; writing; term matching incl. plurals |
| `check_core_backup` | 25 | 0.4 s | Backup folders and their `backup_info.json`, pruning, the "skip if backed up within" interval, every backup location, the fallback to the app folder |
| `check_core_settings` | 20 | 0.4 s | Settings file: filling in new keys, atomic save, the daily `.backups.zip`, recovery from a damaged file |
| `check_core_translation` | 46 | 1.6 s | Language codes, glossary in the prompt, every engine (Claude, DeepL, LibreTranslate, Google, MyMemory, Microsoft) with the network faked, error messages, Google's rate-limit retry, the Claude CLI started without a console window |
| `check_core_corpus` | 6 per file | 0.3 s + files | Your real-world files in `data/real/` (see below) |
| `check_run_all_report` | 19 | 0.3 s | The runner's saved report |

**UI checks**: older scripts, one program each.

| Check | Time | What it covers |
|---|---:|---|
| `check_autosave_fit` | 1.4 s | Autosave & Backup: spin boxes and the location combo wide enough for their text at every font size |
| `check_checkbox_mark` | 0.3 s | The tick in checked, disabled and unchecked check boxes, both themes |
| `check_combobox` | 1.8 s | Drop-down arrows and pop-up lists on every surface: size, contrast, width, selected row |
| `check_date_picker` | 2.0 s | The date fields and their scroll-wheel pop-up: keys, mouse, clamping, placement |
| `check_file_properties` | 0.6 s | File → Properties: header editing, the facts shown, the dialog, save and reopen |
| `check_groupbox_title` | 3.1 s | Group-box borders run through the middle of their titles at every font size |
| `check_merge_compare` | 1.3 s | The Merge row compare pop-up: highlighted differences, choices, keys, sizes |
| `check_notifications` | 5.9 s | The info bar's message queue, colours, history pop-up and startup messages |
| `check_read_after_exec` | 0.4 s | Merge and Restore dialogs still hand over their results after they close |
| `check_scrollbar` | 0.7 s | Scrollbar handle stays clear of the arrows, keeps a minimum length, arrows drawn |
| `check_shortcuts_fit` | 1.4 s | Keyboard Shortcuts: buttons fit their text and the columns line up |
| `check_spinbox_arrows` | 0.5 s | Spin-box arrows visible and large enough, enabled and disabled |
| `check_translation_settings_size` | 1.5 s | Translation Settings fits each engine without jumping or clipping |

The UI checks run offscreen, where Qt has no fonts and draws text as boxes. Some of them can
also run on real fonts, which briefly shows their windows:
`QT_QPA_PLATFORM=windows python tests/check_groupbox_title.py`.

## Your real-world files: `data/real/`

Put any real translation XML files into `tests/data/real/`, of any size and in any number.
`check_core_corpus` tests every one of them on each run:

1. The app and an independent XML parser find the same rows, in the same order.
2. Saving without changes gives back the file byte for byte.
3. Editing one row changes only that row.
4. Deleting a row leaves exactly the other rows ...
5. ... and no blank line.
6. Merging the file into itself changes nothing. This is skipped for a file that already has
   duplicate rows, since Merge refuses such a file.

The tests always work on a copy, so your files are never changed. The folder is local: git
ignores everything in it except its README, so the files never reach the repository. With the
folder empty the check passes and notes that it was skipped.

Each file adds its own load and save time to every run, commits included. Three files, one of
11 000 strings, took about 5 s.

## Reports: `reports/`

Every run, including the one before a commit, writes a Markdown report:
`tests/reports/run_<date>_<time>.md`, plus a copy called `latest.md`. The newest 30 are kept, and
the folder is ignored by git. A report holds:

- **When and what:** the time, the trigger (`manual` or `pre-commit`), which checks ran, the
  branch and commit, and whether there were uncommitted changes. The checks test the files as
  they are on disk, so a run with uncommitted changes did not test the commit itself.
- **Versions:** Python and PySide6.
- **Summary and table:** one row per check with its result, time and number of tests. Only the
  core suites count their tests; the UI checks show "—".
- **Notes:** information a check reports, such as each real-world file's string count, duplicate
  rows and load/save time.
- **Failures:** each failed check's error lines. This section is there only when something
  failed.

If a report cannot be written, the run prints a warning and its result is not affected.

## The pre-commit hook: `hooks/pre-commit`

Turn it on once per clone:

```bash
git config core.hooksPath tests/hooks
```

From then on, `git commit` runs every check (about half a minute) whenever the commit includes
`xml_translation_editor.py` or anything under `tests/`, and stops the commit if one fails.
Commits that change only documentation are not checked. The hook tests the files as they are
on disk, so unsaved edits you have not staged count too.

When it blocks a commit, fix what failed and commit again. `git commit --no-verify` skips the
checks, but leave that for exceptional cases.

## Sample data: `data/`

- `Latvian.xml` is a **frozen** copy of the sample translation file. Several checks expect its
  exact content (header, version, dates, status counts), so don't edit or replace it. For your
  own files use `data/real/`, and do your manual testing on the `Latvian.xml` in the repository
  root, which the checks never read.
- The other files (`Latvian - merge test.xml`, the glossary, the restored copies) are copies of
  the manual-test files.

## Adding a test

Add it to the core suite for its area when one fits. Otherwise create a new
`tests/check_<name>.py`: the runner and the hook pick it up automatically. A new file must:

- run offscreen (importing `core_support` first takes care of that);
- print `FAIL <what failed>` for each failure, and `PASSED: 0 failure(s)` or
  `FAILED: N failure(s)` last;
- exit with 0 only when everything passed, through `sys.exit(...)`, never `os._exit()`;
- never touch the network, your settings or your files.

The smallest core-style check:

```python
"""Core tests: <area>. <What it covers.>

Run:  python tests/check_core_example.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import sys
import unittest

xte = cs.xte


class ExampleTests(unittest.TestCase):
    def test_saved_file_keeps_its_rows(self):
        path = cs.write_exact(cs.temp_dir() / "file.xml", cs.xml_doc([cs.row("Save", "Saglabāt")]))
        segments, entries, *_ = xte.parse_file(path)
        xte.save_file(path, segments, entries)
        cs.assert_xml_intact(self, path, ["Save"])


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))
```

Rules for core tests: one behaviour and one assertion per test, a test name that says what
should happen, and tables of inputs through `self.subTest(...)`. A test that saves an XML file
checks it with `cs.assert_xml_intact()`, which uses an independent XML parser to confirm the
file is well-formed and holds exactly the expected rows.

Useful helpers in `core_support.py`:

- `cs.row(...)`, `cs.xml_doc(...)`: build a translation file as text.
- `cs.write_exact(...)`: write it byte for byte.
- `cs.make_entry(...)`: build one entry.
- `cs.temp_dir()`: a fresh folder of your own.
- `cs.open_window(path)`: a real main window, with every dialog answered for you.
