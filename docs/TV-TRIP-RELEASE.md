# 电视旅行回顾：75 → 77 发布接线

本批已于2026-09-21 08:03:18（北京时间）激活，08:03:49只读回读通过，生产非作者独审已通过。实际source `d4346d3`／包 `d1784a3d…`／应用镜像 `3c55bfba…`；生产一户两库75→77、平台9不变，完整备份、旧75表保全和新两表为空核对通过，没有生产恢复。计划 `9b0c1f83…` 已消费，禁止重放；本页下方为工具合同，不能据此再次执行这份历史计划。118项Linux（零skip）、384MiB／零swap四请求WSGI容量及十阶段隔离迁移均已有独审，固定身份与原件见[本批验收](TV-TRIP-ACCEPTANCE.md#tv-trip-release)。父版为实际 `e8f0427b35157074d179bc4de86a7c5c4db0a755`，镜像 `e5195f8d…`；新包沿 `build_tv_trip_release` 的完整源码、导出和镜像校验。父库组是 75/9，新库组是 77/9，只增加电视旅行选择及操作回执两表。

## 准备与操作

`deploy/prepare_tv_trip_activation.py --inputs-file <absolute-json> --env-sha256 <digest> --output <new-directory>` 只接受固定 `tv-trip-75-to-77` 策略。输入角色精确为 `package`、`build`、`validation`、`selection`、`parentAudit`、`retainedAssistantList`、`migrationRehearsal`、`reviews`。包、构建、验证和保留包描述符沿 `{root,sha256}`；计划及选择沿 `{path,sha256}`。审查角色为 source/browser/release/linux/resources/migration，全部必须真实 PASS。

`retainedAssistantList` 的 package/build/plan 分别绑定原实际包、构建和已消费父计划的固定 SHA；只作为只读原件，不执行或重放父计划。归档实际字节、原文件映射和新候选 114 非 Expo 运行文件一并复核，其中 112 逐字保留、旧 `media_playback.py` 被固定新版替换、增加 `media_trip_playback.py`。继承范围仅未改解码和导入路径，不包含本次改变的播放查询、电视负载或生产恢复。

`deploy/activate_tv_trip_release.py` 沿现有控制器的 stage/activate/verify-rollback 入口。stage 不写生产；activate 独占双锁并消费一次计划，停止 timer 和五服务写者，完整组备份，再执行真实迁移。新 app-only 初始化后必须停止，核验迁移身份及完整库组保全后才能依序启动 app、decoder、workers、web。备份回执不能替代迁移回执。任何失败停止已核候选和数据 helper、保留证据；不会自动恢复、重放计划或重新启动旧版。恢复必须按已备份的完整库组显式进行，再调用固定 `verify-rollback` 核验。

## 真实迁移原件

`migrationRehearsal` 使用 `{input:{root,sha256},run:{root,sha256}}`。工具头与应用头分开：input 的 sourceHead/tree 是冻结 probe；runtimeSourceHead 固定 `aa55f3e7154ec5076ca0ec2360df30e9cf73f981`，实际镜像与完整 root runtime 必须匹配最终包。历史父为 e8。新旧 reader、初始化模块及 probe 的源码闭包逐字匹配最终包。

必须完成 verify/seed/migrate/startup/check/rollback75/partial/populate77/restart/restore77 十阶段，虚构两户三库、部分失败不可重放、完整恢复。非空 77 的精确每新表行数为 `media_playback_journeys:2`、`media_playback_operations:3`。只接受真实成功及其全部输入/运行原件；本地合成回执测试不满足此门槛。

## Linux 选择与容量

精确 118 节点 = 已审 API/会话/原播放 94 项中的 93 项，加 24 项 TV 元数据读取修复回归，以及 `tests/test_tv_trip_capacity.py::test_four_wsgi_reads_2000_media_100_stops_no_large_blob`。单列排除 `test_real_video_in_scoped_playlist_preserves_native_progress`，它依赖 app 镜像没有的 FFmpeg，继续引用原独立浏览器/真实视频证据，不记为 Linux skip。选择 allowedSkips 必须为空，节点集合及五测试模块 SHA 固定；12 个间接 fixture 模块另按源码 SHA 校验，不伪造为被执行节点。

容量 fixture 先以真实会话、上传确认和授权建立一张合成照片，再人工填充加密存储至 2000 张、100 个共享站点、两台已配对 TV；不是 2000 次云导入。四线程分别调用两台 TV GET、成员 control GET 和真实 journey-preview POST。记录真实请求重叠、响应内容/大小/摘要、扫描次数、全表前后摘要，只归一 `member_sessions.last_seen_at`。authorizer 在测量期间拒绝预览及视频缓存 BLOB 列；fixture 初始化和全表摘要在该区间之外。该证据是 Flask WSGI 容量，不是 Gunicorn/Nginx 吞吐、真实电视或解码压力证明。

现有 builder 的 validate 会收集 `/proof/tv-trip-capacity.json`。根执行器获准仅对本次 validation create 的固定 argv 把 `--memory 1024m` 替换为 `--memory 384m` 并增加 `--memory-swap 384m`；共享 builder 源码不变。执行器须保留原始/转换 argv、实际 inspect HostConfig、全部命令和 owned 清理。容量测试及 prepare 均要求 Linux cgroup memory.max=402653184、swap.max=0，max/oom/oom_kill=0，记录进程 RSS 与 cgroup peak。Windows可验证真实 WSGI 逻辑，但缺少 Linux cgroup 的结果不会获发布准入。

正式运行前必须使用已审最终业务字节。本地发布接线测试仅使用真实控制器加录制 Docker runner；不是实际 Docker、迁移演练或生产操作。

原 `test_raw_json_rejected` 六个参数仅增加稳定短 ID（包括 17,000 字符的拒绝输入），参数、断言和测试体不变。118 节点同时通过实际共享 builder 的节点长度/来源校验；选择 SHA 使用 UTF-8、LF 的规范 JSON 字节。迁移运行闭包及 `runtimeSourceHead` 不受测试 ID 改名影响。
