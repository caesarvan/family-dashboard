# 个人站内待办提醒

本批是独立 API／worker 候选，基线 `8b0d46183a663b8e0e5622a48d0b9e14a92a8806`；不表示已经上线。前端、导出适配和 69→71／平台 9 表的发布迁移由后续独立任务处理。本模块只记录本人已读或暂缓，不发送手机推送、不完成任务、不调用 Microsoft／Google。

## 何时出现，谁能看到

未完成待办有合法截止日期（2000–2100 年），到该日 **Asia/Shanghai 09:00** 起出现一条提醒；逾期多日仍是一条。没有截止日期的事项不出现。分配给某成员的任务仅提醒该 active 成员，`shared` 任务给每个 active 成员独立的已读／暂缓状态。这是提醒接收规则，任务本身仍沿用原来的家庭共享权限。

云镜像只接受已选中的 shared 清单，必须具有匹配的 `cloud_items → cloud_sources → cloud_accounts` 记录、有效的来源账号成员，以及一致的 provider／sourceId／remoteId。仅有 JSON `sync` 标记不能产生许可。账号暂时需要重连不抹掉已有共享缓存，但断开来源、停止来源账号成员或取消共享后立即隐藏对应提醒；云端后续变化仍依赖原同步周期。

完成、删除、改负责人和改截止日在下一次 GET 即按 live 任务过滤，不等待 worker。任务标题与依赖修改不会生成新提醒。`occurrence` 由任务原 ID 和截止日生成，客户端视为不透明值。同一截止日重新打开、重新分配回来时保留已读／暂缓历史；改成其他截止日使用新 occurrence，再改回原日期仍恢复原历史。

每次列表 GET 从数据库实时投影标题、原 ID、任务版本和依赖；提醒表没有标题或其他内容快照。暂缓到期后状态立即为 `unread`，不需要 worker tick。

## HTTP 合同

所有接口要求当前家庭的有效成员会话；电视、匿名和其他家庭不能读取本人的提醒或操作记录。写入同时沿用 Origin、CSRF 与身份校验。不接受客户端指定 `owner`。

### 列表

`GET /api/task-reminders?filter=unread&page=0`

`filter` 只允许 `unread`（默认）和 `all`；`page` 是从 0 开始的整数，固定每页 40 条，按截止日、任务 ID 排序。拒绝重复参数、未知参数、负数及前导零。`total` 是当前筛选结果数量，`unreadCount` 是本人所有当前可提醒事项中的未读数。

```json
{
  "items": [{
    "task": {
      "id": "原任务编号", "title": "订酒店", "owner": "member1",
      "due": "2026-10-10", "revision": 3,
      "dependsOn": [], "blockedBy": [], "dependencyStatus": "ready"
    },
    "occurrence": "64位小写十六进制不透明值",
    "revision": 0, "eligibleAt": "2026-10-10T01:00:00.000000+00:00",
    "status": "unread", "readAt": null, "snoozedUntil": null
  }],
  "unreadCount": 1, "total": 1, "page": 0, "pageSize": 40, "hasMore": false,
  "serverNow": "2026-10-10T01:00:00.000000+00:00", "timeZone": "Asia/Shanghai",
  "worker": {"lastCheckedAt": null, "stale": true, "capacityBlocked": false}
}
```

`task.revision` 用于原任务编辑；外层 `revision` 仅用于提醒操作。云镜像额外带最小 `task.sync`（provider、sourceId、remoteId，可有 version、readOnly）。这不是完整编辑 DTO，打开事项时仍须通过原任务入口重新读取。原依赖投影见 [TASK-DEPENDENCIES](TASK-DEPENDENCIES.md)。

`status` 为 `unread|read|snoozed`。`readAt`、`snoozedUntil` 和 `worker.lastCheckedAt` 没有值时为 `null`。已过期的 `snoozedUntil` 保留原时间，状态按服务端当前时钟显示 `unread`，不能仅按该字段是否为空判断状态。

### 已读与暂缓

`POST /api/task-reminders/<原任务ID>/actions`，带当前会话 CSRF：

```json
{
  "requestId": "0123456789abcdef0123456789abcdef",
  "occurrence": "GET取得的64位值",
  "revision": 0,
  "action": "snooze",
  "snoozedUntil": "2026-10-10T02:00:00+00:00"
}
```

`requestId` 是本人成员范围的 32 位小写十六进制随机标识；发生未知结果时必须保留原请求。`revision` 为非负安全整数。`read` 操作不接受 `snoozedUntil`；`snooze` 必须提供带时区的绝对时间，严格晚于服务端当前时间且不超过 30 天。服务端统一转为 UTC。前端“1 小时后／明天上海 09:00”须使用 `serverNow` 计算并由本人明确提交。

成功返回 200：

```json
{
  "operation": {
    "requestId": "0123456789abcdef0123456789abcdef",
    "action": "snooze", "taskId": "原任务编号", "occurrence": "原64位值",
    "revision": 1, "readAt": null,
    "snoozedUntil": "2026-10-10T02:00:00.000000+00:00",
    "committedAt": "2026-10-10T01:00:00.000000+00:00"
  }
}
```

