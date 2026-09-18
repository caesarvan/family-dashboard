# 家庭成员关系：下一批实现契约

设计基线 `bf38f81c5d81dd3e9afd34474383e0910f460434`；本文件是待独立审查的方案，尚未实现、迁移或部署。
交付目标：第三位成员受邀加入既有家庭、明确退出／移除、同一人切换自己所属的两个家庭；全程可用本地凭据和合成数据验收。
不增加外部账号授权，不做账户自动合并、私人数据跨户搬迁、未成年人权限、模块级角色或家庭删除。

## 1. 已有能力与不可改变的归属

- [家庭空间](../household_spaces.py) 的 registry 目前只有 `households`、`household_invitations`；现有邀请码用于创建新家庭及两位固定成员。
- [登录与实体](../app.py) 的 `users.id`、私人 `owner`、云账户、媒体许可及历史回执均属于当前家庭数据库；各户的 `member1` 不是同一人的证明。
- [成员会话](../member_sessions.py) 已有签名、`auth_version`、浏览器代次和撤销；[基础角色](../household_members.py) 已有管理员／普通成员与最后管理员约束。
- 原 `member1/member2` 的 ID、密码散列、私有 owner、财务共享和云令牌不重写。两位默认管理员保持；若已有合法角色变更，也保留实际值，不能再次初始化为 admin。
- `actor.role=member|tv` 保持；家庭角色仍在 `users.household_role`。个人账户不直接成为业务 owner，也不让管理员读取其他成员的私人资料。
- 平台建户邀请 `/api/spaces/invitations` 的既有平台权限独立保留；家庭 admin 获得下面的“邀请加入本户”，不因此获得创建任意家庭的权力。

## 2. 数据模型与权限依据

| 所在库 | 新增记录 | 约束与作用 |
|---|---|---|
| platform | `personal_accounts` | 随机 32 位小写 hex `id`，唯一规范化 `login`，密码散列、`auth_version`、时间；不复制户内密码或第三方令牌 |
| platform | `personal_sessions`／`personal_browsers` | 独立凭据散列、CSRF、失效时间和浏览器代次；与成员、电视 Cookie 分离 |
| household | `household_memberships` | `member_id` 主键指向原 users；`account_id` 可空且非空唯一，`state=active|left|removed`，`revision`、时间；状态是本户访问权限依据 |
| platform | `account_memberships` | 唯一 `(account_id,household_id)` 及 `(household_id,member_id)`，仅作目录索引，不凭索引中的角色／状态授权 |
| household | `member_invitations` | 随机 ID、令牌散列、创建人及 auth_version、到期、撤销／使用状态、revision；仅邀请为普通成员 |
| platform／household | 各自操作记录 | requestId、主体、规范化意图摘要、步骤状态、有限结果；秘密字段仅参与服务端 keyed HMAC，不留原文；户内记录与成员变更同事务提交，平台记录协调跨库收尾 |

既有 users 一次性补 `active/account_id=null/revision=1`；缺记录不能在请求鉴权时自动补齐。新增成员用 `m_` 加 24 位随机 hex，绝不重用退出成员 ID。
新增 users 的内部 username 使用该成员 ID，密码散列来自不可用的随机秘密，不设默认共享密码；通过个人账户进入，初始名“新成员”可由本人沿现有 profile 修改。
本户同一个人只对应一个成员；已绑定身份不得换绑给另一个个人账户。再次受邀时只可由原账户恢复原成员 ID，不继承旧 admin 权限，明确按普通成员加入。
停止成员关系保留 users 和业务历史；新负责人只能选择 active 成员或 shared，旧非活动负责人可以显示“已退出成员”并由有权者明确重新分配。
邀请令牌采用至少 32 字节安全随机数、仅存散列、7 天失效；默认最多 100 个 active 成员、每户 20 个有效邀请、每账号 30 个家庭，超限返回 409。
`login` 使用 3–64 位小写 ASCII 字母／数字／`._-`，密码 12–128 字符；不得把邮箱、同名或用户名相同当作跨家庭绑定证据。

## 3. 个人账户与旧身份的安全绑定

