# 本人手动资产账户与日期估值 API（候选）

本模块独立开发于 `944a712d69375c209ec7a63fe28b3a2287df8beb`，尚未接入生产。仅新增 [finance_accounts.py](../finance_accounts.py)、专项测试与本文；app、Docker、导出调用和正式迁移由独立分支接线。它记录本人提供的资产／负债，不推断机构类型、访问银行、换汇、执行交易或将记录与来源基线、持仓、消费及公共荷包相加。

## 注册与存储

`register_finance_accounts(app, db, Problem, body, require_member, audit, *, initialize=True)` 遵循现有依赖注入；要求 app 已配置真实 `member_sessions` 及 API 的成员／Origin／CSRF 守卫。复用 `finance_source_bridge.ImportSession` 的实际 captured-session 核验。`initialize=True` 在注册时调用 `init_schema(con)` 并提交；已经由发布迁移完成初始化的调用方可传 `False`。

`FINANCE_ACCOUNTS_SCHEMA_SQL` 是唯一显式 DDL：新增 `finance_accounts`、`finance_account_valuations`、`finance_account_operations` 三表。`init_schema(con)` 不自行提交、不调用应用工厂，仅逐条执行这份 DDL；调用方可以在事务中核验后提交或回滚。正式 55→58 迁移、原55表／注册库保全与恢复须另行验证。本次没有执行任何服务器迁移。

账户按户内 `owner` 关联 `users`；估值以 `(owner,account_id,as_of)` 唯一并通过复合外键指向同一 owner 的账户。操作键以 `(owner,request_id)` 唯一。禁止物理删除；归档与恢复都是可逆 CAS 更新。每人最多300账户（含归档），每账户3660日期估值，每人20000回执、回执JSON合计32 MiB。容量限制不阻止已有回执读取／相同请求重放，同日估值纠正不新增历史日期数。

## 公共类型与边界

- `Account = {id,owner,name,institution,kind,currency,note,archived,revision,createdAt,updatedAt,visibility:'private'}`。id为24位小写十六进制，revision为正安全整数；时间为带 UTC 偏移的 ISO 时间。name为非纯空白字符串，最多120字；institution可空、最多120字；note可空、最多1000字，仅note允许换行及Tab。文字不自动trim，拒绝控制字符和孤立代理字符。
- `kind` 只能为 `asset|liability`，currency只能为3位大写字母；两者创建后不能修改。机构为本人自由文本，不代表已验证机构或接入能力。
- `Valuation = {asOf,amountCents,source:'manual',updatedAt}`。asOf为严格有效的 `YYYY-MM-DD`；金额为 `null` 或 `0..100000000000000` 的整数分，包含上限。null表示未知，0表示本人确认零值；负债同样填非负金额，由kind决定汇总减项。输入不接受浮点、字符串金额、布尔值、负数或静默舍入；界面应将最多两位小数的原币文本精确转为整数分。
- `Receipt = {requestId,operation:'create'|'update'|'valuation',accountId,completedAt,result:{account:Account,valuation:Valuation|null},replayed:boolean}`。requestId固定32位小写十六进制。PATCH回执valuation为null；POST和PUT回执含本次日期估值。
- 请求拒绝重复查询参数、额外字段及JSON重复字段；写请求上限16 KiB。客户端不传owner／visibility／更新时间。

## 接口

全部路径以 `/api/finance-accounts` 开头，均仅当前本人；匿名401、电视403、伙伴／其他家庭账户404。列表及回执不可按owner查询。

| 方法与路径 | 请求与响应 |
|---|---|
| GET 根路径 | 必填 `asOf=YYYY-MM-DD`；可选 `status=active|archived|all`，默认active。返回 `{owner,asOf,status,scope:'manual_accounts_only',accounts:[{...Account,valuation:Valuation|null}],totals:[CurrencyTotal]}`。账户按createdAt、id升序，一次返回本人的完整所选集合（最多300）。 |
| POST 根路径 | 完整 `{requestId,revision:0,name,institution,kind,currency,note,valuation:{asOf,amountCents}}`，账户与首条估值原子创建，201 Receipt。 |
| PATCH `/<id>` | `{requestId,revision,changes:{name?,institution?,note?,archived?}}`，非空patch、archived严格布尔；可只归档／恢复，200 Receipt。 |
| PUT `/<id>/valuations/<date>` | `{requestId,revision,amountCents}`，新增或纠正该日记录，每次明确写入递增账户revision，200 Receipt。归档账户必须先恢复。 |
| GET `/<id>/valuations` | 可选page默认1、pageSize默认50／最大100；返回 `{account:Account,valuations:Valuation[],page,pageSize,total}`，日期降序。归档账户仍可读历史；超出尾页返回空数组。 |
| GET `/operations/<requestId>` | 不接受查询参数；200 `{requestId,found,receipt}`。有回执时receipt含replayed:true；没有时found:false、receipt:null，仍不能证明请求未在途。 |

