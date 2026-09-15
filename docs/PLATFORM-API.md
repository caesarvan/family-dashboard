# 平台扩展接口：旅行、助理、家庭空间与偏好

**当前版本：2026-09-15 20:23:00（北京时间），镜像 `sha256:651ecfd6bdb65cf04bb8778c8657a8ec0f27a123940683a44a8b9931a5f22352`。** 旅行资料、完整细项展示与分段定位已发布，保留此前全部模块；106 个方法／路径模板、43 张户内表（41 业务 + 2 认证）及 2 张平台表。源码与文档数量见 [README](../README.md) 及交接清单；测试、迁移和实际接入边界见 [VALIDATION](VALIDATION.md)。

当前源码与文档数量以 [README](../README.md) 及逐文件交接清单为准；接口和存储结构见 [当前索引](PLATFORM-ROUTES.md)，运行版本与验收证据见 [VALIDATION](VALIDATION.md)。

新增例行管理接口见本页第 4 节和 [ROUTINES](ROUTINES.md)；下方 06:50、02:33 等均为历史批次说明。

按 2026-09-15 当前源码核对。基础身份、CSRF、通用实体、图片、资金与账户接口见 [基础 API](API.md)；所有路由见 [完整索引](PLATFORM-ROUTES.md)。财务账本见 [财务 API](FINANCE-API.md)，云日历队列见 [发布 API](CALENDAR-PUBLISH.md)。

