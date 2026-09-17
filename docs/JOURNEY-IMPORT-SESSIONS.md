# 旅行导入的请求会话边界

本分支是未部署候选。仅修复 `journey_workflows.py` 中既有旅行预览、确认和回执查询的请求会话校验；没有新路由、表、DTO、依赖或云写入。实现依赖现有真实成员认证，不接受调用方自报身份。

## 保持的接口与业务语义

- `POST /api/journeys/preview` 仍接收原有计划，保持 v1/v2 归一化、源版本检查和服务器时间处理。
- `POST /api/journeys/apply` 仍接收原始 `previewToken` 与 `idempotencyKey`。请求开始时合法的同本人新会话可以继续普通导入；请求进行中不得换成另一个会话。已有改期令牌的会话绑定另行保留。
- 普通预览仍在 1800 秒后返回 409，过期检查仍早于普通 apply 的历史回放。改期令牌原有的已保存回执恢复规则不变。
- `GET /api/journeys/operations/<key>` 仍只查当前户、当前成员的原键。200 是历史回执，不重新创建旅行；404 `operation_not_found` 不能证明原请求没有在途。
- 同一原键或同一预览操作的回放仍只有一条持久回执；不同预览占用相同键仍冲突。权限、实体 CAS、移出不删除、金额、成员、云日历锁顺序不变。

## 最小修复

1. 固定请求进入业务处理时的真实 `member_session.id`、成员、认证版本和家庭；每次复核同时检查当前 cookie 实际解析结果。原会话仍有效时，正常并发活动或同成员的另一合法登录不会使原请求自动失效，只有原请求会话不再匹配或已撤销/过期才拒绝。
2. 预览及复用该 helper 的成员详情、模板、回执查询先认证，再释放 legacy cookie 解析造成的隐式更新，然后建立独立业务只读快照。读取完成先释放快照，再复核真实会话；成功和“未找到回执”路径都遵守此边界。
3. apply 在 `BEGIN IMMEDIATE` 取得写锁后复核，在业务写入、审计与回执插入后、commit 前再次复核。失败回滚本次业务和审计。普通导入与改期共用这一提交边界。
4. 两种持久回放在 rollback 释放锁/快照后再查会话，且释放 legacy 复核可能开启的隐式更新事务。

`MemberSessions.actor()` 的首次 legacy 注册与活动记录使用独立连接并已提交；数据库及旅行初始化也各自提交。这里释放的是业务连接中重复解析引起的事务，不取消首次会话注册。电视详情继续走既有只读路径，模板/预览/apply/成员回执保持成员权限。

校验只能约束服务器可观察的处理边界；不声称能撤回已发出的字节，也不声称在数据库提交与客户端收到响应之间提供原子撤权。未知响应仍由客户端保留原键并查询/明确重试。

## 实际验证

专项使用真实 Flask 登录、临时 SQLite、实际签名 cookie 和独立 WAL 连接。受控变化发生在认证后、域读取期间、等待写锁时、审计后或回放释放事务后；没有伪造认证成功或业务成功响应。

修复前 `test-results/journey-import-baseline-r1` 保留 12 项原件：11 失败、1 通过，JUnit SHA `97796ad1bae4ed6cbe9a4e3f8bf7afc8b6023a4b46744b234589569bb7011c6c`。已观察到同本人 cookie 替换未拒、审计后过期仍提交、回放后撤销仍返回，以及 legacy 域读取持写锁。

修复后一次执行 40 个新专项和 152 个已有回归：`test_journey_workflows.py` 30、`test_journey_details.py` 26、`test_journey_edit_snapshot.py` 52、`test_journey_transaction_session.py` 6、`test_journey_reschedule.py` 38。首轮实际 190 通过、2 失败；两项新增过期测试错误地回拨全部签名时钟，导致登录 cookie 被视为来自未来，并非业务拒绝错误。只将测试时钟限定到 journey-preview 的签名 salt 后，定向两项实际通过、其余 38 项未重跑（deselected）。不把分轮结果写成单次 192 全通过。

| 原件目录（本工作树 `test-results/` 下） | 实际结果 | JUnit SHA-256 |
| --- | --- | --- |
| `journey-import-fixed-r1` | 190 通过，2 个测试构造失败，133.33 秒 | `1437f6d3a07756f4436bf4d5a9e31165b4529a8bfefddc4867e4d35ed0aa08e8` |
| `journey-import-expiry-r2` | 修正测试后 2 通过，38 deselected，1.90 秒 | `80492535c6a39c55125a1be8a20b9baf93f0cf47db4907ed27a65b0c0cca91e2` |

各轮保留 stdout、空 stderr、JUnit 和 `evidence.json` 的前后输入散列。修复后两轮业务模块 SHA 相同：`ed2e81503361dd4ab25a13956c7c307e872cf5b2c820131e57400ca178475295`。原有回归文件未修改；后续只改新测试的时钟范围与未用导入。

已验证普通创建/更新/双路径回放、复杂分段与 DST、源快照、改期、首次 legacy 访问与注册持久性、写锁等待后撤销及正常活动、同本人新请求恢复/伙伴隔离、过期后历史查询。未运行全仓、浏览器或真实云验证，未访问生产。

参见 [旅行执行](JOURNEY-EXECUTION.md)、[复杂行程模型](EXPO-JOURNEY-SEGMENTS-MODEL.md)、[改期](JOURNEY-RESCHEDULE.md)。
