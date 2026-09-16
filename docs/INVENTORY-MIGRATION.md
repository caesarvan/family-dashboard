# 家庭物品：48 → 53 表迁移

此工具只承接已安装相册的 **48 张户内表 + 2 张平台表**。新增库存五表、索引、数量及不可变历史约束；不导入真实物品、不修改账本、不连接第三方。代码与合成迁移通过并不表示已经发布；实际安装身份仍见 [README](../README.md)。应用接线见 [库存运行说明](INVENTORY-RUNTIME.md)，字段见 [库存 API](INVENTORY-API.md)。

`deploy/check_inventory_migration.py` 复用已审的媒体快照、完整组备份验证和单库原子 DDL 执行。它只导入无外部副作用的库存领域模块，不调用应用工厂；领域模块追加的五个容量触发器也纳入精确 schema 比较。源文件和最终 SQL 的 SHA 都写入 schema 定义，修改传入 SQL 不能绕过核对。

## 更新顺序

由集成人在冻结源码、完成非作者审查及隔离恢复验证后执行。停止 web、sync、media 和 app，并确认数据卷没有写进程；定时备份也应暂停，完成后恢复。保留当前镜像、完整源码和原 `.env`，不重新生成密钥。

以下命令中的路径必须替换为实际停写数据卷与本轮私有发布目录，输出文件必须尚不存在：

```sh
python -B deploy/check_inventory_migration.py snapshot --data-root /actual/data --output /private/release/before.json
# 使用 deploy/backup.py 的 backup_all(/actual/data) 生成完整库组，保存返回值到 backup.json。
python -B deploy/check_inventory_migration.py validate-backup --data-root /actual/data --before /private/release/before.json --backup /private/release/backup.json --output /private/release/backup-check.json
python -B deploy/check_inventory_migration.py migrate --data-root /actual/data --before /private/release/before.json --backup /private/release/backup.json --output /private/release/migration.json
python -B deploy/check_inventory_migration.py check --data-root /actual/data --before /private/release/before.json --output /private/release/after-check.json
```

每一步必须成功才继续。工具先核对平台家庭目录、全部库和备份清单的映射、大小、散列、内容及 SQLite 完整性，再逐户增表。只接受精确 48 表基线；旧库组、已经迁移的 53 表、混合迁移状态、备份缺户或数据已变化均拒绝。任何中断保留现场，不自动重放或覆盖恢复。

随后以新镜像先启动 app，保持所有业务写入方停止，再次执行 `check`。它核对平台目录、旧 48 表的全部行、列、外键、schema 和序列保持，仅增加精确五表及其 schema 对象，五表为空。通过后再启动同步、媒体 worker、web 和备份定时器，检查健康、身份隔离及新静态文件。对外开放后正常业务写入会改变库内容，不能继续要求旧快照完全相等。

## 恢复与范围

完整库组备份会保存库存不可变操作回执及流水；个人 ZIP 不是整库恢复包。恢复必须使用相配源码、原密钥、平台目录与全部家庭数据库。按照 [媒体恢复](MEDIA-RECOVERY.md) 和 [会话恢复](MEMBER-SESSIONS.md#恢复后使旧成员登录失效) 在恢复后使旧成员登录失效，并重新核对电视许可；旧备份可能恢复后来撤销的授权。53 表的实际恢复演练、Linux 镜像和生产迁移仍须单独验收，本文不宣称已完成。

作者在独立临时 SQLite 验证九项：两户完整迁移、真实工厂重启、五个容量触发器、旧数据保持、备份缺失／散列／内容篡改、schema 输入篡改、混合状态与重放拒绝、旧行或额外索引变化、CLI 输出覆盖保护。最终 **9 passed / 5.97s**；初轮 **8 passed / 1 failed** 为测试自身修改备份后未关闭连接，先被侧文件保护拒绝，修正为关闭连接再验证内容篡改后九项全部通过。原件分别保留在 ignored `test-results/inventory-migration.xml` 与 `inventory-migration-final.xml`；不接触生产库。
