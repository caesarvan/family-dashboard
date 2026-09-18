# Expo 个人账户与家庭成员关系

本文的用户流程已随 [R3 成员发布](MEMBERSHIPS-RELEASE-R3.md) 上线。下方分支验证与“候选”说明保留当时范围，原独立前端基线为 `8e6a9954aec21ac69cf0c9d33817f631c4a789f4`；组合及生产身份以发布记录为准。
后端与 Root 接线按 [成员关系设计](HOUSEHOLD-MEMBERSHIP-DESIGN.md) 实施；本分支不修改后端、全局导航、共享类型或 provider。

## 用户流程

- “家庭与成员”中可打开“我的家庭账户”“邀请与加入家庭”“管理成员关系”。Root 另负责登录页及更多页入口。
- 旧成员先登录原家庭，验证自己的原密码后创建个人账户；已有个人账户可直接登录。再次输入原家庭密码，核对个人账号、家庭名称及成员名，明确绑定。
- 管理员创建邀请码，复制邀请码并同时告知家庭地址简称。邀请只授予普通成员；原邀请码只显示一次，可明确撤销未使用邀请。
- 受邀者输入家庭地址简称和邀请码，核对家庭名称。创建或登录个人账户后需重新输入并核对邀请，再明确加入；不会自动切换家庭。
- 在“我的家庭”选择已加入家庭，明确确认后进入。目录里暂时不可用的家庭会单独提示，不当作已经退出。
- 管理员可以移除另一位成员；已绑定本人可明确退出。最后管理员由服务端拒绝退出。历史数据保留；再次加入仍需有效邀请，不自动恢复旧管理员权限。

## 组件接线

三个组件均默认导出，使用现有 Paper 主题、密度与最小 44px 按钮，不增加依赖。

| 组件 | props |
|---|---|
| `PersonalAccountPanel` | `onBack`, `onPendingChange?`, `onIdentityChanged?: () => void \| Promise<void>` |
| `MembershipInvitationsPanel` | `onBack`, `onPendingChange?`, `onJoined?: (membership) => void \| Promise<void>` |
| `MembershipManagementPanel` | `onBack`, `onPendingChange?`, `onLeft?: () => void \| Promise<void>` |

`onPendingChange` 覆盖未提交输入、确认内容、在途及未知操作。父导航仍须阻止未经处理的离开。
成功回调只在有原操作结果并完成 fresh 当前读取后触发；父层仍须核当前身份/挂载状态。provider `refresh()` 仅同步共享导航，不能作为写成功证明。
`HouseholdMembersPanel` 仅 wrapper 新增三子页，原角色调整和撤会话 workspace 保持。

主要 testID：`personal-account-panel`、`membership-invitations-panel`、`membership-management-panel`、`membership-operation`、`membership-join-preview`、`membership-invitation-secret`。
主要无障碍标签：个人账号／个人密码／当前家庭密码／家庭地址简称／邀请码；验证当前家庭身份、创建个人账户、绑定这个身份、核对邀请、加入这个家庭、创建邀请码、复制邀请码。
动态操作标签带家庭或成员名称；撤销邀请以编号末六位区分。共用恢复操作为“查询原操作”“继续核对原操作”“用原操作重试”“读取当前状态”“稍后核对”。

## 请求与恢复边界

### 个人账户恢复增量（候选）

当前家庭入口损坏或家庭库明确不可用时，面板显示“当前家庭暂不可用”，仍允许个人登录、读取“我的家庭”及明确切换到可用家庭；不会把不可用当成匿名成员或已经退出。
只接受 `/api/me` 已知家庭恢复错误的精确状态、文案与 `/space/home` 恢复地址。一般网络失败、401/403、其他服务错误及无效 JSON 仍停止读取。个人 `/api/account/me` 前后身份、代次、CSRF 保持完整检查；成功切换还必须读到目标家庭的派生成员身份。
成员写入、原成员请求重试、旧身份验证及成员操作查询仍要求真实成员与成员 CSRF。家庭不可用时保留原核对编号并禁用对应成员动作；个人原操作仍按原编号只读查询，不把历史回执当当前家庭，也不自动重发。
本增量的模型／真实 Flask 合成恢复用例见 `tests/test_expo_membership_recovery.mjs` 与专属 Python fixture；其中业务响应来自真实临时库和真实 cookie，传输／错误拒绝另有明确合成控制。实际浏览器及发布由后续组合验收，不由这些模型检查替代。
修订后实际 34/34 通过：原 26 项，加五条真实恢复链与三项错误／身份控制；真实恢复覆盖坏路由、未知家庭、默认及子家庭缺库，以及已提交切换丢回复后按原编号读取。后端固定为组合 `bcfabc7899868b4c61af5f3dfd36d48a4c997f18`，前端与被测后端各 791 项执行前后相同。原件 `test-results/account-recovery-final-r1/result.json` SHA-256 `4630f83b141d2ae9f077223a2068bc9bb817e68eec809c072d0eddaaa056bf03`。两套完整 TypeScript 配置均 0 诊断，无安装／发射；Node 实验类型转换与模块警告保留。
首轮 0/3 原件保留：坏路由和缺子库直接阻断个人面板；默认库缺失另暴露后端未处理异常，最初桥接关闭的 EPIPE 遮住了异常，补充诊断取得真实栈。默认库错误与冷启动页面修复由独立 Root 接线提供，本前端分支未复制或修改后端。测试默认使用本仓库；隔离依赖验证可显式设置 `MEMBERSHIP_RECOVERY_SOURCE` 和精确 `MEMBERSHIP_RECOVERY_HEAD`，Python 沿用 `MEMBERSHIP_TEST_PYTHON`／仓库环境探测。

