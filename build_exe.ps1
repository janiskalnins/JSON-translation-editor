#Requires -Version 5.1
<#
.SYNOPSIS
    Build a standalone Windows executable for XML Translation Editor.
.DESCRIPTION
    Performs a full pre-flight check of every dependency needed to produce
    a portable single-file .exe via PyInstaller, then runs the build.

    Checks performed:
      - Running on Windows (64-bit OS, 64-bit Python interpreter)
      - Python >= 3.9
      - pip >= 21.3  (older pip mishandles PySide6 wheel metadata)
      - setuptools, wheel  (needed for any source builds during install)
      - PySide6 >= 6.4  (minimum for stable PyInstaller hooks)
      - PySide6 Qt sub-modules used by the app (QtWidgets, QtGui, QtCore)
      - deep-translator  (Google Translate / MyMemory / Microsoft Translator engines)
      - pyinstaller-hooks-contrib >= 2023.2  (provides the PySide6 hook set)
      - PyInstaller >= 5.8  (first release with reliable PySide6 6.x hooks)
      - PyInstaller Windows runtime deps: altgraph, pefile, pywin32-ctypes
      - Available disk space >= 1.5 GB
      - app script present
      - icon file present (optional -- build proceeds without a custom icon if missing)
      - splash screen image present (optional -- build proceeds without a splash if missing)
      - Tcl/Tk available (required by PyInstaller's --splash; build proceeds without a
        splash if missing)

    Run with:  powershell -ExecutionPolicy Bypass -File build_exe.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
$HOST.UI.RawUI.WindowTitle = "XML Translation Editor -- Build"

# ==============================================================================
#  CONSOLE HELPERS
# ==============================================================================
function Write-Header {
    Clear-Host
    Write-Host ""
    Write-Host "  +==================================================+" -ForegroundColor Magenta
    Write-Host "  |   XML Translation Editor -- Executable Builder   |" -ForegroundColor Magenta
    Write-Host "  +==================================================+" -ForegroundColor Magenta
    Write-Host ""
}
function Write-Step  { param($m) Write-Host "  [ .. ] $m" -ForegroundColor DarkCyan }
function Write-Ok    { param($m) Write-Host "  [ OK ] $m" -ForegroundColor Green    }
function Write-Warn  { param($m) Write-Host "  [WARN] $m" -ForegroundColor Yellow   }
function Write-Fail  { param($m) Write-Host "  [FAIL] $m" -ForegroundColor Red      }
function Write-Info  { param($m) Write-Host "         $m" -ForegroundColor Gray     }
function Write-Sep   {           Write-Host "  --------------------------------------------------" -ForegroundColor DarkGray }

# ==============================================================================
#  BUILD CONSTANTS
# ==============================================================================
$APP_SCRIPT  = "xml_translation_editor.py"
$APP_NAME    = "XMLTranslationEditor"
$ICON_FILE   = "Resources\xml_translation_editor.ico"
$LOGO_FILE   = "Resources\xml_translation_editor.png"
$SPLASH_FILE = "Resources\xml_translation_editor_splash.png"
$USER_GUIDE_FILE = "Resources\User_Guide.pdf"
$DIST_DIR    = "dist"
$BUILD_DIR   = "build"

$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Definition
$AppPath       = Join-Path $ScriptDir $APP_SCRIPT
$IconPath      = Join-Path $ScriptDir $ICON_FILE
$LogoPath      = Join-Path $ScriptDir $LOGO_FILE
$SplashPath    = Join-Path $ScriptDir $SPLASH_FILE
$UserGuidePath = Join-Path $ScriptDir $USER_GUIDE_FILE

# Minimum version requirements
$MIN_PYTHON_MAJOR  = 3;    $MIN_PYTHON_MINOR  = 9
$MIN_PIP_MAJOR     = 21;   $MIN_PIP_MINOR     = 3
$MIN_PYSIDE6_MAJOR = 6;    $MIN_PYSIDE6_MINOR = 4
$MIN_PYINST_MAJOR  = 5;    $MIN_PYINST_MINOR  = 8
$MIN_HOOKS_MAJOR   = 2023; $MIN_HOOKS_MINOR   = 2
$MIN_DISK_GB       = 1.5

# ==============================================================================
#  UTILITY FUNCTIONS
# ==============================================================================

