$ErrorActionPreference = "Stop"

Write-Host "Building capture_agent.exe with PyInstaller..."

pyinstaller --clean --onefile --name capture_agent worker/capture_agent.py

Write-Host "Done. Output: dist/capture_agent.exe"
