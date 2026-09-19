# 助理支出与预算只读查询（候选）

本候选未上线。新增 `POST /api/assistant/finance-query`，只读取当前成员获准查看的账本、预算或已确认手工公共快照；不创建助理计划，不写账本、关联、预算或公共余额，不调用金融机构。Docker、发布白名单和 Expo 接线由集成人分别组合验证。

```python
from assistant_finance_query import register_assistant_finance_query
register_assistant_finance_query(app, db, Problem, body, require_member, limited)
```

实际 `app.py` 在财务中枢与助理初始化之后正常注册。无 DDL、初始化 SQL、依赖或迁移。复用 `finance_source_bridge.ImportSession`、`finance_hub.reconciliation_rows`／`transaction_totals` 和现有 `home_assistant._model_json` transport。

## 请求与身份

请求为 `{prompt: string, useModel?: boolean}`，不接受其他键或 URL 参数；prompt 去首尾空白后 1–2000 字符，拒绝无效控制字符，HTTP 正文最多 16000 字节。useModel 默认 false，必须是布尔值。需要有效成员会话、同源 JSON 和 CSRF；匿名 401、电视／CSRF／跨源 403，沿用现有错误格式 `{error, code?}`。

当前 owner 只来自真实会话；客户端与模型均不能指定成员。`ImportSession` 在请求开始、模型调用前后及读取事务结束后重新核对成员、家庭、会话及撤权。没有跨网络保留 SQLite 读取锁。模型调用前不读取账本；响应使用网络结束后新的授权事务内实际值。公共快照同样在此事务中读取。限流只使用既有 attempts 记账：本地 60 次／600 秒；实际模型解析共用 assistant_plan 的 30 次／3600 秒。不写业务表、审计业务或操作回执。

## 本地解释与可选模型

支持本人本月／上月／单个完整 `YYYY-MM` 的消费、退款后净支出、预算余额或两者概览；省略范围和月份时，响应 message 明示本人及北京时间当前月份。上月正确跨年。明确共享消费使用共享总计；公共荷包只提供当前手工快照，带月份时澄清，不伪装历史月账。

以下输入在模型之前停止，不查询财务表：搜索／查找指令，含修改或执行动作，否定或排除条件，多日期／多月，无年份月份，多人或多个范围，引号／代码中的指令，伴侣等他人私账。未识别分类或不明对象不默认为本人查询。支持固定分类 `餐饮/交通/购物/住房/医疗/教育/娱乐/旅行/日用/其他/未分类`；“全部”表现为 category=null。各币种独立计算，不换汇；不指定币种时分别返回。单次显式要求多个币种则澄清为不筛选或选择一个币种。

`useModel:true` 表示**允许**模型：本地已无歧义时仍返回 mode=local，不调用模型。仅硬约束通过且有财务语境与本人／共享／公共范围依据、但口语表达尚未识别时，才调用配置好的现有供应商。例如“帮我瞧瞧上个月餐饮方面用了多少钱”可走受限模型解析；本地单独不能确认时保持 clarify。未配置、超时或格式错误返回安全错误，用户保留原输入并可切回本地明确表达；没有供应商回落或隐式网络重试。

模型只收到本次用户问题、捕获的北京时间日期／时区、固定可用枚举，以及从本次文字提取的 `constraints` 证据允许值；不附加账本、汇总、余额、真实分类目录、账户、成员目录或凭据。用户自己写在问题中的文字属于所选发送内容。`constraints` 只含 scope/month/currency/category 的原文 token 数组，缺省为 `[null]`；evidence 对应键须逐字复制其中一个值，不能扩展为长句。它不包含计算好的 query 或指标答案，模型仍须理解整段口语、判断只读性和未理解条件。上述口语的约束为 `{"scope":["我"],"month":["上个月"],"currency":[null],"category":["餐饮"]}`。

首次实际合成模型尝试正确解析 query，但把 scope 证据返回为“帮我瞧瞧上个月”，因不在允许 token 中被拒绝。原失败原件保留；窄修仅明确发送上述 token 约束，不放宽证据校验或权限。模拟回归同时保留该长句失败和合法“我”成功，不能把模拟成功替代随后实际模型验收。模型格式如下，供真实 provider 验证；不是客户端可提交字段：

```json
{
  "status": "ready",
  "query": {"scope":"personal","month":"2026-08","metric":"spending","currency":null,"category":"餐饮"},
  "evidence": {"scope":"我","month":"上个月","metric":"用了多少钱","currency":null,"category":"餐饮"}
}
```

