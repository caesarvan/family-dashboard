# 旅行改期与关联事项

本页描述已组合、正在验收的源码候选，尚未发布。实际安装版本仍以 [README](../README.md) 和 [验证记录](VALIDATION.md) 为准。它补齐旅行日期调整时的任务、地点和本地日历协调；完整产品目标仍见 [产品计划](PRODUCT-PLAN.md)。

## 使用流程

1. 在新版旅行详情点击「调整日期」，填写新的出发和返程日期。
2. 选择需要随出发日平移的目的地、未预订分段、未完成准备和本人计划地点。默认保留各项日期；旅行总览始终更新。
3. 点击「预览改期」，逐项核对旧日期、新日期、保留原因及提醒。缩短或延长旅行不会按比例压缩行程，也不会自动截断越界日期。
4. 跨时区分段按当地日期平移。遇到不存在或出现两次的当地时刻，修改当地时间或选择明确的 UTC 偏移，再次预览。
5. 明确确认后一次保存本地改动。已连接的日历沿用既有发布关系，由同步服务更新；本地保存成功不代表云端已确认，实际状态在「同步到日历」中查看。

已完成任务、已到访地点、固定／已预订／已取消分段不随本流程移动。只列出本人地点，不根据地名或日期猜测目的地对应关系。地点的坐标、共享范围、到访确认以及各事项的负责人、本人修改的备注和金额保持；系统生成的时刻说明随选中的分段更新。

采购目前没有截止日期字段；改期页明确提示不适用。预算、实付与预订资料不会自动重算，仍需本人核对改退规则和新增费用。本流程不联系航司、酒店或商家，也不办理改签、取消或付款。

## 接口

全部接口要求当前家庭的成员身份；电视不能调用。POST 沿用同源 JSON 和 `X-CSRF-Token`。签名凭证只在客户端内存保留，不写入 URL 或持久浏览器存储。

### 读取影响范围

`GET /api/journeys/<id>/reschedule`

返回：

```json
{
  "journeyId": "旅行工作流标识",
  "revision": 4,
  "start": "2026-10-01",
  "end": "2026-10-07",
  "snapshotToken": "签名来源快照",
  "expiresIn": 1800,
  "items": [{
    "key": "task:packing",
    "kind": "task",
    "title": "核对行李",
    "before": {"start": "2026-09-29", "end": "2026-09-29"},
    "eligible": true,
    "reason": null,
    "endExclusive": false
  }],
  "warnings": [],
  "capabilities": {"shoppingDue": false}
}
```

`journeyId` 是工作流标识，不是 `tripId`；旅行名称读取 `items` 中 `key:"trip"` 的 `title`。每项 `kind` 为 `overview`、`destination`、`segment`、`task`、`shopping` 或 `place`；稳定 key 分别为 `trip`、`destination:<key>`、`segment:<key>`、`task:<key>`、`shopping:<key>`、`place:<id>`。

`before.start/end` 为日期字符串或 `null`，未知日期保持未知。住宿和日期型活动可使用排他的结束日，由 `endExclusive` 明确标识。不可选的 `reason` 包括 `always_updated`、`completed`、`no_date`、`cloud_managed`、`fixed`、`booked`、`cancelled`、`not_planned`、`missing_event` 和 `timing_changed`；`overview` 使用 `always_updated`，不需要加入选择。分段的时间语义或时区已被独立修改时按 `timing_changed` 保留，不能从旧计划猜测当前含义；普通日期修改从实际当前事件计算。

快照绑定实际成员会话、认证版本、旅行和关联实体及本人地点的版本。打开页面后其他设备修改记录时，旧快照不能继续确认；读取和预览均不修改业务记录、队列或云端数据。

### 查看改期影响

`POST /api/journeys/<id>/reschedule-preview`

```json
{
  "snapshotToken": "读取时返回的签名来源快照",
  "start": "2026-10-03",
  "end": "2026-10-09",
  "selectedKeys": ["destination:kyoto", "task:packing", "place:地点标识"]
}
```

