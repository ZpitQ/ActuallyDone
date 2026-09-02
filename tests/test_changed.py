"""gate run --changed：相关用例、写 partial.json、不覆盖 latest.json。"""

from __future__ import annotations

import json
import subprocess
from io import StringIO
from contextlib import redirect_stdout

from actuallydone.adapters.base import Adapter
from actuallydone.changed import (changed_paths, file_hashes, git_changed,
                                   git_diff_names, run_changed,
                                   same_as_last_ok_partial)
from actuallydone.config import Config
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
        self.assertIn("lib.py", data.get("file_hashes") or {})

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

    def test_父仓库里的子项目git路径相对项目根(self):
        """git status 给出 demo/app/src/lib.py 时，必须收成 src/lib.py 才能对上 watch_roots。"""
        app = self.root / "demo" / "app"
        (app / "src").mkdir(parents=True)
        (app / "src" / "lib.py").write_text("x = 1\n", encoding="utf-8")
        (app / "adone.toml").write_text(
            "version = 1\n[project]\nname = 'f'\n"
            "[gate]\nwatch_roots = ['src']\nwatch_exts = ['.py']\n",
            encoding="utf-8")
        (self.root / "sibling.py").write_text("y = 1\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=self.root, check=True,
                       capture_output=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "add", "-A"], cwd=self.root, check=True,
                       capture_output=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-m", "i"], cwd=self.root, check=True,
                        capture_output=True)
        (app / "src" / "lib.py").write_text("x = 2\n", encoding="utf-8")
        (self.root / "outside.py").write_text("z = 1\n", encoding="utf-8")
        names = git_diff_names(app)
        self.assertEqual(names, ["src/lib.py"])
        from actuallydone.config import Config
        from actuallydone.hookrun import _watched
        cfg = Config.load(app)
        self.assertEqual(changed_paths(cfg), ["src/lib.py"])
        self.assertTrue(_watched("src/lib.py", ["src"], [".py"]))
        self.assertFalse(_watched("demo/app/src/lib.py", ["src"], [".py"]))

    def test_子项目是独立仓库时父目录也要扫到(self):
        """watch_roots 指向的子目录常常各自是 git 仓库，父目录 status 一条都看不到。"""
        sub = self.root / "aics-bank" / "aics-api"
        (sub / "src").mkdir(parents=True)
        (sub / "src" / "lib.py").write_text("x = 1\n", encoding="utf-8")
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "[gate]\nwatch_roots = ['.', 'aics-bank/aics-api']\n"
                   "watch_exts = ['.py']\n")
        subprocess.run(["git", "init"], cwd=sub, check=True, capture_output=True)
        from actuallydone.config import Config
        from actuallydone.hookrun import _watched
        cfg = Config.load(self.root)
        files, note = git_changed(cfg)
        self.assertIn("aics-bank/aics-api/src/lib.py", files, note)
        self.assertTrue(_watched("aics-bank/aics-api/src/lib.py", ["."], [".py"]))

    def test_中文文件名与带空格路径都要原样拿到(self):
        """git 默认把非 ASCII 路径转义成 \\346\\226\\207，按代码页解还会再坏一次。"""
        self._py_project()
        (self.root / "订单 模块").mkdir()
        (self.root / "订单 模块" / "计价.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=self.root, check=True,
                       capture_output=True)
        from actuallydone.config import Config
        files, note = git_changed(Config.load(self.root))
        self.assertIn("订单 模块/计价.py", files, note)

    def test_改名条目只取新路径(self):
        self._py_project()
        subprocess.run(["git", "init"], cwd=self.root, check=True,
                       capture_output=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "add", "-A"], cwd=self.root, check=True,
                       capture_output=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-m", "i"], cwd=self.root, check=True,
                       capture_output=True)
        subprocess.run(["git", "mv", "lib.py", "lib2.py"], cwd=self.root,
                       check=True, capture_output=True)
        from actuallydone.config import Config
        files, note = git_changed(Config.load(self.root))
        self.assertIn("lib2.py", files, note)
        self.assertNotIn("lib.py", files, note)

    def test_没有git仓库时说明原因(self):
        self._py_project()
        from actuallydone.config import Config
        files, note = git_changed(Config.load(self.root))
        self.assertEqual(files, [])
        self.assertIn("仓库", note)

    def test_git不在PATH上时说明原因(self):
        self._py_project()
        from actuallydone.config import Config
        import actuallydone.changed as mod
        orig = mod.shutil.which
        mod.shutil.which = lambda *_a, **_k: None
        orig_fallbacks = mod._GIT_FALLBACKS
        mod._GIT_FALLBACKS = ()
        try:
            files, note = git_changed(Config.load(self.root))
        finally:
            mod.shutil.which = orig
            mod._GIT_FALLBACKS = orig_fallbacks
        self.assertEqual(files, [])
        self.assertIn("没有 git", note)

    def test_git含未跟踪新文件(self):
        self._py_project()
        subprocess.run(["git", "init"], cwd=self.root, check=True,
                       capture_output=True)
        self.write("new_one.py", "x = 1\n")
        names = git_diff_names(self.root)
        self.assertIn("new_one.py", names)
        from actuallydone.config import Config
        cfg = Config.load(self.root)
        self.assertIn("new_one.py", changed_paths(cfg))

    def test_same_as_last_ok_partial比哈希(self):
        self._py_project()
        from actuallydone.changed import _write_partial
        from actuallydone.config import Config
        cfg = Config.load(self.root)
        hashes = file_hashes(cfg, ["lib.py"])
        _write_partial(cfg, ok=True, files=["lib.py"], tests=["test_add"],
                       argv=[], note="ok", file_hashes=hashes)
        self.assertTrue(same_as_last_ok_partial(cfg, ["lib.py"]))
        self.write("lib.py", "def add(a, b):\n    return a - b\n")
        self.assertFalse(same_as_last_ok_partial(cfg, ["lib.py"]))


