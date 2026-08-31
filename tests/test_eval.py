"""可选 eval 门禁：适配器、契约 scenario、integrity 加料，以及 vibe 路径零变化。"""

from __future__ import annotations

from actuallydone import contracts, detect, integrity
from actuallydone.adapters import REGISTRY, detect_all, get
from actuallydone.adapters.eval_adapter import EvalAdapter
from tests.helpers import ProjectCase


EVAL_TOML = '''id = "recall#退货时效"
kind = "recall"
query = "退货多久能到账"
must = ["退货时效"]
'''

EMPTY_TOML = '''id = "recall#空壳"
kind = "recall"
query = "x"
'''

EVAL_STEP = {
    "name": "skill eval",
    "cwd": ".",
    "kind": "test",
    "adapter": "eval",
    "argv": ["python3", "scripts/eval_cs_agent.py"],
}


class TestEvalAdapter(ProjectCase):
    def test_没有markers不会被探测选中(self):
        self.assertEqual(EvalAdapter.markers, ())
        self.write("adone/eval/a.toml", EVAL_TOML)
        self.assertEqual(detect_all(self.root), {})
        self.assertNotIn("eval", detect.detect(self.root).ecosystems)

    def test_只有eval目录时detect_all仍不带eval生态(self):
        self.write("adone/eval/a.toml", EVAL_TOML)
        self.write("README.md", "hi\n")
        self.assertNotIn("eval", detect_all(self.root))
        got = detect.detect(self.root)
        self.assertEqual(got.tests_adapter, "")
        self.assertEqual(got.steps, [])
        self.assertNotIn(".md", got.watch_exts)

    def test_解析PASS_FAIL_SKIP含井号id(self):
        text = "PASS recall#退货时效\nFAIL merge#冲突取严\nSKIP hitl#查物流禁止打断\n"
        res = EvalAdapter(self.root).parse_test_output(text)
        self.assertTrue(res.parsed)
        self.assertEqual(res.passed, 1)
        self.assertEqual(res.failed, 1)
        self.assertEqual(res.skipped, 1)
        self.assertEqual(res.skip_top, 1)
        self.assertEqual(res.passed_names, ["recall#退货时效"])
        self.assertEqual(res.failed_names, ["merge#冲突取严"])
        self.assertEqual(res.skipped_names, ["hitl#查物流禁止打断"])

    def test_没有结果行则解析失败(self):
        res = EvalAdapter(self.root).parse_test_output("ok 5 passed\n")
        self.assertFalse(res.parsed)

    def test_列出场景名与空壳(self):
        self.write("adone/eval/a.toml", EVAL_TOML)
        self.write("adone/eval/empty.toml", EMPTY_TOML)
        ad = EvalAdapter(self.root)
        roots = [self.root / "adone/eval"]
        self.assertEqual(ad.test_names(roots), {"recall#退货时效", "recall#空壳"})
        files = {p.name for p in ad.test_files(roots)}
        self.assertEqual(files, {"a.toml", "empty.toml"})
        by_name = {f.name: f for p in ad.test_files(roots) for f in ad.iter_test_funcs(p)}
        self.assertFalse(ad.is_assertionless(by_name["recall#退货时效"].body))
        self.assertTrue(ad.is_assertionless(by_name["recall#空壳"].body))

    def test_单跑追加only或没有步骤则None(self):
        ad = EvalAdapter(self.root)
        self.assertIsNone(ad.single_test_argv("recall#退货时效"))
        self.write("adone.toml", '''version = 1
[[gate.step]]
name = "skill eval"
argv = ["python3", "scripts/eval_cs_agent.py"]
kind = "test"
adapter = "eval"
''')
        self.assertEqual(ad.single_test_argv("recall#退货时效"),
                         ["python3", "scripts/eval_cs_agent.py", "--only", "recall#退货时效"])

    def test_注册表有eval但无覆盖率能力(self):
        self.assertIn("eval", REGISTRY)
        ad = get("eval", self.root)
        self.assertEqual(ad.name, "eval")
        self.assertIsNone(ad.zero_cover(self.root / "x", self.root))


