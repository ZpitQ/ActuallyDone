"""MCP installer targets shared by Codex, Cursor, and Claude Code."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

MCP_BEGIN = "<!-- ACTUALLYDONE:MCP:BEGIN -->"
MCP_END = "<!-- ACTUALLYDONE:MCP:END -->"
DEFAULT_COMMAND = ("adone", "serve", "--mcp")


@dataclass(frozen=True)
class McpInstallOptions:
    location: str
    project_root: Path
    command: Sequence[str] = field(default_factory=lambda: DEFAULT_COMMAND)
    home: Path | None = None
    dry_run: bool = False

    def __post_init__(self) -> None:
        if self.location not in {"global", "local"}:
            raise ValueError("location must be global or local")
        object.__setattr__(self, "project_root", Path(self.project_root).expanduser().resolve())
        object.__setattr__(self, "command", tuple(str(item) for item in self.command))
        if self.home is not None:
            object.__setattr__(self, "home", Path(self.home).expanduser().resolve())

    @property
    def home_dir(self) -> Path:
        return self.home or Path.home()


@dataclass(frozen=True)
class TargetResult:
    target: str
    changed: bool = False
    paths: tuple[Path, ...] = ()
    message: str = ""
    error: str | None = None

    @property
    def written(self) -> int:
        return 1 if self.changed else 0


class AgentTarget:
    id = ""
    display_name = ""
    docs_url = ""

    def detect(self, options: McpInstallOptions) -> dict[str, Any]:
        paths = self.describe_paths(options)
        return {
            "id": self.id,
            "installed": any(path.is_file() for path in paths),
            "paths": [str(path) for path in paths],
        }

    def install(self, options: McpInstallOptions) -> TargetResult:
        raise NotImplementedError

    def uninstall(self, options: McpInstallOptions) -> TargetResult:
        raise NotImplementedError

    def print_config(self, options: McpInstallOptions) -> str:
        raise NotImplementedError

    def describe_paths(self, options: McpInstallOptions) -> tuple[Path, ...]:
        raise NotImplementedError


def target_command(options: McpInstallOptions) -> dict[str, Any]:
    command = list(options.command)
    if not command:
        command = list(DEFAULT_COMMAND)
    return {"command": command[0], "args": command[1:]}


def merge_marker(text: str, body: str) -> tuple[str, bool]:
    """Replace our marker block, or append it, leaving all other text intact."""
    block = f"{MCP_BEGIN}\n{body.rstrip()}\n{MCP_END}"
    start, end = text.find(MCP_BEGIN), text.find(MCP_END)
    if start >= 0 and end >= start:
        end += len(MCP_END)
        updated = text[:start] + block + text[end:]
    elif start >= 0 or end >= 0:
        raise ValueError("ActuallyDone MCP marker is incomplete")
    else:
        prefix = "" if not text or text.endswith("\n") else "\n"
        updated = text + prefix + block + "\n"
    return updated, updated != text


def remove_marker(text: str) -> tuple[str, bool]:
    start, end = text.find(MCP_BEGIN), text.find(MCP_END)
    if start < 0 and end < 0:
        return text, False
    if start < 0 or end < start:
        raise ValueError("ActuallyDone MCP marker is incomplete")
    end += len(MCP_END)
    if end < len(text) and text[end] == "\n":
        end += 1
    updated = text[:start].rstrip("\n") + ("\n" if text[:start].rstrip("\n") else "") + text[end:]
    return updated, updated != text


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON 配置 {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"JSON 配置 {path} 的根必须是对象")
    return raw


def write_text(path: Path, text: str, options: McpInstallOptions) -> None:
    if options.dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path: Path, data: dict[str, Any], options: McpInstallOptions) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", options)


def ownership_path(config: Path) -> Path:
    return config.with_name(f".{config.name}.actuallydone")


def read_owned_entry(path: Path) -> dict[str, Any] | None:
    try:
        data = read_json_object(path)
    except ValueError:
        return None
    entry = data.get("entry")
    return entry if isinstance(entry, dict) else None


def write_owned_entry(path: Path, entry: dict[str, Any], options: McpInstallOptions) -> None:
    write_json(path, {"entry": entry}, options)


def _target_map() -> dict[str, AgentTarget]:
    from .agent_targets_claude import ClaudeTarget
    from .agent_targets_codex import CodexTarget
    from .agent_targets_cursor import CursorTarget
    return {target.id: target for target in (CodexTarget(), CursorTarget(), ClaudeTarget())}


def targets() -> list[AgentTarget]:
    return list(_target_map().values())


def get_target(target_id: str) -> AgentTarget:
    key = target_id.strip().lower()
    target = _target_map().get(key)
    if target is None:
        raise ValueError(f"不认识的 MCP target：{target_id}（可选 codex、cursor、claude）")
    return target


def parse_targets(value: str | None) -> list[str]:
    raw = value or ",".join(target.id for target in targets())
    ids = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not ids:
        raise ValueError("至少指定一个 MCP target")
    seen: set[str] = set()
    out: list[str] = []
    for item in ids:
        get_target(item)
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out


def run_target_action(target_ids: str | None, options: McpInstallOptions,
                      *, uninstall: bool = False) -> tuple[int, list[TargetResult]]:
    results: list[TargetResult] = []
    try:
        ids = parse_targets(target_ids)
    except ValueError as exc:
        return 2, [TargetResult("", error=str(exc), message=str(exc))]
    for target_id in ids:
        target = get_target(target_id)
        try:
            result = target.uninstall(options) if uninstall else target.install(options)
        except (OSError, ValueError) as exc:
            result = TargetResult(target_id, error=str(exc), message=str(exc))
        results.append(result)
    return (0 if all(not result.error for result in results) else 2), results


def print_target_configs(target_ids: str | None, options: McpInstallOptions) -> tuple[int, str]:
    try:
        ids = parse_targets(target_ids)
    except ValueError as exc:
        return 2, str(exc)
    chunks = []
    for target_id in ids:
        target = get_target(target_id)
        chunks.append(f"[{target.display_name}]\n{target.print_config(options)}")
    return 0, "\n\n".join(chunks) + "\n"


__all__ = [
    "AgentTarget", "DEFAULT_COMMAND", "MCP_BEGIN", "MCP_END", "McpInstallOptions",
    "TargetResult", "get_target", "ownership_path", "parse_targets",
    "print_target_configs", "read_owned_entry", "run_target_action", "targets",
    "write_owned_entry",
]

