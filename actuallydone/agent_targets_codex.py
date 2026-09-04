"""Codex MCP configuration target."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from .agent_targets import (AgentTarget, MCP_BEGIN, MCP_END, McpInstallOptions,
                            TargetResult, merge_marker, remove_marker,
                            target_command, write_text)

CODEX_MCP_BEGIN = "# ACTUALLYDONE:MCP:BEGIN"
CODEX_MCP_END = "# ACTUALLYDONE:MCP:END"


def _toml_block(options: McpInstallOptions) -> str:
    entry = target_command(options)
    args = json.dumps(entry["args"], ensure_ascii=False)
    return (f"{CODEX_MCP_BEGIN}\n[mcp_servers.adone]\n"
            f"command = {json.dumps(entry['command'], ensure_ascii=False)}\n"
            f"args = {args}\n{CODEX_MCP_END}")


def _replace_owned(text: str, replacement: str) -> tuple[str, bool]:
    start, end = text.find(CODEX_MCP_BEGIN), text.find(CODEX_MCP_END)
    if start < 0 and end < 0:
        if not replacement:
            return text, False
        prefix = "" if not text or text.endswith("\n") else "\n"
        return text + prefix + replacement + "\n", True
    if start < 0 or end < start:
        raise ValueError("ActuallyDone MCP marker is incomplete")
    end += len(CODEX_MCP_END)
    return text[:start] + replacement + text[end:], text[:start] + replacement + text[end:] != text


def _has_adone_table(text: str) -> bool:
    return any(re.match(r"^\[\[?mcp_servers\.adone(?:\]|\.)", line.strip())
               for line in text.splitlines())


class CodexTarget(AgentTarget):
    id = "codex"
    display_name = "Codex CLI"
    docs_url = "https://developers.openai.com/codex/mcp"

    def config_path(self, options: McpInstallOptions) -> Path:
        return ((options.home_dir / ".codex" / "config.toml") if options.location == "global"
                else options.project_root / ".codex" / "config.toml")

    def marker_path(self, options: McpInstallOptions) -> Path:
        return options.project_root / "AGENTS.md"

    def describe_paths(self, options: McpInstallOptions) -> tuple[Path, ...]:
        paths = [self.config_path(options)]
        if options.location == "local":
            paths.append(self.marker_path(options))
        return tuple(paths)

    def detect(self, options: McpInstallOptions) -> dict:
        config = self.config_path(options)
        managed = False
        error = None
        if config.exists():
            try:
                text = config.read_text(encoding="utf-8")
                managed = (CODEX_MCP_BEGIN in text and CODEX_MCP_END in text
                           and _has_adone_table(text))
            except (OSError, UnicodeDecodeError) as exc:
                error = str(exc)
        if options.location == "local" and self.marker_path(options).exists():
            try:
                marker = self.marker_path(options).read_text(encoding="utf-8")
                managed = managed or (MCP_BEGIN in marker and MCP_END in marker)
            except (OSError, UnicodeDecodeError) as exc:
                error = str(exc)
        out = {"id": self.id, "installed": managed,
               "paths": [str(path) for path in self.describe_paths(options)]}
        if error:
            out["error"] = error
        return out

    def install(self, options: McpInstallOptions) -> TargetResult:
        config = self.config_path(options)
        old = config.read_text(encoding="utf-8") if config.exists() else ""
        if old:
            try:
                tomllib.loads(old)
            except tomllib.TOMLDecodeError as exc:
                raise ValueError(f"无法读取 TOML 配置 {config}: {exc}") from exc
        if _has_adone_table(old) and CODEX_MCP_BEGIN not in old:
            return TargetResult(self.id, message=f"保留已有 {config}，未覆盖其中的 mcp_servers.adone",
                                 paths=(config,), error=f"{config} 已有非 ActuallyDone 的 mcp_servers.adone")
        new, changed = _replace_owned(old, _toml_block(options))
        if not changed and not old:
            new, changed = _toml_block(options) + "\n", True
        if changed:
            write_text(config, new, options)

        paths = [config] if changed else []
        if options.location == "local":
            marker = self.marker_path(options)
            marker_old = marker.read_text(encoding="utf-8") if marker.exists() else ""
            body = ("# ActuallyDone MCP project guidance\n"
                    "Use adone_status/adone_check to inspect the gate; use adone_run only with its fixed scopes.\n")
            marker_new, marker_changed = merge_marker(marker_old, body)
            if marker_changed:
                write_text(marker, marker_new, options)
                paths.append(marker)
            changed = changed or marker_changed
        message = f"{'写入' if changed else '已是最新'} {config}"
        if options.location == "local":
            message += "；请先信任该项目，否则 Codex 可能不会加载项目级 MCP 配置"
        return TargetResult(self.id, changed=changed, paths=tuple(paths), message=message)

    def uninstall(self, options: McpInstallOptions) -> TargetResult:
        config = self.config_path(options)
        changed = False
        paths: list[Path] = []
        if config.exists():
            old = config.read_text(encoding="utf-8")
            new, owned = _replace_owned(old, "")
            if owned:
                changed = True
                if not options.dry_run:
                    if new.strip():
                        write_text(config, new, options)
                    else:
                        config.unlink(missing_ok=True)
                paths.append(config)
        if options.location == "local":
            marker = self.marker_path(options)
            if marker.exists():
                old = marker.read_text(encoding="utf-8")
                new, owned = remove_marker(old)
                if owned:
                    changed = True
                    if not options.dry_run:
                        if new.strip():
                            write_text(marker, new, options)
                        else:
                            marker.unlink(missing_ok=True)
                    paths.append(marker)
        return TargetResult(self.id, changed=changed, paths=tuple(paths),
                            message=f"{'移除' if changed else '未发现'} {self.display_name} 的 ActuallyDone 配置")

    def print_config(self, options: McpInstallOptions) -> str:
        return _toml_block(options) + f"\n# path: {self.config_path(options)}"


__all__ = ["CodexTarget"]

