"""配置：adone.toml 的读取、默认值与体检。

设计上只有一条硬规矩：**默认值不许替用户猜阈值**。
覆盖率下限、树文件数下限这类数字，宁可留空让检查标「未评估」，
也不要塞一个看起来合理的数字——那会让报告显得健康，而它并不知道真相。
"""

from __future__ import annotations

import sys

try:
    import tomllib
except ModuleNotFoundError:  # 3.10 及更早：给一句人话，而不是一段堆栈
    raise SystemExit(
        f"ActuallyDone 需要 Python 3.11+（用到标准库 tomllib），"
        f"当前解释器是 {sys.executable}。"
        f"用仓库里的 bin/adone 这个入口，它会自动换一个够新的解释器；"
        f"或者 pipx install git+https://github.com/iamharvey/ActuallyDone.git。")

from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_NAME = "adone.toml"

# 依赖与构建产物：树哈希、重复检测都要跳过。
# 把 node_modules 与 target 算进受监视树，回执会在每次 npm install / mvn package 后过期，
# 而「回执已过期」这句话本该指向人改了源码。
PRUNE_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build", "target",
    "__pycache__", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    ".next", ".nuxt", ".gradle", ".adone", ".idea", ".vscode", ".vs",
    "cmake-build-debug", "cmake-build-release", "cmake-build-relwithdebinfo",
    "cmake-build-minsizerel",
})

# 只有「不猜也不会骗人」的值才配出现在这里
DEFAULTS: dict[str, Any] = {
    "version": 1,
    "project": {
        "name": "",
        "ecosystems": [],
        "state_dir": ".adone",
        "material_dir": "adone",
        "skills_dir": ".cursor/skills",
    },
    "gate": {
        "watch_roots": [],
        "watch_exts": [],
        # 哈希到的文件数低于此值即认定扫描出了问题：空哈希会让门禁恒等通过
        "min_tree_files": 1,
        "keep_receipts": 20,
        "step": [],
    },
    "coverage": {"threshold": None, "source": ""},
    "tests": {"roots": [], "adapter": "", "baseline_exempt": []},
    "code": {
        "big_file_lines": 800,
        "big_file_globs": [],
        "mark_globs": [],
        "mark_words": ["TODO", "FIXME", "XXX", "HACK"],
        "dup_min_lines": 8,
        "dup_roots": [],
        "zero_cover_ratio": 0.15,
    },
    "consistency": {"pair": []},
    "docs": {
        "required": [],
        "diagram_globs": [],
        "diagram_render_ext": ".svg",
        "adr_dir": "",
        "excerpt": [],
        "claim": [],
    },
    "requirements": {
        "source": "",
        "tables_from": "",
        "routes_from": "",
        "views_from": "",
    },
    "probe": [],
    "score": {
        "weights": {
            "skills": 1.0, "tests": 2.0, "code": 1.0,
            "requirements": 2.0, "materials": 1.5, "probes": 1.0,
        },
    },
}


class ConfigError(Exception):
    pass


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def find_root(start: Path | None = None) -> Path | None:
    """从当前目录逐级往上找 adone.toml。"""
    cur = (start or Path.cwd()).resolve()
    for d in [cur, *cur.parents]:
        if (d / CONFIG_NAME).is_file():
            return d
    return None


