# 本地待办连接 Microsoft To Do / Google Tasks

发布状态：已随 2026-09-15 01:10:44（北京时间）版本部署，app / sync 镜像 `sha256:2cdb7a8df93574f3399d80ee7d1d1a6ff3bd915ae8e566b16f1f2a83e4268f08`。实现已上线，不表示用户真实 Microsoft / Google 新增云端写入已验收；证据范围见文末与 [VALIDATION](VALIDATION.md)。

旅行准备事项、家庭助理生成的待办和手动本地待办，均可通过「连接待办清单」勾选、预览并确认连接到云端清单。确认的是具体任务及持续同步关系；系统不会扫描并自动上传之前的所有本地待办。

## 使用与权限

1. 在「设置 → 账户与自动同步」绑定 Microsoft 或 Google，选中待办清单。
2. 从待办工作台、旅行详情的「连接待办清单」，或家庭助理应用建议后的入口进入。
3. 选择本人授权的清单，或账户拥有者明确设置的「家庭主清单」。主清单可以是 Microsoft To Do 或 Google Tasks；家庭同时只有一个主清单。
4. 手动勾选本次要同步的项目，核对标题、负责人、截止日期、备注、完成状态及目标清单，再确认。
5. 在同步进度查看结果。云端勾选完成或恢复未完成会回到同一个本地任务；云端标题、日期、备注变化先暂停，由成员比较并选择采用云端或以本地更新云端。

绑定清单属于家庭共同任务数据，但只有本人来源或明确开放的主清单可成为发布目标。非主清单不会作为另一成员的可选目标。发布确认者及授权账户拥有者可以暂停、恢复和处理冲突；每次操作仍要求成员身份、CSRF 和同源检查。电视不能读取发布管理接口或提交确认。

仅使用已有 `Tasks.ReadWrite`（Microsoft）或 `https://www.googleapis.com/auth/tasks`（Google）权限，不额外申请日历写权限。缺失权限时显示需重新授权并保留队列，由账户拥有者重新绑定后重试。授权刷新后再次验证 scope。

Google Tasks 的「家庭主清单」是允许家庭看板双方操作该授权账户清单的服务器授权，**不代表 Google 原生清单变成可共享清单**。本地负责人、旅行关联、工作流 key 和实体 ID 保留在 SQLite；不向云端添加负责人，不伪称云端原生指派。出站白名单仅标题、日期、备注、完成状态及恢复关联标识。

## 持久同步与失败边界

`task_publications` 一项本地实体只允许一个绑定目标。每户持久随机 namespace 和本地实体 ID 生成稳定发布 ID；重复确认返回同一记录。SQLite 队列持久保存待写快照、首次发送标记、基线、ETag、远端 ID、重试时间及状态。进程级账户文件锁与既有读取、日历发布、token 刷新、断开操作共用，避免同一账户多进程竞争。

创建请求在同一 POST 内将恢复标识附在云端备注末尾，例如 `[家庭看板同步:<发布ID>]`。请保留它。两家 Tasks 创建接口没有在已查官方文档中提供本实现可依赖的客户端幂等创建 ID，因此系统**不会在创建已发出而结果未知时盲目再次 POST**：

- 响应丢失后，完整读取有界分页，包括 Google 已完成、隐藏的任务，按标识定位并回读原任务。
- 找到原任务且内容一致，即恢复原远端 ID；先于恢复运行的来源轮询也会抑制该任务的云端镜像，避免副本。
- 未找到时只继续核对；多次失败进入 `needs_review`。「再次核对」仍仅查找，不会重新创建。服务器可能在发出前崩溃，这种保守方式可能留下一项实际上未创建的待办，需要人工核对处理；不以重复创建换取自动成功。
- 只有 POST 本身收到可证明拒绝的 400/401/403/404/429 响应，才允许修复权限/来源后再次尝试创建。POST 成功后的回读失败仍属于结果不明。

更新使用 GET、捕获的 ETag 和 `If-Match` PATCH，再回读。丢失更新响应时比较持久待写内容与远端内容恢复；远端再次变化则暂停。云端只改变完成状态且本地尚未改变时自动回流。云端标题/日期/备注变化、双边同时修改和缺少可用 ETag 都不会静默覆盖。采用云端内容会更新本地白名单字段并保留所有本地关联；以本地更新云端需要新的签名冲突预览，确认及实际 PATCH 两阶段均检查版本。

