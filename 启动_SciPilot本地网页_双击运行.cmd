@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "BACKEND_DIR=%PROJECT_ROOT%backend"
set "FRONTEND_DIST=%PROJECT_ROOT%frontend\dist"
set "SERVER_SCRIPT=%PROJECT_ROOT%frontend\提供_SciPilot前端静态网页服务.py"
set "BUNDLED_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "PYTHON_EXE="

if not exist "%FRONTEND_DIST%\index.html" (
  echo [错误] 没有找到已构建网页：frontend\dist\index.html
  pause
  exit /b 1
)

if exist "%BUNDLED_PYTHON%" (
  set "PYTHON_EXE=%BUNDLED_PYTHON%"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [错误] 没有找到 Python。请先安装 Python 3.11 或更高版本。
    pause
    exit /b 1
  )
  set "PYTHON_EXE=python"
)

echo 正在启动 SciPilot 后端：http://127.0.0.1:8000/
start "SciPilot Backend" /min "%PYTHON_EXE%" -m uvicorn main:app --app-dir "%BACKEND_DIR%" --host 127.0.0.1 --port 8000

echo 正在启动 SciPilot 前端：http://127.0.0.1:5173/
echo 请自行在 Edge 中打开上述前端地址。
echo 关闭本窗口会停止前端；后端可在任务管理器或其最小化窗口中停止。
echo.

"%PYTHON_EXE%" "%SERVER_SCRIPT%" --root "%FRONTEND_DIST%" --host 127.0.0.1 --port 5173

if errorlevel 1 (
  echo.
  echo [提示] 如果端口被占用，请先关闭旧的 SciPilot 服务后重试。
  pause
)
