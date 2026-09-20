# 视频五服务控制器：隔离 Linux 演练

这是**演练准备工具**。作者仅在本机完成代码与离线检查，没有执行 SSH、Docker、迁移、恢复或生产发布。实际运行结果必须来自后续独立审查后、协调者执行的唯一新句柄。

## 验证什么

使用固定 `d0c8362` 控制器、真实不可变镜像与虚构两户三库，顺序完成两个独立项目：

1. `success`：真实旧四服务运行 → 原 `stage` → 原 `activate` → 真实完整组 71→73／平台 9 表迁移、app-only 停止保全 → 实际新五服务与 Nginx HTTP 健康 → 全部停止 → 文档中的完整组恢复程序 → 原 `verify_rollback` 核对 71／9。
2. `failure`：新建另一套两户三库；真实备份后将第二户数据库设为不可写，使非 root 迁移实际失败。停写读取必须实证第一户已到 73 表、第二户仍 71 表、平台仍 9 表。核对原控制器已收停本次 helper、没有重试／自动恢复，保留失败回执；再单独执行完整组恢复及原回退核验入口。

第二项不会在第一项失败后继续。每项均保留实际 argv、PID、stdout／stderr、终态、原始阶段回执、已确认 CID 及最后收停证据。开始时同时拒绝已存在的 Compose 项目与独立演练标签；数据卷和 socket 卷任一已存在都会在创建卷前拒绝。完成空项目／新卷准入前，不发现并接管同名旧容器用于清理。创建结果不明不按名称猜测清理，不返回成功；不删除容器、卷或失败数据，后续清理须另行审核。

## 必须明确的适配边界

