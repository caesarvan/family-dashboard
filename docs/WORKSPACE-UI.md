# 家庭中枢工作台与界面交接

> **当前版本：2026-09-15 16:25:03（北京时间），镜像 `sha256:f1e4cc56979f793f32585f498fa2fca55987356bd68f67e8cc6c14f0b1b6a01d`。** 旅行执行进度、真实待同步提示及两个订单表头兼容已发布，保留此前全部模块；源码／文档数量见 README 和逐文件清单、101 个方法／路径模板、42 张户内表及 2 张平台表。本轮无结构迁移。真实云写与其他外部验收仍按 [VALIDATION](VALIDATION.md) 单列。

> 2026-09-15 12:11:36 已发布 [采购实付核对](SHOPPING-SETTLEMENT.md)：从原采购或本人账本进入，选择付款、核对整项金额与已买到、预览确认后回读；交易明细与关联历史保持本人私有。此版本镜像为 `sha256:1167dffd3b7e234d43460442acfe0d30959370c90c7e8147a1b30baa0e2380b5`。

> 2026-09-15 10:43:53 已发布 [同步状态界面](SYNC-HEALTH.md)：连接中心按来源新鲜度汇总，本人详情与共享聚合分开。业务 revision 未变化时也更新摘要，保留工作台与焦点；电视只读汇总。

## 财务更新与数据下载接缝

账单导入仍由 FinanceHub 管理；确认返回 resultMonths 和 confirmedAt，overview 返回当前 availableMonths。回执和后续月份选择绑定原成员、家庭、CSRF、请求代次与节点；已收到确认成功后，“重新读取账本”仅发 GET。FinanceSourceUI.open(options={}) 的 options.mode 只有 spending_observation 会进入独立观察，省略或其他值回到 baseline；也可在原更新范围下拉框明确选择。它复用原三条来源 API，FinanceBaseline 展示原资产日期与独立报告日期，不相加。DataPortability.open() 继续从设置进入，先读取摘要，明确操作后生成本人 ZIP；保护与最终读取后的非原子限制见 [PORTABILITY](PORTABILITY.md)。

本轮没有增加静态模块或加载顺序，仍为 20 个脚本／14 份样式；不要新增重复的 document 委托或覆盖其他流程返回桥。现有 finance-hub.js、finance-source-ui.js、finance-baseline.js 与 data-portability.js 均先登记唯一编辑者。真实文件与账户不进入 UI 测试。

## 每台电视的显示设置

已发布 tv-display.js/.css：手机编辑每台设备的卡片排序/显隐、主题、密度，16:9 示意预览不查询私有财务。保存后仍留在原编辑器并读回配置；并发 409 需要明确选择最新设置或保留草稿。主题只作用于电视节点及预览，成员工作台偏好独立。

tv-display.js 在 sync-health.js、product-shell.js 前加载，TV 重绘仍调用 TVDisplay.applyBoard()；电视配对入口和布局配置保留。当前完整次序为 20 个脚本／14 份样式，见 [开发指南](DEVELOPMENT.md)。09:47 电视批次的 68+35+11 功能检查与 59 页面记录保留历史范围，本次逐组结果见 [VALIDATION](VALIDATION.md)。

