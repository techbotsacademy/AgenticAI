
@echo off
title AgenticAI Startup

cd /d "%~dp0"

echo ==================================
echo       AGENTIC AI STARTUP
echo ==================================

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found!
    echo Please create it using:
    echo python -m venv .venv
    pause
    exit /b 1
)

echo.
echo [1/3] Checking Python environment...

".venv\Scripts\python.exe" --version

echo.
echo [2/3] Installing required packages...

".venv\Scripts\python.exe" -m pip install -r requirements.txt

if errorlevel 1 (
    echo Package installation failed!
    pause
    exit /b 1
)

echo.
echo [3/3] Starting AgenticAI...

".venv\Scripts\python.exe" app.py

pause
