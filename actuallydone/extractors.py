"""从文件里抽「可比对的符号集合」，供一致性检查与文档对账使用。

抽取器都要跳过注释行。两份 schema 文件的文件头往往在**用自然语言谈论**建表语句
（「所有 CREATE TABLE 均带 IF NOT EXISTS」），照单全收会抽出「均带」「IF」这种表名，
进而报出一堆并不存在的漂移——这个坑本仓库真踩过。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

COMMENT_PREFIXES = ("--", "//", "#", "*", "/*")

_CREATE_TABLE_RE = re.compile(r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?`?(\w+)`?", re.I)
_DROP_TABLE_RE = re.compile(r"DROP TABLE\s+(?:IF EXISTS\s+)?`?(\w+)`?", re.I)
_OPENAPI_PATH_RE = re.compile(r"^  (/\S+):", re.M)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _code_lines(text: str) -> list[str]:
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if s and not s.startswith(COMMENT_PREFIXES):
            out.append(s)
    return out


def sql_tables(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    for ln in _code_lines(read(path)):
        out |= set(_CREATE_TABLE_RE.findall(ln))
    return out


def sql_dropped_tables(path: Path) -> set[str]:
    """被显式删掉的表。一处删了、另一处还在建，是最容易漏掉的一种漂移。"""
    if not path.exists():
        return set()
    out: set[str] = set()
    for ln in _code_lines(read(path)):
        out |= set(_DROP_TABLE_RE.findall(ln))
    return out


def openapi_paths(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(_OPENAPI_PATH_RE.findall(read(path)))


def file_names(path: Path) -> set[str]:
    """目录下所有文件名（不含路径）。"""
    if not path.is_dir():
        return set()
    return {p.name for p in path.rglob("*") if p.is_file()}


EXTRACTORS: dict[str, Callable[[Path], set[str]]] = {
    "sql_tables": sql_tables,
    "openapi_paths": openapi_paths,
    "file_names": file_names,
}


def extract(kind: str, path: Path) -> set[str] | None:
    fn = EXTRACTORS.get(kind)
    return fn(path) if fn else None


# ------------------------------------------------------------------ 路径匹配

def norm_path(p: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", p.rstrip("/")) or "/"


def route_known(path: str, literals: set[str]) -> bool:
    """路径能否在路由注册里找到对应字面量。

    很多框架的注册是「前缀 + 方法字面量」拼出来的，跨文件分散，精确还原代价过高。
    这里用保守匹配：归一化后，只要某个字面量是这条路径的后缀段，就算找得到。
    因此它只用来发现「文档里写了、代码里完全没有」的幻影接口，报警告不报错误。
    """
    n = norm_path(path)
    lits = {norm_path(x) for x in literals}
    if n in lits:
        return True
    segs = [s for s in n.split("/") if s]
    return any("/" + "/".join(segs[i:]) in lits for i in range(len(segs)))
