# 视频完整 IPC 与响应资源验收工具（候选）

本工具只准备独立实验，不构建、部署或修改生产。原 `media_video_linux_probe.py` 及其 768／1024 MiB 单容器 profile 保持不变，不能用其结果代替这里的 384 MiB worker 验收。

## 两个独立 profile

每次 `run` 新建两容器，application **384 MiB**、decoder **768 MiB**，均限制 1 CPU、128 pids、无 swap、只读根、非 root UID 10001、无网络、drop all capabilities、no-new-privileges。两个 profile 各用全新输出与容器，不复用累积 cgroup 峰值，不提高限额重试。

- `worker100`：decoder 先用真实 FFmpeg 生成 12 秒合成 MP4，追加合法 `free` box 到 100 MiB，再完整解码验证。application 使用真实 Google Photos Picker URL／元数据解析和有界下载代码，只有传输响应替换为该合成文件；真实 worker 经配置的私有 Unix socket 调用另一容器的实际 decoder，再执行 AES、SQLite、确认、确认幂等重放和本人完整 WSGI GET／close。100 MiB 测试源缓冲量，不代表 100 MiB 的编码复杂度。
- `response64`：decoder 生成并真实净化短片，给净化后的 MP4 追加合法 `free` box 到 64 MiB，再实际完整解码。通过真实 staging／加密／SQLite／确认流程建立明确尺寸 fixture；读取真实成员端点的整个 WSGI iterable，不拼接额外完整响应，检查摘要、长度、关闭和释放许可。它不是声称 sanitizer 实际输出 64 MiB，也不冒充真实 Google 导入。

两者均检查未共享视频的另一成员拒绝、原 ID／revision 不变、确认不产生第二条记录、配额释放、视频独立 AES envelope；持有响应期间再次读取得到 `video_busy`。Python 网络 guard 仅允许精确 `AF_UNIX /decoder-private/video.sock`，拒绝其他 Unix 路径、TCP 和 DNS。配置 IPC 后，本地 sanitizer 被显式拒绝；真实 worker 若退回本地解码即失败。

## 输入与命令

先把本工具审查合入最终源码，再固定 application／decoder 的完整 `sha256:` 镜像 ID。application 从镜像的 `/app` 加载；decoder 从 `/decoder` 加载。manifest 绑定全部显式应用根模块（含 `media_playback_progress.py`、transport）、requirements、四个 decoder 模块与探针。每个实际已加载本地模块再次核路径与 SHA，不能加载旧 parent 或工具目录覆盖的业务源码。

```text
python -B deploy/media_video_ipc_resource_probe.py prepare --source <固定 checkout> --head <完整 commit> --application-image sha256:<应用镜像> --decoder-image sha256:<decoder镜像> --output <全新 prepared目录>
python -B <已冻结 probe.py> run --prepared /tmp/family-dashboard-media-ipc-probe/<本批>/prepared --output /tmp/family-dashboard-media-ipc-probe/<本批>/worker100 --profile worker100
python -B <已冻结 probe.py> run --prepared /tmp/family-dashboard-media-ipc-probe/<本批>/prepared --output /tmp/family-dashboard-media-ipc-probe/<本批>/response64 --profile response64
```

准备阶段不访问 Docker。Linux `run` 只使用本地 Docker Unix endpoint、已存在不可变镜像和新专用 `/tmp` 根；不接受任意环境、socket 地址、provider URL 或额外挂载。协调者传输前后校验 `prepared.json`、`tools/inputs.json`、`tools/probe.py`，保留各自独占原件。输入工具目录 0755、两个文件 0644，只读挂载；没有在 `noexec` 临时盘生成可执行脚本。

decoder 只挂载冻结工具、自己的合成证据／媒体 fixture 与唯一私有 socket 目录，**不挂 application 的 SQLite 目录**。application 只读挂载合成 fixture，单独保存 SQLite 与成员测试证据。两者匹配 UID，socket 目录 0700／socket 0600。decoder 自己的解码临时目录使用限额 tmpfs。主机空闲内存不足直接拒绝，不占用生产 volume，不修改生产服务。

主机预算采用明确的新策略：每个 profile 启动前，读取 3 次 `/proc/meminfo` 的 `MemAvailable`（t0、t1、t2，读数间隔各 1 秒，总计 2 秒），**全部至少 1280 MiB** 才继续。任何一读不足或读取失败均保存 `preflight.json` 与 `result.json` 的 `preflight_blocked`，不创建容器、不自动等待下一次高点。这个启动阈值是实验准入政策，并非实测峰值；两个容器仍严格保持 384／768 MiB。

