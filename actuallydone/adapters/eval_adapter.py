"""可选的场景评估适配器。

不是一门语言生态，也不会被探测选中：`markers` 为空，`detect_all` 不会把它
当成 `tests.adapter`。只有用户在 `[[gate.step]]` 里手写 `adapter = "eval"`
时才生效。不实现覆盖率。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from ..model import FuncBody, TestResult
from .base import CAP_SINGLE_TEST, CAP_TESTS, Adapter, read

# PASS recall#退货时效
# 只取前两列：FAIL 后面常跟原因（官方 demo 就是这样），行尾锚会把整行丢掉
RESULT_LINE_RE = re.compile(r"^(PASS|FAIL|SKIP)\s+(\S+)", re.M)
EXPECT_KEYS = ("must", "must_not", "expect", "expect_interrupt")


def has_eval_step(cfg) -> bool:
    return any((s.get("adapter") or "").strip().lower() == "eval"
               for s in (cfg.get("gate.step") or []))


def first_eval_step(cfg) -> dict | None:
    for s in cfg.get("gate.step") or []:
        if (s.get("adapter") or "").strip().lower() == "eval":
            return s
    return None


class EvalAdapter(Adapter):
    name = "eval"
    caps = {CAP_TESTS, CAP_SINGLE_TEST}
    markers: tuple[str, ...] = ()
    source_exts: tuple[str, ...] = ()

    def suggest_steps(self, hint_dir: str) -> list[dict]:
        return []

    def suggest_watch(self, hint_dir: str) -> tuple[list[str], list[str]]:
        return ([], [])

    def parse_test_output(self, text: str) -> TestResult | None:
        rows = RESULT_LINE_RE.findall(text)
        if not rows:
            return TestResult(parsed=False)
        passed, failed, skipped = [], [], []
        for status, name in rows:
            if status == "PASS":
                passed.append(name)
            elif status == "FAIL":
                failed.append(name)
            else:
                skipped.append(name)
        return TestResult(passed=len(passed), failed=len(failed),
                          skipped=len(skipped), skip_top=len(skipped),
                          passed_names=passed, failed_names=failed,
                          skipped_names=skipped)

    def test_files(self, roots: list[Path]) -> list[Path]:
        return sorted({p.resolve() for p in self._eval_files(roots)})

    def test_names(self, roots: list[Path]) -> set[str] | None:
        names: set[str] = set()
        for p in self.test_files(roots):
            for sc in self._scenarios(p):
                names.add(sc["id"])
        return names

    def single_test_argv(self, name: str) -> list[str] | None:
        if not name:
            return None
        argv = self._configured_argv()
        if not argv:
            return None
        return list(argv) + ["--only", name]

    def related_tests(self, rel_paths: list[str]) -> list[str] | None:
        names: list[str] = []
        for rel in rel_paths:
            p = self.root / rel
            parts = Path(rel.replace("\\", "/")).parts
            if p.suffix == ".toml" and "eval" in parts and p.is_file():
                names.extend(sc["id"] for sc in self._scenarios(p))
        return sorted(set(names))

    def related_test_argv(self, names: list[str]) -> list[str] | None:
        argv = self._configured_argv()
        if not argv or not names:
            return None
        out = list(argv)
        for n in names:
            out.extend(["--only", n])
        return out

    def iter_test_funcs(self, path: Path) -> list[FuncBody]:
        out: list[FuncBody] = []
        for i, sc in enumerate(self._scenarios(path), 1):
            body = [k for k in EXPECT_KEYS if _has_expect(sc.get(k))]
            out.append(FuncBody(name=sc["id"], line=i, body=body))
        return out

    def is_assertionless(self, body: list[str]) -> bool:
        return not body

    # ------------------------------------------------------------ 内部

    def _eval_dirs(self, roots: list[Path]) -> list[Path]:
        dirs: list[Path] = []
        seen: set[Path] = set()

        def add(p: Path) -> None:
            if not p.is_dir():
                return
            key = p.resolve()
            if key not in seen:
                seen.add(key)
                dirs.append(p)

        add(self.root / "adone" / "eval")
        for r in roots:
            if not r.is_dir():
                continue
            if r.name == "eval":
                add(r)
            elif (r / "eval").is_dir():
                add(r / "eval")
        return dirs

    def _eval_files(self, roots: list[Path]) -> list[Path]:
        out: list[Path] = []
        for d in self._eval_dirs(roots):
            out.extend(sorted(d.glob("*.toml")))
        return out

    def _scenarios(self, path: Path) -> list[dict]:
        try:
            data = tomllib.loads(read(path))
        except Exception:
            return []
        rows = data.get("scenario")
        if isinstance(rows, list):
            items = [r for r in rows if isinstance(r, dict)]
        else:
            items = [data] if isinstance(data, dict) else []
        out: list[dict] = []
        fallback = path.stem
        for item in items:
            sid = str(item.get("id") or "").strip() or fallback
            out.append({**item, "id": sid})
        return out

    def _configured_argv(self) -> list[str] | None:
        p = self.root / "adone.toml"
        if not p.is_file():
            return None
        try:
            from ..config import Config
            cfg = Config.load(self.root)
        except Exception:
            return None
        step = first_eval_step(cfg)
        argv = list((step or {}).get("argv") or [])
        return argv or None


def _has_expect(val) -> bool:
    # expect_interrupt = false 也是一条期望，不能当成空壳
    if val is None or val == [] or val == "":
        return False
    return True
