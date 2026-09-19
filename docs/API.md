# 家庭看板接口文档

当前部署身份见 [HANDOFF](HANDOFF.md)。个人账户与多家庭成员协作此前完成 58/2→61/9 迁移；本人账户分析完成 61/9→66/9，旅行路线随后完成 66→69；当前为 **69 张户内表与 9 张平台表**。最新本地任务依赖发布保持结构不变，见[最新发布验收](TASK-DEPENDENCIES-ACCEPTANCE.md#task-dependencies-release)。本人手动账户六个操作及三表已发布，见[账户验收](EXPO-FINANCE-ACCOUNTS-ACCEPTANCE.md#finance-accounts-release)；此前家庭角色的单列迁移另见[成员验收](EXPO-HOUSEHOLD-MEMBERS-ACCEPTANCE.md#household-members-release)。下面基础接口和历史旅行资料段落保留当时契约与计数，不代表当前总数。已发布 Expo 旅行资料复用现有五个操作，不新增 API 或表；客户端契约见 [新版旅行资料 API](EXPO-JOURNEY-DOCUMENTS-API.md)。

## 本地待办前置事项（已发布）

2026-09-20 06:28:25（北京时间）激活，06:35:47 独立只读审计通过。继续使用原任务 CRUD，不新增表或路由；完整字段和错误见 [TASK-DEPENDENCIES](TASK-DEPENDENCIES.md)，实际范围见[集中验收](TASK-DEPENDENCIES-ACCEPTANCE.md#task-dependencies-release)。

- 本地任务 POST／PATCH 接受 `dependsOn` 原 ID 数组，最多 20 项；旧客户端 PATCH 省略时保留，明确 `[]` 才解除。新建要选择 `sourceId:""` 的本地目的地，云镜像及云目的地不支持依赖。
- 当前任务投影包含只读 `blockedBy` 和 `dependencyStatus`。完成和删除必须在服务端同一写事务内重新核对图、版本和成员；前置未完成为 `task_dependencies_incomplete`，循环为 `task_dependency_cycle`，删除被引用前置为 `task_has_dependents`（均 409）。
- 已完成后续不会因前置重新打开而自动重开；旅行重建保留当前实体依赖。已发布到云的本地任务遇远端完成与本地阻塞时保留冲突，不自动撤销远端完成。
- 明确 `includeShared:true` 的数据导出保留已存 `dependsOn`，不导出派生阻塞状态；个人导出不因此增加共享记录。当前角色、家庭、Origin／CSRF 和 revision 边界保持。

站内提醒 `/api/task-reminders` 与 69→71 表迁移仍是后续候选，不属于本次已发布接口。

## 旅行路线（已上线）

路线只保存当前旅行关联地点的明确顺序，默认私人；显式共享后由同户其他成员只读，只有作者可编辑／删除。路线于 2026-09-19 22:56:47（北京时间）上线，新增三张路线表后为 69/9，实际迁移与独立审计见[路线验收](JOURNEY-ROUTES-ACCEPTANCE.md#journey-routes-release)。完整 DTO、限制和错误见 [路线 API](JOURNEY-ROUTES.md)，界面与恢复见 [Expo 路线](EXPO-JOURNEY-ROUTES.md)，迁移和发布边界见 [路线发布](JOURNEY-ROUTES-RELEASE.md)。

| 方法 | 路径 | 用途与返回 |
|---|---|---|
| GET | `/api/journey-routes` | `scope=mine\|shared\|visible`，可选 journeyId、limit、offset；返回 `{items,total,limit,offset,hasMore}`，只统计当前可见路线 |
| GET | `/api/journey-routes/<id>` | 当前授权详情 `{route,segments}`；站位保留顺序与匿名缺口，连线只连接有授权坐标的原相邻站 |
| POST | `/api/journey-routes` | requestId、title、journeyId、expectedJourneyRevision、stops；visibility 缺省 private，首次 201 |
| PUT | `/api/journey-routes/<id>` | 完整内容及 revision／sourceVersion；站点绑定 expectedRevision，可按原索引保留仍不可用的槽，200 |
| DELETE | `/api/journey-routes/<id>` | JSON 仅含 requestId、revision、sourceVersion；软删除并保留操作回执，200 |
| GET | `/api/journey-routes/operations/<requestId>` | 本人当前家庭原操作回执，未知 404；回执及写入返回 `{operation,replayed,current}`，current 为当前授权详情或 null |

全部接口要求当前成员：匿名 401、电视 403，不可见路线与未知路线均 404。写入需同源 JSON／CSRF；`ImportSession` 在读取、事务与返回边界重验身份。站位 1..100 个，允许往返重复；同一 `BEGIN IMMEDIATE` 原子保存路线、顺序和成功回执。同键同内容先恢复成功、重放 200，不重复写入；同键不同内容 409。未知结果先读原回执，再明确重发原编号和完整内容，404 不能证明在途请求不会提交。

共享路线对作者也一律使用地点当前共享投影，不能借路线扩大名称或坐标的共享范围；地点撤共享、删除或移出该旅行后只留 `{index,state:"unavailable"}`，无隐藏地点事实、不跨缺口连线。路线不会修改地点关联或到访状态，也不调用地图或云服务。个人 ZIP 的路线扩展沿同一当前投影，只在明确 includeShared 时附带他人共享路线，排除原站点外键、回执与源版本；发送前重验投影，详见 [路线数据副本](JOURNEY-ROUTES-PORTABILITY.md)。

## 助理预算与支出只读查询（已发布）

2026-09-19 19:42:01（北京时间）已发布，19:42:33独立只读审计通过。`POST /api/assistant/finance-query` 接受 `{prompt, useModel?}`；需当前成员、同源 JSON 和 CSRF，匿名401、电视403。返回 ready／clarify／unsupported；澄清或不支持时无财务内容。默认本地，允许模型不代表一定调用；模型只解释问题，金额在真实授权读取事务中按完整本人账本和原币计算。

本人净支出、退款分摊与预算不跨币种相加；明确共享只返回既有允许的汇总，公共荷包只投影已确认手工当前快照。无业务写入、新表或迁移。字段、缺省／未知和身份边界见[查询合同](ASSISTANT-FINANCE-QUERY.md)，使用见[Expo 查询](EXPO-FINANCE-QUERY.md)，实际发布状态见[本批验收](ASSISTANT-FINANCE-QUERY-ACCEPTANCE.md#assistant-finance-query-release)。

## 本人账户分析（已发布）

2026-09-19 16:20:25（北京时间）已发布九个操作：报告读取、明确更新公共参考汇率、账户分类／流动性设置、资金事件的列表／新增／修改／删除、精确区间核对及原操作回执读取。路径位于 `/api/finance-analysis/`，完整方法、字段、限制和恢复语义见[分析 API](FINANCE-ANALYSIS-API.md)，汇率来源与版本见[FX 合同](FINANCE-FX.md)。

仅当前家庭本人可读写；报告读取不出网，刷新须明确确认，写入带 CSRF。未知结果先读同一 requestId 的回执，再读当前报告；旧回执不复活已删事件。现有 `/api/finance-accounts` 的原币账户／估值合同不变，分析不与来源报告、持仓、共同荷包或付款账本加总。

## 库存售后待办（已发布）

完整字段、错误和恢复协议见[库存 API](INVENTORY-API.md#明确创建售后待办)，持久关系见[数据模型](DATA-MODEL.md#inventory-followup)，当前验证与发布边界见[售后待办验收](INVENTORY-FOLLOWUP-ACCEPTANCE.md)。本增量不新增 DDL，不写财务或云端。

| 方法 | 路径 | 用途与返回 |
|---|---|---|
| POST | `/api/inventory/acquisitions/<id>/followup` | 当前家庭成员提交原 `requestId`、物品 `itemRevision`、批次 `revision` 和 `data:{title,owner,due,note}`；首次 201、原意图重放 200，返回 `{operation,item,acquisition}`，`operation.entityId` 指向本地任务 |
| GET | `/api/inventory/acquisitions/<id>/followup` | 当前库存权限下返回 `{itemId,acquisitionId,state,task}`；`state` 为 `none\|linked\|deleted`，`none/deleted` 时 `task:null`，`linked` 的 `task` 仅含当前任务 `id/revision/title/owner/due/done/note` |

首次创建要求批次处于售后处理中，沿用当前会话、库存 ACL、CSRF、双版本和事务。每批次至多一条明确创建的家庭共享任务，负责人仅表示分工；文字来自明确输入，不自动复制私人物品名称、来源或金额。不同成员或不同请求号重复创建返回冲突；任务删除后保留关联，不自动补建。

原 key 有成功回执时直接重放，不再执行首次创建的状态与依赖校验；仍须具备当前身份和库存权限。任务后来修改、删除或售后关闭不改变历史 `entityId`。`GET /api/inventory/operations/<requestId>` 仍仅原发起者可读；共享成员通过 followup GET 读取当前任务，不能取得另一成员的回执。历史成功不等于任务当前存在，客户端应重读当前关联。

## 本人手动资产／负债账户（已发布）

接口由 [finance_accounts.py](../finance_accounts.py) 独立注册；完整字段、限制、错误码及会话核验见 [账户 API](FINANCE-ACCOUNTS-API.md)，三表与迁移边界见 [数据模型](DATA-MODEL.md#finance-accounts58)。全部仅当前家庭的本人可读写，匿名 401、电视 403、伙伴或其他家庭账户 404；不接受客户端 owner／visibility。写入须为同源 JSON 并带当前 CSRF，拒绝额外字段、重复查询参数和 JSON 重复字段。

| 方法 | 路径 | 用途与返回 |
|---|---|---|
| GET | `/api/finance-accounts` | 必填 `asOf`，可选 `status=active\|archived\|all`（默认 active）；返回本人所选账户、各自最近有效日期估值及分原币已知部分汇总 |
| POST | `/api/finance-accounts` | 原 `requestId`、`revision:0`、账户完整字段和首条估值；201 历史操作回执 |
| PATCH | `/api/finance-accounts/<id>` | 原 `requestId`、账户 revision 和非空 changes；只修改名称、机构、备注、归档／恢复，200 回执 |
| PUT | `/api/finance-accounts/<id>/valuations/<date>` | 原 `requestId`、账户 revision、amountCents；新增或纠正该日估值，200 回执；归档账户先恢复 |
| GET | `/api/finance-accounts/<id>/valuations` | page／pageSize 分页日期倒序历史，含当前账户元数据；归档账户仍可读 |
| GET | `/api/finance-accounts/operations/<requestId>` | 200 `{requestId,found,receipt}`；有历史时 receipt.replayed=true，没有时 found=false／receipt=null，不证明在途请求未提交 |

账户 id 为 24 位、requestId 为 32 位小写十六进制；没有物理删除接口。写入使用账户 revision CAS 和本人持久幂等记录，同原内容重放只返回历史，不把旧状态安装为当前账户。未知结果保留原编号与完整请求，先核对历史和当前列表，不自动换号重发。业务错误含 `{error,code}`，这是下文基础接口通用错误描述之外的模块契约。

估值日期只决定选择不晚于 asOf 的最近记录；名称和归档筛选使用账户当前状态。未知、零、缺少该日前记录分别显示。汇总不换汇、不与来源基线／持仓／公共资金相加，也不代表完整家庭净资产。本人 ZIP 导出已接入账户白名单；即使 includeShared=true 也不导出伙伴账户，详见 [账户导出](FINANCE-ACCOUNTS-PORTABILITY.md)。

## 已发布持仓：三条读取接口

这三条接口已于 2026-09-17 06:15:34 随持仓版发布，完整字段和状态码见 [持仓 API](INVESTMENTS-API.md)，使用见 [Expo 持仓](EXPO-INVESTMENTS.md)，实际验证见 [持仓发布验收](VALIDATION.md#expo-holdings-release)。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/finance-hub/investments` | 当前成员完整持仓与来源映射；不接受查询参数，客户端分币种精确汇总 |
| GET | `/api/finance-hub/investments/operations/<rid>` | 按 32 位原 requestId 读取手工操作的历史结果；不接受查询参数 |
| GET | `/api/finance-hub/investments/imports/receipts` | 仅接受唯一的 `sourceName`、`sourceDigest`，读取原文件的历史确认回执 |

三者均仅本人当前家庭可读：匿名 401、电视 403；未找到回执返回 404，但不能据此认定在途写入不会提交。原 POST／PATCH／DELETE 路径保留，新界面附原 requestId 并在重试时保持完整内容与版本；原文件确认仍只提交 previewToken。读到回执后另读当前持仓，不根据历史结果复活记录。持久化需 [已完成的 54→55 迁移说明](DATA-MODEL.md#investment-operations55)，没有新银行或云账户连接。

**历史版本：2026-09-15 20:23:00（北京时间），镜像 `sha256:651ecfd6bdb65cf04bb8778c8657a8ec0f27a123940683a44a8b9931a5f22352`。** 当时旅行资料、完整细项展示与分段定位已发布，保留此前全部模块；106 个方法／路径模板、43 张户内表（41 业务 + 2 认证）及 2 张平台表。源码与文档数量见 [README](../README.md) 及交接清单；测试、迁移和实际接入边界见 [VALIDATION](VALIDATION.md)。

> 本文保留基础版本 35 个 HTTP 操作的详细字段。历史平台扩展路由见 [路由索引](PLATFORM-ROUTES.md)，后续新增以本页模块入口与各自合同为准；新家庭、偏好、助理与旅行见 [平台扩展](PLATFORM.md)，账单/XLSX/投资见 [财务导入](FINANCE-IMPORT.md)，通用文件手动四列映射的字段与会话契约见 [列映射](FINANCE-COLUMN-MAPPING.md)。请勿把下方基础接口计数当作新版本总数。

## 旅行资料接口

旅行资料以下五个成员操作已于 2026-09-15 20:23:00 发布；该历史版本当时总计 **106 个方法／路径模板、43 张户内表及 2 张平台表**。请求、响应、文件校验和状态码见 [旅行资料契约](JOURNEY-DOCUMENTS.md)。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/journey-documents` | 带 `journeyId` 读取该旅行中本人和家人共享的资料；不带时读取本人资料库 |
| POST | `/api/journey-documents` | 上传一份 PDF 或图片；首次成功 201，相同 `requestId` 重放成功 200 |
| PATCH | `/api/journey-documents/<id>` | 上传者以 `revision` 修改标题、共享范围及旅行／分段关联 |
| DELETE | `/api/journey-documents/<id>` | 上传者以 `revision` 删除；清除文件并保留阻止旧请求复活的记录 |
| GET | `/api/journey-documents/<id>/file` | 身份核验后下载原 PDF 或净化后的 JPEG；返回附件，非 JSON |

五项均要求成员身份；匿名 401、电视 403，其他家庭或不可见资料 404。只有上传者可修改和删除，家人对明确共享且仍关联有效旅行的资料只读。写入仍使用同源 JSON、CSRF；POST 包含 Base64 文件，请求体上限 **7,200,000 字节**，原文件上限 **5,000,000 字节**，不适用下文常规 600,000 字节上限。并发版本或幂等冲突返回 409，不能自动覆盖或更换请求标识重发。

删除旅行后资料留在上传者的库中，并按仅本人可见处理。文件和下载地址不进入共享 state、日历、任务或助理；个人 ZIP 仅含允许导出的元数据，见 [数据副本](PORTABILITY.md)。

线上已于 2026-09-15 02:33:28 发布旅行细项、日历复核及[财务来源预览与 CAS 确认](FINANCE-SOURCE-BRIDGE.md)。本文第 5.5 节属于该版本；真实来源映射与余额日期尚需核对，未启用持续导入。

本文基础契约保留 2026-09-14 核对的 `app.py`、`cloud_accounts.py`、`cloud_providers.py`、`shopping_media.py` 和 `finance_baseline.py` 字段，供前端、后端和联合开发 Agent 对接。原范围为 **33 条显式路由注册、35 个业务 HTTP 方法操作**；本轮新增操作另列，不据此推断当前总数。Flask 自动生成的 `HEAD`、`OPTIONS` 不重复计数，动态实体类型也不展开计数。

成员会话功能已于 2026-09-15 07:58:24 发布：`GET /api/sessions`、`DELETE /api/sessions/<id>`、`POST /api/sessions/revoke-others`。完整字段、状态码及迁移恢复约束见 [成员登录设备](MEMBER-SESSIONS.md)；该 07:58 历史版本共 91 个 HTTP 方法/路径模板、31 张户内表（其中 2 张认证表）及 2 张平台表。基础 35 个操作仅保留原字段范围，不代表总数。

全部示例均为虚构数据；域名 `https://home.example.test`、账户标签、邮箱、ID、金额和凭证占位符不能用于生产。部署入口见 [README](../README.md)，存储与迁移见 [数据模型](DATA-MODEL.md)，协作约定见 [开发指南](DEVELOPMENT.md)，服务器配置见 [部署指导](DEPLOYMENT.md)。

<a id="投资持仓导入候选接口"></a>


## 旅行分段编辑快照（开发候选）

本批不新增路由或表。`GET /api/journeys/templates` 增加 `capabilities.editSourceSnapshot:true`；新版编辑同时要求它与 `supportedSchemaVersions` 中的 2。`GET /api/journeys/<id>` 返回同一数据库快照内的计划及关联记录。

`POST /api/journeys/preview` 针对已有 `journeyId` 可带 `expectedEntities`，即进入编辑时全部关联 trip、准备、采购及日程的实体编号→revision。新版必须提交该原始版本表；工作流版本、任一实体版本或完整关联集合变化返回 `409 stale_edit_source`，不能悄悄改用新版本覆盖草稿。省略字段的旧客户端保持兼容；格式错误为 400。

普通旅行预览有效期为 1800 秒，过期 apply 为 409。未知提交只按原 token／idempotencyKey 核对或重试；历史回执不等于当前详情，也不证明云端已同步。真实事务、撤权与兼容测试见 [快照契约](EXPO-JOURNEY-SEGMENTS-API.md)及[验收](EXPO-JOURNEY-SEGMENTS-ACCEPTANCE.md)，此段不表示候选已发布。

## 家庭例行计划接口

新版家庭例行计划已于 2026-09-17 19:21:11（北京时间）发布，复用原三张表，补充确认回执读回及过期恢复。前端恢复契约见 [Expo 例行计划 API](EXPO-ROUTINES-API.md)，实际安装状态仍以 [HANDOFF](HANDOFF.md) 为准。

- `GET /api/routines/context`：成员只读共享计划、当前项、未来日期和最近十期；可选 planId/page/includeArchived，每页 40，不在 GET 生成。
- `POST /api/routines/preview`：create/update/pause/resume/skip/archive，返回未来三期、当前操作将生成的事项、十分钟预览签名和 `operationKey`。
- `POST /api/routines/confirm`：仅 previewToken；原子重验会话、家庭、规则和当前实体版本、日期、容量，提交与回执同事务。相同成功 token 即使过期也只重放历史结果；只有持写锁确认过期且未执行时，才返回 410 `preview_expired_unapplied`，允许重新预览。
- `GET /api/routines/operations/<operation_key>`：发起者本人只读历史摘要，64 位小写十六进制编号；404 `routine_receipt_not_found` 不证明在途请求不会提交。当前计划另从 context 核对，不用历史回执恢复旧事项。

全家共享管理，但另一成员不能确认发起者的 token；TV 无管理读取或写权限，只通过原 state 看已生成共享实体。preview 字段、状态／错误、月末和 nextDates 语义见 [完整契约](ROUTINES.md)。新表初始为空，用户未确认计划前不产生事项；不调用云写入器，既有来源配置不能替代每期待办发布确认。


## 投资持仓导入接口

2026-09-15 08:56:01 发布新增 GET /api/finance-hub/investments/imports/template、POST /api/finance-hub/investments/imports/preview 及 POST /api/finance-hub/investments/imports/confirm，均要求本人成员身份；POST 适用同源与 CSRF 校验，电视无权访问。接口完整请求、响应、文件列、金额/日期规则、来源映射、预览期限、409 和重复确认见 [投资持仓契约](INVESTMENT-IMPORT.md)。该增量已发布；现行完整结构见 [路由与存储索引](PLATFORM-ROUTES.md)，基础契约和历次版本不混同，实际验收见 [VALIDATION](VALIDATION.md)。

## 同步状态增量接口

2026-09-15 10:43:53 已发布只读 `GET /api/sync-health`（成员专用），以及既有 `GET /api/state` 中的 `sync.health`（家庭聚合，TV 可读）。它不写数据库、不访问第三方、不重试队列；完整字段、原因码、5 分钟阈值、发布问题权限与 503 见 [同步状态契约](SYNC-HEALTH.md)。该 10:43:53 历史版本总计 95 个 Flask 方法/路径模板且无 schema 变化；当时后续版本扩展到 106 个方法/路径模板、43 张户内表与 2 张平台表；现行结构见页首及路由索引。

## 1. 通用约定

### 1.1 请求和返回

- 接口与页面同源，路径以 `/api/` 开头；OAuth 浏览器导航使用 `/auth/`。没有 `/v1` 版本前缀、OpenAPI 自动生成或统一响应信封。基础实体接口不提供分页、按日期查询或服务端全文搜索；扩展接口按各自契约处理，例如采购实付 `context` 支持 `q/page`，固定 `pageSize=40`。
- 正常 JSON 返回为对象、数组或 `null`，取决于接口。只有明确写出的新增操作返回 `201`；其余成功 JSON 操作返回 `200`。前端不能统一假设存在 `data`、`items` 或 `ok`。
- 写请求一律 `Content-Type: application/json`。无业务字段的写请求也发送 `{}`，包括退出、触发同步和解除绑定。除另有说明，主体必须是 JSON 对象。
- 常规请求体上限为 **600,000 字节**；`POST /api/photos` 为 **8,000,000 字节**，财务文件导入请求为 **3,000,000 字节**。02:33 已发布的来源预览／确认 HTTP 请求同样最多 **3,000,000 字节**，但其中 `candidate` 经规范化后的 UTF-8 JSON 独立限制为不超过 **1,950,000 字节**；准备文件时应控制在约 **1.95 MB 以下**，不能把 3 MB 当作可用候选内容大小。候选还须通过既有基线的完整封装大小校验。代理层上限见部署文档。
- 时间戳使用带时区 ISO 8601；本地日程会转换到 `Asia/Shanghai`。纯日期使用 `YYYY-MM-DD`，个人月度财务使用 `YYYY-MM`。
- 业务金额是整数“分”，禁止浮点元和布尔值；大部分业务字段范围为 `0..100000000000`。财务基线采用独立、更大的范围。采购的未知金额为 `null`，不能当作 `0`。
- 本地实体使用字段白名单重建保存内容，未定义字段一般被忽略；没有通用的“拒绝全部未知字段”机制。云端任务 PATCH 是例外，只允许 `revision`、`done`。
- `/api/` 和 `/auth/` 响应设置 `Cache-Control: no-store`。不要把包含家庭内容的响应写入公共 CDN、共享浏览器缓存或未经隔离的 Service Worker 缓存。

### 1.2 角色、Cookie 和 CSRF

| 标记 | 身份 | 能力 |
| --- | --- | --- |
| 公开 | 无会话 | 访问页面壳、健康检查、查看平台配置状态、登录、发起和轮询电视配对 |
| 成员 | 两个预建本地成员之一，`role: "member"` | 编辑家庭共享内容；仅能管理自己的云端账户和读取自己的私有财务 |
| 电视 | 已批准且未过期的设备 Cookie，`role: "tv"` | 只读共享状态和已附加采购图片；不读取账户管理和私有财务 |

本地账号标识固定为 `member1`、`member2`，不是公开注册系统。显示名称可修改。成员使用 Flask 签名会话 Cookie，默认 `HttpOnly`、`Secure`、`SameSite=Lax`，Cookie 签名按签发时间验证，最多接受 30 天，普通读取不续签；实际成员访问还受下述服务端期限限制。会话内容并非加密保险箱，不应加入令牌或财务明细。成员密码变更会递增 `auth_version`，使旧会话失效。

已发布的服务器会话登记：签名有效之外，还必须存在本人、版本相符、未撤销且未到期的会话行。默认从本次登录/改密起固定 30 天；OAuth 更新 Cookie 不延长这条服务端期限。退出登录先撤销服务端会话，复制的同一凭据也失效；改密撤销本人旧会话，再为当前浏览器签发新会话和 CSRF。旧版合法 Cookie 按一次性的迁移截止时间和原有效期受控接纳，不把缺失的新会话行重新注册。

`SESSION_REFRESH_EACH_REQUEST=False` 继续保证普通读取不重签身份 Cookie。未登录界面首先请求 `/api/me` 建立匿名浏览器关联；有可关联 Cookie 的显式认证通过浏览器代次和最终事务复核防止旧流程重新取得身份。迟到 Cookie 仍可能使页面需要重登；没有预先关联 Cookie 的首次并发直接 API 登录，以及已开始的普通业务响应不在全面取消保证内。具体边界见会话契约。

电视 Cookie 名为 `household_tv`，`HttpOnly`、`Secure`、`SameSite=Strict`，配对后有效 90 天；服务器仅保存设备密钥的 SHA-256。请求头 `X-Display-Mode: tv` 会跳过成员会话，使用电视身份，适合同一浏览器同时打开成员页面和 `/tv`。这个请求头本身不授予身份，没有有效设备 Cookie 仍未登录。

所有 `/api/` 写请求均校验已提供的 `Origin` 是否与当前请求的服务端 origin 一致；**当前实现允许缺省 Origin**。除 `/api/login`、`/api/pair/start`、`/api/pair/poll`、`/api/spaces/redeem` 外，还必须满足：

1. 有效成员会话，电视写入返回 `403`。
2. `X-CSRF-Token` 与当前成员会话一致；从 `GET /api/me` 读取，登录或退出后重新获取。
3. `Content-Type` 为 JSON。当前没有 Bearer API token、API key 或跨域 CORS 接入方式。

```javascript
// 浏览器同源调用示例；真实凭证不要写进源码。
await fetch('/api/me', { credentials: 'same-origin' });
await fetch('/api/login', {
  method: 'POST', credentials: 'same-origin',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'member1', password: 'USER_ENTERED_PASSWORD' })
});
const { csrf } = await (await fetch('/api/me', {
  credentials: 'same-origin', cache: 'no-store'
})).json();
const response = await fetch('/api/items/shopping', {
  method: 'POST', credentials: 'same-origin',
  headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
  body: JSON.stringify({ title: '示例收纳盒', budget: 2500, actual: null, photoIds: [] })
});
if (!response.ok) throw new Error('创建失败，请读取并显示安全的错误提示');
```

### 1.3 错误和限流

受控业务错误统一为 `{"error":"可向用户显示的中文提示"}`。不要依赖中文字符串作为机器错误码，当前尚无稳定的 `code` 字段。未捕获异常、框架 404/405 或代理错误不保证 JSON 格式。

| HTTP | 含义和客户端动作 |
| --- | --- |
| `400` | 字段、格式、金额、引用、上限或业务约束不正确；展示提示，保留草稿 |
| `401` | 未登录、密码不正确，或云端授权失效；云端错误不等于本地 Cookie 一定过期，应区分调用场景 |
| `403` | 电视写入、私有接口无权、CSRF/Origin 不符、同步日历只读，或云端拒绝权限 |
| `404` | 记录/云端账户/图片不存在或不可见；对他人成员的云端账户也使用 404 |
| `409` | 本地 revision、云端版本、来源变化、主清单冲突、同步锁忙，或认证请求已被较新浏览器代次替代；重新发起对应流程 |
| `410` | 电视配对密钥已过期或不存在 |
| `413` | 请求体或图片超过字节限制 |
| `415` | API 写请求不是 JSON |
| `429` | 请求过频、图片解码槽正忙，或云端限流；延迟重试，不能高频循环 |
| `502` | 云端响应、连接、分页或授权交换失败；保留已显示的上次成功内容 |
| `503` | 平台尚未配置，或原家庭存储暂不可用；缺库切换不宣称已退出，不用空库重新初始化身份 |
| `504` | 单次云端读取预算超时 |

本地限流按 **客户端 IP + 操作类别** 计算，代理必须正确传递真实来源。登录 20 次/10 分钟；发起配对 10 次/10 分钟；批准配对 20 次/10 分钟；OAuth 登录启动 30 次/10 分钟；OAuth 绑定启动 20 次/10 分钟；图片上传 30 次/10 分钟；手动同步 10 次/分钟。当前没有统一 `Retry-After` 契约，配对轮询也没有单独的速率参数接口。

## 2. 基础 HTTP 操作索引

下表列出显式成功状态；通用认证、请求体、业务和云端错误仍可能适用。

| 方法 | 路径 | 身份 | 成功结果 |
| --- | --- | --- | --- |
| GET | `/healthz` | 公开 | `200 {"status":"ok"}` |
| GET | `/` | 公开 | `200` 页面壳，内容另行鉴权 |
| GET | `/tv` | 公开 | `200` 同一页面壳，进入电视流程 |
| GET | `/demo` | 公开 | `200` 同一页面壳，使用前端演示数据 |
| GET | `/static/<path:name>` | 公开 | `200` 静态资源；不存在为框架 404 |
| GET | `/api/me` | 公开 | `200` 当前身份和 CSRF，未登录也返回 200 |
| POST | `/api/login` | 公开 | `200 {"ok":true}`，设置成员会话 |
| POST | `/api/logout` | 成员 | `200 {"ok":true}`，清会话并删除电视 Cookie |
| POST | `/api/profile` | 成员 | `200 {"ok":true}` |
| GET | `/api/state` | 成员/电视 | `200` 全量共享状态 |
| POST | `/api/items/<kind>` | 成员 | `201 {"id":"…","revision":1}`；云端新建另有 `ok` |
| PATCH | `/api/items/<kind>/<uid>` | 成员 | `200 {"ok":true}`；云端任务另有 `id`、`revision` |
| DELETE | `/api/items/<kind>/<uid>` | 成员 | `200 {"ok":true}` |
| PUT | `/api/finance` | 成员 | `200 {"ok":true}` |
| GET | `/api/private-finance` | 成员本人 | `200` 本人的月度记录或初始值 |
| PUT | `/api/private-finance` | 成员本人 | `200 {"ok":true}` |
| GET | `/api/finance-baseline/private` | 成员本人 | `200` 本人导入快照，未导入为 JSON `null` |
| POST | `/api/calendar/import` | 成员 | `200 {"imported":N,"note":"…"}` |
| POST | `/api/photos` | 成员 | `201 {"id":"…","url":"/api/photos/…"}` |
| GET | `/api/photos/<uid>` | 成员/电视，另校验照片可见性 | `200 image/jpeg` |
| POST | `/api/pair/start` | 公开 | `200 {"code":"…","secret":"…","expiresIn":600}` |
| POST | `/api/pair/poll` | 公开，持有配对密钥 | `200 {"approved":false或true}` |
| POST | `/api/pair/approve` | 成员 | `200 {"ok":true}` |
| GET | `/api/devices` | 成员 | `200` 已配对且未过期的设备数组 |
| PATCH | `/api/devices/<uid>` | 成员 | `200 {"ok":true}` |
| DELETE | `/api/devices/<uid>` | 成员 | `200 {"ok":true}` |
| GET | `/api/auth/providers` | 公开 | `200 {"providers":[…],"origin":"…"}` |
| GET | `/auth/<provider>/login` | 公开浏览器导航 | `302` 跳转供应商或站内错误入口 |
| GET | `/api/accounts` | 成员本人 | `200 {"accounts":[…],"providers":[…]}` |
| POST | `/api/accounts/bind` | 成员本人 | `200 {"url":"供应商授权地址"}` |
| GET | `/auth/<provider>/callback` | 浏览器绑定的 OAuth 状态 | `302` 回到正式 origin；详情见第 9 节 |
| GET | `/api/accounts/<account_id>/sources` | 账户所属成员 | `200 {"sources":[…],"selected":[…]}` |
| POST | `/api/accounts/<account_id>/sources` | 账户所属成员 | `200 {"ok":true,"queued":true}` |
| POST | `/api/accounts/<account_id>/sync` | 账户所属成员 | `200 {"ok":true,"queued":true}` |
| DELETE | `/api/accounts/<account_id>` | 账户所属成员 | `200 {"ok":true}` |

## 3. 会话、个人资料和状态读取

### 3.1 登录、身份、退出

`POST /api/login` 接收 `username`、`password`。实现查询前分别截断到 80、256 字符；登录字段并非用于修改账号资料。失败返回 `401`，成功清除旧 session，创建新的成员会话和 CSRF。

`GET /api/me` 示例：

```json
{
  "user": {
    "id": "member1", "username": "member1", "name": "示例成员甲",
    "auth_version": 1, "role": "member"
  },
  "csrf": "SESSION_CSRF_PLACEHOLDER"
}
```

未登录是 `{"user":null,"csrf":null}`。电视 `user` 包含 `id`、`role`、`name`、`focus`、`calendarView`，`csrf` 为 `null`，不含用户名或成员版本。

`POST /api/logout` 接收 `{}`。由于通用写权限，当前电视身份不能直接调用该接口退出；成员可删除设备，电视 Cookie 到期也会失效。

### 3.2 更新资料

`POST /api/profile`：`name` 必填，去除首尾空白后 1–20 字符。`password` 缺省/空表示不修改密码；非空时必须是 12–128 字符并携带正确的 `currentPassword`，否则 `400/403`。

```json
{"name":"示例成员甲","currentPassword":"OLD_PASSWORD_PLACEHOLDER","password":"NEW_PASSWORD_PLACEHOLDER"}
```

此接口不支持修改 `username`、添加成员或修改另一位成员。没有 profile revision 参数。

### 3.3 全量状态

`GET /api/state` 返回以下顶层字段，不接受过滤和分页参数：

| 字段 | 内容 |
| --- | --- |
| `events`、`tasks`、`shopping`、`trips` | 各实体数组；每条含 `id`、`revision` 和类型字段 |
| `finance` | 家庭共同资金手动快照，含自己的 `revision` |
| `wealth` | 每位已导入成员的**共享白名单**资产基线数组；未导入为空数组 |
| `people` | 两个成员的 `id`、`name` |
| `display` | `calendarView`、`focus`；电视来自设备设置，成员默认 `today`、`null` |
| `revision` | 全局状态变更版本，用于决定重绘；不是实体编辑 revision |
| `updatedAt` | 本次响应生成时间；不是最后一笔数据更新时间 |
| `sync` | 轮询间隔、连接数量、选中来源、共享清单来源和安全错误摘要 |
| `integrations` | 面向界面的文字说明，非能力枚举协议 |

状态按 `updated_at DESC` 取实体，之后分组；同时间不承诺稳定顺序。客户端应自行按日程时间等排序。共享响应不会包含个人月度财务、私有账户明细、OAuth 邮箱/令牌、密码和财务导入私有原文；但**选中的日历完整标题/地点和共同任务内容均为家庭共享**，日程 `owner` 是归属标签，不是逐条隐私 ACL。

`sync` 的形状：

```json
{
  "mode":"polling", "taskIntervalSeconds":30, "calendarIntervalSeconds":60,
  "configured":true, "connectedAccounts":1, "selectedSources":2,
  "lastSuccess":"2026-01-15T04:00:00+00:00", "error":"",
  "primaryTaskSource":{"id":"local-source-id","name":"示例共同清单"},
  "taskSources":[{"id":"local-source-id","name":"示例共同清单","provider":"microsoft","writable":true}]
}
```

无主清单时 `primaryTaskSource: null`；无成功时间为 `""`。`lastSuccess` 是各来源成功时间最大值，**不证明每个来源均成功**。逐来源状态由账户拥有者在 `/api/accounts` 查看。前端当前约 10 秒读取一次全量状态，未使用 ETag、SSE 或 WebSocket。

## 4. 实体 CRUD 与字段

`kind` 仅为 `tasks`、`shopping`、`events`、`trips`。本地创建每种最多 2,500 条。这个限制不是整个系统唯一记录限制；云端镜像有单独上限，见第 9 节。

### 4.1 通用写入与并发

- `POST /api/items/<kind>` 创建时不需要 revision。返回 ID 后重新获取状态，获得服务端规范化字段。
- `PATCH /api/items/<kind>/<uid>` 必须发送当前记录的 `revision`。本地实体会先合并已有值与请求，再做完整校验，因此允许局部字段更新。请求过期返回 `409`，不存在返回 `404`。
- `DELETE /api/items/<kind>/<uid>` 主体为 `{"revision":2}`。删除不存在或 revision 不符均为 `409`；当前没有幂等删除成功语义。
- 本地 PATCH 成功只返回 `{"ok":true}`，不返回新 revision；重新 GET 状态，不能继续使用旧版本。
- 不要提交 `/api/state.revision` 作为实体版本。发生冲突后重新读取、保留本地草稿并让用户比较，不可静默把旧数据强制覆盖。
- 云端镜像 ID 以 `cloud-` 开头；客户端应以 `sync` 对象决定能力，不能仅根据 ID 前缀判断。
- 删除旅行会保留 `tripId` 指向该旅行的待办、采购和日程；将这些实体的 `tripId` 设为 `""`、移除 `journeyId` / `workflowKey`，并分别递增 revision。不删除已发布的远端日历或任务。

**旅行 v2 受管事件：** 普通创建接口不接受 `travelTiming`、`startDate` 或 `endDateExclusive`，提交返回 400。已有事件同时带 `travelTiming` 且仍由 `journey_links` 管理时，可以通过带 revision 的普通 PATCH 独立修改标题、地点、备注、负责人等非时间字段；改变起止时刻、全天类型或旅行关联返回 409，必须走旅行预览／确认流程。未受管的普通事件也不能通过 PATCH 自行添加旅行时间字段。旅行定时 UTC 与日期型全天字段见 [旅行接口契约](PLATFORM-API.md)。

```json
{"revision":2,"done":true}
```

上面可用于勾选本地任务、采购或云端同步任务。云端同步任务不能带额外标题、负责人、备注字段。

### 4.2 字段表

各类型均有：`title` 必填，去除首尾空白后 1–100 字符；读取时增加不透明字符串 `id`、正整数 `revision`。云端读取字段的长度上限不同，见 4.3。

| 类型 | 字段 | 默认/校验 |
| --- | --- | --- |
| tasks/shopping | `done` | 布尔值，默认 `false`，拒绝字符串或数字 |
| tasks/shopping | `owner` | `shared` / `member1` / `member2`，默认 `shared` |
| tasks/shopping | `note` | 字符串，默认 `""`，最多 500 字符 |
| tasks | `due` | 可选日期，默认 `""`；空值标准化为空字符串 |
| tasks | `tripId` | 默认 `""`；非空必须引用现存旅行 ID |
| shopping | `quantity` | 默认 `"1 件"`，1–30 字符；是自由文本，不是数值数量 |
| shopping | `budget` | 整项预计总价，整数分或 `null`；缺省为 `null` |
| shopping | `actual` | 整项实际总价，整数分或 `null`；缺省为 `null` |
| shopping | `photoIds` | 默认 `[]`，最多 3 个不重复的 32 位小写十六进制图片 ID |
| events | `owner` | 同上，默认 `shared` |
| events | `location` | 默认 `""`，最多 200 字符 |
| events | `note` | 默认 `""`，最多 8,000 字符 |
| events | `start`、`end` | 必填 ISO 时间戳；无时区按北京时间解释；结束不能早于开始 |
| events | `allDay` | 默认 `false`；当前通过布尔转换，调用方应发送真正的 JSON boolean |
| events | `source` | 默认 `"手动"`，1–30 字符的显示来源标签 |
| events | `imported` | 默认 `false`；当前通过布尔转换，只是文件导入标记 |
| trips | `destination` | 默认 `""`，最多 80 字符 |
| trips | `start`、`end` | 必填日期，结束不能早于开始 |
| trips | `budget`、`saved`、`paid` | 非负整数分，缺省为 `0`；分别为预算、已预留、已付款 |
| trips | `note` | 默认 `""`，最多 2,000 字符 |

`owner` 不能作为“只有该成员可见”使用。购物 `budget` 是整项总额，不自动乘以 `quantity`；勾选、实付记录和旅行预留均**不会自动产生公共账户流水或扣减荷包余额**。旧购物记录可能尚无新增字段，读端应把缺少 `budget/actual` 视为 `null`、缺少 `photoIds` 视为 `[]`，下一次合法编辑会写回标准字段。

普通本地及旅行 v1 全天事件的起止时间会归一到北京时间零点，`end` 为**排他结束**。相同开始/结束日会补成至少一天。旅行 v2 全天事件使用独立日期语义，不能套用上述北京时间归一规则；定时事项保留确认后的 UTC 时刻与当地时区元数据。非全天普通事件允许零时长。当天、周视图、前后 3 天和工作量统计均为前端计算，不存在分别的日程查询接口。

```json
{
  "title":"示例午餐", "owner":"shared", "location":"示例地点",
  "start":"2026-01-15T12:00:00+08:00", "end":"2026-01-15T13:00:00+08:00",
  "allDay":false, "source":"手动", "imported":false
}
```

```json
{
  "title":"示例收纳盒", "owner":"shared", "done":false,
  "quantity":"2 件", "note":"示例备注", "budget":2500, "actual":null,
  "photoIds":["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
}
```

### 4.3 云端任务写回与同步日历

读取的镜像实体增加：

```json
{
  "sync": {
    "provider":"microsoft", "sourceId":"local-source-id", "remoteId":"remote-item-id",
    "version":"opaque-provider-version", "readOnly":true
  }
}
```

`readOnly` 在日程上为 `true`，任务为 `false`，但 `false` 仅代表当前支持新建/勾选，不是任意字段可写。镜像标题和日程地点最多 2,048 字符、任务备注最多 8,000 字符；过长数据会使该次同步失败并保留旧快照，而非无提示截断。这与本地创建的较短输入限制不同。

- 同步日程 PATCH、所有镜像 DELETE 返回 `403`；应在原日历/原清单修改或删除，下一次成功同步反映到看板。
- 同步任务 PATCH 严格只接受 `revision`、`done`；其余字段返回 `400`。写回前核对本地 revision 和云端版本；可用时发送 `If-Match`。冲突返回 `409`。
- 新建任务可额外传 `sourceId`。省略或 `null`：有共同主清单则写入该清单，没有则创建本地任务；`""`：明确本地创建；非空：写入该已选择的任务来源。
- 云端新建必须 `owner:"shared"` 且 `tripId:""`。两位成员均可向已选共同任务来源写入，使用来源拥有者在服务器保存的授权；这与“账户管理仅本人”是不同权限边界。
- 新建远端任务实际发送标题、备注和日期；当前不会把创建请求的 `done` 传给供应商。需要创建后标记完成时，再使用返回的 `id/revision` 调用 PATCH。
- 云端新建成功为 `201 {"ok":true,"id":"cloud-…","revision":1}`；云端 PATCH 成功为 `200 {"ok":true,"id":"cloud-…","revision":N}`。远端调用失败不会回退为一条本地任务。
- 写入确认后有约 120 秒的本地已确认结果保护，防止供应商短暂返回旧快照使勾选回跳；这不是离线写队列。失败的新建请求没有通用幂等键，网络结果不明时先同步核查，不要立即重复创建。

## 5. 公共与私人财务

### 5.1 公共资金快照

`GET /api/state.finance` 读取；`PUT /api/finance` **整份替换**。请求必须带 `revision` 和以下所有金额字段，缺少任一金额将返回 `400`：

| 字段 | 含义 |
| --- | --- |
| `wallet` | 核对后的公共荷包余额 |
| `livingSpent`、`livingBudget` | 本月日常已支出、预算 |
| `travelSaved`、`travelAnnualBudget` | 旅行预留、年度旅行预算 |
| `longterm` | 共同长期储蓄 |
| `reserveTarget` | 荷包保留目标 |
| `upcomingPayments` | 已知近期付款 |
| `contributionPercent` | 整数百分比，0–100，缺省 50；不是金额分 |
| `note` | 默认空字符串，最多 500 字符 |
| `confirmedAt` | 由服务器写入当前时间，请求提供的值被忽略 |

初次数据库初始化的配置值见 `app.py:DEFAULT_FINANCE`；部署已有数据库不会因修改这个常量而自动覆盖已保存预算。这里的 `0` 是现有接口的初始值，不保证余额已真实核对，应结合 `confirmedAt` 显示状态。版本不匹配为 `409`。该接口没有账单明细、收入自动划拨、理财交易或外部账户同步能力。

### 5.2 本人月度快照

`GET/PUT /api/private-finance` 始终按会话成员读取或写入；没有 `owner` 查询参数可以切换他人。电视返回 `403`。

未建记录返回：`income:0`、`spent:0`、`budget:0`、当前 `month`、`revision:0`。已建记录还包含服务器写入的 `confirmedAt`。

```json
{"income":10000,"spent":2500,"budget":5000,"month":"2026-01","revision":0}
```

PUT 要求三个非负整数金额和有效月份，首次保存 `revision` 必须为 `0`；后续必须是当前 revision，否则 `409`。**每人只有一份当前快照**，更换 `month` 是覆盖，当前没有月度历史列表或明细流水接口。该快照与导入资产基线是独立存储，彼此不覆盖。

### 5.3 导入资产基线的读取和共享边界

`GET /api/finance-baseline/private` 返回当前成员原始导入私有对象加 `revision`；本人未导入时为 JSON `null`，不能当成空资产证明。电视返回 `403`。共享资产概览从 `/api/state.wealth` 获取，不调用私有接口。

共享白名单只有：`schemaVersion`、`owner`、`asOf`、`importedAt`、`currency`、`sourceDigest`、`balanceAsOfStart`、`balanceAsOfEnd`、`complete`、`assetCents`、`liabilityCents`、`netCents`、`recordedAssetCents`、`recordedLiabilityCents`、`coverage`、`coverageNote`、`excluded`，以及数据库 `revision`。导入和读出都应用白名单，来源文件中的未知公共字段不会直接透出。`coverage`、`coverageNote` 由服务端重建，不能用自定义字符串夹带账户详情。

`excluded` 只保留布尔标记：`missingValuations`、`unconfirmedTransfers`、`foreignCurrencyConversion`、`unvestedCompensation`、`unconfirmedCreditBalances`，缺省为 `false`。

`complete:false` 时 `assetCents/liabilityCents/netCents` 必须为 `null`，仅展示已记录人民币小计，不可据此计算完整净资产。`asOf` 是导入数据版本日期，余额来源日期范围是另两个字段；它们不保证各项来自同一天，也不是实时资产估值。私有数据包含账户、收入和可选消费/来源细节，只能本人读取，**不能拼入共享 `wealth` 或静态 HTML**。

### 5.4 基线导入 CLI 契约

此处为保留的维护者整份导入 CLI 契约。常规来源更新使用第 5.5 节 HTTP 预览／CAS 流程，不通过旧 CLI 绕过本人确认。管理员在备份后运行 `python -m finance_baseline --database /data/household.sqlite3`，或本地包装 `python deploy/import-finance-baseline.py --database <DB>`，经标准输入传一个 UTF-8 JSON 对象，顶层必须恰好为 `private`、`shared`。示例数据库仅属于原家庭，其他家庭须先核对注册 ID 和目标库。完整步骤见 [部署指导](DEPLOYMENT.md) 与 [数据模型](DATA-MODEL.md)。真实 JSON 不进入源码、演示、命令参数或日志。

两份对象必须一致的必填元数据：

| 字段 | 约束 |
| --- | --- |
| `schemaVersion` | 精确整数 `1` |
| `owner` | 现存的 `member1` 或 `member2` |
| `currency` | `CNY` |
| `sourceDigest` | 64 位小写十六进制来源摘要 |
| `asOf`、`balanceAsOfStart`、`balanceAsOfEnd` | 严格 `YYYY-MM-DD`；开始 ≤ 结束 ≤ asOf |
| `importedAt` | 带时区 ISO 时间戳，最多 40 字符 |

私有 `totals` 必须与 shared 的六个汇总字段值和类型逐一相同。`assets`、`liabilities`、`income` 必须为数组，每类最多 500 条。每条必填 `label`、`category`、`status`、`source`（各 1–2,000 字符），`asOf` 日期、`currency`（3 位大写字母）、`amountCents`（非负整数或 `null`）。资产和负债项额外必填 `includedInRecordedSubtotal` 布尔值；为 true 的项目必须是 CNY 且金额不为空，逐项和必须等于共享已记录小计。外币不会自动换汇。

基线金额范围为绝对值不超过 `100000000000000` 分，负值只允许在 `netCents`、`netSpendCents`；递归出现的 `*Cents` 字段也受检查。JSON 大小最多 2,000,000 字节，结构深度最多 20。私有扩展字段当前不是完整的强类型 schema，新增字段要同时考虑渲染、证据口径和隐私测试。

以下是一个最小的**虚构格式例子**，来源摘要仅为占位符，不代表真实源文件：

```json
{
  "private": {
    "schemaVersion":1, "owner":"member1", "currency":"CNY",
    "sourceDigest":"0000000000000000000000000000000000000000000000000000000000000000",
    "asOf":"2026-01-15", "balanceAsOfStart":"2026-01-14", "balanceAsOfEnd":"2026-01-15",
    "importedAt":"2026-01-15T06:00:00+00:00",
    "totals": {
      "complete":false, "assetCents":null, "liabilityCents":null, "netCents":null,
      "recordedAssetCents":100000, "recordedLiabilityCents":25000
    },
    "assets":[{
      "label":"示例储蓄", "category":"cash", "status":"observed", "source":"虚构来源",
      "asOf":"2026-01-14", "currency":"CNY", "amountCents":100000,
      "includedInRecordedSubtotal":true
    }],
    "liabilities":[{
      "label":"示例借款", "category":"loan", "status":"observed", "source":"虚构来源",
      "asOf":"2026-01-15", "currency":"CNY", "amountCents":25000,
      "includedInRecordedSubtotal":true
    }],
    "income":[]
  },
  "shared": {
    "schemaVersion":1, "owner":"member1", "currency":"CNY",
    "sourceDigest":"0000000000000000000000000000000000000000000000000000000000000000",
    "asOf":"2026-01-15", "balanceAsOfStart":"2026-01-14", "balanceAsOfEnd":"2026-01-15",
    "importedAt":"2026-01-15T06:00:00+00:00",
    "complete":false, "assetCents":null, "liabilityCents":null, "netCents":null,
    "recordedAssetCents":100000, "recordedLiabilityCents":25000,
    "excluded":{"missingValuations":true}
  }
}
```

`complete:true` 则要求完整三个金额非空，完整资产/负债等于各自已记录小计，净值等于资产减负债。CLI 验证结构和汇总一致性，**不能代替人对证据完整性作判断**。

导入只 upsert 对应成员基线并在变化时递增全局状态版本，保留实体、图片、云端绑定、公共和个人月度快照。同样的有效内容重复导入不变更版本，比较时忽略顶层 `importedAt`；只改来源摘要或其他内容可能视为新版本。成功退出 0，仅输出 `{"status":"imported或unchanged","counts":{"assets":N,"liabilities":N,"income":N}}`；失败退出 1，stderr 为固定提示，不回显私有数据。

### 5.5 来源候选、预览与确认

以下表格说明默认完整财产基线模式，完整字段见 [FINANCE-SOURCE-BRIDGE](FINANCE-SOURCE-BRIDGE.md)。显式 mode=spending_observation 复用同三条路由：状态返回两套版本，预览附四个 expected 字段及未知覆盖确认，确认提交同一 candidate 和 previewToken；其独立字段与双表写入见 [SPENDING-OBSERVATIONS](SPENDING-OBSERVATIONS.md)。该分支不写原 finance_baselines／finance_source_receipts，不重算共享资产／负债。三个方法不重复计入总路由数。

| 方法 | 路径 | 请求与成功结果 |
| --- | --- | --- |
| GET | `/api/finance-baseline/imports/status` | 返回 `{current,lastReceipt,coverage,warnings}`；无基线时 current 为 null，否则含 revision/sourceDigest 与来源日期 |
| POST | `/api/finance-baseline/imports/preview` | `{candidate,expectedRevision,expectedSourceDigest}` → 日期、覆盖、服务器重算的 private/shared、`changes:{added,updated,preserved}`、20 分钟 previewToken；不写基线或回执 |
| POST | `/api/finance-baseline/imports/confirm` | `{candidate,previewToken}` → `{receiptId,status,revision,sourceDigest,candidateDigest,acceptedAt,replayed}`；原子 CAS 更新和持久回执 |

两个模式均限定当前家庭本人成员会话，匿名 401、TV 403，POST 使用 CSRF 与同源守卫。默认完整基线分支按白名单更新本人基线和获准共享的资产／负债小计；独立观察只写本人观察两表，原基线与共享小计保持不变。预览绑定本人／家庭／有效会话及相应版本和内容；过期、版本或来源冲突返回 409 并保留旧值。重复确认使用各自持久回执，不把历史结果当当前快照。

`deploy/prepare-finance-source.py --config <源码外私人配置.json> --output <源码外候选.json>` 从已完成的本地产物生成候选，不刷新邮箱、不读取服务器凭据、不导入数据库。固定白名单来源须逐条建立稳定映射，run／哈希／字节数和业务日期须通过校验；缺源、未知映射或贷款余额日期缺失时拒绝生成。候选不写入实付账本、手工投资或公共荷包，也不将这些存储与基线相加。普通来源更新须走“准备 → 本人预览 → 确认”；未经配置的来源不能靠空数组覆盖旧数据。

## 6. 采购照片

### 6.1 上传和关联

`POST /api/photos` 接收 JSON `dataUrl`，不是 multipart/form-data：

```json
{"dataUrl":"data:image/jpeg;base64,VALID_BASE64_IMAGE_PLACEHOLDER"}
```

示例不是可解码图片。真实上传成功：

```json
{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","url":"/api/photos/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

之后把 ID 放入采购创建/更新的 `photoIds`。上传和采购保存是两次调用；采购事务会校验全部图片权限并更新引用，如果任一图片不可用，整笔采购修改回滚。`photoIds` 为整份引用列表，省略已有 ID 等于解除关联。

限制与处理：

- 接受严格的 JPEG/PNG/WebP base64 data URL，字符串不超过 7,000,000 字符；原始解码字节不超过 5,000,000，像素总数不超过 4,000,000。格式标签和实际图片都必须可验证。
- 服务端处理 EXIF 方向、缩至最长边 1,600 像素，以新 RGB 画布输出 JPEG，剥离 EXIF、GPS、注释和色彩配置；透明部分变白。输出不超过 2,000,000 字节。
- 单进程同时最多一个解码任务，忙时 `429`。库容量最多 500 张、累计 200,000,000 字节；空间满为业务 `400`。
- 前端选图原始文件最多 20 MB 并尝试压缩，不等于服务器接受 20 MB。HEIC、SVG 等并无原生上传支持，需先转换为受支持格式。
- 同一张图最多在单件采购中出现一次，每件最多 3 张。已共享图片可被其他家庭成员引用到另一采购项，并非只能原上传者再次关联。

### 6.2 读取和删除语义

`GET /api/photos/<uid>` 成功始终返回净化后的 `image/jpeg`，带 `Content-Disposition: inline; filename="shopping.jpg"` 和 `no-store`。

| 图片状态 | 上传者 | 另一成员 | 已配对电视 | 未登录 |
| --- | --- | --- | --- | --- |
| 已上传但从未关联/已无任何采购引用 | 200 | 404 | 404 | 401 |
| 至少关联一个采购项 | 200 | 200 | 200 | 401 |

没有独立照片 DELETE 接口。修改采购移除 ID 或删除采购会移除引用；最后一项引用消失后立即收回家庭共享可见性。无引用且上传时间超过 24 小时的照片在**下一次上传请求**清理，不是固定后台定时删除，上传者在清理前仍可读取。照片 BLOB 随 SQLite 在线备份保存，不在公开 static 目录。

## 7. 电视配对与显示设置

每台设备的 `layout` 已于 2026-09-15 09:47:39 发布，包括卡片顺序、隐藏项、主题和密度。仍使用既有 `GET /api/devices` 与 `PATCH /api/devices/<uid>`，没有新增路由；写入要求正整数 `revision`，省略 `layout` 时精确保留原配置。TV 的 `/api/state` 返回当前设备的 `display.layout`，显示配置与重绘状态版本来自同一读取快照。完整默认值、请求/响应、迁移和冲突规则见 [电视布局契约](TV-DISPLAY.md)。

1. 电视 `POST /api/pair/start {}` 获取 8 位 `code`、随机 `secret`、`expiresIn:600`。该 secret 只交给当前电视配对流程，不能打印进调试日志或转发给另一个用户。
2. 手机成员在 10 分钟内 `POST /api/pair/approve`，提供 code；代码忽略空格并转大写。
3. 电视用 `POST /api/pair/poll {"secret":"PAIRING_SECRET_PLACEHOLDER"}` 轮询。未批准为 `approved:false`；批准后为 true 且设置 `household_tv` Cookie。失效返回 `410`。
4. 此后电视通过设备 Cookie 读取 `/api/me`、`/api/state`、共享照片。无需保留明文 secret 用于日常 API 请求。

批准请求：

```json
{"code":"ABCD2345","name":"示例客厅电视","focus":"member1","calendarView":"week"}
```

`name` 默认“家庭电视”，1–30 字符；`focus` 默认当前成员，可为 `member1/member2/shared`；`calendarView` 默认 `today`，枚举 `today/week/around`。视图分别为今日、周一至周日、当天及前后各 3 天。批准失败使用 `400`，成功延长设备有效期至 90 天。

`GET /api/devices` 返回数组，每条包含 `id`、`name`、`focus`、`calendarView`、`revision`、`created_at`。注意此处创建时间保留 snake_case，接口尚未统一命名风格；不会返回配对 secret、摘要和 code。

`PATCH /api/devices/<uid>` 可局部更新上述三项显示参数，必须带当前 revision；不存在/过期为 `404`，版本冲突为 `409`：

```json
{"revision":1,"calendarView":"around","focus":"member2"}
```

每台设备独立保存，电视下一次读取共享状态应用设置。成员个人页面的视图存在浏览器本地，不会写此设备接口。`DELETE /api/devices/<uid> {}` 即时撤销设备；不要求 revision，目标不存在也返回 `200 {"ok":true}`。

## 8. ICS 文件导入（兼容入口）

`POST /api/calendar/import` 接收 `ics` 文本、可选 `owner`（默认当前成员）和 `source`（默认“文件导入”，仅允许 `Apple/Google/Outlook/文件导入`）。所有成员归属值也允许 `shared`。

```json
{"owner":"shared","source":"文件导入","ics":"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"}
```

ICS 字节上限 500,000，每次展开最多 500 条，全部日程最多 2,500 条。当前展开窗口从执行时刻前 30 天开始、总长 396 天；面向用户提示为“近 30 天至未来一年”。拒绝每秒、每分钟、每小时重复规则；取消项跳过，全天结束仍采用排他日期。

相同 `owner + UID + start` 合并并更新版本，不做整个来源的替换删除；没有 UID 则每次生成新 ID。`source` 不参与合并键。源端已删除事项不会由再次 ICS 导入自动删除，需要在看板手动处理。

成功 `{"imported":N,"note":"…"}` 统计本批准备导入记录，不是新增记录数；重复导入也可能递增版本。导入项 `imported:true`，但没有 `sync`，仍可本地编辑/删除。这个接口是文件快照兼容能力，当前主流程是下节云端自动同步。

## 9. Microsoft / Google 账户与自动同步

供应商枚举仅 `microsoft`、`google`。配置与注册步骤见 [账户接入与同步](ACCOUNT-SYNC.md)，内部适配边界见 [同步设计](SYNC-DESIGN.md)。以下不要求前端直接访问 Microsoft Graph 或 Google API，凭证交换和同步均由服务端执行。

### 9.1 平台状态与账户列表

`GET /api/auth/providers` 公开返回 `origin` 和 `providers`；每个平台有 `id`、`name`、`configured`、`loginUrl`、`callbackUrl`，不返回 client secret。`configured` 仅表示应用配置项齐全，**不等于实际授权或同步健康**。

`GET /api/accounts` 仅列当前成员自己的账户：

```json
{
  "accounts":[{
    "id":"local-account-id", "provider":"microsoft", "name":"示例云账户",
    "email":"example@example.test", "needsReauth":false,
    "capabilities":{"sync":true,"photos":false},
    "selectionVersion":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "sources":[{
      "id":"local-source-id", "remoteId":"remote-list-id", "kind":"tasks",
      "name":"示例共同清单", "owner":"shared", "primary":true,
      "lastSuccess":"2026-01-15T04:00:00+00:00", "error":""
    }]
  }],
  "providers":[{
    "id":"microsoft", "name":"Microsoft", "configured":true,
    "loginUrl":"/auth/microsoft/login", "callbackUrl":"https://home.example.test/auth/microsoft/callback"
  }]
}
```

实际 `providers` 同时包含两个平台。每成员最多绑定 4 个账户，按经过供应商身份端点验证的 `(provider, client_id, subject)` 唯一识别；邮箱仅用于显示，不用邮箱自动关联本地成员。

`selectionVersion` 是当前已保存来源配置的 SHA256 内容版本，不是同步成功时间；用于下面的可选并发核对。详细字段、身份边界和旧客户端行为见 [来源版本](ACCOUNT-SOURCE-VERSION.md)。

### 9.2 绑定、登录和回调

**先绑定，后第三方登录**：已有本地成员登录后，`POST /api/accounts/bind {"provider":"microsoft"}` 获取 `url`，浏览器跳转到该 URL 完成本人授权。请求必须来自配置的正式 `PUBLIC_ORIGIN`；从其他域名/IP 发起返回 `400` 并提示正式入口。不支持的平台 `404`，未配置平台 `503`。

未登录页面第三方登录用浏览器 GET `/auth/<provider>/login`，不是 fetch JSON 接口。它仅请求身份基础权限并登录已绑定的成员，**不会注册新家庭成员、不会按邮箱补绑或新建账户**。非正式 origin 会被重定向到正式入口。

GET `/auth/<provider>/callback` 接收供应商的 `state`、`code`，或 `error`。应用使用授权码流程、PKCE S256、浏览器会话绑定、10 分钟一次性 state。绑定回调还校验原成员和 `auth_version`，授权期间换账号/改密码需要重新开始。OAuth 成功均 `302` 跳回正式 origin：

- 绑定成功：`/?auth=connected`。
- 已绑定身份登录成功：`/?auth=signed-in`，创建新成员会话/CSRF。
- 失败：`/?auth=error&reason=<固定原因>`，前端映射为可操作提示。

当 Expo export 可用时，根入口将 `connected/error` 转入 `/app/connections`，只保留固定状态和白名单原因；页面消费后清除这些查询参数。`signed-in` 继续进入首页，Photos 专用返回继续进入相册。没有 Expo export 时保留经典页回退。

当前可能的原因：`invalid_state`、`provider_denied`、`bind_session_changed`、`provider_error`、`not_configured`、`identity_failed`、`unbound_account`、`already_bound`、`account_limit`、`missing_refresh_token`、`insufficient_permissions`、`invalid_client`、`invalid_grant`、`token_failed`。启动不支持/未配置的第三方登录也重定向为 `not_configured`。本地限流触发时该浏览器导航可能直接得到 JSON `429`。

绑定需要 refresh token；重新绑定相同已有账户时可保留其已有 refresh token。Microsoft 请求身份、`offline_access`、`User.Read`、`Calendars.Read`、可选 `Calendars.Read.Shared`、`Tasks.ReadWrite`；返回基础日历授权时不会仅因为缺少可选共享 scope 阻断绑定。Google 绑定请求身份、只读日历和 Tasks 权限，并启用离线访问。账号绑定成功后还需显式选择来源。

前端只消费固定 reason，不保存 OAuth code/state 到日志、遥测或截图。回调 URL 本身会暂时有供应商参数，因此 Nginx/Gunicorn 必须使用去 query 的日志格式；`/auth/` 响应为 `no-store`、`Referrer-Policy: no-referrer`。令牌只在服务器加密保存，不返回 `/api/accounts` 或 `/api/state`。

### 9.3 来源发现

`GET /api/accounts/<account_id>/sources` 实时向供应商读取可选日历/清单，返回：

```json
{
  "sources":[
    {"id":"remote-calendar-id","kind":"calendar","name":"示例日历","writable":false},
    {"id":"remote-list-id","kind":"tasks","name":"示例清单","writable":true}
  ],
  "selected":[{
    "id":"local-source-id","remoteId":"remote-list-id","kind":"tasks","name":"示例清单",
    "owner":"shared","primary":true,"lastSuccess":"","error":""
  }],
  "selectionVersion":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

发现列表的 `sources[].id` 是**远端 ID**；已选列表的 `selected[].id` 是**本地 ID**，其 `remoteId` 才是远端 ID。新建任务 `sourceId` 使用本地 ID；提交来源选择使用 `remoteId`。不要混用。

来源 GET 有网络副作用（可能刷新令牌）和失败机会，但不会自动选择全部来源；当前发现每类最多 500 个，没有客户端分页接口。账户不属于当前成员时 `404`，不会先读取其云端内容。

### 9.4 来源选择为完整替换

`POST /api/accounts/<account_id>/sources`：

```json
{
  "sources":[
    {"remoteId":"remote-calendar-id","kind":"calendar","owner":"member1","primary":false},
    {"remoteId":"remote-list-id","kind":"tasks","owner":"shared","primary":true}
  ],
  "selectionVersion":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

- **此数组代表该账户的全部最终选择，不是增量追加。** 省略以前选中的来源会删除它的本地镜像；传 `[]` 取消该账户全部同步，允许在授权已失效时清理旧镜像。
- 不删除或修改原云端数据；断开镜像不等于删除远端日历/清单。
- 每账户最多 12 个、全家庭最多 24 个来源；同账户 `(kind, remoteId)` 不可重复，来源必须重新发现且可用。
- `kind` 只允许发现出的 `calendar/tasks`。日历 `owner` 缺省为账户所属成员，可改为两个成员或 `shared`；任务缺省且必须为 `shared`。
- `primary` 缺省 false，必须为布尔值。**2026-09-15 01:10 发布版本**允许 Microsoft 或 Google 的 tasks 为 true。全家庭最多一个共同主清单。另一账户已有主清单时返回 `409`，由该账户拥有者先取消。设为主清单意味着明确允许另一位家庭成员将选中的本地待办连接至此授权账户清单，不代表 Google 原生共享能力。

本地待办连接的新 API 为 `/api/task-publish/state`、`/preview`、`/confirm` 及 `/publications/{id}/{pause|resume|retry|conflict-preview|conflict-confirm}`，完整请求/响应及错误边界见 [TASK-PUBLISH.md](TASK-PUBLISH.md)。这组接口已部署，保留原本地任务 ID、负责人和旅行关联，并要求独立预览确认；不改变已是云端镜像任务的原编辑限制。双平台模拟 HTTP 与临时浏览器通过，真实账户新增发布写入未验收。
- 任务来源必须可写；日历全部以只读方式集成。改变 owner 会立即更新已存在镜像标签，无需等待下一次远端读取。
- `selectionVersion` 可选；Expo 提交最后明确核对的版本。服务端在事务中、修改来源前比较，不符返回 `409` 和 `code: "selection_conflict"`。显式 null 或格式错误返回 `400`。省略时保持旧客户端的完整替换语义，因此经典页仍无版本冲突保护。账户级进程锁忙也会返回 `409`，不得把所有 `409` 当成版本冲突。
- 云端发现结束后重新验证原成员会话，防止请求等待期间换家庭、退出或撤销身份后继续保存。后台 worker 保持自身授权检查；不改变 schema。

成功返回 `{"ok":true,"queued":true,"selectionVersion":"<64位小写十六进制>"}`；空选择时 `queued:false`。`queued:true` 仅证明选择已保存并排入下一轮同步，**不证明第一轮内容已经拉取成功**。版本基于来源配置，恢复为完全相同的配置可能恢复相同版本；不是单调序号。

### 9.5 手动同步、解除绑定和实时性

`POST /api/accounts/<account_id>/sync {}` 将已选来源的下次尝试时间设为立即，有来源返回 `queued:true`，没有来源返回 `queued:false`；不等待同步完成，不返回新日程。应稍后读取状态和逐来源 `lastSuccess/error`。

`DELETE /api/accounts/<account_id> {}` 删除本人绑定、已选择来源及其镜像数据，保留远端原件；当前不调用供应商的全局撤销授权接口。API 不接受另一个成员的账号，即使其共同清单对家庭可见。

当前“自动同步”是后台轮询：任务目标 30 秒、日历目标 60 秒，worker 约每 3 秒检查到期来源，按到期时间轮转；实际延迟还受来源数量、网络、限流、账号锁和前端约 10 秒刷新影响，**没有秒级 SLA、webhook 或推送订阅**。

日历快照范围为当前前 30 天到未来 365 天，周期事件由供应商窗口接口展开；任务读取所选清单含完成记录。单来源最多 2,500 条，全家庭云端镜像最多 20,000 条，超限/分页异常不发布半份快照。每个来源成功后原子替换其镜像，供应商已删除项目才随完整快照移除；失败保留上次内容，按退避重试，最高约 15 分钟。需要重新授权时显示安全错误，由账号拥有者重新绑定。

## 10. 联合开发时必须保持的契约

- 先区分成员、电视、当前成员私有数据和家庭共享数据，新增字段不能因为“前端没显示”就从共享 API 泄露。
- 新增实体字段同步修改 validator、默认值兼容、表单、渲染和冲突测试；数据为 JSON 不意味着可以跳过迁移设计。
- 新增写接口明确 JSON、CSRF、Origin、revision 和云端副作用。不要绕过 `task_write` 直接修改镜像 JSON，也不要将“排队成功”显示为“同步成功”。
- 当前已提供独立家庭数据边界、个人账户与多家庭成员关系，以及成员数据副本 API；分别见 [个人账户](PERSONAL-ACCOUNTS.md)、[成员协作](EXPO-MEMBERSHIPS.md) 和 [个人导出](PORTABILITY.md)。本人账单与导入、媒体管理及同步状态各有独立模块合同，不以本页基础接口清单判断它们尚未实现；也不将这些受控接口视为通用第三方机器认证或不受限公共访问。
- 修改接口后同步更新本文、[数据模型](DATA-MODEL.md)、相关测试及 [验证记录](VALIDATION.md)。本文是人工维护的实现文档，不替代可执行的回归测试。
