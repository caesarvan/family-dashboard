# 本人付款分类规则：设计契约

状态：供非作者评审的设计候选，尚未实现、测试或发布。基线为 `554037c25ad2b2f54d6da5d86c5b8d8a20359057`；当前户内 77 表、平台 9 表。根审查通过后，API/UI 作者按本契约实现，不把本文当作执行证据。

## 1. 最小用户闭环

本人账本的已保存付款详情 → 「为相同标题设置分类规则」→ 核对精确来源、完整标题与目标分类 → 明确保存规则 → 下次导入付款时查看规则分类预览 → 沿原确认入账 → 查看原交易和对应月预算。规则列表可明确停用。

首批只处理 `kind=payments`，只设置新入账记录的 `category`。不改金额、币种、日期、收支方向、原文件身份、去重指纹、共享范围、订单／退款关联、采购实付或旅行归集。保存规则本身不修改任何已有交易或预算。没有模型调用、外部机构访问、历史批量重分类或自动确认。

规则创建后匹配键与目标分类不可编辑；要换分类，先明确停用旧规则，再从原付款详情创建新规则。停用不可撤回，但允许为同一键新建规则。旧规则与回执保留，避免历史分类依据变成另一套含义。

## 2. 已有实现与复用边界

| 当前权威路径 | 实际行为与本次接缝 |
|---|---|
| [finance_hub.py](../finance_hub.py) `parse_import` | 原分类取文件列，缺失为「未分类」；先用它解析 `flow`，再产生指纹。本次规则处理必须在这些步骤之后。纯文件解析函数仍不读规则数据库。 |
| 同文件 `hub_preview` / `hub_confirm` | 已有重复／冲突检查、签名预览、事务内重新核对、原 requestId 回执。只给显式启用规则的新请求增加版本绑定，旧请求保持。 |
| 同文件 `hub_patch_transaction` | 已有单笔分类修正与 revision；继续作为最终人工覆盖入口，不反向修改规则。 |
| 同文件 `reconciliation_rows` / `transaction_totals` | 保留原退款分摊、重复支付排除及预算口径，不新增另一份财务总额。 |
| [finance_source_bridge.py](../finance_source_bridge.py) `ImportSession` | 新规则读写复用成员／家庭／会话复核、读快照与 `BEGIN IMMEDIATE` 写事务。 |
| [journey_finance.py](../journey_finance.py) | 参考独立操作回执、先查回执再验预览期限、读取原 requestId 的具体模式；不调用旅行归集接口或共用其表。 |
| [data_portability.py](../data_portability.py) | 扩展本人规则／回执与交易分类依据白名单，不扩展共享导出。 |

原导入接口、金额列／收支方向映射、请求恢复分别见 [财务 API](FINANCE-API.md)、[导入](FINANCE-IMPORT.md) 和[收支方向](FINANCE-FLOW-ACCEPTANCE.md)。

## 3. 匹配与权限

- 匹配键为 `(当前户数据库, 当前 owner, source, title)`。`source` 使用既有五值 `generic/alipay/wechat/taobao/pinduoduo`，且种类必须为 `payments`；来源不同不匹配，即使标题相同。
- `title` 为 `parse_import` 已经按原规则清理后的完整字符串。仅精确逐字符比较，不做子串、正则、大小写折叠、Unicode 归一化、金额／日期猜测或商户推断。UI 必须完整展示，不能只用截断文本让用户确认。
- 创建必须引用当前本人已保存的付款 `transactionId` 和 `transactionRevision`；服务端读取来源／标题，客户端不能另传或覆盖它们。空标题、解析器占位标题「未命名记录」、损坏来源／类型均拒绝创建。交易的分类可与规则目标不同。
- `category` 沿原 `clean(value, 60, required=True)`：字符串、清理后 1–60 字符，拒绝 NUL／无效编码。允许既有自由分类，不新增固定分类枚举。
- 规则只属于本人。管理员身份、伙伴、家庭共享交易、`includeShared`、TV 均不授予他人的规则权限。家庭由现有空间路由确定，不接受 owner／household 参数。
- 所有新接口需要当前有效成员；写入需同源 JSON 与 CSRF。列表、预览、回执读取在开始和返回前鲜读身份；写入在取得写锁后及提交前复核。失效身份优先于业务结果，不把迟到的私有规则或回执交给新身份。
- 新接口统一 `Cache-Control: private, no-store`；日志不输出标题、规则内容、预览 token 或原文件。当前会话登记／last_seen 例行记账不等于业务写入。

