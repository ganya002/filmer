@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  Mine filmer
echo  Setter opp programmet. Dette vinduet kan sta oppe en liten stund.
echo.

set "DEST=%LOCALAPPDATA%\MineFilmer"
if not exist "%DEST%\app" mkdir "%DEST%\app"
if not exist "%DEST%\web" mkdir "%DEST%\web"
if not exist "%DEST%\assets" mkdir "%DEST%\assets"
if not exist "%DEST%\data" mkdir "%DEST%\data"
if not exist "%DEST%\installer" mkdir "%DEST%\installer"

xcopy /E /I /Y "%~dp0app\*" "%DEST%\app\" >nul
xcopy /E /I /Y "%~dp0web\*" "%DEST%\web\" >nul
xcopy /E /I /Y "%~dp0assets\*" "%DEST%\assets\" >nul
copy /Y "%~dp0installer\Start.vbs" "%DEST%\Start.vbs" >nul
copy /Y "%~dp0installer\lag-snarvei.ps1" "%DEST%\installer\lag-snarvei.ps1" >nul

set "PYEXE="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info>=(3,9) else 1)" 1>nul 2>nul
if not errorlevel 1 set "PYEXE=py -3"
if not defined PYEXE (
  python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,9) else 1)" 1>nul 2>nul
  if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE goto download
goto shortcut

:download
echo Laster ned Python. Det trengs bare forste gang.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip' -OutFile '%DEST%\python-embed.zip' } catch { exit 1 }"
if errorlevel 1 goto nopython
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force -LiteralPath '%DEST%\python-embed.zip' -DestinationPath '%DEST%\python'"
if errorlevel 1 goto nopython
set "PYEXE=%DEST%\python\python.exe"
del "%DEST%\python-embed.zip" >nul 2>nul

:shortcut
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\lag-snarvei.ps1" -Dest "%DEST%" -PythonCmd "%PYEXE%"
if errorlevel 1 goto noshortcut
echo.
echo Ferdig. Ikonet Mine filmer ligger naa paa skrivebordet.
echo.
cscript //nologo "%DEST%\Start.vbs"
exit /b 0

:nopython
echo.
echo Klarte ikke aa laste ned Python. Koble til internett og prov igjen.
pause
exit /b 1

:noshortcut
echo.
echo Programmet er kopiert, men snarveien ble ikke laget.
echo Du kan aapne Mine filmer med filen kjor.bat i %DEST%
pause
exit /b 1
