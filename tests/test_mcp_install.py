from __future__ import annotations

import tempfile
import tomllib
import unittest
from argparse import Namespace
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from actuallydone.cli import build_parser
from actuallydone.config import Config
from actuallydone.install import cmd_install
from actuallydone.agent_targets import McpInstallOptions


class TestTargetRegistry(unittest.TestCase):
    def test_registry_contains_only_first_wave_targets(self):
        from actuallydone.agent_targets import targets
        self.assertEqual([target.id for target in targets()], ["codex", "cursor", "claude"])

    def test_legacy_install_rejects_unknown_target_in_command_handler(self):
        with tempfile.TemporaryDirectory(prefix="adone-install-") as raw:
            root = Path(raw)
            (root / "adone.toml").write_text(
                "[project]\nname='fixture'\n[gate]\nwatch_roots=[]\nwatch_exts=[]\n",
                encoding="utf-8",
            )
            cfg = Config.load(root)
            args = Namespace(mcp=False, target="claude", skills_dir=None,
                             hooks_only=False, only=None, with_hooks=False,
                             ide="cursor", force=False, dry_run=True)
            self.assertEqual(cmd_install(cfg, args), 2)

    def test_mcp_install_parser_accepts_csv_targets_and_locations(self):
        args = build_parser().parse_args(["install", "--mcp", "--target", "codex,cursor",
                                          "--location", "local"])
        self.assertTrue(args.mcp)
        self.assertEqual(args.target, "codex,cursor")
        self.assertEqual(args.location, "local")

    def test_uninstall_parser_requires_explicit_mcp_mode(self):
        args = build_parser().parse_args(["uninstall", "--mcp", "--target", "codex"])
        self.assertTrue(args.mcp)
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["uninstall", "--target", "codex"])


