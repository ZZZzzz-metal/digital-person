@echo off
title 伴学数字人 - 纯前端Mock启动
cd /d "%~dp0"

echo ==============================================================
echo      "伴学"综合情感陪伴数字人 - 纯前端Mock模式
echo ==============================================================
echo.
echo [*] 正在检测 Node.js 环境...
where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未找到 npm 命令！请确保已安装 Node.js。
    pause
    exit /b 1
)

if not exist "apps\web\node_modules" (
    echo [*] 首次运行，正在安装前端依赖...
    cd apps\web
    call npm install
    cd /d "%~dp0"
)

set FRONTEND_PORT=5175
echo [*] 正在以 Mock 模式启动前端...
start "数字人前端" cmd /k "title 数字人前端-Mock [5175] && cd /d "%~dp0apps\web" && npm run dev:mock -- --port %FRONTEND_PORT% --host 127.0.0.1"

timeout /t 3 /nobreak >nul
start http://127.0.0.1:%FRONTEND_PORT%

echo.
echo ==============================================================
echo  Mock 模式已启动！
echo  前端界面: http://127.0.0.1:%FRONTEND_PORT%
echo  按任意键退出并关闭服务。
echo ==============================================================
pause >nul

taskkill /FI "WINDOWTITLE eq 数字人前端*" /T /F >nul 2>nul
exit /b 0