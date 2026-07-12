@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"

echo ========================================
echo KongMing Windows Build
echo Project: %ROOT%
echo ========================================
echo.

if not exist "%ROOT%\backend" (
  echo [ERROR] backend directory not found: %ROOT%\backend
  goto :fail
)

if not exist "%ROOT%\frontend" (
  echo [ERROR] frontend directory not found: %ROOT%\frontend
  goto :fail
)

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] python command not found. Please install Python 3.11+ and add it to PATH.
  goto :fail
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3.11+ is required.
  python --version
  goto :fail
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm command not found. Please install Node.js and add npm to PATH.
  goto :fail
)

echo [1/5] Preparing backend virtual environment...
cd /d "%ROOT%\backend" || goto :fail
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto :fail
) else (
  echo Backend virtual environment already exists.
)

echo.
echo [2/5] Installing backend dependencies...
"%ROOT%\backend\.venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
"%ROOT%\backend\.venv\Scripts\pip.exe" install -e .[dev]
if errorlevel 1 goto :fail

echo.
echo [3/5] Installing frontend dependencies...
cd /d "%ROOT%\frontend" || goto :fail
set "NPM_CONFIG_CACHE=%ROOT%\frontend\.npm-cache"
set "NPM_CONFIG_AUDIT=false"
set "NPM_CONFIG_FUND=false"
if not exist "package-lock.json" goto :npm_install
call npm.cmd ci --no-audit --no-fund --cache "%NPM_CONFIG_CACHE%"
if not errorlevel 1 goto :npm_done

echo [WARN] npm ci failed. Cleaning npm cache and retrying with npm install...
call npm.cmd cache clean --force --cache "%NPM_CONFIG_CACHE%"
if exist "node_modules" rmdir /s /q "node_modules"
if exist "node_modules" (
  echo [ERROR] Cannot remove frontend\node_modules.
  echo [HINT] A running Vite/Node process may be locking the Rollup native module.
  echo [HINT] Stop the frontend process, then run build-windows.bat again.
  goto :fail
)

:npm_install
call npm.cmd install --no-audit --no-fund --cache "%NPM_CONFIG_CACHE%"
if errorlevel 1 (
  echo [ERROR] Frontend dependency installation failed.
  echo [HINT] On Windows, EPERM unlink usually means a running Vite/Node process is using Rollup.
  echo [HINT] Stop the frontend process, then run build-windows.bat again.
  goto :fail
)

:npm_done
echo.
echo [4/5] Building frontend...
call npm.cmd run build
if errorlevel 1 goto :fail

echo.
echo [5/5] Build completed successfully.
echo Frontend dist: %ROOT%\frontend\dist
echo.
pause
exit /b 0

:fail
echo.
echo Build failed. Please check the error output above.
pause
exit /b 1
