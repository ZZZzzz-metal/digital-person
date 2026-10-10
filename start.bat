@echo off
title Digital-Person Launcher
cd /d "%~dp0"

echo ==============================================================
echo        Digital-Person (Companion Student) Launcher
echo ==============================================================
echo.

rem Check npm
where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm is not found. Please install Node.js!
    goto on_error
)

rem Check Python
set PY_CMD=
if exist ".venv\Scripts\python.exe" (
    set "PY_CMD=.venv\Scripts\python.exe"
    goto found_py
)

py -3.12 --version >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=py -3.12"
    goto found_py
)

python --version >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=python"
    goto found_py
)

echo [ERROR] Python 3.12 is not found. Please install Python!
goto on_error

:found_py
echo [*] Python detected: %PY_CMD%
echo [*] Checking frontend dependencies...

if not exist "apps\web\node_modules" (
    echo [*] Running npm install in apps\web...
    pushd apps\web
    call npm install
    popd
)

set BACKEND_PORT=8080
set FRONTEND_PORT=5175

echo.
echo [*] Starting Backend on http://127.0.0.1:%BACKEND_PORT% ...
start "DigitalPerson-Backend" cmd /k "cd /d "%~dp0" && set PYTHONPATH=src && set B2_MODE=stub && %PY_CMD% -m uvicorn server.app:app --host 127.0.0.1 --port %BACKEND_PORT%"

echo [*] Starting Frontend on http://127.0.0.1:%FRONTEND_PORT% ...
start "DigitalPerson-Frontend" cmd /k "cd /d "%~dp0apps\web" && set VITE_BACKEND_URL=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT% --host 127.0.0.1"

echo [*] Opening browser in 3 seconds...
ping 127.0.0.1 -n 4 >nul
start http://127.0.0.1:%FRONTEND_PORT%

echo.
echo ==============================================================
echo  Digital-Person services are running!
echo.
echo  - Frontend Web UI : http://127.0.0.1:%FRONTEND_PORT%
echo  - Backend API     : http://127.0.0.1:%BACKEND_PORT%
echo.
echo  Press any key in this window to stop all services and exit.
echo ==============================================================
echo.
pause >nul

echo [*] Stopping services...
taskkill /FI "WINDOWTITLE eq DigitalPerson-Backend*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq DigitalPerson-Frontend*" /T /F >nul 2>nul
exit /b 0

:on_error
echo.
echo Press any key to exit...
pause >nul
exit /b 1