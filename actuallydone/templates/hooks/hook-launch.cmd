@echo off
setlocal EnableExtensions
REM Windows entry for Cursor hooks. command must start with cmd.
REM Do not name any Python script file here — Windows opens it in the editor.
REM Real work: adone hook <this filename>
set "NAME=%~n0"
set "ADONE={{ADONE_CMD_WIN}}"

if defined ADONE if exist "%ADONE%" (
  "%ADONE%" hook %NAME%
  exit /b %ERRORLEVEL%
)
where adone >nul 2>&1 && (
  adone hook %NAME%
  exit /b %ERRORLEVEL%
)
where py >nul 2>&1 && (
  py -3 -m actuallydone hook %NAME%
  exit /b %ERRORLEVEL%
)
for /f "delims=" %%I in ('where python 2^>nul') do (
  echo %%I | find /i "WindowsApps" >nul || (
    "%%I" -m actuallydone hook %NAME%
    exit /b %ERRORLEVEL%
  )
)
if /i "%NAME%"=="gate-guard" (
  echo {"followup_message":"【完成门禁没跑成】钩子找不到 adone / Python。装好后重跑 adone install --hooks-only --force。这不等于门禁通过。"}
) else (
  echo {}
)
exit /b 0
