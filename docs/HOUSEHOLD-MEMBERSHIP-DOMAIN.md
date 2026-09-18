# 户内成员关系领域层

本模块实现 [成员关系设计](HOUSEHOLD-MEMBERSHIP-DESIGN.md) 的户内 SQLite 部分；尚未接入运行应用、迁移或发布。实现位于 [household_memberships.py](../household_memberships.py)，专项位于 [test_household_memberships.py](../tests/test_household_memberships.py)。个人账户、跨库协调、HTTP 会话及 worker 接线由各自模块负责，本提交不将领域测试描述为完整入口验收。

## 事务与信任边界

调用方先按 **platform → household** 顺序取得写锁，再传入已有事务的户内 `con`。领域写函数和 `schema_initialize` 要求 `con.in_transaction`，只开 SAVEPOINT；成功不 commit，异常回滚本次领域写，保留调用方此前同事务工作。调用方不得传入平台库或在户内回调中反取平台锁。读取放在调用方一致快照内，返回前释放快照并 fresh 核对原捕获身份。

领域函数验证当前户内 active、角色、关系及版本，不能独立证明 HTTP Cookie、CSRF、个人账号登录或密码复验时效。调用方从已核会话取 household/member/account，不采纳客户端 owner/accountId；写锁取得后及提交前核对同一凭据、代次与权限。本人退出会有意撤销自身成员会话，调用方应区分本次已知变更与并发撤权。`bind_account` 另在真实 `users.password` 上核对原家庭密码；个人侧五分钟密码证明由协调层验证。

`request_id` 是 32 位小写 hex，`intent_digest` 是调用方对完整规范意图计算的 64 位小写 hex keyed HMAC，包含操作种类、当前家庭及所有有效参数，秘密只参与 HMAC。领域不保存原请求、密码、原邀请令牌或 Cookie。个人操作以 `account:<id>`，管理员操作以 `member:<localId>` 为持久幂等主体；同主体同 ID 不同摘要或操作种类返回 409。

## 表与初始化

`TABLES`、`SCHEMA_STATEMENTS`、`HOUSEHOLD_MEMBERSHIPS_SCHEMA_SQL` 明确声明三张新表，供独立迁移器核对；不修改任何旧表 DDL。

| 表 | 关系与保留规则 |
|---|---|
| `household_memberships` | 随机稳定 ID；唯一 member_id 外键指 users；可空且非空唯一 account_id；active/left/removed、revision 与时间 |
| `member_invitations` | 随机 ID、SHA-256 token_hash、创建成员与当时 auth_version；pending/used/revoked、revision、时间及使用账户内部记录 |
| `membership_operations` | `(subject, request_id)` 主键；kind、intent_digest、有限 result_json、关联 member_id 和时间 |

`schema_initialize(con, *, now=None)` 仅在三表全部不存在时创建并给每个旧 users 生成 active、未绑定、revision=1 的稳定关系；原 ID、username、密码、实际家庭角色和全部旧表行保持。重启时不重置任何关系；部分表存在或 users 缺关系均 503，不自动补齐。独立迁移/启动层须保证使用完整、经过校验的库，不能把三表被外部删除误当作新库。领域不持久化另一套 schema 标记，也不替代完整迁移指纹校验。

## 固定 Python 接口

异常为 `MembershipError(message, status, code)`，三个属性分别对应有限提示、HTTP 状态及机器码。除明确列出的可选参数，以下参数必填；版本必须为非 bool 的正安全整数，最大 `9007199254740991`。

```python
schema_initialize(con, *, now=None)
active_member(con, member_id)
active_members(con)
membership_record(con, *, member_id=None, account_id=None, membership_id=None)
snapshot(con, household_id, member_id)
list_memberships(con, household_id, actor_member_id, *, status='active')
list_invitations(con, household_id, actor_member_id, *, now=None)
inspect_invitation(con, token, *, now=None)
validate_invitation(con, *, invitation_id, expected_revision, now=None)
operation(con, *, subject, request_id, intent_digest=None)
member_operation(con, *, member_id, request_id)

bind_account(con, *, household_id, member_id, account_id, member_password,
             expected_auth_version, expected_revision, request_id, intent_digest, now=None)
accept_invitation(con, *, household_id, account_id, invitation_id, expected_revision,
                  request_id, intent_digest, now=None)
leave_membership(con, *, household_id, member_id, account_id, expected_auth_version,
                 expected_revision, request_id, intent_digest, now=None)
create_invitation(con, *, household_id, actor_member_id, expected_auth_version,
                  request_id, intent_digest, now=None)
revoke_invitation(con, *, household_id, actor_member_id, invitation_id,
                  expected_revision, request_id, intent_digest, now=None)
remove_membership(con, *, household_id, actor_member_id, member_id, expected_auth_version,
                  expected_revision, request_id, intent_digest, now=None)
record_operation(con, *, subject, request_id, intent_digest, result, now=None)
```