@dataclass
class Config:
    root: Path
    data: dict
    path: Path | None = None

    @classmethod
    def load(cls, root: Path | None = None) -> "Config":
        r = root or find_root()
        if r is None:
            raise ConfigError(
                f"找不到 {CONFIG_NAME}（从当前目录一路往上都没有）。"
                f"在项目根跑一次 adone init，它会探测并生成一份。")
        p = r / CONFIG_NAME
        try:
            raw = tomllib.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            raise ConfigError(f"{p} 解析失败：{e}") from e
        return cls(root=r.resolve(), data=deep_merge(DEFAULTS, raw), path=p)

    @classmethod
    def from_dict(cls, root: Path, raw: dict) -> "Config":
        return cls(root=root.resolve(), data=deep_merge(DEFAULTS, raw))

    # ---------------------------------------------------------------- 取值

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def path_of(self, rel: str) -> Path:
        return self.root / rel

    @property
    def name(self) -> str:
        return self.get("project.name") or self.root.name

    @property
    def state_dir(self) -> Path:
        return self.root / self.get("project.state_dir", ".adone")

    @property
    def material_dir(self) -> Path:
        return self.root / self.get("project.material_dir", "adone")

    @property
    def acceptance_dir(self) -> Path:
        return self.material_dir / "acceptance"

    @property
    def requirements_dir(self) -> Path:
        return self.material_dir / "requirements"

    @property
    def skills_dir(self) -> Path:
        return self.root / self.get("project.skills_dir", ".cursor/skills")

    @property
    def receipts_dir(self) -> Path:
        return self.state_dir / "receipts"

    @property
    def latest_receipt(self) -> Path:
        return self.state_dir / "latest.json"

    @property
    def baseline(self) -> Path:
        return self.state_dir / "test-baseline.json"

    @property
    def policy_baseline(self) -> Path:
        return self.state_dir / "policy-baseline.json"

    @property
    def chain(self) -> Path:
        return self.state_dir / "chain.json"

    @property
    def audits_dir(self) -> Path:
        return self.state_dir / "audits"

    @property
    def latest_audit(self) -> Path:
        return self.state_dir / "audit.json"

    @property
    def cover_out(self) -> Path:
        return self.state_dir / "cover.out"

    @property
    def dirty(self) -> Path:
        return self.state_dir / "dirty"

    @property
    def report(self) -> Path:
        return self.state_dir / "report.html"

    @property
    def audit_report(self) -> Path:
        return self.state_dir / "audit.html"

    @property
    def ecosystems(self) -> list[str]:
        return list(self.get("project.ecosystems", []) or [])

    # ---------------------------------------------------------------- 体检

    def problems(self) -> list[str]:
        """拿配置对现实核一遍。给 doctor 用，也在 gate run 前跑一次。"""
        out: list[str] = []

        if not self.get("gate.watch_roots"):
            out.append("gate.watch_roots 是空的：受监视代码树为空，树哈希会恒等，"
                       "门禁将形同虚设")
        for r in self.get("gate.watch_roots", []):
            if not (self.root / r).is_dir():
                out.append(f"gate.watch_roots 里的 {r} 不是一个目录")
        if not self.get("gate.watch_exts"):
            out.append("gate.watch_exts 是空的：不会有任何文件参与哈希")

        steps = self.get("gate.step", []) or []
        if not steps:
            out.append("一个 gate.step 都没配：门禁跑起来什么也不会执行")
        for i, s in enumerate(steps, 1):
            if not s.get("name"):
                out.append(f"第 {i} 个 gate.step 没有 name")
            if not s.get("argv"):
                out.append(f"gate.step「{s.get('name', i)}」没有 argv")
            cwd = s.get("cwd", ".")
            if not (self.root / cwd).is_dir():
                out.append(f"gate.step「{s.get('name', i)}」的 cwd 不存在：{cwd}")

        thr = self.get("coverage.threshold")
        if thr is not None and not isinstance(thr, (int, float)):
            out.append("coverage.threshold 不是数字")
        if thr is not None and not self.get("coverage.source"):
            out.append("配了 coverage.threshold 却没配 coverage.source，"
                       "不知道该从哪一步的输出里读覆盖率")

        for key in ("requirements.tables_from", "requirements.routes_from",
                    "requirements.views_from", "requirements.source"):
            rel = self.get(key)
            if rel and not (self.root / rel).exists():
                out.append(f"{key} 指向的路径不存在：{rel}")

        for pair in self.get("consistency.pair", []) or []:
            for side in ("a", "b"):
                rel = pair.get(side)
                if not rel:
                    out.append(f"consistency.pair 缺 {side}")
                elif not (self.root / rel).exists():
                    out.append(f"consistency.pair 的 {side} 不存在：{rel}")

        for d in self.get("docs.excerpt", []) or []:
            for side in ("file", "against"):
                rel = d.get(side)
                if rel and not (self.root / rel).exists():
                    out.append(f"docs.excerpt 的 {side} 不存在：{rel}")

        return out
