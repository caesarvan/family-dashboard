# 本地待办的前置依赖

状态：本地待办前置事项已于 2026-09-20 06:28:25（北京时间）发布，06:35:47 独立只读审计通过；实际身份、分段验证与未验边界见[集中验收](TASK-DEPENDENCIES-ACCEPTANCE.md#task-dependencies-release)。下文保留本模块开发／工具合同，不将作者阶段结果扩写为真实云、提醒通知或实体电视验收。

成员可为当前家庭的本地共享待办指定前置事项，例如“确认日期”完成后才能完成“订酒店”。不按负责人划分私有任务：仍沿用现有共享待办权限。电视可以读取状态，不能配置或完成任务。

## 数据与接口

继续使用 `entities(kind='tasks').data`，不增加表或回填旧记录。身份、成员状态、家庭、CSRF、Origin 与 revision 校验保持。

| 字段 | 写入与读取合同 |
| --- | --- |
| `dependsOn` | 可选字符串数组，最多 20 个不重复 ID。ID 非空、首尾无空格、最长 128 字符，兼容旧本地记录编号。只能引用当前家庭已经存在、没有 `sync` 的本地任务；不接受自身、重复值或循环。 |
| `blockedBy` | 只读数组，列出直接前置中未完成或已失效的 ID，顺序与 `dependsOn` 相同。不附带其他家庭资料或账户信息。 |
| `dependencyStatus` | 只读 `ready`、`blocked`、`done`。已经完成的事项为 `done`，否则按 `blockedBy` 是否为空判断。 |

旧记录缺少 `dependsOn` 时读取投影为 `[]`，不触发写入或改变 revision。PATCH 省略 `dependsOn` 保留原值；明确 `[]` 才解除所有依赖。`null`、字符串或其他非数组类型拒绝。请求中伪造 `blockedBy` 或 `dependencyStatus` 不能改变服务端校验。

`GET /api/state` 的 `tasks[]`、`GET /api/journeys/<id>` 的关联 `tasks[]`、`GET /api/assistant/brief` 中的到期待办，以及 `GET /api/routines/context` 的当前/历史本地任务投影包含上述字段。例行操作回执保留原有快照合同，不持久化这两个派生字段；读取当前状态请重新 GET context。库存售后资料页仍使用原精简任务 DTO，依赖可从任务主列表读取。

```http
POST /api/items/tasks
Content-Type: application/json
X-CSRF-Token: <当前会话令牌>

{"title":"订酒店","owner":"shared","due":"2026-12-01",
 "sourceId":"","dependsOn":["<确认日期的本地任务ID>"]}
```

POST 回执仍为 `{id, revision}`、状态码 201。`sourceId: ""` 明确选择看板本地清单。省略来源仍沿用原来的云端主清单路由；若实际目标是云端且依赖非空，会在调用 provider 前返回 400，提示改为本地任务。

```http
PATCH /api/items/tasks/<id>
Content-Type: application/json
X-CSRF-Token: <当前会话令牌>

{"revision":3,"dependsOn":["<当前家庭本地任务ID>"]}
```

完成仍用原 PATCH：`{"revision":4,"done":true}`。服务端进入 `BEGIN IMMEDIATE` 后重新读取目标 revision 和前置状态，只有全部直接前置完成才允许从未完成变为完成。创建时同时传 `done:true` 也必须满足此条件。前端可以提前解释原因，但旧快照不能替代这次服务端检查。

前置任务重新打开后，已经完成的后续任务保持完成历史；其 `blockedBy` 可重新出现，但 `dependencyStatus` 仍为 `done`。修改历史任务的标题或备注不会自动重开它。若本人先将后续任务重新打开，再次完成仍需通过前置检查。

被任何任务引用的前置任务不能删除，即使后续任务已经完成。先在后续任务中明确解除该依赖，再按最新 revision 删除。历史数据中的失效引用读取为阻塞，成员可用明确的依赖编辑解除；完成操作不会默默删除失效边。

| 场景 | 状态码 / `code` |
| --- | --- |
| 类型、重复、数量、ID 或自身依赖不合法 | 400 / `invalid_task_dependencies` |
| 前置不存在、属于其他家庭或是云镜像 | 409 / `task_dependency_unavailable`；使用同一通用提示，不透露哪种情况 |
| 直接或间接循环 | 409 / `task_dependency_cycle` |
| 尝试完成而前置未完成 | 409 / `task_dependencies_incomplete` |
| 删除仍被引用的任务 | 409 / `task_has_dependents` |
| 原 revision 已过期 | 原有 409 冲突响应 |

依赖错误返回 `{error, code}`；原有身份、版本和云接口错误结构不扩改。

## 所有本地写入路径

`task_dependencies.py` 提供纯图校验与投影，不启动 worker、调用 provider 或隐式写库。写入调用方保持同一个 `BEGIN IMMEDIATE` 至实际更新/提交。图只查询本家庭数据库内的 `tasks`，使用迭代遍历处理间接循环，避免长链触发递归深度限制。两个成员同时增加相反方向的边、删除与添加边、完成与重开前置，会按写事务串行检查。

| 来源 | 行为 |
| --- | --- |
| 普通本地任务 POST/PATCH/DELETE | 同一写事务核对图、前置完成状态及当前版本；失败不改变任务或业务审计。 |
| 旅行生成、重新预览保存、改期 | 新任务无依赖；已存在任务保留当前实体 `dependsOn`，不由旧旅行 plan 覆盖。旅行解除关联保留原任务及依赖。依赖配置仍走任务 CRUD，不由旅行草案推测。 |
| 例行事项 | 每次生成新的独立本地任务，无依赖；可在任务页编辑本次任务的依赖。阻塞完成时不会自动产生下一次；完成后新一期不继承旧期依赖。明确跳过沿用原例行语义，不把原任务改成完成。 |
| 助理新增草案 | 保留原明确预览、选择、确认。模型输出的隐藏依赖 ID 与 done 字段不采纳；新本地任务再经依赖校验。允许的模型上下文仍只含标题、日期、负责人，不携带依赖 ID。 |
| 库存售后跟进 | 原严格输入合同不接受依赖数组，只创建未完成本地任务；创建后可用任务 CRUD 设置依赖，完成受到同一保护。 |
| 已发布到云的本地旅行待办 | 本地原实体仍支持依赖；云镜像本身不支持。见下节。 |

删除旅行只解除关联，不删除本地待办，因而不会抹去依赖。旧客户端编辑普通任务、旅行重建、改期与远端状态合并均保留已有字段。

## Microsoft / Google 边界

云同步镜像不能设置依赖，也不能作为依赖目标；编辑镜像仍只支持原来的完成/恢复字段。依赖不会被翻译成 Microsoft To Do 或 Google Tasks 的能力。

本地旅行任务明确发布到云端后仍是本地实体。如果远端已经完成而本地前置未完成，worker 保留本地未完成状态，并将 publication 标为 `conflict`，提示本地依赖校验未通过。远端实际完成状态保持原样；系统不自动撤销远端，也不声称远端未完成。

冲突预览继续读取真实远端状态。选择采纳远端时，会在本地事务内再次检查前置；前置未完成仍返回 409，publication 保留冲突。前置处理完毕后，可重新预览再明确采纳。选择保留本地仍沿用原明确冲突解决流程，不自动执行。

## 数据导出与部署配套

成员明确请求 `POST /api/portability/export` 且 `includeShared:true` 时，共享任务保留已存的 `dependsOn`。默认个人导出不增加共享记录。`blockedBy` / `dependencyStatus` 不导出；导出保留原审计行为。此验证不代表便携文件重新导入或整库恢复已验证。

Dockerfile 仅在原模块 COPY 行加入 `task_dependencies.py`，没有依赖、Compose、环境或迁移变动。旧的固定发布 profile 未放宽；后续发布需由集成人另行固定新模块及实际组合身份，不能直接用旧白名单声称本批可部署。

## 验证范围

`tests/test_task_dependencies.py` 使用真实 Flask 登录、临时 SQLite、两个成员与独立家庭，覆盖输入、完成、历史重开、失效解除、旧客户端、20 个前置和 1100 节点图、并发循环/删除/重开、会话撤权、电视只读、旅行/例行/助理/库存入口与明确共享导出。Microsoft / Google 仅使用原 provider adapter 配合合成 HTTP transport，检查远端已完成而本地阻塞的冲突与后续明确采纳。

相邻回归覆盖原任务 CRUD、云任务、旅行工作流/改期、例行、发布队列、助理、导出和库存跟进。实际结果与保留的失败轮次在本分支 ignored `test-results/task-dependencies-*` 原件中记录；最终交付以作者验证报告的固定源码身份及终态为准。

本批不包含浏览器、Linux 镜像构建、真实云账户、提醒通知、生产部署或实际电视验证。
