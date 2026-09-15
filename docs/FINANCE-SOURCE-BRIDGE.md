# 个人财务来源桥接

**当前版本：2026-09-15 16:25:03（北京时间），镜像 `sha256:f1e4cc56979f793f32585f498fa2fca55987356bd68f67e8cc6c14f0b1b6a01d`。** 旅行执行进度、真实待同步提示及两个订单表头兼容已发布，保留此前全部模块；源码／文档数量见 README 和逐文件清单、101 个方法／路径模板、42 张户内表及 2 张平台表。本轮无结构迁移。真实云写与其他外部验收仍按 [VALIDATION](VALIDATION.md) 单列。

**状态：来源 API 与界面已于 2026-09-15 02:33:28 发布；真实数据接入范围见 [HANDOFF](HANDOFF.md)。** 本地候选生成 CLI、本人预览／CAS 确认已提供；未启用无人值守刷新、邮箱扫描或新调度。真实来源已完成只读结构与身份映射审查，尚未生成或提交真实完整候选；私人映射草案及已证实阻断见第 2.1 节，身份匹配不等于余额、日期或接入已确认。现有基线结构见 [API](API.md) 与 [finance_baseline.py](../finance_baseline.py)。

**CLI 适配已随 2026-09-15 03:58:15 源码发布：** 第 7.1 节的银行资产／负债显式分类及绑定已核对文件哈希的尾备注兼容策略，仅用合成文件验证。它们不代表第 2.1 节的真实记录已接通，也不改变服务器的日期、防缺源、跨集合或 CAS 规则。

默认 `baseline` 模式把既有、已完成核验的个人财务产物转换为带日期和覆盖说明的本人基线，并更新已经批准共享的资产／负债小计。已提供 `spending_observation` 模式，只更新本人消费观察，原资产／负债／收入及共享汇总不写回，见 [独立消费观察](SPENDING-OBSERVATIONS.md)。消费报告、资产快照、手工投资及公共荷包各有口径，不能简单相加。

## 1. 已发现的输入与代码

来源根目录为维护者本机的 `Personal_Finance`；以下均为相对于该目录的路径。实现时从私人配置指定根目录，不将实际明细复制进 family-dashboard 仓库。

| 输入相对路径 | 可读取内容 | 更新边界 |
| --- | --- | --- |
| `04_Banking/accounts.csv` | 余额、币种、统计日期及数据来源 | 余额日期逐行保留；用途描述不是已核对的资金到账证明 |
| `03_Loans/loans.csv` | 已记录的负债与来源 | 当前格式缺少独立余额核对日期；不能用合同日期或文件修改时间冒充 |
| `05_Investments/holdings-template.csv` | 持仓、币种、估值和统计日期 | 缺估值保持缺失；可能与银行账户或看板投资重复 |
| `05_Investments/property-valuation.csv` | 房产估值及来源日期 | 购入价格不能自动替代当前估值 |
| `01_Income/income-history.csv` | 历史收入、合同口径及期间 | 与本月实际税后到账收入分开 |
| `08_Budgets/all-email-spend-report-12m.json` | 月度消费观察、生成时间、覆盖与质量标记 | 属于来源报告口径，不直接成为实际支付账本 |
| `08_Budgets/all-email-spend-transactions-12m.json` | 生产者产物完整性核对；必要时本人私有复核 | 默认只做哈希／元数据验证，不逐笔导入看板 |
| `08_Budgets/statement-attachment-inventory-12m.json` | 生产者产物完整性核对 | 不把原邮件或附件内容带入共享基线 |

旧转换器还引用 `01_Income/nvidia-comp-policy.csv`、`01_Income/nvidia-first-payroll.csv`、`05_Investments/nvidia-rsu-vesting.csv`、`05_Investments/espp-parameters.csv`、`08_Budgets/finance-refresh-2026-09-10.json` 和 `README-待补充资产与保障.md`。这些属于补充依据；不能因旧脚本读过，就将其中的预测、未归属权益或待核对事项自动升级为当前资产／实际收入。固定日期的 refresh 文件也不能代替最新成功运行记录。

