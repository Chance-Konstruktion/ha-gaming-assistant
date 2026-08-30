# ================================================================
#  Build GamingAssistant.exe (single file, no Python required)
#
#  Run this on a Windows machine with Python installed:
#    powershell -ExecutionPolicy Bypass -File build_exe.ps1
#
#  Output: dist/GamingAssistant.exe
# ================================================================

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Building Gaming Assistant .exe" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "[ERROR] Python not found!" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] $(python --version)" -ForegroundColor Green

# Install build dependencies
Write-Host "[SETUP] Installing build dependencies..." -ForegroundColor Yellow
pip install pyinstaller mss Pillow paho-mqtt pywin32 --quiet 2>$null

# Build
Write-Host "[BUILD] Creating single-file .exe ..." -ForegroundColor Yellow
Write-Host ""

pyinstaller `
    --onefile `
    --windowed `
    --name GamingAssistant `
    --hidden-import win32gui `
    --hidden-import win32con `
    --hidden-import pywintypes `
    --hidden-import mss `
    --hidden-import PIL `
    --hidden-import paho.mqtt.client `
    gaming_assistant_gui.py

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Build failed!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

$ExePath = Join-Path $ScriptDir "dist\GamingAssistant.exe"
$SizeMB = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  Build complete!" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Output: $ExePath" -ForegroundColor White
Write-Host "  Size:   $SizeMB MB" -ForegroundColor White
Write-Host ""
Write-Host "  Just copy GamingAssistant.exe to any Windows PC and run it." -ForegroundColor Cyan
Write-Host "  No Python, no installation needed!" -ForegroundColor Cyan
Write-Host ""

Read-Host "Press Enter to exit"