**历史组合已于 2026-09-15 06:50:21 发布：** [助理旅行简报](ASSISTANT-JOURNEY-BRIEF.md)新增 POST 路由，全站 87→88；[工作表发现](FINANCE-API.md#xlsx-工作表名称发现)复用原导入路由。户内 29 表与平台 2 表不变；完整验收见 [VALIDATION](VALIDATION.md)。

首页布局契约见 [工作台界面](WORKSPACE-UI.md)，待办队列见 [待办发布](TASK-PUBLISH.md)，ZIP 下载见 [个人数据导出](PORTABILITY.md)。这些增量已于 2026-09-15 01:10 发布，真实接入与本次公网浏览器的未完成项见 [交接说明](HANDOFF.md)。

**版本分界：本页的旅行 v2、DST/三方冲突、云日历时间复核及 [财务来源桥接](FINANCE-SOURCE-BRIDGE.md) 已于 2026-09-15 02:33:28（北京时间）随 143 文件版本部署；01:10 保留为历史发布记录。** 当前部署和后续运行读回见 [交接说明](HANDOFF.md)。真实 Microsoft / Google 日历写入仍未验收；数据库并发补列修复与助理原事项入口已随后于 2026-09-15 03:11:08 发布，不增加 HTTP 路由或业务表；详见 [日历发布版本范围](CALENDAR-PUBLISH.md)。

示例使用虚构内容。标记为成员的接口要求已登录成员；电视会话不能代替成员授权。除邀请码兑换外，写接口均要求同源 JSON、成员会话和 `X-CSRF-Token`。通用错误为 `{"error":"说明"}`；401 未登录，403 权限/CSRF，400 输入无效，409 版本/状态冲突，429 频率或数量限制。

## 1. 旅行工作流

实现：[journey_workflows.py](../journey_workflows.py)，旅行 v2 的时间规范化/投影由 [journey_time.py](../journey_time.py) 提供。完整时间和兼容契约见 [旅行 v2](TRAVEL-DETAILS-PLAN.md)。旅行工作流 id 与 `entities` 中 tripId 是两个标识，不可互换用于后端路由。

| 方法与路径 | 身份 | 返回或作用 |
|---|---|---|
| GET `/api/journeys` | 成员或已配对电视 | `{"journeys":[详情],"capabilities":{"schemaVersions":[1,2]}}`，按更新时间倒序；capabilities 为 02:33 版本新增 |
| GET `/api/journeys/<id>` | 成员或已配对电视 | 单个详情；不存在返回 404 |
| GET `/api/journeys/templates` | 成员 | `version`、`policyNotice`、`templates`；02:33 版本增加 `supportedSchemaVersions:[1,2]`，模板 id 为 domestic/international |
| POST `/api/journeys/preview` | 成员 | 规范化计划、变更摘要、签名预览 |
| POST `/api/journeys/apply` | 成员 | 原子应用已确认预览，幂等回执 |
| GET `/api/journeys/<id>/calendar` | 成员 | 本地日历实体与 ICS 入口 |
| GET `/api/journeys/<id>/calendar.ics` | 成员 | `text/calendar` 下载；本地生成，不是订阅服务 |

### v1 新建、迁期与升级的预览

未提供 schemaVersion 按 v1 处理；下面例子保留原日期级语义。客户端不能把 v2 字段发送给未声明 v2 能力的旧服务器。

```json
{
  "plan": {
    "title": "秋日双城旅行",
    "start": "2026-10-01",
    "end": "2026-10-04",
    "international": true,
    "memberIds": ["member1", "member2"],
    "budget": 2000000,
    "saved": 1000000,
    "paid": 300000,
    "note": "虚构的接口示例",
    "destinations": [
      {"key":"tokyo","country":"日本","city":"东京","arrival":"2026-10-01","departure":"2026-10-02"},
      {"key":"kyoto","country":"日本","city":"京都","arrival":"2026-10-03","departure":"2026-10-04"}
    ],
    "checklist": [{"key":"booking","title":"核对住宿预订","owner":"member1","dueOffsetDays":-14,"note":"核对改退条款"}],
    "shopping": [{"key":"adapter","title":"转换插头","quantity":"1 个","owner":"member2","budget":8000,"note":"先核对现有物品"}]
  }
}
```

- 所有金额为非负整数分，最大 100,000,000,000；`budget/saved/paid` 省略为 0，采购预算允许 `null` 表示未知。旅行预算当前为人民币口径。
- `title` 必填，最多 100 字；`note` 最多 2,000 字；`start/end` 为 2000～2100 年的有效 `YYYY-MM-DD`，end 包含返程当日，单次最多 367 天。
- `memberIds` 默认本家庭全部成员，必须非空且不重复。负责人 `owner` 为本家庭成员或 `shared`，不要求该负责人也在出行成员中。
- `destinations` 必须有 1～20 项：city 必填最多 80 字，country 可空最多 60 字；arrival/departure 默认旅行起止，必须落在旅行日期内。
- `checklist` 最多 100 项；**省略**则使用国内 5 项/境外 7 项准备模板，传空数组则不生成准备任务。条目包含 key、title、owner、dueOffsetDays、可选 due、note、category。due 优先于 offset；offset 默认 -7，范围 -730～366；截止不能晚于返程。note 最多 500 字，category 默认 preparation、最多 40 字。
- `shopping` 最多 100 项，默认空；quantity 默认“1 件”、最多 30 字；note 最多 500 字。
- 可选 `segments` 最多 100 项。省略时按城市停留自动生成；空数组则只生成整个旅行的总览日程。条目为 key、title、start、end、location、note；end 默认 start，日期必须在旅行内，location 最多 200 字，note 最多 500 字。
- 每组条目中的 key 必须稳定且不重复，只接受 1～64 位字母/数字/下划线/短横线。省略会按下标生成，后续重排时应沿用服务端返回的 key，以保留原实体关联。
- 更新已有工作流：同一请求额外提交 `journeyId` 和最新整数 `revision`。升级旧式旅行：额外提交 `tripId` 和最新 `tripRevision`，不要同时指定另一工作流。
- 升级旧本地准备任务时，可用 `key: "existing-<任务 id>"` 认领原旅行下的任务；不得把云主清单事项直接改成本地任务。

预览返回 `plan`、`summary`、`previewToken`、`expiresIn:1800`；02:33 版本另返回 `canApply`，并可能因未解决冲突令 token 为 null。summary 包含按实体类型统计的 create/update、detach 数量、移除规则和政策说明。预览不写业务实体；签名绑定成员、家庭、计划、原版本和所有受影响实体的 revision。

### v2 时区、航班、住宿与活动（02:33 版本）

顶层显式 `schemaVersion:2`，必填 `referenceTimezone`（IANA），每个目的地增加 `timeZone`。start/end 仍是包含返程日的总日期范围。更新 v1 工作流为 v2 继续提交原 journeyId/revision，沿用原 key；无独立 migrate/reschedule 路由，服务端不会因 start 变化而隐式迁期。迁期按钮提交完整最终 plan，固定/已订项目默认保留，人工单项改期仍可明确提交。未知版本拒绝，已保存 v2 的工作流拒绝降级。

referenceTimezone 用于旅行范围核对和详情参考展示；全站日历仍按固定 Asia/Shanghai 分天、合并时段和统计工作量，不随单趟旅行改变。

| segments.kind | 字段及结果 |
| --- | --- |
| `flight` | `departure/arrival` 各为 `{airport,city,local,timeZone,offsetMinutes?}`，可选 flightNumber；按两端 UTC 时刻验证正时长，允许跨日期线导致当地抵达日期较早 |
| `stay` | 顶层 `propertyName,address,timeZone,checkInDate,checkOutDate`；checkout 排他，返回 nights；可选 `checkInTime/checkOutTime` 为 HH:mm，未知留空；重复时间可指定顶层 checkInOffsetMinutes/checkOutOffsetMinutes |
| `activity` | `start/end` 两个时间点，或 `dateRange:{startDate,endDateExclusive}` 加顶层 timeZone；明确时段和全天日期模式互斥 |
| `legacy_day` | 保留 v1 的 start/end 日期，end 仍包含当天，不把城市停留推断为酒店夜数 |

通用段字段为 key/title/location/note、可选 destinationKey、`bookingState:idea|booked|cancelled`、`datePolicy:fixed|shift_with_trip`。默认航班/已订段 fixed，其余可随旅行迁期。title 最多 100 字，location 200、note 500；机场 80、航班号 40、住宿名称 150、地址 300。取消是人工标记，保留同一实体/关联并在标题注明已取消，不向航司/酒店执行取消。

时间点 local 为 `YYYY-MM-DDTHH:mm[:ss]` 且不带偏移；服务端返回秒级 local、原 IANA、offsetMinutes、UTC Z instant。客户端修改当地时间或时区时须清除旧派生 instant/offset 再预览；已有 instant 或 offset 与 IANA 规则矛盾时拒绝。夏令时不存在时间报 400；重复时刻要求从 choices 选偏移：

```json
{
  "error":"这个当地时间出现两次，请明确选择 UTC 偏移",
  "code":"ambiguous_local_time",
  "field":"segments[0].departure",
  "choices":[
    {"offsetMinutes":120,"instant":"2026-10-25T00:30:00Z"},
    {"offsetMinutes":60,"instant":"2026-10-25T01:30:00Z"}
  ]
}
```

以上是 Berlin 02:30 的合成示例。其他 code 包括 nonexistent_local_time、invalid_timezone、offset_mismatch、instant_mismatch、nonpositive_duration；住宿重复时刻 field 为 `segments[0].checkInTime` 等，偏移写回顶层 checkInOffsetMinutes。具体错误文案不作为稳定程序分支。

### 三方比较和冲突选择（02:33 版本，v1 也受保护）

服务器比较“旧 plan 的生成基线／当前实体／新计划投影”。单独在日历里改过且计划对应字段未变的内容自动保留；双边不同修改进入冲突。预览新增：

```json
{
  "canApply":false,
  "previewToken":null,
  "summary":{
    "conflicts":[{"itemKey":"segment:outbound","entityId":"event-example","fieldGroup":"title","base":{"title":"原名称"},"current":{"title":"日历里修改"},"proposed":{"title":"旅行里修改"},"choices":["current","plan"]}],
    "preserved":[],
    "resolved":[],
    "warnings":[],
    "cloudReviews":[]
  }
}
```

响应还包含完整 plan、expiresIn、summary 原有统计。客户端以同一 plan/版本追加 `conflictResolutions:{"segment:outbound":{"title":"current"}}` 重预览；group 可为 title/location/note/owner/timing，选项仅 current/plan。timing 把 start/end/allDay/travelTiming/startDate/endDateExclusive 当作整体；计划时间变化时 note 也并入该组，避免旧时刻配新机场说明。已失效或未知选择返回 409。有效的最终事件合并结果一并签入 token，apply 不会重新用旧 plan 覆盖保留值。

`summary.warnings[]` 含 code/itemKey/message，以及按类型提供的日期、gapMinutes/airportChanged、迁期规则等；超总日期、目的地空档/重叠和衔接提醒可确认，不截断真实当地日期，也不证明机场最短转机要求。`cloudReviews[]` 标识时间语义变化对既有绑定的复核要求。

### 确认、重试与详情

```json
{"previewToken":"由上一步返回","idempotencyKey":"journey-demo-20261001"}
```

幂等键为 8～80 位字母/数字/下划线/短横线。新建返回 201，更新或同一操作重试返回 200：

```json
{
  "id": "workflow-example",
  "tripId": "trip-example",
  "revision": 1,
  "calendar": {"local":"created","cloud":"not_requested","icsUrl":"/api/journeys/workflow-example/calendar.ics"},
  "replayed": false
}
```

同一预览换幂等键重试也只应用一次；同一个键用于不同预览返回 409。预览过期或关联实体已被其他操作改动时返回 409，需要重新读取并预览。写入使用 SQLite 单事务，不能部分创建旅行/采购/任务。

详情返回 `id/revision/tripId/plan/trip/tasks/shopping/events/progress/budget/calendar/policyNotice/updatedAt`。实体附 id、revision、workflowKey；progress 含 done/total/purchased/purchaseCount；budget 含 total/paid/reserved/purchaseBudget/purchaseActual 及未知预算/实付项数。采购预算属于旅行规划内部组成，不自动与已付款相加或记成财务支出。

迁期保留实体 id、完成状态、采购实付和图片；从计划移除的旧条目保留为独立记录。删除旅行仍走通用 `DELETE /api/items/trips/<tripId>`，并按基础 API 携带 revision；关联事项只解除关系，不能推断远端事项已删除。

v1 仍生成北京时间全天事项，end 为最后一天的翌日零点；上例覆盖 10 月 1～4 日，实体 end 为 10 月 5 日。v2 定时段生成 UTC start/end；全天段另有 startDate/endDateExclusive，住宿 end 正好是退房日。事件带受管 `travelTiming.schemaVersion=2` 和原当地时间/IANA 元数据；普通日程编辑可改标题/地点/备注，但不能改受管时间和关联，需回到旅行计划。详情若选择保留当前事件时间，应读取实际 events，而非假定 plan 的新日期已覆盖它。

`/calendar` 返回 journeyId、revision、events、localStatus、cloudStatus、writeRequirement、icsUrl。其中 cloudStatus 与详情 calendar.cloud 的 `not_requested` 是本地生成流程的静态说明，**真实发布状态必须读取 `/api/calendar-publish/journeys/<id>`**，不能用此字段覆盖发布队列状态。ICS 使用稳定 UID、revision SEQUENCE 和 UTF-8 行折叠；v2 同文件可包含 VALUE=DATE 和 UTC Z，导入外部日历不会建立自动同步。

已有日历绑定若时间类型、时区或取消语义变化，旅行 apply 在相同账号锁/写事务内设置 `review_required=1` 和 needs_review，保留 pending 与远端恢复证据。使用 [review-preview / review-confirm](CALENDAR-PUBLISH.md) 查看旧 pending、新 local、当前 remote，再明确恢复；普通 confirm/retry/resume 不能绕过。已知远端事件删除返回 404 时不自动重建。同稳定云身份/日历重选来源可明确迁移本地引用，但保留暂停/冲突/复核状态。

## 2. 家庭助理

实现：[home_assistant.py](../home_assistant.py)。当前源码四个接口仅限成员，数据范围为当前家庭；新增 journey-brief 已于 2026-09-15 06:50:21 发布，原有三个接口继续保留。

GET `/api/assistant/brief` 返回 today、through、tasks（最多 20 条未完成且截止不晚于 through）、events（最多 30 条覆盖区间的记录）、conflicts（最多 12 组）、shoppingCount、trips（最多 5 趟未结束旅行）、mode、modelConfigured、coverage。到期待办包括逾期事项；时间重叠按同一负责人或共同事项计算。它基于现有数据的截断摘要，不能用于证明日历或财务来源覆盖完整。

例行计划额外返回 `routines={items,dueCount,issueCount,limit:8}`。items 每项为 id/title/kind/owner/scheduledOn/status，只来自当前家庭共享计划；异常优先，其余包含未来七天内及逾期的待处理项。暂停／归档不计入，汇总计数不受八条上限截断。读取不推进计划、不改实体、审计或财务；详细筛选与三个管理接口见 [ROUTINES](ROUTINES.md)。

POST `/api/assistant/plan`：

```json
{"prompt":"待办：明天预约保洁；确认酒店","useModel":false,"includeHouseholdContext":false}
```

prompt 为 1～2,000 字，每 IP 每小时最多 30 次。useModel/includeHouseholdContext 仅在值为 true 时启用。本地支持明确待办/任务/采购/购物前缀、分号分项、今天/明天/后天或显式日期，以及“搜索：关键词”。模型模式要求同时配置 OPENAI_API_KEY/OPENAI_MODEL；未配置返回 503，模型请求/输出失败返回 502，不创建事项。

```json
{
  "id":"plan-example",
  "summary":"已整理为清单草案。",
  "actions":[{"kind":"tasks","data":{"title":"预约保洁","owner":"member1","done":false,"due":"2026-09-16"}}],
  "mode":"local",
  "matches":[]
}
```

actions 的 data 是通用实体校验后的对象，还可能包含基础 API 定义的默认字段；kind 只允许 tasks/shopping。matches 最多 30 条，仅含 id/kind/title/start/due/owner。草案绑定创建成员，每个成员最多保留 200 条，超过 7 天的历史在创建下一草案时清理。

POST `/api/assistant/plans/<id>/apply`：

```json
{"selected":[0]}
```

selected 是非空、无重复的 0 起始动作下标数组，最多 12 项。首次执行须在生成后 24 小时内。成功返回 `{"ok":true,"created":[{"id":"item-example","kind":"tasks","title":"预约保洁"}],"destination":"household"}`。重复提交返回首次执行回执，不创建此前没选的动作；需要新增动作时应生成新草案。其他成员不可执行此草案。

确认后只创建本地清单，不自动推送到第三方主清单。模型不能执行任意 API、转账、下单或发送邀请。仅在成员明确选择时，模型上下文才包括近期日程/任务的白名单字段；个人财务、账户和令牌不会自动发送。

<a id="post-apiassistantjourney-brief本地已合入待发布"></a>

### POST `/api/assistant/journey-brief`

已于 2026-09-15 06:50:21 发布；上方显式锚点保留旧版链接。

把本次旅行文字整理为待核对简报，供用户完成三步表单后进入可编辑旅行向导。它不通过通用助理 apply 创建旅行，也不写业务实体或发布队列。完整类型、模型边界与 JavaScript 接缝见 [助理旅行简报](ASSISTANT-JOURNEY-BRIEF.md)。

```json
{"prompt":"今年想去日本和法国，两万左右，具体日期还没确定","useModel":false}
```

`prompt` 为 0～2000 字字符串，空文字供手工填写入口使用；`useModel` 为严格布尔值，默认 false。与原 `/assistant/plan` 共享每 IP 每小时 30 次请求限额；仍要求当前家庭成员、同源 JSON 和 `X-CSRF-Token`，TV 不可用。

返回 `mode`、`brief`、`missingFields`、`notice`。brief 只含 `title/start/end/budgetCents/international/destinations/note`；目的地只含 `country/city/arrival/departure`，最多 20 站。预算为人民币整数分或 null，未明确的日期、目的地和总预算需本人补齐；约数、人均或明确外币金额不会换算为人民币总预算。`missingFields` 是待补路径，不是旅行预览的 `canApply`。

模型仅在已配置且本次请求明确 `useModel:true` 时调用，只发送本次文字，不发送共享记录、个人财务、账户或历史对话；原接口的 `includeHouseholdContext` 不适用于旅行简报。模型字段经服务端白名单及来源检查，不能注入成员、实体编号、预览令牌或发布动作。模型建议仍需本人核对，不代表真实预订或价格。

响应没有 `previewToken` 或创建授权。用户在三步表单核对后，`JourneyUI.openDraft` 调用既有 `/api/journeys/preview` 获取规范化草稿并打开向导，丢弃桥接预览的令牌；再次预览并明确确认 `/api/journeys/apply` 后才保存。错误 400 表示输入无效，502 表示模型请求或白名单输出无效，503 表示模型未配置；失败不自动重试模型或保存旅行。身份、输入及迟到响应保护详见专文。

## 3. 家庭空间和成员偏好

实现：[household_spaces.py](../household_spaces.py)。默认家庭 slug 为 home；额外家庭的路由、数据库与派生会话密钥隔离。

GET `/api/spaces/current` 可匿名读取当前入口，返回 id/name/slug/entry/canInvite。它不枚举全平台家庭。GET `/space/<slug>` 为 WSGI 跳转，设置已签名的家庭选择 Cookie、清除成员与电视 Cookie，然后跳到登录页；未知 slug 为 404。选择家庭本身不会授予身份。

POST `/api/spaces/invitations` 仅默认家庭 member1 可用，无业务输入字段，发送 `{}` 即可。每 IP 每小时最多 10 次；201 返回 `{"invitation":"一次性随机值","expiresIn":604800}`。服务端仅保存哈希，不负责邮件或消息发送。

POST `/api/spaces/redeem` 无需原成员会话或 CSRF，但要求 JSON、同源检查、有效邀请，且每 IP 每小时最多 10 次：

```json
{
  "invitation":"邀请者提供的一次性值",
  "name":"示例之家",
  "slug":"example-home",
  "MEMBER1_PASSWORD":"替换为第一位成员的独立长密码",
  "MEMBER2_PASSWORD":"替换为第二位成员的独立长密码"
}
```

name 为 1～40 字；slug 为 3～32 位小写字母、数字或连字符，必须以字母开头且不能为 home；每个密码 12～128 字。201 返回 ok/name/entry，成员仍需登录。无效/过期/已用邀请返回 403，重复地址或达到默认 30 户容量返回 409。示例密码仅说明字段，不可用于真实部署。

成员自己的 GET/PUT `/api/preferences` 使用同一对象：

```json
{"theme":"forest","density":"comfortable","homeView":"today"}
```

PUT 必须且只能提交完整三个字段：theme 为 forest/light/ocean，density 为 comfortable/compact，homeView 为 today/week/around。成功返回保存的对象。此接口没有 revision 参数，多个设备并发保存采用最后成功写入；UI 定期刷新偏好时须保留尚未保存的表单草稿。

损坏家庭路由 Cookie 的 API 响应为 400 JSON，已注册家庭数据库不可用为 503；响应含 error 和固定的 recoveryUrl `/space/home`。前端只允许这个已知恢复入口，不能跟随任意服务端字符串跳转。存储缺失时不会使用默认家庭密码偷偷重建成员。

## 4. 家庭例行计划

| 方法与路径 | 请求与结果 |
|---|---|
| GET `/api/routines/context` | 可选 planId、page、includeArchived；返回 version/today/timeZone/limit/plans/pageInfo；每页 40，聚焦计划可额外保留，最近十期和下一期日期只读 |
| POST `/api/routines/preview` | operation 为 create/update/pause/resume/skip/archive；创建传 kind/template/schedule，其余传 planId/revision，update 另带完整 template/schedule；返回 before/after/nextDates/willGenerate/warnings/previewToken/expiresInSeconds |
| POST `/api/routines/confirm` | 仅 previewToken；返回 operation/plan/generated/replayed。十分钟签名，事务中重验会话、规则、当前实体、日期和容量；重复成功 token 读历史结果，不再生成 |

计划全家共享，两位成员都能管理；签名确认只限原发起成员／家庭／会话。匿名 401、TV 403；写接口沿用 JSON／同源／CSRF，坏输入或过期 400、对象缺失 404、依赖变动 409。规则和字段的精确上限、nextDates 在预览与确认后不同含义、月末 clamp、跳过保留原项、缺失不复活及各操作可用状态，以 [ROUTINES](ROUTINES.md) 为完整合同，不能根据此索引扩宽输入。

每期只生成本地实体；既有 `TaskPublish.open({entityIds:[...]})` 是另外的用户确认流程，不把一期授权或默认主清单配置当作未来每期发布授权。GET、助理 brief 和共享导出均不调用 tick。
