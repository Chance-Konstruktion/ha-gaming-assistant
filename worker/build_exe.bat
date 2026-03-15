@echo off
REM ================================================================
REM  Build GamingAssistant.exe (single file, no Python required)
REM
REM  Prerequisites (on your dev machine):
REM    pip install pyinstaller mss Pillow paho-mqtt pywin32
REM
REM  Output: dist/GamingAssistant.exe
REM ================================================================

setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo ================================================================
echo   Building Gaming Assistant .exe
echo ================================================================
echo.

REM Check PyInstaller
where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [SETUP] Installing PyInstaller...
    pip install pyinstaller
)

echo [BUILD] Creating single-file .exe ...
echo.

pyinstaller ^
    --onefile ^
    --windowed ^
    --name GamingAssistant ^
    --icon NONE ^
    --add-data "capture_agent.py;." ^
    --hidden-import win32gui ^
    --hidden-import win32con ^
    --hidden-import pywintypes ^
    --hidden-import mss ^
    --hidden-import PIL ^
    --hidden-import paho.mqtt.client ^
    gaming_assistant_gui.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo ================================================================
echo   Build complete!
echo ================================================================
echo.
echo   Output: %SCRIPT_DIR%dist\GamingAssistant.exe
echo.
echo   This single .exe contains everything:
echo   - Python runtime
echo   - Screenshot capture (mss)
echo   - Image processing (Pillow)
echo   - MQTT client (paho-mqtt)
echo   - Game detection (pywin32)
echo   - GUI (tkinter)
echo.
echo   Just copy GamingAssistant.exe to any Windows PC and run it.
echo   No installation needed!
echo.

pause
endlocal