创建之后删除或修改来源交易，不自动停用规则；它已经是用户明确保存的匹配条件。停用只要求本人规则权限和规则 CAS，不再依赖来源交易存在。

## 4. 持久化建议：两张新表

不将规则塞进共享 `settings`、助理记忆或 `hub_import_receipts`。后者绑定的是原文件导入结果，不能承载规则创建／停用的另一种语义。

建议独立 `finance_category_rules.py` 提供 `SCHEMA_SQL`、事务内 `init_schema`、严格投影、规则快照／应用纯 helper、接口注册与本人导出。它不导入 `finance_hub`，以免后者调用规则 helper 时循环依赖；注册时由 `finance_hub` 传入现有文本清理函数及常量。

| 表 | 必需列／约束 |
|---|---|
| `hub_category_rules` | `id` 24 位小写 hex 主键；`owner` 外键 users；`source` 五值；`title`；`category`；`status` 为 active/disabled；正整数 `revision` 初始 1；`created_from_transaction_id`；UTC `created_at/updated_at`。原交易 ID 无外键，避免删除交易破坏规则与历史。 |
| `hub_category_rule_operations` | `owner` 外键 users；`request_id` 32 位小写 hex；`payload_hash`；`operation` 为 create/disable；`rule_id`；`result` 为最小业务回执 JSON；UTC `completed_at`；主键 `(owner, request_id)`。不保存明文 token，无 rule/transaction 级联删除。 |

精确索引：规则部分唯一索引 `(owner, source, title) WHERE status='active'`，文本比较用 SQLite BINARY；规则列表索引 `(owner, created_at, id)`；回执主键满足查询。CHECK 应约束枚举、严格整数 revision 和必要文本长度；不新增序列或触发器。

每人最多 200 条 active、2000 条包含 disabled 的规则，最多 4000 个成功操作回执／4 MiB 回执正文，单回执不超过 1024 UTF-8 字节。首次新操作在事务中检查容量；旧回执读取／原样重放不因达到上限而失效。不自动清理历史，达到限制时拒绝新建并说明原记录保持。

因此建议明确 **77→79 户内表，平台仍 9**。初始化只在显式事务内逐条执行 DDL，不调用会隐式 commit 的 `executescript`，不在 GET 中建表。未来本批迁移需完整备份、旧 77 表／DDL／行／settings／序列保全、两新表为空，以及非空 79 表稳态恢复；这属于后续独立发布任务，不能改旧固定 75→77 工具的验收总表数。

规则读取遇缺表或损坏行时拒绝该请求，不静默当作空规则集合或跳过坏规则；旧客户端未启用规则的导入保持原独立路径。

## 5. API / DTO

以下为拟新增协议，JSON 不接受重复键、未知字段或额外 URL 参数。新写接口正文上限 16 KiB。ID 为小写 hex；revision 为 `1..9007199254740991` 的严格整数，拒绝布尔、浮点和数值字符串。

### 5.1 规则对象与版本

`Rule` 的精确业务字段：

```text
{id, source, title, category, status, revision,
 createdFromTransactionId, createdAt, updatedAt}
```

不返回 owner。`rulesVersion` 是当前本人全部规则（含 disabled）按 id 升序投影为 `[id,revision,status,source,title,category]` 数组后，使用 UTF-8、`ensure_ascii=False`、紧凑分隔符、无尾换行的规范 JSON SHA-256。空集合也有稳定摘要。任何新建／停用都会变更此摘要；同人其它规则改变造成保守的重新预览是预期行为。

