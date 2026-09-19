# 本人站内提醒：71 表发布适配

本页为独立候选工具合同，不是发布回执。功能、个人导出和精确建表分别见 [TASK-REMINDERS](TASK-REMINDERS.md)、[TASK-REMINDERS-PORTABILITY](TASK-REMINDERS-PORTABILITY.md)、[TASK-REMINDERS-MIGRATION](TASK-REMINDERS-MIGRATION.md)。仅集成人在源码、正式包、浏览器、Linux、完整组演练和发布计划分别审查后执行生产动作。

## 父版与固定输入

父版是已经激活并通过独立只读审计的任务依赖版本，一户两库当时保持家庭 69／平台 9 表。下面是正式包的身份，不用后续 merge commit 替代：

| 原件 | 固定值 |
| --- | --- |
| source / tree | `456585bc1a4f820ca238b3308f09a8d591628f41` / `65a93964e5f20088a8cd0bad878fd03c84dccc94` |
| package | `e4bf7d523a46870de53cc13cdbde3fd5510e39577c325beb452f75a9788b0ca2` |
| manifest | `14f5d762ae07ee33a5228631faa6dc6984da7b2a71e2fc5e508781d786e4aeec` |
| image | `sha256:fbb221027f4542cbfb3f9dc66b26d38314bfbbf2df00e43744936b8288fea547` |
| 独立生产审计 | `ea6f6cebea08105f7d809d0220c28c8e8de02ae35b599fcf6cd371d690ca17df` |
| env | `a72d456815cf113b1ac0c1e032ac8c45b300ccf2cb499520c14b7f54d5314e07` |

本机核对来源为 `task-dependencies-release-20260920-r2/package/` 和该批 `production-audit-r1/task-dependencies-production-readonly-r1.result.json`。新计划的 review bag 必须包含上述审计原件，验证器按完整 SHA 强制核验；文件名可由集成人安排。父包、env、web 镜像和既有 membership marker 的固定规则保持。

入口为 `deploy/build_task_reminders_release.py` 的 prepare／verify／build／validate／assemble，以及 `deploy/activate_task_reminders_release.py` 的 stage／activate。固定 profile 为 `task-dependencies-r2-task-reminders`；不能从 JSON 或 CLI 增加 profile、可变模块或改变父版。32 个发布工具逐文件绑定，包含未修改的 `check_task_reminders_migration.py`。

提醒入口显式提供 69/9→71/9 的 CLI 帮助文案；共享 `main` 的可选 description 参数默认保持旧入口行为，运行时准入、锁与信号处理不变。

运行范围从 105 增至 106 个非 Expo 文件：新增 `task_reminders.py`；只允许改变已有的 `app.py`、`sync_worker.py`、`household_memberships.py`、`data_portability.py`。其余 **101 文件**的名称／摘要映射固定为 `bfb422fbe62093446a2f6c14e0a6a705470b6b2e4e27989b509624a46665f3c0`，包 metadata 不能扩大豁免。所有运行文件仍须逐字节匹配新包。

Dockerfile 只在已有依赖 COPY 行加入 `task_reminders.py`；这一行从原 CRLF 变为 LF，其余字节保持。固定 Docker SHA 为 `6960db583e7c84dbeddd3c026054b989a878e31e56c9787728c9e9cde3bfebc9` → `7fca420d3f86a35742385f7b39719c6d5ebf6c9d08c0e764333ae15ebb46763f`。Compose、env、requirements、依赖锁文件和固定 `prepare_release.py` 不变。强制包含新的前端提醒测试及明确列名的提醒／依赖 browser 脚本，不放宽整个 `scripts/` 目录。正式包必须使用最终已审工具和匹配的 fresh Expo 原件；脚本入包不等于业务演练通过。

## 停写迁移顺序

1. stage 只核候选镜像、原件、父版服务／配置和 marker，独占写入新 stage 回执，明确记录 69/9→71/9。
2. activate 再核 stage 和当前父版，独占建立 attempt；保存旧源码、配置、服务环境、镜像，停止备份 timer、web、media、sync 和 app，确认全部数据写入者停止且干净退出。
3. `begin` 备份完整注册库和每个家庭库，逐库验证保留原件；`migrate` 只新增两张空提醒表，平台保持 9 表，没有回填。
4. 安装固定源码／镜像，只启动 app；核健康、运行字节及完整环境后干净停止 app，再运行 `check_stopped`。原 69 表、平台、序列、用户、任务、资金及 **全部 settings** 必须保全，新两表仍为空，结果必须匹配迁移后的完整组逻辑摘要。
5. 仅在上述检查通过后恢复 app、sync、media、web，核镜像／环境／运行字节和公开 health。对提醒列表和 32 个零构成的合成操作 ID 执行匿名 GET，均须 401，再恢复备份 timer。

worker 正常运行后会生成本人提醒状态及 `settings['task-reminders-worker']` heartbeat，属于迁移验收之后的正常活动。不能把活库随时间变化误称停机保全失败，也不能为了启动 worker 而豁免 app-only 阶段的任何 settings 行。controller 保留 app-only 完成时的固定原件；上线后的独立只读审计必须区分停机证明和活跃状态。

## 失败与恢复

任一备份、迁移、app 启动或保全失败均保留 attempt 和原始现场。候选曾启动时沿用原控制器停止全部候选写入者的清理流程；清理失败不能声称已经停服。不会自动恢复或启动旧应用，不重放已消费计划。跨库部分迁移必须保留现场；若集成人决定回滚，恢复同一完整组备份（注册库及所有家庭库），按迁移文档的 `verify_rollback` 只读核验，才可安排新一次发布。不得只恢复部分家庭库。

本批工具测试只使用临时 Git／tar／文件系统和记录式 Docker／服务调用，覆盖完整包固定边界、原件篡改、父审计绑定、69→71 顺序、匿名读取失败及不可重放。实际 DDL／SQLite 保全由已审迁移 checker 的独立测试提供；本批不重复 API、浏览器、模型、npm 或生产测试。正式 Linux、stage／activate、生产审计、真实账号和本人验收仍须另有真实结果。