删除本地任务不删除云端，也不在下次轮询复活为镜像。远端删除、来源取消选择、账户断开均不删除工作流任务。移动云端任务到另一清单可能改变 ID（Microsoft 文档明确指出），此时按远端不可用处理，不擅自跨清单跟踪或重新创建。暂停不会取消已完成的写入，也不会删除任一端。

取消来源后重新选择同一个授权账户和清单，可以在发布窗口再次勾选原任务，预览会明确标注「重新连接原清单」。确认依据持久保存的 provider/client/subject/list 身份摘要核对原目标，更新来源 ID，保留原发布 ID、远端 ID、首次创建标志与待写快照；重复确认幂等。不同账户或清单不能冒充原目标，伴侣撤回主清单授权后也不能借重连恢复访问。原有冲突、暂停或删除状态仍保留；结果不明的创建继续只查找恢复，不重新 POST。若新来源轮询已生成临时云端镜像，成功重连会移除镜像并继续使用原本地任务。

远端完成状态回流在同一个 `BEGIN IMMEDIATE` 事务内重新检查本地 revision、条件更新任务及发布基线；并发本地编辑不会被读取到的旧整份任务覆盖。

## API

所有路由以 `/api/task-publish` 开头，JSON 格式。所有路由需要成员登录；POST 同时需要 `X-CSRF-Token`。业务错误返回 `{"error":"中文说明"}`。常见状态码：400 输入无效，401 未登录或需重新授权，403 权限/CSRF，404 不可用来源或管理记录，409 版本、来源或绑定冲突。

| 方法 / 路径 | 输入 | 返回及含义 |
| --- | --- | --- |
| GET `/state` | 可选 `journeyId` 或 `entityIds=id1,id2` | `tasks,sources,publications,note,intervalSeconds`；不写云端。无筛选时最多最近 100 项本地任务 |
| POST `/preview` | `{sourceId,entityIds:[...]}`，1–100 个不重复 ID | `tasks,source,previewToken,note`；无队列及 provider HTTP 请求 |
| POST `/confirm` | `{previewToken}` | `queued,publicationIds,needsAuthorization`；一次事务创建队列，仅预览中的项目；15 分钟签名绑定成员、家庭 namespace、来源和实体版本 |
| POST `/publications/{id}/pause` | `{}` | `paused:true`；停止自动同步，两端保留 |
| POST `/publications/{id}/resume` | `{}` | `queued:true`；仅 paused，可恢复后重新核对，仍保留原 pending/ETag |
| POST `/publications/{id}/retry` | `{}` | `queued:true`；仅失败、权限、结果不明或已断开状态；不跳过冲突、不重置首次创建标志 |
| POST `/publications/{id}/conflict-preview` | `{}` | `local,remote,previewToken`；只读远端、捕获两个版本 |
| POST `/publications/{id}/conflict-confirm` | `{previewToken,resolution:"local"或"remote"}` | `queued,adopted`；重新 GET 验证远端后排队条件更新，或采纳到同一实体 |

预览示例：

```json
{"sourceId":"已选择的来源ID","entityIds":["本地待办ID"]}
```

来源只提供清单名称、平台、账户显示名/所属成员、主清单标志、授权是否充足；不返回令牌。发布管理只提供自身状态、关联 ID 与处理权，不泄露 OAuth 凭证。

## 状态

| 状态 | 行为 |
| --- | --- |
| pending / publishing | 已明确确认，等待/正在发送；重启保留 |
| published | 已连接，约 30 秒核对本地与远端；界面约 5 秒刷新状态 |
| retry | 可恢复临时失败，指数退避 |
| uncertain | 创建已发出但结果未核实，只查找原任务 |
| needs_review | 多次临时/不确定失败，需成员再次核对 |
| needs_authorization / permission_denied | 需账户拥有者恢复授权/目标权限后重试 |
| conflict | 内容或版本变化，需比较确认；普通 retry 拒绝 |
| paused | 用户暂停；resume 会重新核对远端 |
| disconnected | 来源或主清单共享授权已撤回；本地保留 |
| remote_deleted / local_deleted | 另一端保留，不自动重新创建或删除 |

## 根模块接入与联合开发

