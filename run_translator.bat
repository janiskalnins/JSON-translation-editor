@echo off
:: ============================================================================
::  JSON Translation Editor -- Hardened Launcher
::  Version 2.1 -- Safe to double-click on any Windows 7/8/10/11 machine.
::
::  Fallback chain:
::    1. PowerShell 5.1 (powershell.exe) -- preferred, full dep management
::    2. PowerShell 7+  (pwsh.exe)       -- modern alternative
::    3. Direct Python launch            -- bypasses PowerShell entirely
::    4. winget Python auto-install      -- no Python found, winget available
::    5. Guided install prompt           -- winget unavailable or failed
::
::  Fast path:
::    If launcher_cache.json (written by run_translator.ps1) and
::    bat_launcher_cache.txt (written by this script) both exist, all
::    pre-flight checks are skipped and PS1 is launched directly.
::
::  Handles:
::    - No Python installed -- tries winget first, then guides to python.org
::    - Zone.Identifier "Unknown publisher" bar -- auto-removed on first run
::    - PowerShell execution policy locked by Group Policy
::    - PowerShell version too old (< 5.1)
::    - Running from a UNC / network-share path
::    - Paths containing spaces or special characters
::    - Missing PySide6 (pip install attempted automatically)
::    - Non-interactive / no-console environments
::    - Script files not found next to launcher
:: ============================================================================

setlocal EnableDelayedExpansion
title JSON Translation Editor

:: -- Resolve script directory (trailing backslash included) -------------------
set "LAUNCH_DIR=%~dp0"
set "PS1=%LAUNCH_DIR%run_translator.ps1"
set "APP=%LAUNCH_DIR%json_translation_editor.py"
set "CACHE_JSON=%LAUNCH_DIR%launcher_cache.json"
set "CACHE_DATA=%LAUNCH_DIR%bat_launcher_cache.txt"
set "ASCII_ART=%LAUNCH_DIR%Resources\json_translation_editor_ascii.txt"
set "ERRCODE=0"

:: -- Resize console for the ASCII banner (skip under Windows Terminal, which --
:: -- manages its own pane geometry) -------------------------------------------
if defined WT_SESSION goto :skip_resize
mode con: cols=72 lines=46 >nul 2>&1
:skip_resize

:: -- Detect UNC path (\\server\share\...) ------------------------------------
:: PowerShell -File cannot run from UNC paths reliably; skip to python fallback.
set "IS_UNC=0"
echo %LAUNCH_DIR% | findstr /r "^\\\\" >nul 2>&1 && set "IS_UNC=1"

echo.
if not exist "%ASCII_ART%" goto :skip_banner
type "%ASCII_ART%"
echo.
:skip_banner
echo   +--------------------------------------------------+
echo   ^|       JSON Translation Editor Launcher          ^|
echo   +--------------------------------------------------+
echo.
echo   !! Do not close this window while the app is running !!
echo      Closing it will also close the Translation Editor.
echo.

:: -- 1. Verify the .py app file exists ----------------------------------------
if not exist "%APP%" (
    echo   [FAIL] Application file not found:
    echo          %APP%
    echo.
    echo          Make sure run_translator.bat is in the same folder as
    echo          json_translation_editor.py
    goto :fatal
)
echo   [ OK ] Application file found.

:: =============================================================================
:: FAST PATH -- skip all pre-flight when cache files are present
:: =============================================================================
:: Requires: launcher_cache.json (PS1 cache) + bat_launcher_cache.txt (BAT cache)
:: Skips: Zone.Identifier unblock, Python detection, PS version/policy checks.

if not exist "%CACHE_JSON%" goto :full_check
if not exist "%CACHE_DATA%" goto :full_check
if "%IS_UNC%"=="1"          goto :full_check
if not exist "%PS1%"        goto :full_check

