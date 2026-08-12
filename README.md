# ActuallyDone

把「做完了」变成一件**可以被别人复核**的事。

AI Agent 说「已完成，测试全部通过」的时候，你没有办法当场判断这句话是真是假。
它可能贴的是上一轮的日志，可能转述而没真跑，可能跑完门禁之后又改了代码，
也可能为了让门禁变绿而把用例删了、把断言去了、把覆盖率下限调低了。

ActuallyDone 提供一个命令 `adone`，让「完成」有一个不依赖自述的判据：

```bash
adone gate run      # 真跑检查，产出一份与代码内容哈希绑死的回执
adone gate check    # 一秒复核：回执是不是新鲜的、是不是全绿的
adone health        # 六个维度的项目健康度，汇成一页可离线打开的 HTML
```

零第三方依赖，只用 Python 标准库（需要 3.11+，因为用了 `tomllib`）。

---

## 设计理念

### 完成 = 一条可复核的证据链

回执（`.adone/latest.json`）里记着**受监视代码树的内容哈希**。改动任何一个被监视的文件，
哈希就变，回执随之过期。于是「跑完门禁再改代码」这种最难发现的伪完成，变成一次字符串比较。

回执还记着每一步的命令、退出码、输出尾巴、通过用例名全集。任何人可以用
`adone gate check --explain` 独立复核，不必相信任何人的转述。

**诚实的边界**：这套机制提高伪造成本，不是密码学级不可伪造。能写文件的人理论上能伪造回执 JSON。
要做到真正不可伪造，需要一个 Agent 无权写入的执行者（CI）。

### 假绿的六种形态

绿灯有两种来源：代码变对了，或者门禁被改松了。后者的常见手法，工具逐一盯着：

| 手法 | 怎么抓 |
| --- | --- |
| 删用例、改用例名 | 与基线快照比对，用例消失就点名 |
| 加跳过（`t.Skip` / `it.skip`） | 跳过点数只许降不许涨，涨了要写理由记账 |
| 把断言删光，留个空壳用例 | 按适配器识别断言 API，无断言用例进基线名单 |
| 调低覆盖率下限 | 配置与文档里声明的下限都纳入比对 |
| 整批用例因连不上依赖被跳过 | 输出里出现 `invalid_marks` 即判本轮证据无效 |
| 编一个不存在的用例名来结案 | 验收契约要求用例既在源码里存在、又在回执的通过名单里 |

只报**新增**的松动：历史遗留不会天天刷屏，新加的一次也跑不掉。
确属合理的放宽，用 `adone integrity --accept-baseline "理由"` 记账——谁在什么时候放宽了什么，一眼可查。

### 只按真跑过的维度计分

跳过的维度在报告里灰显成「未评估」，不参与总分，标题旁写着覆盖了几分之几。
`--only skills` 可以拿 100 分，但页面同时写着「1/6 个维度」，刷不出一个虚高的满分。

同理，**任何一处「这个检查跑不了」都必须显示为未评估，而不是默默算通过**。
适配器缺少某项能力（比如 generic 适配器切不出函数体）时，对应检查直接标未评估。

### 文档与代码的一致性分两类

混为一谈会让报告要么漏报要么天天误报：

- **权威对权威**：两份文件都自称权威全量（例如程序内迁移与绿地建库脚本），必须**完全一致**，
  差一项就是错误。落在「代码质量」维度。
- **选摘查幻影**：文档自述是摘录，不要求全覆盖，只抓**幻影**——文档里写了、代码里根本没有的东西。
  落在「AI 物料」维度。

### 覆盖率低不扣分，失联才扣

需求台账抓的不是「还没做完」——没做的需求不代表项目不健康。真正扣分的是**失联需求**：
标了已做，但绑的表、路由、用例、页面已经不存在了。曾经做过、如今证据没了，这才是偏离。

---

## 安装

三种用法，按侵入程度从低到高：