# ------------------------------------------------------------------------------
# Invoke-Native
#   Runs a native command, temporarily relaxing $ErrorActionPreference to
#   "Continue" so that pip's harmless stderr lines (e.g. "WARNING: Scripts
#   directory not on PATH") are NOT converted into terminating
#   NativeCommandError exceptions by PowerShell 5.1 with Set-StrictMode.
#   Output is suppressed. Returns the process exit code.
# ------------------------------------------------------------------------------
function Invoke-Native {
    param([string[]]$ArgList)
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $exitCode = 0
    try {
        & $ArgList[0] $ArgList[1..($ArgList.Length - 1)] 2>&1 | Out-Null
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $saved
    }
    return $exitCode
}

# ------------------------------------------------------------------------------
# Get-NativeOutput
#   Runs a native command and returns its combined stdout+stderr as a single
#   scalar string via | Out-String.
#
#   WHY Out-String IS CRITICAL FOR VERSION DETECTION:
#   In PowerShell 5.1, the 2>&1 redirection returns an array of objects (one
#   per output line) not a string. Using -match on an array FILTERS the array
#   to matching elements but does NOT set the $Matches automatic variable.
#   This means $Matches[1] retains whatever the last scalar -match set it to.
#   When we later do  $pipRaw -match "pip ([\d.]+)"  on an array, $Matches[1]
#   still holds "3" from the earlier  "Python (\d+)"  match -- which is why
#   the script falsely reported "pip 3 is too old".
#   Piping through Out-String collapses the array to a scalar, making -match
#   work correctly and always update $Matches.
# ------------------------------------------------------------------------------
function Get-NativeOutput {
    param([string[]]$ArgList)
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $result = & $ArgList[0] $ArgList[1..($ArgList.Length - 1)] 2>&1 | Out-String
    }
    finally {
        $ErrorActionPreference = $saved
    }
    return $result
}

# ------------------------------------------------------------------------------
# Test-VersionOk  -- returns $true if installed version >= required version
# ------------------------------------------------------------------------------
function Test-VersionOk {
    param([string]$verStr, [int]$needMajor, [int]$needMinor)
    if ($verStr -match "(\d+)\.(\d+)") {
        $haveMaj = [int]$Matches[1]
        $haveMin = [int]$Matches[2]
        if ($haveMaj -gt $needMajor) { return $true  }
        if ($haveMaj -lt $needMajor) { return $false }
        return ($haveMin -ge $needMinor)
    }
    return $false
}

# ------------------------------------------------------------------------------
# Get-PackageVersion  -- returns version string for an installed package,
#                        or $null if the package is not found.
#
# WHY importlib.metadata INSTEAD OF pip show:
#   Get-NativeOutput collapses all output into a single scalar string via
#   Out-String.  When that scalar is piped to Select-String, the regex
#   anchor "^" matches only the START of the entire string, not the start
#   of each line.  "^Version:" therefore never matched, causing every
#   package to appear as "not installed" even when it was present.
#
#   Using Python's own importlib.metadata avoids all string-parsing
#   fragility: it is the same API pip itself uses internally, works with
#   user-installs, virtual environments, and editable installs, and
#   returns just the version string with no surrounding text to parse.
# ------------------------------------------------------------------------------
function Get-PackageVersion {
    param([string]$Py, [string]$Package)

    # Primary: ask Python's own metadata system (Python 3.8+, always reliable)
    $pyCode  = "import importlib.metadata; print(importlib.metadata.version('$Package'))"
    $ver     = (Get-NativeOutput @($Py, "-c", $pyCode)).Trim()
    if ($LASTEXITCODE -eq 0 -and $ver -match "[\d.]") { return $ver }

    # Fallback: parse pip show line-by-line (handles edge cases)
    $showRaw = Get-NativeOutput @($Py, "-m", "pip", "show", $Package)
    if ($LASTEXITCODE -eq 0) {
        foreach ($line in ($showRaw -split "`r?`n")) {
            if ($line -match "^Version:\s*(.+)$") { return $Matches[1].Trim() }
        }
    }

    return $null
}

# ------------------------------------------------------------------------------
# Install-Package  -- installs/upgrades a package, returns new version or $null
# ------------------------------------------------------------------------------
function Install-Package {
    param([string]$Py, [string]$Package, [switch]$Upgrade)
    if ($Upgrade) {
        $exitCode = Invoke-Native @($Py, "-m", "pip", "install", $Package, "--upgrade", "--quiet")
    } else {
        $exitCode = Invoke-Native @($Py, "-m", "pip", "install", $Package, "--quiet")
    }
    if ($exitCode -ne 0) { return $null }
    return (Get-PackageVersion $Py $Package)
}

# ------------------------------------------------------------------------------
# Format-Size
# ------------------------------------------------------------------------------
function Format-Size {
    param([long]$bytes)
    if ($bytes -ge 1GB) { return "{0:N2} GB" -f ($bytes / 1GB) }
    if ($bytes -ge 1MB) { return "{0:N1} MB" -f ($bytes / 1MB) }
    return "{0:N0} KB" -f ($bytes / 1KB)
}

