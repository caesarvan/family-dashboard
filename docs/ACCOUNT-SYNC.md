# Microsoft / Google 账号与同步

家庭看板入口：[打开看板](https://home.caesarcharles.world/)。可在手机浏览器打开的逐步指南：[账号接入设置](https://home.caesarcharles.world/static/account-setup.html)。本方案采用服务器网页授权，首次由管理员注册两个应用，每位成员随后授权自己的账号。

**当前部署状态（2026-09-14）：Microsoft / Google 已配置，已有实际绑定和所选来源同步成功记录。** 下方注册步骤供新环境或后续维护使用，不要在现有服务器重复初始化。配置已填写、账号已绑定、来源已选择、最近同步成功是不同状态，后续新增来源仍逐项验收，详见 [验收记录](VALIDATION.md)。

**2026-09-15 01:10 发布增量：** Google Tasks 可与 Microsoft To Do 一样被账户拥有者明确设为唯一家庭主清单；旅行/助理/本地待办可逐项预览确认连接并持续同步。双平台模拟 HTTP 与临时浏览器验收已完成，真实账号新增发布写入仍未验收；本次公网浏览器被本机组织策略阻断。接口与失败边界见 [待办发布](TASK-PUBLISH.md)。

## 使用方式与共享范围

新版入口为“账户菜单 / 更多 → 账户与自动同步”（`/app/connections`），使用当前 Expo 官网的白底、黑色按钮、浅灰卡片。连接、选择来源、核对共享范围、查看逐来源同步结果和断开绑定在同一页完成；完整操作见 [Expo 账户界面](EXPO-ACCOUNTS.md)。本段描述本次候选功能，实际发布与验证以 [验收记录](VALIDATION.md) 为准。

1. 首次用原有 member1 / member2 家庭账号登录，在“账户与自动同步”绑定 Microsoft 或 Google；经典页原设置入口仍可使用。
2. 跳转至服务商登录，核对账号与权限后授权，再回到看板。
3. 账号本人选择具体日历、任务清单和日程归属。**只有明确选择的来源才向伴侣和已配对电视共享**，所选日历完整标题、地点按家庭约定展示。
4. 之后可从登录页使用已绑定平台进入同一家庭身份。未绑定的外部账号不能自行注册或查看家庭数据；原密码登录保留。

账号按 provider 和服务商确认的稳定 subject 匹配，不按相同邮箱自动合并。每位成员最多绑定 4 个账号，可以同时连接两个平台。个人账户、收入和消费明细仅本人可见；经确认的资产与负债汇总可共享，电视始终只读。

来源选择是完整替换。新版会保留未保存的输入，若其他窗口已修改选择，则显示最新范围，须明确核对后才能继续保存。暂未发现的旧来源会保留并标识，不能静默取消。网络中断后先读取实际保存结果，不自动重复提交。账户已连接、来源已选择、等待后台检查、最近成功和需要重新授权分别显示；没有选择来源时不会声称已安排同步。版本与旧客户端差异见 [来源版本](ACCOUNT-SOURCE-VERSION.md)。

| 连接来源 | 看板中的行为 |
|---|---|
| Outlook Calendar / Google Calendar | 读取选中日历；创建、改期、取消在原日历操作。 |
| Microsoft To Do | 可设唯一家庭主清单，也可作为附加来源；新增、完成及恢复写回目标清单。本地待办连接须逐项确认。 |
| Google Tasks | 可作附加来源，也可由账户拥有者明确设为唯一家庭主清单。原生 Google 清单共享与看板家庭授权是不同概念，不自动复制到 Microsoft。 |
| Apple 日历客户端 | 底层若是 Outlook 或 Google，连接实际账号；纯 iCloud / Apple 提醒事项后续接入。 |

已有本地待办不自动迁入云清单。原有云端镜像任务的详情、重复规则和删除在原应用管理；新的本地待办发布绑定支持标题/日期/备注/完成持续同步及冲突确认。看板家庭共享不等于 Google Tasks 原生列表共享。两人共有的同一来源不要重复连接为两份展示；更换家庭主清单前，由当前持有者取消旧选择。

本版由服务器自动检查：任务约每 30 秒、日历约每 60 秒；页面约每 10 秒读取服务器。**这是自动轮询同步，尚未启用第三方变更推送。** 网络、限流会延长等待；失败后最多退避 15 分钟再尝试，保留上次成功数据并显示错误。每个来源分页全部成功后才发布新快照。

日历窗口为当前 UTC 时刻前 30 天至后 365 天，重复事件使用服务商展开的实例。单来源最多 2,500 条记录，总记录最多 20,000；每个账号最多选 12 个来源，全家最多 24 个来源。超限或部分读取失败不当作空数据清除。真实账号删除、重复日程例外、令牌刷新及端到端等待，需授权后验收。

## 一、注册 Microsoft 应用

进入 [Microsoft Entra 管理中心](https://entra.microsoft.com/)，使用有权在目标 Entra 租户注册应用的账号。若提示没有目录或权限，先解决租户访问与注册权限。个人 Microsoft 账号可用于看板登录，不代表自动拥有注册应用权限。[官方注册说明](https://learn.microsoft.com/en-us/graph/auth-register-app-v2)

“应用注册 / App registrations → 新注册 / New registration”：

| 字段 | 填写值 |
|---|---|
| 名称 | 家庭看板 |
| 支持的账户类型 | 任何组织目录中的账户和个人 Microsoft 账户 / Accounts in any organizational directory and personal Microsoft accounts |
| 重定向平台 | Web |
| 重定向 URI | https://home.caesarcharles.world/auth/microsoft/callback |

概述页记录 **Application (client) ID / 应用程序（客户端）ID**。Object ID、Directory (tenant) ID 不是 client ID。应用使用 common 入口，与上述账户类型匹配。[账户类型与 authority 对照](https://learn.microsoft.com/en-us/entra/identity-platform/msal-client-application-configuration)

“API 权限 → 添加权限 → Microsoft Graph → 委托的权限 / Delegated permissions”添加或保留：

```text
User.Read
Calendars.Read
Calendars.Read.Shared
Tasks.ReadWrite
openid
profile
email
offline_access
```

登录只请求基础身份范围；绑定同步申请日历读取、任务读写、离线访问。Calendars.Read.Shared 是用于额外共享日历的权限；缺少它不会阻止个人日历和 To Do 绑定。微软可能不在个人账号的返回范围中列出该权限，基本接入检查 User.Read、Calendars.Read、Tasks.ReadWrite 及刷新令牌。具体能访问的共享日历由微软 API 决定，不能仅凭成功绑定就宣称已获得共享日历权限。[官方权限参考](https://learn.microsoft.com/en-us/graph/permissions-reference)

“证书和密码 / Certificates & secrets → 客户端密码 / Client secrets → 新建客户端密码”：名称可填 family-dashboard-server，选择适合维护周期的到期时间并记录到期日。创建后立即保存 **Value / 值**，不要使用 Secret ID；值离开页面后不会再次显示。[官方客户端凭证说明](https://learn.microsoft.com/en-us/graph/auth-register-app-v2#add-credentials)

“身份验证 / Authentication”保留网页授权配置。本版不使用设备授权码，无需启用“允许公共客户端流”或隐式授权的 access token / ID token 复选框。采用授权码和 PKCE，通过服务器交换令牌。[官方授权码流程](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)

## 二、注册 Google 应用

进入 [Google Cloud Console](https://console.cloud.google.com/)，创建或选择项目。“API 和服务 → 库”分别启用 [Google Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com) 和 [Google Tasks API](https://console.cloud.google.com/apis/library/tasks.googleapis.com)。

在 [Google Auth Platform](https://console.cloud.google.com/auth/overview) 填写：

| 页面 / 字段 | 填写值 |
|---|---|
| Branding / 应用名称 | 家庭看板 |
| 支持邮箱、开发者联系邮箱 | 你能接收邮件的邮箱 |
| 应用首页（要求填写时） | https://home.caesarcharles.world/ |
| Authorized domains / 已获授权的网域 | caesarcharles.world，不带协议或 home. |
| Audience / 用户类型 | External，适用于两位个人 Google 账号 |
| 初次发布状态 | Testing，先验收两人连接 |
| Test users / 测试用户 | 添加你和伴侣实际要授权的两个 Google 账号 |

控制台若要求验证域名所有权，使用你管理的 caesarcharles.world 按提示完成。页面布局如有变化，从 Branding、Audience、Data Access、Clients 分别进入。[官方设置入口说明](https://developers.google.com/workspace/calendar/api/quickstart/python#configure_the_oauth_consent_screen)

Data Access / 数据访问配置身份与同步范围：

```text
openid
https://www.googleapis.com/auth/userinfo.email
https://www.googleapis.com/auth/userinfo.profile
https://www.googleapis.com/auth/calendar.readonly
https://www.googleapis.com/auth/tasks
```

登录使用基础身份范围，绑定同步申请日历只读、任务读写与离线访问。[Calendar 范围](https://developers.google.com/workspace/calendar/api/auth)、[Tasks 范围](https://developers.google.com/workspace/tasks/auth)

“Clients / 客户端 → Create client / 创建客户端”：

| 字段 | 填写值 |
|---|---|
| Application type | Web application |
| 名称 | 家庭看板服务器 |
| Authorized redirect URIs | https://home.caesarcharles.world/auth/google/callback |
| Authorized JavaScript origins | 服务器授权不需要；若填写，使用 https://home.caesarcharles.world |

创建后安全保存 Client ID 和 Client secret，下载的凭证 JSON 只放私人位置。Google 网页回调应符合 HTTPS 等规则，公网 IP 不能替代当前域名（localhost 例外）。[Google 网页 OAuth 官方说明](https://developers.google.com/identity/protocols/oauth2/web-server)

**长期使用前处理 Testing 状态。** External + Testing 且申请 Calendar / Tasks 范围时，刷新令牌在 7 天后到期，需要重新授权；仅基础身份范围的例外不适用于本项目的同步。[官方到期规则](https://developers.google.com/identity/protocols/oauth2#expiration)

先验收两位成员，再在 Audience 按控制台流程切换为 In production 并重新连接。两位已知使用者的个人用途可能符合验证例外；是否需要域名、品牌或范围验证，以控制台要求和实际用途为准。发布不代表令牌永久有效，授权撤销或组织策略仍会影响连接。以后向公众开放时须重新评估验证要求。[个人用途例外](https://developers.google.com/identity/protocols/oauth2/policies#use-separate-projects)、[应用状态与限制](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview)

## 三、安全写入服务器配置

不要在聊天里发送 client secret、凭证 JSON、个人密码或令牌，也不要把 secret 放进 SSH 命令参数。管理员在自己的电脑终端输入：

```powershell
ssh -t racknerd
```

进入服务器后执行。可先完成一个平台，稍后添加另一个。

```bash
cd /opt/family-dashboard
python3 deploy/configure-oauth.py --provider microsoft
python3 deploy/configure-oauth.py --provider google
python3 deploy/configure-oauth.py --check
```

按提示填写 client ID，并两次粘贴 secret 的 **Value**。secret 输入不显示字符是正常现象。助手仅修改 PUBLIC_ORIGIN 与所选平台两项配置，保留原家庭密码、加密密钥及另一平台配置。原子写入前生成带时间戳的原配置备份，原文件和备份权限均为 0600。--check 仅报告配置是否填写，不回显值，也不代表授权成功。

维护的字段：

```text
PUBLIC_ORIGIN
MICROSOFT_CLIENT_ID
MICROSOFT_CLIENT_SECRET
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
```

完成后让容器读取新环境变量：

```bash
docker compose up -d --force-recreate app sync web
docker compose ps
curl --fail --silent --show-error https://home.caesarcharles.world/healthz
```

重建会短暂中断服务，数据保留在已有数据卷。restart 不会重新读取 .env，因此使用重建。不要把 cat .env、docker compose config、docker inspect 的完整输出贴到聊天。保管 .env 及备份；不要改动 SECRET_KEY，否则已有加密令牌将无法按原密钥读取。

## 四、成员授权与实际验收

1. 用自己的家庭密码登录域名入口，进入“设置 → 账号与同步”绑定自己的账号，核对身份及权限。
2. 选择准备向双方及电视展示的日历、清单和归属；可由账户拥有者将 Microsoft 或 Google 清单明确设为唯一家庭主清单。
3. 在原应用创建测试任务、带地点的测试日程，等待“最近成功同步”更新，检查另一成员和电视。
4. 手机看板完成、恢复任务，并在原应用核对；在原应用修改、删除测试项目，检查自动同步。
5. 退出后使用已绑定平台登录，确认回到正确家庭身份；验证个人财务隔离、电视只读和密码登录。
6. 管理员检查服务重建后的持续同步；至少跨过一次 access token 更新后再次核对。真实授权、刷新、限流和重复事件验收记录应单独更新，不能用注册成功代替。

## 维护与常见提示

| 情况 | 处理 |
|---|---|
| 等待管理员配置 | 完成平台注册、隐藏输入凭证并重建容器。 |
| redirect_uri_mismatch / AADSTS50011 | 核对 Web 类型、HTTPS、域名和回调路径逐字一致，不加结尾斜杠。 |
| Google access_denied | 核对实际账号是否加入测试用户、API 是否启用、组织是否限制访问。 |
| Microsoft 要求管理员批准 | 由该组织的授权管理员处理。 |
| 授权过期 / invalid_grant | 从本人家庭会话重新授权，Google Testing 另查 7 天规则。 |
| 账号已绑定另一成员 | 使用正确家庭账号登录，不按邮箱自动改绑。 |
| 无日历或清单 | 核对连接账号、授权范围与原服务；读取失败不等于没有数据。 |
| 密钥到期 / 轮换 | 在原应用创建新 secret，运行配置助手并重建；确认连接正常后撤销旧 secret。避免删除重建整个应用，client ID 变化会影响绑定。 |

服务端保存加密访问 / 刷新令牌，浏览器和电视只获得看板会话。一次性 state 与 PKCE 保护授权请求；回调确认发起绑定的成员。代码准备不替代成员同意及真实同步验收。

官方资料核查日期：2026-09-14。界面如有差异，以同名字段和官方说明为准。