```bash
# 1. pipx（推荐）：独立 venv，解释器保证够新，adone 落在 ~/.local/bin
pipx install git+https://github.com/iamharvey/ActuallyDone.git
adone --version

# 2. pip
pip install git+https://github.com/iamharvey/ActuallyDone.git

# 3. vendor 进你的仓库：把这个仓库整个拷进 tools/ 之类的地方，它自成一体，
#    然后走免安装入口 python3 tools/ActuallyDone/bin/adone。
#    这个入口发现自己被一个 3.11 以下的 Python 起起来时，会自动换一个够新的再跑；
#    钩子与 CI 用 vendor 版的好处是：目标机器上没装包时，钩子不会因为找不到命令而失灵
python3 bin/adone --version
```

## 快速上手

```bash
cd 你的项目
adone init                    # 探测生态、测试命令、文档位置，生成 adone.toml
adone doctor                  # 拿配置对现实核一遍：路径在不在、命令跑不跑得动、钩子还灵不灵
adone gate run                # 跑一次门禁，看实际覆盖率，回填 coverage.threshold
adone integrity --accept-baseline "建立初始基线"
adone install --with-hooks    # 把技能与钩子装进 .cursor/
adone health                  # 出一页健康度报告
```

`adone init` 生成的配置里，探测出来的项都标着「请确认」。
**它不猜阈值**：覆盖率下限留空，等你跑完门禁拿实测值回填——一个凭空写下的 80%
会让所有人以为这是团队的约定，其实只是工具编的。

## 装进项目之后长这样

```
你的项目/
  adone.toml              # 配置，人写，入库
  adone/                  # 人写的验收物料，入库
    acceptance/*.toml     #   验收契约：一次交付的每条要求绑到一个用例名
    requirements/*.toml   #   需求台账：跨迭代的那本账
  .adone/                 # 机器写的状态
    receipts/*.json       #   历次回执
    latest.json           #   最新回执
    test-baseline.json    #   假绿基线（这份建议入库：谁放宽了什么，一眼可查）
    report.html  cover.out  dirty  hook.log
  .cursor/skills/…        # adone install 渲染生成（Cursor 只认这个位置）
  .cursor/hooks.json      # adone install --with-hooks 写入
```

## 命令

| 命令 | 做什么 | 耗时 |
| --- | --- | --- |
| `adone init` / `detect` / `doctor` | 探测、生成配置、拿配置对现实核（含已装钩子还能不能用） | 秒级 |
| `adone gate run` | 真跑门禁并写回执 | 取决于你的测试 |
| `adone gate check` | 复核回执是否新鲜且全绿，含契约与假绿检测 | 秒级 |
| `adone gate hash` | 打印当前受监视代码树的哈希与文件数 | 秒级 |
| `adone integrity` | 假绿检测；`--accept-baseline "理由"` 记账 | 秒级 |
| `adone health` | 六维体检出 HTML；`--only` / `--skip` 挑维度 | 秒级 |
| `adone health --all` | 重跑门禁再体检 | 分钟级 |
| `adone health --with-probes` | 加跑业务不变量探针（可能要服务在跑、可能写库） | 取决于探针 |
| `adone requirements init` / `check` | 从需求源生成台账骨架 / 核验证据锚点 | 秒级 |
| `adone install` | 渲染技能与钩子模板到项目；`--hooks-only` 只重装钩子 | 秒级 |

## 六个维度

| 维度 | 看什么 | 默认 |
| --- | --- | --- |
| 技能沉淀 | 技能的 frontmatter、体积、断链、**引用的代码路径行号是否失效** | 跑 |
| 测试与覆盖率 | 读最新回执：失败用例、覆盖率下限、假绿检测结论 | 跑 |
| 代码质量 | 权威对权威的漂移、未引用符号、重复函数体、超大文件、零覆盖函数 | 跑 |
| 需求台账 | 证据锚点还在不在（失联需求） | 跑 |
| AI 物料 | 关键文档齐备、架构图是否比源文件旧、选摘幻影、文档写死的数字对账 | 跑 |
| 业务不变量 | 你自己写的探针：跑起来的系统里那条业务规则还成立吗 | **不跑** |

探针默认不跑，因为它可能要服务在跑、可能会写数据。
一个关键区分：**「探针跑不起来」是警告，「不变量被破坏」才是错误**——
混为一谈会让人以为业务出了问题，实际只是服务没起。

## 配置

`adone.toml` 全部字段见 `adone init` 生成的注释版。几个需要动脑的：

