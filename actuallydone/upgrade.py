"""从 GitHub 拉最新版并覆盖当前安装。

升级是工具级操作：不读 adone.toml，当前目录没有配置也能跑。
依赖为零，只用 urllib。动手之前把本模块用到的东西全部 import 完——
升级子进程会在本进程还活着的时候重写本包文件，成功之后只 print 和 return。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
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
    """返回 (ref, version, 错误)。在 Release / tag / 默认分支里取版本号最新的。

    只认第一个能用的源会漏掉：没有 Release 时停在旧 tag，main 上的补丁永远装不到。
    """
    found: list[tuple[tuple[int, ...], str, str]] = []
    last_err: str | None = None

    data, err = _get_json(f"{API}/releases/latest")
    if isinstance(data, dict) and data.get("tag_name"):
        tag = str(data["tag_name"])
        found.append((parse_version(tag), tag, tag))
    elif err and err != "404":
        last_err = err

    data, err = _get_json(f"{API}/tags")
    if isinstance(data, list) and data:
        names = [str(t.get("name") or "") for t in data if t.get("name")]
        names = [n for n in names if parse_version(n) != (0, 0, 0) or n.strip("vV")]
        if names:
            best = max(names, key=parse_version)
            found.append((parse_version(best), best, best))
    elif err and err != "404":
        last_err = last_err or err

    data, err = _get_json(API)
    if isinstance(data, dict):
        branch = str(data.get("default_branch") or "main")
        raw = _get_text(f"{RAW}/{branch}/actuallydone/__init__.py")
        ver = _version_from_init(raw or "")
        if ver:
            found.append((parse_version(ver), branch, ver))
    elif err:
        last_err = last_err or err

    if not found:
        return None, None, last_err or "查不到远端版本"
    _, ref, ver = max(found, key=lambda x: x[0])
    return ref, ver, None


# --------------------------------------------------------------------------- 启动时提示

# 联网最多半天一次：每次 adone 都打 GitHub 会撞限流，钩子更经不起。
# 已经知道有新版时，交互式命令每次都会问；拒了也不记「今天别烦我」——
# 用户说了让他自己选，下一次敲命令还是他的选择。
_CHECK_TTL = 12 * 3600
_PEEK_TIMEOUT = 3


def cache_path() -> Path:
    override = os.environ.get("ADONE_UPDATE_CACHE")
    if override:
        return Path(override)
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "actuallydone" / "update-check.json"


def read_cache(path: Path | None = None) -> dict:
    p = path or cache_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_cache(data: dict, path: Path | None = None) -> None:
    p = path or cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def peek_latest(timeout: float = _PEEK_TIMEOUT) -> tuple[str | None, str | None]:
    """启动提示用的短超时探测：Release，没有就看 tag 列表第一页。失败返回 (None, None)。"""
    found: list[tuple[tuple[int, ...], str, str]] = []
    req = urllib.request.Request(f"{API}/releases/latest", headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        tag = str((data or {}).get("tag_name") or "")
        if tag:
            found.append((parse_version(tag), tag, tag))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
            json.JSONDecodeError, OSError):
        pass
    if not found:
        req = urllib.request.Request(f"{API}/tags", headers=_headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            if isinstance(data, list):
                names = [str(t.get("name") or "") for t in data if t.get("name")]
                names = [n for n in names if parse_version(n) != (0, 0, 0) or n.strip("vV")]
                if names:
                    best = max(names, key=parse_version)
                    found.append((parse_version(best), best, best))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                json.JSONDecodeError, OSError):
            return None, None
    if not found:
        return None, None
    _, ref, ver = max(found, key=lambda x: x[0])
    return ref, ver


def skip_nudge(args) -> bool:
    """钩子、机器读的输出、没有人坐在前面：问一句都是在添乱。"""
    if os.environ.get("ADONE_NO_UPDATE_CHECK"):
        return True
    if os.environ.get("CI"):
        return True
    if getattr(args, "cmd", None) in ("hook", "serve", "upgrade"):
        return True
    if getattr(args, "json", False):
        return True
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return True
    except OSError:
        return True
    return False


def _ask_upgrade(local: str, remote: str) -> bool:
    print(f"有新版本 {remote}（当前 {local}）。现在升级？[y/N] ", end="", flush=True)
    try:
        ans = input().strip().lower()
    except EOFError:
        print()
        return False
    return ans in ("y", "yes", "是")


def maybe_offer_upgrade(args, *, peek=None, ask=None, upgrade=None,
                        now: float | None = None, force: bool = False) -> int | None:
    """交互式命令在干活之前问一句。返回 None 表示继续原命令；整数是升级后的退出码。

    升完不能接着跑原命令：包文件已经被覆盖，内存里还是旧代码。
    force 只给测试用：非 TTY 的用例也要把后面的分支跑到。
    """
    if not force and skip_nudge(args):
        return None
    local = __version__
    cache = read_cache()
    stamp = float(now if now is not None else time.time())
    remote_ver = str(cache.get("remote_ver") or "")
    checked = float(cache.get("checked_at") or 0)
    stale = stamp - checked > _CHECK_TTL or not remote_ver
    if stale:
        ref, ver = (peek or peek_latest)()
        if not ver:
            return None
        write_cache({"checked_at": stamp, "remote_ref": ref, "remote_ver": ver})
        remote_ver = ver
    if parse_version(remote_ver) <= parse_version(local):
        return None
    if not (ask or _ask_upgrade)(local, remote_ver):
        return None
    print("开始升级。")
    if upgrade is None:
        from argparse import Namespace
        code = cmd_upgrade(Namespace(check=False, ref=None, force=False, dry_run=False))
    else:
        code = upgrade()
    if code == 0:
        print("请重新运行刚才那条命令：升完的是磁盘上的包，当前进程还是旧代码。")
    return code


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


def classify_entry(entry: Path) -> str:
    """看用户敲 adone 时真正跑到的那份入口，而不是当前这份源码在哪。"""
    try:
        text = entry.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        text = ""
    blob = f"{text}\n{entry}\n{entry.resolve()}".replace("\\", "/")
    if "pipx/venvs/actuallydone" in blob:
        return "pipx"
    shebang = text.splitlines()[0] if text.startswith("#!") else ""
    if "site-packages" in blob or "/venv/" in shebang or "/virtualenv/" in shebang:
        if "from actuallydone.cli import main" in text:
            return "pip"
    p = entry.resolve()
    if p.stem.lower() == "adone":
        root = p.parent.parent
        if (root / "actuallydone" / "__init__.py").is_file() and (root / ".git").exists():
            return "git"
    return "unknown"


def upgrade_target() -> tuple[str, Path, str]:
    """优先覆盖 PATH 上的 adone——那才是用户第二天会敲到的命令。

    从仓库里的 bin/adone 跑 upgrade 时，__file__ 在 git 工作树里，
    若据此 checkout，PATH 上的 pipx 1.2.0 纹丝不动：看起来升了，其实还是旧命令。
    """
    which = shutil.which("adone")
    if which:
        mode = classify_entry(Path(which))
        if mode != "unknown":
            return mode, repo_root(), which
    return install_mode(), repo_root(), which or ""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    # git 的输出是 UTF-8，而 text=True 默认按本机代码页解（中文 Windows 是 cp936）
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          encoding="utf-8", errors="replace")


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


def _verify_path_adone() -> str:
    which = shutil.which("adone")
    if not which:
        return ("PATH 里还是没有 adone。新开一个终端，或检查 pipx 的 bin "
                "（macOS/Linux：~/.local/bin；Windows：%USERPROFILE%\\.local\\bin）在不在 PATH 里。")
    proc = subprocess.run([which, "--version"], capture_output=True, text=True)
    out = (proc.stdout or proc.stderr or "").strip()
    return f"PATH 上的 {which} → {out or '跑 --version 失败'}"


def _running_version(which: str) -> str | None:
    """PATH 上那份 adone 的版本。和当前源码的 __version__ 经常不是一回事。"""
    if not which:
        return None
    try:
        proc = subprocess.run([which, "--version"], capture_output=True, text=True,
                              timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", (proc.stdout or "") + (proc.stderr or ""))
    return m.group(1) if m else None


def cmd_upgrade(args) -> int:
    # 动手前把会用到的都 import 完。成功之后不再碰配置与钩子代码。
    mode, root, path_adone = upgrade_target()
    path_ver = _running_version(path_adone) if path_adone else None
    local = path_ver or __version__
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

    print(f"本地 {local}（将覆盖 {mode}"
          + (f"：{path_adone}" if path_adone else "") + "）")
    print(f"远端 {remote_ver or remote_ref}（{remote_ref}）")
    if path_ver and path_ver != __version__:
        print(f"PATH 上的 adone 是 {path_ver}，当前源码是 {__version__}："
              f"以 PATH 那一份为准去升，否则敲 adone 还是旧版。")

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
    print(_verify_path_adone())
    print("若项目里装了钩子，跑一次 adone install --hooks-only --force："
          "钩子把安装时的绝对路径烧进了 ADONE_CMD，换了位置就会失效，"
          "失效的样子和「门禁通过」在终端里一模一样。")
    return 0

