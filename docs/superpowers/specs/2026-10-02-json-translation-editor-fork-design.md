# JSON Translation Editor — fork design

Date: 2026-10-02
Source: XML Translation Editor v39, commit `c7c44e2` (`Z:\GIT\XML Translation Editor`)
Target repo: `Z:\GIT\JSON-translation-editor` (github.com/janiskalnins/JSON-translation-editor)

## Goal

A fork of XML Translation Editor that edits flat JSON language files (English source text as the
key, translation as the value) with every existing feature kept, apart from the XML-only
"Is tablet" flag. Per-string metadata (status, translator, modify date) lives in a sidecar file,
so the JSON stays exactly what the consuming program reads.

Workflows covered: editing existing language files, creating a new language file from an existing
one, and bringing a file's keys in line with another file.

## The files as they are today

Four language files at the repo root, measured 2026-10-02:

| File | Strings | Keys missing vs es.json | Keys only in this file |
|---|---|---|---|
| es.json | 2460 | — | — |
| it.json | 2461 | 0 | 1 |
| pt-BR.json | 2459 | 10 | 9 |
| id.json | 2257 | 205 | 2 |

All four: one flat object, every value a string, no duplicate keys, UTF-8 without BOM, LF, 1-space
indent, non-ASCII written literally, trailing newline. Each is byte-identical to
`json.dumps(obj, ensure_ascii=False, indent=1) + "\n"`. Values hold `{name}`-style placeholders and
`\n` line breaks; `<path>`-style text is translated on purpose (es: `<trazado>`).

## 1. The fork

- **One verbatim commit first**: the XML editor's tracked files at `c7c44e2`, with the message
  naming the source version and commit. All adaptation goes in later commits, so the JSON changes
  can be reviewed as a diff against the original. No XML git history is imported.
- **Copied**: the app, `tests/` (minus `reports/` and `data/real/` contents), `Resources/`
  (minus `User_Guide.pdf`), `run_translator.ps1/.bat`, `build_exe.ps1/.bat`, `docs/FEATURES.md`,
  `docs/BUILDING.md`, `docs/images/` (regenerated later), `CLAUDE.md`, `.claude/rules/`, and the
  `Tools/` scripts (`Tools/` stays gitignored, as in the XML repo).
- **Not copied**: `docs/superpowers/` and `docs/architecture/` of the XML project (they describe
  XML internals; `CLAUDE.md` is the reference), `Latvian.xml`, `.swarm/`, `desktop.ini`,
  `.claude/settings.local.json`, settings files and their archives, backup folders,
  `error_log.txt`, launcher caches. The XML samples in `tests/data/` are copied with the
  verbatim commit (its checks need them) and replaced by JSON samples in the switch-over.
- **Own identity**, so both editors run side by side:

  | | XML editor | JSON fork |
  |---|---|---|
  | App file | `xml_translation_editor.py` | `json_translation_editor.py` |
  | Name / `APP_VERSION` | XML Translation Editor / 39 | JSON Translation Editor / 1 |
  | Settings file | `translation_editor_settings.json` | `json_translation_editor_settings.json` (+ `.backups.zip`) |
  | Backup folder | `XML_Translation_file_Backups` | `JSON_Translation_file_Backups` |
  | Glyph cache folder, AppUserModelID | `XMLTranslationEditor` | `JSONTranslationEditor` |
  | Exe | `XMLTranslationEditor.exe` | `JSONTranslationEditor.exe` |

  The icon stays the same.
- **Repo files**: `.gitignore` merges the XML repo's entries (settings, archives, `.corrupt*`,
  `.tmp`, backups, `Tools/`, `tests/reports/`, `tests/data/real/*` except its README) and adds
  `*.json.meta.corrupt-*`. `.gitattributes` keeps `* text=auto` and adds `tests/hooks/* text eol=lf`.
- The four language files at the root are the user's (committed by them in `0d5d20e`); the fork
  never commits a change to them or a sidecar beside them. The frozen
  test copies go to `tests/data/` (`es.json` plus a short drifted file built for the Sync Keys
  tests).

## 2. Data model and files

### StringEntry

`name` (the JSON key, the English source), `text` (the value), `translator`, `status`
(`New`/`Review`/`Complete`), `modify_date`, `position`. `istablet` is removed. `position` replaces
`seg_idx`: the entry's place in the file, shown in the `#` column (1-based) and stable under
filtering. There are no segments.

### Language file (`es.json`)

