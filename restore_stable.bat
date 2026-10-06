@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_test_build.ps1" -Root "%~dp0." -RestoreStable %*
exit /b %errorlevel%