# ------------------------------------------------------------------------------
# Exit-Fatal  -- print message, wait for keypress, exit
# ------------------------------------------------------------------------------
function Exit-Fatal {
    param([string]$msg)
    Write-Host ""
    Write-Fail $msg
    Write-Host ""
    Read-HostSafe "  Press Enter to exit"
    exit 1
}

# ------------------------------------------------------------------------------
# Read-HostSafe
#   Wrapper around Read-Host that gracefully handles NonInteractive mode.
#   In non-interactive sessions (e.g. launched from a .bat or scheduled task),
#   Read-Host throws PSInvalidOperationException.  We catch it and return the
#   supplied $Default value so the script continues without crashing.
# ------------------------------------------------------------------------------
function Read-HostSafe {
    param(
        [string]$Prompt,
        [string]$Default = ""
    )
    try {
        return Read-Host $Prompt
    } catch {
        # NonInteractive mode -- silently use the default
        return $Default
    }
}

# ==============================================================================
#  PRE-FLIGHT CHECKS
# ==============================================================================
Write-Header
Write-Host "  Running pre-flight dependency checks ..." -ForegroundColor White
Write-Host ""

$anyWarn = $false

# ------------------------------------------------------------------------------
# CHECK 1 -- Windows OS
#   NOTE: $IsWindows was introduced in PowerShell 6.0 (Core) and does not
#   exist in Windows PowerShell 5.1. With Set-StrictMode -Version Latest,
#   reading an undefined variable throws a hard error. We use the .NET
#   OSVersion.Platform property instead, which works in all PS versions.
# ------------------------------------------------------------------------------
Write-Step "Operating system ..."
if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    Exit-Fatal "This build script targets Windows. PyInstaller .exe files only run on Windows."
}
$osVer = [System.Environment]::OSVersion.Version
Write-Ok "Windows $($osVer.Major).$($osVer.Minor) (build $($osVer.Build))"

# ------------------------------------------------------------------------------
# CHECK 2 -- 64-bit OS
# ------------------------------------------------------------------------------
Write-Step "OS architecture ..."
if ([System.IntPtr]::Size -ne 8) {
    Write-Warn "32-bit OS detected. PySide6 requires a 64-bit system."
    $anyWarn = $true
} else {
    Write-Ok "64-bit OS"
}

# ------------------------------------------------------------------------------
# CHECK 3 -- App script and icon present
# ------------------------------------------------------------------------------
Write-Step "Application script: $APP_SCRIPT ..."
if (-not (Test-Path $AppPath)) {
    Exit-Fatal "$APP_SCRIPT not found in $ScriptDir`n         Place build_exe.ps1 in the same folder as $APP_SCRIPT"
}
Write-Ok "Found: $AppPath"

Write-Step "Application icon: $ICON_FILE ..."
if (-not (Test-Path $IconPath)) {
    Write-Warn "$ICON_FILE not found -- building without a custom icon"
    $anyWarn = $true
} else {
    Write-Ok "Found: $IconPath"
}

Write-Step "Splash screen image: $SPLASH_FILE ..."
if (-not (Test-Path $SplashPath)) {
    Write-Warn "$SPLASH_FILE not found -- building without a startup splash screen"
    $anyWarn = $true
} else {
    Write-Ok "Found: $SplashPath"
}

# ------------------------------------------------------------------------------
# CHECK 4 -- Disk space >= 1.5 GB
# ------------------------------------------------------------------------------
Write-Step "Available disk space (need >= $MIN_DISK_GB GB) ..."
try {
    $drive  = Split-Path -Qualifier $ScriptDir
    $freeGB = (Get-PSDrive ($drive -replace ":", "")).Free / 1GB
    if ($freeGB -lt $MIN_DISK_GB) {
        Write-Warn ("Only {0:N1} GB free on {1} -- build may fail (need ~{2} GB)" -f $freeGB, $drive, $MIN_DISK_GB)
        $anyWarn = $true
    } else {
        Write-Ok ("{0:N1} GB free on {1}" -f $freeGB, $drive)
    }
} catch {
    Write-Warn "Could not determine disk space: $_"
}

# ------------------------------------------------------------------------------
# CHECK 5 -- Python >= 3.9
# ------------------------------------------------------------------------------
Write-Sep
Write-Step "Python >= $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR ..."

