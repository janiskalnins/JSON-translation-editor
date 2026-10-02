# Export and Import — design

**Date:** 2026-10-02
**Status:** approved in conversation; spec awaiting review

## Purpose

A translation is three files side by side: the language file (`es.json`), its sidecar
(`es.json.meta`) and its glossary (`es.glossary.csv`). Moving one to another computer means
finding and copying all three by hand, and bringing it back means Merge from File, which ignores
the glossary.

- **Export** packs the three files into one ZIP for transfer, or writes the language file alone
  for the program that consumes it.
- **Import** takes such a ZIP (or a loose `.json` with its companions) and either unpacks it as a
  new translation or merges it into the existing one, glossary included. It replaces
  **File → Merge from File…**.

## Scope and build order

Two steps, each committed and tested on its own:

1. **Export** (section 1). Usable on its own.
2. **Import** (sections 2–4): the package reader, choosing where the translation goes, the
   Glossary tab in the merge window, and removing Merge from File.

Out of scope: importing anything but this app's three files; deleting glossary terms through
Import; merging the sidecar header (language name, version) into an existing file.

## 1. Export

- **Menu:** File → **Export…**, below Properties…. With no file open: a warning "Open a file
  first before exporting it.", no dialog (as Merge does).
- **Unsaved changes:** a Save / Cancel prompt. Save runs `_save()` as usual (Reformat prompt
  included); the export continues only if `is_modified` is False afterwards — the same honest
  signal `_confirm_close_file()` uses.
- **Choice:** a small dialog, `ExportDialog`, two radio buttons:
  - **Package for another computer (ZIP)** (default) — the language file, its `.json.meta` and
    its `.glossary.csv`, whichever exist (the `.json` always does), plus `export_info.json`.
  - **Translation file only** — just the `.json`, for the consuming program.
  The last choice is remembered.
- **Destination:** `QFileDialog.getSaveFileName()` (its own overwrite prompt applies), starting in
  the last export folder, else the open file's folder:
  - ZIP: `<stem>_v<version>_<YYYY-MM-DD>.zip`, or `<stem>_<YYYY-MM-DD>.zip` with no version.
  - JSON: `<stem>.json`. A destination equal to the open file itself is refused with a warning.
- **Contents:** the files are read from disk and stored byte for byte, flat at the top level of
  the ZIP, compressed (`ZIP_DEFLATED`). The ZIP is built in memory and written with
  `_atomic_write_bytes()`; the JSON-only export is written the same way.
- **`export_info.json`** (ZIP only, UTF-8, `indent=1`):

  ```json
  {
   "format": 1,
   "app": "JSON Translation Editor",
   "app_version": "1",
   "exported": "2026-10-02T21:30:00",
   "language": "es",
   "language_name": "Español",
   "version": "1.0.0",
   "files": [
    {"name": "es.json", "role": "translation", "size": 182311, "md5": "…"},
    {"name": "es.json.meta", "role": "metadata", "size": 2210, "md5": "…"},
    {"name": "es.glossary.csv", "role": "glossary", "size": 340, "md5": "…"}
   ]
  }
  ```

  `language` is `effective_language()` (sidecar code, else guessed from the file name);
  `language_name` and `version` are the header's.
- **Messages:** "Exported: es_v1.0.0_2026-10-02.zip  (3 files)", or "(2 files, no glossary)" when
  a companion is missing; "Exported: es.json" for JSON only. A failed write: "Export failed —
  <file name> could not be written" (error level), the destination untouched.
- **Settings:** a new `export` key in `Settings.DEFAULTS`:
  `{"mode": "zip", "last_directory": ""}` (`mode`: `"zip"` | `"json"`).
- **Code:** module-level `build_export_zip(json_path, header) -> (bytes, list_of_names)` and
  `export_manifest(...)`, so the format is tested without Qt; `MainWindow._export()` does the
  prompts and writing.

## 2. Import — reading and destination

- **Menu:** File → **Import…** replaces **Merge from File…** (removed from the menu; its code is
  reused). Sync Keys from File stays. The picker filter is
  `Translation packages (*.zip *.json)`.

### Reading a ZIP — `read_translation_package(path, temp_dir) -> IncomingPackage`

Checked before anything is written outside a temporary folder:

