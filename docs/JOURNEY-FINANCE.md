# 本人旅行费用归集

已随固定 `302a62d` 于2026-09-21 02:38:33（北京时间）发布，实际生产为75/9、五服务；02:38:56只读回读通过，非作者生产独审已通过。开发基线 `dc2b54cfc7fc9063eb839ece87fdab72a21855be`；只归集本人已有付款到原旅行，不改原账单、采购实际金额或旅行共享 `paid/budget/saved`。首批人民币整数分，不做报销、分摊、外币换算或自动对账。实际部署身份、最短操作与结果见[集中验收](JOURNEY-FINANCE-ACCEPTANCE.md#journey-finance-release)。

从已保存旅行选择「我的旅行费用」，选择原付款并预览，明确确认后保存。展示「仅本人已归集」与共享旅行预算并列；不能称为家庭实际总费用或剩余预算。发生退款、重复核对、来源删除或更改时保留原金额，在「需核对」中提示本人调整或解除。没有原旅行时仍可从财务中的本人全部历史解除孤立关联。

## 权限、金额与来源

- 所有端点要求当前家庭内有效成员；电视403，匿名401。所有关联、付款、回执与导出按当前owner读取，不能传owner或household。旅行是当前同户共享对象，`created_by`不是该旅行的私有ACL。
- 只接受 `journey_workflows.id`，24位小写hex；必须与原 `entities(kind=trips)` 的ID和JSON `journeyId` 互指。没有workflow的旧trip须先使用原旅行保存/升级入口，不能把tripId冒充journeyId。
- 付款须本人 `kind=payments,flow=expense,currency=CNY`，且未被有效duplicate关系排除。原订单不是付款；订单关联和采购实付投影均不减少旅行额度，也不加入旅行总额。
- `netCents=amountCents-refundedCents`，只扣既有对账中明确确认的退款金额。退款不再另建负数归集；未核对的退款状态和疑似重复不自动推算。拒绝bool、字符串、小数和负金额，归集范围1～100000000000分。
- 同付款在本人所有旅行的active归集（包括需核对、旅行已删）共同占用额度。更新仅排除自身；全部重新读取和限额检查在同一 `BEGIN IMMEDIATE` 内完成。
- 来源摘要覆盖原付款行、它的有效对账关系及关联原交易行。来源漂移保守进入needs_review，不静默裁剪/移动金额。单纯旅行标题、日期或预算改变在确认后使用当前值，不制造新归集。坏金额/负净额不伪装成0：历史显示source_ineligible、payment为null，仍可解除；apply/update严格拒绝。
- 读取使用 `ImportSession.read`，释放旧快照后再次核身份；写事务取得锁后及提交前再次核验，返回前fresh核验。提交后身份核验失败不代表未写入。SQLite锁忙可恢复503，不自动重试写入。

## HTTP 合同 v1

公共前缀 `/api/finance-hub/journey-allocations`。所有成功响应HTTP200、`version:1`、`Cache-Control`含no-store。写入沿原同源JSON/Origin/CSRF。拒绝未知和重复查询参数。

| 方法/路径 | 参数与响应 |
|---|---|
| GET 根 | 可选journeyId或paymentId（二者互斥）、status=active或all（默认active）、page=0起。`{version,journey,summary,allocations,pageInfo,readAt}`；journeyId不存在404。不指定journeyId仍可读取本人已删除旅行的关联。 |
| GET `/payments` | 必填journeyId；可选q（≤80字符）、page、allocationId（本人该旅行active关联，更新排除自身）。`{version,journey,payments,focus,pageInfo,readAt}`；focus独立，不追加到40项列表。 |
| POST `/preview` | 下方精确intent；`{version,operation,allocationId,journey,payment,beforeAllocatedCents,afterAllocatedCents,beforeStatus,afterStatus,unchanged,warnings,previewToken,expiresAt,expiresInSeconds:600}`。业务只读，不持久nonce。 |
| POST `/confirm` | 仅 `{requestId,previewToken}`；requestId为32位小写hex，token为原字符串≤12000字符。`{version,receipt,replayed}`。 |
| GET `/operations/<requestId>` | 无查询参数；`{version,requestId,found,receipt}`。未见回执仍HTTP200/found=false；不证明在途请求没提交。 |

精确预览intent：

```json
{"operation":"apply","journeyId":"24hex","journeyRevision":1,"tripRevision":1,"paymentId":"原付款ID","paymentRevision":1,"amountCents":7000}
{"operation":"update","allocationId":"32hex","revision":1,"journeyRevision":1,"tripRevision":1,"paymentRevision":1,"amountCents":6000}
{"operation":"revoke","allocationId":"32hex","revision":1}
```

ID中paymentId沿原账本 `[A-Za-z0-9_-]{1,100}`；版本为正整数≤9007199254740991。apply/update绑定原旅程、trip和payment版本；update不能换付款或旅行。revoke仅依赖本人active关联及版本，原旅行/来源缺失、损坏或超额都不妨碍解除。

DTO 精确字段：

- `JourneyRef={id,tripId,revision,tripRevision,title,sharedBudgetCents,sharedManualPaidCents,sharedSavedCents}`，金额均整数；缺失原对象为null，不伪造历史标题。
- `Payment={id,revision,date,title,kind:"payments",flow,currency,amountCents,refundedCents,netCents,reservedCents,availableCents,eligible,reasonCode}`。reasonCode为null/not_expense/duplicate/unsupported_currency；available=max(0,net-reserved)。完整原记录仍沿原对账/交易接口按ID读取。
- `Allocation={id,revision,journeyId,tripId,paymentId,amountCents,status,state,reasonCodes,acceptedNetCents,acceptedRefundedCents,createdAt,updatedAt,journey,payment}`。status为active/revoked，state为current/needs_review/revoked；reasonCodes为journey_missing/source_missing/source_changed/source_ineligible/payment_overallocated。删除或金额无法安全投影时payment可null。
- `JourneySummary={currency:"CNY",coverage:"owner_partial",currentAllocatedCents,needsReviewAllocatedCents,activeAllocatedCents,currentCount,needsReviewCount,sharedBudgetCents}`。仅journeyId模式返回；计算所有页的active关联，revoked不计，current与needs_review分开。不含家庭总额或剩余预算。
- `OperationReceipt={requestId,operation,allocationId,revision,completedAt}`，operation为apply/update/revoke。证明过去提交，不代表当前关联仍有效，不存标题、金额快照或凭证。
- `pageInfo={page,pageSize:40,hasMore}`；关联createdAt降序、ID升序，付款date降序、ID升序。`readAt/expiresAt/completedAt`均UTC。

## 确认、恢复与容量

首次确认前固定原 `{requestId,previewToken}`。服务端在写事务内优先查本人原requestId；同完整body返回原最小回执，优先于token过期/来源删除/对象状态/容量检查。不同body409，不允许复用编号表达新意图。没有旧回执才校验签名、600秒TTL、当前身份和完整依赖，再同事务保存关联、回执和最小audit。回执永久保留，重启不改变恢复语义。

未知结果先GET原回执；found=true后只重试列表读取，不能重发新请求。found=false仍未知，只允许本人明确重试完全相同原body。过期且未提交返回preview_expired，此时才重新预览。提交后的 `/me` 或列表失败不能被当成确认未保存。客户端跨刷新恢复须按当前会话身份隔离，不存文件或登录凭证，不向其他身份展示原token/金额。

每owner最多20000关联（含历史）、40000回执、回执结果合计32MiB，每份最小回执≤1024B。新增/更新为每条active关联保留一行和1024B解除回执余量，不能耗尽解除能力。容量满不静默清历史；已提交重放优先返回。解除保留原amount，将status改revoked、revision+1，释放额度。重新归集需新预览/编号/关联ID，同本人同旅行同付款至多一条active。

错误码：400 `journey_finance_invalid_request`；404 `journey_finance_not_found`；409后缀 `stale/capacity/ineligible/active_exists/request_conflict/preview_expired/storage_limit`；锁忙503 `journey_finance_unavailable`。身份/CSRF/TV沿401/403，不能借错误区分另一成员的私有ID。

## 存储与导出

`journey_finance.SCHEMA_SQL`新增且仅新增 `hub_journey_allocations`、`hub_journey_allocation_operations` 两表及四索引。`init_schema(con)`要求调用方事务与foreign_keys开启，不commit；注册/新家庭factory正常初始化，GET不建表。原73表不回填，完整组迁移为73→75／平台9不变；[迁移与75稳态读取](JOURNEY-FINANCE-MIGRATION.md)及[固定发布适配](JOURNEY-FINANCE-RELEASE.md)已有独立工具和审查。隔离两户三库迁移／恢复已实际通过且完成执行独审；本次生产一户两库已迁移至75/9，旧73表保持、新两表在app停止核验时为空。已消费计划和旧73版计划都不能重放。

关联仅owner外键引用users；旅行/付款ID为稳定文本，不随原对象级联删除。普通退出或成员停用不删私人历史，停用期间不得访问，也不转给管理员/继任成员。

个人ZIP新增 `data.json.personal.journeyAllocations={allocations,operations}`，includeShared不扩大范围。allocation只导出id/revision/journeyId/tripId/paymentId/amountCents/status/acceptedNetCents/acceptedRefundedCents/createdAt/updatedAt；operation只导出operation/allocationId/revision/completedAt。无requestId、payload_hash、source_digest、token、历史来源正文。原transactions.csv不增加归集行；导出不等于导入或恢复。原导出限流/audit保留，不能称整个导出零写。

## 验证范围

定向验证使用真实临时Flask、SQLite、虚构成员/旅行/账单与真实请求；覆盖幂等、重启、过期、并发净额、原对象不变、退款/重复/删除、身份撤权、跨家庭/电视及个人导出。作者44项新用例＋2项相邻按分轮原件保留；候选镜像另实际执行精确46项，0失败／错误／跳过。真实组合浏览器和隔离迁移结果分别见[集中验收](JOURNEY-FINANCE-ACCEPTANCE.md#journey-finance-release)，不相加为一次全量，也不代替真实账户或云验收；本次生产迁移／部署另以实际回执记录。
