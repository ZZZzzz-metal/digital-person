@echo off
chcp 65001 >nul
title 停止数字人服务
cd /d "%~dp0"

echo 正在停止数字人相关的前端与后端服务...
taskkill /FI "WINDOWTITLE eq 数字人后端*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq 数字人前端*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq DigitalPerson-Backend*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq DigitalPerson-Frontend*" /T /F >nul 2>nul

rem 兜底杀死占用 8080 与 5175 的非主系统进程（仅若存在）
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8080.*LISTENING"') do (
    taskkill /PID %%a /F >nul 2>nul
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5175.*LISTENING"') do (
    taskkill /PID %%a /F >nul 2>nul
)

echo [完成] 所有数字人服务已停止。
timeout /t 2 /nobreak >nul
exit /b 0
