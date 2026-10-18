@echo off
rem ===================================================================
rem  Zcode-Status-TypeBar -- one-click install
rem
rem  双击本文件即可完成安装：
rem    1. 检查 Python 3，没有就用 winget 或官网静默装包自动装上
rem    2. 检查 ZCode 是否完全退出（没退出会提示，不会自动杀进程）
rem    3. 定位 app.asar，目录不可写时自动弹 UAC 提权重跑
rem    4. 运行 install.py 完成注入与 MCP 注册
rem
rem  可选参数原样透传给 install.py，例如：
rem    install.bat --skip-mcp
rem    install.bat "D:\Apps\ZCode\resources\app.asar"
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

set "PY_MINOR=3.12"
set "PY_FULL=3.12.10"
set "PY_URL=https://www.python.org/ftp/python/%PY_FULL%/python-%PY_FULL%-amd64.exe"
set "PY_USER_DIR=%LOCALAPPDATA%\Programs\Python\Python312"
set "TMP_EXE=%TEMP%\zusage-python-%RANDOM%.exe"

rem The first argument is this script's own app.asar path, passed back when
rem re-launching elevated. The rest go to install.py.
rem %* is expanded at parse time and is NOT affected by shift, so the
rem remaining arguments are rebuilt manually into REST.
set "ASAR_ARG="
set "REST="
if not "%~1"=="" set "ASAR_ARG=%~1"
if defined ASAR_ARG shift
:collect_args
if "%~1"=="" goto :args_done
set "REST=!REST! %1"
shift
goto :collect_args
:args_done

echo.
echo   Zcode-Status-TypeBar  安装程序
echo   ========================================
echo.

call :find_python
if not defined PY_CMD call :install_python
if not defined PY_CMD (
    echo.
    echo   [x] Python 安装失败。
    echo.
    echo       请手动安装 Python 3.8 或更新的 3.x：
    echo         https://www.python.org/downloads/windows/
    echo       安装时务必勾选 "Add python.exe to PATH"，然后重新双击本文件。
    echo.
    goto :fail
)
echo   [1/4] Python 就绪: !PY_CMD!

rem Use absolute System32 paths: with Git for Windows installed, the find.exe
rem on PATH is GNU find and would treat /I as a filename.
"%SystemRoot%\System32\tasklist.exe" /FI "IMAGENAME eq ZCode.exe" /NH 2>nul | "%SystemRoot%\System32\find.exe" /I "ZCode.exe" >nul
if not errorlevel 1 (
    echo.
    echo   [x] 检测到 ZCode 正在运行。
    echo.
    echo       请完全退出后再安装：
    echo         1. 关掉所有 ZCode 窗口
    echo         2. 在系统托盘（右下角隐藏图标里）右键 ZCode 图标，选择"退出"
    echo.
    echo       只关窗口是不够的，托盘进程还在时会占用文件导致安装失败。
    echo.
    goto :fail
)

call :locate_asar
if not defined ASAR_PATH (
    echo.
    echo   [x] 没有找到 ZCode 的 app.asar。
    echo.
    echo       请确认已安装 ZCode 桌面版。如果装在自定义目录，把 app.asar
    echo       的完整路径作为参数传入：
    echo         install.bat "D:\Apps\ZCode\resources\app.asar"
    echo.
    goto :fail
)

set "ASAR_DIR=!ASAR_PATH:\app.asar=!"
echo test>"%ASAR_DIR%\.zusage-write-test" 2>nul
if errorlevel 1 (
    echo   [2/4] !ASAR_DIR! 不可写，需要管理员权限，正在提权重试...
    echo.
    echo   接下来会弹出 UAC 确认窗口，请点"是"。
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "Start-Process -FilePath '%~f0' -ArgumentList '\"!ASAR_PATH!\"' -Verb RunAs"
    goto :eof
)
del "%ASAR_DIR%\.zusage-write-test" >nul 2>&1
echo   [2/4] ZCode: !ASAR_PATH!

echo   [3/4] 正在安装...
echo.
%PY_CMD% install.py --asar "!ASAR_PATH!" !REST!
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo   [x] 安装失败（退出码 %RC%），上面的信息说明了原因。
    echo.
    echo       常见情况：
    echo         - ZCode 没完全退出：右键托盘图标退出后重试
    echo         - 杀毒软件拦截：把本目录加白名单后重试
    echo         - 上次安装残留：先运行 uninstall.bat 再运行本文件
    echo.
    goto :fail
)

echo   [4/4] 完成
echo.
echo   接下来：
echo     1. 启动 ZCode，打开任意聊天会话
echo     2. 输入框下方会出现 token 用量状态条
echo     3. 点状态条右侧的齿轮可调整显示项和语言
echo.
echo   提示：ZCode 升级会覆盖 app.asar，升级后重新双击本文件即可恢复。
echo   卸载：双击 uninstall.bat
echo.
pause
exit /b 0

rem ===================================================================
rem  Locate Python 3.8+
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

rem ------------------------------------------------------------------
rem  Install Python
rem ------------------------------------------------------------------
:install_python
echo   正在准备 Python %PY_FULL%...
echo.
where winget >nul 2>&1
if not errorlevel 1 (
    echo   使用 winget 安装（可能需要十几秒到一两分钟，请耐心等待）...
    echo.
    winget install --id Python.Python.%PY_MINOR% -e --accept-package-agreements --accept-source-agreements --silent
    call :find_python
    if defined PY_CMD exit /b 0
)

echo   改用官网安装包（约 26 MB，静默安装）...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%TMP_EXE%' -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 (
    echo   [x] 下载失败，请检查网络后重试。
    del "%TMP_EXE%" >nul 2>&1
    exit /b 1
)
echo   下载完成，正在静默安装...
start "" /wait "%TMP_EXE%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
del "%TMP_EXE%" >nul 2>&1

call :find_python
exit /b 0

rem ===================================================================
rem  Locate app.asar (same priority as install.py)
rem ===================================================================
:locate_asar
set "ASAR_PATH="
if defined ASAR_ARG if exist "!ASAR_ARG!" (
    set "ASAR_PATH=!ASAR_ARG!"
    exit /b 0
)
if exist "%LOCALAPPDATA%\Programs\ZCode\resources\app.asar" (
    set "ASAR_PATH=%LOCALAPPDATA%\Programs\ZCode\resources\app.asar"
    exit /b 0
)
if exist "%LOCALAPPDATA%\ZCode\resources\app.asar" (
    set "ASAR_PATH=%LOCALAPPDATA%\ZCode\resources\app.asar"
    exit /b 0
)
if exist "%ProgramFiles%\ZCode\resources\app.asar" (
    set "ASAR_PATH=%ProgramFiles%\ZCode\resources\app.asar"
    exit /b 0
)
if exist "%ProgramFiles(x86)%\ZCode\resources\app.asar" (
    set "ASAR_PATH=%ProgramFiles(x86)%\ZCode\resources\app.asar"
    exit /b 0
)
exit /b 0

rem ===================================================================
:fail
echo.
pause
exit /b 1
