# AI 已有旅行改期：使用与集中验收

<a id="assistant-trip-change-release"></a>

**已于 2026-09-19 17:39:23（北京时间）上线，17:40:24 独立只读审计通过。** 本批将自然语言已有旅行改期接入原快照、预览、明确保存和回执恢复；生产实际一户两库保持 66/9。真实模型处理合成旅行、临时浏览器交互和生产只读审计分别记录。A–D 本人真实完整端到端验收仍为 **0/4**。

## 使用路径与实际范围

1. 打开「更多 → 家庭助理」，输入「把冰岛旅行延后三天」，按需选择「使用已配置的 AI 整理」，点击「整理并预览」。明确的「搜索／查找／找一下」仍优先走本地搜索。
2. 进入后读取建议，同一页保留「改期需求」和 AI 选择；修改后可点「整理改期建议」或「重新整理需求」。默认规则也可处理支持的整日改期；使用 AI 时发送本次文字及必要候选的标题、日期、时区，不附带无关家庭清单或私人财务。
3. 同名或多个候选须明确选一趟。缺年份、日期矛盾、否定／取消、非整日单位或多个修改目标会保留原文并要求补充；例如「改到 10 月 8 日」不会猜年份。候选回选不再次调用模型。
4. 核对原旅行、原日期和建议日期，点「核对改期影响」。页面重新读取真实改期快照，核对原标题、原起止日及版本后才带入日期；默认不勾选任何联动事项。
5. 选择需要联动的准备、分段或地点，使用原「预览改期 → 确认改期」保存，再返回原旅行详情核对。响应丢失沿原操作回执只读恢复，不另建一次改期。

建议不是执行许可。相对日期按旅行本地日历天处理，固定／已订／已完成事项、当地时间和 DST 仍由原改期流程约束。来源变化要求重新整理；身份变化清除旧内容；模型失败保留需求并明确尚未改期。它不办理航司／酒店改签、不自动写云日历，也不把未知结果当成成功。

接口与维护入口：[前端流程](EXPO-ASSISTANT-TRIP-CHANGE.md) · [API 合同](ASSISTANT-TRIP-CHANGE-API.md) · [规划适配器](ASSISTANT-TRIP-INTENT.md) · [应用接线](ASSISTANT-TRIP-CHANGE-INTEGRATION.md) · [原改期引擎](JOURNEY-RESCHEDULE.md) · [发布与恢复合同](ASSISTANT-TRIP-CHANGE-RELEASE.md)。

## 固定来源与产物身份

| 身份 | 值 |
|---|---|
| 打包及 Linux 受验 source | `4c5988874d9f2b206030f6cd42864013db62454b` |
| 受验 integration | `542174b1bf76f236bfb768f1dc1ef33095790c99` |
| 合入 main | `8d35905ef14937703d0488c7190ad0fa16ae79e9` |
| 上述三者共同 tree | `8647c0398949d063b3e1a8aef10647b6a69e3a74` |
| package SHA-256 | `e2ab1963fb5a5d013d7c2cce718d764273ee55ea8e3b622be7cf4b9222d4f035` |
| manifest SHA-256 | `aa116533c6c725f8499f10bc6ac01c55645b69c659b1ae970a143eb1ae7b0696` |
| archive SHA-256 | `9761ebb9ae3b78625d50c5c8ba2dfb6463004c82e7a8c96500c4475a3abb94e6` |
| Linux 镜像 | `sha256:5fc52d2cef49c1fa854bd1e34faf23dc661b8e4ed7822b5e6763bf5798f42dce` |
| 父镜像 | `sha256:21625d6e2d9768ba48cca35100bb8bf02c1c4146afa6b7ad25b9b72cb559c1d2` |
| 固定 plan SHA-256 | `2859f1629e097acc6169574c2302ed6a740e97238ca41263e1ddb05ea65d61d6` |
| 固定候选目录 | `/opt/family-dashboard-candidates/assistant-trip-change-66-20260919-r1` |
| 包内覆盖 | 906 个源码文件、125 个 runtime 文件、23 个 Expo 导出、75 个 HTTPS 静态资源 |
| 数据变化合同 | 户内 66→66／平台 9→9，无新增表或迁移；既有分析五表允许非空 |

正式前端构建基于 `b75f4dda95c39065eb37bb9b94cf650c6befd34d`／tree `8aeedbb7a16b00362c5b104487411e6008eea6d7`。浏览器 R2 运行于测试器修订 `d37149c44b743677d896bdfa6773ff1d152e1e0b`／tree `73833f917758a1e6abb35b59adfe3bb6495fce6c`，显式复用前述构建。这些历史 head 与最终 source 并非同树：独立组合审查核对全部 117 个构建输入、23 个导出及业务运行字节与已测版本一致；新增差异限已审测试器、发布工具和文档。不是再次构建或再次运行全部浏览器。

## 分段验证与失败历史

各行是独立范围，不把重叠用例、三次模型尝试或不同阶段数量相加成一次端到端通过。

