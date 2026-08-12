"""stop 钩子的端到端：渲染出真钩子，起真进程跑。

不测「逻辑的复制品」——这里出问题的历史全在渲染与运行环境上（占位符没替、
钩子进程的 PATH 里没有 adone），把逻辑抄进用例再断言，正好把出事的那段绕过去。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import Namespace
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path

from actuallydone import install
from tests.helpers import ProjectCase

TEMPLATE = install.TEMPLATES / "hooks" / "gate-guard.py"

STUB = """#!/usr/bin/env python3
import os, sys
open(os.environ["ADONE_STUB_MARKER"], "a").write(" ".join(sys.argv[1:]) + "\\n")
sys.stdout.write({PAYLOAD})
"""


class TestHookResolution(ProjectCase):
    def make_stub(self, payload: dict) -> Path:
        """一个假 adone：记下自己被调用过，然后吐一份 gate check 的 JSON。"""
        d = self.root / "fakebin"
        d.mkdir(parents=True, exist_ok=True)
        stub = d / "adone"
        stub.write_text(STUB.replace("{PAYLOAD}", repr(json.dumps(payload))),
                        encoding="utf-8")
        stub.chmod(0o755)
        return stub

    def render_hook(self, path_with_adone: str = "") -> Path:
        """按安装时的 PATH 渲染钩子：ADONE_CMD 就是那一刻 which adone 的结果。"""
        old = os.environ["PATH"]
        os.environ["PATH"] = path_with_adone or "/nonexistent-adone-dir"
        try:
            v = install.variables(self.config())
        finally:
            os.environ["PATH"] = old
        hook = self.root / "hooks" / "gate-guard.py"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(install.render(TEMPLATE.read_text(encoding="utf-8"), v),
                        encoding="utf-8")
        hook.chmod(0o755)
        return hook

    def run_hook(self, hook: Path, path: str) -> dict:
        """钩子进程的环境由客户端定，这里显式给一个：HOME 指到临时目录，
        免得本机 ~/.local/bin 里真装着的 adone 让「找不到」那条用例假绿。"""
        env = {"PATH": path, "HOME": str(self.root / "home"),
               "CURSOR_PROJECT_DIR": str(self.root),
               "ADONE_STUB_MARKER": str(self.root / "called.txt")}
        proc = subprocess.run([sys.executable, str(hook)], input='{"status":"completed"}',
                              capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_门禁通过时钩子放行(self):
        self.make_go_project()
        stub = self.make_stub({"ok": True, "receipt_id": "R-1"})
        hook = self.render_hook(str(stub.parent))
        # 运行时 PATH 里没有 adone，靠安装时烧进去的 ADONE_CMD 找到它
        self.assertEqual(self.run_hook(hook, "/usr/bin:/bin"), {})
        self.assertIn("gate check --json", (self.root / "called.txt").read_text())

    def test_门禁不通过时钩子把问题清单推回来(self):
        self.make_go_project()
        stub = self.make_stub({"ok": False, "problems": ["回执比代码旧", "契约缺 2 条"]})
        hook = self.render_hook(str(stub.parent))
        got = self.run_hook(hook, "/usr/bin:/bin")
        msg = got["followup_message"]
        self.assertIn("回执比代码旧", msg)
        self.assertIn("契约缺 2 条", msg)

    def test_到处都找不到adone时必须回推而不是放行(self):
        """最危险的一格：空输出在终端里和「门禁通过」长得一模一样。"""
        self.make_go_project()
        hook = self.render_hook()                       # 装的时候就没有 adone
        got = self.run_hook(hook, "/nonexistent-adone-dir")
        self.assertIn("followup_message", got, "找不到 adone 却放行了")
        self.assertIn("找不到 adone", got["followup_message"])
        self.assertIn("不等于门禁通过", got["followup_message"])

    def test_hooks_only只碰钩子不碰技能(self):
        """--force --only 曾把技能里的项目私货冲掉过；重渲钩子不该有这个副作用。"""
        self.make_go_project()
        args = Namespace(skills_dir=None, only=None, force=True, dry_run=True,
                         with_hooks=False, hooks_only=True, target="cursor")
        buf = StringIO()
        with redirect_stdout(buf):
            self.assertEqual(install.cmd_install(self.config(), args), 0)
        said = buf.getvalue()
        self.assertIn("gate-guard.py", said)
        self.assertIn("hooks.json", said)
        self.assertNotIn("SKILL.md", said)
