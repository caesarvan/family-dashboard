# 独立消费观察

**当前版本：2026-09-15 20:23:00（北京时间），镜像 `sha256:651ecfd6bdb65cf04bb8778c8657a8ec0f27a123940683a44a8b9931a5f22352`。** 旅行资料、完整细项展示与分段定位已发布，保留此前全部模块；106 个方法／路径模板、43 张户内表（41 业务 + 2 认证）及 2 张平台表。源码与文档数量见 [README](../README.md) 及交接清单；测试、迁移和实际接入边界见 [VALIDATION](VALIDATION.md)。

## 用途与操作路径

从“财务中枢 → 个人财务基线 → 更新财务来源”进入，选择“仅更新消费观察”。用本机准备器生成的 JSON，核对消费报告生成时间、覆盖区间、月份／币种差异和移出窗口项，勾选明确确认后保存；随后“查看我的资产与消费观察”重新读取本人的展示。

本模式只刷新既有财产基线旁的本人消费报告快照，避免为了更新消费月份而强行补齐资产／贷款／收入来源映射。**必须已有本人财产基线**；缺失时预览返回 409，不自动初始化资产或共享汇总。新家庭初始基线仍走 [完整来源桥接](FINANCE-SOURCE-BRIDGE.md) 的核对过程。

- 资产、负债、收入、原基线日期及原共享汇总保持不变；不写账单、订单、投资、手工月度财务、共享采购或公共荷包。
- 报告可能含渠道补记、订单补记和不可读对账单，不代表已核对实付，不与 [账本月度收支](FINANCE-API.md) 相加。
- 不刷新邮箱、调用银行或付款平台，不配置新自动任务，不提供无人值守确认或后台文件上传。
- 只有本人可以读取观察、来源摘要与回执。家庭／成员由真实会话和家庭路由确定，客户端不能指定 owner；伴侣和电视不读取此内容，演示不会请求本接口。

## 本机准备与输入冻结

实现：[prepare-finance-source.py](../deploy/prepare-finance-source.py)，默认模式仍为 `baseline`。新模式明确使用 `--mode spending_observation`；配置只接受 `schemaVersion/sourceRoot/runFile`，不得携带完整基线模式的 `sources`。

虚构配置如下；实际文件和输出都应位于源码之外的本人私有目录：

```json
{
  "schemaVersion": 1,
  "sourceRoot": "C:\\PRIVATE\\Personal_Finance",
  "runFile": "C:\\PRIVATE\\run-2026-09-14.json"
}
```

```powershell
.\.venv\Scripts\python.exe -X utf8 deploy/prepare-finance-source.py --mode spending_observation --config "C:\PRIVATE\spending-source-config.json" --output "C:\PRIVATE\spending-observation-candidate.json"
```

只读取 `sourceRoot` 下三个固定产物及指定 run：

| 相对路径 | 用途 |
| --- | --- |
| `08_Budgets/all-email-spend-report-12m.json` | 月份／币种汇总、生成时间、覆盖和质量字段 |
| `08_Budgets/all-email-spend-transactions-12m.json` | 验证产物存在、大小、哈希与 JSON 结构；原始明细不放进候选 |
| `08_Budgets/statement-attachment-inventory-12m.json` | 同组产物完整性检查；不复制附件或原邮件 |

run 文件名为 `run-YYYY-MM-DD.json`，日期与带时区的 `generated_at` 相符；须 `status=success`、整数 `exit_code=0`、`login_action_required=false`。其文件清单须准确列出三产物的路径、字节数和修改时间，报告生成时间须与 run 一致。修改时间仅用于输入一致性，不是资产或交易业务日期。

每份输入最多 50 MB，三报告合计最多 100 MB。准备器冻结进程内字节、计算 SHA256，规范化后再次读取配置、run 和产物的哈希／mtime；变化、错误、越界、链接路径或输出覆盖来源均拒绝，原输出保留。候选通过验证后才原子替换源码外的输出。它不是服务器代读本机路径的接口；服务端只接收候选内容，不能凭摘要字符串证明原始来源真实性。

成功 stdout 仅为 `status:prepared`、`generatedAt`、`candidateDigest`、`sourceDigest`、`monthCount`，不输出金额或账户标签。`monthCount` 是月份／币种行数，不一定等于自然月份数。失败退出 1，只给固定说明。运行此命令不会向看板发送预览或确认。

## 候选格式与日期覆盖

候选本身是以下对象，不套 `private/shared`，不含 assets、liabilities、income、owner 或令牌。摘要均为说明用的虚构值，实际由 CLI 从输入字节计算。

