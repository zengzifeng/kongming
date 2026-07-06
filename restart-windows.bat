@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"

echo ========================================
echo KongMing Windows Restart
echo Project: %ROOT%
echo ========================================
echo.

if not exist "%ROOT%\stop-windows.bat" (
  echo [ERROR] stop-windows.bat not found.
  goto :fail
)

if not exist "%ROOT%\start-windows.bat" (
  echo [ERROR] start-windows.bat not found.
  goto :fail
)

echo Stopping existing services...
call "%ROOT%\stop-windows.bat" /nopause

echo.
echo Starting services again...
call "%ROOT%\start-windows.bat" /nopause
set "RESULT=%ERRORLEVEL%"
echo.
pause
exit /b %RESULT%

:fail
echo.
echo Restart failed. Please check the error output above.
pause
exit /b 1