$py = $null
foreach ($cmd in @("python", "python3", "py")) {
    # Use Get-NativeOutput so the version string is a scalar (not an array)
    # before we apply -match, ensuring $Matches is populated correctly.
    $v = Get-NativeOutput @($cmd, "--version")
    if ($v -match "Python (\d+)\.(\d+)") {
        if (Test-VersionOk "$($Matches[1]).$($Matches[2])" $MIN_PYTHON_MAJOR $MIN_PYTHON_MINOR) {
            $py = $cmd; break
        }
    }
}

if ($null -eq $py) {
    Write-Fail "Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+ not found on PATH."
    Write-Host ""

    # -- Try winget (Windows 10 1709+ / Windows 11) ----------------------
    $wingetAvail = $false
    try { $null = & winget --version 2>&1; $wingetAvail = ($LASTEXITCODE -eq 0) } catch {}

    if ($wingetAvail) {
        # Find newest Python available in the winget catalog (future-proof).
        $pyWingetId = $null
        foreach ($candidate in @("Python.Python.3.14","Python.Python.3.13","Python.Python.3.12","Python.Python.3.11","Python.Python.3.10","Python.Python.3.9")) {
            try { $null = & winget show --id $candidate --source winget 2>&1 } catch {}
            if ($LASTEXITCODE -eq 0) { $pyWingetId = $candidate; break }
        }
        if (-not $pyWingetId) { $pyWingetId = "Python.Python.3.12" }

        Write-Step "winget found -- installing $pyWingetId from Microsoft Store..."
        Write-Info  "(This may take a minute. Please wait.)"
        Write-Host ""
        try {
            & winget install --id $pyWingetId --source winget `
                --silent --accept-package-agreements --accept-source-agreements
        } catch {}
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Python installed via winget. Restarting build script..."
            Start-Sleep -Seconds 1
            & $PSCommandPath @args
            exit $LASTEXITCODE
        } else {
            Write-Warn "winget install failed (exit $LASTEXITCODE)."
        }
    } else {
        Write-Warn "winget is not available on this machine."
    }

    Write-Host ""
    Write-Host "  How to install Python:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    Option A -- winget:" -ForegroundColor Cyan
    Write-Info  "      winget install Python.Python.3.13   (or .3.12, .3.11 etc.)"
    Write-Host ""
    Write-Host "    Option B -- python.org:" -ForegroundColor Cyan
    Write-Info  "      https://www.python.org/downloads/"
    Write-Info  "      CHECK 'Add Python to PATH' on the first screen."
    Write-Host ""
    Exit-Fatal "Cannot continue without Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+."
}

$pyVerFull = (Get-NativeOutput @($py, "--version")) -replace "Python\s*", "" -replace "\s", ""
Write-Ok "Python $pyVerFull  (command: $py)"

# ------------------------------------------------------------------------------
# CHECK 6 -- 64-bit Python interpreter
# ------------------------------------------------------------------------------
Write-Step "Python interpreter architecture ..."
$pyBits = (Get-NativeOutput @($py, "-c", "import struct; print(struct.calcsize('P')*8)")).Trim()
if ($pyBits -ne "64") {
    Write-Warn "Python interpreter is $pyBits-bit. PySide6 requires 64-bit Python."
    Write-Info "Download 64-bit Python: https://www.python.org/downloads/"
    $anyWarn = $true
} else {
    Write-Ok "64-bit interpreter"
}

# ------------------------------------------------------------------------------
# CHECK 7 -- pip >= 21.3
#
# BUGS FIXED (both caused the false "pip 3 is too old" error):
#
#   Bug 1 - Array vs scalar:
#     In PS 5.1, "& python -m pip --version 2>&1" returns an ARRAY of objects
#     when pip emits any stderr output (e.g. the PATH warning). Applying -match
#     to an array filters the array without updating $Matches. So $Matches[1]
#     still held "3" from the earlier "Python (\d+)" regex, making the version
#     check falsely read "3" instead of the real pip version.
#     Fix: Get-NativeOutput pipes through Out-String to produce a scalar string.
#
#   Bug 2 - NativeCommandError:
#     With $ErrorActionPreference="Stop", PS 5.1 promotes native-command stderr
#     text to ErrorRecord objects. The "WARNING: Scripts not on PATH" line from
#     pip became a terminating NativeCommandError thrown on the 2>&1 line.
#     Fix: Get-NativeOutput and Invoke-Native temporarily set
#     $ErrorActionPreference="Continue" around every pip/python call.
# ------------------------------------------------------------------------------
Write-Sep
Write-Step "pip >= $MIN_PIP_MAJOR.$MIN_PIP_MINOR ..."

$pipRaw = Get-NativeOutput @($py, "-m", "pip", "--version")
if ($LASTEXITCODE -ne 0) {
    Write-Warn "pip missing -- bootstrapping ..."
    Invoke-Native @($py, "-m", "ensurepip", "--upgrade") | Out-Null
    if ($LASTEXITCODE -ne 0) { Exit-Fatal "Cannot install pip. Install it manually." }
    $pipRaw = Get-NativeOutput @($py, "-m", "pip", "--version")
}

# $pipRaw is now a scalar string -- -match correctly populates $Matches
$pipVerStr = if ($pipRaw -match "pip ([\d.]+)") { $Matches[1] } else { "0.0" }

if (-not (Test-VersionOk $pipVerStr $MIN_PIP_MAJOR $MIN_PIP_MINOR)) {
    Write-Warn "pip $pipVerStr is too old (need >= $MIN_PIP_MAJOR.$MIN_PIP_MINOR) -- upgrading ..."
    Invoke-Native @($py, "-m", "pip", "install", "--upgrade", "pip", "--quiet") | Out-Null
    $pipRaw    = Get-NativeOutput @($py, "-m", "pip", "--version")
    $pipVerStr = if ($pipRaw -match "pip ([\d.]+)") { $Matches[1] } else { "0.0" }
}

Write-Ok "pip $pipVerStr"

# ------------------------------------------------------------------------------
# CHECK 8 -- setuptools and wheel
# ------------------------------------------------------------------------------
Write-Sep
foreach ($pkg in @("setuptools", "wheel")) {
    Write-Step "$pkg (build infrastructure) ..."
    $ver = Get-PackageVersion $py $pkg
    if ($null -eq $ver) {
        Write-Warn "$pkg not found -- installing ..."
        $ver = Install-Package $py $pkg
        if ($null -eq $ver) {
            Write-Warn "Could not install $pkg. Build may still succeed."
            $anyWarn = $true
            continue
        }
    }
    Write-Ok "$pkg $ver"
}

# ------------------------------------------------------------------------------
# CHECK 9 -- PySide6 >= 6.4 + individual Qt module imports
# ------------------------------------------------------------------------------
Write-Sep
Write-Step "PySide6 >= $MIN_PYSIDE6_MAJOR.$MIN_PYSIDE6_MINOR ..."

$pyside6Ver = Get-PackageVersion $py "PySide6"
if ($null -eq $pyside6Ver) {
    Write-Warn "PySide6 not installed -- installing (may take a few minutes) ..."
    $pyside6Ver = Install-Package $py "PySide6"
    if ($null -eq $pyside6Ver) { Exit-Fatal "Failed to install PySide6." }
    Write-Ok "PySide6 $pyside6Ver  (freshly installed)"
} elseif (-not (Test-VersionOk $pyside6Ver $MIN_PYSIDE6_MAJOR $MIN_PYSIDE6_MINOR)) {
    Write-Warn "PySide6 $pyside6Ver is below minimum $MIN_PYSIDE6_MAJOR.$MIN_PYSIDE6_MINOR -- upgrading ..."
    $pyside6Ver = Install-Package $py "PySide6" -Upgrade
    if ($null -eq $pyside6Ver) { Exit-Fatal "Failed to upgrade PySide6." }
    Write-Ok "PySide6 $pyside6Ver  (upgraded)"
} else {
    Write-Ok "PySide6 $pyside6Ver"
}

Write-Step "Verifying required PySide6 Qt modules ..."
$qtModules   = @("PySide6.QtWidgets", "PySide6.QtCore", "PySide6.QtGui")
$modulesFail = $false
foreach ($mod in $qtModules) {
    try   { $null = & $py -c "import $mod" 2>&1 } catch {}
    $modOk    = ($LASTEXITCODE -eq 0)
    if (-not $modOk) {
        Write-Fail "  Cannot import $mod"
        $modulesFail = $true
    } else {
        Write-Ok "  $mod"
    }
}
if ($modulesFail) {
    Write-Warn "Some Qt modules failed to import."
    Write-Info "Try: $py -m pip install --force-reinstall PySide6"
    $anyWarn = $true
}

# ------------------------------------------------------------------------------
# CHECK 9b -- deep-translator (Google Translate / MyMemory / Microsoft engines)
# ------------------------------------------------------------------------------
Write-Sep
Write-Step "deep-translator ..."

$deepTransVer = Get-PackageVersion $py "deep-translator"
if ($null -eq $deepTransVer) {
    Write-Warn "deep-translator not installed -- installing ..."
    $deepTransVer = Install-Package $py "deep-translator"
    if ($null -eq $deepTransVer) { Exit-Fatal "Failed to install deep-translator." }
    Write-Ok "deep-translator $deepTransVer  (freshly installed)"
} else {
    Write-Ok "deep-translator $deepTransVer"
}

# ------------------------------------------------------------------------------
# CHECK 9c -- claude-agent-sdk (Claude Subscription engine)
# ------------------------------------------------------------------------------
Write-Sep
Write-Step "claude-agent-sdk (optional, for Claude Subscription engine) ..."

$claudeSdkVer = Get-PackageVersion $py "claude-agent-sdk"
if ($null -eq $claudeSdkVer) {
    Write-Warn "claude-agent-sdk not installed -- installing ..."
    $claudeSdkVer = Install-Package $py "claude-agent-sdk"
    if ($null -eq $claudeSdkVer) {
        Write-Warn "Could not install claude-agent-sdk. Claude (Subscription) engine will not work."
        $anyWarn = $true
    } else {
        Write-Ok "claude-agent-sdk $claudeSdkVer  (installed)"
    }
} else {
    Write-Ok "claude-agent-sdk $claudeSdkVer"
}

# ------------------------------------------------------------------------------
# CHECK 9d -- Node.js + Claude CLI (Claude Subscription engine)
# ------------------------------------------------------------------------------
Write-Sep
Write-Step "Node.js (optional, for Claude Subscription engine) ..."
$nodeOk = $false
try { $null = & node --version 2>&1; $nodeOk = ($LASTEXITCODE -eq 0) } catch {}

if (-not $nodeOk) {
    $wingetAvail2 = $false
    try { $null = & winget --version 2>&1; $wingetAvail2 = ($LASTEXITCODE -eq 0) } catch {}
    if ($wingetAvail2) {
        Write-Step "Node.js not found -- installing via winget ..."
        try {
            & winget install --id OpenJS.NodeJS.LTS --source winget `
                --silent --accept-package-agreements --accept-source-agreements
        } catch {}
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        try { $null = & node --version 2>&1; $nodeOk = ($LASTEXITCODE -eq 0) } catch {}
    }
}

