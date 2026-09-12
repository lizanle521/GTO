@echo off
REM ============================================================
REM  GTO Helper - Start in desktop debug mode
REM
REM  For development and testing on Windows only. The real
REM  deliverable is the Android APK; see the packaging guide.
REM
REM  IMPORTANT: This file must stay pure ASCII with CRLF line
REM  endings. cmd.exe reads .bat files as GBK on Chinese Windows,
REM  so UTF-8 Chinese text would be mangled into garbage and split
REM  commands in half. LF-only line endings also break cmd.exe.
REM ============================================================

setlocal

set PYTHON=C:\Users\admin\.workbuddy\binaries\python\envs\default\Scripts\python.exe
set PROJECT_DIR=%~dp0

if not exist "%PYTHON%" (
    echo [ERROR] Python virtual environment not found:
    echo     %PYTHON%
    echo.
    echo Run install.bat first.
    echo.
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"
set PYTHONPATH=%PROJECT_DIR%

echo ============================================================
echo   GTO Helper - desktop debug mode
echo ============================================================
echo.
echo   Notes:
echo     - Open the Settings tab and enter your API key first.
echo     - Training works WITHOUT an API key (all logic is local).
echo     - Camera recognition requires an API key.
echo.
echo   Press Ctrl+C to quit.
echo ============================================================
echo.

"%PYTHON%" main.py

if errorlevel 1 (
    echo.
    echo [Program exited with error] code: %errorlevel%
    pause
)

endlocal
