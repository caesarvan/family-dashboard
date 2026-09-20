# Linux 视频处理与内存候选探针

本工具只准备和运行隔离合成试验，不是正式发布适配器。当前未执行 SSH、Docker 构建或 Linux 视频测试，不能据此声明服务器已支持视频。部署架构、无凭据／无网络解码服务、媒体响应并发门禁及实际用户验收另行决定。

当前源码基于 `7436084170728bfeed9f229c67a87f113b8e1a29`。`crypto64` 和 `resources` 内的加密段仅是旧 Fernet 实现的历史基线；尚未定版的新 AES-GCM 路径不在此轮范围。最终候选必须绑定已审 AES 实现，另测完整 SQLite 读取→解密→response 与下载→加密→commit，不能以该基线或独立加密函数替代。768 MiB 也是待测候选值，不是生产预算批准。

## 固定输入与阶段

固定父镜像为 `sha256:a783c58c882748d273c5956e2d94a43c99261c61c6b41f0489118d9fd96f6654`。候选仅覆盖已审 `media_videos.py`、`media_images.py`、`media_crypto.py`、原 `tests/test_media_videos.py` 和本探针；不复制数据库、配置、账号或环境文件，不启动 Flask／worker。全部输入从明确 Git head 读取，逐一对比工作区字节，准备后仍重哈希验证精确清单。

工具先由非作者审查。每个后续阶段需集成人批准固定输入，分开执行，不连续自动推进：

1. `prepare` 可离线生成新目录中的最小 Docker context。先由集成人只读确认父镜像 OS／可信 Debian 源中 FFmpeg 的**精确版本**，作为 `--ffmpeg-version`；没有猜测的默认版本。示例占位值不能直接执行。
2. `build` 仅创建无标签候选镜像，不覆盖任何已有镜像／tag／服务。网络只用于新镜像层安装精确版本的 apt FFmpeg 以及固定 pytest 9.0.2；不在宿主安装工具。构建后，从从未启动的临时容器取回 `toolchain.json`，冻结完整 dpkg/pip 版本、ffmpeg／ffprobe SHA 和版本输出及候选 immutable image ID。审查这些实际值后才能 run。依赖传递包以实际镜像身份和清单冻结，不宣称全部 apt 依赖已提前锁版。
3. `run` 每次只选一个 `core`／`resources`／`crypto64` profile，建立独占新容器和输出目录。首次候选为 768 MiB；1024 MiB 仅是独立待批准选项，不能失败后自动加大或重跑。

```text
python -B deploy/media_video_linux_probe.py prepare --source <fixed-checkout> --source-head <40hex> --output <new-prepared-dir> --ffmpeg-version <exact-debian-version>
python -B deploy/media_video_linux_probe.py build --prepared <prepared-dir> --output /tmp/family-dashboard-media-probe/<new-build-run>
python -B deploy/media_video_linux_probe.py run --prepared <prepared-dir> --build-result <build-result.json> --output /tmp/family-dashboard-media-probe/<new-core-run> --profile core --memory-mib 768
```

`resources` 和 `crypto64` 使用分别批准的全新输出和容器；不共享正在写入的目录。caller 只连接宿主 Unix Docker socket，不实现 SSH，不读取 Docker 登录或代理配置。保留每个命令 argv/PID/开始时间/stdout/stderr/终态和散列，不因观察超时发起第二次运行。容器最终 inspect、OOM 状态及原 ID 保留；停止操作只允许本次新创建的 ID，停止后仍留给审查者核对，清理需另行明确执行。不得操作生产容器。

## 资源与隔离

宿主约 1967 MiB RAM，先前 available 约 1254 MiB；这是历史观测。每次 build/run 前读取实时 `/proc/meminfo`，要求当前 MemAvailable 至少为候选上限再加 384 MiB 宿主余量；不满足即阻断。这个门禁不能阻止之后其他进程增加用量，也不证明足以长期生产运行。

测试容器使用 network none、UID/GID 10001、cap-drop ALL、no-new-privileges、read-only 根文件系统、1 CPU、768 MiB 内存且禁用 swap、128 PIDs、128 文件描述符。只有新建合成输出目录 `/proof` 可写挂载，无生产路径／凭据／socket 挂载；`/tmp` 是最大 384 MiB、noexec/nosuid/nodev tmpfs，计入同一 cgroup 内存。进程使用清空后的固定环境。容器内核对 memory/cpu/pids/swap 实际上限；保留 `memory.peak`、`memory.events`、`cpu.stat`、`pids.peak`。

解码器自身的 1.5 GiB 地址空间上限不会取代更小的容器总上限。source buffer、临时文件、输出和加密副本必须一起计入，不能拿 2 MiB 小视频成功来证明 64 MiB 完整响应适用原 app／worker 384 MiB 预算。没有四并发压力测试或生产加压。

## 精确试验

- `core`：原模块全部 **16 个固定节点**，检查实际 collection、JUnit 无 failure/error/skip。包含完整十分钟 H.264、HEVC 10 位旋转、HDR 明确拒绝、损坏与超限、禁止外部引用、POSIX rlimit／超时／临时清理。只运行该文件，不运行 253 项后端矩阵。缺工具或旧 FFmpeg 不支持必要选项应真实失败，不能跳过或改为假成功。
- `resources`：真实 FFmpeg 生成 1920×1080、30 fps、12 秒合成 H.264＋AAC 和 HEVC 10 位＋AAC／90 度旋转，按原模块完整转换并验证时长、尺寸和加密 round trip。H.264 文件用合法顶层 `free` box 填充到 100 MiB，测源文件缓冲上限；这不代表 100 MiB 高复杂度画面的编码负载。逐项记录真实输出尺寸/长度/hash、codec 墙钟耗时、全容器进程 RSS 采样峰值、cgroup 使用峰值和 CPU 时间。12 秒只属于性能样本，产品仍支持最多十分钟；完整时长边界由 core 单独验证。
- `crypto64`：**独立容器**中真实合成 64 MiB 非零字节，使用现有 `MediaCipher` 的 `media-video` purpose 执行完整 Fernet seal/open 并比较原文；保留 64 MiB source 与约 89 MiB ciphertext，观测内部 copies。它是加解密内存试验，明确不是有效 MP4，也不是视频格式验收。失败、OOM 或超时必须原样保留，不通过降低 64 MiB 上限换绿。

20 ms 进程 RSS 采样可能错过极短峰值，而且共享页求和可能重复；cgroup `memory.peak` 包含 tmpfs／缓存，是总预算判断的主要证据。每个 profile 新容器使累计 peak 有清晰范围。样本只用于选择下一轮候选预算／并发策略，不能外推真实 Google、所有 iPhone 或实体电视。

`tests/test_media_video_linux_probe.py` 只离线检查精确选择、命令约束、路径和真实 CLI help，不执行 Docker／FFmpeg。源码冻结和这些工具测试不代表 Linux 试验已完成。
