# ActuallyDone MCP Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent local stdio MCP server and idempotent Codex, Cursor, and Claude Code installers to ActuallyDone without changing the existing gate, receipt, audit, or hook semantics.

**Architecture:** A small `actuallydone.mcp` module owns JSON-RPC framing, MCP handshake, tool schemas, root resolution, validation, and serialization. Tool handlers call `Config`, `gate.collect_check`, `gate.run_gate`, `changed.cmd_run_changed`, and `audit.run_audit`/`brief`; they do not reimplement gate decisions. A separate installer registry owns three target adapters, each of which merges only its own MCP entry and marker text and can remove only those exact entries.

**Tech Stack:** Python 3.11 standard library only (`argparse`, `json`, `pathlib`, `tomllib`, `io`, `contextlib`, `unittest`); newline-delimited JSON-RPC over stdin/stdout; UTF-8 text files.

## Global Constraints

- Keep `dependencies = []`; no MCP or TOML/JSON third-party package.
- MCP stdout contains only JSON-RPC responses; diagnostics and protocol errors go to stderr.
- Resolve the project root in this order: explicit `--root`, `ADONE_PROJECT_DIR`, current directory and its parents containing `adone.toml`.
- Never accept an arbitrary project path, shell command, script path, argv, or cwd inside an MCP tool call.
- `adone_run` and `adone_audit` are explicitly side-effecting in schemas and responses; local receipts are not cryptographic proof and CI remains the final trusted executor.
- Preserve existing `adone install --with-hooks`, `--hooks-only`, `--target cursor|dir`, and hook files byte-for-byte unless the new `--mcp` branch is selected.
- Installer writes must be idempotent, preserve unknown user fields, use exact markers/keys, and uninstall only content written by ActuallyDone.
- Cross-platform path handling must work on POSIX and Windows; all generated text is UTF-8.
- Every task follows TDD: failing test, focused test command, minimal implementation, passing test, then a focused commit.

---

### Task 1: Define MCP protocol and root/error primitives

**Files:**
- Create: `actuallydone/mcp.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Produces `SUPPORTED_PROTOCOL_VERSIONS`, `MCP_SERVER_INFO`, `resolve_mcp_root(explicit: str | None) -> Path`, `JsonRpcError`, `McpServer.handle(message: dict) -> dict | None`, and `serve_stdio(root: Path | None, input_stream, output_stream, error_stream) -> int`.
- `McpServer.handle` must return `None` for `notifications/initialized`, one response object for requests, and JSON-RPC errors with `-32600`, `-32601`, or `-32602` for invalid request, unknown method, or invalid params.

- [ ] **Step 1: Write the failing transcript tests**

```python
class TestMcpProtocol(unittest.TestCase):
    def test_initialize_echoes_supported_version_and_capabilities(self):
        response = McpServer(Path(self.root)).handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"}},
        })
        self.assertEqual(response["result"]["protocolVersion"], "2025-03-26")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_unsupported_version_is_invalid_params(self):
        response = McpServer(Path(self.root)).handle({
            "jsonrpc": "2.0", "id": 2, "method": "initialize",
            "params": {"protocolVersion": "1999-01-01"},
        })
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("supported", response["error"]["data"])

    def test_notification_has_no_response(self):
        self.assertIsNone(McpServer(Path(self.root)).handle({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
        }))

    def test_unknown_method_and_malformed_request_are_json_rpc_errors(self):
        unknown = McpServer(Path(self.root)).handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})
        malformed = McpServer(Path(self.root)).handle({"id": 4, "method": "ping"})
        self.assertEqual(unknown["error"]["code"], -32601)
        self.assertEqual(malformed["error"]["code"], -32600)

    def test_stdio_emits_one_json_line_and_logs_only_to_stderr(self):
        incoming = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n")
        outgoing, diagnostics = io.StringIO(), io.StringIO()
        self.assertEqual(serve_stdio(self.root, incoming, outgoing, diagnostics), 0)
        self.assertEqual(json.loads(outgoing.getvalue())["result"], {})
        self.assertNotIn("{", diagnostics.getvalue())
