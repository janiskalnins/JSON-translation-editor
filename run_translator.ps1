#Requires -Version 5.1
<#
.SYNOPSIS
    Launcher for JSON Translation Editor
.DESCRIPTION
    Checks Python installation, verifies/installs dependencies,
    then launches json_translation_editor.py.
    Run with:  powershell -ExecutionPolicy Bypass -File run_translator.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

# -- Detect Windows Terminal ---------------------------------------------------
# $env:WT_SESSION is set to a GUID by Windows Terminal for every hosted session.
# Under WT the console resize and P/Invoke centering must be skipped: WT manages
# its own window/pane geometry and GetConsoleWindow() returns the WT process HWND.
$script:_isWT = -not [string]::IsNullOrEmpty($env:WT_SESSION)

# == Window: compact size + centered on screen =================================
$HOST.UI.RawUI.WindowTitle = "JSON Translation Editor"

if (-not $script:_isWT) {
    try {
        $raw = $Host.UI.RawUI
        $cW  = 72    # columns
        $cH  = 46    # visible rows -- tall enough to show the full ASCII banner unscrolled

        # Buffer width must be >= window width at all times.
        # Grow buffer first when expanding, shrink window first when contracting.
        $buf = $raw.BufferSize
        if ($buf.Width -lt $cW) { $buf.Width = $cW; $raw.BufferSize = $buf }
        $win = $raw.WindowSize
        $win.Width  = $cW
        $win.Height = $cH
        $raw.WindowSize = $win
        $buf = $raw.BufferSize
        $buf.Width = $cW
        $raw.BufferSize = $buf
    } catch { <# not a real console -- skip #> }

    # Center console window on the primary screen via Win32
    try {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class XmlLauncherWin32 {
    [DllImport("kernel32.dll")]
    public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(
        IntPtr hWnd, IntPtr hWndInsertAfter,
        int X, int Y, int cx, int cy, uint uFlags);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@ -ErrorAction SilentlyContinue
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue

        $hwnd   = [XmlLauncherWin32]::GetConsoleWindow()
        $screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $rect   = New-Object XmlLauncherWin32+RECT
        [void][XmlLauncherWin32]::GetWindowRect($hwnd, [ref]$rect)
        $ww = $rect.Right  - $rect.Left
        $wh = $rect.Bottom - $rect.Top
        $wx = [int](($screen.Width  - $ww) / 2)
        $wy = [int](($screen.Height - $wh) / 2)
        # 0x0001 = SWP_NOSIZE  (move only, do not resize)
        [void][XmlLauncherWin32]::SetWindowPos($hwnd, [IntPtr]::Zero, $wx, $wy, 0, 0, 0x0001)
    } catch { <# no GUI session -- skip #> }
}

# == Output helpers ============================================================
function Write-Header {
    Clear-Host
    Write-Host ""
    if ($script:_asciiBanner) {
        foreach ($line in $script:_asciiBanner) { Write-Host $line }
        Write-Host ""
    }
    Write-Host "  +----------------------------------------------+" -ForegroundColor Cyan
    Write-Host "  |       JSON Translation Editor  --  Launcher  |" -ForegroundColor Cyan
    Write-Host "  +----------------------------------------------+" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  !! Do not close this window while the app runs !!" -ForegroundColor Yellow
    Write-Host "     Closing it will also close the Translation Editor." -ForegroundColor DarkYellow
    Write-Host ""
}

function Write-Step { param($msg) Write-Host "  [ .. ] $msg" -ForegroundColor DarkCyan }
function Write-Ok   { param($msg) Write-Host "  [ OK ] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red }
function Write-Info { param($msg) Write-Host "         $msg" -ForegroundColor Gray }

# == Read-HostSafe =============================================================
function Read-HostSafe {
    param([string]$Prompt, [string]$Default = "")
    try   { return Read-Host $Prompt }
    catch { return $Default }
}

# == Constants =================================================================
$MIN_PYTHON_MAJOR   = 3
$MIN_PYTHON_MINOR   = 9
$APP_SCRIPT         = "json_translation_editor.py"
$REQUIRED_PACKAGES  = @("PySide6", "deep-translator", "claude-agent-sdk")
$PackageImportMap   = @{ "PySide6" = "PySide6"; "deep-translator" = "deep_translator"; "claude-agent-sdk" = "claude_agent_sdk" }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$AppPath   = Join-Path $ScriptDir $APP_SCRIPT
$appArgs   = $args   # defined early -- used by both fast and full paths

# == ASCII banner ===============================================================
# Best-effort: a missing/unreadable art file just means no banner, never an error.
$AsciiArtPath = Join-Path $ScriptDir "Resources\json_translation_editor_ascii.txt"
$script:_asciiBanner = $null
if (Test-Path $AsciiArtPath) {
    try { $script:_asciiBanner = @(Get-Content $AsciiArtPath -ErrorAction Stop) } catch { $script:_asciiBanner = $null }
}

# == Launch cache ==============================================================
# launcher_cache.json records the last known-good Python path and package
# versions so repeated launches skip all pre-flight spawns.
# The cache is written after every successful full check and is invalidated
# automatically if Python can no longer be found, or after CACHE_MAX_DAYS.
$CacheFile     = Join-Path $ScriptDir "launcher_cache.json"
$CACHE_MAX_DAYS = 30

function Read-LaunchCache {
    if (-not (Test-Path $CacheFile)) { return $null }
    try {
        $c = Get-Content $CacheFile -Raw | ConvertFrom-Json
        if ([string]::IsNullOrEmpty($c.python_cmd) -or [string]::IsNullOrEmpty($c.checked_at)) {
            return $null
        }
        $age = (Get-Date) - [datetime]$c.checked_at
        if ($age.TotalDays -gt $CACHE_MAX_DAYS) { return $null }

        $hasRequires     = ($c.PSObject.Properties.Name -contains 'requires')
        $currentRequires = $REQUIRED_PACKAGES -join ","
        if (-not $hasRequires -or $c.requires -ne $currentRequires) { return $null }

        return $c
    } catch { return $null }
}

function Write-LaunchCache {
    param([string]$PythonCmd, [string]$PythonVer, [string]$PySide6Ver)
    try {
        $obj = [ordered]@{
            python_cmd  = $PythonCmd
            python_ver  = $PythonVer
            pyside6_ver = $PySide6Ver
            requires    = ($REQUIRED_PACKAGES -join ",")
            checked_at  = (Get-Date -Format 'o')
        }
        $obj | ConvertTo-Json | Set-Content $CacheFile -Encoding UTF8
    } catch {}
}

function Remove-LaunchCache {
    try { if (Test-Path $CacheFile) { Remove-Item $CacheFile -Force } } catch {}
}

# Invoke Python from a command string that may contain a leading argument
# (e.g. "py -3.9" -> exe="py", pre=@("-3.9"), then append caller's args).
function Invoke-Python {
    param([string]$Cmd, [string[]]$Arguments = @())
    $parts = $Cmd -split '\s+', 2
    $exe   = $parts[0]
    $pre   = if ($parts.Length -gt 1) { $parts[1] -split '\s+' } else { @() }
    & $exe @pre @Arguments
}

# == Helpers ===================================================================
function Test-VersionAtLeast {
    param([int]$MajorHave, [int]$MinorHave, [int]$MajorNeed, [int]$MinorNeed)
    if ($MajorHave -gt $MajorNeed) { return $true  }
    if ($MajorHave -lt $MajorNeed) { return $false }
    return ($MinorHave -ge $MinorNeed)
}

function Find-Python {
    $candidates = @("python", "python3", "py")
    foreach ($cmd in $candidates) {
        try {
            $ver = & $cmd --version 2>&1
            if ($ver -match "Python (\d+)\.(\d+)") {
                $maj = [int]$Matches[1]; $min = [int]$Matches[2]
                if (Test-VersionAtLeast $maj $min $MIN_PYTHON_MAJOR $MIN_PYTHON_MINOR) {
                    return $cmd
                }
            }
        } catch { <# not found, try next #> }
    }
    try {
        $ver = & py "-$MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR" --version 2>&1
        if ($ver -match "Python") { return "py -$MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR" }
    } catch { }
    return $null
}

function Test-PythonPackage {
    param([string]$PythonCmd, [string]$Package)
    $importName = if ($PackageImportMap.ContainsKey($Package)) { $PackageImportMap[$Package] } else { $Package }
    try   { $null = Invoke-Python $PythonCmd @("-c", "import $importName") 2>&1 }
    catch { return $false }
    return ($LASTEXITCODE -eq 0)
}

function Install-PythonPackage {
    param([string]$PythonCmd, [string]$Package)
    Write-Step "Installing $Package ..."
    try   { Invoke-Python $PythonCmd @("-m", "pip", "install", "--upgrade", $Package, "--quiet") }
    catch { return $false }
    return ($LASTEXITCODE -eq 0)
}

function Show-RunningBox {
    Write-Host ""
    Write-Host "  +-------------------------------------------------+" -ForegroundColor DarkCyan
    Write-Host "  |  App is running.  Do NOT close this window.    |" -ForegroundColor DarkCyan
    Write-Host "  |  Closing it will also close the editor.        |" -ForegroundColor DarkCyan
    Write-Host "  +-------------------------------------------------+" -ForegroundColor DarkCyan
    Write-Host ""
}

# ==============================================================================
#  MAIN
# ==============================================================================
Write-Header

# -- Fast path: skip all pre-flight checks if cache is valid -------------------
$cache = Read-LaunchCache
if ($null -ne $cache) {
    $importNames = $REQUIRED_PACKAGES | ForEach-Object {
        if ($PackageImportMap.ContainsKey($_)) { $PackageImportMap[$_] } else { $_ }
    }
    $checkScript = "import " + ($importNames -join ", ")
    $pyOk = $false
    try {
        $null = Invoke-Python $cache.python_cmd @("-c", $checkScript) 2>&1
        $pyOk = ($LASTEXITCODE -eq 0)
    } catch {}

    if ($pyOk) {
        $checkedDate = ([datetime]$cache.checked_at).ToString('dd MMM yyyy')
        Write-Ok "Fast start  (last verified: $checkedDate)"
        Write-Ok "Python $($cache.python_ver)  ($($cache.python_cmd))"
        if (-not [string]::IsNullOrEmpty($cache.pyside6_ver)) {
            Write-Ok "PySide6 $($cache.pyside6_ver)"
        }
        Show-RunningBox
        $launchOk = $false
        try {
            Invoke-Python $cache.python_cmd (@($AppPath) + @($appArgs))
            $launchOk = ($LASTEXITCODE -eq 0)
            $appExitCode = $LASTEXITCODE
        } catch {
            Write-Fail "Failed to launch: $_"
        }

        if ($launchOk) { exit $appExitCode }

        Remove-LaunchCache
        Write-Warn "Cached launch failed -- running full check ..."
        Write-Host ""
    } else {
        # Cached Python/packages no longer valid -- fall through to full check
        Remove-LaunchCache
        Write-Warn "Cached environment invalid -- running full check ..."
        Write-Host ""
    }
}

# -- 1. Check app script exists ------------------------------------------------
Write-Step "Locating $APP_SCRIPT ..."
if (-not (Test-Path $AppPath)) {
    Write-Fail "$APP_SCRIPT not found in: $ScriptDir"
    Write-Info "Make sure run_translator.ps1 is in the same folder as $APP_SCRIPT"
    Write-Host ""
    Read-HostSafe "  Press Enter to exit"
    exit 1
}
Write-Ok "$APP_SCRIPT found"

# -- 2. Find Python ------------------------------------------------------------
Write-Step "Checking Python >= $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR ..."
$PythonCmd = Find-Python

if ($null -eq $PythonCmd) {
    Write-Fail "Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+ not found on PATH."
    Write-Host ""

    $wingetAvail = $false
    try { $null = & winget --version 2>&1; $wingetAvail = ($LASTEXITCODE -eq 0) } catch {}

    if ($wingetAvail) {
        $pyWingetId = $null
        foreach ($candidate in @("Python.Python.3.14","Python.Python.3.13","Python.Python.3.12","Python.Python.3.11","Python.Python.3.10","Python.Python.3.9")) {
            try { $null = & winget show --id $candidate --source winget 2>&1 } catch {}
            if ($LASTEXITCODE -eq 0) { $pyWingetId = $candidate; break }
        }
        if (-not $pyWingetId) { $pyWingetId = "Python.Python.3.12" }

        Write-Step "winget found -- installing $pyWingetId ..."
        Write-Info  "(This may take a minute. Please wait.)"
        Write-Host ""
        try {
            & winget install --id $pyWingetId --source winget `
                --silent --accept-package-agreements --accept-source-agreements
        } catch {}

        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Python installed via winget."
            Write-Host ""
            Write-Info "Restarting launcher to pick up the new Python ..."
            Start-Sleep -Seconds 1
            & $PSCommandPath @args
            exit $LASTEXITCODE
        } else {
            Write-Warn "winget install failed (exit $LASTEXITCODE). See manual steps below."
            Write-Host ""
        }
    } else {
        Write-Warn "winget is not available on this machine."
        Write-Host ""
    }

    Write-Host "  How to install Python:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    Option A -- winget:" -ForegroundColor Cyan
    Write-Info  "      winget install Python.Python.3.13"
    Write-Host ""
    Write-Host "    Option B -- Microsoft Store:" -ForegroundColor Cyan
    Write-Info  "      Search 'python' in the Start menu -> Get"
    Write-Host ""
    Write-Host "    Option C -- python.org:" -ForegroundColor Cyan
    Write-Info  "      https://www.python.org/downloads/"
    Write-Info  "      CHECK 'Add Python to PATH' on the first screen."
    Write-Host ""
    $open = Read-HostSafe "  Open python.org in browser? [Y/n]" -Default "n"
    if ($open -ne "n" -and $open -ne "N") { Start-Process "https://www.python.org/downloads/" }
    Read-HostSafe "  Press Enter to exit"
    exit 1
}

$verStr = (Invoke-Python $PythonCmd @("--version") 2>&1) -replace "Python ", ""
Write-Ok "Python $verStr  ($PythonCmd)"

# -- 3. Check pip --------------------------------------------------------------
Write-Step "Checking pip ..."
$null = Invoke-Python $PythonCmd @("-m", "pip", "--version") 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warn "pip not found -- bootstrapping ..."
    try { $null = Invoke-Python $PythonCmd @("-m", "ensurepip", "--upgrade") 2>&1 } catch {}
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Could not find or install pip. Please install pip manually."
        Read-HostSafe "  Press Enter to exit"
        exit 1
    }
}
Write-Ok "pip is available"

# -- 4. Check / install required packages --------------------------------------
$allOk   = $true
$pkgVers = @{}
foreach ($pkg in $REQUIRED_PACKAGES) {
    Write-Step "Checking $pkg ..."
    if (Test-PythonPackage $PythonCmd $pkg) {
        $pkgVer = Invoke-Python $PythonCmd @("-m", "pip", "show", $pkg) 2>&1 |
                  Select-String "^Version:" |
                  ForEach-Object { $_ -replace "Version: ", "" }
        $pkgVers[$pkg] = "$pkgVer".Trim()
        Write-Ok "$pkg $($pkgVers[$pkg])"
    } else {
        Write-Warn "$pkg not found -- installing ..."
        if (Install-PythonPackage $PythonCmd $pkg) {
            $pkgVers[$pkg] = ""
            Write-Ok "$pkg installed"
        } else {
            Write-Fail "Failed to install $pkg"
            Write-Info "Try manually: $PythonCmd -m pip install $pkg"
            $allOk = $false
        }
    }
}

if (-not $allOk) {
    Write-Host ""
    Write-Fail "One or more dependencies could not be installed."
    Read-HostSafe "  Press Enter to exit"
    exit 1
}

# -- 5. Check Node.js + Claude CLI (optional -- Claude (Subscription) engine) --
Write-Step "Checking Node.js (optional, for Claude Subscription engine) ..."
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
    Write-Step "Checking Claude CLI ..."
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
    }
} else {
    Write-Warn "Node.js unavailable -- Claude (Subscription) engine will not work."
    Write-Info "Install manually: winget install OpenJS.NodeJS.LTS"
}

# -- Write cache so next launch skips all the above ---------------------------
Write-LaunchCache $PythonCmd $verStr $pkgVers["PySide6"]

# -- Launch --------------------------------------------------------------------
Write-Ok "All checks passed -- starting JSON Translation Editor ..."
Show-RunningBox

$launchOk = $false
$appExitCode = 1
try {
    Invoke-Python $PythonCmd (@($AppPath) + @($appArgs))
    $launchOk = ($LASTEXITCODE -eq 0)
    $appExitCode = $LASTEXITCODE
} catch {
    Write-Fail "Failed to launch: $_"
    Remove-LaunchCache
    Read-HostSafe "  Press Enter to exit"
    exit 1
}

if (-not $launchOk) {
    Remove-LaunchCache
    Write-Fail "JSON Translation Editor exited with an error (code $appExitCode)."
    Read-HostSafe "  Press Enter to exit"
}
exit $appExitCode
