# 家庭成员管理 API 候选

基线 `eda8632719a6f1a3202e6d5c2a9a986329c9c287`。本模块仅提供当前家庭两位成员的角色与浏览器会话管理；尚未接入正式应用或部署。app 注册、Docker、发布白名单及独立 schema 迁移验证由组合任务负责。

## 注册与迁移

`register_members(app, db, Problem, body, require_member, audit)` 使用应用真实依赖与 `app.extensions['member_sessions']`，必须在首次请求前注册。调用方须先完成 users 初始化和成员会话初始化。测试通过真实应用的注册接缝注入此模块，不替换身份鉴权结果。

导出 `HOUSEHOLD_ROLE_COLUMN_SQL`：

```sql
ALTER TABLE users ADD COLUMN household_role TEXT NOT NULL DEFAULT 'member' CHECK(household_role IN ('admin','member'))
```

`init_schema(con)` 自管 `BEGIN IMMEDIATE`、提交和失败回滚；调用前连接不得已有事务。缺列时才执行 DDL，并将已存在的 `member1`、`member2` 一次性设为 `admin`，保留两人共同管理。已有列时不重置角色。新家庭先按原应用创建两名成员，再注册本模块，两人同样成为管理员；本模块不提供新增成员接口。将来直接插入 users 的新行默认 `member`，不意味着已实现成员加入。

表数仍为 58，但 users 的定义发生变化。必须由独立迁移检查器证明 users 原五列、另外 57 张表、平台注册信息与序列保持；不能沿用此前无 schema 变化的发布流程，也不以这里的临时 SQLite 测试代替生产迁移或备份恢复验证。

## API 与 DTO

请求均使用当前家庭的真实会话；不接受查询参数或请求体中的 owner/household 选择器。匿名返回 401，电视返回 403，写请求沿用同源 CSRF。认证 `actor.role=member|tv` 与 `/api/me` 保持原样，`householdRole` 是独立数据库权限。

`GET /api/members` 不接受请求参数，按成员 id 排序：

```json
{"currentMemberId":"member1","members":[{"id":"member1","name":"我","householdRole":"admin","authVersion":1,"activeSessionCount":1,"capabilities":{"changeRole":false,"revokeSessions":false}},{"id":"member2","name":"伴侣","householdRole":"admin","authVersion":1,"activeSessionCount":2,"capabilities":{"changeRole":true,"revokeSessions":true}}]}
```

两种家庭角色都能读取名单。管理员的 `activeSessionCount` 为未撤销、未过期、authVersion 与当前用户一致的会话数量；普通成员看到的所有条目该字段均为 `null`。数量不代表物理设备或在线人数。不返回设备明细、Cookie、CSRF、原始 UA、IP、邮箱、密码或第三方令牌。能力仅允许当前管理员操作另一成员，服务端每次独立鉴权。

| 操作 | 精确请求体 |
| --- | --- |
| `POST /api/members/<id>/revoke-sessions` | `{"expectedAuthVersion":1}` |
| `PATCH /api/members/<id>/role` | `{"expectedAuthVersion":1,"householdRole":"member"}` |

版本必须为 1 至 9007199254740991 的整数，拒绝布尔值、浮点数、字符串、额外字段和重复 JSON 字段。目标编号限 1–80 个 ASCII 字母、数字、下划线或连字符；合法但不存在的编号返回 404。家庭角色只允许 `admin|member`。

两种成功响应均为：

```json
{"ok":true,"member":{"id":"member2","householdRole":"member","authVersion":2},"revoked":2}
```

撤销会话不改变目标角色。`revoked` 是此事务失效的当前有效会话数；过期但尚未标记撤销的旧行也会留下撤销标记。两种写操作均原子增加目标 authVersion、标记其会话撤销、推进关联浏览器的认证代次并写审计。数量为零也增加版本，以拒绝尚未登记的旧 Cookie 和携带旧身份的请求。版本达到上限拒绝写入，不溢出。