class TestPreCommitInstall(ProjectCase):
    def _cfg_under(self, sub: str) -> Config:
        """在仓库的子目录里造一个项目，返回指向那一层的 Config。"""
        d = self.root / sub
        (d / "internal").mkdir(parents=True, exist_ok=True)
        (d / "go.mod").write_text("module fixture\n\ngo 1.22\n", encoding="utf-8")
        (d / "internal" / "calc.go").write_text(
            "package internal\n\nfunc Add(a, b int) int { return a + b }\n",
            encoding="utf-8")
        return Config.from_dict(d, {
            "project": {"name": "fixture", "ecosystems": ["go"]},
            "gate": {"watch_roots": ["internal"], "watch_exts": [".go"],
                     "min_tree_files": 1, "step": []},
            "tests": {"adapter": "go", "roots": ["internal"]},
        })

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

    def test_项目在仓库子目录里也要装上(self):
        """多模块工作区：adone.toml 不在仓库根上。

        以前这里硬拼 root/.git，仓库根在上层就当成「不是 git 仓库」跳过，
        于是手工 git commit 从来没被拦过——而它和「装好了」一样安静。
        """
        subprocess.run(["git", "init"], cwd=self.root, check=True,
                       capture_output=True)
        cfg = self._cfg_under("svc/api")
        with redirect_stdout(StringIO()):
            cmd_install(cfg, _args(hooks_only=True))
        hook = self.root / ".git" / "hooks" / "pre-commit"
        self.assertTrue(hook.is_file(), "仓库根在上层时没装 pre-commit")
        self.assertIn(PRE_COMMIT_MARK, hook.read_text(encoding="utf-8"))

    def test_钩子进的是adone_toml那一层(self):
        """站在仓库根上跑 adone，往上找不到子目录里的 adone.toml。"""
        subprocess.run(["git", "init"], cwd=self.root, check=True,
                       capture_output=True)
        cfg = self._cfg_under("svc/api")
        with redirect_stdout(StringIO()):
            cmd_install(cfg, _args(hooks_only=True))
        text = (self.root / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
        self.assertIn('cd "$root/svc/api"', text)

    def test_配了core_hooksPath就写到那边去(self):
        """core.hooksPath 一设，写进 .git/hooks 的东西 git 根本不看。"""
        self.make_go_project()
        subprocess.run(["git", "init"], cwd=self.root, check=True,
                       capture_output=True)
        subprocess.run(["git", "config", "core.hooksPath", ".githooks"],
                       cwd=self.root, check=True, capture_output=True)
        with redirect_stdout(StringIO()):
            cmd_install(self.config(), _args(hooks_only=True))
        moved = self.root / ".githooks" / "pre-commit"
        self.assertTrue(moved.is_file(), "配了 core.hooksPath 却写进 .git/hooks，等于没装")
        self.assertIn(PRE_COMMIT_MARK, moved.read_text(encoding="utf-8"))
        self.assertFalse((self.root / ".git" / "hooks" / "pre-commit").exists())

    def test_不是git仓库就说明原因(self):
        self.make_go_project()
        out = StringIO()
        with redirect_stdout(out):
            cmd_install(self.config(), _args(hooks_only=True))
        said = out.getvalue()
        self.assertIn("不在任何 git 仓库里", said)
        self.assertIn("手工 git commit 不会被拦住", said)
        self.assertFalse((self.root / ".git" / "hooks" / "pre-commit").exists())
