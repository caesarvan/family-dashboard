# Unix 解码服务的 Linux 生命周期验证

本批基于已审服务候选 `194ef7c7ce6779e5880e50603e7eba1a98785af5`，只准备测试与本文。当前 Windows 不支持生产入口所需 AF_UNIX；没有执行本批 Linux 用例、SSH、镜像构建或部署。原服务的 Windows 27 个唯一用例证据仍独立保留，不重复运行。

## 六个用例

1. **真实短片完整链路。** 非 root 子进程启动实际 `serve`，确认 UID、0700 socket/临时目录和 0600 socket。通过实际 Unix socket 传入 12 秒合成 H.264/AAC，返回真实 MP4/JPEG 并校验 SHA、时长；另用真实 FFmpeg 完整解码返回视频。退出验证原 socket、子进程及临时解码目录清理。
2. **实际文件系统权限。** 0750 目录、0660 socket 和软链路径均拒绝；已有 stale socket 被拒绝且原 inode 保留。没有伪造 stat，也未用 root 改 UID。
3. **单 slot 与绝对接收 deadline。** 第一连接发送不完整 body 并持续发送少量字节，第二连接得到固定 `timeout` 且关闭；第一请求不会逐块续期。结束后新请求能进入原槽位，服务保持存活。
4–6. **真实转码取消。** 分别触发断连、SIGTERM 和绝对 deadline。测试专用可执行 wrapper 仅向实际 FFmpeg 的 `display.mp4` 转码添加 `-re` 输入节流，随后 `exec` 为真正 FFmpeg；不睡眠冒充解码，也不返回伪造成功结果。必须先从 `/proc` 观察实际 FFmpeg 命令、PID/start ticks 和非空 codec 工作目录，再取消；断言真实子进程消失、临时目录清空，必要时原服务槽位恢复。

节流 wrapper 是随测试只读挂载、模式 0755 的固定 [helper](../tests/fixtures/media_video_realtime_ffmpeg.py)，不写入 `/tmp`，不改变 tmpfs 的 `noexec,nosuid,nodev` 限制。它使用本次 Python 镜像已有的 `/usr/local/bin/python3` 执行，并固定 exec `/usr/bin/ffmpeg`；不改业务源码、FFmpeg 参数实现或发布配置。取消测试证明真实 FFmpeg 被信号路径终止，**不**证明正常视频性能或无节流输入的时序。没有扩大到 100 MiB 源／64 MiB 完整 IPC 内存预算，后者需独立资源 profile。

## 运行合同

由协调者审查并在专用一次性 Linux 容器运行；要求 `network:none`、非 root、只读根文件系统、cap-drop all、no-new-privileges、CPU/memory/pids/tmpfs 限额。只挂载本轮合成证据输出，不挂载生产数据、`.env`、凭据或 Docker socket。

使用固定源码的四个运行模块 `media_video_service.py`、`media_video_transport.py`、`media_videos.py`、`media_images.py` 及本测试文件，Python/Pillow/pytest 和精确 FFmpeg/ffprobe。工具版本与 SHA、四模块 SHA 和测试 SHA 将写入实际结果，不可用 Windows 工具身份替代 Linux 工具身份。

项目内闭包为本测试、固定节流 helper 及四运行模块，无旧测试 helper、Flask、worker 或数据库依赖。按每个运行模块的实际 `__file__` 记录路径、SHA，并把对应目录明确传给隔离子进程；支持新 service/transport 只读挂载目录优先、已验 codec 位于 `/app` 的布局，源码目录无需可写。子进程不继承父进程的应用环境或 PYTHONPATH。

环境：

- `MEDIA_SERVICE_TEST_EVIDENCE_DIR`：证据 mount 下**尚不存在**的新绝对目录，父目录已存在；测试独占创建。重复运行必须换路径。
- `MEDIA_SERVICE_TEST_TEMP_ROOT`：可选，默认 `/tmp`；应为短路径 tmpfs。每例创建权限 0700 的 `vsl-*` 独占目录，socket 路径最多 103 字节。
- `MEDIA_TEST_FFMPEG` / `MEDIA_TEST_FFPROBE`：可信已安装工具绝对路径；未给时只使用当前容器 PATH。测试不会安装、下载或更新软件。
- `MEDIA_SERVICE_TEST_FFMPEG_WRAPPER`：可选固定只读 helper 的路径；缺省为测试旁 `fixtures/media_video_realtime_ffmpeg.py`。必须可执行且与该固定文件 SHA 相同。取消测试要求 FFmpeg 实际路径为 `/usr/bin/ffmpeg`，保持本轮镜像合同。

执行 `python -B -X utf8 -m pytest -q -p no:cacheprovider tests/test_media_video_service_linux.py --junitxml=<本轮新路径>`。Windows/root/缺少 AF_UNIX、`/proc` 或真实工具时明确失败，不能标为 SKIP/PASS。Windows 准备仅可 AST 和 `--collect-only`；收集到 6 项不表示运行通过。最终 supervisor 需另存固定来源/镜像、argv、started、原 PID、stdout/stderr 和退出码。

## 原件与清理

每例保存服务 argv、仅明确允许的子进程环境变量名、UID/socket mode、实际 `/proc` 子进程身份、取消与槽位恢复观测、stdout/stderr SHA；真实返回视频、独立解码日志和合成源单独保留。正常清理使用实际 SIGTERM 与 codec finally；若不得不紧急 SIGKILL，只对记录的子孙 PID 且 start ticks 仍一致者操作，明确写 `forcedCleanup=true` 并使测试失败，不把强制清理算作正常回收。

本工具只删除自身刚创建且再次检查的 `vsl-*` 合成目录，先保存日志和剩余临时文件列表。没有生产路径、原文件覆盖、外部 provider 或数据库。Linux 真实结果待独立执行、复核后补充，不从本准备提交推断服务已接入 worker 或可以上线。
