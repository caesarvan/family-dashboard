# 旅行费用归集：73→75 迁移与完整库组保全

候选基于后端 `cb51ea6f2f2cbe6457fae05e25b9c14b1fb0faf3`，尚未部署。这里只增加迁移检查器、75 表稳态读取器与定向验证；没有修改旧控制器、旧 73 表默认策略、Docker 或生产数据。服务启停和新发布计划仍由后续独立发布适配负责。

每个家庭库从 73 张业务表增至 75 张，平台注册库保持 9 张。新增 `hub_journey_allocations`、`hub_journey_allocation_operations`；首次迁移后两表必须为空，不从共享旅行 `paid`、采购结算或账单回填。四个显式索引与两张表的 SQLite 自动主键索引均从真实 DDL 推导。旧 `media_video_deleted` 触发器属于原 73 表对象，完整保留。

DDL 固定来自 `journey_finance.SCHEMA_SQL`，SHA-256 为 `f936c9403df6c4ad888502a0fcd03574ccd876a5403bb003015b232833e71450`。包含 initializer 的模块 SHA-256 固定为 `750c3732fbfb0952d7ee01386d6a93529414098cfaa61f1428af2c09acf62a6e`。迁移使用实际 `init_schema(con)`，在每户 `foreign_keys=ON`、`trusted_schema=OFF`、`BEGIN IMMEDIATE` 事务中运行；initializer 不可隐含提交。它先在内存库中证明新增对象和回滚原子性，再允许操作已存在的目标数据库。

新增 DDL 的导入闭包固定为 `journey_finance`、`finance_hub`、`financial_files`、`finance_source_bridge`、`finance_baseline`。模块只可来自本候选源码目录，或原数据 helper 的 `/release` 与 `/app` 同字节布局；`source_identity` 的 source/runtime 映射都必须覆盖这些真实字节。原 73 表 reader 的既有依赖仍保留。不接受调用方指定任意模块或 SQL，不启动应用取得 DDL。

## 首次迁移接口

调用者必须已经停止所有写入者，并固定 source/image、plan、成功 membership marker 和全新外置 proof 目录。以下是 Python 接口，不是可直接上线的 CLI。

| 接口 | 行为与证据 |
|---|---|
| `check_journey_finance_migration.begin(root, proof, source_identity=…, plan_sha256=…, marker_sha256=…)` | 复用原 backup core 和 73/9 reader，独占 `journey-finance-migration-attempt`；保留 before、attempt、完整平台注册家庭组备份及 manifest。拒绝旧 71、部分 74、已 75、同名新增对象或额外未注册库。 |
| `migrate(root, proof, …同一身份…)` | 再次核对原组、备份、来源、marker 和计划，独占写 `migration-attempt.json`，逐户执行真实 initializer；全部成功才写 `migrated.json` 和 `migration-result.json`。 |
| `check_stopped(root, proof, …同一身份…)` | 新 app-only 初始化并干净停止后，核对完整原 73 表及新增空表，保存 `after.json`／`result.json`；worker 尚不能启动。 |
| `verify_rollback(proof, restored_root)` | 只读确认按完整组恢复出的 73/9 与 before 和 marker 相同，不执行恢复写入。 |

旧表全部 schema、索引、触发器、列、行、BLOB、`sqlite_sequence`、`user_version`、`application_id` 与平台组关系须保持。没有 settings、heartbeat、session、付款、采购、媒体缓存或回执豁免。比对前后再次读取，防止验证期间数据变化。

SQLite 多库没有全局原子事务。第二户失败可能留下第一户已 75、第二户仍 73 的部分组：保留失败 attempt，不重跑、不更换 proof 绕过，不自动恢复或启动旧服务。先停止已核实的全部候选写入者，再按[现有完整备份／恢复程序](DEPLOYMENT.md)恢复平台注册库和每个家庭库，最后调用 `verify_rollback`。遗漏任一库、额外库、篡改 manifest、逻辑内容或 marker 均拒绝。73 回滚会丢失上线后新增归集，不能在接收真实新业务后称为无损恢复。

## 非空 75 表稳态

`journey_finance_release_data` 使用独立 `journey-finance-source-update-attempt` 和固定 75/9 `DataSpec`。`snapshot_current`、`validate_backup`、`finish_stopped_backup`、`begin`、`check_stopped`、`verify_restore` 复用原完整组机制，不执行 DDL。允许 active、revoked、失联引用及回执非空，但所有行和全部旧对象须严格保全。

路径、备份 bytes/hash、registry、外键与完整逻辑摘要沿原规则验证；拒绝链接路径、非空 WAL、活动 journal。仅原 backup core 可以在原 main 文件与完整备份均匹配时，由 SQLite 关闭已核实的空 WAL／SHM 对。本模块不手删副文件、不用主库裸拷贝忽略 WAL、不放宽停写前提。

## 验证边界

专项测试从固定本地 Git `dc2b54cfc7fc9063eb839ece87fdab72a21855be` 物化旧源码，由真实应用创建合成两户三库 73/9。付款、购物回执、私人财务、旅行、提醒、settings、视频缓存与播放进度放入合成哨兵；候选 app-only 真实重启后验证原对象与新空表。单户索引授权失败和第二户真实 SQLite 读锁分别验证本户原子回滚与跨户部分失败；恢复运行原文档程序，另覆盖非空 75 的重启、备份、完整恢复与损坏拒绝。

这些是合成 SQLite／Flask 和本地 Git 验证，不是 Linux 五服务、真实迁移、云账号或生产恢复证明。历史源码物化要求本地 Git 对象，普通无 Git 镜像不能把这些检查标成通过。原件只保存在 ignored `test-results`，不提交数据库或私人数据；实际计数与分轮失败记录见作者报告。

作者本地验证共 33 个唯一用例最终通过，0 skip：R1 为 6 pass／27 fail，失败都在 Windows 长备份路径写入；R2 只将临时目录改为独占 `C:/tmp` 短路径并复验这 27 项，27 pass、exit 0。三个 Python 输入两轮字节完全相同，没有重复已通过的 6 项。R1／R2 原件均保留；这不是一次 33/33 或 Linux／生产执行。
