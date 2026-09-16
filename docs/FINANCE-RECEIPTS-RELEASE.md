# 账单回执：53 → 54 表迁移与恢复

本轮新增 `hub_import_receipts`，保存本人明确导入操作的持久化结果。`hub_imports` 保留原七列；逐笔首次来源写入既有交易 JSON。旧记录的未知来源不会通过迁移推断或回填。本文对应独立候选，源码提交、隔离测试、审查、实际发布分别记录；本文不表示生产已迁移。

迁移入口为 [check_finance_receipt_migration.py](../deploy/check_finance_receipt_migration.py)，回执业务契约以 `finance_hub.py` 的实现及本轮 API 文档为准。此工具依赖包含 `FINANCE_IMPORT_RECEIPTS_SCHEMA_SQL` 的后端候选；不能在缺少该常量的旧源码中运行。测试使用 [test_finance_receipt_migration.py](../tests/test_finance_receipt_migration.py)。

## 迁移保证与限制

- 原数据必须是每户精确 53 张业务表，平台注册库精确两表。新增一张回执表后，每户为 54 表；SQLite 内部序列表另行完整比较。
- SQL 只读取同一源码目录的 `finance_hub.FINANCE_IMPORT_RECEIPTS_SCHEMA_SQL`。内存库验证单条 DDL 的对象、列和外键；不运行应用工厂或 worker，不调用云端，不导入新财务数据。
- 先核对完整户组快照与组备份：数据库集合、字节数、SHA、完整表内容、schema、外键与 SQLite 序列均一致。备份缺失、重复、路径异常、内容变化或备份侧车文件会被拒绝。
- 每户在独立 DDL 事务中创建新表；全部原 53 表的行、BLOB 摘要、列、外键、索引、触发器和序列保持，新表必须为空，平台注册库保持。
- 全组迁移不是跨 SQLite 的原子事务。中途失败会保留实际结果供检查，混合或已经迁移的组不能再次当作 53 表基线；工具不会自动恢复、删除新表或重放操作。
- 源码或数据库在核对之后变化时拒绝执行。停写是调用方责任；本脚本不会停止服务，不能把快照检查当作已停写的证明。

## 发布指导

由集成人使用已审查的源文件、构建和发布清单，独立核对实际旧镜像、旧 manifest、原配置及 53 表基线。停止应用、同步、媒体 worker、外部写入口与备份定时器之后，才生成下列输入。不要复用历史发布目录或覆盖原报告。

以下占位路径必须替换为本次已核对的绝对目录；`/data` 表示已停止写入的完整数据卷。运行环境须包含此次完整后端源码及其既有依赖。

```sh
python -B deploy/check_finance_receipt_migration.py snapshot \
  --data-root /data --output /review/new-release/before53.json
DATA_DIR=/data python -B deploy/backup.py > /review/new-release/backup-result.json
python -B deploy/check_finance_receipt_migration.py validate-backup \
  --data-root /data --before /review/new-release/before53.json \
  --backup /review/new-release/backup-result.json --output /review/new-release/backup-verified.json
python -B deploy/check_finance_receipt_migration.py migrate \
  --data-root /data --before /review/new-release/before53.json \
  --backup /review/new-release/backup-result.json --output /review/new-release/migrated54.json
python -B deploy/check_finance_receipt_migration.py check \
  --data-root /data --before /review/new-release/before53.json --output /review/new-release/checked54.json
```

`snapshot` 和 `check` 的完整报告只包含行摘要与计数，不输出真实行值。仍按私有发布资料保存，不进入 Git。所有输出文件必须尚不存在，工具创建后将其权限设为 `0600`。示例中的备份输出重定向同样须保证新路径且由调用方设置私有权限。

迁移及独立检查成功之后，由发布流程安装并启动新应用，继续核对新工厂未改变原记录、配置和后台服务，再检查同源静态资源、匿名权限、服务健康与实际备份。Git 合并、迁移成功和线上发布是三种不同状态，不互相代替。后续 54 表内更新不能重放此次 53 → 54 命令。

## 包含已保存回执的完整恢复

迁移后发生真实导入时，新表不再要求为空。`snapshot-current` 只接受完整 54 表且回执对象、列和外键与当前已审查源常量一致，可生成包含现有回执摘要的参考快照。

```sh
python -B deploy/check_finance_receipt_migration.py snapshot-current \
  --data-root /data --output /review/recovery/current54.json
DATA_DIR=/data python -B deploy/backup.py > /review/recovery/backup-result.json
python -B deploy/check_finance_receipt_migration.py validate-backup \
  --data-root /data --before /review/recovery/current54.json \
  --backup /review/recovery/backup-result.json --output /review/recovery/backup-verified.json
```

恢复操作沿用 [部署文档中的完整平台恢复](DEPLOYMENT.md)；明确选择同一 manifest 的平台注册库及全部家庭库。恢复演练应使用新的隔离目录或卷，不能先覆盖原目录。恢复前保留故障数据与完整原件；本工具只核验，不负责复制或自动回滚。

恢复全部数据库后、尚未启用应用或修改认证状态时执行：

```sh
python -B deploy/check_finance_receipt_migration.py check-restored \
  --data-root /restored-data --before /review/recovery/current54.json \
  --output /review/recovery/restored-verified.json
```

该检查要求参考与恢复后的整个组完全一致，包括回执、原交易、批次、所有其他业务数据、平台注册库、schema、索引、外键、BLOB 和序列。它不要求回执表为空。随后按 [成员会话恢复说明](MEMBER-SESSIONS.md) 撤销恢复的旧会话及进行中 OAuth，再启动恢复应用；这一步会明确改变认证表，不应将其后的状态误称为逐行未变。

隔离验收须通过真实登录检查两户各自的回执与首次来源；同请求读取／重放保持历史结果，不能重新入账，另一户相同成员 ID 不能读取回执。恢复旧 Cookie 在会话失效之后必须被服务端拒绝。没有生产授权覆盖恢复、真实外部云或真实账单验证时，不能将这些隔离检查写成真实平台端到端验收。

## 历史迁移回归

此前 44 → 47／48 媒体与 48 → 53 库存测试仍维持原表数和原断言。它们只在构造对应历史工厂时暂时把新回执 schema 常量设为空，离开该构造范围后恢复；不删除真实新表、不跳过测试，也不把当前 54 表伪装成旧生产库。53 → 54 和包含实际回执的当前工厂／恢复由本轮新测试负责。

实际测试命令、结果、失败修订与源提交身份随本候选交付，组合与发布证据进入 [验证记录](VALIDATION.md) 和 [交接说明](HANDOFF.md)。
