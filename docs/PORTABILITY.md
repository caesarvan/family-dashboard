# 个人数据副本与接口契约

> **当前版本：2026-09-15 20:23:00（北京时间），镜像 `sha256:651ecfd6bdb65cf04bb8778c8657a8ec0f27a123940683a44a8b9931a5f22352`。** 旅行资料、完整细项展示与分段定位已发布，保留此前全部模块；106 个方法／路径模板、43 张户内表（41 业务 + 2 认证）及 2 张平台表。源码与文档数量见 [README](../README.md) 及交接清单；测试、迁移和实际接入边界见 [VALIDATION](VALIDATION.md)。

## 消费观察与异步导出保护

两张消费观察表均存在时，`personal.spendingObservations` 输出 `{current:null,receipts:[]}` 或本人已确认快照及业务回执。`current` 仅含 revision、sourceDigest、candidateDigest、acceptedAt 和重新按固定白名单验证的 candidate；receipts 仅含 receiptId、candidateDigest、sourceDigest、revision、status、acceptedAt。来源只保留三份固定报告的相对文件名、日期、覆盖、散列和聚合月份，不带原文件内容、绝对路径、预览令牌或会话认证上下文。完整字段见 [消费观察契约](SPENDING-OBSERVATIONS.md)。

这份记录仅属于当前成员，`includeShared` 不扩大它的范围。`personal.financeBaselines` 继续导出原始财产基线；消费观察、基线、账单和订单不可重复相加。共享财产小计不采用消费观察。空表输出空值／数组，不生成默认财务内容。

前端在任何异步请求前捕获原成员 ID、家庭 ID、auth_version、CSRF、页面地址和原弹窗节点。先显示中性的加载窗口；摘要前后读取 `/api/me`，导出 POST 前与 Blob 到达后再次读取。每个异步阶段都检查原节点与身份；换页、关闭或后来打开的窗口不会被迟到成功或错误接管。提交期间固定并禁用共享勾选，同一窗口只允许一个进行中的导出；当前网络、429、503 或错误格式不启动下载，保留可重试选项。失效身份清除旧内容。

仅在最后一次身份核对成功后创建 Blob URL 并同步触发下载；已启动 URL 约 30 秒回收，未使用 URL 立即回收，页面退出也清理。没有把私有 Blob、URL、候选或认证值存入浏览器持久化存储。

**并发边界**：关闭页面不能取消服务端已接受的导出审计，已开始的浏览器下载也不能撤回。最终 `/me` 已在服务端读取成员 A 后，另一标签页仅把 Cookie 切到成员 B、当前页面全局身份仍为 A，最后放行旧 `/me` 响应，仍可能下载 A 的副本。独立临时浏览器已观察到这一非原子窗口；它单列为限制，不计入防护通过数。若当前页面已收到新身份、打开新窗口或关闭原窗口，原结果必须丢弃。不能用有限次追加 GET 声称消除了所有跨标签竞态。

验证脚本：`tests/browser_data_portability_guard_check.py`（59 项保护通过，另 1 项非原子观察限制不计通过）及 `tests/browser_data_portability_check.py`（4 项原格式与范围）。它们已按相同完整依赖纳入 2026-09-15 15:10 历史财务批次的 10 组 222 项组合；该批与当前版本的证据分别见 [VALIDATION](VALIDATION.md)，不把其他批次直接累加。

> **例行计划导出扩展对应 2026-09-15 13:43:04（北京时间），镜像 `sha256:5e338ef586fbc0e7b2f2efb842b08b464e33f1b3a4d8be9eb1996100fb371f6e`。** 明确选择 `includeShared:true` 且三张例行表均存在时，`shared.routines` 包含计划、期次及共享业务回执白名单；默认本人副本不包含这一共同配置。不导出预览令牌、nonce、完整确认结果或会话上下文，不把私人财务关系放入例行计划。格式见 [ROUTINES](ROUTINES.md)。


实现：`data_portability.py`、`static/data-portability.js`。入口为成员工作台「设置 → 导出我的数据」。已于 2026-09-15 01:10:44（北京时间）部署；当前发布与验收状态见 [交接说明](HANDOFF.md)。