class TestEvalContracts(ProjectCase):
    def receipt(self, names) -> dict:
        return {"id": "x", "created_at": "now", "ok": True,
                "tests": {"passed_names": names}}

    def _eval_cfg(self, body: str, **over):
        self.write("adone/eval/a.toml", EVAL_TOML)
        self.make_go_project()
        cfg = self.config(
            gate={"step": [EVAL_STEP]},
            tests={"adapter": "go", "roots": ["internal"]},
            **over)
        cfg.acceptance_dir.mkdir(parents=True)
        (cfg.acceptance_dir / "t.toml").write_text(body, encoding="utf-8")
        return cfg

    def test_仅test走原逻辑(self):
        cfg = self._eval_cfg('task = "t"\n[[item]]\n"要求" = "x"\ntest = "TestAdd"\n')
        self.assertEqual(contracts.check_contracts(cfg, self.receipt(["TestAdd"])), [])
        problems = contracts.check_contracts(cfg, self.receipt(["TestSkipped"]))
        self.assertTrue(any("通过名单" in p for p in problems))

    def test_仅scenario走eval名单(self):
        cfg = self._eval_cfg(
            'task = "t"\n[[item]]\n"要求" = "x"\nscenario = "recall#退货时效"\n')
        self.assertEqual(
            contracts.check_contracts(cfg, self.receipt(["recall#退货时效"])), [])
        problems = contracts.check_contracts(cfg, self.receipt(["TestAdd"]))
        self.assertTrue(any("通过名单" in p for p in problems))

    def test_同时有两者以test为准(self):
        cfg = self._eval_cfg(
            'task = "t"\n[[item]]\n"要求" = "x"\n'
            'test = "TestAdd"\nscenario = "根本不存在的场景"\n')
        self.assertEqual(contracts.check_contracts(cfg, self.receipt(["TestAdd"])), [])

    def test_没有eval步骤则scenario无法核验(self):
        self.write("adone/eval/a.toml", EVAL_TOML)
        self.make_go_project()
        cfg = self.config()
        cfg.acceptance_dir.mkdir(parents=True)
        (cfg.acceptance_dir / "t.toml").write_text(
            'task = "t"\n[[item]]\n"要求" = "x"\nscenario = "recall#退货时效"\n',
            encoding="utf-8")
        problems = contracts.check_contracts(cfg, self.receipt(["recall#退货时效"]))
        self.assertTrue(any("未配置 eval 步骤" in p for p in problems))

    def test_没绑定才报没绑定(self):
        cfg = self._eval_cfg('task = "t"\n[[item]]\n"要求" = "x"\n')
        problems = contracts.check_contracts(cfg, self.receipt(["TestAdd"]))
        self.assertTrue(any("没绑定" in p for p in problems))


class TestEvalIntegrity(ProjectCase):
    def test_无eval步即使有场景文件也不扫(self):
        self.make_go_project()
        self.write("adone/eval/a.toml", EVAL_TOML)
        cfg = self.config()
        names = set(integrity.scan(cfg)["test_functions"])
        self.assertEqual(names, {"TestAdd", "TestNoAssert", "TestSkipped"})
        self.assertNotIn("recall#退货时效", names)

    def test_有eval步则删场景文件算用例消失(self):
        self.make_go_project()
        self.write("adone/eval/a.toml", EVAL_TOML)
        cfg = self.config(gate={"step": [EVAL_STEP]})
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        integrity.write_baseline(cfg, integrity.scan(cfg), "建立初始基线")
        self.assertIn("recall#退货时效", integrity.scan(cfg)["test_functions"])
        (self.root / "adone/eval/a.toml").unlink()
        problems = integrity.compare(cfg, integrity.scan(cfg),
                                     integrity.load_baseline(cfg))
        self.assertTrue(any("用例消失" in p and "recall#退货时效" in p for p in problems))


class TestVibeUnchanged(ProjectCase):
    def test_init探测go与现在一致(self):
        self.make_go_project()
        self.write("adone/eval/a.toml", EVAL_TOML)
        self.write(".cursor/skills/x/SKILL.md", "# skill\n")
        got = detect.detect(self.root)
        self.assertEqual(got.ecosystems, {"go": "."})
        self.assertEqual(got.tests_adapter, "go")
        self.assertEqual(got.tests_roots, ["."])
        self.assertEqual([s["adapter"] for s in got.steps if s.get("adapter")], ["go"])
        self.assertEqual(got.watch_exts, [".go"])
        self.assertNotIn("eval", [s.get("adapter") for s in got.steps])
        argv = next(s["argv"] for s in got.steps if s["name"] == "go test")
        self.assertEqual(argv[:2], ["go", "test"])

    def test_init探测java步骤argv不变(self):
        self.make_maven_project()
        got = detect.detect(self.root)
        self.assertEqual(got.tests_adapter, "java")
        test = next(s for s in got.steps if s["name"] == "mvn test")
        self.assertEqual(test["adapter"], "java")
        self.assertIn("jacoco:prepare-agent", test["argv"])
        self.assertNotIn("eval", got.ecosystems)

    def test_无eval步契约与integrity仍只认测试函数(self):
        self.make_go_project()
        self.write("adone/eval/a.toml", EVAL_TOML)
        cfg = self.config()
        cfg.acceptance_dir.mkdir(parents=True)
        (cfg.acceptance_dir / "t.toml").write_text(
            'task = "t"\n[[item]]\n"要求" = "x"\ntest = "TestAdd"\n',
            encoding="utf-8")
        self.assertEqual(
            contracts.check_contracts(cfg, {
                "tests": {"passed_names": ["TestAdd"]}}), [])
        names = set(integrity.scan(cfg)["test_functions"])
        self.assertEqual(names, {"TestAdd", "TestNoAssert", "TestSkipped"})
