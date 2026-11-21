@echo off
rem ============================================================
rem  AutoEmu one-click build  (interactive menu)
rem
rem  Double-click it and pick a number. Command-line modes still work
rem  for automation:  build.cmd [full|arm|verify|collect|sync|clean|reset|help]
rem
rem  No hard-coded absolute paths. Lookup order:
rem    tools\_env.cmd  ->  environment vars  ->  PATH  ->  common locations  ->  ask user
rem  Keep this file pure ASCII: cmd.exe parses .bat with the console code page,
rem  so any non-ASCII byte here can break parsing. Chinese output lives in
rem  tools\menu.txt (printed via `type` under chcp 65001) and tools\rebuild.sh.
rem ============================================================
setlocal EnableExtensions EnableDelayedExpansion

set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"
set "CACHE=%HERE%\tools\_env.cmd"
set "CACHE_SH=%HERE%\tools\_env.sh"
set "SRCFILE=%HERE%\tools\_upstream"

rem Which upstream to sync from: easyworld (Chinese UI) or ctcaer (official).
set "UPSRC="
if exist "%SRCFILE%" for /f "usebackq delims=" %%a in ("%SRCFILE%") do set "UPSRC=%%a"
if not defined UPSRC set "UPSRC=easyworld"
set "VINC=%HERE%\baseline\firmware\hekate\Versions.inc"

set "MODE=%~1"
set "SYNCARGS=%~2 %~3 %~4 %~5"
if not "%MODE%"=="" goto :dispatch

rem ------------------------------------------------------------
rem  interactive menu (no arguments)
rem ------------------------------------------------------------
:menu
call :show_menu
if defined CH set "CH=%CH: =%"
if not defined CH set "CH=1"
if "%CH%"=="0" goto :bye
if "%CH%"=="1" set "MODE=auto"
if "%CH%"=="2" set "MODE=full"
if "%CH%"=="3" set "MODE=arm"
if "%CH%"=="4" set "MODE=verify"
if "%CH%"=="5" set "MODE=collect"
if "%CH%"=="6" set "MODE=sync"
if "%CH%"=="6" set "SYNCARGS=--repo !UPSRC!"
if "%CH%"=="7" set "MODE=sync"
if "%CH%"=="7" set "SYNCARGS=--repo !UPSRC! --apply"
if "%CH%"=="8" set "MODE=clean"
if "%CH%"=="9" set "MODE=reset"
if /i "%CH%"=="p" set "MODE=prepare"
if /i "%CH%"=="r" set "MODE=res"
if /i "%CH%"=="d" set "MODE=onekey"
if /i "%CH%"=="u" set "MODE=update"
if /i "%CH%"=="s" goto :pick_source
if /i "%CH%"=="h" set "MODE=help"
if not defined MODE (
    echo.
    echo   [INVALID] "%CH%" is not a menu item. Pick 1-9, h, or 0.
    goto :menu
)
goto :dispatch

:show_menu
for /f "tokens=2 delims=:" %%c in ('chcp') do set "OLDCP=%%c"
set "OLDCP=%OLDCP: =%"
chcp 65001 >nul 2>nul
if exist "%HERE%\tools\menu.txt" type "%HERE%\tools\menu.txt"
if exist "%HERE%\tools\src-!UPSRC!.txt" type "%HERE%\tools\src-!UPSRC!.txt"
call :baseline_version
if defined VERLINE echo   ^>^> current baseline: !VERLINE!
echo.
set "CH="
set /p "CH=  Select [1-9 / h / 0 = quit]: "
if defined OLDCP chcp %OLDCP% >nul 2>nul
exit /b 0

:baseline_version
set "VERLINE="
if not exist "%VINC%" exit /b 0
set "V1="
set "V2="
set "V3="
for /f "tokens=3" %%a in ('findstr /b /c:"BLVERSION_MAJOR" "%VINC%"') do set "V1=%%a"
for /f "tokens=3" %%a in ('findstr /b /c:"BLVERSION_MINOR" "%VINC%"') do set "V2=%%a"
for /f "tokens=3" %%a in ('findstr /b /c:"BLVERSION_HOTFX" "%VINC%"') do set "V3=%%a"
if defined V1 if defined V2 if defined V3 set "VERLINE=hekate !V1!.!V2!.!V3!"
exit /b 0

:bye
echo.
echo   Bye.
endlocal & exit /b 0

