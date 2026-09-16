# Google Photos 增量授权契约

本候选只提供照片授权入口、已授予能力投影和服务端凭据 helper；复用现有 `cloud_accounts.py` 注册、Google client、回调、成员会话和每户加密存储，不新增表。未接入照片选择器 UI、媒体持久化或后台照片同步；未调用真实 Google 账户，未部署。测试均为合成服务商响应与临时数据库。

## 授权与 HTTP

本人在当前家庭登录后发送：

```http
POST /api/accounts/google-photos/bind
Content-Type: application/json
X-CSRF-Token: <current-member-csrf>

{}
```

`{}` 允许新增 Google 照片账户，也允许重新连接本人同一 Google subject 的既有账户。若从某个已有账户发起升级，提交 `{"accountId":"<id-from-GET-accounts>"}`，服务端必须维持这个账户的 id、owner、provider、client_id 和 subject。邮箱相同不足以匹配身份。accountId 必须是 1–128 个 ASCII 字母、数字、下划线或连字符；显式 null、空值、非字符串及额外字段均拒绝。返回 `200 {"url":"https://accounts.google.com/o/oauth2/v2/auth?..."}`。

接口要求本人、CSRF、同源，拒绝电视；授权起点限制沿用 `oauth_bind` 每 IP 10 分钟 20 次，照片未过期 state 每成员最多 20 个。state 十分钟过期、单次消费、绑定浏览器、Google provider、发起成员和其当前会话 nonce；新授权流程会让同浏览器旧流程失效。回调在网络操作后、写数据库前再次验证成员会话；退出、切换成员/家庭、撤销会话、账户删除等情况不能复活账户或回写旧会话。

