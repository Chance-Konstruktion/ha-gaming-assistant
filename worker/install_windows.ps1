# ================================================================
#  Gaming Assistant - Windows Installer (PowerShell)
#  One-click setup: Python venv, dependencies, desktop shortcut
# ================================================================

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ScriptDir "venv"
$RequirementsFile = Join-Path $ScriptDir "requirements-capture.txt"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Gaming Assistant - Windows Installer" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# ---- Check Python ----
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "[ERROR] Python not found!" -ForegroundColor Red
    Write-Host "Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "Make sure to check 'Add Python to PATH' during installation." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

$pyVersion = & python --version 2>&1
Write-Host "[OK] Found $pyVersion" -ForegroundColor Green

# ---- Create virtual environment ----
if (-not (Test-Path (Join-Path $VenvDir "Scripts\activate.ps1"))) {
    Write-Host "[SETUP] Creating virtual environment..." -ForegroundColor Yellow
    & python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# ---- Activate and install ----
& "$VenvDir\Scripts\activate.ps1"

Write-Host "[SETUP] Installing dependencies..." -ForegroundColor Yellow
& pip install -r $RequirementsFile --quiet 2>$null

Write-Host "[SETUP] Installing pywin32 for game detection..." -ForegroundColor Yellow
& pip install pywin32 --quiet 2>$null

# ---- Ask for broker IP ----
Write-Host ""
$BrokerIP = Read-Host "Enter your Home Assistant MQTT Broker IP (e.g. 192.168.1.10)"
if ([string]::IsNullOrWhiteSpace($BrokerIP)) {
    Write-Host "[ERROR] No broker IP provided" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# ---- Create start script ----
$StartScript = Join-Path $ScriptDir "START_Gaming_Assistant.bat"
$StartContent = @"
@echo off
cd /d "$ScriptDir"
call "venv\Scripts\activate.bat"
echo Starting Gaming Assistant Capture Agent...
echo Broker: $BrokerIP
echo Press Ctrl+C to stop.
echo.
python capture_agent.py --broker $BrokerIP --detect-change
pause
"@
Set-Content -Path $StartScript -Value $StartContent -Encoding ASCII

Write-Host ""
Write-Host "[OK] Start script created: $StartScript" -ForegroundColor Green

# ---- Create desktop shortcut ----
$CreateShortcut = Read-Host "Create desktop shortcut? (y/n)"
if ($CreateShortcut -eq "y") {
    $DesktopPath = [Environment]::GetFolderPath("Desktop")
    $ShortcutPath = Join-Path $DesktopPath "Gaming Assistant.lnk"

    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $StartScript
    $Shortcut.WorkingDirectory = $ScriptDir
    $Shortcut.Description = "Gaming Assistant - Screenshot Capture Agent"
    $Shortcut.Save()

    Write-Host "[OK] Desktop shortcut created!" -ForegroundColor Green
}

# ---- Done ----
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start the agent:" -ForegroundColor Cyan
Write-Host "  Option 1: Double-click 'START_Gaming_Assistant.bat'" -ForegroundColor White
Write-Host "  Option 2: Run 'gaming_assistant.bat $BrokerIP'" -ForegroundColor White
Write-Host "  Option 3: python capture_agent.py --broker $BrokerIP" -ForegroundColor White
Write-Host ""
Write-Host "Advanced options:" -ForegroundColor Cyan
Write-Host "  --interval 10        Capture every 10 seconds" -ForegroundColor White
Write-Host "  --quality 85         Higher JPEG quality" -ForegroundColor White
Write-Host "  --game-hint 'Name'   Set game name manually" -ForegroundColor White
Write-Host "  --detect-change      Skip unchanged frames" -ForegroundColor White
Write-Host ""

# ---- Test run ----
$TestRun = Read-Host "Start the agent now? (y/n)"
if ($TestRun -eq "y") {
    Write-Host ""
    Write-Host "Starting capture agent... Press Ctrl+C to stop." -ForegroundColor Yellow
    & python (Join-Path $ScriptDir "capture_agent.py") --broker $BrokerIP --detect-change
}

Read-Host "Press Enter to exit"
