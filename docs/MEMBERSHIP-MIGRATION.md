# 成员关系迁移的只读前后核验

[核验器](../deploy/membership_migration.py) 比较已停止写入并关闭连接的 SQLite 副本；不执行 DDL、迁移、备份、恢复、应用启动、网络或发布操作。它不属于此前 58→58 发布工具，也不提供回滚授权。输入数据库仅以 `mode=ro&immutable=1` 打开，并设置 `query_only`；期望 DDL 仅在内存数据库构造。

本批基线为 `8e6a9954aec21ac69cf0c9d33817f631c4a789f4`。DDL 参考固定领域 `754d2e1552c8953b9d490df246d1328bdf3abf43`、个人账户 `e5a39274076607e89b9df6c2052d9565018e6ad1` 和接线 `ae8c5698f055f3a0a384bf23ab1d0ece0a3e5069`。这是候选核验契约，不是生产迁移通过记录。

## 核验规则

| 数据库 | 唯一允许增量 | 原内容保全 |
|---|---|---|
| 户内 | 58→61：`household_memberships`、`member_invitations`、`membership_operations`；`member_sessions.personal_identity TEXT` 可空；新增 settings 标记 `membership_schema_v1` | 原 58 表、用户 ID/密码/实际角色、财务/媒体/云 owner、原行与旧列、索引/触发器/视图、`sqlite_sequence`、原 user_version/application_id |
| platform | 2→9：七张个人账户/会话/目录/资格/操作/限流表；user_version 从 0 到 1 | 原 households 与 household_invitations 的行和完整 schema；原索引及 application_id |

- 新增 DDL 与固定源码常量逐字一致，包含 SQLite 自动生成的唯一索引；不接受多表、多列、多索引或不同约束。
- 新会话字段在所有旧行必须为 NULL；完整旧列投影的散列与原表一致，不能借迁移撤销、重签或绑定旧会话。
- settings 仅多 `('membership_schema_v1','{"version":1}',1)`；原 meta revision 和其他设置不能变。
- 每个旧 users 恰好有一条新关系，随机 32 位小写 hex ID、未绑定账户、active、revision=1、有限非负且创建/更新时间相同；不重置旧普通成员为 admin。邀请和户内回执为空。
- 平台七张新表必须全部为空；迁移过程不能顺便注册账户、签发个人会话或创建目录。
- 原表比较包含列类型、约束和全部旧行；行散列保留重复数与 SQLite 值类型，BLOB 仅参与散列。输入错误只返回固定代码，不回显 SQL、值、路径或数据库异常正文。
- 缺库、空文件、损坏、外键异常、缺原表、已有迁移标记、额外 DDL、任何旧行变更均拒绝。符号链接/Windows reparse 路径、同一文件作前后、残留 WAL/SHM/journal 均拒绝；不尝试 checkpoint 或清理 sidecar。
- 输入文件在读取前后和比较结束再核 SHA-256。它是停写副本的核验，不证明多库读取同一瞬间，也不保护仍在运行的写入者。

## 调用与结果

纯库接口 `verify_household(before_path, after_path)`、`verify_platform(before_path, after_path)` 成功返回有限统计/散列，失败抛 `MigrationCheckError`。不需要导入应用、个人账户或领域运行模块。

```text
python -B deploy/membership_migration.py \
  --household-pair before/home.sqlite3 after/home.sqlite3 \
  --household-pair before/second.sqlite3 after/second.sqlite3 \
  --platform-pair before/platform.sqlite3 after/platform.sqlite3 \
  --output new-verification.json
```

输出必须位于所有输入目录之外，只用排他创建，已有文件不会覆写；不安全/非新输出在创建前直接拒绝。核验失败保留 `{verified:false,readOnly:true,code}` 并退出 1。成功退出 0，记录固定来源、各表行数/列/行/schema/file 散列，不记录用户名、密码散列原值、成员 ID、财务内容、邀请/会话原值或数据库路径。

CLI 检查所有显式输入对且禁止重复文件；其 scope 明确为 `explicit_pairs_not_registry_completeness`。调用方负责枚举全部家庭、将每对副本绑定到正确家庭及经过审核的停写全组备份；不能用一对库通过代称整个 registry 已迁移。核验器不读取配置或 .env，不自行寻找运行数据。

## 本地验证与边界

[专项](../tests/test_membership_migration.py) 从本地不可变 Git 对象批读历史 Python 源码，在独立临时进程启动真实旧 Flask/SQLite、通过真实 HTTP 创建第二家庭和旧会话，保留普通角色、非空私有财务、审计序列和平台邀请。副本使用上述固定三来源实际启动并重启；所有 socket connect 被禁止，不启动 worker。

测试同时比较固定 DDL 字面量，并验证密码/角色/owner/设置/会话/序列漂移、遗漏关系、错误初值、非空新表、额外 DDL、损坏/缺库/sidecar、输入变化及排他输出。运行需要本地已有指定 Git 对象；不会自动拉取，不作为无 Git 的旧 Python 镜像测试声称通过。

实际首轮 `test-results/membership-migration-r1` 为 51 PASS／0 失败错误跳过，9.93 秒；XML SHA-256 `3fbab890f3460c486d26ac44ae0ca6b57a44ee7decc9468011588ebb8dc6cc97`。随后仅新增输出目录拒绝约束与三项边界，`membership-migration-output-r2` 实际 4 PASS／50 deselected，5.77 秒，包含原 CLI 正反例回归；XML `7fc592c87c31ab1ea851128b351b1aeaa8fd72392cc8bed6bff40e2ef25a6933`。共 54 个不同用例，不声称最终版本全套再次执行。两轮 stdout/stderr、源文件前后散列、固定历史源清单和临时副本均保留。

独立接线的最终组合仍由 Root 再验，本工具与开发副本测试不代表部署、真实个人账户、云操作或生产备份/恢复已通过。