if ($nodeOk) {
    Write-Ok "Node.js available"
    Write-Step "Claude CLI ..."
    $claudeOk = $false
    try { $null = & claude --version 2>&1; $claudeOk = ($LASTEXITCODE -eq 0) } catch {}
    if (-not $claudeOk) {
        Write-Warn "Claude CLI not found -- installing via npm ..."
        try { & npm install -g "@anthropic-ai/claude-code" --silent } catch {}
        try { $null = & claude --version 2>&1; $claudeOk = ($LASTEXITCODE -eq 0) } catch {}
    }
    if ($claudeOk) {
        Write-Ok "Claude CLI available"
    } else {
        Write-Warn "Claude CLI unavailable -- Claude (Subscription) engine will not work."
        Write-Info "Install manually: npm install -g @anthropic-ai/claude-code"
        $anyWarn = $true
    }
} else {
    Write-Warn "Node.js unavailable -- Claude (Subscription) engine will not work."
    Write-Info "Install manually: winget install OpenJS.NodeJS.LTS"
    $anyWarn = $true
}

# ------------------------------------------------------------------------------
# CHECK 10 -- pyinstaller-hooks-contrib >= 2023.2
# ------------------------------------------------------------------------------
Write-Sep
Write-Step "pyinstaller-hooks-contrib >= $MIN_HOOKS_MAJOR.$MIN_HOOKS_MINOR ..."

