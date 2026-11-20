@echo off
setlocal
where gcc >nul 2>nul
if errorlevel 1 (
    echo [error] gcc not found in PATH.
    echo         Use the MSYS2/mingw-w64 shell, or add its bin directory to PATH.
    exit /b 1
)
if not exist bin mkdir bin
gcc -O2 -Wall -Wextra -std=c11 -o bin\nstask.exe main.c nstask.c sha256.c
if errorlevel 1 (
    echo [error] build failed.
    exit /b 1
)
echo [ok] bin\nstask.exe
echo.
echo Running selftest...
bin\nstask.exe selftest
endlocal
