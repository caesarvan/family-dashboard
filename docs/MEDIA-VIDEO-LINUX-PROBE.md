# Linux 视频处理与内存候选探针

本工具只准备和运行隔离合成试验，不是正式发布适配器。当前未执行 SSH、Docker 构建或 Linux 视频测试，不能据此声明服务器已支持视频。部署架构、无凭据／无网络解码服务、媒体响应并发门禁及实际用户验收另行决定。

历史准备提交 `7805149` 保留旧 Fernet 工具，但不执行其 `crypto64` baseline。当前工具依赖合并 `b953bc8` 引入已审 AES 候选 `f667627`，使用 `response64`／`worker100` 两个真实应用 profile；本轮仍未执行它们。最终执行必须再绑定已审内存门禁／响应关闭与 TV 的完整组合 head，不能使用当前准备树冒充最终候选。768 MiB 仍是待测值，不是生产预算批准。

## 固定输入与阶段

固定父镜像为 `sha256:a783c58c882748d273c5956e2d94a43c99261c61c6b41f0489118d9fd96f6654`。准备 context 明确列出 55 个运行 Python 文件、`requirements.txt`、3 个既有合成 fixture helper、原 `tests/test_media_videos.py` 和 2 个工具输入，共 62 项。完整应用在 `/probe/runtime` 加载，不借用父镜像中未绑定的业务源码；启动前核对清单，运行后记录实际加载路径/hash。无真实数据库、账号或环境文件；Flask／worker 只对新建合成库运行。全部输入从明确 Git head 读取，逐一对比工作区字节，准备后仍重哈希验证精确清单。

工具先由非作者审查。每个后续阶段需集成人批准固定输入，分开执行，不连续自动推进：

1. `prepare` 可离线生成新目录中的最小 Docker context。先由集成人只读确认父镜像 OS／可信 Debian 源中 FFmpeg 的**精确版本**，作为 `--ffmpeg-version`；没有猜测的默认版本。集成人已只读核实父镜像为 Debian 13 trixie/amd64，官方候选版本 `7:7.1.5-0+deb13u1`（amd64 包 SHA256 `8669bc77e55393c14e0dd257ba9a916007cb6da0e1074c9b5e1d53812024f2af`）；实际 apt 可用性、安装版本和工具 SHA 仍须 build 读回，不能改成 latest。示例占位值不能直接执行。
2. `build` 仅创建无标签候选镜像，不覆盖任何已有镜像／tag／服务。网络只用于新镜像层安装精确版本的 apt FFmpeg 以及固定 pytest 9.0.2；不在宿主安装工具。构建后，从从未启动的临时容器取回 `toolchain.json`，冻结完整 dpkg/pip 版本、ffmpeg／ffprobe SHA 和版本输出及候选 immutable image ID；逐一确认实际 Python 运行依赖符合冻结 requirements。审查这些实际值后才能 run。依赖传递包以实际镜像身份和清单冻结，不宣称全部 apt 依赖已提前锁版。
3. `run` 每次只选一个 `core`／`resources`／`response64`／`worker100` profile，建立独占新容器和输出目录。首次候选为 768 MiB；1024 MiB 仅是独立待批准选项，不能失败后自动加大或重跑。

```text
python -B deploy/media_video_linux_probe.py prepare --source <fixed-checkout> --source-head <40hex> --output <new-prepared-dir> --ffmpeg-version <exact-debian-version>
python -B deploy/media_video_linux_probe.py build --prepared <prepared-dir> --output /tmp/family-dashboard-media-probe/<new-build-run>
python -B deploy/media_video_linux_probe.py run --prepared <prepared-dir> --build-result <build-result.json> --output /tmp/family-dashboard-media-probe/<new-core-run> --profile core --memory-mib 768
```

每个 profile 使用分别批准的全新输出和容器；不共享正在写入的目录。caller 只连接宿主 Unix Docker socket，不实现 SSH，不读取 Docker 登录或代理配置。保留每个命令 argv/PID/开始时间/stdout/stderr/终态和散列，不因观察超时发起第二次运行。容器最终 inspect、OOM 状态及原 ID 保留，递归散列真实合成数据库和所有 proof 原件；停止操作只允许本次新创建的 ID，停止后仍留给审查者核对，清理需另行明确执行。不得操作生产容器。

## 资源与隔离

宿主约 1967 MiB RAM，先前 available 约 1254 MiB；这是历史观测。每次 build/run 前读取实时 `/proc/meminfo`，要求当前 MemAvailable 至少为候选上限再加 384 MiB 宿主余量；不满足即阻断。这个门禁不能阻止之后其他进程增加用量，也不证明足以长期生产运行。