```toml
[gate]
# 受监视代码树：回执的树哈希由这些文件的内容算出。改了其中任何一个，回执即过期。
watch_roots = ["backend/internal", "frontend/src"]
watch_exts = [".go", ".ts", ".vue"]
# 扫到的文件数低于这个值直接报错：空哈希会让门禁恒等通过，比没有门禁更危险
min_tree_files = 400

[[gate.step]]
name = "go test"
cwd = "backend"
kind = "test"          # 用 adapter 解析输出，光看退出码会漏掉一整批假绿
adapter = "go"
argv = ["go", "test", "./...", "-count=1", "-v", "-coverprofile={cover_out}"]
# 输出里出现这些串就判本轮证据无效（例如整批用例因为连不上数据库被跳过）
invalid_marks = ["需要 MySQL"]

[[gate.step]]
name = "gofmt"
kind = "fmt"           # 格式化工具往往永远退出 0，有输出即失败
argv = ["gofmt", "-l", "."]
```

把项目特有的规则用配置表达，而不是改代码：

```toml
[[consistency.pair]]           # 两份都自称权威全量，必须完全一致
a = "backend/internal/migrate/migrate.go"
b = "deploy/migrate.sql"
extract = "sql_tables"

[[docs.excerpt]]               # 文档是选摘：只查幻影，不要求全覆盖
file = "blueprint/db/schema.sql"
extract = "sql_tables"
against = "backend/internal/migrate/migrate.go"

[[docs.claim]]                 # 文档里写死的数字与现实对账
file = "blueprint/db/schema.sql"
pattern = "权威全量 DDL（(\\d+) 张表）"
actual = "count:sql_tables:backend/internal/migrate/migrate.go"

[[code.unused]]                # 定义了却没人引用的符号，与语言无关
name = "未注册 handler"
glob = "backend/internal/api/*.go"
define = "^func \\(h \\*Handler\\) ([a-z]\\w*)\\("
use = "h\\.([a-z]\\w*)\\b"
```

## 验收契约与需求台账

契约挡的是**需求缩水**（三条做了两条就说完成）和**编用例名**（清单勾了，用例不存在）：

```toml
# adone/acceptance/2026-08-11-下单限价.toml
task = "下单校验价格区间"

[[item]]
"要求" = "负数价格必须被拒绝"
test = "TestOrderRejectsNegativePrice"    # 必须真实存在，且出现在回执的通过名单里
impl = "internal/service/order.go:168"    # 可选，行号越界会被点出来
```

台账是跨迭代的那本账，每条需求绑几个证据锚点（`table:` / `route:` / `test:` / `view:` /
`file:` / `skill:` / `adr:`），由脚本核。`adone requirements init` 能从一份 markdown 需求源
生成骨架并给出**证据候选**——候选只是候选，人工确认后挪进「证据」才算数。

## 扩展：写一个适配器

适配器封装「这个生态怎么跑测试、怎么读结果」。实现 `Adapter` 的子集即可，
**没实现的能力会让对应检查显示未评估，而不是静默通过**：

```python
from actuallydone.adapters.base import Adapter, CAP_TESTS

class RustAdapter(Adapter):
    name = "rust"
    caps = {CAP_TESTS}
    markers = ("Cargo.toml",)
    source_exts = (".rs",)

    def suggest_steps(self, hint_dir):
        return [{"name": "cargo test", "cwd": hint_dir, "kind": "test",
                 "adapter": "rust", "argv": ["cargo", "test"]}]

    def parse_test_output(self, text):
        ...   # 返回 TestResult；解析不出就返回 TestResult(parsed=False)
```

注册到 `actuallydone/adapters/__init__.py` 的 `REGISTRY` 即可。

## 技能：通用的随包发布，专有的只给骨架

`adone install` 把模板渲染进 `.cursor/skills/`，渲染时替掉阈值、命令、路径等项目相关的措辞——
把「85% 是当前实测水位」原样抄进别人的项目，就是在替他们说谎。

- **随包发布**（方法通用）：`completion-gate`、`acceptance-contract`、`test-integrity`、`verified-delivery`
- **只给空模板**：`coding-standards`、`pr-review-checklist`、`test-driven-dev`——
  它们的价值恰恰在于内容是你们自己踩出来的，通用版没有意义，里面的 TODO 要你自己填

