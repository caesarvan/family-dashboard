# 家庭中枢平台扩展

本文描述 2026-09-14 晚间开始的产品化迭代。完整目标与未完成要求见 [产品目标](PRODUCT-PLAN.md)，实际发布和测试结果见 [验收记录](VALIDATION.md)。这里的实现说明不能代替第三方真实授权验收。

**当前版本：2026-09-15 16:25:03（北京时间），镜像 `sha256:f1e4cc56979f793f32585f498fa2fca55987356bd68f67e8cc6c14f0b1b6a01d`。** 旅行执行进度、真实待同步提示及两个订单表头兼容已发布，保留此前全部模块；源码与文档数量见 [README](../README.md) 及逐文件交接清单；101 个方法／路径模板、42 张户内表及 2 张平台表。本轮无结构迁移。真实云写与其他外部验收仍按 [VALIDATION](VALIDATION.md) 单列。

当前源码与文档数量以 [README](../README.md) 及逐文件交接清单为准；接口和存储结构见 [当前索引](PLATFORM-ROUTES.md)，运行版本与验收证据见 [VALIDATION](VALIDATION.md)。

布局、对账、待办发布与个人数据副本已于 2026-09-15 01:10 发布。服务内部核对与公网浏览器的组织策略阻断分别记录；源码、后续设计和接手边界见 [联合开发说明](HANDOFF.md)。

**02:33 新增能力已发布：** 财务来源桥接、旅行 v2、云日历时间复核与重连恢复、相关导出字段已完成 Linux 候选测试和服务更新；真实账号/来源验证仍与合成验收分开记录。

**03:11:08 新增能力已发布：** 助理“本周待处理”复用原记录编辑器和共享接口，日历发布表补列/命名空间初始化加入事务保护；不增加 HTTP 路由或业务表。界面操作与隔离验收见 [工作台文档](WORKSPACE-UI.md)。

<a id="投资来源与确认事务候选"></a>

## 投资来源与确认事务

2026-09-15 08:56:01 发布增加 investment_import.py，复用私有投资校验和有界 financial_files.py，注册三个投资文件接口并新增四张户内表。member + household + session 上下文保护预览；来源与持仓键仅在本人数据库范围解析；BEGIN IMMEDIATE 中比较持仓/映射/来源版本，提交记录、关联与回执。重复确认读原回执；缺少的文件行保留旧持仓。模块并不连接机构、更新行情或把持仓加到共享基线。

当前组合结构为 101 个 Flask 方法／路径模板、42 张户内表与 2 张平台表，16:25 运行版本没有结构迁移。2026-09-15 15:10 的历史消费观察增量新增两张本人表，复用既有来源三接口；例行三个共享管理接口及三表属于更早增量，采购接口与两张本人私有关系表继续保留。下方历史批次不代表当前总数，字段见 [消费观察](SPENDING-OBSERVATIONS.md)、[例行契约](ROUTINES.md) 和各模块文档。

## 架构变化

前端继续使用原生 JavaScript。`product-shell.js` 最后加载，在成员端提供工作台路由、侧栏/底导航、搜索和主题；原有日程、图片和表单模块继续负责具体操作。电视保留专用只读布局。页面路由使用 URL hash，服务端接口保持同源。

另提供 Web App Manifest 与手机添加到主屏幕的基础元数据；不同系统的安装表现仍需实体设备验收。没有缓存私有 API 或承诺离线编辑能力。

新增业务模块：

