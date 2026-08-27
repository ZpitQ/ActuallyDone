#!/usr/bin/env python3
"""stop 钩子：Agent 想收工时，先看门禁答不答应。

stop 没有否决权——官方文档给的唯一输出是 followup_message，且它会作为下一条用户消息
自动提交。所以这里的形态不是「禁止结束」，而是「把 Agent 推回去把活干完」。
loop_limit 在 hooks.json 里设为 3，脚本自己再兜一层，避免无限回推。

钩子从不阻断会话，但也从不**安静地**放行：门禁跑不起来时，它推一条「门禁没跑成」
回去，而不是输出空对象。空对象在终端里和「门禁通过」长得一模一样，
而「检查失效」被误读成「检查通过」正是这个工具要防的事。

由 adone install 生成。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

MAX_LOOPS = 3
ADONE_ENTRY = {{ADONE_ENTRY}}   # 仓库内免安装入口的相对路径；空串表示没有 vendor 版
ADONE_CMD = {{ADONE_CMD}}       # 安装时 which adone 的绝对路径；空串表示装的时候就没有
STATE_DIR = "{{STATE_DIR}}"
SKILLS_DIR = "{{SKILLS_DIR}}"

# pipx / pip --user 常见落点。钩子进程的 PATH 由客户端决定，实测拿到过既不带
# ~/.local/bin 也不带 /opt/homebrew/bin 的环境，所以 PATH 找不到时还得自己翻一遍
FALLBACK_DIRS = (
    "~/.local/bin",
    "~/.local/pipx/venvs/actuallydone/bin",
    "/opt/homebrew/bin",
    "/usr/local/bin",
    # Windows：venv 的脚本目录叫 Scripts，pipx 默认装到 ~/.local/bin 但也可能在这
    "~/.local/pipx/venvs/actuallydone/Scripts",
    "~/AppData/Roaming/Python/Scripts",
    "~/AppData/Local/Programs/Python/Scripts",
)
# Windows 上装出来的是 adone.exe，按裸名去 os.access 一个都对不上
EXE_NAMES = ("adone", "adone.exe", "adone.cmd", "adone.bat")


def log(root: str, msg: str) -> None:
    """留一行调用痕迹：否则钩子有没有被触发过完全不可观测。"""
    try:
        path = os.path.join(root, STATE_DIR, "hook.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} stop {msg}\n")
    except Exception:
        pass


def resolve_adone(root: str) -> list[str] | None:
    """按可靠性从高到低找 adone，返回命令前缀；一个都找不到返回 None。

    仓库内入口排第一：它跟着代码走，不受这台机器装没装包影响。
    """
    entry = os.path.join(root, ADONE_ENTRY) if ADONE_ENTRY else ""
    if entry and os.path.isfile(entry):
        # 解释器在运行时才定：把安装时的 sys.executable 烧进来，换台机器就跑不动了。
        # 入口自己会在解释器太老时换一个够新的
        return [sys.executable, entry]
    if ADONE_CMD and os.path.isfile(ADONE_CMD):
        return [ADONE_CMD]
    on_path = shutil.which("adone")   # which 会按 PATHEXT 补出 .exe / .cmd
    if on_path:
        return [on_path]
    for d in FALLBACK_DIRS:
        for name in EXE_NAMES:
            cand = os.path.join(os.path.expanduser(d), name)
            if os.path.isfile(cand):
                return [cand]
    return None


def out(obj: dict, root: str | None = None, msg: str = "") -> int:
    if root:
        log(root, msg)
    print(json.dumps(obj, ensure_ascii=False))
    return 0


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}

    root = os.environ.get("CURSOR_PROJECT_DIR") or os.getcwd()
    status = payload.get("status")
    loops = int(payload.get("loop_count") or 0)

    # 用户中断或出错收场时不纠缠，只在 Agent 自认为干完了的时候才拦
    if status not in (None, "completed"):
        return out({}, root, f"status={status} 不拦")
    if loops >= MAX_LOOPS:
        return out({}, root, f"loop_count={loops} 到上限，放行")

    prefix = resolve_adone(root)
    if prefix is None:
        return out({"followup_message": "\n".join([
            "【完成门禁没跑成】这台机器上找不到 adone：",
            "",
            f"- 仓库内入口：{ADONE_ENTRY or '（没有 vendor 版）'}",
            f"- 安装时记下的路径：{ADONE_CMD or '（装钩子时就没有）'}",
            f"- 钩子进程的 PATH：{os.environ.get('PATH', '(空)')}",
            "",
            "这不等于门禁通过——现在没有任何证据表明活干完了。先把 adone 装回来"
            "（`pipx install git+https://github.com/iamharvey/ActuallyDone.git`），"
            "再 `adone install --hooks-only --force` 重渲钩子，然后才谈完成。",
        ])}, root, "找不到 adone，已回推")

    argv = prefix + ["gate", "check", "--json"]
    proc = None
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, cwd=root, timeout=120)
        data = json.loads(proc.stdout)
    except Exception as e:
        why = (proc.stderr or proc.stdout).strip()[-400:] if proc else str(e)
        return out({"followup_message": "\n".join([
            f"【完成门禁没跑成】`{' '.join(argv)}` 没能给出结果（{type(e).__name__}）：",
            "", why or str(e), "",
            "这不等于门禁通过——现在没有任何证据表明活干完了。"
            "先把门禁修到能跑（多半是配置或入口路径的问题），再谈完成。",
        ])}, root, f"check 跑不起来（{type(e).__name__}: {e}），已回推")

    if data.get("ok"):
        return out({}, root, f"门禁通过（回执 {data.get('receipt_id')}），放行")

    problems = data.get("problems") or []
    lines = ["【完成门禁未通过】以下问题在你宣称完成之前必须处理：", ""]
    lines += [f"{i}. {p}" for i, p in enumerate(problems, 1)]
    lines += [
        "",
        f"按 {SKILLS_DIR}/completion-gate/SKILL.md 处理：修掉问题后重跑门禁，"
        f"拿到与当前代码哈希一致的新回执，再收工。",
        "如果确实无法通过（例如本机缺依赖、门禁跑不起来），不要绕过，"
        "直接告诉我卡在哪一步、看到什么输出。",
    ]
    return out({"followup_message": "\n".join(lines)}, root,
               f"未通过（{len(problems)} 个问题，loop_count={loops}），已回推")


if __name__ == "__main__":
    sys.exit(main())