```json
{
  "schemaVersion": 1,
  "kind": "spending_observation",
  "converterVersion": "spending-observation-v1",
  "sourceManifest": {
    "version": 1,
    "files": [
      {"path":"08_Budgets/all-email-spend-report-12m.json","sha256":"1111111111111111111111111111111111111111111111111111111111111111","bytes":1200},
      {"path":"08_Budgets/all-email-spend-transactions-12m.json","sha256":"2222222222222222222222222222222222222222222222222222222222222222","bytes":800},
      {"path":"08_Budgets/statement-attachment-inventory-12m.json","sha256":"3333333333333333333333333333333333333333333333333333333333333333","bytes":400}
    ],
    "run": {
      "sha256":"4444444444444444444444444444444444444444444444444444444444444444",
      "generatedAt":"2026-09-14T08:00:00+08:00",
      "status":"success",
      "exitCode":0,
      "loginActionRequired":false
    },
    "coverage": {
      "requestedStart":"2025-09-14",
      "requestedEnd":"2026-09-14",
      "knownGapsCount":1,
      "unreadableStatementsCount":2,
      "channelOnlyAdded":true,
      "orderOnlyAdded":false
    }
  },
  "spending": {
    "generatedAt":"2026-09-14T08:00:00+08:00",
    "requestedStart":"2025-09-14",
    "requestedEnd":"2026-09-14",
    "monthly":[{"period":"2026-08","currency":"CNY","grossSpendCents":15000,"refundCents":2000,"netSpendCents":13000,"transactionCount":3}],
    "quality":{"knownGapsCount":1,"unreadableStatementsCount":2,"channelOnlyAdded":true,"orderOnlyAdded":false}
  }
}
```

字段集合严格校验，未知字段拒绝；schemaVersion 必须为整数 1。规范化候选编码小于 1,950,000 字节，界面也拒绝达到该长度的文件。sourceManifest 无 `configDigest`，与完整财产模式不同；文件路径必须为上列三条且唯一，SHA256 为 64 位小写十六进制。files 和 monthly 会排序后再计算摘要。

`requestedEnd - requestedStart` 的日期差必须精确为 365 天，结束日须等于 `generatedAt` 在其原时区中的日期。这是生产者的滚动区间约定，不是“两个端点之间恰好 365 个含首尾日期”的说法。生成时间、run 和覆盖字段必须相互一致；首尾月份可能只覆盖一部分，不能把它们标为完整自然月。质量缺口数为零也不证明全部银行、渠道和账单已覆盖。

monthly 必须包含 1～240 条唯一的 `(period,currency)`，period 是窗口内 `YYYY-MM`，currency 是三位大写字母；没有自动汇率转换。`grossSpendCents/refundCents` 是非负整数分，`netSpendCents` 可负，绝对值上限均为 `100000000000000`；拒绝字符串、浮点或布尔值，净额须等于支出减退款。`transactionCount` 为 `0..1000000` 的整数。质量字段的两个计数同为该整数范围，两个补记标志为布尔值。

## 接口契约

由 [finance_source_bridge.py](../finance_source_bridge.py) 注册并分派到 [spending_observations.py](../spending_observations.py)。不新增 URL；未指定 mode 时保留原完整财产模式。成员 POST 仍需同源及 `X-CSRF-Token`，电视拒绝。

| 方法 | 路径 | 模式位置 |
| --- | --- | --- |
| GET | `/api/finance-baseline/imports/status?mode=spending_observation` | 查询参数 |
| POST | `/api/finance-baseline/imports/preview` | JSON 顶层 `mode` |
| POST | `/api/finance-baseline/imports/confirm` | JSON 顶层 `mode` |

### 状态读取

| 响应字段 | 含义 |
| --- | --- |
| `mode` | `spending_observation` |
| `expected` | `expectedRevision/expectedSourceDigest` 为本人独立观察版本；`expectedBaselineRevision/expectedBaselineSourceDigest` 为当前本人财产基线版本，均须原样带入预览 |
| `current` | 独立观察的 `{revision,sourceDigest,acceptedAt}`，尚无时 null |
| `baseline` | `{exists,asOf,balanceAsOfStart,balanceAsOfEnd}`，缺失日期为 null；不是消费报告日期 |
| `previousCoverageKnown` | 当前展示观察是否具有完整可比较的日期／结构 |
| `requiresUnknownCoverageAcknowledgement` | 有旧观察但覆盖无法比较时为 true |
| `spending` | 可比较时仅 `{generatedAt,requestedStart,requestedEnd}`，否则 null；status 不返回完整月度金额 |
| `warnings` | 固定可读说明数组，可能说明选用完整基线中的较新观察 |