运行记录位于 `<CODEX_HOME>/automations/automation-10/run-YYYY-MM-DD.json`，不在财务仓库内。既有生产代码 `tools/outlook_bill_importer/src/outlook_bill_importer/refresh.py` 会生成消费报告及明细；本桥接读取它们的结果，**不调用 refresh、Graph、邮箱登录或附件下载**。

已有一次性转换器位于私人目录 `<私人访问目录>/finance-import/build_baseline_private.py`，产出 `baseline-private.json` 与 `baseline-shared.json`。它含固定日期、估计项和基于行号的标识，且先覆盖输出再做部分校验，不能直接加进定时任务。相邻 `import-and-verify.py` 含外部命令调用，也不是只读预览入口。

旧 [deploy/import-finance-baseline.py](../deploy/import-finance-baseline.py) 仍是维护者从标准输入整份导入的兼容入口，不具备新接口的预览／CAS／防回退保护。普通来源更新使用本页的新流程，不绕过本人确认直接调用旧 CLI。

## 2. 调查时的证据边界

- 消费报告生成于 2026-09-14 10:52:55+08:00，请求覆盖 2025-09-14 至 2026-09-14。
- 同日运行记录标记 success、退出码为零且无需重新登录；生成时间与报告一致，所列三个产物存在且字节数匹配。运行记录没有产物 SHA256，这些检查不等同输入集合的加密摘要核验。
- 银行余额记录日期为 2026-08-28 至 2026-09-08；持仓与房产记录日期为 2026-08-28。消费报告变新不证明这些资产变新。
- 报告包含渠道补记与订单补记；仍有不可读对账单。即使 `coverage.known_gaps` 为空，也没有完整覆盖的证明。
- 以上仅是该次文件快照的观察。实施或运行时必须重新检查，不能把本页日期当作长期有效状态。

### 2.1 真实来源映射审查（2026-09-15）

本次只读核对上述五类 CSV、私人旧转换脚本和旧基线文件。五份 CSV 的哈希及字节数均与旧基线保存的来源记录一致；共 **49 行自然键唯一**。其中 **44 行**还能由旧脚本的静态 `id/source/label` 映射表达式和对应旧记录相互印证，已给出稳定 `id/legacyId` 候选；长期 ID 按自然键生成，旧行序只用于核对已冻结的来源身份。

其余 **5 行**属于旧脚本明确跳过的持仓，没有可确认的旧记录身份，本次未为它们给出 ID。不能把“未出现在旧基线”直接解释为需要新增的资产，须先核对重复覆盖、权益归属和原排除原因。44 组候选也仍是待本人审查的身份映射，未成为已批准的可执行配置。

已证实的接入阻断如下；不同类别可能涉及同一条记录，数量不能相加解释为新增记录数。

| 问题 | 已核对数量 | 当前边界 |
| --- | --- | --- |
| 贷款余额缺独立核对日期 | 10 条 | 旧脚本使用固定日期，CSV 没有余额核对日期列。合同起止日期、mtime、自由文本推测及旧导入值均不作为独立证据；日期保持未确认 |
| 银行记录的资产／负债集合不匹配 | 4 条 | 旧基线将它们放在负债集合，02:33 已发布版的 `banking` 适配器只输出资产；本次已发布 CLI 增量的显式分类见第 7.1 节，尚未用于这些真实记录。不能跨集合冒充映射完成，也不能把负余额直接变成共享资产或擅自计入负债小计 |
| 收入期间与旧 `asOf` 的日期语义不一致 | 12 条 | 现有转换把收入期间转为期间结束日期，与旧脚本固定 `asOf` 不同，会触发现有记录日期防退。期间结束日期不是实收日期，不能随意改成较新日期绕过 CAS |
| 五类 CSV 映射未覆盖的旧收入 | 2 条 | 缺少本次范围内的完整来源映射。必须补适配依据或经审查的保留策略，不能省略后提交整份基线 |
| 持仓 CSV 缺少尾部备注列 | 2 行 | 备注在业务上可选，但当前行缺列，和存在一个空备注字段不同；02:33 已发布版准备器会拒绝该来源文件。本次已发布 CLI 增量仅提供显式审查后兼容策略，不自动修复该真实来源 |

