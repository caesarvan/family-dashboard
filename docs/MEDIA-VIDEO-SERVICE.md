# 独立视频解码服务候选

本批只新增字节协议、Linux Unix socket 服务、定向测试及本文。基线 `6b52378abe751f9a61bc1d8b9d09d2b4d9f0ae93`；尚未连接 worker，也未构建或部署容器。相册、授权、配额、原 ID、确认回执、业务队列和数据库均继续归原 worker／MediaLibrary。本服务不接触它们。

## 最小接线合同

worker 侧调用：

```python
sanitize_remote_media_video(raw, mime_type, socket_path="/decoder-private/video.sock", timeout=900)
```

成功返回既有 `media_videos.VideoPreview`，包括完整 MP4 和 JPEG poster；失败抛既有固定 `MediaVideoError`，没有内部异常链、文件路径或 FFmpeg 诊断。参数 `socket_path` 是可信部署配置，不接受请求或 Google metadata 的路径。IPC 请求只含 `v / mime / length / sha256` 与源 bytes，不允许 URL、命令、文件名、账号、令牌或路径字段。

协议 v1 用 4 字节网络序长度与最多 2048 字节 ASCII JSON 头。严格拒绝重复 key、非有限数、布尔长度、未知字段和超限。输入最多 100 MiB，仅 `video/mp4`／`video/quicktime`；成功响应头只给固定 MP4／JPEG 的长度、SHA256、尺寸、时长及 hasAudio，再依次发送视频和封面。视频最多 64 MiB、封面最多 2 MiB、时长整数最多 600250ms（保留现有编码对齐容差）。读者校验完整长度、摘要、基本容器标记及 EOF 后才构造结果；收到半份响应、错误摘要、额外尾部字节或未知协议，均不返回 Preview。

每连接只处理一次，不支持请求流水线、写半关闭或自动重试。调用者必须保持连接到完整响应结束。客户端及服务端各使用从调用／接受时起的单个绝对 deadline，最长 900 秒；每块 64 KiB I/O 只使用剩余时间，不逐块续期。服务端只开放一个处理中 slot；额外连接收到固定 `timeout` 错误并关闭，不排无限解码队列。若对端在请求发送期间已关闭，客户端也可能得到固定 `tools_unavailable`；这不代表业务任务可自动重放，worker 仍拥有重试／撤权／deadline 规则。

## Linux 隔离和生命周期

生产入口 `media_video_service.py` 只允许非 root 的 Linux 主线程。启动参数仅为可信绝对 socket、临时目录和 FFmpeg／ffprobe 路径；不自动发现或下载工具。socket 目录与临时目录必须预先存在、属当前 UID、权限 0700；socket 新建为 0600。路径及祖先拒绝 symlink。已有 socket（包括 stale）一律拒绝启动，不猜测、不自动删除；退出只清除本进程记录的相同 device/inode socket，不删除替换路径或普通文件。

Linux 主线程的 SIGALRM 覆盖整个请求，包括接收、解码和发送。解码期间监视已完成请求后的连接断开或额外数据，通过取消信号中断主线程；SIGTERM／SIGINT 停止服务。取消使用 `BaseException` 穿透既有 codec 的一般错误包装，触发它原有的进程组终止、wait、临时目录 finally 清理。没有第二套 FFmpeg 参数、解码器或持久缓存。生产应给予足够停止宽限时间；主机 OOM 或 SIGKILL 不能执行 Python finally，因此独立容器退出和 tmpfs 回收仍是最后边界。

部署必须由后续独立接线落实：

- decoder `network:none`、非 root、只读根文件系统、cap-drop all、no-new-privileges，CPU／内存／pids 硬上限。
- decoder 不加载 `.env`、数据库、账号、来源目录或生产数据挂载；只与 worker 共享新专用 Unix socket volume，且两者使用匹配 UID。临时视频只放 decoder 的受限 tmpfs 私有目录。
- runtime 只需本批两模块、已审 `media_videos.py / media_images.py`、Python／Pillow 和精确 FFmpeg 工具；禁止把整个应用源码复制进 decoder。
- 精确 FFmpeg `7:7.1.5-0+deb13u1` 和工具摘要沿后续固定镜像读取；本批不选择或构建新的基础镜像，也不修改 Compose／Docker／现有发布工具。
- 768 MiB 是资源候选，尚未证明可承载完整 IPC；完整 100 MiB 源输入／64 MiB 返回、断连取消、并发忙拒绝与 worker 其他负载需在真实 Linux 容器另验。未因协议有界就宣称资源预算已通过。

## 验证范围

本机 Windows Python 实测没有 `socket.AF_UNIX`，公开生产入口明确拒绝；不能将本机 socketpair 测试写成 Unix socket 验收。定向测试使用真实连接字节流，通过同一个处理函数调用真实 FFmpeg，接收完整 VideoPreview 并再次独立完整解码；其余检查覆盖恶意请求、截断／坏摘要／尾部数据、错误头、绝对 deadline 和固定错误边界。恶意响应测试使用已真实净化的素材，不伪造成功解码。测试不调用 Google、不接真实账号、不启动 Flask 或访问数据库。

最终分轮执行、源码与原件摘要写入 ignored 作者报告。Linux Unix socket 的 UID／权限、单 slot、SIGALRM、断连、服务关闭与子进程清理尚需实际运行验证；不通过 SKIP 把这些边界写成已通过。生产接线、镜像构建、Compose 和端到端 worker／电视验收不属于本次交付。
