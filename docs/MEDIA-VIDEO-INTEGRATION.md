# 视频导入、授权与持久化候选

本批为后端候选，基线 `8d3e6376a606155ff66a0388e43d04cb7562fe9f`；不表示已部署或已通过真实 Google 账号、电视设备验收。播放器、混合电视播放和 FFmpeg 生产镜像配置另批完成。纯处理器接口见 [MEDIA-VIDEOS](MEDIA-VIDEOS.md)。

Google Picker 仍只下载本次明确选择的内容；PHOTO 保留原图片路径。VIDEO 通过 `variant='video'` 的既有受限下载器取得最多 100 MiB 的 MP4，再在 worker 中实际净化完整视频与 JPEG 封面。源片长最多十分钟，MP4 展示副本最多 64 MiB，JPEG 最多 2 MiB。返回实际输出 `durationMs` 整数，允许编码对齐最多 250 ms；不会截掉超长原片冒充成功。

服务端通过 `MEDIA_VIDEO_FFMPEG`、`MEDIA_VIDEO_FFPROBE` 提供可信绝对路径，可在 app 配置或 worker 环境指定；可选 `MEDIA_VIDEO_TEMP_ROOT` 只用于受限临时处理。不从请求传入工具或路径，不自动下载、安装工具。900 秒处理 deadline 仅属于后台 worker；VIDEO 下载 claim 的 lease 为 1200 秒，PHOTO／其他操作保持 600 秒。原导入、Picker 会话到期和成员／来源撤权始终优先，提交时重新做 lease、版本与权限 CAS。

## 数据与 API

原 `media_items` ID、revision、导入记录和明确保存回执不变。原 `preview_cipher` 保存 JPEG 封面；新表 `media_video_cache(media_id, cache_key, cipher, created_at)` 通过 FK 关联原媒体。视频对外仍使用 `media-video` purpose，内部采用独立 `media-video/aesgcm/v1` 密钥域的 AES-256-GCM；明文字节上限 64 MiB，加密后限 67,108,940 字节。原图片与 JSON 的 Fernet 格式及密钥保持兼容。格式、内存实测与尚待完成的 Linux 验证见 [MEDIA-VIDEO-CIPHER](MEDIA-VIDEO-CIPHER.md)。加密元数据绑定原媒体、家庭、拥有者、cache key、视频长度和摘要。

列表、详情、待确认项和电视项在原字段外增加 `mediaType: 'photo' | 'video'`；旧照片缺少该字段时按 photo 读取。video 项增加 `durationMs`、`hasAudio`、同源 `videoUrl`；成员项 `contentType` 为 `video/mp4`，`previewUrl` 始终是 JPEG。不会向客户端暴露 Google 下载 URL、token 或本地文件路径。

| GET 接口 | 权限与响应 |
|---|---|
| `/api/media/items/<id>/video` | 沿原成员媒体 ACL；本人可核对 staged 内容，确认后保持默认私有；明确共享才允许伙伴读取。 |
| `/api/media-tv/items/<id>/video` | 有效配对 TV、已确认且共享、当前来源授权、该 TV 的明确 grant 四项同时成立。 |

返回有界完整 `video/mp4`，`no-store`、`nosniff`，不提供 Range 或外部能力 URL。解密前及之后重新读取身份、ACL、revision 和 cache key，撤销／删除／成员移除发生在读取期间时不会发送旧字节。客户端后续使用完整 fetch→Blob，另须为 Blob 播放配置窄 `media-src` CSP，并在撤权或停止播放时释放 Blob。

新增 VIDEO 每项预留完整 64 MiB 加密上限加原 3 MiB 封面余量。不能沿用照片的 3 MiB 绕过视频配额。现有本人 100 MiB／家庭 200 MiB 总额不变，包含所有真实密文及活动 reservation；选择多个较大视频可能直接返回 quota。完成处理后按实际密文计费并释放差额，确认回执不重建素材。

## 删除、导出与迁移边界

未确认项取消、到期、未选中的子集，以及媒体删除、来源移除／scope 撤回沿原 tombstone 路径，同事务触发删除视频 cache；硬删除原媒体由 FK 级联。退出或移除成员遵循原保留本人资料政策，立即拒绝失效身份与伙伴／TV 读取，不额外销毁本人资料。临时来源重授权失败沿原私有保留政策，不能把 retained 描述为已删除。

个人数据导出仅增加已确认媒体的类型、视频时长及音轨说明；仍通过当前媒体 ACL 和导出后复核，既不导出 MP4/JPEG 文件，也不导出 URL、密文、来源能力、TV grant 或后台任务。整库备份包含加密 cache；个人 ZIP 不等于可恢复的整库备份。

家庭库 **71→72** 只加一表和一个原媒体 tombstone 清理触发器，平台库保持 9。`media_video_storage.SCHEMA_SQL` 是唯一 DDL；initializer 要求干净、FK 开启且已有媒体父表的连接，在一笔 `BEGIN IMMEDIATE` 中添加并核对固定对象。旧 71 表数据、旧媒体列、原 receipt 不回写；重复启动只能接受相同 schema。生产必须在独立迁移批次中完成所有 writer 停止、完整组备份、71 基线核对、72 空表添加、旧表保全核对、app-only 检查和失败保留；本批不提供或执行生产迁移／恢复工具。

## 验证

专项使用真实临时 Flask／SQLite、Fernet、实际 FFmpeg 生成与处理的合成视频，只有 Google 网络 transport 为模拟边界。覆盖完整 worker→staged→确认→回执重放／重启、伙伴与各 TV grant、解密期间撤权、取消／过期／原 tombstone 清理、配额、长处理 lease、元数据导出及 71→72 原数据保全；实际执行计数与失败记录由作者报告分别列出，不把代码存在当作测试通过。

本地作者验证已实际结束：首轮 253 项中 250 通过、3 失败；三项失败分别是撤销设备测试缺少 JSON 请求体、成员移除测试未先开启事务，以及旧表集合断言未包含新表。只修正这些测试后，第二轮仅复测这三项并全部通过；253 个唯一用例共执行 256 次，最终无遗留失败／跳过，原首轮失败记录保留。没有重跑纯处理器的已审 16 项，也没有运行 Linux、浏览器、真实账号或生产验收。原件与哈希见本分支 ignored `test-results/media-video-integration-author-verification-r1.json`。

Google VIDEO 的 PROCESSING／FAILED／UNSPECIFIED 记为本项 `video_not_ready`，不进行下载或无限等待，其他已成功照片仍可使用原确认回执保存。处理状态若在本轮准备阶段从 PROCESSING 变为 READY，可继续真实转换；仅合法 VIDEO `processingStatus` 被视为暂态，媒体 ID、类型、创建时间、文件名、MIME、尺寸及其余字段仍严格核对。会话尚未完成选择、选择变化、过期或撤权仍沿原导入整体失败／取消边界，不伪装成单个视频未就绪。
