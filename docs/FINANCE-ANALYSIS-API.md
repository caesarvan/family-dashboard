# 本人账户分析 API

本批合同，尚未发布。分析只计本人明确选中的 `finance_accounts`；来源报告、当前持仓、共同荷包和付款账本不相加，也不自动生成账户或现金流。账户/估值仍使用原 `/api/finance-accounts` 接口，保留原币、原始日期、未知值和原回执合同。

## 身份与金额

全部接口仅当前家庭的当前成员本人可用，伴侣、电视与跨家庭不能读取。读写在真实会话快照中核对，响应前再次检查身份；写入要求 CSRF。分析结果不进入共享状态、电视或共享导出。

金额沿用两位小数整数分；单条非负整数最大 `100000000000000`，汇总和差值为有符号十进制字符串。未知为 `null`，不等同零。分类只由本人设置，未设置均为 `unknown`。当前账户名称、机构、归档和分类不是历史元数据；整个趋势使用同一选中集合，归档不代表历史余额归零。

## 读取分析

`GET /api/finance-analysis/report?start=2026-01-01&end=2026-09-18&baseCurrency=CNY&step=month&accountIds=all`

日期为闭区间，1999-01-04 起，最多 366 天，`start < end`。`step=day|month`，按日或月末加首尾取样；`accountIds=all` 包含本人归档账户，也可为去重后的 24 位 ID 逗号列表，最多 300 个。选择不属于本人的 ID 整体拒绝，不静默遗漏。读取不访问互联网。

返回类型（所有字段均出现）：

```ts
type Profile = {
  accountId: string; revision: number; updatedAt: string | null;
  assetClass: 'unknown'|'cash'|'fixed_income'|'equity'|'fund'|'property'|'other';
  liquidity: 'unknown'|'immediate'|'within_month'|'over_month'|'restricted';
};
type Coverage = {
  selectedCount: number; knownValuationCount: number; convertedCount: number;
  missingValuationCount: number; unknownValuationCount: number;
  olderValuationCount: number; missingFxCount: number;
};
type Summary = {
  knownAssetCents: string; knownLiabilityCents: string; knownNetCents: string;
  complete: boolean; coverage: Coverage;
};
type Point = {
  date: string;
  valuation: {asOf:string; amountCents:number|null; source:'manual'; updatedAt:string}|null;
  convertedCents: string|null;
  fx: null|{sourceCurrency:string; targetCurrency:string; rateDate:string;
    ageDays:number; sourcePerEur:string; targetPerEur:string;
    sourceVersion:number; targetVersion:number; sourceUrl:string|null;
    bodySha256:string|null; fetchedAt:string|null; lastCheckedAt:string|null};
};
type Change = {
  originalChangeCents: string|null; recordedNetFlowCents: string;
  valuationResidualCents: string|null; convertedChangeCents: string|null;
  convertedNetFlowCents: string|null; convertedValuationResidualCents: string|null;
  fxEffectCents: string|null; roundingCents: string|null;
  status: 'unreviewed'|'stale'|'missing_valuations'|'missing_fx'|'complete';
};
type Review = {
  revision:number; contextDigest:string; status:'unreviewed'|'current'|'stale';
  confirmedAt:string|null; cashflowCount:number; recordedNetFlowCents:string;
  canConfirm:boolean;
};
type Report = {
  owner:string; scope:'private_accounts_only'; start:string; end:string;
  baseCurrency:string; step:'day'|'month'; accountIds:string[];
  accounts:Array<{account:FinanceAccount; profile:Profile; opening:Point; closing:Point;
    review:Review; change:Change}>;
  summary:Summary;
  series:Array<{date:string; summary:Summary}>;
  allocation:Array<{key:Profile['assetClass']; knownCents:string; count:number}>;
  liquidity:Array<{key:Profile['liquidity']; knownCents:string; count:number}>;
  change:{convertedChangeCents:string|null; convertedNetFlowCents:string|null;
    convertedValuationResidualCents:string|null; fxEffectCents:string|null;
    roundingCents:string|null; complete:boolean; reviewedCount:number};
};
```

`FinanceAccount` 是既有原账户 DTO，不添加分析字段。首尾及取样日取不晚于该日的最新估值；最新记录明确未知时不回退旧已知值。折算使用查看日的参考汇率，界面并列显示原估值日期与汇率日期；较早估值是沿用，不是当天真实余额。`complete` 仅表示所选集合在该日恰有已知估值与可用汇率，不能宣称全部家庭财产完整。资产配置和流动性仅汇总可折算的资产，负债单列；未知分类保留桶，百分比只能以已知资产部分为分母，净资产负值不作配置分母。

## 公共参考汇率

`POST /api/finance-analysis/rates/refresh`，JSON `{requestId,start,end}`。只向固定 ECB 官方 HTTPS 地址读取公开参考汇率，服务器将起点向前扩七日；不发送本人账户、金额或身份。读网络在数据库事务之外，实际缓存与回执在复核会话后的同一事务写入；失败保留已有缓存。此前成功的原请求先恢复回执，不因网络故障再次出网。

汇率按同一原始日期 `targetPerEur / sourcePerEur` 交叉折算，不混用日期。至多沿用七天，缺失、未覆盖币种或更旧数据不伪造折算。来源日期、来源 URL、下载时间、原件 SHA、版本均保留；修正报价新增版本，旧版本不覆盖。原币等于报告币种采用恒等换算，不依赖网络。它是估值参考，不是交易成交汇率。