- `app.py`：`register_task_publish(app, db, Problem, body, require_member, audit)`，在账户注册之后执行；每户独立应用/DB 都初始化。
- `sync_worker.py`：每轮调用 `app.extensions['task_publish'].tick()`；使用已有每户调度。先处理发布，再读取来源可减少短暂镜像。
- `cloud_accounts.py`：来源轮询 `observe` 抑制同一已发布实体的镜像；取消来源保留本地任务；Microsoft/Google 均可设主清单。
- `cloud_providers.py`：`find/get/create/update_task_publication` 有界官方 HTTPS transport，复用 token/URL/分页限制；不影响既有 calendar publication methods。
- `static/task-publish.js`：`window.TaskPublish.open({journeyId})`、`open({entityIds:[...]})`、`open()`。委托按钮 `data-task-publish-open="1"`；旅行按钮 `data-journey="cloud-tasks"`。助理必须先成功 apply 取得真实任务 ID，再进入此独立确认流程。
- 部署包含 `task_publish.py`、静态脚本和以上已改模块；无新第三方依赖。表在应用启动时 `CREATE IF NOT EXISTS`，旧队列不迁移、不自动上传旧本地任务。
- 旧手动「直接保存到云端」路径仍使用 `CloudAccounts.task_write`，不等同于这里的本地任务持久发布流程。已是 cloud mirror 的任务不能再经本接口发布。

## 验证证据与未验证项

`tests/test_task_publish.py` 使用临时真实 Flask/SQLite、真实 Provider adapter、模拟 HTTP，覆盖双平台创建/更新、丢响应恢复、幂等重试、云端完成回流、并发本地编辑、冲突采纳、ETag 竞态、暂停/恢复、源断开重连与两端删除、账号/主清单/CSRF/电视/跨户边界及重连时的账户锁身份核对。`tests/browser_task_publish_check.py` 使用真实 Edge 和临时应用验证旅行入口、明确选择/预览确认、发布进度、完成回流、两种冲突处理、同清单重连、手机 390px、缺权限和演示零写入。

执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_task_publish.py tests/test_cloud_accounts.py tests/test_cloud_providers.py tests/test_calendar_publish.py -q
.\.venv\Scripts\python.exe -X utf8 tests/browser_task_publish_check.py
```

浏览器报告：`test-results/task-publish-browser-verification.json`；预览和手机冲突截图：`test-results/task-publish-preview-*.png`、`test-results/task-publish-conflict-phone-*.png`。两平台模拟验收均通过，真实云端写入次数为 0。

本次发布的完整 Linux 测试为 380 passed、1 skipped。27 个静态文件的 HTTP 哈希与含 `/api/task-publish/state` 在内的 10 个匿名受保护 GET 返回 401，只在容器内部验证。正式域名浏览器被 Microsoft Defender SmartScreen 组织策略阻断，状态为 `browser_environment_blocked`，未进入公网应用 UI 验收；上述临时浏览器历史记录仍只证明模拟数据流程，六个既有来源的新读取同步成功也不证明本发布队列已完成真实写入。

**尚未用用户真实 Microsoft/Google 账户执行写入验收。** 模拟 HTTP 成功不证明个人租户的实际权限、配额、ETag 行为、网络环境或 API 最终一致性已验证。生产真实闭环需用户选一项非敏感测试待办并明确确认，再在原 App 勾选完成、核对看板回流。

## 官方接口依据

- [Microsoft 创建 To Do 任务](https://learn.microsoft.com/en-us/graph/api/todotasklist-post-tasks?view=graph-rest-1.0)：委托 Tasks.ReadWrite、POST 路径及任务对象。
- [Microsoft 更新 To Do 任务](https://learn.microsoft.com/en-us/graph/api/todotask-update?view=graph-rest-1.0)：PATCH、HTML body、dueDateTime/status 字段。
- [Google Tasks insert](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks/insert)：创建接口和任务写入 scope。
- [Google Tasks resource](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks)：notes、due（日期编码，不是截止时刻）、status 和 ETag。
- [Google Tasks 性能与条件 PATCH 指南](https://developers.google.com/workspace/tasks/performance)：GET 后使用 ETag/If-Match 更新及 null 清除字段。Microsoft To Do 文档返回 ETag，但方法页未明确保证所有租户条件 PATCH 行为，因此本实现要求有效 ETag、发送 If-Match 并回读；真实租户行为仍待验收。


## 旅行执行页的本地变更状态

本版在现有 GET 状态返回的 publications 中新增 `localChangesPending: boolean | null`。true 表示当前本地受同步管理的字段不同于上次确认基线；false 表示相同；null 表示没有确认基线、实体已缺失或无法比较。不改变原 status，不返回内部基线，不调用服务商或修改队列。仅负责人、旅行关联等非云管理字段变化不会误标为待同步。status=published 是上次处理结果，不能独立证明本地最新修改已到云端。日历仍只返回本人成员的发布项，待办保留原 canManage 和可见性。完整使用与异步守卫见 [旅行执行](JOURNEY-EXECUTION.md)。
