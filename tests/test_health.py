"""维度、评分与渲染，外加探测与安装的端到端。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from actuallydone import detect, install
from actuallydone.dimensions import DIMENSIONS
from actuallydone.health import Ctx
from actuallydone.dimensions import code as dim_code
from actuallydone.dimensions import materials as dim_materials
from actuallydone.dimensions import probes as dim_probes
from actuallydone.model import DimResult
from actuallydone.report import render
from tests.helpers import ProjectCase

BIN = Path(__file__).resolve().parent.parent / "bin" / "adone"


class TestScoring(ProjectCase):
    def test_未评估的维度不参与总分也不算通过(self):
        r = DimResult("x", "X").skip("没配")
        self.assertFalse(r.ran)
        self.assertEqual(r.why_skipped, "没配")

    def test_错误扣十五警告扣五(self):
        r = DimResult("x", "X")
        r.add("错误", "a", "m")
        r.add("警告", "b", "m")
        r.add("提示", "c", "m")   # 提示不扣分
        self.assertEqual(r.score, 80)

    def test_只跑一个维度时报告要写明覆盖了几分之几(self):
        results = [DimResult("skills", "技能沉淀")] + [
            DimResult(d.key, d.title).skip("本轮未跑") for d in DIMENSIONS[1:]]
        out = self.root / "r.html"
        render(results, out, 100, ["skills"], DIMENSIONS, "fixture")
        html = out.read_text(encoding="utf-8")
        self.assertIn(f"1/{len(DIMENSIONS)} 个维度", html)
        self.assertIn("未评估", html)
        self.assertNotIn("<script", html)     # 报告要能离线双击打开


class TestCodeDimension(ProjectCase):
    def test_权威对权威不一致判错误(self):
        self.write("a.sql", "CREATE TABLE orders (id int);\nCREATE TABLE users (id int);")
        self.write("b.sql", "CREATE TABLE orders (id int);")
        cfg = self.config(consistency={"pair": [{"a": "a.sql", "b": "b.sql",
                                                 "extract": "sql_tables"}]})
        res = dim_code.run(Ctx(cfg=cfg))
        self.assertTrue(any(f.severity == "错误" and "users" in f.message
                            for f in res.findings))

    def test_一处删表另一处仍在建要单独点出来(self):
        self.write("a.sql", "CREATE TABLE orders (id int);\nDROP TABLE IF EXISTS legacy;")
        self.write("b.sql", "CREATE TABLE orders (id int);\nCREATE TABLE legacy (id int);")
        cfg = self.config(consistency={"pair": [{"a": "a.sql", "b": "b.sql",
                                                 "extract": "sql_tables"}]})
        res = dim_code.run(Ctx(cfg=cfg))
        self.assertTrue(any("显式删除" in f.message for f in res.findings))

    def test_什么都没配时标未评估而不是满分(self):
        cfg = self.config(code={"big_file_globs": [], "mark_globs": [],
                                "dup_roots": []}, consistency={"pair": []})
        res = dim_code.run(Ctx(cfg=cfg))
        self.assertFalse(res.ran)

    def test_未引用符号靠定义与使用两个正则(self):
        self.write("api/a.go", "package api\n"
                   "func (h *Handler) listUsers(w, r) {}\n"
                   "func (h *Handler) deadOne(w, r) {}\n"
                   "func reg() { r.Get(\"/u\", h.listUsers) }\n")
        cfg = self.config(code={"unused": [{
            "name": "未注册 handler", "glob": "api/*.go",
            "define": r"^func \(h \*Handler\) ([a-z]\w*)\(",
            "use": r"h\.([a-z]\w*)\b"}]})
        res = dim_code.run(Ctx(cfg=cfg))
        self.assertTrue(any("deadOne" in f.message for f in res.findings))


class TestMaterialsDimension(ProjectCase):
    def test_选摘只查幻影不要求全覆盖(self):
        self.write("code.sql", "CREATE TABLE a (id int);\nCREATE TABLE b (id int);")
        self.write("doc.sql", "CREATE TABLE a (id int);")     # 只摘一张，合法
        cfg = self.config(docs={"excerpt": [{"file": "doc.sql", "extract": "sql_tables",
                                             "against": "code.sql"}]})
        res = dim_materials.run(Ctx(cfg=cfg))
        self.assertEqual(res.errors, 0)

    def test_文档里写了代码里没有的算幻影(self):
        self.write("code.sql", "CREATE TABLE a (id int);")
        self.write("doc.sql", "CREATE TABLE a (id int);\nCREATE TABLE ghost (id int);")
        cfg = self.config(docs={"excerpt": [{"file": "doc.sql", "extract": "sql_tables",
                                             "against": "code.sql"}]})
        res = dim_materials.run(Ctx(cfg=cfg))
        self.assertTrue(any("ghost" in f.message for f in res.findings))

    def test_文档写死的数字与现实对账(self):
        self.write("code.sql", "CREATE TABLE a (id int);\nCREATE TABLE b (id int);")
        self.write("doc.md", "本文覆盖 5 张表。")
        cfg = self.config(docs={"claim": [{"file": "doc.md", "pattern": r"覆盖 (\d+) 张表",
                                           "actual": "count:sql_tables:code.sql"}]})
        res = dim_materials.run(Ctx(cfg=cfg))
        self.assertTrue(any("实际是 2" in f.message for f in res.findings))


class TestProbesDimension(ProjectCase):
    def test_服务连不上是警告不变量被破坏才是错误(self):
        self.write("p.py", "print('Connection refused')")
        cfg = self.config(probe=[{"name": "探针", "argv": [sys.executable, "p.py"]}])
        res = dim_probes.run(Ctx(cfg=cfg, with_probes=True))
        self.assertEqual(res.errors, 0)
        self.assertEqual(res.warnings, 1)

    def test_断言失败是错误(self):
        self.write("p.py", "print('库存不变量 → FAIL: 超卖 3 件')")
        cfg = self.config(probe=[{"name": "探针", "argv": [sys.executable, "p.py"],
                                  "fail_pattern": "→ FAIL"}])
        res = dim_probes.run(Ctx(cfg=cfg, with_probes=True))
        self.assertEqual(res.errors, 1)

    def test_默认不跑(self):
        cfg = self.config(probe=[{"name": "探针", "argv": ["true"]}])
        self.assertFalse(dim_probes.run(Ctx(cfg=cfg)).ran)


class TestDetectAndInstall(ProjectCase):
    def test_探测go项目(self):
        self.make_go_project()
        got = detect.detect(self.root)
        self.assertEqual(got.ecosystems, {"go": "."})
        self.assertIn("go test", [s["name"] for s in got.steps])
        self.assertEqual(got.tests_adapter, "go")

    def test_探测node项目(self):
        self.make_node_project()
        got = detect.detect(self.root)
        self.assertIn("node", got.ecosystems)
        self.assertIn("前端构建", [s["name"] for s in got.steps])

    def test_生成的配置能被解析且不猜阈值(self):
        self.make_go_project()
        text = detect.render_config(detect.detect(self.root))
        self.assertIn("请确认", text)
        (self.root / "adone.toml").write_text(text, encoding="utf-8")
        from actuallydone.config import Config
        cfg = Config.load(self.root)
        self.assertIsNone(cfg.get("coverage.threshold"))   # 阈值留空，等人来定

    def test_渲染技能不留占位符(self):
        self.make_go_project()
        cfg = self.config()
        v = install.variables(cfg)
        for tpl in (install.TEMPLATES / "skills").rglob("*.md"):
            rendered = install.render(tpl.read_text(encoding="utf-8"), v)
            self.assertNotIn("{{", rendered, f"{tpl.name} 还有没替换的占位符")

    def test_没设覆盖率下限时不编一个数字出来(self):
        self.make_go_project()
        v = install.variables(self.config())
        self.assertEqual(v["COVERAGE_CLAIM"], "")
        self.assertIn("没设覆盖率下限", v["COVERAGE_DESC"])


class TestCliSmoke(ProjectCase):
    """走真实进程：包能不能被 python -m 与免安装入口两种方式跑起来。"""

    def run_adone(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(BIN), *args],
                              cwd=self.root, capture_output=True, text=True)

    def test_零配置项目从init到health(self):
        self.make_go_project()
        self.assertEqual(self.run_adone("init", "--yes").returncode, 0)
        conf = self.root / "adone.toml"
        conf.write_text(conf.read_text(encoding="utf-8").replace(
            'skills_dir = ".cursor/skills"', 'skills_dir = "agent-skills"'),
            encoding="utf-8")
        proc = self.run_adone("install")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.run_adone("health", "--json", "--only", "skills")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)          # --json 时 stdout 必须只有 JSON
        self.assertEqual(data["ran"], ["skills"])
        self.assertEqual(data["dimensions"][0]["score"], 100)
        # 没跑的维度必须是「未评估」，不能悄悄算通过
        others = [d for d in data["dimensions"] if d["key"] != "skills"]
        self.assertTrue(all(not d["ran"] and d["score"] is None for d in others))

    def test_全量体检真的重跑了门禁(self):
        """--all 说重跑就得真重跑：曾经它 spawn 一个没装的模块，失败后照旧拿旧回执算分。"""
        self.make_go_project()
        self.assertEqual(self.run_adone("init", "--yes").returncode, 0)
        self.assertEqual(self.run_adone("gate", "run").returncode, 0)

        proc = self.run_adone("health", "--all", "--json", "--only", "tests")
        data = json.loads(proc.stdout)          # 门禁进度不许污染 stdout
        self.assertIn("跑门禁：", proc.stderr, "门禁根本没被执行")
        self.assertNotIn("No module named", proc.stderr)
        receipt = json.loads((self.root / ".adone/latest.json").read_text())
        self.assertEqual(data["dimensions"][1]["metrics"][0]["value"], receipt["id"])
