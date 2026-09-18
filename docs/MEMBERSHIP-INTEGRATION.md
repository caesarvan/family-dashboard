# 个人账号与家庭成员：运行接线

本批为开发候选，尚未发布到服务器。领域、个人认证、Expo 面板各自使用独立分支；主接线只有集成人编辑。设计与字段契约见 [成员关系设计](HOUSEHOLD-MEMBERSHIP-DESIGN.md)、[户内领域](HOUSEHOLD-MEMBERSHIP-DOMAIN.md)、[个人账户](PERSONAL-ACCOUNTS.md)、[前端使用](EXPO-MEMBERSHIPS.md)。

## 用户入口

- 登录页的「我的家庭账户」用于个人登录；「使用邀请加入家庭」可先核对邀请，再注册或登录并加入。
- 已有成员从「更多 → 我的家庭账户」验证原家庭密码，创建个人账号后明确绑定原身份。绑定保持原 users.id 和所有私人数据 owner。
- 「更多 → 家庭与成员」保留角色及浏览器撤销，并增加邀请、移除、退出入口。管理员只能移除另一成员；最后一位有效管理员不可退出。
- 「我的家庭账户」列出当前账号的家庭，切换后重新读取家庭身份和数据。原有两个家庭登录按钮仍可用于尚未绑定的旧账号。
- 退出成员登录只退出当前家庭视图；个人账户的退出按钮撤销个人登录及其派生的家庭登录。旧的独立家庭账号不会被自动合并或注销。

## 软件与事务边界

`household_spaces.HouseholdPlatform` 在家庭路由前分发 `/api/account/*` 至独立 Flask 应用。该应用使用个人 Cookie、CSRF、浏览器代次及持久会话；家庭路由 Cookie 仍只用于选库。`membership_http.py` 验证旧成员的签名 Cookie、实际会话和密码，并提供跨库协调回调。

`membership_storage.py` 为应用数据库、成员会话和云账户连接提供 SQLite Connection/Cursor 子类。每条语句先取得可重入的平台协调锁；显式 BEGIN、SAVEPOINT 或隐式写事务持锁到 commit、rollback 或 close。单条自动提交读取释放锁，不因打开连接而跨网络持锁。目标家庭缓存也遵循 platform → cache → household 顺序。

普通成员 HTTP 请求取得新的数据库事务前，会再次核验原捕获的实际会话，防止在请求入口认证后被移除仍写入。派生家庭会话保存个人身份散列与代次；每次读取都在平台协调锁内复核个人会话。切换家庭旋转个人凭据，迟到的旧家庭 Cookie 无法恢复访问。

成员命令同一事务写实际关系、版本、会话撤销和回执。跨库写由 `PersonalAccounts.coordinate` 先持久化 pending，再在 platform → household 锁序内提交户内数据，最后完成平台目录与回执。不能把两库称为全局原子事务。未知结果先 GET 原操作；仅显式 resume 在排除在途操作后根据户内回执收尾或标为 not_committed。

## HTTP 接线

| 路由 | 身份与作用 |
|---|---|
| `/api/account/*` | 个人认证独立路由；写入使用个人 `X-CSRF-Token` |
| `POST /api/account/eligibility` | 另需 `X-Member-CSRF-Token` 和原家庭密码；注册消费资格时重新核验原成员 Cookie |
| `POST /api/membership-links` | 成员 `X-CSRF-Token` + 个人 `X-Account-CSRF-Token`；双重证明绑定 |
| `GET /api/memberships` | 当前有效成员；`status=all` 仅管理员 |
| `GET/POST /api/member-invitations` | 管理员查看/创建；原令牌仅首次创建回复可见 |
| `POST /api/member-invitations/<id>/revoke` | 管理员按邀请版本撤销 |
| `POST /api/memberships/<memberId>/remove` | 管理员按本人 auth_version 和目标关系 revision 移除 |
| `POST /api/memberships/self/leave` | 双会话/双 CSRF，保留最后一位管理员 |
| `GET /api/membership-operations/<requestId>` | 当前有权的原操作主体读取有限回执 |

`/api/me.user` 新增 `membershipRevision`；派生身份另含 `accountId`、`accountAuthVersion`、`authenticationGeneration`。新增字段参与前端身份签名。`/api/state.people` 和 `/api/members` 仅列有效成员。新分配使用实际成员 ID；历史私人数据、记录负责人和原 users 行保留。

## 数据迁移与发布要求

户内新增 `household_memberships`、`member_invitations`、`membership_operations` 三表，既有 `member_sessions` 增加可空 `personal_identity` 列。旧会话初始为 NULL，旧成员仅首次生成未绑定 active 关系，不改原密码、角色或私人数据。`settings.membership_schema_v1` 标记防止三表丢失后被启动过程重新创建并恢复已失效成员。

平台新增个人账号、浏览器、会话、账号家庭目录、操作回执、注册资格、限流七表。准确 SQL 以 `personal_accounts.SCHEMA` 和 `household_memberships.SCHEMA_STATEMENTS` 为准；本批不是历史 58→58 无 DDL 发布。

Docker COPY 和基础打包白名单包含四个新增运行模块。部署前必须使用本批专用迁移核验：停全部写入进程，逐库备份并保留原程序；在隔离副本启动新程序，核对旧行、列、序列、角色和密钥配置保持，以及新表/列/标记精确变化。组合测试、独立审查及新备份验证通过后才能切换服务。

**不能直接回退到不认识失效成员状态的旧程序。** 回退必须停写并恢复发布前整组数据库和对应程序，或使用明确支持新权限模型的修正版；发布后的新数据需要先保全。不可复用旧无 DDL operator 或将此前发布证据记为本批验证。

## 实际验证与尚未完成

主接线使用真实 Flask 客户端、签名 Cookie、临时 SQLite 和合成资料。首轮相关回归 86 项通过；此后加强事务前权限复核和初始化标记，成员与财务基线专项 28 项通过。含注册/绑定、第三人加入、跨家庭切换、移除/原 ID 重新加入、个人退出撤销派生凭据、最后管理员、双 CSRF、平台锁生命周期，以及请求认证后并发移除阻止待办落库。

这些是开发过程验证，最终固定组合仍需重新验收。真实浏览器交互、迁移副本检查、worker 最终写回、独立代码审查及生产部署尚在进行。本人云账号和实体电视不由临时测试替代；实体电视按用户反馈暂缓验证。
