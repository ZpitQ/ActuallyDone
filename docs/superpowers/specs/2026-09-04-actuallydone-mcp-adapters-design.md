# ActuallyDone MCP 与多 Agent 适配设计

## 状态

已确认方向，首批适配 Codex CLI、Cursor、Claude Code。

## 目标

在不改变 ActuallyDone 现有门禁、回执、审计和 hook 语义的前提下，增加一个本地 MCP
入口，使支持 MCP 的 Agent 能读取门禁状态并按固定模式触发已有命令。MCP 是一个 adapter
模块；CLI、IDE hook 和 MCP 共享同一套核心判定逻辑。

## 非目标

- 不依赖、读取或合并 CodeGraph。
- 不增加语义代码图、调用图或索引数据库。
- 不改变现有 `adone.toml` 判据、回执格式和 CI 建议。
- 不保证 Agent 宿主一定会自动触发测试；MCP 只提供统一能力。
- 不通过 MCP 接受 Agent 任意 shell 命令。

## 架构

```text
ActuallyDone 核心
  Config / gate / integrity / policy / audit
        |
        +-- CLI adapter（现有）
        +-- hook adapter（现有）
        +-- MCP adapter（新增）
                    |
                    +-- stdio MCP transport
                    +-- tool dispatcher
                    +-- Codex / Cursor / Claude installer adapters
```

MCP adapter 的接口保持小而稳定：负责协议握手、工具发现、参数校验、核心函数调用和
结果序列化；不在 adapter 中复制门禁判定。MCP transport 与 dispatcher 应能在不启动
Agent 的情况下用 transcript 测试。

## MCP Server

新增命令：

```text
adone serve --mcp [--root PATH]
```

根目录解析顺序为显式 `--root`、`ADONE_PROJECT_DIR`、当前工作目录向上查找
`adone.toml`。首版不接受工具调用中的任意项目路径；这样全局 Agent 配置仍由宿主的
工作目录选择项目，同时避免 MCP 工具被用来跨目录执行命令。找不到配置时返回结构化
错误，不让 JSON-RPC 进程崩溃。

协议层实现当前 MCP 所需的 `initialize`、`notifications/initialized`、`tools/list`、
`tools/call` 和 `ping`；使用标准 JSON-RPC 错误形态，协议日志只写 stderr，stdout
只输出 MCP 消息。版本协商采用客户端提供的协议版本，服务端在不支持时返回明确错误。

## 工具接口

### `adone_status`

只读。返回项目根、配置路径、当前树哈希、最新回执 ID/哈希、回执新鲜度、policy/integrity
问题和证据强度。等价于读取现有状态，不执行测试。

### `adone_check`

只读。调用现有 `gate check` 判定，参数仅允许 `spotcheck`（非负整数，默认 0）和
`with_integrity`（默认 true）。返回 `ok`、问题列表、详情和退出码语义。

### `adone_brief`

只读。调用现有 `audit brief`，返回复核者需要读取的判据、契约、基线和禁止动作。

### `adone_run`

有副作用。参数：

- `scope`: `changed`、`full` 或 `affected`。
- `skip`: 可选步骤名数组；沿用 CLI 的不完整回执语义。

只能映射到既有 CLI 的固定模式，不能传入 argv、脚本路径或 cwd。返回步骤状态、测试
摘要、回执 ID、失败原因和是否可交付。运行期间的进度写 MCP progress/content，诊断日志
写 stderr。

### `adone_audit`

有副作用但不覆盖实现者回执。参数：`mode` 为 `review` 或 `rerun`，`spotcheck` 为
非负整数。调用现有 audit 实现，返回审计 ID、结论、证据强度和报告路径。

所有工具返回稳定的 JSON 对象，同时提供人类可读的 text content；未知工具、缺参数、
配置错误和门禁失败分别使用可区分的错误码/字段。

## Installer Registry

抽象一个 `AgentTarget` 接口，字段/方法至少包括：

- `id`、显示名称和文档链接。
- `detect(location)`：检测 Agent 是否存在、是否已有 ActuallyDone 配置。
- `install(location, options)`：幂等合并 MCP 配置和可选指令标记。
- `uninstall(location)`：只移除 ActuallyDone 自己写入的内容。
- `print_config(location)`：打印不落盘的配置片段。
- `describe_paths(location)`：列出会读写的路径。

首批 target：

### Codex CLI

写入全局 `~/.codex/config.toml` 或项目 `.codex/config.toml` 的
`[mcp_servers.adone]` 表；项目级配置同时写 `AGENTS.md` 的标记段。保留用户的其他
TOML 内容，重复安装不产生差异。输出项目配置可能受 Codex trust 机制影响的提示。

### Cursor

写入全局 `~/.cursor/mcp.json` 或项目 `.cursor/mcp.json` 的 `mcpServers.adone`。项目级
安装可写入 ActuallyDone 的标记说明；全局安装只改 MCP 配置。JSON 合并保留其他 server，
卸载只删除 `adone` 条目。

### Claude Code

写入全局 `~/.claude.json` 或项目级 Claude 配置中的 `mcpServers.adone`，并在项目级
`CLAUDE.md` 中维护标记段。配置写入必须幂等，并保留用户手写的其他 server、权限和内容。

安装命令：

```text
adone install --mcp --target codex,cursor,claude
adone install --mcp --target codex --location local
adone install --mcp --print-config codex
adone uninstall --mcp --target codex,cursor,claude
```

现有 `adone install --with-hooks` 默认行为保持不变；MCP 安装只有显式 `--mcp` 才执行。

## 错误、信任与兼容性

- MCP 服务启动失败、配置缺失和协议错误必须返回可诊断文本，不污染 stdout。
- `run` 与 `audit` 的副作用在工具描述和返回值中明确写出；宿主是否弹确认由 Agent 决定。
- 本地回执仍不可作为不可伪造证明；CI 继续承担最终可信执行者角色。
- 版本升级要保持旧 CLI、旧 hooks 和旧配置可用；MCP 配置使用 marker/精确 key，禁止
  覆盖用户未知内容。
- 没有 MCP 的 Agent 继续走 CLI 和现有技能/说明文件。

## 测试计划

1. MCP transcript：initialize、版本协商、tools/list、tools/call、ping、未知方法、
   参数错误、配置缺失和异常恢复。
2. 工具行为：只读工具不写 `.adone`；run 与 CLI 返回一致；audit 不覆盖 latest/chain。
3. Installer：Codex TOML、Cursor JSON、Claude JSON 的新建、合并、幂等重装、保留未知
   字段、marker 更新和精确卸载。
4. 跨平台：Linux/Windows 路径、UTF-8 stdout/stderr、工作目录不正确和命令不可用。
5. 回归：完整 `python -m unittest`，并保留现有 hook/upgrade 测试不变。

## 交付

在 fork `ZpitQ/ActuallyDone` 的 `codex/mcp-server` 分支开发；完成后运行完整测试，提交
到 fork，再创建指向原仓库 `iamharvey/ActuallyDone` 的 PR。PR 说明会明确 MCP 只新增独立
adapter，不改变 CodeGraph 或 ActuallyDone 的职责边界。

