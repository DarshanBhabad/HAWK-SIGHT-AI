@echo off
echo ===================================================
echo             STARTING HAWK SIGHT AI
echo ===================================================

REM %~dp0 = the folder this start.bat lives in (project root), with a trailing backslash.
REM Using it makes the script work no matter what folder you launch it from.

echo [1/3] Starting Backend Server (port 5000)...
REM Must run FROM the backend folder so:
REM   - the virtual environment (backend\venv) activates correctly, and
REM   - load_dotenv() finds backend\.env (secrets, MySQL, API keys).
start "Hawk Sight AI - Backend" cmd /k "cd /d "%~dp0backend" && call venv\Scripts\activate && python server.py"

echo [2/3] Starting Frontend Server (port 8080)...
start "Hawk Sight AI - Frontend" cmd /k "cd /d "%~dp0frontend" && python -m http.server 8080"

echo [3/3] Waiting for servers to initialize...
timeout /t 4 /nobreak > nul

echo Opening Dashboard in your default browser...
start http://localhost:8080

echo.
echo All systems go! You can safely close this small black window.
echo To stop the servers later, just close the two popup windows.
pause
