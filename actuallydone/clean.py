"""拆掉当前项目里的 ActuallyDone，和 `adone init` / `install --with-hooks` 配套。

拆完之后：没有 adone.toml，钩子不再登记，pre-commit 不再拦提交。
`adone doctor` / `gate` 会说找不到配置——这就是「不再发挥作用」。
别人写在 hooks.json 里的钩子、以及不是我们渲染的技能，一律留下。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import CONFIG_NAME, Config, ConfigError, find_root
from .install import (GENERIC_SKILLS, LEGACY_SCRIPTS, OUR_EXES, OUR_LAUNCHERS,
                      OUR_SCRIPTS, PRE_COMMIT_MARK, PROJECT_SKILLS,
                      git_pre_commit_path, strip_qoder_entry)


def _rel(root: Path, p: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(p)


def _ours_tokens() -> tuple[str, ...]:
    return (*OUR_SCRIPTS, *OUR_LAUNCHERS, *OUR_EXES, *LEGACY_SCRIPTS,
            "hook mark-dirty", "hook gate-guard", "hook commit-guard")


def _strip_hooks_json(data: dict) -> tuple[dict | None, int]:
    """去掉我们的登记。返回 (写回的对象或 None 表示整份可删, 留下的外来条目数)。"""
    events = dict(data.get("hooks") or {})
    mine = _ours_tokens()
    kept = 0
    out_events: dict = {}
    for event, hooks in events.items():
        foreign = [h for h in (hooks or [])
                   if not any(s in str(h.get("command", "")) for s in mine)]
        kept += len(foreign)
        if foreign:
            out_events[event] = foreign
    if not out_events:
        return None, kept
    out = dict(data)
    out["hooks"] = out_events
    return out, kept


def _strip_qoder_settings(data: dict) -> tuple[dict | None, int]:
    """去掉 .qoder/settings.json 里我们的条目，留下别人的。"""
    events = dict(data.get("hooks") or {})
    kept = 0
    out_events: dict = {}
    for event, entries in events.items():
        foreign = []
        for h in (entries or []):
            stripped = strip_qoder_entry(h)
            if stripped is not None:
                foreign.append(stripped)
        kept += len(foreign)
        if foreign:
            out_events[event] = foreign
    rest = {k: v for k, v in data.items() if k != "hooks"}
    if not out_events:
        if rest:
            return rest, kept
        return None, kept
    out = dict(data)
    out["hooks"] = out_events
    return out, kept


def _plan(root: Path, cfg: Config | None) -> list[tuple[str, Path, str]]:
    """返回 (动作, 路径, 给人看的说明)。动作：delete / rewrite / empty-dir。"""
    items: list[tuple[str, Path, str]] = []
    toml = root / CONFIG_NAME
    if toml.is_file():
        items.append(("delete", toml, "配置（没有它门禁不会跑）"))
    bak = root / (CONFIG_NAME + ".bak")
    if bak.is_file():
        items.append(("delete", bak, "探测合并留下的备份"))

    state = cfg.state_dir if cfg else root / ".adone"
    if state.exists():
        items.append(("delete", state, "回执、dirty、基线"))

    material = cfg.material_dir if cfg else root / "adone"
    if material.exists():
        items.append(("delete", material, "验收契约与需求台账目录"))

    skills = cfg.skills_dir if cfg else root / ".cursor" / "skills"
    for name in (*GENERIC_SKILLS, *PROJECT_SKILLS):
        d = skills / name
        if d.exists():
            items.append(("delete", d, f"技能 {name}"))

    qoder_skills = root / ".qoder" / "skills"
    for name in (*GENERIC_SKILLS, *PROJECT_SKILLS):
        d = qoder_skills / name
        if d.exists():
            items.append(("delete", d, f"Qoder 技能 {name}"))

    hooks_json = root / ".cursor" / "hooks.json"
    if hooks_json.is_file():
        data = {}
        try:
            raw = json.loads(hooks_json.read_text(encoding="utf-8"))
            data = raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            data = {}
        stripped, kept = _strip_hooks_json(data)
        if stripped is None and data.get("hooks"):
            items.append(("delete", hooks_json, "钩子登记（里面只剩我们的条目）"))
        elif stripped is not None:
            ours_were_there = json.dumps(data, ensure_ascii=False) != json.dumps(
                stripped, ensure_ascii=False)
            if ours_were_there:
                items.append(("rewrite", hooks_json,
                              f"钩子登记（去掉 adone，留下 {kept} 条别人的）"))

    qoder_settings = root / ".qoder" / "settings.json"
    if qoder_settings.is_file():
        data = {}
        try:
            raw = json.loads(qoder_settings.read_text(encoding="utf-8"))
            data = raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            data = {}
        stripped, kept = _strip_qoder_settings(data)
        if stripped is None:
            if data.get("hooks"):
                items.append(("delete", qoder_settings, "Qoder 钩子登记（里面只剩我们的条目）"))
        elif stripped is not None:
            ours_were_there = json.dumps(data, ensure_ascii=False) != json.dumps(
                stripped, ensure_ascii=False)
            if ours_were_there:
                items.append(("rewrite", qoder_settings,
                              f"Qoder 钩子登记（去掉 adone，留下 {kept} 条别人的）"))

    hooks_dir = root / ".cursor" / "hooks"
    for name in (*OUR_LAUNCHERS, *OUR_EXES, *OUR_SCRIPTS, *LEGACY_SCRIPTS):
        p = hooks_dir / name
        if p.is_file():
            items.append(("delete", p, "钩子启动器"))

    pre, _, _ = git_pre_commit_path(root)
    if pre is not None and pre.is_file():
        text = pre.read_text(encoding="utf-8", errors="replace")
        if PRE_COMMIT_MARK in text:
            items.append(("delete", pre, "本机 git pre-commit"))
    return items


def _rm(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        for child in sorted(path.iterdir(), reverse=True):
            _rm(child)
        path.rmdir()
    else:
        path.unlink(missing_ok=True)


def _rm_empty_parents(path: Path, stop: Path) -> None:
    cur = path if path.is_dir() else path.parent
    stop = stop.resolve()
    while cur.resolve() != stop:
        try:
            next(cur.iterdir())
            return
        except StopIteration:
            parent = cur.parent
            try:
                cur.rmdir()
            except OSError:
                return
            cur = parent
        except OSError:
            return


def _load_or_none(root: Path) -> Config | None:
    try:
        return Config.load(root)
    except ConfigError:
        return None


def cmd_clean(args) -> int:
    start = Path(args.root).resolve() if getattr(args, "root", None) else None
    root = find_root(start) or (start or Path.cwd()).resolve()
    cfg = _load_or_none(root) if (root / CONFIG_NAME).is_file() else None
    items = _plan(root, cfg)
    if not items:
        print(f"{root} 里没有 ActuallyDone 的配置或钩子。")
        return 0

    print(f"将从 {root} 拆除 ActuallyDone（之后门禁和钩子都不会再跑）：")
    for _, path, why in items:
        print(f"  - {_rel(root, path)}  {why}")

    if getattr(args, "dry_run", False):
        print("（演练，没有落盘）")
        return 0

    if not getattr(args, "yes", False) and sys.stdin.isatty():
        ans = input("\n继续？[y/N] ").strip().lower()
        if ans not in ("y", "yes", "是"):
            print("已取消。")
            return 1

    n = 0
    for action, path, _ in items:
        parent = path.parent
        if action == "rewrite":
            data = json.loads(path.read_text(encoding="utf-8"))
            if path.name == "settings.json" and path.parent.name == ".qoder":
                stripped, _ = _strip_qoder_settings(data)
            else:
                stripped, _ = _strip_hooks_json(data)
            if stripped is None:
                path.unlink(missing_ok=True)
                print(f"  删除 {_rel(root, path)}")
                _rm_empty_parents(parent, root)
            else:
                path.write_text(json.dumps(stripped, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
                print(f"  改写 {_rel(root, path)}")
        else:
            _rm(path)
            print(f"  删除 {_rel(root, path)}")
            _rm_empty_parents(parent, root)
        n += 1
    print(f"\n完成：拆掉 {n} 处。这里不再有完成门禁。要重新接入跑 adone init。")
    return 0