列表选择每个账户不晚于asOf的最近一条估值；没有这样的记录时valuation=null。最近记录的amountCents=null不能退回更早的已知金额。归档筛选和名称等元数据均为账户当前状态，不重建过去某日的归档状态或名称；查历史时可明确选择all。

`CurrencyTotal = {currency,assetCount,liabilityCount,knownCount,unknownCount,missingCount,olderCount,knownAssetCents,knownLiabilityCents,knownNetCents}`。最后三个字段为十进制整数分**字符串**，net可为负；服务端精确整数求和，前端使用BigInt。unknownCount指有估值记录但金额未知，missingCount指所选日期之前没有记录；olderCount为实际估值日期早于所选日期的账户数，可能同时属于unknownCount。三类known／unknown／missing计数之和等于账户数。各币种独立，已知部分净额为已知资产减已知负债，不提供完整家庭净资产。knownCount为0时不能将字符串小计0展示为已知完整余额，也不能把历史变化称为投资收益。

## 保存、会话与未知结果

每个写请求先核真实成员，再在BEGIN IMMEDIATE取得锁后重新核对最初captured的session id、credential、auth_version、owner和家庭。完成业务、回执、audit后提交前再次核验；任何失败完整回滚。成功提交／历史重放后另做fresh检查；这只能拒绝尚未发送的响应，不能撤销已经提交或已发送的数据。读取在同一SQLite快照内组装，释放快照后再核真实会话。

原始JSON内容（包括文字空白）、操作、账户及日期共同绑定payload hash。先授权再查本人精确历史回执；原key原内容重放优先于当前账户版本、归档状态和容量检查，不恢复旧字段。更换内容／目标会409 `operation_request_conflict`。当前有效的本人新会话可读历史，也可在明确确认后使用原key原body重试；客户端必须使用当前CSRF并重新核对完整身份，不能因换会话自动重发。历史回执只说明当时结果，随后GET当前账户及历史，不能将回执直接安装为当前状态。

业务错误含 `{error,code}`：400 `invalid_request`；404 `account_not_found`；409 `revision_conflict`、`operation_request_conflict`、`account_archived`、`capacity_exceeded`。权限错误沿应用401／403；容量413沿应用请求大小处理。超时、断网、响应丢失、401或回执暂未找到均不能推断未写；保留原操作编号及内容，在当前本人有效会话中核对。CAS拒绝需保留草稿并读最新版本，由本人重新确认，不能换版本自动覆盖。

## 本人导出接缝

`export_owned_accounts(con, owner)` 是不写入、不提交的纯读函数，调用方负责授权与一致快照／fresh检查。返回 `{accounts,valuations,operations}`；accounts为上述Account白名单，包含归档；valuations仅 `{accountId,asOf,amountCents,source,updatedAt}`；operations仅 `{operation,accountId,completedAt}`。估值和回执都通过owner＋accountId关联本人账户，不导出payload_hash、requestId、原请求／result或认证上下文。不能加入shared导出；不影响已有已批准基线汇总。本模块尚未修改data_portability接线。

## 验证状态

专项 [test_finance_accounts.py](../tests/test_finance_accounts.py) 使用真实应用工厂、登录／配对／家庭HTTP接口与独立临时SQLite；仅在测试注册本模块，不伪造actor或认证结果。覆盖按日原币记录、未知／零、归档恢复、精确超JS安全范围汇总、CAS和幂等、权限隔离、读快照撤权、写锁竞争、审计／到期回滚、本人导出、新应用实例读回，以及提交成功但响应前撤权后的历史恢复。

实际命令为主仓虚拟环境 Python `-B -X utf8 -m pytest tests/test_finance_accounts.py -q --junitxml=test-results/finance-accounts-api-r4/results.xml`：**81 passed，0 failed/error/skip，55.40秒，exit 0**。XML SHA-256 `372c62cc154bfa27a884356efd6c7562c4d1f5e68295a04e8274f854ba0e8a48`；运行前后两份Python源hash相同，产品源码自r1未变。r1保留77通过／1失败原件（测试误将6次合法audit的sqlite_sequence递增视为旧表变化）；r2保留80通过／1失败原件（新增提交后撤权探针未先建立g.db）。两处只修测试，未跳过或削弱权限与事务断言。r3的81通过原件也保留；r4仅为注册fixture兼容后续正式app接线，防止组合时重复注册，不增加通过数。浏览器、正式迁移、生产及真实本人数据均未验。
