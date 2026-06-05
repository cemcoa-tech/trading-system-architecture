@echo off
REM update_expiries_production.bat
REM Production batch file for Windows Task Scheduler
REM Schedule this to run 1 hour before main trading systems

setlocal enabledelayedexpansion

REM Set working directory to script location
cd /d "%~dp0"

REM Create log directory if it doesn't exist
if not exist "logs" mkdir logs

REM Log file with timestamp
set LOG_FILE=logs\expiry_update_%date:~-4,4%%date:~-10,2%%date:~-7,2%_%time:~0,2%%time:~3,2%%time:~6,2%.log
set LOG_FILE=%LOG_FILE: =0%

echo ======================================== >> "%LOG_FILE%"
echo Starting expiry update at %date% %time% >> "%LOG_FILE%"
echo Working directory: %CD% >> "%LOG_FILE%"
echo ======================================== >> "%LOG_FILE%"

REM Check if IBKR Gateway/TWS is running
tasklist /FI "IMAGENAME eq ibgateway.exe" 2>NUL | find /I "ibgateway.exe" >NUL
if %ERRORLEVEL% NEQ 0 (
    tasklist /FI "IMAGENAME eq tws.exe" 2>NUL | find /I "tws.exe" >NUL
    if %ERRORLEVEL% NEQ 0 (
        echo ERROR: IBKR Gateway/TWS not running at %date% %time% >> "%LOG_FILE%"
        echo ERROR: IBKR Gateway/TWS not running. Please start IBKR before running expiry updater.
        echo ======================================== >> "%LOG_FILE%"
        echo Finished with ERROR at %date% %time% >> "%LOG_FILE%"
        echo ======================================== >> "%LOG_FILE%"
        exit /b 1
    )
)

echo IBKR connection verified >> "%LOG_FILE%"

REM Run the Python script (production mode - no --dry-run)
python update_strategy_expiries_v2.py >> "%LOG_FILE%" 2>&1

REM Check exit code
if %ERRORLEVEL% EQU 0 (
    echo SUCCESS: Expiry update completed at %date% %time% >> "%LOG_FILE%"
    
    REM Clean up old log files (keep last 7 days)
    forfiles /P logs /M expiry_update_*.log /D -7 /C "cmd /c echo Deleting @file >> @path\..\cleanup.log & del @file" 2>NUL
    
    set EXIT_CODE=0
) else (
    echo ERROR: Expiry update failed with exit code %ERRORLEVEL% at %date% %time% >> "%LOG_FILE%"
    set EXIT_CODE=1
)

echo ======================================== >> "%LOG_FILE%"
echo Finished at %date% %time% >> "%LOG_FILE%"
echo Exit code: %EXIT_CODE% >> "%LOG_FILE%"
echo ======================================== >> "%LOG_FILE%"

REM Display last 20 lines of log for immediate feedback
echo.
echo Last 20 lines of log:
echo =====================
powershell -Command "Get-Content '%LOG_FILE%' | Select-Object -Last 20"

REM Exit with appropriate code
exit /b %EXIT_CODE%