$hooksVer = Get-PackageVersion $py "pyinstaller-hooks-contrib"
if ($null -eq $hooksVer) {
    Write-Warn "Not found -- installing ..."
    $hooksVer = Install-Package $py "pyinstaller-hooks-contrib"
    if ($null -eq $hooksVer) {
        Write-Warn "Could not install pyinstaller-hooks-contrib. PySide6 bundling may be incomplete."
        $anyWarn = $true
    } else {
        Write-Ok "pyinstaller-hooks-contrib $hooksVer  (installed)"
    }
} elseif (-not (Test-VersionOk $hooksVer $MIN_HOOKS_MAJOR $MIN_HOOKS_MINOR)) {
    Write-Warn "Version $hooksVer is below minimum -- upgrading ..."
    $hooksVer = Install-Package $py "pyinstaller-hooks-contrib" -Upgrade
    Write-Ok "pyinstaller-hooks-contrib $hooksVer  (upgraded)"
} else {
    Write-Ok "pyinstaller-hooks-contrib $hooksVer"
}

# ------------------------------------------------------------------------------
# CHECK 11 -- PyInstaller >= 5.8
# ------------------------------------------------------------------------------
Write-Sep
Write-Step "PyInstaller >= $MIN_PYINST_MAJOR.$MIN_PYINST_MINOR ..."

