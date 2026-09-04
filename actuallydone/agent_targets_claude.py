"""Claude Code MCP configuration target."""

from __future__ import annotations

from pathlib import Path

from .agent_targets import (AgentTarget, McpInstallOptions, TargetResult,
                            merge_marker, read_json_object, remove_marker,
                            ownership_path, read_owned_entry, target_command,
                            write_json, write_owned_entry, write_text)


class ClaudeTarget(AgentTarget):
    id = "claude"
    display_name = "Claude Code"
    docs_url = "https://docs.anthropic.com/en/docs/claude-code/mcp"

    def config_path(self, options: McpInstallOptions) -> Path:
        return ((options.home_dir / ".claude.json") if options.location == "global"
                else options.project_root / ".mcp.json")

    def marker_path(self, options: McpInstallOptions) -> Path:
        return options.project_root / "CLAUDE.md"

    def ownership_path(self, options: McpInstallOptions) -> Path:
        return ownership_path(self.config_path(options))

    def describe_paths(self, options: McpInstallOptions) -> tuple[Path, ...]:
        paths = [self.config_path(options), self.ownership_path(options)]
        if options.location == "local":
            paths.append(self.marker_path(options))
        return tuple(paths)

    def detect(self, options: McpInstallOptions) -> dict:
        managed = False
        error = None
        try:
            data = read_json_object(self.config_path(options))
            servers = data.get("mcpServers")
            owned = read_owned_entry(self.ownership_path(options))
            managed = isinstance(servers, dict) and owned is not None and servers.get("adone") == owned
            if options.location == "local" and self.marker_path(options).exists():
                marker = self.marker_path(options).read_text(encoding="utf-8")
                managed = managed or ("<!-- ACTUALLYDONE:MCP:BEGIN -->" in marker and
                                       "<!-- ACTUALLYDONE:MCP:END -->" in marker)
        except ValueError as exc:
            error = str(exc)
        out = {"id": self.id, "installed": managed,
               "paths": [str(path) for path in self.describe_paths(options)]}
        if error:
            out["error"] = error
        return out

    def install(self, options: McpInstallOptions) -> TargetResult:
        config = self.config_path(options)
        data = read_json_object(config)
        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            raise ValueError(f"JSON 配置 {config} 的 mcpServers 必须是对象")
        ours = target_command(options)
        if "adone" in servers and servers["adone"] != ours:
            return TargetResult(self.id, paths=(config,),
                                 message=f"保留已有 {config}，未覆盖其中的 adone",
                                 error=f"{config} 已有非 ActuallyDone 的 mcpServers.adone")
        changed = "adone" not in servers
        if changed:
            servers["adone"] = ours
            write_json(config, data, options)
            write_owned_entry(self.ownership_path(options), ours, options)
        paths = [config, self.ownership_path(options)] if changed else []
        if options.location == "local":
            marker = self.marker_path(options)
            old = marker.read_text(encoding="utf-8") if marker.exists() else ""
            body = ("# ActuallyDone MCP project guidance\n"
                    "Use adone_status/adone_check to inspect the gate; use adone_run only with its fixed scopes.\n")
            new, marker_changed = merge_marker(old, body)
            if marker_changed:
                write_text(marker, new, options)
                paths.append(marker)
            changed = changed or marker_changed
        return TargetResult(self.id, changed=changed, paths=tuple(paths),
                            message=f"{'写入' if changed else '已是最新'} {config}")

    def uninstall(self, options: McpInstallOptions) -> TargetResult:
        config = self.config_path(options)
        changed = False
        paths: list[Path] = []
        if config.exists():
            data = read_json_object(config)
            servers = data.get("mcpServers")
            owned = read_owned_entry(self.ownership_path(options))
            if isinstance(servers, dict) and owned is not None and servers.get("adone") == owned:
                del servers["adone"]
                changed = True
                if not options.dry_run:
                    write_json(config, data, options)
                paths.append(config)
        owned = read_owned_entry(self.ownership_path(options))
        if owned is not None:
            changed = True
            if not options.dry_run:
                self.ownership_path(options).unlink(missing_ok=True)
            paths.append(self.ownership_path(options))
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
        import json
        return json.dumps({"mcpServers": {"adone": target_command(options)}},
                          ensure_ascii=False, indent=2)


__all__ = ["ClaudeTarget"]