### 5.2 GET `/api/finance-hub/category-rules`

参数仅 `status=active|disabled|all`（默认 active）、可选 source、`page`（默认 0，规范十进制非负整数，最多 8 位）。固定 `pageSize=20`，排序 `created_at DESC, id ASC`；在同一快照计算列表、total 和 rulesVersion。

```text
{version:1, rules:Rule[], page, pageSize:20, total, hasMore, rulesVersion}
```

UI 翻页若发现 rulesVersion 改变，丢弃旧页结果并明确回到当前筛选第一页重新 GET；不拼接两个版本。列表只有本人条件，不提供他人规则计数。

### 5.3 POST `/api/finance-hub/category-rules/preview`

请求只接受以下两种形状：

```text
create:  {operation:"create", transactionId, transactionRevision, category}
disable: {operation:"disable", ruleId, revision}
```

create 要求原记录当前属于本人、payments、revision 相等、合法来源／标题，且不存在同键 active 规则。disable 要求原规则属于本人、active、revision 相等。相同键同分类也不静默当新建成功，而返回冲突，引导读取已有规则。

返回：

```text
{version:1, operation, rule:Rule|null,
 proposal:{source,title,category,status},
 sourceTransaction:{id,revision}|null,
 rulesVersion, previewToken, expiresInSeconds:600, expiresAt}
```

create 的 rule=null、sourceTransaction 为原记录，proposal.status=active；disable 的 rule 为当前规则、sourceTransaction=null、proposal.status=disabled。预览不写规则、回执、交易或审计。

使用独立 signer salt `finance-category-rule-preview-v1`。token 绑定协议版本、当前成员／家庭／会话身份、规范操作、rulesVersion、原交易或规则依赖与随机 nonce。源交易修改／删除、规则 CAS／集合变化均使首次确认失败；不得以 token 中旧标题替代当前原行读取。

### 5.4 POST `/api/finance-hub/category-rules/confirm`

```text
request: {requestId, previewToken}
response: {version:1, receipt:RuleReceipt, replayed:boolean}
RuleReceipt: {requestId,operation,ruleId,revision,status,completedAt}
```

requestId 必须为随机 32 位 hex，previewToken 为 20–12000 字符。首次确认和原样重放均 HTTP 200。创建回执 revision=1/status=active；停用为旧 revision+1/status=disabled。回执表示操作发生时状态，不声称规则目前仍 active。

在 `ImportSession.write()` 的 `BEGIN IMMEDIATE` 内按以下顺序执行：

1. 复核当前身份；先按本人 requestId 查回执。规范完整请求（含原 token）的摘要相同则返回原回执，不再验 token 期限、当前规则状态或来源交易。摘要不同返回 409 `request_conflict`。
2. 未有回执才校验签名、期限、身份、rulesVersion 和全部原行依赖，重新检查 active 唯一键／CAS／容量。不能用客户端 preview DTO 执行写入。
3. 新建一条规则，或 CAS 将 active 规则改 disabled、revision+1；保存回执，并只新增一次 `finance.category_rule.create`／`finance.category_rule.disable` 审计（target=ruleId），settings.meta 沿现有 audit 恰加 1。
4. 提交前再核身份。任一步失败整笔回滚；不出现规则已写但无回执、审计或 meta 的半成品。

两份同版本预览并发确认，最多一个首次写入；另一个冲突。两个不同 requestId 不能为同键制造两条 active。回执查读不新增审计或修改规则版本。

### 5.5 GET `/api/finance-hub/category-rules/operations/<requestId>`

```text
{version:1, requestId, found:boolean, receipt:RuleReceipt|null}
```

HTTP 200；找不到回执只表示本次读取尚未观察到它，不证明旧请求未提交，也不自动重新 POST。新会话下同一有效成员可以读自己的历史回执；旧／撤销会话不能读。不存在或他人的 requestId 均只返回本人范围的 found=false。

### 5.6 错误与恢复

