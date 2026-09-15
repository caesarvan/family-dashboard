# 财务中枢 HTTP 契约

**当前版本：2026-09-15 20:23:00（北京时间），镜像 `sha256:651ecfd6bdb65cf04bb8778c8657a8ec0f27a123940683a44a8b9931a5f22352`。** 旅行资料、完整细项展示与分段定位已发布，保留此前全部模块；106 个方法／路径模板、43 张户内表（41 业务 + 2 认证）及 2 张平台表。源码与文档数量见 [README](../README.md) 及交接清单；测试、迁移和实际接入边界见 [VALIDATION](VALIDATION.md)。

按 2026-09-15 的 [finance_hub.py](../finance_hub.py) 核对。该文件直接声明的既有功能共 15 个 HTTP 操作；其中 2 个账单／订单文件导入接口详见 [FINANCE-IMPORT](FINANCE-IMPORT.md)，本文补齐读取、共享汇总、交易核对、订单/支付/退款关联、预算和投资记录。基础财务快照 `/api/finance`、`/api/private-finance` 与历史基线接口仍见 [API](API.md)，不能与新账本重复相加。

**发布状态：XLSX 工作表名称发现已于 2026-09-15 06:50:21 发布。** 05:47:43 的金额列与对账保护继续保留；完整组合与真实接入边界见 [VALIDATION](VALIDATION.md)。

**投资增量已于 2026-09-15 08:56:01 发布：** 新 [investment_import.py](../investment_import.py) 由 `register_finance_hub()` 登记三个持仓模板／预览／确认接口，完整契约见 [投资持仓整理表导入](INVESTMENT-IMPORT.md)。不改变已发布账单／订单导入的请求和签名规则。

## 通用约定

- 所有接口要求成员登录，电视无权访问；所有写请求为 JSON，带有效 `X-CSRF-Token` 且同源。
- 当前成员由服务端会话确定。个人交易、订单、投资、预算、批次仅该成员可读写，不能通过 `owner` 参数选择他人；多家庭由外层空间路由隔离数据库。
- `amountCents`、`costCents`、`valueCents` 等整数表示 **原币金额乘以 100**。币种由 `currency` 单独表达；不是都转换为人民币，也不自动查询汇率。
- 输入金额字段 `amount`、`cost`、`value` 为原币金额，建议使用十进制字符串，例如 `"125.50"`。接受有限非负数，最多两位小数，单项上限 `1,000,000,000,000` 原币单位；拒绝布尔值、负值、NaN/Infinity 和超过两位小数的数值。`value` 独有的空串/NULL 表示估值未知。
- `currency` 支持三位字母，统一转大写；也归一化已实现的人民币/RMB、美元、日元、港币、欧元别名。客户端宜直接发送 CNY/USD/JPY/HKD/EUR 等代码。接口不会通过币种代码验证某一金融机构是否支持该币种。
- 月份格式 `YYYY-MM`，日期 `YYYY-MM-DD` 且必须存在；默认月份按 `Asia/Shanghai`。`importedAt`、`checkedAt` 使用 UTC ISO 时间。
- 可修改记录使用整数 `revision`，不是字符串或布尔值；过期或缺少要求的版本返回 409，不自动覆盖。
- 除投资创建成功返回 201 外，成功响应通常为 200。错误格式 `{"error":"可读说明"}`；未登录 401，电视/CSRF/同源不满足 403，错误字段 400，非本人或不存在的具体记录 404，版本冲突 409，请求体过大 413，文件解析忙 429。

<a id="采购实付核对独立候选未上线"></a>

## 采购实付核对

