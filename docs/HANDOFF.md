# 联合开发接手说明

**当前版本：2026-09-15 16:25:03（北京时间），镜像 `sha256:f1e4cc56979f793f32585f498fa2fca55987356bd68f67e8cc6c14f0b1b6a01d`。** 旅行执行进度、真实待同步提示及两个订单表头兼容已发布，保留此前全部模块；源码／文档数量见 README 和逐文件清单、101 个方法／路径模板、42 张户内表及 2 张平台表。本轮无结构迁移。真实云写与其他外部验收仍按 [VALIDATION](VALIDATION.md) 单列。

先读 [README](../README.md)，再按下方模块地图阅读接口和源码。本文帮助开发者确定从哪份代码开始、负责哪些文件、如何验证与交付。历次发布和失败修订集中在 [VALIDATION](VALIDATION.md)，不重放历史候选补丁。

## 当前发布与源码状态

本次于 **2026-09-15 16:25:03（北京时间）** 发布 `sha256:f1e4cc56979f793f32585f498fa2fca55987356bd68f67e8cc6c14f0b1b6a01d`。本轮旅行执行、待同步状态与订单表头兼容已合入，无结构变化；15:10:00 财务版本及其 40→42 迁移保留为历史记录。

| 交接项 | 当前范围 |
|---|---|
| 当前源码 | main 通用包 225 文件、38 份 Markdown；Git bundle 另保留未合入分支；逐文件 SHA-256 见对应包 RELEASE-MANIFEST.json |
| 接口与存储 | 101 个 Flask 方法/路径模板，另有 WSGI 家庭入口；每户 42 表 + 平台 2 表；本轮结构不变 |
| 后端 | Windows：1268 passed / 18 skipped；Linux：1285 passed / 1 skipped；每端完整收集 1286 项 |
| 浏览器 | 新旅行执行 53 项、原旅行与发布 8 组；绑定最终源码、零外站请求；历史财务 222 项属于上一版 |
| 发布核对 | 停入口与写入后全家庭备份，42→42 表结构和数据逐项保持；42 静态资源与 18 匿名 GET 检查 |
| 源码边界 | 仅源码／测试／文档；.env、数据库、真实财务输入和 test-results 不随通用包分发 |
| 未验证范围 | 真实消费观察输入、新云写、公网、真实模型、银行／券商、私人来源完整映射、实体设备和生产覆盖恢复仍单列 |

本次交接另含 `deploy/rehearse_restore.py`、`tests/restore_rehearsal_fixture.py`、`tests/test_recovery_rehearsal_safety.py` 和[恢复演练文档](RECOVERY-REHEARSAL.md)。运行镜像保持 16:25 版本；16:54 已完成真实 Docker 合成演练。此增量只含工具、测试和文档；历史完整后端 1286 项与新增安全测试 13 项分别记录。后续修改恢复文档中的 Python／SQL 时，同时复核提取逻辑和实际演练，不能仅更新一份复制的算法。

## 当前候选与文件占用

已发布的旅行执行和恢复工具已经完成交接。**新旅行资料已分模块审查并合入 `codex/integration`，尚未部署**。本节记录集成到 `31397f9423e64a30de6f746bc517868aeb0cdcd5` 时的进度；此时 main 为 `22fe53c`，后续应先核对实际 Git refs，不能凭本段旧快照判断发布状态。旧共享候选目录只作冻结证据，禁止继续在其中开发。

仓库基线为 `ad667bf2b744d707db080964c662249c7cd8b056`，标签 `baseline/2026-09-15-handoff`。当前主仓为项目根目录，各工作树位于维护者本机 `C:/Users/caesarf/Documents/Codex/family-dashboard-access/worktrees/` 下；换机器后按 [Git 指导](GIT-WORKFLOW.md) 从 bundle 创建自己的工作树，不复用这些机器绝对路径。

