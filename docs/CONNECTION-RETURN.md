# 无目标来源时连接账户并返回发布

状态：已于 2026-09-15 03:58:15 发布。本增量不增加后端接口、数据库表、依赖或主页加载顺序；集成版双平台各 16 项临时浏览器检查通过，实际 OAuth 回跳仍待验证，见 [交接说明](HANDOFF.md)。

## 空家庭的待办起步（本轮独立分支，尚未发布）

共同待办尚无记录时，点击“开始安排待办”可选择：

- **添加第一件待办**：进入原编辑器，默认“家庭看板本地待办”；即使已设置云端主清单也不默认写云。取消不创建记录，保存后在共同待办页读回。
- **先设置常用清单**：打开本人账户管理，可连接账户、选择日历或清单并确认共享范围，也可暂不连接。明确点击“返回待办”后重新核对身份与共享状态，回到待办页继续安排。

设置来源不会创建或发布待办。有记录后仍使用原非空目标、手动选择、预览与确认流程。没有来源或应用尚未配置时，本地待办仍可使用；真实平台授权需本人在平台完成。

## 用户流程

1. 在旅行详情打开「同步到云日历」，或打开「连接待办主清单」。没有可用目标时，点击「连接账户或选择来源」。
2. 进入已有「账户与自动同步」管理页。已绑定账户可直接「选择日历与清单」；未绑定时，用户自行点击绑定，并在平台页面授权。
3. 选择来源、确认共享范围并保存。页面停留在账户管理，可继续配置，也可明确点击「返回日历发布」或「返回待办发布」。
4. 返回时重新读取当前成员、家庭和原始记录，再显示发布目标选择。待办不会自动勾选；日历、待办仍分别需要预览和确认发布。

保存来源沿用既有读取同步机制。进入管理页、保存来源和返回均不会自动授予写权限、创建云日历事项或云任务、建立发布关系。已有授权范围不足时，原有显式授权或重新绑定按钮继续工作。

本轮空家庭起步使用独立的配置意图，不向发布接口提交空目标，也不把空数组解释成“所有待办”。原发布意图仍需已有旅行或非空待办 ID；原任务被删除、已转为不支持的来源，或原旅行不存在时，返回校验失败，不回退到其他记录。

## 文件与接缝

| 文件 | 职责 |
| --- | --- |
| `static/accounts-ui.js` | `window.AccountsReturn`、账户管理返回入口、来源读取/保存时的当前身份复核、OAuth 意图处理 |
| `static/calendar-publish.js` | 无日历来源按钮；清除旧预览/冲突上下文；返回时重新读取原旅行；写权限升级前保留返回意图 |
| `static/task-publish.js` | 无清单来源按钮；绑定原旅行或明确任务 ID；返回时重新读取、保持未勾选 |
| `static/product-shell.js` | 空清单入口与受原节点／身份保护的待办导航、首项本地编辑 |
| `tests/browser_task_start_check.py` | 空家庭首项、配置返回、无自动发布与迟到响应的临时浏览器检查 |
| `tests/browser_connection_return_check.py` | 临时 Flask + SQLite + Edge、合成来源发现、本机回跳模拟与隐私/竞态验收 |

`accounts-ui.js` 已在两个发布组件之前加载，无须修改 `index.html`。没有新增 API、数据库表、配置项、后台任务或依赖。

`AccountsReturn.begin(target, context?)` 打开原账户管理；`target` 的发布意图只允许：

```javascript
{kind: 'calendar', journeyId: 'synthetic-journey-id'}
{kind: 'tasks', journeyId: 'synthetic-journey-id'}
{kind: 'tasks', entityIds: ['synthetic-task-id']}
```

配置意图为 `{kind: 'task-setup'}`，只能包含 `kind`，不能附带 `journeyId` 或 `entityIds`。它只核对当前身份，进入原账户管理，不读取发布目标。返回通过 `ProductShell.openTasks({originNode}, context)` 暂存读取 `/api/state`，再次核对 `/me` 及原按钮节点后才导航；较旧 revision 不回退全局状态。首项动作使用同一接缝的 `create:true` 进入原本地待办编辑器。

任务 ID 必须非空、唯一，最多 100 个。全体待办入口在进入连接流程时冻结当前任务 ID 集合；不会在返回时自动扩展为新增加的任务。ID 限 128 字符，使用字母、数字、点、下划线、冒号和连字符。