- **Load**: `json.loads(..., object_pairs_hook=...)` keeps key order and sees duplicates. Refused
  with an error dialog, nothing opened: invalid JSON (with line and column), a top level that is not
  an object, a value that is not a string, a duplicate key (named).
- **Style detection**: indent (the leading whitespace of the first key line; none means compact),
  newline (`\r\n` if present), BOM, trailing newline, and whether non-ASCII is literal
  (`ensure_ascii=False`) or escaped. The file **round-trips** if writing it back in that style
  reproduces its bytes.
- **Save**: every entry in `position` order, `json.dumps` in the detected style, through
  `_atomic_write_bytes()`. An unchanged round-tripping file saves byte-identical; an edit changes
  only that entry's line. A file that does not round-trip asks once, before its first save: "Saving
  will reformat es.json (indent, spacing). Continue?" (No = save cancelled, file stays modified).
- **Delete**: the entry leaves `self.entries` and is absent from the next save.

### Sidecar (`es.json.meta`)

JSON content in a file whose extension is not `.json`, so a program scanning for `*.json` never
loads it as a language.

```json
{
 "format": 1,
 "language": "es-AR",
 "language_name": "Español (Argentina)",
 "version": "1.0.0",
 "entries": {
  "Guide point": {"status": "Complete", "translator": "Jānis", "modified": "2026-10-02"}
 }
}
```

- Only entries with non-default metadata are listed. An unlisted key is `New`, no translator, no
  date. A file with no sidecar is therefore entirely `New` (the agreed first-open rule).
- `entries` follows the language file's key order; written with `indent=1`, `ensure_ascii=False`,
  LF, trailing newline.
- Dates are stored ISO `YYYY-MM-DD` and shown in this machine's short-date format (`DATE_FMT`).
  The XML editor's on-load date normalization and its "Unsaved changes right after open" side
  effect are dropped.
- `language` is the auto-translate target and the Merge guard's code. Missing → guessed from the
  file name stem (`pt-BR.json` → `pt-BR`, `es.json` → `es`).
- `language_name` and `version` replace the XML header's `DisplayLanguage`/`Version`; `version`
  keeps the XML rules (three parts, maxima 99.99.99999) and the backup key `<stem>__v<version>`.
  Empty = no version, key `<stem>`.
- **Save order**: JSON first, then the sidecar, each atomic. If the JSON write fails the sidecar is
  not written. The sidecar is written on every successful save (it may hold only the header).

### New Language…

File menu. Asks for a language code (checked like File Properties) and proposes `<code>.json` in
the open file's folder, with a Save dialog to change it. Refuses to overwrite an existing file
from inside the dialog flow (the Save dialog's own overwrite prompt applies). Writes the open
file's keys in the same order, every value equal to its key, in the open file's style, plus a
sidecar with the code and an empty `entries`. Then opens the new file. With unsaved changes in the
open file it asks Save/Discard/Cancel first (the Close File prompt).

### Glossary

Unchanged: `<stem>.glossary.csv` (`es.glossary.csv`).

## 3. Features

- **Is tablet removed**: table column, filter-bar column, Edit's toggle and the `ToggleSwitch`
  class, File Properties' tablet fact, the compare pop-up's "Tablet" (its row reads "Length").
- **Open / Save As / drag-and-drop** accept `*.json` only (`.json.meta` is not `.json`).
- **Robo-Translate**: while auto-advancing, an entry is skipped unless its status is `New` **and**
  its text equals its key. The entry the chain starts on is always translated, as is a plain
  Auto-translate.
- **Placeholder check** (new):
  - Placeholders are `\{[^{}]*\}` tokens; compared as sets between source and translation.
  - Edit window: an amber (`text_warn`) line under the translation, "Missing: {name} · Extra:
    {nme}", shown only when the sets differ, updated as you type. Save stays allowed.
  - Filter bar: the column freed by "Is tablet" becomes **Check**, a `_WidePopupComboBox` with
    *All* / *Placeholder mismatch*, with the usual active dot and border, reset by Reset All, and
    persisted (or not) exactly as the Status filter is.
- **Merge from File**: unchanged apart from additions being appended at the end and the
  newest-date rule reading ISO dates. The language guard compares the two files' codes (sidecar or
  file-name guess) and warns on a difference, as today.
