<a id="投资持仓整理表导入独立候选尚未部署"></a>

# 投资持仓整理表导入

这项增量让成员把本人核对的国内、海外持仓整理表先预览，再整批确认到个人投资列表；不连接银行或券商、不查询行情、不换汇，不把持仓当作消费账单。现有手工编辑及按币种统计继续可用。本增量已于 2026-09-15 08:56:01 发布，完整测试与真实接入边界见 [验收记录](VALIDATION.md)。

## 使用路径与身份

1. 在“投资账户”进入持仓文件导入，为一个实际账户填写稳定的 `sourceName`。同一机构的两个账户须使用不同来源名称。
2. 首次录入可下载虚构示例模板替换内容；已有手工记录应下载“当前持仓整理表”，保留明确的 `recordId`，避免重复计入。
3. 上传 CSV 或无宏 XLSX。XLSX 先发现工作表，再明确选择一个表；发现工作表不等于已验证全部单元格。
4. 核对逐行新增、更新、不变、日期、币种、成本和估值。错误行使整批无法确认。
5. 确认后重新读取现有 `/api/finance-hub/overview`，以持仓 ID、revision 和 asOf 查看实际结果。确认成功后重试相同凭据只读回原回执。

三条路由全部要求当前成员；电视和匿名用户无权读取模板、预览或确认。所有记录、映射和回执按 owner 查询，每户使用独立数据库。POST 同时适用现有 JSON、同源和 CSRF 检查。预览凭据绑定成员、家庭和当前登录会话，切换身份或重新登录后须重新预览。

`sourceName` 是成员自己命名的账户来源，不是银行账号。系统不根据名称推断同一账户。`sourceName + holdingKey` 在本人范围内构成稳定键，均区分大小写、去除首尾空白；来源名称最多 80 字，持仓编号最多 120 字，不允许控制字符。来源和编号改变可能表示不同记录，不能用改名绕过已有映射。

## 标准整理表

使用固定英文列名，不直接声称兼容任何机构原生持仓导出。

```csv
holdingKey,name,institution,assetType,currency,quantity,cost,value,asOf,note,recordId
sample-holding-001,合成示例基金,合成示例机构,基金,CNY,10,100.00,105.00,2026-01-01,虚构示例,
```

| 列 | 契约 |
| --- | --- |
| `holdingKey` | 必需列和非空文本；同一文件不能重复 |
| `name` / `institution` | 必需，1–120 字；机构是说明文本，未建立真实连接 |
| `assetType` | 必需，1–60 字 |
| `currency` | 必需，沿用现有三位币种校验；各币种分别计算，不做汇率估算 |
| `quantity` | 可选；非负十进制文本，最多 15 位整数及 8 位小数；只作记录，不计算单价 |
| `cost` | 必需；该持仓总成本，原币种金额，非负且最多两位小数；使用小数点，千分隔只能为完整三位分组 |
| `value` | 可选；该日期总估值。新持仓留空表示未知，不能当零。已有估值时空值会阻止整批确认 |
| `asOf` | 必需，实际存在的 `YYYY-MM-DD` 日期，代表用户提供的核对日期；不能早于被更新记录的日期 |
| `note` | 可选，最多 1,000 字，可含带引号的换行 |
| `recordId` | 可选；用于明确关联现存本人记录，不能跨成员、跨家庭或改绑另一来源；不填时仅按已建立的稳定键关联 |
| `csvTextEncoding` | 可选，仅当前持仓导出表使用 `apostrophe-v1`；见下面安全回导说明 |

必需列缺失、未知/重复/空列名、行列数不符、坏引号、重复编号或重复 recordId 均拒绝。可选列可以整体不出现；已出现的列仍须保留空单元格。最多 300 行有效或错误持仓记录，不截取后导入。沿用现有每人 300 项投资上限。