rem ------------------------------------------------------------
rem  pick upstream source
rem ------------------------------------------------------------
:pick_source
for /f "tokens=2 delims=:" %%c in ('chcp') do set "OLDCP2=%%c"
set "OLDCP2=%OLDCP2: =%"
chcp 65001 >nul 2>nul
if exist "%HERE%\tools\src-!UPSRC!.txt" type "%HERE%\tools\src-!UPSRC!.txt"
if defined OLDCP2 chcp %OLDCP2% >nul 2>nul
echo.
echo     1   easyworld   Chinese UI, may lag behind official
echo     2   ctcaer      official upstream, English UI only
echo.
set "PS="
set /p "PS=  Source [1/2, Enter keeps current]: "
if defined PS set "PS=%PS: =%"
if "%PS%"=="1" set "UPSRC=easyworld"
if "%PS%"=="2" set "UPSRC=ctcaer"
> "%SRCFILE%" echo %UPSRC%
echo   saved: %UPSRC%
goto :menu

rem ------------------------------------------------------------
rem  dispatch
rem ------------------------------------------------------------
:dispatch
if /i "%MODE%"=="help"  goto :usage
if /i "%MODE%"=="reset" goto :reset
if /i "%MODE%"=="d"     set "MODE=onekey"
if /i "%MODE%"=="u"     set "MODE=update"

echo.
echo   AutoEmu build
echo   ------------------------------------------------------------
echo   root : %HERE%
echo   mode : %MODE%
echo.

if not exist "%HERE%\baseline\firmware\hekate\Makefile" (
    echo [ERROR] incomplete layout: baseline\firmware\hekate\Makefile not found
    echo         Put this script at the AutoEmu root, next to baseline\ and patches\.
    set "RC=1"
    goto :done
)

if exist "%CACHE%" call "%CACHE%"

call :resolve_msys2
if errorlevel 1 goto :fail
call :resolve_devkit
if errorlevel 1 goto :fail
call :resolve_python
if errorlevel 1 goto :fail

echo   resolved:
echo     MSYS2     : !MSYS2_ROOT!
echo     devkitARM : !DEVKITARM!
echo     Python    : !PY!
call :save_cache

rem ---------- prepare ready.flag / payload.bin for one card ----------
if /i "!MODE!"=="prepare" (
    echo.
    echo == write ready.flag / payload.bin into the TF card ==
    for /f "tokens=2 delims=:" %%c in ('chcp') do set "OLDCPP=%%c"
    set "OLDCPP=!OLDCPP: =!"
    chcp 65001 >nul 2>nul
    rem %* keeps every argument (up to 9 pairs); drop the mode word
    set "PARGS="
    for /f "tokens=1,*" %%a in ("%*") do set "PARGS=%%b"
    "%PY%" "%HERE%\tools\prepare.py" !PARGS!
    set "RC=!ERRORLEVEL!"
    if defined OLDCPP chcp !OLDCPP! >nul 2>nul
    if "!RC!"=="42" (
        echo.
        echo   [ELEVATED] continued in a new administrator window.
        echo              If no new window appeared, the UAC prompt was declined.
        set "RC=0"
    )
    goto :done
)

rem ---------- refresh res.pak / thk.bin from GitHub release ----------
if /i "!MODE!"=="res" (
    echo.
    echo == fetch res.pak / thk.bin from the GitHub release ==
    for /f "tokens=2 delims=:" %%c in ('chcp') do set "OLDCPR=%%c"
    set "OLDCPR=!OLDCPR: =!"
    chcp 65001 >nul 2>nul
    set "RARGS="
    for /f "tokens=1,*" %%a in ("%*") do set "RARGS=%%b"
    if not "!RARGS!"=="" goto :res_run
    set "RARGS=--repo !UPSRC!"
  :res_run
    "%PY%" "%HERE%\tools\fetch_res.py" !RARGS!
    set "RC=!ERRORLEVEL!"
    if defined OLDCPR chcp !OLDCPR! >nul 2>nul
    goto :done
)

