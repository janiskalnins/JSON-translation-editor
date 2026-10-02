# JSON Translation Editor — Features and Reference

Every feature of the app, the settings file, the JSON and `.json.meta` file formats and troubleshooting. For a short overview see the [README](../README.md); to install, run from source or build the `.exe`, see [BUILDING.md](BUILDING.md).

## Table of Contents

- [Features](#features)
  - [Translator Session](#translator-session)
  - [Welcome Screen](#welcome-screen)
  - [Main Window](#main-window)
  - [Filtering](#filtering)
  - [Editing Translations](#editing-translations)
  - [Deleting Entries](#deleting-entries)
  - [Session Translator Override](#session-translator-override)
  - [Auto-Translation](#auto-translation)
  - [Autosave](#autosave)
  - [Backup](#backup)
  - [File Properties](#file-properties)
  - [New Language](#new-language)
  - [Merge from File](#merge-from-file)
  - [Sync Keys from File](#sync-keys-from-file)
  - [Keyboard Shortcuts](#keyboard-shortcuts)
  - [Column Widths](#column-widths)
  - [Themes](#themes)
  - [Date Formatting](#date-formatting)
- [Settings](#settings)
  - [Settings backup](#settings-backup)
- [File Formats](#file-formats)
- [Troubleshooting](#troubleshooting)

---

## Features

### Translator Session

When the application starts, a dialog asks for your **translator name**. This name is used for the session only — it is never written to disk and is discarded when you close the app.

- Click **Continue** (or press **Enter**) to set your name.
- Click **Skip** to proceed without a name.

When a session name is active it is shown in the info bar at the bottom of the window.

**How the name is used:** When you edit a translation entry and change its text, the Translator field is automatically set to your session name. If you did not enter a name, the existing translator field value is preserved unchanged.

To set or change your name at any point during a session — without restarting the
app — use **View → Set Translator Name…**. This works whether or not the startup
prompt is enabled, so it's also how you set a name for the first time if you
skipped the startup dialog or have the prompt disabled.

This prompt can be disabled entirely: check **"Skip translator name prompt on startup"**
in **View → Translation Settings…**. When enabled, the app starts directly without
asking — the translator field on saved entries is only set when you type one in
manually (e.g. via the Override checkbox in the Edit window, or after setting a
session name via **View → Set Translator Name…**).

---

### Welcome Screen

When no file is open, the main window shows a Welcome screen: the app logo,
"JSON Translation Editor", the current version, a short tagline, an **Open
File…** button, and a hint that you can also drop a `.json` file anywhere
in the main window area to open it. Opening or closing a file switches between this
screen and the normal filter/table view automatically.

---

### Main Window

The main window has three areas:

**Filter panel (top)** — A bar under the menu with an accent line on top: six labelled controls for narrowing down which entries are shown (see [Filtering](#filtering)). A filter that is currently narrowing the table is marked with an accent border on its field and a ● after its label.

**Translation table (centre)** — The list of string entries. Columns:

| Column | Description |
|--------|-------------|
| `#` | The entry's position in the language file (stays the same when the table is filtered) |
| Source Text | The original string (read-only reference) |
| Translated Text | The translation |
| Status | `New`, `Review`, or `Complete`, shown as a coloured pill |
| Translator | Name of the person (or engine) that last edited this entry |
| Date | Date the entry was last modified |

The row under the pointer is highlighted, and status pills stay readable on selected rows.

**Info bar (bottom)** — A single bar showing entry count, notifications, file metadata, and save status:

| Section | Description |
|---------|-------------|
| Entry count (left) | Total and visible entry counts; updates with filters |
| Refresh hint | `⟳  F5 — Refresh Filter` — shown when a filter is active and entries may be stale |
| Dynamic zone | Messages (`Loaded`, `Saved`, `Autosaved`, etc.) take priority; messages that arrive together are shown one after another, with a dim `+N` while more are waiting. Warnings show in amber and errors in red. Falls back to save status (`Unsaved changes` in amber, `Autosaved at HH:MM:SS` in green — darker shades in the light theme so they stay legible) when no message is showing |
| Message history | A small list button next to the dynamic zone opens this session's messages, newest first with the time. A dot on it marks a warning (amber) or error (red) you haven't looked at yet |
| Language · Version (right, fixed) | The language name and version from the file's `.json.meta` (e.g. `Español (Argentina)  v1.0.0`; the language code when there is no name) — always anchored at the far right, never shifts |

The dynamic zone has a fixed minimum width so the Language and Version labels stay in place regardless of what notification or save-status text is displayed. The green autosaved label remains visible until the next edit.

#### Opening a file

Use **File → Open…** (`Ctrl+O`) or pass the file path as a command-line argument. The file must be one flat JSON object of text (see [File Formats](#file-formats)); anything else is refused with a message naming the problem, and nothing opens. Status, translator and date are read from `<name>.json.meta` beside it; with no such file every string starts as `New`. The language code (from the `.json.meta`, or guessed from the file name — `pt-BR.json` is `pt-BR`) is used as the target language for auto-translation; the language name and version are displayed in the info bar. A [backup](#backup) is created automatically when a file is opened, unless one was already taken for that file within the last few minutes.

#### Saving

- **File → Save** (`Ctrl+S`) — saves to the currently open file.
- **File → Save As…** (`Ctrl+Shift+S`) — saves to a new location.

Saving writes the language file and then its `.json.meta` sidecar. The JSON is written in the layout the file already had — indent, line endings, byte-order mark, escaped or literal accented letters — so a file you did not change saves byte for byte as it was, and an edit changes only that entry's line. If the file's layout is one the app would not reproduce exactly (for example, irregular spacing), the first save asks **"Reformat File"** and explains it will change the indent or spacing, never the translations; answer No to cancel the save. Autosave never asks: it waits, with a message, until you have saved that file once yourself.

If the JSON saves but the sidecar cannot be written, you are told that the translations were saved and the metadata was not; the file stays marked as modified, so the next Save retries.

The title bar shows a bullet (`●`) when there are unsaved changes. You are prompted to save before closing or opening another file.

#### Closing a file

**File → Close File** (`Ctrl+W`) closes the current file and returns the application to its empty startup state, without quitting. Use it to discard a file's changes mid-session — previously this meant closing the whole application.

If there are unsaved changes you are asked whether to **Save**, **Discard**, or **Cancel**. Choosing Save writes the file and then closes it; if that write fails (for example the file is locked by another application), the error is shown and the file stays open with your changes intact. Autosave stops once the file is closed.

#### Editing an entry

- **Double-click** a row, select it and press **Enter**, or use **Edit → Edit Selected**.
- Right-click any row for a context menu with quick status-change and delete options.

---

### Filtering

The filter panel narrows the visible entries in real time. All filters apply simultaneously.

| Filter | Description |
|--------|-------------|
| Search box | Free-text search across Source, Translation, or both fields. See [Search modes](#search-modes) below. |
| Status | Show only `New`, `Review`, `Complete`, or all |
| Translator | Filter by translator name (partial match) |
| Date range | Show entries modified within a date range — enable each bound with its checkbox. Dates are compared in the current regional format (see [Date Formatting](#date-formatting)). |
| Check | **All**, or **Placeholder mismatch**: only entries whose `{placeholders}` differ between the source and the translation (see [Placeholder check](#placeholder-check)) |

The **From Date** defaults to 01.01.2025. When you change it, the value is saved to settings and restored on the next launch.

Dates (here and in the Edit window) are picked in a small pop-up of scrolling columns, like a phone's date wheel: click the date field (or press Enter/Space when it is focused), scroll or drag each column, or use the arrow keys, then press **Enter** or click the highlighted middle row to apply it. **Escape** or a click outside closes the pop-up without changing the date. The mouse wheel and keys do nothing on the closed field, so a date can't change by accident. A line under the columns shows the date format in use (e.g. `Format: dd.mm.yyyy`); the columns follow the same order. Years from 2000 to 2100 are offered.

Click **Reset All** to clear all filters and show the full list. Filters that are currently narrowing the list are marked with an accent border on their field and a ● after their label, so you can see at a glance which ones are active.

If the active filter matches no entries, the table is replaced by a **"No entries match your filter"** message, so an empty result is never mistaken for an empty file.

Typing in the **Search** or **Translator** box re-filters shortly after you stop typing rather than on every keystroke, which keeps large files responsive. The delay is 150 ms by default (`search.debounce_ms` — see [Settings](#settings)). Every other filter control applies immediately, and **Clear search** / **Reset All** are always instant.

The **Search** and **Translator** fields automatically grow when the window is widened, with Search expanding about three times faster than Translator. Search has a minimum width of about 28 characters and Translator about 18 characters even on narrow windows.

#### Search modes

The **Mode** dropdown next to the search box controls how the search text is matched:

| Mode | Behaviour | Example: searching `tab` |
|------|-----------|--------------------------|
| **Starts with** *(default)* | Matches words that start with the search text. | Matches `Tablet`, `My Tablet computer`, `data-tablet`. Does **not** match `database` or `metadata`. |
| **Contains** | Matches the search text anywhere in the field — original behaviour. | Matches `Tablet`, `database`, and `metadata`. |

Both modes are case-insensitive. Punctuation (hyphens, slashes, dots) counts as a word boundary in **Starts with** mode, so `tab` matches `data-tablet`. Special characters like `.`, `(`, or `?` are treated as literal text — they do not need to be escaped.

The **In:** dropdown selects which field to match: **Both**, **Source**, or **Translated**. Both the chosen mode and the chosen field are saved to settings and restored on the next launch.

#### Refreshing the filtered list

When a filter is active and you edit entries (changing status, text, or other fields), some of those entries may no longer match the current filter — but they remain visible until the list is refreshed.

Press **F5** (or **Edit → Refresh Filter**) to re-apply the current filter to the updated data. Entries that no longer match will be removed from the list; entries that now match will appear.

When a filter is active, a **⟳  F5 — Refresh Filter** hint is shown in the info bar at the bottom of the window as a reminder.

---

### Editing Translations

Double-clicking a row (or pressing Enter) opens the **Edit window**.

#### Layout

- **Source Text** — The original string, shown read-only for reference.
- **Translated Text** — Editable text area. An **🌐 Auto-translate** button sits below it (see [Auto-Translation](#auto-translation)).
- **Character-count indicator** — On the right of the auto-translate row, a live `Source: N · Translated: M  (+Δ)` label shows the current source vs. translation length. It is **green** when the translation is within the warning threshold, **amber** when it exceeds the warning threshold, and **red** when it exceeds the concern threshold. The indicator only highlights when the translation is *longer* than the source — shorter translations stay green. Thresholds are configurable per-zone (short vs. long source) — see the [Settings](#settings) section.
- **Placeholder line** — see [Placeholder check](#placeholder-check) below.
- **Metadata row** — Status, Translator, Override checkbox and Date.
- **Navigation bar** — `◀` Previous / counter / `▶` Next buttons, plus Save and Cancel.
- **Info note** — Reminder that changing the text auto-sets status and date.

#### Automatic behaviour when text changes

When the **Translated Text** content is modified:
- **Status** is automatically set to `Complete`.
- **Date** is automatically set to today.
- **Translator** is automatically set to the session name (if one was entered on startup and the Override checkbox is unchecked).

When only metadata is changed (status, translator, date) without touching the translation text, those fields are saved exactly as you set them — the date is not automatically updated.

When **nothing is changed**, clicking Save (or navigating away) writes nothing — the entry remains completely untouched.

#### Placeholder check

Many strings hold `{placeholders}` (`{name}`, `{n}`, `{}`) that the program fills in when it runs. A translation that drops or misspells one can break the string, so the Edit window compares the `{…}` tokens of the source and the translation as you type. When they differ, an amber line under the translation box says what is wrong, e.g. `Missing: {name} · Extra: {nme}`; it disappears as soon as they agree. Order and repeats do not matter, and text such as `<path>` is not a placeholder (it is translated on purpose). The check never blocks saving. To find every affected entry at once, set the filter bar's **Check** filter to **Placeholder mismatch**.

#### Navigation

Use the `◀` and `▶` buttons (or keyboard shortcuts) to move between entries without closing the dialog. Each step automatically saves the current entry before loading the next one. Clicking Cancel discards only the currently displayed entry.

When you paste into the translation box the text is pasted as plain text with leading and trailing spaces removed. If the source itself starts or ends with a space (such as `" (copy)"`), the status line reminds you that the paste was trimmed, so you can add the space back by hand.

---

### Deleting Entries

Delete one or more strings with **Ctrl+Del** (configurable — see [Keyboard Shortcuts](#keyboard-shortcuts)), **Edit → Delete Selected**, or right-click a row → **🗑️ Delete Selected**.

- **Main table** — select one or more rows, then delete. A confirmation dialog shows the source text for a single row, or the count for multiple rows.
- **Edit window** — deletes the entry currently being edited, after the same confirmation. The dialog then advances to whichever entry now occupies that position (like clicking Next), or closes if it was the last remaining entry.

Deleting is an in-memory change like any other edit — nothing is removed from disk until you **Save** (`Ctrl+S`). If a filter is active, a deleted entry disappears from both the visible list and the total count immediately.

`Ctrl+Del` only deletes entries while the main table has focus, or in the Edit window when focus is outside a text field. Typing in the Search/Translator filter boxes, or in the translation/translator-name fields inside the Edit window, keeps the normal "delete word forward" behaviour instead.

---

### Session Translator Override

When a session translator name is active, an **Override** checkbox appears in the metadata row, labelled with the current session name (e.g. `Override  [Jonas]`).

| Checkbox state | Behaviour |
|---------------|-----------|
| **Unchecked** (default) | Session name is applied automatically when translation text changes |
| **Checked** | Whatever is typed in the Translator field is used as-is; session name is ignored |

The checkbox auto-checks itself as soon as you type anything in the Translator field that differs from the session name. You can also check it manually at any time. It resets to unchecked every time you navigate to a new entry.

When there is no session translator (you clicked Skip at startup), the Override checkbox is hidden entirely.

When auto-translation is used, the Override checkbox is automatically checked and the Translator field is set to the engine name (e.g. `DeepL (AI)`), regardless of the session name.

---

### Auto-Translation

The **🌐 Auto-translate** button in the Edit window translates the Source Text into the target language and inserts the result into the translation field for review. The source language is always English; the target language is the file's language code (from its `.json.meta`, or guessed from the file name).

Translation runs in the background — the Edit window stays fully responsive during the request. The status line below the button shows `✓ Translated to lv-LV` on success, or an error message on failure (full details available on hover).

After a successful translation the Override checkbox is checked and the Translator field is set to the engine name so the machine-translated origin is recorded when the entry is saved.

#### Supported engines

| Engine | Quality | Free tier |
|--------|---------|-----------|
| **Claude** | Excellent — understands UI string context and placeholders; model selectable (Haiku 4.5 / Sonnet 5 / Opus 5) | Pay-per-use (~$0.001/string with Haiku 4.5) |
| **Claude (Subscription)** | Excellent — same models as Claude, selected via a persistent sign-in session | Reuses your Claude Pro/Max plan — no per-string API billing |
| **DeepL** | Excellent | 500 000 characters/month (free API key required) |
| **LibreTranslate** | Good | Free (public server or self-hosted) |
| **Google Translate** | Good | Free, no API key |
| **MyMemory** | Good | Free — 5 000 characters/day, 50 000/day with an email address |
| **Microsoft Translator** | Excellent | Azure API key required; free tier available on Azure |

Claude, DeepL, and LibreTranslate use `urllib` from the standard library. Google
Translate, MyMemory, and Microsoft Translator use the `deep-translator` package —
see [Requirements](BUILDING.md#requirements).

#### Setting up translation

Open **View → Translation Settings…** and choose an engine. Only the settings panel for the selected engine is shown; the others collapse automatically.

**Claude** — Enter your API key from [console.anthropic.com](https://console.anthropic.com), and pick a **Model**: Haiku 4.5 (fast, low cost, default), Sonnet 5 (balanced), or Opus 5 (highest quality).

**Claude (Subscription)** — Click **Sign in with Claude subscription**. This runs `claude setup-token` in the background and opens your browser for an interactive Claude Pro/Max login; once it completes the Status line shows **✓ Signed in** and an OAuth token is stored in settings (never a hand-entered key). Pick a **Model** the same way as the regular Claude engine. Requires Node.js and the Claude CLI (`@anthropic-ai/claude-code`) — both launchers install them automatically if missing. The first translation after signing in is slower (a background session is warmed up); subsequent translations in the same app run reuse that session and are fast. Navigating to another entry, saving, or closing the Edit window while a translation is still running is safe — the abandoned result is discarded, and the next entry still receives its own translation.

**DeepL** — Enter your API key from [deepl.com/pro-api](https://www.deepl.com/pro-api). Free-tier keys end with `:fx` — the application detects this suffix automatically and routes requests to `api-free.deepl.com`. Authentication uses the `Authorization: DeepL-Auth-Key` header (current v2 API standard).

**LibreTranslate** — Enter a server URL (the public `https://libretranslate.com` or your own self-hosted instance). The API key field can be left blank if the server does not require one.

**Google Translate** — No configuration needed; select the engine and start translating.

**MyMemory** — No API key required. Optionally enter an email address to raise the free daily quota from 5 000 to 50 000 characters/day.

**Microsoft Translator** — Enter your Azure Translator resource API key. The Region field is optional and required only for regional (non-global) Azure resources.

#### Testing the connection

Click **🔗 Test Connection** to send the word `"Hello"` to the engine using the field values as currently entered — settings are not saved by this button. The result appears inline: `✓ "Hello" → "Sveiki"  (lv-LV)` on success, or a detailed error message on failure. The test uses the language code of the currently open file, or German (`de-DE`) if no file is open.

#### Robo-Translate

Shift+click the **🌐 Auto-translate** button (or press **Shift+Alt+A**) in the Edit
window to start a hands-off translation chain: it translates the current entry,
counts down (10 seconds by default), advances to the next entry, and repeats — status
line shows `✓  Translated — advancing in {n}s…  (Shift+Alt+A to stop)`.

As the chain advances, an entry is skipped untouched unless its status is `New` **and** its text still equals its source — exactly the state a [New Language](#new-language) file or [Sync Keys](#sync-keys-from-file) gives it. So re-running it over a partly translated file only fills in untranslated entries, and never replaces a translation that was typed in while its status stayed New. The entry you explicitly started the chain on is always translated regardless.

Stop the chain at any time by: toggling it again (Shift+click / Shift+Alt+A), pressing
Escape, closing the Edit window, manually clicking Prev/Next, or a plain click / plain
Alt+A (which stops the chain and does a normal one-off translate instead). The delay and
the `Shift+Alt+A` shortcut are both configurable in **View → Keyboard Shortcuts…**.

#### Glossary

Open **View → Glossary…** to edit a per-file glossary of industry-specific terms
(e.g. bowling, POS, competition terminology) that generic translation often gets
wrong. It's saved as `<filename>.glossary.csv` next to the language file — e.g.
`es.json` → `es.glossary.csv` — so it can also be edited directly in
Excel or Notepad. Each row has a **Term**, its required **Translation**, and an
optional **Note** for context. Use **Add Row** for a blank row, **Duplicate
Row** to copy the selected row (handy for near-identical variants like
singular/plural forms), or **Remove Selected Row** to delete one.

Only the **Claude** and **Claude (Subscription)** engines use the glossary — they're
the only engines that accept free-text context. When a source string contains a
glossary term (case-insensitive, whole word/phrase), the matched term(s) are sent
along with the translation request so the model uses your required translation
instead of guessing — if a string contains several glossary terms, all of them are
sent. Matching also tolerates a regular English plural (a "Lane" entry matches
"Lanes" too, no second row needed), though irregular plurals and other word forms
(e.g. verb tense) still need their own row. Disable this without deleting the file
via **"Use glossary for AI translation"** in Translation Settings.

The glossary CSV is tolerant of external edits: it auto-detects a semicolon or
tab delimiter (common when Excel saves CSV using a European regional format,
including Latvian), falls back to Windows-ANSI decoding if the file wasn't saved
as UTF-8, and recognizes a reordered or renamed header. If any correction was
needed, a notification appears on load, and the Glossary dialog shows a banner
explaining what was fixed before you save — saving always rewrites the file back
into the canonical comma/UTF-8/`term,translation,note` format.

The glossary is also included automatically in this app's [backup](#backup) and
[restore](#restoring-a-backup) system, as a companion file to the language file.

---

### Autosave

Autosave periodically saves the open file without any user action, preventing data loss if the app is closed unexpectedly.

Configure via **View → Autosave & Backup…**:

| Setting | Default | Description |
|---------|---------|-------------|
| Enable autosave | Off | Turn the autosave timer on or off |
| Interval | 5 minutes | How often to save (1–60 minutes) |

Autosave behaves identically to **Ctrl+S** — it writes to the currently open file in place.

#### Status bar feedback

After a successful autosave the info bar label changes from the amber "Unsaved changes" to a **green "Autosaved at HH:MM:SS"**, and stays green until the next edit. This makes it easy to confirm a save happened without interrupting your workflow.

#### Locked file handling

If the file is locked by another process at the moment autosave fires (common when the JSON file is open in another application), a dialog appears:

```
Autosave — File Locked
──────────────────────────────────────────────
Autosave failed at 14:32:07

The file could not be written:
  C:\MyApps\es.json

[error detail]

This usually means another application has the file open.

  [ Save As… ]   [ Skip ]
```

- **Save As…** — opens the standard Save As dialog so you can write the file to a different location or name. The application switches to the new file going forward.
- **Skip** — dismisses the dialog and tries again at the next autosave interval. No changes are lost.

---

### Backup

A backup is created automatically **when a file is opened**, and again automatically right before a restore overwrites an existing file (see [Restoring a backup](#restoring-a-backup)). Backups can be stored next to the language file being backed up, in the editor's own root folder, or both at once — see **Backup location** below.

Re-opening a file shortly after closing it does **not** create a second backup: if the newest slot for that file is younger than the **Skip if backed up within** interval (5 minutes by default), the backup is skipped and the info bar says so. This matters because pruning removes the oldest slot first, so redundant backups of an unchanged file would otherwise push genuinely older snapshots out of the retention window. The safety backup taken before a restore overwrites a file is never skipped, whatever the interval is set to.

Backups run in the background, so opening a large file never freezes the window — the file appears immediately and the "Backup: …" message follows a moment later.

#### Folder layout

```
JSON_Translation_file_Backups/
  es__v1.0.0/                         ← one folder per (filename, version) pair
    2025-03-05_14-30-00/              ← one folder per session / timestamp
      es.json.gz                  ← compressed backup (or es.json if uncompressed)
      es.json.meta.gz             ← its metadata sidecar, if one exists
      es.glossary.csv.gz         ← paired glossary backup, if one exists
      backup_info.json                ← metadata and checksum
```

This `JSON_Translation_file_Backups` tree can exist in up to two places — next to `json_translation_editor.py`, and/or next to each language file you open — depending on the **Backup location** setting. Each location holds a fully independent, complete backup history; nothing about one location depends on the other still existing. Files whose `.json.meta` has no version use a plain `<stem>` folder name (e.g. `es/`).

Each timestamped slot contains:

- The backup file itself (`.json.gz` when compression is enabled, plain `.json` otherwise), and beside it the `.json.meta` sidecar under the same rule when one exists.
- A `backup_info.json` manifest with:

| Field | Description |
|-------|-------------|
| `original_path` | Full path to the source file at the time of backup |
| `backup_created` | ISO 8601 creation timestamp |
| `original_size_bytes` | File size before compression |
| `backup_file` | Name of the backup file in this slot |
| `compressed` | `true` or `false` |
| `md5_checksum` | MD5 hash of the original content for integrity verification |
| `version` / `culture` / `display_language` | The sidecar's `version`, language code (guessed from the file name when it has none) and language name at backup time, or `""` if absent |
| `location` | `"root"` or `"next_to_file"` — which location this specific slot was written to |
| `backup_key` | The folder name directly under `JSON_Translation_file_Backups/` for this slot |
| `trigger` | `"file_open"` for a normal open-time backup, `"pre_restore_safety"` for the automatic snapshot taken just before a restore overwrites the file |
| `is_fallback` | `true` only when a "Next to file only" backup couldn't be written and fell back to the root location |
| `glossary_backed_up` | `true` if a paired glossary (`<stem>.glossary.csv`) existed and was backed up into this slot, `false` otherwise |
| `glossary_file` / `glossary_compressed` / `glossary_md5_checksum` | Only present when `glossary_backed_up` is `true` — the glossary's filename in this slot, whether it's compressed, and its MD5 checksum |
| `meta_backed_up` | `true` if the file's `.json.meta` existed and was backed up into this slot, `false` otherwise |
| `meta_file` / `meta_compressed` / `meta_md5_checksum` | Only present when `meta_backed_up` is `true` — the sidecar's filename in this slot, whether it's compressed, and its MD5 checksum |

#### Restoring a backup

Use **File → Restore from Backup…** to open the built-in restore browser.

The dialog shows all discovered backup slots — from the editor root and from every folder that's ever received a next-to-file backup — nested by filename, then by version, then by timestamp (newest first), with columns for date/time, original size, whether the slot is compressed, and which location it lives at (Next to file / Root). A detail bar at the bottom shows the original file path, creation timestamp, and MD5 checksum of the selected slot.

1. Select a backup slot from the tree.
2. Click **Restore Selected** (or double-click the slot).
3. Choose **Overwrite original** to write back to the original path, or **Save as copy** to write a new file named `<stem>_restored_<timestamp>.json` (with its own `.json.meta`) in the same folder.
4. If a file currently exists at the destination, it's automatically backed up first (tagged as a safety backup) before being overwritten — so restoring the wrong slot is always recoverable.
5. If overwriting the currently open file, you will be prompted to confirm discarding unsaved changes.
6. After a successful restore the application offers to open the restored file immediately.

To remove a backup you no longer need, select it and click **Delete Selected**. You'll be asked to confirm — the confirmation calls out explicitly if it's the only backup remaining for that file at that location. Deletion is permanent and cannot be undone from within the app.

If the selected backup slot includes a glossary, an **"Also restore glossary"**
checkbox appears in the restore browser — check it to restore
`<stem>.glossary.csv` alongside the language file, written to match wherever the language file
itself was restored (original location, or a `_restored_<timestamp>` copy).
Its default checked state is controlled by **"Restore glossary by default
when restoring a backup"** in **View → Autosave & Backup…**.

The metadata sidecar has no checkbox: a slot that holds one restores it together with the language file (MD5-checked like the file itself), so the statuses always match the translations; a slot made before the file had a sidecar restores the JSON only.

A restore record is appended to `restore_log.json` in the language backup folder for auditing.

**MD5 verification** — the restored content is checked against the stored checksum. A mismatch warning is shown (with an option to continue) if the backup file appears corrupted.

#### Backup settings

Configure via **View → Autosave & Backup…**:

| Setting | Default | Description |
|---------|---------|-------------|
| Enable backup | On | Create a backup when a file is opened |
| Keep last | 5 | Maximum number of backup slots to retain per file, per location |
| Skip if backed up within | 5 minutes | Don't create a second backup when this file was already backed up less than this long ago, so re-opening a file doesn't consume a slot. Checked separately for each location. Set to 0 ("Always back up") to back up on every open. The pre-restore safety backup is never skipped |
| Compress backups | On | Store backups as `.json.gz` — typically saves ~70% disk space |
| Backup location | Next to file + Root | Where backups are written: next to the language file, the editor's root folder, or both simultaneously (each location keeps its own independent, complete history) |

When the number of slots for a given file+location exceeds the configured limit, the **oldest** slots are deleted automatically. The limit applies per language file (and version, and location) independently.

---

### File Properties

**File → Properties…** shows the open file's language details and a few facts about it. The details are stored in the file's `.json.meta`.

- **Language code**: e.g. `es-AR`, with the language in readable form (*Spanish (Argentina)*) beside it. It is the target language for auto-translation and the code Merge compares. A code the file's `.json.meta` does not hold yet is shown as guessed from the file name (`es.json` → `es`), and is only stored if you change it. Use letters such as `es`, `es-AR` or `zh-Hant-TW`; an invalid code shows a warning and disables OK.
- **Language name**: the human-readable name, e.g. *Español (Argentina)*. Required, up to 64 characters.
- **Version**: three boxes, e.g. `4` . `1` . `1140`. Use the arrows or the mouse wheel, or type the numbers; pressing `.` moves to the next box. The first two parts go up to 99 and the last up to 99999. Numbers are never padded, so `4.1.1220` is saved as `4.1.1220`. If the stored version isn't in this format, the boxes start at 0.0.0 and OK stays disabled until you set one.
- **About this file**: file name, folder, size, last modified, number of strings, New / Review / Complete with percentages, and untranslated strings (translation still equals the source). The counts include unsaved changes.

**OK** applies the changes like any other edit: the info bar updates at once, the title shows ●, and **Ctrl+S** (or autosave) writes them to the `.json.meta`. The JSON file itself is not touched.

Backups are grouped by version, so after changing the version the next backup starts a new group in **File → Restore from Backup…**; the older backups stay under the old version.

---

### New Language

**File → New Language…** starts a translation into another language from the file you have open. It asks for a language code (such as `lv` or `pt-BR`), proposes `<code>.json` in the same folder (the Save dialog lets you change the name or place), and writes a new file with the open file's keys, in the same order and layout, every value set to its key — so the program shows English until a string is translated. Its `.json.meta` is created with the language code and every string `New`. The new file then opens, ready for Robo-Translate or hand editing.

If the open file has unsaved changes you are first asked to **Save**, **Discard** or **Cancel**. After Discard, the new file takes its keys from the open file as it is on disk, not from the edits you discarded. With no file open the command only shows a reminder that it needs one.

---

### Merge from File

Use **File → Merge from File…** to reconcile the currently open file with a second JSON file (e.g. a copy synced from another device). Strings are matched by their exact source (English) text.

- **New strings** in the incoming file are shown as Addition rows, set to Accept by default — switch any you don't want to Reject before clicking **Apply & Close**. Accepted strings are added at the end of the file.
- **Metadata-only differences** (translator/status/date changed but the translation itself didn't) are auto-resolved using whichever side has the newer modify date; ties default to the open file — no review needed.
- **Genuine conflicts** (the same source string translated differently on each side) and **deletions** (a string missing from the incoming file) are shown in the same resolution table — nothing is changed automatically for these.
- A checkbox in the footer lets you auto-resolve all conflicts by newest modify date at once; deletions always require an explicit choice.
- Rows are color-coded by their current resolution (green = will be added, amber = will change to the incoming value, red = will be deleted) — the color updates live as you change a row's choice.
- Select multiple rows (click, Ctrl+click, or Shift+click — including on the row-number column) and use the toolbar's bulk buttons — **Select All** selects everything, and each of the Additions, Conflicts and Deletions columns has a **Select** button that quickly selects every row of that type — to resolve many rows at once instead of one at a time.
- **Double-click a row** to compare it in a pop-up: the source text, the open file's text and the incoming file's text side by side (wrapped, with the words that differ highlighted), plus translator, status, modify date and length for both sides, and a short reason in the header (e.g. "incoming is newer"). The texts are read-only. The two buttons at the bottom resolve the row (Accept/Reject, Keep open/Keep incoming, Keep/Delete) and move on to the next row; the current choice is marked with ✓, so pressing **Enter** keeps it and moves on. **◀ / ▶** step through every row, and the table's selection follows the pop-up. Keys: `Alt+Left` / `Alt+Right` (the Edit window's Previous/Next shortcuts), `Alt+1` / `Alt+2` for the two buttons, `Escape` to close.
- The counts of additions, conflicts and deletions are shown in a status bar at the bottom of the dialog. **Apply & Close** applies your choices and closes the dialog; **Cancel** closes it without changing anything.
- The dialog window can be maximized via its title bar for reviewing long lists.
- If the two files have different language codes (each from its `.json.meta`, or guessed from its file name), you're warned before anything is compared. A damaged `.json.meta` on the incoming file is reported but never moved aside, since you are only reading from it.
- The merge only changes in-memory state — save (`Ctrl+S`) afterward to persist it, same as any other edit.

---

### Sync Keys from File

Use **File → Sync Keys from File…** to bring the open file's *keys* in line with a reference file — typically the English master, or the language you maintain first. The reference can be in any language: only its keys are used, and no language warning is shown. Values are never compared or copied.

- **Additions** are keys the reference has and your file lacks. Each is inserted right after the nearest preceding reference key that your file already has (at the start if there is none), so the two files keep the same order and their diffs line up. It comes in untranslated: its value is the key itself and its status is `New`.
- **Deletions** are keys your file has and the reference lacks. They default to Keep; a deletion row shows the current translation, so you can copy it to a renamed key by hand before deleting.
- Review happens in the same table as Merge, titled **Sync Keys**, with only the Additions and Deletions columns and no auto-resolve checkbox. Additions default to Accept, deletions to Keep. Double-click a row to compare it.
- If the keys already match, a message says so and no dialog opens.
- Applying changes only the in-memory state — save (`Ctrl+S`) afterward.

**Known limitation:** a renamed key shows up as one addition (the new name) plus one deletion (the old name). Nothing pairs them, so the old translation is not carried over automatically; copy it from the deletion row's value.

---

### Keyboard Shortcuts

#### Global (main window)

| Action | Default shortcut |
|--------|-----------------|
| Open file | `Ctrl+O` |
| Save | `Ctrl+S` |
| Save As | `Ctrl+Shift+S` |
| Close file | `Ctrl+W` |
| Edit selected row | `Enter` |
| Refresh filter | `F5` |
| Exit | `Ctrl+Q` |
| Mark selected as New | `Alt+N` |
| Mark selected as Review | `Alt+R` |
| Mark selected as Complete | `Alt+C` |
| Delete selected | `Ctrl+Del` |

Delete Selected also works from within the Edit window (deletes the entry
currently being edited) when focus isn't in a text field — `Ctrl+Delete`
keeps its normal "delete word" behavior while typing in the translation or
translator fields. In the main window this shortcut only fires while the
entry table has focus (unlike the Mark shortcuts above); use **Edit →
Delete Selected** or right-click → Delete Selected when focus is elsewhere.

#### Edit window

| Action | Default shortcut | Configurable |
|--------|-----------------|--------------|
| Previous entry | `Alt+Left` | ✓ |
| Next entry | `Alt+Right` | ✓ |
| Cancel / close | `Escape` | ✓ |
| Save | `Alt+S` | ✓ |
| Auto-translate | `Alt+A` | ✓ |
| Robo-Translate (toggle) | `Shift+Alt+A` | ✓ |
| Tab between fields | `Tab` / `Shift+Tab` | — |

The Merge and Sync Keys dialogs (File → Merge from File…, File → Sync Keys from File…) are mouse/click-driven — its
toolbar buttons have no keyboard shortcuts. Its row compare pop-up (double-click a
row) uses the Edit window's Previous/Next shortcuts, `Alt+1` / `Alt+2` for its two
resolution buttons, and `Escape` to close.

#### Customising shortcuts

Open **View → Keyboard Shortcuts…**. The dialog has three groups: **Edit Window Navigation** (prev, next, cancel, save), **Edit Window Translation** (auto-translate), and **Selected Rows Actions** (mark status, delete).

1. Click **Record…** next to the shortcut you want to change.
2. The display shows *"Press keys…"* — press your desired combination.
3. The binding is captured and saved immediately.
4. Click **Reset** to restore any individual shortcut to its default.

Changes to Edit window shortcuts take effect the next time the Edit window is opened. Changes to Mark and Delete shortcuts take effect immediately.

---

### Column Widths

The translation table columns can be resized by dragging the column separators. Widths are saved automatically to settings within 400 ms of releasing the mouse, and restored on the next launch.

Default widths (Source Text and Translated Text use stretch mode and share available space):

| Column | Default |
|--------|---------|
| `#` | 45 px |
| Source Text | 280 px (stretch) |
| Translated Text | 280 px (stretch) |
| Status | 90 px |
| Translator | 120 px |
| Date | 95 px |

---

### Themes

Switch between Dark and Light themes via **View → Theme → Dark / Light**.

The selected theme is persisted and restored on the next launch. All dialogs follow the active theme.

**Dark theme** — Dark background (`#1e1e1e`) with light text, blue accents.

**Light theme** — White background with dark text, standard blue accents.

Status pill colours adapt per theme (every text and background pair meets WCAG AA contrast):

| Status | Dark theme | Light theme |
|--------|-----------|-------------|
| New | Grey | Light grey |
| Review | Amber on dark brown | Amber on cream |
| Complete | Green on dark green | Green on light green |

---

### Date Formatting

The application reads the **Windows regional short date format** from system settings (Control Panel → Region → Short date) and uses it everywhere: the table, the Edit window date picker, the filter panel date range pickers, and dates stamped on save.

In the `.json.meta` file dates are stored in the fixed ISO form `YYYY-MM-DD`, so the file means the same on every machine; the app converts them to your regional format on open and back to ISO on save. Opening a file never changes it or marks it as having unsaved changes.

A date in the `.json.meta` that is not ISO (for example, edited by hand) is shown exactly as stored, counted in one amber "Metadata: N unrecognized date(s)" message, and written back unchanged unless you edit that entry's date. For the date-range filter, an entry whose date cannot be read is never filtered out. Slash-separated dates that could be either day-first or month-first are resolved using *this machine's own* convention.

---

## Settings

Settings are saved automatically to `json_translation_editor_settings.json` in the same directory as the script.

```json
{
  "font_family": "Segoe UI",
  "font_size": 10,
  "last_directory": "C:\\Translations",
  "theme": "dark",
  "shortcuts": {
    "edit_prev":      "Alt+Left",
    "edit_next":      "Alt+Right",
    "edit_cancel":    "Escape",
    "edit_save":      "Alt+S",
    "auto_translate": "Alt+A",
    "mark_new":       "Alt+N",
    "mark_review":    "Alt+R",
    "mark_complete":  "Alt+C",
    "delete_entries": "Ctrl+Del"
  },
  "column_widths": {
    "0": 45, "1": 280, "2": 280,
    "3": 90, "4": 120, "5": 95
  },
  "filter_from_date": "01.01.2025",
  "search": {
    "mode": "starts_with",
    "field": "both",
    "debounce_ms": 150
  },
  "translation": {
    "engine": "none",
    "claude_api_key": "",
    "claude_model": "claude-haiku-4-5-20251001",
    "claude_subscription_token": "",
    "deepl_api_key": "",
    "deepl_free": true,
    "libretranslate_url": "https://libretranslate.com",
    "libretranslate_key": "",
    "mymemory_email": "",
    "microsoft_api_key": "",
    "microsoft_region": "",
    "glossary_enabled": true
  },
  "robo_translate": {
    "delay_seconds": 10
  },
  "skip_translator_prompt": false,
  "char_count": {
    "enabled": true,
    "short_text_max": 30,
    "short_warn_pct": 0.13,
    "short_concern_pct": 0.30,
    "long_warn_pct": 0.10,
    "long_concern_pct": 0.25,
    "min_warn": 1,
    "min_concern": 2
  },
  "autosave": {
    "enabled": false,
    "interval_minutes": 5
  },
  "backup": {
    "enabled": true,
    "max_count": 5,
    "compress": true,
    "location_mode": "both",
    "min_interval_minutes": 5,
    "known_next_to_file_dirs": [],
    "restore_glossary_default": false
  }
}
```

| Key | Description |
|-----|-------------|
| `font_family` / `font_size` | UI font — change via **View → Choose UI Font…** |
| `last_directory` | Last used directory for Open / Save As dialogs |
| `theme` | `"dark"` or `"light"` |
| `shortcuts` | All configurable keyboard shortcut bindings |
| `column_widths` | Per-column pixel widths, auto-saved when you resize a column |
| `filter_from_date` | Persisted From-date in the date range filter |
| `search.mode` | Search-box matching mode: `"starts_with"` (default) or `"contains"` |
| `search.field` | Search-box field scope: `"both"`, `"source"`, or `"translated"` |
| `search.debounce_ms` | Delay (ms) after the last keystroke in the search/translator filter boxes before re-filtering; default `150`, clamped to `0`–`3000`, no dedicated UI (hand-edit this file) |
| `translation` | Translation engine selection and API credentials |
| `translation.claude_model` | Claude model used for translation: `claude-haiku-4-5-20251001` (default), `claude-sonnet-5`, or `claude-opus-5` |
| `translation.claude_subscription_token` | OAuth token for the Claude (Subscription) engine — populated by the **Sign in with Claude subscription** button in Translation Settings; never hand-edit this value |
| `translation.mymemory_email` | Optional email for the MyMemory engine — raises the free daily quota from 5 000 to 50 000 characters |
| `translation.microsoft_api_key` / `translation.microsoft_region` | Azure Translator credentials for the Microsoft Translator engine |
| `translation.glossary_enabled` | Whether the per-file glossary (`View → Glossary…`) is applied to Claude/Claude Subscription translation requests. Default `true` |
| `robo_translate.delay_seconds` | Countdown (seconds) between auto-advances during a Robo-Translate chain. Default `10` |
| `skip_translator_prompt` | Skip the startup translator-name dialog entirely (`true` / `false`). Default `false` |
| `char_count.enabled` | Show the character-count traffic-light indicator in the Edit window (`true` / `false`) |
| `char_count.short_text_max` | Source-length boundary in characters between **short** zone (strict) and **long** zone (lenient). Default `30`. |
| `char_count.short_warn_pct` / `short_concern_pct` | Warning / concern threshold as fractions of source length, applied to short sources. Defaults `0.13` / `0.30`. |
| `char_count.long_warn_pct` / `long_concern_pct` | Same, applied to long sources. Defaults `0.10` / `0.25`. |
| `char_count.min_warn` / `min_concern` | Absolute minimum delta (chars) that always triggers warning / concern, used as a floor for very short sources. Defaults `1` / `2`. |
| `autosave.enabled` | Whether autosave is active |
| `autosave.interval_minutes` | Autosave interval in minutes (1–60) |
| `backup.enabled` | Whether to create a backup when a file is opened |
| `backup.max_count` | Maximum number of backup slots to keep per language file, per location |
| `backup.compress` | Whether to gzip-compress backup files |
| `backup.location_mode` | Where backups are written: `"next_to_file"`, `"root"`, or `"both"`. Default `"both"` |
| `backup.min_interval_minutes` | Skip the file-open backup when this file was already backed up less than this many minutes ago, so re-opening a file doesn't consume (and prune out) a slot. Checked per location. `0` backs up on every open. Default `5`, matching the autosave interval default. The `pre_restore_safety` backup taken before an overwrite-restore is never skipped |
| `backup.known_next_to_file_dirs` | Internal, auto-maintained list of folders that have ever received a next-to-file backup, used by **File → Restore from Backup…** to discover them. Not user-editable via any dialog |
| `backup.restore_glossary_default` | Default checked state of the "Also restore glossary" checkbox in **File → Restore from Backup…**. Default `false` |

The **translator session name** is never saved — it is discarded when the application closes.

To reset all settings to defaults, delete `json_translation_editor_settings.json` and restart.

### Settings backup

The settings file holds your API keys, so the app keeps its own history of it:

- **Once a day, at startup,** a snapshot of `json_translation_editor_settings.json` is added to `json_translation_editor_settings.backups.zip` in the same folder. The newest 10 snapshots are kept and older ones are dropped. A settings file that can't be read is never added, so damage can't push good snapshots out.
- **If the settings file is damaged at startup** (its content isn't valid JSON — for example, it was truncated by a crash), the app restores the newest usable snapshot automatically, keeps the damaged file beside it as `json_translation_editor_settings.json.corrupt-<date-time>`, and shows a message saying what it did. If there is no snapshot, defaults are used and the damaged file is still kept. A settings file you *deleted* is not restored — deleting it remains the way to reset to defaults.
- **The info bar and the message history record it too:** a damaged file shows in red, followed by "Settings restored from the backup of <date>" or "Default settings in use" in amber. A missing settings file (also on the very first launch) shows "Settings file not found — default settings in use" in amber, and a file that exists but can't be read (for example, locked by another program) shows in red.
- **To go back to an older snapshot by hand:** close the app, open `json_translation_editor_settings.backups.zip` in File Explorer, copy the dated file you want out of it, rename the copy to `json_translation_editor_settings.json`, and replace the existing file. Close the app first — it rewrites the settings when it exits.

The archive, the `.corrupt-…` copies and the settings file itself all contain API keys in plain text. They are already in `.gitignore`; don't share them. If you rotate or revoke a key, the old value also remains in the older snapshots and in any `.corrupt-…` copies — delete `json_translation_editor_settings.backups.zip` and those copies as part of the rotation.

The archive lives next to the settings file, so it shares that file's fate. If you run the built `.exe` from `dist\`, every `build_exe` run deletes that folder — settings and archive together — so run the exe from a copy outside `dist\`.

---

## File Formats

### The language file (`es.json`)

One flat JSON object. Each key is the English source text and each value is its translation, both text:

```json
{
 "Guide point": "Punto guía",
 "Delete {name}?": "¿Eliminar {name}?"
}
```

- **Refused when invalid.** A file that is not UTF-8 text, is not valid JSON, is not one object (for example an array), has a value that is not text, or repeats a key is not opened. The message names the problem: the line and column of a syntax error, the key with the non-text value, or the duplicated key. Fix the file in a text editor and open it again.
- **Layout is kept.** The indent, line endings (LF or CRLF), byte-order mark, trailing newline and whether accented letters are written as themselves or as `\uXXXX` escapes are detected when the file opens and used when it is saved. An unchanged file is saved byte for byte; an edit changes only that entry's line; a deleted entry removes its line. Line breaks inside a value stay `\n`.
- **Unusual layouts** that cannot be reproduced exactly trigger the one-time "Reformat File" question before the first save.
- Keys are never renamed or re-sorted by an edit. New keys arrive only through [Merge](#merge-from-file), [New Language](#new-language) (a whole new file in the same order) and [Sync Keys](#sync-keys-from-file) (inserted next to their neighbours in the reference file).

### The metadata file (`es.json.meta`)

JSON cannot hold a status, translator or date without changing what your program reads, so they live in a second file with the same name plus `.meta`. The extension is deliberately not `.json`: a program that loads every `*.json` in a folder never finds it. Keep it beside the language file (and commit it with it, if you want the history).

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

| Field | Description |
|-------|-------------|
| `format` | Always `1` |
| `language` | BCP-47 code (e.g. `es-AR`) — the target language for auto-translation and the code Merge compares. When empty or missing, the code is guessed from the file name (`pt-BR.json` → `pt-BR`) |
| `language_name` | Human-readable name shown in the info bar |
| `version` | `major.minor.build` (up to 99.99.99999), shown with a `v` in the info bar and used to group backups; empty means no version |
| `entries` | One object per string that is **not** in its default state — status other than `New`, or a translator, or a date — in the language file's key order. A key that is not listed is `New` with no translator and no date |
| `status` | `New`, `Review` or `Complete` |
| `translator` | Name of the last editor or translation engine |
| `modified` | Last modification date, `YYYY-MM-DD` |

With no `.json.meta`, every string is `New`. A `.json.meta` is written on every successful save, even when it holds only the header. Entries listed for keys that are no longer in the language file are dropped on the next save, with a warning when the file opens.

---

## Troubleshooting

**App won't start — "PySide6 not found"**  
Use the batch/PowerShell launcher, which installs it automatically — or install it yourself, see [Manual Installation](BUILDING.md#manual-installation) (`pip install PySide6`).

**Launcher shows "Unknown publisher" yellow bar in Explorer**  
This is the Windows Zone.Identifier tag applied to downloaded files. Both launchers remove it automatically on the first run — the warning will not appear the next time you open them. If it persists, right-click the file → Properties → check "Unblock" → OK.

**Launcher shows UAC "Unknown publisher" elevation dialog**  
This requires a paid Authenticode code-signing certificate and cannot be resolved without one. The application itself does not request elevation.

**Python is not installed and winget fails**  
See [Manual Installation](BUILDING.md#manual-installation) — install Python from [python.org](https://www.python.org/downloads/) (check "Add Python to PATH") or search "python" in the Windows Start menu to install from the Microsoft Store. The launchers will also display manual install instructions in this case.

**Date picker shows wrong format**  
The date format is read from Windows regional settings at startup. Go to Control Panel → Region → Short date, change the format, and restart the app.

**A date shows as typed in the metadata file instead of in my regional format**  
The `.json.meta` holds dates as `YYYY-MM-DD`. A date in any other form is shown as stored (with an amber "unrecognized date" message when the file opens) and written back unchanged until you edit that entry's date.

**"Open Error" when opening a JSON file**
The message names the problem. *Not valid JSON (line N, column M)* — a missing comma, quote or brace near that position. *The file must hold one JSON object of "source": "translation" pairs* — the top level is an array or a single value. *The value of '…' is not text* — a number, `null`, list or object where a translation should be. *Duplicate key: '…'* — the same source text appears twice; delete one by hand (the app refuses rather than silently keep only one). *The file is not UTF-8 text* — save it as UTF-8 (with or without a byte-order mark).

**Everything shows as New after opening a file**
The `.json.meta` is missing or was damaged. Check for `<name>.json.meta` beside the file, and for a `<name>.json.meta.corrupt-<date-time>` copy: if the app finds a `.json.meta` it cannot read as JSON, it keeps it under that name, shows a red "Metadata: … was damaged" message and starts from all-New. Repair the kept copy by hand and rename it back, or close the app first and restore the file from a backup (**File → Restore from Backup…** restores the sidecar along with the language file).

**"Metadata: … could not be read" and the statuses are not saved**
Another program holds the `.json.meta` open. The app shows all strings as New and **does not overwrite** it, so a Save writes only the language file. Close the other program and reopen the file.

**Saving says "translations saved, metadata not"**
The language file was written but its `.json.meta` could not be (a locked file, a full disk, no permission). The file stays marked as modified; fix the cause and Save again.

**"Reformat File" appears on the first save**
The file's layout (indent, spacing or escapes) is not one the app reproduces exactly, so saving will normalize it. Only whitespace changes, never the translations. Answer Yes once; later saves keep the new layout and ask nothing. Autosave waits until you have done this.

**Autosave says "Autosave paused: save … once with Ctrl+S"**
The open file would be reformatted by saving (see the previous entry). Press **Ctrl+S** and confirm; autosave then resumes.

**Sync Keys shows a renamed key as an addition plus a deletion**
That is the known limitation: nothing pairs the two. Copy the translation from the deletion row's value into the new key by hand, then delete the old one.

**Settings file is corrupt or causing errors**  
A settings file whose content is damaged (not valid JSON) is restored from the newest snapshot automatically at startup (see [Settings backup](#settings-backup)). If the file reads fine but holds a value that causes errors, restore an older snapshot by hand as described there, or delete `json_translation_editor_settings.json` — a fresh file with defaults will be created on next launch.

**Keyboard shortcuts not working in the Edit window**  
Confirm the binding via **View → Keyboard Shortcuts…**. Edit window shortcuts take effect the next time the Edit window is opened. Check that no other application has claimed the same global hotkey.

**Auto-translate button says "No target language"**  
The target language is the open file's language code, from its `.json.meta` or guessed from its file name. Open a translation file first. If the file name is not a language code (e.g. `strings.json`), set the code in **File → Properties…**.

**DeepL returns HTTP 403**  
Common causes: the API key is missing the `:fx` suffix required by free-tier keys, or the key is correct but the old form-field authentication was cached. The application uses the correct `Authorization: DeepL-Auth-Key` header and auto-detects the free tier from the `:fx` suffix. Use **🔗 Test Connection** in Translation Settings to verify.

**Google Translate says "rate-limiting this network (HTTP 429)"**  
The Google engine uses Google's free public web page, which has no API key and no published quota; Google throttles an IP address it sees sending many requests, sometimes for minutes or hours. The app retries once after 3 seconds and then shows this message, and a running Robo-Translate chain stops. Wait a while, raise the Robo-Translate delay (several people behind one office IP share the limit), or switch to another engine in Translation Settings. The underlying library's advice to "try the translate_batch function" does not help: it sends the same requests one after another.

**Translation test shows an error but the key looks correct**  
Hover over the error label in Translation Settings for the full response from the server, including the HTTP status code and body, which usually explains the issue precisely.

**Claude (Subscription) fills in the previous entry's translation, or leaves the field empty**  
Fixed in the current version — if you see it, you are running an older build; update. Earlier builds could fall permanently one translation behind after you navigated away from an entry (or dismissed Translation Settings during a **Test Connection**) while a translation was still running. From that point every translation returned the previous entry's answer, an empty field, or both run together, until the app was restarted. Restarting the app clears it, and is the only workaround on an affected build.

**Autosave fails with "file locked" dialog**  
Another application has the file open exclusively. Click **Save As…** in the dialog to save to a different location, or click **Skip** to retry at the next autosave interval. No changes are lost either way.

**No backups are being created**  
The info bar reports each backup location on its own line ("Backup next to file: …", "Backup in root: …"); a failed location shows in red. If it says "skipped — backed up N min ago", this is deliberate: that location already has a backup newer than the **Skip if backed up within** interval. Lower that setting (or set it to 0, "Always back up") in **View → Autosave & Backup…** if you want a slot on every open. Otherwise, check that backup is enabled in the same dialog. Backups require write permission to the application's own directory. Also confirm the file is being opened via **File → Open…** — backups trigger on file open.

**Backup folder is growing unexpectedly large**  
Reduce **Keep last** in **View → Autosave & Backup…** and enable compression. Compressed backups are typically 70–80% smaller than the originals. Old slots beyond the limit are pruned automatically on the next file open.
