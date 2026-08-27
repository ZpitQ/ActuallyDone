# 变更记录

版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## v1.3.8 — 2026-08-28

1.3.7 之后手跑 `gate-guard.cmd` 有 `hook.log`，Cursor 自动触发仍然没有。

### 修

- **`CreateProcess` 不能直接跑 `.cmd`**：终端里手跑会经 cmd.exe / PowerShell 转发，
  所以脚本是好的；Cursor 把 `hooks.json` 的 command 当可执行文件名去启动，
  批处理起不来，`.adone` 里就没有 `hook.log`。Windows 改为登记
  `.cursor/hooks/gate-guard.exe`，安装时复制本机 `adone.exe` 或专用入口
  `adone-hook-*.exe`。cli 按 `argv[0]` 文件名分发到 `hook mark-dirty` /
  `hook gate-guard`。`.cmd` 仍写出，只给手跑对照。
- **`adone doctor`** 看见还登记着 `.cmd` 就点名：手跑可以、Cursor 调不起来。

升上来必须 `adone upgrade` 再 `adone install --hooks-only --force`。
重渲后 `hooks.json` 的 command 必须是 `.exe`，不能再是 `.cmd`。
`.exe` 是本机生成物，不要提交。

## v1.3.7 — 2026-08-27

### 修

- **Windows 上日志写了「已回推」，Agent 窗口却没有**：`adone hook` 的 JSON
  改为按 UTF-8 立刻刷出，有 `followup_message` 时再多停 200ms。Cursor 在
  Windows 上经过 PowerShell 收 stdout，进程一退出就把管道当收完，Execution
  Log 里变成 `{}`，对话不会出现回推——这是官方承认的 bug，不是脚本没输出。
  升 `adone` 即可，不必重渲钩子。
- **Cursor 在 Windows 上可能用 Git Bash 起钩子**：纯 `.cmd` 被当成 shell 脚本，
  第一行 `@echo off` 就失败。启动器改成 cmd/bash 双语。文件必须按字节写 LF
  （`Path.write_text` 在 Windows 上会变成 CRLF，heredoc 合不上）。
- **`sessionStart` 探针**：打开一轮 Agent 对话就会写 `hook.log`。

## v1.3.6 — 2026-08-27

1.3.5 之后不弹 `.py` 了，但 `.adone` 里没有 `hook.log`，钩子仍然不生效。

### 修

- **`cmd /c .cursor\hooks\gate-guard.cmd` 根本起不来**：Cursor 把整串当成一个
  可执行文件名交给 `CreateProcess`，找不到这个文件，默认放行。所以不弹编辑器，
  也不写 `hook.log`。hooks.json 改回官方那种**单独一条相对路径**：
  `.cursor/hooks/gate-guard.cmd`。`.cmd` 是 Windows 认的可执行文件。
- **`.cmd` 一启动就写 `hook.log`**：不再等 Python 起来才留痕。没有这行，
  就是 Cursor 没拉起进程。
- **`.cmd` 用 CRLF 写出**：从 Mac 写出的 LF 批处理，有的 Windows 会当空文件跳过。
- **不再先跑 `where`**：`where` 可能吃掉 Cursor 喂给钩子的 stdin，后面的
  `adone hook` 拿到空 payload。
- **`adone doctor`** 认「`cmd /c …cmd`」这种登记，点名要重渲。

升上来必须 `adone install --hooks-only --force`。重渲后 `hooks.json` 里不能再有
`cmd /c`。

## v1.3.5 — 2026-08-27

Windows 上升到 1.3.4 之后，**还是弹出 `gate-guard.py`**。

### 修

- **`.cursor/hooks/` 里不能留 `.py`**：v1.3.4 登记了 `.cmd`，但启动器仍去跑旁边的
  `gate-guard.py`，而且那个文件还在钩子目录里。Windows 按文件关联打开 `.py`
  （Cursor 自己就是默认应用），于是每次弹出文件，钩子仍没执行。
  官方论坛的修法是 `command` 以 `cmd` 开头，且**整条命令里不能出现 `.py` 路径**。
