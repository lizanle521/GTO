@echo off
REM ============================================================
REM  GTO Helper - Install desktop debug dependencies
REM
REM  This installs only what is needed to run the app on Windows
REM  for development and testing.
REM
REM  NOTE: This does NOT build the Android APK. Buildozer cannot
REM  run on Windows. See the packaging guide for APK builds.
REM
REM  IMPORTANT: This file must stay pure ASCII with CRLF line
REM  endings. cmd.exe reads .bat files as GBK on Chinese Windows,
REM  so UTF-8 Chinese text would be mangled into garbage and split
REM  commands in half. LF-only line endings also break cmd.exe.
REM  If you edit this file, re-save it as ASCII with CRLF.
REM ============================================================

setlocal

set PYTHON=C://Users//admin//.workbuddy//binaries//python//envs//default//Scripts//python.exe
set PROJECT_DIR=%~dp0

if not exist "%PYTHON%" (
    echo [ERROR] Python virtual environment not found:
    echo     %PYTHON%
    echo.
    echo Create it first with:
    echo   C://Users//admin//.workbuddy//binaries//python//versions//3.13.12//python.exe -m venv C://Users//admin//.workbuddy//binaries//python//envs//default
    echo.
    pause
    exit /b 1
)

echo ============================================================
echo   Installing desktop debug dependencies
echo ============================================================
echo.

echo [1/2] Upgrading pip...
"%PYTHON%" -m pip install --upgrade pip --quiet

REM About the version pins below:
REM   kivy==2.3.1 requires pillow<11 (declared in its "base" extra).
REM   Pinning pillow<11 explicitly stops pip from flip-flopping
REM   between versions on every run. Pillow 10.x is fully sufficient
REM   here - the app only uses it for base64 encoding and resizing.
REM   numpy is unpinned; any recent version works.
echo.
echo [2/2] Installing Kivy, Pillow, numpy...
"%PYTHON%" -m pip install "kivy==2.3.1" "pillow>=10,<11" numpy

if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed.
    echo If the network is slow, try a mirror:
    echo   "%PYTHON%" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple "kivy==2.3.1" "pillow>=10,<11" numpy
    echo.
    pause
    exit /b 1
)

echo.
echo Verifying installation...
"%PYTHON%" -c "import kivy, PIL, numpy; print('Kivy', kivy.__version__); print('Pillow', PIL.__version__); print('numpy', numpy.__version__)"

if errorlevel 1 (
    echo.
    echo [ERROR] Verification failed - some packages could not be imported.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Done. Run start_debug.bat to launch the app.
echo ============================================================
echo.
pause

endlocal
