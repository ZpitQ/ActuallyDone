"""Cursor 钩子的实现。由 `adone hook <名>` 调用，不在 .cursor/hooks/ 里放 .py。

Windows 上 .cursor/hooks/*.py 会被当成「要打开的文件」：Cursor 自己就是 .py
的默认应用，stop 一触发就弹出 gate-guard.py，脚本一行都没跑。
钩子目录里只留 .cmd，逻辑全部在本模块。
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import Config, ConfigError, find_root

MAX_LOOPS = 3


def _payload() -> dict:
    raw = sys.stdin.read()
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    try:
        return json.loads(raw or "{}")
    except (ValueError, OSError):
        return {}


def _root() -> Path:
    start = Path(os.environ.get("CURSOR_PROJECT_DIR") or os.getcwd())
    return find_root(start) or start.resolve()


def _log(cfg: Config | None, event: str, msg: str, root: Path | None = None) -> None:
    try:
        base = cfg.state_dir if cfg is not None else (root or _root()) / ".adone"
        base.mkdir(parents=True, exist_ok=True)
        with open(base / "hook.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {event} {msg}\n")
    except OSError:
        pass


def _emit(obj: dict) -> int:
    """把钩子结果写到 stdout。Windows 上必须立刻刷出，并多等一小会儿。

    Cursor 在 Windows 上经过 PowerShell 收 stdout：进程一退出就当收完，
    管道里还没到的字节会被丢掉。Execution Log 里变成 `{}`，Agent 窗口
    看不到 followup_message——官方承认这是他们的 bug。
    中文走系统代码页（cp936）时，Node 端按 UTF-8 解析也会失败，同样像没回推。
    """
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n"
    buf = getattr(sys.stdout, "buffer", None)
    if buf is not None:
        buf.write(data)
        buf.flush()
    else:
        sys.stdout.write(data.decode("utf-8"))
        sys.stdout.flush()
    if obj.get("followup_message") and os.name == "nt":
        time.sleep(0.2)
    return 0


def _load() -> tuple[Config | None, Path]:
    root = _root()
    try:
        return Config.load(root), root
    except ConfigError:
        return None, root


def cmd_mark_dirty(_args=None) -> int:
    cfg, root = _load()
    try:
        payload = _payload()
    except Exception as e:
        _log(cfg, "afterFileEdit", f"读不动 payload（{type(e).__name__}），改动没记下", root)
        return _emit({})

    path = payload.get("file_path") or ""
    if not path:
        _log(cfg, "afterFileEdit", "payload 里没有 file_path，改动没记下", root)
        return _emit({})

    base = cfg.root if cfg is not None else root
    try:
        rel = os.path.relpath(os.path.realpath(path), os.path.realpath(base))
    except (OSError, ValueError):
        return _emit({})
    rel = rel.replace(os.sep, "/")
    if rel.startswith("../"):
        return _emit({})

    roots = (cfg.get("gate.watch_roots") or ["."]) if cfg else ["."]
    exts = (cfg.get("gate.watch_exts") or []) if cfg else []
    if _watched(rel, roots, exts):
        try:
            dest = (cfg.dirty if cfg is not None else root / ".adone" / "dirty")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "a", encoding="utf-8") as f:
                f.write(rel + "\n")
        except OSError as e:
            _log(cfg, "afterFileEdit", f"写 dirty 失败（{e}）：{rel}", root)
    return _emit({})


def _watched(rel: str, roots: list, exts: list) -> bool:
    if exts and not any(rel.endswith(e) for e in exts):
        return False
    for r in roots:
        r = str(r).rstrip("/")
        if r in ("", "."):
            return True
        if rel == r or rel.startswith(f"{r}/"):
            return True
    return False


def cmd_gate_guard(_args=None) -> int:
    cfg, root = _load()
    payload = _payload()
    status = payload.get("status")
    loops = int(payload.get("loop_count") or 0)

    if status not in (None, "completed"):
        _log(cfg, "stop", f"status={status} 不拦", root)
        return _emit({})
    if loops >= MAX_LOOPS:
        _log(cfg, "stop", f"loop_count={loops} 到上限，放行", root)
        return _emit({})

    if cfg is None:
        _log(cfg, "stop", "找不到 adone.toml，已回推", root)
        return _emit({"followup_message": "\n".join([
            "【完成门禁没跑成】从当前目录往上找不到 adone.toml。",
            "",
            "这不等于门禁通过。把 Cursor 工作区开在放 adone.toml 的那一层"
            "（或它的子目录），再谈完成。",
        ])})

    try:
        from .gate import collect_check
        data = collect_check(cfg)
    except Exception as e:
        _log(cfg, "stop", f"check 跑不起来（{type(e).__name__}: {e}），已回推", root)
        return _emit({"followup_message": "\n".join([
            f"【完成门禁没跑成】gate check 没能给出结果（{type(e).__name__}）：",
            "", str(e), "",
            "这不等于门禁通过——现在没有任何证据表明活干完了。",
        ])})

    if data.get("ok"):
        _log(cfg, "stop", f"门禁通过（回执 {data.get('receipt_id')}），放行")
        return _emit({})

    problems = data.get("problems") or []
    skills = cfg.get("project.skills_dir") or ".cursor/skills"
    lines = ["【完成门禁未通过】以下问题在你宣称完成之前必须处理：", ""]
    lines += [f"{i}. {p}" for i, p in enumerate(problems, 1)]
    lines += [
        "",
        f"按 {skills}/completion-gate/SKILL.md 处理：修掉问题后重跑门禁，"
        f"拿到与当前代码哈希一致的新回执，再收工。",
        "如果确实无法通过（例如本机缺依赖、门禁跑不起来），不要绕过，"
        "直接告诉我卡在哪一步、看到什么输出。",
    ]
    _log(cfg, "stop", f"未通过（{len(problems)} 个问题，loop_count={loops}），已回推")
    return _emit({"followup_message": "\n".join(lines)})


HOOKS = {
    "mark-dirty": cmd_mark_dirty,
    "gate-guard": cmd_gate_guard,
}


def cmd_hook(args) -> int:
    fn = HOOKS.get(args.hook)
    if fn is None:
        print(f"不认识的钩子：{args.hook}（可用：{'、'.join(HOOKS)}）", file=sys.stderr)
        return 2
    return fn(args)
