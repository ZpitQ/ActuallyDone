"""Node / TypeScript 适配器（vitest 与 jest 的常见输出）。"""

from __future__ import annotations

import re
from pathlib import Path

from ..model import FuncBody, TestResult
from .base import (CAP_COVERAGE, CAP_FUNCS, CAP_TESTS, CAP_VIEWS, Adapter,
                   brace_funcs, read)

# vitest / jest 的逐条行：✓ 名字 / × 名字 / ↓ 名字（skipped）
TICK_RE = re.compile(r"^\s*[✓√]\s+(.+?)(?:\s+\d+ms)?$", re.M)
CROSS_RE = re.compile(r"^\s*[×✗x]\s+(.+?)(?:\s+\d+ms)?$", re.M)
DOWN_RE = re.compile(r"^\s*[↓-]\s+(.+?)\s+\[skipped\]", re.M)
# 汇总行：Tests  12 passed | 1 failed | 2 skipped (15)
SUM_RE = re.compile(r"Tests?\s+(?:(\d+) failed[^\n]*?)?(\d+) passed", re.I)
JEST_SUM_RE = re.compile(r"Tests:\s+(?:(\d+) failed, )?(?:(\d+) skipped, )?(\d+) passed")
COV_RE = re.compile(r"All files\s*\|\s*([\d.]+)")
NAME_RE = re.compile(r"""^\s*(?:it|test)(?:\.\w+)?\(\s*['"`](.+?)['"`]""", re.M)
FUNC_START = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function\s+\w+|const\s+\w+\s*=\s*(?:async\s*)?\()")
ASSERT_WORDS = ("expect(", "assert.", "assert(", "should.", "toEqual", "toBe")


def js_func_name(decl: str) -> str:
    m = re.search(r"function\s+(\w+)", decl) or re.search(r"const\s+(\w+)", decl)
    return m.group(1) if m else "?"


class NodeAdapter(Adapter):
    name = "node"
    caps = {CAP_TESTS, CAP_COVERAGE, CAP_FUNCS, CAP_VIEWS}
    markers = ("package.json", "*/package.json")
    source_exts = (".ts", ".tsx", ".js", ".jsx", ".vue")

    def suggest_steps(self, hint_dir: str) -> list[dict]:
        pkg = self.root / hint_dir / "package.json"
        scripts: dict = {}
        if pkg.exists():
            import json
            try:
                scripts = json.loads(read(pkg)).get("scripts", {}) or {}
            except Exception:
                scripts = {}
        steps: list[dict] = []
        if "lint" in scripts:
            steps.append({"name": "前端 lint", "cwd": hint_dir,
                          "argv": ["npm", "run", "lint"]})
        if "test" in scripts:
            steps.append({"name": "前端测试", "cwd": hint_dir, "kind": "test",
                          "adapter": "node",
                          "argv": ["npm", "run", "test", "--", "--run"]})
        if "build" in scripts:
            steps.append({"name": "前端构建", "cwd": hint_dir,
                          "argv": ["npm", "run", "build"]})
        return steps

    def suggest_watch(self, hint_dir: str) -> tuple[list[str], list[str]]:
        src = f"{hint_dir}/src" if (self.root / hint_dir / "src").is_dir() else hint_dir
        return ([src], [".ts", ".tsx", ".vue", ".js", ".jsx"])

    # ------------------------------------------------------------ 测试

    def parse_test_output(self, text: str) -> TestResult | None:
        passed = [n.strip() for n in TICK_RE.findall(text)]
        failed = [n.strip() for n in CROSS_RE.findall(text)]
        skipped = [n.strip() for n in DOWN_RE.findall(text)]

        n_pass, n_fail, n_skip = len(passed), len(failed), len(skipped)
        m = JEST_SUM_RE.search(text) or SUM_RE.search(text)
        if m:
            g = m.groups()
            # 汇总行比逐条行可靠：reporter 精简模式下逐条行可能一条都没有
            if len(g) == 3:
                n_fail = int(g[0] or 0)
                n_skip = int(g[1] or 0)
                n_pass = int(g[2])
            else:
                n_fail = int(g[0] or 0)
                n_pass = int(g[1])
        if not (n_pass or n_fail or n_skip):
            return TestResult(parsed=False)

        cov = COV_RE.search(text)
        return TestResult(
            passed=n_pass, failed=n_fail, skipped=n_skip, skip_top=n_skip,
            passed_names=passed, failed_names=failed, skipped_names=skipped,
            coverage=float(cov.group(1)) if cov else None,
        )

    def test_files(self, roots: list[Path]) -> list[Path]:
        out: list[Path] = []
        for r in roots:
            if not r.is_dir():
                continue
            for pat in ("*.test.ts", "*.test.js", "*.spec.ts", "*.spec.js",
                        "*.test.tsx", "*.spec.tsx"):
                out.extend(sorted(r.rglob(pat)))
        return sorted(set(out))

    def test_names(self, roots: list[Path]) -> set[str] | None:
        names: set[str] = set()
        for p in self.test_files(roots):
            names |= {n.strip() for n in NAME_RE.findall(read(p))}
        return names

    def iter_test_funcs(self, path: Path) -> list[FuncBody]:
        """把每个 it/test 块当作一个用例函数。"""
        lines = read(path).splitlines()
        out: list[FuncBody] = []
        for i, ln in enumerate(lines):
            m = NAME_RE.match(ln)
            if not m:
                continue
            depth = 0
            body: list[str] = []
            for j in range(i, len(lines)):
                raw = lines[j]
                depth += raw.count("{") - raw.count("}")
                s = raw.strip()
                if s:
                    body.append(s)
                if j > i and depth <= 0:
                    break
            out.append(FuncBody(name=m.group(1).strip(), line=i + 1, body=body[1:-1]))
        return out

    def is_assertionless(self, body: list[str]) -> bool:
        return not any(w in ln for ln in body for w in ASSERT_WORDS)

    def skip_sites(self, text: str) -> int:
        return len(re.findall(r"\b(?:it|test|describe)\.(?:skip|todo)\b|\bxit\(|\bxdescribe\(",
                              text))

    # ------------------------------------------------------------ 代码

    def iter_funcs(self, path: Path) -> list[FuncBody]:
        return brace_funcs(read(path).splitlines(), FUNC_START, js_func_name)

    def zero_cover(self, profile: Path, cwd: Path) -> tuple[int, int] | None:
        """读 lcov：FN 声明函数，FNDA 记录命中次数。"""
        if not profile.exists() or profile.suffix not in (".info", ".lcov"):
            return None
        total = zero = 0
        hits: dict[str, int] = {}
        for ln in read(profile).splitlines():
            if ln.startswith("FN:"):
                name = ln.split(",", 1)[-1]
                hits.setdefault(name, 0)
            elif ln.startswith("FNDA:"):
                cnt, _, name = ln[5:].partition(",")
                hits[name] = hits.get(name, 0) + int(cnt or 0)
        total = len(hits)
        zero = sum(1 for v in hits.values() if v == 0)
        return (zero, total) if total else None

    def views(self, target: Path) -> set[str] | None:
        if not target.is_dir():
            return None
        out: set[str] = set()
        for pat in ("*.vue", "*.tsx", "*.jsx"):
            out |= {p.name for p in target.rglob(pat)}
        return out