| 状态 | 含义 |
| --- | --- |
| 400 | JSON、版本、字段或查询参数不合法 |
| 401 | 实际会话已失效或请求过程中身份变化 |
| 403 | 非管理员、本人操作、不允许的角色或读后角色变化 |
| 404 | 当前家庭中无此目标 |
| 409 | 目标版本变化、角色未变化、最后管理员保护或版本已达上限 |
| 503 | 数据库角色或成员版本无法安全核对 |

管理员不能操作自己，不能清空最后一位管理员。不同管理员并发互相降权时，写锁内重新检查发起者实际会话及当前角色，不能同时把两人降为普通成员。

## 事务与恢复边界

入口捕获实际 session id、owner、authVersion 与家庭 id。读操作在建立完整业务快照前释放旧 Cookie 解析可能产生的隐式事务；读后先释放快照，再核对实际会话及当前角色。首次旧 Cookie 登记已由现有 `actor()` 事务提交，不能因读操作回滚而丢失初始化。写操作在取得 SQLite 写锁后鉴权，审计后、提交前再次鉴权；失败回滚角色、版本、会话、浏览器代次及审计。

成功的角色调整要求目标重新登录。目标仍可使用原有效凭据登录；撤销不是封禁、删除或退出家庭。已保存的云账户及私人数据不删除或改归属，已有成员会话发起的 OAuth 上下文失效；新的匿名登录流程仍按原登录规则处理。不宣称撤回所有已经开始的普通业务请求、外部操作或后台同步。

本批没有操作回执或 requestId。相同旧版本重发会返回 409，不应自动重试。响应未知时只允许用户明确 GET 当前名单核对；即使版本和目标角色相同，也不能把读取结果当作这次操作回执。只有再次确认新操作，才使用新读出的目标版本提交。客户端仍须使用完整身份与生命周期围栏，防止迟到结果覆盖当前界面。

家庭管理员不获得他人私人财务、照片、日历、云账户或导出权限；不改变共同任务、旅行与电视的原权限。平台邀请仍为原有“创建另一个家庭”流程，家庭管理员角色不扩展该权限。本批未实现邀请加入、退出家庭、通用成员数量、同一用户多户或全局账号。

## 实际验证

专项使用独立临时家庭 SQLite、真实 Flask 请求与签名 Cookie；只允许本地回环 HTTP，拒绝外网。覆盖迁移一次性与 DDL 回滚、两户同 id 隔离、普通成员/匿名/电视拒绝、同源 CSRF、旧 Cookie、锁等待后撤权、读后撤权、审计后过期完整回滚、两个管理员并发降权、CAS 防重复撤销与成员绑定 OAuth 失效。

实际记录位于作者 worktree 的 ignored `test-results/`，不进入发布包：

| 原件目录 | 实际结果 |
| --- | --- |
| `household-members-r1` | 43 项，41 通过、2 失败；失败为成功写入后测试误要求审计序列保持不变 |
| `household-members-r2` | 仅重验修订的 2 项并新增 5 项，7 通过、41 未选；审计序列改为单独核对递增，其他表与非审计序列仍比较不变 |
| `household-members-compat-r1` | 用成员注册 fixture 作为 pytest plugin 注入真实 app 后运行原 `test_member_sessions.py` 和 `test_household_spaces.py`，68 通过、2 失败；两个本地 HTTP 登录竞态被测试自身全网络禁令拦截 |
| `household-members-compat-r2` | 测试网络护栏改为仅允许回环地址，原两项定向补验均通过，59 未选 |

累计 48 个成员专项与 70 个旧会话/多户用例均有通过结果；不是一次完整 118 项运行。四轮保留真实 stdout、stderr、JUnit 与输入前后 SHA；业务模块 SHA 始终为 `7c52fd65426f3eaee0c970982abd0563d01ddab44fd1a9ff38f9661eb4a3ffa9`。两次失败均保留，未改既有测试或重跑已通过集合。

真实浏览器、接线后的全应用、生产迁移/恢复、真实云和实体电视尚未验证。
