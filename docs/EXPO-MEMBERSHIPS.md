# Expo 个人账户与家庭成员关系

本文件记录独立前端候选，基线 `8e6a9954aec21ac69cf0c9d33817f631c4a789f4`。尚未组合验证、迁移或部署。
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
