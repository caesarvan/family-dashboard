# 家庭例行计划

**版本：2026-09-15 13:43:04（北京时间），镜像 `sha256:5e338ef586fbc0e7b2f2efb842b08b464e33f1b3a4d8be9eb1996100fb371f6e`。** 家庭共享周期计划与原有模块一并交付；完整组合验证及运行边界见 [HANDOFF](HANDOFF.md) 和 [VALIDATION](VALIDATION.md)。合成测试不等于真实云账户、实体手机／电视或生产长期调度已验收。

成员建立本地待办或采购模板，预览未来三期，明确确认后立即生成第一件今天或未来的事项。它不会自动发送到 Microsoft／Google；已有云发布流程仍需另行授权、预览与确认。

## 周期与当前事项

- 固定以 `Asia/Shanghai` 日期判断今天。`anchor` 是合法的 `2000-01-01..2100-12-31` 日期，可早于今天；首期从原节奏找 `>=today` 的日期，不补历史。
- `frequency` 为 `daily/weekly/monthly`，整数 `interval` 分别为 `1..365 / 1..52 / 1..12`。周计划从锚点起按若干个七天计算，不接受星期多选或 cron。
- 月计划固定 `monthEnd:"clamp"`：锚点为 31 日时，短月取月底，下一长月仍取 31 日；不会从 2 月 28 日重新计算锚点。年度闰日按同一规则。
- 生成日期也不超过 2100 年。下一期超界显示 `exhausted`，保留记录，不循环补期。
- 每计划只有一个当前期次。完成后从原规则找严格晚于 `max(当前期原 scheduledOn,today)` 的日期，生成一个后继；即使停机数月，也只生成一个未来事项。
- 事项的标题、`due`、负责人、备注、照片、实付或旅行关联可以在原编辑器修改，不改变周期；下一期使用模板，不复制后来编辑。
- 采购新期固定 `done:false / actual:null / photoIds:[]`，数量与预算来自模板；不复制付款、旅行、图片或云来源。任务新期为本地任务，截止日为期次日期，`tripId:""`。

规则修改只影响未来，当前事项所有字段保持。暂停停止后续生成；暂停中完成不会推进，明确恢复时若当前项已完成，立即按此刻日期生成后继。未完成则保留；删除后显示 `missing`，不会复活。

“跳过本期并保留现有事项”只对运行中计划开放，须预览、确认。旧事项不删改、不标完成，旧期固定 `skipped`，新期成为当前期。以后勾选旧事项也不改变跳过历史。归档保留事项及历史，不能恢复、编辑或物理删除规则。

## 权限与容量

计划、模板及生成事项属于本家庭共享内容，两位成员都可管理。`createdBy` 只是共享成员编号；模板 `owner` 为负责人。不得填写私人账户、财务明细、密码或令牌，未定义字段被拒绝。

管理接口要求有效成员会话；匿名 401、电视 403。电视只从原 `/api/state` 读取已生成的共享事项，不能读管理 context、历史或签名。POST 沿用 JSON、CSRF、同源检查；预览额外绑定发起成员、家庭与会话，不能转交另一成员确认。

最多 100 个未归档计划（active 和 paused 均计入），每类 tasks／shopping 最多 2500 条现有实体。归档只释放计划名额，不删除事项；容量不足不关闭当前期、不部分写入。归档历史不计入 100 上限，列表分页，单计划仅返回最近十期。

本模块不改公共资金、私人账本、投资、预算表、采购实付关联或旅行 `paid`。采购预算是模板估价，完成不证明付款。

## HTTP 接口

共同前缀 `/api/routines`，沿用普通 JSON 600,000 字节上限。GET 不迁移、不补期；context 和助理摘要只读业务记录。

### GET /context

| 可选参数 | 语义 |
|---|---|
| `planId` | 精确聚焦本户计划，不受分页／归档筛选隐藏；不存在 404 |
| `page` | `0..999999999` 十进制文本，默认 0；拒绝负数、多余前导零和重复参数 |
| `includeArchived` | 文本 true／false，默认 false；false 包含 active 和 paused，true 包含所有状态 |

响应：

```json
{
  "version": 1,
  "today": "2026-09-15",
  "timeZone": "Asia/Shanghai",
  "limit": {"activePlans": 100, "itemsPerKind": 2500},
  "plans": [],
  "pageInfo": {"page": 0, "pageSize": 40, "more": false}
}
```

plan 字段为 `id/revision/state/status/kind/template/schedule/createdBy/createdAt/updatedAt/current/nextDates/history`。state 持久化为 active／paused／archived；派生 status 为 pending／completed／missing／paused／archived／capacity_blocked／exhausted。revision 是单调增加整数，不应假设每操作只加一。

