# 开发与多 Agent 交接

**当前版本：2026-09-15 16:25:03（北京时间），镜像 `sha256:f1e4cc56979f793f32585f498fa2fca55987356bd68f67e8cc6c14f0b1b6a01d`。** 旅行执行进度、真实待同步提示及两个订单表头兼容已发布，保留此前全部模块；源码与文档数量见 [README](../README.md) 及逐文件交接清单；101 个方法／路径模板、42 张户内表及 2 张平台表。本轮无结构迁移。真实云写与其他外部验收仍按 [VALIDATION](VALIDATION.md) 单列。

当前源码与文档数量以 [README](../README.md) 及逐文件交接清单为准；接口和存储结构见 [当前索引](PLATFORM-ROUTES.md)，运行版本与验收证据见 [VALIDATION](VALIDATION.md)。

**当前开发入口：** 项目已建立独立 Git 仓库。每个 agent 使用独立分支及 worktree；先读 [项目规则](../AGENTS.md) 与 [Git 协作指导](GIT-WORKFLOW.md)。旅行资料功能仍位于独立候选分支，依赖与未验收项见 [HANDOFF](HANDOFF.md#当前候选与文件占用)；下方标有时间的批次记录不是待应用补丁。

## 财务月份、消费观察与导出开发入口

历史月份导航涉及 finance_hub.py 和 finance-hub.js/.css；来源双模式涉及 spending_observations.py、finance_source_bridge.py、finance_baseline.py、deploy/prepare-finance-source.py 与两个来源 UI；导出涉及 data_portability.py 和 data-portability.js。三条流程分别维护，不因新增消费报告而修改原资产基线或实际账本。公共文件先登记唯一编辑者，接口见 [财务 API](FINANCE-API.md)、[消费观察](SPENDING-OBSERVATIONS.md)、[导出](PORTABILITY.md)。

2026-09-15 15:10 财务增量的回归入口为 [月份 API](../tests/test_finance_import_navigation.py)、[观察 API/CLI](../tests/test_spending_observations.py)、[月份浏览器](../tests/browser_finance_import_navigation_check.py)、[观察浏览器](../tests/browser_spending_observations_check.py)、[导出保护浏览器](../tests/browser_data_portability_guard_check.py)。均使用虚构文件和临时数据库；该历史财务组合的 10 个脚本、重试观察修正、依赖复用和不计通过的导出限制见 VALIDATION。当前后续无结构变化更新必须保持 42→42 检查，不重放 15:10 的历史两表迁移。

## 家庭例行计划开发入口

模块 [household_routines.py](../household_routines.py)、[界面](../static/household-routines.js)／[样式](../static/household-routines.css)和 [ROUTINES](ROUTINES.md) 可分别维护；下方采购及更早批次测试保留历史范围。公共接缝包括 app 注册、四阶段 worker、共享副本、只读助理、清单／助理入口、index、Docker 和发布白名单。没有新环境变量、依赖或后台线程。

`register_routines(app,db,Problem,body,require_member,audit)` 必须在 assistant 和 portability 前登记；`app.extensions['household_routines'].tick()` 自建 app context，不依赖 g.actor。worker 按 `task_publish → calendar_publish → cloud_accounts → household_routines` 执行，阶段前检查 stop，已进入事务正常收尾。直接生成本地 entities，不能复用会自动写默认主清单的 add_item／task_write 路径。

`brief(con)` 仅读当前家庭共享规则和实体，GET 不补期；导出只在 includeShared:true 调用 export_shared_routines(con)，禁止 nonce、会话及完整回执进入副本。三张表在 13:43 历史首次 37→40 迁移时为空并保留原 37 表；当前线上已是 42 表，本版无结构更新使用 42→42 检查。备份覆盖全部当前内容；日期、当前实体保护、唯一期次和容量逻辑须一起维护。

在独立测试配置和临时数据库内运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_household_routines.py tests/test_routine_journeys.py tests/test_worker_shutdown.py
.\.venv\Scripts\python.exe tests/browser_household_routines_check.py
.\.venv\Scripts\python.exe tests/browser_assistant_actions_check.py
```

例行模块测试用 household_routines.today() 固定上海日期，模拟提供者和真实临时 SQLite／Flask。13:43 历史批次的模块 81、跨模块 17、完整 1154 项与三组浏览器，以及 15:10 历史批次的完整 1218 项和财务 10 组 222 项，各自只说明该批次。当前完整后端和受影响浏览器结果见 [VALIDATION](VALIDATION.md)，不累加历史专项。下一轮修改前先在 [HANDOFF](HANDOFF.md) 登记独占路径。

<a id="采购实付核对开发入口候选未上线"></a>

## 采购实付核对开发入口

以下保留 12:11:36 历史批次的 [采购实付模块及契约](SHOPPING-SETTLEMENT.md)。适用发布记录为 **2026-09-15 12:11:36**，镜像 `sha256:1167dffd3b7e234d43460442acfe0d30959370c90c7e8147a1b30baa0e2380b5`；源码清单为 **200 个文件、32 份 Markdown、40 个静态资源**，[索引](PLATFORM-ROUTES.md) 为 **98 路由、37 张户内表和 2 张平台表**。本次新增两张本人私有表，既有业务表和公共实体字段保持原契约。

后端接入为 `register_shopping_settlement(app, db, Problem, body, require_member, audit)`，`app.py` 在 `register_finance_hub()` 之后、`register_portability()` 之前调用；后者在两表均存在时调用 `export_owned_settlements(con, owner)`，只将业务白名单写入 `personal.shoppingSettlements`。无新依赖、环境变量、后台同步阶段或第三方写入。UI 公开 `window.ShoppingSettlement.open({shoppingId, transactionId, linkId})`，三个聚焦字段均可省略；采购列表和本人账本分别委托进入。身份、原页面与异步响应保护须与这两个入口一起保留。

在虚构配置和临时数据库中运行以下专项；浏览器脚本需要 Edge 与项目的 Playwright 环境，不能代替完整后端、相关浏览器及部署迁移门槛：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_shopping_settlement.py tests/test_shopping_settlement_journeys.py
.\.venv\Scripts\python.exe tests/browser_shopping_settlement_check.py
```

采购后端专项实际通过 **44 项，29.46 秒**；跨模块专项在最终后端 `4048b95c…` 上通过 **10 项，6.85 秒**，30 项依赖前后散列一致，覆盖旅行迁期、删除、图片、本人 ZIP、伴侣／电视隔离和财务口径。新采购 UI 通过 61 项，既有对账保护通过 57 项；工作台另记录 59 条页面／视口。完整组合与各报告源码范围由 [HANDOFF](HANDOFF.md) 和 [VALIDATION](VALIDATION.md) 汇总，专项数量不再叠加到完整后端计数。文件所有权按交接表分配，不能同时修改共享的 `app.py`、`static/finance-hub.js`、`static/shopping-ui.js`。

## 同步状态开发入口

同步状态模块已于 2026-09-15 10:43:53 发布：[SYNC-HEALTH](SYNC-HEALTH.md) 定义只读来源快照、本人问题筛选、共享摘要及原模块入口。无表／列／依赖变化。专项命令如下；全部验收见 [VALIDATION](VALIDATION.md)。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_sync_health.py
.\.venv\Scripts\python.exe tests/browser_sync_health_check.py
```

## 电视设置开发入口

后端白名单位于 [tv_display.py](../tv_display.py)，设备路由/读取事务由 app.py 集中维护；界面独立为 tv-display.js / .css，加载顺序见本文第 3 节。跨模块接缝和隐私见 [TV-DISPLAY](TV-DISPLAY.md)，并行文件责任见 [HANDOFF](HANDOFF.md)。以下在虚构配置与临时数据库中运行，不能替代完整后端与相关浏览器回归。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_tv_display.py tests/test_display_preferences.py
.\.venv\Scripts\python.exe tests/browser_tv_display_check.py
```

成员会话的最小回归入口（虚构配置、临时数据库与模拟提供者）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_member_sessions.py tests/test_session_refresh.py tests/test_household_spaces.py tests/test_member_session_restore.py tests/test_member_session_portability.py
.\.venv\Scripts\python.exe tests/browser_member_sessions_check.py
```

以上模块专项不能替代完整后端和受影响浏览器。12:11:36 历史批次的三组浏览器记录为 **118 项功能检查（采购 61 + 对账保护 57）**，另有 **59 条工作台页面／视口记录**；不将两类混称为 177 项功能场景。同步、投资、会话和电视的旧批次保留历史范围，不与本次相加。本地只用虚构配置与临时数据库，不运行旧生产 live_check 脚本。

**采购历史发布记录：2026-09-15 12:11:36，镜像 `sha256:1167dffd3b7e234d43460442acfe0d30959370c90c7e8147a1b30baa0e2380b5`。** Windows 完整回归为 **1035 passed / 12 skipped，共 1047 项**；Linux：**1046 passed / 1 skipped**。本次新增两张户内私有表，保留原有表和数据；完整源码、迁移与逐组浏览器范围见 [VALIDATION](VALIDATION.md)。上一轮 2026-09-15 10:43:53 同步状态版本为 993 项后端、35 张户内表，属于历史记录，不能代替本次两表迁移证据。

> 新增模块接手顺序：先读 [产品目标](PRODUCT-PLAN.md)、[平台扩展](PLATFORM.md)、[工作台界面](WORKSPACE-UI.md)和[当前路由索引](PLATFORM-ROUTES.md)，再使用下方基础模块说明。发布脚本现在只打包源码并生成逐文件 SHA-256 清单，不再生成任何密码或 `.env`；并行修改导致源码变化时保留旧包并报错。

当前交接清单的源码、文档与静态资源数量以 [README](../README.md) 及逐文件清单为准；接口与存储结构须与 [路由索引](PLATFORM-ROUTES.md) 一致，另有 WSGI 家庭入口。运行镜像与后续源码候选分别按 [交接说明](HANDOFF.md) 的状态使用。

“已实现”表示仓库已有实现，不等于真实账号或设备已验收。旅行细项、来源更新、日历时间复核与重连恢复已于 2026-09-15 02:33:28 发布；公网浏览器仍受组织策略阻断。任务模板见 [联合开发说明](HANDOFF.md)，镜像、数据保留和测试范围见 [验证记录](VALIDATION.md)。

03:11:08 历史版本发布助理“本周待处理”与日历表并发初始化保护：Windows 551 项、Linux 550 项通过，1 项因容器无 Docker CLI 跳过，行动台临时浏览器 21 场景通过。此前财务来源预览／CAS、旅行明细与时区／日期核对、对应导出字段均已发布。新增源码 `finance_source_bridge.py`、`journey_time.py` 和 `pytest.ini` 必须随交接包保留；独立副本中的后续改进仍须重新集成、验证和发布。

<a id="投资与首次电视连接候选开发"></a>

## 投资与首次电视连接开发

投资整理表导入、本人副本扩展和首次电视配对入口已于 2026-09-15 08:56:01 发布。文件所有权见 [接手说明](HANDOFF.md#当前候选与文件占用)，字段和事务规则见 [持仓导入](INVESTMENT-IMPORT.md)。使用虚构文件与独立临时数据库，禁止拿实际账单或银行账号作测试 fixture。

后端针对测试（完整 pytest 仍作为合并门槛）：

```sh
python -m pytest -q tests/test_investment_import.py tests/test_finance_hub.py tests/test_investment_import_portability.py tests/test_data_portability.py
```

新增浏览器脚本需要 Windows 的 Edge、Playwright 和项目依赖，以真实临时 Flask/SQLite 运行：

```powershell
python tests/browser_investment_import_check.py
python tests/browser_tv_onboarding_check.py
```

受影响回归包括既有账单文件/金额列/对账/工作表选择和成员会话。独立专项与最终组合完整测试必须分别注明；旧报告或通过数量不能自动当成本次组合证明。重新生成索引使用 python tests/inspect_contract.py；它只实例化临时新库。不要执行 tests/live_check.py 等生产写检查来替代测试。

## 1. 当前项目和版本管理状态

项目目录为 `C:\Users\caesarf\OneDrive - NVIDIA Corporation\Documents\AI\family-dashboard`，已建立独立本地 Git 仓库。基线为 `ad667bf2b744d707db080964c662249c7cd8b056`，默认分支 main，集成分支 codex/integration；旧旅行资料候选已按职责拆成独立功能分支。当前没有远端、托管 PR 或平台强制分支保护，审查以固定 commit 和本地报告记录。

父 AI 仓库的本机 exclude 忽略本项目，原索引保留。工作树位于维护者 `Documents/Codex/family-dashboard-access/worktrees` 下；其他机器按 [Git 指导](GIT-WORKFLOW.md) 创建自己的目录。每个任务独立 worktree，不对父 AI 目录批量暂存或清理。检查状态同时包括未跟踪文件，不能只看 git diff。

当前本机和 racknerd 是不同副本。开发路径在本机，部署目录是服务器 `/opt/family-dashboard`。生产 `.env`、SQLite 数据卷和用户已修改的密码都是运行状态，不是可随源码覆盖的模板。

每轮先核对 [当前候选与文件占用](HANDOFF.md#当前候选与文件占用)，按独立分支和 worktree 分配模块。共享文件如 journey-ui.js、finance-hub.js 的接口先协商，由集成人安排合并顺序；任务写明 base commit、允许路径、依赖提交、公共入口和集成人。

使用 Git diff 审查固定 base/head，审查通过后合入 integration；发生冲突时由集成人逐项解决并重新审查，不强行选择整份 ours/theirs。组合测试绑定实际合并提交，通过后再合入 main。散列保留为文件与归档证据，不替代 Git 历史或联合验证。

## 2. 已开发范围与文件地图

成员会话模块以 `app.extensions["member_sessions"]` 供 app/OAuth/家庭路由调用，基础初始化先建核心数据库，再登记会话；入口 `MemberSessions.open()` 由设置页打开。会话、OAuth、家庭切换共享 generation/current-session 契约，不能只替换某个 UI 文件。

下表的“接手边界”是便于分工的建议；开始并行工作前仍需由集成人明确本次文件所有权。

| 模块 | 已实现功能 | 核心文件 | 接手边界 |
| --- | --- | --- | --- |
| 应用基础 | 双成员登录、服务端会话撤销、资料、CSRF/同源、实体与冲突 | `app.py`、`member_sessions.py` | 后端集成人统一身份、schema、注册与 OAuth/家庭接缝；认证表不进个人 ZIP |
| 日程 | 今日、本周、前后 3 天；日期导航；按日数量和时段并集；全天单独计数 | `static/calendar-ui.js`、`static/calendar.css` | 纯日期计算和日程渲染可独立交给一个 Agent |
| 大屏 | 只读配对、撤销、两台电视分别设置侧重成员和视图；日程与采购自动翻页 | `app.py`、`static/app.js`、日程/采购模块 | 设备接口由后端集成，卡片播放由对应模块负责 |
| 共同待办 | 本地新建、编辑、完成/恢复、删除；旅行准备关联；云清单新建及完成/恢复回写 | `app.py`、`static/app.js`、`cloud_accounts.py` | 本地实体与云端镜像边界要一起审查 |
| 采购 | 数量、备注、预计总价、实付、最多 3 张图片；未知金额不作为零 | `static/shopping-ui.js`、`static/shopping.css` | 表单、金额汇总和图片草稿交互可独立负责 |
| 采购实付核对 | 本人 CNY 付款选择、共享字段预览确认、修订／解绑、私有回执和导出 | `shopping_settlement.py`、`static/shopping-settlement.js/.css` | 后端核对与 UI 独立负责；集成人维护入口／导出／清单；旅行迁期保留与隐私由跨模块专项覆盖，详见 [专文](SHOPPING-SETTLEMENT.md) |
| 图片存储 | 认证读取、草稿权限、JPEG 重编码、去除元数据、大小/像素/总量限制、孤立照片清理 | `shopping_media.py` | 路由和引用事务需与 `app.py` 契约联动 |
| 旅行工作流 | 多城市段、准备/采购/本地日程一体生成；签名预览、版本核对、幂等回执 | `journey_workflows.py`、`static/journey-ui.js/.css` | 保留关联实体 ID、已完成状态、采购实付和图片；和云发布负责人约定事件关系 |
| 旅行时间（02:33 发布） | 航班、住宿、活动的当地时间／IANA 时区、日期区间、夏令时与迁期核对 | `journey_time.py`、`journey_workflows.py`、`static/journey-ui.js` | 时间语义与云日历发布共同审查；固定 tzdata 版本，不能以 UTC 日期替代当地日期 |
| 家庭财务 | 公共荷包、日常预算、旅行储备、长期储蓄、待付款、出资比例、核对日期 | `app.py`、`static/app.js` | 手动快照，不能假定为自动账本 |
| 个人月度财务 | 本人收入、支出、预算和月份，服务端按当前成员隔离 | `app.py`、`static/app.js` | 不加入共享状态 |
| 资产基线 | 私有来源快照、经批准的资产/负债共享小计、日期与覆盖范围、幂等 CLI 导入 | `finance_baseline.py`、`static/finance-baseline.js`、`static/finance-baseline.css`、`deploy/import-finance-baseline.py` | 来源转换在私有目录进行；仓库只放通用逻辑和虚构测试 |
| 财务来源桥接（02:33 发布） | 白名单来源准备、本人预览、CAS 确认、缺源／日期倒退保旧和持久回执 | `finance_source_bridge.py`、`deploy/prepare-finance-source.py`、`static/finance-source-ui.js` | 稳定映射、隐私与汇总口径一并审查；不写账单、投资或公共荷包，详见 [来源桥接](FINANCE-SOURCE-BRIDGE.md) |
| 财务中枢 | 本人账单/订单导入、去重、分类、逐笔选择共同汇总；分币种预算与日期估值投资 | `finance_hub.py`、`financial_files.py`、`static/finance-hub.js/.css` | CSV/XLSX 文件校验、账本口径和投资同一负责人；不得把不同币种、订单/支付或历史资产基线简单相加 |
| 云日历发布 | 按需写权限、发布队列、读回、持续修改同步、远端冲突预览确认、暂停恢复 | `calendar_publish.py`、`static/calendar-publish.js`、`cloud_accounts.py`、`cloud_providers.py` | 与账号负责人共用进程锁；保留幂等键/ETag，避免轮询镜像双份显示 |
| 家庭空间 | 邀请创建家庭、每户独立数据库/密钥、家庭入口、个人展示偏好 | `household_spaces.py`、`static/household-spaces.js` | 路由 cookie 只选户，不授予权限；平台注册目录与所有户库一起备份 |
| 家庭助理 | 日程概览、搜索、受控清单及三步旅行简报；可选模型模式 | `home_assistant.py`、`static/home-assistant.js/.css` | 模型产物必须再次校验且由成员确认，不把个人财务或令牌作为自动上下文 |
| 工作台 | 侧栏/手机导航、页面路由、主题、密度、成员偏好、Web App Manifest | `static/product-shell.js/.css`、`static/manifest.webmanifest` | 最后加载，协调公共渲染入口；电视保持专用布局 |
| 首页布局 | 卡片排序、隐藏、恢复默认、按成员跨设备保存 | `dashboard_preferences.py`、`static/product-shell.js/.css` | 独立 revision；至少一张可见卡片；电视配置不变 |
| 待办发布 | 旅行/助理/手动本地任务发布至云清单、完成回流、冲突核对 | `task_publish.py`、`static/task-publish.js`、云适配器 | 保留本地实体 ID/负责人；不确定创建仅远端查询恢复，禁止盲目再 POST |
| 数据副本 | 本人资料/账本/投资/偏好导出 ZIP，可选已共享家庭记录 | `data_portability.py`、`static/data-portability.js` | 无伴侣私密/凭证；CSV 原币与 JSON 整数分；不是 SQLite 恢复包 |
| 第三方账号 | Microsoft / Google 绑定与登录、来源选择、刷新令牌、授权错误分类、成员归属 | `cloud_accounts.py`、`static/accounts-ui.js` | OAuth、账号与同步协调由一个后端负责人处理 |
| 服务商适配 | Graph、Google Calendar / Tasks、分页、时间归一化、任务版本校验 | `cloud_providers.py` | 适配器 Agent 通过稳定的 provider 接口交付 |
| 同步状态 | 逐来源新鲜度、家庭聚合和本人发布问题 | `sync_health.py`、`static/sync-health.js/.css` | 不探测提供者、不修改队列；不将账户/来源名称塞入共享摘要，入口交集成人 |
| 家庭例行计划 | 日／周／月模板、固定节奏、单当前项、暂停／跳过／历史、助理只读提示 | `household_routines.py`、`static/household-routines.js/.css` | 共享规则但签名限本人；三空表初始化，本地生成、每期另行云发布 |
| 同步进程 | 最多两户并行，按待办发布→日历发布→云来源→本地例行执行；任务约 30 秒、日历约 60 秒，到期处理并退避 | `sync_worker.py`、`cloud_accounts.py`、两个发布模块 | 不在 Web 请求中启动第二套轮询线程；同户不重入，不能用主家庭健康代表全部家庭 |
| ICS 兼容入口 | 文件导入、重复事件展开、去重与有界数量校验 | `app.py` | 兼容路径，不是 Apple 实时连接器 |
| 部署与维护 | Docker、Gunicorn、Nginx、HTTPS、备份、证书续期、发布包和 OAuth 配置工具 | `Dockerfile`、`compose.yaml`、`deploy/` | 发布只由指定集成人操作 |
| 文档和测试 | 需求、运维、接入指南、后端/日期/浏览器回归；pytest 限定 tests 收集范围 | `docs/`、`tests/`、`pytest.ini` | 文档要区分实现、测试和未完成集成；不要删除测试收集配置后误收集环境或结果目录 |

账号接入细节见 [ACCOUNT-SYNC](ACCOUNT-SYNC.md) 和 [SYNC-DESIGN](SYNC-DESIGN.md)。采购、日程和资产基线的口径见 [本轮功能说明](FEATURES-20260914.md)。

## 3. 前端不是打包框架项目

前端是同源静态 HTML、CSS 和原生 JavaScript，没有 React/Vue、Node 构建流程或 npm 运行依赖。Node 用于 JavaScript 语法和纯函数测试。新增模块需要同时检查 HTML 引用、全局依赖、Docker 复制范围和发布白名单。

`static/index.html` 当前通过 `defer` 按以下顺序加载脚本：

1. `app.js`：通用状态、请求、表单、弹窗、卡片入口、全局操作分发。
2. `accounts-ui.js`：登录页第三方入口、账号绑定、来源选择及错误提示。
3. `calendar-ui.js`：导出 `window.CalendarViews`。
4. `shopping-ui.js`：导出 `window.ShoppingUI`。
5. `finance-baseline.js`：导出 `window.FinanceBaseline`。
6. `finance-source-ui.js`：02:33 已发布，导出 `window.FinanceSourceUI`，由本人基线页进入候选预览。
7. `journey-ui.js`：导出 `window.JourneyUI`。
8. `calendar-publish.js`：导出 `window.CalendarPublish`；复用财务中枢工作区 CSS。
9. `task-publish.js`：导出 `window.TaskPublish`，处理待办页/旅行/助理的显式发布入口。
10. `finance-hub.js`：导出 `window.FinanceHub`。
11. `investment-import.js`：导出 `window.InvestmentImport`，由财务中枢进入持仓文件预览与确认。
12. `home-assistant.js`：家庭助理工作区。
13. `household-spaces.js`：家庭入口与邀请流程。
14. `data-portability.js`：导出 `window.DataPortability`，处理成员设置页下载。
15. `member-sessions.js`：导出 `window.MemberSessions`，处理本人登录设备与会话撤销。
16. `tv-display.js`：导出 `window.TVDisplay`，手机按设备设置及电视实际排布。
17. `sync-health.js`：导出 `window.SyncHealth`，只读问题弹窗与局部状态指示器。
18. `shopping-settlement.js`：导出 `window.ShoppingSettlement`，只在成员主动选择后核对采购实付。
19. `household-routines.js`：导出 `window.HouseholdRoutines`，共享计划、预览、确认、历史与原事项返回。
20. `product-shell.js`：最后加载，接管成员工作台、导航和主题；电视分支调用 `TVDisplay.applyBoard()`。

`app.js` 在 `DOMContentLoaded` 才调用 `boot()`，此时上述模块已执行。不要提前执行 `boot()`，也不要把依赖公共状态的模块改成 `async` 加载。原生顶层 `let` / `const` 能被后续脚本引用，但不一定是 `window` 的属性；用 `window.data` 替代 `data` 会改变行为。

CSS 顺序为 `style.css → calendar.css → shopping.css → finance-baseline.css → journey-ui.css → finance-hub.css → home-assistant.css → product-shell.css → member-sessions.css → investment-import.css → tv-display.css → sync-health.css → shopping-settlement.css → household-routines.css`，最后一项为例行计划模块样式。工作台样式覆盖基础布局，随后加载的模块样式使用各自范围内的选择器。电视外观只作用于电视和其预览，不覆盖成员主题。工作台接管成员端渲染；原 `renderBoard()` 仍用于电视。需要稳定存在的行为应使用文档级事件委托或模块的重新绑定入口，并避免重绘清空未保存的弹窗。电视字段及接缝见 [电视布局契约](TV-DISPLAY.md)。同步摘要由 updateFooter() 调用 SyncHealth.refreshIndicators() 局部更新，same revision 不等于状态未变；详情只为当前成员读取，见 [SYNC-HEALTH](SYNC-HEALTH.md)。

公共依赖主要包括：

| 依赖 | 用途和注意事项 |
| --- | --- |
| `user`、`csrf`、`data`、`focus`、`isTV`、`isDemo` | 登录身份、共享快照与显示状态；私有财务不应塞进 `data` |
| `api()`、`write()`、`refresh()` | 同源 `/api` 请求、CSRF、JSON 写入和状态刷新；避免各模块另造身份/错误处理 |
| `esc()`、`money()`、`person()`、`ownerOptions()` | HTML 转义、金额和人物展示；来自远端的标题、备注、账号名同样必须转义 |
| `openModal()`、`closeModal()`、`bindForm()`、`field()` 等 | 公共弹窗与表单；保存失败应保留草稿 |
| `activeManager` | 完成/恢复后重绘当前清单的路由状态；编辑器打开时不要保留错误 manager |
| `canEdit()` | 前端操作可用性；实际权限仍由服务器验证 |

`calendarCard()`、`shoppingCard()` 和 `financeCard()` 是核心集成接缝，分别调用 `CalendarViews.renderCard()`、`ShoppingUI.renderCard()`、`FinanceBaseline.decorateCard(walletCard())`。`manage()` / `editItem()` 把对应页面交给模块处理。`accounts-ui.js` 保留全局账户管理函数，并导出 `window.AccountsReturn`，负责成员／家庭上下文核验和显式返回意图；日历与待办发布模块依赖该对象，须保持当前 `defer` 加载顺序，见 [连接返回契约](CONNECTION-RETURN.md)。

通用 `data-action` 点击分发在部分导航操作后要求 `canEdit()`。只影响视图、不修改数据的操作使用模块自己的 `data-calendar-*` / `data-wealth-summary` 等委托，避免被通用写权限守卫吞掉。私有数据的请求仍只应发生在本人明确打开私有页面时。

前端每 10 秒请求共享快照，以共享 `revision` 判断是否重绘；另有时钟、每分钟展示重绘及大屏播放定时器。成员日程视图按本机账号保存在 `localStorage`；电视读取服务端 `display.calendarView`。自动刷新不得清空尚未保存的表单或正在上传的图片草稿。

## 4. 本地环境与安全测试

运行依赖以 `requirements.txt` 为准。生产 Docker 使用锁定 digest 的 Python 3.12 镜像；Windows 本地已使用 Python 3.14 验证。下列命令在项目目录执行，创建的虚拟环境只服务于本项目：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest playwright
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/test_calendar_views.js
```

本轮 `requirements.txt` 将 `tzdata==2026.4` 作为固定运行依赖；Docker 设置 `PYTHONTZPATH=""`，使标准库 zoneinfo 使用这一包的时区数据，避免宿主系统数据库版本不同。不要另外无版本升级 tzdata。pytest／Playwright 测试工具不属于生产依赖锁；历史工具版本以 [VALIDATION](VALIDATION.md) 为准。`pytest.ini` 的 `testpaths=tests` 且排除 `.venv/test-results/.git/__pycache__`；`test_*.py` 使用隔离数据库／模拟服务商，不自动执行 `*_check.py` 浏览器脚本。测试前确认当前 shell 没有注入真实服务商凭证，尤其不要启动指向生产卷的开发服务器或同步进程。

新功能的推荐浏览器回归入口：

```powershell
.\.venv\Scripts\python.exe tests/browser_product_shell_check.py
.\.venv\Scripts\python.exe tests/browser_product_workflows_check.py
.\.venv\Scripts\python.exe tests/browser_journeys_check.py
.\.venv\Scripts\python.exe tests/browser_financial_files_check.py
.\.venv\Scripts\python.exe tests/browser_calendar_publish_check.py
.\.venv\Scripts\python.exe tests/browser_finance_source_check.py
.\.venv\Scripts\python.exe tests/browser_journey_details_check.py
.\.venv\Scripts\python.exe tests/browser_journey_timing_review_check.py
```

这些脚本目前显式使用本机 Microsoft Edge 的 `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`。安装 Playwright 包不等于该浏览器路径可用；Linux 或不同安装位置需要先调整测试启动配置。截图和 JSON 输出在 `test-results/`，不进入生产镜像。

| 测试 | 当前覆盖 | 执行范围 |
| --- | --- | --- |
| `test_app.py` | 登录、CSRF、共享 CRUD、409、个人月度财务、电视、ICS、旅行关系 | 临时 SQLite |
| `test_cloud_accounts.py`、`test_cloud_review.py` | 绑定、归属、同步事务、锁、回写及源删除边界 | 模拟远端与临时 SQLite |
| `test_cloud_providers.py` | 服务商响应、分页、日期、任务条件写 | 模拟 HTTP |
| `test_oauth_config.py` | OAuth 配置工具及 Compose 转义 | 隔离配置；部分检查需要 Docker CLI |
| `test_microsoft_binding.py`、`test_oauth_diagnostics.py` | Graph scope 归一化、可选共享日历权限、安全错误分类 | 模拟授权 |
| `test_shopping_media.py` | 图片解码、限额、上传与引用权限、事务回滚 | 临时 SQLite 和生成图片 |
| `test_finance_baseline.py` | 汇总核对、部分覆盖、幂等、字段白名单、成员隔离 | 虚构财务数据 |
| `test_finance_source_bridge.py` | 五类适配器、run／来源核验、缺源和日期保旧、预览无写入、CAS／重放、回执与隐私 | 本轮本地增量，合成源文件和临时 SQLite |
| `test_display_preferences.py` | 电视设置、迁移兼容、revision、只读权限 | 临时 SQLite |
| `test_calendar_views.js` | 时区、周边界、时间并集、全天和轮播覆盖 | Node 纯函数 |
| `test_household_routines.py`、`test_routine_journeys.py` | 日历数学、预览/CAS、回执、并发、缺失/跳过、旅行采购和模拟云回流、只读助理及共享导出 | 临时多家庭；不读私人输入或访问真实服务商 |
| `test_household_spaces.py`、`test_platform_backup.py` | 家庭 cookie/会话隔离、目录缺失拒绝补建、完整组备份与保留 | 临时多数据库 |
| `test_journey_workflows.py` | 预览、关联事务、迁期、实体版本、幂等、权限 | 虚构旅行与临时 SQLite |
| `test_finance_hub.py`、`test_financial_files.py` | 私有账本、退款转账、多币种、幂等、CSV/XLSX/编码与文件边界 | 虚构文件和临时 SQLite |
| `test_home_assistant.py` | 草案归属、白名单、确认、模型上下文边界 | 模拟模型与临时 SQLite |
| `test_calendar_publish.py` | 授权升级、幂等恢复、ETag 冲突、远端删改检测、暂停恢复与去镜像 | 两个平台的模拟 HTTP，禁止真实云端写入 |
| `browser_calendar_publish_check.py` | 旅行入口、目标日历、缺权限、发布队列、暂停恢复、冲突核对 | 临时 Flask 与模拟云端，真实本地浏览器 |
| `browser_product_shell_check.py` | 新版工作台导航、主题、密度和手机布局 | 临时服务与虚构数据 |
| `browser_product_workflows_check.py` | 助理草案确认、财务预览入账/核对、投资、伴侣隐私与演示写入边界 | 临时 Flask 和隔离数据库 |
| `browser_journeys_check.py` | 多段旅行、预览应用、迁期、关联任务与采购 | 临时 Flask 和虚构旅行 |
| `browser_financial_files_check.py` | 实际上传表单解析 XLSX 与 GB18030 文件 | 临时 Flask 和生成文件 |
| `browser_finance_source_check.py` | 私人候选文件预览、确认、失败保留、CAS 冲突重预览、幂等和成员／TV 隔离 | 02:33 版本验证：完整临时 Flask、合成候选和真实浏览器 |
| `browser_journey_details_check.py` | 航班／住宿／活动表单、跨日期变更线、夏令时、全天区间和迁期冲突 | 02:33 版本验证：虚构旅行与临时 Flask |
| `browser_journey_timing_review_check.py` | 云日历时间语义待核对、只读预览、显式确认及原远端 ID 更新 | 02:33 版本验证：临时 Flask 与模拟 Google／Microsoft，禁止真实云端写入 |
| `platform_live_check.py` | 发布后页面与静态资源哈希、匿名权限和布局 | 正式 HTTPS 只读检查；拦截所有非 GET/HEAD 请求，不读取凭据或登录 |

以下旧脚本需要先阅读和改造，不作为默认回归命令：

| 脚本 | 实际行为与限制 |
| --- | --- |
| `browser_features_check.py`、`browser_calendar_check.py`、`shopping_ui_check.py` | 早期功能/日程/采购布局验证；部分选择器针对旧界面，先按新版工作台适配，不能直接以旧断言失败判定新版回归 |
| `browser_check.py` | 依赖事先存在的 `127.0.0.1:8765` 测试服务，使用固定测试密码并新建任务，不自建临时服务；先确认该端口对应隔离数据库 |
| `live_check.py` | 直接连接正式 IP、读取本地 `.env` 的旧初始密码、创建/修改任务、配对/撤销电视，并通过 SSH 重启生产 app。现在默认主清单可能指向真实 Microsoft To Do，临时任务也可能成为云端写入；不要盲跑 |
| `accounts_live_check.py` | 访问正式域名且断言 Microsoft/Google 都未配置；这个断言已不适用于当前部署。还会访问伪造回调作验证；不能用历史结果代替现在的账号验收 |
| `domain_check.py` | 访问正式域名，尝试 `.env` 中可能过时的初始密码，并打开 `/tv` 创建待配对设备。不是完全无副作用的匿名检查 |

模拟授权测试通过不能替代成员本人完成 OAuth、实际选中来源、远端读写及刷新令牌验证。视口测试通过也不代表已在两块实体电视和用户手机浏览器上验收。

## 5. 多 Agent 协作方式

每个 Agent 的每个任务都使用独立 `codex/<agent>-<task>` 分支和 worktree；禁止共用同一物理工作目录。开始时核对 `git rev-parse --show-toplevel`、`git branch --show-current`、HEAD 和干净状态。仓库主分支为 main，集成分支为 codex/integration，命令与固定提交审查见 [Git 指导](GIT-WORKFLOW.md)。

1. 集成人持有公共后端、HTML 加载顺序、跨模块样式、依赖、发布脚本以及最终部署。
2. 专项 Agent 持有互不重叠的模块文件和相应测试，先交付接口契约，再实现。
3. 涉及跨文件依赖时，把请求发送给文件拥有者；不要悄悄修改不归自己持有的文件。
4. 审查 Agent 默认只读，审查明确的 base/head commit，用具体文件、行为、证据说明问题；修复在原任务分支形成新提交并再次审查。
5. 审查通过后集成人合入 integration，执行对应组合测试和再次审查后才合入 main；部署另按已审查发布清单执行。失败候选保留分支，不通过复制文件混入主工作树。

本项目可采用的分工示例：

| 角色 | 独占文件示例 | 交付接口 |
| --- | --- | --- |
| 集成人 | `app.py`、`static/app.js`、`static/index.html`、`Dockerfile`、`compose.yaml` | 路由接入、主状态、部署与验收 |
| 日程 Agent | `static/calendar-ui.js`、`static/calendar.css`、`tests/test_calendar_views.js` | `CalendarViews` 保持既有接口；增加字段先协商 |
| 采购 Agent | `static/shopping-ui.js`、`static/shopping.css`、`tests/shopping_ui_check.py` | `ShoppingUI` 和预算/照片表单契约 |
| 数据 Agent | `finance_baseline.py`、对应后端测试 | 白名单、幂等和字段校验；真实导入由集成人执行 |
| 财务 Agent | `finance_hub.py`、`financial_files.py`、`static/finance-hub.js/.css`、对应测试 | 导入预览/确认、金额与币种口径、隐私、预算和投资 |
| 旅行 Agent | `journey_workflows.py`、`static/journey-ui.js/.css`、对应测试 | 稳定 event ID、版本、旅行任务采购关联；`JourneyUI.open(id)` |
| 账号与云发布 Agent | `cloud_accounts.py`、`cloud_providers.py`、`calendar_publish.py`、`static/calendar-publish.js` | 写权限升级、共享账号锁、幂等/ETag、远端去镜像；与旅行 Agent 协议先行 |
| 例行计划 Agent | `household_routines.py`、专项与 `ROUTINES.md`；UI和跨模块测试另设独占人 | 规则与实体保护、日期／容量、回执与共享白名单；公共 app/worker/助理/导出接缝交集成人 |
| 平台 Agent | `household_spaces.py`、`sync_worker.py`、`deploy/backup.py`、对应测试 | 逐户密钥、数据库目录、调度和备份 manifest；部署配置交集成人 |
| 助理 Agent | `home_assistant.py`、`static/home-assistant.js/.css`、对应测试 | 输入范围、草案接口、确认动作，不直接写远端或金融账户 |
| 工作台 Agent | `static/product-shell.js/.css`、工作台浏览器测试 | 页面路由、主题、密度与手机布局；不同时接管其他 Agent 的业务弹窗 |

开始前写清任务目标、base commit、分支/worktree、允许路径、依赖提交、接口与交付标准。交付 head commit、diff、真实测试及未验证范围，文件散列可作为额外证据。新 Agent 用虚构 fixture 即可开发，不需要生产密钥或整份个人财务仓库。

可复制的交接提示词：

> 在 family-dashboard 项目继续开发【功能】。先阅读 README、docs/DEVELOPMENT.md、docs/PLATFORM.md、docs/PLATFORM-ROUTES.md 及相关专项文档和源码。你只拥有【具体文件清单】，其他文件由集成人修改。当前验收标准是【可观察行为】；公共接口为【输入/输出及错误语义】。保持每户两成员与跨户隔离、电视只读、个人财务仅本人、多币种分别计算、金额整数分及 revision/ETag 冲突保护。使用虚构数据和隔离数据库，不读取/提交真实财务来源，不改生产 .env，不发布。完成后返回修改文件、接口变化、测试命令与结果、未覆盖项及需要集成人完成的操作。涉及源码打包的文件在集成人宣布 freeze 后不再修改，发现问题先通知集成人。

## 6. 变更检查单

- 读取当前源码和最近验证记录，区分产品需求、历史方案及实际已上线行为。
- 增加实体字段时确定默认值、旧记录兼容、`null` 与 `0` 的含义、共享/私有范围，并同步数据与接口文档。
- 写操作保留 CSRF、同源校验、角色限制和 revision。日历读取授权不能推断为写授权；旅行发布必须经过独立授权/预览确认队列及 ETag 校验，云任务保留现有受限回写接口。
- 跨表变化使用事务，失败时不发布半套记录；来源取消、旅行删除、照片解绑同时验证关系清理。
- 共享 payload 使用服务端白名单；敏感字段不能靠 CSS 隐藏，不能放在 demo、static、截图 fixture 或普通日志。
- 前端保存失败保留草稿；处理 409/401/403/429；未知金额、同步失败和数据日期要能被用户理解。
- 修改卡片布局时检查手机无全局横向溢出，以及 720p、1080p、4K 的今日/周/前后 3 天；完整标题、地点及大额数字仍需可读。
- 新增 Python 文件同时检查 `Dockerfile` 的 `COPY` 和 `deploy/prepare_release.py` 发布白名单；新增静态模块检查 script/CSS 顺序。
- 运行与变更相关的测试，记录实际命令、通过/失败/跳过和边界。通过后没有新修改或疑点，无需重复同一套检查。
- 发布前备份平台注册目录和全部家庭，核对完整 manifest；保护 `.env` 和数据卷。首次部署和更新见 [DEPLOYMENT](DEPLOYMENT.md)，日常维护见 [OPERATIONS](OPERATIONS.md)。交付时记录源码/镜像版本和逐户实际状态。

## 7. 故障排查入口

| 现象 | 优先检查 | 证据边界 |
| --- | --- | --- |
| 白屏或某个卡片缺失 | 浏览器 Console、静态资源 404、脚本顺序、`app.js` 调用的模块 API | HTML 下载成功不代表 JS 完成启动 |
| 数据更新后界面没变化 | 写请求状态、实体与 meta revision、10 秒轮询、`activeManager`、电视 display 偏好 | 不要只修改 DB JSON 而忘记状态版本 |
| 409 保存失败 | 读到的 revision 与当前数据库版本，是否存在另一成员/同步并发修改 | 刷新后让用户重试，不自动覆盖新版本 |
| Microsoft 绑定失败 | `cloud_accounts.py` 安全诊断阶段、固定错误类型和数值 AADSTS、回调 URL、应用配置 | 不输出 code/state/token/secret/邮箱或服务商错误全文 |
| 云同步不更新 | worker 运行状态、来源 `last_success` / `next_attempt` / `failures` / `error`、账号是否需重授权 | 某个来源成功不能证明所有日历已覆盖 |
| 云任务创建/勾选失败 | 主清单或指定来源、远端版本、账号锁、`task_write()` | 重复创建可能产生重复远端任务，先核实原请求结果 |
| 图片上传失败 | 413/429、浏览器转换、输入像素/格式、Nginx 上限、图片总配额 | 不记录或回显图片原始 data URL |
| 财务小计不一致 | `sourceDigest`、导入日期、来源日期、逐项包含标记、币种和排除项 | 未核实余额或估值不能补零后算净资产 |
| 来源候选 400／409（02:33 已发布） | [来源契约](FINANCE-SOURCE-BRIDGE.md)、稳定 ID／legacyId、业务日期、run 完整性和目标 revision/sourceDigest | HTTP 3 MB 不等于候选内容 3 MB；规范化候选须控制在约 1.95 MB 以下。缺源／缺映射／日期倒退保留旧基线，不能删旧记录绕过 |
| 电视权限错误 | 设备是否批准/过期/撤销、`household_tv`、`X-Display-Mode: tv` | 同浏览器成员 cookie 不应让电视写入 |
| 更新 Nginx 配置无效或 502 | 实际容器内配置、bind mount 的旧 inode、app 地址改变后 web 是否重建 | host 文件更新不代表容器已读取新文件 |

## 8. 已有边界与后续路线

以下为接手时的已知边界，不代表已承诺本轮继续实现：

| 范围 | 当前状态 | 后续开发需先明确 |
| --- | --- | --- |
| 日历连接 | Microsoft / Google 所选日历轮询读取；旅行发布支持额外写权限、队列与冲突核对；ICS 保留 | 新写入需真实账号验收；Apple 实时连接与变更推送未实现 |
| 共同清单 | Microsoft To Do 或 Google Tasks 主清单；本地任务持续发布与完成回流 | 新发布路径有版本/冲突核对且需真实验收；普通云镜像只回写完成状态；Apple 提醒事项未接入 |
| 财务 | 公共荷包手动核对；CSV/XLSX 账单订单、私有账本、多币种预算、手动投资及持仓整理表导入已部署；来源候选 CLI／本人预览 CAS 已发布 | 小荷包／金融账户自动 API、证券实时行情和定时刷新基线未接入；真实来源须先补稳定映射与核对日期，不能从合成测试推断数据覆盖 |
| 净资产 | 后端区分 complete/partial；当前共享卡片以“待完整核对”展示现有部分数据 | 引入完整基线前需同时补齐前端 complete 展示分支和验收 |
| 采购 | 预算、实付、参考图片在看板内保存 | 不自动产生荷包支出；图片解绑后的回收是后续上传触发，无独立管理界面 |
| 通知与离线 | 在线轮询及页内提示 | 没有 WebSocket/SSE、原生推送或离线编辑队列 |
| 账号/租户 | 邀请制多家庭，每户固定两成员，独立数据库与密钥；当前最多 30 户 | 无开放匿名注册、套餐计费、任意成员数量或通用角色管理；扩大容量需验证资源和隔离 |
| 运维 | 单台服务器、Docker、同机 SQLite 备份、证书续期；两户合成 Docker 恢复已完成 | 异地加密备份、生产覆盖恢复、跨机恢复及高可用未完成 |
| 工程协作 | 独立 Git 仓库、各 agent 分支/worktree、源码测试和配套文档 | 无远端 PR/强制分支保护、CI/CD、正式 schema 版本管理或 OpenAPI 自动生成 |

变更这些边界时，先更新合同和测试，再扩展实现；不要把路线图条目写入“已完成”。

## 旅行草稿与会话专项

新增 `tests/test_session_refresh.py`（23 项，已计入全量）、`tests/browser_journey_import_guard_check.py`（31 项）、`tests/browser_journey_draft_guard_check.py`（32 项）与 `tests/browser_journey_confirm_guard_check.py`（5 项）。三份浏览器专项须使用后端真实默认 `SESSION_REFRESH_EACH_REQUEST=False`，不能用测试覆盖掩盖遗漏的后端补丁。普通预览和已发提交之后的每个读取阶段均需保护当前界面；已发写请求不因关窗撤销，重试仍用原幂等键。

确认专项通过真实 HTTP 延迟分别挂起身份核对和预览响应，覆盖新建重新预览、409 后基于最新版本重新预览及 503 重试。旧确认在等待与失败期间保持禁用，普通按钮点击和 Enter 均不发送旧凭证；成功后使用新凭证，仅新增一次持久操作，既有实体 ID 保持。该测试不替代服务端权限、版本及幂等校验，也不声称取消已经发出的提交。

## 05:47:43 导入指引专项

新增 `tests/test_journey_examples.py` 和 `tests/test_finance_amount_columns.py` 已计入完整后端回归。前者校验下载、预览无写、确认和稳定关联；后者校验物理列选择、签名、旧无编号指纹、重选冲突和权限。旅行示例下载与金额选择浏览器专项使用临时 Flask/SQLite/Edge，分别为 8 与 13 个场景。

回归命令见 README 新增四行；本轮四组重跑与六组同源码沿用按下表区分，各组不可互相替代：

| 浏览器专项 | 范围 | 通过场景 | 证据批次 |
|---|---|---|---|
| `tests/browser_journey_import_guard_check.py` | 旅行导入保护 | 31 | 沿用同源码证据 |
| `tests/browser_journey_draft_guard_check.py` | 相邻草稿与提交返回 | 32 | 沿用同源码证据 |
| `tests/browser_journey_confirm_guard_check.py` | 重新预览确认 | 5 | 沿用同源码证据 |
| `tests/browser_journey_details_check.py` | 旅行时间细项 | 10 | 沿用同源码证据 |
| `tests/browser_journey_return_budget_check.py` | 旅行返回与预算 | 23 | 沿用同源码证据 |
| `tests/browser_journey_examples_check.py` | 旅行示例下载 | 8 | 沿用同源码证据 |
| `tests/browser_finance_amount_columns_check.py` | 账单金额列选择 | 13 | 本轮重跑 |
| `tests/browser_financial_files_check.py` | 现有文件导入 | 5 | 本轮重跑 |
| `tests/browser_finance_reconciliation_check.py` | 现有关联与对账 | 6 | 本轮重跑 |
| `tests/browser_finance_reconciliation_guard_check.py` | 对账迟到响应与身份保护 | 57 | 本轮重跑 |

保留现有 SESSION_REFRESH_EACH_REQUEST=False、旅行请求／表单／身份守卫和重新预览时禁用旧确认。下载说明不提供自由文本 AI 解析，金额选择不提供任意列映射；05:47 当时 XLSX 说明页发现未合入；现已于 06:50:21 随组合版本发布。

本次对账界面增量绑定原页面和原成员／家庭／CSRF，读取、候选、预览、确认及撤销的迟到结果不接管后来页面；已发送写入不能由关页取消。独立专项为 `tests/browser_finance_reconciliation_guard_check.py`。本修复不声称覆盖全部财务缓存生命周期。

XLSX 工作表发现与助理旅行简报已于 2026-09-15 06:50:21 合入并发布，详情见 [验收记录](VALIDATION.md)。

## 06:50:21 工作表与旅行简报开发接缝

新接口 `/api/assistant/journey-brief` 由原 `register_assistant` 注册，不增加依赖或业务表。助理只把白名单简报交给 `JourneyUI.openDraft`，经原旅行预览和明确确认保存；成员／家庭／CSRF 与原表单代次保护不能拆掉。`financial_files.py` 与 `finance_hub.py` 同步支持 `inspectSheets`；财务 JS 的选表变更不得覆盖原对账与缓存身份守卫。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_financial_sheet_discovery.py tests/test_assistant_journey_brief.py tests/test_home_assistant.py
.\.venv\Scripts\python.exe tests/browser_financial_sheet_discovery_check.py
.\.venv\Scripts\python.exe tests/browser_assistant_journey_brief_check.py
```

本轮完整组合验证如下，不能把合入前 revision 的 51 项 API 或 25/21/5 浏览器再相加：

| 浏览器专项 | 范围 | 本轮通过场景 |
|---|---|---|
| `tests/browser_journey_import_guard_check.py` | 旅行文件导入保护 | 31 |
| `tests/browser_journey_draft_guard_check.py` | 相邻草稿与提交返回 | 32 |
| `tests/browser_journey_confirm_guard_check.py` | 重新预览确认 | 5 |
| `tests/browser_journey_details_check.py` | 旅行 v2 时间细项 | 10 |
| `tests/browser_journey_return_budget_check.py` | 旅行返回与预算 | 23 |
| `tests/browser_journey_examples_check.py` | 旅行示例下载 | 8 |
| `tests/browser_finance_amount_columns_check.py` | 账单金额列选择 | 13 |
| `tests/browser_financial_files_check.py` | 现有文件导入 | 5 |
| `tests/browser_finance_reconciliation_check.py` | 现有关联与对账 | 6 |
| `tests/browser_finance_reconciliation_guard_check.py` | 对账迟到响应与身份保护 | 57 |
| `tests/browser_financial_sheet_discovery_check.py` | XLSX 名称发现与选表 | 11 |
| `tests/browser_assistant_journey_brief_check.py` | 助理简报到旅行向导 | 25 |
| `tests/browser_assistant_actions_check.py` | 助理原事项处理与返回 | 21 |

Windows **742 passed / 12 skipped**，Linux **753 passed / 1 skipped**，两套均完整运行测试集，各收集 754 项；13 组临时浏览器全部重跑、共 **247** 场景通过。Windows 的 POSIX 跳过由 Linux 执行，Linux Docker CLI 跳过由 Windows 覆盖；实际模型与云发布仍单独验收。
