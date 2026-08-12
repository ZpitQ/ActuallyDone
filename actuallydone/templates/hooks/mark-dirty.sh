#!/bin/bash
# afterFileEdit 钩子：改到受监视代码树就记一笔。
#
# 这个钩子没有否决权（文档未定义 afterFileEdit 的输出字段），只用它的副作用：
# 往 <state_dir>/dirty 追加改过的文件，供 stop 钩子告诉 Agent「你改了什么」。
# 是否算「过期」由树哈希判定，本标记只是给人看的线索，不是判据。
#
# 无论发生什么都输出 {} 并退出 0：钩子不该把会话卡死。
#
# 由 adone install 生成。

set -uo pipefail

ROOT="${CURSOR_PROJECT_DIR:-$PWD}"
STATE_DIR="{{STATE_DIR}}"
WATCH_ROOTS=({{WATCH_ROOTS}})
WATCH_EXTS=({{WATCH_EXTS}})

payload="$(cat 2>/dev/null || true)"
file="$(printf '%s' "$payload" | jq -r '.file_path // empty' 2>/dev/null || true)"

if [ -n "$file" ]; then
  rel="${file#"$ROOT"/}"
  in_root=0
  for r in "${WATCH_ROOTS[@]}"; do
    case "$rel" in "$r"/*) in_root=1; break;; esac
  done
  if [ "$in_root" = "1" ]; then
    for e in "${WATCH_EXTS[@]}"; do
      case "$rel" in *"$e")
        mkdir -p "$ROOT/$STATE_DIR" 2>/dev/null || true
        printf '%s\n' "$rel" >>"$ROOT/$STATE_DIR/dirty" 2>/dev/null || true
        break;;
      esac
    done
  fi
fi

echo '{}'
