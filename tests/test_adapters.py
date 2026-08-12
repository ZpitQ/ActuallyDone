"""适配器：输出解析、用例名提取、函数切分、覆盖率。"""

from __future__ import annotations

from actuallydone.adapters import CAP_TESTS, get
from actuallydone.adapters.go_adapter import GoAdapter, func_name
from actuallydone.adapters.node_adapter import NodeAdapter
from actuallydone.adapters.python_adapter import PythonAdapter
from tests.helpers import GO_TEST_OUTPUT, NODE_TEST_OUTPUT, ProjectCase


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


class TestRegistry(ProjectCase):
    def test_不认识的生态退回无能力基类而不是抛错(self):
        ad = get("cobol", self.root)
        self.assertEqual(ad.caps, set())
        self.assertIsNone(ad.test_names([self.root]))   # None 才能让上层标「未评估」

    def test_能力集合(self):
        self.assertIn(CAP_TESTS, get("go", self.root).caps)