首次独立观察的 expectedRevision 为 0、expectedSourceDigest 为 null；**这不代表可以忽略现有基线版本**。例如已有基线 revision 4，客户端必须发送 status 返回的 4 和对应摘要。没有基线也可以读取状态，但不能确认创建观察。

### 预览请求与响应

精确请求字段为 `mode/candidate/expectedRevision/expectedSourceDigest/expectedBaselineRevision/expectedBaselineSourceDigest/acknowledgeUnknownPreviousCoverage`。四个版本字段必须同时匹配当前值及类型，不能把整数写成字符串。最后一项必须是布尔值；旧覆盖未知时必须由本人明确勾选 true，表示保留旧快照、不推断旧覆盖，不是允许日期倒退。

使用实际状态和上一节候选组装请求，例如：

```javascript
const payload = {
  mode: 'spending_observation',
  candidate: preparedCandidate,
  ...status.expected,
  acknowledgeUnknownPreviousCoverage: userAcknowledgedUnknownCoverage
};
```

响应字段为 `mode/previewToken/candidateDigest/sourceDigest/expected/spending/changes/warnings/baseline/assetBaselineUnchanged/expiresIn`。spending 是完整规范化月度观察；baseline 只含原 `asOf/balanceAsOfStart/balanceAsOfEnd`；assetBaselineUnchanged 为 true，expiresIn 为 1200 秒。changes 为：

```json
{
  "added": 1,
  "updated": 0,
  "preserved": 2,
  "removedMonths": [{"period":"2025-08","currency":"CNY"}]
}
```

这是变更字段的节选示意，added／updated／preserved 按月份与币种计行。removedMonths 包括已移出新滚动窗口的旧月份，以及一个受限的首月边界情况：新旧覆盖均可比较且符合 365 天约定、新 requestedStart 向前推进、并且新首月起点不是 1 号时，旧记录中对应新首月的币种分组可能因最后一笔来源记录滚出而消失。后者仍列入 removedMonths，预览警示它只是可能退出、需本人核对报告；不补零，也不推算原交易日期。完整窗口月份或不满足该首月例外的旧月份／币种消失仍返回 409，不能把其他缺源当删除。生成时间或覆盖结束日期倒退也返回 409，同时比较原有效展示与已经存储的独立观察，不能先替换旧基线绕过防退。预览不写观察、回执或基线。

### 确认与历史回执

精确请求为 `{mode,candidate,previewToken}`。candidate 必须与预览规范化语义相同；四个 expected 不重复放进 confirm，它们已经进入签名。令牌有效 20 分钟，绑定候选摘要、本人、家庭、登录会话凭据与认证版本，换设备会话或身份不能复用。

虚构响应如下：

```json
{
  "receiptId":"5555555555555555555555555555555555555555555555555555555555555555",
  "status":"imported",
  "revision":1,
  "sourceDigest":"6666666666666666666666666666666666666666666666666666666666666666",
  "candidateDigest":"7777777777777777777777777777777777777777777777777777777777777777",
  "acceptedAt":"2026-09-15T06:00:00+00:00",
  "replayed":false,
  "assetBaselineUnchanged":true
}
```

确认在 `BEGIN IMMEDIATE` 内核验身份及两套 CAS，原子保存本人当前快照、持久回执与审计，失败全部回滚。相同 candidate 再预览确认可返回 `status:unchanged`，不改变当前观察 revision 或接受时间；相同有效令牌重放返回原回执并置 replayed=true。旧回执不代表现在仍是该版本，也不会重建后来删除的观察或基线。要显示当前状态，另读 status 与本人 private，而不是用回执替换当前最新展示。

