"""读源文件用的解码。项目不是 UTF-8 的时候，工具不该假装看懂了。

为什么值得单独一个模块：GBK 的尾字节范围含 ASCII，`乗` 是 81 5C，
按 UTF-8 解会漏出一个 `\\`，`亄`（81 7B）会漏出一个 `{`。这类字符一旦混进
源码文本，大括号计数就会切错函数体——扫不到的测试方法不会报错，
只会让「相关用例」少几条，和「这文件本来就没测试」长得一模一样。

编码由 `project.source_encoding` 决定，`adone init` 探测后写进配置，人可以改。
一律先试 UTF-8，配置项决定解不动时退到哪：`gbk` 退到 GB18030，
`auto` 再加上本机编码。逐个文件判断——一个仓库里两种编码混着放很常见。
"""

from __future__ import annotations

import locale
import os
import sys
from pathlib import Path

AUTO = "auto"
# GB18030 是 GBK 的超集，能解的都能解，还多认生僻字，所以拿它当 gbk 的实现
_ALIAS = {
    "gbk": "gb18030", "gb2312": "gb18030", "cp936": "gb18030",
    "ansi": "gb18030", "": AUTO, "auto": AUTO,
}

_default = AUTO


def force_utf8_stdio() -> None:
    """把本进程的 stdout / stderr 改成 UTF-8。

    中文 Windows 上 Python 默认按 cp936 写控制台。门禁按字节读 Maven 再按
    UTF-8 解（现在的 mvn 常吐 UTF-8），print 那些字时会
    `UnicodeEncodeError: 'gbk' codec can't encode`——pre-commit 里跑
    `gate run` 就是这么炸的。用户在钩子里加 `PYTHONIOENCODING=utf-8`
    是对的，但那只罩得住 git 钩子，而且下一次 `install --hooks-only`
    会盖掉。入口自己改，所有路径（终端、钩子、pre-commit）都一样。
    """
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if reconf is None:
            continue
        try:
            reconf(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            pass


def set_default(encoding: str | None) -> None:
    """整个进程用哪种编码读源文件。一次运行只服务一个项目，所以是进程级的。"""
    global _default
    _default = normalize(encoding)


def get_default() -> str:
    return _default


def normalize(encoding: str | None) -> str:
    name = str(encoding or "").strip().lower().replace("_", "-")
    return _ALIAS.get(name, name or AUTO)


def candidates(encoding: str | None = None) -> tuple[str, ...]:
    """UTF-8 永远排第一，配置项决定它解不动时退到哪。

    不能把配置的编码放前面：GB18030 几乎什么字节都能解出「一个字」，
    于是 GBK 项目里那几个 UTF-8 文件会被静悄悄读成乱码，而且不报错。
    UTF-8 是自校验的，整份中文源码碰巧也是合法 UTF-8 的概率可以忽略。
    """
    enc = normalize(encoding if encoding is not None else _default)
    seq = ["utf-8-sig", "utf-8"]
    if enc == AUTO:
        seq.append("gb18030")
        local = (locale.getpreferredencoding(False) or "").lower()
        if local and local not in seq:
            seq.append(local)
    elif not enc.startswith("utf-8"):
        seq.append(enc)
    return tuple(seq)


def decode(data: bytes, encoding: str | None = None) -> str:
    """按候选编码依次严格解码；都不成再带替换解一次，绝不抛异常。"""
    for enc in candidates(encoding):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def read(path: Path, encoding: str | None = None) -> str:
    """读源文件。读不到返回空串——调用方原本就当「没内容」处理。"""
    try:
        return decode(Path(path).read_bytes(), encoding)
    except OSError:
        return ""


def sniff(paths, limit: int = 60) -> tuple[str, dict[str, int]]:
    """探测一批源文件的编码，返回 (建议值, 计数)。

    建议值只有三种：`utf-8`、`gbk`、`auto`（混着放，或一个都没看出来）。
    """
    tally = {"utf-8": 0, "gbk": 0, "unknown": 0, "ascii": 0}
    for i, p in enumerate(paths):
        if i >= limit:
            break
        try:
            data = Path(p).read_bytes()
        except OSError:
            continue
        if not data:
            continue
        try:
            data.decode("ascii")
            tally["ascii"] += 1
            continue                      # 纯 ASCII 两种编码都成立，不算票
        except UnicodeDecodeError:
            pass
        try:
            data.decode("utf-8")
            tally["utf-8"] += 1
            continue
        except UnicodeDecodeError:
            pass
        try:
            data.decode("gb18030")
            tally["gbk"] += 1
        except UnicodeDecodeError:
            tally["unknown"] += 1
    if tally["unknown"]:
        return AUTO, tally
    if tally["utf-8"] and tally["gbk"]:
        return AUTO, tally
    if tally["gbk"]:
        return "gbk", tally
    return "utf-8", tally
