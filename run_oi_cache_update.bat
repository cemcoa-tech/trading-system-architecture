@echo off
REM run_oi_cache_update.bat
REM ─────────────────────────────────────────────────────────────────────────
REM Wrapper to run OI cache update with proper Python environment
REM ─────────────────────────────────────────────────────────────────────────

cd /d "C:\Users\USER\Desktop\trading-system-architecture"

C:\Users\USER\anaconda3\python.exe run_oi_cache_update.py %*

if %ERRORLEVEL% neq 0 (
    echo ERROR: OI cache update failed with code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

echo OI cache update completed successfully
