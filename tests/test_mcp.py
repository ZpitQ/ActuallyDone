from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from actuallydone.cli import build_parser
from actuallydone.mcp import McpServer, serve_stdio


class TestMcpProtocol(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="adone-mcp-")
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_initialize_echoes_supported_version_and_capabilities(self):
        response = McpServer(self.root).handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"}},
        })
        self.assertEqual(response["result"]["protocolVersion"], "2025-03-26")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_unsupported_version_is_invalid_params(self):
        response = McpServer(self.root).handle({
            "jsonrpc": "2.0", "id": 2, "method": "initialize",
            "params": {"protocolVersion": "1999-01-01"},
        })
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("supported", response["error"]["data"])

    def test_notification_has_no_response(self):
        self.assertIsNone(McpServer(self.root).handle({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
        }))

    def test_unknown_method_and_malformed_request_are_json_rpc_errors(self):
        unknown = McpServer(self.root).handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})
        malformed = McpServer(self.root).handle({"id": 4, "method": "ping"})
        self.assertEqual(unknown["error"]["code"], -32601)
        self.assertEqual(malformed["error"]["code"], -32600)

    def test_stdio_emits_one_json_line_and_logs_only_to_stderr(self):
        incoming = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n")
        outgoing, diagnostics = io.StringIO(), io.StringIO()
        self.assertEqual(serve_stdio(self.root, incoming, outgoing, diagnostics), 0)
        self.assertEqual(json.loads(outgoing.getvalue())["result"], {})
        self.assertNotIn("{", diagnostics.getvalue())

    def test_stdio_recovers_from_parse_error_and_continues(self):
        incoming = io.StringIO("not-json\n[]\n" +
                               json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}) + "\n")
        outgoing, diagnostics = io.StringIO(), io.StringIO()
        self.assertEqual(serve_stdio(self.root, incoming, outgoing, diagnostics), 0)
        responses = [json.loads(line) for line in outgoing.getvalue().splitlines()]
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["error"]["code"], -32600)
        self.assertEqual(responses[2]["result"], {})
        self.assertEqual(diagnostics.getvalue(), "")

    def test_root_resolution_honors_environment_before_working_directory(self):
        with patch.dict(os.environ, {"ADONE_PROJECT_DIR": str(self.root)}):
            from actuallydone.mcp import resolve_mcp_root
            self.assertEqual(resolve_mcp_root(), self.root.resolve())


class TestMcpTools(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="adone-mcp-tools-")
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
step = []
""",
            encoding="utf-8",
        )
        self.server = McpServer(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_tools_list_has_five_fixed_tools(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 5,
                                       "method": "tools/list", "params": {}})
        self.assertEqual({item["name"] for item in response["result"]["tools"]}, {
            "adone_status", "adone_check", "adone_brief", "adone_run", "adone_audit"})
        run = next(item for item in response["result"]["tools"]
                   if item["name"] == "adone_run")
        self.assertIn("side effect", run["description"].lower())

    def test_unknown_tool_and_invalid_arguments_are_tool_errors(self):
        unknown = self.server.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                                      "params": {"name": "missing", "arguments": {}}})
        bad = self.server.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                  "params": {"name": "adone_run",
                                              "arguments": {"scope": "shell"}}})
        self.assertTrue(unknown["result"]["isError"])
        self.assertTrue(bad["result"]["isError"])
        self.assertIn("changed", json.dumps(bad, ensure_ascii=False))

    def test_tools_call_rejects_unknown_top_level_parameters(self):
        response = self.server.handle({
            "jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "adone_status", "projectPath": str(self.root)},
        })
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("projectPath", response["error"]["data"])

    def test_run_emits_progress_notifications_for_progress_token(self):
        python = sys.executable.replace("\\", "/")
        self.root.joinpath("adone.toml").write_text(
            f"""[project]
name = "fixture"

[gate]
watch_roots = ["src"]
watch_exts = [".py"]
min_tree_files = 1

