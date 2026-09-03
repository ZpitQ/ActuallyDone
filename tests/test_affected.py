"""范围化全量：单元哈希、继承校验、Maven -pl/-amd、契约名单并集。"""

from __future__ import annotations

import json
import sys
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr

from argparse import Namespace

from actuallydone import gate, policy
from actuallydone.adapters.java_adapter import JavaAdapter
from actuallydone.contracts import check_contracts
from actuallydone.detect import cmd_doctor
from actuallydone.model import TestResult
from tests.helpers import ProjectCase


class TestUnitHash(ProjectCase):
    def test_总哈希算法不变(self):
        self.make_go_project()
        cfg = self.config()
        h1, n1 = gate.tree_hash(cfg)
        h2, n2 = gate.tree_hash(cfg)
        self.assertEqual(h1, h2)
        self.assertEqual(n1, n2)

    def test_改一个单元只有那份哈希变(self):
        self.write("a/src/A.go", "package a\n")
        self.write("b/src/B.go", "package b\n")
        cfg = self.config(gate={"watch_roots": ["a/src", "b/src"],
                                "watch_exts": [".go"], "min_tree_files": 1})
        before = gate.unit_hashes(cfg)
        self.assertEqual(set(before), {"a/src", "b/src"})
        self.write("a/src/A.go", "package a\nfunc X() {}\n")
        after = gate.unit_hashes(cfg)
        self.assertNotEqual(before["a/src"], after["a/src"])
        self.assertEqual(before["b/src"], after["b/src"])

    def test_改超时不进判据快照(self):
        step = {"name": "测试", "cwd": ".", "kind": "test", "adapter": "go",
                "argv": ["go", "test", "./..."]}
        self.make_go_project()
        cfg = self.config(gate={"watch_roots": ["internal"], "watch_exts": [".go"],
                                "min_tree_files": 1, "step": [step]})
        snap = policy.snapshot(cfg)
        self.assertNotIn("timeout_seconds", json.dumps(snap))
        other = self.config(gate={
            "watch_roots": ["internal"], "watch_exts": [".go"],
            "min_tree_files": 1,
            "step": [{**step, "timeout_seconds": 30, "stall_seconds": 10}]})
        loose, _ = policy.diff(snap, policy.snapshot(other))
        self.assertEqual(loose, [])


class TestScopedArgv(ProjectCase):
    def test_maven插入pl和amd(self):
        self.write("pom.xml", "<project/>")
        self.write("mod-a/pom.xml", "<project/>")
        self.write("mod-b/pom.xml", "<project/>")
        ad = JavaAdapter(self.root)
        got = ad.scoped_test_argv(
            ["./mvnw", "-B", "-ntp", "test"],
            ["mod-a/src", "mod-b/src"])
        self.assertIsNotNone(got)
        self.assertIn("-pl", got)
        self.assertIn("mod-a,mod-b", got)
        self.assertIn("-amd", got)
        self.assertEqual(got[:3], ["./mvnw", "-B", "-ntp"])
        self.assertEqual(got[-1], "test")

    def test_gradle返回None(self):
        self.write("build.gradle", "plugins { id 'java' }\n")
        ad = JavaAdapter(self.root)
        self.assertIsNone(ad.scoped_test_argv(
            ["./gradlew", "test"], ["src"]))

    def test_不是maven命令返回None(self):
        self.write("pom.xml", "<project/>")
        ad = JavaAdapter(self.root)
        self.assertIsNone(ad.scoped_test_argv(
            [sys.executable, "-c", "pass"], ["src"]))


