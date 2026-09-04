# MCP 安装与使用指南

这份指南说明如何把 ActuallyDone 的本地 MCP 服务接入 Codex CLI、Cursor 和 Claude
Code。服务复用项目已有的门禁、回执和审计逻辑；安装器只负责写入对应宿主的 MCP 配置。

## 前置条件

- Python 3.11 或更高版本。
- 已安装 `adone`，并且 `adone --version` 能正常输出版本。
- 项目根目录已有 `adone.toml`。没有配置时，先在项目目录执行 `adone init`。

推荐使用 `pipx` 安装：

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install git+https://github.com/iamharvey/ActuallyDone.git
adone --version
```

Windows PowerShell 可以把 `python3` 换成 `py -3`。如果使用源码目录验证：

```bash
python -m pip install -e /path/to/ActuallyDone
adone --version
```

如果终端提示找不到 `adone`，重开终端并确认 pipx 的命令目录已加入 PATH。Linux/macOS
通常是 `~/.local/bin`，Windows 通常是 `%USERPROFILE%\\.local\\bin`。

## 一分钟接入

在项目根目录执行以下命令，会为三个宿主写入全局配置：

```bash
adone install --mcp --target codex,cursor,claude
```

如果只想让当前项目使用 MCP，执行项目级安装：

```bash
adone --root /path/to/project install --mcp \
  --target codex,cursor,claude --location local
```

Windows PowerShell 可以使用项目的绝对路径，例如：

```powershell
adone --root C:\\work\\my-project install --mcp `
  --target codex,cursor,claude --location local
```

安装完成后重启宿主或重新打开会话，使其重新读取 MCP 配置。项目级 Codex 配置还要求
先信任该项目，否则 Codex 可能不会加载 `.codex/config.toml`。

## 配置位置

`--location` 不写时默认为 `global`。项目级安装的项目根由 `--root` 指定；省略时，
ActuallyDone 会按 `ADONE_PROJECT_DIR`、当前目录及其父目录查找 `adone.toml`。

| 宿主 | 全局 MCP 配置 | 项目级 MCP 配置 | 项目级说明文件 |
| --- | --- | --- | --- |
| Codex CLI | `~/.codex/config.toml` | `<项目>/.codex/config.toml` | `<项目>/AGENTS.md` |
| Cursor | `~/.cursor/mcp.json` | `<项目>/.cursor/mcp.json` | `<项目>/.cursor/ACTUALLYDONE.md` |
| Claude Code | `~/.claude.json` | `<项目>/.mcp.json` | `<项目>/CLAUDE.md` |

Cursor 和 Claude Code 的 JSON 配置旁边会有一个隐藏的来源记录文件，用来判断
`mcpServers.adone` 是否由 ActuallyDone 写入。不要手工删除这个文件，否则卸载器无法
确认条目的归属。Codex 配置使用注释标记和 `[mcp_servers.adone]` 表。

MCP 安装不会安装或重写原有技能和 hooks。需要技能或 hooks 时，另行执行：

```bash
adone install --with-hooks
```

## 查看配置而不写文件

使用 `--print-config` 可以预览一个或多个宿主的配置片段：

```bash
adone install --mcp --print-config codex
adone install --mcp --print-config cursor,claude
```

该命令只打印配置，不创建目录、配置文件或来源记录。需要确认当前项目路径时，先运行：

```bash
adone --root /path/to/project install --mcp --print-config codex
```

## MCP 服务如何运行

安装器写入的固定启动命令是：

```text
adone serve --mcp
```

也可以手动启动并指定项目根：

```bash
adone serve --mcp --root /path/to/project
```

服务是长驻的 stdio JSON-RPC 进程：

- MCP 消息从 stdin 读取并写到 stdout。
- 诊断日志写到 stderr，不混入协议输出。
- 未指定 `--root` 时，使用 `ADONE_PROJECT_DIR` 或从当前目录向上查找 `adone.toml`。
- 工具调用不接受 `projectPath`、`cwd`、任意 Shell 命令、脚本路径或自定义 argv。

宿主通常会自动启动这个进程；手动启动主要用于排查路径和 PATH 问题。启动后可先用
宿主的 MCP 工具列表确认是否看到以下五个工具。

## 可用工具

