"""Java / Kotlin / Groovy 适配器（Maven 与 Gradle，JUnit 4/5 与 TestNG）。"""

from __future__ import annotations

import csv
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..model import FuncBody, TestResult
from .base import (CAP_COVERAGE, CAP_FUNCS, CAP_ROUTES, CAP_SINGLE_TEST,
                   CAP_TESTS, CAP_VIEWS, Adapter, brace_funcs, companion_stems,
                   read)

# Maven 每个测试类打一行「Tests run: … -- in <类>」，Results: 段再打一行合计。
# 聚合行的判据是后面没有 - in / -- in；认错就把最后一个类的数字当全局合计。
SUREFIRE_RE = re.compile(
    r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)"
    r"(?!\s*-+\s*in\b)")
GRADLE_SUM_RE = re.compile(
    r"(\d+) tests? completed(?:,\s*(\d+) failed)?(?:,\s*(\d+) skipped)?", re.I)
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DISPLAY_RE = re.compile(r'@DisplayName\s*\(\s*"([^"]*)"\s*\)')
CLASS_RE = re.compile(r"\b(?:class|object|interface)\s+(\w+)")
TEST_ANN_RE = re.compile(
    r"@(?:Test|ParameterizedTest|RepeatedTest|TestFactory|TestTemplate)\b")
NOT_METHOD = {"if", "for", "while", "switch", "catch", "synchronized", "try",
              "return", "new", "throw", "else", "when", "assert", "class",
              "interface", "enum", "record", "object", "fun"}
# JUnit 5 的用例常常是包级可见：`void testAdd()`，不能要求必须有 public
METHOD_DECL_RE = re.compile(
    r"^\s*(?:(?:public|protected|private|static|final|synchronized|native|"
    r"abstract|default|strictfp|open|override|suspend|inline|internal|"
    r"actual|expect|operator|infix)\s+)*"
    r"(?:fun\s+(?:`([^`]+)`|(\w+))|[\w.<>,\[\]?]+\s+(\w+))\s*\(")
JAVA_FUNC_START = re.compile(
    r"^\s*(?:(?:public|protected|private|static|final|synchronized|native|"
    r"abstract|default|strictfp)\s+)*[\w.<>,\[\]?]+\s+\w+\s*\(")
KT_FUNC_START = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|open|override|suspend|"
    r"inline|actual|expect|operator|infix)\s+)*fun\s+")
GROOVY_FUNC_START = re.compile(
    r"^\s*(?:(?:public|protected|private|static)\s+)*"
    r"(?:def|void|int|long|boolean|String|Object)\s+\w+\s*\(")
SKIP_RE = re.compile(
    r"@Disabled\b|@Ignore\b|"
    r"\bassume(?:True|False|That|NoException)\s*\(|"
    r"\bAssumptions\.|"
    r"@(?:Enabled|Disabled)If\w*|"
    r"@(?:Enabled|Disabled)OnOs\b|"
    r"@(?:Enabled|Disabled)(?:OnJre|ForJreRange)\b|"
    r"@Test\s*\([^)]*\benabled\s*=\s*false")
PATH_ANN_RE = re.compile(
    r'@(Get|Post|Put|Patch|Delete|Request)Mapping\s*\(\s*'
    r'(?:(?:value|path)\s*=\s*)?"([^"]*)"')
JAXRS_PATH_RE = re.compile(r'@Path\s*\(\s*"([^"]*)"\s*\)')
TEST_STEM_END = ("Test", "Tests", "IT", "ITCase", "TestCase")
REPORT_GLOBS = (
    "**/target/surefire-reports/*.xml",
    "**/target/failsafe-reports/*.xml",
    "**/build/test-results/**/*.xml",
)
JACOCO_NAMES = {"jacoco.xml", "jacocoTestReport.xml", "jacoco.csv"}
# jacoco:report 采不到数据时打的原话。命令照样 BUILD SUCCESS，所以只能认这句
JACOCO_NO_DATA = "Skipping JaCoCo execution due to missing execution data file"
JACOCO_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__",
                    ".adone", ".idea", ".next", "dist"}
