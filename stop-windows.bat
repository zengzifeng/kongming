@echo off
setlocal EnableExtensions

echo ========================================
echo KongMing Windows Stop
echo ========================================
echo.

call :kill_port 5001 Backend
call :kill_port 5173 Frontend

echo.
echo Stop command completed.
echo.
if /I not "%~1"=="/nopause" pause
exit /b 0

:kill_port
set "PORT=%~1"
set "NAME=%~2"
set "FOUND=0"

echo Checking %NAME% port %PORT%...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  set "FOUND=1"
  echo Stopping %NAME% process PID %%P on port %PORT%...
  taskkill /F /PID %%P >nul 2>nul
  if errorlevel 1 (
    echo [WARN] Failed to stop PID %%P. It may have already exited or requires administrator permission.
  ) else (
    echo [OK] Stopped PID %%P.
  )
)

if "%FOUND%"=="0" (
  echo [SKIP] No LISTENING process found on port %PORT%.
)
exit /b 0
