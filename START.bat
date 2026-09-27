@echo off
setlocal
cd /d "%~dp0"

rem --- keep console + python output in UTF-8 so Chinese text shows correctly ---
chcp 65001 >nul 2>nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

rem --- bundled Java (full edition): runtime\jre-win is the Windows build ---
rem     We only accept it if it actually runs, so a Linux JRE copied onto
rem     Windows (runtime\jre) is never mistaken for a usable one.
set "BUNDLED_JAVA="
if exist "%~dp0runtime\jre-win\bin\java.exe" set "BUNDLED_JAVA=%~dp0runtime\jre-win\bin\java.exe"
if not defined BUNDLED_JAVA if exist "%~dp0runtime\jre\bin\java.exe" set "BUNDLED_JAVA=%~dp0runtime\jre\bin\java.exe"
if defined BUNDLED_JAVA (
    "%BUNDLED_JAVA%" -version >nul 2>nul
    if errorlevel 1 (
        set "BUNDLED_JAVA="
    ) else (
        set "TOOLKIT_JAVA=%BUNDLED_JAVA%"
        echo   [Java] bundled: %BUNDLED_JAVA%
    )
)
if not defined TOOLKIT_JAVA echo   [Java] no bundled JRE - searching PATH / launchers...

rem --- find python: py launcher -> python -> python3 ---
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY where python3 >nul 2>nul && set "PY=python3"

if not defined PY (
    echo.
    echo   [ERROR] Python not found.
    echo   Please install Python 3.8+ : https://www.python.org/downloads/
    echo   During install, tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

%PY% app\tool.py

echo.
echo   Press any key to close...
pause >nul
endlocal