[[gate.step]]
name = "smoke"
argv = ['{python}', '-c', 'print("smoke")']
""",
            encoding="utf-8",
        )
        incoming = io.StringIO(json.dumps({
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "adone_run", "arguments": {"scope": "full"},
                       "_meta": {"progressToken": "run-9"}},
        }) + "\n")
        outgoing, diagnostics = io.StringIO(), io.StringIO()
        self.assertEqual(serve_stdio(self.root, incoming, outgoing, diagnostics), 0)
        responses = [json.loads(line) for line in outgoing.getvalue().splitlines()]
        progress = [item for item in responses if item.get("method") == "notifications/progress"]
        self.assertTrue(progress)
        self.assertTrue(all(item["params"]["progressToken"] == "run-9" for item in progress))
        self.assertEqual(responses[-1]["id"], 9)
        self.assertFalse(responses[-1]["result"]["isError"])

    def test_status_is_structured_and_does_not_create_state(self):
        result = self.server.call_tool("adone_status", {})
        self.assertIn("structuredContent", result)
        self.assertEqual(result["structuredContent"]["project_root"], str(self.root))
        self.assertFalse((self.root / ".adone").exists())

    def test_check_returns_gate_shape_and_rejects_negative_spotcheck(self):
        bad = self.server.call_tool("adone_check", {"spotcheck": -1})
        self.assertTrue(bad["isError"])
        self.assertEqual(bad["structuredContent"]["exit_code"], 2)
        good = self.server.call_tool("adone_check", {"with_integrity": False})
        self.assertIn("ok", good["structuredContent"])
        self.assertIn("problems", good["structuredContent"])

    def test_run_writes_receipt_and_audit_does_not_replace_it(self):
        python = sys.executable.replace("\\", "/")
        self.root.joinpath("adone.toml").write_text(
            f"""[project]
name = "fixture"

[gate]
watch_roots = ["src"]
watch_exts = [".py"]
min_tree_files = 1

[[gate.step]]
name = "smoke"
argv = ['{python}', '-c', 'print("smoke")']
""",
            encoding="utf-8",
        )
        run = self.server.call_tool("adone_run", {"scope": "full"})
        self.assertFalse(run["isError"])
        receipt = run["structuredContent"]["receipt"]
        self.assertTrue(receipt["ok"])
        latest_before = (self.root / ".adone" / "latest.json").read_text(encoding="utf-8")
        audit = self.server.call_tool("adone_audit", {"mode": "review", "spotcheck": 0})
        self.assertFalse(audit["isError"])
        self.assertTrue((self.root / ".adone" / "audit.json").is_file())
        self.assertEqual((self.root / ".adone" / "latest.json").read_text(encoding="utf-8"),
                         latest_before)

    def test_read_only_status_and_check_keep_dirty_marker(self):
        python = sys.executable.replace("\\", "/")
        self.root.joinpath("adone.toml").write_text(
            f"""[project]
name = "fixture"
[gate]
watch_roots = ["src"]
watch_exts = [".py"]
min_tree_files = 1
[[gate.step]]
name = "smoke"
argv = ['{python}', '-c', 'print("smoke")']
""", encoding="utf-8")
        self.assertFalse(self.server.call_tool("adone_run", {"scope": "full"})["isError"])
        dirty = self.root / ".adone" / "dirty"
        dirty.write_text("src/main.py\n", encoding="utf-8")
        self.server.call_tool("adone_status", {})
        self.assertTrue(dirty.is_file())
        self.server.call_tool("adone_check", {})
        self.assertTrue(dirty.is_file())

    def test_run_rejects_arbitrary_command_arguments(self):
        result = self.server.call_tool("adone_run", {
            "scope": "full", "argv": ["rm", "-rf", "."]})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["exit_code"], 2)

    def test_missing_config_is_a_structured_tool_error(self):
        with tempfile.TemporaryDirectory(prefix="adone-mcp-no-config-") as raw:
            result = McpServer(Path(raw)).call_tool("adone_status", {})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"], "config_error")


class TestMcpCli(unittest.TestCase):
    def test_cli_parses_mcp_server(self):
        with tempfile.TemporaryDirectory(prefix="adone-mcp-cli-") as raw:
            root = Path(raw)
            args = build_parser().parse_args(["serve", "--mcp", "--root", str(root)])
        self.assertEqual(args.cmd, "serve")
        self.assertTrue(args.mcp)
        self.assertEqual(Path(args.root), root)

    def test_cli_rejects_serve_without_mcp(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["serve"])


if __name__ == "__main__":
    unittest.main()

