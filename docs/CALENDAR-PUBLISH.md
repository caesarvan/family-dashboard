# 旅行日程发布到 Microsoft / Google

本模块将旅行工作流中的本地日程发布到成员自己绑定的云日历。实现包含真实 HTTP 适配器、持久队列、授权升级、发布读回校验、后续本地修改同步和云端冲突处理。

**版本范围：旅行 v2 时间模型、`review_required`、时间复核接口及加强后的重连/锁保护已于 2026-09-15 02:33:28（北京时间）随 143 文件版本部署。01:10 版本保留为历史发布记录。** 该批历史镜像为 `sha256:07666ba7e4473c5feb967cf0bcf2616244d0e510b18191c35cdf724ae1cbb139`；03:11:08 历史版本又增加了发布表并发初始化保护。当前交付、运行镜像和部署证据以 [HANDOFF](HANDOFF.md) 为准。旅行输入、DST 错误、三方冲突与能力探测见 [旅行 v2 契约](TRAVEL-DETAILS-PLAN.md) 和 [平台 API](PLATFORM-API.md#1-旅行工作流)。

数据库并发初始化修复已于 2026-09-15 03:11:08 发布：`BEGIN IMMEDIATE` 包住列检查、条件补列和发布命名空间写入，失败则回滚。实际多进程测试验证竞争初始化、既有 review 标志/待写数据保留与失败后重试。此保护仅覆盖日历发布表初始化；部署仍按停止写入、备份、串行预热和分步启动执行。

**验证边界：自动化测试仅使用临时 SQLite 数据库和模拟的云端 HTTP 响应；尚未用真实 Microsoft / Google 账户验收新增的日历写入权限与发布。** 原有日历读取和清单同步维持原授权范围。不能把已有绑定成功视为新增写入功能已完成真实账号验收。

## 入口与代码

- 前端入口：`window.CalendarPublish.open(journeyId)`，旅行详情的「同步到云日历」按钮调用。
- 前端文件：[calendar-publish.js](../static/calendar-publish.js)，复用 [finance-hub.css](../static/finance-hub.css) 的工作区组件样式。
- 后端：[calendar_publish.py](../calendar_publish.py)。调用 `register_calendar_publish(app, db, Problem, body, require_member, audit)`，须在 `register_accounts` 和 `register_journeys` 之后。
- 旅行投影：[journey_time.py](../journey_time.py) 将已验证的当地时间/IANA 投影为 UTC 定时或明确的全天日期；[journey_workflows.py](../journey_workflows.py) 维护稳定事件关联和三方编辑保护。
- 云端请求：[cloud_providers.py](../cloud_providers.py)。新增日历 ACL 查询、创建、查找、读取与条件更新方法。
- OAuth 与去重：[cloud_accounts.py](../cloud_accounts.py)。新增按需写权限升级；已发布的远端事件回流时保留本地旅行实体，避免双份显示。
- 工作进程：[sync_worker.py](../sync_worker.py) 调用 `app.extensions['calendar_publish'].tick()`；每次最多处理 2 条到期记录。
- 测试：[test_calendar_publish.py](../tests/test_calendar_publish.py)。覆盖两个提供商、真实本地身份与 CSRF、模拟远端持久状态和失败恢复。

日历发布沿用已配置的 Microsoft / Google OAuth 应用与 `SECRET_KEY`，不增加专用环境变量或 API key。旅行 v2 使用标准库 zoneinfo 及项目固定的 tzdata 依赖。初始化创建发布表；02:33 版本额外检查并补充 `review_required INTEGER NOT NULL DEFAULT 0`，不重置现有队列或令牌。部署前仍应备份数据目录；补列的事务范围与发布预热步骤见页首。

## 权限升级

默认绑定请求保持原有 scope。只有成员点击「开启日历写入」，后端才为该成员的已绑定账号生成新的授权请求。

| 平台 | 新增请求的权限 | 接受的等效授予 |
| --- | --- | --- |
| Microsoft | `Calendars.ReadWrite` | `Calendars.ReadWrite` 或 `Calendars.ReadWrite.Shared` |
| Google | `https://www.googleapis.com/auth/calendar.events` | 此 scope 或完整的 `https://www.googleapis.com/auth/calendar` |

升级同时保留原请求的基本身份、日历读取和任务权限。Microsoft 写权限被视为满足原有 `Calendars.Read` 校验；Google 完整 Calendar scope 被视为满足 `calendar.readonly`。

内部方法为 `CloudAccounts.authorize(provider, 'bind', user, calendar_write=True, account_id=...)`。一次性的 OAuth state 使用 `bind_write:<account_id>` 模式，仍有浏览器绑定、PKCE、有效期和成员 `auth_version` 校验。升级回调必须返回同一个已绑定账号的真实 provider subject；选择了不同账号、未授予写权限或缺少原必要权限时，升级失败并保留原账号记录。每名成员同时最多 20 个未过期升级请求。

应用管理员需让 OAuth 应用允许请求这些权限；企业租户的管理员批准策略、Google 应用的测试用户/发布及敏感 scope 审核条件仍由各平台决定。成员必须亲自在提供商页面完成授权。代码不会推断未返回的写入 scope，也不通过修改本地标记伪造授权。

写入时另外读取所选日历的真实 ACL：Microsoft `canEdit`，Google `accessRole` 为 `owner` 或 `writer`。OAuth 已有写权限不代表每本日历都可编辑。没有编辑权限时暂停并显示原因。

Microsoft 创建用户日历事项所需权限及 `transactionId` 见 [Microsoft Graph 创建事件](https://learn.microsoft.com/en-us/graph/api/calendar-post-events?view=graph-rest-1.0)。Google 插入事件的 scope、调用方指定 ID 及 `sendUpdates` 见 [Google Calendar events.insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert)。

## HTTP 接口

所有接口要求已登录的家庭成员；电视无权访问。写接口还要求 JSON、同源请求和 `X-CSRF-Token`，与主应用一致。账号、日历和发布记录均按当前成员限制；旅行内容本身仍按现有家庭共享规则显示。返回中不包含 access token、refresh token 或客户端密钥。

### 1. GET `/api/calendar-publish/journeys/<journey_id>`

读取该旅行的日程、当前成员已选择的日历来源，以及该成员的发布进度。

```json
{
  "journeyId": "journey-example",
  "events": [{"id":"event-example","revision":1,"title":"旅行示例","start":"2026-10-01T00:00:00+08:00","end":"2026-10-04T00:00:00+08:00","allDay":true,"location":"示例城市","note":""}],
  "sources": [{"id":"source-example","name":"我的日历","accountId":"account-example","provider":"google","accountName":"示例成员","writeAuthorized":false}],
  "publications": [],
  "mode": "durable_queue",
  "note": "确认后持续发布本地日程修改。云端修改冲突会暂停；删除本地计划不会自动删除云端事项。"
}
```

`events[].end` 使用排他结束时间；以上全天事项覆盖 10 月 1～3 日。来源仅包含成员在账户设置中已经选中的日历，不自动添加其他日历。

`publications[]` 字段：`id`、`entityId`、`sourceId`、`provider`、`status`、`error`、`reviewRequired`（整数 0/1）、`localRevision`、`updatedAt`。这里的 `localRevision` 是已成功发布并读回确认的本地版本；不把正在排队的新版本标成成功。每趟旅行最多发布 101 项日程，包含概览与最多 100 个分段。

`events` 只暴露标题、起止、全天、地点、备注这六个受管字段及本地 id/revision，不把完整 `travelTiming` 发给 provider。全天快照优先使用实体 `startDate/endDateExclusive`，转换成兼容的 `+08:00` 日期边界；住宿退房日不再加一天。定时快照可用 `+08:00` 表示同一真实时刻，provider 出站仍转 UTC；两端当地时间和 IANA 说明写入 note，参与既有摘要比较。

### 2. POST `/api/calendar-publish/authorize`

```json
{"accountId":"account-example"}
```

返回 `{"url":"https://..."}`。前端检查 HTTPS 与 Microsoft/Google 授权主机后跳转。只能为本人已绑定的账号升级，且须通过配置的 `PUBLIC_ORIGIN` 访问。

### 3. POST `/api/calendar-publish/preview`

```json
{"journeyId":"journey-example","sourceId":"source-example"}
```

返回 `events`、`source`、`previewToken`、`expiresInSeconds: 900` 和说明 `note`。签名绑定当前成员、当前家庭命名空间、旅行、来源、provider/client/subject/远端日历目标摘要，以及全部事件 ID/版本/受管理字段摘要。内部 targetDigest 不供客户端自行构造；即使来源编号相同，目标身份变化也必须重新预览。

预览不建立发布队列，不访问云端，也不创建云事件。它展示已记录的授予范围；真正日历 ACL 会在 worker 执行时检查。

### 4. POST `/api/calendar-publish/confirm`

```json
{"journeyId":"journey-example","sourceId":"source-example","previewToken":"由预览接口返回"}
```

返回 `queued: true`、`publicationIds`、`needsAuthorization`。确认先按顺序取得当前目标和既有发布的旧账号锁，再在 `BEGIN IMMEDIATE` 内重新检查本地版本、来源、拥有者和目标身份，变化则返回 409。

缺少写权限时新记录可保存为 `needs_authorization`，**不会写云端**；授权后由 worker 检查并继续。重复确认同目标的同实体使用同一发布标识。取消选择或完全解绑后，同 provider/client/subject/日历重选会产生新的本地来源/账号 ID；明确预览确认可迁移引用，同时保留原状态、review flag、pending、attempts、remote_id、etag 和 last_hash。已冲突、已暂停、待复核或本地已删除的记录不会被恢复为自动可写；重选期间已产生的云镜像会去除，原旅行实体保留。

不同身份或日历的明确首次发布可以创建新的目标绑定，但不能挪用原发布记录。即使云身份相同，改由另一家庭成员绑定也不能接管原成员的发布。签名预览或冲突/复核 token 在来源迁移后失效，需重新预览。

### 5. POST `/api/calendar-publish/publications/<id>/retry`

请求体 `{}`。将可重试的记录重新加入队列，返回 `{"queued":true}`。`conflict`、`local_deleted`、`paused`、`needs_review` 或 `reviewRequired=1` 均不能通过该入口绕过核对。

### 6. POST `/api/calendar-publish/publications/<id>/pause`

请求体 `{}`。返回 `paused: true` 与说明。停止后续发布，保留云端已有事项。该操作与 worker 使用同一账号锁，不在远端请求中途改变状态。

### 7. POST `/api/calendar-publish/publications/<id>/resume`

请求体 `{}`。仅允许 `paused` 且 `reviewRequired=0` 时恢复，返回 `queued: true`。保留原远端 ID 和 ETag；云端已改动则再次进入冲突。`needs_review → pause → resume` 无法绕过时间复核，最后一步返回 409。

### 8. POST `/api/calendar-publish/publications/<id>/conflict-preview`

请求体 `{}`。仅用于当前成员的 `conflict` 记录，在账号锁内真实读取远端并展示两边受管理字段。

返回 `local`、`remote`、`previewToken`、`note`。两边字段均为 `title/start/end/allDay/location/note`。签名绑定成员、发布记录、队列绑定/状态快照、本地版本/摘要、远端 ID/ETag/摘要，有效期 15 分钟。`reviewRequired=1` 时应使用时间复核接口，不能使用本接口。

远端已取消、包含参与者、找不到原发布标记或已删除时，不提供可覆盖的预览，应到原日历核对并停止自动发布。

### 9. POST `/api/calendar-publish/publications/<id>/conflict-confirm`

```json
{"previewToken":"由冲突预览接口返回"}
```

这是用户明确选择「以本地内容更新云端」的提交。后端再次检查成员、冲突状态及本地版本，保存预览时的远端 ETag 并排队。worker 仍重新 GET 并使用 `If-Match`；预览之后的任何远端版本变化都会再次暂停。返回 `{"queued":true}`，不代表云端已经更新。

### 10. POST `/api/calendar-publish/publications/<id>/review-preview`（02:33 版本）

请求体 `{}`。要求 `reviewRequired=1` 且本地工作流关联仍存在。账号锁内只 GET/查找原远端事件，不写云、不清空旧 pending；返回旧待处理快照、当前本地和实际远端供比较：

```json
{
  "local": {"title":"示意航班","location":"示意机场","note":"当地时间与 IANA 说明","start":"2026-10-01T09:00:00+08:00","end":"2026-10-01T12:00:00+08:00","allDay":false},
  "previous": {"title":"示意航班","location":"示意机场","note":"原全天计划","start":"2026-10-01T00:00:00+08:00","end":"2026-10-02T00:00:00+08:00","allDay":true},
  "remote": {"title":"示意航班","location":"示意机场","note":"原全天计划","start":"2026-10-01T00:00:00+08:00","end":"2026-10-02T00:00:00+08:00","allDay":true},
  "previewToken":"由服务端返回的临时凭证",
  "expiresInSeconds":900,
  "note":"旅行时间或类型已变化。确认后才恢复发布；云端若再次变化会暂停。未找到云端事项时，将用原发布标识核对后创建。"
}
```

`previous` 在没有旧 pending 时为 null；尚无已知 remote_id 且按稳定标记未找到时 remote 可为 null。**已经保存 remote_id 的事件读取返回 404，不把它降级为新建场景。** 找到的事件标记不符、带参与者或已取消均拒绝。签名绑定 queueBinding、本地 revision/digest、远端 ID/ETag/digest 和当前成员，15 分钟有效。

### 11. POST `/api/calendar-publish/publications/<id>/review-confirm`（02:33 版本）

```json
{"previewToken":"由 review-preview 返回"}
```

成功返回 `{"queued":true}`。账号锁和写事务内重查来源、拥有者、队列快照、review flag、本地关联和版本；任一变化返回 409，旧队列保留。确认后才设置新 pending、预览核实的 remote_id/etag，清零 `review_required` 并设为 pending；worker 后续核对原标识和 ETag 再执行。旧创建响应丢失时，预览可先找到旧事件并沿用其 ID，之后更新到新时间；不会因为修改行程再分配发布 ID。

以上两个接口返回 401/403/404 的身份、来源和提供商权限错误沿用全局规则；没有复核条件、预览过期/被其他操作改变或远端身份不能确认时要求重新核对。重复发送已消费的复核 token 返回 409，实际是否发布以状态接口为准。

## 数据模型

表名 `calendar_publications`，每个家庭使用自己的 SQLite 数据库。

| 字段 | 类型 / 含义 |
| --- | --- |
| `id` | TEXT PK；64 位十六进制稳定发布键 |
| `owner` | TEXT，关联 `users(id)`；拥有目标云账号的成员 |
| `journey_id` / `entity_id` | 本地旅行与事件标识 |
| `source_id` / `account_id` | 当前来源与账号；重新绑定后可由再次确认更新来源映射 |
| `provider` / `calendar_id` | 提供商与远端日历标识 |
| `remote_id` / `etag` | 已读回确认的远端事件 ID 和版本 |
| `last_hash` / `local_revision` | 上次成功发布的字段摘要与本地版本 |
| `pending_data` | 固定的待发布字段 JSON；没有待处理版本时为 NULL |
| `pending_hash` / `pending_revision` | 待处理快照摘要与版本 |
| `status` / `error` | 状态及经过限制的本地错误说明 |
| `review_required` | INTEGER NOT NULL DEFAULT 0；时间语义复核门槛，不能仅用 status 推断 |
| `attempts` / `next_attempt` | 重试计数及下次尝试 Unix 时间 |
| `created_at` / `updated_at` | UTC ISO 时间 |

索引：`(status,next_attempt)`、`(owner,journey_id)`、`(source_id,remote_id)`。

`settings.calendar_publication_namespace` 保存每户随机命名空间。稳定键由命名空间、provider、OAuth client ID、provider subject、远端日历 ID 和本地实体 ID 共同派生。不同家庭不会复用同一个签名预览或发布标识。

旅行、实体、来源和账号字段有意不使用级联删除：删除本地计划或解除绑定不能被误报为远端已删除。发布记录留在数据库供后续核对；只有 `owner` 有用户外键。

## 队列与失败处理

| 状态 | 含义与动作 |
| --- | --- |
| `pending` | 已获用户确认，等待执行 |
| `publishing` | 正在调用远端；进程退出后到期仍可恢复 |
| `published` | 云端写入并读回一致；继续跟踪本地修改与远端版本 |
| `retry` | 暂时网络错误或服务错误；指数退避重试 |
| `needs_authorization` | 缺少已授予的日历写权限或授权需要处理 |
| `permission_denied` | 所选日历不可编辑；核对 ACL 或更换日历后重试 |
| `conflict` | 远端版本、内容或身份发生变化；需要比较并明确处理 |
| `error` | 连续 12 次可重试失败后暂停；可由成员重试 |
| `paused` | 成员主动停止，允许明确恢复 |
| `needs_review` | 旅行时间类型、时区或取消语义变化，须明确复核；旧 pending 和远端恢复信息保留 |
| `local_deleted` | 本地关联事件移除；云端原事项保留 |

worker 每次最多处理 2 条。没有本地修改时，也会在到期检查时读取远端并核对存在、ETag、标记和字段，随后将下次检查时间设为 60 秒后。实际延迟受队列长度、远端限流和网络影响；这不是推送订阅或确定的实时 SLA。

`review_required=1` 独立于 status，worker、普通 confirm、retry、resume 和迟到的错误处理均不能清除它。旅行 apply 与 publisher 使用同一组账号锁；后台取到旧 account_id 后会在锁内重读，若已重绑则直接停止。用户动作按绑定快照重查并在写事务中执行，旧连接的请求不能改变新绑定；网络错误在原账号锁释放前记录，避免覆盖随后确认的状态。

Microsoft 创建使用稳定 `transactionId`，并写一个 `singleValueExtendedProperties` 字符串属性，内容为发布键和字段摘要。结果不明时按扩展属性寻找原事件再读回，不依赖每次 POST 都成功返回。扩展属性查询方式参见 [Microsoft 单值扩展属性读取](https://learn.microsoft.com/en-us/graph/api/singlevaluelegacyextendedproperty-get?view=graph-rest-1.0)。

Google 创建使用 `h` 加 64 位十六进制发布键作为确定性 event ID，符合其 base32hex 字符规则；同时写入 `extendedProperties.private` 的发布键与摘要。

发送之前先将待发布快照持久化。若创建或更新已经发生但响应丢失，下一次通过远端标识/摘要/实际字段读回一致来恢复成功状态，避免重复创建或盲目覆盖。已知远端 ID 返回 404 时进入冲突，不自动重建被删除的事项。

后续更新先比较已记录 ETag，再带 `If-Match` PATCH。Google 使用 `sendUpdates=none`；任何事项一旦含有参与者，代码会停止更新。Google 版本条件机制见 [资源版本控制说明](https://developers.google.com/workspace/calendar/api/guides/version-resources)。

只写受管理字段：标题、起止时间、全天标志、地点、纯文本备注，以及内部发布标记。创建不设置参与者并禁用默认提醒；不生成邀请、会议参与人、支付或远端删除请求。

## 验证与后续验收

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_calendar_publish.py tests/test_cloud_accounts.py tests/test_microsoft_binding.py tests/test_oauth_diagnostics.py tests/test_cloud_providers.py
node --check static/calendar-publish.js
```

新增模拟测试覆盖：预览零写入、重复确认、缺 scope、日历 ACL、错误账号升级、失败升级保留旧绑定、CSRF、成员隔离、电视拒绝、创建/更新响应丢失恢复、ETag 并发冲突、远端参与者限制、暂停恢复、本地删除、远端删除、去除重复镜像以及明确冲突预览确认。

本次发布前专项：`tests/test_calendar_publish.py`、[test_journey_publication_review.py](../tests/test_journey_publication_review.py)、[test_calendar_publication_rebind.py](../tests/test_calendar_publication_rebind.py) 合跑 **113 passed，72.46 秒**；其中重连专项由另一 agent 独立复跑 **62 passed，39.35 秒**。测试全部使用临时 SQLite 与双 provider 假 HTTP，包含复核不能经暂停恢复绕过、未知旧创建恢复、目标与成员变化、旧账号锁、已删除远端不复活和重新选择后的镜像清理。旅行解析和三方比较证据见 [旅行 v2 验证](TRAVEL-DETAILS-PLAN.md#7-可复用的测试与必须新增的边界)。

02:33 发布对应的全量验证为 Windows **547 passed，230.14 秒**；Linux **546 passed、1 项平台 CLI 跳过，415.25 秒**。发布时现有 1 户数据库完成串行初始化，共 29 张业务表，队列为空，受保护数据与环境配置保留，app 健康、sync/web 运行。上段为 02:33 历史证据；03:11:08 后续发布已包含并发补列修复，Windows 551 passed、Linux 550 passed / 1 skipped。真实云写与公网浏览器仍按交接记录保留未验收项。

上线后仍需由账号本人分别在 Microsoft 和 Google 完成额外授权，使用专门的测试日历发布一份示例旅行，核对全天结束日期、时区、标题和地点，再验证修改、冲突及恢复。只有这些真实验收完成，才能将对应平台标为真实账号已验证。自动测试不会进行任何生产日历写入。


## 旅行执行页的本地变更状态

本版在现有 GET 状态返回的 publications 中新增 `localChangesPending: boolean | null`。true 表示当前本地受同步管理的字段不同于上次确认基线；false 表示相同；null 表示没有确认基线、实体已缺失或无法比较。不改变原 status，不返回内部基线，不调用服务商或修改队列。仅负责人、旅行关联等非云管理字段变化不会误标为待同步。status=published 是上次处理结果，不能独立证明本地最新修改已到云端。日历仍只返回本人成员的发布项，待办保留原 canManage 和可见性。完整使用与异步守卫见 [旅行执行](JOURNEY-EXECUTION.md)。
