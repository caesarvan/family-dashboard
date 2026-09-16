# 媒体数据库升级

`deploy/check_media_migration.py` 负责从已发布的 **44 张家庭表**增加媒体表。平台仍为两表。它不启动应用、不调用云服务、不自动恢复数据库，也不替代发布人员停止写入服务。不要对当前44表数据库重放历史43→44或43→43工具。

## 范围与约束

- `media47`：`household_media.py` 的三张表（导入、媒体、逐台电视许可）。
- `media48`（默认）：再增加 `media_playback.py` 的播放状态表；缺少该源文件时直接拒绝，不能以占位SQL代替。
- 从固定发布目录读取两模块的字面量 `SCHEMA_SQL`，不导入应用。迁移前重新比对SQL及预期对象。
- 快照包含所有已登记家庭及平台注册库的行摘要、列、外键和完整schema；不输出数据行。旧44表、序列和对象须原样保留，新表必须为空。账户删除trigger虽然挂在旧表上，也须与新源码精确一致。
- 备份必须为 `deploy.backup.backup_all` 生成的完整库组，校验每个文件的摘要、大小和只读内容；拒绝缺库、额外库、链接、旁文件和改动。
- 每个家庭的DDL独立原子提交。跨家庭不是一个SQLite事务：中途失败须停止服务并检查已迁移家庭，工具拒绝直接重放混合库组。恢复需要明确选定完整备份组并另行执行，绝不自动覆盖在线数据。

## 发布顺序

先冻结已审源代码、镜像和Compose配置，确认现有 `.env`（包括已启用AI的配置）保持。实际部署前在隔离的两家庭数据上执行相同迁移与备份恢复，并验证新镜像能够启动。

1. 进入维护窗口，停止web入口、app、sync、已有的media worker，以及定时备份等其他写入者。迁移工具不检测或终止进程，不能带写入者运行。
2. 对同一个数据卷执行 `snapshot`；从固定发布目录运行 `deploy/backup.py`，将其JSON输出保存为私有文件；执行 `validate-backup`。不要仅复制主SQLite文件而漏掉WAL。
3. 执行 `migrate`，然后独立执行 `check`。每一步都检查退出码；失败则保持维护状态。
4. 仅在保持旧数据和新增空表检查通过后，启动同一镜像的app、sync、media和web，检查健康、登录、同步与相册入口。启动后的业务写入不再满足“新表为空”条件，不能重跑发布前的 `check` 作为日常健康检查。

以下为维护人员在容器中使用的参数示例，`/release`须是本次固定源码目录，`/data`须是实际数据卷，`/evidence`须事先创建且仅管理员可访问。先用所选profile确认目标源码齐全；所有输出名必须尚不存在：

```sh
python /release/deploy/check_media_migration.py snapshot --data-root /data --source-root /release --profile media48 --output /evidence/before.json
DATA_DIR=/data python /release/deploy/backup.py > /evidence/backup.json
python /release/deploy/check_media_migration.py validate-backup --data-root /data --source-root /release --profile media48 --before /evidence/before.json --backup /evidence/backup.json --output /evidence/backup-check.json
python /release/deploy/check_media_migration.py migrate --data-root /data --source-root /release --profile media48 --before /evidence/before.json --backup /evidence/backup.json --output /evidence/migration.json
python /release/deploy/check_media_migration.py check --data-root /data --source-root /release --profile media48 --before /evidence/before.json --output /evidence/after-check.json
```

执行前设置 `umask 077`，且确认重定向的 `backup.json`尚不存在；该备份脚本通过 `DATA_DIR`读取卷路径，无命令行参数。`backup.json`必须是实际运行结果，不能手写成功凭证。完整SQLite备份包含加密照片BLOB；恢复也须保留原服务端密钥，否则不能解密。

## 当前验证边界

本候选的7个合成SQLite测试验证两家庭44→47、完整备份与旧行保留、修改SQL/备份/旧行/旧表对象拒绝、混合库组拒绝。实际48表组合、Linux新镜像、备份恢复及生产升级须在电视模块和最终组合冻结后分别记录；本文不声称已经部署。