私人审查保存在 `<私人访问目录>/finance-source-mapping-review/`，包括 `private-mapping-review.json`、`private-config-draft.review.json` 和回读核验记录。草案刻意不符合 CLI 配置 schema，标记为阻止导入，不能传给准备器或来源 API；逐条自然键、旧记录标识和账户标签只留在私人文件中，不进入源码、发布包或通用日志。

回读核验确认 **7 个输入文件哈希保持不变**，44 组候选 ID 无重复，10 条贷款日期仍未填写。未运行旧构建／导入脚本，未读取 `.env` 或 OAuth 文件，未刷新邮箱、调用服务器或修改财务源；**未生成、预览提交或导入任何真实完整候选**。本次也未重新核验成功 run 与消费报告覆盖，不能把此前报告日期或已部署 API 当作真实财务已经自动接通的证明。

银行显式分类与尾备注兼容机制已在第 7.1 节交付；下一步是将机制应用到经本人核对的真实映射、排除口径和文件哈希。收入期间／快照日期的迁移语义及遗漏旧记录保留仍需解决，不能放宽必需金额、身份或日期字段校验。贷款仍需独立余额日期依据。解决这些问题后，重新冻结来源、核验成功 run 和报告覆盖，另行生成完整候选，并读取当前目标版本执行本人预览／CAS 确认。现有缺源保旧、日期防退和共享白名单规则继续有效；渠道／订单补记仍不得写成实付账本。

## 3. 输入验收与冻结

每次候选生成按以下顺序执行：

1. 只接受指定来源根目录内的白名单文件；拒绝根目录之外的路径、符号链接越界、意外附件或任意文件读取请求。
2. 找到所需日期的成功运行记录，检查 `status`、`exit_code`、`login_action_required`、`generated_at` 与产物清单。运行失败、缺产物或生成时间不匹配时，不使用看起来较新的残留文件。
3. 核对记录列出的文件大小和修改时间；另计算每个实际输入文件的 SHA256。金额解析使用 Decimal，不能经二进制浮点隐式四舍五入。
4. 将白名单输入冻结为进程内不可变字节副本，记录转换器版本、来源相对路径、字节数、哈希、来源日期、运行记录摘要和覆盖信息。再次读取原文件摘要及修改时间，变化则丢弃本次候选后重试；不额外复制原账单到仓库。
5. 从冻结副本转换；候选生成后再次验证输出结构、逐项小计和隐私白名单。通过后才原子发布完整候选清单；不能分别覆盖两个正式 JSON 后再核验。

目前生产者没有跨产物的原子发布标记。首次实现应采用前后哈希复核与稳定产物检查；后续可由生产者最后写入含全产物哈希的完成 manifest，使读取者只消费一个完成版本。

源文件的“修改时间”用于检测读取竞态，不用作财务业务日期。调度等待、重试或重新打包也不能刷新财务的日期或完整度。

## 4. 日期、覆盖与汇总规则

沿用 schemaVersion 1 的 private/shared 结构，新增来源桥接元数据只进入私有部分。

| 字段／口径 | 当前规则 |
| --- | --- |
| `asOf` | 本次接受的来源版本日期，不是桥接脚本启动日期 |
| `importedAt` | 实际接收时间，独立于来源日期 |
| 每项 `asOf` | 原始余额／估值／收入记录的业务日期 |
| `balanceAsOfStart` / `balanceAsOfEnd` | 根据采用的资产与负债记录日期计算，不硬编码 |
| `spending.generatedAt` 与请求区间 | 保留消费报告自己的时间与覆盖范围，不覆盖余额日期 |
| `complete` | 默认保留部分覆盖；只有所需资产负债清单和估值均有有效依据时才可改变 |
| `recordedAssetCents` / `recordedLiabilityCents` | 仅汇总明确纳入的同币种、非缺失记录 |
| 完整资产／负债／净资产 | 不完整时保持空值，不能用已有小计伪装全量结果 |

外币没有经明确核对的换算依据时，不进入人民币共享小计。未归属权益、缺估值、到账未确认、未核对信用余额及可能重复的账户记录应保留状态和排除原因。

贷款缺少核对日期时，保留已有已知日期及日期依据，或者将该项列为待补证据；不因为 CSV 更新而自动前推日期。行顺序变化不应产生新资产，需在私人配置中建立稳定标识／对应关系，不能继续以 CSV 行号作为长期身份。

