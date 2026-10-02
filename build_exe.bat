@echo off
:: ============================================================================
::  JSON Translation Editor -- Build Executable (Hardened Launcher)
::  Version 2.0
::
::  Fallback chain:
::    1. PowerShell 5.1 (powershell.exe) -- preferred, full pre-flight checks
::    2. PowerShell 7+  (pwsh.exe)       -- modern alternative
::    3. Direct Python + PyInstaller     -- bypasses PowerShell entirely
::    4. winget Python auto-install      -- no Python found, winget available
::    5. Guided install prompt           -- winget unavailable or failed
::
::  Handles:
::    - Zone.Identifier "Unknown publisher" bar -- auto-removed on first run
::    - PowerShell execution policy locked by Group Policy
::    - PowerShell version too old (< 5.1)
::    - Running from a UNC / network-share path
::    - Paths with spaces or special characters
::    - No Python installed -- tries winget, then guides to python.org
::    - Missing PySide6 / PyInstaller -- pip install attempted automatically
::    - Non-interactive environments
:: ============================================================================

setlocal EnableDelayedExpansion
title JSON Translation Editor -- Build

:: -- Resolve script directory -------------------------------------------------
set "LAUNCH_DIR=%~dp0"
set "PS1=%LAUNCH_DIR%build_exe.ps1"
set "APP=%LAUNCH_DIR%json_translation_editor.py"
set "ERRCODE=0"

:: -- Detect UNC path ----------------------------------------------------------
set "IS_UNC=0"
echo %LAUNCH_DIR% | findstr /r "^\\\\" >nul 2>&1 && set "IS_UNC=1"

echo.
echo   +--------------------------------------------------+
echo   ^|    JSON Translation Editor -- Build Launcher    ^|
echo   +--------------------------------------------------+
echo.

:: -- 1. Verify app script exists ----------------------------------------------
if not exist "%APP%" (
    echo   [FAIL] Application file not found:
    echo          %APP%
    echo.
    echo          Make sure build_exe.bat is in the same folder as
    echo          json_translation_editor.py
    goto :fatal
)
echo   [ OK ] Application file found.

:: -- 0. Unblock Zone.Identifier (removes yellow "Unknown publisher" bar) ------
powershell.exe -NoProfile -Command ^
  "foreach ($f in @('%~f0','%PS1%')) { if (Test-Path $f) { Unblock-File -Path $f -ErrorAction SilentlyContinue } }"
echo   [ OK ] Zone.Identifier tag removed.

:: -- 2. Locate Python ---------------------------------------------------------
set "PYTHON="

for %%C in (python python3) do (
    if not defined PYTHON (
        %%C --version >nul 2>&1
        if not errorlevel 1 set "PYTHON=%%C"
    )
)

if not defined PYTHON (
    py --version >nul 2>&1
    if not errorlevel 1 set "PYTHON=py"
)

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
    ) do (
        if not defined PYTHON if exist %%P (
            %%P --version >nul 2>&1
            if not errorlevel 1 set "PYTHON=%%~P"
        )
    )
)

if defined PYTHON (
    "%PYTHON%" --version >nul 2>&1
    if errorlevel 1 set "PYTHON="
)

:: =============================================================================
:: STRATEGY 1 -- PowerShell launcher (full pre-flight + build)
:: =============================================================================
if not exist "%PS1%" (
    echo   [WARN] build_exe.ps1 not found. Skipping PowerShell launcher.
    goto :direct_python
)

if "%IS_UNC%"=="1" (
    echo   [WARN] Launcher is on a network path. Skipping PowerShell launcher.
    goto :direct_python
)

set "PS_EXE="
set "PS_MAJOR=0"
powershell.exe -NoProfile -Command "exit 0" >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%V in ('powershell.exe -NoProfile -Command "$PSVersionTable.PSVersion.Major" 2^>nul') do set "PS_MAJOR=%%V"
    if !PS_MAJOR! GEQ 5 set "PS_EXE=powershell.exe"
)

if not defined PS_EXE (
    pwsh.exe -NoProfile -Command "exit 0" >nul 2>&1
    if not errorlevel 1 set "PS_EXE=pwsh.exe"
)

if not defined PS_EXE (
    echo   [WARN] PowerShell 5.1+ not available. Skipping PS launcher.
    goto :direct_python
)

%PS_EXE% -ExecutionPolicy Bypass -NoProfile -Command "exit 0" >nul 2>&1
if errorlevel 1 (
    echo   [WARN] PowerShell execution policy prevents script execution.
    goto :direct_python
)

echo   [ OK ] PowerShell %PS_MAJOR%+ found. Running full build script...
echo.
%PS_EXE% -ExecutionPolicy Bypass -NoProfile -File "%PS1%"
set "ERRCODE=!errorlevel!"

if "!ERRCODE!"=="0" goto :done
echo.
echo   [WARN] PowerShell build script failed (code !ERRCODE!). Trying direct Python...
echo.