| 分支 | 本轮负责人 / worktree 目录名 | 已保存范围与状态 |
|---|---|---|
| `main` | 集成人 / 项目根目录 | 已发布业务基线与审查后的交接文档；线上结构仍为 101 路由、42 户内表 |
| `codex/integration` | 集成人专用 | 仅合并审查通过的提交，不供模块 agent 直接开发 |
| `codex/journey-documents-api` | journey_workflows / journey-documents-api | `90292c7`；product_interface 独立审查功能，root 复核末尾空行修正，已合入 integration |
| `codex/journey-documents-ui` | product_interface / journey-documents-ui | `a9dd519`；journey_workflows 审查提出三项修复，作者修复后由 root 复核，已合入 integration |
| `codex/journey-documents-portability` | finance_hub / journey-documents-portability | `8eb120e`；本人导出和恢复夹具，由 root 独立审查后合入 integration |
| `codex/journey-documents-wiring` | 集成人 / journey-documents-wiring | `2774e75`；app、加载、Docker 与发布白名单，由 finance_hub 独立审查后合入 integration |
| `codex/finance-journey-migration` | finance_hub / finance-journey-migration | `ec0ec4c`；可移植 42→43 检查器、16 项测试及契约，由 root 独立审查后合入 integration |
| `codex/journey-documents-release` | journey_workflows / journey-documents-release | `aecfd6c`；专用发布控制器、66 项命令替身检查，由 root 独立审查后合入 integration；未执行生产迁移 |
| `codex/journey-release-guide` | journey_workflows / journey-release-guide | `af81669`；发布输入、原始证据和失败处理指导，由 root 独立审查并复核文案修正后合入 integration |
| `codex/root-journey-docs` | root / root-journey-docs | 当前候选的 README、接口索引、数据与部署文档；独立提交、交由非作者审查 |
| `codex/docs-git-handoff`、`codex/git-workflow-guide` | 文档集成人与文档 agent，各自独立目录 | 本次 README、Git 规则与指导；通过独立审查后逐层合入 main |

候选实现资料默认本人私有、明确选择后向本户成员共享，电视不能读取资料；PDF 仅下载，图片解码净化，删旅行保留上传者资料并可重新关联。新增 5 个方法/路径模板及 1 张表，候选为 **106 路由、43 户内表及 2 张平台表**；完整字段见 [旅行资料契约](JOURNEY-DOCUMENTS.md)，生成索引反映候选源码，不能理解为线上结构已经改变。

各模块分支保留独立职责，**单独分支不一定能启动完整新功能**。UI、导出和接线依赖新后端；完整测试在审查后的集成提交上执行，不通过复制其他工作树文件拼装。浏览器验证使用固定提交的 detached worktree，作者仍只在自己的功能分支修复；修复再次审查和 Git 合并后才验证新提交。

已完成的组合证据：`edc4ad9` 上资料 API／导出组合 **85 passed**（68 + 12 + 原导出 5），后续仅 API 末尾空行整理不改变 AST；`c91c6fe` 上完整资料浏览器 **43/43**、原详情 **10/10**、执行流程 **53/53**、返回流程 **23/23** 通过，共 129 项，232 个受控源文件前后相同且无页面错误或外站请求。43 项包含刷新后的准确分段焦点、四种空闲身份切换清屏，以及成功响应丢失后原旅行删除／重新关联的幂等重试。迁移工具在无 Git 的独立 TAR 解压目录中 **16 passed**，不依赖开发者路径。

本机合成恢复 seed 15 / verify 216 是独立夹具记录；完整后端、Linux 镜像、新 43 表实际 Docker 恢复、最终集成复核与正式迁移尚待绑定最终源码完成。旧浏览器失败和后续修复分开保留，原 42 表镜像的通过记录不能移作此候选验收。当前通用源码排除全部真实输入、配置和私有 `test-results/`。

旅行执行跨模块接缝：`static/journey-ui.js/.css` 管详情刷新、负责人筛选和原流程返回；`task_publish.py`、`calendar_publish.py` 管 `localChangesPending` 的只读比较；`finance_hub.py` 管来源限定的订单表头兼容。验收入口为 `tests/browser_journey_execution_check.py`、`tests/test_publication_local_changes.py` 和 `tests/test_order_source_headers.py`。这些文件及接口变更由集成人协调，不能由旅行与云同步 agent 同时修改同一文件。见 [旅行执行契约](JOURNEY-EXECUTION.md)。

本页不登记已结束任务的永久占用者。家庭例行计划、采购实付、同步问题中心、电视布局、投资导入、成员会话、旅行简报及更早的 worker／旅行返回／连接返回均已在当前版本内；旧候选只供追溯，不是待应用操作。**不要重复 apply 历史补丁，也不要用旧候选整目录覆盖当前源码。**

下一轮开始前，由集成人登记目标、独立分支/worktree、base commit、允许路径、依赖与冻结状态。只在自己的工作树提交；结束交付 head commit 与 diff，散列补充文件证据。其他 agent 未收到审查通过的提交时，不假定依赖已经合入。