02:33 历史批次新增的 `personal.financeSourceReceipts` 与共享事件的旅行时间／日期元数据已随 2026-09-15 02:33:28 版本发布；来源回执仅限本人，旅行字段仍需显式选择共享记录。

**投资增量已于 2026-09-15 08:56:01 发布：** [投资持仓整理表导入](INVESTMENT-IMPORT.md) 的本人来源、稳定关联和业务回执已接入 ZIP 导出。下文新增投资字段随本次发布启用；原有导出权限与历史版本记录保持，实际验证见 [VALIDATION](VALIDATION.md)。

导出当前成员保存的资料，便于查阅和后续迁移。默认只含本人数据；勾选后附带本家庭已共享的记录。导出不会更改业务记录，也不会发起第三方同步。

**采购实付导出扩展对应 2026-09-15 12:11:36 发布记录，镜像 `sha256:1167dffd3b7e234d43460442acfe0d30959370c90c7e8147a1b30baa0e2380b5`。** 两张采购核对表均存在时，副本增加 `personal.shoppingSettlements`。此扩展不增加导出接口、不改变 `includeShared` 权限；合成 ZIP 验证不等于正式账户已经下载副本，发布与数据保留证据见 [VALIDATION](VALIDATION.md)。

## 权限与请求

### 旅行资料扩展

旅行资料元数据已随 20:23 发布接入；当前表结构见页首。两个原导出接口不变，ZIP 仍为五个文件、`schemaVersion: 1`、64 MiB 未压缩内容上限；文件 BLOB 不进入个人 ZIP。

摘要始终包含 `personal.journeyDocuments` 和 `shared.journeyDocuments` 计数；没有资料表时两项为零。本人全部未删除资料只计入 personal 一次，包括本人共享和旅行删除后保留的资料。shared 仅统计另一成员明确共享且仍关联有效旅行的资料，不包含本人的重复记录。

`data.json` 增加 `coverage.journeyDocuments: "metadata_only"` 和始终存在的 `personal.journeyDocuments` 数组。只有 `includeShared: true` 才有 `shared.journeyDocuments`。两处都仅包含以下 13 个字段：

`id`、`journeyId`、`owner`、`title`、`filename`、`mimeType`、`bytes`、`visibility`、`segmentKey`、`unlinked`、`createdAt`、`updatedAt`、`revision`。

`visibility` 是当前有效范围，孤立资料为 private；不导出 BLOB、下载 URL、上传请求标识、内容摘要、删除标志，以及界面派生的 `segmentMissing`／`canManage`。已删除资料不在副本中。旅行文件须在资料夹逐份下载；没有文件批量导出、ZIP 还原或一键重新导入接口，完整字段见 [资料契约](JOURNEY-DOCUMENTS.md)。

两个接口均要求成员登录；匿名返回 401，电视返回 403。写接口另需同源 JSON 和 `X-CSRF-Token`，参见 [基础 API](API.md)。成员由会话确定，不能传入 owner 读取另一人的数据。

| 方法 | 路径 | 响应 |
|---|---|---|
| GET | `/api/portability/summary` | 本人记录数量、共享实体数量、格式与覆盖提示 |
| POST | `/api/portability/export` | `application/zip` 附件，私有且禁止缓存 |

空库摘要示例（字段计数随真实保存数据变化）：

```json
{
  "personal": {"transactions":0,"investments":0,"budgets":0,"financeBaselines":0,"assistantPlans":0,"journeyDocuments":0},
  "shared": {"journeyDocuments":0},
  "format": "zip",
  "note": "导出的是当前保存的记录，并非已覆盖全部金融账户。采购图片和旅行资料仅含元数据，不包含文件；旅行文件请在资料夹逐份下载。账号连接需要重新授权。"
}
```

导出请求：

```json
{"includeShared": false}
```

`includeShared` 可省略，默认为 false；必须是布尔值，任何未知字段都会拒绝。每个家庭现有的 IP 限速记录限制每小时 6 次导出请求，单进程同时只生成一份副本；超限或占用返回 429。归档条目合计未压缩内容超过 64 MiB 返回 413，不返回不完整 ZIP。前端失败时保留选项并允许重试。