- `Controller.stage/activate/data_call/helper_state/stop_data_helper/verify_rollback` 与真实迁移代码保持原文件字节，`FixtureController` 仅覆盖 `evidence` 为演练来源核验。它核真实 b8 包、双镜像构建原件、固定工具源码与完整 fixture hash；不制造资源或独审 PASS。报告固定 `productionPlanAdmissionExercised=false`，正式 `prepare` 的实际准入另验。
- 镜像固定 app `75d2cf…`、decoder `005cc3…`、旧 app `a783c5…`、web `1ae82d…`，不构建镜像。只创建 `fd-vcr-<随机16位>-success|failure` 项目及其卷；不读取生产 `.env`／数据库，不使用生产项目、端口或路径。
- 私有合成环境、marker、部署根目录、manifest、compose、nginx 配置、loopback HTTP 和镜像标签前缀是显式 fixture 适配。旧安装目录是完整声明的最小源码 fixture，包含原 Git app／requirements 和独立旧 Expo 哨兵，不冒充完整生产安装树。候选源除 compose/nginx 外逐字节保留真实包。真实数据库由旧 app 的登录／邀请／加入／待办 API 生成；保留虚构个人财务和 audit 行。
- 应用 `PUBLIC_ORIGIN` 保留种子的 `https://steady-rehearsal.invalid`，`COOKIE_SECURE=1`；种子通过 Flask 本地请求使用该 HTTPS 来源，不解析或连接这个域名。控制器仅用另一个 `http://127.0.0.1:<端口>/healthz` 做无认证健康检查；两者分别记录为 `publicOrigin`／`healthOrigin`，不放宽应用的 HTTPS 校验，也不据此声称实际 TLS 已验证。
- 第二轮实际 Docker 内部网络没有发布该主机端口。因此演练传输层只将上述精确健康请求映射为主机 curl → 已核 Nginx 的内部 bridge IPv4:80 → app；不改原控制器或 compose，不关闭 `internal`，不直接检查 app。读取前交叉核 web CID／固定镜像／项目标签／运行态、唯一内部网络 ID／endpoint／IPAM 子网；HTTP 200 后再核同 CID／PID／endpoint。禁代理、重定向和非 HTTP，保留 30 秒上限。`health-transport-*.json` 与命令原件明确记录请求和实际 URL、归属、状态及失败；不再宣称验证了主机端口发布。依据 [Docker internal 说明](https://docs.docker.com/reference/compose-file/networks/#internal) 和 [bridge 主机访问说明](https://docs.docker.com/engine/network/drivers/bridge/)，实际可达性仍须后续 Linux 新轮证明。
- app／media 各 192 MiB、sync 128 MiB、web 64 MiB、decoder 384 MiB，总 960 MiB；无 swap，实际迁移 helper 单独 384 MiB。decoder 检查先核实际 384 MiB，再仅映射限额字段调用原 768 MiB 合同检查；其余用户、命令、socket、权限和隔离条件不放宽。最多五个服务同时运行，旧服务先全停再启动新服务。
- 备份 timer 使用独占 fixture 状态，不调用 systemd；不模拟 Docker 成功结果、迁移或恢复算法。此处验证控制流程，不证明真实 timer 调度／备份竞态、生产 TLS 或生产峰值容量。生产 384／768 MiB 大媒体资源实验必须单独报告，不能相加成并发证明。
- app、sync、media 和 web 仅接入合成内部网络，网络标记 `internal`；decoder 和 setup／migration／restore helper 无网络。没有真实账户、云凭据或外部媒体。

## 准备与执行

离线 `prepare` 绑定干净固定 Git 提交、完整真实包及构建原件，输出全部执行依赖、真实来源文件、种子和文档恢复程序；目标镜像内不需要 Git 或 pytest。Windows 长路径原件须使用 `\\?\` 绝对路径。

```text
python -B deploy/media_video_controller_rehearsal.py prepare --repo <本分支干净checkout> --head <完整提交> --package-dir <实际b8包目录> --package-sha256 <实际包SHA> --build-dir <实际双镜像build-r1> --build-sha256 <实际build.json SHA> --output-dir <全新准备目录>
```

协调者审查输入 SHA 后，将完整准备目录复制到隔离路径，以该目录的固定 operator 执行。只允许 root、Linux、`python -B`，禁止环境 Docker／Compose 选择器。

```text
python3 -B <准备目录>/operator/deploy/media_video_controller_rehearsal.py run --bundle <准备目录> --input-sha256 <已审input.json SHA> --output-dir /tmp/family-dashboard-controller-rehearsal/run-<随机16位hex>
```

启动前固定三次可用内存读取（间隔 1 秒），均须不低于 1088 MiB；任何一次不足即 `preflight_blocked`、零新容器，不等待高点、不降低门槛、不暂停生产。运行期间每 250 ms 监控，低于 256 MiB、读取失败或监控停滞会中止，并只收停已核本轮 CID；恢复动作不得在压力中止后继续。原命令句柄持续跟到终态，不重复启动。

首次或后续准入读取异常保留已采样记录及 `preflight_failed`、零容器终态；监控线程无法启动时保留原异常，不 join 未启动线程，也不进入任何场景。旧 a767 本机准备包留作历史证据；审查后的最终提交须由协调者重新准备，不能沿用旧输入 SHA。

`input.json` 绑定原始依赖，`adaptations.json` 逐项记录差异，`result.json` 分开记录两场景、fixture 限额、失败／收停、生产准入未覆盖边界。实际 Linux `passed=true` 仅能在两场景及全部收停证据通过后形成；本页不预先声明运行通过。

首次 Linux 演练在种子 helper 启动应用时因把 HTTP 健康地址误作 `PUBLIC_ORIGIN` 而失败；尚未启动旧四服务或执行 stage／activate，第二场景未运行。该轮失败原件保留；本次来源拆分需重新独审，并由协调者使用新的输入和输出目录执行，不能将旧轮记为通过。

第二轮已到真实迁移／app-only 保全／新五服务，最后主机端口健康连接被拒绝而整轮失败；候选和 helper 已收停，数据库已迁移到 73，未自动回退，第二场景仍未运行。其原件及现场保持；本次健康传输修正只能在新的准备与运行目录验证，不重放旧 attempt。

第三轮真实健康检查返回 HTTP 200，原 activate 已完成，随后恢复包装程序因备份文件已经存在而拒绝继续。四个既存文件经停写只读核对，均与 proof 中完整备份组逐字节一致；原备份本就保留在数据卷中。修正只调整恢复前的备份文件准备：先核对整个组，接受内容相同的普通文件，拒绝符号链接、目录或内容冲突，缺失文件才独占创建。固定文档中的 SQLite 恢复程序和原 verify_rollback 保持不变。第三轮仍为失败，全部测试容器已停止，第二场景未运行；修正须经独审并使用全新演练目录验证。

该修正首次准备时因新增定向测试文件未列入固定源码清单而被拒绝，未创建准备包或启动 Docker。清单已仅补入 `tests/test_media_video_restore_fixture.py` 这一明确路径，其余范围核对继续执行。