rem ---------- one key: fetch upstream resources, then build ----------
rem This is the "new machine, one command" path: it only needs network for
rem res.pak / thk.bin; the source tree is already inside this folder.
if /i "!MODE!"=="onekey" (
    echo.
    echo == step 0/3: check upstream ^(read-only, failures are ignored^) ==
    for /f "tokens=2 delims=:" %%c in ('chcp') do set "OLDCP0=%%c"
    set "OLDCP0=!OLDCP0: =!"
    chcp 65001 >nul 2>nul
    "%PY%" "%HERE%\tools\sync.py" --repo !UPSRC! --quick
    if defined OLDCP0 chcp !OLDCP0! >nul 2>nul
    echo.
    echo == step 1/3: fetch upstream resources ^(res.pak / thk.bin^) ==
    for /f "tokens=2 delims=:" %%c in ('chcp') do set "OLDCPO=%%c"
    set "OLDCPO=!OLDCPO: =!"
    chcp 65001 >nul 2>nul
    "%PY%" "%HERE%\tools\fetch_res.py" --repo !UPSRC!
    set "RC=!ERRORLEVEL!"
    if defined OLDCPO chcp !OLDCPO! >nul 2>nul
    if not "!RC!"=="0" (
        echo.
        echo   [WARN] resource fetch failed ^(offline? set HTTPS_PROXY=http://127.0.0.1:10808^)
        if not exist "%HERE%\baseline\firmware\resources\res.pak" (
            echo   [ERROR] res.pak missing and cannot be downloaded - abort.
            set "RC=1"
            goto :done
        )
        if not exist "%HERE%\baseline\firmware\resources\thk.bin" (
            echo   [ERROR] thk.bin missing and cannot be downloaded - abort.
            set "RC=1"
            goto :done
        )
        echo   local copies exist, continuing with them.
    )
    echo.
    echo == step 2/3: compile ^+ package ^+ collect ==
    set "MODE=full"
)

rem ---------- update: sync upstream (apply), then build ----------
rem Follow upstream end-to-end: sync --apply backs up baseline first and refuses
rem to land anything when the patch conflicts, so no half-applied tree. On success
rem it falls through to the normal full build below.
if /i "!MODE!"=="update" (
    echo.
    echo == step 1/2: sync upstream ^(apply^) ==
    "%PY%" "%HERE%\tools\sync.py" --repo !UPSRC! --apply
    set "RC=!ERRORLEVEL!"
    if not "!RC!"=="0" (
        echo.
        echo   [ERROR] sync failed - baseline was NOT replaced ^(or was left as-is^).
        echo           patch conflict? see SYNC.md section 4 / UPGRADE.md section 3
        goto :done
    )
    echo.
    echo == step 2/2: compile ^+ package ^+ collect ==
    set "MODE=full"
)

rem ---------- sync upstream ----------
if /i "!MODE!"=="sync" (
    echo.
    echo == sync upstream hekate ==
    set "ARGS=!SYNCARGS!"
    echo !ARGS! | findstr /i /c:"--repo" >nul || set "ARGS=--repo !UPSRC! !ARGS!"
    "%PY%" "%HERE%\tools\sync.py" !ARGS!
    set "RC=!ERRORLEVEL!"
    if not "!RC!"=="0" (
        echo.
        echo   [HINT] pull failed? set a proxy and retry:
        echo          set HTTPS_PROXY=http://127.0.0.1:10808
        echo   [HINT] patch conflict? see SYNC.md section 4 / UPGRADE.md section 3
    )
    goto :done
)

rem ---------- build ----------
rem Keep the console on UTF-8 for everything that prints Chinese (rebuild.sh and
rem compare.py); restore the original code page at :done.
for /f "tokens=2 delims=:" %%c in ('chcp') do set "OLDCP=%%c"
set "OLDCP=!OLDCP: =!"
chcp 65001 >nul 2>nul
"%MSYS2_ROOT%\usr\bin\bash.exe" -l "%HERE%\tools\rebuild.sh" "%MODE%"
set "RC=!ERRORLEVEL!"

rem ---------- compare against the shipped assets ----------
if not "!RC!"=="0" goto :done
if /i "!MODE!"=="arm" goto :done
if /i "!MODE!"=="clean" goto :done
if /i "!MODE!"=="collect" goto :done

echo.
echo == compare with shipped assets ==
"%PY%" "%HERE%\verify\compare.py" "%HERE%\baseline\firmware\hekate\output"
set "CMP=!ERRORLEVEL!"
if not "!CMP!"=="0" (
    echo.
    echo [NOTE] Artifacts differ from the shipped ones.
    echo        Expected if you changed the source or synced a new upstream.
    if /i "!MODE!"=="verify" (
        echo [FAIL] verify mode requires a byte-identical rebuild.
        set "RC=1"
    )
) else (
    echo.
    echo [PASS] All ARM artifacts are byte-identical to the shipped ones.
)

:done
if defined OLDCP chcp !OLDCP! >nul 2>nul
if not "!RC!"=="0" goto :done_pause
if /i "!MODE!"=="sync" goto :tip_sync
if /i "!MODE!"=="help" goto :done_pause
if /i "!MODE!"=="reset" goto :done_pause
if /i "!MODE!"=="clean" goto :done_pause
if /i "!MODE!"=="prepare" goto :done_pause
if /i "!MODE!"=="res" goto :done_pause
if /i "!MODE!"=="collect" goto :tip_plain

echo.
echo == done ==
if /i "!MODE!"=="arm" (
    echo   output : %HERE%\baseline\firmware\hekate\output\
) else (
    echo   bundle : %HERE%\baseline\assets\auto-emu.zip
    echo   next   : replace src\NsToolbox.App\NsToolbox.AutoEmu.zip, then rebuild the app.
)
echo   out    : %HERE%\out\  [copies + MANIFEST.txt]
goto :done_pause

:tip_sync
echo.
echo == sync finished (see the report above) ==
goto :done_pause

:tip_plain
echo.
echo == done ==
echo   out    : %HERE%\out\  [copies + MANIFEST.txt]

:done_pause
set "FINAL=%RC%"
rem Always keep the window open so the output is readable (double-click, cmd, anywhere).
rem Automation can set AUTOEMU_NO_PAUSE=1 to skip it.
if not defined AUTOEMU_NO_PAUSE (
    echo.
    echo   Press any key to close this window ...
    pause >nul
)
endlocal & exit /b %FINAL%

:fail
set "RC=1"
goto :done


rem ============================================================
rem  helpers
rem ============================================================

:resolve_msys2
if defined MSYS2_ROOT if exist "!MSYS2_ROOT!\usr\bin\bash.exe" if exist "!MSYS2_ROOT!\usr\bin\make.exe" exit /b 0
rem derive from DEVKITARM: <msys64>\opt\devkitpro\devkitARM
if defined DEVKITARM if exist "!DEVKITARM!\..\..\..\usr\bin\bash.exe" (
    for %%D in ("!DEVKITARM!\..\..\..") do set "MSYS2_ROOT=%%~fD"
)
if defined MSYS2_ROOT if exist "!MSYS2_ROOT!\usr\bin\bash.exe" exit /b 0
rem derive from bash.exe on PATH: <msys64>\usr\bin\bash.exe
for /f "delims=" %%P in ('where bash 2^>nul') do (
    for %%D in ("%%~dpP..\..") do (
        if exist "%%~fD\usr\bin\bash.exe" if exist "%%~fD\usr\bin\make.exe" if not defined MSYS2_ROOT set "MSYS2_ROOT=%%~fD"
    )
)
if defined MSYS2_ROOT exit /b 0
rem common install locations (drive letters come from system vars, not hard-coded)
for %%D in ("%SystemDrive%\msys64" "%ProgramFiles%\msys64" "%ProgramFiles%\MSYS2" "%USERPROFILE%\msys64") do (
    if exist "%%~D\usr\bin\bash.exe" if exist "%%~D\usr\bin\make.exe" if not defined MSYS2_ROOT set "MSYS2_ROOT=%%~D"
)
if defined MSYS2_ROOT exit /b 0
echo.
echo [NEED] MSYS2 not found (needs usr\bin\bash.exe and usr\bin\make.exe).
set /p "IN=Enter MSYS2 root (e.g. X:\msys64), blank to abort: "
if not defined IN exit /b 1
set "IN=!IN:"=!"
for %%I in ("!IN!") do set "IN=%%~fI"
if not exist "!IN!\usr\bin\bash.exe" (
    echo   [INVALID] !IN!\usr\bin\bash.exe not found
    exit /b 1
)
set "MSYS2_ROOT=!IN!"
exit /b 0

:resolve_devkit
if defined DEVKITARM if exist "!DEVKITARM!\base_rules" exit /b 0
if defined MSYS2_ROOT if exist "!MSYS2_ROOT!\opt\devkitpro\devkitARM\base_rules" (
    set "DEVKITARM=!MSYS2_ROOT!\opt\devkitpro\devkitARM"
)
if defined DEVKITARM if exist "!DEVKITARM!\base_rules" exit /b 0
echo.
echo [NEED] devkitARM not found (needs base_rules and bin\arm-none-eabi-gcc.exe).
echo        Usually under ^<MSYS2^>\opt\devkitpro\devkitARM
set /p "IN=Enter devkitARM directory, blank to abort: "
if not defined IN exit /b 1
set "IN=!IN:"=!"
for %%I in ("!IN!") do set "IN=%%~fI"
if not exist "!IN!\base_rules" (
    echo   [INVALID] !IN!\base_rules not found
    exit /b 1
)
set "DEVKITARM=!IN!"
exit /b 0

:resolve_python
if defined PY if exist "!PY!" (
    "!PY!" -c "import sys" >nul 2>nul && exit /b 0
    set "PY="
)
rem the Microsoft Store python.exe is a 0-byte stub; a test run filters it out
for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PY if exist "%%P" (
        "%%P" -c "import sys" >nul 2>nul && set "PY=%%P"
    )
)
if defined PY exit /b 0
rem py launcher: resolve to the real interpreter
for /f "delims=" %%P in ('py -c "import sys;print(sys.executable)" 2^>nul') do (
    if not defined PY if exist "%%P" set "PY=%%P"
)
if defined PY exit /b 0
echo.
echo [NEED] Python 3 not found (used by build.py and compare.py).
set /p "IN=Enter full path to python.exe, blank to abort: "
if not defined IN exit /b 1
set "IN=!IN:"=!"
for %%I in ("!IN!") do set "IN=%%~fI"
if not exist "!IN!" (
    echo   [INVALID] !IN! not found
    exit /b 1
)
"!IN!" -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo   [INVALID] that file is not a working Python
    exit /b 1
)
set "PY=!IN!"
exit /b 0