这与 [账单文件确认](FINANCE-IMPORT.md#导入确认回执与实际月份) 的内容去重协议不同：后者没有这两张快照／回执表。已发送的写请求不能由关闭页面撤销。UI 在确认后提供查看本人资产与消费观察的入口，使用新的本人读取；它不自动再次提交确认或启用后台调度。

常见错误：400 格式、字段、金额或报告元数据不正确；401 会话失效；403 非当前会话／家庭／成员的签名、TV 或 CSRF／同源不满足；409 预览过期、任一 CAS 改变、缺基线、未知旧覆盖未确认、日期倒退或不符合首月例外的窗口内旧月份丢失。409 保留候选供重新核对；重预览会撤销旧确认资格，不能自动重放旧写入。

## 持久化与本人读取

模块在原来源桥接注册时初始化，扩展对象为 `app.extensions['spending_observations']`。下面是实际两表与索引 DDL 的参考；由经过审核的发布初始化执行，不是在运行服务中手工贴 SQL 的迁移步骤。

```sql
CREATE TABLE IF NOT EXISTS finance_spending_observations(
    owner TEXT PRIMARY KEY REFERENCES users(id), revision INTEGER NOT NULL,
    source_digest TEXT NOT NULL, candidate_digest TEXT NOT NULL,
    candidate_json TEXT NOT NULL, accepted_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS finance_spending_receipts(
    id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
    candidate_digest TEXT NOT NULL, source_digest TEXT NOT NULL,
    expected_revision INTEGER NOT NULL, expected_baseline_revision INTEGER NOT NULL,
    observation_revision INTEGER NOT NULL, status TEXT NOT NULL,
    accepted_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS finance_spending_receipts_owner
    ON finance_spending_receipts(owner,accepted_at);
```

每个 owner 保留一个独立当前候选快照和多条确认回执。candidate_json 只保存规范化汇总、报告摘要与覆盖，没有原始交易行、账户匹配值、附件、原令牌或会话凭据。原 `finance_baselines` 的 private_data、shared_data、日期、revision、source_digest 不由本模式 UPDATE；已有原快照完整保留。

`GET /api/finance-baseline/private` 在返回副本中选择消费观察，不写回基线：

1. 没有独立观察时沿用原基线 spending。
2. 原基线 spending 可完整比较，且生成时间严格较新、覆盖结束日期不早于独立观察时，使用原基线该观察，并提示独立版本仍保留。
3. 其他情况使用已确认独立观察；同一生成时间而内容不同会提示冲突，不把两个版本相加。

存在独立观察时，private 响应增加 `spendingObservation:{revision,sourceDigest,acceptedAt,origin,warnings,assetBaselineUnchanged}`。其中 revision／sourceDigest 标识独立快照，即使 origin 为 `baseline`；origin 可能为 `baseline` 或 `spending_observation`。页面显示的是所选观察自己的生成时间、请求区间与质量状态，不能据此宣称资产余额更新。

本人 ZIP 的 `personal.spendingObservations` 含 `{current,receipts}`，只导出本人规范化当前快照和公开业务回执字段；shared 不包含观察，伴侣不读取它。具体导出与恢复范围统一见 [PORTABILITY](PORTABILITY.md) 和 [DEPLOYMENT](DEPLOYMENT.md)。2026-09-15 15:10 的历史版本已按两表新增方案核验 40→42 迁移，该次首次迁移并非零 schema 变化；16:25 历史运行版本没有结构迁移，当时使用 42→42 检查；20:23 旅行资料已独立完成 42→43。旧零结构示例不能用于当前 43 表，后续 43→43 指导尚待独立实现与验证。

## 验证与接手

实现分工：[spending_observations.py](../spending_observations.py) 管规范化、版本、日期和事务；[finance_source_bridge.py](../finance_source_bridge.py) 分派 mode；[finance_baseline.py](../finance_baseline.py) 只在本人响应叠加展示；[finance-source-ui.js](../static/finance-source-ui.js) 管文件选择、明确预览确认与原节点身份保护；[finance-baseline.js](../static/finance-baseline.js) 展示所选观察的日期和质量。

针对性测试入口如下，只使用临时合成数据；不需要真实银行或邮箱账户：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_spending_observations.py tests/test_finance_source_bridge.py tests/test_finance_baseline.py
.\.venv\Scripts\python.exe -X utf8 tests/browser_spending_observations_check.py
```

独立后端／CLI 检查包括预览无写、原基线整行保留、双 CAS、窗口缺失、月份与币种、旧覆盖未知确认、重放不复活、跨成员／家庭／TV、CLI 输入变化保留原输出和本人导出白名单。这些检查只覆盖合成输入与本地行为，不能据此声明真实来源准确；已发布组合的冻结、浏览器及发布证据以 [VALIDATION](VALIDATION.md) 登记为准。

本机已基于现有 Personal_Finance 报告只读准备源码外消费观察候选；尚未上传或在真实成员会话确认导入，未启用自动刷新或更改既有邮箱自动化。该转换不等于服务器已接收，更不证明全部报告准确。资产日期、贷款、映射和覆盖仍按 [来源桥接第 2.1 节](FINANCE-SOURCE-BRIDGE.md#21-真实来源映射审查2026-09-15) 核对。