ASSERT_WORDS = (
    "assertEquals", "assertTrue", "assertFalse", "assertThat", "assertThrows",
    "assertDoesNotThrow", "assertAll", "assertNull", "assertNotNull",
    "assertSame", "assertNotSame", "assertArrayEquals", "assertInstanceOf",
    "Assertions.", "Assert.", "fail(", "failNow",
    "assertThatThrownBy", "assertThatExceptionOfType", "assertThatCode",
    "verify(", "verifyNoMoreInteractions", "verifyNoInteractions",
    "andExpect(", "andDo(",
    "Truth.", "assertWithMessage", "MatcherAssert",
    "assertThatThrown", "expectThrows",
)
STALE_SLACK = 2.0


def _blank_block_comments(text: str) -> str:
    """把 /* */ 换成等量空白，行号不动。brace_funcs 只剥 //，javadoc 会污染函数体。"""
    def repl(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))
    return re.sub(r"/\*.*?\*/", repl, text, flags=re.S)


def _func_name(decl: str) -> str:
    m = re.search(r"(?:fun\s+)?(?:`([^`]+)`|(\w+))\s*\(", decl)
    return (m.group(1) or m.group(2)) if m else "?"


def _simple_class(classname: str) -> str:
    return classname.rsplit(".", 1)[-1] if classname else "?"


def _clean_xml_name(name: str) -> str:
    name = re.sub(r"\[\d+]$", "", name)
    return re.sub(r"\(\)$", "", name)


def _join_path(prefix: str, path: str) -> str:
    if not prefix:
        return path if path.startswith("/") else f"/{path}" if path else "/"
    if not path:
        return prefix if prefix.startswith("/") else f"/{prefix}"
    a = prefix if prefix.startswith("/") else f"/{prefix}"
    b = path if path.startswith("/") else f"/{path}"
    return a.rstrip("/") + b


def _is_test_stem(stem: str) -> bool:
    return stem.startswith("Test") or any(stem.endswith(s) for s in TEST_STEM_END)


