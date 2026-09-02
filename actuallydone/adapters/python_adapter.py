"""Python 适配器（unittest 与 pytest）。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..model import FuncBody, TestResult
from .base import (CAP_COVERAGE, CAP_FUNCS, CAP_SINGLE_TEST, CAP_TESTS, Adapter,
                   read)

# pytest 汇总行字段顺序不固定：默认 -q 是 "5 passed, 1 failed in 0.3s"
PYTEST_SUM_LINE_RE = re.compile(r"in [\d.]+s")
PYTEST_N_FAILED = re.compile(r"(\d+) failed")
PYTEST_N_PASSED = re.compile(r"(\d+) passed")
PYTEST_N_SKIPPED = re.compile(r"(\d+) skipped")
PYTEST_LINE_RE = re.compile(r"^(\S+::\S+)\s+(PASSED|FAILED|SKIPPED)", re.M)
# unittest -v: "test_foo (mod.Case) ... ok / FAIL / skipped 'why'"
UNITTEST_RE = re.compile(r"^(\w+) \([^)]+\)[^\n]*\.\.\. (ok|FAIL|ERROR|skipped)", re.M)
DEF_TEST_RE = re.compile(r"^\s*def (test\w*)\(", re.M)
DEF_RE = re.compile(r"^(\s*)def \w+\(")
ASSERT_WORDS = ("assert ", "assertEqual", "assertTrue", "assertRaises", "assertIn",
                "assertIs", "assertNot", "self.fail", "pytest.raises")


def _pytest_summary(text: str) -> TestResult | None:
    """从含 `in 0.3s` 的那一行分别捞 failed / passed / skipped，不依赖字段顺序。"""
    line = ""
    for ln in text.splitlines():
        if PYTEST_SUM_LINE_RE.search(ln) and any(
                w in ln for w in ("passed", "failed", "skipped")):
            line = ln
            break
    if not line:
        return None

    def n(pat: re.Pattern) -> int:
        m = pat.search(line)
        return int(m.group(1)) if m else 0

    failed, passed, skipped = n(PYTEST_N_FAILED), n(PYTEST_N_PASSED), n(PYTEST_N_SKIPPED)
    if failed + passed + skipped == 0:
        return None
    return TestResult(failed=failed, passed=passed, skipped=skipped, skip_top=skipped)


class PythonAdapter(Adapter):
    name = "python"
    caps = {CAP_TESTS, CAP_COVERAGE, CAP_FUNCS, CAP_SINGLE_TEST}
    markers = ("pyproject.toml", "setup.py", "requirements.txt")
    source_exts = (".py",)

    def suggest_steps(self, hint_dir: str) -> list[dict]:
        has_pytest = (self.root / hint_dir / "pytest.ini").exists() or \
            any((self.root / hint_dir).glob("tests/test_*.py"))
        argv = (["python3", "-m", "pytest", "-q"] if has_pytest
                else ["python3", "-m", "unittest", "discover", "-v"])
        return [{"name": "python 测试", "cwd": hint_dir, "kind": "test",
                 "adapter": "python", "argv": argv}]

    def suggest_watch(self, hint_dir: str) -> tuple[list[str], list[str]]:
        return ([hint_dir], [".py"])

    # ------------------------------------------------------------ 测试

    def parse_test_output(self, text: str) -> TestResult | None:
        rows = PYTEST_LINE_RE.findall(text)
        if rows:
            p = [n for n, s in rows if s == "PASSED"]
            f = [n for n, s in rows if s == "FAILED"]
            s = [n for n, s_ in rows if s_ == "SKIPPED"]
            return TestResult(passed=len(p), failed=len(f), skipped=len(s),
                              skip_top=len(s), passed_names=p, failed_names=f,
                              skipped_names=s)
        rows = UNITTEST_RE.findall(text)
        if rows:
            p = [n for n, s in rows if s == "ok"]
            f = [n for n, s in rows if s in ("FAIL", "ERROR")]
            s = [n for n, s_ in rows if s_ == "skipped"]
            return TestResult(passed=len(p), failed=len(f), skipped=len(s),
                              skip_top=len(s), passed_names=p, failed_names=f,
                              skipped_names=s)
        summed = _pytest_summary(text)
        if summed is not None:
            return summed
        return TestResult(parsed=False)

    def test_files(self, roots: list[Path]) -> list[Path]:
        out: list[Path] = []
        for r in roots:
            if r.is_dir():
                out.extend(sorted(r.rglob("test_*.py")))
                out.extend(sorted(r.rglob("*_test.py")))
        return sorted(set(out))

    def test_names(self, roots: list[Path]) -> set[str] | None:
        names: set[str] = set()
        for p in self.test_files(roots):
            names |= set(DEF_TEST_RE.findall(read(p)))
        return names

    def single_test_argv(self, name: str) -> list[str] | None:
        if not name:
            return None
        if "::" in name:   # pytest 的用例 ID 自己就是定位符
            return ["python3", "-m", "pytest", "-q", name]
        return ["python3", "-m", "unittest", "discover", "-v", "-k", name]

    def related_tests(self, rel_paths: list[str]) -> list[str] | None:
        names: list[str] = []
        indexed = self.test_files([self.root])
        for rel in rel_paths:
            p = self.root / rel
            if p.suffix != ".py":
                continue
            stem = p.stem
            targets: list[Path] = []
            if stem.startswith("test_") or stem.endswith("_test"):
                if p.is_file():
                    targets.append(p)
            else:
                for cand in (p.with_name(f"test_{stem}.py"),
                             p.with_name(f"{stem}_test.py")):
                    if cand.is_file():
                        targets.append(cand)
                for tf in indexed:
                    if tf.stem in {f"test_{stem}", f"{stem}_test"}:
                        targets.append(tf)
            for t in targets:
                names.extend(DEF_TEST_RE.findall(read(t)))
        return sorted(set(names))

    def related_test_argv(self, names: list[str]) -> list[str] | None:
        if not names:
            return None
        if any("::" in n for n in names):
            return ["python3", "-m", "pytest", "-q", *names]
        return ["python3", "-m", "unittest", "discover", "-v",
                "-k", " or ".join(names)]

    def iter_test_funcs(self, path: Path) -> list[FuncBody]:
        return [f for f in self.iter_funcs(path) if f.name.startswith("test")]

    def is_assertionless(self, body: list[str]) -> bool:
        return not any(w in ln for ln in body for w in ASSERT_WORDS)

    def skip_sites(self, text: str) -> int:
        return len(re.findall(r"@(?:unittest\.)?skip|pytest\.mark\.skip|self\.skipTest\(",
                              text))

    # ------------------------------------------------------------ 代码

    def iter_funcs(self, path: Path) -> list[FuncBody]:
        """Python 靠缩进切块：def 行的缩进决定这个函数在哪结束。"""
        lines = read(path).splitlines()
        out: list[FuncBody] = []
        for i, ln in enumerate(lines):
            m = DEF_RE.match(ln)
            if not m:
                continue
            indent = len(m.group(1))
            name = re.search(r"def (\w+)", ln).group(1)
            body: list[str] = []
            for j in range(i + 1, len(lines)):
                nxt = lines[j]
                if not nxt.strip():
                    continue
                cur_indent = len(nxt) - len(nxt.lstrip())
                if cur_indent <= indent:
                    break
                s = re.sub(r"#.*$", "", nxt).strip()
                if s:
                    body.append(s)
            out.append(FuncBody(name=name, line=i + 1, body=body))
        return out

    def zero_cover(self, profile: Path, cwd: Path) -> tuple[int, int] | None:
        """读 coverage.py 的 JSON 报告（coverage json -o ...）。"""
        if not profile.exists() or profile.suffix != ".json":
            return None
        try:
            data = json.loads(read(profile))
        except Exception:
            return None
        files = data.get("files") or {}
        if not files:
            return None
        zero = sum(1 for f in files.values()
                   if (f.get("summary") or {}).get("percent_covered", 0) == 0)
        return zero, len(files)