通过预检后，独立只读线程从镜像核验前持续到本次两个容器清理结束，每 250 ms 读取主机内存，并即时保存 `host-memory-samples.jsonl`。低于 **256 MiB**、读取／线程异常、采样超过 1 秒未完成均锁定中止，之后内存回升也不恢复。阻塞的 Docker attach 和 decoder 就绪等待都会检查该信号；协调者中止当前 CLI，并立即 `kill` 仅本次已记录的容器 ID，再读终态和日志，不逐个等待 10 秒停止期。先创建并记录两个容器 ID，再启动任何负载。每个 create 最多等待 10 秒，先取得原 ID 再消费中止信号，避免丢失可安全清理的目标；创建本身不会启动负载。若 create 超时但没有返回 ID，结果保留 unconfirmedCreate，可能已创建的未启动容器不猜测 ID、不扩大清理范围，整轮失败。监测线程不执行 Docker，不竞争命令原件编号。正常路径仍使用既有有序停止／验证。

线程启动本身失败时，也保留锁定原因、threadStarted=false 和独占失败回执，不 join 尚未启动的线程。`host-memory.json` 保存样本数、实际最小主机可用量、锁定原因和线程终态；压力中止的结果必须为 `aborted`，缺失／部分内层回执不得补成成功。主机采样最小值不等于两个 cgroup 同时峰值，也不构成生产负载保证。监测和预检只用于本次隔离验收，不扩展为生产监控。

## 证据与判定

每个 Docker 操作保留固定 argv、开始时间、子进程 PID、原 stdout／stderr、SHA、退出码；预算版另记实际 childExitCode，中止／超时的协调者 exitCode 125／124 不冒充子进程真实退出码；只跟踪原句柄，未知结果不重放。每个角色分别保存 cgroup 实际限额、`memory.peak/events`、CPU／pids、退出码、实际加载模块与工具摘要。峰值包含各自 fixture／应用启动全过程，不把阶段采样或两个容器的数值相加后冒充单进程峰值。

两个容器必须都正常退出、无 OOM 或 memory max 事件，应用完整流程成立且所有源码匹配才通过。失败也停止**仅本次新建并记录的容器 ID**，保存终态并保留容器，不自动删除／恢复／扩大限额。因 SIGKILL/OOM 缺少内层完成回执即失败，不能靠外层日志补成成功。

本机只运行小文件、命令约束、网络 guard、源码闭包与失败判定的离线工具测试，不运行 Docker、大媒体或本轮 Linux profile。实际结果待 root 独审工具与输入后运行。Flask WSGI 客户端和真实 IPC 的资源实验，不等同 Gunicorn 四线程负载、真实 Google、实体电视、最终浏览器或生产验收；最小 decoder 镜像的短片启动证据与本完整资源实验也分别记录。

本次离线 R1 实际 21／21；随后只复验临时盘挂载调整影响的 2 项，R2 2／2、19 项未选。共 21 个唯一用例、23 次执行；两个轮次的命令、开始与终态、源码前后摘要、stdout／stderr／JUnit 保留在 ignored `test-results/media-video-ipc-resources-r1` 和 `r2`。此计数不是 Linux 资源通过证明。

预算策略增量另存 `test-results/media-video-ipc-resources-budget-r1`／`r2`／`r3`：实际分别 14／14、2／2、4／4，共 17 个唯一新增用例、20 次执行；旧 21 项未重跑。各轮均保存运行时三文件完整快照与哈希，后两轮只验证新增协调顺序及受影响的 CLI 退出码边界。覆盖启动不足／读失败、256 MiB 边界、锁定中止、线程异常／停滞、在途 child 中止、仅本次 ID 清理、正常顺序和未知 create 结果。它们是离线控制流程证据，未运行 Docker 或本轮 Linux 资源验收。

独立审查指出原三读间隔为 0.5 秒、线程启动失败时 join 未启动线程会截断回执；原提交和反例保持。修正后 R4 仅执行 3 个采样参数用例及新增的线程启动失败协调者用例，实际 4／4、35 项未选；原件与三文件快照在 `test-results/media-video-ipc-resources-budget-r4`。没有重跑之前的预算／业务全组，也不表示已在 Linux 运行 profile。
