# 通用财务文件四字段映射

已于北京时间 2026-09-18 06:56:39 发布，06:57:18 正常 TLS 读回通过；组合与实际发布证据集中在[本批验收](FINANCE-COLUMN-MAPPING-ACCEPTANCE.md)。只扩展既有 `finance_hub.py` 的本人文件导入；无新表、机构连接、外部调用或汇率计算。`financial_files.py` 的文件安全读取与原精确金额解析保持原实现。已有自动列识别、工作表选择及金额列选择继续兼容。

## HTTP 契约

使用现有 `POST /api/finance-hub/imports/preview`、`POST /api/finance-hub/imports/confirm` 和 `GET /api/finance-hub/imports/results/<requestId>`。所有请求仍需当前本人会话；写请求还需 CSRF。TV 不可用，家庭管理员也不获得其他成员账本权限。

本批手动映射仅支持 `source: "generic"`，`kind` 为原 `payments` 或 `orders`。文件为 CSV、TXT、无宏 XLSX，或既有 `csv` 文本字段。文件对象仍为 `{name,contentBase64,encoding?,sheet?}`。通用表格须独立提供币种列，不从金额符号、机构或用户偏好推断币种。

1. 多工作表 XLSX 先用旧 `inspectSheets: true` 请求选择工作表；该请求不得同时提交手动映射控制字段。
2. 检查表头：提交原来源、类型和文件，加 `inspectColumns: true` 和可选 `headerLine`（严格整数 1–60）。省略时取前 60 行内第一个非空记录；有前言时应明确选择实际表头行。
3. 用户选择四个不同列，提交原负载加 `mapping`，不带 `inspectColumns`、`inspectSheets`、`amountColumn` 或顶层 `headerLine`。
4. 获得可确认预览后，确认必须携原完整负载、原 `previewToken` 和原 `requestId`。

```json
{
  "source": "generic",
  "kind": "payments",
  "file": {"name": "synthetic.csv", "contentBase64": "..."},
  "mapping": {
    "version": 1,
    "headerLine": 1,
    "date": 0,
    "amount": 1,
    "title": 2,
    "currency": 3
  }
}
```

`mapping` 必须恰好包含以上六字段。`version` 严格为整数 1；四个索引严格为整数 0–79、互不重复且在实际表头范围内。拒绝布尔值、浮点数、额外字段和重复 JSON 字段。检查/映射与其它选择步骤混用返回原形状 `{error}`、HTTP 400。

检查表头响应保留原预览公共字段，并增加：

```json
{
  "requiresColumnSelection": true,
  "columnSelection": {
    "headerLine": 1,
    "lineKind": "csv_lines",
    "columns": [
      {"index": 0, "label": "日期", "columnLabel": "A"},
      {"index": 1, "label": "金额", "columnLabel": "B"},
      {"index": 2, "label": "标题", "columnLabel": "C"},
      {"index": 3, "label": "币种", "columnLabel": "D"}
    ],
    "suggestedMapping": {"date": 0, "amount": 1, "title": null, "currency": 3}
  },
  "rows": [],
  "errors": [],
  "previewToken": null
}
```

示例“标题”不在既有自动别名中，因此建议值为 `null`；用户仍可选择该列。建议只在某字段恰有一个既有别名匹配时给索引，重复标签不会擅自选第一个。`columns` 保留原序、空标签和重复标签，最多 80 列，每个标签最多 200 字符；本模式至少需要四列。没有数据行样例，也不生成确认令牌。

实际映射预览返回 `requiresColumnSelection: false`，`columnSelection` 保留上述信息并增加原 `mapping`；`amountSelection: null`、`requiresAmountSelection: false`。自动预览新增字段为 `false` / `null`，旧字段继续可用。检查表头不能确认入账。

## 日期、金额与行位置

- CSV/TXT 支持既有逗号、制表符、分号。读取完整 CSV 记录处理引号内换行；`headerLine` 指记录起始的物理行，`sourceLocation.lineStart/lineEnd` 指实际物理行范围，`lineKind: "csv_lines"`。不能把 CSV 记录序号当物理行号。
- XLSX 使用安全读取器输出的工作表行序；空白行保留，多行单元格不改变工作表行号。`headerLine` 和位置均为工作表行，`lineKind: "worksheet_rows"`。
- 日期复用既有年月日严格解析，支持原年/月/日或斜杠替换规则，不新增日月次序猜测。金额复用非负精确整数分解析；零合法，空值、指数、歧义逗号与负数不接受。币种独立校验。
- 标题单元格空时沿用“未命名记录”。其余已识别的方向、类别、交易编号等保留原自动读取；未知收支方向仍为 `unknown`，不会因为选择金额列而变成支出。订单单独统计，不再次计入支付支出。
- 每批最多 5000 个非空数据记录；文件字节、展开大小、XML、公式和宏限制沿用读取器。错误行沿用 `errors[{line,message}]`，最多回显 50 条，`errorCount` 为全量错误数。任一错误使令牌为空、整批不能确认，不部分保存。