`active_member(s)` 返回安全内部摘要 `{id,name,householdRole,authVersion,membershipId,membershipRevision}`；不含密码及个人 account_id。非 active 或缺关系返回 None，非法角色/版本拒绝。需要登录密码的接线可在同一 con 通过该检查后读取原 users。`membership_record` 是仅协调层可用的内部记录，恰好选择一个参数；不可直接序列化为成员列表。

`snapshot` 及 bind/accept/leave/remove 的直接结果固定为 `{id,householdId,memberId,memberName,householdRole,state,revision}`。`list_memberships` 默认 active；普通成员不可读取 `status='all'`。HTTP 包装层返回 `{memberships:[...]}`，不增加私人财务、云、媒体或个人账号字段。

邀请摘要固定为 `{id,state,revision,expiresAt,householdRole:'member'}`；expired 和 invalid 是读取时根据到期和原 inviter active/admin/auth_version 派生的状态。创建首次返回 `{invitation,token}`，token 采用 32 字节安全随机数；原回执和重试只返回 `{invitation}`。撤销返回 `{invitation}`，已 used 不允许撤销。列表只有 admin 可读。inspect/validate 不返回创建人的私人信息，确认接受时必须再次验证；最多 20 个当前有效邀请、7 天有效、100 个 active 成员，超限 409。

接受邀请不签发成员 Cookie。首次加入创建 `m_` 加 24 位随机 hex 的 users.id/internal username、随机不可用密码散列和普通成员角色；已绑定同账户 active 关系不重复创建。left/removed 仅同原账户凭新有效邀请恢复相同 member_id/membership id，角色为 member，revision/auth_version 再递增，旧私有 owner 不迁移。不同账户创建新 ID，不接管旧私有记录。

bind 和 leave 的 expected_auth_version 是本人版本，create 是操作者版本；**remove 的 expected_auth_version 是操作者版本，expected_revision 是目标 membership 版本**。目标 auth_version 在同事务读取并递增，不要求客户端提供未公开字段。管理员只能移除另一成员，最后一位 active admin 不能退出/被移除；inactive users 中保留的 admin 值不参与人数。历史回执不重建或覆盖当前状态；已失权管理员先被拒绝。leave 原结果可由已认证的原账户内部查询，不借撤销 Cookie 授权。

停用事务递增目标 auth_version/membership revision、撤销目标 member_sessions 并推进关联浏览器代次，记录 audit。原 users/私有数据/令牌保留；已有 cloud_accounts 标记 needs_reauth，calendar/task 的待发布、进行中及已发布关联状态置 paused，保留内容和外部引用。媒体没有 paused 枚举，因此该模块不删除或重置媒体；运行接线与 worker 仍须拒绝 inactive，并防止飞行中结果将 paused 改回 published/retry。重新加入不自动恢复云写队列。已完成的外部动作不声称撤回。

`operation` 仅供已证明精确主体的协调层，返回 `{requestId,found,state:null|'completed',result:null|原结果}`；found=false 不能证明原请求未在途。`member_operation` 先核 active，再查自己的成员操作或与本人同 member_id 的绑定账户操作；两个本人主体恰好用了相同 ID 时返回 409，不能猜测是哪份回执，不开放他人回执。平台层自行实现 pending/not_committed 以及显式 resume，领域不重做未知操作。

`record_operation` 只接受 account 主体及严格两种有限结果：七字段成员摘要，或 `{ok:true,householdId,memberId,entry:'/app/home'}`。新回执验证实际 account→membership 绑定，switch 还须 active；派生成员会话与回执必须由调用方放在同一户内事务。恢复原 switch 回执不重签 Cookie，也不把历史结果当作当前权限。

## 验证边界

专项使用既有真实 Flask 应用创建的临时 SQLite、真实 Cookie 和独立事务；合成账户/金额/云占位数据，禁止 socket 外连。涵盖迁移旧表保持、三表部分初始化和缺关系拒绝、实际密码绑定、第三人成员、邀请/回执秘密边界、到期/失权/限额、退出/移除和 Cookie 失效、原 ID 私有数据恢复、最后 admin、并发竞争、审计失败与外层回滚。

实际 R1 单轮 32/32 PASS（19.59 秒），全部 tracked 与两份作者源码前后 SHA 相同。随后补他人使用被停用成员云账户的队列暂停、两种本人主体同 ID 回执歧义两项检查；R2 仅执行新增两项及四项直接相关回归，6 PASS / 28 deselected（5.42 秒），不是声明最终 34 项在同一轮全跑。原件为本树 ignored `test-results/membership-domain-r1/` 与 `membership-domain-r2/` 的 results.xml、stdout.txt、stderr.txt、record.json，均保留；未有失败轮次。历史列表当前没有分页，100/20 仅限制 active/有效数量，HTTP/客户端须对大响应给出明确上限错误，不宣称永久全量历史可用。

本专项不证明个人账户 HTTP/跨库恢复、动态 owner 全应用接线、运行 worker、OAuth/媒体票据或生产迁移已完成；这些必须在后续真实组合分别验收。没有外部服务、实体设备或本人真实资料验收。
