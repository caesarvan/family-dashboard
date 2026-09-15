# 多国多城旅行细项：v2 契约与后端实现状态

**状态：旅行 v2 已于 2026-09-15 02:33:28（北京时间）随 143 文件版本部署；01:10 版本保留为历史发布记录。** [journey_time.py](../journey_time.py)、[journey_workflows.py](../journey_workflows.py) 已支持航班、住宿、活动、IANA/DST 验证、DATE/UTC ICS、三方日程比较和云时间语义复核标记。本模块验证仅使用合成行程及临时数据库，未访问真实云端账户、签证政策或预订平台。模拟集成与浏览器证据、后续公网读回以 [交接说明](HANDOFF.md) 为准；真实 Microsoft / Google 日历写入仍未验收。

日历发布表并发补列的事务保护已于 2026-09-15 03:11:08 随后发布；发布切换仍停止旧服务并串行初始化现有数据库，具体事务范围见 [数据模型初始化](DATA-MODEL.md#1-存储与初始化)。

正式能力字段为 `GET /api/journeys/templates` 的 `supportedSchemaVersions:[1,2]`，列表同时返回 `capabilities:{schemaVersions:[1,2]}`。v1 不自动升级；v2 拒绝降级，避免丢弃时区结构。以下第 1 节保留实现前差距作为审查依据，第 2～6 节以本次明确的实施契约为准；第 7 节列出模块与集成验收边界。

本次复用旅行预览、事务、稳定事项关联及云发布队列，新增时间语义和已有事件保护。

## 1. 实现前能力与差距（历史基线）

| 维度 | 当前可表达 | 当前限制 / 证据 |
| --- | --- | --- |
| 多国多城 | 最多 20 个目的地，国家/城市、抵达日、离开日及稳定 key | 没有城市时区、机场或国家代码关联；目的地日期分别落在旅行 start/end 内即可，不检查先后、衔接、重叠、空档。见 [normalize](../journey_workflows.py) 的 destinations 分支 |
| 城市分段 | 最多 100 段，key/title/start/end/location/note；默认按目的地生成停留段 | 只有 YYYY-MM-DD，end 包含当天；不是航班/酒店专用结构。传入未识别的航班、时区等字段会被当前白名单丢弃 |
| 航班 | 可以在标题/备注人工记下信息 | 没有起降两端机场、当地时间及各自时区，无法可靠验证飞行时长、当地日期倒退或转机衔接 |
| 住宿 | 可以作为一段「停留」 | 段结束日包含当天，不能直接解释为酒店退房日；没有入住/退房语义或晚数。中转日两城均出现可以表示接触两个城市，但不能据此推导住宿晚数 |
| 本地旅行日程 | 总行程和每段各创建一个事件 | [materialize](../journey_workflows.py) 将全部段固定为 `allDay:true`、`00:00:00+08:00`，排除结束日为段结束翌日。没有生成定时旅行事件的路径 |
| 一般日历 / 云端定时事件 | 现有事件能存带偏移时间，provider 能转换同一真实时刻 | [app.validate](../app.py) 和 [event_snapshot](../calendar_publish.py) 归一到 Asia/Shanghai；[provider._event](../cloud_providers.py) 不保留原 IANA 时区身份。定时事件的真实时刻可正确转换，但无法再恢复「原机场当地 09:00」这一完整语义 |
| 云端旅行发布 | 已有持久队列、稳定发布 ID、回读、条件更新及冲突暂停 | 旅行源数据目前全为全天。provider 的定时发布可以用 UTC 表达真实时刻，但全天日期仍按 Shanghai 转换；需保留日期语义，不能将酒店当地零点直接送入旧全天转换路径 |
| 日历展示 | 今日、本周、前后 3 天；定时跨日切分与重叠合并 | [calendar-ui.js](../static/calendar-ui.js) 使用固定 Asia/Shanghai 和 `+08:00` 日边界。适合作为家庭时区视图，不是目的地当地时区行程表；全天不计忙碌时长 |
| ICS | 日期级全天事件导出，稳定 UID、revision SEQUENCE、转义及 75 字节折行 | [journey_calendar_ics](../journey_workflows.py) 无条件输出 `DTSTART/DTEND;VALUE=DATE`，新增航班若沿用此出口会丢失时间 |
| 迁期 | 现有 UI 可整体顺延目的地、分段和准备截止日，保留任务/事件 ID | [journey-ui.js](../static/journey-ui.js) 将出发日期差用于全部日期，没有「已订 / 固定日期」区别；直接调用后端只更新提交的 plan，不自动推导所有相关迁期 |
| 已有记录保护 | apply 校验预览时的工作流及所有关联实体 revision；事务回滚；保留 done/actual/photoIds；移除采用解绑 | 对于**预览前已经修改的日程**，[editCurrent](../static/journey-ui.js) 只合并最新待办/采购，不合并 events；apply 会从 plan 重建事件字段。因此当前通用日程编辑后的标题/时间可能在后续旅行调整中被旧 plan 覆盖，revision 校验不能检测这类已发生的修改 |

现有日期级旅行正常使用不受本设计影响。新增航班或住宿前必须处理上表的时间与已有事件边界。

## 2. 最小结构扩展：schemaVersion 2

继续使用现有 `journey_workflows.plan`、`journey_links`、`entities`，不引入平行的第二套旅行主数据。现有 `/api/journeys/preview`、`/apply`、详情、日历发布及 ICS 路由继续使用。

### 顶层及目的地

- `schemaVersion:2`；未提供版本按 v1 处理，未知版本拒绝。
- `referenceTimezone`：IANA 时区，例如 `Asia/Shanghai`，用于旅行总日期范围核对及旅行详情的参考时间；目的地不能只按国家推断时区。它不改变全站日历时区，当前 calendar-ui.js 仍固定按 Asia/Shanghai 分天和计算工作量。
- 保留 `start/end` 为人工确认的旅行日期范围，end 仍包含当天。定时段按真实时刻转换到 referenceTimezone 后核对总范围；超范围在预览中提供覆盖起止日期和核对提醒，可以确认保留，不静默截断或自动扩展总日期。纯日期停留保持当地日历日期；跨时区造成的边界差异提示核对，不用字符串大小比较误判整个段不可行。
- `destinations[]` 在原 key/country/city/arrival/departure 上增加 `timeZone`；时区必须显式选择或确认。目的地顺序是行程意图，不充当时间排序依据。
- 原 `budget/saved/paid` 和采购统计保持原语义，本轮不增加自动汇率、预订支付或将住宿费用重复加进预算的逻辑。

### 通用分段

`segments[]` 保留稳定 key，增加 `kind:flight|stay|activity|legacy_day`、可选 `destinationKey`、`datePolicy:fixed|shift_with_trip`、人工标记的 `bookingState:idea|booked|cancelled`。`booked` 仅表示用户已确认，不表示系统核验了预订。

| kind | 最小必要字段 | 生成日程 |
| --- | --- | --- |
| flight | `departure:{airport,city,local,timeZone}` 与 `arrival:{airport,city,local,timeZone}`；可选 flightNumber | 一个真实起降区间的定时事件，`allDay:false`；各端机场和当地时间在详情独立显示。每个转机航段单独一个 key |
| stay | `propertyName,address,timeZone,checkInDate,checkOutDate`；可选已知 `checkInTime/checkOutTime` | 一个日期型住宿事件，覆盖入住日至退房前夜，DTEND 为退房日；晚数按日期差，不按秒数/86400。未知入住时间不伪造为零点或下午 3 点；详细时刻仅展示，不默认生成假时长日程 |
| activity | `start:{local,timeZone}`、`end:{local,timeZone}`，地点和说明 | 有明确起止时刻才生成定时事件；只知道日期时显式用 `dateRange:{startDate,endDateExclusive}` 生成日期事件。两种模式互斥 |
| legacy_day | 保留原 start/end（含结束日）及地点/说明 | 保留原全天日期与原事件 ID，避免把旧停留自动解读成酒店晚数 |

每个 `local` 是无偏移的当地日期时间，例如 `2026-10-03T00:30:00`，同时必须有 IANA timeZone。服务端在预览返回该端的 `offsetMinutes`、`instant`（UTC Z），当地时间规范为秒。客户端提交的 UTC 或 offset 与 IANA 解析不符时拒绝。编辑 local/timeZone 后应先清除旧 instant/offsetMinutes，再重预览；重复时间从错误响应 choices 中明确选择 offsetMinutes。

住宿字段位于 segment 顶层，入住/退房时间未知为 `""`；已知时可提供 `checkInOffsetMinutes/checkOutOffsetMinutes` 解决 DST 歧义，返回对应 `checkInInstant/checkOutInstant` 及 nights。全天 activity 必须提供 segment.timeZone。`bookingState=cancelled` 保留同一事件和关联，标题加 `[已取消]`、说明为人工标记，恢复状态也沿用原 ID；不会替用户取消预订或删除远端事件。真正从 segments 移除才进入原有解绑保留流程。

**示意请求片段，不代表真实航班班次：**

```json
{
  "schemaVersion": 2,
  "referenceTimezone": "Asia/Shanghai",
  "segments": [{
    "key": "flight-outbound-1",
    "kind": "flight",
    "title": "东京 → 檀香山",
    "datePolicy": "fixed",
    "bookingState": "idea",
    "departure": {
      "airport": "HND",
      "city": "东京",
      "local": "2026-10-03T00:30:00",
      "timeZone": "Asia/Tokyo"
    },
    "arrival": {
      "airport": "HNL",
      "city": "檀香山",
      "local": "2026-10-02T13:00:00",
      "timeZone": "Pacific/Honolulu"
    }
  }]
}
```

上述示意在本机 zoneinfo 下为正向 7.5 小时区间；当地抵达日期早于出发日期完全可能。应验证 `arrival.instant > departure.instant`，不能验证 `arrival.local > departure.local`。

## 3. 时间、日期和衔接规则

1. **区分日期与时刻。** 航班及定时活动保留 UTC instant + 每端 IANA zone + 当地墙上时间；酒店晚数、全天活动是日历日期，不将它们当作真实 UTC 零点时刻。
2. **夏令时不可猜测。** 用 zoneinfo 做往返校验，拒绝不存在的当地时间；同一个当地时间有两种合法 offset 时，要求用户选 `offsetMinutes` 后预览。不能默认取 Python fold=0。无效 IANA、缺时区、offset 不一致均拒绝。
3. **重算真实耗时。** 飞行、转机、跨日排序用 instant；酒店晚数用 checkOutDate−checkInDate。跨夏令时的当地一天可能不是 24 小时。
4. **转机提示与事实边界。** 可显示前段抵达至后段起飞的间隔、机场/城市是否变化、是否跨日及负间隔。正间隔不代表满足机场最短转机或入境要求；本轮不接此类政策规则。机场文本/代码仅是用户标注，不声称已核验航班或地点库。
5. **错误与提醒分开。** 负真实时长、无效时区、退房不晚于入住、重复 key 是阻止保存的错误；同日换城、目的地重叠、行程空档、短衔接和已订项目超出总范围是明确提醒。不可把所有城市覆盖区间强制变成不重叠序列。
6. **显示语义明确。** 全站日历固定 Asia/Shanghai；旅行详情显示每端当地时间和 IANA，并可附 plan.referenceTimezone 下的参考时间。修改该旅行字段不会调整全站今日/周视图的分天规则。酒店全天块不计作 48 小时忙碌；航班定时块按上海日界参与全站日历已有重叠合并。

本机只读计算还确认了两个可作为回归样例的边界：`Europe/Berlin 2026-03-29 02:30` 不存在；`2026-10-25 02:30` 有 +02:00 与 +01:00 两种合法映射。实现时把测试固定于明确的 IANA 时区规则，并记录/固定所用 tzdata 版本；升级时区库不能偷偷改变已确认事件的 UTC 基线。

## 4. 事件投影、ICS 与云端兼容

**保留 entities.events 的现有 start/end/allDay 兼容字段，增加受服务端保护的旅行时间元数据。** 例如 `travelTiming:{kind,segmentKey,startLocal,endLocal,startTimeZone,endTimeZone,startDate,endDateExclusive}`；元数据从已验证的 plan 投影生成，普通客户端不得自行伪造工作流关联。

- 定时事件的兼容 start/end 继续存可表示同一时刻的带偏移 ISO；旅行详情读 travelTiming 展示当地时间。现有家庭时区日历可以继续显示同一真实时刻。
- 日期事件增加明确 `startDate/endDateExclusive`。旧 start/end 可继续生成 Shanghai 的显示兼容值，但不得把该兼容值当成酒店真实入住/退房时刻。新事件投影、快照、ICS 和 provider 的全天路径使用日期字段。
- Google/MS 定时发布可继续使用现有 UTC 出站路径表达真实时刻，不必先为所有城市建立 Windows 时区映射。详情/云端说明可以同时写出双方当地时间和时区；不添加参与者或触发预订动作。
- 日期事件在两家 provider 写入/回读后必须保持原日期，包含开始、排除结束，不被 Shanghai↔目的地偏移推到前一天。不要把 stay 的退房日再加一天。
- ICS：全天使用 `VALUE=DATE`；定时使用 UTC `DTSTART/DTEND`（Z），并在经过转义的说明中保留当地时区文字。复用稳定 UID、revision SEQUENCE 和 75 字节折行。先用 UTC 方案可避免手工拼装不完整 VTIMEZONE。
- `event_snapshot` 与冲突比较需要纳入新的时间语义，区分「同一真实时刻仅改变展示区」和「保留当地时刻重新计算真实时刻」。后者是实质时间变更，不能按标题/UTC 偶然相同忽略。
- 新生成的航班、住宿事项不会因为旅行已有云发布记录而自动上传；新 entity ID 仍需要现有日历发布预览确认。旧全天事件改成定时航班或重解释日期/时区时，预览标明实质语义变化，并将其已有发布绑定置于需确认状态，防止后台队列在用户审阅前改写云端。
- 02:33 版本已将 v2 旅行事件的时间编辑引导回旅行详情；普通事件 API 保留受管时间元数据，拒绝直接改变这些时间字段，标题、地点和备注仍可独立编辑。早期普通表单按 +08:00 写入并丢弃未知字段的行为不能用于 v2 时间编辑。

这需要协调 `journey_workflows.py`、`app.validate`、`static/journey-ui.js`、`static/calendar-ui.js`、`calendar_publish.py`、`static/calendar-publish.js` 和 `cloud_providers.py`。不能仅升级 travel UI 而保留旧 ICS/普通编辑/云快照行为。

## 5. 迁期与已有事件保护

### 明确迁期计划

本轮沿用 `/api/journeys/preview`，UI 的明确迁期动作计算最终 plan。后端**不会**因为总 start 改变而隐式移动分段，避免前后端重复平移；不支持独立 reschedule/migrate 路由：

```json
{
  "journeyId": "当前工作流ID",
  "revision": 7,
  "plan": {"schemaVersion": 2, "referenceTimezone": "Asia/Shanghai", "start": "2026-10-10", "end": "2026-10-18", "...": "完整最终计划"}
}
```

服务端规范化完整最终计划，仍经现有 apply 签名及幂等事务保存。`summary.warnings` 包含逐项 `reschedule_moved/reschedule_preserved`、`outside_trip_dates`、目的地空档/重叠、`flight_connection`；每项有 code/itemKey/message，时段提醒附日期、衔接附 gapMinutes/airportChanged。超概览范围为可确认提醒，不截断机场当地日期。人工单独编辑已订或 fixed 项可以提交；datePolicy 限制的是自动迁期按钮，不把预订标记当作不可修改事实。

- **航班和已订住宿默认 fixed**，总旅行日期变更不表示航空公司或酒店已改期。没有明确勾选和确认时保持原日期；预览列出需要人工改订的项目。
- `shift_with_trip` 的计划事项按当地日历日期平移，保留当地钟点后重新按 IANA 解析。跨 DST 不用 UTC 秒数加 `N×86400`。不存在/重复时间要求重新选择，不能自动纠正。
- 准备事项继续使用已有明确 due/dueOffsetDays；本轮不增加 segment 锚点 dueRule。待办对外仍是日期，不伪装成带时区的精确到期时刻。
- HTTP 预览顶层为 plan/summary/canApply/previewToken/expiresIn；warnings 提供核对提醒及连程间隔，不提供通用逐项 before/after 或 UTC 耗时差。逐项迁期前后对照来自 UI 的内存草稿，航班耗时由规范化 instant 计算展示；entityId 只存在于特定冲突/保留/已解决/云复核项，不能假设每条 warning 都有。移除项默认保留记录并解绑。

### 三方比较保护独立编辑

实现使用已保存的旧 plan 重新 materialize 得到上次计划生成基线，无须新增副本表。规范 v2 plan 保存确认的 UTC instant，投影基线时直接使用它，不因 tzdata 更新偷偷改时刻；后续预览若旧 instant 与新规则不一致会要求重新确认。

预览比较 **上次生成基线 / 当前实体 / 本次计划投影**：

- 当前实体未变：可以应用新计划。
- 计划在某字段未变、实体独立修改过：保留实体值，在预览中反映，不从旧 plan 覆盖。
- 两边同时改同一字段：显示冲突，要求选择保留实体或使用计划；起止时刻、时区、日期类型作为一个整体时间组处理，不能拼成混合时间对。
- title/location/note/owner 以组做合并；timing 包含 start/end/allDay/travelTiming/startDate/endDateExclusive。计划 timing 变化时 note 也并入该组，防止保留旧时刻却配上新航班当地时间说明。v1 工作流可从旧 plan 建立基线；没有工作流的旧旅行仍走既有显式升级预览。
- `done/actual/photoIds`、负责人、旅行关联及已发布实体 ID 继续保留；预览后任何相关 revision 变化仍返回 409，用户重新预览。业务字段合并与事件/基线/关联更新在一个 SQLite 写事务中完成。

预览返回 `summary.conflicts/preserved/resolved`，每项包含 itemKey/entityId/fieldGroup/base/current/proposed。无解冲突时 `canApply:false,previewToken:null`，不允许 apply。客户端以 `conflictResolutions:{"segment:key":{"timing":"current","title":"plan"}}` 重预览；有效选择限定 current/plan，过时或未知组返回 409。最终 effectiveEvents 一并签名，apply 使用已确认合并结果。时间错误响应为 HTTP 400 `{error,code,field,choices}`；例如 field=`segments[0].departure`，ambiguous_local_time 的 choices 含两个 offsetMinutes/instant。

### 稳定身份与云端保护

- 使用稳定 segment key 建立 `segment:<key>` → 原 entity ID；改日期、机场、酒店名、顺序不更换 key。新增才生成新 key，不能用数组下标或日期重新计算身份。
- v1 升级为 v2 时保留 `event:overview`、原 `segment:<key>`、journey ID、trip ID、task ID；不凭城市名称猜测匹配。把旧全天段升级为定时事件需明确选中原段并查看 diff。
- apply 继续复用 actor/household/version 签名、operationId、idempotencyKey 收据及 BEGIN IMMEDIATE；重复提交或丢响应重试不能再生成一组本地事件。
- 已有 calendar/task publication 的远端 ID、待恢复写快照和版本不得被迁期事务清空。尚未核实的旧写入先按原快照恢复，再处理最新已确认本地版本；不能为追求最新日期丢弃不确定写入证据而另建远端事项。
- 远端人工修改继续由 publisher 以 ETag 对比暂停；旅行 apply 不得将 conflict/paused/remote_deleted 重新置为自动可写。纯本地新日期确认不等于确认覆盖已变化的云端。
- apply 在 BEGIN IMMEDIATE 之前按账户 ID 排序取得所有关联日历账户锁，事务内重查集合。类型/时区/取消语义变化给现有发布标记 `status=needs_review,review_required=1`，保留 pending_data/hash/revision、remote_id/etag/last_hash；同事务更新本地事件。暂停、恢复或普通重试不能绕过复核，解除由 calendar publisher 独立的签名 review-preview/review-confirm 执行。
- 删除一段默认本地解绑，云端原项保留并暂停该关联的继续更新；删除整趟旅行不自动删除云日历或云任务。任何未来远端删除功能应另作明确预览确认，本轮不实现。

## 6. 版本兼容与交付顺序

1. 02:33 版本已在模板响应中提供 `supportedSchemaVersions:[1,2]`，列表提供 `capabilities:{schemaVersions:[1,2]}`。旧响应没有能力字段时 UI 禁止提交 v2，不能降级丢弃时区；完整 v2 不得发送给 01:10 等未声明该能力的旧运行时。
2. v1 原样读取和展示，现有日期/预算/预览 token 语义保持。升级必须通过显式预览；旧城市段默认 `legacy_day`，不自动推断为航班或酒店。
3. 先实现纯函数时间解析/规范化与基线比较，再接 v2 preview/apply。使用现有 JSON 存储与有界输入，最多 20 目的地、100 分段；预览 token 大小须单独验证，不因新增字段无限膨胀。
4. 一并接旅行编辑 UI、普通日程编辑保护、双类型 ICS、云快照/出站/冲突显示和新事件确认边界。全部模拟/本地浏览器通过后，才向真实用户开放能力标志。
5. 02:33 版本的 [requirements.txt](../requirements.txt) 已固定 `tzdata==2026.4`；[Dockerfile](../Dockerfile) 设置 `PYTHONTZPATH=""`，使 zoneinfo 使用安装包内的 IANA 数据而非镜像系统规则。Windows 原生开发也应核对实际 TZPATH 和版本，不仅看依赖已安装。升级 tzdata 或调整来源必须回归 DST/日期线及双平台投影；已确认 UTC 基线保留，新预览如与新规则矛盾应要求核对，不能随依赖升级偷偷漂移。

## 7. 可复用的测试与必须新增的边界

**本模块已执行：** `.venv\Scripts\python.exe -m pytest tests/test_journey_workflows.py tests/test_journey_details.py -q`，结果 **56 passed（25.94 秒）**：原 v1 30 项及 v2 26 项。新增验证包含 Tokyo→Honolulu 日期倒退但 UTC 正向、Berlin/New York 春秋 DST、半小时/45 分钟偏移、DATE/UTC 混合 ICS、住宿跨 DST 晚数、取消恢复/重排/重试稳定 ID、预览前编辑三方保护、时间与说明整体保留、预览后 revision 冲突、needs_review 保留远端/pending 字段以及在数据库写事务前获取账户锁。此结果不等同于真实账户授权、真实云日历写入或生产浏览器验收；这些证据由相应独立测试记录提供。

**直接复用/扩展：**

- [test_journey_workflows.py](../tests/test_journey_workflows.py)：预览零写、apply 关联、同 token/幂等键去重、成员/电视/跨户签名、预览后实体变更 409、迁期 ID 稳定及实付保留、移出事项解绑、升级旧旅行、事务回滚、ICS 折行和注入转义。
- [test_cloud_providers.py](../tests/test_cloud_providers.py)：Google 定时偏移归一及全天排除结束日；Microsoft UTC 读取保留原全天日期；分页完整性、版本条件写、外站续页拒绝。
- [test_calendar_publish.py](../tests/test_calendar_publish.py)：重复确认、丢创建/更新响应恢复、实时本地版本、缺 scope、ACL、过期预览、远端编辑冲突、If-Match 竞态、暂停/删除保留、轮询不生成镜像、禁止参与者邀请。
- [test_task_publish.py](../tests/test_task_publish.py)：迁期准备任务仍保留原 ID、完成回流并发保护、双边日期/标题冲突、重连保留 attempted、跨户/成员边界。重排或迁期不能悄悄把已连接待办重新上传。
- [test_calendar_views.js](../tests/test_calendar_views.js)：上海参考时区跨日切分、午夜结束排除次日、全天排除结束日且不计忙碌时长、重叠合并、电视分页。
- [browser_journeys_check.py](../tests/browser_journeys_check.py)、[browser_calendar_publish_check.py](../tests/browser_calendar_publish_check.py)、[browser_task_publish_check.py](../tests/browser_task_publish_check.py)：临时真实 Flask + Edge + 假 provider transport，复用手机与电视布局/零外站写保护。

**新增后必须真正断言的情况：**

| 领域 | 必须验证 |
| --- | --- |
| 时区解析 | 无效 IANA、naive 输入无 zone、offset 与 zone 不一致；Berlin 不存在/重复当地时间；Asia/Kolkata +05:30、Asia/Kathmandu +05:45，不只测整小时偏移 |
| 国际日期线与跨日 | 上述 Tokyo→Honolulu 7.5 小时示意、本地到达日更早、返程跨两天；UTC 正向但当地字符串倒序须接受；真正 arrival UTC≤departure UTC 须拒绝 |
| 住宿 | 同日入住退房拒绝；两晚跨 DST 仍为两晚；退房日不多显示一晚；未知时刻不得生成虚假定时安排；v1 包含结束日的段升级不擅自减晚数 |
| 多城市衔接 | 合理同日换城、不同机场转机、重叠与空档提示；不把任意正间隔认定为「可转机」；目的地重新排序不改实体 ID |
| 迁期 | fixed 航班/已订住宿不随总日期改变；选中计划项按当地日期平移；DST 后当地钟点保留而 UTC 变化；未选项、手工截止日及已有完成/照片/实付保留 |
| 独立编辑 | 在预览前改过日程标题/时间，然后只改旅行预算，原日程必须保留；双边同时间组变更要求确认；预览后并发修改返回 409；失败时实体、plan、基线、任务及事件一起回滚 |
| 事件及云同步 | 新事件需新确认；原全天转定时需语义变更确认；原事件/发布/远端 ID 不变；迁期碰到 pending、uncertain、conflict、paused 不清空恢复证据或复活写入；新旧两平台回读的真实时刻及日期一致 |
| ICS 与 UI | 一个文件同时包含 DATE 和 UTC Z 事件，导入读取后精确还原；转义/folding/UID/SEQUENCE 不回退；出发/到达当地时区标签可见、390px 不溢出；全站周视图固定按 Asia/Shanghai 分天，旅行详情才使用 plan.referenceTimezone 的参考展示；TV 只读不触发写入 |
| 兼容 | v1 样本原样读取/重新保存；没有能力标志的旧服务不提交 v2；未知 schemaVersion 拒绝；显式升级保留 key/实体 ID/云绑定；不同家庭同 key 不互通 |

验收不能以「可在备注里输入航班」或「云端 API 调用返回成功」替代。完成标准是：用户能输入两端当地时间和酒店日期，看懂归一后的时区及跨日结果；改期前可核对哪些项保持固定、哪些待确认；确认后本地、ICS 和两家模拟云日历表示相同的时间语义，且不产生副本或覆盖未经确认的已有变更。
