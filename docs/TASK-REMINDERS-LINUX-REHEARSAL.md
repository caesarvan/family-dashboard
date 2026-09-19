# 提醒 Linux 双户迁移与恢复演练

本工具是未发布提醒候选的独立验证入口，依赖发布适配器候选 `0f6cf52078468302523f81de6e8ae532c05269e0`。本次只开发三个新文件，不修改旧发布核心、业务 API 或迁移检查器；工具检查通过不等于实际 Linux 演练或生产迁移完成。合同见[提醒 API](TASK-REMINDERS.md)、[69→71 迁移检查器](TASK-REMINDERS-MIGRATION.md)。

## 实际演练范围

`deploy/task_reminders_linux_rehearsal.py` 复用路线演练的程序生成、财务及路线哨兵、完整组恢复帮助函数，和 `steady_linux_rehearsal.phase` 的隔离容器。候选 package、source、镜像运行文件及实际执行的帮助模块必须逐字节匹配。固定父镜像为已安装任务依赖版本 `sha256:fbb221027f4542cbfb3f9dc66b26d38314bfbbf2df00e43744936b8288fea547`，旧 manifest 为 `14f5d762ae07ee33a5228631faa6dc6984da7b2a71e2fc5e508781d786e4aeec`；检查新镜像父层和配置保持，不使用宿主历史 Git fixture。

1. 在全新临时目录，由父镜像真实 app 工厂、登录、邀请、兑换、任务与角色 API 创建两个家庭、三个数据库，严格 69/9。填入原有私人、审计、五张财务表，以及路线、站点、软删除和操作回执哨兵；DDL 全部来自镜像运行代码。
2. 调用实际 `check_task_reminders_migration.begin/migrate`，先完整备份，再按运行模块实际 DDL 新增两张空表，得到 71/9。
3. 只启动真实 app 并初始化全部已注册家庭；随后独立检查旧 69 表的 schema、行、序列、平台注册库 9 表及 marker 全部保全，两张新表仍为空。**不启动 worker，也不豁免 `settings` heartbeat。**
4. 从迁移前完整备份复制到全新 `/proof/restored-old`，执行候选文档提取出的真实恢复程序，再用 `verify_rollback` 核对原 69/9 完整组。
5. 在新 71/9 库通过真实本地 Flask 登录、任务创建、提醒列表、已读／暂缓、回执查询与同请求重放，生成每户两条提醒状态及两条回执。截止日固定为过去的合法日期，暂缓时刻从实际 `serverNow` 加一小时计算。此阶段才允许新增任务与会话／审计记录：每次创建仅允许 `settings.meta` 的 SQL revision 增加 1，两次合计精确增加 2；其 data 和其余 settings 行必须原样，提醒动作／回执查询／重放也须保持完整 settings 不变。财务与路线哨兵继续逐表核对。`populated-settings.json` 保留每户前后摘要和精确版本差异；这项边界不用于豁免前面的迁移或 app-only 检查。
6. 固定非空 71/9 全组参考快照，真实 app 重启后严格核对；完整备份后，在另一全新 `/proof/restored-current` 执行同一文档恢复程序，再核对全部提醒状态、回执、原数据和 marker。

恢复程序只允许把文档唯一 `/data` 根路径映射为两个固定演练目录，保留原程序及映射后摘要。恢复后的服务不启动，为精确比较保留会话，不执行生产恢复时的会话失效步骤。因此结果仅证明隔离的数据库内容恢复，不能声称完整生产故障切换、真实用户重新登录或提醒后台持续运行已验证。

## 执行和失败记录

此命令须由集成人在候选通过非作者审查、实际镜像构建完成后执行。宿主要求 Linux root、`python -B`、无优化模式；不接受环境中的 Docker／Compose 选择器。容器使用 UID/GID `10001:10001`、只读根文件系统、`--network none`、资源限制和临时 `/tmp`，不暴露端口。仅挂载本次新建的 `data`、`proof` 与只读候选 `source`；种子容器只挂前两者，不接触生产目录、凭证或真实云。

```text
python -B deploy/task_reminders_linux_rehearsal.py --candidate <已核验候选目录> --package-sha256 <实际包SHA256> --image-id <实际sha256镜像ID> --output-dir <全新独占演练目录>
```

每次输出目录必须不存在。各阶段命令、退出码、stdout/stderr、程序摘要、来源身份、备份、前后快照及最终 `result.json` 保留；失败终止后续阶段，不能覆盖结果或直接重放。工具不自动修复或恢复生产。演练中的恢复仅创建上述两个新的临时目标，不覆盖原演练失败现场。原件中的合成数据库和回执也不提交 Git。

## 分开记录工具检查与业务演练

`tests/test_task_reminders_linux_rehearsal.py` 禁止实际子进程或网络。原 31 项工具检查覆盖真实生成程序、来源／父身份、哨兵和空表汇总、恢复根路径、隔离参数，以及记录式执行器的阶段失败与禁止重放。执行器替身用于检查编排，**不能作为迁移、API 或恢复业务成功的证据**。另有本地真实 Flask／SQLite 闭合检查执行完整非空提醒生成程序，仅映射本机模块路径，验证两次创建导致 meta +2、提醒动作不改 settings，并拒绝意外 meta 或其他 settings 漂移；此本地检查不替代 Linux 迁移与恢复演练。

```text
python -B -X utf8 -m pytest tests/test_task_reminders_linux_rehearsal.py -q --basetemp=<新临时目录> --junitxml=<新XML路径>
```

已有 Windows 迁移测试的 33 个唯一用例为 R1 32 通过／1 个注入步骤失败，加 R2 单项通过，实际原件见迁移文档；它们依赖历史 Git fixture，不放进普通 Linux 测试容器冒称通过。本工具后续实际 Linux 容器演练单独记录 package／source／镜像、12 阶段和所有数据库原件。在拿到终态证据前，Linux 演练、生产迁移、真实云、实体电视与 A–D 本人完整验收都不能由本工具检查推定完成。
