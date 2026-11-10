@echo off
rem Square / Windows 7 build: Python 3.8 + PyInstaller 5.13.2
rem Output: dist\Square-Win7.exe
rem Keep this file ASCII-only: cmd parses .bat in the OEM code page.
setlocal
cd /d "%~dp0"

set "PYTHON=%~1"
if "%PYTHON%"=="" set "PYTHON=%~dp0.venv-win7\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=E:\Python38\python.exe"
if not exist "%PYTHON%" set "PYTHON=D:\IPA\PJ-IPAStudio_Windows_Professional\pyscript\communication\executor\parser\python.exe"

if not exist "%PYTHON%" goto nopython

rem Isolate PATH so PyInstaller's bindepend cannot pick up UCRT DLLs shipped by
rem unrelated software (the 3.13 line accidentally bundled TortoiseGit's ucrtbase.dll).
set "PATH=%SystemRoot%\system32;%SystemRoot%;%SystemRoot%\System32\Wbem"
for %%I in ("%PYTHON%") do set "PATH=%PATH%;%%~dpI"

echo [0/3] Interpreter: %PYTHON%
"%PYTHON%" -VV
if errorlevel 1 goto fail

echo [1/3] Checking dependencies...
"%PYTHON%" -c "import customtkinter, PIL, numpy, segno, pyzbar, PyInstaller; print('deps ok')"
if errorlevel 1 goto fail

rem Remove only this line's artifacts: keep dist\Square.exe and dist\Square.zip
if exist build\Square-Win7 rmdir /s /q build\Square-Win7
if exist dist\Square-Win7.exe del /q dist\Square-Win7.exe

echo [3/3] Running PyInstaller with square-win7.spec...
"%PYTHON%" -m PyInstaller --noconfirm square-win7.spec
if errorlevel 1 goto fail

echo Verifying bundled binaries...
"%PYTHON%" tools\check_bundle.py build\Square-Win7\Analysis-00.toc
if errorlevel 1 goto fail

echo.
echo Done: %~dp0dist\Square-Win7.exe
exit /b 0

:nopython
echo.
echo ERROR: no Python 3.8 interpreter found.
echo Pass one as the first argument, or create a venv at .venv-win7.
exit /b 2

:fail
echo.
echo Build FAILED. See the messages above.
exit /b 1
