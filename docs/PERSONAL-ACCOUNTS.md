# 个人账户认证与跨库协调

本模块实现 [成员关系设计](HOUSEHOLD-MEMBERSHIP-DESIGN.md) 的平台侧认证与协调。当前为独立候选代码；完整应用接线、迁移发布及浏览器交互由后续组合验收确认，不表示已经上线。

个人账户只用于证明身份和选择已绑定家庭。业务私有 owner 仍是各户原 `users.id`；注册不自动绑定，用户名相同不自动合并，退出后目录和历史回执不授予户内权限。

## 存储与身份

平台新增七张表：`personal_accounts`、`personal_browsers`、`personal_sessions`、`account_memberships`、`account_operations`、`account_qualifications`、`personal_limits`。`init_schema(con)` 只接受空闲连接，自管事务。首次仅允许 `PRAGMA user_version=0` 且七表全无；完成后置为 1。已初始化必须保留七表，部分或全部丢失均拒绝，不重新创建身份。旧 `households`、平台邀请以及户内数据均不重写。

密码使用项目现有 Werkzeug 密码散列；资格、凭据、CSRF 和浏览器标识在库中保存散列。意图中的密码／原邀请令牌只进入服务端 keyed HMAC，不存原文。操作编号在同一账户内唯一，注册回执和后续操作不能复用同编号覆盖彼此。

独立 `personal_account` Cookie 使用单独签名 salt、HttpOnly、SameSite=Lax 和部署的 Secure 设置。浏览器代次存于平台库，注册、登录、退出及新切换成功均恰增加 1，并旋转个人 CSRF。不同浏览器不互相退出；乱序回来的旧 Cookie 不能恢复已失效代次。切换保留原密码证明时间，不延长 300 秒的近期证明。

账户路径拒绝电视身份，敏感响应 `no-store`。同源写入校验个人 CSRF，并检查 Origin／Sec-Fetch-Site；资格签发另检查成员 CSRF。限流计数在独立短事务落库，失败登录也计数。

## Root 接线 API

`PersonalAccounts(platform, callbacks)` 暴露独立 Flask `engine.app`，由 Root 在 `/api/account/*` 的户内路由选择之前分发。构造时初始化平台新表；本文件自身不修改应用注册。

| API | 合同 |
| --- | --- |
| `guard(identity=None, require=False, recent=False)` | 可无 HTTP 上下文调用；同线程可重入，使用独立原始平台 SQLite 连接和 `BEGIN IMMEDIATE`；必须先于任何户内锁 |
| `guard_con` | 当前 guard 的平台连接，未持锁为 `None` |
| `capture(raw_cookie=None, require=True, csrf=False, recent=False, csrf_header='X-CSRF-Token')` | 捕获并核对真实签名 Cookie、浏览器代次、个人 session、account auth_version；显式 Cookie 可在无请求环境读取 |
| `identity_dict(identity)` | 仅 `browserHash,generation,csrfHash,sessionId,accountId,authVersion,credentialHash`；供派生成员会话保存不可伪造的原身份，无密码／原 credential |
| `current(con, identity, require=False, recent=False)` | 在已有平台锁下 fresh 校验；接受捕获对象或精确上述字典；返回内部 session 字段及 `accountId`，不额外反取锁 |
| `handle_bind(body)`／`handle_leave(body)` | Root 成员路由代理；Root 先校验成员主 CSRF，本模块校验 `X-Account-CSRF-Token`，维护 pending 与恢复 |
| `Error(message,status,code=None)` | 有限 HTTP 错误，不能把异常视作未提交证明 |

必须提供 callbacks：

- `membership`：已固定的 `household_memberships` 领域模块。
- `household(household_id)`：上下文管理器，返回已有目标库的空闲连接；不可缺库新建或回退 default。本模块开启并提交／回滚户内事务。
- `member_proof(platform_con,password_or_None)`：从当前真实成员 Cookie 和相应成员 CSRF 取得 `{householdId,memberId,authVersion,sessionId,membershipRevision}`，有密码则核原成员密码。
- `validate_member_proof(platform_con,proof,household_con=None)`：复核原捕获成员身份，不能用中途新会话替代；已传户内连接时必须复用。注册对既有资格的 fresh 校验不要求重新提交成员 CSRF；资格签发和成员写入口已各自校验。
- `install_member(platform_con,household_con,new_personal_identity,membership_summary)`：在已有户内事务创建派生成员 session，返回响应装饰函数；只在平台成功提交后安装 Cookie。个人身份已旋转，不能再用旧派生身份要求授权。
- `is_tv()`：真实电视身份检查；缺检测时 fail closed。

回调自己的权限异常须由独立账户 Flask 注册相应错误处理，或转换为 `engine.Error`。可选 `boundary(name)` 只用于确定性中断验证，不运行网络业务。嵌套 guard 内异常会使外层事务失败，即使调用者捕获异常也不能误提交。