:: Load cached PowerShell executable path (plain data file, not executed).
:: The variable is NEVER set to the file's raw content -- only ever to one
:: of these two hardcoded literals, gated by a findstr membership test
:: against the file. This makes it structurally impossible for a crafted
:: value (e.g. containing unbalanced quotes or shell metacharacters) to
:: ever reach a quoted comparison or invocation, even indirectly.
set "BAT_CACHE_PS_EXE="
findstr /x /i /c:"powershell.exe" "%CACHE_DATA%" >nul 2>&1 && set "BAT_CACHE_PS_EXE=powershell.exe"
if not defined BAT_CACHE_PS_EXE (
    findstr /x /i /c:"pwsh.exe" "%CACHE_DATA%" >nul 2>&1 && set "BAT_CACHE_PS_EXE=pwsh.exe"
)
if not defined BAT_CACHE_PS_EXE goto :cache_invalid

:: Quick sanity-check: make sure the cached exe still responds
"%BAT_CACHE_PS_EXE%" -NoProfile -Command "exit 0" >nul 2>&1
if errorlevel 1 goto :cache_invalid

echo   [ OK ] Fast start (pre-flight cached).
echo.
echo   +-------------------------------------------------+
echo   ^|  App is running.  Do NOT close this window.   ^|
echo   ^|  Closing it will also close the editor.       ^|
echo   +-------------------------------------------------+
echo.
"%BAT_CACHE_PS_EXE%" -ExecutionPolicy Bypass -NoProfile -File "%PS1%" %*
set "ERRCODE=!errorlevel!"
if "!ERRCODE!"=="0" goto :done

:: Fast path failed -- wipe both caches and fall through to full check
:cache_invalid
if exist "%CACHE_JSON%" del /f /q "%CACHE_JSON%" 2>nul
if exist "%CACHE_DATA%" del /f /q "%CACHE_DATA%" 2>nul
set "ERRCODE=0"
echo   [WARN] Cached environment invalid -- running full check...
echo.

:: =============================================================================
:: FULL CHECK
:: =============================================================================
:full_check

:: -- 0. Unblock files (remove Zone.Identifier downloaded-from-internet tag) ---
:: Windows tags every file downloaded from the internet with a Zone.Identifier
:: alternate data stream.  Explorer shows a yellow "Unknown publisher" warning
:: for tagged .bat and .ps1 files.  We strip the tag silently on first run so
:: the warning disappears the next time the launcher is opened.
:: Note: this only removes the Explorer SmartScreen bar -- it does NOT affect
:: the UAC "Unknown publisher" elevation prompt, which requires a paid
:: Authenticode certificate.
powershell.exe -NoProfile -Command ^
  "foreach ($f in @('%~f0','%PS1%')) { if (Test-Path $f) { Unblock-File -Path $f -ErrorAction SilentlyContinue } }"
echo   [ OK ] Zone.Identifier tag removed (no more yellow bar on next open).


:: -- 2. Locate Python (handles fresh installs where PATH is not set) -----------
set "PYTHON="

:: Try standard PATH commands first
for %%C in (python python3) do (
    if not defined PYTHON (
        %%C --version >nul 2>&1
        if not errorlevel 1 set "PYTHON=%%C"
    )
)

:: Try Windows py launcher (handles multiple Python versions)
if not defined PYTHON (
    py --version >nul 2>&1
    if not errorlevel 1 set "PYTHON=py"
)

:: Try well-known installation paths when PATH is not configured
if not defined PYTHON (
    for %%P in (
        "%LocalAppData%\Programs\Python\Python313\python.exe"
        "%LocalAppData%\Programs\Python\Python312\python.exe"
        "%LocalAppData%\Programs\Python\Python311\python.exe"
        "%LocalAppData%\Programs\Python\Python310\python.exe"
        "%LocalAppData%\Programs\Python\Python39\python.exe"
        "%ProgramFiles%\Python313\python.exe"
        "%ProgramFiles%\Python312\python.exe"
        "%ProgramFiles%\Python311\python.exe"
        "%ProgramFiles%\Python310\python.exe"
        "%ProgramFiles%\Python39\python.exe"
        "%ProgramFiles(x86)%\Python313\python.exe"
        "%ProgramFiles(x86)%\Python312\python.exe"
    ) do (
        if not defined PYTHON if exist %%P (
            %%P --version >nul 2>&1
            if not errorlevel 1 set "PYTHON=%%~P"
        )
    )
)