成功回执 `result={inserted:number,updated:number,rateCount:number,retrievedAt:string}`。具体公共缓存及报价实现由 `finance_fx.py` 提供。

## 分类、现金流与区间核对

`PUT /api/finance-analysis/accounts/<accountId>/profile`

```json
{"requestId":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","revision":0,"assetClass":"cash","liquidity":"immediate"}
```

没有 profile 时 revision 为 0，保存后为 1。此分类仅用于本人当前分析，不改原账户 revision 或共享范围。

`GET /api/finance-analysis/accounts/<accountId>/cashflows?start=2026-01-01&end=2026-09-18&page=1&pageSize=50`

返回 `{owner,accountId,start,end,items:Cashflow[],page,pageSize,total}`，分页最多 100、每人总事件最多 10000。只列 `(start,end]`，因为起点是日终估值。`Cashflow={id,accountId,date,direction:'in'|'out',amountCents:number,note:string,revision:number,createdAt,updatedAt}`。

`POST /api/finance-analysis/accounts/<accountId>/cashflows`：

```json
{"requestId":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","revision":0,"date":"2026-09-01","direction":"in","amountCents":100000,"note":"本人核对的外部资金转入"}
```

`PATCH .../cashflows/<id>` 使用同一完整表单、当前事件 revision；`DELETE .../cashflows/<id>` 仅 `{requestId,revision}`。现金流原币固定为所属账户币种，不接受转换金额。`in/out` 描述账户余额的外部增加/减少：资产账户为转入/转出，负债为借入/偿付。利息、分红、费用和证券交易导致的余额变动不能凭分类猜成资金进出；已登记的外部资金进出不再写付款账本。账户间转移须本人分别核对两端；不自动配对或从单边事件断言家庭外部收入。已归档账户可读历史，须先恢复账户再新增或更改事件。

`PUT /api/finance-analysis/accounts/<id>/reviews/<start>/<end>`：

```json
{"requestId":"cccccccccccccccccccccccccccccccc","revision":0,"contextDigest":"64位report给出的当前摘要","confirmed":true}
```

本人明确确认两端估值和期间外部资金进出已完整核对。必须恰有起止日的已知估值；有 0 条流水也必须明确确认，不从空集合推定零。保存时重算摘要比较；两端估值或区间内现金流改变即变为 stale，不能沿用已确认状态。核对记录只适用于精确账户和区间，不自动延伸。成功返回当前 `Review`。

原币差值 `V1−V0` 始终仅称余额变化。核对有效后残差 `R=V1−V0−ΣF` 为“扣除资金进出后的估值变动”，不能直接称交易收益、年化收益或投资回报。FX 分解采用期末汇率计残差：资金进出为 `Σ(Fi×ri)`，估值残差为 `R×r1`，汇率影响为 `V0×(r1−r0)+Σ[Fi×(r1−ri)]`，三者精确构成报告币种余额变化。各组件分别四舍五入到分，`roundingCents` 显式保留舍入差；任一所需汇率缺失则该归因的折算组件为空。负债在集合净额中按负号计，单账户仍保留正余额口径。

## 幂等、错误和保存结果不明

写入统一返回 HTTP 200（首次或重放），包括现金流创建和汇率刷新：

```ts
type Receipt = {requestId:string; operation:'profile'|'cashflow_create'|'cashflow_update'|
  'cashflow_delete'|'review'|'rates_refresh'; accountId:string|null;
  completedAt:string; result:Profile|Cashflow|{deleted:true,id:string}|Review|FxRefreshResult;
  replayed:boolean};
```

`GET /api/finance-analysis/operations/<requestId>` 返回 `{requestId,found,receipt:Receipt|null}`。requestId 为 32 位小写十六进制；同 key 不同原始 payload/路径/操作返回 409。先恢复成功的原操作再判断当前账户/事件 revision；回执是历史结果，不能代替重新读取当前分析。回执未找到不证明请求未执行，保留原编号查询或重试，不自动换编号。容量为每人 20000 条、32 MiB。

拒绝未知/重复 JSON 和 query 字段。错误统一 `{error,code}`；400 参数，401/403 身份权限，404 本人不可访问的账户/事件，409 revision/context/capacity/archived，413 过大，502/503 公共来源不可用。错误不含原财务内容、响应原文或网络凭据。重放和错误响应同样复核当前会话。

## 新增持久化与导出

`FINANCE_ANALYSIS_SCHEMA_SQL` 精确新增四表，原账户三表不改：

- `finance_account_profiles(owner,account_id,asset_class,liquidity,revision,updated_at)`，owner/account FK，主键 owner/account。
- `finance_account_cashflows(id,owner,account_id,as_of,direction,amount_cents,note,revision,created_at,updated_at)`，owner/account FK；现金流修改/删除使关联区间摘要变化。
- `finance_account_reviews(owner,account_id,start_date,end_date,context_digest,revision,confirmed_at)`，主键 owner/account/start/end。
- `finance_analysis_operations(owner,request_id,payload_hash,operation,account_id,result,completed_at)`，主键 owner/request；汇率刷新 account_id 为空。

`init_schema(con)` 不提交事务。`register_finance_analysis(app,db,Problem,body,require_member,audit,*,initialize=True)` 只注册本模块并在初始化时建立四表及公共 FX 表。`export_owned_analysis(con,owner)` 返回本人 `{profiles,cashflows,reviews,operations}`，调用方负责一致快照；操作只导出业务摘要，不导出 payload hash 或会话。公共 FX 由 `finance_fx.py` 另定义一表；本批总计五张新表，旧 61 张家庭表与 9 张平台表内容保全。
