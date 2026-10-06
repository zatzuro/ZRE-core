@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0zre_launch.ps1" %*
exit /b %errorlevel%
