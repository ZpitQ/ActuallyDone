"""适配器：输出解析、用例名提取、函数切分、覆盖率。"""

from __future__ import annotations

from actuallydone.adapters import CAP_TESTS, get
from actuallydone.adapters.go_adapter import GoAdapter, func_name
from actuallydone.adapters.java_adapter import JavaAdapter
from actuallydone.adapters.node_adapter import NodeAdapter
from actuallydone.adapters.python_adapter import PythonAdapter
from tests.helpers import (GO_TEST_OUTPUT, GRADLE_TEST_OUTPUT, MAVEN_TEST_OUTPUT,
                           NODE_TEST_OUTPUT, ProjectCase)


class TestGoAdapter(ProjectCase):
    def test_解析测试输出要分开顶层与子用例的跳过数(self):
        res = GoAdapter(self.root).parse_test_output(GO_TEST_OUTPUT)
        self.assertEqual(res.passed, 3)      # TestAdd、TestSub、TestSub/负数
        self.assertEqual(res.failed, 1)
        self.assertEqual(res.skipped, 1)
        self.assertEqual(res.skip_top, 1)
        self.assertEqual(res.coverage, 85.9)
        self.assertIn("TestSub/负数", res.passed_names)

    def test_没开verbose时判为解析不出而不是零通过(self):
        res = GoAdapter(self.root).parse_test_output("ok  \tfixture/internal\t0.3s\n")
        self.assertFalse(res.parsed)

    def test_列出用例名(self):
        self.make_go_project()
        names = GoAdapter(self.root).test_names([self.root / "internal"])
        self.assertEqual(names, {"TestAdd", "TestNoAssert", "TestSkipped"})

    def test_无断言用例能被认出来(self):
        self.make_go_project()
        ad = GoAdapter(self.root)
        funcs = {f.name: f for f in ad.iter_test_funcs(self.root / "internal/calc_test.go")}
        self.assertTrue(ad.is_assertionless(funcs["TestNoAssert"].body))
        self.assertFalse(ad.is_assertionless(funcs["TestAdd"].body))

    def test_方法名要跳过接收者(self):
        self.assertEqual(func_name("func (w *Worker) Start(ctx context.Context) {"), "Start")
        self.assertEqual(func_name("func Add(a, b int) int {"), "Add")

    def test_提取路由字面量(self):
        self.write("api/routes.go", '''package api
func reg(r chi.Router) {
	r.Get("/listing-tasks", h.list)
	r.Post("/listing-tasks/{id}/publish", h.publish)
}
''')
        got = GoAdapter(self.root).routes(self.root / "api")
        self.assertEqual(got, {"/listing-tasks", "/listing-tasks/{id}/publish"})


class TestNodeAdapter(ProjectCase):
    def test_汇总行优先于逐条行(self):
        res = NodeAdapter(self.root).parse_test_output(NODE_TEST_OUTPUT)
        self.assertEqual(res.passed, 2)
        self.assertEqual(res.failed, 1)

    def test_列出用例标题与页面(self):
        self.make_node_project()
        ad = NodeAdapter(self.root)
        self.assertEqual(ad.test_names([self.root / "src"]), {"拒绝负数价格"})
        self.assertEqual(ad.views(self.root / "src"), {"OrderView.vue"})

    def test_读lcov算零覆盖函数(self):
        p = self.write("cov/lcov.info", "\n".join([
            "SF:src/a.ts", "FN:1,foo", "FN:9,bar", "FNDA:3,foo", "FNDA:0,bar",
            "end_of_record",
        ]))
        self.assertEqual(NodeAdapter(self.root).zero_cover(p, self.root), (1, 2))


class TestPythonAdapter(ProjectCase):
    def test_解析unittest输出(self):
        out = ("test_add (m.C) ... ok\n"
               "test_sub (m.C) ... FAIL\n"
               "test_x (m.C) ... skipped 'why'\n")
        res = PythonAdapter(self.root).parse_test_output(out)
        self.assertEqual((res.passed, res.failed, res.skipped), (1, 1, 1))

    def test_按缩进切函数体(self):
        p = self.write("m.py", "def f():\n    a = 1\n    return a\n\ndef g():\n    pass\n")
        funcs = {f.name: f.body for f in PythonAdapter(self.root).iter_funcs(p)}
        self.assertEqual(funcs["f"], ["a = 1", "return a"])


