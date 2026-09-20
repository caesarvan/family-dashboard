# 视频展示副本：独立处理模块

`media_videos.py` 是候选 helper，尚未接入导入队列、媒体表、配额、共享、电视或生产。保留已经成功的 Google 照片流程。本模块不下载原片、不访问真实账户、不保存持久数据，不删除或改写原平台文件。

## 接口与完整时长

```python
from media_videos import VideoTools, sanitize_media_video, MediaVideoError

tools = VideoTools('/usr/bin/ffmpeg', '/usr/bin/ffprobe')  # 部署方提供的可信绝对路径
result = sanitize_media_video(selected_bytes, 'video/mp4', tools=tools, temp_root=private_temp_dir)
```

`VideoPreview` 为不可变对象：`data`（repr 隐藏）、`content_type='video/mp4'`、`width`、`height`、整数 `duration_ms`、`has_audio`、`sha256`、`poster: media_images.Preview`。来源身份、原媒体 ID、账号、原创建日期由调用方保留；本 helper 不接受媒体文件名、URL 或来源元数据作为路径。输出哈希只说明此次字节，不承诺跨 FFmpeg 版本相同。

- 非空 `bytes`，精确 MIME 为 `video/mp4` 或 `video/quicktime`；最多 **100 MiB**、最长 **600 秒**。输入尺寸最多 2000 万像素，主视频恰好一条，音轨最多一条。H.264 与 HEVC 为本批视频输入范围；HDR 的 HLG/PQ 明确拒绝，尚未验证色调映射，不能把 8 位转换说成 HDR 色彩正确。
- 完整解码并转为 H.264／yuv420p；有音轨时转为 AAC、48 kHz、双声道，无声视频不添加虚构音轨。长边最多 1280、小图不放大，偶数尺寸，30 fps。应用来源显示方向到像素，输出不需要原旋转元数据。
- 输出硬上限 **64 MiB**。目标码率根据完整时长和 85% 输出字节预算计算，扣除 AAC 后最高 2 Mbit/s，给十分钟内容及封装开销留空间。不会使用 `-t`、`-fs` 或 `-shortest` 截断来取得“成功”；仍超限则完整失败，不返回半成品。
- 转码后重新 probe，并再次完整解码输出；要求 H.264／可选 AAC 和正确尺寸。核对输入、输出时长，容许最多 250 ms 的帧率/音轨编码对齐差异；返回实际输出 `duration_ms`，不是将较长视频谎报为十分钟。这个对齐容差不是内容截断功能。
- 移除来源 metadata、chapters、附加轨道和 H.264 SEI，再从展示副本提取首帧 JPEG，通过既有图片净化器处理；海报最多 2 MiB。必要的容器/编解码信息仍存在。像素/声音中可识别的个人信息不会被消除。

## 子进程与临时数据边界

调用需要可信且实际可用的 FFmpeg、ffprobe，FFmpeg 必须包含 libx264、AAC、MOV/MP4、JPEG、scale 与 filter_units。没有工具或必要选项时明确失败，不回退为未经检查的原始文件。使用本机已安装的 FFmpeg 9.0.1 做合成验证；只读检查发现 racknerd PATH 当前无 ffmpeg/ffprobe。本轮未安装全局软件或修改服务器，未来镜像依赖及 Linux 实测需单独交付。

进程内只允许一次转换，不在 Web 请求中并发处理。全部阶段共用 900 秒墙钟期限，单次 probe 最多 30 秒；解码/编码线程最多 2，过滤线程 1。POSIX 子进程在 exec 前设置 1.5 GiB 地址空间、600 秒 CPU、65 MiB 单文件、64 个文件描述符限制；Windows 在允许可信 wrapper 启动解码器之前绑定 Job Object，限制整个进程树 1.5 GiB 提交内存、600 秒 CPU、4 个进程，并在关闭时终止整个作业。Windows wrapper 必须等待真实进程结束；不能用会提早返回的 Windows `os.execv` 模拟 POSIX exec。

