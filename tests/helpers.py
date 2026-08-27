"""造微型项目的脚手架。

用真实文件而不是 mock：这些检查的对象就是文件系统，mock 掉之后测的是 mock 自己。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from actuallydone.config import Config  # noqa: E402

GO_MAIN = """package internal

func Add(a, b int) int { return a + b }

func Sub(a, b int) int { return a - b }
"""

GO_TEST = """package internal

import "testing"

func TestAdd(t *testing.T) {
\tif Add(1, 2) != 3 {
\t\tt.Fatal("加法不对")
\t}
}

func TestNoAssert(t *testing.T) {
\t_ = Add(1, 2)
}

func TestSkipped(t *testing.T) {
\tt.Skip("暂时跳过")
}
"""

GO_TEST_OUTPUT = """=== RUN   TestAdd
--- PASS: TestAdd (0.00s)
=== RUN   TestSub
=== RUN   TestSub/负数
    --- PASS: TestSub/负数 (0.00s)
--- PASS: TestSub (0.01s)
=== RUN   TestSkipped
--- SKIP: TestSkipped (0.00s)
=== RUN   TestBroken
--- FAIL: TestBroken (0.00s)
FAIL
coverage: 85.9% of statements
"""

NODE_TEST_OUTPUT = """ \u2713 src/order.test.ts > \u62d2\u7edd\u8d1f\u6570\u4ef7\u683c 3ms
 \u2713 src/order.test.ts > \u63a5\u53d7\u96f6\u4ef7 1ms
 \u00d7 src/order.test.ts > \u5e93\u5b58\u4e0d\u8db3\u65f6\u4e0b\u5355 5ms

 Tests  1 failed | 2 passed (3)
"""

MAVEN_TEST_OUTPUT = """
[INFO] Running com.example.CalcTest
[INFO] Tests run: 2, Failures: 0, Errors: 0, Skipped: 1 -- in com.example.CalcTest
[INFO] Running com.example.OtherTest
[INFO] Tests run: 1, Failures: 1, Errors: 0, Skipped: 0 -- in com.example.OtherTest
[INFO]
[INFO] Results:
[INFO]
[INFO] Tests run: 3, Failures: 1, Errors: 0, Skipped: 1
"""

GRADLE_TEST_OUTPUT = """
3 tests completed, 1 failed, 1 skipped

BUILD SUCCESSFUL in 1s
"""

JAVA_CALC_TEST = '''package com.example;

import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class CalcTest {
    @Test
    void testAdd() {
        assertEquals(3, Calc.add(1, 2));
    }

    @Test
    @DisplayName("加法")
    void testPlus() {
        mockMvc.perform(get("/x")).andExpect(status().isOk());
    }

    @Disabled
    @Test
    void testSkip() {
        assertEquals(1, 1);
    }

    @Test
    void testNoAssert() {
        Calc.add(1, 2);
    }
}
'''

JAVA_SUREFIRE_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="com.example.CalcTest" tests="3" failures="0" errors="0" skipped="1" time="0.1">
  <testcase name="testAdd()" classname="com.example.CalcTest" time="0.01"/>
  <testcase name="加法" classname="com.example.CalcTest" time="0.01"/>
  <testcase name="testSkip()" classname="com.example.CalcTest" time="0.0">
    <skipped/>
  </testcase>
</testsuite>
'''

JAVA_JACOCO_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<report name="fixture">
  <package name="com/example">
    <class name="com/example/Calc" sourcefilename="Calc.java">
      <method name="add" desc="(II)I" line="3">
        <counter type="METHOD" missed="0" covered="1"/>
      </method>
      <method name="unused" desc="()V" line="7">
        <counter type="METHOD" missed="1" covered="0"/>
      </method>
      <method name="&lt;init&gt;" desc="()V" line="1">
        <counter type="METHOD" missed="0" covered="1"/>
      </method>
    </class>
  </package>
  <counter type="INSTRUCTION" missed="10" covered="90"/>
  <counter type="LINE" missed="15" covered="85"/>
  <counter type="METHOD" missed="1" covered="1"/>
</report>
'''


class ProjectCase(unittest.TestCase):
    """每个用例一个临时项目，测完即删。"""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="adone-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel: str, text: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def make_go_project(self) -> None:
        self.write("go.mod", "module fixture\n\ngo 1.22\n")
        self.write("internal/calc.go", GO_MAIN)
        self.write("internal/calc_test.go", GO_TEST)

    def make_node_project(self) -> None:
        self.write("package.json",
                   '{"name":"fixture","scripts":{"build":"tsc","test":"vitest"}}')
        self.write("src/order.ts", "export function order() { return 1 }\n")
        self.write("src/order.test.ts",
                   'it("拒绝负数价格", () => { expect(1).toBe(1) })\n')
        self.write("src/OrderView.vue", "<template><div/></template>\n")

    def make_maven_project(self) -> None:
        self.write("pom.xml", """<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>fixture</artifactId>
  <version>1.0</version>
  <build><plugins>
    <plugin><artifactId>jacoco-maven-plugin</artifactId></plugin>
    <plugin><groupId>com.diffplug.spotless</groupId><artifactId>spotless-maven-plugin</artifactId></plugin>
  </plugins></build>
</project>
""")
        self.write("src/main/java/com/example/Calc.java",
                   "package com.example;\npublic class Calc {\n"
                   "    public static int add(int a, int b) { return a + b; }\n"
                   "    public static int unused() { return 0; }\n}\n")
        self.write("src/test/java/com/example/CalcTest.java", JAVA_CALC_TEST)
        self.write("target/surefire-reports/TEST-com.example.CalcTest.xml",
                   JAVA_SUREFIRE_XML)
        self.write("target/site/jacoco/jacoco.xml", JAVA_JACOCO_XML)

    def make_gradle_project(self) -> None:
        self.write("build.gradle", """plugins { id 'java'; id 'jacoco' }
repositories { mavenCentral() }
dependencies { testImplementation 'org.junit.jupiter:junit-jupiter:5.10.0' }
test { useJUnitPlatform() }
""")
        self.write("src/main/java/com/example/Calc.java",
                   "package com.example;\npublic class Calc {\n"
                   "    public static int add(int a, int b) { return a + b; }\n}\n")
        self.write("src/test/java/com/example/CalcTest.java", JAVA_CALC_TEST)
        self.write("build/test-results/test/TEST-com.example.CalcTest.xml",
                   JAVA_SUREFIRE_XML)

    def config(self, **over) -> Config:
        data = {
            "project": {"name": "fixture", "ecosystems": ["go"]},
            "gate": {"watch_roots": ["internal"], "watch_exts": [".go"],
                     "min_tree_files": 1, "step": []},
            "tests": {"adapter": "go", "roots": ["internal"]},
        }
        for k, v in over.items():
            data.setdefault(k, {})
            data[k] = {**data.get(k, {}), **v} if isinstance(v, dict) else v
        return Config.from_dict(self.root, data)
