"""adone clean：拆完之后门禁和钩子都不再跑。"""

from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from io import StringIO
from contextlib import redirect_stdout

from actuallydone.clean import cmd_clean
from actuallydone.config import ConfigError, Config
from actuallydone.detect import cmd_init
from actuallydone.install import PRE_COMMIT_MARK, cmd_install
from tests.helpers import ProjectCase
from tests.test_hooks import _args as _install_args


def _args(**over) -> Namespace:
    base = dict(root=None, yes=True, dry_run=False)
    base.update(over)
    return Namespace(**base)


class TestClean(ProjectCase):
    def test_没有配置时什么都不删(self):
        out = StringIO()
        with redirect_stdout(out):
            rc = cmd_clean(_args(root=str(self.root)))
        self.assertEqual(rc, 0)
        self.assertIn("没有", out.getvalue())

    def test_演练不落盘(self):
        self.make_go_project()
        with redirect_stdout(StringIO()):
            cmd_init(Namespace(root=str(self.root), force=True, yes=True))
        self.assertTrue((self.root / "adone.toml").is_file())
        with redirect_stdout(StringIO()):
            rc = cmd_clean(_args(root=str(self.root), dry_run=True))
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / "adone.toml").is_file())

    def test_拆完找不到配置钩子也不再登记(self):
        self.make_go_project()
        with redirect_stdout(StringIO()):
            cmd_init(Namespace(root=str(self.root), force=True, yes=True))
            cmd_install(Config.load(self.root), _install_args(hooks_only=True))
        hooks = json.loads((self.root / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
        self.assertIn("stop", hooks.get("hooks") or {})
        with redirect_stdout(StringIO()):
            rc = cmd_clean(_args(root=str(self.root)))
        self.assertEqual(rc, 0)
        self.assertFalse((self.root / "adone.toml").exists())
        self.assertFalse((self.root / ".adone").exists())
        self.assertFalse((self.root / ".cursor" / "hooks.json").exists())
        with self.assertRaises(ConfigError):
            Config.load(self.root)

    def test_别人的钩子留下(self):
        self.make_go_project()
        with redirect_stdout(StringIO()):
            cmd_init(Namespace(root=str(self.root), force=True, yes=True))
            cmd_install(Config.load(self.root), _install_args(hooks_only=True))
        path = self.root / ".cursor" / "hooks.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["hooks"]["sessionStart"].insert(0, {"command": "echo hello"})
        path.write_text(json.dumps(data), encoding="utf-8")
        with redirect_stdout(StringIO()):
            cmd_clean(_args(root=str(self.root)))
        self.assertTrue(path.is_file())
        left = json.loads(path.read_text(encoding="utf-8"))
        cmds = [h.get("command") for h in (left.get("hooks") or {}).get("sessionStart") or []]
        self.assertEqual(cmds, ["echo hello"])
        self.assertNotIn("stop", left.get("hooks") or {})

    def test_我们渲染的技能也拆掉(self):
        self.make_go_project()
        with redirect_stdout(StringIO()):
            cmd_init(Namespace(root=str(self.root), force=True, yes=True))
            cmd_install(Config.load(self.root), _install_args(with_hooks=True))
        skill = self.root / ".cursor" / "skills" / "completion-gate" / "SKILL.md"
        self.assertTrue(skill.is_file())
        with redirect_stdout(StringIO()):
            cmd_clean(_args(root=str(self.root)))
        self.assertFalse(skill.exists())

    def test_本机pre_commit也拆掉(self):
        self.make_go_project()
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True)
        with redirect_stdout(StringIO()):
            cmd_init(Namespace(root=str(self.root), force=True, yes=True))
            cmd_install(Config.load(self.root), _install_args(hooks_only=True))
        hook = self.root / ".git" / "hooks" / "pre-commit"
        self.assertTrue(hook.is_file())
        self.assertIn(PRE_COMMIT_MARK, hook.read_text(encoding="utf-8"))
        with redirect_stdout(StringIO()):
            cmd_clean(_args(root=str(self.root)))
        self.assertFalse(hook.exists())