成功响应：`Content-Disposition: attachment; filename=family-data-<member>-<UTC时间>.zip`，`Cache-Control: private, no-store`。不返回 JSON 成功壳；客户端应按 Blob 下载。业务读取处于单户 SQLite 读事务内，读完后再压缩归档。

## ZIP 内容

| 文件 | 内容 |
|---|---|
| `data.json` | schemaVersion、UTC 导出时间、当前家庭与本人身份、覆盖说明、personal，以及选填 shared |
| `transactions.csv` | 本人所有已保存原始交易，包含 id/date/title/amount/currency/kind/flow/category/source/externalId/visibility/revision |
| `investments.csv` | 本人投资的 id/institution/name/assetType/currency/cost/value/asOf/revision |
| `README.txt` | 金额、覆盖、隐私、图片与恢复边界说明 |
| `manifest.json` | schemaVersion、exportedAt；其他四个文件的字节数和 SHA-256；不包含自身散列 |

JSON 金额保持原始整数分；CSV 的 amount/cost/value 是原币金额字符串，保留两位小数。估值未知在 JSON 中保留 null、CSV 中为空。CSV 文本中公式危险前缀加单引号，JSON 保留原文。不同币种、历史基线和现值不能直接相加。

`personal` 包含：全部本人交易、投资、分类预算、导入批次、对账关系、月度收支、私有财务基线、显示偏好、首页布局、本人助理草案和执行结果、本人账号连接的展示标签与已选来源名称、本人上传图片的元数据。导出交易不受看板分页上限影响；已确认重复的原始行仍保留，对账关系记录在 `reconciliations`，CSV 不是去重后的支出报表。

`reconciliations` 明确只导出 id、kind、leftId、rightId、amountCents、status、revision、createdAt、updatedAt。确认令牌和 `confirm_digest` 均不导出。

本地新增 `personal.financeSourceReceipts` 只读取当前成员的 `finance_source_receipts`，导出列为 `id/candidate_digest/source_digest/expected_revision/expected_source_digest/baseline_revision/status/accepted_at`，保留 snake_case；没有 owner、原预览令牌或签名。它记录本人的来源确认回执，不是支付记录，不参与资产或支出相加。来源 manifest 仍随本人 `financeBaselines` 的私有数据导出，伴侣和电视无权读取；完整来源预览与接收契约见 [FINANCE-SOURCE-BRIDGE](FINANCE-SOURCE-BRIDGE.md)。

选中的 `shared` 包含成员显示名、本家庭共享日程/待办/采购/旅行实体、公共资金快照、批准的财务基线汇总、旅行计划和被引用图片的元数据。实体按字段白名单导出，不带内部同步凭证或镜像元数据。

当前源码候选新增 `personal.calendarEvents`，只包含本人创建且当前为私密的本地日程。`shared.entities.events` 只在 `includeShared:true` 时包含当前可见的共享日程；两处保留原 ID、revision 和可用的 `visibility`／`createdBy`。伙伴的私密日程不会进入本人副本或 summary 计数。压缩后交付 ZIP 前再次核对日程快照，若共享撤回、删除或更新则拒绝交付旧副本。兼容规则见[本地日程隐私](CALENDAR-PRIVACY.md)，部署状态以 [README](../README.md) 为准。

本地新增的共享事件白名单包括 `travelTiming`、`startDate`、`endDateExclusive` 和 `workflowKey`，用于保留旅行的当地时间／时区语义、纯日期及排他结束日期。这些随已共享家庭实体**仅在明确 `includeShared:true` 时**导出；不会放入默认本人资料副本，也不因此扩大个人财务可见范围。日期元数据不等同外部日历已同步证明。

不包含伴侣私人账本、投资或收入明细，也不包含密码散列、应用密钥、OAuth token/state/PKCE、服务商身份 subject 或 client ID。账号标签可能含本人的邮箱，下载文件应保存在本人控制的设备上。

## 覆盖与恢复边界

<a id="投资导入历史独立候选尚未部署"></a>

### 投资导入历史

`personal.investments` 和 `investments.csv` 继续包含本人已保存的手工及文件导入持仓。新增字段在当前家庭数据库按当前成员 `owner` 查询，并使用固定白名单：