| 阶段 | 实际结果 | 能证明及不能证明的范围 |
|---|---|---|
| 正式 Expo 构建 | 独立 checkout 全新 `npm ci`、产品与测试 TypeScript 检查、24/24 Node 行为测试、Expo web 导出均退出 0 | 依赖非 junction；环境禁用 dotenv、无 ambient Expo public 变量；构建前后输入一致。该次构建有 23 个导出，不是本人设备验收 |
| 模型第 1 次 | 真实提供方一次请求，返回 JSON 后被严格解码拒绝，API 502；未保存 | 首次未保存 advisory 原文，不能单凭此轮断言具体字段原因 |
| 模型第 2 次 | 单独授权的一次诊断请求，API 502；原业务状态不变 | 确认 `shift_days` 同时返回推算 `startDate`，违反互斥字段合同。未丢弃字段或放宽解码 |
| 模型第 3 次 | 提示词修订后，一次提供方调用／一次 HTTP，API 200 ready | 真实 `nvidia`／`us/azure/openai/gpt-4o-mini`，仅合成旅行和临时 DB；新快照→明确选择准备事项→原预览／保存→原回执重放→应用重启读回通过。不是本人真实旅行或真实云日历 |
| 浏览器 R1 | 前两组通过，整轮失败 | 第三组身份切换回调未完成时，测试器提前注销路由；stdout 保留 `Route is already handled!`，最终结果也保留未完成三组的断言失败 |
| 浏览器生命周期修订 | 9 项聚焦回归通过 | 两项真实 Edge／loopback 路由检查及七项临时 Git 构建适用性检查；完成标记移至回调与 fulfill／abort 成功后，不掩盖异常、不修改产品响应 |
| 浏览器 R2 | 三组全部通过 | 临时 Flask／SQLite／HTTPS／Edge 的真实业务 HTTP；①改期与已提交响应丢失恢复、重启读回；②多候选、缺年、过期票及来源变化；③搜索优先、真实会话切换后清除旧建议。模型／云调用及生产写入均为 0 |
| 视觉检查 | Root 已查看 R1 的 390px 和 1280px 两张稳定截图 | 原文、原／新日期、尚未改期状态和入口可读，所见视口无观察到的横向裁切；不是 R2 全页视查，也不是实体手机或电视验收 |
| Linux 正式镜像验证 | **448/448，通过；0 skip、0 failure、0 error** | 精确十模块 selection、JUnit 身份及加载 runtime 散列相互绑定；临时容器、测试命令与外层命令均退出 0，不访问生产 |
| Linux 数据保全演练 | 两户三库 66/9，五张分析表预填数据；新 app 实际启动后全组一致 | 完整停写备份、全部行／schema／序列及 marker 验证通过。合成 marker 被明确替换，`exactProductionControllerProgram=false`；不声称完整生产控制器原样演练，也不代替生产本次备份 |

适配器早期审查曾发现否定、取消、非整日、日期更正和多目标被误判为 ready；修订采用统一语义阻塞，并保留正向模型目标辅助。提示词修订只强化各 `change.kind` 的互斥字段及完整 null 示例；实际失败样本仍被严格拒绝，原文否定／歧义和权限边界未放宽。各组件、接线、提示词、测试器和发布工具均保留非作者审查记录。

## 原件索引

以下为私有本地证据目录，不把合成请求原文、选票、截图或数据库纳入 Git：

- `A`：`C:/Users/caesarf/Documents/Codex/family-dashboard-access`。
- `R`：`A/worktrees/assistant-trip-change-release/test-results/assistant-trip-change-final-reviews-r1`，保留分轮原件和来源索引；下表未另标时相对该目录。
- Linux 下载原件另在 `A/assistant-trip-change-linux-originals-r1`；main 同树记录在 `A/assistant-trip-change-main-merge-r1.json`。

| 原件 | SHA-256 |
|---|---|
| `fresh-expo/build-evidence.json` | `e2a2377c6e2acb7932828ad0d05e5ec75092a37ea263c0c2335bf9ed31f8829f` |
| `real-model/attempt-1/result.json` | `4d2f58b13b3f81dddd56abc9384b6be85d5ceb942bbba79279a348382a9a5b9f` |
| `real-model/attempt-2/result.json` | `0bbc9c93e6e88e6279b5d46b8d60b0940b2ca116a5a97f4d6bbb987f459dab8e` |
| `real-model/attempt-3/result.json` | `5f4cbe0798bab6f0f91cc1b3949f851608464c3f9179fa8400b1a955486f2f8c` |
| `browser/r1/result.json` | `63adc4daf11594dd309407d044b48dcad574ab0eecafe2502fdc5c157b75d835` |
| `browser/r2/result.json` | `16c984fd7aa05ac2d527686d7fbab405710a203d53ee710997bf2fa9978e9e27` |
| `root-records/assistant-trip-change-browser-root-visual-r1.json` | `14b32bd1c5d1ee70d1fbeda771a797ab443ff5d71338719962eebac62db7a4a3` |
| `component-reviews/assistant-trip-change-final-combination-independent-review-r1.json` | `759189ceebfb626ecdc99d95b1c5ac715876ef17a33e386f5a2014a8250b200d` |
| `linux/build.json` | `d321dbda20f3b9e672b80df3d221aa0fd028c27b4ba1d7aee303147cab13d236` |
| `linux/validation/validation.json` | `2c3c6ae8556ed79783696555ef59bb72852d467852b9a9257931a6a145cfdac4` |
| `linux/rehearsal/result.json` | `3951cbaae1e38500ae1d6f67948b7e497e5f631daa71f1e64fe73697148c703f` |
| `linux-reviews/assistant-trip-change-linux-validation-final-independent-review-r1.json` | `1c4ca3c4380d78fbefcef691a811ce56f87200e7dc87a6e39976fdd571862417` |

