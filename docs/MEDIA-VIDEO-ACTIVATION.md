# 视频五服务发布控制器（候选，未执行生产）

这是独立的新控制器，复用已审查的五服务生命周期、71→73／平台 9 表迁移器和双镜像包验证。没有继承旧四服务的激活路径。只有后续非作者审查、隔离完整演练及明确批准的新计划完成后，才可用于生产。源码提交、镜像构建和单项 Linux 实验均不等同上线。

应用包仍固定 `b8c4d599`，应用镜像 `sha256:75d2cf07e1fe01eb56fe1fed999442b922d046eba52c64e4227ed176a0e975a5`，decoder 镜像 `sha256:005cc30d5eec73abdfa1fcc62f4d84d871edc2a1cc6169c96390e368f1511c8c`。外置 operator 单独从固定 Git 提交提取 9 个运行工具文件；不会放宽应用打包白名单或重建业务镜像。

## 离线准备

输入 JSON 必须提供：

- `package`：原包目录 `root`、`package.json` 的 `sha256`。
- `build`：原双镜像构建目录 `root`、总 `build.json` 的 `sha256`；内部两个完整构建、镜像配置、运行文件、原输出和 contexts 仍由已审 `verify_build` 逐一核验。
- `migration`：`run` 和 `input` 两个描述符，分别指真实 Linux 结果目录和完整 prepared 输入目录。描述符为 `{root, result, sha256}`；`result` 是目录内相对文件名。要求十个阶段、两户三库、app-only 保全、旧 71／非空 73 完整恢复及跨户部分失败恢复全部真实通过，并核所有输入／proof 文件。工具来源提交可以不同，应用运行字节必须匹配固定镜像包。
- `worker100`、`response64`：各自真实 Linux profile 的 `{root,result,sha256}`。必须明确 `passed/status=passed`、完整双角色回执、同两个镜像、精确运行源码、384／768 MiB 和零 OOM/max 事件；缺失、失败、压力中止、部分输出均拒绝。输入与本批输出目录全文件再哈希进入计划。
- `reviews`：`package/lifecycle/controller/migration/resources/browser` 六份真实非作者报告，分别为 `{path,sha256}`。接受已有报告的 `verdict/conclusion/status/decision` 结论字段；存在的每个结论都必须为 `PASS` 或 `PASS_` 开头的限定通过。至少明确提供 `findings` 或 `blockingFindings`，存在的两种字段都必须为空数组；冲突结论、未关闭问题或格式缺失均拒绝。批准计划的人仍须核对报告的具体范围与来源，程序不会生成审查通过记录。

准备工具只接受环境文件的 SHA256，不读取生产 `.env`。环境摘要由授权只读采集另行提供；实际 stage 必须重新核验。

```text
python -B deploy/prepare_media_video_activation.py --repo <固定干净工具 checkout> --head <完整工具提交> --inputs-file <真实输入 JSON> --env-sha256 <生产环境摘要> --output <新候选目录>
```

输出包含 `plan.json`、`operator.json`、独立 `operator/` 和从已核包安全展开的 `source/`。原证据目录保持原地，以绝对路径绑定；转移到服务器后，必须按服务器上的最终证据路径重新离线组装，再审批新的计划 SHA。禁止手工改已审批计划路径或用占位成功 JSON 组装。

## 明确分开的生产阶段

由外置 `operator/deploy/media_video_release_controller.py` 执行，候选目录必须在 `/opt/family-dashboard-candidates`。CLI 要求 Linux root、`python -B`、无优化、无环境覆盖 Docker/Compose 选择器。按固定顺序同时非阻塞持有 `.membership-release.lock` 和 `.static-release.lock`，覆盖两类历史控制器；第二把锁失败或操作异常时，释放全部已打开描述符。

1. `stage <candidate> <plan SHA>`：只读重新核对原件、工具、源码、父 manifest `83ff8610…add5c1`、父应用 `a783c58c…6654`、环境 0600 和摘要、四服务身份及两个现存不可变镜像。不会启动验证容器、备份、停服务或改生产配置；仅在候选目录独占写 stage 回执。
2. `activate <candidate> <plan SHA>`：再次核对后独占写计划消费标记。保全父源码、原环境及镜像标签；停备份 timer、确认备份 service 不在运行；依序停 web／sync／media（1200 秒）／app，核数据与 socket 卷无使用者。
3. 使用新 app 镜像、无网络、非 root、384 MiB/no swap 的受限 helper 调用真实完整组 `begin/migrate`。先独占记录创建意图，`docker create` 后记录唯一 CID、名称及计划／动作标签，复核身份才 `start --attach`。真实生产数据只挂此受控 helper，环境保持私有文件，不进入日志或公开回执。
4. 安装已核 b8c4 源码和导出，保留旧 Expo 目录，绑定两个镜像标签。只对 manifest 管理且已完整备份的旧源文件处理移除。环境文件不改；现存 socket 卷必须是空、UID 10001、0700 的本地卷，异常不会自动删除。
5. 单独启动 app，使用真实 app factory 初始化全部注册家庭，再停止 app。真实 `check_stopped` 比较完整旧 71 表、序列和平台、新两表空状态。关联收据完全一致才按 app → decoder → sync/media → web 启动。复核 HTTPS health、源码和环境后恢复 timer，写完成回执。

计划消费标记、stage、迁移尝试和各阶段记录均不覆盖。失败保留原件并停止明确记录的候选 CID；media 未确认停止则保留 decoder 并报告未完整停止。不会自动恢复数据库、删除 socket/卷、启动旧程序或自动重新执行未知操作。

