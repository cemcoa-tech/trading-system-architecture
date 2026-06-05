@echo off
REM run_mes_xgboost_strategy.bat
REM Batch file to run MES XGBoost Ensemble Strategy

echo ========================================
echo MES XGBoost Ensemble Strategy Runner
echo ========================================
echo.

REM Activate virtual environment if it exists
if exist venv\Scripts\activate.bat (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo No virtual environment found, using system Python
)

echo.
echo Running MES XGBoost Ensemble Strategy...
echo.

python run_mes_xgboost.py >> mes_xgboost_strategy_log.txt 2>&1

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo Strategy execution completed successfully
    echo ========================================
) else (
    echo.
    echo ========================================
    echo Strategy execution failed with error code %ERRORLEVEL%
    echo Check mes_xgboost_strategy_log.txt for details
    echo ========================================
)

echo.
pause
