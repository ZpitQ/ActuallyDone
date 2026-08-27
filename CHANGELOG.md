# 变更记录

版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
