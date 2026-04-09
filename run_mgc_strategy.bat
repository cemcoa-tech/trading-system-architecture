@echo off
echo ========================================
echo MGC Pullback Strategy Execution
echo ========================================
echo Starting at: %date% %time%
echo.

REM Change to trading framework directory
cd /d C:\TradingFramework

REM Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found!
    echo Please run setup instructions first.
    pause
    exit /b 1
)

REM Activate virtual environment
echo Activating Python virtual environment...
call venv\Scripts\activate

REM Check if main.py exists
if not exist "main.py" (
    echo ERROR: main.py not found!
    echo Please ensure trading framework is properly deployed.
    pause
    exit /b 1
)

REM Run the MGC strategy
echo.
echo Running MGC Pullback Strategy...
echo ========================================
python main.py --strategy mgc

REM Check execution result
if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo Strategy completed successfully!
    echo Completed at: %date% %time%
    echo ========================================
) else (
    echo.
    echo ========================================
    echo Strategy failed with error code: %ERRORLEVEL%
    echo Completed at: %date% %time%
    echo Check logs for details.
    echo ========================================
)

echo.
echo Press any key to exit...
pause > nul
