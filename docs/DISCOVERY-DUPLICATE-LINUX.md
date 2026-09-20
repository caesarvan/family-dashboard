# 重复照片提示：四请求 Linux 资源验证

本批资源R2已实际通过并独审：63dc源／b63镜像，四个真实请求均200且服务端重叠，独立恢复200；扫描计数8／恢复2、请求期间图片／视频BLOB读取0，数据库摘要一致。384／64MiB两容器未触发内存事件，123件原件、监控及owned收尾已核；仅证明这组元数据负载。旧R1绑定455源，在四请求开始前因客户端只读数据库观察失败，外层又报缺失 `database.json`，两层失败保留。本批已于2026-09-20 23:06:47（北京时间）激活，23:07:24只读回读通过；非作者生产审计已通过。该上线事实不扩展资源测量范围，完整身份与证据见 [集中验收](DISCOVERY-ACCEPTANCE.md#discovery-release)。`deploy/discovery_duplicate_linux_probe.py` 只运行一次隔离 profile，不构建镜像、不访问生产、不降低限额、不自动重试；沿用已审 Docker 命令原件、主机内存监控和 cgroup 读取 helper。

## 固定输入与执行

在含已审 discovery 发布适配及本工具的完整组合源码上，使用固定 `deploy.build_discovery_release.verify_package`（`local-photo-r1-discovery`）核包，绑定真实单镜像 build 回执。准备过程只读 Git / 包 / build，并写全新输出：

```text
python -B deploy/discovery_duplicate_linux_probe.py prepare --source-root <固定源码目录> --expected-head <40位HEAD> --package <正式包目录> --package-sha256 <SHA> --build <实际build.json> --build-sha256 <SHA> --output-dir <全新input目录>
python -B /tmp/family-dashboard-discovery-duplicate-probe/<新input>/tools/probe.py run --input-root /tmp/family-dashboard-discovery-duplicate-probe/<新input> --input-sha256 <经独审input.json SHA> --output-dir /tmp/family-dashboard-discovery-duplicate-probe/<全新run>
```

不接受任意 profile、可变镜像 tag、旧应用 overlay、额外环境变量、主机网络或外部 URL。应用直接从不可变镜像 `/app` 加载；112 非 Expo 文件与23导出、实际加载模块路径／SHA和依赖版本均核对。`input.json` 固定 kind、source/tree/package/manifest/image/build、runtimeFiles/exportFiles、三个工具来源闭包、限额与主机预算；每件输入哈希可回读。正式包尚未产生时不能执行准备或用旧资源结果替代。

## 实际负载与观察口径

- app 384 MiB、client 64 MiB，均 memory-swap 等于 memory、UID10001、只读根、cap-drop、no-new-privileges、私有 internal Docker 网络，无主机端口。Gunicorn 为真实1 worker／4 threads。应用拒绝外连；Google账号／令牌均为明确的合成 fixture。
- 用真实本地上传／净化／加密／确认 API 创建目标照片，再在启动测量前直接填入1001条正确行绑定的 Google 来源加密元数据与小型展示副本。共1002条本人已确认 ready 照片；目标不计入1000条候选扫描上限。直接填表不是实际 Google 导入证明。
- 四个真实 HTTP GET 各 limit=20。至少一个成功返回 scanned=1000、capped=true、20条原 ID；其它请求只允许200或明确503 `unavailable`。随后单独恢复 GET 必须200。没有人为保持事务、延迟扫描或替换业务 DTO。
- 请求前后 hook 记录实际服务端处理区间，必须存在重叠；SQLite trace 只计真实候选 SELECT，四并发计数与恢复计数分开。SQLite authorizer 记录并拒绝图片／视频 BLOB 读取，任何尝试均失败。观察器不代替真实授权、结果或 SQL执行。
- 登录后与恢复后，由应用侧已鉴权的只读 SQLite 连接按before／after顺序各一次取全部表摘要，包含未checkpoint的WAL内容；应用原件、真实HTTP响应和客户端摘要必须一致，客户端数据库挂载仍只读。只规范 `member_sessions.last_seen_at` 会话触达字段，其余所有表、列、加密字节及 schema 必须相同。原件记录完整表名单／列名单／行数／摘要，既不输出数据库内容，也不把登录写入混成只读接口写入。全库摘要在请求观察范围外，不归入请求的零媒体BLOB读取声明。

主机门槛640 MiB（三读 t0/t1/t2 全部达标），运行250ms监控，低于256 MiB、读取失败或监控延迟超过1秒即失败。cgroup 原件保存两容器当前值、生命周期峰值、实际限制和事件；`max`、`oom`、`oom_kill` 等必须为0，不能把“未OOM”当“未触限”。两独立峰值不相加声称同时峰值。客户端完成后等待协调者 ACK，避免进程退出导致最后 cgroup 读回丢失。

## 原件与失败

`result.json` kind 为 `discovery-duplicates-linux-result-v1`，绑定 input SHA、真实 Docker commands、owned IDs、proof、数据库摘要、主机监控、完整非数据库 artifacts 哈希。`client/http.json` 保存合成 duplicate 响应及时间；`app/request-*.json` 保存实际扫描／BLOB计数与服务端区间。`client/finished.json` 必须绑定 result SHA；最终 inspect、日志、退出状态与清理结果均保留。

缺失原件、HTTP错误、无重叠／真实扫描、恢复失败、数据库改变、内存事件、监测丢失或清理失败均不通过；先保留客户端原失败，再判断是否缺少数据库摘要，不能用缺文件覆盖首个原因。只清理已记录并重新核对名称／label／镜像的本次容器 ID；创建结果未知时保留意图，不按名称猜测 ID，不扩大清理。不删除失败原件，不重放同输出目录。

本地定向检查只证明工具边界和真实小型 Flask／SQLite fixture的观察方式，不证明 Linux 资源。即使本 profile 实际通过，也只覆盖这四个重复元数据请求；与图片净化／大视频响应叠加的峰值、真实云、手机／电视和生产任意并发另验。
