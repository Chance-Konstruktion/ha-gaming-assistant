@echo off
REM ================================================================
REM  Gaming Assistant - Capture Agent for Windows
REM  Captures screenshots and sends them to Home Assistant via MQTT
REM ================================================================

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%venv"
set "PYTHON_SCRIPT=%SCRIPT_DIR%capture_agent.py"
set "REQUIREMENTS=%SCRIPT_DIR%requirements-capture.txt"

REM ---- Find a working Python interpreter ----
set "PYTHON="

REM 1. Try py launcher (most reliable on Windows)
where py >nul 2>&1
if not errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=py -3"
        goto :python_found
    )
)

REM 2. Try python3
where python3 >nul 2>&1
if not errorlevel 1 (
    python3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=python3"
        goto :python_found
    )
)

REM 3. Try python (but verify it's real, not the Windows Store alias)
where python >nul 2>&1
if not errorlevel 1 (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=python"
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

REM ---- Create virtual environment if needed ----
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [SETUP] Creating virtual environment...
    %PYTHON% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        echo [HINT] Try: %PYTHON% -m pip install --user virtualenv
        pause
        exit /b 1
    )

    echo [SETUP] Installing dependencies...
    call "%VENV_DIR%\Scripts\activate.bat"
    pip install -r "%REQUIREMENTS%" pywin32 2>nul
    if errorlevel 1 (
        echo [WARN] Some packages may have failed. Trying core packages only...
        pip install mss Pillow paho-mqtt requests
    )
    echo [SETUP] Installation complete.
    echo.
) else (
    call "%VENV_DIR%\Scripts\activate.bat"
)

REM ---- Configuration ----
REM Edit these values or pass them as command line arguments

if "%~1"=="" (
    echo ================================================================
    echo   Gaming Assistant - Capture Agent
    echo ================================================================
    echo.
    echo Usage:
    echo   gaming_assistant.bat BROKER_IP [OPTIONS]
    echo.
    echo Examples:
    echo   gaming_assistant.bat 192.168.1.10
    echo   gaming_assistant.bat 192.168.1.10 --interval 10 --quality 80
    echo   gaming_assistant.bat 192.168.1.10 --game-hint "Elden Ring"
    echo   gaming_assistant.bat 192.168.1.10 --detect-change --resize 1280x720
    echo.
    echo Options:
    echo   --interval N      Seconds between captures (default: 5^)
    echo   --quality N       JPEG quality 1-100 (default: 75^)
    echo   --resize WxH      Image size (default: 960x540^)
    echo   --monitor N       Monitor index, 1=primary (default: 1^)
    echo   --game-hint NAME  Manual game name hint
    echo   --detect-change   Skip unchanged frames
    echo   --client-id ID    Unique client ID (default: hostname^)
    echo   --port N          MQTT port (default: 1883^)
    echo   --user NAME       MQTT username
    echo   --password PASS   MQTT password
    echo.
    set /p "BROKER=Enter your Home Assistant MQTT Broker IP: "
    if "!BROKER!"=="" (
        echo [ERROR] No broker IP provided.
        pause
        exit /b 1
    )
    echo.
    echo Starting capture agent...
    echo Press Ctrl+C to stop.
    echo.
    python "%PYTHON_SCRIPT%" --broker !BROKER!
) else (
    echo [START] Gaming Assistant Capture Agent
    echo [START] Broker: %~1
    echo.
    python "%PYTHON_SCRIPT%" %*
)

REM ---- Cleanup ----
if errorlevel 1 (
    echo.
    echo [ERROR] Capture agent exited with an error.
    pause
)

endlocal
