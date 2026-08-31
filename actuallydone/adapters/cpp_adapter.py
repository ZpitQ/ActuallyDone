"""C++ 适配器（CMake / CTest / GoogleTest / Catch2）。

配置里一律写 `cmake` / `ctest`，由 gate.resolve_cmd 在 Windows 上对上
`cmake.exe` / `ctest.exe`。步骤用 `cmake --build` 与 `cmake -E chdir`，
不绑某个生成器，Visual Studio / Ninja / Unix Makefiles 都能跑。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..model import FuncBody, TestResult
from .base import (CAP_COVERAGE, CAP_FUNCS, CAP_SINGLE_TEST, CAP_TESTS, Adapter,
                   brace_funcs, companion_stems, read)

# GoogleTest / 自研迷你跑器：可选的 CTest「1: 」前缀
GTEST_OK_RE = re.compile(r"^(?:\d+:\s*)?\[\s+OK\s+\]\s+(\S+)", re.M)
# 汇总行是「[  FAILED  ] 1 tests.」，名字必须以字母开头，才能和用例行分开
GTEST_FAIL_RE = re.compile(r"^(?:\d+:\s*)?\[\s+FAILED\s+\]\s+([A-Za-z_]\S*)", re.M)
GTEST_SKIP_RE = re.compile(r"^(?:\d+:\s*)?\[\s+SKIPPED\s+\]\s+(\S+)", re.M)
# CTest -V：1/2 Test #1: name ....   Passed
CTEST_RE = re.compile(
    r"^\s*\d+/\d+\s+Test\s+#\d+:\s+(\S+)\s*\.+\s*"
    r"(?:\*\*\*)?(Passed|Failed|Not Run|Timeout|Skipped)",
    re.M | re.I)
# Catch2 v2/v3 逐条：passed / failed 行里带用例名
CATCH_PASS_RE = re.compile(r"^\s*(?:passed|PASSED):\s+(.+?)(?:\s+\(\d|$)", re.M)
CATCH_FAIL_RE = re.compile(r"^\s*(?:failed|FAILED):\s+(.+?)(?:\s+\(\d|$)", re.M)
GTEST_MACRO_RE = re.compile(
    r"^\s*TEST(?:_F|_P)?\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)", re.M)
CATCH_MACRO_RE = re.compile(
    r'^\s*TEST_CASE\s*\(\s*"([^"]+)"', re.M)
CPP_FUNC_START = re.compile(
    r"^\s*(?:(?:inline|static|virtual|constexpr|explicit|friend|unsigned|"
    r"signed|long|short|const|volatile|typename|template)\s+)*"
    r"[\w:<>*&]+\s+(\w+)\s*\(")
ASSERT_WORDS = (
    "ASSERT_", "EXPECT_", "ASSERT(", "EXPECT(",
    "REQUIRE(", "CHECK(", "CHECK_EQ", "REQUIRE_EQ",
    "assert(", "static_assert", "FAIL()", "ADD_FAILURE",
)
SKIP_RE = re.compile(
    r"\bGTEST_SKIP\b|\bDISABLED_\w+|"
    r"\bSUCCEED\(\);\s*$|"
    r"\bSKIP\s*\(|\bSKIP_TEST\b|"
    r"Catch::TestCaseSkipped",
    re.M)
SOURCE_EXTS = (".cpp", ".cc", ".cxx", ".c++", ".hpp", ".hh", ".hxx", ".h")


def _gtest_name(suite: str, case: str) -> str:
    return f"{suite}.{case}"


def cpp_func_name(decl: str) -> str:
    m = re.search(r"(\w+)\s*\(", decl)
    return m.group(1) if m else "?"


def _is_test_file(path: Path) -> bool:
    stem = path.stem
    parent = path.parent.name.lower()
    if parent in {"test", "tests", "gtest", "unittests"}:
        return path.suffix.lower() in {".cpp", ".cc", ".cxx", ".c++"}
    low = stem.lower()
    return low.startswith("test_") or low.endswith("_test") or low.endswith("_tests")


class CppAdapter(Adapter):
    name = "cpp"
    caps = {CAP_TESTS, CAP_SINGLE_TEST, CAP_COVERAGE, CAP_FUNCS}
    markers = ("CMakeLists.txt", "*/CMakeLists.txt",
               "meson.build", "*/meson.build")
    source_exts = SOURCE_EXTS

    def _base(self, hint_dir: str) -> Path:
        return self.root if hint_dir in ("", ".") else self.root / hint_dir

    def _rel(self, hint_dir: str, name: str) -> str:
        return name if hint_dir in ("", ".") else f"{hint_dir}/{name}"

    def suggest_steps(self, hint_dir: str) -> list[dict]:
        base = self._base(hint_dir)
        if (base / "CMakeLists.txt").is_file():
            # -DCMAKE_BUILD_TYPE 给单配置生成器（Ninja / Makefiles）；
            # --config / -C Release 给 Visual Studio 多配置。三边同一份 argv。
            return [
                {"name": "cmake configure", "cwd": hint_dir,
                 "argv": ["cmake", "-S", ".", "-B", "build",
                          "-DCMAKE_BUILD_TYPE=Release"]},
                {"name": "cmake build", "cwd": hint_dir,
                 "argv": ["cmake", "--build", "build", "--config", "Release"]},
                {"name": "ctest", "cwd": hint_dir, "kind": "test",
                 "adapter": "cpp",
                 "argv": ["cmake", "-E", "chdir", "build", "ctest",
                          "--output-on-failure", "-V", "-C", "Release"]},
            ]
        if (base / "meson.build").is_file():
            return [
                {"name": "meson setup", "cwd": hint_dir,
                 "argv": ["meson", "setup", "build", "--buildtype=release"]},
                {"name": "meson compile", "cwd": hint_dir,
                 "argv": ["meson", "compile", "-C", "build"]},
                {"name": "meson test", "cwd": hint_dir, "kind": "test",
                 "adapter": "cpp",
                 "argv": ["meson", "test", "-C", "build", "-v"]},
            ]
        return []

    def suggest_watch(self, hint_dir: str) -> tuple[list[str], list[str]]:
        base = self._base(hint_dir)
        roots: list[str] = []
        for name in ("include", "src", "tests", "test"):
            if (base / name).is_dir():
                roots.append(self._rel(hint_dir, name))
        if not roots:
            roots = [hint_dir]
        return (roots, [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h"])

    # ------------------------------------------------------------ 测试

    def parse_test_output(self, text: str) -> TestResult | None:
        g_ok = GTEST_OK_RE.findall(text)
        g_fail = GTEST_FAIL_RE.findall(text)
        g_skip = GTEST_SKIP_RE.findall(text)
        if g_ok or g_fail or g_skip:
            return TestResult(passed=len(g_ok), failed=len(g_fail),
                              skipped=len(g_skip), skip_top=len(g_skip),
                              passed_names=g_ok, failed_names=g_fail,
                              skipped_names=g_skip)
        catch_p = [n.strip() for n in CATCH_PASS_RE.findall(text)]
        catch_f = [n.strip() for n in CATCH_FAIL_RE.findall(text)]
        if catch_p or catch_f:
            return TestResult(passed=len(catch_p), failed=len(catch_f),
                              skipped=0, skip_top=0,
                              passed_names=catch_p, failed_names=catch_f)
        rows = CTEST_RE.findall(text)
        if rows:
            p = [n for n, s in rows if s.lower() == "passed"]
            f = [n for n, s in rows if s.lower() in {"failed", "timeout"}]
            s = [n for n, st in rows if st.lower() in {"skipped", "not run"}]
            return TestResult(passed=len(p), failed=len(f), skipped=len(s),
                              skip_top=len(s), passed_names=p, failed_names=f,
                              skipped_names=s)
        return TestResult(parsed=False)

    def test_files(self, roots: list[Path]) -> list[Path]:
        out: list[Path] = []
        for r in roots:
            if not r.is_dir():
                continue
            for ext in (".cpp", ".cc", ".cxx", ".c++"):
                out.extend(p for p in sorted(r.rglob(f"*{ext}")) if _is_test_file(p))
        return sorted(set(out))

    def test_names(self, roots: list[Path]) -> set[str] | None:
        names: set[str] = set()
        for p in self.test_files(roots):
            text = read(p)
            names |= {_gtest_name(a, b) for a, b in GTEST_MACRO_RE.findall(text)}
            names |= set(CATCH_MACRO_RE.findall(text))
        return names

    def single_test_argv(self, name: str) -> list[str] | None:
        if not name:
            return None
        # CTest 的 -R 对 add_test(NAME) 生效；GTest 的 Suite.Name 交给子进程
        filt = name
        return ["cmake", "-E", "chdir", "build", "ctest",
                "--output-on-failure", "-V", "-C", "Release",
                "-R", f"^{re.escape(name.split('.')[0] if '.' in name else name)}",
                "--", f"--gtest_filter={filt}", f"--only={filt}"]

    def _names_in(self, path: Path) -> list[str]:
        if not path.is_file():
            return []
        text = read(path)
        return ([_gtest_name(a, b) for a, b in GTEST_MACRO_RE.findall(text)]
                + CATCH_MACRO_RE.findall(text))

    def related_tests(self, rel_paths: list[str]) -> list[str] | None:
        indexed = self.test_files([self.root])
        names: list[str] = []
        for rel in rel_paths:
            p = self.root / rel
            if p.suffix.lower() not in self.source_exts:
                continue
            if _is_test_file(p):
                names.extend(self._names_in(p))
                continue
            stem = p.stem.lower()
            want = {s.lower() for s in companion_stems(p.stem)}
            for tf in indexed:
                if tf.stem.lower() in want or stem in tf.stem.lower():
                    names.extend(self._names_in(tf))
                    continue
                for n in self._names_in(tf):
                    suite = n.split(".", 1)[0].lower()
                    if stem == suite or stem in suite:
                        names.append(n)
        return sorted(set(names))

    def related_test_argv(self, names: list[str]) -> list[str] | None:
        parts: list[str] = []
        seen: set[str] = set()
        for n in names:
            key = n.split(".", 1)[0] if "." in n else n
            if key and key not in seen:
                seen.add(key)
                parts.append(re.escape(key))
        if not parts:
            return None
        return ["cmake", "-E", "chdir", "build", "ctest",
                "--output-on-failure", "-V", "-C", "Release",
                "-R", f"^({'|'.join(parts)})"]

    def iter_test_funcs(self, path: Path) -> list[FuncBody]:
        lines = read(path).splitlines()
        out: list[FuncBody] = []
        for i, ln in enumerate(lines):
            gm = re.match(
                r"^\s*TEST(?:_F|_P)?\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)", ln)
            cm = re.match(r'^\s*TEST_CASE\s*\(\s*"([^"]+)"', ln)
            if not gm and not cm:
                continue
            name = _gtest_name(gm.group(1), gm.group(2)) if gm else cm.group(1)
            depth = 0
            opened = False
            body: list[str] = []
            for raw in lines[i:]:
                stripped = re.sub(r"//.*$", "", raw).strip()
                depth += raw.count("{") - raw.count("}")
                if "{" in raw:
                    opened = True
                if stripped:
                    body.append(stripped)
                if opened and depth <= 0:
                    break
            inner = body[1:-1] if len(body) > 2 else []
            out.append(FuncBody(name=name, line=i + 1, body=inner))
        return out

    def is_assertionless(self, body: list[str]) -> bool:
        return not any(w in ln for ln in body for w in ASSERT_WORDS)

    def skip_sites(self, text: str) -> int:
        return len(SKIP_RE.findall(text))

    # ------------------------------------------------------------ 代码

    def iter_funcs(self, path: Path) -> list[FuncBody]:
        return brace_funcs(read(path).splitlines(), CPP_FUNC_START, cpp_func_name)

    def zero_cover(self, profile: Path, cwd: Path) -> tuple[int, int] | None:
        if not profile.exists():
            return None
        if profile.suffix not in {".info", ".lcov"} and profile.name != "lcov.info":
            return None
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

    def coverage_from_reports(self, *roots: Path) -> float | None:
        files: list[Path] = []
        for root in roots:
            if not root.is_dir():
                continue
            files.extend(root.rglob("lcov.info"))
            files.extend(root.rglob("coverage.info"))
        if not files:
            return None
        lf = lh = 0
        for p in files:
            for ln in read(p).splitlines():
                if ln.startswith("LF:"):
                    lf += int(ln[3:] or 0)
                elif ln.startswith("LH:"):
                    lh += int(ln[3:] or 0)
        if lf <= 0:
            return None
        return round(100.0 * lh / lf, 1)

    def coverage_diagnosis(self, *roots: Path, output: str = "") -> str:
        return ("C++ 覆盖率认 lcov.info / coverage.info（gcov / llvm-cov）。"
                "MSVC 没有 gcov：覆盖率会标未评估，不要填 coverage.threshold。"
                "GCC/Clang 可在 configure 加 -DCMAKE_CXX_FLAGS=--coverage，再用 lcov 出报告")
