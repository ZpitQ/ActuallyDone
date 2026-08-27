@echo off
setlocal EnableExtensions
REM Cursor launches this path as the hook process. Do not prefix cmd /c in
REM hooks.json: that whole string becomes one executable name and never starts.
REM Do not name a Python file here. Real work is: adone.exe hook <this name>
set "NAME=%~n0"
set "ROOT=%CURSOR_PROJECT_DIR%"
if not defined ROOT set "ROOT=%CD%"
if not exist "%ROOT%\.adone" mkdir "%ROOT%\.adone" 2>nul
>>"%ROOT%\.adone\hook.log" echo %DATE% %TIME% %NAME% launched

set "ADONE={{ADONE_CMD_WIN}}"
if defined ADONE if exist "%ADONE%" goto :run

if exist "%USERPROFILE%\.local\bin\adone.exe" (
  set "ADONE=%USERPROFILE%\.local\bin\adone.exe"
  goto :run
)
if exist "%LOCALAPPDATA%\pipx\venvs\actuallydone\Scripts\adone.exe" (
  set "ADONE=%LOCALAPPDATA%\pipx\venvs\actuallydone\Scripts\adone.exe"
  goto :run
)
if exist "%USERPROFILE%\.local\pipx\venvs\actuallydone\Scripts\adone.exe" (
  set "ADONE=%USERPROFILE%\.local\pipx\venvs\actuallydone\Scripts\adone.exe"
  goto :run
)
if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" (
  "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" -3 -m actuallydone hook %NAME%
  exit /b %ERRORLEVEL%
)

if /i "%NAME%"=="gate-guard" (
  echo {"followup_message":"【完成门禁没跑成】钩子找不到 adone.exe。把 pipx 的 Scripts 加进 PATH，或重跑 adone install --hooks-only --force。这不等于门禁通过。"}
) else (
  echo {}
)
exit /b 0

:run
REM Nested .cmd must be call'd, otherwise this script is replaced and never returns.
if /i "%ADONE:~-4%"==".cmd" call "%ADONE%" hook %NAME%
if /i not "%ADONE:~-4%"==".cmd" "%ADONE%" hook %NAME%
exit /b %ERRORLEVEL%
