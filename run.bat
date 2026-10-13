@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

if "%~1"=="" goto :login
goto :run

:login
python seu_login.py %*
goto :end

:run
python seu_login.py %*
goto :end

:end
if errorlevel 1 pause