| 文件 | 职责 |
|---|---|
| household_spaces.py | 家庭注册目录、邀请、请求分发、成员显示偏好 |
| journey_workflows.py | 多城旅行、准备/采购/日程生成、预览签名、事务与重试回执 |
| journey_time.py（02:33 发布） | 旅行 v2 的 IANA／DST、当地时间与 UTC、航班／住宿／活动时间和排他日期校验 |
| spending_observations.py | 本人消费观察快照与持久回执；旧资产基线和共享小计不变，复用来源三路由显式 mode。见 [消费观察](SPENDING-OBSERVATIONS.md) |
| finance_source_bridge.py（02:33 发布） | 本人来源预览／CAS 确认、共享小计重算、缺源／日期回退保旧和持久回执 |
| deploy/prepare-finance-source.py（02:33 发布） | 读取白名单已完成产物与私人稳定映射，冻结核验后原子生成源码外候选；不刷新或写入账本 |
| finance_hub.py | 账单订单导入、去重、分类预算、多币种投资；内部登记 investment_import.py 文件导入流程 |
| financial_files.py | 有界 CSV/GB18030/XLSX 读取、工作表选择、公式和外链拒绝 |
| household_routines.py | 共享周期规则、日期数学、逐期本地生成、确认回执、只读 brief 和共享导出 |
| shopping_settlement.py | 本人付款与共享采购核对；只读预览、事务确认、私有链接与回执；仅投影整项实付和买到状态 |
| home_assistant.py | 本地概览、冲突、搜索、计划草案、可选模型接入 |
| calendar_publish.py | 旅行日历发布、写权限升级、队列与冲突状态；本轮另含 review_required 时间语义核对，真实写入单独验收 |
| task_publish.py | 已确认本地待办发布至本人来源或家庭主清单，完成回流、远端冲突、不确定创建结果查询恢复 |
| sync_health.py | 只读聚合各来源新鲜度；共享摘要不含账号／来源名称，本人问题中心仅返回本人账户及可管理发布项，详见 [同步状态契约](SYNC-HEALTH.md) |
| dashboard_preferences.py | 本人首页卡片顺序/隐藏，独立 revision 与并发保存检查 |
| data_portability.py | 本人数据 ZIP 副本、可选家庭共享记录、字段白名单和资源限额 |
| product-shell.js/.css | 工作台页面、主题、密度、移动端导航 |

## 多家庭隔离

原家庭数据库仍是 `/data/household.sqlite3`，无需搬迁已有数据。平台目录是 `/data/platform.sqlite3`。新家庭数据库在 `/data/spaces/<随机 id>/household.sqlite3`，云同步锁也在各自目录。照片、私有财务、投资、OAuth 状态和第三方令牌均随所属家庭数据库隔离。

`GET /space/<slug>` 选择家庭，设置 HttpOnly/SameSite 的已签名 routing cookie，并清除原有成员会话和电视 cookie。routing cookie **不授予数据访问权限**；每个家庭的 Flask 会话和 OAuth 加密密钥由服务器主密钥与家庭随机 id 派生，仍需用该家庭账号登录。

创建入口使用一次性邀请码。原家庭 `member1` 作为平台管理员生成邀请码；受邀者自行设置新家庭的名称、地址和两位成员密码。默认限制 30 个家庭、每户两位成员；这是邀请试用容量，不是已完成无限扩展。没有开放匿名注册、支付套餐或自动邮件邀请。

同步 worker 最多并行处理两个家庭，同一家庭不重复调度；每个第三方账户继续使用原有进程锁。不能用单户的同步正常推断所有家庭都正常。

当前 worker 对每户依次执行待办发布、日历发布、云来源读取、本地例行推进；一个阶段失败会记脱敏错误并继续后续阶段。持久队列与来源镜像共用稳定映射，避免本地任务发布后显示两份；待办请求结果不确定时只能先查远端，详见 [待办发布](TASK-PUBLISH.md)。

### 家庭与偏好接口

| 方法与路径 | 权限 | 输入或结果 |
|---|---|---|
| GET /api/spaces/current | 匿名可读当前空间的名称/入口 | id、slug、name、entry、canInvite；不列出其他家庭 |
| POST /api/spaces/invitations | 原家庭 member1 + CSRF | 返回一次性 invitation，有效期 7 天；服务端只存哈希 |
| POST /api/spaces/redeem | 持邀请码；JSON、同源、限速 | invitation、name、slug、MEMBER1_PASSWORD、MEMBER2_PASSWORD；成功返回新家庭 entry |
| GET /space/&lt;slug&gt; | 只选择入口 | 清除原会话，跳转登录页 |
| GET /api/preferences | 成员本人 | theme、density、homeView |
| PUT /api/preferences | 成员本人 + CSRF | 完整三字段：forest/light/ocean、comfortable/compact、today/week/around |

旧成员账号和密码不会重置。已注册家庭的存储或成员记录缺失时，拒绝使用主家庭环境密码补建身份。

## 旅行与采购闭环

