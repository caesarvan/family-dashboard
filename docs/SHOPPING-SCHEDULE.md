# 采购截止日与优先级：后端合同

本合同已与 Expo 编辑器及助理草案组合，通过独立审查并合入 main；2026-09-20 03:54:39（北京时间）激活，03:55:48 独立只读审计通过。实现扩展现有采购实体、旅行计划和明确改期接口，保持 69/9，不增加表、迁移回填、云端权限或独立采购任务。[使用、分段验证与最新发布状态](SHOPPING-SCHEDULE-ACCEPTANCE.md#shopping-schedule-release)。下方接口合同保持。

## 字段与普通采购

| 字段 | 合同 |
| --- | --- |
| `due` | 空字符串，或有效的 `YYYY-MM-DD`，年份 2000—2100（含两端）。纯日期，不附时区或时刻。`null`、数字、布尔值和不完整日期均拒绝。 |
| `priority` | `low`、`normal`、`high`；除此之外的类型或值均拒绝。它表达安排优先级，不是订单、付款或配送状态。 |

新记录省略字段默认 `due: ""`、`priority: "normal"`。旧记录读取不会为此写库、补截止日期或更新 revision；消费者应按上述默认解释缺省字段。明确编辑后保存规范值。

```json
POST /api/items/shopping
{"title":"转换插头","quantity":"2 件","owner":"member1","budget":10000,
 "due":"2027-09-28","priority":"high"}
```

原 POST 回执 `{id,revision}` 不变。通过 `/api/state` 或旅行详情读取购物实体，原 `id`、`revision`、`tripId`、`journeyId` 规则不变。PATCH 仍需要当前 `revision`：

```json
PATCH /api/items/shopping/<id>
{"revision":3,"due":"","priority":"normal"}
```

PATCH 省略字段保留原值；显式空字符串清空截止，显式 `normal` 降回普通。非法输入返回 400，版本已变化返回 409，原角色、会话、CSRF 和 Origin 保护保持。校验失败不写实体或替换图片引用。

## 旅行预览、保存与旧客户端

`POST /api/journeys/preview` 的 `plan.shopping[]` 增加同样两字段：

```json
{"key":"adapter","title":"转换插头","quantity":"2 件","owner":"member1",
 "budget":10000,"note":"","due":"2027-09-28","priority":"high"}
```

生成的实体继续使用原 `workflowKey: "shopping:adapter"`、稳定 entity ID 和旅行关联。在已有旅行编辑中，若旧客户端省略 `due` 或 `priority`，服务端从**当前同 key 的关联购物实体**保留该字段，不能从旧计划恢复已清空日期。显式字段作为本次预览的修改意图进行校验，只有明确 apply 后保存。新行没有原实体时使用默认值。

原工作流 revision、关联实体 revision、会话验证、签名预览及幂等确认不变。预览后其他成员修改采购，旧确认返回 409；读取最新后重新核对。无需额外端点或订单/财务调用。apply 仍保留原 done、actual、photoIds；已有库存和结算关联依赖同一 entity ID，继续保留。

采购截止允许晚于返程，普通旅行预览以 `summary.warnings[]` 的 `code: "shopping_due_after_trip"`、`itemKey: "shopping:<key>"` 提示核对，保留填写的日期。后续用户明确选择改期时也不会自动截断越界日期。相对出发天数可由 AI/前端草案转换为绝对日期，但本后端采购合同仅保存 `due`，没有第二份隐含偏移或自动平移规则。

## 明确改期

`GET /api/journeys/<journeyId>/reschedule` 现在返回 `capabilities: {shoppingDue: true}`。有日期、未完成、未由云来源管理的采购输出：

```json
{"key":"shopping:adapter","kind":"shopping","title":"转换插头",
 "before":{"start":"2027-09-28","end":"2027-09-28"},
 "eligible":true,"reason":null,"endExclusive":false}
```

完成项 reason 为 `completed`，云来源为 `cloud_managed`，空日期为 `no_date`；不可选的完成/云项仍展示实际旧日期，空日期为 null/null。读取和预览只读。改期默认不选采购，只有显式加入 `selectedKeys: ["shopping:adapter"]` 才按出发日差值移动截止。

`reschedule-preview` 沿用现有 `selected`、`after`、`warnings` 与 `blockingIssues` DTO。提醒 `shopping_schedule` 说明仅调整选中采购截止；日期晚于旅行结束沿用 `outside_trip_dates` 提示。日期越过支持年份拒绝预览。apply 一次事务更新选中采购原实体和 plan 行，未选/已完成/无日期保持原实体；同步当前实体的 due/priority 到计划，优先级、金额、图片、负责人、完成及其他关联不动。

原 `previewToken`/`idempotencyKey` 和 `/api/journeys/operations/<key>` 回执恢复不变。重复确认只读取原回执，不二次移动截止或创建采购。本地改期成功不表示外部云日历已确认，采购自身不会因此成为云待办。

旧 Expo 改期解析器曾硬编码 `shoppingDue === false`；新 capability 必须与已审前端一起构建、验收及发布，不能仅更新此后端后声称旧页面兼容。新前端应兼容旧服务器的 false。

## 数据与验证边界

`entities.data` 和 `journey_workflows.plan` 继续使用 JSON；无 DDL、批量回填或启动写入。共享导出仅在本人明确 `includeShared: true` 时按既有规则包含采购 due/priority，新增 `priority` 白名单不增加私人来源、订单或财务共享。

定向测试位于 `tests/test_shopping_schedule.py`，使用真实 Flask、独立 SQLite、实际认证/预览/确认/回执；网络被禁止。覆盖 CRUD、严格值校验、旧 v1/v2 请求省略/清空、旧库无回填、明确改期和同凭证重放、边界日期、版本冲突、权限、图片/库存/实付关联及共享导出。原 `tests/test_journey_reschedule.py` 的 capability 断言同步为 true，其余既有改期保护仍需回归。

真实浏览器、独立视觉审查、AI 调用、真实用户操作及部署须另行提供证据；本合同及合成测试不等于这些验收完成。
