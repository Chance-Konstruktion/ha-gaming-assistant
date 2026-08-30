@echo off
REM ================================================================
REM  Build GamingAssistant.exe (single file, no Python required)
REM
REM  Prerequisites (on your dev machine):
REM    Python 3.10+ installed
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

REM ---- Find a working Python / pip ----
set "PYTHON="
set "PIP="

REM 1. Try py launcher
where py >nul 2>&1
if not errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=py -3"
        set "PIP=py -3 -m pip"
        goto :python_found
    )
)

REM 2. Try python3
where python3 >nul 2>&1
if not errorlevel 1 (
    python3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=python3"
        set "PIP=python3 -m pip"
        goto :python_found
    )
)

REM 3. Try python
where python >nul 2>&1
if not errorlevel 1 (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=python"
        set "PIP=python -m pip"
        goto :python_found
    )
)

REM 4. Common install paths
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
) do (
    if exist %%P (
        set "PYTHON=%%~P"
        set "PIP=%%~P -m pip"
        goto :python_found
    )
)

echo.
echo [ERROR] Python 3.10+ is not installed or not in PATH.
echo.
echo Please install Python from: https://www.python.org/downloads/
echo IMPORTANT: Check "Add Python to PATH" during installation!
echo.
echo Alternatively, disable the Windows Store app alias:
echo   Settings ^> Apps ^> Advanced app settings ^> App execution aliases
echo   Turn off "python.exe" and "python3.exe"
echo.
pause
exit /b 1

:python_found
echo [OK] Found Python: %PYTHON%
for /f "tokens=*" %%v in ('%PYTHON% --version 2^>^&1') do echo [OK] Version: %%v
echo.

REM ---- Check PyInstaller, install if missing ----
%PYTHON% -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [SETUP] Installing PyInstaller and dependencies...
    %PIP% install pyinstaller mss Pillow paho-mqtt pywin32
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
    echo.
)

echo [BUILD] Creating single-file .exe ...
echo.

%PYTHON% -m PyInstaller ^
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
