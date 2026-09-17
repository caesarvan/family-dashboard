# 家庭成员管理首批契约

基线 `eda8632719a6f1a3202e6d5c2a9a986329c9c287`。本批增加当前家庭的基础角色与管理员退出另一成员浏览器的能力，不扩展成员数量、全局账号或家庭加入／退出。现有两位成员继续共同管理。

## 权限与迁移

- 保持 `actor.role=member|tv` 和现有 `/me` 契约；新增数据库 `users.household_role`，只允许 `admin|member`。不把家庭角色替换为现有认证 role。
- 缺列时在串行事务内新增列，缺省 `member`，将已存在的两位家庭成员一次性设为 `admin`。新家庭首次初始化后的两位成员同样成为管理员。已存在列时不得重置角色，不调整原密码、会话、云绑定或私人数据。
- 这是 schema 变化，即使表数仍为 58，也必须另有迁移与旧数据保全检查，不能沿用本轮旅行导入的无迁移发布工具。
- 管理员与普通成员都可查看家庭成员列表。只有当前仍有效的管理员可变更另一成员角色、退出其浏览器；首批不允许操作本人。最后一位管理员不可被移除。
- 家庭角色不扩大私人财务、照片、日程、云账户或导出权限，不改变普通成员已有的共同任务／旅行／电视能力。
- 平台“邀请创建新家庭”继续按原平台权限控制，不误作邀请加入当前家庭。

## API（本批新增）

全部沿用当前家庭会话与同源 CSRF。匿名 401，电视 403；不接受 household/owner 参数选择其他家庭。新请求事务内重新检查实际会话、当前管理员角色、目标版本及约束。

`GET /api/members`：

```json
{"currentMemberId":"member1","members":[{"id":"member1","name":"我","householdRole":"admin","authVersion":1,"activeSessionCount":1,"capabilities":{"changeRole":false,"revokeSessions":false}},{"id":"member2","name":"伴侣","householdRole":"admin","authVersion":1,"activeSessionCount":2,"capabilities":{"changeRole":true,"revokeSessions":true}}]}
```

`activeSessionCount` 对管理员为当前有效会话整数数量，对普通成员固定 `null`；不是物理设备数或在线人数。不返回 Cookie、CSRF、账户邮箱、原始 UA、IP 或第三方令牌。能力由服务端给出，UI 隐藏不能代替鉴权。

`POST /api/members/<id>/revoke-sessions`，体 `{"expectedAuthVersion":1}`。

`PATCH /api/members/<id>/role`，体 `{"expectedAuthVersion":1,"householdRole":"member"}`。

共同成功结构：`{"ok":true,"member":{"id":"member2","householdRole":"member","authVersion":2},"revoked":2}`。撤销请求的 householdRole 保持实际原角色。版本冲突 409；目标不存在 404；非法输入 400；不允许的角色／本人操作 403。角色未变化的 PATCH 返回 409，UI 不提供相同角色提交。

两种成功操作均在同一事务递增目标 auth_version、撤销目标有效会话、推进相关浏览器认证代次，记录不含隐私内容的审计。角色修改也要求目标重新登录。会话数量为零时，明确执行撤销仍增加版本，以拒绝未登记旧 Cookie 或在途认证。目标可以随后使用自己的凭据重新登录；该操作不是封禁、删除成员或家庭退出。

## 界面与恢复

「更多 → 家庭与成员」打开 Expo 原生风格面板，列表简明显示姓名、本人标记、家庭角色。管理员可在另一成员卡片选择「退出所有浏览器」或「调整角色」，确认中写明目标及“需要重新登录”。不显示伙伴设备详情，不混入电视管理。现有本人会话接口保持本人专属。

使用完整当前身份、fresh 会话与 epoch 围栏；hidden/blur/offline/身份变化隐藏旧数据和操作，返回重新确认。写入前后身份核验。导航锁定未决确认／保存／未知结果；不把载荷、权限或目标放入持久化浏览器存储。

发生已发送请求结果未知时，保留原目标与预期版本，仅允许用户明确只读重新读取当前成员列表；不自动再次 POST/PATCH，不从当前版本推断本次操作成功。告知“当前状态已更新，本次操作结果仍无法确认”，明确结束核对后才可重新选择操作并以新预期版本确认。成功回复后也重新读取当前状态，不能用迟到成功回执覆盖当前角色。此批没有持久化操作回执接口。

## 分工与验收

- 后端：`household-members-api` 分支独占 `household_members.py`、`tests/test_household_members.py`、`docs/HOUSEHOLD-MEMBERS.md`；导出 `register_members(app, db, Problem, body, require_member, audit)`，初始化在注册时完成，复用 `app.extensions['member_sessions']`。
- UI：`household-members-ui` 分支独占 `HouseholdMembersPanel.tsx`、`householdMembers.ts`、Node 模型测试和使用文档；props `{onBack,onPendingChange?}`。接口如需改动先协调，不自行写 app 接线。
- Root：`household-members-wiring` 负责 app 注册、Expo 路由与加载顺序、Docker／运行白名单；后续另立迁移验证与发布任务。

必要验证：两位旧成员共同管理员且重启不重置；两户、匿名、TV、普通成员服务端拒绝管理；旧 Cookie／版本及在途管理员操作受限，目标可重新登录；角色并发和最后管理员保护；丢失回复只读恢复且无第二次写入；身份和前后台晚回调不回显。证明私人数据与云绑定未扩大或删除。不得宣称撤销会中断所有已开始普通业务请求或撤回外部已完成操作。
