# 本人手动账户：55→58 迁移检查器

这是独立候选工具，尚未接入发布流程或执行生产迁移。依赖 [账户 API](FINANCE-ACCOUNTS-API.md) 的固定 schema 与 [应用接线](FINANCE-ACCOUNTS-INTEGRATION.md)。不能用既有 55→55 发布脚本部署这个增加三表的版本。

`deploy/check_finance_accounts_migration.py` 只应用 `finance_accounts.py` 的 `FINANCE_ACCOUNTS_SCHEMA_SQL`，严格限定三条建表语句：`finance_accounts`、`finance_account_valuations`、`finance_account_operations`。绑定模块来源、源文件 SHA、SQL SHA、对象、列及外键；拒绝额外 SQL 和已有对象名碰撞。原 55 张户内表（含认证与会话表）及平台注册库保持，新增三表必须为空。

## 操作契约

所有操作的前提是停止 app、同步／媒体 worker、备份定时器和其它数据库写入者，并保持停写直至完整保全核对结束。本工具不负责停服务、创建备份、恢复数据库或启动应用。逐库事务不能代替跨库停写；正常在线逐库备份也不能称为全组原子快照。

每条命令接受 `--data-root`、独占的新 `--output`，需要时传 `--before` 快照 JSON 和 `--backup`（既有 `deploy.backup.backup_all` 返回的结果 JSON）。输出文件不得已存在或为符号链接；结果权限设为 `0600`，CLI 标准输出仅摘要。

| action | 作用 |
|---|---|
| `snapshot` | 完整读取注册库和全部家庭，验证严格 55 表基线。 |
| `validate-backup` | 对 55 或 58 表快照核验当前库仍完全一致，再核验包含注册库与所有家庭的备份 manifest、路径、大小、SHA、不可变 SQLite 内容；拒绝缺项、重复、旁路文件及 sidecar。 |
| `migrate` | 重核固定 schema、55 表基线、碰撞、当前快照和完整备份；每户一个显式事务建三表；核对旧表全部行、schema、列、外键与 `sqlite_sequence`、注册库及家庭集合；新表为空，并再次验证原备份。 |
| `check` | 以迁移前 55 表快照为参照，验证当前正好为上述空表增量。 |
| `snapshot-current` | 验证 58 表结构并记录完整快照；允许三表已有真实账户、估值与操作回执。 |
| `check-restored` | 对恢复后的 58 表完整组与原 58 表快照逐项精确比较，包括已填新表；不要求新表为空。 |
| `check-rollback` | 对显式恢复后的完整 55 表组与原迁移前快照精确比较；本操作只核验、不执行恢复。 |

备份与恢复沿用 [部署文档](DEPLOYMENT.md) 的完整组程序及 [成员会话恢复失效处理](MEMBER-SESSIONS.md)。先核对恢复的行／schema／序列与注册库完全一致，再按已审流程失效旧会话。恢复 55 表时应配套原 55 表应用；不能启动会自动初始化新表的 58 表应用后再声称回滚成功。

单户 DDL 失败会回滚该户全部新增表。若进程在两个家庭之间中断，已完成家庭与未完成家庭可能并存；再次运行会因快照漂移拒绝。保留原证据、检查失败原因，必要时显式恢复完整旧组并用 `check-rollback` 核对，不自动重放，也不只恢复其中一个数据库。已经产生新账户记录后，旧备份不含这些记录，回滚决策必须另行处理这些新增数据；本工具不会丢弃或合并它们。

## 本地验证范围

专项使用临时真实 Flask／SQLite 创建两个家庭，原库含旧流水、导入／持仓回执、资料 BLOB 和存在间隔的自增序列；网络被禁止。覆盖 55→58、应用启动后的零额外变化、已归档账户／零与未知估值／历史回执的完整备份恢复与重新登录读回，完整及中断迁移后的 55 表恢复，并验证备份损坏、源漂移、对象名碰撞、额外 SQL、单户原子回滚和 CLI 独占输出拒绝。

同时运行原 `tests/test_investment_operation_migration.py`。该旧模块只增加 fixture 级禁止新账户注册，保留真实 54→55 历史工厂和原有全部表数／数据保全断言，不删除表或放宽比较。

实际命令：使用主仓 `.venv/Scripts/python.exe`，在作者 worktree 执行 `-B -X utf8 -m pytest tests/test_finance_accounts_migration.py tests/test_investment_operation_migration.py -q --junitxml=test-results/finance-accounts-migration-r1/results.xml`。首轮 **42 passed（新 33、旧 9），73.22 秒，零失败／错误／跳过**；JUnit SHA-256 `ba2234d4256d83963e8e67303138f6556da6bc913025d22b33b55df37403e212`，stdout `6ff9cfeb361621c79f720a77a27dc33102f2cae9b418b9e7154b1af858f45651`，stderr 为空。原件只留作者 worktree 的 `test-results/finance-accounts-migration-r1/`，不入库；该轮执行后 checker 和两份测试文件未改。未进行服务器、Docker、真实家庭数据或生产恢复演练。

后续仅维护本次新增注册直接影响的历史工厂，保留原断言：`test_finance_receipt_migration.py` 的 53→54 套件增加禁用 accounts 注册，独立执行 **20 passed／33.88 秒**，JUnit `12261579da2ec345e857e26363aaadf064edd6302cc25c96663bd67442696a6d`，原件 `test-results/finance-accounts-historical-receipts-r1/`。库存 48→53 与媒体 44→47/48 的历史 fixture 也仅各禁用这次新增注册，随后仅执行 `tests/test_inventory_migration.py tests/test_media_migration.py`：**22 passed（9＋13）／15.19 秒**，JUnit `463e6094005f5445c10edd003c401304a41d752f73ee565de066e4b40251a3b2`，原件 `test-results/finance-accounts-historical-inventory-media-r1/`。这两轮均零失败／错误／跳过，测试源前后 SHA 不变；没有重跑已过的 42 项，不能将三轮记录称为一次全仓验证。

静态检查另发现更早就存在的历史工厂与声明表数差异，本批未改、未运行、未据此声称这些套件通过：`test_inventory_restore.py`／`test_media_restore.py` 声明 53 表，但直接调用后来已包含回执及持仓操作表的应用工厂；`test_journey_documents_migration.py` 声明 42→43，其内嵌工厂仅禁用 documents／places 注册；`test_journey_places_migration.py` 声明 43→44，仅禁用 places 注册。这些旧工厂还会加载后加的媒体、库存、回执等模块，问题早于本次三表增量，应另行维护准确历史依赖，不能通过提高旧断言表数掩盖迁移边界。