- **钩子逻辑改走 `adone hook`**：`mark-dirty` / `gate-guard` 进了包本身。
  Windows 的 `hooks.json` 登记 `cmd /c .cursor\hooks\gate-guard.cmd`，
  `.cmd` 只调用 `adone hook gate-guard`（或 `py -3 -m actuallydone hook …`），
  不再点任何 `.py` 文件。安装时会**删掉**残留的 `gate-guard.py` / `mark-dirty.py`。
- **`adone doctor`**：钩子目录里还留着 `.py` 就点名「会被编辑器打开」。

升上来必须 `adone install --hooks-only --force`。然后确认：
`.cursor\hooks\` 里没有 `.py`，`hooks.json` 的 `command` 里也没有 `.py`。

## v1.3.4 — 2026-08-27

Windows 上钩子「已安装」但每次弹出 `gate-guard.py`、改完代码不重跑门禁。

### 修

- **登记 `.py` 等于打开文件**：Cursor 把 `hooks.json` 的 `command` 交给操作系统
  去启动。`.py` 的默认关联是编辑器（常常就是 Cursor 自己），于是 stop 钩子一触发
  就弹出 `gate-guard.py`，脚本一行都没跑——回执过期检查从未发生，Agent 改完
  代码没人提醒。v1.3.3 的 `cmd /c py -3 …py` 命令里仍有 `.py`，一样会被打开。
  现在 Windows 上登记的是 `.cursor/hooks/gate-guard.cmd` / `mark-dirty.cmd`：
  `.cmd` 才是 Windows 认的可执行文件，启动器找到解释器再跑旁边的 `.py`。
- **`adone doctor` 认这件事**：hooks.json 里还登记着 `.py` 时，点名「会打开文件
  而不是执行」，而不是报「钩子：已装」。
- **stdin 带 BOM**：Windows 上 Cursor 喂给钩子的 JSON 有时带 UTF-8 BOM，
  不剥掉就解析失败，改动记不下来。两个钩子都剥。

从 v1.3.3 升上来也必须 `adone install --hooks-only --force`。重渲后
`hooks.json` 的 `command` 里不能再出现 `.py`。

## v1.3.3 — 2026-08-27

Java 团队在 Windows 上反馈的两件事。它们是同一类病，和 v1.3.2 修的 `mvn` 一样：
**体检用的判断和操作系统实际执行的判断不一致**，于是「检查失效」长得像「检查通过」。

### 修

- **Windows 上钩子静默不触发，Agent 改完代码没人提醒**：`afterFileEdit` 挂的是
  `mark-dirty.sh`（bash + jq），`stop` 挂的是靠 shebang 加可执行位启动的
  `gate-guard.py`——这三样在 Windows 上都不成立，Cursor 起不动，钩子什么都不做。
  而 `doctor` 查的是 `os.access(X_OK)`，那在 Windows 上对任何存在的文件恒为真，
  所以体检还报「钩子：已装」。现在：
  - `mark-dirty` 从 bash 移植成 Python（`mark-dirty.py`），去掉 bash 与 jq 依赖，
    顺带认 Windows 给的反斜杠 `file_path`；旧的 `.sh` 会被摘掉登记并删除。
  - `hooks.json` 里注册**显式解释器调用**（Windows 上是 `cmd /c py -3 …`），
    不再依赖 shebang 与可执行位。这也是官方文档 Python 示例的写法。
  - `doctor` 改为真的去解析登记命令里的解释器，起不来就报出来；
    还登记着旧版 `.sh` 时点名要求重渲。
  - `gate-guard` 在 Windows 上能找到 `adone.exe` / `adone.cmd`，
    并会翻 `Scripts` 这类 Windows 专有的脚本目录。
- **`mvn test jacoco:report` 成功了却读不到覆盖率**：pom 只声明了插件、没把
  `prepare-agent` 绑进生命周期时，`mvn test` 不挂探针，`jacoco:report` 打一行
  `Skipping JaCoCo execution due to missing execution data file` 就 BUILD SUCCESS，
  一份报告都不写。现在 `adone init` 生成的步骤是
  `mvn -B -ntp jacoco:prepare-agent test jacoco:report`（CLI 显式跑，不依赖 pom 绑定）；
  读不到覆盖率时会指出断在哪一环——探针没挂上 / 只有 `.exec` 没有 xml /
  一份报告都没找到 / 报告里行计数为空——而不是只说「没解析到覆盖率数字」。
- **多模块覆盖率报的是第一个模块**：以前返回「第一份能解析出数字的报告」，
  在 aics-api + aics-gateway 这种仓库里既不是整体水位，还会随模块改名而跳变。
  改成把各模块的行数加起来；有 `jacoco-aggregate` 聚合报告时只认聚合报告，
  免得重复计数。

### 文档

- README 新增「Windows」与「Java 的覆盖率读不到」两节。
- 限制声明写清：Windows 的支持是「按 Windows 语义实现并有针对性用例」，
  不是「在 Windows CI 上跑过」——仓库里没有 Windows runner。

## v1.3.2 — 2026-08-27

### 修

- **Windows 上 `mvn` / `npm` 一律「命令不存在」**：这两个在 Windows 上是 `.cmd`
  批处理，而 `CreateProcess` 不查 `PATHEXT`，`subprocess` 直接抛 `FileNotFoundError`；
  偏偏 `doctor` 用的 `shutil.which` 认 `PATHEXT`，于是「体检说命令在、门禁说命令不存在」。
  现在门禁、抽查、探针、doctor 全部走同一个 `resolve_cmd`：先解析成带后缀的全路径再执行。
  `./mvnw` 在 Windows 上会自动对上 `mvnw.cmd`，同一份 `adone.toml` 两边都跑得动。
- **`命令不存在: None`**：`WinError 2` 的 `e.filename` 是 `None`，报错等于什么都没说。
  现在报出命令名，并分清「PATH 里没有」与「步骤目录不存在」两种情况。
- **真实原因被「解析不出测试结果」盖掉**：命令没启动起来时，`kind = "test"` 的判定
  会把 note 覆写成「适配器不认这种输出格式」，把人引到适配器上去查。现在启动失败的
  步骤保留原因，不再冒充解析失败。
- **依赖与构建产物不再进受监视树**：`node_modules`、`target`、`build`、`dist` 等
  会被裁掉。以前 `watch_roots = ["."]` 能扫出四万多个文件，回执在每次
  `npm install` / `mvn package` 后就过期，而「回执已过期」本该指向人改了源码。
  互相嵌套的 `watch_roots`（`"."` 加上几个子模块）也不再把同一个文件算两遍。
  **注意**：这会让树哈希变一次，已有回执需要重跑一次 `adone gate run`。
- **Windows 中文 locale 下解码炸掉**：`mvn` 的输出常常不是 `cp936`，
  解码异常会把「测试失败」误报成「命令跑不起来」。改为 `errors="replace"`。

## v1.3.1 — 2026-08-27

### 修

- **`adone upgrade` 改错对象**：从仓库里的 `bin/adone` 跑时按源码位置判断是 git，
  去 checkout 这份源码，PATH 上的 pipx 还是 1.2.0。现在优先覆盖 `which adone`
  指向的那一份，并用它的 `--version` 跟远端比，升完再核一次 PATH。
- **版本发现取最新**：Release / tag / 默认分支都看，装版本号最高的。
  以前没有 Release 就停在旧 tag，main 上的补丁装不到。
- **Java 覆盖率认不到报告**：不再只认 `target/site/jacoco/jacoco.xml`，
  会扫 `jacoco.xml` / `jacoco.csv` / jacoco 目录下的 `index.html`。
  `coverage.source` 对不上步骤名时，改从任意测试步骤或磁盘报告回退，
  不再因为「没解析到数字」让覆盖率门禁形同虚设。

## v1.3.0 — 2026-08-27

### Java / JVM 适配器

接入的 Java 团队配了 `kind = "test"` 的 `mvn test`，适配器却退回无能力基类，
解析不出 Surefire 输出，门禁把「全部通过」判成「解析不出」。这一版补上。

- **内置 `java` 适配器**：认 `pom.xml` / `build.gradle[.kts]`，Maven 与 Gradle
  （`./mvnw` / `./gradlew` 优先），JUnit 4/5 与 TestNG。用例名规范形式是
  `CalcTest#testAdd`，带 `@DisplayName` 时两种写法都能对上契约与抽查。