class TargetFiles(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="adone-target-")
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.options = McpInstallOptions("local", self.root, home=self.home)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cursor_merge_preserves_foreign_server_and_is_idempotent(self):
        from actuallydone.agent_targets import get_target
        path = self.root / ".cursor" / "mcp.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"mcpServers": {"other": {"command": "other"}},
                                    "custom": True}), encoding="utf-8")
        target = get_target("cursor")
        first = target.install(self.options)
        before = path.read_text(encoding="utf-8")
        second = target.install(self.options)
        self.assertEqual(first.written, 1)
        self.assertEqual(second.written, 0)
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertIn("other", before)
        self.assertTrue((self.root / ".cursor" / "ACTUALLYDONE.md").is_file())

    def test_codex_merge_and_uninstall_preserve_foreign_table(self):
        from actuallydone.agent_targets import get_target
        path = self.root / ".codex" / "config.toml"
        path.parent.mkdir(parents=True)
        path.write_text('[mcp_servers.other]\ncommand = "other"\n', encoding="utf-8")
        target = get_target("codex")
        target.install(self.options)
        text = path.read_text(encoding="utf-8")
        self.assertIn("mcp_servers.other", text)
        self.assertIn("mcp_servers.adone", text)
        target.uninstall(self.options)
        text = path.read_text(encoding="utf-8")
        self.assertIn("mcp_servers.other", text)
        self.assertNotIn("mcp_servers.adone", text)
        self.assertNotIn("ACTUALLYDONE:MCP", text)

    def test_codex_config_is_valid_toml_and_reinstall_is_idempotent(self):
        from actuallydone.agent_targets import get_target
        target = get_target("codex")
        config = self.root / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('[mcp_servers.other]\ncommand = "other"\n', encoding="utf-8")

        first = target.install(self.options)
        installed = config.read_text(encoding="utf-8")
        parsed = tomllib.loads(installed)
        self.assertEqual(parsed["mcp_servers"]["adone"]["args"], ["serve", "--mcp"])
        self.assertTrue(first.changed)
        self.assertIn("信任", first.message)

        second = target.install(self.options)
        self.assertFalse(second.changed)
        self.assertIsNone(second.error)
        self.assertEqual(config.read_text(encoding="utf-8"), installed)

    def test_claude_local_uses_project_mcp_json_and_marker(self):
        from actuallydone.agent_targets import get_target
        target = get_target("claude")
        target.install(self.options)
        config = self.root / ".mcp.json"
        self.assertEqual(json.loads(config.read_text(encoding="utf-8"))["mcpServers"]["adone"]["args"],
                         ["serve", "--mcp"])
        marker = self.root / "CLAUDE.md"
        marker.write_text("Before\n" + marker.read_text(encoding="utf-8") + "After\n",
                          encoding="utf-8")
        target.uninstall(self.options)
        self.assertFalse(config.read_text(encoding="utf-8").find('"adone"') >= 0)
        self.assertEqual(marker.read_text(encoding="utf-8"), "Before\nAfter\n")

    def test_existing_unowned_entry_is_not_overwritten_or_uninstalled(self):
        from actuallydone.agent_targets import get_target
        target = get_target("cursor")
        config = self.root / ".cursor" / "mcp.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"mcpServers": {"adone": {"command": "custom"}}}),
                          encoding="utf-8")
        installed = target.install(self.options)
        self.assertTrue(installed.error)
        target.uninstall(self.options)
        self.assertIn("custom", config.read_text(encoding="utf-8"))

    def test_same_value_foreign_json_entry_is_preserved_on_uninstall(self):
        from actuallydone.agent_targets import get_target
        ours = {"command": "adone", "args": ["serve", "--mcp"]}
        for target_id, relative in (("cursor", Path(".cursor") / "mcp.json"),
                                    ("claude", Path(".mcp.json"))):
            with self.subTest(target=target_id):
                config = self.root / relative
                config.parent.mkdir(parents=True, exist_ok=True)
                config.write_text(json.dumps({"mcpServers": {"adone": ours}}),
                                  encoding="utf-8")
                target = get_target(target_id)
                target.install(self.options)
                target.uninstall(self.options)
                self.assertEqual(json.loads(config.read_text(encoding="utf-8")),
                                 {"mcpServers": {"adone": ours}})

    def test_modified_owned_json_entry_is_preserved_on_uninstall(self):
        from actuallydone.agent_targets import get_target
        target = get_target("cursor")
        target.install(self.options)
        config = self.root / ".cursor" / "mcp.json"
        data = json.loads(config.read_text(encoding="utf-8"))
        data["mcpServers"]["adone"] = {"command": "user-owned", "args": []}
        config.write_text(json.dumps(data), encoding="utf-8")

        target.uninstall(self.options)

        self.assertEqual(json.loads(config.read_text(encoding="utf-8"))["mcpServers"]["adone"],
                         {"command": "user-owned", "args": []})
        self.assertFalse(target.ownership_path(self.options).exists())

    def test_codex_nested_unowned_table_is_not_followed_by_duplicate_parent(self):
        from actuallydone.agent_targets import get_target
        target = get_target("codex")
        config = self.root / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        original = '[mcp_servers.adone.settings]\nvalue = "custom"\n'
        config.write_text(original, encoding="utf-8")
        result = target.install(self.options)
        self.assertTrue(result.error)
        self.assertEqual(config.read_text(encoding="utf-8"), original)

    def test_print_config_is_a_valid_json_fragment_for_json_targets(self):
        from actuallydone.agent_targets import get_target
        snippet = get_target("claude").print_config(self.options)
        parsed = json.loads(snippet)
        self.assertEqual(parsed["mcpServers"]["adone"]["args"], ["serve", "--mcp"])

    def test_detect_distinguishes_our_entry_from_foreign_config(self):
        from actuallydone.agent_targets import get_target
        target = get_target("cursor")
        self.assertFalse(target.detect(self.options)["installed"])
        (self.root / ".cursor").mkdir(parents=True)
        (self.root / ".cursor" / "mcp.json").write_text(
            json.dumps({"mcpServers": {"adone": {"command": "other"}}}), encoding="utf-8")
        self.assertFalse(target.detect(self.options)["installed"])
        (self.root / ".cursor" / "mcp.json").unlink()
        target.install(self.options)
        self.assertTrue(target.detect(self.options)["installed"])


class TestClaudeAndCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="adone-cli-install-")
        self.root = Path(self.tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (self.root / "adone.toml").write_text(
            """[project]
name = "fixture"

[gate]
watch_roots = ["src"]
watch_exts = [".py"]
min_tree_files = 1
""",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_install_print_and_uninstall_commands(self):
        args = build_parser().parse_args([
            "--root", str(self.root), "install", "--mcp",
            "--target", "codex,cursor,claude", "--location", "local",
        ])
        self.assertEqual(args.func(args), 0)
        self.assertTrue((self.root / ".codex" / "config.toml").is_file())
        self.assertTrue((self.root / ".cursor" / "mcp.json").is_file())
        self.assertTrue((self.root / ".mcp.json").is_file())

        buf = StringIO()
        print_args = build_parser().parse_args([
            "--root", str(self.root), "install", "--mcp", "--print-config", "claude",
        ])
        with redirect_stdout(buf):
            self.assertEqual(print_args.func(print_args), 0)
        self.assertIn('"mcpServers"', buf.getvalue())
        self.assertEqual(list((self.root / ".mcp.json").parent.glob("*.bak")), [])

        remove_args = build_parser().parse_args([
            "--root", str(self.root), "uninstall", "--mcp",
            "--target", "codex,cursor,claude", "--location", "local",
        ])
        self.assertEqual(remove_args.func(remove_args), 0)
        self.assertNotIn('"adone"', (self.root / ".mcp.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

