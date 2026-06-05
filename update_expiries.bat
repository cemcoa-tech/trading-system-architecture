@echo off
REM update_expiries.bat
REM Batch file to run expiry updater via Windows Task Scheduler
REM Schedule this to run 1 hour before main trading systems

setlocal enabledelayedexpansion

REM Set working directory to script location
cd /d "%~dp0"

REM Log file with timestamp
set LOG_FILE=expiry_update_%date:~-4,4%%date:~-10,2%%date:~-7,2%_%time:~0,2%%time:~3,2%%time:~6,2%.log
set LOG_FILE=%LOG_FILE: =0%

echo ======================================== >> %LOG_FILE%
echo Starting expiry update at %date% %time% >> %LOG_FILE%
echo ======================================== >> %LOG_FILE%

REM Run the Python script
REM Use --dry-run for testing, remove for production
python update_strategy_expiries.py --dry-run >> %LOG_FILE% 2>&1

REM Check exit code
if %ERRORLEVEL% EQU 0 (
    echo SUCCESS: Expiry update completed at %date% %time% >> %LOG_FILE%
) else (
    echo ERROR: Expiry update failed with exit code %ERRORLEVEL% at %date% %time% >> %LOG_FILE%
)

echo ======================================== >> %LOG_FILE%
echo Finished at %date% %time% >> %LOG_FILE%
echo ======================================== >> %LOG_FILE%

REM Display last 20 lines of log
echo.
echo Last 20 lines of log:
echo =====================
powershell -Command "Get-Content '%LOG_FILE%' | Select-Object -Last 20"

pause