### 本次财务增量的交接边界

消费观察、历史月份导航和导出保护已结束独立候选阶段，并已包含在当前清单。旧 export-guard-candidate 目录只供追溯，没有待应用补丁或仍在占用的永久负责人。后续修改先向集成人登记唯一编辑者。

消费观察由 spending_observations.py 管规范化、覆盖、双版本 CAS 和事务，finance_source_bridge.py 分派显式 mode；finance_baseline.py 只在本人响应选择观察，不更新旧资产基线或共享小计。账单导航由 finance_hub.py 返回实际 resultMonths／availableMonths，finance-hub.js 保留成功回执并只重试读取。data_portability.py／data-portability.js 负责本人白名单副本和异步身份保护；最终身份读取后的 Cookie-only 切换仍有已观察的非原子限制。

这三条流程与来源、导出及既有财务模块共用文件，下一轮不得按旧任务分工同时写 finance-hub.js、finance-source-ui.js 或 data-portability.js。只提交允许路径的 BASE/RESULT 和精确 diff；完整源码、测试及接口应来自同一当前清单。

采购实付跨模块接缝为：`shopping_settlement.py` 负责私有来源、预览确认及回执；`static/shopping-settlement.js/.css` 负责新流程；`shopping-ui.js` 提供已保存采购入口；`finance-hub.js` 经原模型身份守卫提供账本入口、原订单对账及精确返回；`app.py`、`index.html`、Docker／发布白名单与 `data_portability.py` 由集成人统筹。整项 CNY 实付与 done 只投影到原共享采购，原交易、来源及关系不公开，旅行 paid 和账本不自动改变。

维护者的 `test-results/`、私人配置、运行数据库、真实财务输入和运行截图不进入通用源码包。包内保留可复跑测试与脱敏说明；单独查看原证据须明确范围，开发不要求生产凭据。

## 模块地图与接口入口

