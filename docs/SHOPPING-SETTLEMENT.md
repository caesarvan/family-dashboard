# 采购实付核对

**当前上线：Expo 采购实付入口，2026-09-18 08:03（北京时间）。** 新版从采购项「核对实付」或本人交易详情「核对采购实付」进入，沿用下述三接口与明确共享规则。正常 TLS 读回通过；[使用与验收](EXPO-SHOPPING-SETTLEMENT-ACCEPTANCE.md#expo-shopping-settlement-release)集中记录证据。下述 2026-09-15 安装身份和表数量为首版历史，不代表当前数据库结构。

**适用发布记录：2026-09-15 12:11:36，镜像 `sha256:1167dffd3b7e234d43460442acfe0d30959370c90c7e8147a1b30baa0e2380b5`。** 本版本增加采购实付的三条接口、两张本人私有表与成员核对界面；组合清单为 200 个源文件、32 份 Markdown、40 个静态资源、98 个方法／路径模板、37 张户内表与 2 张平台表。实际专项与完整回归见第 6 节；真实银行账单接入、实体电视操作及新的云端写入仍未验收，合成测试不能代替本人真实操作。

## 1. 目的与操作边界

成员从本人已导入的账单或订单中选择证据，核对拟公开到家庭采购的人民币实付和完成状态，经预览、明确确认后更新**原采购**。这是采购实付核对，不是付款、报销、银行转账或新建账单。

- `actual` 是整项采购实际总价，以人民币整数分保存。确认采用替换语义，不在旧实付上再次累加；`budget`、数量、标题和负责人不随账单改变。
- `done` 表示“已买到”，与是否付款分别核对。付款成功、订单成功或退款状态均不能自动证明是否收到／退回物品。
- 采购 `actual: null` 表示尚未记录，`0` 表示明确记录为零。界面“元”与接口“分”只在输入输出边界转换。
- 采购实付不会生成 `hub_transactions`，不会改变原交易的 `visibility`，不会扣减公共荷包、增加私人月度支出，或累加到旅行 `paid`。

旅行的采购实付汇总仍只统计 `done=true` 的采购；旅行 `paid`、采购预算和采购实付分项不能重复相加。基础字段见 [API](API.md#4-实体-crud-与字段)，旅行预算含义见 [平台 API](PLATFORM-API.md#1-旅行工作流)。

## 2. 原币、订单、分配与退款

首版仅将 **CNY** 的本人有效消费付款投影为采购实付。订单本身是核对线索，不直接当作已支付金额；收入、转账、排除项、重复付款和不明方向不能作为实付来源。外币没有自动汇率换算，不能按 1:1 写入人民币采购。

一笔付款可以按明确分配额用于不同采购，分配须受该付款的净额上限约束。`netCents` 为付款金额减已关联退款，`reservedCents` 为已有活动采购关联占用额；新关联不能超过剩余额度，更新本关联时扣除其他关联占用额。已经确认分配到付款的独立退款减少可用净额；订单与付款之间的对账分配用于核对订单，不等同已被采购使用的额度，不能重复扣除。具体订单／付款／退款关系见 [财务 API](FINANCE-API.md)。

税费、运费、优惠和商品数量没有独立的账本分配字段，不能根据标题猜测，也不能在已经包含这些费用的付款金额上再次加算。后续退款、来源删除或对账关系变化需要重新核对；只出现“退款”字样不等于整笔已退。退款不自动改变采购“已买到”状态。

## 3. 隐私与导出

采购是家庭共享实体，`owner` 表示负责人，不是访问控制。已配对电视也能读取共享采购。新增关联与业务回执按本人保存在私有表中，共享实体只接收经过确认的 `actual`、`done`。

- 不把交易 ID、订单号、商户、账单标题、来源名称、付款账户、原始错误或预览凭据塞进 `entities.data`、采购备注或旅行计划。
- 不自动上传或附加账单图片。原有采购照片一旦关联采购便可被伴侣和电视读取；图片规则见 [基础 API](API.md#6-采购照片)。
- 每位成员对同一采购保有独立的私有关联；另一成员不能读取、修改或撤销该关联。共享采购值仍是一个版本，后续更新须重新核对实际 revision。
- 本人数据导出的 `personal.shoppingSettlements` 包含 `{links, receipts}` 白名单业务记录；不导出预览签名、会话上下文、Cookie、CSRF 或另一成员的关系。选择 `includeShared` 只额外包含原有共享实体，不扩大私有关系可见性。导出边界见 [PORTABILITY](PORTABILITY.md)。

## 4. 修订、旅行与删除

预览不更新采购或账本；确认在同一数据库事务中核对采购版本、本人来源和分配关系，再保存投影、私有关联及幂等回执。预览后的编辑、删除或来源变化需要重新预览，不能用旧快照覆盖。

旅行工作流本身的三方字段合并只覆盖日程；采购 `done/actual/photoIds` 在旅行重新生成时专门保留。新核对不得更改原采购 ID、照片或旅行关联；另一端已打开的旅行预览会因采购 revision 改变而拒绝旧确认。迁期重新预览后仍保留实际采购值。

从旅行计划移除采购，或删除整趟旅行，按既有行为只解除旅行关系并保留采购历史。删除采购后，旧预览、回执回放和同名新采购均不得让原记录复活或自动接回。私有来源删除与解除关系也不能自动删除家庭采购。

普通撤销选择 `detach_keep_current`，解除本人的关联并保留采购当前值。若明确选择 `restore_if_unchanged`，只有采购 revision 及上次投影的 `actual/done` 均未变化时才恢复**最近一次确认前的值**；update 后不是恢复到首次关联前。否则返回 409，不能自动改用“只解绑”完成提交。即使后来只修改了照片或名称，也不能绕过 revision 检查。退款或来源变化只是派生 `needs_review`，不会自动回滚共享采购。

同一已成功预览再次确认只返回历史回执，`replayed=true`；不再次修改实体或增加支出。历史结果不是当前采购状态的证明，应重新读取 context 或原采购。已撤销关系或已删除采购也不能被旧回执回放恢复。

## 5. 接口与数据模型

三个接口的共同前缀为 `/api/finance-hub/shopping-settlements`。全部只允许当前家庭已登录成员，不能用请求中的 owner 指定他人。POST 沿用 JSON、CSRF 和同源检查；电视禁止读取私有候选及关系。金额只接受 `0..100000000000` 的整数分，拒绝 bool、浮点或金额字符串。

### 5.1 GET /context

可选查询参数：`transactionId`、`shoppingId`、`linkId`、`q`、`page`；`q` 最多 80 字符且不含控制字符，`page` 为 `0..999999999` 的十进制整数文本，不接受多余前导零，固定 `pageSize=40`。明确聚焦的记录不会被搜索词或分页隐藏，追加的聚焦记录可使单个返回数组略超 40 项；订单入口仅提供已存在 `order_payment` 关系的付款证据，付款入口不限制其余付款候选。

返回字段：

| 字段 | 内容 |
| --- | --- |
| `version` | `1` |
| `transaction` | `{id,revision,kind,flow,currency}` 或 `null` |
| `payments` | 本人付款数组：`id,revision,title,date,currency,amountCents,refundedCents,netCents,reservedCents,availableCents,eligible,reasonCode` |
| `shopping` | 家庭采购数组：`id,revision,title,actual,done` |
| `links` | 本人关系数组：`id,revision,shoppingId,paymentId,amountCents,status,state,reviewReasons,appliedShoppingRevision,createdAt,updatedAt` |
| `warnings` | 待核对的提示字符串数组 |
| `pageInfo` | `{page,pageSize:40,paymentsMore,shoppingMore,linksMore}` |

关系 `status` 为持久化的 `active/revoked`；`state` 为读取时派生的 `current/needs_review/revoked`。来源或采购被修改、删除后，即使仍保留活动关系历史，也不能据此推断采购金额仍与付款一致。`eligible` 与原因提示用于选择前核对，确认时仍重新验证；搜索结果不是智能匹配的已确认结论。

付款 `reasonCode` 为 `not_payment/not_expense/duplicate/unsupported_currency` 或 `null`；关系 `reviewReasons` 可含 `source_missing/source_changed/source_ineligible/shopping_missing/shopping_changed`，不返回内部异常。金额仍被活动关系占用时不会因待核对状态自动释放，需本人更新或解除关系。

### 5.2 POST /preview

以下示例的 ID 和金额均为虚构。初次关联明确发送：

```json
{
  "operation": "apply",
  "paymentId": "synthetic-payment-id",
  "shoppingId": "synthetic-shopping-id",
  "shoppingRevision": 3,
  "amountCents": 7900,
  "done": true
}
```

更新同一付款的既有关系：

```json
{
  "operation": "update",
  "linkId": "synthetic-link-id",
  "revision": 1,
  "shoppingRevision": 4,
  "amountCents": 6900,
  "done": true
}
```

`revision` 是本人关系版本，`shoppingRevision` 是共享采购版本，不能互换。update 保留同一付款来源；换付款需明确处理旧关系后重新核对。每个 owner/shopping 的关系独立，不能借另一成员的 linkId 更新。

每种 operation 必须提供示例中的全部字段，且不能添加 owner、交易标题、照片、预算或其他字段。

撤销必须明确 mode：

```json
{
  "operation": "revoke",
  "linkId": "synthetic-link-id",
  "revision": 2,
  "mode": "detach_keep_current",
  "shoppingRevision": 5
}
```

另一 mode 为 `restore_if_unchanged`。采购已经不存在时，解除关系可提交 `shoppingRevision: null`；不得据此创建替代采购。

返回 `operation`、`linkId`、`before`、`after`、`payment`、`sharing`、`warnings`、`previewToken`、`expiresInSeconds`：

- `before`：`{shoppingId,revision,actual,done}` 或 `null`。
- `after`：`{shoppingId,actual,done}` 或 `null`；完整表示拟替换的共享字段。
- `payment`：`{id,currency,netCents,reservedOtherCents,availableCents}` 或 `null`。
- `sharing`：`{fields:["actual","done"],ledgerUnchanged:true}`。
- `expiresInSeconds`：`600`。预览仅核对，不执行采购、账单或资金变更。

### 5.3 POST /confirm

```json
{"previewToken":"仅使用本次本人预览返回的凭据"}
```

返回 `{operation,link,shopping,changedFields,replayed}`。`shopping` 是 `{id,revision,actual,done}` 或 `null`，`link` 为本人业务关系，`changedFields` 表示本次共享采购的实际变更字段；撤销或回放不意味着当前实体仍存在。确认失败保持原记录，客户端须保留草稿并显示错误，不自动重试写入。

未登录或服务端会话失效返回 401；电视／CSRF／同源拒绝、预览所属成员或会话不匹配为 403。context 中不存在或无权访问的私有记录为 404；版本冲突、确认时来源／分配／采购已变化或不能安全恢复原值为 409。过期、坏签名及格式无效的预览为 400；无效金额、币种及来源条件也不能产生可确认的成功预览。不要把所有“重新预览”错误都归为同一状态码。

### 5.4 本户存储与接入

新增 `hub_shopping_settlements` 与 `hub_shopping_settlement_receipts` 两张本户私有表，不修改公共实体结构，也不增加平台表；本版本为 **37 张户内表、2 张平台表**。

关系表保存本人、采购／付款稳定 ID、分配额、状态、版本与投影基线；回执表保存确认幂等及业务结果。活动关系有 `(owner, shopping_id)` 唯一约束，回执有 `(owner, nonce_digest)` 唯一约束。每位成员最多保留 20,000 条关系及 40,000 条回执，达到上限拒绝新确认，历史不会静默删除。

来源／采购删除后保留必要历史，不通过级联或旧预览重新生成被删除对象。本人导出由 `export_owned_settlements(con, owner)` 返回 `{links,receipts}` 白名单：links 仅含 `id/revision/shoppingId/paymentId/amountCents/status/appliedShoppingRevision/createdAt/updatedAt`；receipts 仅含 `id/operation/linkId/createdAt/changedFields`。不导出 context 的派生 `state/reviewReasons`，也不导出内部 nonce、上下文、投影前值、来源快照或摘要。原照片与旅行链接表保持不变。

## 6. 验收范围

新增跨模块测试文件为 [test_shopping_settlement_journeys.py](../tests/test_shopping_settlement_journeys.py)。在项目目录使用主环境 Python 执行：

```powershell
& 'C:\Users\caesarf\OneDrive - NVIDIA Corporation\Documents\AI\family-dashboard\.venv\Scripts\python.exe' -X utf8 -m pytest tests/test_shopping_settlement_journeys.py -q
```

2026-09-15，最终后端 [test_shopping_settlement.py](../tests/test_shopping_settlement.py) 通过 **44 项，29.46 秒**；跨模块专项通过 **10 项，6.85 秒**。这些专项均使用临时数据库和虚构输入；跨模块的真实 Flask／SQLite、合成图片及 ZIP 验证覆盖：

- `done=false/true` 的采购汇总；迁期保留实际金额、完成状态、照片、原 ID 和旅行关联。
- 实付确认使旧旅行预览返回 409，重新预览后保留最新采购。
- 两位成员对同一采购保有独立私有关联；共享 state、电视及另一成员 ZIP 没有私有来源或签名，`includeShared=false/true` 均验证。
- 删除旅行保留采购；删除采购前尚未确认或已经确认的旧预览均不重建，旅行明确生成的同 key 新采购也不会接收旧投影。
- 删除原付款保留采购和历史回执；照片编辑后不能恢复旧值，但明确解绑保留现值。
- 公共余额、私人月度财务、账本、对账关系、预算及旅行 `paid/saved/budget` 不因核对或迁期被重复记账。

本次完整 Windows 后端为 **1035 passed / 12 skipped，共 1047 项**；Linux：**1046 passed / 1 skipped**。上述 44 项和 10 项属于完整收集中的专项，不能再次相加。

浏览器使用临时 Flask／SQLite、虚构记录和本机 Edge：新 [采购实付界面](../tests/browser_shopping_settlement_check.py) **61 项**，受影响的 [既有对账保护](../tests/browser_finance_reconciliation_guard_check.py) **57 项**，合计 **118 项功能检查**；[工作台](../tests/browser_product_shell_check.py) 另有 **59 条页面／视口记录**，不混算为功能场景。新界面报告记录九张截图，覆盖 360／768／1440 三种宽度和三套主题；无 JavaScript 错误、外部请求或服务商调用。

后端专项阻断外部 socket 连接；浏览器使用本机临时地址和合成服务商，报告分别绑定实际源码与测试范围，不宣称浏览器脚本拦截了所有进程网络。验收不读取真实账单、不调用真实银行或生产业务写入，不代表实体电视、公网浏览器或新的 Microsoft／Google 写入已验收。发布时间、镜像、数据保留与迁移证据由 [VALIDATION](VALIDATION.md) 统一记录；离线模拟不能替代实际 Docker 恢复验证。