## 5. 消费、订单和投资不重复叠加

来源报告已经融合银行、支付渠道与订单，其 `channel_only_spend_added`、`order_only_spend_added` 等质量信息必须保留在私有覆盖说明中。

**渠道补记和订单补记不能由桥接直接写成已确认实付。** 本桥接只把报告月度汇总作为 `spending.monthly` 的来源观察，不写入 `hub_transactions`，不调用对账确认，不修改 `private_finance` 的手工月度快照，也不回填公共荷包支出或余额。

已存在的 `hub_investments` 与资产基线保持独立视图，不把两者直接相加。未来如需统一资产清单，先由本人确认来源记录与看板投资的对应关系，再按单一来源计数；转换器不能凭同名机构猜测是同一账户。

合同收入、历史收入、预测到手收入、实际到账和未归属权益维持不同状态。消费减少也不能反向推导当前账户余额，转账不能凭单边邮件当作工资或新资产。

## 6. 私密范围与共享授权

本人私有基线可包含账户来源、收入、持仓、逐项状态及核对说明；伴侣和电视只使用现有共享字段白名单。原始邮件、交易记录、账户标识、来源完整路径、凭据与诊断原文不得进入共享 payload、运行日志或通知。

继续使用已批准的“共享资产／负债汇总，明细仅本人可见”范围。自动更新不得顺带开放个人收入、消费、投资持仓明细或新的数据类别；共享范围变化必须与普通来源刷新分开处理。

候选目录、冻结源和旧版本属于私有数据，保存在源码发布白名单之外。运行日志只输出状态、日期、记录计数、转换版本与非敏感摘要，不输出金额、账户标签、邮箱、令牌或原始记录。

## 7. 本地 CLI 与私人配置

实现位于 [prepare-finance-source.py](../deploy/prepare-finance-source.py)，共用 [finance_source_bridge.py](../finance_source_bridge.py) 的候选校验。脚本只准备文件，不连接看板、读取服务器凭据、刷新邮箱或写数据库。

在源码目录运行，参数均指向源码之外的私人位置：

```powershell
.\.venv\Scripts\python.exe -X utf8 deploy/prepare-finance-source.py --config "C:\PRIVATE\finance-source-config.json" --output "C:\PRIVATE\finance-source-candidate.json"
```

