# 视频迁移与完整库组保全候选

本候选基于 `6752ca81ebf32332c705c8da7da33e7d514e3c91`。仅新增迁移检查器、当前数据 profile、定向测试和本文；不修改业务、共享发布控制器、Compose 或运行中的生产数据。它不等于发布授权、Linux 演练或上线回执。

每个家庭库从 71 表增至 73 表，平台保持 9 表。新增 `media_video_cache`、`media_playback_progress`，初次迁移时两表必须为空。新增 `media_video_deleted` 触发器挂在旧 `media_items` 上，软删除媒体时清理对应视频缓存；它被单独计入 schema 对象比较，不能按新表名过滤而遗漏。原 71 表的所有对象、列、行、序列、数据库版本及 application ID 保持，照片、私人资料、分享许可、确认回执和提醒状态均不回填。

DDL 只读取实际 `media_video_storage.SCHEMA_SQL`、`media_playback_progress.SCHEMA_SQL`；SHA-256 分别固定为 `a36509e46c9baaa1a780ac7cd2e9951f63c04ba5df3a6f29e0c37fad7b15284f`、`a9302203d12100c21e6a93c839b1c3444c26e781e8cee1646494b21375a4fbee`。两模块及影响密文上限的 `media_crypto.py` 同时绑定 source/runtime 字节。仅允许当前目录或已约定 `/release` 与 `/app` 相同字节的布局。

SQL 用 `sqlite3.complete_statement` 识别两条建表和一条完整建触发器语句，保留触发器内部的分号；在每户 `BEGIN IMMEDIATE` 事务中逐句执行。不调用会自行提交的 runtime initializer，也不调用 `executescript`。任一语句失败则本户回滚。检查器不启动 app、worker、解码器，不发送网络请求。

## 首次 71→73 调用

调用者须先停止所有写入者，固定源码、镜像、计划以及已有成功 marker，并提供独立、全新的 proof 目录。以下为 Python 接口，未新增生产 CLI。

| 接口 | 约束与原件 |
|---|---|
| `check_media_video_migration.begin(root, proof, source_identity=…, plan_sha256=…, marker_sha256=…)` | 复用已审完整组备份核心与父 71/9 读取器，使用独立 `media-video-migration-attempt`。拒绝旧 69、部分 72、已 73、额外家庭库或同名 video 对象。保留 `attempt.json`、`before.json`、全部三库备份和 manifest 校验原件。 |
| `migrate(root, proof, …同一身份…)` | 重新核对原库、完整 retained backup、marker、plan 和三模块 source/runtime 字节，再独占写入 `migration-attempt.json`；成功保存 `migrated.json`、`migration-result.json`。 |
| `check_stopped(root, proof, …同一身份…)` | 停写状态核对平台 9 表不变、每户旧 71 表和新增空表/触发器准确，独占保存 `after.json`、`result.json`。无需启动应用；若后续发布进行 app-only 启动，也必须干净停止后再核对，worker 留待通过之后。 |
| `verify_rollback(proof, restored_root)` | 只读验证完整恢复出的原 71/9 组与迁移前逻辑快照、marker 完全相等，不执行恢复。 |

SQLite 多文件之间没有此模块提供的全局事务。第二户失败时第一户可能已提交；保留部分现场及 attempt，不覆盖或自动重试，不换 proof 绕过。必须另按完整库组恢复流程恢复平台与所有家庭，再独立核对恢复结果。生产服务的停止、备份时机和发布阶段由后续已审控制器负责。

## 当前 73→73 保全与恢复

`media_video_release_data` 复用既有 source-update 核心，使用独立 `media-video-source-update-attempt`，不含 DDL：`snapshot_current`、`validate_backup`、`finish_stopped_backup`、`begin`、`check_stopped`、`verify_restore`。允许新表非空，但完整缓存密文、playhead、sequence、提醒、回执、settings 与全部旧行都必须保持；没有媒体、提醒或 heartbeat 豁免。

`verify_restore` 是只读核验，实际恢复由原文档程序完成。所有备份必须覆盖平台注册的完整组，核文件大小、SHA-256、逻辑摘要、schema、外键与 registry 对应关系。非空 WAL、活动 journal、链接路径、缺失/额外库及篡改 manifest 均拒绝；仅复用原备份核心对匹配快照的空 WAL 对关闭规则。原始数据库备份属于敏感产物，不提交 Git；报告仅含摘要和数量。

## 本地验证边界

`tests/test_media_video_migration.py` 从固定已部署父源码 `8d3e6376a606155ff66a0388e43d04cb7562fe9f` 在临时目录创建两户三库合成种子，补入私人日程、照片/软删/确认记录、电视许可、提醒和历史回执。历史 app 启动仅用于生成基线；迁移和当前保全不依赖任何 app 启动。测试使用真实 SQLite、完整备份及原文档中的恢复程序；新媒体缓存字节为合成不透明值，不冒充加密、视频解码或播放验证。

定向覆盖首次空表与触发器、旧行/列/索引/序列漂移、平台/提醒/settings、备份/marker/plan/source 绑定、单户事务失败、第二户部分失败、完整 71 回滚、非空 73→73 保全与完整恢复、触发器及外键实际清理、拒绝非空 WAL 与非法基线。无需运行全套业务、FFmpeg、前端或浏览器测试。

作者 R1 唯一执行已完成：33/33 通过，0 failure/error/skip，108.93 秒；原 session `91520` 终态 exit 0，stdout/stderr/XML/源字节前后记录保存在 ignored `test-results/media-video-migration-r1`。实际进行了完整组 SQLite 恢复；没有执行 Linux、生产、app-only 新版启动或服务发布。非作者审查和后续发布演练仍待独立完成。
