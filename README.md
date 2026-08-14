# ActuallyDone

把「做完了」变成一件**可以被别人复核**的事。

AI Agent 说「已完成，测试全部通过」的时候，你没有办法当场判断这句话是真是假。
它可能贴的是上一轮的日志，可能转述而没真跑，可能跑完门禁之后又改了代码，
也可能为了让门禁变绿而把用例删了、把断言去了、把覆盖率下限调低了。

ActuallyDone 提供一个命令 `adone`，让「完成」有一个不依赖自述的判据：

```bash
adone gate run      # 真跑检查，产出一份与代码内容哈希绑死的回执
adone gate check    # 一秒复核：回执是不是新鲜的、是不是全绿的
adone audit         # 换一个模型来查：独立复核，不看实现过程，不覆盖被审的证据
adone health        # 六个维度的项目健康度，汇成一页可离线打开的 HTML
```

判据全部落在磁盘上（树哈希、验收契约、三份基线、回执链），不在任何人的会话里。
所以复核这件事不必由写代码的那个模型来做——见[对抗检查](#对抗检查换一个模型来核)。

零第三方依赖，只用 Python 标准库（需要 3.11+，因为用了 `tomllib`）。
当前版本 **v1.2.0**，变更记录见 [CHANGELOG.md](CHANGELOG.md)。

---

## 设计理念

### 完成 = 一条可复核的证据链

回执（`.adone/latest.json`）里记着**受监视代码树的内容哈希**。改动任何一个被监视的文件，
哈希就变，回执随之过期。于是「跑完门禁再改代码」这种最难发现的伪完成，变成一次字符串比较。

回执还记着每一步的命令、退出码、输出尾巴、通过用例名全集。任何人可以用
`adone gate check --explain` 独立复核，不必相信任何人的转述。

回执还带着**自哈希**与指向上一份回执的 `prev`，链头记在 `.adone/chain.json`。
手写一份「全绿」回执因此不再是填一个数字：自哈希要重算、链头要改、`prev` 还得对得上。

**诚实的边界**：这套机制提高伪造成本，不是密码学级不可伪造。能写文件的人理论上能重算整条链。
要做到真正不可伪造，需要一个 Agent 无权写入的执行者（CI）。展开见
[威胁模型与证据强度](#威胁模型与证据强度)。

### 门禁自己有多严，也要留档

改代码让门禁变绿要费力气，改判据让门禁变绿不费吹灰之力：缩小受监视目录、把测试命令换成
`-run TestNothing`、删掉一条验收契约、把用例名塞进假绿检测的豁免名单——每一条都能让门禁变绿，
而且原本一声不吭。

`adone policy` 把「决定门禁有多严」的东西拍成快照存进 `.adone/policy-baseline.json`：
受监视范围与文件数下限、每个步骤的 `kind/cwd/argv/invalid_marks`（`argv[0]` 指向仓库内脚本时
连脚本内容的 sha256 一起）、覆盖率下限与来源、测试适配器与豁免名单、各类检查项的条数、
以及契约面（有几份契约、每份几条、每条绑的哪个用例）。

和假绿检测同一个套路：只报**放松**，收紧只提示。

```bash
adone policy                                  # 有没有人把门槛悄悄调低
adone policy --accept "把 go vet 并进 build 步骤，命令因此变了"
```

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

第七种形态是「回执里写着通过，其实那一步根本没跑那些用例」。
`adone gate check --spotcheck` 从契约绑定的用例里随机抽两条当场真跑一遍：
跑不过是问题；退出码 0 但一条用例都没跑起来同样是问题，因为那不叫通过，那叫没跑。
默认关闭——钩子每次收工都要跑 `check`，几秒的代价不该压在那条路径上，交付前与 CI 里显式开。

### 自己检查自己是最弱的一档

即便判据是硬的，让写代码的那个模型来跑复核，仍有两个洞：它复用同一套盲点
（漏想到的分支，写测试时会再漏一次），而且它有动机把结论读得宽松一点。

判据从一开始就设计成**外置**的——树哈希、契约、基线、回执链全在磁盘上，
不依赖任何会话上下文——所以第二个模型天然就有独立得出结论的能力。
`adone audit` 与 `adone brief` 把这件事变成一条命令：
换一个会话、最好换一个模型，复核者不看实现过程，只看仓库里的证据。
用法见[对抗检查](#对抗检查换一个模型来核)。

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

## 威胁模型与证据强度

一个把「已完成」当成结论输出的工具，必须先说清楚这个结论有多硬。按对手的意图分三档：

### 一、无意漂移（挡得住）

改完代码忘了重跑、贴的是上一轮日志、跑门禁时跳过了一步、依赖挂了导致整批用例被跳过、
文档里的数字与代码对不上。这些是日常的绝大多数，树哈希、`complete` 标记、`invalid_marks`
与各维度检查逐条盯着。

### 二、敷衍作弊（现在挡得住，但靠的是让它留痕）

指为了让门禁变绿而动手脚，但不打算专门去研究这个工具怎么骗。四条最短路径，以及现在会怎样：

| 走法 | 现在的结果 |
| --- | --- |
| 手写 `.adone/latest.json`，填上 `adone gate hash` 打出来的哈希加 `"ok": true` | 自哈希对不上 → 被拦。要绕过得同时重算自哈希、改 `chain.json` 链头、让 `prev` 追得到 |
| 改 `adone.toml`：缩 `watch_roots`、换 `argv`、删检查项、调低下限 | 判据锁比对基线 → 被拦，除非跑 `adone policy --accept "理由"` 署名记账 |
| 删掉验收契约文件（没有契约就等于没有需求） | 契约面在判据快照里 → 被拦 |
| 把 `go test` 换成一个打印完美输出的脚本（`argv` 一个字没变） | 仓库内脚本的 sha256 在快照里 → 被拦；`--spotcheck` 还会当场真跑一条 |
| 把用例名塞进 `tests.baseline_exempt`，假绿检测就看不见它 | 豁免名单变长按放松处理 → 被拦 |
| 删掉 `.adone/policy-baseline.json` 让判据锁失效 | 上一份回执记着基线指纹 → 被拦，且 `gate run` 不会替已有基线重建 |

共同点是：**每条路都从「无声」变成了「要么留下一条署名记账，要么留下一处显眼的痕迹」**。
`policy-baseline.json`、`test-baseline.json`、`chain.json` 三份都建议**入库**——它们是证据，不是缓存。
入库之后，上面每一条都会出现在 `git diff` 里，变成一次需要在评审中解释的改动。

`.gitignore` 要这么写（**`.adone/*` 不能写成 `.adone/`**：排除目录本身的话 git 根本不会下去看，
后面的 `!` 一条都不生效，而且它不报错——你以为基线入库了，其实一直没有）：

```gitignore
.adone/*
!.adone/test-baseline.json
!.adone/policy-baseline.json
!.adone/chain.json
```

### 三、蓄意对抗（挡不住，只能靠 CI）

一个明确打算骗过这个工具、并且能写你的工作区的执行者，可以重算整条回执链、
同步改掉三份基线、把它们一起提交。本地零依赖的方案到此为止，**没有例外**。

`adone audit --rerun` 把这一档的成本又抬高一截：复核者自己把门禁全量跑一遍，
伪造者得让**真跑出来的结果**也对得上，光把文件改圆没用。但复核者与实现者跑在同一台机器、
同一套权限下，所以这仍是提高成本，不是跨过这条线。

要跨过这条线，需要一个 Agent 无权写入的执行者：在 CI 上跑 `adone gate run`，
把回执与链头作为产物留在 CI 侧；本地那份只是副本。届时证据强度可以从「自述」升到
「由 X 签名」——回执里的 `evidence` 段就是为这一步留的位置。

### 结论上写着它有多硬

`gate check` 通过时，以及健康度报告的头部，都会带一行：

```
证据强度：自述（本地跑）· 判据已锁 · 回执链完整
```

「总分 91」这种数字天然带着可信度暗示，所以可信度必须和数字出现在同一屏里，
而不是躲在文档某处的免责声明里。

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
adone policy                  # 判据基线由首次 gate run 自动建立，这里确认一眼
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
    chain.json            #   回执链头（下面三份都建议入库：它们是证据，不是缓存）
    test-baseline.json    #   假绿基线：谁放宽了什么，一眼可查
    policy-baseline.json  #   判据基线：门禁自己有多严
    audits/*.json         #   历次独立复核结论（复核者写，与上面的回执互不覆盖）
    audit.json            #   最新复核结论
    audit.html            #   最新复核结论的离线 HTML
    report.html  cover.out  dirty  hook.log
  .cursor/skills/…        # adone install 渲染生成（Cursor 只认这个位置）
  .cursor/hooks.json      # adone install --with-hooks 写入
```

## 命令

| 命令 | 做什么 | 耗时 |
| --- | --- | --- |
| `adone init` / `detect` / `doctor` | 探测、生成配置、拿配置对现实核（含已装钩子还能不能用） | 秒级 |
| `adone gate run` | 真跑门禁并写回执 | 取决于你的测试 |
| `adone gate check` | 复核回执是否新鲜且全绿，含契约、假绿检测、判据锁与回执链 | 秒级 |
| `adone gate check --spotcheck [N]` | 再抽 N 条（默认 2）声称通过的用例当场真跑 | 取决于用例 |
| `adone audit` | 独立复核：与 check 同一套判定，但**默认开抽查**、口吻是复核者的、结论另写一份（JSON + HTML） | 取决于抽查 |
| `adone audit --rerun` | 不信任回执时，自己把门禁全量跑一遍再与回执比对 | 取决于你的测试 |
| `adone audit report` | 把已有 `audit.json` 渲成一页离线 HTML，不重跑检查；`--out` / `--open` | 秒级 |
| `adone brief` | 复核者的冷启动简报：该读什么、跑什么、不许动什么 | 秒级 |
| `adone gate hash` | 打印当前受监视代码树的哈希与文件数 | 秒级 |
| `adone integrity` | 假绿检测；`--accept-baseline "理由"` 记账 | 秒级 |
| `adone policy` | 判据锁：门禁自己有没有被悄悄放松；`--accept "理由"` 记账 | 秒级 |
| `adone health` | 六维体检出 HTML；`--only` / `--skip` 挑维度 | 秒级 |
| `adone health --all` | 重跑门禁再体检 | 分钟级 |
| `adone health --with-probes` | 加跑业务不变量探针（可能要服务在跑、可能写库） | 取决于探针 |
| `adone requirements init` / `check` | 从需求源生成台账骨架 / 核验证据锚点 | 秒级 |
| `adone install` | 渲染技能与钩子模板到项目；`--hooks-only` 只重装钩子 | 秒级 |

## 对抗检查：换一个模型来核

最硬的检查不是自己检查自己。这一节是完整用法。

### 为什么能这么用

复核需要的东西一件都不在会话里：受监视代码树的哈希、验收契约绑的用例名、
三份基线、回执链，全部在仓库的文件里，任何执行者都能独立读、独立算、独立跑。
所以**复核者不需要知道实现者干了什么**——它反而不该知道，那会把实现者的盲点带进来。

### 两个角色，两条命令

| 角色 | 跑什么 | 产出 | 不许做 |
| --- | --- | --- | --- |
| 实现者 | `adone gate run` / `gate check` | `.adone/latest.json` + 链头 | 无 |
| 复核者 | `adone brief` / `adone audit` / `adone audit report` | `.adone/audit.json` + `audit.html` + `.adone/audits/*` | `policy --accept`、`integrity --accept-baseline`、改配置与代码 |

`audit` 与 `check` 共用同一套判定（口径分家等于给「换个命令再问一次」留后门），
但有三点刻意的差别：

- **默认开抽查**（`--spotcheck` 默认 2）。`check` 每次收工都跑，那几秒不该压在钩子路径上；
  复核只跑一次，省这几秒等于放掉「回执写着通过其实没跑」那一类。
- **不写 `latest.json`、不推进证据链**。复核者顺手覆盖被审的回执，等于把证据抹掉。
  `--rerun` 也一样，重跑的结果只落在 `.adone/audits/`。
- **口吻是复核者的**。`check` 通过时说「可以宣称完成」；`audit` 说「独立复核通过」，
  不通过时说「实现者不能宣称完成」——复核者不替实现者宣布完成。

### 怎么开一场（Cursor / 任意 Agent 都一样）

1. 实现者交付后，**开一个新会话**，换一个模型更好（Claude 实现就让 GPT 复核，反之亦然）。
2. 只给这一句，不要粘贴实现过程、不要转述它做了什么：

```
按 independent-check 独立复核这个仓库的交付：<仓库路径>
```

   没装技能时，把这句换成：`跑 adone brief，按它说的做，然后跑 adone audit`。
   `adone install` 会把 `independent-check` 技能渲染进 `.cursor/skills/`，
   里面写清了复核者的三条铁律与报告口径。

3. 复核者先跑 `adone brief` 冷启动——它会打印这个项目的判据在哪、现有几份契约、
   实现者留的是哪份回执、以及复核者不许碰的东西；然后跑 `adone audit`。
4. 不信任那份回执时（它可能是精心构造的），跑 `adone audit --rerun` 全量重跑并逐项比对：
   树哈希对不上、回执写着全绿而重跑没过、**回执列着的用例名在重跑里根本没出现**，都会被点名。
5. 未通过则把问题清单**原样**交回实现者。修完之后由**复核者再核一次**，
   不接受实现者自证已修好。

### 复核结论长什么样

```
独立复核（复核现有回执）：对照回执 20260813-222226，当前树 695afde9413b（564 个文件）

独立复核通过：这份交付的证据自洽，且抽查的用例当场真跑仍然通过。
  · 回执 20260813-222226（2026-08-13T22:22:26）
  · 树哈希一致 695afde9413b（564 个文件）
  · 证据链第 2 环，自哈希 31c0fba54c5f
  · 判据与基线一致 e557a81a7694（2026-08-13T10:41:35「首次建立」）
  · 验收契约 1 份 / 2 条，全部绑定到已通过的用例
  · 抽查真跑 1 条（取自契约绑定用例）：TestPipelineDispatchSerialPerSKU 现在仍然通过
证据强度：自述（本地跑）· 判据已锁 · 回执链完整 · 已由独立复核者抽 1 条当场真跑

结论写入 .adone/audit.json（不覆盖实现者的回执与证据链）
HTML 报告：.adone/audit.html
```

结论那句话与末行都**如实写明复核者核到了哪一层**：只读证据、抽 N 条真跑、全量重跑是三档不同的
强度，写成同一句话等于把最弱的一档冒充最强的（`--spotcheck 0` 时那句会变成
「本次只读证据，没有当场重跑」）。`--json` 输出同样的结论供脚本或 CI 消费。
给人看的那页是 `.adone/audit.html`（`--out` 改路径，`--open` 生成后打开）；
已经有结论、只想出 HTML 时跑 `adone audit report`，不重跑检查。

### 边界

复核者与实现者跑在同一台机器、同一套文件权限下。一个铁了心造假的实现者可以重算整条链
并同步改掉三份基线——`--rerun` 让它还得让真跑的结果也对得上，但真正的不可伪造仍然需要
一个 Agent 无权写入的执行者。别把「独立复核通过」读成「不可能造假」。

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

- **随包发布**（方法通用）：`completion-gate`、`acceptance-contract`、`test-integrity`、
  `verified-delivery`、`independent-check`（给复核者的那一份：只报告、不修复、不替实现者记账）
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
  列不出用例名，因此假绿检测、验收契约与 `--spotcheck` 在纯 generic 项目里会显示未评估。
  单条重跑目前只有 go（`-run '^Name$'`）与 python（pytest 用例 ID / unittest `-k`）支持。
- **对抗检查是「同机不同会话」，工具不验证复核者的身份。** `.adone/audit.json` 里的
  `role: auditor` 是自述——换一个模型、不给它实现过程，这两件事得由你在流程上保证，
  工具只保证复核者拿得到独立判据、且它的结论不会覆盖被审的证据。
- 路由锚点用的是保守的后缀匹配（框架的路由注册常跨文件拼接，精确还原代价过高），
  所以它只报警告，用来发现「文档里写了、代码里完全没有」的幻影接口。

## LICENSE

MIT，见 [LICENSE](LICENSE)。
