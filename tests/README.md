# Tests

Automatic checks for JSON Translation Editor. They run without showing any window, take about
half a minute in total, and run by themselves before every commit that changes the app or the
tests.

## Quick start

```bash
python tests/run_all.py                          # run every check
python tests/run_all.py core_json merge_compare  # run only these (with or without check_ / .py)
python tests/check_core_json.py                  # run one check on its own
```

Each check prints one line, `PASS`, `FAIL` or `TIMEOUT`, with its time. Under a failed check you
see the lines that say what went wrong. The last lines are the summary and the report path:

```
PASS      0.4s  check_core_json
FAIL      0.7s  check_scrollbar
        FAIL handle overlaps the down arrow at 14 pt
22 passed, 1 failed (26.1 s)
Report: tests\reports\run_2026-09-27_14-05-33.md
```

The exit code is 0 when everything passed, 1 when something failed, and 2 for an unknown check
name.

## What the tests protect

- **Your files.** Opening and saving never corrupts a language file or its `.json.meta`
  sidecar, never loses or merges an entry, and never creates a duplicate key. An unchanged save
  gives back the file byte for byte, and a change touches only the entries you edited, so a diff
  stays clean.
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
| `check_core_json` | 55 | 0.4 s | Reading and saving language files: refused files, style detection (indent, line endings, BOM, escaped non-ASCII), byte-for-byte saves; the `.json.meta` sidecar (defaults, orphans, unknown status, bad dates, damaged or unreadable); the load/save pair, save order and a failed sidecar write |
| `check_core_merge` | 24 | 0.6 s | Merge from File: what counts as an addition, conflict or deletion, which side wins, appending additions, and whole-file merges for every combination of choices |
| `check_core_workflows` | 44 | 1.7 s | A real main window: Edit dialog, bulk status, delete, Close File, Save (sidecar failures, an unreadable sidecar), Save As, Merge from File, Restore from Backup, autosave |
| `check_core_dates_filter` | 19 | 0.3 s | Date formats, and every filter-bar option |
| `check_core_glossary` | 23 | 0.3 s | Glossary files in any encoding, separator and header layout; bad rows; writing; term matching incl. plurals |
| `check_core_backup` | 26 | 0.5 s | Backup folders and their `backup_info.json`, pruning, the "skip if backed up within" interval, every backup location, the fallback to the app folder |
| `check_core_settings` | 20 | 0.4 s | Settings file: filling in new keys, atomic save, the daily `.backups.zip`, recovery from a damaged file |
| `check_core_translation` | 46 | 1.6 s | Language codes, glossary in the prompt, every engine (Claude, DeepL, LibreTranslate, Google, MyMemory, Microsoft) with the network faked, error messages, Google's rate-limit retry, the Claude CLI started without a console window |
| `check_core_corpus` | 5 per file | 0.3 s + files | Your real-world files in `data/real/` (see below) |
| `check_run_all_report` | 19 | 0.3 s | The runner's saved report |

**UI checks**: older scripts, one program each.

| Check | Time | What it covers |
|---|---:|---|
| `check_autosave_fit` | 1.4 s | Autosave & Backup: spin boxes and the location combo wide enough for their text at every font size |
| `check_checkbox_mark` | 0.3 s | The tick in checked, disabled and unchecked check boxes, both themes |
| `check_combobox` | 1.8 s | Drop-down arrows and pop-up lists on every surface: size, contrast, width, selected row |
| `check_date_picker` | 2.0 s | The date fields and their scroll-wheel pop-up: keys, mouse, clamping, placement |
| `check_file_properties` | 0.6 s | File → Properties: editing the sidecar header, the facts shown, the dialog, save and reopen |
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

Put any real JSON language files into `tests/data/real/`, of any size and in any number; a
`.json.meta` sidecar beside one is read too. `check_core_corpus` tests every `*.json` there on
each run:

1. The app and the `json` module find the same keys, in the same order.
2. Saving without changes gives back the file byte for byte. A file that does not round-trip in
   its own style (say, no space after the colons) is skipped here and named in the Notes.
3. Editing one entry changes only its line (indented files).
4. Deleting an entry leaves exactly the other keys.
5. Merging the file into itself changes nothing.

The tests always work on a copy, so your files are never changed. The folder is local: git
ignores everything in it except its README, so the files never reach the repository. With the
folder empty the check passes and notes that it was skipped.

Each file adds its own load and save time to every run, commits included; a file of 2 500
strings takes a few hundredths of a second.

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
- **Notes:** information a check reports, such as each real-world file's string count and
  load/save time.
- **Failures:** each failed check's error lines. This section is there only when something
  failed.

If a report cannot be written, the run prints a warning and its result is not affected.

## The pre-commit hook: `hooks/pre-commit`

Turn it on once per clone:

```bash
git config core.hooksPath tests/hooks
```

From then on, `git commit` runs every check (about half a minute) whenever the commit includes
`json_translation_editor.py` or anything under `tests/`, and stops the commit if one fails.
Commits that change only documentation are not checked. The hook tests the files as they are
on disk, so unsaved edits you have not staged count too.

When it blocks a commit, fix what failed and commit again. `git commit --no-verify` skips the
checks, but leave that for exceptional cases.

## Sample data: `data/`

- `es.json` is a **frozen** copy of the Spanish language file (2 460 strings) and `es.json.meta`
  its sidecar: version `1.0.0` and metadata for the first three keys, one of them dated 1998 for
  the date-picker check. Several checks expect this exact content, so don't edit or replace
  them. For your own files use `data/real/`, and do your manual testing on the language files in
  the repository root, which the checks never read.
- `es.glossary.csv` is a two-term glossary for it.

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

jte = cs.jte


class ExampleTests(unittest.TestCase):
    def test_saved_file_keeps_its_keys(self):
        path = cs.write_pair(cs.temp_dir(), "es", {"Save": "Guardar"})
        loaded = jte.load_translation_file(path)
        jte.save_translation_file(path, loaded.entries, loaded.style, loaded.header)
        cs.assert_json_intact(self, path, ["Save"])


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))
```

Rules for core tests: one behaviour and one assertion per test, a test name that says what
should happen, and tables of inputs through `self.subTest(...)`. A test that saves a language file
checks it with `cs.assert_json_intact()`, which uses the `json` module (not the app) to confirm the
file is valid JSON and holds exactly the expected keys, in order, none twice.

Useful helpers in `core_support.py`:

- `cs.json_doc(...)`, `cs.sidecar_doc(...)`: build a language file or a sidecar as bytes.
- `cs.write_pair(...)`: write a language file and, optionally, its sidecar.
- `cs.write_exact(...)`: write bytes as they are.
- `cs.make_entry(...)`, `cs.bare_entry(...)`: build one entry.
- `cs.temp_dir()`: a fresh folder of your own.
- `cs.open_window(path)`: a real main window, with every dialog answered for you.