current 为 `{index,scheduledOn,entityId,state,entity}` 或 null。index 是每计划递增的生成编号，不是锚点以来所有理论期次的编号。entity 是现有共享字段白名单及 id／revision，缺失则 null。当前期 state 由完成状态派生 pending／completed／missing；已关闭历史固定 completed／skipped，重开旧事项不倒退计划。

context 的 nextDates 只含尚未生成的未来三期，当前项单独展示；2100 上限可能使其不足三期。暂停／归档显示理论日期不表示执行。history 是最近十期，包含当前期，按编号倒序；其余历史仍在数据库与显式共享的副本中。planId 聚焦可能使 plans 比 40 条多一条。

### POST /preview

创建示例均为虚构：

```json
{
  "operation": "create",
  "kind": "tasks",
  "template": {"title": "每周整理公共空间", "owner": "shared", "note": ""},
  "schedule": {"frequency": "weekly", "interval": 1, "anchor": "2026-09-15"}
}
```

kind 只能是 tasks／shopping，创建后不能改。tasks 模板必填完整 title／owner／note；shopping 另必填 quantity／budget。title 去首尾空白后 1..100 字符，note 0..500，quantity 1..30；owner 为 shared 或本户成员 ID。budget 为人民币整数分 `0..100000000000` 或 null，拒绝 bool、浮点和字符串，零与未知不同。

schedule 必填 frequency／interval／anchor，可选 `timeZone:"Asia/Shanghai"` 与 `monthEnd:"clamp"`，省略时由服务器补齐；其他值或未知字段拒绝。修改必须完整提供新模板与节奏：

```json
{
  "operation": "update",
  "planId": "synthetic-plan-id",
  "revision": 2,
  "template": {"title": "每两周整理公共空间", "owner": "member1", "note": ""},
  "schedule": {"frequency": "weekly", "interval": 2, "anchor": "2026-09-15"}
}
```

暂停、恢复、跳过、归档只接受以下三字段，operation 换为 pause／resume／skip／archive：

```json
{"operation":"skip","planId":"synthetic-plan-id","revision":2}
```

返回 `{operation,today,timeZone,before,after,nextDates,willGenerate,warnings,previewToken,operationKey,expiresInSeconds}`。before 是当前 plan 或 null；after 为 `{kind,template,schedule,state}`；warnings 为字符串数组。operationKey 是服务端签名 nonce 派生的 64 位小写十六进制编号，用于本人历史回执读回，不是新的写入凭据。

willGenerate 为 `{index,scheduledOn,kind,data}` 或 null。create、skip、当前项已完成的 resume 会生成；pause、archive、update 不生成。**preview.nextDates 包含尚未生成的 willGenerate 日期作为第一期，再列后两期**；确认后 context.nextDates 排除新 current，这是时间点差异，不是重复生成。

签名有效 600 秒，绑定原成员／家庭／会话、当天日期、规则完整记录、当前期、当前实体及 revision、实体数量和未归档计划数量。不写临时预览表；依赖改变须重新预览。

### POST /confirm

```json
{"previewToken":"仅使用本人本次预览返回的签名"}
```

返回 `{operation,plan,generated,replayed,operationKey}`；generated 为 `{id,kind,revision,scheduledOn}` 或 null。BEGIN IMMEDIATE 中重新核对 MemberSessions.current、捕获的实际 session ID、请求 actor、签名及依赖，原子保存规则、期次、实体、回执和 audit／meta；审计后、提交前再次核对会话。读取接口释放原快照后重新核对身份，兼容旧 Cookie 的隐式事务。

同一签名在原有效成员会话内重复确认先查历史回执：即使预览超过 600 秒，已执行操作仍返回历史结果、replayed:true，不重建或再推进。历史结果不是当前状态证明；后来删除、归档或编辑也不会被回放恢复。尚无回执时才在写锁内检查时效；过期返回 410 与 `code:preview_expired_unapplied`，不写业务数据。所有首次确认都在此写锁后检查时效，因此这一 410 可结束原未知状态并重新预览，普通 GET 404 则不能。确认后读回 context；关闭窗口不能取消已发送写入，结果不明时沿用同一 token，不自动产生新确认。

格式、未知字段或坏签名为 400；无登录／会话撤销 401；电视、CSRF、签名所属成员／家庭／会话不符 403；本户计划不存在 404；日期、版本、实体、容量、状态改变或归档后操作 409；锁内核实原操作未执行且预览过期为上述 410。冲突保留草稿后重读、预览，不静默覆盖或改变操作。

### GET /operations/\<operationKey\>

仅当前户、当前有效成员本人可读其发起的历史回执；同户另一成员也不能代读。重新登录后可读取本人历史，但不能用旧会话签名产生新写入。编号严格为 64 位小写十六进制，不接受查询参数。