**适用发布记录：2026-09-15 12:11:36，镜像 `sha256:1167dffd3b7e234d43460442acfe0d30959370c90c7e8147a1b30baa0e2380b5`。** [shopping_settlement.py](../shopping_settlement.py) 由 `app.py` 在财务中枢之后单独注册，增加三个接口及两张本人私有表；该发布批次索引为 98 个方法／路径模板、37 张户内表与 2 张平台表；这是该批次的历史范围。上文各功能的既有发布日期保留其历史范围。完整请求、响应和错误边界见 [采购实付核对契约](SHOPPING-SETTLEMENT.md)，本次组合验收见 [VALIDATION](VALIDATION.md)。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/finance-hub/shopping-settlements/context` | 本人的付款、关联及本家庭共享采购；可用 `transactionId/shoppingId/linkId/q/page` 聚焦与分页 |
| POST | `/api/finance-hub/shopping-settlements/preview` | `operation: apply/update/revoke`，只预览共享字段变化，返回十分钟确认令牌 |
| POST | `/api/finance-hub/shopping-settlements/confirm` | 只提交 `previewToken`，事务内复核本人会话、来源、分配和采购版本后提交或重放回执 |

此处金额请求只用 **CNY 整数分** `amountCents`，范围 `0..100000000000`，不适用上文手工账本的原币 `amount` 字符串规则。一次确认替换整项采购 `actual`；`done` 为独立必填布尔值，不因付款而自动完成。共享投影仅含这两个字段，私人付款、账户、来源与关联 ID 不写入共享实体；不改变原交易可见性、公共余额、私人月预算或旅行 `paid`。

同一付款的有效采购分配不能超过明确退款后的净额；订单核对的 `allocatedCents` 不在这里重复扣减。更新保留同一付款；更换付款需先明确解绑。默认解绑保留采购当前值，选择恢复则必须匹配最近一次确认写入的采购版本和 `actual/done`，否则 409，不自动改为另一种操作。来源修改／删除使关联显示待核对，不自动重算共享实付；重复确认返回历史结果，不复活已删除采购。预览不保存到数据库，确认才保存私有链接与回执。本人副本字段见 [导出白名单](PORTABILITY.md#采购实付关联与回执)。

## 1. GET `/api/finance-hub/overview?month=YYYY-MM`

返回当前成员的月份概览。省略月份时使用北京时间当前月。

| 字段 | 含义 |
| --- | --- |
| `month` | 当前筛选月份 |
| `transactions` | 该月记录，按日期和 id 倒序，最多 500 条 |
| `transactionCount` / `totalRecordCount` | 该月记录数 / 该成员全部月份记录数 |
| `availableMonths` | 候选新增；`[{month,recordCount}]`，当前本人实际现存记录按月份倒序分组；包括保留的订单／排除记录，不是有效消费次数 |
| `truncated` | 该月超过 500 条时为 true；汇总仍覆盖该月全部记录 |
| `totals` | 按币种计算该月流水和订单，字段见下 |
| `investments` / `investmentTotals` | 本人全部投资记录及分币种持仓汇总，不随 month 筛选 |
| `budgets` | 本人该月预算以及已记录支出、剩余额度 |
| `imports` | 本人最近 12 个有新记录入账的批次，不随 month 筛选 |
| `coverage` | 仅已导入记录的覆盖说明 |
| `connectors` | 各平台 `mode: csv`、`status: manual_import`；表示文件导入模式而非账户自动连接。XLSX 同样属于此手动文件通道 |
| `institutionsStatus` | 固定为 `manual_dated_records`，不表示银行/券商已授权 |

空数据示例：

```json
{
  "month":"2026-09",
  "transactions":[],
  "transactionCount":0,
  "totalRecordCount":0,
  "availableMonths":[],
  "truncated":false,
  "totals":[],
  "investments":[],
  "investmentTotals":[],
  "budgets":[],
  "imports":[],
  "coverage":"仅已导入记录；候选关联须本人确认，已确认重复才排除，不能视为全部财务资产。",
  "connectors":[{"id":"alipay","mode":"csv","status":"manual_import"}],
  "institutionsStatus":"manual_dated_records"
}
```

上例的 `connectors` 为节选，实际还包含 wechat、taobao、pinduoduo。

<a id="实际月份导航与确认回执独立候选"></a>

### 实际月份导航与确认回执

`month` 仍是调用方筛选值，不自动修改 API 请求的月份。即使该月 `transactionCount=0`，其他月份存在记录时 `availableMonths` 仍返回所有实际月份，条数合计等于 `totalRecordCount`；它与 `transactions` 的 500 条展示限制无关。字段只出现在本人成员接口，不进入共享汇总或电视状态。

账单／订单确认接口增加 `confirmedAt` 和 `resultMonths`，详见 [导入确认回执](FINANCE-IMPORT.md#导入确认回执与实际月份)。后者按本次确认实际保留的唯一记录分月，重复输入行不重复计数，冲突采用原记录日期；不能从预览日期或本次拟新增行推导。前端将单月直接定位，跨月提供各月入口；确认已经成功而读取账本失败时仅重试 GET。它没有改变删除后明确重导入、原有金额核对或内容去重语义。

### 消费观察与实付账本的接口边界

[独立消费观察](SPENDING-OBSERVATIONS.md) 复用来源桥接的三个 `/api/finance-baseline/imports/...` 方法／路径，以 `mode=spending_observation` 分派；它们不是本文件 `finance-hub/imports` 的别名。消费观察保存已生成报告的本人月度快照，不插入此账本，也不改变订单／付款关联、预算、采购实付、投资或公共余额。

### 交易对象

| 字段 | 含义 |
| --- | --- |
| `id` / `revision` | 本地记录标识与当前版本 |
| `date` / `amountCents` / `currency` | 交易日期、原币百分之一单位金额、币种 |
| `title` / `category` | 标题（最多 200 字符）、分类（最多 60 字符） |
| `externalId` / `status` | 文件中的原交易编号和状态；不是实时平台查询结果 |
| `merchantOrderId` / `paymentId` / `originalTransactionId` | 可选商户订单号、支付号和原交易号；新导入保留的匹配证据，旧记录可能缺省 |
| `source` | generic/alipay/wechat/taobao/pinduoduo |
| `kind` | payments 或 orders |
| `flow` | expense/income/refund/transfer/unknown/excluded |
| `fingerprint` | 原始导入去重标识，核对分类时不重算 |
| `visibility` | 初始为 private；仅明确标记的 payments 消费/退款允许 shared |
| `importedAt` / `checkedAt` | 入账时间 / 最近核对时间；未核对时后者为 NULL |
| `reconciliation` | overview 和对账详情中的派生关联状态；不改写原始金额，字段见下 |

当前没有单独的流水分页或搜索接口；500 条显示上限是可见列表限制，不能把它误当成汇总只含 500 条。每位成员最多保留 20,000 条账单/订单记录。

### `totals[]` 口径

每个币种一项，字段为 `currency`、`count`、`expenseCents`、`incomeCents`、`refundCents`、`transferCents`、`unknownCents`、`excludedCents`、`orderCents`、`categories`、`netSpendCents`、`recordedSurplusCents`，另有 `duplicateCents` 和 `duplicateCount` 表示本人确认后排除的重复支付/退款。

- payments 按 flow 分桶；`netSpendCents = expenseCents - refundCents`，`recordedSurplusCents = incomeCents - netSpendCents`。这只是已记录流水结余，不是账户余额。
- `categories` 是消费加、退款减的分类映射。已确认关联的退款分配金额使用原付款的当前分类，未分配的退款仍使用自身分类；没有确认关系时不推断分类。
- orders 中未被 excluded 的记录进入 `orderCents`，不再次计入支付收支；订单的退款/未知状态仍需核对，不能把订单总额当作实际净支付。
- transfer、unknown、excluded 不进入收入/支出；`count` 包含该币种所选月份的全部记录，包括订单与排除记录。
- 相同导入指纹的重传去重不等于跨平台支付对账。不同文件中相似支付可显示为候选，只有本人确认 `duplicate` 后左侧记录才从有效收支和预算排除。`count` 仍为原始记录数；`duplicateCount` 单列排除数量，原始记录可以查阅。

### `investmentTotals[]` 口径

字段为 `currency`、`count`、`costCents`、`valuedCostCents`、`valueCents`、`unvaluedCount`、`unrealizedGainCents`、`allocation`。

`costCents` 覆盖全部记录；只有已估值项目计入 `valuedCostCents` 与 `valueCents`。`unrealizedGainCents = valueCents - valuedCostCents`，不会把未估值项目当作价值归零。`allocation[]` 含 `assetType`、`valueCents`、`percent`；百分比只基于同币种已估值部分，总估值为零时为 NULL。不同日期的手动记录一并汇总，每个项目的 `asOf` 必须保留展示。

## 2. GET `/api/finance-hub/shared?month=YYYY-MM`

返回当前家庭所有成员逐笔选择共享的消费和退款汇总。仍要求成员登录，不向电视开放该接口。

```json
{
  "month":"2026-09",
  "totals":[{"currency":"CNY","expenseCents":15000,"refundCents":2000,"netSpendCents":13000,"count":2}],
  "note":"仅成员逐笔确认的共同消费，不自动写入公共荷包余额。"
}
```

每个 totals 项只输出四个金额/计数字段与币种，共五个字段，不返回 owner、账户、来源、交易标题、编号、分类、收入或投资。只有 `visibility=shared`、`kind=payments`、`flow=expense/refund`、日期在该月的记录纳入。

本人确认排除的重复记录不进入共同汇总，包括 `count`；保留记录继续使用其原来的 private/shared 范围。关联不会自动把个人付款或退款变成共同消费。

## 3. GET `/api/finance-hub/template?kind=payments`

`kind` 可选 payments/orders，默认 payments。返回 `filename`、`csv`、`encoding: UTF-8` 和 `note`。不是文件流；前端生成下载 Blob。模板仅含固定虚构示例，使用前应替换。

CSV 表头为 `date,title,amount,currency,flow,category,id,status`。金额是原币金额，不是分；明确 `flow`，退款金额也填正数。文件格式的完整规则见 [FINANCE-IMPORT](FINANCE-IMPORT.md)。

## 4. PATCH `/api/finance-hub/transactions/<id>`

只允许核对 `category`、`flow`、`visibility`，至少携带正确的 `revision`；未知字段拒绝。金额、日期、来源和编号不可通过本接口改写。

```json
{"revision":1,"category":"餐饮","flow":"expense","visibility":"shared"}
```

返回完整更新后的交易对象，`revision` 增加 1，`checkedAt` 设为当前时间。

`category` 为 1～60 字符。`flow` 只能是上述六个值。共享只允许 payments 的 expense/refund；把已经共享的消费改成 income/transfer/unknown/excluded 时，必须同次请求将 `visibility` 改为 private，否则返回 400。订单不能加入该共同消费汇总。

该接口即使只提交合法 revision，也会作为一次核对更新版本和时间；客户端不应把空 PATCH 用作无副作用的探测。

有活动对账关系时改变 flow 返回 409，须先撤销关联。分类和共享范围仍可独立核对；关联退款的派生预算分类随原付款分类更新。

## 5. DELETE `/api/finance-hub/transactions/<id>`

```json
{"revision":2}
```

成功返回 `{"deleted":true}`。仅删除本人本地记录；不会向原平台删除账单。删除后再导入原文件会重新入账，因为当前没有永久删除墓碑。批次历史是原导入回执，不随逐笔删除回写其 `importedCount`。

有活动对账关系时删除返回 409；撤销所有活动关系后可以删除。撤销历史保留原本的记录 ID，详情中的 `left/right` 在原记录已删除后为 NULL。

## 6. POST `/api/finance-hub/investments`

```json
{
  "name":"虚构资产示例",
  "institution":"示例机构",
  "assetType":"基金",
  "currency":"USD",
  "quantity":"12.5",
  "cost":"100.00",
  "value":"120.00",
  "asOf":"2026-09-01",
  "note":"合成数据，仅用于接口示例"
}
```

| 输入字段 | 约束 |
| --- | --- |
| `name` / `institution` | 必填，各 1～120 字符；机构可自填，不会建立机构连接 |
| `assetType` | 必填，1～60 字符，自由类别；如存款、基金、股票、理财 |
| `currency` | 必填，按通用币种规则处理 |
| `quantity` | 可省略或空串；有值时必须是字符串，整数部分最多 15 位、小数最多 8 位，非负。不是自动计算估值的单价乘数 |
| `cost` | 必填，原币持仓总成本 |
| `value` | 可省略、NULL 或空串表示未估值；否则为原币总估值 |
| `asOf` | 必填，存在的日期；表示用户提供的核对日期，不是服务器验证过的行情时间 |
| `note` | 可选，最多 1000 字符 |

未知字段拒绝，不能提交 `visibility=shared`。每位成员最多 300 项。成功为 201，返回 `id`、`revision:1`、标准化文本/币种/数量/日期/备注，输入 `cost/value` 转换为 `costCents/valueCents`，并固定 `valuationSource: manual`、`visibility: private`。

```json
{
  "id":"synthetic-investment-id",
  "revision":1,
  "name":"虚构资产示例",
  "institution":"示例机构",
  "assetType":"基金",
  "currency":"USD",
  "quantity":"12.5",
  "costCents":10000,
  "valueCents":12000,
  "asOf":"2026-09-01",
  "note":"合成数据，仅用于接口示例",
  "valuationSource":"manual",
  "visibility":"private"
}
```

没有独立 GET 投资列表/单项接口，使用 overview 的 `investments`。

## 7. PATCH `/api/finance-hub/investments/<id>`

提交 **整份投资输入对象**，字段与 POST 相同，并附上当前 `revision`。这不是仅传变化字段的局部合并：name/institution/assetType/currency/cost/asOf 必须重新提交，可选字段省略将恢复默认（如 value 变为未知、note 变空）。

成功返回完整标准化对象，新 revision 为原值加 1。读取响应中的 `costCents/valueCents` 后编辑时，客户端应除以 100 转成 `cost/value`，不能直接把分当作元回传。

## 8. DELETE `/api/finance-hub/investments/<id>`

请求 `{"revision":1}`。成功为 `{"deleted":true}`。仅删除本人本地持仓，不赎回、不卖出，不修改银行/券商资产。本次发布中，文件导入持仓删除后仍保留原来源／持仓键关联，防止旧文件自动恢复记录。

<a id="投资持仓文件导入独立候选尚未部署"></a>

### 投资持仓文件导入

三条接口均要求本人登录；POST 使用同源 JSON 和 `X-CSRF-Token`。模板也不向电视或匿名开放，来源和持仓均只在当前家庭、当前成员范围查找。

| 方法 | 路径 | 请求与结果概要 |
| --- | --- | --- |
| GET | `/api/finance-hub/investments/imports/template` | `mode=sample` 返回虚构 CSV；`mode=current&sourceName=...` 返回该来源已关联及尚未关联的本人持仓，附 `recordId` 和可逆文本保护列 |
| POST | `/api/finance-hub/investments/imports/preview` | `{sourceName,file,inspectSheets?}`；`file` 为 `{name,contentBase64,encoding?,sheet?}`。返回 `fileInfo`、`rows`、`counts`、`preservedCount`、`errors/errorCount`、`warnings`、`previewToken` |
| POST | `/api/finance-hub/investments/imports/confirm` | 仅接受 `{previewToken}`；成功返回 `created/updated/unchanged/replayed/receiptId/confirmedAt` |

持仓接口不接受账单导入的 `source/kind/csv/amountColumn`。使用固定英文列的整理表，不把机构原生导出自动视为受支持格式。`cost/value` 使用小数点；千分隔只能是完整三位 ASCII 或全角逗号分组，两种逗号混用、`1,23`、`12,34.56`、货币符号及科学计数法均按行拒绝，不生成确认凭据。现有手工金额 API 的解析行为未随本增量改变。

XLSX 未指定工作表时自动只发现名称；`inspectSheets:true` 也只返回名称，不解析持仓或签发 token。选表后重新预览。任何错误行都使 `previewToken:null`，禁止部分确认；新持仓空估值为未知，已有估值不能被空值覆盖，也不能用较早日期或另一币种覆盖原记录。

有效 token 引用服务端暂存快照，期限 15 分钟，绑定本人、家庭和当前登录会话。确认在 `BEGIN IMMEDIATE` 内校验本人完整持仓、来源和关联的版本摘要，再原子写入。预览之后本人任一持仓或关联变化返回 409，需保留文件重新预览。同来源同文件的历史回执重放只返回原计数及 `replayed:true`，不覆盖后来修改或恢复删除的持仓。

手工持仓通过 `recordId` 明确关联，原 ID 保留；没有字段变化时不改原 revision。遗漏行保留原持仓，不视为清仓。所有持仓继续仅本人可见，不写消费账本、公共荷包或历史资产基线，不发起银行连接、行情查询或云端写入。四表结构见 [数据模型](DATA-MODEL.md#投资持仓导入四表)，本人导出白名单见 [个人数据副本](PORTABILITY.md#投资导入历史)；所有列、错误和回放细节以 [专文](INVESTMENT-IMPORT.md) 为准。

## 9. PUT `/api/finance-hub/budgets`

```json
{"month":"2026-09","currency":"CNY","category":"餐饮","amount":"1200.00","revision":0}
```

预算主键为当前成员、月份、币种、分类。`month/currency/amount` 必填；category 缺省为“全部”，提供时须 1～60 字符。“全部”表示同币种本月总预算，其他文字精确匹配分类，不进行分类别名推断。

新建 `revision` 为 0（可省略）；修改必须使用 overview 中当前预算的 revision。错误版本返回 409。成功 `{"saved":true,"revision":1}` 或更高版本。每位成员最多 1200 个预算键，目前没有预算删除接口。

overview 中预算对象含 `month`、`currency`、`category`、`amountCents`、`revision`、`spentCents`、`remainingCents`。总预算与分类预算各自比较，不把它们相加。`spentCents` 是已导入消费减退款，`remainingCents = amountCents - spentCents`，可能为负；导入不完整时不可当作真实可支配余额。

## 10. GET `/api/finance-hub/reconciliation?transactionId=<id>&q=<keyword>`

`transactionId` 必填且须为本人记录；可以来自其他月份，不受 overview 最近 500 条限制。可选 q 为最多 160 字符的标题或原始编号搜索词。只搜索当前成员、当前家庭已导入的同币种记录，查询与候选生成均不修改账本。

返回 `transaction`、`candidates`、`candidateCount`、`truncated`、`relations`、`note`。候选最多 40 组，关系历史最多最近 100 条（活动和已撤销）。搜索关键词不限制日期；无关键词时，完全相同编号可跨日期推荐，否则订单/重复记录要求相差不超过 7 天且金额相同，退款可在 30 天内按可分配金额推荐。`identifierMatch` 比较 externalId/merchantOrderId/paymentId/originalTransactionId 中至少三字符的完全相同值；它是匹配线索，不是原平台确认。

每个候选包含 `kind`、`left`、`right`、`maxAmountCents`、`suggestedAmountCents`、`reasons[]`、`uncertainty[]`、`identifierMatch`、`dateDistanceDays`、`sameAmount`、`score`。left/right 为当前版本的原始交易对象。score 只用于候选排序，不是准确率或自动匹配结果。没有候选时可输入另一笔的标题或编号查找；不放宽币种、归属、方向及金额上限。

| kind | 左侧 left | 右侧 right | 确认后的效果 |
| --- | --- | --- | --- |
| `order_payment` | 有效订单 | 实际 expense 付款 | 分配订单与付款金额，订单仍不重复计支出 |
| `refund_payment` | 独立 refund 退款 | 实际 expense 付款 | 仅分配输入退款额，预算分类继承对应付款 |
| `duplicate` | 本人决定从统计排除的支付/退款 | 本人决定保留的支付/退款 | 同币种、同方向、同金额；只保留右侧计入有效统计 |

`transaction.reconciliation` 派生字段：

| 字段 | 含义 |
| --- | --- |
| `duplicateOf` | 被确认重复时为保留记录 ID，否则 NULL |
| `relationCount` | 涉及本条记录的活动关系数 |
| `allocatedCents` | 订单已关联付款额、付款已关联订单额，或退款已分配原付款额 |
| `unallocatedCents` | 原金额减 allocatedCents；不等同真实未支付或未退款余额 |
| `refundedCents` | 付款已关联的独立退款分配额 |
| `remainingAfterRefundCents` | 仅 expense 付款提供：原金额减已关联退款额 |
| `categoryAllocations` | 退款的 `{category,amountCents}` 分配列表；未分配部分留在原退款分类 |

退款仍按**退款自身日期**进入月度统计。只关联 30 元到 100 元付款时，已关联退款为 30 元，余下 70 元不会被推断为全额退款。订单关联到某笔付款后，可在详情跳到该付款查看退款；系统不猜测一个付款对应多个订单时退款应分给哪个订单。

## 11. POST `/api/finance-hub/reconciliation/preview`

```json
{"kind":"refund_payment","leftId":"synthetic-refund-id","rightId":"synthetic-payment-id","amount":"30.00"}
```

仅接受 kind/leftId/rightId/amount。amount 为原币金额字符串，可省略以采用当前可分配上限；必须大于零。订单的累计分配不能超过订单金额，同一付款的订单分配合计也不能超过付款金额。退款的累计分配不能超过该独立退款金额，同一付款关联的所有退款合计不能超过付款金额。支持分次关联到**不同**记录；同一对已存在活动关系时先撤销再重建所需金额，不隐式覆盖。

duplicate 必须分配整条金额；被排除的左侧不能已有任何活动关系，右侧不能本身是被排除记录。这避免重复链、循环和已分配资金再次计入。确认前需撤销冲突关系；保留记录上已有订单和退款关联可以保留。

响应包含 `owner`、`kind`、`leftId`、`rightId`、`leftRevision`、`rightRevision`、`amountCents`、`left`、`right`、候选的理由/不确定性字段、`effect`、`previewToken`、`expiresInSeconds:1200`。预览不入账；签名绑定当前成员、家庭密钥、两个记录版本、关系类型与金额。

## 12. POST `/api/finance-hub/reconciliation/confirm`

```json
{"previewToken":"替换为对账预览响应中的令牌"}
```

仅接受 previewToken。事务内重新核对归属、双方版本、活动关系和分配上限。成功返回：

```json
{
  "relation":{"id":"synthetic-relation-id","kind":"refund_payment","leftId":"synthetic-refund-id","rightId":"synthetic-payment-id","amountCents":3000,"status":"active","revision":1,"createdAt":"2026-09-15T00:00:00+00:00","updatedAt":"2026-09-15T00:00:00+00:00"},
  "replayed":false
}
```

确认增加左右记录的 revision，并写入审计；overview 原始记录数量与原金额不变。对同一有效预览重复确认返回同一 relation、replayed=true，不重复分配或增加版本。预览过期返回 400，跨成员令牌返回 403，版本变化返回 409。已撤销关系不接受旧预览恢复；必须重新预览，重新确认后沿用关系 ID 并增加关系 revision。

## 13. POST `/api/finance-hub/reconciliation/<id>/revoke`

```json
{"revision":1}
```

只允许本人撤销自己的关系，核对关系 revision。返回 `{relation,replayed}`，relation.status 为 revoked、revision 增加 1；同时增加左右原始记录的 revision。重复同次撤销返回 replayed=true。过期版本 409，非本人/不存在 404。撤销 duplicate 会恢复左侧原记录计入统计，撤销退款关联会使对应退款金额恢复自身分类；不会删除任何原始记录或修改外部账单。

## 存储与协作边界

### XLSX 工作表名称发现

沿用 `POST /api/finance-hub/imports/preview` 与 `/api/finance-hub/imports/confirm`，不增加路由、数据库表、导出字段、依赖或环境变量。已于 2026-09-15 06:50:21 发布；本人、家庭、CSRF 与 TV 禁止访问的边界不变。

预览新增顶层 `inspectSheets`，只接受布尔值；省略或 `false` 保持正常解析，`null`、数字、字符串、数组、对象返回 400。`true` 仅接受 XLSX `file`，不能与 CSV 文本、CSV 文件或 `amountColumn` 同时使用。

```json
{
  "source":"wechat",
  "kind":"payments",
  "inspectSheets":true,
  "file":{
    "name":"synthetic-sheets.xlsx",
    "contentBase64":"REPLACE_WITH_SYNTHETIC_XLSX_BASE64",
    "sheet":""
  }
}
```

Base64 为不可直接执行的占位符，须替换为合成 XLSX 的实际字节编码。发现模式即使填写 `file.sheet`，也只列出全部普通工作表，不读取该表业务记录；客户端应留空，再要求明确选表。成功响应骨架：

```json
{
  "requiresSheetSelection":true,
  "requiresAmountSelection":false,
  "amountSelection":null,
  "fileInfo":{
    "name":"synthetic-sheets.xlsx",
    "format":"xlsx",
    "encoding":"OOXML / UTF-8",
    "sheet":null,
    "sheets":["说明页","支付账单"],
    "worksheetRows":null,
    "note":"仅列出工作表名称，尚未解析记录或核对单元格。选择账单工作表后再检查金额与预览。"
  },
  "rows":[],"errors":[],"totals":[],"warnings":[],
  "newCount":0,"duplicateCount":0,"errorCount":0,
  "previewToken":null,"expiresInSeconds":1200
}
```

HTTP 200 只表示名称列表已生成。列表包括隐藏的普通工作表，也可能包含说明页、空表或公式表；尚未解析业务记录，不表示单元格有效。计数 0 不证明没有交易或错误；`expiresInSeconds` 是通用字段，此时没有有效令牌。

选表后保留原文件及来源，设置 `file.sheet`，移除 `inspectSheets`、`amountColumn` 并清空旧 `previewToken`，重新正常预览。正常预览返回 `requiresSheetSelection:false`，再沿用下文的金额选择、逐行校验、去重与签名规则。表不可读时保留名称列表和重试入口，不自动合并或导入其他表。新 UI 中 XLSX 工作表名留空会先发现；旧 API 未传 `inspectSheets` 时仍默认解析首个可见表，CSV 行为不变。

`confirm` 硬性拒绝 `inspectSheets:true`，即使附有有效签名；该字段出现时也必须为布尔值。正常预览的签名绑定显式 `inspectSheets`：预览省略而确认补 `false`，同样须重新预览。只有完整正常预览的有效令牌才能入账。

换表立即清除旧金额选择、行和令牌并禁用确认。文件、输入、原页面、成员或家庭改变后，迟到成功或失败不能恢复旧结果；未失焦的输入也受保护。发现与预览不入账、不持久保存附件或名称列表；已明确发送的确认不能通过关页或换表撤回。

发现阶段保留 ZIP 大小、路径、重复项、链接、压缩格式、工作簿目标及全部关系外链检查，并检查包内所有 XML 部件（扩展名不区分大小写）的编码、DTD/ENTITY、结构、深度和节点数。宏、加密、损坏 XML、外链或超限仍为硬错误，不能伪装成选择状态；选定表正常解析时才检查公式、错误值、金额、日期与单元格限制。完整数值限制见 [文件安全边界](FINANCE-IMPORT.md#文件与安全限制)。

新增专项入口为 [工作表发现 API 测试](../tests/test_financial_sheet_discovery.py) 与 [临时浏览器检查](../tests/browser_financial_sheet_discovery_check.py)。合入前的合成专项不替代当前组合版本的整体验证，也不证明真实平台账单已验收。

### 导入金额列选择

此局部契约扩展现有 `POST /api/finance-hub/imports/preview` 与 `POST /api/finance-hub/imports/confirm`，不新增路由。本扩展已于 2026-09-15 05:47:43 发布。完整文件限制见 [FINANCE-IMPORT](FINANCE-IMPORT.md)，整合与发布证据见 [VALIDATION](VALIDATION.md)。

请求可选增加 `amountColumn`：**从 0 开始的整数列索引**。省略时，唯一金额候选自动选择；多个候选时要求本人选择。显式 `null`、布尔值、浮点数、字符串、负数、越界或非金额候选列均返回 400，不把 `0` 当作未选择。

```json
{
  "source":"generic",
  "kind":"payments",
  "csv":"date,title,amount,amount,currency,flow,id\n2026-09-02,合成示例,100.00,80.00,CNY,expense,synthetic-001\n",
  "amountColumn":3
}
```

同一选择适用于 `{file:{name,contentBase64,encoding,sheet}}` 文件请求；不改变互斥的 `csv` / `file` 规则。只允许当前自动识别表头里的金额候选，按物理列索引去重；同名表头保留为不同候选。

两个预览状态均返回 `amountSelection` 与 `requiresAmountSelection`：

```json
{
  "amountSelection":{
    "required":true,
    "selectedIndex":null,
    "headerLine":1,
    "columns":[
      {"index":2,"label":"amount","columnLabel":"C"},
      {"index":3,"label":"amount","columnLabel":"D"}
    ]
  },
  "requiresAmountSelection":true,
  "rows":[],"errors":[],"totals":[],
  "newCount":0,"duplicateCount":0,"errorCount":0,
  "previewToken":null,"expiresInSeconds":1200
}
```

`required` 表示文件有多个金额候选，即便已选择也保持 true；`selectedIndex` 是实际所选索引，无选择才为 null。`headerLine` 从 1 开始，表示转换后的 CSV 表头行；XLSX 的含换行单元格会影响 CSV 物理行号，不把它当作原 Excel 行号。`columnLabel` 是 A、B、…、CB 等显示位置；UI 必须转义原列名。

`requiresAmountSelection=true` 是等待输入状态，HTTP 200 **不代表业务记录已通过校验**。此时没有行解析结果或有效令牌，错误计数 0 也不能解释为文件无错误。客户端显示列选择，携原完整请求与 `amountColumn` 重新调用预览。

选择后 `requiresAmountSelection=false`、`selectedIndex` 为整数，恢复现有逐行校验和重复检查；无错误时才返回令牌。唯一列同样返回其来源信息。金额仍为非负、最多两位小数，标准化结果使用整数分；无法解析的所选金额仍阻止确认。

确认必须发送与预览一致的完整请求、选择及 `previewToken`。选择纳入签名摘要；增删或修改选择、原文件内容、来源、类型、编码或工作表均要求重预览。服务端也拒绝未选择的多候选确认，包括来自旧版本的有效签名，不仅依赖前端禁用按钮。省略选择的旧单金额列请求保持兼容。

选择不改变同一文件同一行的身份。已经入账后改选不同金额再导入，原记录不覆盖、不新增副本；现有确认回执返回 `conflicts`。保留旧指纹生成方式以兼容历史无编号文件重传；原默认列不可解析、但用户明确选择了另一有效金额列时，使用文件摘要与行位置维持稳定身份。原文件内容本身发生变化时仍按既有无编号文件规则处理，不据此跨文件自动合并。

未增加数据库字段或导出字段。预览选择只在本次请求与签名内，不保存原附件；没有自动平台授权或云写入。本人/家庭隔离及 TV 禁止访问不变。可用 [金额选择 API 测试](../tests/test_finance_amount_columns.py) 与 [临时浏览器测试](../tests/browser_finance_amount_columns_check.py) 核对此流程；真实平台导出变体仍须逐份验收。

本模块五张每户表：`hub_transactions`（owner + fingerprint 唯一）、`hub_imports`（批次）、`hub_investments`（个人资产）、`hub_budgets`（owner/month/currency/category 主键）、`hub_reconciliations`（可撤销关系）。每位成员最多保留 20,000 条关系（含撤销历史）。所有写操作保持事务与审计；原 `private_finance` 和 `finance_baselines` 不被导入覆盖。

关系表列为 id/owner/kind/left_id/right_id/amount_cents/status/revision/confirm_digest/created_at/updated_at；owner/kind/left_id/right_id 联合唯一。confirm_digest 仅为预览令牌的 SHA-256，用于重试去重，不保存原令牌；不返回前端、不加入个人数据导出。新增表在模块注册时自动创建，不需重建已有数据库或修改环境变量。

新接口需要接手验证时，使用 [test_finance_hub.py](../tests/test_finance_hub.py)、[test_financial_files.py](../tests/test_financial_files.py) 和合成文件。实际账单模板、账户余额和投资估值的准确性必须按来源与日期核对；测试通过只证明覆盖到的代码行为，不证明所有真实账单已完成对账。

对账的金额、幂等、权限与实际跨家庭路由验证见 [test_finance_reconciliation.py](../tests/test_finance_reconciliation.py)。不使用真实个人账单或真实支付平台执行回归。

### 对账界面请求生命周期

本次发布仅加强前端流程，不改变四条对账 API。页面绑定生成时的成员、家庭与 CSRF，候选／预览／确认／撤销在处理结果前重新核对身份和原页面。确认使用原 previewToken、撤销使用原 relation ID 和 revision；已发送操作不能由关闭页面取消。未知结果在原页面重试沿用服务端幂等，记录变化仍按既有 409 重新核对。缓存账本标签与账单／投资／预算编辑入口也先核对服务器身份，覆盖另一标签页登录后当前页面身份尚未刷新这一场景。不将凭据写入持久存储，不共享个人明细。此项不等同于所有财务缓存生命周期的全面加固。

XLSX 工作表发现与助理旅行简报已于 2026-09-15 06:50:21 合入并发布，详情见 [验收记录](VALIDATION.md)。
