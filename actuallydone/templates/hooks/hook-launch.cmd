@echo off
setlocal EnableExtensions
REM Cursor 在 Windows 上把 hooks.json 的 command 当「要启动的程序」。
REM 登记 .py 时，系统按文件关联用编辑器打开它——每次弹出 gate-guard.py，
REM 脚本根本没跑，Agent 改完代码没人提醒。
REM 这个 .cmd 才是 Windows 认的可执行文件；它找到解释器再去跑同名的 .py。
REM stdin 原样传下去（Cursor 用它喂 JSON）。
set "SCRIPT=%~dpn0.py"
if not exist "%SCRIPT%" (
  echo {}
  exit /b 0
)

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  for /f "delims=" %%I in ('where python 2^>nul') do (
    echo %%I | find /i "WindowsApps" >nul || (
      set "PY=%%I"
      goto :run
    )
  )
)
if not defined PY where python3 >nul 2>&1 && set "PY=python3"
if not defined PY (
  if /i "%~n0"=="gate-guard" (
    echo {"followup_message":"【完成门禁没跑成】这台机器上找不到 Python，钩子起不来。装 Python 3.11+（不要用微软商店那个会打开应用商店的 python 别名）后重跑 adone install --hooks-only --force。"}
  ) else (
    echo {}
  )
  exit /b 0
)

:run
%PY% "%SCRIPT%"
exit /b %ERRORLEVEL%
