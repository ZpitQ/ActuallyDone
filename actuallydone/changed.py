"""开发中按改动文件跑相关用例。不写 latest.json，也不改步骤 argv。

`gate run --changed` 与 stop 钩子共用这一份。全量回执仍只由 `gate run` 产出。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from .config import Config
from .gate import judge_step, read_dirty, run_step


def changed_paths(cfg: Config, paths: list[str] | None = None) -> list[str]:
    """优先用调用方给出的名单，其次 `.adone/dirty`，再退到 `git diff`。"""
    if paths:
        return _uniq(paths)
    dirty = read_dirty(cfg)
    if dirty:
        return dirty
    return git_diff_names(cfg.root)


def git_diff_names(root: Path) -> list[str]:
    """已跟踪改动、暂存区、未跟踪新文件。新文件只靠 dirty 会漏掉。"""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            cwd=root, capture_output=True, text=True, errors="replace",
            timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    seen: list[str] = []
    for ln in proc.stdout.splitlines():
        if len(ln) < 4:
            continue
        path = ln[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[-1]
        rel = path.strip().strip('"').replace("\\", "/")
        if rel and rel not in seen:
            seen.append(rel)
    return seen


def file_hashes(cfg: Config, rels: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in rels:
        p = cfg.root / rel
        if not p.is_file():
            continue
        try:
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        except OSError:
            continue
    return out


def same_as_last_ok_partial(cfg: Config, files: list[str]) -> bool:
    """上一轮 --changed 已通过，且这些文件内容没再变。"""
    if not files or not cfg.partial.exists():
        return False
    try:
        data = json.loads(cfg.partial.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not data.get("ok") or data.get("kind") != "changed":
        return False
    prev = data.get("file_hashes") or {}
    now = file_hashes(cfg, files)
    return now == prev and set(files) == set(prev)


def pick_test_adapter(cfg: Config):
    from .adapters import get
    for spec in cfg.get("gate.step") or []:
        if spec.get("kind") == "test" and spec.get("adapter"):
            return get(spec["adapter"], cfg.root)
    return get(cfg.get("tests.adapter") or "", cfg.root)


def _test_cwd(cfg: Config) -> str:
    for spec in cfg.get("gate.step") or []:
        if spec.get("kind") == "test":
            return spec.get("cwd") or "."
    return "."


def _uniq(paths: list[str]) -> list[str]:
    out: list[str] = []
    for p in paths:
        rel = str(p).strip().replace("\\", "/")
        if rel and rel not in out:
            out.append(rel)
    return out


def run_changed(cfg: Config, paths: list[str] | None = None, *,
                quiet: bool = False) -> dict:
    """跑相关用例，只写 `.adone/partial.json`。成功时清 dirty。"""
    files = changed_paths(cfg, paths)
    if not files:
        if not quiet:
            print("没有改动文件（dirty 与 git diff 都空），跳过相关用例")
        return {"ok": True, "problems": [], "files": [], "tests": [],
                "skipped": "no-changes"}

    ad = pick_test_adapter(cfg)
    names = ad.related_tests(files)
    if names is None:
        msg = (f"适配器「{ad.name}」不会按文件找相关用例。"
               f"对着这些文件写一条测试再继续，不要跑全量门禁："
               f"{'、'.join(files[:8])}"
               + ("…" if len(files) > 8 else ""))
        _write_partial(cfg, ok=False, files=files, tests=None, argv=None,
                       note=msg)
        if not quiet:
            print(msg)
        return {"ok": False, "problems": [msg], "files": files, "tests": None,
                "unassessed": True}

    if not names:
        msg = (f"找不到与这些文件相关的用例，写一条再继续（不要跑全量）："
               f"{'、'.join(files[:8])}"
               + ("…" if len(files) > 8 else ""))
        _write_partial(cfg, ok=False, files=files, tests=[], argv=None,
                       note=msg)
        if not quiet:
            print(msg)
        return {"ok": False, "problems": [msg], "files": files, "tests": [],
                "unassessed": False}

    argv = ad.related_test_argv(names)
    if argv is None:
        msg = (f"找到相关用例 {'、'.join(names[:8])}，"
               f"但适配器「{ad.name}」拼不出只跑它们的命令。"
               f"写一条能单独跑的用例再继续，不要跑全量门禁")
        _write_partial(cfg, ok=False, files=files, tests=names, argv=None,
                       note=msg)
        if not quiet:
            print(msg)
        return {"ok": False, "problems": [msg], "files": files, "tests": names,
                "unassessed": True}

    spec = {
        "name": "related tests",
        "cwd": _test_cwd(cfg),
        "kind": "test",
        "adapter": ad.name,
        "argv": argv,
    }
    if not quiet:
        print(f"跑相关用例：{', '.join(names)}", flush=True)
        print(f"  {' '.join(argv)}", flush=True)

    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    st = run_step(cfg, spec)
    judge_step(cfg, spec, st)
    problems: list[str] = []
    if not st.ok:
        problems.append(st.note or f"相关用例未通过（退出码 {st.exit_code}）")
        if st.output_tail:
            problems.append(st.output_tail)

    hashes = file_hashes(cfg, files)
    _write_partial(cfg, ok=st.ok, files=files, tests=names, argv=argv,
                   note=st.note or "", seconds=st.seconds,
                   output_tail=st.output_tail, file_hashes=hashes)
    if st.ok:
        cfg.dirty.unlink(missing_ok=True)
    if not quiet:
        mark = "通过" if st.ok else "不通过"
        print(f"  [{mark}] related tests  {st.seconds}s"
              + (f"  {st.note}" if st.note else ""), flush=True)
        if not st.ok and st.output_tail:
            print(st.output_tail)
    return {
        "ok": st.ok, "problems": problems, "files": files, "tests": names,
        "argv": argv, "seconds": st.seconds,
    }


def cmd_run_changed(cfg: Config) -> int:
    got = run_changed(cfg)
    if got.get("skipped"):
        return 0
    return 0 if got.get("ok") else 1


def _write_partial(cfg: Config, *, ok: bool, files: list[str],
                   tests: list[str] | None, argv: list[str] | None,
                   note: str, seconds: float | None = None,
                   output_tail: str = "",
                   file_hashes: dict[str, str] | None = None) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.partial.write_text(json.dumps({
        "kind": "changed",
        "ok": ok,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "files": files,
        "file_hashes": file_hashes or {},
        "tests": tests,
        "argv": argv,
        "seconds": seconds,
        "note": note,
        "output_tail": output_tail,
        "latest": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
