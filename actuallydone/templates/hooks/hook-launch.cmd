:<<"::::"
@echo off
setlocal EnableExtensions
REM 中文 Windows 默认 GBK。门禁 print Maven 输出时会 UnicodeEncodeError。
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
REM cmd.exe branch. Cursor on Windows may instead run this file with Git Bash;
REM that path is the shell block after the closing delimiter.
set "NAME=%~n0"
set "ROOT=%CURSOR_PROJECT_DIR%"
if not defined ROOT set "ROOT=%CD%"
if not exist "%ROOT%\.adone" mkdir "%ROOT%\.adone" 2>nul
>>"%ROOT%\.adone\hook.log" echo %DATE% %TIME% %NAME% launched via cmd
set "ADONE={{ADONE_CMD_WIN}}"
if defined ADONE if exist "%ADONE%" goto :run
if exist "%USERPROFILE%\.local\bin\adone.exe" set "ADONE=%USERPROFILE%\.local\bin\adone.exe" & goto :run
if exist "%LOCALAPPDATA%\pipx\venvs\actuallydone\Scripts\adone.exe" set "ADONE=%LOCALAPPDATA%\pipx\venvs\actuallydone\Scripts\adone.exe" & goto :run
if exist "%USERPROFILE%\.local\pipx\venvs\actuallydone\Scripts\adone.exe" set "ADONE=%USERPROFILE%\.local\pipx\venvs\actuallydone\Scripts\adone.exe" & goto :run
if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" (
  "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" -3 -m actuallydone hook %NAME%
  exit /b %ERRORLEVEL%
)
if /i "%NAME%"=="gate-guard" echo {"followup_message":"【相关用例没跑成】钩子找不到 adone.exe。重跑 adone install --hooks-only --force。只跑 gate run --changed，不要跑全量。"}
if /i "%NAME%"=="commit-guard" echo {"permission":"deny","user_message":"钩子找不到 adone.exe，不能提交。重跑 adone install --hooks-only --force，再跑 adone gate run（全量）。"}
if /i not "%NAME%"=="gate-guard" if /i not "%NAME%"=="commit-guard" echo {}
exit /b 0
:run
if /i "%ADONE:~-4%"==".cmd" call "%ADONE%" hook %NAME%
if /i not "%ADONE:~-4%"==".cmd" "%ADONE%" hook %NAME%
exit /b %ERRORLEVEL%
::::
# Git Bash / sh branch. 1.3.6's pure-cmd file died on `@echo off` and never wrote hook.log.
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
NAME=$(basename "$0" .cmd)
ROOT="${CURSOR_PROJECT_DIR:-$PWD}"
mkdir -p "$ROOT/.adone" 2>/dev/null || true
echo "$(date +%Y-%m-%dT%H:%M:%S) $NAME launched via sh" >> "$ROOT/.adone/hook.log"
ADONE_WIN="{{ADONE_CMD_WIN}}"
run_adone() {
  if [ -n "$1" ] && [ -f "$1" ]; then
    exec "$1" hook "$NAME"
  fi
}
run_adone "$ADONE_WIN"
case "$ADONE_WIN" in
  [A-Za-z]:*)
    drive=$(printf '%s' "$ADONE_WIN" | cut -c1 | tr 'A-Z' 'a-z')
    rest=$(printf '%s' "$ADONE_WIN" | cut -c3- | tr '\\' '/')
    run_adone "/$drive$rest"
    ;;
esac
for cand in \
  "$HOME/.local/bin/adone.exe" \
  "$HOME/.local/bin/adone" \
  "$LOCALAPPDATA/pipx/venvs/actuallydone/Scripts/adone.exe"
do
  run_adone "$cand"
done
command -v adone >/dev/null 2>&1 && exec adone hook "$NAME"
command -v py >/dev/null 2>&1 && exec py -3 -m actuallydone hook "$NAME"
command -v python >/dev/null 2>&1 && exec python -m actuallydone hook "$NAME"
if [ "$NAME" = "gate-guard" ]; then
  printf '%s\n' '{"followup_message":"【相关用例没跑成】钩子找不到 adone。重跑 adone install --hooks-only --force。只跑 gate run --changed，不要跑全量。"}'
elif [ "$NAME" = "commit-guard" ]; then
  printf '%s\n' '{"permission":"deny","user_message":"钩子找不到 adone，不能提交。重跑 adone install --hooks-only --force，再跑 adone gate run（全量）。"}'
else
  printf '%s\n' '{}'
fi
exit 0
