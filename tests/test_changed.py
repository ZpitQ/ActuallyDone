"""gate run --changed：相关用例、写 partial.json、不覆盖 latest.json。"""

from __future__ import annotations

import json
import subprocess
from io import StringIO
from contextlib import redirect_stdout

from actuallydone.adapters.base import Adapter
from actuallydone.changed import changed_paths, run_changed
from actuallydone.install import PRE_COMMIT_MARK, cmd_install
from tests.helpers import ProjectCase
from tests.test_hooks import _args


class TestRelatedRun(ProjectCase):
    def _py_project(self) -> None:
        self.write("lib.py", "def add(a, b):\n    return a + b\n")
        self.write("test_lib.py",
                   "import unittest\nimport lib\n"
                   "class T(unittest.TestCase):\n"
                   "    def test_add(self):\n"
                   "        self.assertEqual(lib.add(1, 2), 3)\n")
        self.write("adone.toml",
                   "version = 1\n"
                   "[project]\nname = 'f'\necosystems = ['python']\n"
                   "[gate]\nwatch_roots = ['.']\nwatch_exts = ['.py']\n"
                   "min_tree_files = 1\n"
                   "[[gate.step]]\nname = 'python 测试'\nkind = 'test'\n"
                   "adapter = 'python'\n"
                   "argv = ['python3', '-m', 'unittest', 'discover', '-v']\n"
                   "[tests]\nadapter = 'python'\n")

    def test_成功只写partial不写latest并清dirty(self):
        import shutil
        if not shutil.which("python3"):
            self.skipTest("需要 PATH 上的 python3")
        self._py_project()
        dest = self.root / ".adone" / "dirty"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("lib.py\n", encoding="utf-8")
        from actuallydone.config import Config
        cfg = Config.load(self.root)
        with redirect_stdout(StringIO()):
            got = run_changed(cfg)
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["tests"], ["test_add"])
        self.assertTrue(cfg.partial.is_file())
        self.assertFalse(cfg.latest_receipt.exists())
        self.assertFalse(cfg.dirty.exists())
        data = json.loads(cfg.partial.read_text(encoding="utf-8"))
        self.assertEqual(data["kind"], "changed")
        self.assertFalse(data["latest"])

    def test_找不到相关用例不退回全量(self):
        self._py_project()
        self.write("orphan.py", "def nope():\n    return 0\n")
        from actuallydone.config import Config
        cfg = Config.load(self.root)
        with redirect_stdout(StringIO()):
            got = run_changed(cfg, paths=["orphan.py"])
        self.assertFalse(got["ok"])
        self.assertIn("找不到", got["problems"][0])
        self.assertIn("不要跑全量", got["problems"][0])
        self.assertFalse(cfg.latest_receipt.exists())

    def test_适配器不会找时标未评估(self):
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "[gate]\nwatch_roots = ['.']\nwatch_exts = ['.txt']\n"
                   "min_tree_files = 1\n"
                   "[[gate.step]]\nname = 'x'\nkind = 'test'\nadapter = 'generic'\n"
                   "argv = ['true']\n")
        self.write("a.txt", "x\n")
        from actuallydone.config import Config
        cfg = Config.load(self.root)
        with redirect_stdout(StringIO()):
            got = run_changed(cfg, paths=["a.txt"])
        self.assertFalse(got["ok"])
        self.assertTrue(got.get("unassessed"))
        self.assertIsNone(Adapter(self.root).related_tests(["a.txt"]))

    def test_dirty优先于git_diff(self):
        self._py_project()
        dest = self.root / ".adone" / "dirty"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("lib.py\n", encoding="utf-8")
        from actuallydone.config import Config
        cfg = Config.load(self.root)
        self.assertEqual(changed_paths(cfg), ["lib.py"])


class TestPreCommitInstall(ProjectCase):
    def test_with_hooks写入本机pre_commit(self):
        self.make_go_project()
        subprocess.run(["git", "init"], cwd=self.root, check=True,
                       capture_output=True)
        with redirect_stdout(StringIO()):
            self.assertEqual(cmd_install(self.config(), _args(hooks_only=True)), 0)
        hook = self.root / ".git" / "hooks" / "pre-commit"
        self.assertTrue(hook.is_file())
        text = hook.read_text(encoding="utf-8")
        self.assertIn(PRE_COMMIT_MARK, text)
        self.assertIn("gate run", text)
        self.assertIn("gate check", text)
        self.assertNotIn("\r", text)

    def test_不是git仓库就跳过(self):
        self.make_go_project()
        out = StringIO()
        with redirect_stdout(out):
            cmd_install(self.config(), _args(hooks_only=True))
        self.assertIn("不是 git 仓库", out.getvalue())
        self.assertFalse((self.root / ".git" / "hooks" / "pre-commit").exists())