- **JUnit XML + 新鲜度**：控制台只有汇总数，逐条名字从 surefire / failsafe /
  Gradle `test-results` 的 XML 读。用步骤开始时间丢掉上一轮残留报告；
  XML 合计与控制台对不上时只给计数、不给名字——抽查标未评估，不标通过。
- **JaCoCo、Spring 路由、JPA 表名**：覆盖率从 `jacoco.xml` 读；
  `@GetMapping` 等与类级 `@RequestMapping` 前缀拼接；抽取器新增 `jpa_tables`。
- **`adone detect --merge`**：给已经配好的项目增量追加步骤和 `watch_*`，
  不冲掉 `coverage.threshold`。`--write` 仍是整份覆盖。改 `tests.adapter`
  必须显式 `--adopt-tests`，否则假绿基线与判据锁会对不上。
- **`adone upgrade`**：从 GitHub 拉最新版，识别 pipx / pip / git 三种装法并覆盖。
  没有 Release 时回退到 tag、再回退到默认分支。远端更旧拒绝降级。
  在本仓库的脏工作树上跑会被拦住。

### 修

- `coverage.source` 指向 `kind=test` 的步骤，不再误取第一步（Java 第一步可能是 spotless）。
- `adone doctor` 按步骤 cwd 解析 `./mvnw` / `./gradlew`，不再谎报「不在 PATH 里」。
- 适配器协议新增 `parse_test_run(text, *, cwd, since)`，Go / Node / Python 行为不变。