:: =============================================================================
:: STRATEGY 2 -- Direct Python + PyInstaller
:: =============================================================================
:direct_python
if not defined PYTHON goto :no_python

echo   [ OK ] Python: %PYTHON%

for /f "tokens=1,2 delims= " %%A in ('"%PYTHON%" --version 2^>^&1') do set "PY_VER=%%B"
echo   [ OK ] Version %PY_VER%

:: Check PySide6
echo   [ .. ] Checking PySide6...
"%PYTHON%" -c "import PySide6" >nul 2>&1
if not errorlevel 1 goto :pyside_ok

echo   [WARN] PySide6 not found. Installing...
"%PYTHON%" -m pip --version >nul 2>&1
if not errorlevel 1 goto :pip_ok_pyside

echo   [ .. ] pip not found. Bootstrapping...
"%PYTHON%" -m ensurepip --upgrade >nul 2>&1
if not errorlevel 1 goto :pip_ok_pyside
echo   [FAIL] Cannot bootstrap pip.
goto :fatal

:pip_ok_pyside
"%PYTHON%" -m pip install PySide6 --quiet
if not errorlevel 1 goto :pyside_installed
echo   [FAIL] pip install PySide6 failed.
goto :fatal

:pyside_installed
echo   [ OK ] PySide6 installed.
goto :check_deep_translator_b

:pyside_ok
echo   [ OK ] PySide6 available.

:check_deep_translator_b
echo   [ .. ] Checking deep-translator...
"%PYTHON%" -c "import deep_translator" >nul 2>&1
if not errorlevel 1 goto :deep_translator_ok_b

echo   [WARN] deep-translator not found. Installing...
"%PYTHON%" -m pip install deep-translator --quiet
if not errorlevel 1 goto :deep_translator_installed_b
echo   [FAIL] pip install deep-translator failed.
goto :fatal

:deep_translator_installed_b
echo   [ OK ] deep-translator installed.
goto :check_claude_sdk_b

:deep_translator_ok_b
echo   [ OK ] deep-translator available.

:check_claude_sdk_b
echo   [ .. ] Checking claude-agent-sdk...
"%PYTHON%" -c "import claude_agent_sdk" >nul 2>&1
if not errorlevel 1 goto :claude_sdk_ok_b

echo   [WARN] claude-agent-sdk not found. Installing...
"%PYTHON%" -m pip install claude-agent-sdk --quiet
if errorlevel 1 goto :claude_sdk_fail_b
echo   [ OK ] claude-agent-sdk installed.
goto :check_node_b

:claude_sdk_fail_b
echo   [WARN] Could not install claude-agent-sdk -- Claude (Subscription) engine will not work.
echo          Install manually: pip install claude-agent-sdk
goto :check_node_b

:claude_sdk_ok_b
echo   [ OK ] claude-agent-sdk available.

:check_node_b
echo   [ .. ] Checking Node.js (optional -- Claude Subscription engine)...
node --version >nul 2>&1
if not errorlevel 1 goto :node_ok_b

echo   [WARN] Node.js not found. Checking for winget...
winget --version >nul 2>&1
if errorlevel 1 goto :node_skip_b

echo   [ .. ] Installing Node.js via winget...
winget install --id OpenJS.NodeJS.LTS --source winget --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :node_skip_b

for /f "tokens=2,*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYS_PATH=%%B"
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USER_PATH=%%B"
set "PATH=%SYS_PATH%;%USER_PATH%;%PATH%"

node --version >nul 2>&1
if errorlevel 1 goto :node_skip_b
echo   [ OK ] Node.js installed via winget.
goto :check_claude_cli_b

:node_skip_b
echo   [WARN] Node.js unavailable -- Claude (Subscription) engine will not work.
echo          Install manually: winget install OpenJS.NodeJS.LTS
goto :pyinst_check

:node_ok_b
echo   [ OK ] Node.js available.

:check_claude_cli_b
echo   [ .. ] Checking Claude CLI...
claude --version >nul 2>&1
if not errorlevel 1 goto :claude_cli_ok_b

echo   [WARN] Claude CLI not found. Installing via npm...
npm install -g @anthropic-ai/claude-code --silent
if errorlevel 1 goto :claude_cli_fail_b
echo   [ OK ] Claude CLI installed.
goto :pyinst_check

:claude_cli_fail_b
echo   [WARN] Could not install Claude CLI automatically.
echo          Install manually: npm install -g @anthropic-ai/claude-code
goto :pyinst_check

:claude_cli_ok_b
echo   [ OK ] Claude CLI available.

:: Check PyInstaller
:pyinst_check
echo   [ .. ] Checking PyInstaller...
"%PYTHON%" -c "import PyInstaller" >nul 2>&1
if not errorlevel 1 goto :pyinst_ok