`CalendarPublish.open(journeyId, expectedContext?)` 和 `TaskPublish.open(options, expectedContext?)` 保留原单参数调用方式。可选上下文只在内存中使用：打开后仍需调用 `/api/me`，读取目标，再次复核身份，才显示结果。

## 同页身份与异步边界

- 读取 `/api/me` 的 `user.id`、`user.householdId`、`user.auth_version`，并把响应顶层 `csrf` 与页面当前值比较。
- CSRF 仅保留在当前 JavaScript 内存中。任何身份或 CSRF 变化都要求重新打开入口；不会依靠前端缓存判断跨家庭访问权限。
- 原记录通过 `/api/calendar-publish/journeys/<journeyId>` 或 `/api/task-publish/state?journeyId=...` / `entityIds=...` 重新校验。
- 账户管理涉及本人账户内容；展示前再次校验 `/me`。同页返回发现实际 Cookie 已换成员时移除旧管理内容并提示刷新。
- 发布组件用页面代次和原对话框节点限制异步结果；旧请求不能重新打开已关闭页面、覆盖新记录选择或清除后来建立的返回流程。
- 每次打开发布页都清除旧预览和冲突确认令牌。后端既有 CSRF、成员/家庭权限、预览签名和写入确认规则继续生效。

## OAuth 全页跳转

仅在用户明确点击账户绑定或日历写权限升级、服务端返回的授权地址通过原有 HTTPS/平台域名检查后，准备短期返回意图。实际授权仍由既有 OAuth 流程执行。

使用当前标签页 `sessionStorage` 的 `family-dashboard.connection-return.v1` 键，白名单内容为：

```json
{
  "v": 1,
  "flowId": "synthetic-flow-id",
  "target": {"kind": "calendar", "journeyId": "synthetic-journey-id"},
  "memberId": "member1",
  "householdId": "default",
  "authVersion": 1,
  "createdAt": 1790000000000,
  "expiresAt": 1790000600000
}
```

有效期 10 分钟，不含标题、内容、邮箱、财务数据、CSRF、OAuth 访问/刷新令牌、预览或冲突令牌。返回意图与发布授权不同；修改意图不能绕过服务端记录和成员权限。

收到本机 `?auth=connected` 或 `?auth=error` 回跳后，重新核验当前 `/me` 和原目标，只恢复账户管理里的「重新打开日历发布/待办发布」按钮。不会自动打开旧选择，也不会恢复任何旧内容、预览或确认。用户点击后再次读取原记录，以当前会话开始新选择。

配置意图也使用同一 10 分钟白名单存储，只保存 `kind: task-setup`；模拟全页回跳后仅恢复“返回待办”按钮，不恢复草稿、勾选或发布凭证。

过期、非法、跨成员、跨家庭、密码版本变化、缺失发布目标均丢弃意图。正常退出登录、家庭切换表单提交、创建家庭表单提交、登录表单提交和家庭/平台登录链接点击会主动清理。错误原因、身份字段和正常清理都不能证明所有跨标签页或手工 Cookie 操作。

**同一成员重新登录可能保持相同 `auth_version`。因此全页恢复不声称证明“仍是原登录会话”；它只提供当前身份核验后的重新发起入口。** 已消费的存储意图删除；旧异步流程只能清理自己持有的意图标识。

## 验证与限制

运行专用浏览器脚本，另保留原待办和日历发布浏览器回归：

```powershell
python -X utf8 tests/browser_task_start_check.py
python -X utf8 tests/browser_connection_return_check.py
python -X utf8 tests/browser_task_publish_check.py
python -X utf8 tests/browser_calendar_publish_check.py
```

脚本只创建临时本机家庭和合成账户；阻断所有非本机浏览器请求。来源发现使用假的平台传输，返回来源后仍走真实 Flask 接口与源选择保存。专用报告输出到 `test-results/connection-return-browser-verification.json`，截图也仅含合成内容。

OAuth 证据限于调用实际意图序列化函数后，以同源重载模拟授权完成/取消回跳；没有访问微软或 Google 授权网站，也未确认真实平台重定向、移动 Safari 或长时间跨标签页行为。生产回归仍需本人实际授权后验证，但不需要把凭据交给 agent。

既有接口与配置见 [账户接入文档](ACCOUNT-SYNC.md)、[云日历发布](CALENDAR-PUBLISH.md)、[待办发布](TASK-PUBLISH.md) 和 [接口索引](API.md)。