通过 `/api/journeys/preview` 提交计划，服务端验证日期、成员、城市段、任务和金额，生成签名预览。`/api/journeys/apply` 接收预览和幂等键，在一次事务中写入旅行、准备任务、采购和本地日程。

更新计划要携带工作流版本，并核对关联实体版本。迁期保留实体 id、任务完成状态、采购实付和图片；其他成员已改动时返回冲突，重新预览后处理。删除旅行保留已有待办、采购和日程，仅清除关联，不擅自删除远端日历。

云日历发布是独立的确认流程：选择本人可编辑的来源、检查写权限、预览并加入持久队列；实际写入后读回核对。幂等、持续迁期、暂停/恢复与冲突对比的接口及真实验证边界见 [云日历发布](CALENDAR-PUBLISH.md)。

<a id="本人付款与采购投影候选"></a>

### 本人付款与采购投影

新增三个 `/api/finance-hub/shopping-settlements/context|preview|confirm` 操作，由 `register_shopping_settlement()` 在财务中枢之后、个人副本之前注册。不新建交易或调用云服务：本人选择已有 CNY 付款，经只读预览与明确确认，把整项金额及独立买到状态投影到已有共享采购。确认在 `BEGIN IMMEDIATE` 中重验会话、来源、付款分配和采购版本，原采购 ID、照片、负责人及旅行关联保持。

`hub_shopping_settlements` 与 `hub_shopping_settlement_receipts` 是按本人隔离的两张户内表。两位成员可分别关联同一采购，但共享实体仍使用同一 revision，不能静默覆盖旧预览；私有来源和回执不放进 `/api/state`。来源改变只派生待核对，不后台更改实付。默认解绑保留当前值，恢复旧值必须显式选择且满足版本与原投影条件。删除旅行继续保留采购；删除采购后，旧确认或回执重放不创建替代实体。