:: Sanity-check: make sure the Python we found actually executes
if defined PYTHON (
    "%PYTHON%" --version >nul 2>&1
    if errorlevel 1 set "PYTHON="
)

:: -----------------------------------------------------------------------------
:: STRATEGY 1 -- PowerShell launcher (full dependency checking + pip management)
:: -----------------------------------------------------------------------------
if not exist "%PS1%" (
    echo   [WARN] run_translator.ps1 not found. Skipping PowerShell launcher.
    goto :direct_python
)

if "%IS_UNC%"=="1" (
    echo   [WARN] Launcher is on a network path. Skipping PowerShell launcher.
    goto :direct_python
)

:: Detect PowerShell 5.1 (powershell.exe)
set "PS_EXE="
set "PS_MAJOR=0"
powershell.exe -NoProfile -Command "exit 0" >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%V in ('powershell.exe -NoProfile -Command "$PSVersionTable.PSVersion.Major" 2^>nul') do set "PS_MAJOR=%%V"
    if !PS_MAJOR! GEQ 5 set "PS_EXE=powershell.exe"
)

:: Fall back to PowerShell 7+ (pwsh.exe) if 5.1 not usable
if not defined PS_EXE (
    pwsh.exe -NoProfile -Command "exit 0" >nul 2>&1
    if not errorlevel 1 set "PS_EXE=pwsh.exe"
)

if not defined PS_EXE (
    echo   [WARN] PowerShell 5.1+ not available. Skipping PS launcher.
    goto :direct_python
)

:: Verify execution policy allows -File (Group Policy can block even Bypass)
%PS_EXE% -ExecutionPolicy Bypass -NoProfile -Command "exit 0" >nul 2>&1
if errorlevel 1 (
    echo   [WARN] PowerShell execution policy prevents script execution.
    echo          This is common on corporate/managed machines.
    goto :direct_python
)

echo   [ OK ] PowerShell %PS_MAJOR%+ found. Running full launcher...
echo.
%PS_EXE% -ExecutionPolicy Bypass -NoProfile -File "%PS1%" %*
set "ERRCODE=!errorlevel!"

:: On success, write BAT cache so next launch uses the fast path
if "!ERRCODE!"=="0" echo %PS_EXE%>"%CACHE_DATA%"
if "!ERRCODE!"=="0" goto :done

echo.
echo   [WARN] PowerShell launcher failed (code !ERRCODE!). Trying direct Python...
echo.

:: -----------------------------------------------------------------------------
:: STRATEGY 2 -- Direct Python launch (no PowerShell dependency)
:: -----------------------------------------------------------------------------
:direct_python
if not defined PYTHON goto :no_python

echo   [ OK ] Python: %PYTHON%

:: Check Python version >= 3.9
set "PY_MINOR=0"
for /f "tokens=2 delims=." %%M in ('"%PYTHON%" --version 2^>^&1') do set "PY_MINOR=%%M"
:: Rough check: version string "3.X.Y" -- extract minor
for /f "tokens=1,2 delims= " %%A in ('"%PYTHON%" --version 2^>^&1') do set "PY_VER=%%B"
echo   [ OK ] Version %PY_VER%

:: Check for PySide6; install if missing
:: IMPORTANT: All pip calls are at top-level (not inside if-blocks) so that
:: pip output lines containing ) do not confuse the batch parser.
echo   [ .. ] Checking PySide6...
"%PYTHON%" -c "import PySide6" >nul 2>&1
if not errorlevel 1 goto :pyside_ok

echo   [WARN] PySide6 not found. Installing (this may take a minute)...

:: Ensure pip is available
"%PYTHON%" -m pip --version >nul 2>&1
if not errorlevel 1 goto :pip_ok