照片授权仅请求 `openid email profile` 和 `https://www.googleapis.com/auth/photospicker.mediaitems.readonly`，使用 PKCE S256、`access_type=offline`、`prompt=consent`、`include_granted_scopes=true`。固定复用 `<PUBLIC_ORIGIN>/auth/google/callback`，无需另设照片回调。增量授权会合并用户实际同意的范围，但应用必须检查 token response 的实际 scope。Picker scope 支持用户主动选择的照片会话，不代表可后台读取整个 Google Photos 库。[Google Web Server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server#incrementalAuth)、[Google Photos 授权](https://developers.google.com/photos/overview/authorization)。

照片回调必须包含实际 Picker scope 和可用离线 refresh token；缺少 scope、只有 Calendar/Tasks、近似字符串或错误类型都不算照片授权。既有同 subject 账户若响应省略 refresh token，可沿用该账户已加密保存的 refresh token。照片授权无需日历/待办权限；常规账户授权入口原有无 scope 兼容路径保持不变。

升级原有账户时保留 account id 和所有已选来源行（包括共享归属、主清单、同步状态）。若新实际 scope 会丢失原先明确授予的日历读取/写入或待办权限，或者不能覆盖当前所选来源，回调拒绝且不替换旧 tokens。权限按能力比较，Google 全量 calendar scope 可覆盖既有日历读写。授权拒绝/降权可能已改变 Google 端状态，保留本地旧记录不保证旧凭据在服务商端仍可用；后续普通同步按原有错误处理。

成功重定向：`<PUBLIC_ORIGIN>/?auth=photos-connected`。失败仍为 `/?auth=error&reason=<allowlisted-reason>`，例如 `invalid_state`、`bind_session_changed`、`session_changed`、`already_bound`、`insufficient_permissions`、`missing_refresh_token`、`provider_error`、`account_limit`。不会将 provider 原始响应或凭据串进 URL/日志。新 JSON 接口错误沿用 `{ "error": "中文提示" }`，常见状态：400 输入/平台不匹配，401 未登录/需重授权，403 非成员/CSRF/缺少权限，404 非本人或不存在，409 账户忙/已改变，429 限流，503 未配置。

## 安全账户投影

`GET /api/accounts` 仍只返回当前成员当前家庭的账户；每项新增布尔字段：

```json
{
  "id": "11111111111111111111111111111111",
  "provider": "google",
  "name": "Synthetic Member",
  "email": "member@example.test",
  "needsReauth": false,
  "capabilities": { "photos": true },
  "sources": []
}
```

`capabilities.photos` 只说明加密存储中的最近实际 scope 明确包含 Picker 权限，不证明远端实时有效；须同时看 `needsReauth`，真正操作以 helper/服务商结果为准。Microsoft、缺失 scope、没有 Picker 或不可解密的记录返回 false；不可解密同时标记 needsReauth。输出不含 scope、subject、access/refresh token、client secret。

照片独立账户没有日历/待办同步来源。已有实际 Google scope 未覆盖日历与待办时，`GET /api/accounts/<id>/sources` 与非空 `POST .../sources` 返回 403，不向服务商尝试来源发现；刷新后也重验。空 `sources: []` 仍可清除旧来源，不需要远端权限。需要日历/待办时，由用户通过原 `/api/accounts/bind` 单独授权；不因照片连接成功显示同步来源已授权。

## 服务端 helper

```python
token = app.extensions['cloud_accounts'].photos_access_token(account_id, owner)
```

这是服务端 API，没有 HTTP 凭据出口。owner 必须是调用业务已经授权的当前成员 id；不得从未校验的客户端字段直接传入。helper 可在服务端任务中使用，因此不隐式依赖 Flask request 或检查成员会话。它只检查当前家庭账户归属、Google provider、client 配置、needs_reauth、已授予 Picker scope，并取得与同步/断开共用的账户 OS 锁。

**未来媒体业务仍须在自身提交事务中重验当前成员会话和家庭、媒体授权/归属。** helper 返回凭据后即释放锁，不保证后续外部请求或本地媒体写入期间会话仍有效，也不授权照片共享、导入或外部写入。任何调用者都不得 HTTP 序列化、记录或把该 token 传给模型。

未过期 token 不触发网络。临近到期时，向原固定 Google token endpoint 请求刷新，不带 scope：

- 响应明确 scope：以实际返回范围为准；若 Picker 已消失，先加密保存新 grant，再返回 403，公开 photos 能力转为 false，不返回 token。
- 响应省略 scope：仅在旧记录有明确 Picker grant、同一 refresh 凭据用于此次请求，且数据库中的 account/client/subject/owner/完整加密凭据和重授权状态都未改变时，保留此前 scope。响应可轮换 refresh token；不以授权请求范围生成实际 grant。
- 原记录没有明确 scope：刷新前即拒绝。HTTP 期间删除、归属/subject/client/凭据更换、标记重授权或配置改变时，不保存返回 token、不复活账户。

该省略语义来自 RFC 6749 §6（刷新未指定 scope 时使用原授权范围）和 §5.1（相同范围时响应可省略 scope）；Google 增量授权文档说明合并授权的 refresh token 可换取对应合并范围的 access token。[RFC 6749 §6](https://www.rfc-editor.org/rfc/rfc6749#section-6)、[RFC 6749 §5.1](https://www.rfc-editor.org/rfc/rfc6749#section-5.1)、[Google 增量授权](https://developers.google.com/identity/protocols/oauth2/web-server#incrementalAuth)。

## 验证与后续接入

新专项 `tests/test_google_photos_oauth.py` 使用真实 Flask HTTP 路由、成员会话与临时 SQLite，服务商 token/UserInfo/source factory 全部合成。覆盖严格输入、最小 scope、PKCE/浏览器/服务商/state 重放、实际权限、照片独立账户、同 subject 升级/降权保护、锁与刷新竞态、会话切换/撤销、跨户数据库/凭据隔离、安全 JSON 和错误日志。原账户、成员会话、日历发布、待办发布与 OAuth 诊断测试用于回归。

新增路由须由集成人后续更新路由清单/部署证明；本分支不编辑 app/schema/UI/Docker/发布工具。未来 UI 应区分 `photos-connected` 与普通 `connected`，使用真实 capability 和 reauth 状态，调用照片 Picker 的交互与存储仍属独立候选。真实 Google 同意屏幕、测试用户/应用验证、权限撤销、服务商刷新与手机浏览器行为均未验收。
