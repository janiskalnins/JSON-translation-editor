# JSON Translation Editor Fork Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a verbatim copy of XML Translation Editor v39 into JSON Translation Editor v1, which edits flat `"English source": "translation"` JSON files with per-string metadata in a `<file>.json.meta` sidecar.

**Architecture:** One file (`json_translation_editor.py`), like the XML editor. The XML parser, segments and header regexes are replaced by a small JSON layer (`parse_json_bytes` / `dump_json_pairs`, whole-file rewrite in the file's own detected style) and a sidecar layer (`parse_sidecar_bytes` / `build_sidecar_bytes`), joined by `load_translation_file` / `save_translation_file`. The UI keeps working on `StringEntry`; dates stay in the system short-date format in memory and are ISO only in the sidecar.

**Tech Stack:** Python 3.9+, PySide6, stdlib `json`; tests are the existing offscreen checks (`tests/run_all.py`, stdlib `unittest` for `check_core_*`).

**Spec:** `docs/superpowers/specs/2026-10-02-json-translation-editor-fork-design.md` (read it with this plan).

## Global Constraints

- Repo: `Z:\GIT\JSON-translation-editor`. Source of the copy: `Z:\GIT\XML Translation Editor` at commit `c7c44e2` (v39). Never edit the XML repo.
- Single-file app: everything shipped lives in `json_translation_editor.py`; `tests/` and `Tools/` are dev-only.
- Python 3.9+; no new runtime dependencies (stdlib + PySide6 + what the XML editor already uses).
- Identity: name "JSON Translation Editor", `APP_VERSION = "1"`, settings `json_translation_editor_settings.json`, backups `JSON_Translation_file_Backups`, glyph cache and AppUserModelID `JSONTranslationEditor`, exe `JSONTranslationEditor.exe`. Resource file names (`Resources/xml_translation_editor.*`) stay as they are.
- Sidecar: `<name>.json.meta`, `format` 1, keys `language`, `language_name`, `version`, `entries`; entry fields `status`, `translator`, `modified` (ISO `YYYY-MM-DD`); only entries with non-default metadata listed; `indent=1`, `ensure_ascii=False`, LF, trailing newline.
- Language file: refuse invalid JSON / non-object / non-string value / duplicate key; write back in the detected style; unchanged round-tripping file saves byte-identical.
- First open without a sidecar: every entry `New`.
- The language files at the repo root (`es.json`, `id.json`, `it.json`, `pt-BR.json`) are the user's, committed by them in `0d5d20e`. Never commit a change to them, and never commit a sidecar (`*.json.meta`) at the root; restore them (`git checkout -- <file>`, delete the `.meta`) after any manual run.
- The pre-commit hook (`tests/hooks/pre-commit`) runs every check before a commit that touches the app or `tests/`; a red suite blocks the commit. Never use `--no-verify`. Every task ends green.
- Launchers/build scripts: pure ASCII; `.ps1` saved UTF-8 with BOM, `.bat` CRLF (CLAUDE.md "Encoding rules").
- Test style (`.claude/rules/testing.md`): one assertion per test, input tables through `subTest`, Arrange-Act-Assert, names describe behaviour. Core checks import `core_support as cs` first and end with `sys.exit(cs.run_suite(sys.modules[__name__]))`.
- Commit messages: conventional type prefix, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
- In tests the app module is imported as `jte` (`import json_translation_editor as jte`, or `jte = cs.jte` in core checks).

All paths below are relative to `Z:\GIT\JSON-translation-editor` unless they start with a drive letter. Line numbers refer to the copied file at `c7c44e2`; they drift as tasks land, so find code by the quoted text.

---

### Task 1: Copy the XML editor verbatim and set up the repo

**Files:**
- Create: every tracked file of the XML repo except the exclusions below, plus `.claude/rules/*.md` and `Tools/`
- Modify: `.gitignore`, `.gitattributes`
- Test: `tests/run_all.py` (existing checks, unchanged)

**Interfaces:**
- Consumes: nothing.
- Produces: a working copy of the XML editor in the JSON repo, hook enabled; later tasks edit these files.

- [ ] **Step 1: Check the source is clean at c7c44e2**

Run (Bash):
```bash
git -C "/z/GIT/XML Translation Editor" rev-parse --short HEAD
git -C "/z/GIT/XML Translation Editor" status --short
```
Expected: `c7c44e2`, and at most ` M .claude/settings.local.json`. Anything else: stop and ask.

- [ ] **Step 2: Keep the JSON repo's own ignore and attributes files aside**

```bash
cd "/z/GIT/JSON-translation-editor"
cp .gitignore "$TEMP/json_repo.gitignore"
cp .gitattributes "$TEMP/json_repo.gitattributes"
```

- [ ] **Step 3: Copy the tracked files**

`git archive` cannot be used: the XML repo's `.gitattributes` marks `tests`, `.claude`, `CLAUDE.md` and others `export-ignore`.

```bash
SRC="/z/GIT/XML Translation Editor"; DEST="/z/GIT/JSON-translation-editor"
cd "$SRC"
git -c core.quotepath=off ls-files \
 | grep -v -E '^(docs/superpowers/|docs/architecture/|\.swarm/|desktop\.ini$|\.claude/settings\.local\.json$|Latvian\.xml$|Resources/User_Guide\.pdf$)' \
 | while IFS= read -r f; do mkdir -p "$DEST/$(dirname "$f")"; cp "$f" "$DEST/$f"; done
mkdir -p "$DEST/.claude/rules" && cp .claude/rules/*.md "$DEST/.claude/rules/"
cp -r Tools "$DEST/Tools" && rm -rf "$DEST/Tools/__pycache__" "$DEST/Tools/_scratch" "$DEST/Tools/screenshots"
```
`README.md` is overwritten on purpose (Task 15 rewrites it).

- [ ] **Step 4: Merge `.gitignore`**

Write `.gitignore` as: the XML repo's `.gitignore` content with these edits, followed by a blank line, `# Python template from the initial repo` and the full content of `$TEMP/json_repo.gitignore`.
- Replace the line `.claude/` with two lines: `.claude/*` and `!.claude/rules/`.
- Keep the existing XML-era settings/backup lines (they are needed until Task 2 renames things) and add after them:
```gitignore
json_translation_editor_settings*.json
json_translation_editor_settings.backups.zip
json_translation_editor_settings.backups.zip.corrupt
json_translation_editor_settings.json.corrupt-*
.json_translation_editor_settings.*.tmp
JSON_Translation_file_Backups/
# Damaged sidecars kept aside by the editor
*.json.meta.corrupt-*
```

- [ ] **Step 5: Merge `.gitattributes`**

Use the XML repo's `.gitattributes` and add after `tests/hooks/* text eol=lf`:
```gitattributes
# Language files and their sidecars keep LF in the working copy, exactly as the consuming program reads them
*.json text eol=lf
*.json.meta text eol=lf
```

- [ ] **Step 6: Enable the hook and run every check**

```bash
cd "/z/GIT/JSON-translation-editor"
git config core.hooksPath tests/hooks
python tests/run_all.py
```
Expected: last lines `N passed, 0 failed (...)` and `Report: tests/reports/...`. A failure here is an environment problem (missing PySide6, deep-translator, claude-agent-sdk): report it, do not edit code.

- [ ] **Step 7: Confirm the user's files are untouched, then stage**

```bash
git diff --quiet -- es.json id.json it.json pt-BR.json; echo "exit=$?"
git add -A
git diff --cached --name-only | grep -E '^(es|id|it|pt-BR)\.json$' ; echo "exit=$?"
```
Expected: `exit=0`, then nothing listed and `exit=1` (the copy did not touch the user's language files; the XML repo has none).

- [ ] **Step 8: Commit**

```bash
git commit -F - <<'EOF'
chore: fork XML Translation Editor v39 (c7c44e2) verbatim

Copied from Z:\GIT\XML Translation Editor at c7c44e2 without its
history, minus docs/superpowers, docs/architecture, Latvian.xml,
.swarm, desktop.ini, local settings and the User Guide PDF. The JSON
adaptation follows in later commits so it can be reviewed as a diff.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```
The hook runs the checks (~30 s) and must pass.

---

### Task 2: Give the fork its own identity

**Files:**
- Rename: `xml_translation_editor.py` → `json_translation_editor.py`
- Modify: `json_translation_editor.py`, `tests/*.py`, `tests/hooks/pre-commit`, `run_translator.ps1`, `run_translator.bat`, `build_exe.ps1`, `build_exe.bat`, `.gitignore`
- Test: `tests/check_notifications.py` (new assertion), all checks

**Interfaces:**
- Consumes: Task 1's copy.
- Produces: module `json_translation_editor`; constants `SETTINGS_FILE = Path("json_translation_editor_settings.json")`, `BACKUP_DIR_NAME = "JSON_Translation_file_Backups"`, `APP_VERSION = "1"`, `APP_NAME = "JSON Translation Editor"`; tests import the module as `jte`.

- [ ] **Step 1: Rename the module and the test alias**

```bash
cd "/z/GIT/JSON-translation-editor"
git mv xml_translation_editor.py json_translation_editor.py
sed -i 's/import xml_translation_editor as xte/import json_translation_editor as jte/; s/\bxte\b/jte/g' tests/*.py
grep -n "xml_translation_editor\|\bxte\b" tests/*.py ; echo "exit=$?"
```
Expected: no matches (`exit=1`).

- [ ] **Step 2: Write the failing test for the window title**

In `tests/check_notifications.py`, find where it checks `_file_label` (search `_file_label("Latvian.xml"`) and add next to those checks, in the same `check(label, condition, detail)` style that file uses:
```python
    check("window title names the JSON editor",
          win.windowTitle().startswith("JSON Translation Editor v1 — "),
          repr(win.windowTitle()))
```
Use the `MainWindow` instance that block already has (search upward for the variable built with `jte.MainWindow()` in that function; if the block has none, put the check in the first function of the file that builds one, right after it is shown).

- [ ] **Step 3: Run it to see it fail**

Run: `python tests/check_notifications.py`
Expected: `FAIL window title names the JSON editor` (title still says XML / v39).

- [ ] **Step 4: Change the names in the app**

In `json_translation_editor.py`:
- Module docstring lines 2-3 → `JSON Translation Editor` / `A PySide6 desktop app for viewing, filtering, and editing JSON translation files.`
- `SETTINGS_FILE = Path("translation_editor_settings.json")` → `Path("json_translation_editor_settings.json")`.
- `APP_VERSION = "39"   # ...` → `APP_VERSION = "1"    # plain integer, matches the GitHub release tag scheme (v1, v2, ...) -- bump manually before tagging a release`, and add below it `APP_NAME = "JSON Translation Editor"`.
- `_glyph_cache_dir()`: `"XMLTranslationEditor"` → `"JSONTranslationEditor"`.
- `BACKUP_DIR_NAME = "XML_Translation_file_Backups"` → `"JSON_Translation_file_Backups"`, and the two literal mentions in `AutosaveBackupDialog` (`"Location:  XML_Translation_file_Backups / ..."`) and docstrings (`<location_root>/XML_Translation_file_Backups/`, `'<folder>/XML_Translation_file_Backups'`) to the new name.
- `WelcomeScreen._build_ui`: `QLabel("XML Translation Editor")` → `QLabel(APP_NAME)`.
- `_update_title`: `f"XML Translation Editor v{APP_VERSION} — {name}{mod}"` → `f"{APP_NAME} v{APP_VERSION} — {name}{mod}"`.
- `main()`: `SetCurrentProcessExplicitAppUserModelID("XMLTranslationEditor")` → `"JSONTranslationEditor"`; `app.setApplicationName("XML Translation Editor")` → `app.setApplicationName(APP_NAME)`.

Leave every other "XML" mention for Task 6 (they describe the file format, which has not changed yet).

- [ ] **Step 5: Change the names in tests and the hook**

```bash
sed -i 's/translation_editor_settings\.json/json_translation_editor_settings.json/g; s/XML_Translation_file_Backups/JSON_Translation_file_Backups/g; s/XMLTranslationEditor/JSONTranslationEditor/g' tests/*.py
sed -i 's/xml_translation_editor\\\.py/json_translation_editor\\.py/' tests/hooks/pre-commit
grep -n "translation_editor" tests/hooks/pre-commit
```
Expected: the hook line now reads `grep -qE '^(json_translation_editor\.py|tests/)'`. Check the hook kept LF: `file tests/hooks/pre-commit` must not say CRLF.

Then `grep -rn "XML Translation Editor\|v39" tests/` and change any test expectation of the old title or version to `JSON Translation Editor` / `v1`.

- [ ] **Step 6: Change the launchers and build scripts**

Edit with a Python script, so the encodings stay right (`.ps1` UTF-8 with BOM, `.bat` ASCII + CRLF):
```python
from pathlib import Path
swaps = [("xml_translation_editor.py", "json_translation_editor.py"),
         ("XMLTranslationEditor", "JSONTranslationEditor"),
         ("XML Translation Editor", "JSON Translation Editor")]
for name, enc, nl in (("run_translator.ps1", "utf-8-sig", None), ("build_exe.ps1", "utf-8-sig", None),
                      ("run_translator.bat", "ascii", "\r\n"), ("build_exe.bat", "ascii", "\r\n")):
    p = Path(name)
    text = p.read_text(encoding=enc)
    for old, new in swaps:
        text = text.replace(old, new)
    assert all(ord(c) <= 127 for c in text), name
    p.write_text(text, encoding=enc, newline=nl if nl else "")
```
`Resources\xml_translation_editor.ico/.png/_splash.png/_ascii.txt` are not touched by these swaps (they contain `xml_translation_editor.` followed by another extension, not `.py`). Verify:
```bash
grep -n "xml_translation_editor" run_translator.ps1 run_translator.bat build_exe.ps1 build_exe.bat
```
Expected: only `Resources\xml_translation_editor.*` lines.

Also check the box-drawn banners still line up (`JSON` is one character longer than `XML`): in each banner line containing `JSON Translation Editor`, remove one space before the closing `|` so the right border keeps its column.

- [ ] **Step 7: Drop the XML-era ignore lines**

In `.gitignore` delete the `translation_editor_settings*` lines, `.translation_editor_settings.*.tmp` and both `XML_Translation_file_Backups/` lines (the `json_...` and `JSON_...` lines from Task 1 replace them).

- [ ] **Step 8: Run all checks**

Run: `python tests/run_all.py`
Expected: `N passed, 0 failed`, the new title check included.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -F - <<'EOF'
refactor: rename the fork to JSON Translation Editor v1

Own module name, settings file, backup folder, glyph cache,
AppUserModelID and exe name, so it runs next to the XML editor.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Remove "Is tablet" from the UI, model, merge and facts

The file format is still XML in this task: `StringEntry.istablet` and the XML read/write code keep the attribute (Task 6 deletes them). Everything a user sees or a feature compares loses it.

**Files:**
- Modify: `json_translation_editor.py` (constants `COL_TAB`/`HEADERS`, `Settings.DEFAULTS["column_widths"]`, `TranslationModel.data`, `FilterEngine`, `FilterPanel`, `ToggleSwitch` (delete), `EditDialog`, `compute_merge_diff`, `MainWindow._apply_merge_diff`, `FileFacts`/`compute_file_facts`, `FilePropertiesDialog`, `MergeCompareDialog`)
- Test: `tests/check_core_dates_filter.py`, `tests/check_core_merge.py`, `tests/check_file_properties.py`, `tests/check_merge_compare.py`, `tests/check_spinbox_arrows.py`, `tests/check_combobox.py`, plus any other `grep -n tablet tests/*.py` hit

**Interfaces:**
- Consumes: Task 2's names.
- Produces: `HEADERS = ["#", "Source Text", "Translated Text", "Status", "Translator", "Date"]`; `FileFacts` without `tablet`; `FilterEngine` without `istablet`; `FilterPanel` without `tablet_combo` (Task 11 adds a `check_combo` in its place); `MergeCompareDialog._meta_values()` returns `(translator, status, date, length)`.

- [ ] **Step 1: Write the failing tests**

(Merge's tablet comparison has no observable effect on its own — a tablet-only difference with equal dates never picks a winner — so it is removed without a test of its own; `check_core_merge.py` must stay green.)

In `tests/check_file_properties.py`, next to the other `compute_file_facts` checks, add (same `check()` style as the file):
```python
    check("FileFacts has no tablet count",
          "tablet" not in jte.FileFacts.__dataclass_fields__,
          repr(list(jte.FileFacts.__dataclass_fields__)))
```
In `tests/check_core_dates_filter.py` add:
```python
class NoTabletColumnTests(unittest.TestCase):
    def test_table_has_no_tablet_column(self):
        self.assertNotIn("Tablet", jte.HEADERS)
```

- [ ] **Step 2: Run them to see them fail**

Run: `python tests/check_file_properties.py`, `python tests/check_core_dates_filter.py`
Expected: each reports the new test as `FAIL`.

- [ ] **Step 3: Remove tablet from the model, filter and Edit window**

- Delete `COL_TAB = 6`; `HEADERS` loses `"Tablet"`; `Settings.DEFAULTS["column_widths"]` loses `"6": 60`.
- `TranslationModel.data`: delete the `COL_TAB` DisplayRole line and the whole `ForegroundRole` block for it (keep `if role == Qt.ForegroundRole: return None`); the alignment tuple becomes `(COL_IDX, COL_STATUS)`.
- `FilterEngine`: delete `self.istablet = "All"` and the `# IsTablet` block in `matches()`.
- `FilterPanel._build`: delete the "Is tablet column" block; remove `self.tablet_combo` from the vertical-policy loop; `fit_to_font` combo tuple loses it; `_reset_all` loses its three tablet lines; `_on_filter` loses `tablet_map`/`e.istablet`; `_refresh_active_indicators` loses the `"tablet"` row and `self.tablet_combo` from the widget tuple.
- Delete `class ToggleSwitch` entirely.
- `EditDialog._build`: delete the `QLabel("Is Tablet:")` and `self.tablet_toggle` lines. `_load_row`: delete `self._original_tablet = ...`. `_commit_current`: delete `new_tablet`, its comparison line and `src_entry.istablet = new_tablet`. `_populate`: delete the `tablet_toggle.setChecked` line. In `keyPressEvent`'s comment, drop "tablet toggle, ".

- [ ] **Step 4: Remove tablet from merge, facts and the compare pop-up**

- `compute_merge_diff`: delete `or current.istablet != incoming.istablet` (keep the other three comparisons, closing the parenthesis after `modify_date`).
- `MainWindow._apply_merge_diff`: delete both `target.istablet = ...` lines.
- `FileFacts`: delete `tablet: int`. `compute_file_facts`: delete the `tablet=` argument.
- `FilePropertiesDialog._build_ui`: delete `("tablet", "Tablet strings:")` from the facts tuple; `_load_facts`: delete the `labels["tablet"]` line.
- `MergeCompareDialog`: in `_meta_values()` drop the `tablet` variable and return `(..., str(len(entry.text)))` as the fourth value; rename the fourth `_META_FIELDS` caption from `"Tablet · Length"` (search the class for it) to `"Length"`; keep the tuple length at four.

- [ ] **Step 5: Fix the remaining tablet references in tests**

```bash
grep -n -i "tablet" tests/*.py
```
For each hit outside `check_core_xml.py` and `core_support.py` (whose XML builders keep `istablet` until Task 6): delete assertions on the tablet column, combo, toggle, fact or compare value, and remove `tablet=` from `FileFacts(...)` constructions (`check_spinbox_arrows.py`, `check_file_properties.py`). In `check_combobox.py` and `check_groupbox_title.py`, drop the filter-bar tablet combo from the lists of combos they visit.

- [ ] **Step 6: Run all checks**

Run: `python tests/run_all.py`
Expected: `N passed, 0 failed`; `grep -n -i tablet json_translation_editor.py` lists only `StringEntry.istablet`, `_ATTR_RE`, `_ATTR_PARSE_DEFAULTS`, `_entry_from_segment`, `build_string_xml` and `_NEW_STRING_TEMPLATE`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -F - <<'EOF'
refactor: drop the Is tablet column, filter, toggle and fact

The JSON format has no tablet flag. The XML reader keeps the field
until the format switch removes it.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: JSON language-file reading and writing (pure functions)

**Files:**
- Modify: `json_translation_editor.py` (new section `JSON LANGUAGE FILE` after the `FILE PROPERTIES` helpers, i.e. right after `describe_culture()`)
- Modify: `tests/core_support.py` (add `json_doc`, `assert_json_intact`)
- Create: `tests/check_core_json.py`, `tests/data/es.json` (copy of the root `es.json`)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `class JsonStyle` (frozen dataclass: `indent: Optional[str]`, `newline: str`, `bom: bool`, `trailing_newline: bool`, `ensure_ascii: bool`)
  - `DEFAULT_JSON_STYLE = JsonStyle(indent=" ", newline="\n", bom=False, trailing_newline=True, ensure_ascii=False)`
  - `class JsonFormatError(ValueError)`
  - `detect_json_style(text: str, bom: bool) -> JsonStyle`
  - `parse_json_bytes(raw: bytes) -> Tuple[List[Tuple[str, str]], JsonStyle]`
  - `dump_json_pairs(pairs: List[Tuple[str, str]], style: JsonStyle) -> bytes` (raises `ValueError` when two pairs share a key)
  - `cs.json_doc(pairs, indent=" ", newline="\n", bom=False) -> bytes`, `cs.assert_json_intact(tc, path, expected_names)`

- [ ] **Step 1: Add the frozen sample and the test helpers**

```bash
cp es.json tests/data/es.json
```
In `tests/core_support.py`, add `import json` to the imports and, under `# ── The oracle`, add:
```python
def json_doc(pairs, indent: Optional[str] = " ", newline: str = "\n", bom: bool = False) -> bytes:
    """A language file as bytes, written with the json module (not the app), in the given style.
    *pairs* is a dict or a list of (key, value)."""
    text = json.dumps(dict(pairs), ensure_ascii=False, indent=indent) + "\n"
    data = text.replace("\n", newline).encode("utf-8")
    return b"\xef\xbb\xbf" + data if bom else data


def assert_json_intact(tc: unittest.TestCase, path: Path, expected_names: List[str]) -> None:
    """The independent judge of a saved language file: the json module must read one object whose
    keys are exactly *expected_names*, in order, none twice, every value a string."""
    try:
        pairs = json.loads(path.read_bytes().decode("utf-8-sig"), object_pairs_hook=list)
    except ValueError as e:
        tc.fail(f"{path.name} is not valid JSON: {e}")
    names = [k for k, _v in pairs]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    tc.assertEqual((duplicates, all(isinstance(v, str) for _k, v in pairs), names),
                   ([], True, list(expected_names)))
```

- [ ] **Step 2: Write the failing tests**

Create `tests/check_core_json.py`:
```python
"""Core checks for the JSON language file: reading (refusals included), style detection and
writing back byte for byte. Later tasks add the sidecar and the load/save pair."""

import core_support as cs  # first: offscreen platform, scratch folder, sys.argv[0]

import json
import sys
import unittest

jte = cs.jte

PAIRS = [("Save", "Guardar"), ("Path {n}", "Trazado {n}"), ("Ā", "Ā")]


def _parse(data: bytes):
    return jte.parse_json_bytes(data)


class ParseTests(unittest.TestCase):
    def test_pairs_keep_file_order(self):
        pairs, _style = _parse(cs.json_doc([("b", "B"), ("a", "A")]))
        self.assertEqual(pairs, [("b", "B"), ("a", "A")])

    def test_refused_files(self):
        cases = {
            "invalid JSON": b'{"a": "A",}',
            "not an object": b'["a"]',
            "a value that is not text": b'{"a": 1}',
            "a nested object": b'{"a": {"b": "c"}}',
            "a duplicate key": b'{"a": "A", "a": "B"}',
            "not UTF-8": b'{"a": "\xff"}',
            "empty": b"",
        }
        for label, data in cases.items():
            with self.subTest(label):
                with self.assertRaises(jte.JsonFormatError):
                    _parse(data)

    def test_invalid_json_names_the_line(self):
        with self.assertRaises(jte.JsonFormatError) as ctx:
            _parse(b'{\n "a": "A",\n}')
        self.assertIn("line 3", str(ctx.exception))

    def test_duplicate_key_is_named(self):
        with self.assertRaises(jte.JsonFormatError) as ctx:
            _parse(b'{"Save": "A", "Save": "B"}')
        self.assertIn("'Save'", str(ctx.exception))

    def test_empty_object_reads_as_no_pairs(self):
        self.assertEqual(_parse(b"{}\n")[0], [])


class StyleTests(unittest.TestCase):
    def test_detected_indent(self):
        cases = {
            "one space": (cs.json_doc(PAIRS), " "),
            "four spaces": (cs.json_doc(PAIRS, indent="    "), "    "),
            "tab": (cs.json_doc(PAIRS, indent="\t"), "\t"),
            "one line": (json.dumps(dict(PAIRS), ensure_ascii=False).encode("utf-8"), None),
        }
        for label, (data, indent) in cases.items():
            with self.subTest(label):
                self.assertEqual(_parse(data)[1].indent, indent)

    def test_crlf_is_detected(self):
        self.assertEqual(_parse(cs.json_doc(PAIRS, newline="\r\n"))[1].newline, "\r\n")

    def test_bom_is_detected(self):
        self.assertTrue(_parse(cs.json_doc(PAIRS, bom=True))[1].bom)

    def test_missing_trailing_newline_is_detected(self):
        self.assertFalse(_parse(cs.json_doc(PAIRS)[:-1])[1].trailing_newline)

    def test_escaped_non_ascii_is_detected(self):
        data = json.dumps(dict(PAIRS), indent=1).encode("ascii") + b"\n"
        self.assertTrue(_parse(data)[1].ensure_ascii)

    def test_literal_non_ascii_is_detected(self):
        self.assertFalse(_parse(cs.json_doc(PAIRS))[1].ensure_ascii)


class WriteTests(unittest.TestCase):
    def test_unchanged_files_write_back_byte_for_byte(self):
        cases = {
            "the frozen es.json": (cs.DATA / "es.json").read_bytes(),
            "CRLF": cs.json_doc(PAIRS, newline="\r\n"),
            "BOM": cs.json_doc(PAIRS, bom=True),
            "escaped non-ASCII": json.dumps(dict(PAIRS), indent=1).encode("ascii") + b"\n",
            "four-space indent": cs.json_doc(PAIRS, indent="    "),
            "tab indent": cs.json_doc(PAIRS, indent="\t"),
            "one line": json.dumps(dict(PAIRS), ensure_ascii=False).encode("utf-8"),
            "no trailing newline": cs.json_doc(PAIRS)[:-1],
            "quotes, backslashes, line breaks": cs.json_doc(
                [("a\nb", 'say "hi"\\n'), ("tab\there", "{name}\n\n{n}")]),
            "empty object": b"{}\n",
        }
        for label, data in cases.items():
            with self.subTest(label):
                pairs, style = _parse(data)
                self.assertEqual(jte.dump_json_pairs(pairs, style), data)

    def test_one_changed_value_changes_one_line(self):
        original = (cs.DATA / "es.json").read_bytes()
        pairs, style = _parse(original)
        pairs[1] = (pairs[1][0], "CAMBIADO")
        written = jte.dump_json_pairs(pairs, style)
        changed = [i for i, (a, b) in enumerate(zip(original.splitlines(), written.splitlines()))
                   if a != b]
        self.assertEqual(changed, [2])

    def test_two_pairs_with_one_key_are_refused(self):
        with self.assertRaises(ValueError):
            jte.dump_json_pairs([("a", "A"), ("a", "B")], jte.DEFAULT_JSON_STYLE)

    def test_written_file_is_intact(self):
        path = cs.temp_dir() / "es.json"
        path.write_bytes(jte.dump_json_pairs(PAIRS, jte.DEFAULT_JSON_STYLE))
        cs.assert_json_intact(self, path, [k for k, _v in PAIRS])


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))
```

- [ ] **Step 3: Run it to see it fail**

Run: `python tests/check_core_json.py`
Expected: errors such as `AttributeError: module 'json_translation_editor' has no attribute 'parse_json_bytes'`, last line `FAILED: N failure(s)`.

- [ ] **Step 4: Implement**

Add after `describe_culture()` in `json_translation_editor.py`:
```python
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
```

- [ ] **Step 5: Run it to see it pass**

Run: `python tests/check_core_json.py`
Expected: `PASSED: 0 failure(s)`.

- [ ] **Step 6: Run all checks and commit**

Run: `python tests/run_all.py` → `N passed, 0 failed`.
```bash
git add json_translation_editor.py tests/core_support.py tests/check_core_json.py tests/data/es.json
git commit -F - <<'EOF'
feat: read and write flat JSON language files in their own style

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: The sidecar (pure functions)

**Files:**
- Modify: `json_translation_editor.py` (new section `SIDECAR` right after the JSON section)
- Modify: `tests/core_support.py` (add `sidecar_doc`, `bare_entry`)
- Modify: `tests/check_core_json.py` (new classes)

**Interfaces:**
- Consumes: `StringEntry` (attributes `name`, `status`, `translator`, `modify_date`), `STATUSES`, `parse_date`, `format_date_for_storage`, `_log_error`.
- Produces:
  - `META_SUFFIX = ".meta"`, `META_FORMAT = 1`, `LANGUAGE_CODE_RE`
  - `@dataclass class FileHeader: language: str = ""; language_name: str = ""; version: str = ""`
  - `class SidecarError(ValueError)`
  - `meta_path_for(json_path: Path) -> Path`
  - `guess_language(json_path: Path) -> str`
  - `effective_language(header: FileHeader, json_path: Optional[Path]) -> str`
  - `parse_sidecar_bytes(raw: bytes) -> Tuple[FileHeader, Dict[str, Dict[str, str]]]`
  - `apply_sidecar_meta(entries: List[StringEntry], meta: Dict[str, Dict[str, str]]) -> List[str]` (mutates the entries' metadata, returns warning texts)
  - `build_sidecar_bytes(entries: List[StringEntry], header: FileHeader) -> bytes`
  - `read_file_header(json_path: Path) -> FileHeader` (never raises)
  - `cs.sidecar_doc(entries=None, language="es", language_name="Español", version="1.0.0", **extra) -> bytes`, `cs.bare_entry(name, text=None) -> StringEntry`

- [ ] **Step 1: Add test helpers**

In `tests/core_support.py`, after `json_doc`:
```python
def sidecar_doc(entries: Optional[Dict[str, Tuple[str, str, str]]] = None, language: str = "es",
                language_name: str = "Español", version: str = "1.0.0", **extra: Any) -> bytes:
    """A sidecar as bytes. *entries* maps a key to (status, translator, ISO date); *extra* adds or
    overrides top-level fields (e.g. format=2)."""
    data = {"format": 1, "language": language, "language_name": language_name,
            "version": version,
            "entries": {k: {"status": s, "translator": t, "modified": d}
                        for k, (s, t, d) in (entries or {}).items()}}
    data.update(extra)
    return (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def bare_entry(name: str, text: Optional[str] = None) -> "jte.StringEntry":
    """An entry as a language file without a sidecar gives it: New, no translator, no date."""
    return make_entry(name=name, text=name if text is None else text, status="New",
                      translator="", modify_date="")
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/check_core_json.py` (above the `if __name__` block), and add `from datetime import date` and `from pathlib import Path` to its imports:
```python
ISO = "2026-10-02"
SHOWN = jte.format_date_for_storage(date(2026, 10, 2))


class SidecarParseTests(unittest.TestCase):
    def test_header_is_read(self):
        header, _meta = jte.parse_sidecar_bytes(
            cs.sidecar_doc(language="es-AR", language_name="Español (Argentina)", version="1.2.3"))
        self.assertEqual(header, jte.FileHeader("es-AR", "Español (Argentina)", "1.2.3"))

    def test_missing_fields_default(self):
        self.assertEqual(jte.parse_sidecar_bytes(b"{}"), (jte.FileHeader(), {}))

    def test_bom_is_accepted(self):
        header, _meta = jte.parse_sidecar_bytes(b"\xef\xbb\xbf" + cs.sidecar_doc())
        self.assertEqual(header.language, "es")

    def test_refused_sidecars(self):
        cases = {
            "not JSON": b"{",
            "a list": b"[]",
            "a newer format": cs.sidecar_doc(format=2),
            "language not text": cs.sidecar_doc(language=5),
            "entries not an object": cs.sidecar_doc(entries=[]),
            "an entry not an object": b'{"entries": {"a": "Complete"}}',
            "an entry field not text": b'{"entries": {"a": {"status": 1}}}',
        }
        for label, data in cases.items():
            with self.subTest(label):
                with self.assertRaises(jte.SidecarError):
                    jte.parse_sidecar_bytes(data)


def _applied(meta: dict, names=("a", "b")):
    entries = [cs.bare_entry(n) for n in names]
    warnings = jte.apply_sidecar_meta(entries, meta)
    return entries, warnings


class ApplyMetaTests(unittest.TestCase):
    def test_listed_entry_takes_its_metadata(self):
        entries, _w = _applied({"a": {"status": "Review", "translator": "Jo", "modified": ISO}})
        self.assertEqual((entries[0].status, entries[0].translator, entries[0].modify_date),
                         ("Review", "Jo", SHOWN))

    def test_unlisted_entry_stays_new(self):
        entries, _w = _applied({"a": {"status": "Review", "translator": "Jo", "modified": ISO}})
        self.assertEqual((entries[1].status, entries[1].translator, entries[1].modify_date),
                         ("New", "", ""))

    def test_unknown_status_reads_as_new(self):
        entries, _w = _applied({"a": {"status": "Done"}})
        self.assertEqual(entries[0].status, "New")

    def test_bad_date_is_kept_as_stored(self):
        entries, _w = _applied({"a": {"status": "Review", "modified": "2026-13-45"}})
        self.assertEqual(entries[0].modify_date, "2026-13-45")

    def test_warnings(self):
        cases = {
            "clean": ({"a": {"status": "Review", "translator": "", "modified": ISO}}, []),
            "orphan": ({"gone": {"status": "Review"}},
                       ["Metadata: 1 entries for keys no longer in the file"]),
            "unknown status": ({"a": {"status": "Done"}},
                               ["Metadata: 1 unknown status value(s) read as New"]),
            "bad date": ({"a": {"modified": "foo"}},
                         ["Metadata: 1 unrecognized date(s) (e.g. 'foo')"]),
        }
        for label, (meta, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(_applied(meta)[1], expected)


def _built(entries, header=jte.FileHeader("es", "Español", "1.0.0")) -> dict:
    return json.loads(jte.build_sidecar_bytes(entries, header))


class BuildSidecarTests(unittest.TestCase):
    def test_only_entries_with_metadata_are_listed(self):
        entries = [cs.bare_entry("a"), cs.make_entry(name="b", status="Review", translator="",
                                                     modify_date="")]
        self.assertEqual(list(_built(entries)["entries"]), ["b"])

    def test_dates_are_written_iso(self):
        entries = [cs.make_entry(name="b", modify_date=SHOWN)]
        self.assertEqual(_built(entries)["entries"]["b"]["modified"], ISO)

    def test_unparseable_date_is_written_as_stored(self):
        entries = [cs.make_entry(name="b", modify_date="foo")]
        self.assertEqual(_built(entries)["entries"]["b"]["modified"], "foo")

    def test_header_is_written(self):
        built = _built([], jte.FileHeader("pt-BR", "Português", "2.0.1"))
        self.assertEqual((built["format"], built["language"], built["language_name"],
                          built["version"]), (1, "pt-BR", "Português", "2.0.1"))

    def test_layout_is_one_space_indent_with_trailing_newline(self):
        raw = jte.build_sidecar_bytes([cs.make_entry(name="ā")], jte.FileHeader())
        self.assertEqual(raw, (json.dumps(json.loads(raw), ensure_ascii=False, indent=1)
                               + "\n").encode("utf-8"))

    def test_metadata_survives_a_round_trip(self):
        original = [cs.make_entry(name="a", status="Review", translator="Jo", modify_date=SHOWN),
                    cs.bare_entry("b")]
        _header, meta = jte.parse_sidecar_bytes(jte.build_sidecar_bytes(original, jte.FileHeader()))
        copies, _w = _applied(meta)
        self.assertEqual([(e.status, e.translator, e.modify_date) for e in copies],
                         [(e.status, e.translator, e.modify_date) for e in original])


class SidecarPathTests(unittest.TestCase):
    def test_meta_path_sits_beside_the_file(self):
        self.assertEqual(jte.meta_path_for(Path("C:/t/es.json")), Path("C:/t/es.json.meta"))

    def test_guessed_language(self):
        cases = {"es.json": "es", "pt-BR.json": "pt-BR", "zh-Hant-TW.json": "zh-Hant-TW",
                 "deu.json": "deu", "strings.json": "",
                 "es_restored_2026-10-02_10-00-00.json": ""}
        for name, expected in cases.items():
            with self.subTest(name):
                self.assertEqual(jte.guess_language(Path(name)), expected)

    def test_effective_language_prefers_the_header(self):
        self.assertEqual(jte.effective_language(jte.FileHeader(language="es-AR"), Path("es.json")),
                         "es-AR")

    def test_effective_language_falls_back_to_the_file_name(self):
        self.assertEqual(jte.effective_language(jte.FileHeader(), Path("it.json")), "it")

    def test_read_file_header_without_a_sidecar(self):
        self.assertEqual(jte.read_file_header(cs.temp_dir() / "es.json"), jte.FileHeader())

    def test_read_file_header_of_a_damaged_sidecar(self):
        folder = cs.temp_dir()
        cs.write_exact(folder / "es.json.meta", b"{")
        self.assertEqual(jte.read_file_header(folder / "es.json"), jte.FileHeader())

    def test_read_file_header_reads_the_sidecar(self):
        folder = cs.temp_dir()
        cs.write_exact(folder / "es.json.meta", cs.sidecar_doc(version="3.1.4"))
        self.assertEqual(jte.read_file_header(folder / "es.json").version, "3.1.4")
```

- [ ] **Step 3: Run them to see them fail**

Run: `python tests/check_core_json.py`
Expected: the new classes error with `AttributeError: ... 'parse_sidecar_bytes'` and similar.

- [ ] **Step 4: Implement**

Add `date` is already imported (`from datetime import datetime, date`). After the JSON section:
```python
# ══════════════════════════════════════════════════════════════
#  SIDECAR  (<name>.json.meta: per-string status, translator, date, plus the file's header)
# ══════════════════════════════════════════════════════════════

META_SUFFIX = ".meta"   # not ".json": a program that loads every *.json in the folder must not see it
META_FORMAT = 1
LANGUAGE_CODE_RE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$")


@dataclass
class FileHeader:
    """What the XML header held: the language code ("" = guess it from the file name), its
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
    return stem if LANGUAGE_CODE_RE.match(stem) else ""


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
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `python tests/check_core_json.py` → `PASSED: 0 failure(s)`.

- [ ] **Step 6: Run all checks and commit**

`python tests/run_all.py` → `N passed, 0 failed`.
```bash
git add json_translation_editor.py tests/core_support.py tests/check_core_json.py
git commit -F - <<'EOF'
feat: read and write the .json.meta sidecar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: Switch the app from XML to JSON

The biggest task: the app stops reading XML. Every check that builds XML moves to JSON in the same commit, because the hook runs all of them. Work through the steps in order and run the named check after each group.

**Files:**
- Modify: `json_translation_editor.py` (`StringEntry`, load/save bundle, `TranslationModel.data`, `MainWindow` state/load/save/close/autosave/open/drop/merge/delete/properties/backup header/restore label, `BackupThread.run`, file dialogs and texts; delete the XML code)
- Modify: `tests/core_support.py`, every `tests/check_*.py` with XML hits, `tests/README.md` sample-data lines
- Delete: `tests/check_core_xml.py`, `tests/data/Latvian*.xml`, `tests/data/Latvian*.csv`
- Create: `tests/data/es.json.meta`, `tests/data/es.glossary.csv`

**Interfaces:**
- Consumes: Task 4 (`parse_json_bytes`, `dump_json_pairs`, `JsonStyle`, `DEFAULT_JSON_STYLE`, `JsonFormatError`), Task 5 (sidecar API).
- Produces:
  - `StringEntry(name, translator, status, modify_date, text, position=0)` — keyword construction everywhere
  - `entries_from_pairs(pairs) -> List[StringEntry]` (positions 1..n, all New)
  - `dump_json(entries, style) -> bytes`
  - `@dataclass class LoadedFile: entries; style; round_trips: bool; header: FileHeader; notices: List[Tuple[str, str]]; meta_blocked: bool`
  - `load_translation_file(path: Path, keep_damaged: bool = True) -> LoadedFile`
  - `class MetadataWriteError(Exception)`
  - `save_translation_file(path, entries, style, header, write_meta: bool = True) -> None`
  - `MainWindow` attributes `header: FileHeader`, `json_style: JsonStyle`, `round_trips: bool`, `_meta_blocked: bool`; read-only properties `target_culture`, `display_language`, `file_version` (replaces `xml_version`)
  - `MainWindow._apply_merge_diff(diff, additions_to_add, conflict_resolutions, deletions_to_remove)` (no date arguments)
  - `MainWindow._write_files(path) -> None` (raises like `save_translation_file`)
  - `cs.write_pair(folder, stem, pairs, meta=None, header=None) -> Path`, `cs.make_entry(...)` with `position`

- [ ] **Step 1: Write the failing load/save tests**

Append to `tests/check_core_json.py`:
```python
def _pair(pairs, meta=None, name="es"):
    return cs.write_pair(cs.temp_dir(), name, pairs, meta=meta)


class LoadTests(unittest.TestCase):
    def test_without_a_sidecar_every_entry_is_new(self):
        loaded = jte.load_translation_file(_pair(PAIRS))
        self.assertEqual({e.status for e in loaded.entries}, {"New"})

    def test_sidecar_metadata_is_applied(self):
        loaded = jte.load_translation_file(_pair(PAIRS, {"Save": ("Review", "Jo", ISO)}))
        self.assertEqual(loaded.entries[0].status, "Review")

    def test_positions_count_from_one(self):
        loaded = jte.load_translation_file(_pair(PAIRS))
        self.assertEqual([e.position for e in loaded.entries], [1, 2, 3])

    def test_header_comes_from_the_sidecar(self):
        loaded = jte.load_translation_file(_pair(PAIRS, {}))
        self.assertEqual(loaded.header.version, "1.0.0")

    def test_damaged_sidecar_is_kept_aside(self):
        path = _pair(PAIRS)
        cs.write_exact(jte.meta_path_for(path), b"{")
        jte.load_translation_file(path)
        self.assertEqual(len(list(path.parent.glob("es.json.meta.corrupt-*"))), 1)

    def test_damaged_sidecar_gives_an_error_notice(self):
        path = _pair(PAIRS)
        cs.write_exact(jte.meta_path_for(path), b"{")
        self.assertEqual(jte.load_translation_file(path).notices[0][1], "error")

    def test_damaged_sidecar_stays_put_when_not_keeping(self):
        path = _pair(PAIRS)
        cs.write_exact(jte.meta_path_for(path), b"{")
        jte.load_translation_file(path, keep_damaged=False)
        self.assertTrue(jte.meta_path_for(path).exists())

    def test_unreadable_sidecar_blocks_its_overwrite(self):
        path = _pair(PAIRS)
        jte.meta_path_for(path).mkdir()   # reading a folder raises OSError
        self.assertTrue(jte.load_translation_file(path).meta_blocked)

    def test_round_trip_flag(self):
        cases = {"canonical": (cs.json_doc(PAIRS), True),
                 "no space after colons": (b'{\n "a":"A"\n}\n', False)}
        for label, (data, expected) in cases.items():
            with self.subTest(label):
                path = cs.write_exact(cs.temp_dir() / "es.json", data)
                self.assertEqual(jte.load_translation_file(path).round_trips, expected)

    def test_refused_file_raises(self):
        path = cs.write_exact(cs.temp_dir() / "es.json", b'{"a": 1}')
        with self.assertRaises(jte.JsonFormatError):
            jte.load_translation_file(path)


class SaveTests(unittest.TestCase):
    def _loaded(self, meta=None):
        path = _pair(PAIRS, meta)
        return path, jte.load_translation_file(path)

    def test_saved_language_file_is_intact(self):
        path, loaded = self._loaded()
        loaded.entries[0].text = "Guardar ya"
        jte.save_translation_file(path, loaded.entries, loaded.style, loaded.header)
        cs.assert_json_intact(self, path, [k for k, _v in PAIRS])

    def test_saved_sidecar_holds_the_metadata(self):
        path, loaded = self._loaded()
        loaded.entries[0].status = "Complete"
        jte.save_translation_file(path, loaded.entries, loaded.style, loaded.header)
        self.assertEqual(json.loads(jte.meta_path_for(path).read_bytes())["entries"]["Save"]["status"],
                         "Complete")

    def test_write_meta_false_leaves_the_sidecar_alone(self):
        path, loaded = self._loaded({"Save": ("Review", "Jo", ISO)})
        before = jte.meta_path_for(path).read_bytes()
        loaded.entries[0].status = "Complete"
        jte.save_translation_file(path, loaded.entries, loaded.style, loaded.header, write_meta=False)
        self.assertEqual(jte.meta_path_for(path).read_bytes(), before)

    def test_sidecar_failure_raises_metadata_write_error(self):
        path, loaded = self._loaded()
        jte.meta_path_for(path).mkdir()
        with self.assertRaises(jte.MetadataWriteError):
            jte.save_translation_file(path, loaded.entries, loaded.style, loaded.header)

    def test_sidecar_failure_still_writes_the_language_file(self):
        path, loaded = self._loaded()
        jte.meta_path_for(path).mkdir()
        loaded.entries[0].text = "Guardar ya"
        try:
            jte.save_translation_file(path, loaded.entries, loaded.style, loaded.header)
        except jte.MetadataWriteError:
            pass
        self.assertIn("Guardar ya".encode("utf-8"), path.read_bytes())

    def test_failed_language_write_raises(self):
        path = cs.temp_dir() / "missing folder" / "es.json"
        with self.assertRaises(OSError):
            jte.save_translation_file(path, [cs.bare_entry("a")], jte.DEFAULT_JSON_STYLE,
                                      jte.FileHeader())

    def test_failed_language_write_writes_no_sidecar(self):
        path = cs.temp_dir() / "missing folder" / "es.json"
        try:
            jte.save_translation_file(path, [cs.bare_entry("a")], jte.DEFAULT_JSON_STYLE,
                                      jte.FileHeader())
        except OSError:
            pass
        self.assertFalse(jte.meta_path_for(path).exists())
```
In `tests/core_support.py`:
- Delete `HEADER`, `FOOTER`, `row()`, `xml_doc()`, `assert_xml_intact()`, the `import html` and `import xml.etree.ElementTree as ET` lines.
- Replace `make_entry` with:
```python
def make_entry(**fields: Any) -> "jte.StringEntry":
    values = dict(name="Save", translator="Jane", status="Complete", modify_date=DEFAULT_DATE,
                  text="Guardar", position=1)
    values.update(fields)
    return jte.StringEntry(**values)
```
- Add:
```python
def write_pair(folder: Path, stem: str, pairs, meta: Optional[Dict[str, Tuple[str, str, str]]] = None,
               header: Optional[Dict[str, str]] = None) -> Path:
    """Write <stem>.json from *pairs* and, when *meta* is given (even {}), its sidecar with those
    entries and *header* fields (sidecar_doc's defaults otherwise). Returns the .json path."""
    path = write_exact(folder / f"{stem}.json", json_doc(pairs))
    if meta is not None:
        write_exact(folder / f"{stem}.json.meta", sidecar_doc(meta, **(header or {})))
    return path
```
- In `open_window`'s docstring nothing changes; it still calls `win._load(path)`.

- [ ] **Step 2: Run them to see them fail**

Run: `python tests/check_core_json.py`
Expected: `LoadTests`/`SaveTests` error (`load_translation_file` missing, `StringEntry` has no `position`).

- [ ] **Step 3: Change `StringEntry` and add the load/save bundle**

Replace the `StringEntry` dataclass:
```python
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
```
Delete `normalize_entry_dates()`.

After `read_file_header()` add:
```python
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
```
`_atomic_write_bytes` is defined further down the file (backup section); that is fine, it is looked up at call time.

Run: `python tests/check_core_json.py` → `ParseTests` … `SaveTests` pass. (The app itself is still wired to XML; the next steps switch it.)

- [ ] **Step 4: Delete the XML code**

Delete from `json_translation_editor.py`: `_START_TAG_PATTERN`, `_START_TAG_RE`, `_SPLIT_RE`, `_ATTR_RE`, `_ATTR_PARSE_DEFAULTS`, `_TEXT_RE`, `_start_tag`, `_get_attr`, `_CDATA_RE`, `_get_text`, `_CULTURE_RE`, `_DISPLAY_LANGUAGE_RE`, `_VERSION_RE`, `parse_xml_header`, `_entry_from_segment`, `parse_file`, `_escape_attr_value`, `_set_attr`, `build_string_xml`, `_file_newline`, `save_file`, `_ROOT_TAG_RE`, `build_header_xml`, `_NEW_STRING_INDENT`, `_NEW_STRING_TEMPLATE`, `insert_additions`, `_ROW_LEAD_RE`, `_remove_entry_segment`. Keep `_file_label`, `_VERSION_PARTS_RE`, `VERSION_PART_MAXIMA`, `parse_version_parts`, `format_version`, `describe_culture`. Change the comment on `DISPLAY_LANGUAGE_MAX_LEN = 64` to `# keeps the info bar and title readable`. Rename the section banner `FILE PROPERTIES` stays.

`glossary_path_for(xml_path)` → parameter `json_path`, docstring example `es.json -> es.glossary.csv`.

- [ ] **Step 5: Rewire `TranslationModel` and `MainWindow` state**

- `TranslationModel.data`: `if col == COL_IDX: return str(entry.position)`.
- `MainWindow.__init__`: delete `self.segments: List[str] = []` and the three `target_culture`/`display_language`/`xml_version` lines; add in their place:
```python
        self.header:     FileHeader = FileHeader()          # the open file's sidecar header
        self.json_style: JsonStyle  = DEFAULT_JSON_STYLE    # layout to write the open file back in
        self.round_trips: bool      = True                  # Task 7 asks before reformatting when False
        self._meta_blocked: bool    = False                 # its sidecar could not be read: leave it alone
```
- Add to `MainWindow` (next to `_get_theme`):
```python
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
```
- Replace every `self.xml_version` with `self.file_version` (`sed -i 's/\bxml_version\b/file_version/g' json_translation_editor.py tests/*.py`).
- Add `from dataclasses import dataclass, replace` (extend the existing import).

- [ ] **Step 6: Rewire load, save, close, autosave, open and drop**

`_open`: title `"Open JSON Translation File"`, filter `"JSON Files (*.json);;All Files (*)"`.

`_load` becomes:
```python
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
```
Add the save helper and rewrite `_write`:
```python
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
```
`_save_as`: title `"Save JSON Translation File"`, filter `"JSON Files (*.json);;All Files (*)"`.

`_autosave_tick`: replace `save_file(self.current_file, self.segments, self.entries)` with `self._write_files(self.current_file)` and add, before `except PermissionError`, :
```python
        except MetadataWriteError as e:
            _log_error(f"autosave: writing the sidecar of {self.current_file}", e)
            self._show_message("Autosave: translations saved, metadata not — Save to retry", 6000, "error")
            return
```

`_close_file`: delete `self.segments = []` and the three culture/language/version resets; add `self.header = FileHeader()`, `self.json_style = DEFAULT_JSON_STYLE`, `self.round_trips = True`, `self._meta_blocked = False`. Keep `closed_label = _file_label(self.current_file.name, self.file_version)` before the resets.

`dragEnterEvent`: `.endswith(".xml")` → `.endswith(".json")`.

`_update_translator_status`: `"Ready — open an XML translation file"` → `"Ready — open a JSON translation file"`. `_update_file_meta_labels` docstring: "from the loaded file's sidecar".

`WelcomeScreen._build_ui`: tagline `"A structured editor for JSON translation files"`; hint `"or drop a .json file anywhere in the main window area"`.

`_build_menu`: `"Open XML…"` → `"Open…"`.

- [ ] **Step 7: Rewire delete, merge and File Properties**

`_delete_entries`: delete the `for entry in entries: _remove_entry_segment(...)` loop (keep `delete_ids` and the list filter).

`_merge_from_file`:
```python
        start = self.settings.get("last_directory") or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select File to Merge From", start, "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        try:
            incoming = load_translation_file(Path(path), keep_damaged=False)
        except Exception as e:
            QMessageBox.critical(self, "Merge Error", f"Failed to read file:\n{e}")
            return
        incoming_culture = effective_language(incoming.header, Path(path))
```
then the existing language-mismatch block unchanged, `compute_merge_diff(self.entries, incoming.entries)`, the dialog block unchanged, and at the end:
```python
        self._apply_merge_diff(diff, additions_to_add, conflict_resolutions, deletions_to_remove)
        for text, level in incoming.notices:
            self._show_message(f"Incoming file: {text}", 6000, level)
```
`_apply_merge_diff(self, diff, additions_to_add, conflict_resolutions, deletions_to_remove)`: delete the `</resources>` guard; the deletion block becomes
```python
        delete_names = {entry.name for entry in deletions_to_remove}
        deleted_count = sum(1 for entry in self.entries if entry.name in delete_names)
        if delete_names:
            self.entries = [entry for entry in self.entries if entry.name not in delete_names]
```
the addition block becomes
```python
        added_count = len(additions_to_add)
        if additions_to_add:
            next_position = max((e.position for e in self.entries), default=0) + 1
            self.entries = self.entries + [replace(entry, position=next_position + i)
                                           for i, entry in enumerate(additions_to_add)]
```
and delete the two `Dates: ...` message blocks at the end. Update the docstring: "into self.entries".

`_open_file_properties` (culture stays read-only until Task 8):
```python
        dlg = FilePropertiesDialog(self.target_culture, self.display_language, self.file_version,
                                   compute_file_facts(self.entries, self.current_file),
                                   self.is_modified, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        language = dlg.display_language()
        parts = dlg.version_parts()
        language_changed = language != self.display_language
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
```
Docstring: "Edit the sidecar's language name and version (File → Properties…)…". `FilePropertiesDialog` docstring: "edit the sidecar header's language name and version". Its `_lang_edit` placeholder → `"e.g. Español"`.

- [ ] **Step 8: Rewire the backup header and the restore texts**

`BackupThread.run`: replace `culture, display_language, version = parse_xml_header(source_path)` with
```python
            header           = read_file_header(source_path)
            culture          = effective_language(header, source_path)
            display_language = header.language_name
            version          = header.version
```
`_do_restore_after_backup`: `parse_xml_header(dest_path)[2]` → `read_file_header(dest_path).version`.
`_do_restore`: `"restored.xml"` → `"restored.json"`, `".xml"` → `".json"`.
`AutosaveBackupDialog`: `"Compress backups (.xml.gz)"` → `"Compress backups (.json.gz)"`.
`_create_backup` docstring example `Latvian.xml.gz` → `es.json.gz`.

- [ ] **Step 9: Check no XML is left in the app**

```bash
grep -n -E "segments|seg_idx|istablet|parse_file|save_file|parse_xml_header|build_header_xml|insert_additions|_remove_entry_segment|normalize_entry_dates|</resources>|\.xml|XML" json_translation_editor.py
```
Expected: no matches except `xml_translation_editor.ico/.png` resource names, `_merge_tint_qss`-style unrelated words (none expected), and comments in `MergeCompareDialog` that say "QTextDocument" (not XML). Fix any real hit.

Run: `python -c "import ast; ast.parse(open('json_translation_editor.py', encoding='utf-8').read()); print('OK')"` → `OK`.

- [ ] **Step 10: Replace the sample data**

```bash
git rm -q tests/check_core_xml.py "tests/data/Latvian.xml" "tests/data/Latvian - merge test.xml" \
  "tests/data/Latvian.glossary.csv" "tests/data/Latvian_restored_2026-09-26_07-33-10.xml" \
  "tests/data/Latvian_restored_2026-09-26_07-33-10.glossary.csv"
```
Create `tests/data/es.json.meta` with this Python (run from the repo root), so it lists the first three keys of the frozen `es.json`, one of them dated 1998 for the date-picker check:
```python
import json
from pathlib import Path
keys = list(json.loads(Path("tests/data/es.json").read_text(encoding="utf-8")))[:3]
meta = {"format": 1, "language": "es", "language_name": "Español", "version": "1.0.0",
        "entries": {keys[0]: {"status": "Complete", "translator": "Jane", "modified": "2025-02-01"},
                    keys[1]: {"status": "Review", "translator": "Jo", "modified": "1998-05-06"},
                    keys[2]: {"status": "Complete", "translator": "Jane", "modified": "2026-09-30"}}}
Path("tests/data/es.json.meta").write_bytes((json.dumps(meta, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
```
Create `tests/data/es.glossary.csv`:
```csv
term,translation,note
path,trazado,
profile,perfil,longitudinal profile
```

- [ ] **Step 11: Move every check to JSON**

Find the work: `grep -n -E "xml_doc|cs\.row\(|HEADER|FOOTER|istablet|seg_idx|segments|parse_file|save_file|Latvian|\.xml|assert_xml_intact|parse_xml_header|build_header_xml|insert_additions|normalize_entry_dates|_remove_entry_segment|xml_version" tests/*.py`

Apply these rules file by file, running each check after editing it:

| XML-era code | JSON replacement |
|---|---|
| `cs.write_exact(p, cs.xml_doc([cs.row(n, t, translator=tr, status=s, modify_date=d), ...]))` | `cs.write_pair(folder, stem, {n: t, ...}, meta={n: (s, tr, iso_d), ...})` where `iso_d` is the ISO form of the date (`date(2025, 2, 1).isoformat()` for `cs.DEFAULT_DATE`) |
| rows whose metadata does not matter | `cs.write_pair(folder, stem, {...})` (no sidecar → all New) |
| `cs.assert_xml_intact(self, path, names)` | `cs.assert_json_intact(self, path, names)` |
| `jte.parse_file(p)` → `(segments, entries, culture, language, version)` | `loaded = jte.load_translation_file(p)` → `loaded.entries`, `effective_language(loaded.header, p)`, `loaded.header.language_name`, `loaded.header.version` |
| `win.segments` / `entry.seg_idx` | delete the assertion; assert on `win.entries`, `e.position` or the saved file instead |
| `win.target_culture = x` / `win.display_language = x` (now read-only properties) | `win.header = jte.FileHeader(language=x)` / `jte.FileHeader(language_name=x)` |
| `cs.make_entry(..., istablet=..., seg_idx=...)` | drop `istablet`; `seg_idx=` → `position=` |
| `"Latvian.xml"` copies of `tests/data/Latvian.xml` (`check_combobox`, `check_date_picker`, `check_file_properties`, `check_groupbox_title`) | copy `tests/data/es.json` **and** `tests/data/es.json.meta` to the scratch folder and load `es.json` |
| `KEY = "Latvian__v4.1.1140"` and backup file names (`check_core_backup`) | write the source as `es.json` with a sidecar `version="4.1.1140"` → `KEY = "es__v4.1.1140"`, `es.json.gz`, `es.glossary.csv`; `RAW` = `cs.json_doc(...)` bytes |
| `Latvian_restored_*.xml` globs (`check_core_workflows`) | `es_restored_*.json` |
| `_file_label("Latvian.xml", ...)` expectations (`check_notifications`) | `_file_label("es.json", "4.1.1140") == "es.json  v4.1.1140"` |
| `build_header_xml` / `parse_xml_header` checks (`check_file_properties`) | delete them; the Save + reopen check reads the sidecar header with `jte.read_file_header(path)` and compares language name and version |
| `normalize_entry_dates` tests, "legacy dates" tests (`check_core_dates_filter`, `check_core_workflows`: `test_file_with_legacy_dates_opens_modified`, `test_save_writes_canonical_dates`, `test_save_with_canonical_dates_saves_an_intact_file`) | delete them: the sidecar stores ISO dates, nothing is normalized on open |
| `_apply_merge_diff(diff, a, c, d, dates_normalized, dates_unrecognized)` | `_apply_merge_diff(diff, a, c, d)` |
| merge "</resources> missing" test (`check_core_merge`) | delete it |
| merge additions "inserted before </resources>" assertions | additions are appended: assert `[e.name for e in win.entries][-len(additions):] == [names...]` |
| deletion "leaves no blank line" test (`check_core_workflows.test_deleting_a_row_leaves_no_blank_line`) | becomes `test_deleting_a_row_changes_only_its_line`: the saved file's lines equal the original's minus that key's line, and the line before it loses its trailing comma when the deleted row was last |

`check_core_corpus.py`: glob `REAL.glob("*.json")`; its six tests become: (1) the app and `json.loads(..., object_pairs_hook=list)` find the same keys in the same order; (2) an unchanged save is byte-identical when `loaded.round_trips`, else `self.skipTest`-style subTest note (`print(f"NOTE {name}: does not round-trip; save would reformat")`); (3) editing the middle entry changes only that line (indented files only); (4) deleting it leaves exactly the other keys (`assert_json_intact`); (5) merging the file into itself changes nothing. Keep the `NOTE` line per file (strings, load/save time). Update `tests/data/real/README.md` to say `*.json` (and that sidecars beside them are read too).

Each test that saves a language file must still end with `cs.assert_json_intact` (or have a sibling test on the same steps that does), as the oracle rule in CLAUDE.md requires for XML today.

- [ ] **Step 12: Run every check**

Run: `python tests/run_all.py`
Expected: `N passed, 0 failed`. Fix failures by finding the XML assumption the failing test still makes; do not weaken an assertion to make it pass.

- [ ] **Step 13: Smoke-test the real app**

Run: `python json_translation_editor.py es.json` (the root file, untracked). Check: 2460 strings load, every status New, the info bar shows `es` at the right, the `#` column counts from 1. Edit one entry, Save, then `git diff --no-index tests/data/es.json es.json` shows exactly one changed line, and `es.json.meta` lists that one entry as Complete. Restore the root file afterwards: `git checkout -- es.json && rm es.json.meta`.

- [ ] **Step 14: Commit**

```bash
git add -A
git status --short | grep -E "\.meta$" ; echo "exit=$?"   # expect only tests/data/es.json.meta staged
git commit -F - <<'EOF'
feat: edit JSON language files with a .json.meta sidecar

The XML parser, segments and header code are gone. A language file is
read as ordered key/value pairs and written back in its own style;
status, translator, date and the language/version header live in the
sidecar. Merge appends additions; deletes drop entries from the list.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 7: Ask before reformatting a file that does not round-trip

**Files:**
- Modify: `json_translation_editor.py` (`MainWindow._write`, `_autosave_tick`, `_load`, `__init__`)
- Test: `tests/check_core_workflows.py`

**Interfaces:**
- Consumes: `MainWindow.round_trips`, `_write_files`.
- Produces: `MainWindow._confirm_reformat(path: Path) -> bool`; `MainWindow._autosave_reformat_warned: bool`.

- [ ] **Step 1: Write the failing tests**

In `tests/check_core_workflows.py` add:
```python
ODD = b'{\n "Save":"Guardar",\n "Open":"Abrir"\n}\n'   # no space after the colons: does not round-trip


class ReformatTests(unittest.TestCase):
    def _open_odd(self, **answers):
        path = cs.write_exact(cs.temp_dir() / "es.json", ODD)
        return path, cs.open_window(path, **answers)

    def test_declined_reformat_leaves_the_file_unchanged(self):
        path, ctx = self._open_odd(question=QMessageBox.No)
        with ctx as (win, _modals):
            win.entries[0].text = "Guardar ya"
            win.is_modified = True
            win._save()
        self.assertEqual(path.read_bytes(), ODD)

    def test_reformat_is_asked_once(self):
        path, ctx = self._open_odd(question=QMessageBox.Yes)
        with ctx as (win, modals):
            win.is_modified = True
            win._save()
            win.is_modified = True
            win._save()
        self.assertEqual(modals.titles("question"), ["Reformat File"])

    def test_accepted_reformat_saves_an_intact_file(self):
        path, ctx = self._open_odd(question=QMessageBox.Yes)
        with ctx as (win, _modals):
            win.is_modified = True
            win._save()
        cs.assert_json_intact(self, path, ["Save", "Open"])

    def test_autosave_skips_a_file_that_would_be_reformatted(self):
        path, ctx = self._open_odd()
        with ctx as (win, _modals):
            win.is_modified = True
            win._autosave_tick()
        self.assertEqual(path.read_bytes(), ODD)
```
(Add `from PySide6.QtWidgets import QMessageBox` to the file's imports if it is not there.)

- [ ] **Step 2: Run them to see them fail**

Run: `python tests/check_core_workflows.py`
Expected: the declined/once/autosave tests `FAIL` (the file is rewritten without asking).

- [ ] **Step 3: Implement**

In `MainWindow`:
```python
    def _confirm_reformat(self, path: Path) -> bool:
        """Before the first save of an open file that would not come back byte for byte: ask."""
        if self.round_trips or path != self.current_file:
            return True
        r = QMessageBox.question(
            self, "Reformat File",
            f"Saving will reformat {path.name} (indent, spacing). The translations themselves do "
            "not change.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return r == QMessageBox.Yes
```
At the top of `_write`: `if not self._confirm_reformat(path): return`.
In `_autosave_tick`, after the `is_modified` guard:
```python
        if not self.round_trips:
            if not self._autosave_reformat_warned:
                self._autosave_reformat_warned = True
                self._show_message(f"Autosave paused: save {self.current_file.name} once with "
                                   "Ctrl+S to confirm reformatting it", 6000, "warning")
            return
```
In `__init__` add `self._autosave_reformat_warned = False`; in `_load` (with the other state) set it back to `False`.

- [ ] **Step 4: Run them to see them pass, then all checks**

`python tests/check_core_workflows.py` → `PASSED`; `python tests/run_all.py` → `N passed, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add json_translation_editor.py tests/check_core_workflows.py
git commit -F - <<'EOF'
feat: ask before reformatting a file that does not round-trip

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 8: File Properties edits the language code

**Files:**
- Modify: `json_translation_editor.py` (`FilePropertiesDialog`, `MainWindow._open_file_properties`)
- Test: `tests/check_file_properties.py`

**Interfaces:**
- Consumes: `LANGUAGE_CODE_RE`, `describe_culture`, `effective_language`.
- Produces: `FilePropertiesDialog(language, display_language, version, facts, has_unsaved, parent)` with accessor `language_code() -> str` and widget `_code_edit: QLineEdit`, `_code_warning: QLabel`.

- [ ] **Step 1: Write the failing tests**

In `tests/check_file_properties.py`, in the dialog section (same `check()` style), add:
```python
    dlg = jte.FilePropertiesDialog("es", "Español", "1.0.0", facts, False, parent=win)
    check("language code is editable and prefilled", dlg._code_edit.text() == "es",
          repr(dlg._code_edit.text()))
    dlg._code_edit.setText("es-AR")
    check("language name follows the code", "Argentina" in dlg._culture_label.text(),
          repr(dlg._culture_label.text()))
    dlg._code_edit.setText("not a code!")
    check("an invalid code disables OK", not dlg._ok_btn.isEnabled(), "OK enabled")
    check("an invalid code shows the hint", not dlg._code_warning.isHidden(), "hint hidden")
    dlg._code_edit.setText("pt-BR")
    check("language_code() returns the trimmed code", dlg.language_code() == "pt-BR",
          repr(dlg.language_code()))
    dlg.reject()
```
(Use the `facts` and `win` objects that section already builds; reuse their names.) And in the real-window part:
```python
    # change only the code, OK, Save, reopen
    with patch.object(jte.FilePropertiesDialog, "exec", lambda d: (d._code_edit.setText("es-AR"), QDialog.Accepted)[1]):
        win._open_file_properties()
    check("a changed code marks the file modified", win.is_modified, "not modified")
    win._save()
    check("the code is saved in the sidecar", jte.read_file_header(path).language == "es-AR",
          repr(jte.read_file_header(path)))
```
(Use the names that part already uses for the window, the path and `patch`.)

- [ ] **Step 2: Run them to see them fail**

Run: `python tests/check_file_properties.py`
Expected: `AttributeError: 'FilePropertiesDialog' object has no attribute '_code_edit'`.

- [ ] **Step 3: Implement the dialog**

In `FilePropertiesDialog.__init__`: parameter `culture` → `language`; `self._culture = culture` → `self._language = language`. Docstring: "edit the sidecar header's language code, language name and version".

In `_build_ui`, replace the culture row with:
```python
        code_row = QHBoxLayout()
        code_row.setSpacing(8)
        self._code_edit = QLineEdit()
        self._code_edit.setPlaceholderText("e.g. es-AR")
        self._code_edit.setMaxLength(35)
        self._code_edit.textChanged.connect(self._on_code_changed)
        self._culture_label = QLabel()
        code_row.addWidget(self._code_edit)
        code_row.addWidget(self._culture_label)
        code_row.addStretch()
        form.addRow("Language code:", code_row)
        self._code_warning = QLabel("Use a code like es, es-AR or zh-Hant-TW.")
        self._code_warning.setWordWrap(True)
        form.addRow(QLabel(), self._code_warning)
```
Delete `self._culture_code` everywhere (its `_apply_style` line too). In `_load_values`, replace the culture block with `self._code_edit.setText(self._language)` (the signal fills the label). Add:
```python
    def _on_code_changed(self, text: str):
        code = text.strip()
        name = describe_culture(code) if LANGUAGE_CODE_RE.match(code) else ""
        self._culture_label.setText(name or ("(unknown language)" if code else ""))
        self._validate()

    def language_code(self) -> str:
        return self._code_edit.text().strip()
```
`_validate`:
```python
    def _validate(self, *_args):
        version_ok = self._stored_parts is not None or self._version_touched
        code_ok = bool(LANGUAGE_CODE_RE.match(self.language_code()))
        self._version_warning.setVisible(not version_ok)
        self._code_warning.setVisible(not code_ok)
        self._ok_btn.setEnabled(bool(self._lang_edit.text().strip()) and version_ok and code_ok)
```
`_validate` can run from `textChanged` before `_ok_btn` exists (the code edit is built first): guard with `if not hasattr(self, "_ok_btn"): return` at its top.
In `_apply_style`: `self._culture_label.setStyleSheet(dim)` and `self._code_warning.setStyleSheet(f"color: {t['text_warn']};")`; size the code edit to its text: `self._code_edit.setFixedWidth(self._code_edit.fontMetrics().horizontalAdvance("zh-Hant-TW") + 24)`.

- [ ] **Step 4: Apply the code in the window**

In `_open_file_properties`, after reading `language` and `parts`:
```python
        code = dlg.language_code()
        code_changed = code != self.target_culture
```
Include `code_changed` in the "nothing changed" test and in the `replace(...)`:
```python
        self.header = replace(
            self.header,
            language=code if code_changed else self.header.language,
            language_name=language if language_changed else self.header.language_name,
            version=format_version(parts) if version_changed else self.header.version)
```
(Comparing with `target_culture`, not the stored code, means OK on a guessed code writes nothing.)

- [ ] **Step 5: Run the check, then all checks**

`python tests/check_file_properties.py` → `PASSED`; `python tests/check_groupbox_title.py` and `python tests/check_spinbox_arrows.py` (they open this dialog) → `PASSED`; `python tests/run_all.py` → `N passed, 0 failed`.

- [ ] **Step 6: Commit**

```bash
git add json_translation_editor.py tests/check_file_properties.py
git commit -F - <<'EOF'
feat: edit the language code in File Properties

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 9: Backups and restore carry the sidecar

**Files:**
- Modify: `json_translation_editor.py` (`_write_backup_slot`, `BackupThread.run`, `MainWindow._do_restore`, `_do_restore_after_backup`, `_read_glossary_backup` → `_read_companion_backup`, `_write_restore_log`)
- Test: `tests/check_core_backup.py`, `tests/check_core_workflows.py`

**Interfaces:**
- Consumes: `meta_path_for`, `glossary_path_for`.
- Produces: `_write_companion(slot_dir: Path, source: Path, data: bytes, compress: bool) -> str` (file name in the slot); `_write_backup_slot(..., meta_source, meta_bytes, meta_md5, ...)`; manifest keys `meta_backed_up`, `meta_file`, `meta_compressed`, `meta_md5_checksum`; `MainWindow._read_companion_backup(slot_dir, info, prefix: str, label: str) -> Tuple[Optional[bytes], Optional[bool]]`.

- [ ] **Step 1: Write the failing tests**

In `tests/check_core_backup.py`, give the module-level `_write_slot()` helper a `meta: bytes = None` parameter (after `glossary`) and pass it on:
```python
        meta_source=source.parent / f"{source.name}.meta" if meta is not None else None,
        meta_bytes=meta,
        meta_md5=hashlib.md5(meta).hexdigest() if meta is not None else None,
```
(`source` there is the `es.json` path Task 6 gave the helper.) Then add to `WriteSlotTests`:
```python
    def test_slot_holds_the_sidecar(self):
        slot = _write_slot(cs.temp_dir() / "bk", compress=False, meta=b"{}\n")
        self.assertEqual((slot / "es.json.meta").read_bytes(), b"{}\n")

    def test_manifest_records_the_sidecar(self):
        info = _manifest(_write_slot(cs.temp_dir() / "bk", compress=True, meta=b"{}\n"))
        self.assertEqual((info["meta_backed_up"], info["meta_file"], info["meta_compressed"],
                          info["meta_md5_checksum"]),
                         (True, "es.json.meta.gz", True, hashlib.md5(b"{}\n").hexdigest()))

    def test_manifest_without_a_sidecar(self):
        self.assertFalse(_manifest(_write_slot(cs.temp_dir() / "bk"))["meta_backed_up"])
```
and to `BackupThreadTests` (after Task 6, `BackupRun` writes `es.json` with a sidecar whose version is `4.1.1140`):
```python
    def test_thread_backs_up_the_sidecar(self):
        b = BackupRun()
        b.run(location_mode="root")
        slot = b.root / KEY / b.slots(b.root)[0]
        self.assertTrue(_manifest(slot)["meta_backed_up"])
```

In `tests/check_core_workflows.py`, `RestoreTests._slot()` gets a `meta: Optional[bytes] = None` parameter passed on exactly like `_write_slot()` above (`meta_source=jte.meta_path_for(source) if meta is not None else None`, `meta_bytes=meta`, `meta_md5=...`). Add to `RestoreTests`:
```python
    META = cs.sidecar_doc({"Old": ("Review", "Jo", "2026-10-02")})

    def test_copy_restore_restores_the_sidecar_with_it(self):
        path = self.load()
        slot, info = self._slot(path, meta=self.META)
        self.modals.answers.update(button="Save as copy", question=QMessageBox.No)
        self.win._do_restore(slot, info)
        copy = next(path.parent.glob("es_restored_*.json"))
        self.assertEqual(jte.meta_path_for(copy).read_bytes(), self.META)

    def test_overwrite_restore_brings_back_the_sidecar(self):
        path = self.load()
        slot, info = self._slot(path, meta=self.META)
        self.modals.answers["button"] = "Overwrite original"
        self.win._do_restore(slot, info)
        meta = jte.meta_path_for(path)
        cs.wait_until(lambda: meta.exists() and meta.read_bytes() == self.META)
        cs.wait_until(lambda: not self.win._backup_threads)
        self.assertEqual(meta.read_bytes(), self.META)
```

- [ ] **Step 2: Run them to see them fail**

`python tests/check_core_backup.py`, `python tests/check_core_workflows.py` → the new tests fail (`unexpected keyword argument 'meta_source'`, missing sidecar).

- [ ] **Step 3: Implement the slot writer**

Add above `_write_backup_slot`:
```python
def _write_companion(slot_dir: Path, source: Path, data: bytes, compress: bool) -> str:
    """Write a file that travels with the backed-up language file (sidecar, glossary) into the
    slot, gzipped when *compress*. Returns its name in the slot."""
    if compress:
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
            gz.write(data)
        name, payload = source.name + ".gz", buf.getvalue()
    else:
        name, payload = source.name, data
    _atomic_write_bytes(slot_dir / name, payload)
    return name
```
`_write_backup_slot` gets keyword parameters `meta_source: Optional[Path] = None, meta_bytes: Optional[bytes] = None, meta_md5: Optional[str] = None` (after the glossary ones; the defaults keep every existing call working). Replace the glossary write body with `_write_companion` and add the same for the sidecar, before the manifest is written:
```python
        meta_backed_up = False
        if meta_source is not None and meta_bytes is not None:
            try:
                info["meta_file"]         = _write_companion(slot_dir, meta_source, meta_bytes, compress)
                info["meta_compressed"]   = compress
                info["meta_md5_checksum"] = meta_md5
                meta_backed_up = True
            except Exception:
                pass  # best-effort, like the glossary: never blocks the language-file backup
        info["meta_backed_up"] = meta_backed_up
```
`BackupThread.run`: read the sidecar like the glossary (`meta_source = meta_path_for(source_path)`, `meta_bytes`/`meta_md5` when it exists, `None` on a read failure) and pass the three to `_write_backup_slot`. In `written_notice`, add `", +metadata"` when `slot_info.get("meta_backed_up")` (before the glossary note).

- [ ] **Step 4: Implement restore**

Rename `_read_glossary_backup(self, slot_dir, info)` to `_read_companion_backup(self, slot_dir, info, prefix: str, label: str)`: it reads `info[f"{prefix}_file"]`, `info.get(f"{prefix}_compressed", True)`, `info.get(f"{prefix}_md5_checksum", "")`, and its mismatch dialog title/text use `label` (`f"{label} Checksum Mismatch"`, `f"MD5 mismatch for the {label.lower()} backup ..."`). The glossary call becomes `self._read_companion_backup(slot_dir, info, "glossary", "Glossary")`.

In `_do_restore`, next to the glossary read:
```python
        meta_raw_bytes, meta_md5_verified = None, None
        if info.get("meta_backed_up", False):
            meta_raw_bytes, meta_md5_verified = self._read_companion_backup(slot_dir, info, "meta", "Metadata")
```
Pass `meta_raw_bytes, meta_md5_verified` through both `_do_restore_after_backup(...)` calls (new parameters after the glossary ones). In `_do_restore_after_backup`, right after the language file is written:
```python
        restored_meta_to = None
        if meta_raw_bytes is not None:
            try:
                _atomic_write_bytes(meta_path_for(dest_path), meta_raw_bytes)
                restored_meta_to = str(meta_path_for(dest_path))
            except Exception as e:
                _log_error(f"restoring the sidecar of {dest_path}", e)
                meta_md5_verified = None
        meta_msg = None
        if info.get("meta_backed_up", False) and restored_meta_to is None:
            meta_msg = ("Metadata restore failed", "error")
```
Show `meta_msg` next to `glossary_msg` at the end. `_write_restore_log` gets `restored_meta_to, meta_md5_verified` and adds `"restored_meta_to"`/`"meta_md5_verified"` to the record only when `restored_meta_to` is not None (same pattern as the glossary keys).

- [ ] **Step 5: Run the checks, then all checks**

`python tests/check_core_backup.py`, `python tests/check_core_workflows.py`, `python tests/check_read_after_exec.py` → `PASSED`; `python tests/run_all.py` → `N passed, 0 failed`.

- [ ] **Step 6: Commit**

```bash
git add json_translation_editor.py tests/check_core_backup.py tests/check_core_workflows.py
git commit -F - <<'EOF'
feat: back up and restore the sidecar with its language file

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 10: Robo-Translate skips entries that already have text

**Files:**
- Modify: `json_translation_editor.py` (`EditDialog._robo_advance`)
- Test: `tests/check_core_workflows.py`

**Interfaces:**
- Consumes: `EditDialog(model, row_index, app_font, shortcuts=..., target_culture=..., transl_cfg=..., parent=...)`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

```python
class RoboSkipTests(unittest.TestCase):
    def test_chain_translates_only_new_untranslated_entries(self):
        path = cs.write_pair(cs.temp_dir(), "es",
                             {"A": "A", "B": "Be", "C": "C", "D": "D"},
                             meta={"C": ("Review", "Jo", "2026-10-02")})
        with cs.open_window(path) as (win, _modals):
            dlg = jte.EditDialog(win.model, 0, win.settings.get_font(), shortcuts={},
                                 target_culture="es", transl_cfg={}, parent=win)
            started = []
            dlg._start_translation = lambda: started.append(dlg.entry.name)
            dlg._robo_active = True
            dlg._robo_advance()
            dlg.reject()
        self.assertEqual(started, ["D"])
```

- [ ] **Step 2: Run it to see it fail**

Run: `python tests/check_core_workflows.py` → `FAIL ...: ['B'] != ['D']`.

- [ ] **Step 3: Implement**

In `_robo_advance` replace `if self.entry.status not in ("Review", "Complete"): break` with:
```python
            # Only an entry nobody has touched: New and its text still the English source. A file
            # opened without a sidecar is all New, but its existing translations must stay.
            if self.entry.status == "New" and self.entry.text == self.entry.name:
                break
```
Update the docstring's second paragraph: "Entries already translated (status Review/Complete, or text that differs from the source) are skipped…".

- [ ] **Step 4: Run it to see it pass, then all checks; commit**

`python tests/check_core_workflows.py` → `PASSED`; `python tests/run_all.py` → green.
```bash
git add json_translation_editor.py tests/check_core_workflows.py
git commit -F - <<'EOF'
feat: Robo-Translate skips entries that already have a translation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 11: Placeholder check in the Edit window and the filter bar

**Files:**
- Modify: `json_translation_editor.py` (new helpers after `FilterEngine`'s imports area — put them right before `class FilterEngine`; `FilterEngine`, `FilterPanel`, `EditDialog`)
- Test: `tests/check_core_dates_filter.py`, `tests/check_core_workflows.py`, `tests/check_combobox.py`

**Interfaces:**
- Consumes: Task 3's freed filter column.
- Produces: `placeholder_mismatch(source: str, translation: str) -> Tuple[List[str], List[str]]`; `placeholder_warning(source: str, translation: str) -> str` ("" when they match); `FilterEngine.check` (`"All"` | `"placeholders"`); `FilterPanel.check_combo`; `EditDialog._placeholder_label`.

- [ ] **Step 1: Write the failing tests**

In `tests/check_core_dates_filter.py`:
```python
class PlaceholderTests(unittest.TestCase):
    def test_warning_text(self):
        cases = {
            "same set": ("Path {n}", "Trazado {n}", ""),
            "missing": ("{name} saved", "guardado", "Missing: {name}"),
            "extra": ("saved", "{nme} guardado", "Extra: {nme}"),
            "both": ("{a} {b}", "{a} {c}", "Missing: {b} · Extra: {c}"),
            "order and repeats ignored": ("{a} {b}", "{b} {a} {a}", ""),
            "angle brackets are not placeholders": ("<path>", "<trazado>", ""),
            "empty braces count": ("{}", "", "Missing: {}"),
        }
        for label, (source, translation, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(jte.placeholder_warning(source, translation), expected)

    def test_filter_keeps_only_mismatches(self):
        engine = jte.FilterEngine()
        engine.check = "placeholders"
        entries = [cs.make_entry(name="{n} a", text="{n} b"), cs.make_entry(name="{n} c", text="d")]
        self.assertEqual([e.text for e in entries if engine.matches(e)], ["d"])
```
In `tests/check_core_workflows.py`:
```python
class PlaceholderLabelTests(unittest.TestCase):
    def _dialog(self, win):
        return jte.EditDialog(win.model, 0, win.settings.get_font(), shortcuts={},
                              target_culture="es", transl_cfg={}, parent=win)

    def test_label_shows_a_missing_placeholder(self):
        path = cs.write_pair(cs.temp_dir(), "es", {"{name} saved": "{name} guardado"})
        with cs.open_window(path) as (win, _modals):
            dlg = self._dialog(win)
            dlg.trans_edit.setPlainText("guardado")
            text = dlg._placeholder_label.text()
            dlg.reject()
        self.assertEqual(text, "Missing: {name}")

    def test_label_is_hidden_when_placeholders_match(self):
        path = cs.write_pair(cs.temp_dir(), "es", {"{name} saved": "{name} guardado"})
        with cs.open_window(path) as (win, _modals):
            dlg = self._dialog(win)
            hidden = dlg._placeholder_label.isHidden()
            dlg.reject()
        self.assertTrue(hidden)
```
In `tests/check_combobox.py`, add `panel.check_combo` to the list of filter-bar combos it visits (where `status_combo` is listed).

- [ ] **Step 2: Run them to see them fail**

`python tests/check_core_dates_filter.py`, `python tests/check_core_workflows.py`, `python tests/check_combobox.py` → `AttributeError: ... 'placeholder_warning'` / `'check_combo'` / `'_placeholder_label'`.

- [ ] **Step 3: Implement the helpers and the filter**

Before `class FilterEngine`:
```python
# A {placeholder} the program fills in at run time ({name}, {n}, {}); a translation that drops or
# misspells one can break the string. <path>-style text is translated on purpose, so it does not count.
_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")


def placeholder_mismatch(source: str, translation: str) -> Tuple[List[str], List[str]]:
    """(missing, extra): the {…} tokens only in the source and only in the translation, sorted.
    Compared as sets, so order and repeats do not matter."""
    src, tr = set(_PLACEHOLDER_RE.findall(source)), set(_PLACEHOLDER_RE.findall(translation))
    return sorted(src - tr), sorted(tr - src)


def placeholder_warning(source: str, translation: str) -> str:
    missing, extra = placeholder_mismatch(source, translation)
    parts = []
    if missing:
        parts.append("Missing: " + " ".join(missing))
    if extra:
        parts.append("Extra: " + " ".join(extra))
    return " · ".join(parts)
```
`FilterEngine.__init__`: `self.check = "All"   # "All" | "placeholders"`. In `matches()` before `return True`:
```python
        # Check
        if self.check == "placeholders" and not placeholder_warning(entry.name, entry.text):
            return False
```
`FilterPanel._build`, where the tablet column was (before the Reset column):
```python
        # ── Check column ──────────────────────────
        self.check_combo = _WidePopupComboBox()
        self.check_combo.addItems(["All", "Placeholder mismatch"])
        self.check_combo.setItemData(
            1, "Entries whose {placeholders} differ between source and translation", Qt.ToolTipRole)
        self.check_combo.currentIndexChanged.connect(self._on_filter)
        check_row = QHBoxLayout()
        check_row.addWidget(self.check_combo)
        self._add_column(outer, "check", "Check", check_row)
```
Add `self.check_combo` to the vertical-policy loop, to `fit_to_font`'s combo tuple, to `_reset_all` (blockSignals / `setCurrentIndex(0)` / unblock, like `status_combo`), to `_on_filter` (`e.check = "placeholders" if self.check_combo.currentIndex() == 1 else "All"`) and to `_refresh_active_indicators` (`"check": (e.check != "All", [self.check_combo])` and the widget tuple).

- [ ] **Step 4: Implement the Edit window line**

In `EditDialog._build`, right after `tg.addLayout(tr_bar)`:
```python
        self._placeholder_label = QLabel("")
        self._placeholder_label.setWordWrap(True)
        self._placeholder_label.setFont(self.app_font)
        self._placeholder_label.hide()
        tg.addWidget(self._placeholder_label)
```
Connect in `__init__` next to the char-count connection: `self.trans_edit.textChanged.connect(self._update_placeholder_warning)`. Add:
```python
    def _update_placeholder_warning(self):
        text = placeholder_warning(self.entry.name, self.trans_edit.toPlainText())
        self._placeholder_label.setText(text)
        self._placeholder_label.setVisible(bool(text))
```
Call it at the end of `_populate()` under the same `hasattr` guard style (`if hasattr(self, "_placeholder_label"): self._update_placeholder_warning()`). In `_apply_style()` add `self._placeholder_label.setStyleSheet(f"color: {t['text_warn']};")` (use the theme variable name that method already uses).

- [ ] **Step 5: Run the checks, then all checks; commit**

The three checks → `PASSED`; also `python tests/check_groupbox_title.py` (filter bar layout) → `PASSED`; `python tests/run_all.py` → green.
```bash
git add json_translation_editor.py tests/check_core_dates_filter.py tests/check_core_workflows.py tests/check_combobox.py
git commit -F - <<'EOF'
feat: warn about {placeholder} mismatches and filter by them

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 12: New Language…

**Files:**
- Modify: `json_translation_editor.py` (imports, `new_language_entries`, `MainWindow._new_language`, `_build_menu`)
- Modify: `tests/core_support.py` (patch `QInputDialog.getText`)
- Test: `tests/check_core_workflows.py`

**Interfaces:**
- Consumes: `save_translation_file`, `FileHeader`, `LANGUAGE_CODE_RE`, `_confirm_close_file`.
- Produces: `new_language_entries(entries: List[StringEntry]) -> List[StringEntry]`; `MainWindow._new_language()`; patched-modal answers `text` and `text_ok`.

- [ ] **Step 1: Let the tests answer the input dialog**

In `tests/core_support.py`, import `QInputDialog` with the other widgets and add to `patches` in `patched_modals`:
```python
        (QInputDialog, "getText",
         staticmethod(lambda *a, **k: (modals.answer("text", ""), modals.answer("text_ok", True)))),
```
Extend the `patched_modals` docstring: "…both file dialogs, QInputDialog.getText (answers["text"], answers["text_ok"])…".

- [ ] **Step 2: Write the failing tests**

```python
class NewLanguageTests(unittest.TestCase):
    def test_new_entries_are_untranslated_and_new(self):
        source = [cs.make_entry(name="Save", text="Guardar", position=1),
                  cs.make_entry(name="Open", text="Abrir", position=2)]
        self.assertEqual([(e.name, e.text, e.status, e.translator, e.modify_date)
                          for e in jte.new_language_entries(source)],
                         [("Save", "Save", "New", "", ""), ("Open", "Open", "New", "", "")])

    def test_new_file_holds_every_key_with_its_english_text(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar", "Open": "Abrir"})
        with cs.open_window(path, text="lv", save_path=str(folder / "lv.json")) as (win, _m):
            win._new_language()
        self.assertEqual(json.loads((folder / "lv.json").read_bytes()), {"Save": "Save", "Open": "Open"})

    def test_new_file_is_intact(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar", "Open": "Abrir"})
        with cs.open_window(path, text="lv", save_path=str(folder / "lv.json")) as (win, _m):
            win._new_language()
        cs.assert_json_intact(self, folder / "lv.json", ["Save", "Open"])

    def test_new_file_records_its_language(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar"})
        with cs.open_window(path, text="lv-LV", save_path=str(folder / "lv.json")) as (win, _m):
            win._new_language()
        self.assertEqual(jte.read_file_header(folder / "lv.json").language, "lv-LV")

    def test_new_file_is_opened(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar"})
        with cs.open_window(path, text="lv", save_path=str(folder / "lv.json")) as (win, _m):
            win._new_language()
            opened = win.current_file
        self.assertEqual(opened, folder / "lv.json")

    def test_cancelled_code_writes_nothing(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar"})
        with cs.open_window(path, text_ok=False, save_path=str(folder / "lv.json")) as (win, _m):
            win._new_language()
        self.assertFalse((folder / "lv.json").exists())

    def test_invalid_code_is_asked_again(self):
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "es", {"Save": "Guardar"})
        with cs.open_window(path, text=["not a code!", "lv"],
                            save_path=str(folder / "lv.json")) as (win, modals):
            win._new_language()
        self.assertEqual(modals.titles("warning"), ["New Language"])
```
(Add `import json` to the test file's imports if missing.)

- [ ] **Step 3: Run them to see them fail**

Run: `python tests/check_core_workflows.py` → `AttributeError: ... 'new_language_entries'` / `'_new_language'`.

- [ ] **Step 4: Implement**

Add `QInputDialog` to the `PySide6.QtWidgets` import. After `entries_from_pairs`:
```python
def new_language_entries(entries: List[StringEntry]) -> List[StringEntry]:
    """Every key of *entries*, in order, untranslated: the value is the English key, so the program
    shows English until the string is translated."""
    return [StringEntry(name=e.name, translator="", status="New", modify_date="", text=e.name,
                        position=i) for i, e in enumerate(entries, start=1)]
```
In `MainWindow`:
```python
    def _new_language(self):
        """File → New Language…: a new language file with the open file's keys, all untranslated."""
        if not self.current_file:
            QMessageBox.warning(self, "New Language", "Open a file first: its keys are copied.")
            return
        if self.is_modified and not self._confirm_close_file():
            return
        code = ""
        while True:
            text, ok = QInputDialog.getText(
                self, "New Language", "Language code (e.g. lv, pt-BR):", text=code)
            if not ok:
                return
            code = text.strip()
            if LANGUAGE_CODE_RE.match(code):
                break
            QMessageBox.warning(self, "New Language", "Use a code like lv, pt-BR or zh-Hant-TW.")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save New Language File", str(self.current_file.parent / f"{code}.json"),
            "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        entries = new_language_entries(self.entries)
        try:
            save_translation_file(Path(path), entries, self.json_style, FileHeader(language=code))
        except Exception as e:
            QMessageBox.critical(self, "New Language", f"Failed to write the new file:\n{e}")
            return
        self.is_modified = False   # the open file was saved or its changes discarded above
        self._load(Path(path))
        self._show_message(f"Created: {Path(path).name}  ({len(entries)} strings)", 5000)
```
`_build_menu`: right after the `"Open…"` action line add `self._act(fm, "New Language…", self._new_language, "")`.

- [ ] **Step 5: Run the check, then all checks; commit**

`python tests/check_core_workflows.py` → `PASSED`; `python tests/run_all.py` → green.
```bash
git add json_translation_editor.py tests/core_support.py tests/check_core_workflows.py
git commit -F - <<'EOF'
feat: create a new language file from the open file's keys

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 13: Sync Keys from File…

**Files:**
- Modify: `json_translation_editor.py` (`SyncDiff`, `compute_sync_diff`, `insert_synced`, `merge_row_reason`, `MergeConflictDialog`, `MergeCompareDialog`, `MainWindow._sync_keys_from_file`, `_apply_sync`, `_build_menu`)
- Test: `tests/check_core_merge.py`, `tests/check_merge_compare.py`

**Interfaces:**
- Consumes: `load_translation_file`, `MergeConflictDialog`'s accessors.
- Produces:
  - `@dataclass class SyncDiff: additions: List[StringEntry]; deletions: List[StringEntry]`
  - `compute_sync_diff(open_entries, reference_entries) -> SyncDiff`
  - `insert_synced(open_entries, reference_entries, additions) -> List[StringEntry]` (new list, positions 1..n)
  - `merge_row_reason(kind, open_entry, incoming_entry, other: str = "incoming") -> str`
  - `MergeConflictDialog(additions, conflicts, deletions, parent=None, sync_mode: bool = False)` with `other_side_name() -> str`
  - `MainWindow._sync_keys_from_file()`, `MainWindow._apply_sync(reference_entries, additions, deletions)`

- [ ] **Step 1: Write the failing tests**

In `tests/check_core_merge.py`:
```python
def _entries(*names):
    return [cs.bare_entry(n, text=f"{n}!") for n in names]


class SyncDiffTests(unittest.TestCase):
    def test_additions_are_the_reference_keys_this_file_lacks(self):
        diff = jte.compute_sync_diff(_entries("a", "c"), _entries("a", "b", "c", "d"))
        self.assertEqual([e.name for e in diff.additions], ["b", "d"])

    def test_additions_are_untranslated_and_new(self):
        diff = jte.compute_sync_diff(_entries("a"), _entries("a", "b"))
        self.assertEqual((diff.additions[0].text, diff.additions[0].status), ("b", "New"))

    def test_deletions_are_the_keys_the_reference_lacks(self):
        diff = jte.compute_sync_diff(_entries("a", "x", "c"), _entries("a", "c"))
        self.assertEqual([e.name for e in diff.deletions], ["x"])

    def test_values_are_never_compared(self):
        diff = jte.compute_sync_diff([cs.bare_entry("a", "uno")], [cs.bare_entry("a", "one")])
        self.assertEqual((diff.additions, diff.deletions), ([], []))


class InsertSyncedTests(unittest.TestCase):
    def test_insertion_positions(self):
        cases = {
            "between": (("a", "c"), ("a", "b", "c"), ["a", "b", "c"]),
            "at the start": (("b",), ("a", "b"), ["a", "b"]),
            "at the end": (("a",), ("a", "b"), ["a", "b"]),
            "two in a row": (("a", "d"), ("a", "b", "c", "d"), ["a", "b", "c", "d"]),
            "after a key the reference moved": (("c", "a"), ("a", "b", "c"), ["c", "a", "b"]),
        }
        for label, (open_names, ref_names, expected) in cases.items():
            with self.subTest(label):
                open_entries, reference = _entries(*open_names), _entries(*ref_names)
                additions = jte.compute_sync_diff(open_entries, reference).additions
                result = jte.insert_synced(open_entries, reference, additions)
                self.assertEqual([e.name for e in result], expected)

    def test_positions_are_renumbered(self):
        open_entries, reference = _entries("a", "c"), _entries("a", "b", "c")
        additions = jte.compute_sync_diff(open_entries, reference).additions
        self.assertEqual([e.position for e in jte.insert_synced(open_entries, reference, additions)],
                         [1, 2, 3])


class SyncWindowTests(unittest.TestCase):
    def _sync(self, open_pairs, ref_pairs):
        """Sync id.json from es.json, accepting the dialog's defaults, then save. Returns the path
        and how many times the review dialog was opened."""
        folder = cs.temp_dir()
        path = cs.write_pair(folder, "id", open_pairs)
        ref = cs.write_pair(folder, "es", ref_pairs)
        opened = []

        def fake_exec(dlg):
            opened.append(dlg.windowTitle())
            dlg.done(QDialog.Accepted)   # stores the default choices, as a real Apply & Close does
            return QDialog.Accepted

        with cs.open_window(path, open_path=str(ref)) as (win, _modals):
            with mock.patch.object(jte.MergeConflictDialog, "exec", fake_exec):
                win._sync_keys_from_file()
            win._save()
        return path, opened

    def test_synced_file_gains_the_missing_key_untranslated(self):
        path, _o = self._sync({"a": "satu", "c": "tiga"}, {"a": "uno", "b": "dos", "c": "tres"})
        self.assertEqual(json.loads(path.read_bytes()), {"a": "satu", "b": "b", "c": "tiga"})

    def test_synced_file_is_intact(self):
        path, _o = self._sync({"a": "satu", "c": "tiga"}, {"a": "uno", "b": "dos", "c": "tres"})
        cs.assert_json_intact(self, path, ["a", "b", "c"])

    def test_extra_keys_are_kept_by_default(self):
        path, _o = self._sync({"a": "satu", "x": "lama"}, {"a": "uno"})
        self.assertIn("x", json.loads(path.read_bytes()))

    def test_review_dialog_is_titled_sync_keys(self):
        _path, opened = self._sync({"a": "satu"}, {"a": "uno", "b": "dos"})
        self.assertEqual(opened, ["Sync Keys"])

    def test_matching_keys_open_no_dialog(self):
        _path, opened = self._sync({"a": "satu"}, {"a": "uno"})
        self.assertEqual(opened, [])
```
(Add `json`, `from unittest import mock`, `from PySide6.QtWidgets import QDialog` to the file's imports if missing.)

In `tests/check_merge_compare.py`, add (same `check()` style, using the window that file builds):
```python
    sync_dlg = jte.MergeConflictDialog(
        [cs_entry("b", "b")], [], [cs_entry("x", "lama")], parent=win, sync_mode=True)
    check("sync mode has no conflicts column", not hasattr(sync_dlg, "_auto_chk") or sync_dlg._auto_chk.isHidden(),
          "auto-resolve shown")
    check("sync mode names the reference file", sync_dlg.other_side_name() == "reference",
          repr(sync_dlg.other_side_name()))
    sync_dlg.reject()
```
where `cs_entry(name, text)` is whatever helper that file already uses to build a `StringEntry` (create `def cs_entry(name, text): return jte.StringEntry(name=name, translator="", status="New", modify_date="", text=text, position=0)` at the top if it has none).

- [ ] **Step 2: Run them to see them fail**

`python tests/check_core_merge.py`, `python tests/check_merge_compare.py` → `AttributeError: ... 'compute_sync_diff'` / `unexpected keyword argument 'sync_mode'`.

- [ ] **Step 3: Implement the pure functions**

After `compute_merge_diff`:
```python
@dataclass
class SyncDiff:
    additions: List[StringEntry]   # untranslated new entries, in the reference file's order
    deletions: List[StringEntry]   # entries of the open file that the reference lacks


def compute_sync_diff(open_entries: List[StringEntry],
                      reference_entries: List[StringEntry]) -> SyncDiff:
    """Line the open file's keys up with a reference file of any language. Values are never
    compared or copied: a missing key comes in untranslated (value = key, New)."""
    open_names = {e.name for e in open_entries}
    reference_names = {e.name for e in reference_entries}
    additions = [StringEntry(name=r.name, translator="", status="New", modify_date="", text=r.name)
                 for r in reference_entries if r.name not in open_names]
    deletions = [e for e in open_entries if e.name not in reference_names]
    return SyncDiff(additions, deletions)


def insert_synced(open_entries: List[StringEntry], reference_entries: List[StringEntry],
                  additions: List[StringEntry]) -> List[StringEntry]:
    """A new list with each addition right after the nearest key before it (in the reference
    file's order) that the open file has, or at the start when there is none; positions are
    renumbered 1..n. Keeps the files in the same order, so their diffs line up."""
    adding = {a.name: a for a in additions}
    present = {e.name for e in open_entries}
    after: Dict[Optional[str], List[StringEntry]] = {}
    anchor: Optional[str] = None
    for r in reference_entries:
        if r.name in adding:
            after.setdefault(anchor, []).append(adding[r.name])
        elif r.name in present:
            anchor = r.name
    result = list(after.get(None, []))
    for e in open_entries:
        result.append(e)
        result.extend(after.get(e.name, []))
    return [replace(e, position=i) for i, e in enumerate(result, start=1)]
```
`merge_row_reason(kind, open_entry, incoming_entry, other: str = "incoming")`: the two first branches return `f"only in the {other} file"` and `"only in the open file"`.

- [ ] **Step 4: Implement sync mode in the dialogs**

`MergeConflictDialog.__init__` gets `sync_mode: bool = False` (after `parent`), stored as `self._sync_mode`; window title `"Sync Keys" if sync_mode else "Resolve Merge Conflicts"`. Add:
```python
    def other_side_name(self) -> str:
        """What the second file is called in row texts: 'reference' when syncing keys."""
        return "reference" if self._sync_mode else "incoming"
```
In `_build_ui`:
- After the `columns = [...]` list: 
```python
        if self._sync_mode:
            # Syncing has no conflicts. The buttons still exist (other code enables them), owned by
            # the dialog so they are deleted with it, never shown.
            for btn in (self._btn_select_conflicts, self._btn_keep_open, self._btn_keep_incoming):
                btn.setParent(self)
                btn.hide()
            columns = [c for c in columns if c[1] != "Conflicts"]
```
- Header labels: `"Incoming file value"` → `"New value" if self._sync_mode else "Incoming file value"`.
- After `footer_lay.addWidget(self._auto_chk)`: `self._auto_chk.setVisible(not self._sync_mode)`.
- Status text: in sync mode `f"{len(self._additions)} addition(s), {len(self._deletions)} deletion(s) need your review ({total} row(s) total). Double-click a row to compare."`.

`MergeCompareDialog`: the pane caption `"Incoming file"` → `f"{merge_dlg.other_side_name().capitalize()} file"`; the placeholder `"Not in the incoming file"` → `f"Not in the {self._merge.other_side_name()} file"` (use the attribute name the class stores the merge dialog under); the `merge_row_reason(...)` call passes `other=<that dialog>.other_side_name()`.

- [ ] **Step 5: Implement the window command**

```python
    def _sync_keys_from_file(self):
        """File → Sync Keys from File…: add the keys a reference file has (untranslated) and offer
        the ones it lacks for deletion. Values are never copied."""
        if not self.current_file:
            QMessageBox.warning(self, "Sync Keys", "Open a file first before syncing its keys.")
            return
        start = self.settings.get("last_directory") or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Reference File", start, "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        try:
            reference = load_translation_file(Path(path), keep_damaged=False)
        except Exception as e:
            QMessageBox.critical(self, "Sync Error", f"Failed to read file:\n{e}")
            return
        diff = compute_sync_diff(self.entries, reference.entries)
        if not diff.additions and not diff.deletions:
            self._show_message(f"Keys already match {Path(path).name}", 4000)
            return
        dlg = MergeConflictDialog(diff.additions, [], diff.deletions, parent=self, sync_mode=True)
        if dlg.exec() != QDialog.Accepted:
            return
        self._apply_sync(reference.entries, dlg.accepted_additions(), dlg.deletions_to_remove())

    def _apply_sync(self, reference_entries: List[StringEntry], additions: List[StringEntry],
                    deletions: List[StringEntry]):
        if not additions and not deletions:
            return   # every row rejected/kept: leave the entries (and the model's list) as they are
        delete_names = {e.name for e in deletions}
        kept = [e for e in self.entries if e.name not in delete_names]
        self.entries = insert_synced(kept, reference_entries, additions)
        self.is_modified = True
        self.model.load(self.entries)
        self._apply_filters()
        self._update_title()
        self._update_count()
        self._show_message(f"Synced keys: {len(additions)} added, {len(deletions)} deleted", 6000)
```
`_build_menu`: after `"Merge from File…"` add `self._act(fm, "Sync Keys from File…", self._sync_keys_from_file, "")`.

- [ ] **Step 6: Run the checks, then all checks; commit**

`python tests/check_core_merge.py`, `python tests/check_merge_compare.py`, `python tests/check_read_after_exec.py` → `PASSED`; `python tests/run_all.py` → green.
```bash
git add json_translation_editor.py tests/check_core_merge.py tests/check_merge_compare.py
git commit -F - <<'EOF'
feat: sync keys from a file of any language

Missing keys come in untranslated after their nearest neighbour; keys
the reference lacks are offered for deletion (default Keep). Reuses the
Merge review table without its Conflicts column.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 14: Claude keeps placeholders; note trimmed pastes

**Files:**
- Modify: `json_translation_editor.py` (`_PLACEHOLDER_PROMPT`, `_translate_claude`, `ClaudeSubscriptionSession.translate`, `PlainPasteTextEdit`, `EditDialog`)
- Test: `tests/check_core_translation.py`, `tests/check_core_workflows.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_PLACEHOLDER_PROMPT: str`; `PlainPasteTextEdit.paste_trimmed = Signal()`.

- [ ] **Step 1: Write the failing tests**

In `tests/check_core_translation.py`:
```python
class PlaceholderPromptTests(unittest.TestCase):
    def test_claude_prompt_asks_to_keep_placeholders(self):
        sent = {}

        class _Response:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"content": [{"text": "x"}]}'

        def fake_urlopen(req, timeout=None):
            sent["body"] = json.loads(req.data)
            return _Response()

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            jte._translate_claude("{name} saved", "es", "key", "model")
        self.assertIn(jte._PLACEHOLDER_PROMPT, sent["body"]["messages"][0]["content"])
```
(Add `json` / `mock` imports if missing.)
In `tests/check_core_workflows.py`:
```python
class TrimmedPasteTests(unittest.TestCase):
    def test_trimmed_paste_is_noted_when_the_source_has_outer_spaces(self):
        path = cs.write_pair(cs.temp_dir(), "es", {" (copy)": " (copia)"})
        with cs.open_window(path) as (win, _modals):
            dlg = jte.EditDialog(win.model, 0, win.settings.get_font(), shortcuts={},
                                 target_culture="es", transl_cfg={}, parent=win)
            mime = QMimeData()
            mime.setText(" (copia) ")
            dlg.trans_edit.insertFromMimeData(mime)
            status = dlg._transl_status.text()
            dlg.reject()
        self.assertIn("trimmed", status)
```
(`from PySide6.QtCore import QMimeData`.)

- [ ] **Step 2: Run them to see them fail**

`python tests/check_core_translation.py`, `python tests/check_core_workflows.py` → `AttributeError: ... '_PLACEHOLDER_PROMPT'`, empty status.

- [ ] **Step 3: Implement**

Near `_format_glossary_prompt_block`:
```python
_PLACEHOLDER_PROMPT = ("Keep every {placeholder} (text in curly braces) and every line break exactly "
                       "as in the source.  ")
```
In both prompt strings, after `"Return ONLY the translated text — no explanation, no quotes, no commentary."` insert `f"  {_PLACEHOLDER_PROMPT}"` (keep the glossary block after it).

`PlainPasteTextEdit`:
```python
class PlainPasteTextEdit(QTextEdit):
    """QTextEdit that always pastes as plain text with trimmed whitespace."""

    paste_trimmed = Signal()   # a paste lost leading or trailing whitespace

    def insertFromMimeData(self, source):
        """Strip rich text and surrounding whitespace from any paste."""
        raw = source.text()
        text = raw.strip()
        if text:
            self.insertPlainText(text)
        if text != raw:
            self.paste_trimmed.emit()
```
In `EditDialog.__init__` (next to the other `trans_edit` connections):
```python
        self.trans_edit.paste_trimmed.connect(self._on_paste_trimmed)
```
and:
```python
    def _on_paste_trimmed(self):
        # A key like " (copy)" starts with a space the program relies on; a trimmed paste drops it.
        if self.entry.name != self.entry.name.strip():
            self._transl_status.setText("Note: the source starts or ends with a space; the paste was trimmed.")
```

- [ ] **Step 4: Run the checks, then all checks; commit**

Both checks → `PASSED`; `python tests/run_all.py` → green.
```bash
git add json_translation_editor.py tests/check_core_translation.py tests/check_core_workflows.py
git commit -F - <<'EOF'
feat: tell Claude to keep placeholders; note pastes that lose outer spaces

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 15: Documentation and generated assets

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `docs/FEATURES.md`, `docs/BUILDING.md`, `tests/README.md`, `requirements.txt` (header comment only if it names XML)
- Modify (gitignored, not committed): `Tools/take_screenshots.py`, `Tools/build_user_guide.py`, `Tools/make_readme_images.py`, `Tools/check_doc_links.py`
- Regenerate: `docs/images/*.png`, `Resources/User_Guide.pdf`

**Interfaces:**
- Consumes: the finished app.
- Produces: docs that describe the JSON editor; `Resources/User_Guide.pdf` restored for `build_exe.ps1`.

- [ ] **Step 1: Rewrite CLAUDE.md for JSON**

Work through `CLAUDE.md` top to bottom. Keep everything about the UI, settings, translation engines, backups, tests, launchers and pitfalls that still holds. Change:
- Project overview: flat JSON files + `.json.meta` sidecar; companion-file table (`json_translation_editor.py`, settings and backup names, `tests/data/es.json` + `es.json.meta`), real line count (`wc -l json_translation_editor.py`).
- Replace "Architecture → Data model" with the JSON layer (`parse_json_bytes`/`dump_json_pairs`/`JsonStyle`, `load_translation_file`/`save_translation_file`, `LoadedFile`, sidecar API, `FileHeader`, properties `target_culture`/`display_language`/`file_version`).
- Replace the sections "XML file format" and "XML character escaping" with "JSON file format" (flat object; refusals; style detection; byte-identical save; reformat prompt) and "Sidecar format" (the spec's example; only non-default entries; ISO dates; damaged → `.corrupt-<time>`; blocked when unreadable).
- Key classes table: remove `ToggleSwitch`; add `LoadedFile`, `FileHeader`, `JsonStyle`, `SyncDiff`.
- Save/load flow, Close File, Merge (additions appended, language guard on sidecar/file-name codes), new sections "New Language" and "Sync Keys from File", "Placeholder check", Robo-Translate skip rule, File Properties (editable code), backup manifest `meta_*` keys and restore of the sidecar.
- Delete pitfalls that only concern XML ("Regex parser is intentional", "Never go back to read_text()/write_text()…", "XML escaping — never use html.escape() defaults", "Column # shows XML position" → rewrite as "Column # shows the file position (`position`)"), and the "Opening a file can set `is_modified = True`" pitfall (no date normalization any more). Add: "Never replace `parse_json_bytes`' duplicate check with plain `json.loads`" and "The sidecar extension is `.meta`, not `.json`, on purpose".
- Testing checklist: replace XML-specific items (Latvian.xml, `modifyDate`, `</resources>`, tablet) with their JSON counterparts and add items for New Language, Sync Keys, placeholder line/filter, reformat prompt, damaged sidecar, Robo skip.
- Every `Latvian.xml` → `es.json`; every `xml_translation_editor.py` → `json_translation_editor.py` (resource file names stay).

- [ ] **Step 2: Rewrite the user docs**

- `README.md`: landing page for JSON Translation Editor (what it edits, the sidecar in one paragraph, install/run, links to `docs/FEATURES.md` and `docs/BUILDING.md`, the `docs/images` mockups).
- `docs/FEATURES.md`: same structure as now; replace the XML format section with the JSON + sidecar formats; add New Language, Sync Keys, placeholder check; remove Is tablet; settings file name `json_translation_editor_settings.json`; Troubleshooting entries for "refused file" messages and damaged sidecars.
- `docs/BUILDING.md`: script/exe names.
- `tests/README.md`: the check table (remove `check_core_xml`, add `check_core_json` with its test count from the last report), sample data `es.json`/`es.json.meta`, real files `*.json`.

Run: `python Tools/check_doc_links.py` → no broken links (fix any it lists).

- [ ] **Step 3: Point the tools at JSON sample data and regenerate assets**

In the four `Tools/` scripts: import `json_translation_editor`, load `tests/data/es.json` (copied with its `.meta` to a scratch folder) instead of `Latvian.xml`, and read `APP_VERSION`/`APP_NAME` from the new module. Then:
```bash
python Tools/take_screenshots.py dark
python Tools/take_screenshots.py light
python Tools/make_readme_images.py
python Tools/build_user_guide.py
```
Look at every new `docs/images/*.png` (Read tool) and check the window title says "JSON Translation Editor v1". Verify the PDF's links with pikepdf as CLAUDE.md "How to verify" describes (every `/Dest` a literal array).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md docs/FEATURES.md docs/BUILDING.md tests/README.md docs/images Resources/User_Guide.pdf requirements.txt
git commit -F - <<'EOF'
docs: describe the JSON editor; regenerate screenshots and User Guide

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```
(Docs-only changes do not trigger the hook's checks; `Tools/` stays uncommitted.)

---

### Task 16: Final verification

**Files:** none changed unless a check fails.

- [ ] **Step 1: Run every check and the syntax check**

```bash
python -c "import ast; ast.parse(open('json_translation_editor.py', encoding='utf-8').read()); print('OK')"
python tests/run_all.py
```
Expected: `OK`, then `N passed, 0 failed`.

- [ ] **Step 2: Real-file pass over the user's four files**

Copy the user's `es.json`, `id.json`, `it.json`, `pt-BR.json` into `tests/data/real/` (gitignored) and run `python tests/run_all.py core_corpus`. Expected: `PASS`, one `NOTE` per file. Delete the copies afterwards.

- [ ] **Step 3: Manual run**

`python json_translation_editor.py id.json` and walk through: open `id.json` → Sync Keys from `es.json` (205 additions untranslated after their neighbours, 2 deletions defaulting to Keep) → Cancel. File → New Language… `lv` into a scratch folder → 2460 keys, all New. Edit an entry with `{name}` and drop it → amber "Missing: {name}"; Check filter → Placeholder mismatch lists it. File → Properties: change the code to `id-ID`. Do not save the user's files (Discard on close). `git status --short` shows no change to the four root files and no `.meta` files there (`git checkout -- <file>` and delete any `.meta` otherwise).

- [ ] **Step 4: Report**

Tell the user what was built, the commit list (`git log --oneline 61107f1..HEAD`), that nothing was pushed, and that the four language files are unchanged.
