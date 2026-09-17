# Expo 家庭与成员（候选）

本批基线 `eda8632719a6f1a3202e6d5c2a9a986329c9c287`，新增面板与客户端模型，尚未组合验收或部署。现有两位成员迁移为共同管理员；家庭角色与成员／电视认证身份分开。本人登录设备仍使用既有入口，本面板不重建它。

## 使用流程

从「更多 → 家庭与成员」查看姓名、本人标记和家庭角色。管理员可看到有效浏览器会话数量；数量不是物理设备数或在线人数。

- **调整角色**：在另一成员卡片打开确认，核对姓名与修改前后的角色，再点击「确认调整角色」。角色变化会要求对方当前浏览器重新登录。
- **退出所有浏览器**：核对目标后点击「确认退出所有浏览器」。即使当前显示零个会话，也可明确执行；对方仍能随后用自己的凭据重新登录。
- 普通成员可查看成员角色，不显示管理操作或伴侣会话数量。不能操作本人，不删除成员，也不改变私人数据、云账户或电视许可。

两种操作均只发送当前预期版本及必要的新角色，不发送家庭选择、owner 或其他个人字段。成功后重新读取当前成员列表；读回失败时隐藏旧列表和操作，只允许重新读取，不再次提交刚才的写入。

## 不确定结果与生命周期

发出请求后网络中断、5xx、畸形成功响应或后置身份核验失败，均不能直接判断保存结果。面板保留原目标和预期版本，仅允许「读取当前成员状态」；此接口没有操作回执，当前状态不是本次操作成功的证明。

明确只读核对成功后，用户可选择「结束本次核对」。这一操作只结束本地状态，不发送写请求；随后若要再次操作，须按当前版本重新选择并确认。每次前后台切换都会使以前的核对凭据失效。409 等经后置身份确认的明确拒绝要求重新读取，不自动采用新版本重发。

确认、请求中和未知结果通过 `onPendingChange` 保护导航。取消尚未提交的确认后可返回；未知结果须先核对并明确结束。隐藏、浏览器失焦、页面离开、离线与导航失焦立即隐藏姓名、角色及操作，取消迟到回调。同一完整会话的未决意图只在组件内存保留；恢复前重新核对身份。身份变化或卸载清除，不使用 localStorage 或 URL 存储数据。

## 开发合同与稳定控件

组件：`frontend/src/components/HouseholdMembersPanel.tsx`，props `{onBack:()=>void,onPendingChange?:(pending:boolean)=>void}`。认证沿 `role/householdId/id/auth_version/csrf` 完整围栏，家庭角色来自实际 `GET /api/members`。Root 负责菜单、导航保护、后端注册与迁移，不属于此作者分支。

模型：`frontend/src/lib/householdMembers.ts`。导出 `readMembers`、`memberIntent`、`intentStillAllowed`、`readMemberResult`、`canEndMemberReview`、`MembersFence`、`checkedMemberWrite`、`membersRequest` 及对应类型。固定同源请求仅允许 `/me`、`/members` 和目标 `/role`、`/revoke-sessions`；15 秒超时、128,000 字节 JSON 响应上限、拒绝重定向与错误类型。

| 功能 | accessible label / testID |
|---|---|
| 面板／当前列表／未知区 | `household-members-panel` / `members-current` / `members-unknown` |
| 成员卡片 | `household-member-<id>` |
| 操作 | `调整角色：<姓名>` / `退出所有浏览器：<姓名>` |
| 确认标题 | `调整成员角色？` / `退出所有浏览器？` |
| 确认按钮 | `确认调整角色` / `确认退出所有浏览器` / `取消` |
| 只读刷新 | `刷新成员列表` / `重新读取成员列表` / `读取当前成员状态` |
| 明确结束 | `结束本次核对`；仅本次身份与生命周期内明确读回成功后出现 |
| 返回／隐藏时取消确认 | `返回更多` / `取消待确认操作` |

按钮声明至少 44px 操作区，主题和间距复用 Paper 与 `useDisplayDensity`。实际四宽、浅深主题、键盘、窗口失焦及重挂时序待组合浏览器验证，源码不能代替视觉验收。

## 验证范围

`tests/test_expo_household_members.mjs` 是有界 DTO、CAS 意图、同身份生命周期、未知核对凭据及请求安全的纯客户端测试。文件中的虚构合同样例和 fetch 协议单元替身不代表真实 API 通过；后端固定组合的真实 Flask DTO 与浏览器流程另行验证。

本地已实际执行 13 项客户端检查，13 通过、0 失败／跳过。最终窄范围 strict TypeScript 为 0 diagnostics，结果 `test-results/members-ui-types-r2/types-result.json` SHA `a64e30b3a2eb08cd284acbf6bc7d0b90622ad349e0ec35fd7a8f89f202a5d5f6`。纯模型原件 `test-results/members-ui-r1/result.json` SHA `e0914d389b9d2f7ff2c99e2ff0f92d847b700f8c92212fbe248ac2ff18040228`；其中面板为增加初次挂载焦点检查前的版本，模型与测试字节保持。未安装依赖，使用已有物理依赖只读类型解析；这不代替 Root 完整应用类型检查或浏览器验收。

重点组合验收：两成员共同管理员；普通成员／匿名／TV／跨户直接调用管理接口被拒；角色变更与撤销真实旧 Cookie 失效但能重新登录；丢失已提交响应只读恢复且零第二次写入；成功后 GET 失败隐藏旧操作；hidden/offline/身份变化不回显迟到内容；私人财务、照片、云绑定及电视能力不扩大。既有普通业务在途请求与真实外部操作不在“即时撤回”承诺内。

相关实现：[成员会话](../member_sessions.py)、[既有会话合同](MEMBER-SESSIONS.md)、[客户端模型测试](../tests/test_expo_household_members.mjs)。家庭角色新增列属于 schema 迁移，不能按无迁移发布。
