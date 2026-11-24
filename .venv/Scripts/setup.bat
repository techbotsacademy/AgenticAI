
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

REM Get Python 3.11 installation path
for /f "delims=" %%I in ('py -3.11 -c "import sys; print(sys.base_prefix)"') do set "PYTHON_HOME=%%I"

set "PYTHON_EXE=%PYTHON_HOME%\python.exe"

REM Create virtual environment if it doesn't exist
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3.11 -m venv .venv
)

REM Generate pyvenv.cfg
echo Creating pyvenv.cfg...

(
    echo home = %PYTHON_HOME%
    echo include-system-site-packages = false
    echo version = 3.11.9
    echo executable = %PYTHON_EXE%
    echo command = %PYTHON_EXE% -m venv .\.venv
) > .venv\pyvenv.cfg

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Environment setup completed!
pause
