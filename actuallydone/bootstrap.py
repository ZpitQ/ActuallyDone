"""开跑之前先确认：跑我们的这个解释器够不够新，不够就换一个。

真实发生过一回：Cursor 的 stop 钩子被 anaconda 的 python3（3.10）起了起来，
`import tomllib` 当场 ModuleNotFoundError，门禁于是「没跑成」。钩子拿到的 PATH
与你终端里的常常不是一回事，所以这件事不能指望用户把环境配对——
入口脚本自己去找一个 3.11+ 的解释器换过去，实在找不到再明说，别留一个看不懂的堆栈。

本模块必须能在 3.11 以下被 import：它的整个存在意义就是在那种解释器上做判断。
所以这里只用老 Python 也有的东西，且不要 import 包里任何别的模块。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

MIN_VERSION = (3, 11)          # tomllib 进标准库的版本
GUARD_ENV = "ADONE_BOOTSTRAPPED"
# 明写版本号的名字优先：PATH 里的 python3 指向谁完全看运气
CANDIDATE_NAMES = ("python3.14", "python3.13", "python3.12", "python3.11", "python3")
# 钩子拿到的 PATH 可能很干净，PATH 里翻不着就去这些常见位置找。
# Linux 上 pipx / 用户级 Python 落在 ~/.local/bin；pyenv 在 ~/.pyenv/shims。
EXTRA_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin",
              "/Library/Frameworks/Python.framework/Versions/Current/bin")


def extra_dirs():
    home = os.path.expanduser("~")
    return EXTRA_DIRS + (
        os.path.join(home, ".local", "bin"),
        os.path.join(home, ".pyenv", "shims"),
    )


def has_tomllib(exe):
    """真去 import 一次。名字叫 python3.12 的软链指向 3.9 这种事是有的，
    而且我们要的本来就不是版本号，是那个模块。"""
    try:
        proc = subprocess.run([exe, "-c", "import tomllib"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    except Exception:
        return False
    return proc.returncode == 0


def candidates(which=None, isfile=None):
    """按优先级列出可能的解释器路径，去重且保序。"""
    which = which or shutil.which
    isfile = isfile or os.path.isfile
    out = []
    for name in CANDIDATE_NAMES:
        found = which(name)
        if found and found not in out:
            out.append(found)
        for d in extra_dirs():
            path = os.path.join(d, name)
            if isfile(path) and path not in out:
                out.append(path)
    return out


def find_modern_python(which=None, isfile=None, probe=None):
    """找一个带 tomllib 的解释器；找不到返回 None。"""
    probe = probe or has_tomllib
    here = os.path.realpath(sys.executable)
    for exe in candidates(which, isfile):
        if os.path.realpath(exe) == here:
            continue      # 就是当前这个，已经知道它不行
        if probe(exe):
            return exe
    return None


def _die(extra=""):
    ver = ".".join(str(v) for v in sys.version_info[:3])
    sys.stderr.write(
        "ActuallyDone 需要 Python {}+（用到标准库 tomllib），"
        "当前解释器是 {}（{}）。{}\n".format(
            ".".join(str(v) for v in MIN_VERSION), sys.executable, ver,
            extra or "PATH 与常见安装位置里都没找到更新的，装一个 python3.11+ 再试。"))
    raise SystemExit(2)


def ensure_modern_python(entry):
    """够新就直接返回（正常路径零开销）；不够新就换个解释器重跑同一个入口。"""
    if sys.version_info >= MIN_VERSION:
        return
    if os.environ.get(GUARD_ENV):
        _die("换过一次解释器还是不行，不再换下去了。")
    exe = find_modern_python()
    if exe is None:
        _die()
    os.environ[GUARD_ENV] = "1"
    os.execv(exe, [exe, os.path.abspath(entry)] + sys.argv[1:])
