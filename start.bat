@echo off
title Digital-Person Starter
cd /d "%~dp0"

echo ==============================================================
echo        Digital-Person (Companion Student) Launcher
echo ==============================================================
echo.
echo [*] Checking Python and Node.js environment...

set "PY_CMD="
if exist ".venv\Scripts\python.exe" (
    set "PY_CMD=.venv\Scripts\python.exe"
) else (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY_CMD=py -3.12"
    ) else (
        where python >nul 2>nul
        if %errorlevel% equ 0 (
            set "PY_CMD=python"
        )
    )
)

if "%PY_CMD%"=="" (
    echo [ERROR] Python not found. Please install Python 3.12.
    pause
    exit /b 1
)

where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] npm not found. Please install Node.js.
    pause
    exit /b 1
)

if not exist "apps\web\node_modules" (
    echo [*] Installing frontend dependencies (npm install)...
    cd apps\web
    call npm install
    cd /d "%~dp0"
)

set BACKEND_PORT=8080
set FRONTEND_PORT=5175

echo.
echo [*] Launching Backend on http://127.0.0.1:%BACKEND_PORT% ...
start "DigitalPerson-Backend" cmd /k "title DigitalPerson-Backend [8080] && cd /d "%~dp0" && set PYTHONPATH=src&& set B2_MODE=stub&& %PY_CMD% -m uvicorn server.app:app --host 127.0.0.1 --port %BACKEND_PORT%"

echo [*] Launching Frontend on http://127.0.0.1:%FRONTEND_PORT% ...
start "DigitalPerson-Frontend" cmd /k "title DigitalPerson-Frontend [5175] && cd /d "%~dp0apps\web" && set VITE_BACKEND_URL=http://127.0.0.1:%BACKEND_PORT%&& npm run dev -- --port %FRONTEND_PORT% --host 127.0.0.1"

echo [*] Opening browser in 3 seconds...
timeout /t 3 /nobreak >nul
start http://127.0.0.1:%FRONTEND_PORT%

echo.
echo ==============================================================
echo  Digital-Person services are now running!
echo.
echo  - Frontend Web UI : http://127.0.0.1:%FRONTEND_PORT%
echo  - Backend API     : http://127.0.0.1:%BACKEND_PORT%
echo.
echo  Press any key to stop all services and exit.
echo ==============================================================
echo.
pause >nul

echo [*] Stopping services...
taskkill /FI "WINDOWTITLE eq DigitalPerson-Backend*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq DigitalPerson-Frontend*" /T /F >nul 2>nul
echo Done.
exit /b 0