```

- [ ] **Step 2: Run `python -m unittest tests.test_mcp.TestMcpProtocol -v` and verify it fails because `actuallydone.mcp` is absent.**
- [ ] **Step 3: Implement newline JSON-RPC framing, `JsonRpcError`, version negotiation, `ping`, notification suppression, and root resolution. Read each input line as UTF-8 JSON, write compact UTF-8 JSON plus `\n`, catch parse/runtime errors into a response or stderr without terminating the loop.**
- [ ] **Step 4: Run the focused test again; expect all protocol tests to pass, then run `python -m unittest tests.test_mcp -v`.**
- [ ] **Step 5: Commit with `git add actuallydone/mcp.py tests/test_mcp.py && git commit -m "feat: add local MCP protocol transport"`.**

### Task 2: Add stable ActuallyDone MCP tool dispatcher

**Files:**
- Modify: `actuallydone/mcp.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Produces `TOOL_DEFINITIONS`, `McpServer.call_tool(name: str, arguments: dict) -> dict`, and `serialize_tool_result(data: object, text: str | None = None) -> dict`.
- Tools are named `adone_status`, `adone_check`, `adone_brief`, `adone_run`, and `adone_audit`.

- [ ] **Step 1: Add failing tests for `tools/list`, argument validation, and read-only/side-effect metadata.**

```python
    def test_tools_list_has_five_fixed_tools(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}})
        self.assertEqual({item["name"] for item in response["result"]["tools"]}, {
            "adone_status", "adone_check", "adone_brief", "adone_run", "adone_audit"})
        run = next(item for item in response["result"]["tools"] if item["name"] == "adone_run")
        self.assertIn("side effect", run["description"].lower())

    def test_unknown_tool_and_invalid_arguments_are_tool_errors(self):
        unknown = self.server.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                                      "params": {"name": "missing", "arguments": {}}})
        bad = self.server.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                  "params": {"name": "adone_run", "arguments": {"scope": "shell"}}})
        self.assertTrue(unknown["result"]["isError"])
        self.assertTrue(bad["result"]["isError"])
        self.assertIn("changed", json.dumps(bad, ensure_ascii=False))

    def test_status_is_structured_and_does_not_create_state(self):
        result = self.server.call_tool("adone_status", {})
        self.assertIn("structuredContent", result)
        self.assertFalse((self.root / ".adone").exists())
```

- [ ] **Step 2: Run `python -m unittest tests.test_mcp.TestMcpTools -v` and verify the new assertions fail.**
- [ ] **Step 3: Implement tool schemas and dispatch. `adone_status` calls `tree_hash`, `load_latest`, `collect_check(..., spotcheck=0)` and returns root/config/tree/receipt/evidence/problem fields. `adone_check` calls `collect_check` with validated `spotcheck >= 0` and `with_integrity`. `adone_brief` captures `brief(cfg)` text and returns it without changing files.**
- [ ] **Step 4: Implement side-effecting calls: `adone_run` accepts only `scope in {changed, full, affected}` and `skip` as a list of strings, calls `cmd_run_changed` for `changed` or `run_gate` for the other scopes, then reads the relevant receipt/partial output; `adone_audit` accepts only `mode in {review, rerun}` and non-negative `spotcheck`, calls `run_audit` with captured output, and reads the audit verdict. Never pass through arbitrary argv/cwd/projectPath.**
- [ ] **Step 5: Return both stable JSON in `structuredContent` and human-readable `content: [{"type": "text", "text": ...}]`; use `isError: true` for validation/config/gate failures while preserving `exit_code` and `problems`. Run `python -m unittest tests.test_mcp -v` and expect PASS.**
- [ ] **Step 6: Commit with `git add actuallydone/mcp.py tests/test_mcp.py && git commit -m "feat: expose gate and audit MCP tools"`.**

### Task 3: Wire `adone serve --mcp` into the CLI

**Files:**
- Modify: `actuallydone/cli.py`
- Modify: `actuallydone/__main__.py` if the entrypoint needs forwarding
- Test: `tests/test_mcp.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Produces a `serve` parser with required `--mcp` and optional `--root`; `cmd_serve(args) -> int` calls `serve_stdio` and returns its exit code.

- [ ] **Step 1: Add failing parser tests.**

```python
    def test_cli_parses_mcp_server(self):
        args = build_parser().parse_args(["serve", "--mcp", "--root", str(self.root)])
        self.assertEqual(args.cmd, "serve")
        self.assertTrue(args.mcp)
        self.assertEqual(Path(args.root), self.root)

    def test_cli_rejects_serve_without_mcp(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["serve"])
