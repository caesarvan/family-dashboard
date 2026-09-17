# 电视精选照片轮播与手机控制

照片轮播、手机控制、持久化状态和短授权显示已纳入现有应用与发布版本，当前安装身份见 [README](../README.md)。依赖 `household_media.py` 的媒体库与独立电视许可；开始播放不会新增共享或许可。视频播放和实体电视仍未验收；本模块的临时环境测试不代表真实 Google 账号的完整轮播链路验收。

设备会话加固已随 2026-09-17 13:00:01 版本发布，13:00:47 正常 TLS 读回通过，见 [设备发布验收](EXPO-DEVICES-ACCEPTANCE.md)。它不改变播放接口、许可规则或数据库结构；[Expo 电视展示](EXPO-TV.md) 已于 14:19:19 发布，14:19:53 正常 TLS 读回通过，实际范围见 [电视展示验收](EXPO-TV-ACCEPTANCE.md)。

## 注册与交付边界

现有应用工厂已在每个家庭注册媒体库后调用 `register_media_playback(app)`，返回 `MediaPlayback` 并写入 `app.extensions['media_playback']`。播放模块和静态入口已集成；首次专项浏览器测试使用临时应用注册和测试 HTML 注入，不能把该测试方式当作当前工厂尚未注册的依据。

控制器依赖当前同版本媒体库的 `transaction`、`_member`、`_tv`、`_authority`、`_item`、`_item_dto`、`_audit`、`ITEM_VIEW` 和 `MediaError`。后续引擎协议变更需组合验证。电视读取先用 `_tv` 验证实际 `household_tv` cookie；客户端不能提交设备 ID 来替代电视身份。成员读取与修改均在事务中重新验证真实成员会话及家庭。保留应用现有 CSRF、Origin、只读电视和 no-store 响应规则。

现有静态入口已加载 `media-tv.css` 与 `media-tv.js`，脚本在 `tv-display.js` 之前 defer 加载。`TVDisplay.render` 追加控制区，`TVDisplay.applyBoard` 调用显示挂载；看板布局契约不变。`media_playback.py` 已列入 Docker 精确源码清单，现有完整备份与恢复包含播放表。本轮不重新执行首次建表迁移；此文档不是生产操作说明。

## 数据与事务

每个家庭使用既有 `media_playback` 表（首次引入时新增，目前已包含在 55 张业务表内）：

| 列 | 含义 |
| --- | --- |
| `device_id` | 24 位小写十六进制；主键，外键 `devices(id) ON DELETE CASCADE` |
| `mode` | `dashboard` 或 `photos` |
| `paused` | 整数 0 / 1 |
| `interval_seconds` | 整数 5–120 秒 |
| `cursor` | 当前时间锚点对应的照片索引；整数 0–1000000 |
| `anchor_at` | 服务端 Unix 秒；自动轮播从此时间计算，不写每一帧 |
| `revision` | 每个设备独立 CAS；已保存值 1–9007199254740991 |
| `updated_at` | 最后一次控制修改的服务端 Unix 秒 |

新设备没有记录时返回看板、10 秒、revision 0。只读不创建行。设备删除级联删除播放状态；设备到期立即拒绝其读取/控制。`devices.display_layout` 与该表的 revision 无关联，也不会被播放控制修改。

`SCHEMA_SQL` 是明确的首次迁移 DDL；外部迁移可在自己的事务执行。`initialize_media_playback(con)` 要求连接空闲且启用外键，创建使用 `BEGIN IMMEDIATE`；已有表必须与本版 DDL 一致，否则拒绝隐式修复。请求修改使用媒体库 `BEGIN IMMEDIATE`、当前成员认证、revision 对比、更新和审计同一事务。审计失败也撤销控制写入。两个连接提交同一 revision 只有一个成功。

播放顺序为目前对此电视有效的照片 ID 升序，最多 2000 张；只选已确认 `ready`、明确 `shared`、存在该设备 `media_tv_grants`、来源账号仍具有实际 Picker 授权的照片。读取列表不加载预览 BLOB。集合增删会重新按当前列表取模，不承诺维持删除前的索引。暂停保留位置，上一张/下一张在暂停时仍可使用；修改间隔保留当前位置并重设时间锚点。账号撤销、照片删除/改私密、电视许可撤销均在下一次读取重新判断，控制无权绕过。

## 手机 API

`GET /api/media-playback/devices/<deviceId>` 只限同家庭有效成员；任何成员都可控制家庭已配对设备，但媒体共享/电视许可仍只由照片拥有者管理。不接受查询参数。响应为：

```json
{
  "deviceId": "111111111111111111111111",
  "revision": 3,
  "mode": "photos",
  "paused": false,
  "intervalSeconds": 10,
  "position": 0,
  "photoCount": 2,
  "canStart": true,
  "updatedAt": "2026-09-16T09:00:00+00:00"
}
```

