@echo off
chcp 65001 >nul
rem ============================================================
rem One-click build (this file and build_toolkit.py are to be kept in xpai-build/ and must NEVER be copied into the distribution directory)
rem   1. Obfuscate the sensitive constants in scripts/toolkit/*.py (scrypt-locked packed blobs + inline decode + decoys)
rem   2. Compile into .pyd (with docstring stripped), and after pure-pyd verification, delete the source
rem   3. Delete config.yaml
rem Usage: copy the clean source into xpai-camera-control-source/scripts/toolkit/,
rem       then just double-click this file
rem ============================================================
cd /d "%~dp0..\xpai-camera-control-source"
if errorlevel 1 (
    echo [Failed] Cannot enter the project directory xpai-camera-control-source. Please check that the directory has not been renamed.
    pause
    exit /b 1
)

if not exist "scripts\toolkit\__init__.py" (
    echo toolkit has no .py source awaiting compilation, so nothing will be done.
    pause
    exit /b 0
)

rem If gcc is not in PATH, fall back to the default MSYS2 MinGW64 install path
where gcc >nul 2>nul || set "PATH=C:\msys64\mingw64\bin;%PATH%"

python "%~dp0build_toolkit.py"
if errorlevel 1 (
    echo.
    echo [Failed] Build failed. Please see the error above.
    pause
    exit /b 1
)

del /f /q config.yaml 2>nul
echo.
echo [Done] Build succeeded: source deleted, config.yaml deleted. This directory is now in a distributable state.
pause
