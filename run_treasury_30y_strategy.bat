@echo off
echo ========================================
echo Treasury 30-Year End-of-Month Strategy Execution
echo ========================================
echo Starting at: %date% %time%
echo.

REM Change to current directory
cd /d "%~dp0"

REM Run the Treasury 30Y strategy using specific Python path with logging
echo.
echo Running Treasury 30-Year End-of-Month Strategy...
echo ========================================
"C:\Users\USER\anaconda3\python.exe" main.py --strategy zb >> treasury_30y_strategy_log.txt 2>&1

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