持仓整理表对 cost/value 先校验明确的十进制文本：接受 `1234.56`、`1,234.56` 和 `1，234.56`；拒绝可能代表欧洲小数逗号的 `1,23` / `1，23`、错误分组 `12,34.56`、两种逗号混用、货币符号和科学计数法。币种以 currency 列为准；不能通过去除任意逗号放大金额。随后复用现有金额校验，转为整数 `costCents` / `valueCents` 保存（原币种 ×100），不使用浮点数计算；数量保留文本。本次未改变旧手工金额 API 的解析行为。总成本和估值不会与财务历史基线、公共荷包、消费流水或订单自动相加。

## 三条接口

### GET `/api/finance-hub/investments/imports/template`

默认 `mode=sample` 返回纯虚构示例：

```json
{"filename":"investment-holdings-template.csv","csv":"holdingKey,...\n...","rowCount":1,"warnings":[]}
```

`?mode=current&sourceName=...` 返回当前来源已关联、以及尚未关联来源的本人记录。已有该来源映射用原 holdingKey；未关联记录以现有投资 id 作建议 holdingKey，均填 recordId。属于其他来源的记录排除，warnings 给出数量；用户须移除不属于这次账户的行，缺行会保留，绝不视为清仓。额外返回 sourceName。

为防止 CSV 被表格软件当作公式执行，当前表对 holdingKey/name/institution/assetType/currency/asOf/note/recordId 的每个单元格都添加单引号前缀，并使用 `csvTextEncoding=apostrophe-v1` 标记。回导仅在明确标记下移除恰一个前缀，因此原本含单引号或公式样式的文字能原样恢复。请保留保护列和前缀；它们缺失时会拒绝，不能静默修改财务文字。金额和数量仍按数字格式校验。

### POST `/api/finance-hub/investments/imports/preview`

```json
{
  "sourceName":"本人命名的账户来源",
  "file":{"name":"holdings.xlsx","contentBase64":"BASE64_FILE_BYTES","sheet":"持仓"},
  "inspectSheets":false
}
```

`file` 与现有财务文件接口相同：name、contentBase64，以及可选 encoding（CSV 的 auto/utf-8/gb18030）和 sheet。原文件最多 2 MiB，请求最多 3,000,000 字节；保留原 ZIP/XML/展开大小/工作表行列/公式/宏/外部关系检查和解析并发限制。不得传额外字段。`inspectSheets` 必须为布尔值，仅 XLSX 支持 true。

发现模式返回 `requiresSheetSelection:true`、fileInfo.sheets、空 rows/errors、全零 counts 和 `previewToken:null`。它只完成工作簿结构发现，尚未解析持仓，不得确认。未指定 sheet 的 XLSX 自动使用同样的结构发现，因此带说明或公式的封面不会阻止选择另一有效表；明确选择含公式的表仍会拒绝。须指定 sheet 后才能取得确认凭据。

普通成功预览的响应骨架：

```json
{
  "sourceName":"本人命名的账户来源",
  "sourceDigest":"SHA256",
  "fileInfo":{"name":"holdings.xlsx","format":"xlsx","sheet":"持仓","sheets":["持仓"]},
  "requiresSheetSelection":false,
  "rows":[{"line":2,"holdingKey":"sample-holding-001","action":"create","before":null,
    "after":{"name":"合成示例基金","institution":"合成示例机构","assetType":"基金","currency":"CNY",
      "quantity":"10","costCents":10000,"valueCents":10500,"asOf":"2026-01-01","note":"",
      "valuationSource":"file_import","visibility":"private"},"warnings":[]}],
  "counts":{"create":1,"update":0,"unchanged":0},"preservedCount":0,
  "warnings":[],"errors":[],"errorCount":0,"previewToken":"SIGNED_PREVIEW_REFERENCE"
}
```

before 含已有完整投资对象、id 和 revision；after 使用现有规范化投资字段，创建时尚无新 id。action 只有 create/update/unchanged。errors 为 `[{line,message}]`；line 为 CSV 物理行尾序号，多行带引号字段会占多行，0 表示批次错误。任何错误都使 previewToken 为 null，其他有效行仅供核对，不会部分写入。

同一来源已经确认过相同原始文件字节、选择的 sheet 和解码结果时，返回 `replayed:true`、rows 为空、counts.unchanged 为文件记录数，并明确提示“仅返回原回执，不重写当前持仓”。这也不会恢复后来已删除的持仓；不把历史文件内容伪装为当前值。