上例系统日期在 2026-09。无法确定时模型返回 `{status:"clarify"|"unsupported",query:null,evidence:null}`。ready 必须同时满足严格键集／类型、日期／范围／币种／分类约束及原文证据；指标证据必须来自实际问题中的消费、用钱、退款、预算或概览表达。模型不能更换范围、月份或增加对象，也不能绕过任何本地硬约束；模型文字不直接作为用户答案。实际调用才标 mode=model。

## 响应 DTO v1

“v1”是本合同版本，响应没有额外 version 字段。HTTP 200 均为 `Cache-Control: no-store`。

```typescript
type FinanceQuery = {
  status: 'ready' | 'clarify' | 'unsupported';
  mode: 'local' | 'model'; message: string;
  query: null | {
    scope: 'personal' | 'shared' | 'public'; month: string | null;
    metric: 'spending' | 'budget' | 'summary'; currency: string | null; category: string | null;
  };
  totals: {currency: string; expenseCents: number; refundCents: number; netSpendCents: number; count: number}[];
  budgets: {currency: string; category: string; amountCents: number; spentCents: number; remainingCents: number}[];
  snapshot: null | {
    walletCents: number | null; livingSpentCents: number | null;
    livingBudgetCents: number | null; savingsCents: number | null; confirmedAt: string | null;
  };
  coverage: {
    status: 'recorded' | 'partial' | 'no_records' | 'manual_snapshot'; note: string;
    recordCount: number; unknownCount: number; orderCount: number; duplicateCount: number;
  };
  navigation: null | {screen: 'finance'; tab: 'ledger' | 'budgets' | 'shared'; month: string | null};
};
```

- clarify／unsupported 永远 query、snapshot、navigation=null，totals／budgets=[]；coverage 为空、说明尚未查询，没有财务内容。
- personal：完整本人账本先处理关联，再按月份／币种筛选，不使用 overview 的 500 条展示切片。订单和转账不计消费，确认重复排除；退款按退款发生月计入，分类金额使用完整关联分摊，包括跨月付款与部分分摊后的剩余退款分类。全部预算与分类预算逐项展示，不相加。spending 不返回预算；budget／summary 返回适用预算。
- shared：query.metric 固定 spending，category=null，budgets=[]，snapshot=null；只投影现有共享接口允许的 currency、expenseCents、refundCents、netSpendCents、count。coverage 仅反映可见共享消费，不返回私人分类、预算或私人／排除记录数量。
- public：query.metric 固定 summary，month/currency/category=null。snapshot 仅有已确认手工人民币当前值；savingsCents 直接映射 longterm，名称为“共同长期储蓄”，不加 travelSaved。confirmedAt 缺失时所有金额及 confirmedAt=null，初始默认金额不能冒充已确认值。金额字段缺失或无有效整数值亦为 null。
- 无账本记录使用 no_records 与空 totals；只有订单／未知方向使用 partial 和独立计数；真实零值是有记录的零，不能与未知或无记录混淆。没有预算时 budgets=[]，不制造零额度；即使已有预算，余额也只是减去已记录净支出，不能证明实际可用余额。
- 金额均为原币精确整数分。汇总或预算超出 JavaScript 安全整数范围时返回无财务内容的 unsupported，不四舍五入或转换为浮点近似。
- navigation：personal spending／summary→ledger，budget→budgets；shared／public→shared，public month=null。这只是财务页面入口，不是执行凭据。返回时可用 query 生成明确本地文本、useModel:false 重新查询，并校验新 query 一致；身份变化必须丢弃旧结果。

可靠本地刷新文本：`查询本人 2026-08 CNY 餐饮 支出`／`预算`／`支出与预算`，不筛选时省略币种或分类；共享为 `查询 2026-08 CNY 共享消费`；公共为 `查询公共荷包`。

## 验证范围

专项 [test_assistant_finance_query.py](../tests/test_assistant_finance_query.py) 使用真实 create_app 注册、真实登录／CSRF、临时 SQLite 和合成数据，仅 provider I/O 模拟。覆盖精确支出／退款／确认重复／订单／转账数学、完整大账本、多币种、跨月分类分摊、无记录与未知、共享白名单、公共未确认值、同 ID 跨家庭、电视／成员／撤权、迟到模型、模型最小载荷及实际口语解析增益。另有原导入与预算路由写入合成 fixture 后只读核对，业务表前后保持。

开发测试仅证明合成隔离场景，不是实际模型、私人财务、本人线上界面或生产验收。精确提交、JUnit 与运行结果由交付记录绑定；初轮与后续修订证据分别保留，不相加为独立测试总数。
