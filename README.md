# JSON Translation Editor

A Windows desktop app for editing flat JSON language files, the kind where each key is the English
source text and its value is the translation (`"Guide point": "Punto guía"`). It shows every
string in a filterable table, tracks what is New, in Review or Complete, fills in translations
with machine translation or Claude, checks that `{placeholders}` survive, and backs up every file
it opens. It writes the JSON back in the layout it found it in, so an unchanged file is saved
byte for byte and an edit changes only that entry's line.

Status, translator and date cannot live in the JSON without changing what your program reads, so
they go in a small file beside it: `es.json` gets `es.json.meta`. The extension is `.meta` on
purpose, so a program that loads every `*.json` in a folder never sees it. Open a file with no
`.meta` and every string starts as New. → [File formats](docs/FEATURES.md#file-formats)

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/hero_dark.png">
    <img src="docs/images/hero_light.png" width="100%"
         alt="The main window's table of source texts and translations, with the Edit Translation window open over it">
  </picture>
</p>

## What it does

- **Find any string fast.** Search source or translated text, and filter by status, translator,
  date range and placeholder mismatches. → [Filtering](docs/FEATURES.md#filtering)
- **Edit one entry at a time.** The Edit window steps through entries from the keyboard, warns
  when a translation runs much longer than its source, and flags a missing or extra
  `{placeholder}`. → [Editing Translations](docs/FEATURES.md#editing-translations)
- **Translate automatically.** Seven engines (Claude, Claude with a Pro/Max subscription, DeepL,
  LibreTranslate, Google, MyMemory, Microsoft), a per-file glossary for Claude, and
  Robo-Translate to work through the untranslated entries hands-free. →
  [Auto-Translation](docs/FEATURES.md#auto-translation)
- **Start a new language.** Copy the open file's keys into a new `<code>.json`, every string
  untranslated. → [New Language](docs/FEATURES.md#new-language)
- **Keep files in step.** Merge another translator's file, or sync a file's keys with a reference
  file of any language, and review every change side by side before anything is written. →
  [Merge from File](docs/FEATURES.md#merge-from-file), [Sync Keys](docs/FEATURES.md#sync-keys-from-file)
- **Never lose work.** Autosave, a versioned backup every time a file opens, and a browser to
  restore any of them. → [Autosave](docs/FEATURES.md#autosave), [Backup](docs/FEATURES.md#backup)
- **Keep the file's details right.** Edit the language code, language name and version, and see
  how many strings are New, in Review or Complete. → [File Properties](docs/FEATURES.md#file-properties)
- **Make it yours.** Dark and light themes, any UI font and size, and keyboard shortcuts you can
  rebind. → [Themes](docs/FEATURES.md#themes), [Keyboard Shortcuts](docs/FEATURES.md#keyboard-shortcuts)

## Screenshots

<table>
  <tr>
    <td width="33%" align="center" valign="top">
      <a href="docs/FEATURES.md#merge-from-file"><picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/images/merge_dark.png">
        <img src="docs/images/merge_light.png" width="100%" alt="Resolve Merge Conflicts window listing additions, conflicts and deletions">
      </picture></a><br>
      <b>Merge from File</b>
    </td>
    <td width="33%" align="center" valign="top">
      <a href="docs/FEATURES.md#setting-up-translation"><picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/images/translation_settings_dark.png">
        <img src="docs/images/translation_settings_light.png" width="100%" alt="Translation Settings window with the engine choice and its settings">
      </picture></a><br>
      <b>Translation Settings</b>
    </td>
    <td width="33%" align="center" valign="top">
      <a href="docs/FEATURES.md#restoring-a-backup"><picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/images/restore_dark.png">
        <img src="docs/images/restore_light.png" width="100%" alt="Restore from Backup window with backups grouped by file and version">
      </picture></a><br>
      <b>Restore from Backup</b>
    </td>
  </tr>
</table>

## Get started

Runs on Windows 10 and 11.

1. Download **Source code (zip)** from the
   [latest release](https://github.com/janiskalnins/JSON-translation-editor/releases/latest) and
   unzip it.
2. Double-click `run_translator.bat`. The first time, it installs whatever is missing — Python and
   PySide6, plus Node.js and the Claude CLI for the Claude subscription engine (through `winget`,
   `pip` and `npm`) — then starts the app.
3. Open a language file with **File → Open…**, or drop it onto the window.

Were you given `JSONTranslationEditor.exe`? Just run it — everything is inside it, there is
nothing to install.

If the automatic install can't run (no internet, `winget` blocked by policy), see
[Manual Installation](docs/BUILDING.md#manual-installation).

## Documentation

- [Features and reference](docs/FEATURES.md) — every feature, the settings file and the JSON and
  `.json.meta` file formats.
- [User Guide (PDF)](Resources/User_Guide.pdf) — an illustrated guide to every window.
- [Troubleshooting](docs/FEATURES.md#troubleshooting) — common problems and their fixes.

## Your data

- **Settings**, including translation API keys, are kept in `json_translation_editor_settings.json`
  next to the app, with a daily snapshot in `json_translation_editor_settings.backups.zip`. →
  [Settings](docs/FEATURES.md#settings), [Settings backup](docs/FEATURES.md#settings-backup)
- **Backups** of every file you open go to a `JSON_Translation_file_Backups` folder next to the
  file, next to the app, or both. A backup holds the language file, its `.json.meta` and its
  glossary. → [Backup](docs/FEATURES.md#backup)

## For developers

- [BUILDING.md](docs/BUILDING.md) — requirements, running from source, the launchers and
  building the standalone `.exe`.
- [tests/README.md](tests/README.md) — the offscreen checks and the pre-commit hook.
- [CLAUDE.md](CLAUDE.md) — how the code is organised.