| 负责功能 | 核心文件 | 先读的契约与关键边界 |
|---|---|---|
| 家庭例行计划 | `household_routines.py`、`static/household-routines.js/.css` | [例行计划契约](ROUTINES.md)；固定起始日、单个自动当前项、十分钟签名预览、原子回执、缺失与容量提示、只读助理及共享导出 |
| 基础应用与共享数据 | `app.py`、`static/app.js` | [基础 API](API.md)；身份、CSRF/同源、共享实体 revision、模块注册和通用弹窗。原生 JS，无前端构建服务 |
| 家庭隔离与登录会话 | `household_spaces.py`、`member_sessions.py`、对应 UI | [平台架构](PLATFORM.md)、[成员会话](MEMBER-SESSIONS.md)；每户独立 DB/密钥、两成员、邀请、撤销和认证代次。缺库不得初始化空身份 |
| 成员工作台 | `static/product-shell.js/.css`、`dashboard_preferences.py` | [工作台界面](WORKSPACE-UI.md)；导航、搜索、主题/密度、卡片顺序/隐藏。成员偏好与电视布局分别保存 |
| 电视配对与显示 | `tv_display.py`、`static/tv-display.js/.css`；`app.py` 设备接口 | [电视显示设置](TV-DISPLAY.md)；整设备 revision，`layout` 四字段整体替换，隐藏只影响显示。`deviceForm()` 转入 `TVDisplay.openDevice(id)`，TV 重绘后调用 `applyBoard()` |
| 日程、采购与图片 | `static/calendar-ui.js`、`static/shopping-ui.js`、`shopping_media.py` | [基础 API](API.md)、[使用手册](USER-GUIDE.md)；时区/日界、共享权限、图片引用及草稿，TV 保留分页与长内容滚动 |
| 采购实付核对 | `shopping_settlement.py`、`static/shopping-settlement.js/.css` | [采购核对契约](SHOPPING-SETTLEMENT.md)；整项 CNY 替换、done 独立、私有 link／receipt、版本与重放、两种撤销、本人导出；不改账本／trip.paid |
| 同步状态与问题中心 | `sync_health.py`、`static/sync-health.js/.css` | [同步状态契约](SYNC-HEALTH.md)；本人详情和共享聚合分离，不触发云写；app/cloud_accounts/外壳加载接缝交集成人 |
| 云账户与同步 | `cloud_accounts.py`、`cloud_providers.py`、`sync_worker.py`、`static/accounts-ui.js` | [账号接入](ACCOUNT-SYNC.md)、[连接返回](CONNECTION-RETURN.md)；成员授权、选源、账号锁、分页后替换与失败保旧。停止信号不保证在途请求立即结束 |
| 云日历与本地待办发布 | `calendar_publish.py`、`task_publish.py`、对应 UI | [日历发布](CALENDAR-PUBLISH.md)、[待办发布](TASK-PUBLISH.md)；明确预览确认、原幂等标识、ETag/冲突、目标重连与本地实体 ID。不确定创建不得盲目重发 POST |
| 旅行与跨模块联动 | `journey_workflows.py`、`journey_time.py`、`static/journey-ui.js/.css`、旅行示例 JSON | [平台 API](PLATFORM-API.md)、[旅行时间](TRAVEL-DETAILS-PLAN.md)；v1/v2、各地时间/IANA、排他日期、稳定 key、三方比较、待办/采购/日程联动和返回原计划 |
| 私有账本与投资 | `finance_hub.py`、`financial_files.py`、`investment_import.py`、对应 UI | [财务 API](FINANCE-API.md)、[账单导入](FINANCE-IMPORT.md)、[持仓导入](INVESTMENT-IMPORT.md)；整数分、分币种、未知值、工作表/金额选择、对账及原始来源标识。预览与确认分开 |
| 独立消费观察 | `spending_observations.py`、`finance_source_bridge.py`、`finance_baseline.py`、来源准备器和 UI | [消费观察](SPENDING-OBSERVATIONS.md)；需要已有本人基线，滚动覆盖、原基线不变、独立回执；不代表核对实付或自动银行接入 |
| 个人财务基线来源 | `finance_baseline.py`、`finance_source_bridge.py`、`deploy/prepare-finance-source.py`、对应 UI | [来源桥](FINANCE-SOURCE-BRIDGE.md)；私人映射、日期/覆盖范围、版本 CAS、缺源保旧。不能将个人银行余额当公共荷包，真实映射仍需核对 |
| 家庭助理 | `home_assistant.py`、`static/home-assistant.js/.css` | [平台 API](PLATFORM-API.md)、[旅行简报](ASSISTANT-JOURNEY-BRIEF.md)；本周待处理、原事项编辑返回、三步简报到向导。与旅行负责人共享 `journey-ui.js` 接缝，不能自动云发布 |
| 本人数据副本 | `data_portability.py`、`static/data-portability.js` | [导出契约](PORTABILITY.md)；仅本人私密与显式勾选的共同记录。排除令牌、会话/设备认证表和暂存预览；不是数据库恢复包 |
| 部署与备份 | `Dockerfile`、`compose.yaml`、`deploy/` | [部署指导](DEPLOYMENT.md)、[运维说明](OPERATIONS.md)；源码白名单、现有配置、全部家庭、停止写入、成组备份及相配恢复 |