`position` 从 0 开始，空集合为 0；`updatedAt` 在未保存状态为 null。

`PUT` 同路径，真实成员 cookie + `X-CSRF-Token`：

```json
{"revision":3,"action":"interval","intervalSeconds":15}
```

允许 action：`start`（从第一张开始）、`dashboard`、`pause`、`resume`、`previous`、`next`、`interval`。`intervalSeconds` 仅在 `interval` 必填，其他动作禁止此字段。revision 与间隔都要求 JSON 整数，bool/浮点/字符串不接受；未知字段、重复 JSON 键、非有限数值、超过 16 KiB 的请求和查询参数拒绝。`start` 需至少一张已授权照片；暂停/继续/前后翻页只用于照片模式。成功返回上述完整状态，revision 加 1。

没有自动动作重试或永久幂等回执：同 revision 的重复 PUT 返回 409，不能让下一张执行两次。网络结果不明时先 GET 刷新，用户再决定是否操作，不能用新 revision 自动重发未知结果。手机控件也遵循此规则。

错误遵循媒体库安全 JSON，例如 `{"error":"记录已变化，请刷新核对后重试","code":"conflict"}`。主要状态：400 `invalid_input`，401 会话失效，403 只读电视或 `not_selected`（无照片），404 `not_found`（不存在/已过期/其他家庭的设备），409 `conflict`（revision 变化或非照片模式），429 `quota`，503 媒体不可用。不返回令牌、账号信息、文件名或原始图片 metadata。

## 电视只读 API 与显示 lease

`GET /api/media-tv/playback` 必须有实际有效电视 cookie，不接受 deviceId 或任何查询参数；同时存在成员 cookie 也不能替代电视 cookie。响应示例：

```json
{
  "deviceId":"111111111111111111111111",
  "revision":3,
  "mode":"photos",
  "paused":false,
  "intervalSeconds":10,
  "position":0,
  "photoCount":2,
  "canStart":true,
  "updatedAt":"2026-09-16T09:00:00+00:00",
  "serverTime":"2026-09-16T09:00:02+00:00",
  "validUntil":"2026-09-16T09:00:17+00:00",
  "item":{
    "id":"222222222222222222222222",
    "revision":4,
    "width":1600,
    "height":900,
    "previewUrl":"/api/media-tv/items/222222222222222222222222/preview"
  }
}
```

看板模式或没有有效照片时 `item:null`。看板模式 TV 返回 `photoCount:0`，不会预取照片集合；手机 GET 仍可显示可开始的数量。`validUntil` 取服务端当前时间加 15 秒与设备到期时间中的较早值。预览 URL 使用媒体库已有路由，读取 bytes 前后再次检查授权与照片 revision；仅发送净化后的 JPEG。

浏览器约每 2 秒重新读取，5 秒网络超时；图片从 fetch/no-store 得到 JPEG Blob，解码后以临时 object URL 显示。它把服务端 lease 长度减去请求全部耗时，映射到 `performance.now()`，不依赖设备墙钟。失败、断网、pagehide、页面隐藏、身份变化或 lease 到期会移除 src、撤销 object URL、显示中性提示；恢复连接/页面可见后重新验证。迟到状态/图片通过请求 epoch 与身份检查丢弃。暂停并不暂停授权检查；看板继续后台现有刷新，返回看板隐藏照片层。

撤销不能收回已经交付给浏览器的 bytes；正常轮询约 2 秒反映撤销，旧授权快照最多只支持剩余 15 秒显示。浏览器事件循环被系统完全冻结时 JavaScript 无法操作屏幕；恢复后立即检查到期/可见性，不能承诺物理电视固件的冻结行为。未实现离线照片存储、Service Worker 缓存或后台相册下载。

## 前端接口和验证

`window.MediaTV.mountControls(node, deviceId, {getIdentity})` 返回 dispose；身份对象包含 `user/csrf/isTV/isDemo`。控件在读写前后核对 `/api/me`，只允许当前成员；身份切换清空旧数据。`ensureDisplay()` 只挂载真实 TV 角色，`notifyIdentityChanged()` 可供统一身份入口主动清理；同时自带身份轮询兜底。手机显示指定设备的开始/看板、暂停/继续、上一张/下一张、间隔与刷新。并发冲突保留安全提示，要求用户刷新。

`tests/test_media_playback.py` 使用实际临时 SQLite、成员会话、配对 cookie、加密媒体、双户与双连接验证。`tests/browser_media_tv_check.py` 启动两套临时 Flask 和实际 Edge，挂入现有 TVDisplay 设置与看板：390px 手机、1920px 电视、三个配对屏幕、控制动作、真实 grant 撤销、断网恢复、故意缩短 lease/阻塞响应、迟到图片与身份变化。浏览器故障注入不代表真实云调用或物理电视测试。原件与截图仅写 ignored `test-results/media-tv-playback/`；失败原件保留。