## v1.2.0 — 2026-08-14

### 审计结论也能出一页离线 HTML

`adone health` 一直能出 HTML，`adone audit` 却只落 JSON——复核结论要给人看、
要丢进聊天窗口时，还得自己转一道。这一版补上。

- **`adone audit` 每次都会写出 `.adone/audit.html`**，与 `audit.json` 同一份结论、
  同一套口吻：通过说「独立复核通过」，不通过说「实现者不能宣称完成」，
  核到哪一层就写哪一层。单文件、零外链，双击就能看。`--out` 改路径，`--open` 生成后打开。
- **`adone audit report`**：只把已有 `audit.json` 渲成 HTML，**不重跑检查**。
  还没有结论时拒绝（退出码 2），结论未通过时退出码 1。复核者不该为了出一份报告
  再抽一次、再改一次审计 ID。
- 报告底部写明本机复核不是不可伪造——不要把「独立复核通过」写成「不可能造假」。

## v1.1.0 — 2026-08-13

### 对抗检查：把复核交给另一个模型

判据一直都在磁盘上而不在会话里，所以第二个模型本来就有能力独立得出结论——
缺的只是一条命令、一个身份、一份不覆盖被审证据的结论文件。这一版补的就是这三样。

- **`adone audit`**：独立复核。与 `gate check` 共用同一套判定（口径分家等于给
  「换个命令再问一次」留后门），但**默认开抽查**（`--spotcheck` 默认 2）、
  结论写进 `.adone/audit.json` 与 `.adone/audits/*`，**不碰** `latest.json` 与证据链——
  复核者顺手覆盖被审的回执，等于把证据抹掉。口吻也是复核者的：通过时说「独立复核通过」，
  不通过时说「实现者不能宣称完成」，不替实现者宣布完成。
- **`adone audit --rerun`**：不信任那份回执时，复核者自己把门禁全量跑一遍再逐项比对——
  树哈希对不上、回执写着全绿而重跑没过、回执列着的用例名在重跑里根本没出现，都会被点名。
  重跑产物同样只落 `audits/`。
- **`adone brief`**：复核者的冷启动简报。不看聊天记录也能上手：判据在哪、现有几份契约、
  实现者留的是哪份回执、要跑哪几条命令、以及复核者不许碰的东西
  （`policy --accept`、`integrity --accept-baseline`、改配置改代码）。
