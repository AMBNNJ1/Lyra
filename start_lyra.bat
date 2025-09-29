@echo off
echo.
echo ================================
echo   Lyra Web Server Startup
echo ================================
echo.
cd /d "%~dp0"
echo [1/3] Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment!
    pause
    exit /b 1
)
echo [2/3] Checking .env file...
if not exist .env (
    echo WARNING: .env file not found!
)
echo [3/3] Starting Flask server on http://localhost:7860
echo.
echo Press Ctrl+C to stop the server
echo.
python web\server.py
echo.
echo Server stopped.
pause
