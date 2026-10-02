---
paths:
  - "json_translation_editor.py"
  - "*.ps1"
  - "*.bat"
---

# Security

- Never pass user-controlled strings to `subprocess`, `os.system`, or shell expansion. Use parameterized args.
- Language file paths from user input must be validated before open/write operations.
- API keys (translation engines) are stored in settings JSON only — never in source, never logged.
- Launcher scripts (`.ps1`, `.bat`): wrap every native command in `try/catch`; check `$LASTEXITCODE`. No `eval` on user input.
- Never expose internal file paths or exception details in user-visible error dialogs.
- Auto-translation HTTP requests use `urllib.request` with no proxy bypass. Exception: the `deep-translator` library (Google Translate / MyMemory / Microsoft Translator engines) depends on `requests` internally — call it only through `deep_translator`'s documented translator classes (`GoogleTranslator`, `MyMemoryTranslator`, `MicrosoftTranslator`); never import or call `requests` directly elsewhere in the codebase. `httpx` remains disallowed.
