"""Qoder 钩子：另一套落点和出口。现有 test_hooks 的 Cursor 期望一条都不改。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from actuallydone import install
from actuallydone.clean import cmd_clean, _strip_qoder_settings
from actuallydone.config import Config
from tests.helpers import ProjectCase

ADONE = Path(__file__).resolve().parent.parent / "bin" / "adone"


def _args(**over) -> Namespace:
    base = dict(skills_dir=None, only=None, force=True, dry_run=False,
                with_hooks=False, hooks_only=False, target="cursor", ide="auto")
    base.update(over)
    return Namespace(**base)


def _without_qoder_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("QODER_PROJECT_DIR", None)
    env.pop("QODER_HOME", None)
    return env


class TestQoderProtocol(ProjectCase):
    def _toml(self) -> None:
        self.make_go_project()
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "ecosystems = ['go']\n"
                   "[gate]\nwatch_roots = ['internal']\nwatch_exts = ['.go']\n"
                   "min_tree_files = 1\n"
                   "[[gate.step]]\nname = 'go test'\nkind = 'test'\n"
                   "adapter = 'go'\nargv = ['go', 'test', './...']\n"
                   "[tests]\nadapter = 'go'\n")

    def _dirty_orphan(self) -> None:
        self.write("internal/orphan.go", "package internal\nfunc Orphan() {}\n")
        dest = self.root / ".adone" / "dirty"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("internal/orphan.go\n", encoding="utf-8")

    def run_hook(self, name: str, payload: dict, extra_env: dict | None = None):
        env = _without_qoder_env()
        env["CURSOR_PROJECT_DIR"] = str(self.root)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, str(ADONE), "hook", name],
            input=json.dumps(payload), capture_output=True, text=True,
            env=env, cwd=self.root)

    def test_PostToolUse记下dirty(self):
        self._toml()
        path = str(self.root / "internal" / "calc.go")
        proc = self.run_hook("mark-dirty", {
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": path},
        })
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout or "{}"), {})
        dirty = (self.root / ".adone" / "dirty").read_text(encoding="utf-8")
        self.assertIn("internal/calc.go", dirty)

    def test_Stop失败exit2且文案走stderr(self):
        self._toml()
        self._dirty_orphan()
        proc = self.run_hook("gate-guard", {
            "hook_event_name": "Stop",
            "stop_hook_active": False,
        })
        self.assertEqual(proc.returncode, 2, proc.stderr + proc.stdout)
        self.assertIn("相关用例", proc.stderr)
        self.assertNotIn("followup_message", proc.stdout)

    def test_stop_hook_active立刻放行(self):
        self._toml()
        self._dirty_orphan()
        proc = self.run_hook("gate-guard", {
            "hook_event_name": "Stop",
            "stop_hook_active": True,
        })
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout or "{}"), {})
        log = (self.root / ".adone" / "hook.log").read_text(encoding="utf-8")
        self.assertIn("stop_hook_active", log)

    def test_PreToolUse非commit立刻放行(self):
        self._toml()
        proc = self.run_hook("commit-guard", {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
        })
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout or "{}"), {})

    def test_PreToolUse拦git_commit(self):
        self._toml()
        proc = self.run_hook("commit-guard", {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m x"},
        })
        self.assertEqual(proc.returncode, 2, proc.stderr + proc.stdout)
        out = json.loads(proc.stdout)
        decision = out["hookSpecificOutput"]["permissionDecision"]
        self.assertEqual(decision, "deny")
        self.assertIn("全量", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_同一条gate_guard喂Cursor仍是followup_message(self):
        """Cursor 的 {status:completed} 必须还是 exit 0 + followup_message。"""
        self._toml()
        self._dirty_orphan()
        proc = self.run_hook("gate-guard", {"status": "completed", "loop_count": 0})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = json.loads(proc.stdout)
        self.assertIn("followup_message", got)
        self.assertIn("相关用例", got["followup_message"])


class TestQoderInstall(ProjectCase):
    def test_ide_auto无Qoder环境不创建qoder目录(self):
        self.make_go_project()
        old = {k: os.environ.pop(k) for k in ("QODER_PROJECT_DIR", "QODER_HOME")
               if k in os.environ}
        try:
            with redirect_stdout(StringIO()):
                rc = install.cmd_install(self.config(),
                                         _args(hooks_only=True, ide="auto"))
        finally:
            os.environ.update(old)
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / ".cursor" / "hooks.json").is_file())
        self.assertFalse((self.root / ".qoder").exists())

    def test_ide_qoder不写cursor_hooks(self):
        self.make_go_project()
        with redirect_stdout(StringIO()):
            rc = install.cmd_install(self.config(),
                                     _args(hooks_only=True, ide="qoder"))
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / ".qoder" / "settings.json").is_file())
        self.assertFalse((self.root / ".cursor" / "hooks.json").exists())
        self.assertFalse((self.root / ".cursor").exists())
        data = json.loads((self.root / ".qoder" / "settings.json").read_text(
            encoding="utf-8"))
        events = data["hooks"]
        self.assertIn("PostToolUse", events)
        self.assertIn("Stop", events)
        self.assertIn("PreToolUse", events)
        matchers = {e.get("matcher") for e in events["PreToolUse"]}
        self.assertEqual(matchers, {"Bash", "Shell"})
        blob = json.dumps(events)
        self.assertNotIn(".cursor/hooks/", blob)
        self.assertNotIn(".exe", blob)

    def test_合并保留别人的Qoder钩子(self):
        self.make_go_project()
        dest = self.root / ".qoder" / "settings.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps({
            "hooks": {
                "UserPromptSubmit": [{
                    "hooks": [{"type": "command", "command": "echo-foreign"}],
                }],
                "Stop": [{
                    "hooks": [{"type": "command", "command": "my-stop.sh"}],
                }],
            }
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        with redirect_stdout(StringIO()):
            rc = install.cmd_install(self.config(),
                                     _args(hooks_only=True, ide="qoder", force=True))
        self.assertEqual(rc, 0)
        data = json.loads(dest.read_text(encoding="utf-8"))
        events = data["hooks"]
        self.assertEqual(events["UserPromptSubmit"][0]["hooks"][0]["command"],
                         "echo-foreign")
        stop_cmds = [h.get("command") for group in events["Stop"]
                     for h in (group.get("hooks") or [])]
        self.assertIn("my-stop.sh", stop_cmds)
        self.assertTrue(any("hook" in json.dumps(group) for group in events["Stop"]))

    def test_装Qoder时技能写到qoder_skills(self):
        self.make_go_project()
        with redirect_stdout(StringIO()):
            rc = install.cmd_install(self.config(),
                                     _args(with_hooks=True, ide="qoder", only="completion-gate"))
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / ".qoder" / "skills" / "completion-gate"
                         / "SKILL.md").is_file())
        self.assertFalse((self.root / ".cursor" / "skills").exists())


class TestQoderDoctorClean(ProjectCase):
    def test_没装Qoder不算问题(self):
        self.make_go_project()
        lines, problems = install.hooks_report(self.config())
        self.assertEqual(problems, [])
        self.assertTrue(any("未安装" in ln for ln in lines))
        self.assertFalse(any("Qoder" in ln for ln in lines))

    def test_settings在但缺Stop报装了一半(self):
        self.make_go_project()
        dest = self.root / ".qoder" / "settings.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps({
            "hooks": {
                "PostToolUse": [{
                    "matcher": "Write",
                    "hooks": [{
                        "type": "command",
                        "command": "python3",
                        "args": ["-m", "actuallydone", "hook", "mark-dirty"],
                    }],
                }],
            }
        }), encoding="utf-8")
        _, problems = install.hooks_report(self.config())
        self.assertTrue(any("装了一半" in p for p in problems), problems)

    def test_clean剥离Qoder登记留下别人的(self):
        self.make_go_project()
        dest = self.root / ".qoder" / "settings.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps({
            "hooks": {
                "Stop": [{
                    "hooks": [
                        {"type": "command", "command": "keep-me.sh"},
                        {"type": "command", "command": "python3",
                         "args": ["-m", "actuallydone", "hook", "gate-guard"]},
                    ],
                }],
            }
        }), encoding="utf-8")
        skill = self.root / ".qoder" / "skills" / "completion-gate" / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text("# x\n", encoding="utf-8")
        with redirect_stdout(StringIO()):
            rc = cmd_clean(Namespace(root=str(self.root), yes=True, dry_run=False))
        self.assertEqual(rc, 0)
        self.assertFalse(skill.exists())
        kept = json.loads(dest.read_text(encoding="utf-8"))
        blob = json.dumps(kept)
        self.assertIn("keep-me.sh", blob)
        self.assertNotIn("actuallydone", blob)

    def test_strip整份只剩我们的可以删(self):
        data = {
            "hooks": {
                "Stop": [{
                    "hooks": [{"type": "command", "command": "python3",
                               "args": ["-m", "actuallydone", "hook", "gate-guard"]}],
                }],
            }
        }
        stripped, kept = _strip_qoder_settings(data)
        self.assertIsNone(stripped)
        self.assertEqual(kept, 0)