## HTTP 与未知结果

账户 `/me` 返回设计约定的 `{account,csrf,authVersion,authenticationGeneration}`。无有效个人凭据时建立匿名 CSRF；不暴露户内成员列表。其余写入严格拒绝多余／重复 JSON 字段，版本拒绝布尔和非正安全整数。

| 路径 | 行为 |
| --- | --- |
| POST `/api/account/eligibility` | 真实当前成员及原密码、两域 CSRF，签发 300 秒注册资格 |
| POST `/api/account/invitations/inspect` | `{householdSlug,token}`；返回 `{household:{id,name,slug},householdRole:'member',joinTicket,eligibilityToken,expiresAt}` |
| POST `/api/account/register` | `{requestId,login,password,eligibilityToken}`；只注册，不绑定；密码散列完成后再次核资格及原身份 |
| POST `/api/account/login` | `{login,password}`；登录名为 3–64 位小写 ASCII 字母、数字、`._-`，密码 12–128 字符；错误不区分账号存在性 |
| POST `/api/account/logout` | `{requestId}`；撤当前浏览器个人凭据；Root live 检查使该凭据派生的成员失效，原独立本地成员 Cookie 不被删除 |
| GET `/api/account/households` | 只列本人的目录，逐户检查同一 membership ID／member／account 且 active；不可读项返回 unavailable |
| POST `/api/account/invitations/accept` | `{requestId,joinTicket}`；登录／注册后必须重新 inspect；当前账户和浏览器绑定的新 ticket 才可新提交 |
| POST `/api/account/switch-household` | `{requestId,membershipId,expectedRevision}`；精确目录与户内关系复核后创建派生 session；回执重放不签 Cookie |
| GET `/api/account/operations/<requestId>` | 仅本人有限历史；`found=false` 不是未提交证明 |
| POST `/api/account/operations/<requestId>/resume` | `{}`；显式只收尾或确证 not_committed，不重做原业务 |

注册丢回复时，原匿名浏览器与资格代次仅可读对应注册回执或同意图返回原结果，不重新签发个人 Cookie；缺上下文需明确登录后核对。原 requestId 不同内容返回 409。历史回执不覆盖当前成员状态。

跨库执行顺序是：平台 pending 独立提交 → 重新取得平台写锁 → 目标户写事务及同事务领域回执 → 平台目录与有限结果收尾。提交前 fresh 检查捕获的个人身份；绑定还需要近期个人密码证明和原成员证明。本人 leave 导致的预期成员撤销不误判成个人凭据撤销。

户内提交后平台中断保留 pending。resume 持同样锁序读取原户内回执：有回执仅补平台目录／结果；可读并排除在途且确定无回执则记不可逆 `not_committed`；库不可读保持 pending。迟到原请求取得锁后检查终态，不能复活已结束意图。任何 Cookie 只在成功平台提交后安装；恢复 switch 不重签原登录凭据。

## 验证范围

专项采用真实 Flask Cookie、临时平台及两个户内 SQLite 库、实际领域模块、独立 writer 和有界线程握手。覆盖注册资格／双 CSRF／限流和严格输入、真实会话过期／撤销／换代、丢响应、pending 两个提交边界、未知库与 not_committed、乱序切换、同名成员两户绑定及原 owner 保留。

2026-09-18 本地实际记录：`test-results/personal-accounts-r2` 的 37 项全部通过；随后新增并发登录、失败限流、嵌套回滚三项，`personal-accounts-r3` 定向 3 项全部通过。两轮生产模块字节相同，原 37 项及 fixture 的 AST 未改；这是两轮合计覆盖 40 项，不冒充同次全量运行。最终领域依赖为独立树 `754d2e1552c8953b9d490df246d1328bdf3abf43` 的真实模块，SHA-256 `dad3afb0efa5bd8aa5cd0670185d023fb18c00c5b02d8468b682fbaeb7c9e757`；通过环境变量 `PERSONAL_ACCOUNTS_DOMAIN_ROOT` 显式加载，未合入本作者分支。组合后默认从当前源根目录加载。

R2／R3 均保留 invocation、XML、stdout／stderr、作者源码旁存及输入前后散列。R2 XML SHA-256 `943959afd728580003601e8c3ea5df2dd1f093d6a35407ed9294112e0af41d6b`，R3 XML `4f1f696093dcdcbe9c517b1701c998136355f4d756f06dd207fda922ea723151`。首轮 R1 为 26 通过、1 失败：测试接线未将原应用的会话撤销异常转换到独立 Flask 错误域；已保留原件并修复测试接线，未删断言。

此独立专项不替代 Root 最终连接锁、成员 live、迁移检查器、UI 和完整连续链验收；不使用生产数据、外部云或实体电视。