| `personal` 字段 | 导出字段 |
| --- | --- |
| `investmentSources` | `sourceName`、`revision`、`updatedAt` |
| `investmentLinks` | `sourceName`、`holdingKey`、`investmentId`、`createdAt` |
| `investmentImportReceipts` | `id`、`sourceName`、`sourceDigest`、`confirmedAt`、`result` |

回执 `result` 仅导出整数 `created/updated/unchanged`、布尔 `replayed`、字符串 `receiptId/confirmedAt`。额外字段及不符合这些标量类型的值不导出。来源摘要是文件版本的业务标识，不是确认凭据；历史计数不表示当前仍持有那些资产。

持仓删除后，`investmentLinks` 可保留原 ID 的防重复导入关联，目标不一定仍存在于 `investments`。导出保留这一历史，不恢复已删除持仓。旧库仍可导出原有内容；三个新增字段在对应表不存在时省略，空表则输出空数组。

`hub_investment_import_previews` 完全不读取或导出；不包含暂存 `snapshot/context_hash`、预览 ID、签名 token、nonce、Cookie、CSRF、成员会话散列或另一成员的投资导入历史。选择 `includeShared:true` 也不扩大这些本人字段的范围。来源／关联／回执不是交易流水，不与持仓、历史基线或公共资金重复相加。四表及确认流程见 [投资导入契约](INVESTMENT-IMPORT.md)。

<a id="采购实付关联与回执候选"></a>

### 采购实付关联与回执

`personal.shoppingSettlements` 为 `{"links":[],"receipts":[]}`。`data_portability.py` 在原单户读取事务中调用 `export_owned_settlements(con, owner)`；`owner` 仅来自当前成员会话。两个新表均存在时输出该对象，空表输出空数组，旧库缺表时省略这一字段。

| 数组 | 唯一允许的业务字段 |
| --- | --- |
| `links` | `id`、`revision`、`shoppingId`、`paymentId`、`amountCents`、`status`、`appliedShoppingRevision`、`createdAt`、`updatedAt` |
| `receipts` | `id`、`operation`、`linkId`、`createdAt`、`changedFields`；变化字段只允许 `actual`、`done` |

不导出 `source_snapshot/source_digest/before_values/projected_values/nonce_digest`、预览令牌、会话上下文、Cookie 或 CSRF；链接导出也不包含上下文接口临时派生的 `state/reviewReasons`。选择 `includeShared:true` 仍只导出本人的关联与回执，不包含另一成员的付款和溯源。共享采购的 `actual/done` 随原共享实体白名单导出，二者不能与私有来源字段混放。

原付款或采购删除后，本人链接与回执可保留历史 ID；它们不是重新创建记录的指令。`amountCents` 是本次核对分配的人民币分，采购整项实付仍以当前共享实体为准；两个成员可以分别核对同一采购，不能把历史链接金额相加作为家庭支出。此副本不修改账本、采购或共享权限。操作和删除规则见 [采购实付核对](SHOPPING-SETTLEMENT.md)。

### 通用恢复限制

`coverage.completeFinancialCoverage` 固定为 false：导出的只是目前保存的记录，不宣称覆盖全部金融账户。参考图片只有编号、尺寸和大小，不含图片二进制；连接第三方需要重新授权。发布队列、运行锁、完整审计日志和平台目录没有作为可恢复的运行状态导出。

当前没有一键重新导入该 ZIP 的接口。管理员灾难恢复使用包含数据库与注册目录的 [在线备份与恢复流程](DEPLOYMENT.md)，不能拿此 ZIP 覆盖 SQLite。

## 验证

[旅行／采购／副本跨模块专项](../tests/test_shopping_settlement_journeys.py) 在最终采购后端上实际通过 **10 项，6.85 秒**，30 项依赖文件前后散列一致。使用两位合成成员、临时 Flask/SQLite、图片和真实 ZIP，覆盖本人白名单、伴侣／电视隔离、迁期保留及删除后不复活。12:11:36 采购历史版本的 Windows 完整后端为 **1035 passed / 12 skipped，共 1047 项**；Linux：**1046 passed / 1 skipped**。副本专项与完整组合分别记录，不能据此认定正式账户下载已验收；浏览器逐组范围及发布证据见 [交接说明](HANDOFF.md) 与 [验收记录](VALIDATION.md)。