入口：“家庭与成员 → 我的家庭账户”。原本地登录继续可用；创建个人账户不自动接管任何其他户内身份。
当前成员先用自己的原家庭密码重新证明身份，再创建个人账户或登录已有个人账户；确认页同时显示个人账号、家庭名称和当前成员名，明确“绑定这个身份”。
绑定必须同时满足当前有效家庭成员会话、原成员密码、当前个人账户会话及其 5 分钟内密码验证；服务器从会话取双方 ID，不收客户端 owner/accountId。
旧成员无可用密码时本批不做管理员代绑、邮箱猜测或云身份自动合并；保留原登录方式，不转移其数据。
同一个人绑定第二户时，必须在第二户独立证明那个旧成员的密码；只输入家庭地址或持有第一户会话不够。
注册资格仅来自上述家庭密码证明，或有效邀请检查所得 300 秒 `joinTicket`；采用同源匿名 CSRF、限流和浏览器代次，不开放无邀请批量注册。
注册仅创建个人账户；绑定／接受邀请另一次明确确认。资格令牌不可反复创建多个个人账户；密码与原令牌不进入日志、URL、操作回执或前端持久化存储。

## 4. HTTP 合同：账户与跨户操作

下列均为计划新增；`/api/account/*` 在家庭路由选择之前分发，以独立个人账户 Cookie 和 CSRF 鉴权。户内业务仍只认当前家庭会话。
新写操作统一 `requestId` 为 32 位小写 hex；拒绝额外／重复 JSON 字段，版本为正安全整数。同原 ID 不同意图 409，相同意图只返回原结果或 pending，不重复业务写。
表中字段均必填；`?` 表示可省略。所有敏感响应 `no-store`；匿名 401、TV／越权 403、不可见资源 404、版本／资格／状态冲突 409。

| 方法与路径 | 精确请求字段 | 返回与用途 |
|---|---|---|
| GET `/api/account/me` | 无 | `{account:null|{id,login},csrf,authVersion:null|number,authenticationGeneration}`；未登录只给匿名 CSRF，不枚举成员 |
| POST `/api/account/eligibility` | `{memberPassword}`，必须同时有当前成员会话及其 CSRF | `{eligibilityToken,expiresAt}`；300 秒、绑定原家庭／成员／auth_version／浏览器，不能作为登录凭据 |
| POST `/api/account/register` | `{requestId,login,password,eligibilityToken}`；邀请检查也可提供注册资格令牌 | `{account:{id,login}}`；注册成功安装个人 Cookie，资格只消费一次；不自动绑定／加入 |
| POST `/api/account/login` | `{login,password}` | `{account:{id,login}}`；旋转个人会话与 CSRF；错误不泄露是否存在账号 |
| POST `/api/account/logout` | `{requestId}` | `{ok:true}`；撤本浏览器个人会话及由它签发的成员会话，保留其他浏览器 |
| GET `/api/account/households` | 无 | `{memberships:[{id,householdId,name,slug,memberId,memberName,householdRole,revision}],unavailable:[{householdId,code:'temporarily_unavailable'}]}`；仅当前账户、逐户复核 active，不可用不冒充不存在 |
| POST `/api/account/switch-household` | `{requestId,membershipId,expectedRevision}` | `{ok:true,householdId,memberId,entry:'/app/home'}`；复核目标 membership 后签发目标户成员 Cookie 与家庭路由 Cookie |
| GET `/api/account/operations/<requestId>` | 无 | `{requestId,found,state:null|'pending'|'completed',result:null|有限结果}`；只读本人操作；`found=false` 不证明未执行 |

资格接口需要两个独立 CSRF 域：`X-CSRF-Token` 为个人／匿名账户 CSRF，`X-Member-CSRF-Token` 为当前家庭 CSRF；不可互相代用。
注册丢回复时不把个人账户存在当回执；同浏览器资格上下文可查询该注册操作的有限状态，已失去上下文时先明确登录该账号核对，不能自动换用户名重建。
个人 Cookie 仅证明个人会话；业务仍检查户内成员状态。由个人会话派生的成员凭据记录其来源 session/version，注销／换账号后的旧凭据不能继续作为新请求的身份。
切换保持原户和目标户的独立签名；旧 cookie 不传给目标 app。个人浏览器代次将切换串行化，迟到 Cookie 即使覆盖浏览器也只能导致重新核对，不能恢复旧权限。
现 `/space/<slug>` 保留为显式旧家庭登录入口，不能绕过 inactive membership，也不能自动建立账号归属或用 GET 签发个人账户的目标户登录。

## 5. HTTP 合同：本户邀请、加入与离开

本户接口使用现有成员会话／CSRF、事务内 fresh actor 和角色复核；绑定额外检查个人会话及其 CSRF。检查／接受邀请是个人账户路由，不依赖当前所选家庭。