## 生产发布与独立读回

本批从已安装的资产分析 source `f25357f935d64774922efa68d42a2ba41bb18037`／tree `1efb6a439fd8fdd95a1af5c4958296452ccfcb71`、manifest `30d5fe729ab9c407c43d8de3fa0129acd9c1e8ec2aa3e9473c5fb5e2485cb5f4` 更新。固定计划先经非作者审查，原件在 `A/worktrees/assistant-trip-change-api/test-results/assistant-trip-change-final-plan-independent-review-r1.json`，SHA-256 `fe54165ad69aab861cb5b9ee886a47bd8af39799bc72ebf404b4f00c02558284`。

| 阶段（2026-09-19，北京时间） | 实际结果与原件身份 |
|---|---|
| stage 17:36:33 | 命令与传输退出 0，`staged=true`；stage SHA-256 `43f6739bdd046712f35c88d9e6f91ecd4e8c7eca8b6f5e3e7d89690e7933ae93` |
| activation 17:39:23 | 命令与传输退出 0，`completed=true`；activation SHA-256 `92c7bfb56b5c586a4b71e091ac334e5e43783fbf23e8744d1314693b107dc639` |
| release 目录 | `/opt/family-dashboard-releases/assistant-trip-change-66-20260919T093752056048Z` |
| 独立只读审计 17:40:24 | `PASS_INDEPENDENT_ASSISTANT_TRIP_CHANGE_PRODUCTION_READONLY_AUDIT`；报告 SHA-256 `d9788b0434e49c45cfae59d065eedae7778383c341bcc7f05521bef6fd7ce2c3` |
| 生产完整库组 | 实际 1 户、2 库；户内 66→66、平台 9→9，全部行、列、schema、序列保持；不要求分析五表为空 |
| before／after | 两份原件 SHA-256 均为 `4ba7510cc6208d1f1fdf248241066a6295b006bbaf839e0aa0a79ec7ede9934a`；逻辑摘要均为 `367fa0dfb42ff37201129d295847690be466a222686c1c67e5a02eab543c8d99` |
| 完整停写备份 | 两库备份均保留并逐库校验；备份 manifest SHA-256 `44308665047b2a8b56d9917f6fbaae04de6a007fb03f67052da8b0447b6693fd` |
| 原成员成功 marker | `d223842c531e115b21430e860ffa8e742b1fbf0616942a228d04009e66dedb93`，保持 |
| 原环境文件 | SHA-256 `a72d456815cf113b1ac0c1e032ac8c45b300ccf2cb499520c14b7f54d5314e07`，保持；不输出值 |

生产控制器完成全停写备份、真实新 app 启动及停止后全组比较，再恢复 app／sync／media／web 和备份 timer。独立审计确认 906 个安装源码、三个业务服务各 125 个 runtime 文件均匹配固定包；四服务 running、restart 0、无 OOM，app healthy，备份 timer active。三个业务服务环境键值映射与各自激活前一致；序列顺序不同，不声称原顺序逐字节相同。web 保持原容器和镜像。

正常 TLS 读回核对全部 75 个静态资源及 `/app`、`/app/assistant`、`/app/tv` 三入口；health 200、`/tv` 转向 `/app/tv`、metadata 404。既有 20 个匿名接口均拒绝访问。新 `/api/assistant/trip-change` **只执行匿名 GET，实际 401**：`postExecuted=false`、`postAuthorizationVerified=false`，不声称在生产验证了 POST、CSRF、模型或本人改期。

本地发布传输原件在 `A/assistant-trip-change-final-{stage,activate}-transport.*`；独立报告为 `A/assistant-trip-change-production-readonly-review-r1.json`。报告只返回允许的脱敏指纹投影和 receipt 原件 SHA，`databaseContentsReturned=false`、`environmentValuesReturned=false`；不是可按旧 base64 流程还原的完整 receipt／数据库归档。原生产备份和未投影回执留在固定 release 目录。

## 保留的验收缺口

A–D 本人真实完整链仍为 **0/4**。本轮仅为已有旅行改期提供可用入口和受控保存流程；本人真实旅行、真实云日历写权限／创建／改期与外部读回、实体电视仍未验收。用户当前无实体电视可测，该缺口继续保留，不以浏览器代替。真实模型的一次合成成功不保证任意中文表达都可自动理解，不能支持的需求保留原文补充或使用原手动改期。

后续纯文档交付不改变本页固定运行包。继续开发须采用新的独立分支、固定基线和非作者审查；发布工具绑定本批安装起点，不得把已消费计划当作通用更新脚本重放。