:save_cache
rem machine-local cache only; `build.cmd reset` removes it
rem _env.cmd: read back by this script.  _env.sh: read back by tools\rebuild.sh,
rem because the MSYS2 login shell does NOT inherit environment variables.
> "%CACHE%" echo @echo off
>>"%CACHE%" echo set "MSYS2_ROOT=!MSYS2_ROOT!"
>>"%CACHE%" echo set "DEVKITARM=!DEVKITARM!"
>>"%CACHE%" echo set "PY=!PY!"
if exist "%HERE%\tools" (
    > "%CACHE_SH%" echo # generated by build.cmd -- safe to delete ^(build.cmd reset^)
    >>"%CACHE_SH%" echo export MSYS2_ROOT='!MSYS2_ROOT:\=/!'
    >>"%CACHE_SH%" echo export DEVKITARM='!DEVKITARM:\=/!'
    >>"%CACHE_SH%" echo export PY='!PY:\=/!'
)
exit /b 0

:reset
if exist "%CACHE%" (
    del /q "%CACHE%" >nul 2>nul
    echo cleared: %CACHE%
) else (
    echo no cache file: %CACHE%
)
if exist "%CACHE_SH%" (
    del /q "%CACHE_SH%" >nul 2>nul
    echo cleared: %CACHE_SH%
)
set "RC=0"
goto :done