平移天数等于新旧出发日期之差，从来源快照对应的当前记录计算；反复预览不会叠加平移。`selectedKeys` 只接受仍可调整的已列出对象。仅更改返程日时，日期平移量为零，但仍需核对总范围及警告。

返回 `journeyId/revision/start/end/items/warnings/blockingIssues/canApply/previewToken/expiresIn`。每项在来源字段上增加 `selected` 和 `after:{start,end}`，以此显示实际前后差异。定时分段和有已知时刻的住宿还提供 `timeBefore/timeAfter`，包含可用的 `start/end:{local,timeZone,offsetMinutes}`，在确认页核对当地时刻与偏移；同日改变时分或偏移也算实际变化。`warnings` 条目含 `code/key/message`。存在阻断问题时返回 HTTP 200、`canApply:false` 和空预览凭证；不可确认的预览不产生保存操作。

时区问题在 `blockingIssues` 中给出 `code/key/message`，并可包含 `field:"start"|"end"`、`local`、`timeZone` 和 `choices:[{offsetMinutes,instant}]`。纠正后以同一快照重新预览：

```json
{
  "snapshotToken": "原来源快照",
  "start": "2026-10-25",
  "end": "2026-10-29",
  "selectedKeys": ["segment:walk"],
  "timeOverrides": {
    "segment:walk": {
      "start": {"local": "2026-10-25T02:30:00", "offsetMinutes": 60}
    }
  }
}
```

示例为虚构的重复当地时刻。仅纠正选中分段的起止当地时间和偏移；原 IANA 时区保持，UTC 时刻由服务端重新验证，不由浏览器加固定秒数猜测。

### 确认与未知结果恢复

确认继续使用 `POST /api/journeys/apply`：

```json
{"previewToken":"最终预览凭证","idempotencyKey":"本次固定操作编号"}
```

响应保留 `id/tripId/revision/calendar`，增加 `operation:"reschedule"` 和 `reschedule:{start,end,changedKeys}`；重放原成功操作带 `replayed:true`。此分支的 `calendar` 为 `{local:"updated",cloud:"status_not_checked",icsUrl}`，仅说明本地更新，不能据此推断已绑定或未绑定。同一保存请求的重试必须保留原凭证和编号，不能为了绕过冲突创建新编号。

`GET /api/journeys/operations/<idempotencyKey>` 用于只读核对本人历史回执，返回 `found:true/idempotencyKey/result`。没有记录时返回 404 和 `code:"operation_not_found"`；404 不证明先前仍在途的请求不会成功。预览已过期也可以用有效成员会话核对已保存回执。读取历史回执不会恢复随后修改或删除的记录；查看结果后重新读取当前旅行。

来源已变化返回 409 `stale_snapshot`；确认前变化返回 409 `stale_preview`。界面保留输入，重新读取来源后由本人再次核对。事务会话失效返回认证错误，界面隐藏旧成员内容。

## 实现与发布边界

- `journey_reschedule.py` 负责日期建议、逐项影响和时区校验；`journey_workflows.py` 负责来源签名、权限、版本复核及确认事务。
- `JourneyReschedulePanel.tsx` 和 `lib/journeyReschedule.ts` 提供独立面板；`TripsScreen.tsx` 仅传工作流标识和返回回调。面板后台／离线隐藏，恢复时复核身份，迟到响应不能覆盖新的成员或旅行。
- 沿用 `journey_actions` 保存回执；不新增表，不改变地点共享或日历目标。所有本地日期改动与回执在同一个 SQLite 事务中完成。
- 新模块必须进入 Docker COPY 和源码发布白名单。已有固定版本发布算子不能直接重放，下一次部署须绑定当时实际运行版本。
- 本地 SQLite、浏览器及模拟提供方的验证与真实账号、真实模型和实体电视验收分别记录。尚未有本轮发布证据，不能把源码候选当作线上可用。