已读会清空暂缓时间，暂缓会清空已读时间。操作回执的版本是提交后的提醒版本；只改变本人提醒状态，不修改原任务、依赖、任务 revision、共享业务审计或云端内容。

### 未知结果与错误

`GET /api/task-reminders/operations/<requestId>` 返回同一 `{operation}` 或 404。回执只含本人操作 ID、原任务 ID、不透明 occurrence、动作、版本及时间，没有任务标题或内容。之后任务完成、删除、改负责人、改截止日、暂缓到期，仍可核对自己已经提交的历史操作；成员撤权立即拒绝。

POST 在检查新写入条件之前，先查本人的原回执。同一 requestId 加同一标准化 intent 重放原结果，不延长暂缓、不重复写入；相同 ID 换动作、版本、目标或时间返回冲突。回执 404 后只能由用户明确重试原请求，不能自动换 ID。已确认回执后列表读取失败，只重试读取。

| 场景 | HTTP / code |
| --- | --- |
| 字段、筛选、编号、版本或暂缓时间不合法 | 400 / `invalid_reminder_request` |
| 新操作对应任务不再适用或本人不是接收者 | 409 / `reminder_unavailable` |
| 截止日 occurrence 或提醒 revision 已变化 | 409 / `reminder_stale` |
| 同 requestId 已保存另一 intent | 409 / `reminder_request_conflict` |
| 历史容量达到上限 | 409 / `reminder_capacity` |
| 本人原请求没有回执 | 404 / `reminder_operation_not_found` |

这些错误返回 `{error,code}`；原身份与 CSRF 错误保持既有 401／403 合同。新操作收到明确 409 后刷新列表；未知传输结果先核对原请求。没有可用身份时清除前端私人状态并重新登录。

## 数据、事务和保留策略

新增家庭库两表：`task_reminders` 以 `(owner,task_id,due)` 为主键，保存读／暂缓、revision、active 和时间；`task_reminder_operations` 以 `(owner,request_id)` 为主键，保存 intent 摘要与最小回执。用户引用保留外键，但不对任务设级联删除，才能在任务删除或改期后核对原操作。平台库无变化。

列表 GET 不生成记录、不改变 heartbeat。尚未物化的提醒投影版本为 0，worker 首次插入也为 0，避免“刚看到提醒，后台初始化后就冲突”。POST 使用同一 `BEGIN IMMEDIATE`，先后核对当前会话，再检查 live 接收资格、截止日、当前提醒版本和时钟，原子保存状态与回执。竞争的不同请求不能覆盖同一版本；相同请求得到同一回执。读取使用同一家庭快照，返回前再次核对会话身份。

每家庭最多 20,000 条提醒状态和 40,000 条操作回执。达到容量时保留旧状态和所有回执，明确拒绝新的相应记录；已有回执的重放与读取继续可用。worker 只物化剩余容量，返回 `capacityBlocked`。没有按年龄自动删除回执，也不按任务已完成／改期删除历史，避免破坏同日期重开与未知结果核对。后续若需要归档，须另行设计明确的安全流程，当前没有自动释放容量接口。

成员停止／移除时，`household_memberships._stop` 在原同一事务中删除该成员的两表记录并撤销会话；失败回滚也恢复提醒记录。worker 可清理遗留非 active 成员记录。普通退出登录不清理。成员重新加入后获得新的本人提醒历史，其他成员状态不受影响。

## worker 与运行边界

`sync_worker.sync_household` 先运行本地 `task_reminders`，再运行原 task publish、calendar publish、cloud accounts、routines。单阶段失败仍按原机制隔离，不输出任务、令牌或异常正文；一户一个 tick 的既有调度保持。

每次成功 tick 单独记录 `lastCheckedAt` 和容量状态。距此时间超过 60 秒或时钟倒退时 `stale=true`。这是提醒阶段的实际检查时间，不是云端同步完成时间或准实时承诺。慢云请求仍会延后下一轮调度；GET 的即时资格与暂缓到期判断不依赖该 heartbeat。

注册顺序在 cloud accounts／任务依赖基础之后；Docker COPY 包含新模块。当前开发应用会创建两张空表，但尚未提供生产迁移、导出或固定发布白名单适配；不能直接把此分支用于既有 69 表发布计划。

## 本批验证范围

本地真实 Flask／SQLite、冻结时钟和线程竞争验证覆盖阈值、逾期、独立成员状态、分页、GET 只读、初始版本、read／snooze、到期、回执重放、重启、完成／删除／改期、依赖、撤权、同事务清理、电视／家庭隔离、真实来源关系及容量拒绝。网络调用在测试中禁止，云记录全部为合成 fixture。

原件保留在本任务 ignored `test-results/task-reminders-r1/` 及后续明确增量目录；最终实际数量与固定提交见作者交付报告。没有真实云、浏览器、实体电视或生产部署验收，本页不把后续任务算作已完成。
