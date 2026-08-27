"""适配器注册表。

`get()` 拿不到对应生态时返回**基类**而不是抛错：基类什么能力都没有，
上层会把相关检查标成「未评估」——这正是我们要的行为，
比崩掉一整份报告好，也比假装查过了好。
"""

from __future__ import annotations

from pathlib import Path

from .base import (CAP_COVERAGE, CAP_FUNCS, CAP_ROUTES, CAP_SINGLE_TEST,
                   CAP_TABLES, CAP_TESTS, CAP_VIEWS, Adapter)
from .go_adapter import GoAdapter
from .java_adapter import JavaAdapter
from .node_adapter import NodeAdapter
from .python_adapter import PythonAdapter

REGISTRY: dict[str, type[Adapter]] = {
    "go": GoAdapter,
    "java": JavaAdapter,
    "node": NodeAdapter,
    "python": PythonAdapter,
    "generic": Adapter,
}

__all__ = ["REGISTRY", "get", "detect_all", "Adapter", "CAP_TESTS", "CAP_COVERAGE",
           "CAP_FUNCS", "CAP_ROUTES", "CAP_TABLES", "CAP_VIEWS", "CAP_SINGLE_TEST"]


def get(name: str, root: Path) -> Adapter:
    cls = REGISTRY.get((name or "").strip().lower(), Adapter)
    return cls(root)


def detect_all(root: Path) -> dict[str, list[str]]:
    """返回 {生态名: [命中的标志文件]}，只含命中的。"""
    out: dict[str, list[str]] = {}
    for name, cls in REGISTRY.items():
        if name == "generic":
            continue
        hits = cls.detect(root)
        if hits:
            out[name] = hits
    return out