class JavaAdapter(Adapter):
    name = "java"
    caps = {CAP_TESTS, CAP_SINGLE_TEST, CAP_COVERAGE, CAP_FUNCS, CAP_ROUTES, CAP_VIEWS}
    markers = ("pom.xml", "build.gradle", "build.gradle.kts",
               "settings.gradle", "settings.gradle.kts",
               "*/pom.xml", "*/build.gradle", "*/build.gradle.kts",
               "*/settings.gradle", "*/settings.gradle.kts")
    source_exts = (".java", ".kt", ".groovy")

    # ------------------------------------------------------------ 探测

    def _base(self, hint_dir: str) -> Path:
        return self.root if hint_dir in ("", ".") else self.root / hint_dir

    def _is_maven(self, base: Path) -> bool:
        return (base / "pom.xml").is_file()

    def _is_gradle(self, base: Path) -> bool:
        return any((base / n).is_file() for n in (
            "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"))

    def _has_wrapper(self, base: Path, name: str) -> bool:
        """POSIX 上包装器要有执行位；Windows 上它叫 name.cmd / name.bat，执行位无意义。

        配置里一律写 ./mvnw，由 gate.resolve_cmd 在 Windows 上补出 .cmd，
        这样同一份 adone.toml 两边都跑得动。
        """
        if any((base / f"{name}{e}").is_file() for e in (".cmd", ".bat")):
            return True
        p = base / name
        return p.is_file() and os.access(p, os.X_OK)

    def _mvn_cmd(self, base: Path) -> list[str]:
        if self._has_wrapper(base, "mvnw"):
            return ["./mvnw", "-B", "-ntp"]
        return ["mvn", "-B", "-ntp"]

    def _gradle_cmd(self, base: Path) -> list[str]:
        if self._has_wrapper(base, "gradlew"):
            return ["./gradlew", "--console=plain"]
        return ["gradle", "--console=plain"]

    def _build_tool(self, hint: Path | None = None) -> str:
        base = hint or self.root
        if self._is_maven(base) or self._is_maven(self.root):
            return "maven"
        return "gradle"

    def suggest_steps(self, hint_dir: str) -> list[dict]:
        base = self._base(hint_dir)
        steps: list[dict] = []
        if self._is_maven(base):
            pom = read(base / "pom.xml") if (base / "pom.xml").is_file() else ""
            low = pom.lower()
            if "spotless" in low or "checkstyle" in low:
                steps.append({"name": "spotless:check", "cwd": hint_dir,
                              "argv": [*self._mvn_cmd(base), "spotless:check"]})
            argv = [*self._mvn_cmd(base)]
            if "jacoco" in low:
                # prepare-agent 必须在 test 前面，而且要显式写在 CLI 上：
                # pom 只声明了插件却没绑 prepare-agent 时，mvn test 不挂探针，
                # jacoco:report 只打一行 Skipping 就 BUILD SUCCESS，一份报告都没有
                argv += ["jacoco:prepare-agent", "test", "jacoco:report"]
            else:
                argv.append("test")
            steps.append({"name": "mvn test", "cwd": hint_dir, "kind": "test",
                          "adapter": "java", "argv": argv})
            return steps
        if self._is_gradle(base):
            texts = []
            for n in ("build.gradle", "build.gradle.kts"):
                if (base / n).is_file():
                    texts.append(read(base / n).lower())
            blob = "\n".join(texts)
            if "spotless" in blob or "checkstyle" in blob:
                steps.append({"name": "spotlessCheck", "cwd": hint_dir,
                              "argv": [*self._gradle_cmd(base), "spotlessCheck"]})
            argv = [*self._gradle_cmd(base), "cleanTest", "test"]
            if "jacoco" in blob:
                argv.append("jacocoTestReport")
            steps.append({"name": "gradle test", "cwd": hint_dir, "kind": "test",
                          "adapter": "java", "argv": argv})
        return steps

    def suggest_watch(self, hint_dir: str) -> tuple[list[str], list[str]]:
        # 不能退回 hint_dir 本身：tree_files 用裸 rglob，会把 target/generated-sources 哈希进去
        base = self._base(hint_dir)
        if (base / "src").is_dir():
            rel = "src" if hint_dir in ("", ".") else f"{hint_dir}/src"
            return ([rel], list(self.source_exts))
        roots: list[str] = []
        if base.is_dir():
            for child in sorted(base.iterdir()):
                if child.is_dir() and (child / "src").is_dir():
                    roots.append(f"{child.relative_to(self.root).as_posix()}/src")
        return (roots, list(self.source_exts))

    # ------------------------------------------------------------ 测试

    def parse_test_output(self, text: str) -> TestResult | None:
        return self.parse_test_run(text)

    def parse_test_run(self, text: str, *, cwd: Path | None = None,
                       since: float | None = None) -> TestResult | None:
        console = self._console_counts(text)
        xml = self._xml_cases(cwd, since) if cwd is not None else None
        coverage = self.coverage_from_reports(cwd, self.root) if cwd is not None else None

        if console and xml:
            xml_n = (xml["passed"] + xml["failed"] + xml["skipped"],
                     xml["failed"], xml["skipped"])
            con_n = (console["passed"] + console["failed"] + console["skipped"],
                     console["failed"], console["skipped"])
            if xml_n == con_n:
                return TestResult(
                    passed=xml["passed"], failed=xml["failed"], skipped=xml["skipped"],
                    skip_top=xml["skipped"],
                    passed_names=xml["passed_names"], failed_names=xml["failed_names"],
                    skipped_names=xml["skipped_names"], coverage=coverage)
            # 对不上：计数信控制台，名字留空——抽查因此标未评估，不标通过
            return TestResult(
                passed=console["passed"], failed=console["failed"],
                skipped=console["skipped"], skip_top=console["skipped"],
                coverage=coverage)
        if console:
            return TestResult(
                passed=console["passed"], failed=console["failed"],
                skipped=console["skipped"], skip_top=console["skipped"],
                coverage=coverage)
        if xml and (xml["passed"] or xml["failed"] or xml["skipped"]):
            return TestResult(
                passed=xml["passed"], failed=xml["failed"], skipped=xml["skipped"],
                skip_top=xml["skipped"],
                passed_names=xml["passed_names"], failed_names=xml["failed_names"],
                skipped_names=xml["skipped_names"], coverage=coverage)
        return TestResult(parsed=False)

    def _console_counts(self, text: str) -> dict | None:
        rows = SUREFIRE_RE.findall(text)
        if rows:
            run, fail, err, skip = (int(x) for x in rows[-1])
            failed = fail + err
            return {"passed": max(run - failed - skip, 0), "failed": failed, "skipped": skip}
        m = GRADLE_SUM_RE.search(text)
        if m:
            total, failed, skipped = int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)
            return {"passed": max(total - failed - skipped, 0),
                    "failed": failed, "skipped": skipped}
        return None

    def _xml_cases(self, cwd: Path, since: float | None) -> dict | None:
        files = self._report_files(cwd, since)
        if not files:
            return None
        passed: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        for p in files:
            try:
                root = ET.parse(p).getroot()
            except ET.ParseError:
                continue
            tag = root.tag.rsplit("}", 1)[-1]
            if tag not in ("testsuite", "testsuites"):
                continue
            suites = [root] if tag == "testsuite" else list(root.findall("testsuite"))
            if tag == "testsuites":
                suites += [el for el in root.iter()
                           if el is not root and el.tag.rsplit("}", 1)[-1] == "testsuite"]
            # 去重：iter 可能把直接子节点算两遍
            seen: set[int] = set()
            for suite in suites:
                if id(suite) in seen:
                    continue
                seen.add(id(suite))
                for case in suite.findall("testcase"):
                    classname = case.get("classname") or suite.get("name") or ""
                    raw = case.get("name") or ""
                    key = f"{_simple_class(classname)}#{_clean_xml_name(raw)}"
                    kids = {c.tag.rsplit("}", 1)[-1] for c in list(case)}
                    if "failure" in kids or "error" in kids:
                        failed.append(key)
                    elif "skipped" in kids:
                        skipped.append(key)
                    else:
                        passed.append(key)
        return {
            "passed": len(passed), "failed": len(failed), "skipped": len(skipped),
            "passed_names": passed, "failed_names": failed, "skipped_names": skipped,
        }

    def _report_files(self, cwd: Path, since: float | None) -> list[Path]:
        out: list[Path] = []
        floor = (since - STALE_SLACK) if since else None
        for pat in REPORT_GLOBS:
            for p in cwd.glob(pat):
                if not p.is_file():
                    continue
                if floor is not None and p.stat().st_mtime < floor:
                    continue
                out.append(p)
        return sorted(set(out))

    def test_files(self, roots: list[Path]) -> list[Path]:
        out: list[Path] = []
        for r in roots:
            if not r.is_dir():
                continue
            for ext in self.source_exts:
                for p in r.rglob(f"*{ext}"):
                    if _is_test_stem(p.stem):
                        out.append(p)
        return sorted(set(out))

    def _scan_test_methods(self, path: Path
                           ) -> list[tuple[str, str, int, str | None]]:
        """返回 (类名, 方法名, 行号, DisplayName 或 None)。"""
        lines = _blank_block_comments(read(path)).splitlines()
        class_name = path.stem
        pending: list[str] = []
        display: str | None = None
        out: list[tuple[str, str, int, str | None]] = []
        for i, ln in enumerate(lines):
            cm = CLASS_RE.search(ln)
            if cm and not METHOD_DECL_RE.match(ln):
                class_name = cm.group(1)
                pending, display = [], None
                continue
            if TEST_ANN_RE.search(ln) or DISPLAY_RE.search(ln):
                pending.append(ln)
                dm = DISPLAY_RE.search(ln)
                if dm:
                    display = dm.group(1)
                if not METHOD_DECL_RE.search(ln):
                    continue
            m = METHOD_DECL_RE.match(ln)
            if not m:
                if ln.strip() and not ln.strip().startswith("@") and pending:
                    if not ln.strip().startswith("//"):
                        pending, display = [], None
                continue
            name = m.group(1) or m.group(2) or m.group(3)
            if name in NOT_METHOD:
                continue
            if any(TEST_ANN_RE.search(a) for a in pending) or TEST_ANN_RE.search(ln):
                out.append((class_name, name, i + 1, display))
            pending, display = [], None
        return out

    def test_names(self, roots: list[Path]) -> set[str] | None:
        names: set[str] = set()
        for p in self.test_files(roots):
            for cls, name, _, display in self._scan_test_methods(p):
                names.add(f"{cls}#{name}")
                if display:
                    names.add(f"{cls}#{display}")
        return names

    def single_test_argv(self, name: str) -> list[str] | None:
        if not name:
            return None
        if "#" in name:
            cls, method = name.split("#", 1)
        else:
            cls, method = name, ""
        if not cls:
            return None
        base = self.root
        tool = self._build_tool(base)
        precise = bool(method and IDENT_RE.match(method))
        if tool == "maven":
            sel = f"{cls}#{method}" if precise else cls
            return [*self._mvn_cmd(base), "test", f"-Dtest={sel}", "-DfailIfNoTests=false"]
        sel = f"*.{cls}.{method}" if precise else f"*.{cls}"
        return [*self._gradle_cmd(base), "cleanTest", "test", "--tests", sel]

    def related_tests(self, rel_paths: list[str]) -> list[str] | None:
        by_stem: dict[str, list[Path]] = {}
        for p in self.test_files([self.root]):
            by_stem.setdefault(p.stem, []).append(p)
        names: list[str] = []
        for rel in rel_paths:
            p = self.root / rel
            if p.suffix not in self.source_exts:
                continue
            if _is_test_stem(p.stem):
                names.extend(self._class_names(p if p.is_file() else None, p.stem))
                continue
            for cand in companion_stems(p.stem):
                for tp in by_stem.get(cand, []):
                    names.extend(self._class_names(tp, tp.stem))
        return sorted(set(names))

    def _class_names(self, path: Path | None, fallback: str) -> list[str]:
        if path is None or not path.is_file():
            return [fallback] if fallback else []
        classes = [cls for cls, *_ in self._scan_test_methods(path)]
        return classes or [path.stem]

    def related_test_argv(self, names: list[str]) -> list[str] | None:
        classes: list[str] = []
        seen: set[str] = set()
        for n in names:
            cls = (n.split("#", 1)[0] if "#" in n else n).strip()
            if cls and cls not in seen:
                seen.add(cls)
                classes.append(cls)
        if not classes:
            return None
        base = self.root
        if self._build_tool(base) == "maven":
            return [*self._mvn_cmd(base), "test",
                    f"-Dtest={','.join(classes)}", "-DfailIfNoTests=false"]
        argv = [*self._gradle_cmd(base), "cleanTest", "test"]
        for cls in classes:
            argv.extend(["--tests", f"*.{cls}"])
        return argv

    def scoped_test_argv(self, argv: list[str], units: list[str],
                         *, cwd: Path | None = None) -> list[str] | None:
        """Maven：插入 -pl <模块> -amd。Gradle 没有 -amd，返回 None。"""
        if not argv or not units:
            return None
        name = Path(argv[0]).name.lower()
        if "gradle" in name:
            return None
        if "mvn" not in name:
            return None
        reactor = cwd or self.root
        modules: list[str] = []
        for u in units:
            m = self._maven_module(u, reactor)
            if m and m not in modules:
                modules.append(m)
        if not modules:
            return None
        if "-pl" in argv or "--projects" in argv:
            return None
        out = list(argv)
        i = 1
        while i < len(out):
            a = out[i]
            if a.startswith("-") and not a.startswith("-D") and ":" not in a:
                i += 1
                if a in {"-T", "-f", "-s", "-P", "--threads", "--file", "--settings"}:
                    i += 1
                continue
            break
        out[i:i] = ["-pl", ",".join(modules), "-amd"]
        return out

    def _maven_module(self, unit: str, reactor: Path) -> str | None:
        p = (self.root / unit).resolve()
        if p.is_file():
            p = p.parent
        reactor = reactor.resolve()
        root = self.root.resolve()
        while True:
            if (p / "pom.xml").is_file():
                try:
                    rel = p.relative_to(reactor).as_posix()
                except ValueError:
                    try:
                        rel = p.relative_to(root).as_posix()
                    except ValueError:
                        return None
                return "." if rel in (".", "") else rel
            if p.parent == p or p == root.parent:
                break
            p = p.parent
        return None

    def slowest_tests(self, cwd: Path, *, since: float | None = None,
                      n: int = 5) -> list[tuple] | None:
        files = self._report_files(cwd, since)
        if not files:
            return []
        rows: list[tuple[str, float, str]] = []
        for p in files:
            try:
                root = ET.parse(p).getroot()
            except ET.ParseError:
                continue
            tag = root.tag.rsplit("}", 1)[-1]
            if tag not in ("testsuite", "testsuites"):
                continue
            suites = [root] if tag == "testsuite" else list(root.findall("testsuite"))
            if tag == "testsuites":
                suites += [el for el in root.iter()
                           if el is not root and el.tag.rsplit("}", 1)[-1] == "testsuite"]
            seen: set[int] = set()
            mod = self._module_of_report(p)
            for suite in suites:
                if id(suite) in seen:
                    continue
                seen.add(id(suite))
                for case in suite.findall("testcase"):
                    classname = case.get("classname") or suite.get("name") or ""
                    raw = case.get("name") or ""
                    key = f"{_simple_class(classname)}#{_clean_xml_name(raw)}"
                    try:
                        sec = float(case.get("time") or 0)
                    except ValueError:
                        sec = 0.0
                    rows.append((key, sec, mod))
        rows.sort(key=lambda r: -r[1])
        return rows[:max(int(n), 1)]

    def _module_of_report(self, path: Path) -> str:
        try:
            rel = path.relative_to(self.root).as_posix()
        except ValueError:
            return path.parent.as_posix()
        for marker in ("/target/", "/build/"):
            i = rel.find(marker)
            if i >= 0:
                return rel[:i] or "."
        return "."

    def failure_diagnosis(self, output: str) -> str | None:
        from .base import SPRING_PORT_RE, port_conflict_diagnosis
        m = SPRING_PORT_RE.search(output or "")
        if m:
            return (f"端口 {m.group(1)} 被占。如果冲突发生在第二个及以后的"
                    f"测试上下文启动时，那是 Spring 测试上下文缓存——"
                    f"前一个上下文没关、socket 还在它手里，串行也会撞。"
                    f"改成 @SpringBootTest(webEnvironment = RANDOM_PORT)。")
        return port_conflict_diagnosis(output)

    def iter_test_funcs(self, path: Path) -> list[FuncBody]:
        wanted = {name for _, name, _, _ in self._scan_test_methods(path)}
        if not wanted:
            return []
        return [f for f in self.iter_funcs(path) if f.name in wanted]

    def is_assertionless(self, body: list[str]) -> bool:
        return not any(w in ln for ln in body for w in ASSERT_WORDS)

    def skip_sites(self, text: str) -> int:
        return len(SKIP_RE.findall(text))

    # ------------------------------------------------------------ 代码

    def iter_funcs(self, path: Path) -> list[FuncBody]:
        lines = _blank_block_comments(read(path)).splitlines()
        ext = path.suffix
        if ext == ".kt":
            start = KT_FUNC_START
        elif ext == ".groovy":
            start = GROOVY_FUNC_START
        else:
            start = JAVA_FUNC_START
        return brace_funcs(lines, start, _func_name)

    def zero_cover(self, profile: Path, cwd: Path) -> tuple[int, int] | None:
        files = [p for p in self._jacoco_files(cwd, self.root) if p.suffix == ".xml"]
        if not files:
            return None
        zero = total = 0
        for p in files:
            try:
                root = ET.parse(p).getroot()
            except ET.ParseError:
                continue
            for method in root.iter():
                if method.tag.rsplit("}", 1)[-1] != "method":
                    continue
                name = method.get("name") or ""
                if name in ("<init>", "<clinit>"):
                    continue
                for c in method:
                    if c.tag.rsplit("}", 1)[-1] != "counter":
                        continue
                    if c.get("type") != "METHOD":
                        continue
                    total += 1
                    if int(c.get("covered") or 0) == 0:
                        zero += 1
        return (zero, total) if total else None

    def _jacoco_files(self, *roots: Path) -> list[Path]:
        """不限定 target/site/jacoco：团队常把报告写到 jacoco-reports/ 或只开了 CSV。"""
        seen: set[Path] = set()
        out: list[Path] = []
        for root in roots:
            if root is None or not root.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames
                               if d not in JACOCO_SKIP_DIRS and not d.startswith(".")]
                for fn in filenames:
                    if fn not in JACOCO_NAMES and not (
                            fn == "index.html" and "jacoco" in dirpath.lower()):
                        continue
                    p = Path(dirpath) / fn
                    if p not in seen and p.is_file():
                        seen.add(p)
                        out.append(p)
        return sorted(out)

    def coverage_from_reports(self, *roots: Path) -> float | None:
        """多模块项目要把各模块的行数加起来。

        以前是「返回第一份能解析出数字的报告」，那在 aics-api + aics-gateway 这种
        多模块仓库里报的是字母序第一个模块的覆盖率，既不是整体水位，
        也会随模块改名而跳变。
        """
        files = self._jacoco_files(*roots)
        xmls = [p for p in files if p.suffix == ".xml"]
        # 有聚合报告就只认它：再把各模块报告加进来就是重复计数
        agg = [p for p in xmls if "aggregate" in p.as_posix().lower()]
        for group in (agg or xmls, [p for p in files if p.suffix == ".csv"]):
            covered = missed = 0
            for p in group:
                got = (self._xml_line_counts(p) if p.suffix == ".xml"
                       else self._csv_line_counts(p))
                if got:
                    covered += got[0]
                    missed += got[1]
            if covered + missed:
                return round(100.0 * covered / (covered + missed), 1)
        # HTML 只有百分比，加不起来，只能取第一份
        for p in [p for p in files if p.name == "index.html"]:
            pct = self._html_line_pct(p)
            if pct is not None:
                return pct
        return None

    def _xml_line_pct(self, path: Path) -> float | None:
        got = self._xml_line_counts(path)
        if not got or not sum(got):
            return None
        return round(100.0 * got[0] / sum(got), 1)

    def _xml_line_counts(self, path: Path) -> tuple[int, int] | None:
        """返回（覆盖行数，未覆盖行数）。解析不了或没有 LINE 计数返回 None。"""
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return None
        covered = missed = 0
        # 先读 report 自己的 LINE counter；没有再退回各 package 的
        counters = [c for c in list(root)
                    if c.tag.rsplit("}", 1)[-1] == "counter" and c.get("type") == "LINE"]
        if not counters:
            counters = [c for pkg in root
                        if pkg.tag.rsplit("}", 1)[-1] == "package"
                        for c in list(pkg)
                        if c.tag.rsplit("}", 1)[-1] == "counter" and c.get("type") == "LINE"]
        for c in counters:
            covered += int(c.get("covered") or 0)
            missed += int(c.get("missed") or 0)
        return (covered, missed) if covered + missed else None

    def _csv_line_pct(self, path: Path) -> float | None:
        got = self._csv_line_counts(path)
        if not got or not sum(got):
            return None
        return round(100.0 * got[0] / sum(got), 1)

    def _csv_line_counts(self, path: Path) -> tuple[int, int] | None:
        try:
            with path.open(encoding="utf-8", errors="replace", newline="") as f:
                rows = list(csv.DictReader(f))
        except OSError:
            return None
        covered = missed = 0
        for row in rows:
            try:
                missed += int(row.get("LINE_MISSED") or 0)
                covered += int(row.get("LINE_COVERED") or 0)
            except ValueError:
                continue
        return (covered, missed) if covered + missed else None

    def coverage_diagnosis(self, *roots: Path, output: str = "") -> str:
        """没读到覆盖率时，说清是哪一环断了，而不是让人对着「没解析到数字」猜。

        最常断的一环是 prepare-agent 没绑进构建生命周期：`mvn test jacoco:report`
        会打一行 Skipping 然后 BUILD SUCCESS，一份报告都不写——命令成功了，
        覆盖率却无从谈起，这是 Java 团队最容易撞上的假绿。
        """
        if JACOCO_NO_DATA in output:
            return ("JaCoCo 没采集到数据（输出里有「Skipping JaCoCo execution due to "
                    "missing execution data file」）。pom 没把 prepare-agent 绑进构建"
                    "生命周期，`mvn test` 时探针就没挂上，报告自然是空的。"
                    "把步骤 argv 改成 mvn -B -ntp jacoco:prepare-agent test jacoco:report"
                    "（CLI 显式跑 prepare-agent，不依赖 pom 的绑定）")
        reports = self._jacoco_files(*roots)
        if reports:
            return (f"找到 {len(reports)} 份 jacoco 报告（{self._show(reports[0])} 等）"
                    f"但一行都没统计到：报告里的 LINE 计数是空的，"
                    f"确认测试真的执行到了被测类，而不是整批被跳过")
        execs = self._exec_files(*roots)
        if execs:
            return (f"有 {self._show(execs[0])} 但没有 jacoco.xml / jacoco.csv："
                    f"探针采到了数据，是 jacoco:report 没跑或没配 XML 输出。"
                    f"在测试步骤末尾加上 jacoco:report")
        return ("一份 jacoco 报告都没找到（按 jacoco.xml / jacocoTestReport.xml / "
                "jacoco.csv 从步骤目录和仓库根递归扫的）。确认 pom 里启用了 "
                "jacoco-maven-plugin，且步骤是 "
                "mvn -B -ntp jacoco:prepare-agent test jacoco:report")

    def _exec_files(self, *roots: Path) -> list[Path]:
        out: list[Path] = []
        for root in roots:
            if root is None or not root.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames
                               if d not in JACOCO_SKIP_DIRS and not d.startswith(".")]
                out += [Path(dirpath) / fn for fn in filenames if fn.endswith(".exec")]
        return sorted(set(out))

    def _show(self, p: Path) -> str:
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            return p.name

    def _html_line_pct(self, path: Path) -> float | None:
        try:
            text = read(path)
        except OSError:
            return None
        m = re.search(r"<tfoot>.*?Total.*?(\d+(?:\.\d+)?)%\s*</td>\s*</tr>",
                      text, re.S | re.I)
        return float(m.group(1)) if m else None

    def routes(self, target: Path) -> set[str] | None:
        files: list[Path] = []
        if target.is_dir():
            for ext in self.source_exts:
                files.extend(sorted(target.rglob(f"*{ext}")))
        elif target.is_file():
            files = [target]
        else:
            return None
        out: set[str] = set()
        for p in files:
            out |= self._routes_in(read(p))
        return out

    def _routes_in(self, text: str) -> set[str]:
        """类级 @RequestMapping / @Path 前缀 + 方法级路径。"""
        text = _blank_block_comments(text)
        out: set[str] = set()
        class_prefix = ""
        pending_paths: list[str] = []
        for ln in text.splitlines():
            cm = CLASS_RE.search(ln)
            if cm and not METHOD_DECL_RE.match(ln):
                for pref in pending_paths:
                    out.add(_join_path("", pref))
                class_prefix = pending_paths[-1] if pending_paths else ""
                pending_paths = []
                continue
            for m in PATH_ANN_RE.finditer(ln):
                pending_paths.append(m.group(2))
            for m in JAXRS_PATH_RE.finditer(ln):
                pending_paths.append(m.group(1))
            if METHOD_DECL_RE.match(ln) and pending_paths:
                for path in pending_paths:
                    out.add(_join_path(class_prefix, path))
                pending_paths = []
        for pref in pending_paths:
            out.add(_join_path(class_prefix, pref))
        return out

    def views(self, target: Path) -> set[str] | None:
        if not target.is_dir():
            return None
        out: set[str] = set()
        templates = target / "src" / "main" / "resources" / "templates"
        if not templates.is_dir():
            templates = target / "main" / "resources" / "templates"
        if templates.is_dir():
            out |= {p.name for p in templates.rglob("*.html") if p.is_file()}
        for pat in ("*.jsp", "*.ftl"):
            out |= {p.name for p in target.rglob(pat) if p.is_file()}
        return out