`--with-hooks` 会写入两个 Cursor 钩子：`afterFileEdit` 记录改动过的文件，
`stop` 在 Agent 想收工时跑一次 `gate check`，不通过就把问题列表作为下一条用户消息推回去。
钩子没有否决权，但它**从不安静地放行**：门禁跑不起来时也会推一条「门禁没跑成」回去，
因为空输出在终端里和「门禁通过」长得一模一样。

钩子进程的 PATH 由客户端决定，不由你决定（实测拿到过一个既没有 `~/.local/bin`、
python3 还是 3.10 的环境）。所以钩子按 `仓库内免安装入口 → 安装时记下的 adone 绝对路径 →
PATH → ~/.local/bin 等常见落点` 逐个找，全找不到就推「找不到 adone」回来。
`afterFileEdit` 那个钩子解析 payload 优先用 `jq`，没有就用 `python3`，两个都没有时
往 `hook.log` 记一笔——**它绝不会一声不吭地什么都不记**，因为一个永远为空的 `dirty`
和一个从没被改过的仓库长得一模一样。

换了 adone 的装法之后，用 `adone install --hooks-only --force` 重渲钩子：
它一个技能文件都不碰，不会把你写进技能里的项目私货冲掉；`.cursor/hooks.json`
是**合并**而不是覆盖，你自己配的其他钩子会原样留着。

装完之后钩子会不会失效，交给 `adone doctor` 定期核：脚本还在不在、可执行位还在不在、
`hooks.json` 里登记了没有、钩子里烧的那条 adone 路径现在还找不找得到、
配置改了而钩子还是旧的（比如 `state_dir` 换了，钩子还在往老地方写）。
这些都是钩子静默失效的真实形态——不主动去核，你不会知道。

## 自测

```bash
cd ActuallyDone            # 仓库根
python3 -m unittest        # 标准库，不引 pytest
```

## 它自己被用出来的样子

第一个使用者是一个 Go + Vue 的电商刊登系统原型（受监视代码树 564 个文件、约 18.2 万行）。
一轮 `adone health --all` 的产出：门禁 1226 通过 / 9 跳过（顶层 1）/ 覆盖率 85.9%，总分 91（5/6 个维度）。

同一轮里被查出来、且都是真问题的：

- 程序内迁移建了 153 张表，绿地建库脚本只有 137 张——用后者建库，商品库与 Feed 功能直接起不来，
  而那份文件的头部还写着「与迁移代码等价」；另有 1 张表已被迁移代码显式 `DROP`，建库脚本却还在建。
- 三张架构图的 `.svg` 比 `.mmd` 源文件旧了三天。
- 蓝图的 schema 选摘里有 1 张幻影表，代码里已经没有了。

这些都不是演示数据，是这套检查在一个自认为「已完成」的仓库上第一次跑出来的东西。

## 限制声明

- **只在 Cursor + macOS + Python 3.11+ 上验证过。** 其他 IDE、其他 Agent 平台、Linux 与
  Windows 都没有测过。`adone install --target` 预留了别的平台，但没有验证。
- 钩子机制依赖 Cursor 的 `hooks.json`；`stop` 钩子只能推消息，不能阻断，这是平台决定的。
- **需要 Python 3.11+**（标准库 `tomllib`）。钩子进程拿到的 PATH 常常与你终端里的不同——
  本机就发生过钩子被 anaconda 的 3.10 起起来、`import tomllib` 直接失败的事。
  `bin/adone` 因此会在解释器过老时自动找一个 3.11+ 的换过去（PATH 找不到就去
  `/opt/homebrew/bin` 等常见位置翻），实在找不到会明说，而不是丢一段堆栈。
- 内置适配器只有 go / node / python / generic 四个。generic 适配器只能跑步骤，
  列不出用例名，因此假绿检测与验收契约在纯 generic 项目里会显示未评估。
- 路由锚点用的是保守的后缀匹配（框架的路由注册常跨文件拼接，精确还原代价过高），
  所以它只报警告，用来发现「文档里写了、代码里完全没有」的幻影接口。

## LICENSE

MIT，见 [LICENSE](LICENSE)。
