# 旅行简报事项的源码发布工具

本批已于 **2026-09-20 01:13:38（北京时间）激活，01:23:44 独立生产只读审计通过**。Linux 构建、199 项验证、合成两户保全及实际生产一户两库的 stage／activate 已完成，固定身份与原件见[集中验收](ASSISTANT-TRIP-ITEMS-ACCEPTANCE.md#assistant-trip-items-release)。本次计划已消费；本工具固定的旧父版本不能用来再次更新当前线上版本。没有本批 DDL，A–D 本人完整验收仍为 0/4，真实云和实体电视另验。

## 固定基线与范围

本次已完成发布使用的历史父版本为路线版本；工具仅接受该固定基线：source `a9d3261116a5ad83fafb28ebda168bcd628367b4`，tree `c82b4e24a4e8093290611ac5e09701cb7f406c83`，package `c54dec688fbe99fef64b00ec92344d599259e134f328dbe49f0315b397dd22ef`，manifest `0ec456641fc66d9e5a71c067e7731479fa5fd6fb7a05aa4ee84b1b27b5e7b070`，父镜像 `sha256:9a966634bb220e7ce2a071fa130f011414b4c413eeecac0f9b3d3eccd5fb5bbc`。此前生产只读审计 SHA-256 为 `a7742fb97173fcf3024c4a81ea85cfc433067af6939ade507a66447c9d147e61`。

本批保持户内 69 表、平台 9 表；Docker SHA-256 仍为 `36f5d699823890c26dbc243010f584c5aa5d44c109bd6e63b705e9e025a2a90b`，依赖、运行文件集合与既有配置均不变化（组合及生产只读审计已核对 127 个运行文件）。根目录允许变更仅 `home_assistant.py` 和 `README.md`；前端、文档、测试、发布工具沿原路径范围核对。新增前端测试只有显式允许的 `frontend/tests/journeyBriefItems.test.mjs`，其他未列出的前端输入仍拒绝。

`assistant_trip_items_release_profile.py` 固定选择 `journey-routes-r1-assistant-trip-items`。CLI 或计划 JSON 不能选择任意表数、模块、回调或数据目录来改变该合同。

## 复用与保全

`assistant_trip_items_release_{package,plan,controller}.py` 是现有包、计划和源代码更新控制器的薄入口。共享 `ReleaseSpec.schema_pair` 默认仍为 `(66, 9)`，本入口在已审源码中明确指定 `(69, 9)`；stage 和完成回执直接报告该配置，不事后改写回执。原激活顺序、来源及运行字节核对、计划与原件绑定、环境映射、独占执行、失败停写及不自动恢复逻辑保持。

数据侧 `DataSpec` 只由受审源码构造。旧 66 表 `_profile` 原文保留；本入口使用 `check_journey_routes_migration.snapshot_current` 和 `verify_restore` 的精确 69 表读取器，不调用该模块的 `begin`、`migrate` 或旧 66 表回滚路径。整组包含 registry 中所有家庭与平台；旧行、列、schema、外键、序号、成员迁移 marker 与配置都必须保持。三张路线表可以非空，软删除路线、站点及 operation 回执都参与指纹比较。

停写后调用新 data 的 `begin`：完整备份全库组、核对原始 manifest 与文件字节及逻辑指纹、保留相对目录结构。只允许原有空 WAL 对的受控关闭；非空 WAL、遗漏库、链接或越界路径、备份字节变化均拒绝。真实新 app 启动并干净停止后调用 `check_stopped`；完整 69/9 快照必须等于 before，才允许继续启动服务。重复执行或任一失败保留原件，不覆盖或自动重放。

## 操作接口与证据

以下保留本次已完成发布的接口合同，不是当前线上版本的再次执行指南。后续发布必须重新固定实际父版本、完整组合源码、正式 Expo 原件及受审计划：

- `python -B deploy/assistant_trip_items_release_package.py prepare|verify|build|validate`：与此前发布相同的显式 repo/commit、构建原件及其 SHA、包身份、Linux image 和 nodeid selection 参数。
- `python -B deploy/assistant_trip_items_release_plan.py --package-dir … --package-sha256 … --build-dir … --build-sha256 … --validation-dir … --validation-sha256 … --reviews … --reviews-sha256 … --candidate …`：仅离线组装新候选。
- Linux 控制器 `assistant_trip_items_release_controller.py stage|activate <candidate> <plan_sha256>`：沿原部署权限和真实计划操作，已消费的计划不能重放。

保留 `attempt.json`、`before.json`、`backup.json`、`backup-finish.json`、`backup-verified.json`、完整 `backup-group/`、`identity.json`、启动后的 `after.json` 与 `result.json`，以及外层 stage/activation 原件。本批没有 `migration-attempt.json` 或 `migrated.json`。原 schema 迁移记录与成员 marker 不变。

本机专项使用合成两户三库：各一条 69/9 非空路线与旧默认 66/9 的 begin → 真实 app restart → check → 文档恢复程序 → verify_restore；另测 schema/外键/行/序号漂移、回执身份、空 WAL、失败保留与源码范围。recording controller 仅记录命令，不执行 Docker。恢复测试只恢复隔离数据库并验证完整内容，不打开恢复后服务；正式恢复后开放服务仍按 [DEPLOYMENT.md](DEPLOYMENT.md) 的会话失效步骤执行。

作者本机首轮实际 `43 passed`，0 failed/error/skipped，177.21 秒；范围为两个新增专项文件及旧控制器的 `test_populated66_backup_then_app_preservation_before_workers_without_migration`。JUnit、stdout、退出码和源码绑定汇总保存在作者 worktree 忽略目录 `test-results/trip-items-release-r1.*` 与 `test-results/assistant-trip-items-release-verification-r1.json`，不提交原件。旧 `_profile` 原文核对一致，SHA-256 为 `ffd1420d17b2c990935824c08de43275069fc3539d4ce636577de21cc6ba0281`。

真实 Linux 构建、199 项验证、两户三库保全、最终浏览器及生产原件已由集成人分别记录并经非作者审查，统一见[集中验收](ASSISTANT-TRIP-ITEMS-ACCEPTANCE.md)。生产实际一户两库 69→69／9→9 的完整停写备份和启动前后保全通过；本轮 Linux 与生产均未执行备份恢复。本机专项、Linux、模型与浏览器结果不相加，也不改变 A–D 本人完整验收 0/4。