每次使用独占临时目录，环境只传必要系统目录和本次临时目录，不继承令牌、代理或 FFREPORT。不使用 shell；诊断输出各限 256 KiB，读取有界，外层轮询检查输出文件大小和截止时间。Windows 文件增长用监测及时终止，不能承诺内核级磁盘峰值恰等于 64 MiB；返回字节仍严格检查上限。所有成功/失败路径都等待子进程结束并移除临时目录，不把诊断、路径、源 metadata 或字节带到公开错误。

输入固定使用 MOV demuxer，只允许 `file` 协议；明确禁用 `enable_drefs` 和 `use_absolute_path`，并在容器检查中拒绝非自包含 dref 声明，不让视频引用网络、相对或绝对外部轨道。不能把 FFmpeg 忽略外部声明后成功解码内嵌轨道当成严格拒绝。不会自动探测播放列表、网页或任意协议。进程限制不是操作系统漏洞沙箱，生产仍须由部署层提供无网络、非特权、隔离挂载和总并发/磁盘预算。 当前 racknerd 只读观测总 RAM 1967 MiB、available 1261 MiB，Swap 1023 MiB／已用 281 MiB；这些是观测时数值。模块 1.5 GiB 限制不是预分配，也不代表服务器有此余量。部署必须为独立视频 worker 另行核定整个进程和原 Web／同步服务的总内存、CPU、并发及临时磁盘预算。

技术依据限官方文档：[输入协议白名单](https://ffmpeg.org/ffmpeg-protocols.html#Protocol-Options)、[MOV 外部引用开关](https://ffmpeg.org/ffmpeg-formats.html#mov_002fmp4_002f3gp)、[旋转、流选择与 metadata 选项](https://ffmpeg.org/ffmpeg.html)、[ffprobe JSON 与条目选择](https://ffmpeg.org/ffprobe.html)。本机 `ffprobe -h demuxer=mov` 已确认两个外部轨道开关均受支持。

## 错误与后续接线

`MediaVideoError` 只含固定 `code` 与中文 `message`，没有原异常链。

| code | 边界 |
|---|---|
| `invalid_input` | 空值、类型错误 |
| `too_large` | 输入/输出字节超限 |
| `too_long` | 片长超过十分钟 |
| `unsupported` | 不支持的容器、视频/轨道或色彩模式 |
| `invalid` | 损坏、无法解码、输出校验不一致或资源失败 |
| `timeout` | 总期限/probe期限/本进程并发等待超限 |
| `tools_unavailable` | 工具、必要编码选项或资源隔离不可用 |

后续 worker 必须在处理前后复核家庭、成员会话、Google 选择和授权，再把视频真实字节数纳入配额；不能自动提高原 100/200 MiB 配额。展示副本保存、家庭共享、逐电视许可仍需要现有独立确认。视频缓存表、加密目的域、迁移、删除/解绑/备份恢复、同源读取、电视租约及混合轮播均未由本 helper 实现。

## 验证

`tests/test_media_videos.py` 从 FFmpeg lavfi 生成真实小型合成素材，检查 H.264＋AAC 完整解码、HEVC 10 位旋转、完整十分钟与超时长、损坏/假头/超限输入、实际外部轨道请求拒绝、真实子进程内存/超时/输出预算和临时清理。测试不接受只带 ftyp 的假 MP4 作为成功，也不跳过缺失工具。可通过测试环境 `MEDIA_TEST_FFMPEG`／`MEDIA_TEST_FFPROBE` 指定现有可信工具，不修改系统 PATH。

测试各轮及工具原件哈希在 ignored 作者报告中记录。真实 iPhone/Google 视频、Linux 资源控制与实体电视均须后续单独验证；合成 HEVC 旋转不等于验证了所有 iPhone、HDR 或真实媒体集成。
