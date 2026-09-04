"""独立的本地 MCP stdio 适配器。

这一层只负责 JSON-RPC/MCP 协议、参数边界和结果序列化；门禁与审计判定仍由
ActuallyDone 现有核心模块完成。stdout 是协议通道，诊断只能写 stderr。
"""

from __future__ import annotations

import json
import io
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from threading import Lock
from typing import Any, Callable, TextIO

from . import __version__
from .config import CONFIG_NAME, find_root

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MCP_SERVER_INFO = {"name": "actuallydone", "version": __version__}
_MISSING = object()

TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "adone_status",
        "description": "Read the current ActuallyDone gate status without running tests.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "adone_check",
        "description": "Check the existing ActuallyDone receipt and gate policy without running the gate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spotcheck": {"type": "integer", "minimum": 0, "default": 0},
                "with_integrity": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "adone_brief",
        "description": "Read the independent-review brief for this project.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "adone_run",
        "description": "Side effect: run the fixed ActuallyDone gate scope and write its normal receipt or partial result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["changed", "full", "affected"]},
                "skip": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["scope"],
            "additionalProperties": False,
        },
    },
    {
        "name": "adone_audit",
        "description": "Side effect: perform the independent audit and write an audit verdict without replacing the implementation receipt.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["review", "rerun"], "default": "review"},
                "spotcheck": {"type": "integer", "minimum": 0, "default": 2},
            },
            "additionalProperties": False,
        },
    },
)


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            out["data"] = self.data
        return out


def resolve_mcp_root(explicit: str | None = None) -> Path:
    """按 CLI 参数、环境变量、当前目录向上的顺序选择项目根。"""
    raw = explicit or os.environ.get("ADONE_PROJECT_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (find_root() or Path.cwd()).resolve()


def _response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, err: JsonRpcError) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": err.as_dict()}


class _ProgressStream(io.StringIO):
    """Capture command output while forwarding non-empty chunks as progress."""

    def __init__(self, progress: Callable[[str], None]) -> None:
        super().__init__()
        self._progress = progress

    def write(self, value: str) -> int:
        written = super().write(value)
        message = value.strip()
        if message:
            self._progress(message)
        return written