helper 的客户端超时或中断不等于容器退出。失败时只向本次已核 CID 发停止请求，随后重新核对状态、PID 为 0、数据／socket 卷无运行使用者，再记录已停止；不会删除 helper，便于核对失败现场。创建结果不明、身份变化、收停未确认时明确记录停止不完整，保留原尝试，不能自动重放迁移或恢复服务。停止部分迁移不代表数据库组已恢复，仍须完整组人工回退和核验。

## 完整组回退与只读核验

回退必须由操作者另行审核执行：停止所有项目服务与备份 timer，验证没有数据/socket 卷使用者，核对本次 `releaseDirectory` 下保全的父源码、环境、镜像及 `proof/backup-group`。按照现有部署文档的完整库组恢复步骤，将平台与**全部家庭**恢复到同一份保全时点；不能只回退单个已迁移库，也不能让旧应用打开 73 表库。保留成功成员迁移 marker 和原备份；严禁对失败迁移原尝试重跑。

恢复原源码、manifest 和环境，并完成全库组人工恢复后，可运行：

```text
python -B <candidate>/operator/deploy/media_video_release_controller.py verify-rollback <candidate> <plan SHA> --release <本次独占 releaseDirectory>
```

该入口要求 timer、备份 service 和所有数据/socket/项目服务均停止，调用既有 `verify_rollback` 只读核对完整 71／9 组及 marker，再独占写核验回执。它不会执行恢复或启动服务；恢复旧服务及独立审计仍需单独审查和授权。非空 73 的合成恢复是迁移验收内容，不把它误当作生产回退到旧版的许可。

本组件的离线测试使用真实文件／SHA／Git 边界与记录型 Docker 传输模型。R1 24 项、R2 新增 5 项、R3 资源原件校验 11 项（含 2 项新增）、R4 来源目录权限修订后仅复验 prepare 1 项，分轮共 31 个唯一用例／41 次执行，不能称为同轮完整运行。另只读核验现有真实 Linux 迁移原件与 58 个镜像运行文件匹配，并确认真实 `preflight_blocked` 的 worker100 结果被计划组装拒绝；没有重新运行这些 Linux 负载。

双锁／helper 修订 R5 仅运行 16 项相关用例：9 项新增、7 项受影响流程复验，全部通过；累计为 40 个唯一用例／57 次执行。覆盖两把锁的竞争、第二把锁打开失败及异常释放；Windows 使用真实原生文件锁适配，只证明描述符与释放流程，不冒充 Linux `flock` 实测。helper 的超时、中断、未知创建、收停失败和身份变化使用记录型 Docker 模拟；停止 PID 和卷写者断言不是实际容器结果。

## 2026-09-20 候选验证进展

最初的资源准入失败与第一轮维护窗口失败均保留。第二轮受控维护窗口中，`worker100` 和 `response64` 两项真实 Linux 实验已分别通过，非作者报告 `media-video-ipc-resource-execution-independent-r2.json` 的 SHA256 为 `c1937d436a03e13adced9e82a4efab29cb036707080dc2e961a680e8d6d38c97`。两项都使用固定 app／decoder 镜像及 384／768 MiB 限额；前者实际完成 100 MiB 输入下载、IPC、保存与响应，后者验证明确构造的 64 MiB 完整显示响应。未发生 OOM／内存限额事件；两项不代表最坏编码复杂度或生产持续并发容量。维护窗口已恢复原 media 进程和备份 timer；没有验证恢复后的业务 worker tick。

实际准备曾因 Windows 长路径、原独审报告的 `decision` 字段不兼容而失败。长路径输入修正后，工具 `b61d0d51ddc65eb5ff32b5793fb36d98591f6dfd` 增加对已有报告字段的严格兼容；16 项定向检查与非作者差异审查通过，没有修改原审查报告或放宽资源、迁移、应用包检查。随后本机准备 R3 成功，独审明确仅证明本机准备，Windows 绝对路径不可直接用于服务器。

在服务器最终证据路径重新准备也已实际退出 0（原 PID 912559），只创建候选和回执，没有执行 `stage` 或 `activate`：

- 候选：`/opt/family-dashboard-candidates/media-video-b61-20260920-r1`。
- 计划 SHA256：`650ddf8b547e8c781b8184a8a6ecb0ebf18867d71f2f087a9e6bbc679b265f66`。
- operator SHA256：`954007aa8478b6a8d32af4220c0ff58515c2c87c008f823bc194ef3fd7b8aea8`，与本机成功准备相同。
- 本机原件归档：访问目录下 `media-video-activation-server-r1/evidence`，包含实际命令、终态、计划、输入、原审查报告及服务器候选文件摘要；这些原件保持在 Git 外。

服务器准备已通过非作者核对：`media-video-activation-server-independent-r1.json`，SHA256 `6013459bc5a308c17c3fb3121d13802d5805aaa3b402c0f2cab84835b1bb4608`，结论仅为 `PASS_SERVER_PREPARATION_NOT_ACTIVATION`。17 件下载原件和 1113 个来源／manifest／operator 文件均核对一致，与本机 R3 的计划仅有 12 处绝对路径变化，证据映射相同。新控制器自身的完整 Linux 五服务隔离演练和生产运行尚未完成；演练工具首轮独审发现监控初始化失败回执及预存 socket 卷准入问题，必须修正并复审后执行。已有单项迁移、媒体资源与浏览器成功不能替代该演练，也不表示视频已经上线。
