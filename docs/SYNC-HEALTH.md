# 同步状态与问题处理

本模块已于 2026-09-15 10:43:53 发布。本文描述只读接口、成员与家庭边界、摘要更新及问题处理入口；正式镜像和逐组验收见 [README](../README.md) 与 [VALIDATION](VALIDATION.md)。

## 使用方式

“连接中心”显示整个家庭所选日历与清单的状态。只有所有来源都在最近 5 分钟内成功同步，且没有错误、授权问题或异常时间，才显示全部正常。某个来源刚成功，不能掩盖其他来源延迟或尚未首次成功。

成员点“查看同步与问题”打开问题详情，查看本人绑定的账户、来源和本人有权处理的日历／待办发布记录。入口通向既有账户管理、日历复核或待办发布页面，查看状态本身不会重新授权、重试队列或写入云端。若需要修改或发布，继续沿用原页面的确认流程。

电视只显示共享的数量和时间汇总，没有详情入口。成员也不会在详情里看到伴侣的账户名、来源名称或私人发布标题。页面断网或刷新失败时保留上次成功读取的快照，并标明状态可能已过期。

## 接口

`GET /api/sync-health` 要求有效成员会话，响应 `Cache-Control: no-store`。未登录返回 401，电视身份返回 403。没有查询参数、写接口、自动重试或第三方网络调用；家庭路由沿用当前空间的数据库隔离。

响应字段：

| 字段 | 含义 |
|---|---|
| `version` | 固定为 1 |
| `checkedAt` | 本次读快照的 UTC 时间 |
| `staleAfterSeconds` | 当前固定 300 秒 |
| `household` | 家庭聚合状态，结构同下表 |
| `accounts` | 仅当前成员绑定的账户和所选来源 |
| `publications.calendar` | 记录 owner 为当前成员的日历发布统计与未完成事项 |
| `publications.tasks` | 记录 owner 或 account_owner 为当前成员的待办发布统计与未完成事项 |

`household` 同时通过既有 `GET /api/state` 的 `sync.health` 返回，电视可以读取该聚合对象。它不包含账户／来源名称、ID、邮箱、第三方错误文本或私人内容。

| 聚合字段 | 含义 |
|---|---|
| `state` | `not_connected`、`not_selected`、`needs_attention`、`waiting` 或 `current` |
| `connectedAccounts` / `selectedSources` | 本家庭已绑定账户和所选来源数量 |
| `sourceCounts` | 下表六种来源状态各自的数量，零值也返回 |
| `reauthAccounts` | 标记需重新授权或应用标识不匹配的账户数量 |
| `latestSuccess` / `oldestSuccess` | 当前所选来源有效成功时间的最大／最小值；没有则为 null |
| `lastCompleteSuccess` | 仅当全部来源均为 `current` 时返回最早成功时间，其余为 null |

旧 `sync.lastSuccess` 和其他旧字段保留兼容；新增界面使用 `sync.health` 判断完整性，不再把最大时间戳视作全家庭同步正常。

来源按以下顺序判断；每个来源只计入一个状态：

| 状态 | 判断与原因码 |
|---|---|
| `needs_authorization` | 账户有重新授权标记：`reauth_required`；配置 client ID 缺失或改变：`client_configuration_changed` |
| `error` | 存在同步错误或连续失败计数大于零：`sync_failed` |
| `waiting` | 从未记录成功时间：`awaiting_first_success` |
| `unknown` | 成功时间不可解析、缺时区或晚于检查时间：`invalid_success_time` |
| `delayed` | 成功时间距检查时间超过 300 秒：`stale_success` |
| `current` | 有效成功时间在 300 秒内，且没有上述问题；原因码为 null |

账户对象为 `id, provider, label, state, reasonCode, selectedSources, sources`。账户无来源且无需重新授权时为 `not_selected / none_selected`；否则优先级为授权、错误、未知、延迟、等待、正常。每个来源为 `id, name, kind, primary, state, reasonCode, lastSuccess, ageSeconds, nextAttemptAt`；时间均为带时区 ISO 字符串或 null，`ageSeconds` 为整数或 null。`nextAttemptAt` 只是队列计划时间，不能据此证明后台进程正在运行。

家庭状态先判断未连接，再判断授权／错误／未知／延迟，然后判断未选择、首次等待，最后为正常。账户即使尚未选择来源，只要需要重新授权，也计入 `needs_attention`。

每类 `publications` 包含：

