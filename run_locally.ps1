# Ensure execution policy is set or warn user
Write-Host "=======================================================================" -ForegroundColor Cyan
Write-Host "        Starting Agentic File Management System Local Setup (PowerShell)" -ForegroundColor Cyan
Write-Host "=======================================================================" -ForegroundColor Cyan

# Set working directory to the directory of this script
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($ScriptDir) {
    Set-Location $ScriptDir
}

# Check for Python
$PythonCmd = "python"
try {
    & python --version | Out-Null
} catch {
    try {
        & py --version | Out-Null
        $PythonCmd = "py"
    } catch {
        Write-Error "Python is not installed or not in your PATH. Please install Python from https://www.python.org/downloads/"
        Read-Host "Press Enter to exit..."
        exit 1
    }
}

Write-Host "[INFO] Using Python command: $PythonCmd" -ForegroundColor Green

# Check for virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host "[INFO] Creating virtual environment (.venv)..." -ForegroundColor Yellow
    & $PythonCmd -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create virtual environment."
        Read-Host "Press Enter to exit..."
        exit 1
    }
} else {
    Write-Host "[INFO] Virtual environment (.venv) already exists." -ForegroundColor Green
}

# Activate virtual environment
Write-Host "[INFO] Activating virtual environment..." -ForegroundColor Yellow
.venv\Scripts\Activate.ps1

# Install requirements
Write-Host "[INFO] Installing / updating required dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install dependencies."
    Read-Host "Press Enter to exit..."
    exit 1
}

# Start the Streamlit application
Write-Host "[INFO] Starting Streamlit application..." -ForegroundColor Green
Write-Host "[INFO] Log in using the password: admin" -ForegroundColor Cyan
streamlit run app.py