新规则 API 沿 `{error,code}`：400 `invalid_request`（字段、类型、格式）；401 `session_changed`；403 `forbidden`（TV／CSRF／来源）；404 `not_found`（原记录／规则不可读）；409 `conflict`（版本、唯一键、依赖变化），`request_conflict` 或 `preview_expired`；409 `capacity_exceeded`；503 `unavailable`（SQLite busy/locked，不吞其它 SQLite 异常）。超正文上限沿公共 413。

首次明确拒绝可保留草稿后重新预览。超时、断网或无法解析响应为未知，保留原 requestId/原确认体；即使后来收到拒绝，也不能抹掉先前的未知提交。

## 6. 接入现有付款导入，不改变旧协议

### 6.1 显式启用与预览绑定

既有 preview/confirm 请求新增可选严格布尔 `applyCategoryRules`。缺失或 false 走旧逻辑、旧 payload 摘要及旧 signer 形状；不能因本人已有规则而偷偷应用。true 仅允许 payments，orders=true 拒绝；不更改 mapping v1/v2 的键或语义。

新 Expo 付款导入显示「使用本人分类规则」开关，初始选中；订单不显示且不发送此字段。切换开关、文件、来源或字段映射均废弃旧 previewToken，保留其余输入，要求重新预览。旧客户端缺字段仍完全保留原行为。

true 必须纳入导入 payload 摘要；在同一授权快照读取规则，并使用独立 salt `household-finance-category-preview-v1`，签名内容包含 `{version:1,owner,context,digest,rulesVersion}`。当前规则数为零也绑定空摘要，防止预览后新建规则改变确认含义。工作表／表头发现仍不读规则、不生成确认 token，也不返回分类应用统计。

### 6.2 行处理顺序与返回字段

顺序固定为：原文件解析 → 原 `flow` 和 fingerprint/sourceRowKey 产生 → 原重复／冲突判断 → 只给拟新增 payments 行匹配规则 → 原币汇总。绝不把规则目标分类再次传给 `normalized_flow`。

true 的普通预览在原 DTO 上增加：

```text
categoryRules: {version:1, rulesVersion, matchedRows, changedRows}
rows[]: 原字段 + category + sourceCategory
        + categoryRule: null|{id,revision,category}
        + retainedCategory: string|null
```

sourceCategory 为原解析分类，包括原缺失时的「未分类」；category 为本次候选分类。拟新增且命中时，categoryRule 标明依据；相同目标分类仍计 matchedRows，但不计 changedRows。统计只计非重复的新候选行。

重复／冲突行不应用规则，categoryRule=null；单一已存匹配的 retainedCategory 是其当前分类，多个歧义匹配为 null。UI 明示「原记录保持」，不得把输入行 category 说成旧账本已更新。并发确认时的实际重复／冲突判断仍以事务内数据为准。

true 的首次确认仍先走原 `hub_import_receipts` 的 requestId＋完整 payload/token 摘要恢复；只有未有回执才在原写事务里重核签名、context、rulesVersion、文件解析和重复检查，并应用当前同版本规则。集合变更返回 409 `category_rules_changed`，零入账，要求重新预览；不自动采用新规则或退回原分类。原样已成功请求即使规则停用／被替代、token 过期仍返回原回执。

新增入账交易记录：

```text
categoryProvenance: {
  version:1, sourceCategory,
  appliedRule:null|{id,revision,category}, manuallyOverridden:false
}
```

仅此新模式保存该字段；旧记录不回填猜测。appliedRule 是入账时快照，停用／替换规则不改它。原人工 PATCH 实际改变 category 时，若已有该字段，则保留 sourceCategory/appliedRule 并将 manuallyOverridden 置 true；仅方向／共享变更或原分类值原样回传不改变此标记。曾人工修改后再改回规则分类仍保留 true。字段是历史依据，不把旧规则状态当当前授权或当前分类。

true 的成功导入回执在原字段上增加 `categoryRules:{version:1,rulesVersion,applied,changed}`，数值只数本次实际 INSERT 的行；存入原回执，GET／重放返回原值。旧模式回执不增加该字段。已有 requestId、receiptId、resultMonths 和“删除后明确重导”等原合同不变。