成功返回 `{found:true,operationKey,operation,planId,revision,generated,createdAt}`，revision 为当时确认后的计划版本，generated 沿用上述精简结构；createdAt 是原回执 UTC 时间。未找到返回 404 与 `code:routine_receipt_not_found`，只表示此刻尚未找到，原确认可能仍在途。响应 `Cache-Control: no-store`，不返回完整计划、nonce、签名或会话信息；没有写入、补期或延长预览。原有回执不含 operationKey 也可按现存 owner／nonce_digest 精确读取，无 schema 迁移。新 Expo 接缝及验收范围见 [EXPO-ROUTINES-API](EXPO-ROUTINES-API.md)。

## 存储、调度与共享导出

新增三表，不改旧表：

| 表 | 列及约束 |
|---|---|
| household_routines | id／kind／template／schedule／state／revision／current_index／created_by／created_at／updated_at；kind/state 枚举 CHECK，created_by 引用 users，state/id 索引 |
| routine_occurrences | plan_id／occurrence_index／entity_id／scheduled_on／state／created_at／closed_at；主键 plan/index、entity_id 唯一、每计划至多一个 current 的部分唯一索引；entity_id 不设实体外键，以保留删除历史 |
| routine_receipts | id／owner／nonce_digest／operation／plan_id／result／created_at；owner/nonce_digest 唯一，只保存已确认结果 |

`register_routines(app,db,Problem,body,require_member,audit)` 登记 `app.extensions['household_routines']`。worker 在云来源读取后调用 tick()，遵守原停止信号协议；无独立定时器、网络调用、凭据或新环境变量。

tick 自建 app context，不依赖 g.actor。只读筛选后，仅可能推进的规则进入写事务并重读全部条件。未完成、缺失、暂停、容量阻塞或日期用尽不持续争写锁／写审计／递增版本。成功后写 system:routines 审计与 meta revision，同一事务生成一期；双 worker 和重复确认不破坏唯一性。

`engine.brief(con)` 使用调用方连接只读返回 `{items:[{id,title,kind,owner,scheduledOn,status}],dueCount,issueCount,limit:8}`。只含 active，优先 missing／capacity_blocked／exhausted，再按原 scheduledOn 排列；普通 pending 仅列今天至七天后及逾期。dueCount 统计全部 active 中 pending／missing 且原 scheduledOn<=today，issueCount 统计全部上述问题，数量可超过八条展示上限。id 是原计划 ID，不读私财／服务商、不补期。

`export_shared_routines(con)` 返回 plans／occurrences／receipts，仅显式 includeShared:true 时由原导出模块调用。plans 是规则业务字段及共享 createdBy，occurrences 是期次历史，receipts 仅 id／operation／planId／createdAt／generatedId。不导出 owner、nonce、完整确认结果、签名或会话；默认本人副本不含本组共享计划。管理员备份仍含完整三表。见 [PORTABILITY](PORTABILITY.md) 和 [DEPLOYMENT](DEPLOYMENT.md)。

## 验证与接手

[后端专项](../tests/test_household_routines.py) 使用真实临时 Flask／SQLite、虚构成员和固定日期，硬拒 socket 网络，覆盖周期数学、月底／闰年／2100、原节奏、预览／回放、依赖 CAS、事项删改、暂停／恢复／归档、missing／skip、零与未知、鉴权／已撤销会话、双线程确认／worker、空闲不取写锁、只读摘要及导出白名单。

[跨模块专项](../tests/test_routine_journeys.py) 独立验证旅行、模拟云任务完成回流、采购实付和共享导出。使用独立虚拟环境和临时数据库运行对应 pytest；计数和依赖散列以实际报告为准。完整组合与 Linux 结果见 VALIDATION，真实云写及实体设备仍独立待验。

本模块、专项与本文可独立维护；app.py／sync_worker.py／data_portability.py、共享 UI、Docker 和发布白名单由集成人负责。移植须同时保留三表、事务、日期上限、原事项保护及停止协议，不能只复制界面或让 GET 自动生成。

本轮模块阶段的实际记录为后端 81 项、跨模块 17 项；完整 Windows 1136 passed / 18 skipped、Linux 1153 passed / 1 skipped，各自 1154 项；新例行浏览器 77 项。模块计数不重复累加，最终组合依赖、浏览器和部署读回以 [VALIDATION](VALIDATION.md) 为准。

初始化只新增三张空表及冻结索引，不预置计划，不把已有实体转换成规则。用户未确认创建计划前没有自动事项；发布后六个旧来源自然读取成功也不能证明某期任务已经云发布。37→40 首次迁移和后续 40→40 零 schema 更新是不同检查，不能互换。当前模块文件占用已结束；下一轮按 [开发交接](DEVELOPMENT.md) 登记独占路径。
