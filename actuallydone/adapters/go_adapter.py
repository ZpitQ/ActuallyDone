"""Go 适配器。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..model import FuncBody, TestResult
from .base import (CAP_COVERAGE, CAP_FUNCS, CAP_ROUTES, CAP_SINGLE_TEST,
                   CAP_TESTS, Adapter, brace_funcs, read)

# 必须带 re.M：go test 的结果行散布在多行输出里，少了它 findall 只会看字符串开头，
# 解析出 0 个用例——而 0 个用例又长得很像「测试没跑」，会把门禁引向错误结论。
PASS_RE = re.compile(r"^\s*--- PASS: (\S+)", re.M)
FAIL_RE = re.compile(r"^\s*--- FAIL: (\S+)", re.M)
SKIP_RE = re.compile(r"^\s*--- SKIP: (\S+)", re.M)
COVER_RE = re.compile(r"coverage: ([\d.]+)% of statements")
TESTFUNC_RE = re.compile(r"^func (Test\w+)\(", re.M)
FUNC_START = re.compile(r"^func\b")
ASSERT_WORDS = ("t.Error", "t.Fatal", "t.Errorf", "t.Fatalf", "require.", "assert.",
                "b.Error", "b.Fatal")
CHI_RE = re.compile(r'r\.(?:Get|Post|Put|Patch|Delete|Head|Options|Route|Handle)'
                    r'(?:Func)?\("([^"]*)"')


def func_name(decl: str) -> str:
    """从 func 声明行取名字，方法要跳过接收者：func (w *W) Start() -> Start。"""
    rest = decl[len("func "):].lstrip()
    if rest.startswith("("):
        depth = 0
        for i, ch in enumerate(rest):
            depth += (ch == "(") - (ch == ")")
            if depth == 0:
                rest = rest[i + 1:].lstrip()
                break
    return rest.split("(")[0].strip() or "?"


class GoAdapter(Adapter):
    name = "go"
    caps = {CAP_TESTS, CAP_COVERAGE, CAP_FUNCS, CAP_ROUTES, CAP_SINGLE_TEST}
    markers = ("go.mod", "*/go.mod")
    source_exts = (".go",)

    def suggest_steps(self, hint_dir: str) -> list[dict]:
        return [
            {"name": "gofmt", "cwd": hint_dir, "argv": ["gofmt", "-l", "."],
             "kind": "fmt"},
            {"name": "go build", "cwd": hint_dir, "argv": ["go", "build", "./..."]},
            {"name": "go vet", "cwd": hint_dir, "argv": ["go", "vet", "./..."]},
            {"name": "go test", "cwd": hint_dir, "kind": "test", "adapter": "go",
             "argv": ["go", "test", "./...", "-count=1", "-v",
                      "-coverprofile={cover_out}"]},
        ]

    def suggest_watch(self, hint_dir: str) -> tuple[list[str], list[str]]:
        return ([hint_dir], [".go"])

    # ------------------------------------------------------------ 测试

    def parse_test_output(self, text: str) -> TestResult | None:
        passed = PASS_RE.findall(text)
        failed = FAIL_RE.findall(text)
        skipped = SKIP_RE.findall(text)
        cov = COVER_RE.findall(text)
        if not (passed or failed or skipped):
            # 没有 -v 时 go test 只打 ok/FAIL，逐条数据无从谈起
            return TestResult(parsed=False)
        return TestResult(
            passed=len(passed), failed=len(failed), skipped=len(skipped),
            skip_top=len({n for n in skipped if "/" not in n}),
            passed_names=passed, failed_names=failed, skipped_names=skipped,
            coverage=float(cov[-1]) if cov else None,
        )

    def test_files(self, roots: list[Path]) -> list[Path]:
        out: list[Path] = []
        for r in roots:
            if r.is_dir():
                out.extend(sorted(r.rglob("*_test.go")))
        return out

    def test_names(self, roots: list[Path]) -> set[str] | None:
        names: set[str] = set()
        for p in self.test_files(roots):
            names |= set(TESTFUNC_RE.findall(read(p)))
        return names

    def single_test_argv(self, name: str) -> list[str] | None:
        # 子测试名（TestX/case_1）里的斜杠是 -run 的分隔符，只按顶层跑，
        # 上层核对 --- PASS 时也只认顶层，两边口径一致
        top = name.split("/")[0]
        if not top:
            return None
        return ["go", "test", "./...", "-run", f"^{top}$", "-count=1", "-v"]

    def iter_test_funcs(self, path: Path) -> list[FuncBody]:
        return [f for f in brace_funcs(read(path).splitlines(), FUNC_START, func_name)
                if f.name.startswith("Test")]

    def is_assertionless(self, body: list[str]) -> bool:
        return not any(w in ln for ln in body for w in ASSERT_WORDS)

    def skip_sites(self, text: str) -> int:
        return len(re.findall(r"\bt\.Skip(?:f|Now)?\(", text))

    # ------------------------------------------------------------ 代码

    def iter_funcs(self, path: Path) -> list[FuncBody]:
        return brace_funcs(read(path).splitlines(), FUNC_START, func_name)

    def zero_cover(self, profile: Path, cwd: Path) -> tuple[int, int] | None:
        if not profile.exists():
            return None
        from ..gate import launch_argv, resolve_cmd
        exe = resolve_cmd("go", cwd) or "go"
        proc = subprocess.run(launch_argv(exe, ["tool", "cover", f"-func={str(profile)}"]),
                              cwd=cwd, capture_output=True, text=True)
        if proc.returncode != 0:
            return None
        rows = [ln.split() for ln in proc.stdout.splitlines() if ln.strip()]
        # 末列精确比对："100.0%".endswith("0.0%") 是真，用 endswith 会把满覆盖当零覆盖
        zero = sum(1 for r in rows if r and r[-1] == "0.0%" and r[0] != "total:")
        total = sum(1 for r in rows if r and r[0] != "total:")
        return (zero, total) if total else None

    def routes(self, target: Path) -> set[str] | None:
        files = sorted(target.rglob("*.go")) if target.is_dir() else [target]
        out: set[str] = set()
        for p in files:
            out |= set(CHI_RE.findall(read(p)))
        return out