### POST `/api/finance-hub/investments/imports/confirm`

```json
{"previewToken":"SIGNED_PREVIEW_REFERENCE"}
```

仅接受该一个字段。凭据有效期 15 分钟；文件/来源/工作表变化后必须重新预览。服务端确认的是原预览暂存的规范化快照，不重新接受客户端金额。成功返回：

```json
{"created":1,"updated":0,"unchanged":0,"replayed":false,"receiptId":"SERVER_RECEIPT_ID","confirmedAt":"UTC_ISO_TIMESTAMP"}
```

重放返回同一回执与原计数，只有 replayed 为 true；原计数不代表本次又创建或更新了一次。新会话可重新提交原文件预览后获得新凭据，再读回历史回执。

确认使用 BEGIN IMMEDIATE 和本人持仓、全部来源/映射的版本摘要 CAS。预览之后任一本人持仓被编辑、删除或新增，或者来源/映射变化，都会 409 且整批不写；保留原文件重新预览。重复确认并发只提交一次，另一请求读回原回执。错误/过期/身份不符为 400 或 409，未登录 401、电视/CSRF/异源 403、容量 413、预览或解析配额 429。

## 安全更新规则和持久化

- 同名、同机构、同币种只用于发现疑似重复并阻止自动 create；必须使用当前整理表的 recordId 明确关联，绝不根据名称猜配对。
- 显式 recordId 须属于本人且尚未关联其他 sourceName/holdingKey；不能通过文件改绑、改币种。未导入的行保留原值，不自动删除持仓。
- 旧 asOf 拒绝。已有 valueCents 不为 null 时，空估值拒绝整批；不采用“保留旧估值却推进日期”的做法。若确需清空，使用已有投资编辑器明确操作。
- 现有手工记录没有发生金额/字段变化时，只建立明确映射，不重写原数据和 revision；因此原 valuationSource 可以仍为 manual。文件新增或实际更新的记录标为 file_import，日期仍是用户提供，并非银行或行情验证。
- 删除持仓后保留稳定键映射墓碑，阻止重新导入旧文件自动复活。已删除记录不出现在当前整理表；不能用原键无声重建。

新增四张每户表：

| 表 | 主要列及范围 |
| --- | --- |
| hub_investment_sources | owner/source_name 复合主键；revision、updated_at。最多 300 个本人来源 |
| hub_investment_links | owner/source_name/holding_key 主键；investment_id 在本人范围唯一、created_at；删除后保留墓碑 |
| hub_investment_import_previews | id、owner、context_hash、source_name、source_digest、snapshot、expires_at、created_at；只保存规范化快照，不保存原文件；每人最多 20 份有效预览，后续预览会清理过期记录 |
| hub_investment_import_receipts | id、owner、source_name、source_digest、result、confirmed_at；owner/source_name/source_digest 唯一，最多 20,000 回执/人；result 仅公开计数、回放标志和回执时间 |

本人数据副本可白名单导出 sources、links 和 receipts；临时 previews、context_hash、签名凭据及候选快照均不导出，不进入共享摘要、电视或助理上下文。完整管理员备份仍覆盖全部数据库。模块由 `register_finance_hub()` 内部登记，复用原投资校验器；新增 `investment_import.py` 需要进入镜像和发布白名单。

## 验证边界

测试使用本机临时数据库、合成 CSV/XLSX、真实 Flask API；覆盖预览无持仓写入、显式手工关联、重复/并发回放、CAS、旧日期/空值/币种、未知估值、多币种、缺行保留、删除墓碑、本人/家庭/会话/电视隔离、文件安全拒绝、模板公式文本保护和本人导出。没有读取真实账单或持仓，没有银行连接、实时行情、生产导入或真实账户自动更新验证。实际完整后端、8 组组合浏览器与发布后读回见 [VALIDATION](VALIDATION.md)；本文件场景列表不替代该证据，也不提升真实机构或生产导入覆盖。
