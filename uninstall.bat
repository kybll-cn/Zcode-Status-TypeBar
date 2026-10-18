@echo off
rem ===================================================================
rem  Zcode-Status-TypeBar -- one-click uninstall
rem
rem  双击本文件即可。移除 app.asar 里的注入行、注销 MCP server、
rem  删除插件目录，并把 app.asar 还原成未注入状态。
rem
rem  可选参数原样透传给 uninstall.py，例如：
rem    uninstall.bat --keep-files
rem    uninstall.bat --dry-run
rem ===================================================================

rem This file is GBK-encoded and is parsed with the system ANSI code page.
rem Do not add "chcp 65001": cmd would then read the GBK bytes as UTF-8.
rem Keep these comments ASCII-only so they survive every code page.
rem If PYTHONIOENCODING is set in the environment, Python writes UTF-8
rem bytes and a GBK console shows mojibake. Unset it with "set VAR=" so
rem Python follows the real console encoding.
set "PYTHONIOENCODING="
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PY_USER_DIR=%LOCALAPPDATA%\Programs\Python\Python312"

rem %* is expanded at parse time and is NOT affected by shift, so arguments
rem are rebuilt manually into REST.
set "REST="
:collect_args
if "%~1"=="" goto :args_done
set "REST=!REST! %1"
shift
goto :collect_args
:args_done

echo.
echo   Zcode-Status-TypeBar  卸载程序
echo   ========================================
echo.

call :find_python
if not defined PY_CMD (
    echo   [x] 没有找到 Python 3，无法自动卸载。
    echo.
    echo       卸载本身只需处理两处，你也可以手动做：
    echo.
    echo         1. 删除目录  %USERPROFILE%\.zcode\zcode-token-usage-statusbar
    echo         2. 编辑  %USERPROFILE%\.zcode\cli\config.json
    echo            删除 mcp.servers 下的 zcode-token-usage-statusbar 条目
    echo         3. 用 resources 目录下的 app.asar.zusage-backup-版本号
    echo            覆盖回 app.asar
    echo.
    goto :fail
)
echo   [1/3] Python 就绪: !PY_CMD!

rem Use absolute System32 paths: with Git for Windows installed, the find.exe
rem on PATH is GNU find and would treat /I as a filename.
"%SystemRoot%\System32\tasklist.exe" /FI "IMAGENAME eq ZCode.exe" /NH 2>nul | "%SystemRoot%\System32\find.exe" /I "ZCode.exe" >nul
if not errorlevel 1 (
    echo.
    echo   [x] 检测到 ZCode 正在运行。
    echo.
    echo       请先完全退出 ZCode：关掉所有窗口，并在系统托盘右键
    echo       ZCode 图标选择"退出"。否则 app.asar 被占用，无法还原。
    echo.
    goto :fail
)

set "ASAR_PATH="
set "CFG=%USERPROFILE%\.zcode\zcode-token-usage-statusbar\config.json"
if exist "%CFG%" (
    rem Read asar_path with Python: a batch for /f split on ":" would
    rem cut "C:\..." down to just "C".
    for /f "usebackq delims=" %%a in (`%PY_CMD% -c "import json,sys; print(json.load(open(sys.argv[1],encoding='utf-8-sig')).get('asar_path',''))" "%CFG%" 2^>nul`) do (
        set "ASAR_PATH=%%a"
    )
)
if defined ASAR_PATH (
    set "ASAR_DIR=!ASAR_PATH:\app.asar=!"
    echo test>"!ASAR_DIR!\.zusage-write-test" 2>nul
    if errorlevel 1 (
        echo   [2/3] !ASAR_DIR! 不可写，需要管理员权限，正在提权重试...
        echo.
        echo   接下来会弹出 UAC 确认窗口，请点"是"。
        echo.
        powershell -NoProfile -ExecutionPolicy Bypass -Command ^
            "Start-Process -FilePath '%~f0' -Verb RunAs"
        goto :eof
    )
    del "!ASAR_DIR!\.zusage-write-test" >nul 2>&1
    echo   [2/3] 目标: !ASAR_PATH!
) else (
    echo   [2/3] 未找到配置文件，将自动查找 ZCode...
)

echo   [3/3] 正在卸载...
echo.
%PY_CMD% uninstall.py !REST!
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo   [x] 卸载失败（退出码 %RC%），上面的信息说明了原因。
    echo.
    echo       常见情况：
    echo         - ZCode 没完全退出：右键托盘图标退出后重试
    echo         - app.asar 被改过：见 README 的卸载一节
    echo.
    goto :fail
)

echo   卸载完成，请重新启动 ZCode。
echo.
pause
exit /b 0

rem ===================================================================
:find_python
set "PY_CMD="
py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py -3"
    exit /b 0
)
python -c "import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
    exit /b 0
)
if exist "%PY_USER_DIR%\python.exe" (
    set "PY_CMD="%PY_USER_DIR%\python.exe""
    exit /b 0
)
exit /b 0

rem ===================================================================
:fail
pause
exit /b 1