| 方法与路径 | 精确请求字段 | 返回与权限 |
|---|---|---|
| POST `/api/membership-links` | `{requestId,memberPassword,expectedAuthVersion,expectedRevision}` | 当前双方身份明确绑定；已有同一映射返回原结果，已绑定他人 409；返回 membership 摘要 |
| GET `/api/member-invitations` | 无 | admin 看本户邀请 ID、状态、到期、revision；不返回原 token 或受邀者个人凭据 |
| POST `/api/member-invitations` | `{requestId,expectedAuthVersion}` | active admin；`{invitation:{id,state,revision,expiresAt,householdRole:'member'},token}`；token 仅首次成功回复出现 |
| POST `/api/member-invitations/<id>/revoke` | `{requestId,expectedRevision}` | active admin 撤邀请；used 不回滚成员关系，409 后只读核对 |
| POST `/api/account/invitations/inspect` | `{householdSlug,token}` | 同源匿名／个人 CSRF；返回最小家庭名称、普通成员角色、300 秒 joinTicket 与注册资格；不含成员／私有资料 |
| POST `/api/account/invitations/accept` | `{requestId,joinTicket}` | 已登录个人账户；确认家庭及角色后一次性消费；返回 membership 摘要，不自动切换家庭 |
| POST `/api/memberships/<memberId>/remove` | `{requestId,expectedRevision,expectedAuthVersion}` | active admin 对另一成员设 removed；拒绝最后一位 active admin；返回有限操作结果 |
| POST `/api/memberships/self/leave` | `{requestId,expectedRevision,expectedAuthVersion}` | 已绑定本人且个人／家庭会话都有效，设 left；最后 admin 须先明确转交；退出当前家庭，不影响其他家庭资格 |
| GET `/api/membership-operations/<requestId>` | 无 | 当前仍有权的原主体查户内操作；格式同账户操作查询，不能读取其他人的记录 |

邀请确认时重新检查发起人仍 active admin、其版本未变、邀请未撤销／到期及 joinTicket 的账户／浏览器；不是 inspect 成功就永久有效。
注册／登录会旋转个人身份；完成后重新 inspect 同一原邀请，取得绑定当前账户的新 joinTicket，确认页再允许接受，不沿用匿名旧 ticket。
绑定以当前户 member_id 为准；邀请加入若已 active 返回当前关系，不建第二人；若 left/removed，只在新有效邀请及本人明确确认下恢复同一关系为 member。
原 `/api/members` 保持兼容 DTO，只列 active 成员，角色／撤会话操作拒绝 inactive；管理员另用计划新增 GET `/api/memberships?status=all` 查看最小历史成员状态。
成员摘要固定 `{id,householdId,memberId,memberName,householdRole,state,revision}`；`id` 是随机 membership ID，非私人 owner，非个人账号 ID。
离开、绑定和接受邀请的有限回执同时可由本人账户查询；未绑定者先完成明确绑定再自助退出，避免撤销唯一登录后无法核对。管理员移除未绑定成员由原管理员核对，不借已撤 Cookie 授权。
首次邀请回复丢失时，回执不恢复原 token；管理员可明确撤销该邀请再创建新邀请，不能因为页面没 token 自动重复创建。

## 6. 多库提交、撤权和未知结果

- 平台目录不是权限缓存：访问和发会话都核户内 membership；个人会话、原家庭、目标家庭的身份不可混用。库不可读返回可恢复错误，不创建空库或 fallback 到 default。
- 跨库操作先持久化平台 pending 意图，再在目标户同一写事务提交 membership／users／邀请消费／户内回执，最后完成目录和有限回执；每步以相同 requestId 对账。
- 不假设 WAL 下两库提交原子。目标户未提交可拒绝／结束；已提交后仅修复索引、完成回执，不再次创建成员或重新消费邀请。服务重启须能从持久步骤核对。
- 目录未完成时不得提前签发有效目标会话；GET 核对不触发业务写。单独显式恢复接口 POST `/api/account/operations/<requestId>/resume` 只完成已证实提交的收尾，不能自动重做未提交操作。
- 多库锁顺序固定 platform → household，禁止反向嵌套；网络／提供方调用不持锁。最终户内提交前核捕获会话、membership、管理员和版本；并发接受只允许一个结果。
- 停用在同一户内事务更新 membership revision、递增 users.auth_version、撤销目标会话与认证代次、记录审计；登录、OAuth完成、媒体票据和各业务鉴权都拒绝 inactive。
- 同户 worker 在取得令牌及最终保存前检查 owner active；待同步／待发布暂停且不转移owner。已有云数据不自动删除，已完成外部动作不声称撤回；重新加入后也不自动恢复云写队列。
- 未知结果保留原 requestId/意图，只读查询；没有回执不能断言失败、自动新建 ID 或自动重发。已知完成后 fresh 读取当前状态，旧回执不装作当前权限。
- 前端身份包含个人 session代次＋household/member/auth_version/membershipRevision/CSRF；切换、hidden、blur、offline、unmount 清私有显示并丢弃迟到结果，dirty／unknown 必须先明确处理。

