"""从 GitHub 拉最新版并覆盖当前安装。

升级是工具级操作：不读 adone.toml，当前目录没有配置也能跑。
依赖为零，只用 urllib。动手之前把本模块用到的东西全部 import 完——
升级子进程会在本进程还活着的时候重写本包文件，成功之后只 print 和 return。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__

REPO = "iamharvey/ActuallyDone"
API = f"https://api.github.com/repos/{REPO}"
GIT_URL = f"https://github.com/{REPO}.git"
RAW = f"https://raw.githubusercontent.com/{REPO}"
UA = "actuallydone-upgrade"


# --------------------------------------------------------------------------- 版本

def parse_version(s: str) -> tuple[int, ...]:
    """容 v 前缀与预发布后缀，做元组比较。不要用字符串比。"""
    s = (s or "").strip()
    if s[:1] in "vV":
        s = s[1:]
    main = re.split(r"[-+]", s, maxsplit=1)[0]
    parts: list[int] = []
    for p in main.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _headers() -> dict[str, str]:
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get_json(url: str) -> tuple[object | None, str | None]:
    """返回 (数据, 错误人话)。错误时数据是 None。"""
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        if e.code == 403:
            reset = e.headers.get("X-RateLimit-Reset", "")
            hint = f"（额度重置时间戳 {reset}）" if reset else ""
            return None, f"GitHub API 限流或拒绝访问（403）{hint}。设 GITHUB_TOKEN 再试"
        if e.code == 404:
            return None, "404"
        return None, f"GitHub API 返回 {e.code}：{e.reason}"
    except urllib.error.URLError as e:
        return None, f"连不上 GitHub（{e.reason}）。检查网络再试"
    except TimeoutError:
        return None, "连 GitHub 超时。检查网络再试"
    except json.JSONDecodeError:
        return None, "GitHub API 返回的不是 JSON"


def _get_text(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode()
    except (urllib.error.URLError, TimeoutError):
        return None


def _version_from_init(text: str) -> str | None:
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    return m.group(1) if m else None


def discover_remote() -> tuple[str | None, str | None, str | None]:
    """返回 (ref, version, 错误)。ref 是 tag/branch，version 是可比的版本号。"""
    data, err = _get_json(f"{API}/releases/latest")
    if isinstance(data, dict) and data.get("tag_name"):
        tag = str(data["tag_name"])
        return tag, tag, None
    if err and err != "404":
        return None, None, err

    data, err = _get_json(f"{API}/tags")
    if isinstance(data, list) and data:
        names = [str(t.get("name") or "") for t in data if t.get("name")]
        names = [n for n in names if parse_version(n) != (0, 0, 0) or n.strip("vV")]
        if names:
            best = max(names, key=parse_version)
            return best, best, None
    if err and err != "404":
        return None, None, err

    data, err = _get_json(API)
    if not isinstance(data, dict):
        return None, None, err or "查不到仓库信息"
    branch = str(data.get("default_branch") or "main")
    raw = _get_text(f"{RAW}/{branch}/actuallydone/__init__.py")
    ver = _version_from_init(raw or "")
    return branch, ver, None


# --------------------------------------------------------------------------- 安装方式

def install_mode(pkg_file: Path | None = None) -> str:
    pkg = (pkg_file or Path(__file__)).resolve().parent
    posix = pkg.as_posix()
    if "pipx/venvs/actuallydone" in posix:
        return "pipx"
    if pkg.parent.name == "site-packages":
        return "pip"
    root = pkg.parent
    if (root / ".git").exists():
        return "git"
    return "unknown"


def repo_root(pkg_file: Path | None = None) -> Path:
    return (pkg_file or Path(__file__)).resolve().parent.parent


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def git_blockers(root: Path) -> list[str]:
    """脏工作树或未推送提交：在本仓库跑 upgrade 必须被拦住。"""
    problems: list[str] = []
    st = _git(root, "status", "--porcelain")
    if st.returncode != 0:
        return [f"git status 失败：{st.stderr.strip() or st.returncode}"]
    if st.stdout.strip():
        problems.append("工作树不干净（git status 有输出）：可能是开发仓库，"
                        "checkout 会冲掉未提交的改动。要继续得显式 --force")
    up = _git(root, "rev-parse", "--abbrev-ref", "@{u}")
    if up.returncode == 0:
        ahead = _git(root, "log", "--oneline", "@{u}..HEAD")
        if ahead.returncode == 0 and ahead.stdout.strip():
            problems.append("有还没推送的提交：checkout 会让它们难找回来。"
                            "要继续得显式 --force")
    return problems


# --------------------------------------------------------------------------- 执行

def install_argv(mode: str, ref: str) -> list[str]:
    spec = f"git+{GIT_URL}@{ref}"
    if mode == "pipx":
        return ["pipx", "install", "--force", spec]
    if mode == "pip":
        return [sys.executable, "-m", "pip", "install", "--upgrade", spec]
    raise ValueError(f"install_argv 不支持 {mode}")


def run_upgrade(mode: str, ref: str, root: Path) -> tuple[int, str]:
    if mode in ("pipx", "pip"):
        argv = install_argv(mode, ref)
        proc = subprocess.run(argv)
        return proc.returncode, " ".join(argv)
    if mode == "git":
        fetch = _git(root, "fetch", "--tags", "origin")
        if fetch.returncode != 0:
            return fetch.returncode, fetch.stderr.strip() or "git fetch 失败"
        ck = _git(root, "checkout", ref)
        if ck.returncode != 0:
            return ck.returncode, ck.stderr.strip() or f"git checkout {ref} 失败"
        return 0, f"git fetch --tags && git checkout {ref}"
    return 2, f"认不出安装方式（{mode}），请用 pipx 或 pip 重装"


def cmd_upgrade(args) -> int:
    # 动手前把会用到的都 import 完。成功之后不再碰配置与钩子代码。
    mode = install_mode()
    root = repo_root()
    local = __version__
    want_ref = getattr(args, "ref", None)
    check_only = getattr(args, "check", False)
    force = getattr(args, "force", False)
    dry = getattr(args, "dry_run", False)

    if want_ref:
        remote_ref, remote_ver = want_ref, want_ref
        raw = _get_text(f"{RAW}/{want_ref}/actuallydone/__init__.py")
        if raw:
            remote_ver = _version_from_init(raw) or want_ref
    else:
        remote_ref, remote_ver, err = discover_remote()
        if err:
            print(f"查不到远端版本：{err}", file=sys.stderr)
            return 2
        if not remote_ref:
            print("GitHub 上既没有 Release 也没有 tag，也读不到默认分支。", file=sys.stderr)
            return 2

    print(f"本地 {local}（{mode}）")
    print(f"远端 {remote_ver or remote_ref}（{remote_ref}）")

    comparable = remote_ver and parse_version(str(remote_ver)) != (0, 0, 0)
    if comparable and parse_version(str(remote_ver)) == parse_version(local):
        print("已是最新。")
        return 0
    if comparable and parse_version(str(remote_ver)) < parse_version(local):
        print(f"远端 {remote_ver} 比本地 {local} 旧，拒绝降级。"
              + ("（加 --force 才降）" if not force else ""))
        if not force:
            return 0 if check_only else 2
    if comparable and parse_version(str(remote_ver)) > parse_version(local):
        if check_only:
            print(f"有新版本 {remote_ver}。跑 adone upgrade 安装。")
            return 1
    elif check_only:
        print("无法比较版本号；要装指定 ref 用 adone upgrade --ref …")
        return 2

    if mode == "unknown":
        print("认不出当前是 pipx、pip 还是 git 工作树，不敢覆盖。"
              "用 pipx install git+https://github.com/iamharvey/ActuallyDone.git 重装。",
              file=sys.stderr)
        return 2

    if mode == "git":
        blockers = git_blockers(root)
        if blockers and not force:
            for b in blockers:
                print(b, file=sys.stderr)
            return 2
        if blockers and force:
            print("（--force：忽略脏工作树 / 未推送提交）")

    if dry:
        if mode == "git":
            print(f"[演练] git fetch --tags && git checkout {remote_ref}  （在 {root}）")
        else:
            print(f"[演练] {' '.join(install_argv(mode, remote_ref))}")
        return 0

    code, detail = run_upgrade(mode, remote_ref, root)
    if code != 0:
        print(f"升级失败：{detail}", file=sys.stderr)
        return code or 1
    print(f"已更新到 {remote_ver or remote_ref}。")
    print("若项目里装了钩子，跑一次 adone install --hooks-only --force："
          "钩子把安装时的绝对路径烧进了 ADONE_CMD，换了位置就会失效，"
          "失效的样子和「门禁通过」在终端里一模一样。")
    return 0
