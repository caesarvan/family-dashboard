# 库存与媒体：53 表恢复专项

`tests/test_inventory_restore.py` 使用真实应用工厂、邀请创建第二家庭及实际成员认证，在两户各 53 张表、平台 2 张表的临时 SQLite 上演练。工厂必须自行注册库存、媒体和播放模块；不提供注册 fallback。不调用云服务，不启动 worker，也不操作生产。

通过实际库存 API 创建私有物品、采购关联批次、分次收货、消耗及反转，保留原事件和幂等回执。另用原媒体 API／Pillow／Fernet 建立两户私有与共享照片、旅行关联、加密 metadata／preview BLOB、逐台电视许可和暂停播放状态。库存来源表尚无金融来源 HTTP 写接口：测试仅通过核心 `apply_with_receipt` 受信事务接缝写入明确的合成来源，用于验证恢复和 `export_inventory` 的 owner 投影，不声称已接入真实订单、账单或金融来源。

恢复复用 `backup_all` 的两户三库完整组，核对 manifest 中每份快照 SHA，再从 `documented_programs` 提取 [部署文档](DEPLOYMENT.md#6-备份恢复与回滚) 的原程序。仅将固定 `/data` 换为测试临时目录；恢复算法、参数语义、迁移工具和 controller 不改。恢复后在执行任何身份失效 SQL 前，精确比较全部 53 表及平台两表的 schema、行、BLOB 和序列。

每个恢复家庭执行 [原登录失效 SQL](MEMBER-SESSIONS.md#恢复后使旧成员登录失效)，核对用户版本加一、会话撤销及 OAuth 状态清除，实际四份旧 cookie 访问库存／媒体均为 401。新登录后验证：

- 库存现有量 6、在途 2，原采购关联、四条不可变流水及反转引用保持；数据库仍拒绝修改／删除流水和回执。
- 原创建、批次、收货及反转载荷合法重放只返回已有回执，五库存表与四媒体表均不变化；他人回执、私有条目和另一家庭 ID 不可读。
- 合成来源仅进入本人的核心导出；伙伴的共享投影不包含订单编号、来源摘要或明细键。
- 媒体密文逐值保持、照片实际解密后 SHA 相同，私有／共享、旅行及跨户隔离仍成立；获准电视读取、未获准电视拒绝，明确撤回后旧预览不可再读。

原 `test_media_restore.py` 的当前工厂硬边界同步为 **53**，同时精确核对五库存表和四媒体表，原媒体 BLOB／权限断言全部保留；[媒体恢复说明](MEDIA-RECOVERY.md) 中 48 表描述是该阶段记录。历史 `test_media_migration.py` 仅在合成旧库 fixture 中显式禁用后来的库存 registrar，继续严格测试 44→47／48；没有放松为任意表数，也没有修改旧迁移 helper。

本地运行：

```powershell
python -B -X utf8 -m pytest -q tests/test_inventory_restore.py tests/test_media_restore.py tests/test_media_migration.py
```

Linux 候选需另外使用最终不可变镜像执行，运行模块来自镜像，测试／文档／deploy 辅助文件只读挂载；本地通过不等于 Docker 恢复或生产验收。恢复前保持 app／sync／media worker 和外部入口停止，核完整组、密钥及真实 schema；失败不开放部分家庭。旧快照可能带回备份后的撤权和旧电视许可，原成员失效 SQL 不会自动撤 TV，重新核对或撤回后才恢复展示。库存新流水也不能靠恢复旧快照“撤销”，已有业务写入须先由维护者处理恢复时点及损失边界。