## 签名、去重和恢复

完整 `mapping` 纳入排序 JSON 的原预览摘要，含实际表头行和全部索引；映射对象键顺序不影响摘要。无新字段的旧请求摘要不变。确认不能借原令牌改变映射；已消费请求号改负载返回 HTTP 409、`code: "import_request_conflict"`。预览仍有效 1200 秒，普通无效/过期预览仍返回既有 HTTP 400，不引入另一套过期语义。

新通用记录在既有 `hub_transactions.data` 内保存 `sourceRowKey`：由来源、payments/orders 类型、严格解码文本的 SHA-256、所选工作表、位置类型及原始行起止组成。文件名不参与，因此改名重传不新增。XLSX 使用所选工作表安全序列化文本的摘要，不以 ZIP 容器元数据区别记录。编码改变而实际解码文本不同属于不同来源，必须重新预览；不能覆盖旧记录。

索引同时匹配旧交易指纹及原行 key。手动映射会按旧自动路径额外有界重读一次，只提取历史指纹，含旧多金额列选择、原列不可读或旧逗号解析规则；该内部步骤的旧金额绝不进入公开预览、汇总或账本。旧记录无须补写 key 或迁移。既有明确交易编号仍按原规则跨文件去重。日期、金额、标题或币种改列后，同一原行按重复/冲突计数，旧行保持原值；回执月份来自实际保留的记录。不同类型不会因相同行位置合并；跨文件相似金额和日期也不会自动合并。

成功回执仍是本人请求的历史业务结果。相同原文件/映射/令牌/请求号可在预览过期后读取原回执，不再次写入或恢复后来删除的账本记录。GET 缺回执仍为 HTTP 404、`import_result_not_found`，不是“未在途”的证明。结果未知时应保留完整原负载和 key，由用户明确核对，不自动改映射或发新请求号。

## 本次会话修复与验证边界

真实 Flask、Cookie、临时 SQLite 基线复现 9 个失败：guard 后替换同成员另一有效 cookie 的五入口，以及业务 SELECT 后撤销的四读/回放入口。只修导入 preview/confirm/results：固定原 session ID、owner、credential、auth version 和家庭；读前释放旧 cookie 解析的隐式写事务，完整业务快照释放后再 fresh 验证；确认取得写锁后和审计后提交前复核；锁内回放也先释放再 fresh。普通会话活动不视为身份更换。首次旧 cookie 注册已由应用 guard 提交，读操作不撤销该必要初始化。

专项原件保存在作者树忽略目录 `test-results/column-mapping-*`，失败不覆盖。修复前候选 `f70f7da` 的 `column-mapping-combined-r3` 同轮实际 **393/393 通过**（新增映射 46、会话 21、原 8 个导入模块 326），0 failure/error/skip，pytest 91.26 秒；完整 Python 输入运行前后哈希相同。JUnit SHA-256 `5db3b36ff60894e7e19d1c9fcb2c0c06f80f75de77d0f769d5bb70448aa8c10d`，`record.json` SHA-256 `ebe9dc81d9b2fba5516527ebdbde7c120e3d2f999ffe1d00db179dc64aede71d`。覆盖文件安全、金额、金额列、工作表、回执/导航和淘宝分组兼容；基线 9 失败及中间 61/65 通过原件保留。上述后端专项不修改 `financial_files.py`，不运行浏览器、真实文件或生产服务，也不声称全仓测试已通过；后续组合与发布另见本页顶部验收链接。

非作者真实复现发现 `f70f7da` 手动映射的数据短行会继承旧 `CNY` 默认值。本次仅将手动映射的缺币种默认值改为空并拒绝，旧自动/平台行为保持；新增 CSV/XLSX 的短尾缺值与显式空值四例，均实际预览错误、令牌为空、确认拒绝且业务表/回执/审计零写。修复后 `column-mapping-currency-r4` 实际 **228/228 通过**（映射 50 + 原 hub/file/amount 178），0 failure/error/skip，38.38 秒，完整 Python 输入前后不变。JUnit SHA-256 `04bc98560c96eb6ee8fd76806416d32d747580e27f8ab23feae40d04d0b1c56e`，`record.json` SHA-256 `d69e7d72a8d39515bbbf45e1603a8b23aeb2b34d56ef97c0640ab6177f56671a`。该轮未重跑其余会话/兼容模块，不把前一轮 393 写成修复后全量结果；审查复现原件独立保留。

相关：[现有文件导入](FINANCE-IMPORT.md)、[财务 API](FINANCE-API.md)、[新映射专项](../tests/test_finance_column_mapping.py)、[真实会话专项](../tests/test_finance_column_mapping_sessions.py)。