class TestJavaAdapter(ProjectCase):
    def test_聚合行不带in才是全局合计(self):
        res = JavaAdapter(self.root).parse_test_output(MAVEN_TEST_OUTPUT)
        self.assertEqual((res.passed, res.failed, res.skipped), (1, 1, 1))

    def test_解析Gradle汇总行(self):
        res = JavaAdapter(self.root).parse_test_output(GRADLE_TEST_OUTPUT)
        self.assertEqual((res.passed, res.failed, res.skipped), (1, 1, 1))

    def test_逐类行不能被当成全局合计(self):
        # 只有带 -- in 的行，没有 Results 段：解析不出合计
        only_class = ("[INFO] Tests run: 2, Failures: 0, Errors: 0, Skipped: 0 "
                      "-- in com.example.CalcTest\n")
        res = JavaAdapter(self.root).parse_test_output(only_class)
        self.assertFalse(res.parsed)

    def test_Gradle静默成功时计数取自XML(self):
        self.make_maven_project()
        ad = JavaAdapter(self.root)
        res = ad.parse_test_run("BUILD SUCCESSFUL\n", cwd=self.root, since=0)
        self.assertTrue(res.parsed)
        self.assertEqual(res.passed, 2)
        self.assertEqual(res.skipped, 1)
        self.assertIn("CalcTest#testAdd", res.passed_names)
        self.assertIn("CalcTest#加法", res.passed_names)

    def test_XML与控制台对不上时有计数无名字(self):
        self.make_maven_project()
        ad = JavaAdapter(self.root)
        # 控制台说 10 通过，XML 只有 2：对不上
        res = ad.parse_test_run(
            "Tests run: 10, Failures: 0, Errors: 0, Skipped: 0\n",
            cwd=self.root, since=0)
        self.assertEqual(res.passed, 10)
        self.assertEqual(res.passed_names, [])

    def test_旧XML不参与解析(self):
        self.make_maven_project()
        report = self.root / "target/surefire-reports/TEST-com.example.CalcTest.xml"
        import os
        os.utime(report, (1_000_000, 1_000_000))   # 1970 年代
        res = JavaAdapter(self.root).parse_test_run(
            "BUILD SUCCESSFUL\n", cwd=self.root, since=1_700_000_000)
        self.assertFalse(res.parsed)

    def test_源码与XML的名字形式一致且含DisplayName(self):
        self.make_maven_project()
        ad = JavaAdapter(self.root)
        names = ad.test_names([self.root / "src"])
        self.assertIn("CalcTest#testAdd", names)
        self.assertIn("CalcTest#testPlus", names)
        self.assertIn("CalcTest#加法", names)
        xml = ad.parse_test_run("BUILD SUCCESSFUL\n", cwd=self.root, since=0)
        for n in xml.passed_names:
            self.assertIn(n, names)

    def test_andExpect不算无断言_Disabled计入跳过(self):
        self.make_maven_project()
        ad = JavaAdapter(self.root)
        p = self.root / "src/test/java/com/example/CalcTest.java"
        funcs = {f.name: f for f in ad.iter_test_funcs(p)}
        self.assertFalse(ad.is_assertionless(funcs["testPlus"].body))
        self.assertTrue(ad.is_assertionless(funcs["testNoAssert"].body))
        self.assertGreaterEqual(ad.skip_sites(p.read_text(encoding="utf-8")), 1)

    def test_jacoco零覆盖与行覆盖率(self):
        self.make_maven_project()
        ad = JavaAdapter(self.root)
        self.assertEqual(ad.zero_cover(self.root / "cover.out", self.root), (1, 2))
        res = ad.parse_test_run(MAVEN_TEST_OUTPUT, cwd=self.root, since=0)
        self.assertEqual(res.coverage, 85.0)

    def test_Spring类级前缀拼接(self):
        self.write("src/main/java/com/example/Api.java", '''
@RequestMapping("/api")
class Api {
    @GetMapping("/orders")
    void list() {}
    @PostMapping(value = "/orders")
    void create() {}
}
''')
        got = JavaAdapter(self.root).routes(self.root / "src")
        self.assertIn("/api/orders", got)

    def test_单跑命令Maven精确与显示名降级(self):
        self.make_maven_project()
        ad = JavaAdapter(self.root)
        self.assertEqual(ad.single_test_argv("CalcTest#testAdd"),
                         ["mvn", "-B", "-ntp", "test",
                          "-Dtest=CalcTest#testAdd", "-DfailIfNoTests=false"])
        argv = ad.single_test_argv("CalcTest#加法")
        self.assertEqual(argv[-2], "-Dtest=CalcTest")

    def test_单跑命令Gradle(self):
        self.make_gradle_project()
        ad = JavaAdapter(self.root)
        self.assertIn("--tests", ad.single_test_argv("CalcTest#testAdd"))
        self.assertIn("*.CalcTest.testAdd", ad.single_test_argv("CalcTest#testAdd"))
        self.assertIn("*.CalcTest", ad.single_test_argv("CalcTest#加法"))

    def test_探测建议步骤含mvn_test且不用fmt(self):
        self.make_maven_project()
        steps = JavaAdapter(self.root).suggest_steps(".")
        names = [s["name"] for s in steps]
        self.assertIn("mvn test", names)
        self.assertIn("spotless:check", names)
        test = next(s for s in steps if s["name"] == "mvn test")
        self.assertEqual(test["kind"], "test")
        self.assertEqual(test["adapter"], "java")
        self.assertIn("jacoco:report", test["argv"])
        self.assertFalse(any(s.get("kind") == "fmt" for s in steps))

    def test_监视src而不是模块根(self):
        self.make_maven_project()
        roots, exts = JavaAdapter(self.root).suggest_watch(".")
        self.assertEqual(roots, ["src"])
        self.assertIn(".java", exts)
        self.assertIn(".kt", exts)


class TestRegistry(ProjectCase):
    def test_不认识的生态退回无能力基类而不是抛错(self):
        ad = get("cobol", self.root)
        self.assertEqual(ad.caps, set())
        self.assertIsNone(ad.test_names([self.root]))   # None 才能让上层标「未评估」

    def test_能力集合(self):
        self.assertIn(CAP_TESTS, get("go", self.root).caps)
        self.assertIn(CAP_TESTS, get("java", self.root).caps)
