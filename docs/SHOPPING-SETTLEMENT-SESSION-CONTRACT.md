# 采购实付：请求内会话边界

本修订已随 Expo 采购实付于 2026-09-18 08:03（北京时间）发布，正常 TLS 读回通过；实际身份与未验范围见[集中验收记录](EXPO-SHOPPING-SETTLEMENT-ACCEPTANCE.md#expo-shopping-settlement-release)。仅修复 [shopping_settlement.py](../shopping_settlement.py) 的三个现有操作：`GET /api/finance-hub/shopping-settlements/context`、`POST .../preview`、`POST .../confirm`。金额、分配、共享字段、数据库结构及请求／响应形状保持 [原结算协议](SHOPPING-SETTLEMENT.md)；没有增加回执查询接口。

## 身份与事务

- 使用全局请求守卫已经捕获的真实成员会话，随后每次核对实际 Cookie 解析出的会话 id、owner、credential hash、auth_version，以及原 actor 与家庭。不能在请求中途换成同一成员的另一个有效会话；普通 last_seen_at 更新不视为身份变化。
- context 与 preview 在开始业务快照前核验会话，释放 legacy Cookie 解析可能产生的隐式写事务，再开始一致读取。形成响应后先释放业务快照，再重新读取当前会话；撤销、到期或身份变化返回既有 `{error}`／401，不返回旧数据或预览令牌。
- 全局守卫已用独立事务提交成员初始化和 legacy 会话注册。本模块只回滚自己连接的解析写入，不回滚首次注册。真实首次 legacy context／preview、预览确认及回放均包含在专项中。
- confirm 取得 `BEGIN IMMEDIATE` 写锁后复核原会话；新写入在采购投影、关联、回执及审计完成后、提交前再次复核。失败时这些业务修改整体回滚。不能把正常并发会话活跃时间更新误判为新身份。
- 原回执回放在锁内按既有本人 nonce 查找，形成历史响应后释放事务，再核验原会话。不会把历史购物状态重新写回当前数据库。

预览令牌仍绑定具体会话，有效期仍为 600 秒，原过期检查仍先于历史回执查找；过期返回原 400，同成员新会话不能借旧 token 跨会话恢复。没有改变签名、nonce、CAS、额度或幂等规则。context 只是当前状态，不是操作回执；未知写入不能依据当前状态或没有变化就断言未提交。

## 真实复现与验证（以下为作者分支专项阶段记录）

全部使用真实 Flask 请求、Cookie、临时 SQLite 与合成付款／采购，专项禁止网络连接。事务钩子仅控制撤销、时钟到期、实际锁竞争或审计失败的时序，不替换认证结果或业务成功响应。测试见 [会话专项](../tests/test_shopping_settlement_sessions.py)。

| 轮次 | 实际结果 |
| --- | --- |
| 未修改业务源码的 baseline r1 | 10 个预期失败：同成员换 Cookie 的 context／preview／confirm／历史回放 4 项；业务快照中撤销的 context／preview 2 项；释放历史读取事务时撤销 1 项；审计后到期的 apply／update／revoke 3 项。原实现均错误返回 200，测试要求 401；没有夹具初始化错误。 |
| 修复后 fixed r1 | 一次实际执行 82/82：新会话专项 28＋原结算 44＋原旅行采购 10；零失败、错误、跳过，69.19 秒。325 个 Python 输入前后散列相同。 |

修复后覆盖原 10 个复现、全局守卫后撤销／auth_version 改变／到期、真实 writer 锁等待后的失效与正常活跃对照、legacy 首次注册与无读锁阻塞、审计后替换 Cookie、审计异常完整回滚，以及 confirm／回放原令牌过期顺序。旧模块覆盖金额与退款额度、本人／家庭／电视隔离、CSRF、版本冲突、确认回放、旅行关联保全及更新／两种解除模式。

私有原件均在本作者工作树 `test-results/`，不进入仓库，失败原件保留：

- `shopping-sessions-baseline-r1/results.xml` SHA `7fb18c046905d3ac55d02e197a8c40ebfcc19f22be584a57dcc5907c9c7f985a`；`record.json` SHA `4d933e94027109db6e92d832bec9ba0240d21e167e80ec00de80ea648ffa728e`。另保留与该轮记录散列精确相等的原 10 项测试源码 `executed-test.py`。
- `shopping-sessions-fixed-r1/results.xml` SHA `826611acc43abaf6b11ebc1efa5578794be4d41a11bc74089e79eb6ba52c77b8`；`record.json` SHA `fa6bed7d33b18cbf30f231e07ac7d256fd45b5b0ef759a78d5b0ac592848ef01`；stdout SHA `5d960b1410428d751673db6bc96df3fc1818324f2dc1098b8fa7b43e53d6defe`，stderr 为空。

本轮没有执行全仓测试、Expo 浏览器、Linux 发布验证或生产操作；这些结果不能由上述临时 HTTP 专项推断。正常数据库写锁仍按 SQLite 事务串行化；这里不承诺最后一次核验完成之后发生的撤销可以收回已经提交的写入或响应。