echo   [WARN] PyInstaller not found. Installing...
"%PYTHON%" -m pip install pyinstaller --quiet
if not errorlevel 1 goto :pyinst_installed
echo   [FAIL] pip install pyinstaller failed.
goto :fatal

:pyinst_installed
echo   [ OK ] PyInstaller installed.
goto :build

:pyinst_ok
echo   [ OK ] PyInstaller available.

:: Run the build
:build
:: Bundle the icon/logo the same way build_exe.ps1 does, so this fallback
:: path (used only when PowerShell is unavailable) still produces an exe
:: with a working window icon and Welcome-screen logo. Non-fatal if either
:: file is missing -- the build just proceeds without it.
set "ICON_ARGS="
if exist "Resources\xml_translation_editor.ico" set ICON_ARGS=--icon "Resources\xml_translation_editor.ico" --add-data "Resources\xml_translation_editor.ico;Resources"
if exist "Resources\xml_translation_editor.png" set ICON_ARGS=%ICON_ARGS% --add-data "Resources\xml_translation_editor.png;Resources"

:: Splash screen: same non-fatal reasoning as the icon/logo above, plus a
:: Tcl/Tk check -- PyInstaller's --splash is rendered by a small bundled
:: Tcl/Tk runtime, and fails the whole build outright if the BUILD
:: machine's Python has no tkinter (unlike the icon/logo, which degrade
:: gracefully on their own). End users never need Tcl/Tk themselves.
set "SPLASH_ARGS="
"%PYTHON%" -c "import tkinter" >nul 2>&1
if not errorlevel 1 if exist "Resources\xml_translation_editor_splash.png" set SPLASH_ARGS=--splash "Resources\xml_translation_editor_splash.png"

echo.
echo   [ .. ] Running PyInstaller build...
echo.
:: PySide6 is deliberately not passed to --collect-all: that bundles every Qt
:: module in the wheel, WebEngine and 3D and Quick included, even though the
:: app imports only QtWidgets, QtGui and QtCore. PyInstaller's own hooks
:: collect those plus the plugins they need.
"%PYTHON%" -m PyInstaller --onefile --windowed --name JSONTranslationEditor ^
    --noconfirm --collect-all deep_translator --collect-all claude_agent_sdk %ICON_ARGS% %SPLASH_ARGS% json_translation_editor.py
set "ERRCODE=!errorlevel!"

if "!ERRCODE!"=="0" (
    echo.
    echo   [ OK ] Build complete. Output: dist\JSONTranslationEditor.exe
    if exist "Resources\User_Guide.pdf" (
        copy /y "Resources\User_Guide.pdf" "dist\User_Guide.pdf" >nul
        echo   [ OK ] Copied User_Guide.pdf to dist\
    )
) else (
    echo.
    echo   [FAIL] PyInstaller failed with code !ERRCODE!.
    echo          Try: pip install --upgrade --force-reinstall pyinstaller PySide6
)
goto :done

:: =============================================================================
:: NO PYTHON -- guide the user
:: =============================================================================
:no_python
echo.
echo   +---------------------------------------------------------+
echo   ^|  Python is not installed on this computer.             ^|
echo   +---------------------------------------------------------+
echo.

:: Try winget first
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
echo   [ OK ] winget found. Installing !WINGET_PY_ID!...
echo          Please wait...
echo.
winget install --id !WINGET_PY_ID! --source winget --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :winget_failed

echo.
echo   [ OK ] Python installed via winget.
echo          Restarting build launcher...
echo.
cmd /c "%~f0"
exit /b %errorlevel%

:winget_failed
echo.
echo   [WARN] winget install failed. See manual instructions below.
echo.

:no_winget
echo   How to install Python:
echo.
echo     Option A -- winget (Windows 10 1709+ / Windows 11):
echo       winget install Python.Python.3.13   (or .3.12, .3.11 etc.)
echo.
echo     Option B -- Microsoft Store:
echo       Search "python" in Start menu and click Get.
echo.
echo     Option C -- python.org:
echo       https://www.python.org/downloads/
echo       CHECK "Add Python to PATH" on the first screen.
echo.
echo   After installation, close this window and run build_exe.bat again.
echo.

choice /C YN /T 20 /D N /M "Open python.org in your browser now? [Y=yes, N=no, default N in 20s]" >nul 2>&1
if errorlevel 2 goto :fatal
if errorlevel 1 (
    start "" "https://www.python.org/downloads/"
    echo.
    echo   Browser opened. Install Python then re-run this launcher.
)
goto :fatal

:: =============================================================================
:: EXIT POINTS
:: =============================================================================
:fatal
echo.
echo   If problems persist, open a Command Prompt in this folder and run:
echo     python -m PyInstaller --onefile --windowed json_translation_editor.py
echo.
set "ERRCODE=1"

:done
if "!ERRCODE!" NEQ "0" (
    echo.
    echo   Exited with code !ERRCODE!.
    pause
)

endlocal & exit /b %ERRCODE%
