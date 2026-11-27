@echo off
setlocal
cd /d "%~dp0"
py -3 app\server.py --open
if not errorlevel 1 goto done
python app\server.py --open
if errorlevel 1 (
  echo.
  echo Fant ikke Python. Dobbelklikk Installer.bat i stedet.
  pause
)
:done