**投资与首次电视配对增量已于 2026-09-15 08:56:01 发布：** 本页记录投资持仓文件导入、更新、模块加载与返回流程。电视空态入口见 [使用手册第 8 节](USER-GUIDE.md#8-为两块电视分别配对)。本次实际 8 组 175 场景及服务器内部读回见 [VALIDATION](VALIDATION.md)；历史验证、真实机构与实体设备验收边界分别保留。

## 成员登录设备交互

本人打开“设置 → 登录设备”后读取最新列表；选择其他浏览器或“退出其他浏览器”先确认，再向服务端撤销并读回。当前登录保持有效；自己的退出仍在设置页底部。退出其他会话不解除云账户绑定或电视配对。

请求绑定原成员、家庭、CSRF 和弹窗节点；迟到列表、成功或错误不接管后来流程。点击确认前重新核对会话，已发送操作不能因关窗被取消。单独浏览器入口为 `tests/browser_member_sessions_check.py`；07:58 历史 14 组与本次投资 8 组分别见 [VALIDATION](VALIDATION.md)，真实设备仍待验收。

**历史流程增量：** 2026-09-15 10:43:53 同步问题中心，镜像 `sha256:6882d2a2009ce4ef378cc2448026f5a7edc4b63fd14e440bc104fcdd6d7e159c`。本地与镜像验收、实际浏览器分组及线上读回见 [VALIDATION](VALIDATION.md)；投资、会话和旅行等历史流程继续保留，未扩大真实平台验收范围。

本文描述已实现的产品外壳及真实浏览器验收，供后续 UI、业务模块与集成人协作。设计目标是让家庭成员从同一个入口处理安排、清单、旅行与财务；已有编辑器和服务端权限仍是实际操作边界。其他总体说明见 [README](../README.md) 和 [开发交接](DEVELOPMENT.md)。

发布状态：首页卡片布局、财务关联对账、任务发布与个人数据导出已于 2026-09-15 01:10:44（北京时间）部署。本页保留的浏览器通过记录来自临时环境；本次正式域名的浏览器访问被组织安全策略阻断，不能称公网 UI 验收通过。服务器内部验收与范围见下文；最终发布证据见 [README](../README.md) 和 [VALIDATION](VALIDATION.md)。

**02:33 新增界面已发布：** 财务来源更新、旅行 v2 明细及“核对旅行时间变化”已随整体镜像上线。下述浏览器记录来自临时 Flask/Edge；02:34 的服务器内部检查另确认 28 个静态资源匹配、11 个匿名接口拒绝及六个来源同步成功。

**2026-09-15 03:11:08 已发布：** “本周待处理”操作入口和云日历发布表并发初始化修复已进入 `sha256:2aff068d58560acd4099954fc034f3aeedc55bff1a0971ceb27d5ff33e0c4b5d`。Windows 551 passed / 230.87s、Linux 550 passed / 1 skipped、主目录行动台浏览器 21 场景及 JS 语法检查通过。第 5.2、6.2 节描述本次已发布界面，实际公网和外部账号边界见 [交接说明](HANDOFF.md)。

## 1. 当前界面与交付文件

新增 [member-sessions.js](../static/member-sessions.js) 与[样式](../static/member-sessions.css)，由设置页“登录设备”按钮调用 `MemberSessions.open()`。脚本以 defer 加载在 `product-shell.js` 前，基础 app.js 与对话框能力先可用；样式位于 product-shell.css 后。不要将会话记录或撤销凭据纳入共享搜索、财务缓存或个人 ZIP。

- [product-shell.js](../static/product-shell.js)：页面导航、共享内容搜索、主题偏好、工作台内容与业务模块入口。
- [product-shell.css](../static/product-shell.css)：设计令牌、桌面侧栏、手机底部导航、三套主题、两种密度、原有卡片与弹窗的统一样式。
- [界面浏览器检查](../tests/browser_product_shell_check.py)：真实 Flask、临时数据库和 Edge 的布局、导航、偏好及基础操作验证。
- [业务闭环浏览器检查](../tests/browser_product_workflows_check.py)：真实助理方案、账单导入、账单核对、投资录入与成员隔离验证。
- [助理行动台](../static/home-assistant.js)及其[样式](../static/home-assistant.css)：五类原记录入口及按数据出现的第六类例行计划、上下文保护和处理后读回；[专项浏览器检查](../tests/browser_assistant_actions_check.py)覆盖合成操作与隔离。
- [finance-source-ui.js](../static/finance-source-ui.js)：本轮新增的本人来源文件选择、日期／共享小计预览、确认与失败保留；由财务基线弹窗进入。
- [旅行界面](../static/journey-ui.js)与[云日历发布界面](../static/calendar-publish.js)：本轮新增的航班／住宿／活动表单、迁期／冲突选择与时间语义核对；不由产品外壳直接写云端。
- [investment-import.js](../static/investment-import.js) 及其[样式](../static/investment-import.css)（2026-09-15 08:56:01 已发布）：来源与文件选择、XLSX 选表、持仓差异、明确确认、虚构示例与本人持仓导出。由 `finance-hub.js` 的投资账户页提供入口，返回时重新读取本人持仓，不借用共享 `data`。

没有新增 React、Vue、npm 构建链或外部字体服务。房屋插画由本地 CSS 绘制，旅行插画复用已有 `journey.svg`。样式和脚本直接由同源静态服务提供。

## 2. 页面导航

桌面使用左侧常驻导航；宽度不超过 760 px 时使用底部导航，保留今日概览、日程、共同待办、家庭助理四个直接入口，其他页面从“更多”展开。页面内的编辑器使用原有 `dialog`，避免将已有表单或上传草稿移出它们依赖的 DOM。

| 页面键与地址片段 | 页面内容 | 主要操作入口 |
| --- | --- | --- |
| `home` / `#home` | 问候、今日安排数、未完成待办、待采购、共同荷包余额；日程、公共财务、待办、采购与下一趟旅行卡片 | 家庭助理、快捷新建、侧重成员、日程范围、外观、首页卡片编辑 |
| `calendar` / `#calendar` | 独立日程工作台，今日、本周、前后 3 天和日期导航 | 添加安排、展开某日完整日程、侧重成员 |
| `tasks` / `#tasks` | 共同待办全列表；待完成、已完成、全部筛选；标题/备注搜索 | 新增、完成/恢复、本地事项编辑 |
| `shopping` / `#shopping` | 采购全列表、已填预算小计、缺预算数量、完成状态筛选与搜索 | 新增、预算/实付/数量/图片编辑、标为买到 |
| `trips` / `#trips` | 旅行卡片、目的地、日期、预算与准备进度 | 打开旅行工作台，已有旅行可进入关联规划 |
| `finance` / `#finance` | 共同资金卡片，账单、投资、个人基线和月度预算入口 | 私有财务工作台、账单导入与核对、投资记录 |
| `assistant` / `#assistant` | 助理介绍和启动入口；“本周待处理”五类原记录与按需出现的例行计划行动台 | 打开原事项、核对并回读，继续搜索、规划、审阅和确认；行动台已发布 |
| `connections` / `#connections` | 已绑定账户/选中来源的汇总状态，Microsoft、Google、财务导入和电视入口 | 管理账户与来源、财务导入中心、显示设备 |
| `settings` / `#settings` | 外观、家庭空间、个人账户、连接与电视设置 | 保存主题偏好、修改资料、配对/管理电视、退出 |
| `household` / `#household` | 当前家庭名称、成员、共享边界 | 切换家庭、邀请码与家庭创建入口 |

`ProductShell.navigate(route)` 更新地址片段，支持浏览器前进/后退及刷新恢复当前页面。仅接受表内已知页面键；地址片段不包含账户、财务记录或 OAuth 信息。路由恢复仍先经过正常登录，不构成公开访问权限。

家庭名称读取 `/api/spaces/current` 的 `name`；未取得名称时使用“我们的家”。登录页也提供 `data-household-open` 与 `data-household-redeem` 两个入口，分别交给家庭空间模块处理切换与邀请码创建。创建家庭不依赖原家庭已登录。

## 3. 外观、布局与同步

已提供的外观是以下三套固定主题：

| `theme` | 界面名称 | 风格 |
| --- | --- | --- |
| `forest` | 暖绿森林 | 深绿底色、暖白文字与柔和绿色强调 |
| `light` | 晨光白 | 米白底色、深绿文字与浅色卡片 |
| `ocean` | 海岸蓝 | 深蓝底色、蓝绿色强调 |

信息密度为 `comfortable`（舒适）或 `compact`（紧凑）。密度调整欢迎区、卡片留白和列表间距，不改变任何业务数据。采购勾选及图片编辑保留较大的触控区域，手机待办完成按钮采用 44 px 触控区域。

默认日程范围 `homeView` 为 `today`、`week` 或 `around`。界面通过 `CalendarViews.setMode(value, {persist:false})` 应用服务器偏好；旧版日程模块没有该方法时，才使用现有模式按钮兼容。用户当前会话内的普通视图切换仍由日程模块负责。

偏好请求契约：

```json
{
  "theme": "forest",
  "density": "comfortable",
  "homeView": "today"
}
```

- `GET /api/preferences`：已登录成员读取本人的偏好。界面兼容直接对象与 `{ "preferences": { ... } }` 的返回形态。
- `PUT /api/preferences`：使用已有 `write()`，发送完整三个字段和 CSRF；服务端是最终校验与持久化位置。
- 成员登录后读取偏好，页面重新可见时刷新；常驻可见页面约每 60 秒检查一次。普通共享内容仍由原有 `/api/state` 约 10 秒刷新。
- 外观在本机缓存，以便短时网络失败时保留上次外观。显式保存失败时，弹窗保留选中项并显示错误，不提示保存成功。
- 演示偏好仅写本机缓存，不发偏好写请求。
- 电视不读取或写入成员偏好接口，保留原有设备侧重成员、设备日程视图和全屏展示方式。

### 3.1 成员首页卡片布局（2026-09-15）

首页“编辑首页”和设置页“首页卡片布局”打开独立编辑器。五张卡片为 `calendar`（日程）、`finance`（家庭财务）、`tasks`（待办）、`shopping`（采购）、`trips`（旅行）；默认也是这一顺序。上下移按钮或聚焦卡片后按 Alt + ↑ / ↓ 排序，勾选控制显示；至少保留一张卡片。“恢复默认”只调整草稿，点击保存后才生效。

手机按钮保留至少 44 px 触控区域，保存区在弹窗内固定可达，较长清单可滚动。桌面按顺序两列展示，奇数最后一张铺满；平板/手机按顺序单列。隐藏仅影响首页卡片，顶部概览数字和对应导航页面仍可使用，不删除记录，也不是新的权限控制。电视继续使用专用固定布局。

独立接口由 [dashboard_preferences.py](../dashboard_preferences.py) 的 `register_dashboard_layout(app, db, Problem, body, require_member, audit)` 注册，不扩充原 `/api/preferences` 三字段契约。

```json
{
  "revision": 0,
  "order": ["calendar", "finance", "tasks", "shopping", "trips"],
  "hidden": []
}
```

- `GET /api/dashboard-layout`：成员本人读取；无记录时返回默认布局与 revision 0，不写入。电视返回 403，未登录返回 401。
- `PUT /api/dashboard-layout`：只接收上述三个字段，沿用 CSRF、同源和 JSON 守卫。revision 必须是非负整数（不接受布尔值）；顺序与隐藏键必须属于五张已知卡片，重复键去重，遗漏卡片追加默认顺序。全部隐藏、额外 owner 字段、非法键等返回 400。
- `member_dashboard_layout(owner PRIMARY KEY REFERENCES users, data, revision)` 存在各家庭独立数据库中，同一家庭的两位成员互不共享布局；它不进入 `/api/state`。
- `BEGIN IMMEDIATE` 保护读版本和写入；过期版本返回 409，不覆盖。内容未改变时不增加 revision；首次竞争保存也只有一个请求成功。
- 兼容规则：新客户端未提交的已知卡片默认显示；当前不认识但数据库原已存的未来卡片键会保留，移至顺序末尾并保留隐藏状态。旧客户端不能凭请求新增未知键，也不会抹除未来配置。
- 成员登录、回到前台和约 60 秒定时读取服务端布局；本人布局不另写本机永久缓存。演示只存 `household_demo_layout`，不调用布局 API；TV 零布局请求。
- 保存失败保留草稿。409 显示“查看最新布局”，实际读取另一设备保存的布局后，用户可以采用最新布局或保留自己的草稿；保留草稿仍需再次点击保存，没有自动覆盖。

当前没有鼠标拖放、自定义列数、任意卡片宽高、上传背景、自由颜色或第三方皮肤。主题与密度仍仅在既有枚举内选择。


## 4. 可见范围与操作边界

1. 工作台全局搜索只遍历已经进入共享 `data` 的日程、待办、采购和旅行，匹配标题、地点、目的地与备注。不会为搜索额外读取个人账本、投资或资产基线。最多显示 40 项匹配结果。
2. 今日概览的荷包余额只在共同财务存在 `confirmedAt` 时显示金额；没有核对记录时显示“待核对”。该金额仍是手动核对的快照，不表示已实时连接支付宝或银行。
3. 采购预算小计仅加总未完成且预算已填写的记录。未知预算单独计数，不按零元推定。
4. 公共财务、经批准的资产/负债汇总按原有共享接口展示；个人月度收支、个人财务基线、账单和投资仍需要所属成员的私有 API。
5. 连接中心展示“支持的接入方式”和当前账户/来源汇总，不将未连接的服务标为已同步。账单文件导入不表示已取得购物或银行账户的实时连接。
6. 普通成员的写入仍由 `canEdit()`、原有 CSRF/同源校验和服务端成员守卫共同控制。UI 的按钮可见性不能替代后端授权。
7. 演示允许浏览、筛选、搜索和切换主题。旅行模块提供自己的演示预览；助理显示明确标注的示例。个人财务工作台在演示中给出解释与登录入口，不读取真实财务。演示不创建账单、任务、投资或远端事项。
8. TV 不渲染侧栏、底部导航或新工作台，继续显示经过尺寸验证的五张卡片；照片和财务私有权限保持服务端验证。

家庭成员姓名、搜索结果、行程名称等动态文本通过 `esc()` 转义。不能把服务商返回的标题或家庭名称直接拼成未转义 HTML。

## 5. 加载顺序与模块接口

基础业务样式先加载，product-shell.css 提供主题；member-sessions.css、investment-import.css、tv-display.css 随后加载，sync-health.css 最后加载且仅作用于模块与摘要。product-shell.js 以 defer 位于业务模块之后，在 DOMContentLoaded 的 boot() 前加载。

本版本的实际 `defer` 顺序为：`app.js → accounts-ui.js → calendar-ui.js → shopping-ui.js → finance-baseline.js → finance-source-ui.js → journey-ui.js → calendar-publish.js → task-publish.js → finance-hub.js → investment-import.js → home-assistant.js → household-spaces.js → data-portability.js → member-sessions.js → tv-display.js → sync-health.js → shopping-settlement.js → household-routines.js → product-shell.js`。基础身份、请求与弹窗先加载，product-shell.js 最后接管工作台；例行模块在采购核对之后、产品外壳之前加载。问题中心仍只读局部刷新；例行 notifyStateChanged() 只更新提示，不发请求或丢弃草稿。已对照 [HTML](../static/index.html)。

产品外壳只包装全局 `renderBoard()` 与 `renderLogin()`，保留原有 `openModal()`、`closeModal()`、`manage()`、`editItem()` 和 `bindForm()`。业务模块的异步请求、表单校验、图片草稿、版本冲突及云端回写仍由原模块处理。

| 依赖 | 调用与约束 |
| --- | --- |
| 基础状态 | `user`、`data`、`csrf`、`focus`、`isTV`、`isDemo`、`activeManager` 来自 `app.js` 顶层词法作用域，不等价于 `window.data` |
| 基础工具 | `api()`、`write()`、`esc()`、`money()`、`dateKey()`、`displayDate()`、`person()`、`toast()`、`canEdit()` |
| 旧有卡片 | `calendarCard()`、`financeCard()`、`tasksCard()`、`shoppingCard()`、`travelCard()` 保持原有入口 |
| 列表编辑 | 工作台使用 `listRow(kind,item,true)`；完成与保存后由共享刷新重绘列表，编辑器仍留在 `#dialog` |
| 日程 | `CalendarViews.helpers`、`currentMode()`、`setMode()`、`openManager()` |
| 旅行 | `window.JourneyUI.open(tripOrJourneyId?)`，页面按钮在运行时检测模块存在 |
| 财务 | `window.FinanceHub.open(tab?)`，账单与投资入口分别传 `ledger` / `investments`；个人基线继续使用 `FinanceBaseline.openPrivate()` |
| 同步问题中心 | `window.SyncHealth.open()`；`data-sync-health-open` 入口由模块监听。纯 `summaryMarkup(health, options)`/`summaryText(health)` 提供共享文案；`refreshIndicators()` 仅从 data.sync.health 局部刷新，不发 API；私有弹窗每次核对 /me |
| 投资持仓导入 | `window.InvestmentImport.open()`；投资页的 `data-investment-import-open` 按钮由独立模块监听；模板、预览和确认只服务于当前成员，不纳入共享搜索 |
| 财务来源（02:33 发布） | `window.FinanceSourceUI.open()`；`FinanceBaseline.openPrivate()` 的 `data-finance-source-open` 按钮由独立模块监听；只为本人打开，不使用共享 data 保存候选 |
| 旅行 v2（02:33 发布） | `JourneyUI` 先检查服务端支持版本，保留 v1 显式升级入口；三方冲突选择后重新预览，旧服务器不支持时保留草稿并阻止 v2 提交 |
| 日历时间核对（02:33 发布） | `CalendarPublish.open(journeyId)` 展示 reviewRequired；`data-cp="review-preview"`／`review-confirm` 进入独立核对，不允许普通恢复／重试绕过 |
| 助理 | `window.HomeAssistant.open()`；行动台复用已有共享 API 和原编辑器；可选模型仍需成员明确勾选，不由行动台自动调用 |
| 家庭空间 | `window.HouseholdSpaces.open()` / `redeem()`；未登录页面由家庭空间模块监听专用属性 |
| 待办发布 | `window.TaskPublish`；`data-task-publish-open="1"` 入口由 `task-publish.js` 监听，发布前由模块预览确认 |
| 数据导出 | `window.DataPortability.open()`；`data-portability-open` 入口由 `data-portability.js` 监听，默认不附带共同记录 |

对外导出：

```javascript
ProductShell.navigate('shopping');
ProductShell.openPreferences();
await ProductShell.openLayout();
await ProductShell.refreshLayout(true);
const homeLayout = ProductShell.getLayout();
ProductShell.openSearch();
await ProductShell.refreshPreferences(true);
ProductShell.refresh();
const currentRoute = ProductShell.getRoute();
const appearance = ProductShell.getPreferences();
```

`refresh()` 会重建主区域，不应由业务模块拿来代替服务端状态刷新。编辑草稿必须留在业务模块所属的弹窗内，不要放进会定时重建的 `.ps-page`。

新增模块缺失时应显式降级或显示暂不可用，不模拟一次成功写入。产品外壳没有单独的登录令牌、账户列表缓存或独立后台写入队列。

### 5.1 本轮新增的真实操作入口与草稿边界

财务入口为“家庭财务 → 我的财务基线 → 更新财务来源”，按钮实际文字是“更新财务来源”，弹窗标题是“更新我的财务来源”。选择 JSON 后点击“预览来源更新”，模块才读取文件并请求 status／preview；预览展示来源版本、余额记录日期、新增／更新／保留数量、家庭可见小计和可展开的本人明细。勾选“我已核对来源日期、变化和共享小计”后，“确认更新基线”才可用。

来源 UI 的文件选择上限为 2,000,000 字节；后端规范化候选上限为 1,950,000 字节，HTTP 请求上限 3,000,000 字节，三者不能混为同一个限制。503 保留候选与确认选项；真实 409 保留文件、使旧预览失效，要求“重新预览”及再次确认。成功获得持久回执后清除候选；若随后共享页面刷新失败，会区分“保存已成功”和“页面刷新失败”。关闭弹窗、切换成员／家庭或返回资产时丢弃当前内存草稿；不写 localStorage、不后台上传，演示／TV 不进入此流程。完整边界见 [来源桥接](FINANCE-SOURCE-BRIDGE.md)。

旅行 v2 仍从旅行工作台进入，增加 flight/stay/activity/legacy_day 表单。当地时间与时区不能由家庭概览时间反推；住宿退房日、日期活动排他结束日与未知入住时刻分别保留。预览先展示 DST 选择、迁期影响、保留字段及两边同时修改的冲突；选择当前日程或计划后必须重新预览。已订／固定事项、取消标记及稳定关联 ID 不因普通保存丢失，能力检测失败、503 或 409 都保留草稿。字段语义见 [旅行 v2](TRAVEL-DETAILS-PLAN.md)。

旅行时间类型、时区语义或取消状态改变后，云日历发布区显示“旅行时间变化 · 待核对”，提供“核对旅行时间变化”。弹窗分别展示“新的旅行日程”“云端当前内容”，并可展开此前等待发布的内容。用户可选择“保留云端并停止同步”，或“确认变化并恢复发布”；后者只表示重新排队，worker 成功读回后才显示已发布。暂停状态保留 reviewRequired，普通恢复按钮不能绕过核对。

文件所有权建议：工作台负责人只持有产品外壳；财务来源负责人持有 finance-source-ui 与基线入口；旅行负责人持有 JourneyUI；云发布负责人持有 CalendarPublish。涉及 `static/index.html`、`app.js`、实体守卫或第三方适配器时向集成人交付接口，不并行改同一文件。完整分工见 [HANDOFF](HANDOFF.md)。

### 5.2 已发布：“本周待处理”操作与接缝

入口为“家庭助理 → 告诉助理，今天想一起完成什么…”或首页“和家庭助理聊聊”。顶部类别按钮将焦点移动到待办、日程协调、采购金额、旅行准备、公共资金或继续规划区域，手机无需逐屏滚动寻找入口。近期范围使用已有 brief 的今天至七天后，并包含逾期待办；最多 20 项待办、12 组冲突、8 项采购待补、5 趟未结束旅行，不代表完整自然周或全部来源。

本地待办可按原 ID 和 revision 标记完成；普通冲突日程使用 `editItem()`，采购进入 `ShoppingUI.openEditor()`，旅行或 v2 事件进入 `JourneyUI.open(tripOrJourneyId)`，公共资金调用原 `financeForm()`。同步记录在行动台只提供原记录详情；这里不直接修改上游、重新创建替代事项或新增云发布授权。已有明确授权的后台发布仍遵循原队列规则。

离开行动台时保留当前页面内存中的规划文字、已选草案和已提交结果。原编辑器保存或取消后，返回行动台重新核对 `/api/me` 并读取共享快照，区分已更新、未保存变化与读回失败。未保存的字段、图片新增/移除均会阻止快捷返回；上传或保存中须等待。409 不覆盖新版本，503 不自动重试；完成状态已提交而读回失败时，禁用重复完成按钮直到刷新确认。搜索结果及本次创建结果也按原 ID 打开。

`HomeAssistant` 的快照来自 `/api/assistant/brief` 和 `/api/state`，不请求个人财务、私有账本或投资接口。每次打开建立独立上下文对象；旧请求只处理捕获的对象，不能清除新成员或新家庭上下文。重新进入和从编辑器返回时，身份确认前仅显示加载占位；确认失败不渲染缓存。上下文不写 localStorage，浏览器刷新/关页后不恢复；TV 不提供此操作入口，演示只显示虚构说明且不请求家庭记录。

该增量沿用既有 JS/CSS 引用及 `HomeAssistant.open()`，不改变 HTML 加载顺序或增加 API/数据库/模型依赖。依赖 `#dialog` 与原表单结构；购物图片保护读取 `#shopping-photo-list img` 的引用快照，因为照片数组由 `ShoppingUI` 内部维护。后续编辑器修改 DOM、照片状态或关闭行为时必须同时回归这些接缝，不能只运行 JS 语法检查。

<a id="53-投资文件导入与回读独立候选尚未部署"></a>

### 5.3 投资文件导入与回读

实际入口是“家庭财务 → 账单与投资 → 投资账户 → 导入 / 更新持仓”。新模块复用 `#dialog`、`openModal()`、`api()` 与成员状态，没有第二份家庭数据或独立登录令牌。完整用户操作见 [使用手册 6.2](USER-GUIDE.md#62-投资持仓整理表导入更新与导出)，接口和文件契约见 [投资导入说明](INVESTMENT-IMPORT.md)。

流程为来源名称和文件 → XLSX 留空时发现并选择工作表 → 新增／更新／不变差异 → 本人勾选并确认 → 成功页 → 返回投资账户重新读取 `/api/finance-hub/overview`。CSV 不需要选表；表名列表不是有效持仓预览，不能直接确认。核对页对比当前与文件中的机构、资产类型、数量、币种、成本、估值和日期。缺少的行保留原持仓；预览和模板下载都不更新投资记录。

“下载虚构示例”只下载模板；填写来源后“导出现有持仓”只导出该来源及尚未归属来源的本人记录，排除其他来源。编号与文本保护列用于明确关联和安全回导；浏览器不自行推断银行账户身份。原始附件不持久保存，持仓和导出内容不进入共享 `data`、电视或伴侣界面，不修改公共荷包或共享资产基线；银行／券商自动连接、实时行情、汇率换算均未接入。

异步操作捕获原成员、家庭、CSRF、流程对象、原视图节点与请求代次；输入或工作表改变使旧请求失效，显示差异和确认结果前再次核对 `/api/me`，包括仅 Cookie 已换成员的情况。“重新预览”先失效旧凭据和勾选，不能在等待时确认旧差异。确认网络失败保留原凭据供同一请求重试；409 要求重新预览。已经发出的写入不会因关窗撤销，迟到成功或错误不接管新窗口；返回账户调用原财务模块的鉴权读取，不直接重绘旧缓存。

联合开发时，`static/investment-import.js/.css` 属于独立导入组件；`static/finance-hub.js` 的入口和返回读取、`static/index.html` 的加载、后端 `investment_import.py` 与发布白名单由集成人协调。不能把旧财务脚本整文件覆盖回来而丢失既有对账、模型来源身份或每按钮请求保护。专项入口为 [browser_investment_import_check.py](../tests/browser_investment_import_check.py)，只用临时数据和本机浏览器；最终冻结后的结果由集成人登记，不以本节替代上线或真实银行验收。

## 6. 真实浏览器验证

验证使用临时数据库、虚构成员密码与虚构账单，在随机本机端口启动实际 Flask 应用，由 Microsoft Edge / Playwright 操作真实页面。没有连接生产账户、读取真实财务或调用实际第三方写接口。

```powershell
.\.venv\Scripts\python.exe -X utf8 tests/browser_product_shell_check.py
.\.venv\Scripts\python.exe -X utf8 tests/browser_product_workflows_check.py
```

两个脚本显式使用 Windows Edge 路径；其他平台需调整浏览器启动配置。等待使用 DOM 断言和实际 API 回读，不使用受 CSP 限制的 `wait_for_function`。测试截图和 JSON 位于本机 `test-results/`，不进入生产镜像。

2026-09-14 临时环境历史验收证据：

| 验收 | 已观察到的结果 |
| --- | --- |
| 页面适配 | 1440×1100、1920×1080、820×1180、390×844、360×800，各覆盖 10 个工作台，共 50 个页面无全局横向溢出 |
| 电视布局 | 1280×720、1920×1080、3840×2160，各覆盖今日/本周/前后 3 天，共 9 个组合；保留五张卡片、无全局溢出或卡片内容溢出 |
| TV 偏好隔离 | 浏览器监听到成员偏好 API 请求为 0 |
| 主题与密度 | 三主题均通过真实卡片渲染；密度切换生效；浅色卡片、弹窗和采购提示可读 |
| 偏好跨设备 | 真正 `PUT` 保存后，全新手机浏览器会话读取到相同主题、密度和默认周视图 |
| 保存失败 | 模拟偏好 `PUT` 返回 503，错误显示于弹窗，已选主题保留，未报告成功 |
| 导航 | 手机“更多”可打开各页面；浏览器返回恢复前一页，刷新恢复地址片段；搜索定位记录、清单筛选可用 |
| 待办 | 实际登录后创建待办，勾选完成，已完成筛选中能读回该记录 |
| 助理方案 | 输入两项待办，预览阶段任务数不变；取消第二项后仅创建第一项；禁用按钮重复点击不新增；重放相同计划确认请求仍只保留一项 |
| 财务导入 | 上传虚构 CSV，预览阶段账本为 0 条；确认后新增 1 条、1234 分；通过 UI 核对分类后 `checkedAt` 有值 |
| 投资录入 | 通过 UI 创建虚构 USD 资产，成本 100000 分、估值 120000 分，账面差额为 20000 分，API 回读一致 |
| 成员隔离 | 成员二的真实 API 和财务弹窗看不到成员一的虚构账单与投资；共享状态和汇总不含虚构私有名称 |
| 演示副作用 | 助理与旅行演示未产生任何 `/api/` 写请求 |
| 页面错误 | 两个浏览器检查均为 0 个 JavaScript 页面错误 |

JSON 证据文件为 `test-results/product-shell-verification.json` 和 `test-results/product-workflows-verification.json`。重点截图包含 `product-desktop-first-screen.png`、`product-phone-first-screen.png`、`product-theme-light.png`、`product-theme-ocean.png`、`product-tv.png`、`product-finance-preview-phone.png` 和 `product-investments-desktop.png`。

这些结果证明的是上述合成数据、本机应用与浏览器范围，不代替真机电视验收、真实 Microsoft/Google 账户授权回写，或真实金融平台账单覆盖验证。测试脚本记录的 CSV 流程也不自动证明之后新增文件格式已经验收。

### 6.1 02:33 新增功能的临时浏览器证据

| 脚本与结果文件 | 已观察到的行为 | 边界 |
| --- | --- | --- |
| `tests/browser_finance_source_check.py`；`test-results/finance-source-browser-verification.json` | 真实私有入口、文件预览不写基线、日期及小计、503 保留、第二设备制造 CAS 冲突、重预览、重复候选不增版本、成员／TV 隔离；360/390/1440 px | 合成候选，pageErrors／externalRequests 为空，productionWrites 为 0 |
| `tests/browser_journey_details_check.py`；`test-results/journey-details-browser-verification.json` | 跨日期变更线航班、住宿晚数、活动／旧日期段、DST 不存在／重复时间、迁期选择、独立事件保护、显式冲突、v1 升级、旧服务能力拒绝与演示无写入 | 虚构行程与临时 Flask，completed 为 true；pageErrors／externalRequests 为空，productionWrites 为 0 |
| `tests/browser_journey_timing_review_check.py`；`test-results/journey-timing-review-browser-verification.json` | Microsoft／Google 两种模拟服务商均验证语义待核对可见、预览只读远端、暂停不绕过、显式确认和原远端 ID 更新；360/390/1440 px | 双平台 passed 为 true；没有真实云写入、外站请求或页面错误 |

以上浏览器证据来自临时环境，不等于正式域名或真实账号验收。该代码另通过 Linux 546 passed、1 skipped 并于 02:33 发布；可以按 [开发指南](DEVELOPMENT.md) 在隔离环境复核，当前状态见 [HANDOFF](HANDOFF.md)。

### 6.2 行动台的 21 项检查

`tests/browser_assistant_actions_check.py` 已在独立候选的真实临时 Flask、SQLite 与 Edge 中通过 **21 项**合成检查。三处独立审查问题修复后重新执行，结果已取代修复前的 18 项记录；并入主目录后再次完成 **21 场景通过**，JS 语法检查通过。主目录集成全量为 **551 passed / 230.87s**，证据为 `test-results/actions-schema-suite.xml`；Linux 隔离镜像后续 550 passed / 1 skipped，并于 03:11:08 完成发布和容器内部检查；公网浏览器和真实云写仍按交接记录单列。

| 范围 | 已观察到的结果 |
| --- | --- |
| 五类入口与原记录 | 本地事项按原 ID 打开；同步事项只读；普通冲突日程原编辑器与 v2 精确旅行入口可用；搜索与创建结果精确定位 |
| 采购与资金 | 原采购补预算后读回旅行采购预算，公共余额不变；公共资金另行手工确认，未写账本或银行 |
| 完成与创建 | 同一待办双击仅一次 PATCH、原记录完成；两项草案只勾一项，确认后仅创建一项且重复按钮不再创建 |
| 失败与版本 | 409 保留另一设备修改；503 保留文字/勾选；写入成功但读回失败时不报告完成且阻止重复提交；请求中关闭弹窗不会重开 |
| 身份竞态与缓存 | 真实 A→B 登录切换后，延迟返回的 A `/me` 不清除 B 草稿；从原事项返回时，身份请求挂起及随后 503 的两阶段均无旧缓存内容、无写入 |
| 图片草稿 | 实际删除图片、实际上传且文件输入清空、上传请求挂起时均阻止误返回；保存后 SQLite `photoIds` 与新增/删除结果一致 |
| 权限与隐私 | 两成员上下文隔离、真实第二家庭和原 ID 隔离；匿名 401、已配对 TV 403；演示无 API 请求，未读取个人财务接口 |
| 适配与错误 | 1440 px 桌面、390/360 px 手机无横向溢出，类别跳转移动焦点，浅色/海岸继承现有主题；外站请求、私有财务接口请求、JS 页面错误均为 0 |

报告为 `test-results/assistant-actions-verification.json`；截图包括 `assistant-actions-desktop.png`、`assistant-actions-phone.png`、`assistant-actions-light-phone.png`、`assistant-actions-photo-removal-dirty-phone.png` 和 `assistant-actions-return-verification-failure-phone.png`。原 `browser_product_workflows_check.py` 也在修复后的独立候选复跑通过。所有数据、图片和成员均为合成，服务仅运行在本机随机端口；这些结果不代表新候选已部署、正式域名 UI 通过或真实云账号写入通过。

```powershell
.\.venv\Scripts\python.exe -X utf8 tests/browser_assistant_actions_check.py
```

## 7. 后续 UI 优化边界

当前还没有拖动式布局设计器、通知中心、离线编辑、PWA 安装、用户自定义主题文件、模块市场或完整辅助技术人工验收。旅行、财务和助理的深入操作主要在宽弹窗内完成；若未来改为原生子页面，需要先拆除各业务模块对 `#dialog` 及 `openModal()` 的依赖，并保持异步草稿和失败重试行为。

下一步新增功能应通过真实工作台入口连接，不重复建立第二份共享状态；新增财务或账户搜索应先明确服务端私有范围，不能仅凭前端隐藏字段判断安全。


### 2026-09-15 首页布局补充验收

`tests/test_dashboard_layout.py` 的 17 项测试通过，覆盖版本冲突/并发首次保存、输入白名单、未来键保留、本人/跨家庭隔离、TV/CSRF/同源限制与恢复默认。

`tests/browser_dashboard_layout_check.py` 在真实临时 Flask + Edge 下通过：桌面按钮与键盘排序、隐藏后的实际 GET 读回、全新手机读取同成员布局、另一成员默认布局不变、四种宽度无横向溢出、最后一张不可隐藏、恢复默认保存前不写、503 草稿保留、真实 409 后比较/保留草稿/再次保存、前台同步、隐藏页面仍能打开、演示零写入，以及 720p/1080p/4K TV 固定五卡和零布局 API 请求。JavaScript 页面错误为 0。

证据是 `test-results/dashboard-layout-verification.json`；截图 `layout-editor-desktop.png`、`layout-editor-phone.png`、`layout-custom-desktop.png`。这些记录仅证明临时环境行为；该功能现已随 01:10:44 版本部署，公网浏览器验收状态见下文。

设置页还暴露 `data-portability-open` 的“导出我的数据”（`DataPortability` 模块负责）；共同待办工具条为成员提供 `data-task-publish-open="1"` 的“同步本地待办”（任务发布模块负责）。产品外壳只提供入口，不自行生成导出文件或写入云端。


### 2026-09-15 财务对账与数据导出独立验收

- `tests/browser_finance_reconciliation_check.py`：通过正式导入 API 在临时库写入四条虚构记录（订单 100、付款 100、另一来源重复付款 100、退款 30 元），实际点击核对候选、预览、确认三类关系。预览不写，确认可幂等重放；确认后净支出 70 元，订单 100 元独立展示，购物分类预算剩余 30 元。原生确认撤销重复关系后净支出恢复 170 元；四条原始 JSON 和金额不变，成员二看不到记录或候选。证据 `test-results/finance-reconciliation-browser-verification.json`，0 页面错误、0 生产写入。
- `tests/test_data_portability.py`：5 项既有测试通过，验证成员/家庭/TV 边界、CSRF/同源、501 行完整导出、CSV 安全转义/精确金额、未知估值、体积限制及忙时拒绝。
- `tests/browser_data_portability_check.py`：设置页实际打开导出摘要，默认不勾选共同数据；真实下载个人 ZIP 和附带共同记录的 ZIP，两份均包含五个文件，manifest 中四份内容的字节数与 SHA-256 均匹配。数据保留本人账单原始整数分、估值 null、布局、基线与本人连接标签，不含伴侣私人记录、密码散列、token、client id、subject 或内部同步元数据。503 时选择保留、无下载且允许重试；演示/TV 无入口或请求。证据 `test-results/data-portability-browser-verification.json`，0 页面错误、0 生产写入。

导出截图为 `data-portability-phone.png`；对账截图为 `finance-reconciliation-candidates-phone.png`、`finance-reconciliation-refund-preview-phone.png`、`finance-reconciliation-net70-phone.png`。下载 ZIP 仅在临时目录中用于解包验证，测试结束删除；它不是恢复生产数据库的备份格式。

### 2026-09-15 01:10:44 发布与本次验收边界

四项增量已部署，Linux 测试 380 项通过、1 项跳过。服务器内部检查确认 28 张家庭业务表、原数据保留、六个来源新同步成功；通过容器内部 HTTP 校验 27 个静态文件的哈希，并确认 10 个受保护 GET API 匿名返回 401。这些是服务器内部与同步读取证据，不证明成员操作或真实云端发布写入已经验收。

公网浏览器检查脚本为 [workflows_live_check.py](../tests/workflows_live_check.py)，复用 [platform_live_check.py](../tests/platform_live_check.py)。计划覆盖入口引用的 23 个静态资源、10 个匿名受保护 API（6 个既有和 4 个新增）、桌面/手机各 10 个工作台、电视演示及演示首页布局。脚本阻断非 GET/HEAD、OAuth、配对、空间切换与外站请求，使用无登录凭据的新浏览器上下文。

本次实际结果是 `browser_environment_blocked`：本机 Microsoft Defender SmartScreen 显示“组织已阻止此内容”，应用登录页未加载。上述 23 资源、10 API 与 UI 场景均未进入执行阶段；不能以服务器内部 27 文件检查替代公网浏览器结果，也不能把拦截页的 JavaScript 错误归因于家庭应用。

证据为 `test-results/platform-live-browser-verification.json`、`test-results/workflows-live-browser-verification.json`，以及 `test-results/workflows-live-organization-block.png`。没有关闭组织策略、更换浏览器或访问路线来绕过阻断，没有生产写请求、OAuth/配对操作或凭据读取。真实 Microsoft / Google 账号发布写入仍需本人授权后验收。

## 05:47:43 导入入口说明

旅行表单导入区新增 v1/v2 JSON 下载与格式说明；两个普通同源 download 链接不触发导入或重置草稿。财务多金额列先显示列位置／原名称，选择后重新预览，确认沿用原签名流程。新增两个静态示例文件由 Docker COPY static 与源码白名单收录；没有新增 index 或后端路由接缝。本地专项与服务器内部资产验证见 [VALIDATION](VALIDATION.md)，公网和真实账户边界仍保留。

本次对账界面增量绑定原页面和原成员／家庭／CSRF，读取、候选、预览、确认及撤销的迟到结果不接管后来页面；已发送写入不能由关页取消。独立专项为 `tests/browser_finance_reconciliation_guard_check.py`。本修复不声称覆盖全部财务缓存生命周期。

XLSX 工作表发现与助理旅行简报已于 2026-09-15 06:50:21 合入并发布，详情见 [验收记录](VALIDATION.md)。

## 06:50:21 工作表与旅行简报交互

财务 XLSX 名称留空先发现，选表使旧金额、预览行和令牌失效；无效表保留名单与重试，包安全错误仍直接拒绝。助理文字通过三步简报带入原可编辑旅行向导，重新整理与继续保留明确分开；旅行入口仍优先处理明确清单命令。身份、家庭、CSRF、输入快照与请求代次守卫保留；没有自动模型、真实日历发布或直接保存旅行。

| 浏览器专项 | 范围 | 本轮通过场景 |
|---|---|---|
| `tests/browser_journey_import_guard_check.py` | 旅行文件导入保护 | 31 |
| `tests/browser_journey_draft_guard_check.py` | 相邻草稿与提交返回 | 32 |
| `tests/browser_journey_confirm_guard_check.py` | 重新预览确认 | 5 |
| `tests/browser_journey_details_check.py` | 旅行 v2 时间细项 | 10 |
| `tests/browser_journey_return_budget_check.py` | 旅行返回与预算 | 23 |
| `tests/browser_journey_examples_check.py` | 旅行示例下载 | 8 |
| `tests/browser_finance_amount_columns_check.py` | 账单金额列选择 | 13 |
| `tests/browser_financial_files_check.py` | 现有文件导入 | 5 |
| `tests/browser_finance_reconciliation_check.py` | 现有关联与对账 | 6 |
| `tests/browser_finance_reconciliation_guard_check.py` | 对账迟到响应与身份保护 | 57 |
| `tests/browser_financial_sheet_discovery_check.py` | XLSX 名称发现与选表 | 11 |
| `tests/browser_assistant_journey_brief_check.py` | 助理简报到旅行向导 | 25 |
| `tests/browser_assistant_actions_check.py` | 助理原事项处理与返回 | 21 |

本轮全部组合浏览器重新执行；证据与网络范围见 [VALIDATION](VALIDATION.md)，操作见 [使用手册 5.5](USER-GUIDE.md#55-用文字整理多国多城旅行) 和 [6.1](USER-GUIDE.md#61-xlsx-首表是说明页时先选账单工作表)。

## 采购实付与原页面返回

`shopping-settlement.js/.css` 在同步状态模块之后、工作台外壳之前加载；入口调用 `ShoppingSettlement.open({shoppingId?,transactionId?,linkId?})`。采购负责人不是隐私权限，服务端只允许本人关系和明确共享的 `actual/done`。订单没有已核对付款时通过 `FinanceHub.openReconciliation` 进入原对账，完成后显式返回同一采购。输入修改使旧预览失效；每个异步阶段绑定原节点、成员、家庭、CSRF 与请求代次。成功确认和历史回执都重新读取当前 context/state；关窗不能取消已经发送的写入。

本批新界面 61 项检查、三主题各 360/768/1440 共 9 张截图；原对账另有 57 项，工作台另有 59 条页面/视口记录。使用临时 Flask/SQLite 和虚构账单，不是实体电视、真实金融账号或公网浏览器验收。详见 [VALIDATION](VALIDATION.md)。

## 家庭例行计划界面与返回

实现为 [household-routines.js](../static/household-routines.js)及[局部样式](../static/household-routines.css)，公开 `HouseholdRoutines.open({planId?})`、`refresh()`、`notifyStateChanged()`。待办、采购、助理三入口只向有效成员显示，TV／演示不访问管理 API；模块自身也验证身份，不能仅依赖按钮隐藏。

列表按页面筛选 active／paused／archived；规则编辑、未来三期预览、确认与历史在同一工作区完成。共享状态 revision 变化只提示重新核对，保留当前草稿；所有读取、写入和读回绑定原节点、请求代次、成员／家庭／CSRF。日期或版本 409 后重新预览，不自动重发；提交后结果不确定保留原预览令牌，不能靠关窗取消已经发出的写入。

详情可打开精确的原事项；从采购／任务编辑器返回时重新读取身份和原计划。发布本期任务进入现有 TaskPublish 页，仅携本期 entity ID，仍需目标选择、授权、预览和确认；后续期次无自动发布。与助理返回条同时存在时须保留原调用链，不能用全局查找把旧响应画到新弹窗。

助理按原 plan ID 打开缺失／容量／日期异常和近期计划，最多八条且计数不截断；不读私人财务。模板更新只影响未来、跳过保留旧项、缺失不复活、采购新期金额和照片为空的文字必须与 [ROUTINES](ROUTINES.md) 一致。

专项入口：[browser_household_routines_check.py](../tests/browser_household_routines_check.py)。本轮新例行 77、助理 21 项，功能合计 98；工作台另 59 条页面／视口，测试仅合成数据和回环地址。实体设备、公网和真实新增云写另行验收，见 [VALIDATION](VALIDATION.md)。