- **Allowed entries:** exactly one `<stem>.json`, optionally `<stem>.json.meta`,
  `<stem>.glossary.csv` and `export_info.json`, all at the top level. Refused with "Not a
  translation package: <reason>" (a `PackageError`):
  - a name with `/` or `\`, a `..` part, a drive letter or a leading slash;
  - any other file, a second `.json`, or no `.json`;
  - a total uncompressed size above `IMPORT_MAX_BYTES` (10 MB), checked from the ZIP's directory
    before any entry is read;
  - a damaged archive (`zipfile.BadZipFile`, a CRC error while reading).
- **Unpacking:** each allowed entry is read into memory and written into a
  `tempfile.TemporaryDirectory()` under a name the app builds from the stem — never the path
  stored in the ZIP.
- **Checksums:** with `export_info.json` present, every file it lists must be in the ZIP with the
  listed size and MD5, and every file in the ZIP (bar the manifest) must be listed. Any mismatch
  is collected; the caller shows "These files do not match their checksums: es.json.meta —
  Import anyway?" with **No** as the default. Without a manifest (a hand-made ZIP): accepted,
  info message "No checksums in this package — files not verified". An unreadable manifest
  counts as a mismatch of every file.

### Reading a `.json`

The file plus `<stem>.json.meta` and `<stem>.glossary.csv` from its own folder, when they exist.
No checksums.

### Parsing

The incoming language file is read with `load_translation_file(path, keep_damaged=False)` — the
same refusals as Merge today (bad JSON, duplicate key, …), shown in an "Import Error" dialog; its
sidecar problems become "Incoming file: …" messages. The incoming glossary is read with
`parse_glossary()`; its warnings become "Incoming glossary: …" messages.

### Where it goes

`incoming_language = effective_language(incoming.header, incoming_json_name)`; codes compare
case-insensitively with `_` and `-` equal (`pt_br` = `pt-BR`).

1. **A file is open and its `target_culture` equals the incoming language** → merge into the open
   file (section 3).
2. **Otherwise** → `QFileDialog.getExistingDirectory()`, starting in the open file's folder, else
   `last_directory`.
   - **`<folder>/<stem>.json` exists** → if it is not the open file, `_confirm_close_file()`
     (Save / Discard / Cancel) first; then `_load()` it and merge. Merge's existing
     language-mismatch warning still applies.
   - **It does not** → first `_confirm_close_file()` for the current file (Cancel stops here,
     nothing written); then, if `<stem>.json.meta` or `<stem>.glossary.csv` already exist there,
     one Yes/No prompt names them ("…will be replaced"). The companions are written first and the
     `.json` last, each with `_atomic_write_bytes()`, so a failure never leaves a `.json` without
     the sidecar that came with it; then the new file is opened with `_load()`. Message:
     "Imported: es.json  v1.0.0  (N strings) into <folder name>".

- **Headers:** a merge keeps the open file's header (language code, name, version); a freshly
  unpacked file brings its own.
- **Nothing to do:** when strings and glossary have no differences, "Nothing to import — es.json
  already matches" (info), no window.

## 3. The merge window's Glossary tab

### Comparing — `compute_glossary_diff(open_entries, incoming_entries) -> GlossaryDiff`

- Rows are matched by `term.strip().casefold()`. A repeated term: the first row counts, and a
  warning names the rest.
- **additions:** terms only in the incoming glossary. **changes:** the same term with a different
  `translation` or `note` (compared stripped), as `(open_entry, incoming_entry)` pairs. Terms only
  in the open glossary are kept and not listed. Identical rows are nothing.

### The window

`MergeConflictDialog` gains an optional `glossary_diff` argument:

- Its current table and toolbar become the **Strings (N)** tab, unchanged; a **Glossary (M)** tab
  sits beside it. Only tabs with rows are shown (`QTabWidget` with one tab hidden; with no
  glossary rows the dialog looks exactly as today). Sync Keys passes no glossary diff.
- **Glossary table:** Type, Term, Open file, Incoming, Resolution. A file's cell is the
  translation, plus " — note" when there is one; tooltips carry the full text, like the Strings
  table.
  - **New term:** Accept / Reject, default **Accept**, tinted `dlg_count_ok` (Reject untinted).
  - **Changed:** Keep open / Keep incoming, default **Keep open** (glossaries have no dates),
    tinted `dlg_count_warn`, faint for Keep open and full strength for Keep incoming.
- **Toolbar:** Selection (Select All), New terms (Select / Accept / Reject), Changed (Select /
  Keep open / Keep incoming), in a `FlowLayout` with the same captions, dividers and tints as the
  Strings toolbar.
- The footer (auto-resolve checkbox, Apply & Close, Cancel) and the counts strip are shared; the
  strip adds "N new term(s), M changed term(s)". Auto-resolve and the double-click compare pop-up
  apply to the Strings tab only.
- **Results after `exec()`:** `accepted_glossary_additions()` and `glossary_changes_to_apply()`,
  stored in `done()` before `WA_DeleteOnClose` destroys the widgets (see the pitfall in
  CLAUDE.md).

### Applying

- Strings: `_apply_merge_diff()` as today — in memory, ●, saved with Ctrl+S.
- Glossary: the open glossary with each kept change replaced in place and accepted new terms
  appended in incoming order, written at once with `write_glossary()` to
  `glossary_path_for(current_file)` (created if missing), as View → Glossary's Save does, then
  `self.glossary` is reloaded. Message: "Glossary: N added, M updated". A failed write is an
  error message and leaves the strings merge applied.

## 4. Errors, security, tests, docs

- **Errors:** every refusal happens before anything outside the temporary folder is written.
  Dialogs name files, never full temp paths or exception internals (`.claude/rules/security.md`);
  details go to `_log_error()`.
- **Security:** ZIP entry names are validated and never used as paths; the size limit is checked
  before decompression.
- **Tests (written first):**
  - `tests/check_core_export.py` (new, stdlib `unittest` through `core_support`): export ZIP
    contents byte-identical to the files on disk, manifest roles/sizes/MD5s, JSON-only export,
    missing companions, suggested names; the reader's refusals (subfolder, `..`, drive letter,
    unknown file, two `.json`, no `.json`, over 10 MB, bad CRC), checksum mismatch, an unlisted
    file, no manifest; `compute_glossary_diff` (new, changed, identical, case/space folding,
    duplicates) and the applied glossary's order.
  - `tests/check_core_workflows.py`: Export with unsaved changes (Save, Cancel); Import into the
    open file, into a folder holding the file, into an empty folder, over stray companions, with
    nothing to import, from a plain `.json`. Every saved language file goes through
    `cs.assert_json_intact()`.
  - `tests/check_merge_compare.py`, `tests/check_read_after_exec.py`: the tabs, glossary results
    read after a real `exec()`, the Strings-only dialog unchanged.
  - Existing Merge tests keep passing through Import's merge path.
- **Docs:** `docs/FEATURES.md` (Export, Import, Merge from File removed, the `export` settings
  key); `CLAUDE.md` (key classes, an "Export & Import" section replacing "Merge from File" as the
  entry point, the test list and the manual checklist); `tests/README.md`'s table for the new
  check.
