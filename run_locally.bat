@echo off
setlocal enabledelayedexpansion

echo =======================================================================
echo        Starting Agentic File Management System Local Setup
echo =======================================================================

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python is not installed or not added to your PATH environment variable.
        echo Please download and install Python from https://www.python.org/downloads/
        pause
        exit /b 1
    ) else (
        set PYTHON_CMD=py
    )
) else (
    set PYTHON_CMD=python
)

echo [INFO] Found Python using command: !PYTHON_CMD!

:: Navigate to project directory (where this script is located)
cd /d "%~dp0"

:: Check if virtual environment directory exists
if not exist .venv (
    echo [INFO] Creating virtual environment (.venv)...
    !PYTHON_CMD! -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [INFO] Virtual environment created successfully.
) else (
    echo [INFO] Virtual environment (.venv) already exists.
)

:: Activate the virtual environment and run the application
echo [INFO] Activating virtual environment and updating dependencies...
call .venv\Scripts\activate.bat

echo [INFO] Installing / updating required dependencies from requirements.txt...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo [INFO] Starting Streamlit application...
echo [INFO] Log in using the password: admin
streamlit run app.py

pause