默认 `--mode baseline` 的配置顶层只接受 `schemaVersion`、`sourceRoot`、`runFile`、`sources`。消费观察模式的精确配置不同，只接受前三项，不接收 `sources`，见 [模式差异](SPENDING-OBSERVATIONS.md#本机准备与输入冻结)。以下是虚构的单来源配置示意；实际配置必须逐条覆盖所选 CSV 的全部非空记录，包括明确排除的记录。

```json
{
  "schemaVersion": 1,
  "sourceRoot": "C:\\PRIVATE\\Personal_Finance",
  "runFile": "C:\\PRIVATE\\run-2026-09-14.json",
  "sources": [{
    "kind": "banking",
    "path": "04_Banking/accounts.csv",
    "records": [{
      "id": "cash-stable-example",
      "match": {"尾号": "SYNTHETIC-ONLY"},
      "label": "示例资产",
      "include": true,
      "exclusionReason": ""
    }]
  }]
}
```

| 配置字段 | 规则 |
| --- | --- |
| `sources[].kind` | `banking / loans / holdings / property / income`；分别只接受第 1 节对应固定 CSV 路径 |
| `sources[].encoding` | 可选 `utf-8-sig`（默认）、`utf-8`、`gb18030` |
| `sources[].allowMissingTrailingNotes` | 本次已发布 CLI 增量；可选布尔值，默认 `false`。仅允许 holdings／property／income，且表头最后一列必须精确为 `备注`；详见第 7.1 节 |
| `sources[].reviewedTrailingNotesFileSha256` | 启用上述策略时必填，64 位小写十六进制，须精确匹配本人已核对的 CSV 原始文件字节；策略未启用时不可填写 |
| `records[].id` | 全候选唯一、长期稳定；1～100 个 ASCII 字母／数字／`_.:-`，不得采用来源行号 |
| `match` | 当前 CSV 已有列名和精确文本值；必须唯一匹配一条且不同映射不得消费同一行 |
| `label` | 私有界面显示标签，最多 200 字符；配置中的匹配值不会写入候选 |
| `include` / `exclusionReason` | 明确是否进入资产／负债小计；排除时理由必填。收入、外币、缺估值及非 `dated_record` 状态不能纳入 |
| `date` / `dateBasis` | 来源缺业务日期时的人工核对日期／依据；贷款必须提供。不能使用合同日期／mtime 自动填充 |
| `legacyId` | 可选：本人核对后将旧基线记录绑定到新稳定 ID。省略时先按相同 `id` 匹配 |
| `recordType` | 本次已发布 CLI 增量，仅 banking 映射允许 `asset / liability`；省略沿用旧配置的 asset 行为，不根据账户类型文字或余额正负猜测 |
| `liabilitySign` | 仅 banking 且 `recordType=liability` 时允许并必填：`positive / negative`；资产或其他适配器携带此字段会拒绝 |
| `currency` | 可选，仅来源没有币种列时使用，默认 CNY；不提供汇率或进行换算 |
| `status` | 可选；默认按已记录金额、未估值或历史收入区分。未归属／待确认状态只能排除 |

金额从适配器固定列读取，使用 Decimal 转为整数分；不提供手工金额覆盖。收入 `YYYY-MM` 或 `YYYY` 转为该期间结束日期，并标明是历史税前期间口径，不能据此认定到账。来源格式不明确时拒绝，不猜测。

三个消费报告产物始终必需。成功 run 必须有 `status=success`、整数 `exit_code=0`、`login_action_required=false`、带时区的 `generated_at`，文件名日期须匹配。其 `files` 恰好列出三个产物的 `path/bytes/modified_at`；路径不得越界，修改时间容忍仅限小于一秒的表示精度。报告的生成时间须与 run 完全一致。

每个文件最多 50 MB，整组来源最多 100 MB，每份 CSV／每类候选最多 500 条，月度观察最多 240 条。配置、输出、run 不得通过符号链接／junction 访问；输出不能位于源码或来源目录，也不能覆盖配置／run。候选经过结构、日期和金额验证、原文件哈希及 mtime 二次检查后原子替换。POSIX 下临时输出权限为 0600；Windows 仍应把私人目录放在仅本人可访问的 ACL 范围内。

默认 baseline 模式成功 stdout 只有 `status/asOf/candidateDigest/sourceDigest/counts`；消费观察模式改为 `status/generatedAt/candidateDigest/sourceDigest/monthCount`。失败退出 1，仅输出固定提示，保留原候选。没有 `--write`、远端地址或自动确认选项。

### 7.1 已发布 CLI 增量：显式银行分类与已核对尾备注格式

同一 banking CSV 可包含资产和负债，每条仍由精确自然键映射。资产输出到 `assets`、类别 `cash`；负债输出到 `liabilities`、类别 `liability`。声明 `liabilitySign=positive` 时源值必须大于或等于零；声明 `negative` 时源值必须小于或等于零，验证后取相反数成为非负整数分。零与负零都规范化为零，未知余额仍为 `null`，不能进入共享小计。资产负值、符号与声明相反、缺负债符号口径、亚分金额均拒绝，不能通过取绝对值自动修正。

例如下列虚构映射表示源文件按负数记录的负债，实际是否进入小计仍由原有 `include/exclusionReason` 决定：

```json
{
  "id": "bank-liability-synthetic",
  "legacyId": "old-liability-synthetic",
  "match": {"尾号": "SYNTHETIC-DEBT"},
  "label": "示例负债",
  "recordType": "liability",
  "liabilitySign": "negative",
  "include": false,
  "exclusionReason": "示例：与已有负债重复覆盖，继续排除"
}
```

这可为首次导入、新记录，或旧记录本来就在正确集合中的同集合 `legacyId` 更新生成候选。它不提供跨集合迁移：把既有 asset 改放 liabilities，即使保留同一 ID 或 legacyId，现有服务器仍会因旧资产未被消费而返回 409 并保留基线。不得通过换 ID、删旧项或改服务器守卫绕过。外币继续按原币记录并排除人民币小计，无汇率换算；共享小计仅由服务器按现有白名单重算。

CSV 默认要求每行与表头列数一致；明确写出的尾部空备注字段无需兼容开关。仅当持有人检查了具体源文件，并确认短行代表省略末尾备注时，才可在该 source 上同时设置 `allowMissingTrailingNotes=true` 与 `reviewedTrailingNotesFileSha256`。摘要覆盖文件原始字节，不是规范化文本；文件换版、换行或编码变化都需要重新核对摘要，不能定时自动更新这个审查标记。

兼容策略仅对上述三种已知适配器、末列精确为 `备注`、且恰少最后一格的行补一个空字符串。可判定的多列、缺多格、缺必需金额／日期表头、备注并非末列、重复／空表头和不闭合引号仍拒绝；贷款的独立日期配置要求不变。带引号的逗号或换行按严格 CSV 规则解析，不凭拆字符串猜列。

**CSV 本身存在不可判别的歧义：** 中间漏掉分隔符可能与省略最后一格形成完全相同的字节。显式策略和文件 SHA256 只绑定持有人核对过的格式声明，不能自动证明金额或中间字段语义正确，也不能称为全面检测中间缺列。无法作出这一确认时保持默认拒绝，并要求来源显式写出空备注字段；候选预览仍须逐项核对金额、币种和日期。

分类、符号、兼容策略和审查摘要都参与 `configDigest`，文件哈希仍参与来源 manifest；配置或输入在准备期间变化会拒绝且保留原输出。输出候选仍使用原 HTTP schema，不包含原始匹配值或这些配置字段。本增量不读取真实私人配置，不生成真实完整候选，不补贷款日期，不更改收入期间或旧记录日期防退规则。

## 8. 候选、预览与确认 HTTP 契约

以下是默认完整基线模式；CLI 文件顶层就是 `candidate`，无需包一层 `private/shared`。候选消费观察的不同字段与四个 CAS 预期值见 [SPENDING-OBSERVATIONS](SPENDING-OBSERVATIONS.md#接口契约)：

| 顶层字段 | 内容 |
| --- | --- |
| `schemaVersion` / `converterVersion` | `1` / `finance-source-v1` |
| `asOf` | 成功生产任务生成时间所使用的本地日期 |
| `sourceManifest` | `{version:1,files:[{path,sha256,bytes}],configDigest,run,coverage}`；无绝对路径或原始匹配值 |
| `sourceManifest.run` | `{sha256,generatedAt,status,exitCode,loginActionRequired}` |
| `sourceManifest.coverage` | `{requestedStart,requestedEnd,knownGapsCount,unreadableStatementsCount,channelOnlyAdded,orderOnlyAdded}` |
| `assets / liabilities / income` | 每项 `{id,legacyId?,label,category,amountCents,currency,asOf,status,source,includedInRecordedSubtotal,exclusionReason,dateBasis}` |
| `spending` | `{generatedAt,requestedStart,requestedEnd,monthly,quality}`，只作为私有来源观察 |
| `spending.monthly[]` | `{period,currency,grossSpendCents,refundCents,netSpendCents,transactionCount}`；月份与币种唯一，净额须等于支出减退款 |

`amountCents` 为非负整数分或明确未估值的 `null`；`netSpendCents` 可为负。客户端 `owner/shared/totals/importedAt` 以及其他未知字段会被拒绝。服务端以当前认证成员填 owner，并重算日期范围、资产／负债小计和共享排除标记；完整资产、负债、净资产始终为 `null`，`complete=false`。

三个接口均只供登录成员，电视拒绝；POST 复用应用同源与 CSRF 守卫。`GET /space/<slug>` 是切换家庭的导航入口：服务端设置签名的 `household_space` 路由 Cookie，清除原成员会话和电视 Cookie，再以 `303` 跳转到 `/`。切换后须在目标家庭重新登录，可先用 `GET /api/spaces/current` 核对当前空间。

后续请求携带目标家庭的路由 Cookie 与成员会话，API 路径仍为 `/api/finance-baseline/imports/...`；不要拼成 `/space/<slug>/api/...`。路由 Cookie 本身不授予成员权限，也不能通过请求字段选择其他成员或数据库。

### GET `/api/finance-baseline/imports/status`

无请求体。返回：

```json
{
  "current": null,
  "lastReceipt": null,
  "coverage": "partial_dated_records",
  "warnings": ["来源观察不会写入实付账本、投资账户或公共荷包。"]
}
```

存在基线时 `current` 为 `{revision,sourceDigest,asOf,balanceAsOfStart,balanceAsOfEnd}`；存在回执时 `lastReceipt` 使用下述确认响应格式。status 不返回账户、金额或来源匹配值；也不假装持有尚未提交的本地候选。

### POST `/api/finance-baseline/imports/preview`

请求 `{candidate,expectedRevision,expectedSourceDigest}`。首次使用 `0/null`；否则使用刚读取 status 的目标版本。返回：

```text
{
  previewToken, candidateDigest, expectedRevision, expectedSourceDigest,
  private, shared,
  changes: {added: integer, updated: integer, preserved: integer},
  asOf, balanceAsOfStart, balanceAsOfEnd,
  coverage: "partial_dated_records", warnings: [string], expiresIn: 1200
}
```

`changes` 是三类记录合计的数量，`preserved` 表示匹配后关键记录字段未变。当前没有缺源时逐分区保旧合并；缺源／缺记录直接拒绝整份候选。private 是服务端核验后的本人预览，shared 是即将共享的白名单汇总。预览不写基线、回执或实际账本。

### POST `/api/finance-baseline/imports/confirm`

请求 `{candidate,previewToken}`，必须提交与预览时语义一致的候选。令牌有效 20 分钟，绑定家庭、成员、候选摘要、目标 revision 和目标来源摘要。返回：

```text
{
  receiptId, status: "imported" | "unchanged", revision,
  sourceDigest, candidateDigest, acceptedAt, replayed: boolean
}
```

确认在 `BEGIN IMMEDIATE` 事务中重新校验目标 revision/sourceDigest、来源日期及记录映射，然后写基线、回执和审计。任何一步失败全部回滚。重复提交同一已成功确认的令牌返回原回执并置 `replayed=true`；该回执表达原操作结果，当前最新版本仍以 status.current 为准。

错误：400 候选／金额／run 格式不正确；401 未登录；403 TV／CSRF／其他成员家庭或候选与令牌不一致；409 目标变更、过期令牌、日期／覆盖倒退、旧记录缺映射或已有金额变为未知。409 应保留浏览器候选供修正或重新预览，不应盲目重试 confirm。

## 9. 幂等、缺源保旧与旧版迁移

- `candidateDigest` 根据排序规范化后的整个候选计算；`sourceDigest` 根据转换器版本和来源 manifest 计算。排序和请求 JSON 键顺序不影响候选摘要。
- `importedAt` 仅在服务端生成；同一来源候选重复准备、重新预览并确认，不增加基线 revision 或刷新业务日期。
- 已存在每条记录必须由相同 `id` 或明确 `legacyId` 消费一次。旧基线没有 ID 时，一次性迁移锚点是 `legacy-assets-<零起始索引>`／`legacy-liabilities-...`／`legacy-income-...`；它只指向被 CAS 锁定的旧快照，不能用作新的长期来源身份。
- 任一旧记录未匹配、同一旧记录被映射两次、已有金额变为 null、逐项日期／来源版本日期倒退时拒绝整个候选，旧数据保持原貌。删除／纠错确认和自动分区合并尚未实现。
- 已桥接过的来源文件集合不能减少；报告覆盖结束日期不能倒退，覆盖天数不能缩短。滚动报告窗口可以整体前移；它始终带自己的区间和质量状态，不代表余额同步变新。
- 来源不完整保持部分覆盖；更多报告质量缺口会在本人预览中保留，不提升完整度。旧资产日期不会因报告刷新自动变化。
- 服务器能核验候选结构与哈希格式，但不能远程证明私人源文件真实性。源文件一致性由本机 CLI 执行；本人确认仍承担来源映射与口径的核对，不能把“哈希合法”写成“机构已验证”。

真实只读审查的具体范围与阻断见第 2.1 节；本候选适配增量仅完成合成验证，没有生成真实候选。贷款缺独立余额核对日期、旧基线还存在日期语义差异和补充来源，所以必须先建立私人稳定映射并补齐依据，不能自动用当前来源覆盖旧版。

## 10. 注册、持久回执与其他模块

在已有 `register_finance_baseline(...)` 后调用：

```python
from finance_source_bridge import register_finance_source_bridge
register_finance_source_bridge(app, db, Problem, body, require_member, audit)
```

无需额外依赖或环境变量。扩展登记在 `app.extensions['finance_source_bridge']`，包含 `receiptColumns` 与纯校验函数 `normalizeCandidate`。已发布的完整基线模式使用每户一张 `finance_source_receipts` 表（此次候选不重建或修改该表）；独立消费观察另用 [两张新表](SPENDING-OBSERVATIONS.md#持久化与本人读取)，不能合并回执或复用基线 revision。完整基线回执列为：

```text
id TEXT PRIMARY KEY
owner TEXT NOT NULL REFERENCES users(id)
candidate_digest TEXT NOT NULL
source_digest TEXT NOT NULL
expected_revision INTEGER NOT NULL
expected_source_digest TEXT NULL
baseline_revision INTEGER NOT NULL
status TEXT NOT NULL
accepted_at TEXT NOT NULL
```

回执持久化到成功应用的事务中；不保存原令牌、签名、密码或源匹配值。本人数据导出可按 owner 读取这些列，不能跨成员导出。来源 manifest 保存在私有 `finance_baselines.private_data.sourceBridge` 内，共享序列化仍走原白名单。全库备份自然包含回执，恢复规则沿用 [OPERATIONS](OPERATIONS.md)。

`hub_transactions`、对账关系、`hub_investments`、手工月度财务和公共荷包不会被此模块写入或参与基线相加。未来无人值守接收、受限写入凭据、调度与真实账户自动验收均不在当前实现范围。

## 11. 验证与接手

[test_finance_source_bridge.py](../tests/test_finance_source_bridge.py) 使用虚构 CSV／JSON、临时 SQLite 与真实 Flask 守卫。可复用 `synthetic_candidate(as_of='2026-09-14', amount_cents=12000)` 给浏览器验收提供无私人信息的候选。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_finance_source_bridge.py tests/test_finance_baseline.py
```

覆盖五种本地适配器、冻结期间输入变化、run／哈希／字节数检查、缺日期／缺源／坏金额保旧、预览无写入、确认回执重放、并发 CAS、事务失败回滚、跨成员家庭和 TV 隔离、共享重算与金额边界，以及 CLI 输出隐私和防覆盖源文件。真实来源准确性、Windows 私人目录 ACL 与本人映射确认不能由合成测试代替；线上发布和真实来源接入应分别记录证据。

## 12. 独立消费观察模式

为已有财产基线单独更新已完成的消费报告，无需为本次刷新补齐资产／贷款／收入 CSV 映射；这不会解决第 2.1 节真实资产映射、贷款日期与覆盖阻断，也不重写任何原资产行。

同一准备器新增 `--mode spending_observation`，只读取三个固定报告产物与指定成功 run，在源码之外生成私人 JSON。界面从“我的资产与消费观察 → 更新财务来源”选择“仅更新消费观察”，查看生成时间、365 天区间、月份／币种差异和移出窗口项，明确确认后保存独立本人快照。

HTTP 复用既有 status／preview／confirm 三个方法与路径，以 `mode=spending_observation` 分派；它不是新建三个额外路由。status 回传本人观察及财产基线的两套版本，preview 绑定四个预期值与有效成员会话，confirm 提交同一 candidate 和签名。没有基线时 409，不能将本模式当作新家庭初始建账入口。

精确请求、响应、完整虚构候选、DDL、日期防退／窗口缺失、未知旧覆盖确认和历史回执恢复边界统一放在 [SPENDING-OBSERVATIONS](SPENDING-OBSERVATIONS.md)，不将两种模式的不同字段拼成一个请求。账单文件导入的 [resultMonths 与 availableMonths](FINANCE-IMPORT.md#导入确认回执与实际月份) 属于实际账本导航，与此处报告月份口径分开。

模式已随本版发布。功能验证使用临时合成数据；另已在本机只读转换现有报告，准备源码外消费观察候选，尚未上传或确认导入，没有新增邮箱刷新或自动调度。软件发布、本机转换和真实服务器接收是三个独立证据范围。
