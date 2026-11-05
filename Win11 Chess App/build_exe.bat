@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo   Simple Chess - building SimpleChess.exe
echo ============================================
echo.

set PY=
where py >nul 2>nul
if %errorlevel%==0 set PY=py -3
if not defined PY (
  where python >nul 2>nul
  if %errorlevel%==0 set PY=python
)
if not defined PY goto nopython

%PY% -c "import tkinter" >nul 2>nul
if not %errorlevel%==0 goto notk

echo Step 1 of 2: installing the packaging tool, needs internet this one time only...
%PY% -m pip install --upgrade pyinstaller
if not %errorlevel%==0 goto fail

echo.
echo Step 2 of 2: building the program...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name SimpleChess chess_app.py
if not %errorlevel%==0 goto fail

copy /y "dist\SimpleChess.exe" "SimpleChess.exe" >nul
echo.
echo ============================================
echo   Done!  SimpleChess.exe is in this folder.
echo   Double-click it to play. It works offline.
echo ============================================
pause
exit /b 0

:nopython
echo Python was not found.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH"
echo during setup, then run this file again.
pause
exit /b 1

:notk
echo Python is installed but its Tk component is missing.
echo Re-run the Python installer, choose Modify, and keep "tcl/tk and IDLE" ticked.
pause
exit /b 1

:fail
echo.
echo The build failed. Check the messages above.
pause
exit /b 1
