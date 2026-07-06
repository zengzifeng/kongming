@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"

echo ========================================
echo KongMing Windows Start
echo Project: %ROOT%
echo ========================================
echo.

if not exist "%ROOT%\backend\.venv\Scripts\python.exe" (
  echo [ERROR] Backend virtual environment not found.
  echo Please run build-windows.bat first.
  goto :fail
)

if not exist "%ROOT%\frontend\node_modules" (
  echo [ERROR] Frontend dependencies not found.
  echo Please run build-windows.bat first.
  goto :fail
)

if not exist "%ROOT%\backend\run.py" (
  echo [ERROR] Backend entry file not found: %ROOT%\backend\run.py
  goto :fail
)

if not exist "%ROOT%\frontend\package.json" (
  echo [ERROR] Frontend package.json not found: %ROOT%\frontend\package.json
  goto :fail
)

if not exist "%ROOT%\frontend\node_modules\.bin\vite.cmd" (
  echo [ERROR] Local Vite executable not found: %ROOT%\frontend\node_modules\.bin\vite.cmd
  echo Please run build-windows.bat first and confirm npm dependencies installed successfully.
  goto :fail
)

echo Starting backend on http://localhost:5001 ...
start "KongMing Backend - 5001" cmd /k "pushd ""%ROOT%\backend"" && set KONGMING_ENV=dev&& set PORT=5001&& .venv\Scripts\python.exe run.py"

echo Starting frontend on http://localhost:5173 ...
start "KongMing Frontend - 5173" cmd /k "pushd ""%ROOT%\frontend"" && set NODE_OPTIONS=--dns-result-order=ipv4first&& node_modules\.bin\vite.cmd --host 0.0.0.0"

set "LOCAL_IP="
for /f "tokens=2 delims=:" %%I in ('ipconfig ^| findstr /R /C:"IPv4.*[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*"') do (
  if not defined LOCAL_IP (
    for /f "tokens=*" %%A in ("%%I") do (
      echo %%A | findstr /R /V /C:"^127\." /C:"^169\.254\." >nul && set "LOCAL_IP=%%A"
    )
  )
)

echo.
echo Services are starting in separate windows.
echo Frontend local : http://localhost:5173
if defined LOCAL_IP echo Frontend network: http://%LOCAL_IP%:5173
if not defined LOCAL_IP echo Frontend network: unable to detect local IPv4 address
echo Backend        : http://localhost:5001
echo.
echo Use stop-windows.bat to stop both services.
echo.
if /I not "%~1"=="/nopause" pause
exit /b 0

:fail
echo.
echo Start failed. Please check the error output above.
pause
exit /b 1
