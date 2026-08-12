#!/bin/bash
# afterFileEdit 钩子：改到受监视代码树就记一笔。
#
# 这个钩子没有否决权（文档未定义 afterFileEdit 的输出字段），只用它的副作用：
# 往 <state_dir>/dirty 追加改过的文件，供 stop 钩子告诉 Agent「你改了什么」。
# 是否算「过期」由树哈希判定，本标记只是给人看的线索，不是判据。
#
# 无论发生什么都输出 {} 并退出 0：钩子不该把会话卡死。但「什么都没记下」必须
# 在 hook.log 里留痕——一个永远为空的 dirty 和一个从没被改过的仓库长得一模一样。
#
# 由 adone install 生成。

set -uo pipefail

ROOT="${CURSOR_PROJECT_DIR:-$PWD}"
STATE_DIR="{{STATE_DIR}}"
WATCH_ROOTS=({{WATCH_ROOTS}})
WATCH_EXTS=({{WATCH_EXTS}})

note() {
  # date 也可能不在 PATH 里（能走到这个函数，说明这台机器的环境已经很奇怪了），
  # 没时间戳也要把话说出来
  ts="$(date +%Y-%m-%dT%H:%M:%S 2>/dev/null || true)"
  mkdir -p "$ROOT/$STATE_DIR" 2>/dev/null || true
  printf '%s afterFileEdit %s\n' "${ts:-?}" "$1" \
    >>"$ROOT/$STATE_DIR/hook.log" 2>/dev/null || true
}

# 用内建 read 而不是 cat 读 stdin：cat 也在 PATH 上，PATH 一坏连 payload 都拿不到，
# 那时连「我没能记下改动」这句话都发不出来
payload=""
IFS= read -r -d '' payload 2>/dev/null || true

# jq 不是每台机器都有。没有它就用 python3；两个都没有时记一笔，不装作没事发生
file=""
if [ -n "$payload" ]; then
  if command -v jq >/dev/null 2>&1; then
    file="$(printf '%s' "$payload" | jq -r '.file_path // empty' 2>/dev/null || true)"
  elif command -v python3 >/dev/null 2>&1; then
    file="$(printf '%s' "$payload" | python3 -c \
      'import json,sys; print(json.load(sys.stdin).get("file_path") or "")' 2>/dev/null || true)"
  else
    note "既没有 jq 也没有 python3，解析不了 payload，改动没记下"
  fi
fi

if [ -n "$file" ]; then
  rel="${file#"$ROOT"/}"
  case "$rel" in
    /*) rel="" ;;   # 不在本仓库里的文件，不关我们的事
  esac
fi

if [ -n "${rel:-}" ]; then
  in_root=0
  for r in "${WATCH_ROOTS[@]}"; do
    r="${r%/}"
    # adone init 对单模块项目生成的就是 "."，那时整棵树都受监视。
    # 早先只按 "$r"/* 匹配，"." 一个文件都匹配不上，dirty 于是永远为空
    if [ -z "$r" ] || [ "$r" = "." ]; then
      in_root=1
      break
    fi
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
