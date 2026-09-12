@echo off
chcp 65001 >nul
title 桌面识别 - Desktop Recognizer

set PYTHON=C:\Users\admin\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe

if not exist "%PYTHON%" (
    echo [错误] 未找到 Python 环境：%PYTHON%
    echo 请先运行 install.bat 安装依赖。
    pause
    exit /b 1
)

cd /d "%~dp0"
start "" "%PYTHON%" main.py