class McpServer:
    def __init__(self, root: Path,
                 progress_callback: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.root = root.expanduser().resolve()
        self._progress_callback = progress_callback
        self._progress_token: str | int | float | None = None
        self._progress_count = 0

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise_error = JsonRpcError(-32600, "Invalid Request")
            request_id = message.get("id") if isinstance(message, dict) else None
            return _error(request_id, raise_error)

        method = message.get("method")
        if not isinstance(method, str):
            return _error(message.get("id"), JsonRpcError(-32600, "Invalid Request"))
        request_id = message.get("id", _MISSING)
        params = message.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            err = JsonRpcError(-32602, "Invalid params", "params must be an object")
            return None if request_id is _MISSING else _error(request_id, err)

        try:
            result = self._dispatch(method, params)
        except JsonRpcError as exc:
            return None if request_id is _MISSING else _error(request_id, exc)
        except Exception as exc:  # pragma: no cover - guarded for protocol uptime
            err = JsonRpcError(-32603, "Internal error", str(exc))
            return None if request_id is _MISSING else _error(request_id, err)
        if request_id is _MISSING:
            return None
        return _response(request_id, result)

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return self._initialize(params)
        if method == "notifications/initialized":
            return {}
        if method == "tools/list":
            return {"tools": self.tool_definitions()}
        if method == "tools/call":
            return self._call_tool_request(params)
        if method == "ping":
            return {}
        raise JsonRpcError(-32601, "Method not found", {"method": method})

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion") or SUPPORTED_PROTOCOL_VERSIONS[0]
        if requested not in SUPPORTED_PROTOCOL_VERSIONS:
            raise JsonRpcError(
                -32602,
                "Unsupported protocol version",
                {"requested": requested, "supported": list(SUPPORTED_PROTOCOL_VERSIONS)},
            )
        return {
            "protocolVersion": requested,
            "capabilities": {"tools": {}},
            "serverInfo": dict(MCP_SERVER_INFO),
            "instructions": "Use ActuallyDone tools to inspect and run the project gate.",
        }

    def tool_definitions(self) -> list[dict[str, Any]]:
        return [dict(item) for item in TOOL_DEFINITIONS]

    def _call_tool_request(self, params: dict[str, Any]) -> dict[str, Any]:
        unknown = set(params) - {"name", "arguments", "_meta"}
        if unknown:
            raise JsonRpcError(-32602, "Invalid params",
                               f"unknown tools/call parameters: {', '.join(sorted(unknown))}")
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise JsonRpcError(-32602, "Invalid params", "tools/call requires a tool name")
        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(-32602, "Invalid params", "tool arguments must be an object")
        meta = params.get("_meta", {})
        if meta is None:
            meta = {}
        if not isinstance(meta, dict):
            raise JsonRpcError(-32602, "Invalid params", "tools/call _meta must be an object")
        progress_token = meta.get("progressToken")
        if (isinstance(progress_token, bool)
                or not isinstance(progress_token, (str, int, float, type(None)))):
            raise JsonRpcError(-32602, "Invalid params",
                               "_meta.progressToken must be a string or number")
        return self.call_tool(name, arguments, progress_token=progress_token)

    def call_tool(self, name: str, arguments: dict[str, Any], *,
                  progress_token: str | int | float | None = None) -> dict[str, Any]:
        handlers = {
            "adone_status": self._status,
            "adone_check": self._check,
            "adone_brief": self._brief,
            "adone_run": self._run,
            "adone_audit": self._audit,
        }
        handler = handlers.get(name)
        if handler is None:
            return serialize_tool_result(
                {"error": "unknown_tool", "message": f"Unknown tool: {name}"},
                f"Unknown tool: {name}", is_error=True, exit_code=2,
            )
        previous_token = self._progress_token
        previous_count = self._progress_count
        self._progress_token = progress_token
        self._progress_count = 0
        try:
            return handler(arguments)
        except Exception as exc:  # keep tool failures inside the MCP result envelope
            return serialize_tool_result(
                {"error": "internal_error", "message": str(exc)},
                f"ActuallyDone tool failed: {exc}", is_error=True, exit_code=2,
            )
        finally:
            self._progress_token = previous_token
            self._progress_count = previous_count

    def _emit_progress(self, message: str) -> None:
        if self._progress_callback is None or self._progress_token is None:
            return
        self._progress_count += 1
        self._progress_callback({
            "progressToken": self._progress_token,
            "progress": self._progress_count,
            "message": message,
        })

    def _config(self):
        from .config import Config, ConfigError
        try:
            return Config.load(self.root), None
        except ConfigError as exc:
            return None, serialize_tool_result(
                {"error": "config_error", "message": str(exc),
                 "project_root": str(self.root)},
                str(exc), is_error=True, exit_code=2,
            )

    def _status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments:
            return _invalid_arguments("adone_status", arguments)
        cfg, error = self._config()
        if error:
            return error
        from .gate import collect_check, load_latest
        from .integrity import integrity_problems
        from .policy import policy_problems
        receipt = load_latest(cfg)
        got = collect_check(cfg, with_integrity=True, spotcheck=0, clear_dirty=False)
        policy_bad, _ = policy_problems(cfg, receipt)
        integrity_bad = integrity_problems(cfg, receipt)
        receipt_tree = (receipt or {}).get("tree") or {}
        if receipt is None:
            freshness = "missing"
        elif receipt_tree.get("hash") == got["tree_hash"]:
            freshness = "fresh"
        else:
            freshness = "stale"
        data = {
            "project_root": str(cfg.root),
            "config_path": str(cfg.path or (cfg.root / CONFIG_NAME)),
            "tree": {"hash": got["tree_hash"], "file_count": got["tree_files"]},
            "receipt": {
                "id": got["receipt_id"],
                "self_hash": (receipt or {}).get("self_hash"),
                "tree_hash": receipt_tree.get("hash"),
                "created_at": (receipt or {}).get("created_at"),
                "ok": (receipt or {}).get("ok"),
                "complete": (receipt or {}).get("complete"),
            },
            "freshness": freshness,
            "ok": got["ok"] and not cfg.problems(),
            "problems": [*cfg.problems(), *got["problems"]],
            "policy_problems": policy_bad,
            "integrity_problems": integrity_bad,
            "details": got["details"],
            "evidence": got["evidence"],
            "evidence_line": got["evidence_line"],
        }
        return serialize_tool_result(data, _summary_text(data))

    def _check(self, arguments: dict[str, Any]) -> dict[str, Any]:
        allowed = {"spotcheck", "with_integrity"}
        unknown = set(arguments) - allowed
        if unknown:
            return _invalid_arguments("adone_check", arguments,
                                      f"unknown arguments: {', '.join(sorted(unknown))}")
        spotcheck = arguments.get("spotcheck", 0)
        with_integrity = arguments.get("with_integrity", True)
        if isinstance(spotcheck, bool) or not isinstance(spotcheck, int) or spotcheck < 0:
            return _invalid_arguments("adone_check", arguments,
                                      "spotcheck must be a non-negative integer")
        if not isinstance(with_integrity, bool):
            return _invalid_arguments("adone_check", arguments,
                                      "with_integrity must be boolean")
        cfg, error = self._config()
        if error:
            return error
        from .gate import collect_check
        got = collect_check(cfg, with_integrity=with_integrity, spotcheck=spotcheck,
                            clear_dirty=False)
        data = {
            "ok": got["ok"], "problems": got["problems"], "details": got["details"],
            "receipt_id": got["receipt_id"], "tree_hash": got["tree_hash"],
            "tree_files": got["tree_files"], "evidence": got["evidence"],
            "evidence_line": got["evidence_line"], "spotcheck": got["spotcheck"],
            "exit_code": 0 if got["ok"] else 1,
        }
        return serialize_tool_result(data, _summary_text(data), is_error=not got["ok"],
                                     exit_code=data["exit_code"])

    def _brief(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments:
            return _invalid_arguments("adone_brief", arguments)
        cfg, error = self._config()
        if error:
            return error
        from .audit import brief
        out = io.StringIO()
        with redirect_stdout(out):
            code = brief(cfg)
        data = {"text": out.getvalue(), "exit_code": code}
        return serialize_tool_result(data, data["text"], exit_code=code)

    def _run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        allowed = {"scope", "skip"}
        unknown = set(arguments) - allowed
        if unknown:
            return _invalid_arguments("adone_run", arguments,
                                      f"unknown arguments: {', '.join(sorted(unknown))}")
        scope = arguments.get("scope")
        if scope not in {"changed", "full", "affected"}:
            return _invalid_arguments("adone_run", arguments,
                                      "scope must be one of changed, full, affected")
        skip = arguments.get("skip", [])
        if not isinstance(skip, list) or any(not isinstance(item, str) for item in skip):
            return _invalid_arguments("adone_run", arguments,
                                      "skip must be an array of step names")
        if scope == "changed" and skip:
            return _invalid_arguments("adone_run", arguments,
                                      "skip is not supported with changed scope")
        cfg, error = self._config()
        if error:
            return error
        stdout = _ProgressStream(self._emit_progress)
        stderr = _ProgressStream(self._emit_progress)
        self._emit_progress(f"Starting ActuallyDone {scope} gate")
        with redirect_stdout(stdout), redirect_stderr(stderr):
            if scope == "changed":
                from .changed import cmd_run_changed
                code = cmd_run_changed(cfg)
            else:
                from .gate import run_gate
                code = run_gate(cfg, skip=skip, affected=scope == "affected")
        self._emit_progress(f"Finished ActuallyDone {scope} gate (exit code {code})")
        from .gate import load_latest
        receipt = load_latest(cfg) if scope != "changed" else None
        partial = None
        if cfg.partial.is_file():
            try:
                partial = json.loads(cfg.partial.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                partial = None
        data = {
            "scope": scope, "ok": code == 0, "exit_code": code,
            "stdout": stdout.getvalue(), "stderr": stderr.getvalue(),
            "receipt": receipt, "partial": partial,
        }
        return serialize_tool_result(data, _summary_text(data), is_error=code != 0,
                                     exit_code=code)

    def _audit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        allowed = {"mode", "spotcheck"}
        unknown = set(arguments) - allowed
        if unknown:
            return _invalid_arguments("adone_audit", arguments,
                                      f"unknown arguments: {', '.join(sorted(unknown))}")
        mode = arguments.get("mode", "review")
        spotcheck = arguments.get("spotcheck", 2)
        if mode not in {"review", "rerun"}:
            return _invalid_arguments("adone_audit", arguments,
                                      "mode must be review or rerun")
        if isinstance(spotcheck, bool) or not isinstance(spotcheck, int) or spotcheck < 0:
            return _invalid_arguments("adone_audit", arguments,
                                      "spotcheck must be a non-negative integer")
        cfg, error = self._config()
        if error:
            return error
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            from .audit import run_audit
            code = run_audit(cfg, spotcheck=spotcheck, rerun=mode == "rerun")
        verdict = None
        if cfg.latest_audit.is_file():
            try:
                verdict = json.loads(cfg.latest_audit.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                verdict = None
        data = {"mode": mode, "ok": code == 0, "exit_code": code,
                "verdict": verdict, "audit_path": str(cfg.latest_audit),
                "report_path": str(cfg.audit_report),
                "stdout": out.getvalue(), "stderr": err.getvalue()}
        return serialize_tool_result(data, _summary_text(data), is_error=code != 0,
                                     exit_code=code)


def serialize_tool_result(data: Any, text: str | None = None, *,
                          is_error: bool = False, exit_code: int | None = None) -> dict[str, Any]:
    structured = data if isinstance(data, dict) else {"value": data}
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": text if text is not None else
                     json.dumps(structured, ensure_ascii=False, indent=2)}],
        "structuredContent": structured,
        "isError": bool(is_error),
    }
    if exit_code is not None:
        result["structuredContent"].setdefault("exit_code", exit_code)
    return result


def _invalid_arguments(tool: str, arguments: dict[str, Any], message: str | None = None) -> dict[str, Any]:
    detail = message or f"invalid arguments for {tool}"
    return serialize_tool_result({"error": "invalid_arguments", "tool": tool,
                                  "message": detail, "arguments": arguments},
                                 detail, is_error=True, exit_code=2)


def _summary_text(data: dict[str, Any]) -> str:
    if "problems" in data and data["problems"]:
        return "ActuallyDone gate has problems: " + "; ".join(map(str, data["problems"]))
    if "ok" in data:
        return "ActuallyDone: " + ("ok" if data["ok"] else "not ok")
    if "text" in data:
        return data["text"]
    return json.dumps(data, ensure_ascii=False, indent=2)


def _write_message(stream: TextIO, message: dict[str, Any]) -> None:
    stream.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    stream.flush()


def serve_stdio(root: Path | None = None, input_stream: TextIO | None = None,
                output_stream: TextIO | None = None,
                error_stream: TextIO | None = None) -> int:
    """运行一条请求一行的 MCP stdio 服务，协议响应只写 output_stream。"""
    incoming = input_stream or sys.stdin
    outgoing = output_stream or sys.stdout
    diagnostics = error_stream or sys.stderr
    write_lock = Lock()

    def emit_progress(params: dict[str, Any]) -> None:
        with write_lock:
            _write_message(outgoing, {
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": params,
            })

    server = McpServer(root or resolve_mcp_root(), progress_callback=emit_progress)
    for line in incoming:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = server.handle(message)
        except json.JSONDecodeError as exc:
            response = _error(None, JsonRpcError(-32700, "Parse error", str(exc)))
        except Exception as exc:  # keep the long-lived stdio process alive
            diagnostics.write(f"MCP request failed: {exc}\n")
            diagnostics.flush()
            response = _error(None, JsonRpcError(-32603, "Internal error", str(exc)))
        if response is not None:
            _write_message(outgoing, response)
    return 0


__all__ = [
    "MCP_SERVER_INFO",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "JsonRpcError",
    "McpServer",
    "resolve_mcp_root",
    "serve_stdio",
]

