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

REM ---- Check Python installation ----
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Download Python from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

REM ---- Create virtual environment if needed ----
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [SETUP] Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
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