## 7. 文件职责与迁移分期

后端负责人新增 `household_memberships.py`（户内关系／邀请／事务）和 `personal_accounts.py`（个人认证／目录／协调）；注册接口由 Root 独占接线，不复制业务文件。
后端与 Root 先约定 session capture/current 的扩展；`app.py`、`household_spaces.py`、`member_sessions.py`、`household_members.py` 同属安全接缝，明确单一作者后并行。
UI 新增个人账户／家庭选择面板及模型，扩展 `HouseholdMembersPanel.tsx`；Root 独占 `LoginScreen.tsx`、`HouseholdApp.tsx`、household provider/types 的身份和导航接线。
必须改造的已核硬编码：`app.check_owner`；`cloud_accounts.py` scope；`finance_baseline.py` owner；`home_assistant.py` 成员提示；`accounts.ts/AccountsScreen`、`devices.ts/DevicesScreen`、`tv.ts`；统一从当前户有效成员取得可选值。
退户旧记录仍按保留 users 解释显示；私人 owner 必须等于当前有效成员，不得因为全局 account_id 相同跨户读取。旅行／清单原成员引用不静默替换。
迁移 M1：加个人账户库表与户内 membership／邀请／操作表，给旧 users 补 active 未绑定关系；校验原表、owner、密码、角色、registry、云与媒体原件，重启不重置。
迁移 M2：启用注册／明确绑定／邀请加入；只有动态成员校验、UI读取及 worker 拒绝 inactive 全部通过才开放第三人入口，不发布“能加入却无法协作”的半成品。
迁移 M3：启用退出／移除及多家庭切换的完整闭环；目录修复和未知恢复已验。M1–M3 可分开发提交，但用户入口须按可用闭环一起交付。
迁移/备份负责人另建精确 DDL checker、版本清单、停写全组备份与恢复演练；新表数由最终DDL实际核定，不能沿用 58→58/no-DDL 发布器。
停用引入权限投影变化；导出、备份、worker、恢复与运行文件白名单必须包含新增状态／表。回滚不能直接运行会忽略 inactive 的旧应用。

## 8. 必需的本地端到端验收

1. 带非空私人财务、0/null估值、照片、云绑定和原回执的两户迁移；旧 member1/member2、合法角色和密码保持，重启结果一致。
2. 旧成员注册并明确绑定；同名两户不自动合并，错误另一户密码／冒认 owner／已绑定身份失败且无私有数据变更。
3. admin 创建邀请码→第三人注册→核对家庭与普通角色→加入→分配待办／旅行准备并完成；邀请码重放、撤销、过期、发起人失权均有实际拒绝。
4. 同一个人独立证明第二户旧身份，再从所属家庭列表切换；两户同对象 ID 内容不同，旧页面／图片迟到不回显，未保存和未知操作挡切换。
5. 本人退出与 admin 移除后，旧 cookie、密码登录、OAuth收尾、媒体票据和 worker 后续工作均受限；其他家庭／其他人的数据和权限不变，最后 admin 不能退出。
6. 新邀请明确恢复原成员 ID，原私人数据只还给原绑定本人，不恢复旧 admin 或云写队列；不能把停用位置转给新账号。
7. 各跨库提交点中断／重启、并发邀请接受、实际提交后丢响应：GET不是重放，原操作可核对，显式收尾不产生第二成员或第二次授权。
8. 320／390／1280／1920 浅深色、44px与键盘；匿名／TV／普通成员越权、双户、CSRF、版本及身份切换；真实临时 Flask/SQLite/浏览器，无成功业务 DTO mock。

上述为待实施验收清单，不是通过记录；个人真实环境、云端新操作和实体设备不由本设计宣称完成。