$piVer = Get-PackageVersion $py "pyinstaller"
if ($null -eq $piVer) {
    Write-Warn "Not found -- installing ..."
    $piVer = Install-Package $py "pyinstaller"
    if ($null -eq $piVer) { Exit-Fatal "Failed to install PyInstaller." }
    Write-Ok "PyInstaller $piVer  (installed)"
} elseif (-not (Test-VersionOk $piVer $MIN_PYINST_MAJOR $MIN_PYINST_MINOR)) {
    Write-Warn "Version $piVer is below minimum -- upgrading ..."
    $piVer = Install-Package $py "pyinstaller" -Upgrade
    if ($null -eq $piVer) { Exit-Fatal "Failed to upgrade PyInstaller." }
    Write-Ok "PyInstaller $piVer  (upgraded)"
} else {
    Write-Ok "PyInstaller $piVer"
}

# ------------------------------------------------------------------------------
# CHECK 12 -- PyInstaller Windows runtime dependencies
# ------------------------------------------------------------------------------
Write-Sep
Write-Step "PyInstaller Windows runtime dependencies ..."

$winDeps = [ordered]@{
    "altgraph"       = "0.17"
    "pefile"         = "2023.2"
    "pywin32-ctypes" = "0.2"
}

foreach ($dep in $winDeps.Keys) {
    $minVer   = $winDeps[$dep]
    $minParts = $minVer -split "\."
    $minMaj   = [int]$minParts[0]
    $minMin   = [int]$minParts[1]

    Write-Step "  $dep >= $minVer ..."
    $ver = Get-PackageVersion $py $dep
    if ($null -eq $ver) {
        Write-Warn "  $dep not found -- installing ..."
        $ver = Install-Package $py $dep
        if ($null -eq $ver) {
            Write-Warn "  Could not install $dep (PyInstaller may bundle it internally)."
        } else {
            Write-Ok "  $dep $ver  (installed)"
        }
    } elseif (-not (Test-VersionOk $ver $minMaj $minMin)) {
        Write-Warn "  $dep $ver is old -- upgrading ..."
        $ver = Install-Package $py $dep -Upgrade
        Write-Ok "  $dep $ver  (upgraded)"
    } else {
        Write-Ok "  $dep $ver"
    }
}

# ------------------------------------------------------------------------------
# CHECK 13 -- PyInstaller dry-run sanity check
# ------------------------------------------------------------------------------
Write-Sep
Write-Step "PyInstaller executable sanity check ..."
$piHelp = Get-NativeOutput @($py, "-m", "PyInstaller", "--version")
if ($LASTEXITCODE -ne 0) {
    Exit-Fatal "PyInstaller is installed but cannot be run: $piHelp"
}
Write-Ok "PyInstaller $($piHelp.Trim()) runs correctly"

# ------------------------------------------------------------------------------
# CHECK 14 -- Tcl/Tk availability (required by PyInstaller's --splash option)
#   PyInstaller's splash screen is rendered by a small bundled Tcl/Tk runtime;
#   if the BUILD machine's Python has no tkinter, passing --splash makes
#   PyInstaller fail the whole build outright (unlike the icon/logo, which
#   degrade gracefully). So this is checked up front and --splash is simply
#   omitted if unavailable -- end users never need Tcl/Tk themselves, since
#   the minimal runtime PyInstaller needs is bundled into the exe.
# ------------------------------------------------------------------------------
Write-Sep
Write-Step "Tcl/Tk availability (required for splash screen) ..."
$tkOk = $false
try { $null = & $py -c "import tkinter" 2>&1 } catch {}
if ($LASTEXITCODE -eq 0) {
    $tkOk = $true
    Write-Ok "tkinter available"
} else {
    Write-Warn "tkinter not available -- building without a startup splash screen"
    $anyWarn = $true
}

# ==============================================================================
#  PRE-FLIGHT SUMMARY
# ==============================================================================
Write-Host ""
Write-Sep
if ($anyWarn) {
    Write-Warn "Pre-flight completed with warnings (see above). Proceeding with build."
} else {
    Write-Ok "All pre-flight checks passed."
}

# ==============================================================================
#  BUILD
# ==============================================================================
Write-Sep
Write-Host ""
Write-Step "Cleaning previous build artefacts ..."
foreach ($dir in @($DIST_DIR, $BUILD_DIR)) {
    $full = Join-Path $ScriptDir $dir
    if (Test-Path $full) { Remove-Item $full -Recurse -Force; Write-Info "  Removed $full" }
}
$specPath = Join-Path $ScriptDir "$APP_NAME.spec"
if (Test-Path $specPath) { Remove-Item $specPath -Force }
Write-Ok "Clean"