```

- [ ] **Step 2: Run `python -m unittest tests.test_mcp.TestMcpCli -v`; expect failure.**
- [ ] **Step 3: Add lazy `cmd_serve`, a `serve` subparser, and `--mcp`/`--root` options without changing the existing top-level/root or install parsers. Ensure `maybe_offer_upgrade` does not prompt for `serve`.**
- [ ] **Step 4: Run parser tests and a subprocess transcript (`python -m actuallydone serve --mcp --root <fixture>` with `ping`); expect exit code 0, valid JSON stdout, and empty protocol data on stderr.**
- [ ] **Step 5: Run `python -m unittest tests.test_core tests.test_mcp -v` and commit `feat: add adone serve mcp command`.**

### Task 4: Create the AgentTarget installer registry and config primitives

**Files:**
- Create: `actuallydone/agent_targets.py`
- Modify: `actuallydone/install.py`
- Modify: `actuallydone/cli.py`
- Test: `tests/test_mcp_install.py`

**Interfaces:**
- Produces `AgentTarget` protocol/base class with `id`, `display_name`, `docs_url`, `detect(location)`, `install(location, options)`, `uninstall(location)`, `print_config(location)`, and `describe_paths(location)`.
- Produces `McpInstallOptions(location: str, project_root: Path, command: list[str])`, `get_target(id: str)`, and `targets()` for `codex`, `cursor`, and `claude`.
- `install --mcp` and `uninstall --mcp` are separate branches; old install arguments retain their current choices and behavior.

- [ ] **Step 1: Add failing registry and CLI isolation tests.**

```python
class TestTargetRegistry(unittest.TestCase):
    def test_registry_contains_only_first_wave_targets(self):
        self.assertEqual([target.id for target in targets()], ["codex", "cursor", "claude"])

    def test_legacy_install_parser_still_rejects_unknown_old_target(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["install", "--target", "claude"])

    def test_mcp_install_parser_accepts_csv_targets_and_locations(self):
        args = build_parser().parse_args(["install", "--mcp", "--target", "codex,cursor",
                                          "--location", "local"])
        self.assertEqual(args.mcp_targets, "codex,cursor")
        self.assertEqual(args.location, "local")
```

- [ ] **Step 2: Run `python -m unittest tests.test_mcp_install.TestTargetRegistry -v`; verify failure.**
- [ ] **Step 3: Implement the registry, target ID normalization, `global|local` location validation, fixed command `adone serve --mcp`, and CLI branches. `--print-config` must not write files; `--target` without `--mcp` uses the legacy choices.**
- [ ] **Step 4: Run focused tests and assert `adone install --with-hooks --target cursor` still selects the original path.**
- [ ] **Step 5: Commit `feat: add MCP agent target registry`.**

### Task 5: Implement Codex and Cursor installers

**Files:**
- Create: `actuallydone/agent_targets_codex.py`
- Create: `actuallydone/agent_targets_cursor.py`
- Modify: `actuallydone/agent_targets.py`
- Test: `tests/test_mcp_install.py`

**Interfaces:**
- Codex adapter merges `[mcp_servers.adone]` into `~/.codex/config.toml` for `global` or `<root>/.codex/config.toml` for `local`; local installation updates `<root>/AGENTS.md` between `<!-- ACTUALLYDONE:MCP:BEGIN -->` and `<!-- ACTUALLYDONE:MCP:END -->`.
- Cursor adapter merges `mcpServers.adone` into `~/.cursor/mcp.json` or `<root>/.cursor/mcp.json`; local installation updates `<root>/.cursor/ACTUALLYDONE.md` marker content.
- Both adapters preserve unknown TOML/JSON keys, write UTF-8, produce stable output, and uninstall only the exact `adone` entry and marker block.

- [ ] **Step 1: Add failing tests for new files, merge, idempotence, foreign keys, marker replacement, print-only, and exact uninstall.**

```python
    def test_cursor_merge_preserves_foreign_server_and_is_idempotent(self):
        path = self.root / ".cursor" / "mcp.json"
        self.write_json(path, {"mcpServers": {"other": {"command": "other"}}, "custom": True})
        target = get_target("cursor")
        first = target.install(McpInstallOptions("local", self.root, command=["adone", "serve", "--mcp"]))
        before = path.read_text(encoding="utf-8")
        second = target.install(McpInstallOptions("local", self.root, command=["adone", "serve", "--mcp"]))
        self.assertEqual(first.written, 1)
        self.assertEqual(second.written, 0)
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertIn("other", before)

    def test_codex_uninstall_removes_only_our_table_and_marker(self):
        target = get_target("codex")
        target.install(McpInstallOptions("local", self.root, command=["adone", "serve", "--mcp"]))
        self.write_text(self.root / ".codex" / "config.toml",
                        '[mcp_servers.other]\ncommand = "other"\n\n[mcp_servers.adone]\ncommand = "adone"\n')
        target.uninstall(McpInstallOptions("local", self.root, command=[]))
        self.assertIn("mcp_servers.other", (self.root / ".codex" / "config.toml").read_text())
        self.assertNotIn("mcp_servers.adone", (self.root / ".codex" / "config.toml").read_text())
