@echo off
chcp 65001 >nul
title 安装依赖

set PYTHON=C:\Users\admin\.workbuddy\binaries\python\versions\3.13.12\python.exe
set VENV=C:\Users\admin\.workbuddy\binaries\python\envs\default

echo [1/2] 创建虚拟环境...
if not exist "%VENV%\Scripts\python.exe" (
    "%PYTHON%" -m venv "%VENV%"
)

echo [2/2] 安装依赖包...
"%VENV%\Scripts\pip.exe" install PyQt6 mss pillow -i https://mirrors.tencent.com/pypi/simple/

echo.
echo 安装完成！双击「启动.bat」即可运行。
pause
