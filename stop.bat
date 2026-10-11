@echo off
title Stop Digital-Person
cd /d "%~dp0"

echo [*] Stopping Digital-Person services...
taskkill /FI "WINDOWTITLE eq DigitalPerson-Backend*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq DigitalPerson-Frontend*" /T /F >nul 2>nul

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8080.*LISTENING"') do (
    taskkill /PID %%a /F >nul 2>nul
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5175.*LISTENING"') do (
    taskkill /PID %%a /F >nul 2>nul
)

echo [OK] All services stopped.
timeout /t 2 /nobreak >nul
exit /b 0