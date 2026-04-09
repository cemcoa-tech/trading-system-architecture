@echo off
echo ========================================
echo Trading Framework Setup
echo ========================================
echo Setting up at: %date% %time%
echo.

REM Create deployment directory if it doesn't exist
if not exist "C:\TradingFramework" (
    echo Creating deployment directory...
    mkdir C:\TradingFramework
)

cd /d C:\TradingFramework

REM Check Python installation
echo Checking Python installation...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python not found!
    echo Please install Python 3.8+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

python --version

REM Create virtual environment
echo.
echo Creating Python virtual environment...
if exist "venv" (
    echo Virtual environment already exists, skipping creation.
) else (
    python -m venv venv
    if %ERRORLEVEL% NEQ 0 (
        echo ERROR: Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo Virtual environment created successfully.
)

REM Activate virtual environment
echo.
echo Activating virtual environment...
call venv\Scripts\activate

REM Upgrade pip
echo.
echo Upgrading pip...
python -m pip install --upgrade pip

REM Install required packages
echo.
echo Installing required packages...
pip install pandas ib_insync

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to install required packages!
    pause
    exit /b 1
)

REM Create necessary directories
echo.
echo Creating necessary directories...
if not exist "data" mkdir data
if not exist "logs" mkdir logs

echo.
echo ========================================
echo Setup completed successfully!
echo ========================================
echo.
echo Next steps:
echo 1. Copy trading framework code to this directory
echo 2. Install and configure IB Gateway
echo 3. Run test_connection.bat to verify setup
echo 4. Set up Windows Task Scheduler
echo.
echo Press any key to exit...
pause > nul
