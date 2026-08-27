#!/usr/bin/env python3
"""afterFileEdit 钩子：改到受监视代码树就记一笔。

这个钩子没有否决权（文档未定义 afterFileEdit 的输出字段），只用它的副作用：
往 <state_dir>/dirty 追加改过的文件，供 stop 钩子告诉 Agent「你改了什么」。
是否算「过期」由树哈希判定，本标记只是给人看的线索，不是判据。

用 Python 而不是 bash：这个钩子早先是 .sh，在 Windows 上没有 bash 也没有 jq，
Cursor 起不动它，于是「Agent 改了代码却没人提醒」——而钩子失效的样子
和「一切正常」在终端里完全一样。adone 本身就是 Python，用它没有新依赖。

无论发生什么都输出 {} 并退出 0：钩子不该把会话卡死。但「什么都没记下」必须
在 hook.log 里留痕——一个永远为空的 dirty 和一个从没被改过的仓库长得一模一样。

由 adone install 生成。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

STATE_DIR = "{{STATE_DIR}}"
WATCH_ROOTS = {{WATCH_ROOTS_PY}}
WATCH_EXTS = {{WATCH_EXTS_PY}}


def log(root: str, msg: str) -> None:
    try:
        path = os.path.join(root, STATE_DIR, "hook.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} afterFileEdit {msg}\n")
    except OSError:
        pass


def watched(rel: str) -> bool:
    if not any(rel.endswith(e) for e in WATCH_EXTS):
        return False
    for r in WATCH_ROOTS:
        r = r.rstrip("/")
        # adone init 对单模块项目生成的就是 "."，那时整棵树都受监视
        if r in ("", "."):
            return True
        if rel == r or rel.startswith(f"{r}/"):
            return True
    return False


def main() -> int:
    root = os.environ.get("CURSOR_PROJECT_DIR") or os.getcwd()
    try:
        raw = sys.stdin.read()
        if raw.startswith("\ufeff"):   # Windows 上 Cursor 喂的 JSON 有时带 BOM
            raw = raw[1:]
        payload = json.loads(raw or "{}")
    except (ValueError, OSError) as e:
        log(root, f"读不动 payload（{type(e).__name__}），改动没记下")
        print("{}")
        return 0

    path = payload.get("file_path") or ""
    if not path:
        log(root, "payload 里没有 file_path，改动没记下")
        print("{}")
        return 0

    # Windows 上 payload 给的是反斜杠路径，受监视根用的是正斜杠，先统一
    try:
        rel = os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    except (OSError, ValueError):
        print("{}")
        return 0
    rel = rel.replace(os.sep, "/")
    if rel.startswith("../"):
        print("{}")   # 不在本仓库里的文件，不关我们的事
        return 0

    if watched(rel):
        try:
            d = os.path.join(root, STATE_DIR)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "dirty"), "a", encoding="utf-8") as f:
                f.write(rel + "\n")
        except OSError as e:
            log(root, f"写 dirty 失败（{e}）：{rel}")
    print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