class TestCarryAndCheck(ProjectCase):
    def _two_mods(self):
        self.write("mod-a/src/A.go", "package a\n")
        self.write("mod-b/src/B.go", "package b\n")
        cfg = self.config(
            project={"name": "fixture", "ecosystems": ["go"]},
            gate={"watch_roots": ["mod-a/src", "mod-b/src"],
                  "watch_exts": [".go"], "min_tree_files": 1,
                  "step": [{"name": "noop", "cwd": ".",
                            "argv": [sys.executable, "-c", "pass"]}]},
            tests={"adapter": "go", "roots": ["mod-a/src"]})
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        cfg.receipts_dir.mkdir(parents=True, exist_ok=True)
        return cfg

    def _write_full(self, cfg, **over) -> dict:
        units = gate.unit_hashes(cfg)
        h, n = gate.tree_hash(cfg)
        receipt = {
            "tool": "actuallydone",
            "id": "20260903-100000",
            "created_at": "2026-09-03T10:00:00",
            "complete": True,
            "ok": True,
            "scope": "full",
            "units": units,
            "tree": {"hash": h, "file_count": n},
            "tests": {"pass": 2, "fail": 0, "skip": 0, "skip_top": 0,
                      "passed_names": ["TestA", "TestB"],
                      "failed_names": [], "skipped_names": [],
                      "ran_names": ["TestA", "TestB"], "parsed": True},
            "coverage": {"percent": 80.0, "threshold": 70},
            "steps": [{"name": "测试", "ok": True}],
            "seq": 1,
            "prev": None,
        }
        receipt.update(over)
        receipt["self_hash"] = gate.self_hash(receipt)
        path = cfg.receipts_dir / f"receipt-{receipt['id']}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        cfg.latest_receipt.write_text(json.dumps(receipt, ensure_ascii=False,
                                                 indent=2), encoding="utf-8")
        gate.write_chain_head(cfg, receipt)
        return receipt

    def test_没有全量回执就拒绝affected(self):
        cfg = self._two_mods()
        src, err = gate.inheritable_full(cfg)
        self.assertIsNone(src)
        self.assertIn("没有可继承", err)

    def test_老回执没有单元哈希不能当源头(self):
        cfg = self._two_mods()
        rec = self._write_full(cfg)
        rec.pop("units")
        rec["self_hash"] = gate.self_hash(rec)
        (cfg.receipts_dir / f"receipt-{rec['id']}.json").write_text(
            json.dumps(rec), encoding="utf-8")
        cfg.latest_receipt.write_text(json.dumps(rec), encoding="utf-8")
        src, err = gate.inheritable_full(cfg)
        self.assertIsNone(src)
        self.assertIn("没有单元哈希", err)

    def test_继承名单并集给契约用(self):
        src = {"id": "X", "tests": {"passed_names": ["TestA", "TestB"]}}
        ran = TestResult(passed=1, passed_names=["TestA", "TestC"], parsed=True)
        got = gate._carry_tests(ran, src)
        self.assertEqual(set(got.ran_names), {"TestA", "TestC"})
        self.assertEqual(set(got.passed_names), {"TestA", "TestB", "TestC"})

    def test_契约认继承的通过名单(self):
        cfg = self._two_mods()
        self.write("mod-a/src/a_test.go",
                   "package a\n\nimport \"testing\"\n\nfunc TestB(t *testing.T) {}\n")
        rec = self._write_full(cfg)
        rec["scope"] = "affected"
        rec["carried"] = {"from_receipt": rec["id"], "units": ["mod-b/src"]}
        rec["tests"]["ran_names"] = ["TestA"]
        rec["tests"]["passed_names"] = ["TestA", "TestB"]
        cfg.acceptance_dir.mkdir(parents=True, exist_ok=True)
        (cfg.acceptance_dir / "x.toml").write_text(
            'task = "t"\n[[item]]\n"要求" = "x"\ntest = "TestB"\n',
            encoding="utf-8")
        problems = check_contracts(cfg, rec)
        self.assertEqual(problems, [])

    def test_源头不在链上check拒绝(self):
        cfg = self._two_mods()
        rec = self._write_full(cfg)
        rec["scope"] = "affected"
        rec["carried"] = {"from_receipt": "不存在", "units": ["mod-b/src"]}
        rec["self_hash"] = gate.self_hash(rec)
        cfg.latest_receipt.write_text(json.dumps(rec), encoding="utf-8")
        bad, _ = gate.scope_problems(cfg, rec)
        self.assertTrue(any("不在链上" in p for p in bad))

    def test_继承单元其实改过就拒绝(self):
        cfg = self._two_mods()
        rec = self._write_full(cfg)
        self.write("mod-b/src/B.go", "package b\nfunc Changed() {}\n")
        rec["scope"] = "affected"
        rec["carried"] = {"from_receipt": rec["id"], "units": ["mod-b/src"]}
        rec["units"] = {**rec["units"], "mod-b/src": rec["units"]["mod-b/src"]}
        bad, _ = gate.scope_problems(cfg, rec)
        self.assertTrue(any("mod-b/src" in p and "改过" in p for p in bad))

    def test_affected全绿时explain写出真跑和继承(self):
        cfg = self._two_mods()
        full = self._write_full(cfg)
        rec = dict(full)
        rec["id"] = "20260903-110000"
        rec["scope"] = "affected"
        rec["carried"] = {"from_receipt": full["id"], "units": ["mod-b/src"]}
        rec["tests"] = {**full["tests"], "ran_names": ["TestA"],
                        "passed_names": ["TestA", "TestB"]}
        rec["self_hash"] = gate.self_hash(rec)
        (cfg.receipts_dir / f"receipt-{rec['id']}.json").write_text(
            json.dumps(rec), encoding="utf-8")
        cfg.latest_receipt.write_text(json.dumps(rec), encoding="utf-8")
        gate.write_chain_head(cfg, rec)
        _, details = gate.scope_problems(cfg, rec)
        self.assertTrue(any("本轮真跑" in d and "继承" in d for d in details))
        line = gate.evidence_line({"evidence": gate.evidence_of(cfg, rec),
                                   "carried": rec["carried"]})
        self.assertIn("部分重跑", line)
        self.assertIn(full["id"], line)

    def test_没有模块变化时affected直接放行(self):
        cfg = self._two_mods()
        self._write_full(cfg)
        buf = StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = gate.run_gate(cfg, affected=True)
        self.assertEqual(rc, 0)
        self.assertIn("没有单元", buf.getvalue())

    def test_gradle步骤affected拒绝不写回执(self):
        self.write("mod-a/src/A.java", "class A {}")
        self.write("mod-b/src/B.java", "class B {}")
        self.write("build.gradle", "plugins { id 'java' }\n")
        cfg = self.config(
            project={"ecosystems": ["java"]},
            gate={"watch_roots": ["mod-a/src", "mod-b/src"],
                  "watch_exts": [".java"], "min_tree_files": 1,
                  "step": [{"name": "gradle test", "cwd": ".", "kind": "test",
                            "adapter": "java",
                            "argv": ["./gradlew", "test"]}]},
            tests={"adapter": "java", "roots": ["mod-a/src"]})
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        cfg.receipts_dir.mkdir(parents=True, exist_ok=True)
        units = gate.unit_hashes(cfg)
        h, n = gate.tree_hash(cfg)
        rec = {
            "id": "F1", "ok": True, "complete": True, "scope": "full",
            "created_at": "2026-09-03T10:00:00",
            "units": units, "tree": {"hash": h, "file_count": n},
            "tests": {"passed_names": []}, "steps": [], "seq": 1,
        }
        rec["self_hash"] = gate.self_hash(rec)
        (cfg.receipts_dir / "receipt-F1.json").write_text(
            json.dumps(rec), encoding="utf-8")
        cfg.latest_receipt.write_text(json.dumps(rec), encoding="utf-8")
        gate.write_chain_head(cfg, rec)
        self.write("mod-a/src/A.java", "class A { int x; }")
        buf = StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = gate.run_gate(cfg, affected=True)
        self.assertEqual(rc, 2)
        self.assertIn("不要用 --affected", buf.getvalue())
        self.assertFalse((cfg.receipts_dir / "receipt-F1.json").read_text() == "")
        # 没写出新回执覆盖 latest 的 scope
        latest = json.loads(cfg.latest_receipt.read_text(encoding="utf-8"))
        self.assertEqual(latest.get("scope"), "full")

    def test_affected真跑并继承通过名单(self):
        self.write("pom.xml", "<project/>")
        self.write("mod-a/pom.xml", "<project/>")
        self.write("mod-b/pom.xml", "<project/>")
        self.write("mod-a/src/A.java", "class A {}")
        self.write("mod-b/src/B.java", "class B {}")
        mvn = self.write("mvn", """#!/usr/bin/env python3
import sys
print("[INFO] Tests run: 1, Failures: 0, Errors: 0, Skipped: 0")
open("ran-argv.txt", "w").write(" ".join(sys.argv))
""")
        mvn.chmod(0o755)
        cfg = self.config(
            project={"ecosystems": ["java"]},
            gate={"watch_roots": ["mod-a/src", "mod-b/src"],
                  "watch_exts": [".java"], "min_tree_files": 1,
                  "step": [{"name": "mvn test", "cwd": ".", "kind": "test",
                            "adapter": "java",
                            "argv": ["./mvn", "-B", "test"]}]},
            tests={"adapter": "java", "roots": ["mod-a/src"]})
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        cfg.receipts_dir.mkdir(parents=True, exist_ok=True)
        units = gate.unit_hashes(cfg)
        h, n = gate.tree_hash(cfg)
        full = {
            "id": "F-full", "ok": True, "complete": True, "scope": "full",
            "created_at": "2026-09-03T10:00:00",
            "units": units, "tree": {"hash": h, "file_count": n},
            "tests": {"passed_names": ["OldTest"], "pass": 1, "fail": 0,
                      "skip": 0, "skip_top": 0, "parsed": True},
            "coverage": {"percent": 80.0, "threshold": None},
            "steps": [{"name": "mvn test", "ok": True}],
            "seq": 1,
        }
        full["self_hash"] = gate.self_hash(full)
        (cfg.receipts_dir / "receipt-F-full.json").write_text(
            json.dumps(full), encoding="utf-8")
        cfg.latest_receipt.write_text(json.dumps(full), encoding="utf-8")
        gate.write_chain_head(cfg, full)
        self.write("mod-a/src/A.java", "class A { int x; }")
        buf = StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = gate.run_gate(cfg, affected=True)
        self.assertEqual(rc, 0, buf.getvalue())
        argv = (self.root / "ran-argv.txt").read_text()
        self.assertIn("-pl", argv)
        self.assertIn("mod-a", argv)
        self.assertIn("-amd", argv)
        latest = json.loads(cfg.latest_receipt.read_text(encoding="utf-8"))
        self.assertEqual(latest["scope"], "affected")
        self.assertEqual(latest["carried"]["from_receipt"], "F-full")
        self.assertIn("mod-b/src", latest["carried"]["units"])
        self.assertIn("OldTest", latest["tests"]["passed_names"])
        self.assertNotIn("OldTest", latest["tests"]["ran_names"])

    def test_gate_slow读surefire耗时(self):
        self.write("mod-a/target/surefire-reports/TEST-A.xml",
                   '''<?xml version="1.0"?>
<testsuite name="A"><testcase name="slow" classname="com.A" time="2.5"/>
</testsuite>''')
        cfg = self.config(
            project={"ecosystems": ["java"]},
            tests={"adapter": "java"},
            gate={"watch_roots": ["mod-a"], "watch_exts": [".java"],
                  "min_tree_files": 1,
                  "step": [{"name": "mvn test", "cwd": ".", "kind": "test",
                            "adapter": "java", "argv": ["mvn", "test"]}]})
        buf = StringIO()
        with redirect_stdout(buf):
            rc = gate.cmd_gate_slow(cfg, n=5)
        self.assertEqual(rc, 0)
        self.assertIn("A#slow", buf.getvalue())
        self.assertIn("mod-a", buf.getvalue())


