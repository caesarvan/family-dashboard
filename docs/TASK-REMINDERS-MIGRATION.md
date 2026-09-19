# 提醒数据库迁移检查器：69/9 → 71/9

本文件配套 `deploy/check_task_reminders_migration.py`。它是提醒候选的独立迁移与验证模块，基线为 `eb565b85982f47c44d5b7b86bf13ee4da7499f91`；不是生产执行回执，也不提供部署授权。提醒业务合同见 [TASK-REMINDERS](TASK-REMINDERS.md)。本批没有修改 API、前端、发布控制器、镜像政策或服务配置。

## 固定数据变化

每个家庭库由原有 69 张业务表增加到 71 张，平台注册库保持 9 张。只新增 `task_reminders` 和 `task_reminder_operations`，首次新增必须为空，不回填，不写任务、用户、财务、库存、旧操作回执或 `settings`。两表的列、主键、外键及隐式索引，必须与实际 `task_reminders.SCHEMA_SQL` 完全一致。

检查器直接读取运行模块中的常量，没有另抄一份 DDL。该常量的固定 SHA-256 为 `72470a0ce30bffe0e710184b0498477a0345d8e4197da6c6f5510a6020389657`，仅允许两条指定的 `CREATE TABLE IF NOT EXISTS`。模块文件必须来自当前源码目录；在既有 `/release`、`/app` 容器布局下，两份文件必须逐字节一致，并同时匹配传入的源码和镜像运行文件摘要。

所有原表的完整 schema、列、行摘要、`sqlite_sequence`、数据库版本与 application ID 均核对；SQLite 完整性和外键检查沿用原读库工具。额外列、索引、表、外键破坏、原数据变化及非空新增表都不能被当作成功。

## 调用顺序与证据

本模块是供后续经过审查的发布适配器调用的 Python 接口，没有通用生产命令或自动发现服务器入口。调用者负责停止所有写入者、固定 source/image/plan 身份，并提供与数据目录分离、独占的新证据目录。

| 接口 | 输入和结果 |
| --- | --- |
| `begin(root, proof, source_identity=…, plan_sha256=…, marker_sha256=…)` | 严格读取完整 69/9 组，沿用 `assistant_trip_items_release_data` 建立独占 attempt、全组备份和逐库保全证据。只承认平台注册库列出的所有家庭库；缺失或额外家庭库均拒绝。 |
| `migrate(root, proof, …同一身份…)` | 先核对完整 retained backup、原始快照、marker、plan、源码/镜像摘要；全部通过后独占写入 `migration-attempt.json`，再按户执行迁移。成功保留 `migrated.json` 和 `migration-result.json`。 |
| `check_stopped(root, proof, …同一身份…)` | 在只启动 app 验证、随后干净停止后，对完整组再核对。原 69 表和平台 9 表必须保持逻辑一致，新 2 表仍为空；成功独占写入 `after.json`、`result.json`。 |
| `snapshot_current(root)` | 只读识别合法 71/9 组，允许两张新表已经有提醒状态和历史回执，返回包含完整 schema/行/文件摘要的快照。不会重做首次迁移。 |
| `verify_restore(reference, restored_root, marker_sha256=…)` | 只读核对从完整备份恢复出的 71/9 组，必须与原快照逐库逻辑一致。 |
| `verify_rollback(proof, restored_root)` | 只读核对从首次迁移前备份恢复出的完整 69/9 组及原 marker；不会执行恢复。 |

备份复用原 `deploy/backup.py` manifest、注册库和路径规则，检查每个文件大小、SHA-256、逻辑摘要及完整组关系。快照报告含摘要与数量，不含私人记录明文；备份数据库本身仍是敏感产物，不得提交到 Git。已有 `attempt`、迁移记录或结果文件不可覆盖。重新调用 `migrate` 不会把已完成或失败的迁移称为幂等成功。

## 停写、失败与恢复边界

建表在每个家庭库自己的 `BEGIN IMMEDIATE` 事务中逐句执行实际常量。检查器不调用会提前提交已有事务的 `executescript`；其中任一句失败，该库回滚。真实 app 的 `register_task_reminders` 初始化另外通过合成 app-only 启动验证。

SQLite 多文件之间没有本模块提供的全局事务。若第一个家庭已提交，第二个家庭失败，保留部分迁移现场及 attempt，禁止直接重跑、换 proof 绕过或只恢复失败的那一库。后续操作必须遵守完整组恢复流程，使用对应的平台注册库和所有家庭库备份，经 `verify_rollback` 确认，再由集成人决定新的一次发布。检查器自身不删除现场、不自动恢复、不启动服务。

初始 preflight 失败发生在迁移 attempt 和建表之前；备份阶段自身失败可能留下备份 attempt，也必须保留。已有非空 WAL、活动 journal、链接/非法路径、失配的注册库或不完整备份会拒绝，不能临时忽略。既有备份流程仅允许关闭与停写快照一致的空 WAL 对，不能用作活跃数据库恢复工具。

`check_stopped` 专门验证 app-only 阶段。提醒 worker 的正常 tick 会在 `settings['task-reminders-worker']` 写 heartbeat，也会生成提醒行，所以 worker、云同步及其他写入者必须在这一步之后才可恢复。**不豁免 `settings`，不把后台已运行后的变化归入 app-only 保全。** 全服务启动后的 heartbeat/服务读回属于后续发布验收，不能以冻结快照要求活跃库永久不变。

## 本地合成验证

定向入口为 `tests/test_task_reminders_migration.py`，只使用临时数据库，不读真实账户或生产库。复用历史 69/9 种子：固定源码 `a9d3261116a5ad83fafb28ebda168bcd628367b4`，真实 Flask 建立两个合成家庭、一个平台注册库，并填入私人哨兵、财务和路线历史。种子源码逐字节核对 Git blob；`baseline69-identity.json` 保留源摘要及逐库快照。当前候选源码复制到独立目录，启动子进程禁止网络。

覆盖完整 69→71 建表和当前 app-only 重启；原表、序列、平台、版本、heartbeat、schema 和外键异常；marker/plan/备份/源码绑定；预检失败零建表；单库事务回滚；跨户部分提交后用文档中的真实恢复程序恢复整组；已非空 71/9 重启、备份和完整恢复；拒绝首次迁移重放；非空 WAL 和未注册家庭拒绝。不会运行发布、生产迁移、真实云、模型或后台 worker。

可在该候选的独立测试目录运行下面的本地 pytest 入口，每次使用新的输出目录；测试通过只表示这些合成边界成立，生产和 Linux 发布仍待后续审查与演练。

```text
python -B -X utf8 -m pytest tests/test_task_reminders_migration.py -q --basetemp=<新临时目录> --junitxml=<新报告路径>
```

作者本地结果为 33 个唯一用例分别通过：R1 为 32 通过、1 个故障注入步骤失败（Windows 深层备份路径无法建立 SQLite 写入连接），该项改为直接翻转临时备份字节后，R2 单项通过。检查器在两轮之间没有修改，原失败日志和 XML 保留；这不是一次完整 33/33 的重跑记录。非作者审查、Linux 演练和任何生产执行仍是后续步骤。
