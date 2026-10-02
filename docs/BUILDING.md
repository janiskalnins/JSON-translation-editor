# XML Translation Editor — Installing, Running and Building

Requirements, manual installation, the launchers, the project's files, building the standalone `.exe` and the developer checks. For what the app does, see the [README](../README.md) and [FEATURES.md](FEATURES.md).

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
  - [Manual Installation](#manual-installation)
- [Running the Application](#running-the-application)
  - [Option A — Batch file launcher (recommended for most users)](#option-a--batch-file-launcher-recommended-for-most-users)
  - [Option B — PowerShell launcher](#option-b--powershell-launcher)
  - [Option C — Direct Python](#option-c--direct-python)
- [Project Files](#project-files)
- [Building a Standalone Executable](#building-a-standalone-executable)
- [Running the Checks](#running-the-checks)

---

## Requirements

| Component | Minimum version |
|-----------|----------------|
| Python    | 3.9 or newer   |
| PySide6   | 6.4 or newer   |
| OS        | Windows 10/11  |

> The application uses Windows-specific APIs for reading the system date format from regional settings. It will run on other platforms but will fall back to `dd.MM.yyyy` date formatting.

The Claude, DeepL, and LibreTranslate engines use only the Python standard library (`urllib`) for HTTP requests — no additional packages required for those three. The Google Translate, MyMemory, and Microsoft Translator engines use the [`deep-translator`](https://pypi.org/project/deep-translator/) package. The Claude (Subscription) engine additionally needs Node.js, the Claude CLI (`@anthropic-ai/claude-code`), and the `claude-agent-sdk` Python package.

---

## Installation

**You normally don't need to install anything yourself:**

- **Running from source** — just double-click `run_translator.bat` or run `run_translator.ps1` (see [Running the Application](#running-the-application)). The launcher detects Python, PySide6, and every other dependency the app needs and installs whatever is missing automatically via `winget`/`pip`/`npm`.
- **Standalone executable** — if you were given `XMLTranslationEditor.exe` (see [Building a Standalone Executable](#building-a-standalone-executable)), there is nothing to install at all. Python and every dependency are bundled inside the `.exe` — just run it.

The [Manual Installation](#manual-installation) steps below are only needed as a fallback, for example if the machine has no internet access, `winget`/`npm` are blocked by policy, or the automatic install otherwise fails.

### Manual Installation

| Component | Needed for | Install command | Link |
|-----------|-----------|------------------|------|
| Python 3.9+ | Running the app from source | `winget install --id Python.Python.3.13 --source winget` | [python.org/downloads](https://www.python.org/downloads/) |
| PySide6 6.4+ | Always — the GUI framework | `pip install PySide6` | [pypi.org/project/PySide6](https://pypi.org/project/PySide6/) |
| deep-translator | Google Translate / MyMemory / Microsoft Translator engines only | `pip install deep-translator` | [pypi.org/project/deep-translator](https://pypi.org/project/deep-translator/) |
| Node.js (LTS) | Claude (Subscription) engine only | `winget install --id OpenJS.NodeJS.LTS --source winget` | [nodejs.org](https://nodejs.org/) |
| Claude CLI | Claude (Subscription) engine only | `npm install -g @anthropic-ai/claude-code` | [npmjs.com/package/@anthropic-ai/claude-code](https://www.npmjs.com/package/@anthropic-ai/claude-code) |
| claude-agent-sdk | Claude (Subscription) engine only | `pip install claude-agent-sdk` | [pypi.org/project/claude-agent-sdk](https://pypi.org/project/claude-agent-sdk/) |

When installing Python manually, check **"Add Python to PATH"** in the installer, then verify with:

```powershell
python --version
```

The two Python packages every install needs (PySide6 plus the optional `deep-translator`) can also be installed together from the repo's `requirements.txt`:

```powershell
pip install -r requirements.txt
```

If `winget` isn't available, Python and Node.js can also be installed from the Microsoft Store (search "python" / search a Node.js LTS package in the Start menu), or via their installers linked above.

---

## Running the Application

### Option A — Batch file launcher (recommended for most users)

Double-click `run_translator.bat`. The launcher:

- Removes the Windows "Unknown publisher" warning bar (Zone.Identifier) on first run
- Tries PowerShell 5.1, then PowerShell 7+, then direct Python as fallback
- If Python is not installed, attempts to install it automatically via `winget`
- Installs PySide6 automatically if missing
- Falls back gracefully at every step with clear error messages

### Option B — PowerShell launcher

```powershell
powershell -ExecutionPolicy Bypass -File run_translator.ps1
```

Pass an XML file path to open it on startup:

```powershell
powershell -ExecutionPolicy Bypass -File run_translator.ps1 "C:\Translations\Latvian.xml"
```

The PowerShell launcher performs the same pre-flight checks as the batch launcher and includes the same winget Python auto-install fallback.

The launcher window is automatically resized and centred on the primary screen. When run inside **Windows Terminal** the resize/centering step is skipped — Windows Terminal manages its own pane geometry. A warning banner reminds you not to close the launcher window while the application is running.

### Option C — Direct Python

```
python xml_translation_editor.py
python xml_translation_editor.py "C:\Translations\Latvian.xml"
```

---

## Project Files

| File | Purpose |
|------|---------|
| `xml_translation_editor.py` | Main application source |
| `run_translator.ps1` | PowerShell launcher — checks Python, installs PySide6, starts app |
| `run_translator.bat` | Hardened batch launcher with multi-strategy fallback chain |
| `build_exe.ps1` | Builds a standalone `.exe` using PyInstaller (full pre-flight checks) |
| `build_exe.bat` | Hardened batch wrapper for `build_exe.ps1`, with direct-Python fallback |
| `translation_editor_settings.json` | Auto-generated settings file (created on first run) |
| `translation_editor_settings.backups.zip` | Auto-created daily snapshots of the settings file, so API keys survive damage (see [Settings backup](FEATURES.md#settings-backup)) |
| `Latvian.xml` | Example translation file |
| `tests/` | Developer checks: `run_all.py`, the offscreen check scripts, sample data and the pre-commit hook (see [Running the Checks](#running-the-checks)) |
| `XML_Translation_file_Backups/` | Auto-created backup folder (see [Backup](FEATURES.md#backup)) |

---

## Building a Standalone Executable

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1
```

Or use the batch file wrapper:

```
build_exe.bat
```

`build_exe.bat` uses the same hardened fallback chain as `run_translator.bat`: it tries PowerShell 5.1, then PowerShell 7+, then invokes PyInstaller directly via Python if PowerShell is unavailable. If Python is not installed, it attempts a `winget` auto-install first.

The build script performs a full pre-flight check before building:

1. Confirms Windows 64-bit OS and 64-bit Python interpreter.
2. Verifies Python ≥ 3.9.
3. Upgrades `pip` if needed — uses `importlib.metadata` for reliable package detection.
4. Checks and installs `setuptools`, `wheel`, `PySide6`, `pyinstaller-hooks-contrib`, `PyInstaller`, and Windows runtime dependencies (`altgraph`, `pefile`, `pywin32-ctypes`).
5. Runs PyInstaller `--onefile --windowed` to produce a single portable `.exe` in the `dist\` subfolder, bundling the application icon and the Welcome-screen logo (`Resources\xml_translation_editor.ico` / `.png`) into the exe itself, plus a startup splash screen (`Resources\xml_translation_editor_splash.png`) if the build machine has Tcl/Tk available.
6. Verifies the output file exists, copies `Resources\User_Guide.pdf` next to it in `dist\` (best-effort — a missing guide only logs a warning), and offers to launch it for a smoke test.

The script handles non-interactive environments (scheduled tasks, CI) without throwing errors.

Everything needed to hand the app to someone else ends up in `dist\`: `XMLTranslationEditor.exe` and `User_Guide.pdf`.

Because the `.exe` bundles PySide6 and every translation engine into a single ~170 MB
file, most of the startup delay is the file unpacking itself into a temp folder before
Python even starts — a startup splash screen (logo + "Starting…") appears immediately
to cover that wait, closing on its own once the main window is ready.

**Build fails with PyInstaller**  
Update both packages: `pip install --upgrade PySide6 pyinstaller`. The build script checks and installs all required dependencies before starting.

---

## Running the Checks

For contributors: the `tests/` folder holds offscreen checks of the UI and the core logic. Run
them all with `python tests/run_all.py`; [tests/README.md](../tests/README.md) lists every check
and explains the reports and the pre-commit hook.
