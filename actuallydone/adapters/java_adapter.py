"""Java / Kotlin / Groovy 适配器（Maven 与 Gradle，JUnit 4/5 与 TestNG）。"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..model import FuncBody, TestResult
from .base import (CAP_COVERAGE, CAP_FUNCS, CAP_ROUTES, CAP_SINGLE_TEST,
                   CAP_TESTS, CAP_VIEWS, Adapter, brace_funcs, read)

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
JACOCO_GLOBS = (
    "**/target/site/jacoco/jacoco.xml",
    "**/target/site/jacoco-aggregate/jacoco.xml",
    "**/build/reports/jacoco/test/jacocoTestReport.xml",
    "**/build/reports/jacoco/jacocoTestReport.xml",
    "**/build/reports/jacoco/jacoco-aggregate/jacoco.xml",
)
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

    def _mvn_cmd(self, base: Path) -> list[str]:
        wrapper = base / "mvnw"
        if wrapper.is_file() and os.access(wrapper, os.X_OK):
            return ["./mvnw", "-B", "-ntp"]
        return ["mvn", "-B", "-ntp"]

    def _gradle_cmd(self, base: Path) -> list[str]:
        wrapper = base / "gradlew"
        if wrapper.is_file() and os.access(wrapper, os.X_OK):
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
            argv = [*self._mvn_cmd(base), "test"]
            if "jacoco" in low:
                argv.append("jacoco:report")
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
        coverage = self._jacoco_line_pct(cwd) if cwd is not None else None

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
        files = self._jacoco_files(cwd)
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

    def _jacoco_files(self, cwd: Path) -> list[Path]:
        out: list[Path] = []
        for pat in JACOCO_GLOBS:
            out.extend(p for p in cwd.glob(pat) if p.is_file())
        return sorted(set(out))

    def _jacoco_line_pct(self, cwd: Path) -> float | None:
        covered = missed = 0
        for p in self._jacoco_files(cwd):
            try:
                root = ET.parse(p).getroot()
            except ET.ParseError:
                continue
            # 只要 report 自己的 LINE counter，不要把 package/class 的再加一遍
            for c in list(root):
                if c.tag.rsplit("}", 1)[-1] != "counter":
                    continue
                if c.get("type") != "LINE":
                    continue
                covered += int(c.get("covered") or 0)
                missed += int(c.get("missed") or 0)
        denom = covered + missed
        return round(100.0 * covered / denom, 1) if denom else None

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