class TestDoctorScope(ProjectCase):
    def test_doctor报告单元和缩范围能力(self):
        self.write("pom.xml", "<project/>")
        self.write("mod-a/pom.xml", "<project/>")
        self.write("mod-a/src/A.java", "class A {}")
        self.write("mod-b/src/B.java", "class B {}")
        cfg = self.config(
            project={"ecosystems": ["java"]},
            gate={"watch_roots": ["mod-a/src", "mod-b/src"],
                  "watch_exts": [".java"], "min_tree_files": 1,
                  "step": [{"name": "mvn test", "cwd": ".", "kind": "test",
                            "adapter": "java", "argv": ["mvn", "-B", "test"]}]},
            tests={"adapter": "java", "roots": ["mod-a/src"]})
        buf = StringIO()
        with redirect_stdout(buf):
            cmd_doctor(cfg, Namespace())
        out = buf.getvalue()
        self.assertIn("单元：2 个 watch_roots", out)
        self.assertIn("mod-a/src", out)
        self.assertIn("--affected", out)

    def test_commit_scope是affected但没有源头算问题(self):
        self.write("pom.xml", "<project/>")
        self.write("src/A.java", "class A {}")
        cfg = self.config(
            project={"ecosystems": ["java"]},
            gate={"watch_roots": ["src"], "watch_exts": [".java"],
                  "min_tree_files": 1, "commit_scope": "affected",
                  "step": [{"name": "mvn test", "cwd": ".", "kind": "test",
                            "adapter": "java", "argv": ["mvn", "-B", "test"]}]},
            tests={"adapter": "java", "roots": ["src"]})
        buf = StringIO()
        with redirect_stdout(buf):
            rc = cmd_doctor(cfg, Namespace())
        self.assertNotEqual(rc, 0)
        self.assertIn("可继承", buf.getvalue())