Write-Host ""
Write-Host "  Building executable -- this typically takes 1-4 minutes ..." -ForegroundColor White
Write-Host ""

Set-Location $ScriptDir

# PyInstaller output goes to the console so the user can see progress.
# We still need ErrorActionPreference = Continue to suppress any incidental
# stderr lines from PyInstaller's sub-processes.
$iconArgs = @()
if (Test-Path $IconPath) {
    $iconArgs += @("--icon", $IconPath, "--add-data", "$IconPath;Resources")
}
if (Test-Path $LogoPath) {
    # Bundled so the Welcome screen's logo (loaded via APP_LOGO_PATH at
    # runtime) still resolves inside a frozen onefile exe, same reasoning
    # as the icon above.
    $iconArgs += @("--add-data", "$LogoPath;Resources")
}
if ($tkOk -and (Test-Path $SplashPath)) {
    # PyInstaller embeds the splash image directly into the bootloader --
    # no --add-data needed. It is shown while the onefile archive is
    # unpacking, before Python or Qt have started; xml_translation_editor.py's
    # main() closes it once the main window is shown.
    $iconArgs += @("--splash", $SplashPath)
}

$saved = $ErrorActionPreference
$ErrorActionPreference = "Continue"
# PySide6 is deliberately NOT --collect-all'd: that flag bundles every Qt
# module in the wheel (WebEngine, 3D, Quick, ...) whether or not the app
# imports it -- roughly 200 MB of dead weight. PyInstaller's own PySide6
# hooks bundle just what the script imports (QtWidgets/QtGui/QtCore) plus
# the Qt plugins those modules need.
& $py -m PyInstaller `
    --onefile `
    --windowed `
    --name        $APP_NAME `
    --distpath    $DIST_DIR `
    --workpath    $BUILD_DIR `
    --specpath    $ScriptDir `
    --noconfirm `
    --collect-all deep_translator `
    --collect-all claude_agent_sdk `
    @iconArgs `
    $APP_SCRIPT
$buildExit = $LASTEXITCODE
$ErrorActionPreference = $saved

if ($buildExit -ne 0) {
    Write-Host ""
    Write-Fail "PyInstaller failed (exit code $buildExit)."
    Write-Info "Common fixes:"
    Write-Info "  $py -m pip install --upgrade --force-reinstall pyinstaller PySide6"
    Write-Info "  Ensure antivirus is not blocking PyInstaller's temp folder."
    Read-HostSafe "  Press Enter to exit"
    exit 1
}

# ==============================================================================
#  VERIFY OUTPUT
# ==============================================================================
Write-Host ""
$exePath = Join-Path $ScriptDir "$DIST_DIR\$APP_NAME.exe"
if (-not (Test-Path $exePath)) {
    Exit-Fatal "Build reported success but .exe not found at:`n         $exePath"
}

$exeSize = (Get-Item $exePath).Length

# Copy the User Guide alongside the exe so it travels with dist\ when the
# folder is handed off -- best-effort, same as the icon check above: a
# missing guide should never fail an otherwise-successful build.
if (Test-Path $UserGuidePath) {
    try {
        Copy-Item -Path $UserGuidePath -Destination (Join-Path $ScriptDir $DIST_DIR) -Force -ErrorAction Stop
        Write-Ok "Copied User_Guide.pdf to $DIST_DIR\"
    } catch {
        Write-Warn "Could not copy User_Guide.pdf to $DIST_DIR\: $($_.Exception.Message)"
    }
} else {
    Write-Warn "User_Guide.pdf not found at $UserGuidePath -- skipping (dist\ will not include it)"
}

Write-Host ""
Write-Host "  +----------------------------------------------------------------+" -ForegroundColor Green
Write-Host "  |                    BUILD SUCCESSFUL                            |" -ForegroundColor Green
Write-Host "  +----------------------------------------------------------------+" -ForegroundColor Green
Write-Host ("  |  Output : {0,-56}|" -f $exePath) -ForegroundColor Green
Write-Host ("  |  Size   : {0,-56}|" -f (Format-Size $exeSize)) -ForegroundColor Green
Write-Host "  +----------------------------------------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Info "The .exe is fully portable -- no Python or PySide6 needed on the target PC."
Write-Info "Usage:  $APP_NAME.exe  [optional: path\to\file.xml]"
Write-Host ""

$launch = Read-HostSafe "  Launch the executable now to test it? [Y/n]" -Default "n"
if ($launch -ne "n" -and $launch -ne "N") {
    Write-Info "Starting $APP_NAME.exe ..."
    Start-Process $exePath
}

Read-HostSafe "  Press Enter to exit"