- **Sync Keys from File…** (new, File menu, next to Merge): pick a reference file of any language.
  - Additions: keys the reference has and this file lacks. Each is inserted after the nearest
    preceding reference key that this file already has (at the start if none), value = key,
    status `New`.
  - Deletions: keys this file has and the reference lacks; default Keep.
  - Values are never compared or copied. No language guard (cross-language is the point).
  - Review reuses `MergeConflictDialog` with only the Additions and Deletions categories (no
    Conflicts column, no auto-resolve checkbox); a deletion row shows its current value so a
    translation of a renamed key can be copied by hand. Known limitation: a renamed key is an
    addition plus a deletion; nothing pairs them.
  - Nothing to do → info message, no dialog. Applying marks the file modified; no auto-save.
- **File Properties**: language code is a `QLineEdit`, validated as `^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*$`,
  with `describe_culture()` beside it; language name and version as today; facts lose the tablet
  line. Changes are in-memory edits of the sidecar header until Save.
- **Backups**: a slot holds the JSON, the sidecar when it exists, and the glossary. The manifest
  adds `meta_backed_up` and, when true, `meta_file`/`meta_compressed`/`meta_md5_checksum`; header
  fields (`version`, `culture`, `display_language`) come from the sidecar (file-name guess for the
  code). Restore writes the JSON and, when the slot has one, its sidecar together (no checkbox;
  MD5 verified like the main file); a slot without a sidecar restores the JSON only. Glossary keeps
  its checkbox.
- **Info bar, title, messages**: language name and `v<version>` from the sidecar; file messages as
  today ("Loaded: es.json  v1.0.0  (2460 strings)", "(no version)").
- **Translation engines**: unchanged; the target code comes from the sidecar/file name. The Claude
  prompt gains: keep `{placeholders}` and line breaks exactly as in the source.
- **Paste trimming**: kept. The plan checks the Edit window for a source with leading/trailing
  spaces (e.g. `" (copy)"`) and, if a pasted translation would lose them, shows it in the existing
  status line.

## 4. Errors and edge cases

| Situation | Behaviour |
|---|---|
| Invalid JSON / not an object / non-string value / duplicate key | Error dialog naming the problem; nothing opens |
| Sidecar unreadable as JSON or wrong shape | Moved aside as `es.json.meta.corrupt-<time>` (copied if locked); error message in the info bar; file opens all `New` |
| Sidecar entry whose key is not in the file | Warning "Metadata: N entries for keys no longer in the file"; dropped on next save |
| Unknown status in the sidecar | `New`, one warning |
| Unparseable date in the sidecar | Shown as stored (as the XML editor shows a bad date), written back unchanged unless that entry is edited, one warning |
| File does not round-trip in its style | Reformat prompt before the first save |
| JSON write fails | Error dialog, stays modified, sidecar untouched |
| JSON written, sidecar write fails | Error dialog: translations saved, metadata not; stays modified |
| BOM / CRLF / escaped non-ASCII | Kept as found |
| Sidecar exists, JSON missing | Not an openable file; nothing happens |

Message levels follow the XML editor's rule: `error` when an action failed, `warning` when it worked
but found a data problem, `info` otherwise.

## 5. Testing

- `check_core_xml.py` → `check_core_json.py`: load and refusals, style detection, byte-identical
  save of `tests/data/es.json`, one edit changes one line, CRLF/BOM/escaped files, values with `\n`,
  `"`, `\\`, deletion, sidecar round trip, defaults, orphans, damaged sidecar, unknown status, bad
  date, save order and the split-failure case. Oracle (`cs.assert_json_intact`): the standard `json`
  module must read exactly the expected keys, in order, none twice.
- Adjusted: `check_core_merge`, `check_core_workflows`, `check_core_backup`,
  `check_core_dates_filter`, `check_core_corpus` (reads `tests/data/real/*.json`),
  `check_file_properties`, `check_merge_compare`, `check_notifications`, `check_date_picker`,
  `check_read_after_exec`.
- New: placeholder detection and the Check filter, the Robo-Translate skip rule, New Language,
  Sync Keys (insertion position, deletions default Keep, values untouched).
- UI-only checks (scrollbar, checkbox, spin box, combo box, group box, fit checks) pass unchanged
  except where they visit a removed widget.
- `run_all.py` and the pre-commit hook carry over; the hook is enabled in the new clone
  (`git config core.hooksPath tests/hooks`).
- Last step: screenshots, README images and `Resources/User_Guide.pdf` regenerated from JSON
  sample data; `README.md`, `docs/FEATURES.md`, `docs/BUILDING.md` and `CLAUDE.md` rewritten for
  JSON.

## Out of scope

Pairing renamed keys automatically; nested JSON or non-string values; a different icon; importing
the XML repo's history; changing the user's language files.