| 字段 | 含义 |
|---|---|
| `counts` | 按原有发布状态计数，包括 `published`；不存在的状态不返回 |
| `items` | 最多 100 条非 `published` 事项；优先复核、授权、错误，再到待处理和暂停 |
| `truncated` | 还有未展示的事项时为 true；完整管理仍进入原模块 |

事项对象为 `id, journeyId, entityId, title, status, reviewRequired, updatedAt, nextAttemptAt, action`。`action` 为 `{kind: "calendar", target: journeyId}`、`{kind: "tasks", target: entityId}` 或 null。原实体／必需旅行计划已移除时不提供操作目标。`updatedAt` 是记录更新时间，不能当作云端最后成功时间。状态机和重试／复核语义仍分别由 [日历发布](CALENDAR-PUBLISH.md) 与 [待办发布](TASK-PUBLISH.md) 定义。

读取失败返回固定的 503 对象：

```json
{"error":"同步状态暂时无法读取，请稍后刷新","reasonCode":"sync_health_unavailable"}
```

响应不会包含 SQL、令牌、账户 subject、remote ID 或原始提供者错误。

## 实现与联合开发

| 文件 | 职责 |
|---|---|
| `sync_health.py` | 只读快照、状态计算、本人记录筛选与详情路由 |
| `cloud_accounts.py` | 原同步摘要扩展 `health`，同一读事务取得来源与聚合 |
| `app.py` | 在发布模块初始化后注册详情接口 |
| `static/sync-health.js` / `.css` | 摘要、只读问题详情、身份复核与原模块跳转 |
| `static/app.js` | 状态轮询即使 revision 未变化，也刷新小范围指示器 |
| `static/product-shell.js` | 连接中心摘要与入口 |
| `static/index.html`、`Dockerfile`、`deploy/prepare_release.py` | 显式加载、镜像和源码包文件清单 |

后端导出 `household_health(con, client_ids, now=None)` 和 `register_sync_health(app, db, require_member)`。前者复用已有事务；没有事务时自行开启只读快照并在结束时 rollback，不提交调用方事务。详情接口用同一快照读取统计和条目，显式选择字段，不解密令牌、不导入提供者或修改任何业务表。

前端导出 `window.SyncHealth.open()`、`summaryMarkup(health, options)`、`summaryText(health)` 和 `refreshIndicators()`。摘要容器使用 `data-sync-health-summary`；`data-sync-health-open` 由模块监听。`refreshIndicators()` 只读取最近一次 `/state` 结果，不发起额外请求；相同语义不重画，保留按钮焦点与正在编辑的工作台。模块在 `tv-display.js` 后、`product-shell.js` 前加载。

详情请求与操作入口检查 `/api/me`、当前成员、家庭、CSRF 和原弹窗节点。已观察到身份切换或弹窗替换后，旧响应被忽略；无法核对身份时清除详情。若另一标签页只改了 Cookie，且发生在最后一次身份核对返回之后，本页须在下次显式读取时才能发现，不承诺跨标签页即时清屏。演示和电视不访问详情 API；任何查看状态动作都不得暗中调用重试、确认或发布写接口。

本增量不增加表、列、环境变量、依赖、后台服务或调度任务。更新按 [DEPLOYMENT](DEPLOYMENT.md) 保留生产配置与数据；现有写进程停止后，候选初始化前后全部表、列和行应完全一致。发布包仍要显式包括新后端与静态文件。不要将健康检查成功当作外部同步成功。

## 验证与边界

专项测试使用虚构家庭和临时数据库：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_sync_health.py
.\.venv\Scripts\python.exe tests/browser_sync_health_check.py
```

本次已完成最终组合验证：Windows **981 passed / 12 skipped**，Linux **992 passed / 1 skipped**；两端完整收集 993 项；本轮 3 组浏览器记录：131 项功能检查，另有 59 条页面／视口记录；两类不混算。逐组脚本与范围见 [VALIDATION](VALIDATION.md)。专项涵盖来源新鲜度、首次等待、错误／授权、异常时间、只读事务及敏感字段、身份与迟到响应、断网和移动端；不能将合成测试称为真实新增云写、实体电视或公网浏览器通过。

5 分钟是状态提示阈值，不是同步延迟承诺。该模块判断数据库中已有成功记录和错误，不主动探测第三方，也不能证明外部内容完整或后台未来一定会成功。财务文件和投资导入有各自的来源日期、覆盖和核对流程，不计入日历／清单同步正常数量。