echo   [ .. ] pip not found. Bootstrapping with ensurepip...
"%PYTHON%" -m ensurepip --upgrade >nul 2>&1
if not errorlevel 1 goto :pip_ok
echo   [FAIL] Cannot bootstrap pip.
echo          Try manually: pip install PySide6
goto :fatal

:pip_ok
"%PYTHON%" -m pip install PySide6 --quiet
if not errorlevel 1 goto :pyside_installed
echo   [FAIL] pip install PySide6 failed.
echo.
echo          Possible causes:
echo            No internet connection
echo            Firewall or proxy blocking PyPI
echo            Insufficient disk space
echo.
echo          Try manually in a Command Prompt:
echo            pip install PySide6
goto :fatal

:pyside_installed
echo   [ OK ] PySide6 installed successfully.
goto :check_deep_translator

:pyside_ok
echo   [ OK ] PySide6 is available.

:check_deep_translator
echo   [ .. ] Checking deep-translator...
"%PYTHON%" -c "import deep_translator" >nul 2>&1
if not errorlevel 1 goto :deep_translator_ok

echo   [WARN] deep-translator not found. Installing (this may take a minute)...
"%PYTHON%" -m pip install deep-translator --quiet
if not errorlevel 1 goto :deep_translator_installed
echo   [FAIL] pip install deep-translator failed.
echo.
echo          Try manually in a Command Prompt:
echo            pip install deep-translator
goto :fatal

:deep_translator_installed
echo   [ OK ] deep-translator installed successfully.
goto :check_claude_sdk

:deep_translator_ok
echo   [ OK ] deep-translator is available.

:check_claude_sdk
echo   [ .. ] Checking claude-agent-sdk...
"%PYTHON%" -c "import claude_agent_sdk" >nul 2>&1
if not errorlevel 1 goto :claude_sdk_ok

echo   [WARN] claude-agent-sdk not found. Installing...
"%PYTHON%" -m pip install claude-agent-sdk --quiet
if errorlevel 1 goto :claude_sdk_fail
echo   [ OK ] claude-agent-sdk installed successfully.
goto :check_node

:claude_sdk_fail
echo   [WARN] Could not install claude-agent-sdk -- Claude (Subscription) engine will not work.
echo          Install manually: pip install claude-agent-sdk
goto :check_node

:claude_sdk_ok
echo   [ OK ] claude-agent-sdk is available.

:check_node
echo   [ .. ] Checking Node.js (optional -- needed for Claude Subscription engine)...
node --version >nul 2>&1
if not errorlevel 1 goto :node_ok

echo   [WARN] Node.js not found. Checking for winget...
winget --version >nul 2>&1
if errorlevel 1 goto :node_skip

echo   [ .. ] Installing Node.js via winget...
winget install --id OpenJS.NodeJS.LTS --source winget --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :node_skip

for /f "tokens=2,*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYS_PATH=%%B"
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USER_PATH=%%B"
set "PATH=%SYS_PATH%;%USER_PATH%;%PATH%"

node --version >nul 2>&1
if errorlevel 1 goto :node_skip
echo   [ OK ] Node.js installed via winget.
goto :check_claude_cli

:node_skip
echo   [WARN] Node.js unavailable -- Claude (Subscription) engine will not work.
echo          Install manually: winget install OpenJS.NodeJS.LTS
goto :launch

:node_ok
echo   [ OK ] Node.js is available.

:check_claude_cli
echo   [ .. ] Checking Claude CLI...
claude --version >nul 2>&1
if not errorlevel 1 goto :claude_cli_ok

echo   [WARN] Claude CLI not found. Installing via npm...
npm install -g @anthropic-ai/claude-code --silent
if errorlevel 1 goto :claude_cli_fail
echo   [ OK ] Claude CLI installed successfully.
goto :launch

:claude_cli_fail
echo   [WARN] Could not install Claude CLI automatically.
echo          Install manually: npm install -g @anthropic-ai/claude-code
goto :launch

