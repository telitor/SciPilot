@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "BACKEND_DIR=%PROJECT_ROOT%backend"
set "FRONTEND_DIST=%PROJECT_ROOT%frontend\dist"
set "SERVER_SCRIPT=%PROJECT_ROOT%frontend\提供_SciPilot前端静态网页服务.py"
set "VENV_PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"
set "PYTHON_EXE="

if not exist "%FRONTEND_DIST%\index.html" (
  echo [错误] 没有找到已构建网页：frontend\dist\index.html
  pause
  exit /b 1
)

if not exist "%BACKEND_DIR%\.env" (
  echo [错误] 没有找到 backend\.env。请先复制 backend\.env.example 并填写后端配置。
  pause
  exit /b 1
)

if exist "%VENV_PYTHON%" (
  set "PYTHON_EXE=%VENV_PYTHON%"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [错误] 没有找到 backend\.venv 或系统 Python。
    echo 请先按 README 安装 Python 3.10+ 和 backend\requirements.txt。
    pause
    exit /b 1
  )
  set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" -c "import fastapi, uvicorn, supabase, openai" >nul 2>nul
if errorlevel 1 (
  echo [错误] 当前 Python 缺少后端依赖。请先运行：
  echo   python -m pip install -r backend\requirements.txt
  pause
  exit /b 1
)

"%PYTHON_EXE%" "%BACKEND_DIR%\scripts\check_runtime_config.py"
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

set "BACKEND_PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do set "BACKEND_PORT_PID=%%P"
if defined BACKEND_PORT_PID (
  echo [错误] 端口 8000 已被进程 PID %BACKEND_PORT_PID% 占用。
  echo 这通常表示旧版 SciPilot 后端仍在运行。请先关闭旧后端，再重新双击启动。
  pause
  exit /b 1
)

echo 正在启动 SciPilot 后端：http://127.0.0.1:8000/
start "SciPilot Backend" /min "%PYTHON_EXE%" -m uvicorn main:app --app-dir "%BACKEND_DIR%" --host 127.0.0.1 --port 8000

echo 正在启动 SciPilot 前端：http://127.0.0.1:5173/
echo 浏览器将在服务启动后打开；也可以手动访问上述地址。
echo 关闭本窗口会停止前端；后端可在任务管理器或其最小化窗口中停止。
echo.

start "" "http://127.0.0.1:5173/"
"%PYTHON_EXE%" "%SERVER_SCRIPT%" --root "%FRONTEND_DIST%" --host 127.0.0.1 --port 5173

if errorlevel 1 (
  echo.
  echo [提示] 如果端口被占用，请先关闭旧的 SciPilot 服务后重试。
  pause
)