:usage
echo.
echo   AutoEmu one-click build  (needs MSYS2 + devkitPro/devkitARM + Python 3)
echo.
echo   No argument        show the interactive menu (pick a number)
echo   build.cmd 1..9     same actions as the menu, for automation
echo   build.cmd auto     reuse artifacts if up to date, else full build
echo   build.cmd full     always build ARM artifacts ^+ package ^+ compare
echo   build.cmd arm      build ARM artifacts only (no packaging)
echo   build.cmd verify   same as full, but must be byte-identical to shipped
echo   build.cmd collect  copy existing artifacts into out\ with MANIFEST.txt
echo   build.cmd sync     check upstream hekate (latest), dry-run by default
echo     build.cmd sync --repo ctcaer --ref v6.5.5 --apply   example
echo   build.cmd clean    remove build\ output\ assets\ release\ build-info.json out\
echo   build.cmd reset    clear the machine-local path cache (tools\_env.cmd)
echo   build.cmd prepare  write ready.flag / payload.bin(.backup) into the target TF card
echo   build.cmd res      fetch res.pak ^+ thk.bin from GitHub (auto: current source)
echo   build.cmd onekey   fetch resources -^> compile -^> package -^> collect (one shot)
echo   build.cmd update   sync upstream ^(apply^) -^> compile -^> package (follow upstream)
echo   build.cmd help     this text
echo.
echo   menu:  1 auto  2 full  3 arm  4 verify  5 collect
echo          6 sync  7 sync --apply  8 clean  9 reset
echo          p prepare task files  s switch upstream source
echo          h help  0 quit
echo.
echo   upstream source: easyworld (Chinese UI) or ctcaer (official).
echo   sync uses it automatically; override with --repo ctcaer.
echo.
echo   lookup: tools\_env.cmd -^> env vars -^> PATH -^> common dirs -^> ask user
echo   window stays open after the run; set AUTOEMU_NO_PAUSE=1 to skip that.
echo.
set "RC=0"
goto :done