- **`independent-check` 技能**（随包发布，`adone install` 渲染进 `.cursor/skills/`）：
  复核者的三条铁律（不看自述看证据、只报告不修复、不替它记账）、结论怎么读、报告怎么写。
  `verified-delivery` 相应从五段扩成六段，末段是换会话换模型的独立复核；
  `completion-gate` 加了一节「交付时把结论交给别人验」。
- **复核强度如实标注**：结论末行区分「只读证据核对 / 抽 N 条当场真跑 / 全量重跑核对」——
  三档强度写成同一句话，等于把最弱的一档冒充最强的。
- 重构：`gate.run_gate` 抽出 `execute_steps`、`check_gate` 抽出 `collect_check`，
  两条命令共用同一份判定与执行逻辑。
- README 新增「对抗检查：换一个模型来核」完整用法，并说明边界——工具不验证复核者身份，
  「换个模型、不给它实现过程」得由流程保证。

### 修

- **`.gitignore` 里的三份基线其实一直没入库**：写成 `.adone/` 会让 git 连目录都不下去看，
  后面的 `!.adone/xxx.json` 一条都不生效，而且不报错——README 让人把基线入库，
  仓库自带的忽略规则却在悄悄拦住。改成 `.adone/*` 并逐条放行三份基线，README 附上正确写法。

## v1.0.0 — 2026-08-12

第一个正式版本。此前的形态是某个项目里的一组脚本，从这一版起它是一个独立、可安装、
可被别的项目直接用起来的工具，接口（`adone.toml` 字段、回执格式、命令行）从此按语义化版本管理。

### 证据强度加固

把几条原本「无声就能走通」的绕过路径，变成「要么留下一条署名记账，要么留下明显痕迹」。

- **判据锁**（新增 `adone policy`）：把「门禁有多严」拍成快照存进 `.adone/policy-baseline.json`——
  受监视范围、每个步骤的命令与失效标记、覆盖率下限、假绿豁免名单、各类检查项条数、
  以及契约面。与假绿检测同一套路：只报放松，收紧只提示，合理的放松用
  `adone policy --accept "理由"` 署名记账。步骤命令指向仓库内脚本时，脚本内容的 sha256
  一并入快照——否则「把 `go test` 换成一个打印完美输出的脚本」这条路仍然无声。
- **回执自哈希与链**：回执新增 `seq` / `prev` / `self_hash`，链头写进 `.adone/chain.json`。
  手写一份全绿回执从此要重算自哈希、改链头、让 `prev` 追得到。升级前产生的老回执
  优雅降级为链起点，不会让已装项目一升级就全红。
- **证据强度标注**：回执新增 `evidence` 段，`gate check` 的结论与健康度报告头部都会写明
  「自述（本地跑）· 判据已锁 · 回执链完整」。字段结构为后续 CI 签名留好了位置。
- **抽查真跑**（`adone gate check --spotcheck [N]`，默认关闭）：从契约绑定的用例里随机抽 N 条
  当场再跑一遍。退出码 0 但一条用例都没跑起来同样判为问题——那不叫通过，那叫没跑。
  适配器新增 `single_test_argv` 能力，go 与 python 支持，其余显示未评估而不是静默通过。
- README 新增「威胁模型与证据强度」：按无意漂移 / 敷衍作弊 / 蓄意对抗三档对手，
  逐条说明挡得住什么、挡不住什么，以及要跨过最后一档必须走 CI 的路线。

### 此前已有的能力（首个正式版一并记录）

- 完成门禁：`adone gate run` 产出与受监视代码树内容哈希绑死的回执，`adone gate check` 秒级复核。
- 假绿检测：`adone integrity` 抓删用例、加跳过、删断言、调低下限等六种「把门禁改绿」的手法。
- 验收契约与需求台账：把每条需求钉到一个用例名上，由脚本核；跨迭代的证据锚点失联即报。
- 健康度报告：六个维度汇成一页离线 HTML，只按真跑过的维度计分，跑不了的检查一律标未评估。
- 适配器：go / node / python / generic，缺能力就标未评估，绝不返回空结果冒充「查过了」。
- `adone init` / `detect` / `doctor` 零配置上手，`adone install` 把技能与 Cursor 钩子渲染进项目。