- 精确路径、方法和字段 allowlist，不接受客户端 owner/accountId 选择器。注册、登录、邀请检查等均沿既有设计的实际 HTTP 合同。
- 个人路由主 CSRF 属于个人会话；验证旧身份另带成员 CSRF。户内路由主 CSRF 属于成员会话；绑定与退出另带个人 CSRF，不混用。
- 全部请求使用同源凭据、`no-store`、拒绝重定向、15 秒期限、512KB 流式上限、UTF-8/JSON 校验；成员／邀请历史最多接受 1000 行。历史接口目前无分页，超过上限明确报错，不声称已覆盖完整历史。
- fresh 核个人账户、authVersion、浏览器代次、CSRF，以及家庭／成员／auth_version／membershipRevision／成员 CSRF。登录、注册、切换和注销须核恰好下一代且 CSRF 已轮换；并发身份变化不安装迟到结果。
- 原本地成员 Cookie 可在个人注销后保留；派生成员 Cookie 不可保留。绑定保持原本地成员 Cookie，仅核新关系版本；退出保留个人登录供回执恢复。
- 写前生成安全随机编号并记录原操作。网络中断、畸形或大响应、后验身份读取失败均不推断未提交；GET 未找到不是取消或失败证据。
- invite/revoke/remove 的原请求体只保留版本和编号等必要字段；用户明确“用原操作重试”才 POST 原路由、原编号、原请求，不换编号。回执不恢复邀请码，需明确撤销旧邀请后再创建。
- 跨库操作只 GET 核对，pending 时可明确 resume 收尾；not_committed 才允许结束核对并重新选择。历史回执不会直接充当当前成员列表或权限。
- 明确 4xx 拒绝且后验身份相同可解除提交锁；409 提示 fresh 核对。已知成功后读取失败保留完成回执，不能再次写。
- “稍后核对”只结束本地面板，先提示保存原编号，不声称取消。之后可展开“按编号查询原操作”，按本人当前会话读取；不会自动重发。

密码、邀请令牌和短期资格只存内存，不放 URL/localStorage/日志。失焦、隐藏、离线、pagehide、路由离开清输入与私有显示、丢弃迟到响应；仅同主体不含秘密的操作编号及必要原意图可保留。身份变化清不属于当前主体的句柄。

## 本分支验证范围

`tests/test_expo_memberships.mjs` 是客户端 DTO、精确会话转换、双 CSRF、原操作状态、身份围栏和有界传输测试；合成 DTO/传输桩不作为真实 API 成功证据。
本地首轮 20 项通过；最终 R3 23/23 通过，另含家庭名称同户绑定、resume 不接受替代意图、派生成员与个人代次一致。两个完整 TypeScript 配置均 0 诊断；均只读映射现有依赖，无安装、发射或构建。
原件 `test-results/membership-final-r3/result.json` SHA-256 为 `b6ce805937e42392c896b7c3fcad8bdce3dac55a4ecde1a0a6b4ee04877477fe`；Node输出 `1a811b8a2fd63d39c6e642c01c8601dedaed093f15dd74924b56eb927f16e2c9`，types输出 `7ffa1e482bf96b8330bcfcdd7f172639ee6fe7c06efa3c32f7fd8de339e08659`。列入源码执行前后相同。最终 UI 两处本地返回/提示修正另复核类型，不重复未变的 Node 模型测试。
首轮 TypeScript 应用配置发现两处模型类型错误（扩展名和联合类型收窄），测试配置通过；原失败输出保留，修复后重新执行两配置。
真实 Flask/SQLite DTO、第三人加入与分配事项、跨户切换、撤权、故障恢复及四宽浅深色浏览器验收须待 Root 组合冻结。本文不宣称这些已通过，也不宣称真实个人账户、云端或实体电视验收。

## 非作者审查后的契约修正

邀请状态按实际领域 DTO 使用 `pending`，个人账号接受完整 `[a-z0-9._-]{3,64}`。写请求返回 `pending`／`not_committed` 操作封套时保留原编号，按状态核对，不重复提交；匿名注册仅在已确认 `not_committed` 时可结束本地核对。
修正后实际 26/26：25 项客户端测试及 1 项固定领域真实 DTO 测试。新增 `tests/test_expo_memberships_real_dto.mjs` 使用固定领域提交 `754d2e1552c8953b9d490df246d1328bdf3abf43`、真实临时应用 SQLite，实际调用创建／列表／重放／撤销／过期／失效邀请；禁用网络，关闭连接并清理临时库。这是领域 DTO 验证，不等同 HTTP 或浏览器验收。
两个完整 TypeScript 配置再次 0 诊断，只读依赖、无发射。原件 `test-results/membership-review-fix-r1/result.json` SHA-256 为 `60ac9965c1587bea9d80e2d6306e749e408b1663ceac8e5f61c5bf7cfd4a9c19`；Node 的实验类型转换及模块类型警告保留在输出中。上述 R3 为修正前记录，未改报为最终结果。

真实 DTO 测试默认从当前仓库读取领域模块；Python 优先采用 `MEMBERSHIP_TEST_PYTHON`、仓库 `.venv`，其次探测系统 Python。只有显式指定 `MEMBERSHIP_DOMAIN_ROOT` 的独立审查运行才校验原固定外部提交。此可移植性修订后独立领域 1/1 再次通过，原件 `test-results/membership-test-portability-r1/result.json` SHA-256 `99eb396c494b78f25a32e3818925a1d4ed8338815d5f14c8e8043fdee839d218`；当前 UI 作者树尚不含领域模块，默认仓库模式待组合后执行，未重复未改的 25 项客户端测试。