### 6.3 财务语义

- expense/income/refund/transfer/unknown/excluded 的 flow 原样保留。分类命中不能使 unknown 成为 income，也不能把还款／转账计入支出。
- orders 从不应用规则；商品明细、订单金额和付款对账不变。
- refund 未分配部分使用其自身分类；已经确认分配的退款仍按原付款当前分类分摊。规则不建立退款关系，不双减金额；跨月和不同币种沿原口径。
- 原记录人工改分类后重导，仍跳过／冲突保留原记录，不被规则覆盖。分类变化不重新计算 fingerprint/sourceRowKey，也不成为新增交易理由。
- 新付款入账后，其分类自然进入现有同币种预算／支出计算；预算限额、公共荷包、共享预算、采购 actual 和旅行 paid 不写入。创建／停用规则自身不改变任何金额统计。

## 7. UI 状态与恢复

复用本人交易详情；有未保存的分类／方向／共享草稿时，先沿现有行为保存或明确放弃，不暗中提交这些草稿。新规则入口只对有效 payments 提供。列表入口为财务 →「我的分类规则」，可筛 active/disabled/all、来源并分页。

规则状态链：`editing → previewing → reviewed → confirming → receipt`；读取失败回 editing，确认未知进入 `unknown`。reviewed 展示完整匹配键、「只影响以后确认的新付款」与目标分类，确认按钮为「确认保存规则」／「确认停用规则」。没有按匹配自动保存或自动重发。

unknown 时只允许核对原请求及受保护的退出操作，不能另起保存；先 GET 原 operations。found=true 展示历史回执，再明确刷新列表取得当前状态。found=false 保留未知；内存中仍有原 token 时，用户可在核对后明确重试原确认体。刷新后只恢复最小 marker，再鲜读 `/me` 和原 operations，不自动恢复 POST。

持久 marker 只保存 `{memberIdentity,requestId}`，不放规则文本、分类、文件、token 或完整 DTO。身份键使用现有包含家庭的成员 identity。丢失 token 且仍 found=false 时，用户可明确「结束本地核对」后重新读取／预览；按钮说明旧请求仍可能完成。新的预览依赖和 active 唯一键必须阻止迟到原提交造成双写；不得通过删除原 requestId 的服务端证据实现退出。

隐藏／离线立即遮蔽私有列表和预览，取消后续读派发，确认未知状态不伪装取消；恢复时先核 `/me`。身份变化清空标题、输入、回执及 marker；迟到响应不得安装。每条读取链使用统一有界期限，不启动后台扫描。原文件输入与交易详情草稿遵循已有离开保护。

规则预览里的类别与导入行采用文本渲染，不作为 HTML；规则管理不开放 TV、公共资金页、伙伴页面或共享搜索入口。旧人工分类仍可覆盖新入账结果，不自动把人工修改变成新规则。

## 8. 本人导出

在当前本人 ZIP 的 personal 段新增 `categoryRules:Rule[]`（含停用历史）与 `categoryRuleOperations:RuleReceipt[]`；summary 提供这两个本人计数。只输出本协议明确列出的业务字段，不输出 owner、token、payload_hash、context 或内部签名摘要。

本人 transactions JSON 中保留经过类型白名单核对的 categoryProvenance；旧无字段保持缺失。本人 transactionImportReceipts 的导出白名单增加本协议 categoryRules 统计。现有交易 CSV 保持原列及当前 category，不为首批另造可执行规则导入／恢复格式；完整依据在 JSON。

`includeShared=true` 也不导出他人规则／回执／categoryProvenance；共享汇总不能出现 ruleId、来源标题或匹配条件。导出结束前继续按现有 ImportSession 复核身份。

## 9. 实现责任边界