当前路由定位入口是 [PLATFORM-ROUTES](PLATFORM-ROUTES.md) 和 [contract-inventory.json](contract-inventory.json)，结构为 101 个方法/路径模板、42 张户内表与 2 张平台表，须与最终源码实例化一致。例行管理的字段、鉴权和签名见 [ROUTINES](ROUTINES.md)，采购接口继续按 [采购核对契约](SHOPPING-SETTLEMENT.md#5-接口与数据模型)；不能仅按 UI 文案猜测 API。

## 例行计划公共接缝

`app.py` 在助理前注册 `household_routines`。`sync_worker.py` 每户顺序执行待办发布、日历发布、云读取、例行推进，各阶段开始前检查停止标记。推进只在观察到当前事项完成时创建下一期；不调用云账户默认写入器，不继承上一期云写授权。

`data_portability.py` 只在 `includeShared=true` 时加入 `shared.routines`。`home_assistant.py` 调用只读 `brief(con)`；`static/home-assistant.js` 按存在的数据显示例行计划待处理组。`static/product-shell.js` 提供三个入口并在共享状态刷新时通知例行模块；通知不发送请求、不重置草稿。新模块在 `product-shell.js` 之前加载。公开接口为 `HouseholdRoutines.open({planId?})`、`refresh()` 和 `notifyStateChanged()`。返回桥支持原待办／采购编辑器与 TaskPublish 初始选择页；保留未保存字段、图片和写中保护，显式返回重新核对原计划，不接管助理外层的关闭返回处理。Docker COPY 和 `deploy/prepare_release.py` 白名单都包含新后端。

当前完整结构为 101 路由／42 户内表／2 平台表；例行版 101／40 和采购版 98／37 是历史范围。最终结果见 [VALIDATION](VALIDATION.md)，不沿用历史通过数。

## 已开发与待真实验证

目前可用的本地完整流程包括：家庭进入/邀请与会话管理；日程和主清单连接；多城市旅行经表单预览确认联动准备、采购和日程；助理处理原事项或整理旅行简报；私人账单/持仓文件预览确认与本人导出；本人付款经预览确认核对原共享采购、订单对账后返回、来源变化复核与明确解除；两台电视分别配对并保存显示设置；按来源检查同步新鲜度并打开本人原问题。云写入始终由独立授权和明确确认驱动。

| 尚需实际验收或实现 | 必须保留的界限 |
|---|---|
| 公网与实体设备 | 组织 SmartScreen 曾阻断公网浏览器，未绕过；容器内部和临时浏览器不等于公网、遥控器、电视休眠唤醒或长期常亮通过 |
| Microsoft / Google 新写流程 | 既有来源读取与同步有历史实测；新的云日历/待办发布、真实 OAuth 回跳、冲突/重连和刷新令牌闭环须本人授权验收 |
| 真实私人财务 | 稳定来源映射、贷款余额日期、真实脱敏账单与持仓格式逐一核对；未连接个人银行/券商、实时行情或小荷包自动 API，未建立无人值守财务刷新 |
| 模型能力 | 本地规则与操作流程可运行；可选模型需服务器配置及本人明确选择，真实调用和抽取质量单独验收，不能称本地规则为模型回答 |
| 运维与商业化 | 同机备份不是异地容灾；生产覆盖恢复、跨机恢复、公开注册/更多角色、计费与运营制度未完成 |

共同资金与经批准的资产/负债汇总可以共享；个人账户、消费、投资与来源明细只属于本人。电视侧重某成员或隐藏财务卡片都不改变服务器权限。所有新模块须保留这些数据边界。

## 文件所有权与协作协议

1. **每个任务独立分支和 worktree。** 禁止多人编辑同一工作目录，即使计划修改不同文件也须隔离。集成人维护 main/integration，模块 agent 只维护分配的 codex 功能分支。共用文件变更先约定契约和顺序。
2. **跨模块接缝先约定。** 助理与旅行共用 `journey-ui.js`；账单、投资、对账与采购入口共用 `finance-hub.js`，采购入口还涉及 `shopping-ui.js`；成员与电视入口共用 `product-shell.js`；会话、OAuth 和家庭路由跨后端。模块负责人提供精确输入/输出、权限与插入点，不直接覆盖另一人的文件。
3. **用提交审查和合并。** 交付 base/head commit、允许路径、diff、测试与未验证项；另一位 agent 审查固定提交。通过后集成人按依赖合入 integration，组合验证与再次审查后合入 main。Git 合并冲突逐项处理，禁止整目录覆盖或以旧 SHA 补丁绕过提交审查，详见 [Git 流程](GIT-WORKFLOW.md)。
4. **按真实依赖记录验证。** 记录执行脚本、源码散列、临时配置、退出码、通过/跳过、截图及未覆盖范围。独立候选通过不自动代表组合版本通过；不要把多平台测试数相加当独立场景。
5. **冻结后不再改源。** 新问题先通知集成人，再决定解除哪个文件的冻结。新增 Python 文件要检查 Docker COPY/发布白名单；新增静态模块要检查 `defer` 和 CSS 顺序。公共入口与最后发布由集成人处理。

保存失败保留草稿；异步请求绑定原节点、请求代次、原成员/家庭/CSRF，并按流程重新核验身份。已经发送的写请求不会因关闭弹窗而取消；重试保留原幂等标识，不自动重发。鉴权由后端执行，前端隐藏按钮不能替代权限。

## 可复制的 agent 任务模板

```text
项目：family-dashboard。先读 README、docs/HANDOFF.md、docs/DEVELOPMENT.md
及负责模块的 API 契约。核对当前源码与线上版本，不重放历史补丁。

目标：[用户能完成的具体操作及结果]
基线：[base commit、codex/<agent>-<task> 分支、独立 worktree 绝对路径]
依赖：[需要的其他分支及审查通过的 commit；无则写无]
允许编辑：[唯一文件清单；共用文件需精确到授权范围]
接口：[方法、路径、输入/输出、身份/家庭边界、版本和错误语义]
集成人接缝：[模块注册、脚本/CSS顺序、数据迁移、公共文件]
验收：[正常闭环、失败草稿、并发/迟到响应、跨成员/家庭/TV、视口]
交付：[head commit、base...head diff、真实命令/结果、截图、未验收范围]
审查：[另一位 agent 对固定 base/head 的结论；由集成人合并]

使用临时数据库和虚构数据，不读取或上传生产凭据、真实账单或原始数据库。
不改生产、不部署；测试通过不等于真实云账户/实体设备已验收。
不编辑其他 worktree，不自行合入 integration/main。冻结后修复须新提交并重新审查。
```

## 接手后的首轮检查

1. 核对 Git 根目录、分支、HEAD、工作区状态和分配的 worktree；按 [Git 流程](GIT-WORKFLOW.md) 建立独立任务分支。使用源码归档时先核对清单，正式联合开发使用 bundle 恢复提交历史，不用旧候选整目录覆盖。
2. 按 [DEVELOPMENT](DEVELOPMENT.md) 创建项目虚拟环境、安装 `requirements.txt` 和测试工具。生产是 Python 3.12，Windows 已使用 Python 3.14；前端无需 npm 构建。
3. 按 [DEPLOYMENT 第 2 节](DEPLOYMENT.md#2-配置密钥与数据文件) 配置独立开发密钥、测试密码与临时 `DATA_DIR`，只绑定回环地址。Python 不自动读取 `.env`，不要复制生产配置。浏览器测试按各脚本使用自己的临时夹具。
4. 先运行负责模块的已有测试，确认本机 Edge/Playwright 路径，再跑适用的真实临时浏览器。`pytest` 不自动运行 `*_check.py`；不要把旧生产 `live_check.py` 当默认回归。具体命令见 [开发与验收](DEVELOPMENT.md)。
5. 明确接口/迁移/隐私变化后再编码。公共 API、数据模型、用户步骤、错误行为和相应测试一起交付；金额是整数分、不同币种分别计算，日期语义按旅行契约。
6. 由集成人检查合并结果，完成对应组合测试、冻结、打包及发布。源码打包只收白名单，不生成凭据，也不是内容脱敏器；不能把私人文件临时放到 `docs/tests/static/deploy`。

部署人员分清 [空服务器安装](DEPLOYMENT.md#3-空服务器首次安装) 与 [已有服务器更新](DEPLOYMENT.md#5-已有服务器发布更新)。15:10:00 历史财务版本完成 40→42 消费观察迁移。本版使用第 5.2 节 42→42 无结构更新，保留全部 42 表、列、行、schema 和 SQLite 序号；拒绝 40 表输入，不能改数字绕过。历史 37→40 例行迁移保留独立证据。

更新保留 `.env` 和主密钥，先关闭 web，再停止 sync/app，核对注册目录、全部家庭与完整备份组后串行初始化。app 启动读回通过才开放 sync/web；提交前按已审路径受控恢复，已有业务写入后先保全现场，不能让旧镜像盲接未知库。恢复使用相配源码、密钥、注册目录与家庭映射；**恢复后先使目标家庭旧成员登录失效，再启动 app/web 核对，最后才恢复 sync**。具体步骤见 [部署与恢复](DEPLOYMENT.md#6-备份恢复与回滚)、[运维](OPERATIONS.md) 和 [会话恢复要求](MEMBER-SESSIONS.md#恢复后使旧成员登录失效)。上一财务版本的 165／119 项离线激活／控制器恢复、79 项文档零结构检查均不是生产恢复演练。

## 后续工作

优先完成已实现能力的真实端到端验收：允许环境中的公网访问和 OAuth、两台电视长期展示、云任务/日历读回与冲突，以及真实脱敏账单/持仓和个人来源映射。每次选一个可观察闭环，保留现有数据与授权边界。

两户虚构数据的实际 Docker 恢复已完成；之后推进异地加密备份、生产覆盖恢复及跨机恢复、同步错误趋势、队列容量、备份年龄与磁盘可观测性（当前来源状态页已实现）、更丰富成员角色、Apple 提醒事项桥接、离线能力和商业化条件。详细优先级见 [PRODUCT-PLAN](PRODUCT-PLAN.md)，各历史发布、失败修订和未验证记录见 [VALIDATION](VALIDATION.md)。
