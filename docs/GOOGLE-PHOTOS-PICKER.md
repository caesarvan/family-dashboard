# Google Photos 本人选择导入：协议适配器

`google_photos_picker.py` 是纯服务端协议适配器，只访问 Google Photos Picker 会话及用户在该会话中主动选择的媒体。它不扫描全库、不实现 OAuth、不注册应用接口、不存储文件，也不访问真实账号。此候选通过合成 transport 测试；真实 OAuth、Google 返回 URL 的兼容性与导入体验尚待后续验证。原文件仍在 Google，媒体缓存与保留策略由后续模块负责。

## 官方契约与边界

后续持久化功能须在选择授权前说明具体展示副本用途、独立共享控制和删除办法，并保护 Google 数据及 access/refresh tokens 的静态存储。不能把选择动作扩大解释为全库访问、永久授权、自动家庭共享或训练模型许可；本模块不实现这些持久化与共享功能。官方政策还限制 Photos 替代品、通用图库和人脸聚类用途，产品需保持明确的家庭旅行/记忆场景增益。[用户数据与开发者政策](https://developers.google.com/photos/support/api-policy)

[最佳实践](https://developers.google.com/photos/overview/best-practices) 的性能缓存 60 分钟段落明确标注 Library API only。它不能替代对 Picker 展示副本用途、保存期限和用户同意的独立设计；本模块限制的是临时 baseUrl 下载能力，没有磁盘缓存或永久授权机制。后续重试应由上层根据幂等性与错误采取有界退避，不能层层叠加自动创建重试。

2026-09-16 核对 [Picker REST 总览](https://developers.google.com/photos/picker/reference/rest)：服务 origin 是 `https://photospicker.googleapis.com`，仅使用 `POST /v1/sessions`、`GET/DELETE /v1/sessions/{sessionId}` 和 `GET /v1/mediaItems`。会话指南有一处旧 `photoslibrary.googleapis.com` 示例，本适配器以 REST 为准，不回退到 Library API。

唯一所需 scope 为 `https://www.googleapis.com/auth/photospicker.mediaitems.readonly`。上层 OAuth 必须明确向本人请求选择权限；本模块接收已取得的 access token，不判断其属于哪个本地成员。后续接入必须绑定登录成员、家庭及 Google 账户，禁止把前端传来的任意 token 当作本人身份。

[PickingSession](https://developers.google.com/photos/picker/reference/rest/v1/sessions) 包含 `id`、`pickerUri`、`expireTime`、`mediaItemsSet`，选择尚未结束时还提供 `pollingConfig.pollInterval` / `timeoutIn`。`maxItemCount` 是字符串形式的 int64，Google 上限 2000。适配器默认请求 100 项，接受 1–2000，不使用 0 表示默认上限。

轮询交上层调度：遵循 pollInterval，并同时限制最初 timeoutIn 和 expireTime；timeoutIn 为 0 应停止。不得每次拿新 timeoutIn 就无限延长同一流程。本模块仅返回时长字符串，不睡眠、不自动轮询、不自动创建新会话。pickerUri 仅返回给当前授权者，在 Google 页面选择；不能放 iframe。界面自行决定是否使用官方支持的 `/autoclose`。[会话流程](https://developers.google.com/photos/picker/guides/sessions)

`sessions.create` 的可选 requestId 被官方描述为 limited-input-device OAuth 简化流程的一部分，未说明可作为普通网页通用幂等保证；本适配器不发送它，也不自动重试创建。创建超时、连接失败、5xx、重定向或成功响应不可解析时 `outcome_unknown=True`，上层必须承认可能已创建会话。会话创建失败的 4xx 则按明确错误处理。[创建方法](https://developers.google.com/photos/picker/reference/rest/v1/sessions/create)

## Python 接口

```python
from google_photos_picker import GooglePhotosPicker, PickerError

# access_token 只能由服务端已绑定本人的 OAuth 流程传入。
with GooglePhotosPicker(access_token) as photos:
    session = photos.create_session(max_item_count=100)
    # 将 session['pickerUri'] 发给本人；按 pollingConfig 在后续操作读取。
    session = photos.get_session(session['id'])
    if session['mediaItemsSet']:
        chosen = photos.list_selected_media(session['id'])
        # 只处理用户明确希望导入的本次已选 media ID。
        downloaded = photos.download_media(
            session['id'], chosen[0]['id'], variant='preview', width=2048, height=2048)
        # downloaded.data 是 bytes，content_type 是经过核验的 MIME。
        # 文件持久化、解码、成员权限及发布均由上层处理。
        photos.delete_session(session['id'])  # 完成全部需要的字节获取之后清理
```

示例中的选择清单可能为空，上层应先检查后再取第一项。示例只展示方法关系，不能作为同步等待用户选择的网页处理器；OAuth、轮询与用户动作需要独立流程。

| 方法 | 返回／行为 |
|---|---|
| `create_session(max_item_count=100)` | 规范化会话 dict，保留官方 camelCase 字段；单次 POST |
| `get_session(session_id)` | 校验返回 ID、有效期、布尔及轮询字段；已过期抛错 |
| `delete_session(session_id)` | 成功返回 None；先清理该实例持有的下载能力；未知删除结果不自动重试 |
| `list_selected_media(session_id, page_size=100, max_items=2000, max_pages=40)` | 先核对会话已完成选择，再完整有界分页；返回元数据列表 |
| `download_media(session_id, media_id, variant='preview', width=2048, height=2048)` | 返回 `DownloadedMedia(data, content_type, filename, variant)`，不含 URL |
| `close()` | 清理实例中的 token 引用与临时选择清单；上下文管理器退出时调用 |

一个实例只保留最近一次**完整成功**读取的会话选择。重新列举前会清除旧能力，任何中途失败都不会注册半份清单。下载只接受该实例已登记的 session ID 和 media ID，不接受调用者给定 baseUrl。公开元数据是副本，修改返回 dict 不会修改内部下载目标。实例供同一授权账户的一次导入流程顺序使用，不得跨成员共享或并发调用；不要将其存进公共全局缓存。刷新 access token 时建立新实例并重新读取选择。

返回媒体字段为 `id`、`createTime`、`type` 和 `mediaFile.{mimeType,filename,mediaFileMetadata}`；元数据只保留尺寸及视频 processingStatus，不带 baseUrl、拍摄设备信息或地理坐标。文件名仅作展示，不能直接作为存储路径。异常 `PickerError` 只包含固定 `code` / `message` / `status` / `retryable` / `reauth` / `outcome_unknown`；`retryable` 表示上层可判断是否重试，不表示本模块已经重试。

## 分页与能力有效期

[mediaItems.list](https://developers.google.com/photos/picker/reference/rest/v1/mediaItems/list) 只列本次选择，pageSize 最大 100；可能返回空页且仍有 nextPageToken。本模块允许空页继续，但页数最多 40、唯一媒体最多 2000；调用者可进一步降低上限。达到 max_items 而仍有下一页直接报 `selection_limit`，不会返回声称完整的截断结果。重复分页 token 报错；完全一致的重复媒体 ID 去重，元数据或 baseUrl 冲突则拒绝整份结果。会话 GET 的 ID、列表或条目附带的 sessionId 不一致时也拒绝。

单页 JSON 不超过 2 MiB，全部分页原始 JSON 累计不超过 16 MiB；规范化元数据加内部 URL 也独立限制 16 MiB。每字段有限长，未知字段不公开；严格拒绝非对象 JSON、重复键、非有限数及畸形日期。标识暂限 1–1024 个 ASCII 字母、数字及 `_~.-`，排除单独点段；不把这一保守输入限制宣称为 Google 对所有 ID 的保证。

内部 baseUrl 的有效期取会话 expireTime 与本次读取起点后 60 分钟的较早者；后续 GET 可以缩短但不能延长此能力。下载前后都检查有效期，权限拒绝、撤销或不可访问会清空清单。Google 可以提前撤销 URL，这仍以实际请求结果为准。[媒体访问说明](https://developers.google.com/photos/picker/guides/media-items)

## 下载、格式与网络限制

| variant | 参数与范围 | 接受的实际响应 | 字节上限 |
|---|---|---|---|
| `preview` | PHOTO 或 VIDEO 的图片预览，`=wN-hN`，宽高各 1–4096 | JPEG / PNG / WebP / GIF | 8 MiB |
| `photo` | 仅 PHOTO，`=d` | 来源声明及实际响应均为 JPEG / PNG / WebP / GIF | 25 MiB |
| `video` | 仅 VIDEO 且 `mediaFile.mediaFileMetadata.videoMetadata.processingStatus == READY`，`=dv` | MP4 | 100 MiB |

VIDEO 的 preview 取得图片缩略图，不是视频文件；即使原视频仍在处理，也可尝试缩略图，失败按原错误返回。video 变体严格要求 READY。photo 不接受 HEIC / RAW / SVG 等原文件；HEIC 的 preview 如果 Google 返回允许的图片格式，可被接受。Motion Photo 首版只走 PHOTO 图片路径，不下载其运动视频部分。

`=d` 的官方语义是保留除位置外的 EXIF 元数据，`=dv` 是高质量转码版本；不宣称字节等于相机原文件或完成原片备份。视频 READY 字段以 [REST MediaFileMetadata](https://developers.google.com/photos/picker/reference/rest/v1/mediaItems) 为准，不采用媒体指南中 Library API 风格的旧字段路径。

字节响应同时核对 MIME 与 JPEG/PNG/WebP/GIF/MP4 的基本文件头；这不等于完整解码、恶意文件扫描或媒体可播放验证。上层必须使用生成的存储标识、正确响应 Content-Type/下载策略，并在展示前执行自己的解码、尺寸、内容和权限检查。文件字节暂存在内存，峰值内存可能高于单份字节上限；本模块没有磁盘缓存。

固定 TLS origins：协议为 `photospicker.googleapis.com`，媒体首版只接受官方例子中的精确 `lh3.googleusercontent.com`，pickerUri 仅接受 `photos.google.com` 且本模块不抓取该页面。未知媒体 host、显式端口、userinfo、片段、媒体查询参数、路径点段和控制字符都拒绝；**精确 lh3 限制是本地保守策略，尚未验证真实账号可能出现的其他 Google 下载 hosts**，不得擅自扩成任意 googleusercontent 子域。

所有请求禁止重定向，包括同域跳转；默认 urllib TLS 证书验证保留，Authorization 仅在经过 URL 验证的请求中发送。JSON 和字节响应禁压缩并逐块限制大小。元数据每次 30 秒分块 deadline，分页总 120 秒；媒体 120 秒分块 deadline；socket timeout 最大 30 秒。正在阻塞的读取可能继续等待至 socket timeout，因此不是硬实时取消；它仍能终止持续慢滴流。未知写入不会自动重试，读取也由上层决定重试。

仅 API 的 403 错误会有界读取至多 64 KiB JSON，严格匹配 `error.code=403`、`status=PERMISSION_DENIED` 和 `google.rpc.ErrorInfo` 的完整类型、`domain=googleapis.com`、`reason=SERVICE_DISABLED`、`metadata.service=photospicker.googleapis.com` 后返回固定 `api_disabled`。不返回远端 message、headers、项目标识、activation URL 或异常原文；错误类型、domain、service 不符或正文无效时仍为普通 `forbidden`，媒体下载的 403 不应用此分类。成功 JSON 解码后也检查当前 token 的字面回显，包括 Unicode 转义形式。字节响应拒绝当前 token 的直接字节回显。不要记录 transport 参数、pickerUri、会话原始响应或实例内部清单。

`api_disabled` 只将本次导入记为失败，不重发创建 POST，也不把有效账户标为需要重新授权、不撤回既有家庭共享或电视许可。界面展示固定启用提示；维护者确认启用对应 API 后，用户需明确“重新选片”、重新同意临时处理，才能创建新选择。普通未知 403 仍沿原保守权限处理，401／无效令牌及实际 scope 丢失的保护保持；不能把重新授权当成所有 403 的解决方法。这一故障修订的合成回归不等于用户真实选片成功。

## 可注入 transport 与测试

```python
def transport(method, url, *, headers, body, timeout):
    # body 是 bytes 或 None；返回兼容以下接口的 response：
    # status: int, headers.get(name), geturl(), read1(max_bytes), close()
    ...
```

transport 是可信服务端扩展点，必须遵守 timeout、不得自行跟随重定向或记录凭据。适配器在调用前核对 URL，并统一读取和校验原始响应；fake transport 不能用已解码 JSON 绕过大小、编码或 MIME 检查。测试对生产默认 transport 设置阻断，默认 urllib 路径仅用 fake opener 验证，没有真实请求。

```powershell
uv run --no-project --python 3.14 --link-mode copy --with pytest python -m pytest -q tests/test_google_photos_picker.py
```

专项覆盖会话契约、scope/host、分段和总量限制、分页循环与冲突、整份失败撤销能力、结果未知、URL/重定向、safe error/凭据回显、媒体类型及文件头、READY 与缩略图区分、到期和撤权、慢响应与清理。合成文件头只用于协议测试，不作为有效可解码的图片/视频样本。首跑因超大 bytes 参数生成过长 pytest ID，触发 Windows 环境变量限制；改为短 ID 后运行通过，未把首跑写成无错误。

后续接入仍需独立负责 OAuth 配置与验证、持久化导入状态、本人权限与 CSRF、上层额度/重试、用户预览确认、缓存清理、删除/撤权、图像解码与真实账号兼容验收。本模块不会把照片时间或内容认定为地点已到访，也不会自动共享媒体给其他成员或电视。