测试容器使用 network none、UID/GID 10001、cap-drop ALL、no-new-privileges、read-only 根文件系统、1 CPU、768 MiB 内存且禁用 swap、128 PIDs、128 文件描述符。只有新建合成输出目录 `/proof` 可写挂载，无生产路径／凭据／socket 挂载；`/tmp` 是最大 384 MiB、noexec/nosuid/nodev tmpfs，计入同一 cgroup 内存。进程使用清空后的固定环境。容器内核对 memory/cpu/pids/swap 实际上限；保留 `memory.peak`、`memory.events`、`cpu.stat`、`pids.peak`。

解码器自身的 1.5 GiB 地址空间上限不会取代更小的容器总上限。source buffer、临时文件、输出和加密副本必须一起计入，不能拿 2 MiB 小视频成功来证明 64 MiB 完整响应适用原 app／worker 384 MiB 预算。没有四并发压力测试或生产加压。

## 精确试验

- `core`：原模块全部 **16 个固定节点**，检查实际 collection、JUnit 无 failure/error/skip。包含完整十分钟 H.264、HEVC 10 位旋转、HDR 明确拒绝、损坏与超限、禁止外部引用、POSIX rlimit／超时／临时清理。只运行该文件，不运行 253 项后端矩阵。缺工具或旧 FFmpeg 不支持必要选项应真实失败，不能跳过或改为假成功。
- `resources`：真实 FFmpeg 生成 1920×1080、30 fps、12 秒合成 H.264＋AAC 和 HEVC 10 位＋AAC／90 度旋转，按原模块完整转换并验证时长、尺寸和当前 AES 加密 round trip。H.264 文件用合法顶层 `free` box 填充到 100 MiB，测源文件缓冲上限；这不代表 100 MiB 高复杂度画面的编码负载。逐项记录真实输出尺寸/长度/hash、codec 墙钟耗时、全容器进程 RSS 采样峰值、cgroup 使用峰值和 CPU 时间。12 秒只属于性能样本，产品仍支持最多十分钟；完整时长边界由 core 单独验证。
- `response64`：真实 FFmpeg 生成并净化完整短 MP4，再追加合法顶层 `free` box 到 64 MiB，并独立完整解码。通过真实 MediaLibrary 完成／确认入口建立私密尺寸 fixture，释放原缓冲后，实际 Flask route 从 SQLite 读取、AES 解密、完整消费 WSGI iterable，调用并完成 response.close。核对原 ID/revision、完整响应 hash/长度、cipher 长度、确认回执重放、唯一记录和 reservation 归零。**填充后的 64 MiB 是响应大小夹具，不是 sanitizer 的真实输出或真实 Google 导入**；不把这个构造称为 worker 成功。
- `worker100`：同样真实生成完整 1080p 短 MP4、合法填充至 100 MiB；合成 Google transport 从文件分块读取，不在测试替身中额外常驻一份 100 MiB body。使用真实 GooglePhotosPicker 的 URL/元数据/下载上限校验、真实 worker claim/download、FFmpeg、AES seal、SQLite commit、本人确认和后续完整 WSGI 响应关闭；只替换 provider 网络传输，不替换业务方法/DTO/加密器/解码器。记录 transport 实际读满并关闭、临时解码清理、实际缓存和回执。

两个应用 profile 复用 `test_household_media`、`test_journey_documents`、`test_google_photos_picker` 的已存合成账号／登录／metadata helper。运行容器自身 network none，并阻断 Python socket 连接。只使用合成 cookie/token，不读取真实账号。真实数据库仅在本次新 `/proof/household`，供独立核对；没有网络服务监听、生产挂载或并发压测。失败、OOM 或超时必须原样保留，不通过降低产品 64 MiB 上限换绿。

20 ms 进程 RSS 采样可能错过极短峰值，而且共享页求和可能重复；cgroup `memory.peak` 包含 tmpfs／缓存，是总预算判断的主要证据。每个 profile 新容器使累计 peak 有清晰范围。应用 profile 的 cgroup 累计 peak **包含 fixture 准备阶段**；额外分阶段记录准备、下载入库、SQLite解密/完整WSGI关闭的 RSS/内存采样和耗时，不能把采样当作可重置的精确阶段峰值。样本只用于选择下一轮候选预算／并发策略，不能外推真实 Google、所有 iPhone 或实体电视。

`tests/test_media_video_linux_probe.py` 只离线检查精确选择／依赖闭包、命令约束、路径、实际文件分块读取／填充盒构造和真实 CLI help，不执行 Docker／FFmpeg。源码冻结和这些工具测试不代表 Linux 试验已完成。