| 必须接线的模块 | 最小修改 |
|---|---|
| 新 `finance_category_rules.py` | 两表 DDL、无隐式 commit 的 initializer、本人规则 API／操作回执、快照与确定性应用、导出白名单。 |
| `finance_hub.py` | 注册新模块；新导入开关与签名／版本绑定；事务内应用与原回执统计；人工分类 PATCH 保留历史依据。旧解析指纹／flow 算法不改。 |
| `data_portability.py` | 本人 summary/JSON 规则及回执、嵌套 provenance 白名单。 |
| `Dockerfile` | 精确 COPY 新模块；`app.py` 已调用 register_finance_hub，可由后者注册，无必要不增加第二处注册。 |
| `frontend/src/lib/financeImport.ts`、`FinanceImportPanel.tsx` | 严格解析可选 DTO、付款开关、旧预览失效、规则显示与既有导入恢复。 |
| `frontend/src/screens/FinanceScreen.tsx`、财务 DTO 类型 | 原详情入口、当前分类／历史依据文案、原草稿保护与规则列表导航。 |
| 新 `frontend/src/lib/financeCategoryRules.ts` 与独立规则面板 | 上述状态机、严格 DTO、统一读取期限、最小 marker／原 requestId 恢复；不把全部逻辑堆入 FinanceScreen。 |
| 聚焦 API/UI 测试及现有接口／模型／导出文档 | 按下列场景验证；实际文件范围由根分工后确认。 |

新增模块改变运行闭包，并有 77→79 DDL。迁移／发布白名单、备份与恢复另由根安排独立适配；不能沿当前 77→77 source-update profile 假装无迁移，也不能预填将来的包、镜像或 Linux PASS。

## 10. 最小可验证验收

全部只用虚构成员、两户临时 SQLite 和合成文件。规则／预览测试不调用模型或外部机构。

1. **完整手机闭环：** 本人现存付款 → 创建规则预览／确认 → 新月份不同原交易导入 → 显示原分类和规则目标 → 明确入账 → 原 ID 详情、来源依据、当月分类预算均正确；规则保存阶段账本不变。
2. **精确匹配：** 相同来源完整标题命中；其它来源、大小写差异、仅包含标题、orders 不命中；placeholder 拒绝。两成员同名规则互不影响，跨户／TV 不能读取或创建。
3. **权限与事务：** 预览后删改源交易、停用规则、换成员／撤会话；锁冲突、唯一键竞争、审计或回执写失败。首次确认必须明确失败或整笔回滚，旧表和设置不能半写。
4. **规则未知结果：** 真实 create/disable 已 commit 后丢响应，GET 原 requestId 返回回执，没有第二次业务写／audit；整页刷新只恢复 marker；换 token 复用 ID 冲突，原 token 过期后仍能恢复已成功结果。
5. **导入版本与未知结果：** true 预览后新建／停用任何本人规则，旧首次确认零入账并要求新预览；真实导入已 commit 后规则变化，仍按原 requestId 恢复原统计，无第二批交易。缺字段／false 的旧预览、旧 token 和旧回执保留。
6. **分类不改变交易身份：** 带转账／还款／unknown／refund 的文件分类命中后，逐行原 flow、fingerprint、sourceRowKey、金额／日期／来源不变。人工修正旧分类后重导不覆盖旧值，也不新建重复记录。
7. **退款／预算边界：** 确认的跨月部分退款继续使用原付款当前分类，未分配部分用退款自身分类，币种独立；orders、重复支付、transfer/unknown 不进入新增支出。采购实付、旅行归集／paid 和公共余额原样保留。
8. **停用／替换及导出：** 原交易删除后仍可停用；停用不改旧入账，下一次新导入不命中；显式创建替代规则有新 ID、旧 provenance 不变。本人 JSON 可追溯，伙伴／共享导出无新私有字段。验证空／非空两表初始化、现有库保全及容量上限。

真正浏览器可收束为手机完整导入闭环和桌面未知恢复／版本竞争／身份隔离两条流程；更细输入组合由真实 API/SQLite 与聚焦前端检查覆盖。A–D 本人完整验收、真实账单样本和生产迁移均另列，不由合成结果替代。
