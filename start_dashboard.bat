@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Python no esta instalado. Instala Python 3.10+ desde python.org y vuelve a ejecutar este archivo.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Creando entorno local...
  %PY% -m venv .venv
)
echo Comprobando actualizaciones de ZRE Core...
".venv\Scripts\python.exe" updater.py
echo Comprobando dependencias...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo No se pudieron instalar las dependencias. Comprueba tu conexion a internet.
  pause
  exit /b 1
)
start "ZRE Browser" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://localhost:8765/?fresh=%RANDOM%%RANDOM%'"
echo Iniciando el puente local. Cierra esta ventana para detenerlo.
".venv\Scripts\python.exe" server\iracing_bridge.py %*
