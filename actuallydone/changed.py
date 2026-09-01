"""开发中按改动文件跑相关用例。不写 latest.json，也不改步骤 argv。

`gate run --changed` 与 stop 钩子共用这一份。全量回执仍只由 `gate run` 产出。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .config import Config
from .gate import judge_step, read_dirty, run_step


def changed_paths(cfg: Config, paths: list[str] | None = None) -> list[str]:
    """调用方名单，否则 dirty 与 git 合并（路径都相对 adone.toml 所在目录）。"""
    if paths:
        return _uniq(paths)
    return _uniq(read_dirty(cfg) + git_changed(cfg, quiet=True)[0])


# 钩子进程的 PATH 由客户端决定，实测拿到过没有 git 的环境。找不到就默默返回空，
# 与「仓库真的干净」长得一模一样，于是「改了一堆却不跑增量」。
_GIT_FALLBACKS = (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
    "/usr/bin/git",
    "/usr/local/bin/git",
    "/opt/homebrew/bin/git",
)


def git_exe() -> str | None:
    found = shutil.which("git")
    if found:
        return found
    for cand in _GIT_FALLBACKS:
        if Path(cand).is_file():
            return cand
    return None


def _git_out(exe: str, args: list[str], cwd: Path) -> str | None:
    """跑一条 git，按 UTF-8 解码输出。

    不能用 text=True 的默认编码：那是本机代码页。中文 Windows 是 cp936，
    而 git 的路径一律是 UTF-8，解出来的中文文件名对不上磁盘上的任何文件。
    """
    try:
        proc = subprocess.run([exe, *args], cwd=cwd, capture_output=True,
                              encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


# -z：条目以 NUL 分隔。默认格式会把中文路径转义成 "\346\226\207"，
# 还会因为路径里的空格和 `->` 切错，-z 两个问题一起没有了。
_STATUS_ARGV = ["-c", "core.quotepath=false", "-c", "status.relativePaths=false",
                "status", "--porcelain", "-z", "-uall"]


def _porcelain_entries(out: str) -> list[str]:
    parts = out.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(parts):
        item = parts[i]
        i += 1
        if len(item) < 4:
            continue
        code, path = item[:2], item[3:]
        if "R" in code or "C" in code:
            i += 1          # 改名条目后面紧跟着旧路径
        if path:
            paths.append(path.replace("\\", "/"))
    return paths


def _real(p: Path | str) -> str:
    return os.path.realpath(str(p))


def _rel_within(root_real: str, abs_path: str) -> str | None:
    """abs_path 在 root 之内则返回相对路径。Windows 上盘符大小写会不一致。"""
    base = root_real.rstrip(os.sep)
    if os.path.normcase(abs_path) == os.path.normcase(base):
        return None
    prefix = os.path.normcase(base) + os.sep
    if not os.path.normcase(abs_path).startswith(prefix):
        return None
    return abs_path[len(base) + 1:].replace(os.sep, "/").replace("\\", "/")


def _repo_tops(exe: str, dirs: list[Path]) -> list[Path]:
    """这些目录各自属于哪个 git 仓库。子项目常常是独立仓库，父目录 status 看不到。"""
    tops: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        if not d.is_dir():
            continue
        out = _git_out(exe, ["rev-parse", "--show-toplevel"], d)
        if out is None:
            continue
        line = out.strip().splitlines()[0].strip() if out.strip() else ""
        if not line:
            continue
        key = os.path.normcase(_real(line))
        if key in seen:
            continue
        seen.add(key)
        tops.append(Path(line))
    return tops


def git_changed(cfg: Config, *, quiet: bool = False) -> tuple[list[str], str]:
    """返回 (相对项目根的改动名单, 说明)。说明用来在钩子日志里解释为什么是空的。

    要同时扛住两种布局：项目嵌在父仓库里（路径带 `demo/app/` 前缀），
    以及项目里套着若干独立子仓库（父目录 `git status` 一条都看不到）。
    """
    root = cfg.root
    exe = git_exe()
    if exe is None:
        return [], "PATH 里没有 git"
    dirs = [root]
    for r in (cfg.get("gate.watch_roots") or []):
        d = root / str(r)
        if d.is_dir():
            dirs.append(d)
    tops = _repo_tops(exe, dirs)
    if not tops:
        return [], "不在任何 git 仓库里"

    root_real = _real(root)
    seen: list[str] = []
    lines = 0
    for top in tops:
        out = _git_out(exe, _STATUS_ARGV, top)
        if out is None:
            continue
        top_real = _real(top)
        for raw in _porcelain_entries(out):
            lines += 1
            rel = _rel_within(root_real, _real(os.path.join(top_real, raw)))
            if rel and rel not in seen:
                seen.append(rel)
    note = f"{len(tops)} 个仓库、{lines} 条改动"
    if lines and not seen:
        note += "，但都不在项目目录内"
    return seen, note


def git_diff_names(root: Path) -> list[str]:
    """按项目根取 git 改动名单。路径相对 `root`。"""
    return git_changed(Config.load(root))[0]


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
            # 名单为空时最该说清楚的是「为什么空」：钩子静默失效的样子和仓库干净一样
            print(f"没有改动文件（dirty 空，git：{git_changed(cfg)[1]}），跳过相关用例")
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
