
@echo off
echo Setting up Python environment...

REM Find Python 3.11
py -3.11 --version >nul 2>&1

if errorlevel 1 (
    echo Python 3.11 is not installed.
    echo Please install Python 3.11 first.
    pause
    exit /b 1
)

REM Create virtual environment if it doesn't exist
if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv .venv
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Environment setup completed!
pause