| 工具 | 类型 | 参数 | 用途 |
| --- | --- | --- | --- |
| `adone_status` | 只读 | 无 | 读取当前树哈希、最新回执、新鲜度、问题和证据强度 |
| `adone_check` | 只读 | `spotcheck`、`with_integrity` | 校验现有回执和门禁判据；不会运行完整门禁 |
| `adone_brief` | 只读 | 无 | 返回复核者应读取的判据、契约、基线和限制 |
| `adone_run` | 有副作用 | `scope`、`skip` | 按固定范围运行门禁并写入正常回执或部分结果 |
| `adone_audit` | 有副作用 | `mode`、`spotcheck` | 运行审计并写入审计结论，不覆盖实现者回执 |

参数边界：

- `adone_check.spotcheck` 是大于等于 0 的整数，默认 `0`；`with_integrity` 默认 `true`。
- `adone_run.scope` 只能是 `changed`、`full` 或 `affected`；`skip` 是步骤名称数组，
  `changed` 范围不支持 `skip`。
- `adone_audit.mode` 只能是 `review` 或 `rerun`；`spotcheck` 是大于等于 0 的整数，
  默认 `2`。

只读工具不会因为读取状态而清理 dirty 标记或创建新的门禁回执。`adone_run` 和
`adone_audit` 会写入 `.adone` 下的本地产物，宿主应在调用前按自己的权限策略提示用户。

## 重复安装、冲突与卸载

重复执行安装命令是幂等的：已有正确配置时不会叠加内容。安装器还会保留未知的 JSON/TOML
字段、其他 MCP server 以及项目说明文件中标记段以外的文字。

如果某个宿主已经存在不是 ActuallyDone 写入的 `adone` 条目，安装器会报告冲突并保留
原内容，不会覆盖。即使内容恰好相同，没有来源记录也不会被接管或删除。

先预览将要执行的卸载操作：

```bash
adone --root /path/to/project uninstall --mcp \
  --target codex,cursor,claude --location local --dry-run
```

确认后卸载项目级配置：

```bash
adone --root /path/to/project uninstall --mcp \
  --target codex,cursor,claude --location local
```

卸载全局配置时改用 `--location global`。卸载器只删除 ActuallyDone 自己写入的 MCP
条目、来源记录和项目级标记；外部 server、用户修改过的条目和周围说明会保留。

## 常见问题

### 找不到项目配置

看到 `adone.toml` 解析失败或找不到配置时，在项目目录执行 `adone init`，或者显式指定：

```bash
adone serve --mcp --root /path/to/project
adone --root /path/to/project install --mcp --target codex --location local
```

### 宿主看不到 MCP 工具

确认 `adone --version` 在宿主启动进程使用的 PATH 中可用；然后重新执行安装命令并重启
宿主。可以用 `--print-config` 检查目标名称和路径是否正确。Codex 项目级配置还要在
Codex 中信任项目。

### 配置文件被判定为冲突

先备份并检查对应 JSON/TOML 文件中的 `adone` 条目。安装器不会覆盖用户已有的同名条目；
如需接管，请先由用户明确移除冲突条目，再重新执行安装。

### 能否让 MCP 自动保证测试已经运行

MCP 提供固定的读取和执行入口，但宿主是否自动调用工具由宿主策略决定。`adone_run`
返回的本地回执是本地证据，不能替代 CI 的最终验证。

### 如何确认服务进程没有污染协议输出

MCP 服务把 JSON-RPC 消息写 stdout，把诊断信息写 stderr。排查时不要把普通 Shell 输出
混入 stdin；优先通过宿主的 MCP 连接状态、工具列表和 `ping` 检查连通性。

## 相关命令速查

```bash
# 查看版本
adone --version

# 初始化项目配置
adone init

# 启动 MCP 服务
adone serve --mcp

# 全局安装三个宿主
adone install --mcp --target codex,cursor,claude

# 项目级安装三个宿主
adone install --mcp --target codex,cursor,claude --location local

# 预览配置，不落盘
adone install --mcp --print-config codex,cursor,claude

# 预览并卸载项目级配置
adone uninstall --mcp --target codex,cursor,claude --location local --dry-run
adone uninstall --mcp --target codex,cursor,claude --location local
```