:claude_cli_ok
echo   [ OK ] Claude CLI is available.

:launch
echo   [ OK ] Starting JSON Translation Editor...
echo.
echo   +-------------------------------------------------+
echo   ^|  App is running.  Do NOT close this window.   ^|
echo   ^|  Closing it will also close the editor.       ^|
echo   +-------------------------------------------------+
echo.
"%PYTHON%" "%APP%" %*
set "ERRCODE=!errorlevel!"
goto :done

:: -----------------------------------------------------------------------------
:: NO PYTHON -- guide the user through installation
:: -----------------------------------------------------------------------------
:no_python
echo.
echo   +---------------------------------------------------------+
echo   ^|  Python is not installed on this computer.             ^|
echo   +---------------------------------------------------------+
echo.

:: -- Try winget (built into Windows 10 1709+ and all of Windows 11) -----------
:: winget installs Python from the Microsoft Store silently, sets PATH
:: automatically, and requires no browser or manual steps.
echo   [ .. ] Checking for winget (automatic install)...
winget --version >nul 2>&1
if errorlevel 1 goto :no_winget

:: Find the newest Python winget knows about -- not tied to one version.
set "WINGET_PY_ID="
for %%V in (3.14 3.13 3.12 3.11 3.10 3.9) do (
    if not defined WINGET_PY_ID (
        winget show --id Python.Python.%%V --source winget >nul 2>&1
        if not errorlevel 1 set "WINGET_PY_ID=Python.Python.%%V"
    )
)
if not defined WINGET_PY_ID set "WINGET_PY_ID=Python.Python.3.12"
echo   [ OK ] winget found. Installing !WINGET_PY_ID! from Microsoft Store...
echo          This may take a minute -- please wait.
echo.
winget install --id !WINGET_PY_ID! --source winget --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :winget_failed

echo.
echo   [ OK ] Python installed successfully via winget.
echo.
echo   Restarting launcher to pick up new Python installation...
echo.
:: Re-launch this same bat file now that Python is on PATH.
:: Use cmd /c so the current process exits cleanly.
cmd /c "%~f0" %*
exit /b %errorlevel%

:winget_failed
echo.
echo   [WARN] winget install failed (code %errorlevel%).
echo          Falling back to manual install instructions.
echo.

:no_winget
:: -- Manual install instructions (fallback) -----------------------------------
echo   How to install Python manually:
echo.
echo     Option A -- winget (Windows 10 1709+ / Windows 11):
echo       Open a Command Prompt and run:
echo         winget install Python.Python.3.13   (or .3.12, .3.11 etc.)
echo.
echo     Option B -- Microsoft Store (Windows 10 / 11):
echo       1. Open Start menu and search for "python"
echo       2. Click "Get" in the Microsoft Store listing
echo          (PATH is set automatically -- no extra steps)
echo.
echo     Option C -- python.org installer:
echo       1. Open: https://www.python.org/downloads/
echo       2. Download and run the installer
echo       3. CHECK "Add Python to PATH" on the first screen
echo.
echo   After installation, close this window and run the launcher again.
echo.

:: Try to open the download page -- choice.exe may not exist on stripped installs
choice /C YN /T 20 /D N /M "Open python.org in your browser now? [Y=yes, N=no, default N in 20s]" >nul 2>&1
if errorlevel 2 goto :fatal
if errorlevel 1 (
    start "" "https://www.python.org/downloads/"
    echo.
    echo   Browser opened. Install Python then re-run this launcher.
)
goto :fatal

:: -----------------------------------------------------------------------------
:: EXIT POINTS
:: -----------------------------------------------------------------------------
:fatal
echo.
echo   If problems persist, open a Command Prompt in this folder and run:
echo     python json_translation_editor.py
echo.
set "ERRCODE=1"

:done
if "!ERRCODE!" NEQ "0" (
    echo.
    echo   Exited with code !ERRCODE!.
    pause
)

endlocal & exit /b %ERRCODE%
