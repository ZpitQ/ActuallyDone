"""stop 钩子的端到端：渲染出真钩子，起真进程跑。

不测「逻辑的复制品」——这里出问题的历史全在渲染与运行环境上（占位符没替、
钩子进程的 PATH 里没有 adone），把逻辑抄进用例再断言，正好把出事的那段绕过去。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from argparse import Namespace
from io import StringIO
from contextlib import redirect_stderr, redirect_stdout
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
        buf = StringIO()
        with redirect_stdout(buf):
            self.assertEqual(install.cmd_install(self.config(), _args(hooks_only=True,
                                                                     dry_run=True)), 0)
        said = buf.getvalue()
        self.assertIn("gate-guard.py", said)
        self.assertIn("hooks.json", said)
        self.assertNotIn("SKILL.md", said)

    def test_hooks_only配only时报错而不是静默忽略(self):
        """静默吞掉用户明确给出的参数，是这个工具最不该犯的错。"""
        self.make_go_project()
        err = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(err):
            rc = install.cmd_install(self.config(),
                                     _args(hooks_only=True, only="completion-gate"))
        self.assertEqual(rc, 2)
        self.assertIn("没有意义", err.getvalue())


def _args(**over) -> Namespace:
    base = dict(skills_dir=None, only=None, force=True, dry_run=False,
                with_hooks=False, hooks_only=False, target="cursor")
    base.update(over)
    return Namespace(**base)


class TestMarkDirty(ProjectCase):
    """afterFileEdit 钩子：它记不下东西时，dirty 为空和「仓库没被改过」长得一样。

    这个钩子早先是 bash + jq，在 Windows 上根本起不来。现在是 Python，
    起进程时也只用 sys.executable，不再假设机器上有 bash。
    """

    def render(self, **cfg_over) -> Path:
        cfg = self.config(**cfg_over)
        src = install.TEMPLATES / "hooks" / "mark-dirty.py"
        hook = self.root / "hooks" / "mark-dirty.py"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(install.render(src.read_text(encoding="utf-8"),
                                       install.variables(cfg)), encoding="utf-8")
        return hook

    def fire(self, hook: Path, file_path: str) -> None:
        env = dict(os.environ, CURSOR_PROJECT_DIR=str(self.root))
        proc = subprocess.run([sys.executable, str(hook)],
                              input=json.dumps({"file_path": file_path}),
                              capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "{}")   # 钩子不该把会话卡死

    def dirty(self) -> str:
        p = self.root / ".adone" / "dirty"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def test_受监视根是点号时也要记下改动(self):
        """adone init 对单模块项目生成的就是 watch_roots = ["."]，
        而按 "./*" 匹配时一个文件都对不上，dirty 于是永远为空。"""
        self.make_go_project()
        hook = self.render(gate={"watch_roots": ["."], "watch_exts": [".go"]})
        self.fire(hook, str(self.root / "internal/calc.go"))
        self.assertIn("internal/calc.go", self.dirty())

    def test_受监视根是子目录时按前缀匹配(self):
        self.make_go_project()
        self.write("other/x.go", "package other\n")
        hook = self.render(gate={"watch_roots": ["internal"], "watch_exts": [".go"]})
        self.fire(hook, str(self.root / "internal/calc.go"))
        self.fire(hook, str(self.root / "other/x.go"))
        self.assertIn("internal/calc.go", self.dirty())
        self.assertNotIn("other/x.go", self.dirty())

    def test_不在受监视后缀里的文件不记(self):
        self.make_go_project()
        self.write("internal/readme.md", "随便写点什么")
        hook = self.render(gate={"watch_roots": ["."], "watch_exts": [".go"]})
        self.fire(hook, str(self.root / "internal/readme.md"))
        self.assertEqual(self.dirty(), "")

    def test_Windows风格的反斜杠路径也能对上(self):
        """Cursor 在 Windows 上给的 file_path 是反斜杠，而受监视根写的是正斜杠。"""
        self.make_go_project()
        hook = self.render(gate={"watch_roots": ["internal"], "watch_exts": [".go"]})
        self.fire(hook, str(self.root / "internal" / "calc.go").replace("/", os.sep))
        self.assertIn("internal/calc.go", self.dirty())

    def test_仓库外的文件不算(self):
        self.make_go_project()
        hook = self.render(gate={"watch_roots": ["."], "watch_exts": [".go"]})
        self.fire(hook, "/etc/somewhere/else.go")
        self.assertEqual(self.dirty(), "")

    def test_payload坏了也要留痕而不是静默(self):
        self.make_go_project()
        hook = self.render()
        env = dict(os.environ, CURSOR_PROJECT_DIR=str(self.root))
        proc = subprocess.run([sys.executable, str(hook)], input="不是 JSON",
                              capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.dirty(), "")
        log = (self.root / ".adone" / "hook.log").read_text(encoding="utf-8")
        self.assertIn("读不动 payload", log)


class TestHooksJson(ProjectCase):
    def test_合并而不是冲掉别人的钩子(self):
        """整份覆盖会把用户自己配的钩子一起删掉，而它们失效同样是无声的。"""
        mine = {"version": 1, "hooks": {
            "beforeShellExecution": [{"command": "./my-guard.sh"}],
            "stop": [{"command": "./my-stop.sh"}],
        }}
        merged, kept = install.merge_hooks(mine)
        self.assertEqual(kept, 2)
        self.assertEqual(merged["hooks"]["beforeShellExecution"], [{"command": "./my-guard.sh"}])
        cmds = [h["command"] for h in merged["hooks"]["stop"]]
        self.assertEqual(cmds[0], "./my-stop.sh")
        self.assertIn(".cursor/hooks/gate-guard.py", cmds[1])

    def test_重装不会把自己的条目叠成两份(self):
        once, _ = install.merge_hooks({})
        twice, kept = install.merge_hooks(once)
        self.assertEqual(twice, once)
        self.assertEqual(kept, 0)

    def test_注册的是显式解释器调用而不是裸脚本路径(self):
        """靠 shebang 加可执行位启动是 POSIX 才成立的约定：Windows 上 Cursor
        起不动 .py，钩子静默不触发，Agent 改完代码没人提醒。"""
        merged, _ = install.merge_hooks({})
        for event in ("afterFileEdit", "stop"):
            cmd = merged["hooks"][event][0]["command"]
            self.assertNotEqual(cmd.split()[0][-3:], ".py", cmd)
            self.assertIn(".cursor/hooks/", cmd)

    def test_旧版bash钩子会被摘掉(self):
        old = {"version": 1, "hooks": {
            "afterFileEdit": [{"command": ".cursor/hooks/mark-dirty.sh", "timeout": 10}]}}
        merged, kept = install.merge_hooks(old)
        self.assertEqual(kept, 0)
        blob = json.dumps(merged, ensure_ascii=False)
        self.assertNotIn("mark-dirty.sh", blob)
        self.assertIn("mark-dirty.py", blob)


class TestInstallFailsLoud(ProjectCase):
    def test_写不进去时给人话而不是堆栈(self):
        self.make_go_project()
        skills = self.root / "只读技能目录"
        skills.mkdir()
        skills.chmod(0o500)
        self.addCleanup(skills.chmod, 0o700)
        err, out = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = install.cmd_install(self.config(), _args(skills_dir=str(skills)))
        self.assertEqual(rc, 1)
        said = err.getvalue()
        self.assertIn("写不进去", said)
        self.assertIn("安装没有完成", said)
        self.assertNotIn("Traceback", said)


class TestDoctorChecksHooks(ProjectCase):
    """钩子失效时，doctor 是唯一有机会说话的地方。"""

    def install_hooks(self, **cfg_over):
        cfg = self.config(**cfg_over)
        with redirect_stdout(StringIO()):
            install.cmd_install(cfg, _args(hooks_only=True))
        return cfg

    def test_没装钩子不算问题(self):
        self.make_go_project()
        lines, problems = install.hooks_report(self.config())
        self.assertEqual(problems, [])
        self.assertIn("未安装", lines[0])

    def test_钩子找不到adone时报出来(self):
        self.make_go_project()
        cfg = self.install_hooks()
        guard = self.root / ".cursor" / "hooks" / "gate-guard.py"
        guard.write_text(re.sub(r'^ADONE_CMD = ".*"', 'ADONE_CMD = "/nonexistent/adone"',
                                guard.read_text(encoding="utf-8"), flags=re.M),
                         encoding="utf-8")
        old = os.environ["PATH"]
        os.environ["PATH"] = str(self.root / "空目录")
        os.environ["HOME"] = str(self.root / "空家")
        try:
            _, problems = install.hooks_report(cfg)
        finally:
            os.environ["PATH"] = old
        self.assertTrue(any("找不到 adone" in p for p in problems), problems)

    def test_钩子命令里的解释器找不到时报出来(self):
        """钩子起不来的样子就是「什么都不发生」，doctor 是唯一有机会说话的地方。
        以前这里只查可执行位，而 os.access(X_OK) 在 Windows 上恒为真。"""
        self.make_go_project()
        cfg = self.install_hooks()
        hooks_json = self.root / ".cursor" / "hooks.json"
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        data["hooks"]["stop"][0]["command"] = "绝不存在的解释器 .cursor/hooks/gate-guard.py"
        hooks_json.write_text(json.dumps(data), encoding="utf-8")
        _, problems = install.hooks_report(cfg)
        self.assertTrue(any("绝不存在的解释器" in p for p in problems), problems)

    def test_登记的脚本不存在时报出来(self):
        self.make_go_project()
        cfg = self.install_hooks()
        (self.root / ".cursor" / "hooks" / "mark-dirty.py").unlink()
        _, problems = install.hooks_report(cfg)
        self.assertTrue(any("mark-dirty.py" in p for p in problems), problems)

    def test_还登记着旧版bash钩子要报出来(self):
        self.make_go_project()
        cfg = self.install_hooks()
        hooks_json = self.root / ".cursor" / "hooks.json"
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        data["hooks"]["afterFileEdit"] = [{"command": ".cursor/hooks/mark-dirty.sh"}]
        hooks_json.write_text(json.dumps(data), encoding="utf-8")
        _, problems = install.hooks_report(cfg)
        self.assertTrue(any("旧版 mark-dirty.sh" in p for p in problems), problems)

    def test_配置改了钩子没重渲要报出来(self):
        self.make_go_project()
        self.install_hooks()
        moved = self.config(project={"state_dir": ".adone2"})
        _, problems = install.hooks_report(moved)
        self.assertTrue(any("state_dir" in p for p in problems), problems)
