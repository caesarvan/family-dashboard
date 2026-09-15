# 旅行执行与发布进度

已于 2026-09-15 16:25:03（北京时间）发布；镜像与完整验证见 [README](../README.md) 和 [VALIDATION](VALIDATION.md)。

旅行详情把行程、负责人、准备事项、采购和云端发布放在同一入口。已打开的详情定期读取最新状态，完成任务后无需关闭再打开；正在编辑的计划或事项仍保留自己的草稿。

## 使用方式

1. 从旅行列表打开一份已保存的计划，查看准备与采购进度。
2. 按全部、本人、伴侣或共同筛选负责人。筛选只改变显示，不修改任务负责人或同步账户。
3. 查看本地完成状态和云端连接状态。尚未连接、等待同步、已同步、暂停或需要处理分别显示；本地勾选并不证明云端已成功更新。
4. 从原任务进入编辑或清单连接，从日历区域进入旅行日历发布。选择来源、预览、确认、授权和冲突处理沿用原流程。
5. 读取失败时保留上次结果并提示尚未更新，可手动刷新。关闭详情、进入编辑或切换成员／家庭后，旧读取结果不接管新页面。

## 数据与权限

复用以下现有接口，不增加路由或数据表：

| 读取 | 用途 | 可见范围 |
|---|---|---|
| `GET /api/journeys/<id>` | 当前旅行、准备、采购、日程和 revision | 本户成员的共享计划 |
| `GET /api/task-publish/state?journeyId=<id>` | 已关联任务的实际发布状态 | 沿用待办发布接口的成员可见性与 canManage |
| `GET /api/calendar-publish/journeys/<id>` | 当前成员的旅行日历发布状态 | 本人授权和发布记录 |
| `GET /api/me` | 原成员、家庭、认证代次和 CSRF 核验 | 当前登录会话 |

两个发布状态接口的每条 publication 增加 `localChangesPending`：`true` 表示本地受同步管理的字段与上次确认内容不同，`false` 表示相同，`null` 表示缺少已确认基线、缺少本地实体或无法比较。该字段不改变原 status、不发送云请求，也不返回内部比较基线。未运行 worker 时，status 仍可能为 published 而 localChangesPending 已为 true；这时显示等待同步，不能将上次成功当作当前更新成功。原接口的已删除项目筛选与字段校验错误继续保留。

`journey.calendar.cloud` 的固定默认值不能作为实际发布状态。完成进度来自原实体；云端状态来自持久化发布记录。没有返回结果或读取失败时不推断“没有连接”或“已同步”。周期读取仅查看本地数据库记录，不直接轮询第三方服务商；worker 继续按原调度同步。

任务负责人保持原语义。发布到某个成员授权的清单不等于在 Microsoft 或 Google 中指派给该负责人。日历区域仅描述本人的发布情况，不能推断伴侣没有发布，也不能展示其账户或目标日历。

## 开发接缝

界面实现位于 `static/journey-ui.js` 和 `static/journey-ui.css`。后端接缝为 `task_publish.py`、`calendar_publish.py`：在同一只读事务快照中比较原实体和已确认内容，不修改队列或触发服务商请求。详情刷新绑定原旅行、原节点、请求代次、成员、家庭、认证版本及 CSRF；页面不可见时暂停周期读取。任务、采购和日历编辑继续使用原模块及返回桥。冲突后读取最新版本，不自动重发旧 PATCH 或覆盖远端内容。

打开、关闭和编辑之间的异步守卫保护当前界面；已经发出的写操作仍可能被服务器接受。网络失败不等于写入取消，不能通过换一个幂等标识盲目重试。

接口细节见 [旅行平台 API](PLATFORM-API.md)、[待办发布](TASK-PUBLISH.md)、[日历发布](CALENDAR-PUBLISH.md) 与 [连接返回](CONNECTION-RETURN.md)。真实云账户、OAuth 和实体设备验收仍按 [VALIDATION](VALIDATION.md) 单列；本地模拟服务商不是实际云写成功证据。

## 本地验收入口

在隔离开发环境运行，使用虚构数据；后端 `pytest` 不会自动执行下面的浏览器脚本。

```sh
python -m pytest -q tests/test_publication_local_changes.py tests/test_order_source_headers.py
python tests/browser_journey_execution_check.py
```

浏览器脚本需 Playwright 与 Microsoft Edge，启动真实临时 Flask/SQLite，只允许回环请求，并使用模拟 Microsoft/Google 提供者。最终执行 53 项通过；另已复跑原旅行、返回预算、导入、草稿、确认及两个发布模块的 8 组浏览器检查。完整后端结果见 VALIDATION，各轮历史失败与最终成功分别保留，不能累加。

`editLinked` 只在原身份和详情仍匹配时发布暂存的 `/api/state` 读取，不改全局 `app.refresh`。有限次身份读取不能让跨标签 Cookie 切换原子化；关闭页面也不能撤回服务器已经接受的写入。