```

- [ ] **Step 2: Run `python -m unittest tests.test_mcp_install.TestCodexCursor -v`; verify failure.**
- [ ] **Step 3: Implement JSON merge with `json.loads`/`json.dumps` and a narrow TOML table renderer/parser that edits only the `[mcp_servers.adone]` table; reject malformed files with a diagnostic instead of overwriting them. Use a command array field plus `type = "stdio"` where the host format supports it.**
- [ ] **Step 4: Implement marker helpers that replace only the owned block, leave surrounding text untouched, and remove empty generated files/directories only when no user content remains.**
- [ ] **Step 5: Run focused tests, then `python -m unittest tests.test_mcp_install tests.test_configmerge -v`; commit `feat: install MCP config for Codex and Cursor`.**

### Task 6: Implement Claude Code installer and uninstall/report behavior

**Files:**
- Create: `actuallydone/agent_targets_claude.py`
- Modify: `actuallydone/agent_targets.py`
- Modify: `actuallydone/cli.py`
- Test: `tests/test_mcp_install.py`

**Interfaces:**
- Claude adapter merges `mcpServers.adone` into `~/.claude.json` for global or the project-level Claude config selected by `location=local`; local installation maintains the owned block in `<root>/CLAUDE.md`.
- CLI supports `adone install --mcp --target codex,cursor,claude [--location global|local] [--print-config ...]` and `adone uninstall --mcp --target ... [--location ...]`.

- [ ] **Step 1: Add failing tests for Claude JSON preservation, local marker, `--print-config`, multi-target output, and uninstall with foreign `mcpServers`.**
- [ ] **Step 2: Run `python -m unittest tests.test_mcp_install.TestClaudeAndCli -v`; expect failure.**
- [ ] **Step 3: Implement Claude path selection, JSON merge, marker maintenance, target iteration with per-target errors, and human-readable paths/actions. Do not modify `CLAUDE.md` for global installs.**
- [ ] **Step 4: Implement `print_config` as deterministic JSON/TOML snippets containing `command = "adone"`, `args = ["serve", "--mcp"]`, and location-specific paths without writing files.**
- [ ] **Step 5: Run `python -m unittest tests.test_mcp_install -v`; commit `feat: add Claude Code MCP installer and uninstall`.**

### Task 7: Documentation, compatibility tests, and packaging

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml` only if package data/entry points require it
- Test: `tests/test_mcp.py`
- Test: `tests/test_mcp_install.py`

**Interfaces:**
- Documents MCP trust/side-effect boundaries, three install commands, print/uninstall commands, root environment variable, and CI limitation.

- [ ] **Step 1: Add failing documentation assertions only where existing test conventions permit; otherwise record the exact command transcripts in the docs review checklist.**
- [ ] **Step 2: Add README sections with these commands and expected behavior:**

```text
adone serve --mcp
adone install --mcp --target codex,cursor,claude
adone install --mcp --target codex --location local
adone install --mcp --print-config codex
adone uninstall --mcp --target codex,cursor,claude
```

- [ ] **Step 3: Add a changelog entry stating MCP is an adapter and cannot make local receipts不可伪造; CI remains authoritative.**
- [ ] **Step 4: Run `python -m unittest` and `python -m compileall -q actuallydone`; expect no failures.**
- [ ] **Step 5: Commit `docs: document MCP server and agent adapters`.**

### Task 8: Final verification and delivery

**Files:**
- Modify only files required by earlier tasks

- [ ] **Step 1: Run the complete regression suite:** `python -m unittest -v`.
- [ ] **Step 2: Run a clean temporary-project transcript for `initialize`, `notifications/initialized`, `tools/list`, `adone_status`, invalid `adone_run`, and `ping`; assert every stdout line parses as JSON and no stderr line is emitted as protocol data.**
- [ ] **Step 3: Exercise install/uninstall twice for all three targets in both locations and compare snapshots for idempotence and foreign-field preservation.**
- [ ] **Step 4: Run `git diff --check`, inspect `git diff origin/main...HEAD`, and verify no arbitrary shell argument or changed legacy hook behavior exists.**
- [ ] **Step 5: Push the branch with `git push -u origin codex/mcp-server`; then search the upstream repository for its PR template before creating a PR from `ZpitQ:codex/mcp-server` to `iamharvey:main`.**

