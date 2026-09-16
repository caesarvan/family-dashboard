# 本人持仓与操作结果

本页描述 Expo 持仓界面使用的后端契约，已于 2026-09-17 06:15:34（北京时间）发布，06:16:14 正常 TLS 读回通过。实际 main `f2146f2`／source `1bb4342`，55 张户内表；完整身份与验证边界见 [发布记录](VALIDATION.md#expo-holdings-release)。它补充当前持仓、来源映射和可靠的保存结果读取，不建立银行连接、独立资产账户、历史估值或汇率模型。

实现入口为 [finance_hub.py](../finance_hub.py)、[investment_operations.py](../investment_operations.py) 和 [investment_import.py](../investment_import.py)。原文件导入字段与确认语义见 [INVESTMENT-IMPORT](INVESTMENT-IMPORT.md)。

## 身份、数值与版本

- 三条新增 GET 和全部原持仓接口只允许当前成员。匿名返回 401，电视返回 403；本人由服务端会话确定，每户使用独立数据库。写请求要求同源 JSON 和当前 `X-CSRF-Token`。
- 新 GET 结束读取快照后再次核对实时成员会话，避免同一快照内的重复身份查询漏掉另一连接已提交的撤销。写入成功或重放也在事务完成后重新核对；若此时身份失效会隐藏响应，已提交操作仍可在本人重新登录后按原编号查询。
- `institution` 是本人填写的机构说明，`sourceName` 是本人命名的文件来源；它们不是银行账号或已验证的机构连接。个人持仓及来源、操作结果均不共享。
- 记录金额是原币整数分，单项范围 `0..100000000000000`。新 GET 不返回可能超出 JavaScript 安全整数的组合金额；客户端应验证每项安全整数后使用 BigInt 分币种汇总。不要使用旧 overview 中超出安全整数的 JSON number 转换回 BigInt。
- `valueCents:null` 表示估值未知，0 表示已知为零。成本和估值均为该持仓总额；数量是可选文本，不参与推算单价。浮盈亏只适用于已有估值部分，不包括分红、已实现收益、税费和汇率变化。
- `asOf` 是本人提供的估值／核对日期。`updatedAt` 是服务端记录最近写入时间；读取、重试或为未变化记录建立来源映射不会推进持仓时间或 revision。
- PATCH、DELETE 使用原整数 `revision`。发生冲突时保留草稿，读取最新记录后由本人重新确认；不能自动更新 revision 后重写。

## GET `/api/finance-hub/investments`

不接受查询参数。一次返回当前成员全部持仓（写入上限 300 条）与来源；两个集合在同一 SQLite 快照中读取。空结果是 `{ "investments": [], "sources": [] }`。

```json
{
  "investments": [{
    "id": "0123456789abcdef01234567", "revision": 2,
    "name": "合成示例基金", "institution": "合成示例机构", "assetType": "基金",
    "currency": "CNY", "quantity": "10.5", "costCents": 10000,
    "valueCents": 10500, "asOf": "2026-09-01", "note": "",
    "valuationSource": "file_import", "visibility": "private",
    "updatedAt": "2026-09-02T12:00:00+00:00",
    "source": {"sourceName": "合成账户", "holdingKey": "fund-001"}
  }],
  "sources": [{
    "sourceName": "合成账户", "revision": 1,
    "updatedAt": "2026-09-02T12:00:00+00:00",
    "holdingCount": 1, "deletedCount": 0
  }]
}
```

原持仓 DTO 增加 `updatedAt` 和 `source`；没有映射时 source 为 null。顺序为最近写入时间降序、相同时间按 id 排序。sources 按来源名称排序，`holdingCount` 是该来源目前仍存在的本人持仓数，`deletedCount` 是已有映射但持仓已删除的墓碑数。来源 revision 和 updatedAt 来自最近文件确认，不因手工编辑、删除或读取自动推进。无当前持仓的来源仍保留，不能用更改来源名称绕过墓碑。

这两个集合不与资产基线、公共资金、付款或来源消费观察自动相加；也不根据同名机构推测是同一真实账户。

## 手工 POST、PATCH 与 DELETE

沿用 `/api/finance-hub/investments` 的 POST，以及 `/api/finance-hub/investments/<id>` 的 PATCH、DELETE。新增可选 `requestId`，必须恰为 32 位小写十六进制字符；新版客户端为每次本人确认生成一个随机编号，网络重试继续使用原编号和原完整请求。缺少 requestId 的经典请求继续支持，且不产生新操作回执。

POST、PATCH 接受 `name/institution/assetType/currency/quantity/cost/value/asOf/note`；PATCH 是完整编辑对象，另需当前 revision。`name/institution` 最多 120 字，assetType 最多 60 字，note 最多 1,000 字。quantity 为空串时保存 null，否则要求非负十进制文本，最多 15 位整数和 8 位小数。

`cost/value` 为原币金额，建议发送十进制字符串；value 可为空串或 null。投资手工金额接受 `1234.56`、`1,234.56`、`1，234.56` 及既有人民币符号前缀；拒绝 `1,23`、错误千分组、混合两种逗号、科学计数法、正负号、NaN/Infinity、布尔值及超过两位小数。该校验只作用于投资记录，不改变账本原 `cents` 函数。文件导入仍使用其原本更严格的无货币符号模板规则。

```json
{
  "requestId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "name": "合成示例基金", "institution": "合成示例机构", "assetType": "基金",
  "currency": "CNY", "quantity": "10.5", "cost": "100.00", "value": "105.00",
  "asOf": "2026-09-01", "note": ""
}
```

DELETE 新版请求仅接受 `{ "requestId": "...", "revision": 2 }`。POST 仍返回 201，PATCH／DELETE 返回 200；带 requestId 时在原 DTO 或 `{deleted:true}` 上附加 `requestId` 与 `replayed:false`。同一已成功操作重试返回历史结果及 `replayed:true`，创建重试仍返回 201。

同一成员的 requestId 在 create、update、delete 三类操作及所有记录之间全局唯一。摘要绑定操作类型、记录 id、原 revision 和规范化完整投资值；如 `"100.00"` 与数值 100 规范化相同，可重放。数量文本不会改写，`"10"` 与 `"10.0"` 是不同记录值。创建时通常不发送 revision；若发送，它也参与摘要，不能在重试时改变。

BEGIN IMMEDIATE 内先核验真实会话及旧回执，再检查容量、当前记录和版本，执行写入、审计并保存结果。旧成功先于当前记录和容量检查，所以删除后的创建／修改重试不复活旧记录，删除重试不因已删除而变成 404。新 key 不会自动继承旧操作授权。失败和容量超限整笔回滚，不消耗成功回执；同 key 不同内容返回冲突。

| HTTP / code | 含义与恢复 |
|---|---|
| 409 `revision_conflict` | 当前版本不同或 revision 类型不正确；原草稿保留，读取并重新核对 |
| 409 `operation_request_conflict` | 原 key 已用于不同 kind、记录、版本或规范化值；读取原 key 结果，不能改写它 |
| 409 `operation_capacity` | 本人成功回执数量或结果字节数达到上限；原回执仍可读取和重放 |
| 400 | 输入字段、金额、操作编号不合法，或新建将超过 300 项持仓；不能误识别为版本冲突 |
| 404 | 尚不存在或不属于本人；不会向他人泄露记录 |

## GET `/api/finance-hub/investments/operations/<requestId>`

不接受查询参数，读取本人该操作的持久化历史结果：

```json
{
  "requestId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "kind": "create", "recordId": "0123456789abcdef01234567",
  "result": {"id": "0123456789abcdef01234567", "revision": 1},
  "completedAt": "2026-09-02T12:00:00+00:00"
}
```

示例 result 为节略；实际 create/update result 包含原完整持仓 DTO，delete 为 `{deleted:true}`，均不附加 requestId/replayed，也不附加新读取接口的 source/updatedAt。

未读到时返回 404、`code:investment_operation_not_found`。**404 不证明原请求没有执行或以后不会提交。** 超时、断网或响应丢失后应保留原请求，先读该结果；暂未读到可再次查询或由本人使用原 key、原内容重试。结果存在后再读当前列表，历史创建或修改结果不代表记录现在仍存在或仍是该版本。

首次明确 revision_conflict 且未经历结果未知的操作，可以核对结果未成功、读取新版本并由本人明确确认新操作。经历过未知结果时，不因后来 409/404 自动换 key，否则延迟请求可能重复执行。退出、切换成员或家庭后隐藏私人草稿和旧响应，并重新核验身份；本接口允许同一成员重新登录后查询持久结果。

## GET `/api/finance-hub/investments/imports/receipts`

查询参数必须恰为唯一的 `sourceName` 和 `sourceDigest`；sourceName 使用原预览返回的规范化来源名称，sourceDigest 使用原预览的 64 位小写十六进制摘要。空、重复、未知或格式错误的参数返回 400。

200 返回原文件确认结果 `created/updated/unchanged/receiptId/confirmedAt`，`replayed:true`，并附带匹配的 sourceName/sourceDigest。未读到返回 404、`code:investment_import_receipt_not_found`，同样不证明在途确认不会提交。该 GET 不要求有效 previewToken、不重新解析文件、不重新确认，也不恢复被删持仓。

原 POST `/investments/imports/confirm` 继续只接受 `{previewToken}`，响应仍为既有六字段，没有 sourceName/sourceDigest。客户端保留它发起确认时的来源与摘要，不能将迟到响应套到后来选择的文件。15 分钟凭据失效后，先用本 GET 核对原结果；若需重新预览，使用原文件及来源并由本人再次确认。相同文件的历史回执与当前持仓不同，应分别展示。

## 数据库、导出与发布接缝

新增唯一一张户内表 `hub_investment_operations`，DDL 的唯一来源为模块 `INVESTMENT_OPERATIONS_SCHEMA_SQL`，由 `register_investment_operations(app, db, Problem, require_member, identity)` 初始化。finance_hub 调用注册器并使用返回的事务助手；investment_import 额外接收可选 identity 回调核验新回执 GET。

| 列 | 契约 |
|---|---|
| owner | 非空，引用 users(id) |
| request_id | 非空，与 owner 组成主键 |
| kind | create / update / delete |
| record_id | 历史目标持仓 id；不对持仓表建立外键，删除后保留历史结果 |
| payload_digest | 规范化操作的 SHA-256；仅用于请求去重 |
| result | 原响应 JSON；不存原文件、凭据、预览令牌或客户端草稿 |
| completed_at | 服务端实际完成时间 |

每人最多 20,000 条成功操作，result UTF-8 字节总额最多 32 MiB；限额在写事务中执行，不按请求竞态预估，也不清理成功回执以腾空间。旧回执重放优先于限额和当前持仓检查。原四张投资文件导入表不改变结构。

个人导出需显式白名单 `requestId/kind/recordId/result/completedAt`，result 再对白名单原 DTO 或 deleted 过滤；不导出 payload_digest，不加入 shared 或电视响应。完整管理员备份需包含新表。实际已有 54 表环境需经独立审查的 54→55 迁移／完整恢复；运行文件白名单、Docker COPY、路由索引与导出由集成人接线，本分支不执行生产初始化或迁移。

## 验证范围

[test_investment_operations.py](../tests/test_investment_operations.py) 使用临时 SQLite、真实 Flask 路由、两成员及独立家庭、配对电视与合成持仓，验证原接口兼容、幂等重试、并发 CAS、晚提交前 404、提交后响应丢失、原子回滚、回执容量、来源墓碑、严格金额及会话撤销。外部网络被测试显式禁止。最终执行结果随交付记录提供；源码测试不替代新 UI 浏览器、Linux 发布、真实机构或生产数据验收。
