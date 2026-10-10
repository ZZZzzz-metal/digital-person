@echo off
chcp 65001 >nul
title 数字人一键启动控制台
cd /d "%~dp0"

echo ==============================================================
echo        “伴学”综合情感陪伴数字人 - 一键启动器
echo ==============================================================
echo.
echo   [1] 启动全栈模式 (FastAPI 后端 + Web 前端) [推荐]
echo   [2] 启动纯前端 Mock 模式 (无需 Python，全本地数据)
echo   [3] 仅停止当前运行的服务
echo.
echo ==============================================================

set "CHOICE=1"
set /p "CHOICE=请输入选项 [默认 1，直接回车启动]: "

if "%CHOICE%"=="3" goto do_stop
if "%CHOICE%"=="2" goto start_mock
goto start_full

:start_full
echo.
echo [1/3] 正在检测运行环境...

rem 查找 Python
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
    echo [错误] 未找到 Python 环境，请先安装 Python 3.12 或创建 .venv！
    echo 提示: 你可以选择选项 [2] 启动纯前端 Mock 模式。
    pause
    exit /b 1
)

rem 查找 npm
where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未找到 npm 命令，请确保已安装 Node.js！
    pause
    exit /b 1
)

rem 检查前端依赖
if not exist "apps\web\node_modules" (
    echo [提示] 首次运行，正在安装前端依赖 (npm install)...
    cd apps\web
    call npm install
    cd ..\..
)

set BACKEND_PORT=8080
set FRONTEND_PORT=5175

echo [2/3] 正在启动后端与前端服务...
echo       - 后端端口: %BACKEND_PORT%
echo       - 前端端口: %FRONTEND_PORT%

rem 启动后端子窗口
start "DigitalPerson-Backend" cmd /k "chcp 65001 >nul && title 数字人后端 [8080] && cd /d "%~dp0" && set PYTHONPATH=src&& set B2_MODE=stub&& %PY_CMD% -m uvicorn server.app:app --host 127.0.0.1 --port %BACKEND_PORT%"

rem 启动前端子窗口
start "DigitalPerson-Frontend" cmd /k "chcp 65001 >nul && title 数字人前端 [5175] && cd /d "%~dp0apps\web" && set VITE_BACKEND_URL=http://127.0.0.1:%BACKEND_PORT%&& npm run dev -- --port %FRONTEND_PORT% --host 127.0.0.1"

echo [3/3] 等待服务初始化并在浏览器中打开页面...
timeout /t 3 /nobreak >nul
start http://127.0.0.1:%FRONTEND_PORT%

goto run_monitor

:start_mock
echo.
echo [1/2] 正在检测 Node.js 环境...
where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未找到 npm 命令，请确保已安装 Node.js！
    pause
    exit /b 1
)

if not exist "apps\web\node_modules" (
    echo [提示] 首次运行，正在安装前端依赖 (npm install)...
    cd apps\web
    call npm install
    cd ..\..
)

set FRONTEND_PORT=5175
echo [2/2] 正在以 Mock 模式启动前端...
start "DigitalPerson-Frontend" cmd /k "chcp 65001 >nul && title 数字人前端-Mock [5175] && cd /d "%~dp0apps\web" && npm run dev:mock -- --port %FRONTEND_PORT% --host 127.0.0.1"

timeout /t 3 /nobreak >nul
start http://127.0.0.1:%FRONTEND_PORT%
goto run_monitor

:run_monitor
echo.
echo ==============================================================
echo  “伴学”数字人服务正在运行中！
echo.
echo  - 前端界面: http://127.0.0.1:%FRONTEND_PORT%
echo  - 访问页面即可开始对话、测试表情与管理记忆。
echo.
echo  【退出说明】
echo   随时按任意键即可一键关闭全部后端与前端服务。
echo ==============================================================
echo.
pause >nul

:do_stop
echo.
echo 正在停止服务进程...
taskkill /FI "WINDOWTITLE eq 数字人后端*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq 数字人前端*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq DigitalPerson-Backend*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq DigitalPerson-Frontend*" /T /F >nul 2>nul
echo 服务已全部停止。
timeout /t 2 /nobreak >nul
exit /b 0