旅行迁期保留当前采购的实付、完成状态和图片；若采购在旅行预览后被核对修改，旧旅行确认返回冲突，重新预览后继续。采购实付只有在已买到后纳入原采购统计，不自动增加旅行 `paid`，也不改变私人月预算或公共余额。接口、金额与删除规则见 [采购实付契约](SHOPPING-SETTLEMENT.md)，本人导出白名单见 [PORTABILITY](PORTABILITY.md#采购实付关联与回执)。12:11:36 采购历史迁移从 35 张户内表增加为 37 张，不向既有表增加列；保留原表、数据与 schema 对象，并核对两张新表的结构与初始空值。迁移、备份与读回证据见 [VALIDATION](VALIDATION.md)，不能沿用旧 35 表零迁移的发布结论。

### 旅行 v2 与云时间语义核对（02:33 发布）

`journey_time.py` 与 `journey_workflows.py` 复用原工作流、preview/apply、关联实体和 ICS 出口。能力响应声明支持 `[1,2]`；v1 不自动升级，v2 不允许降级。新分段为 `flight/stay/activity/legacy_day`，保留稳定 key、人工预订状态和 `fixed/shift_with_trip` 日期策略。航班保存两端当地时间、IANA 时区及校验后的 UTC 时刻；住宿按入住／退房日期计晚数；日期型活动使用排他结束日。DST 缺失时间拒绝，重复时间需要明确选择偏移。详细字段见 [旅行 v2](TRAVEL-DETAILS-PLAN.md)。

更新时比较旧计划生成值、当前关联日程和新计划：只被成员独立修改的字段保留；两边都改动同组字段时必须选择当前日程或新计划并重新预览。仍保留实体 ID、完成状态、采购实付和照片。已订／固定事项的整体迁期须逐项明确选择；人工取消仅改变标记，不自动取消预订或删除远端事项。

旅行时间类型、时区语义或取消状态变化会把已有发布置为 `needs_review`、`review_required=1`，保留原远端 ID 和待处理证据。发布模块新增 `POST /api/calendar-publish/publications/<rid>/review-preview`（请求 `{}`）及 `/review-confirm`（请求 `{previewToken}`）。预览读取当前本地／远端；确认核对成员、队列绑定和本地版本后才重新排队，worker 继续使用远端版本保护。普通暂停、恢复、重试不能绕过此标记；`queued:true` 不代表云端已更新。旅行负责人处理语义变化，云发布负责人处理远端核对，不能各自另建一套旅行日历。

模板提醒的是准备工作，不是已核实的护照/签证/入境政策。真实国别要求必须结合出行人证件、日期和官方资料核对。

## 财务数据口径

账单和订单导入分为预览、确认两步。初始可见性是本人私有；只有逐笔明确选择共同消费，才进入不含账户名称或单笔细节的共享汇总。导入不改已有荷包余额、财务基线或其他成员的收支。

支持 UTF-8/GB18030 CSV 和受限 XLSX，工作表可选择，单文件不超过 2 MB。文件格式、限制、请求样例和合成样本验证范围见 [财务文件导入](FINANCE-IMPORT.md)。这不等于所有平台实际导出格式均已验收。

支付流水计算收入/支出/退款；本人账户间转账不算消费；电商订单单独统计，避免和支付记录重复。每种币种分别计算，未接汇率源时不进行总额换算。投资成本与估值为手动记录，需要注明日期；未估值项目保持未知，不按零值计算收益。

新增对账使用单独的 `hub_reconciliations` 保存订单/付款、退款/付款、已确认重复关系。候选不是已核实事实，须预览后由本人确认；确认与撤销检查 revision 并调整有效汇总，原始记录保留。导入自身幂等和跨来源重复消费判断分开处理，完整约束见 [财务 API](FINANCE-API.md)。

当前固定版本财务基线继续保留，是另一个有日期的来源。不能把手动投资记录与旧基线简单相加，否则同一资产可能重复计算。

### 财务来源桥接（02:33 发布）

新增流程是“源码外私人配置 → 本地准备 JSON 候选 → 本人预览 → 明确确认”，不是后台自动同步。`register_finance_source_bridge(app,db,Problem,body,require_member,audit)` 在原基线注册之后接入三个 `/api/finance-baseline/imports/status|preview|confirm` 操作。预览不写基线，确认把目标 revision/sourceDigest 作为 CAS 条件，在同一事务写本人基线和 `finance_source_receipts`；原令牌不入库，重放返回原回执。

服务端从本人逐项记录重算共享白名单小计；候选不能指定 owner 或共享总额。来源缺失、稳定映射不完整、已有金额变未知或来源／逐项日期回退时保留旧基线。消费报告的渠道／订单补记只作为本人来源观察，不进入实付账本，不覆盖公共荷包或手工投资。真实来源目前仅核对列头／报告结构；贷款核对日期和旧记录映射仍需补证据。CLI、字节限制、私密范围与完整契约见 [来源桥接](FINANCE-SOURCE-BRIDGE.md)。

## 家庭助理

| 方法与路径 | 功能 |
|---|---|
| GET /api/assistant/brief | 未来一周日程、到期待办、重叠时间、待采购数量和覆盖说明 |
| POST /api/assistant/plan | prompt、useModel、includeHouseholdContext；返回草案 id、summary、actions、mode 和搜索匹配 |
| POST /api/assistant/plans/&lt;id&gt;/apply | selected 数组；确认所选动作，返回创建结果；同一草案重复提交返回原回执 |

本地模式支持“待办：明天预约保洁；确认酒店”“采购：收纳袋；转换插头”“搜索：酒店”。自由表达的模型能力通过环境变量 `OPENAI_API_KEY` 与 `OPENAI_MODEL` 启用。两者未配置时，本地能力仍可用，并明确显示模型尚未配置。

模型请求固定发送到 OpenAI Responses API，`store=false`，不跟随重定向。每次由成员选择是否使用模型、是否提供近期家庭上下文。自动上下文只允许日程和待办的部分字段，不包含财务、账户、令牌或备注；用户输入的本次文字本身会发送。模型响应必须通过动作白名单和服务端字段校验，模型不能直接执行数据库操作。

每次最多 12 个新增待办/采购动作，草案绑定创建成员，24 小时后禁止执行，历史最多保留 7 天。确认后创建到本地家庭清单；独立按钮允许再次选择将已创建的待办发布到第三方清单，采购不由此发布。不会自动下单、转账、发送邀请或完成预订。

## 布局与数据副本

个人外观偏好继续使用 `/api/preferences`；首页卡片顺序/隐藏使用独立 `/api/dashboard-layout`，以 revision 检测其他设备修改，至少保留一张卡片。此布局不改变电视配置，也不改变成员可访问的数据范围。细节见 [工作台界面](WORKSPACE-UI.md)。

`/api/portability/summary` 与 `/export` 按当前会话导出本人所有已保存记录，可选附带家庭共享内容。归档不含伴侣私有账本或凭证，照片仅元数据；有容量与并发限制。该副本不能替代全户 SQLite 备份或直接用于灾难恢复，见 [导出契约](PORTABILITY.md)。

本轮增加 `personal.financeSourceReceipts`，仅限所属成员且不含令牌／签名；`travelTiming/startDate/endDateExclusive/workflowKey` 则随明确选择的共享事件导出。二者的隐私范围不同，不能因为共享旅行就附带另一位成员的财务来源。

## 发布与恢复

除原有文件外，Dockerfile 和发布清单必须包含全部新增 Python 模块和静态文件。不要只上传前端。原生产 `.env`、数据库和 OAuth 绑定继续保留。

本版要求 `finance_source_bridge.py`、`journey_time.py`、`pytest.ini` 和财务来源 UI；固定 `tzdata==2026.4`，Docker 使用空 `PYTHONTZPATH`。02:33 已完成镜像验收及发布；后续修改仍按 [HANDOFF](HANDOFF.md) 约定文件所有权并统一发布。

备份脚本先快照平台注册目录，再备份原家庭及注册目录中的全部家庭；输出 manifest 记录路径、大小和 SHA-256。单个数据库通过 SQLite backup API 保持一致性，不声称多个数据库在同一全局事务点。完整 manifest 保留最近 14 组，清理不能删除这些 manifest 引用的文件。

恢复一个家庭时只恢复对应数据库；恢复整个平台需要配套的平台注册目录和其引用的家庭数据库，不能把另一个家庭的文件放入该目录。主 SECRET_KEY 的丢失会影响所有家庭会话、派生密钥和第三方令牌，应按原有密钥保管流程单独备份。尚未执行生产覆盖恢复演练。

基础 [API](API.md) 和 [数据模型](DATA-MODEL.md) 保留旧模块的详细说明；旅行、助理、空间与偏好见 [平台 API](PLATFORM-API.md)，旅行 v2 见 [时间与细项契约](TRAVEL-DETAILS-PLAN.md)，账本与投资见 [财务 API](FINANCE-API.md)，来源候选见 [桥接契约](FINANCE-SOURCE-BRIDGE.md)，云日历见 [发布 API](CALENDAR-PUBLISH.md)。所有方法、路径和业务表由 [完整路由与存储索引](PLATFORM-ROUTES.md) 汇总。

## 家庭例行计划与四阶段调度

计划、期次和回执分为 household_routines、routine_occurrences、routine_receipts 三表。注册只初始化空表／索引，核心 users 先存在；不读取私人账本，不把已有实体变成规则。共享计划两成员可管理，但 previewToken 绑定原成员／家庭／有效会话以及当天、规则、当前实体和容量；confirm 在 BEGIN IMMEDIATE 内重查并持久幂等回执，重复成功请求不生成第二项。

worker 对每户执行 task_publish → calendar_publish → cloud_accounts → household_routines，最多两户并行；每阶段前检查 stop。例行只读筛选未完成／缺失／暂停／阻塞状态，只有可推进规则才进入写事务重查；同事务关闭上一期、插入本地实体与期次、递增规则／共享 meta并记 system:routines 审计。一个规则最多维持一个当前项，不补历史。

原 scheduledOn 控制节奏，手工修改当前标题／due 不改变下一期；update 只改未来模板。skip 不改旧实体、不伪称完成；删除当前项保持 missing，归档不删除历史。采购新期 actual=null/photoIds=[]/done=false，保留模板数量和预算，不复制 trip/payment/link/cloud 字段。明确云发布仍逐期经过原任务发布流程，不调用 cloud.task_write。

助理 brief 使用传入连接只读共享数据；同 revision／新状态提示不重置草稿。成员 ZIP 显式 includeShared 时导出三表业务白名单，完整管理员备份保存全部内容。规则输入、限额、上下文签名和接口见 [ROUTINES](ROUTINES.md)，迁移见 [DEPLOYMENT](DEPLOYMENT.md)。