`tests/test_data_portability.py` 使用虚构数据和隔离数据库验证本人/伴侣/电视/其他家庭边界、CSRF/同源、未知字段、501 条完整导出、公式安全、金额精度、未知估值、归档 SHA-256、资源上限与并发槽恢复。浏览器验收与最终测试结果见 [验收记录](VALIDATION.md)。

本次发布的 [投资导出专项](../tests/test_investment_import_portability.py) 使用两位合成成员真实创建／预览／确认后生成 ZIP，覆盖同来源名和持仓键的本人隔离、两户隔离、暂存与认证字段排除、未知估值与零、删除关联保留，以及旧库缺表兼容。导出保留既有审计写入及 `settings.meta` 递增；业务、认证、共享设置和预览记录不被导出修改。该局部验证不是生产持仓导入或正式账户下载验收。

临时浏览器历史验证已通过设置入口、实际 ZIP 下载与 manifest 校验、失败保留选项，以及伴侣/演示/电视边界；见 `test-results/data-portability-browser-verification.json` 和 [工作台验收说明](WORKSPACE-UI.md)。这证明的是临时数据流程，不是正式账户已完成下载的记录。

02:33 版本 Linux 测试 546 项通过、1 项跳过。服务器内部已确认 29 张户内表、原数据保留、六个来源新同步成功、28 个静态资源哈希一致，以及含 `/api/portability/summary` 在内的 11 个匿名 API 返回 401。公网浏览器受组织策略阻断，没有执行正式账号 ZIP 下载或生产写请求；真实 Microsoft / Google 发布写入也未据此验收。

## 家庭例行计划共享副本

仅 `POST /api/portability/export` 的 `includeShared:true` 增加 `shared.routines={plans,occurrences,receipts}`，无新增导出路由；原请求仍限有效成员、同源 JSON 与 CSRF，TV 不可导出。两位成员都可导出本家庭规则；不能跨家庭或读取伴侣私人财务。

- plans：id、kind、template 的 title/owner/note/quantity/budget 白名单、schedule 的 frequency/interval/anchor/timeZone/monthEnd、state/revision/currentIndex、共享 createdBy、createdAt/updatedAt。
- occurrences：planId/index/entityId/scheduledOn/state/createdAt/closedAt。保存的历史状态用于追溯，实体已删除也不复活。
- receipts：id/operation/planId/createdAt/generatedId。排除确认者 owner、nonce_digest、签名、会话上下文及完整 result。

完整管理员备份必须包含三表全部内容；成员副本只是业务数据，不是可直接还原 SQLite 的恢复包。恢复不得仅导入共享 JSON 重建相同 ID 或跳过旧会话失效要求。新模块阶段跨模块 17 项包括真实临时 ZIP 白名单验证；最终组合和各平台计数见 [VALIDATION](VALIDATION.md)，不据此声称真实家庭已经下载或恢复过。


## 账单导入回执与来源（本地候选，尚未发布）

本人 ZIP 新增 `personal.transactionImportReceipts`，仅从当前家庭的 hub_import_receipts 读取本人记录。导出字段白名单为 requestId、receiptId、batchId、imported、duplicates、conflicts、confirmedAt、resultMonths（仅 month／recordCount）、note；不导出预览令牌、token_digest、payload_digest 或扩展认证字段。旧 `personal.imports` 七列投影不变，不能将操作回执当作另一份交易重复计金额。

`personal.transactions[].provenance` 保留首次来源批次、文件名／格式／工作表、物理行范围和导入时间；旧记录未保存来源时为 `{status:"unknown"}`。仅为索引与文本元数据，不含原文件字节、Base64、下载链接或任何平台凭据。共享部分不含交易来源或导入回执；即使勾选附带共同数据，伙伴和电视仍不读取这些私人字段。

回执在交易删除后仍存在，供原编号精确读回和防止重试复建。完整数据库备份／恢复必须包含新表；个人 ZIP 是可读业务副本，不携带签名验证资料，不能单凭 ZIP 重建运行时幂等保障。受控迁移／恢复由本轮发布检查单独验收。本增量不改变旧导出 summary 的计数口径。
