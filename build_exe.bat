@echo off
rem 方寸 / Square 打包脚本：onefile、无控制台，产物 dist\Square.exe
rem 可重复执行：每次先清掉上次的 build\ 与 dist\
rem 注意：本文件为 GBK 编码 + CRLF 换行，勿存成 UTF-8，否则 cmd 解析会断行
setlocal
cd /d "%~dp0"

echo [1/2] Cleaning previous build (build\, dist\)...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [2/2] Running PyInstaller with square.spec...
python -m PyInstaller --noconfirm square.spec
if errorlevel 1 goto fail

echo.
echo Done: %~dp0dist\Square.exe
exit /b 0

:fail
echo.
echo Build FAILED. See the messages above.
exit /b 1
