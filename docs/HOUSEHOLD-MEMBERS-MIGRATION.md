# 家庭成员角色：58 表内单列迁移

本检查器是独立候选，尚未部署。原 `finance_accounts58` 升为 `household_members58`，表数仍为 58，但新增 `users.household_role`，这是明确的 schema 迁移。

仅执行固定 `household_members.HOUSEHOLD_ROLE_COLUMN_SQL` 与已审 `init_schema`：缺列时新增非空 TEXT、缺省 `member`、CHECK 仅允许 `admin|member`；将原 `member1`／`member2` 一次性设为 `admin`。已有列时不重置角色。迁移不改原姓名、用户名、密码、认证版本、会话、私人资料或平台注册库，不启动 app、worker、网络、备份或恢复。

## 保全与中断边界

- `schema_definition()` 核实实际模块来源、源码散列与精确 DDL；不是只数表。原 users 五列、默认值、主键及 schema 需符合旧结构。
- 沿用 media 的完整表行／schema／列／外键／`sqlite_sequence` 与注册库指纹。snapshot 另外附各户 users 原五列投影散列及角色摘要；投影读取事务内的完整 users 指纹必须等于先前完整快照，无明文用户资料写进报告。
- 迁移核实原五列投影相同、初始角色精确、其余 57 表及序列原样，唯一 schema 差异是该列。后续 `snapshot-current` 可接受合法普通成员角色，不要求永远全部管理员。
- `validate-backup` 保留原完整 immutable 指纹、文件摘要、路径、独立文件与 sidecar 检查；另核新增投影，不能以投影取代完整备份验证。全组包含平台注册库和每一户数据库。
- 每户由 API 初始化器独立事务提交，整个多户组不是一个事务。所有写入者必须从快照到迁移后验证持续停止。任何半迁移、重复执行、备份或源数据漂移都拒绝盲目重放；保留现场后明确按原完整组备份恢复，再用 `check-rollback` 核对。检查器自己不复制、恢复或删除数据库。

## CLI 契约

入口 `python -B deploy/check_household_members_migration.py <action> --data-root <停写数据根> --output <新JSON路径>`。输出必须不存在，使用 exclusive 创建且设为 0600；已有输出不覆盖。固定发布算子仍须另行审查并绑定真实源码、备份、镜像和操作授权，以下动作列表不代表本候选已在生产执行。

| action | 输入与含义 |
|---|---|
| `snapshot` | 原 58 表、users 五列完整组快照 |
| `validate-backup` | `--before` 与 `--backup`；核完整原／新角色结构备份及当前源与快照一致 |
| `migrate` | `--before` 与 `--backup`；全组预检查后按户执行已审初始化器，再核列迁移及备份仍完整 |
| `check` | `--before`；核当前组仅发生预期列迁移 |
| `snapshot-current` | 新角色结构完整快照，可含普通成员及非空资产账户 |
| `check-restored` | `--before` 为新结构参考；核恢复组所有完整指纹与角色投影一致 |
| `check-rollback` | `--before` 为旧结构参考；核完整组回退后五列 users 与其余数据／schema／序列一致 |

恢复后如需失效会话，仍沿[部署恢复规程](DEPLOYMENT.md)在完整恢复验证之后单独执行；不能把失效后的数据变化混入原恢复相等断言。在线逐库备份不等同跨库原子快照。

## 验证记录

专项使用真实临时两户 Flask／SQLite、非空资产账户与回执、资料 BLOB 和序列间隙；覆盖原五列保全、普通成员角色重启保持、两户完整备份／恢复、部分迁移拒绝重放、DDL 后角色更新失败整户回滚、真实 SQL 篡改及不可变备份保护。首轮在固定组合 `d0998d8da8d12c9f7251a5b2f30d7b2d880e6f3c` 实际通过，原件 `test-results/members-migration-r1/` 保留；随后公开只读 `users_projection` 接口供发布后 immutable 备份校验，并补快照间并发改变与 DDL 前拒绝漂移检查，最终结果待下轮记录。未进行生产、真实云或恢复覆盖。

依赖：成员 API `d995f39109ff23e0b04ab72f7711a044ed5df321` 与实际 app 注册 `2f1e2d8474a6d7256ce8fde4c2c3e84a96cf6cc5` 均经非作者审查；只在本独立分支按集成人授权合入后运行，不使用浮动源或混合模块导入。接口详见[成员管理](HOUSEHOLD-MEMBERS.md)。
