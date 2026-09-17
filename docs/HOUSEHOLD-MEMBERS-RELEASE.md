# 家庭成员角色发布适配器

本轮已于北京时间 2026-09-18 05:49:18 完成激活，05:49:55 post 通过，05:55:19 独立读回及随后审计通过。正式包、实际 227 项 Linux 终态及角色列保全见[集中验收](EXPO-HOUSEHOLD-MEMBERS-ACCEPTANCE.md#household-members-release)。下方保留生成器专项及历史父版本边界，固定工具不可重放。

本适配器仅生成未绑定的 9 份本地发布工具，不执行打包、绑定、上传、数据库迁移或服务器阶段。父版本为已安装的旅行 JSON 导入版；本轮户内表数仍为 **58 → 58**，但 `schemaChange=true`：仅 `users` 新增 `household_role` 列，已有两名成员初始化为管理员。它不是无 schema 变化发布。

父工具为私有目录 `expo-trip-import-tools-20260918-r1` 的 7 个 operators、`prepare-package.py` 和 `bind-release.py`；9 份原始字节的完整 SHA 固定在 [适配器](../deploy/household_members_release/prepare.py) 的 `PINNED` 中，先核原始散列再归一化换行。父安装身份：

- archive：`0206b70e83f111fc99431c6021096e90d29cad15787c15788ba8022540c677e4`
- manifest：`79679fa35c8a1ca234c38f26d277150797c1e6ad445d5843d19cde7bfc6fc5a3`
- app/sync/media image：`sha256:578142cb4d209d573ee0c54408d9494833ec49a74df1c5647a403e47ec5a72c1`

生成目录必须是 source-root 下尚不存在的 `household-members-tools-*`；所有工具和 generation 记录以排他方式创建。未提供最终 freeze 时测试数为空；提供 freeze 也只绑定经审查的输入，不能代替实际测试执行。最终 package/binder 和每个服务器入口仍要求独立的七算子审查及外部 binding，保留尝试记录，不自动重放。

## 精确变更与保全

`SOURCE_PINS` 固定已独立审查的 `app.py`、`household_members.py`、`Dockerfile` 和 `deploy/check_household_members_migration.py`。新迁移 helper 固定 SHA 为 `733257bb1e087d8fa54ad50941c7530bbfaed720444cd22563eef1c94c245287`，profile 为 `household_members58`。SQL 摘要来自模块的 `HOUSEHOLD_ROLE_COLUMN_SQL`，同时绑定模块完整 SHA；实际接口见 [迁移说明](HOUSEHOLD-MEMBERS-MIGRATION.md) 与 [API 说明](HOUSEHOLD-MEMBERS.md)。

Docker 只接受已审查 COPY 行增加 `household_members.py` 的精确字节变化（包括该行换行），其余内容不变。`journey_workflows.py` 恢复为相对父版本逐字节不变；其它原受保护后端、认证、TV、依赖、backup、Compose 和资源限制继续保持。保留完整 build input 分区及原有三份额外本地构建来源，不扩大全局发布白名单，不把 Node 测试放进 Python 镜像。

激活顺序继承父版停写、独占尝试、源/环境/镜像保留和完整数据库组备份，只在受控位置增加迁移：

1. 停止备份计时器及写入服务，取得旧 58 表基线；核验完整户库和平台 registry 备份的文件、哈希、不可变读取及内容指纹，保存整组副本。
2. 再次核对原数据与基线完全相同，由固定 helper 调用一次 `migrate`；helper 内部调用自管事务的 `init_schema`，算子不另套事务或直接执行 DDL。
3. 保存 `migration.json` 和 `after-migration.json`。`verify_addition` 证明旧 `users` 五列投影、其余 57 表的行/schema/序列和平台 registry 保全，仅增加批准的角色列并完成初始管理员赋值。
4. 安装源码并仅启动 app，核验镜像、健康、运行字节；要求启动后的完整快照（含 `usersProjection`）等于迁移后快照，再保存 `after-app.json` 与 `preservation.json`。然后才启动 workers/web 和备份计时器。

失败保留现场及完整旧组备份，不自动回滚或重试迁移；恢复须使用已审 helper 的完整组回滚/恢复校验及独立操作流程。本适配器不执行恢复。不能将旧五列投影保全表述为 `users` 完整 schema 没有变化。

post 阶段重新核对新增两份迁移证明与原证明哈希链，并用固定 helper 对记录的迁移前/后快照执行只读 `verify_addition`。新的在线备份校验先保留父级路径、文件 SHA、sidecar、完整 immutable 指纹守卫，再补 `usersProjection` 和 `verify_current`；该当前 profile 接受合法的普通成员角色，不会重新将角色设为 admin。在线备份是逐库备份，不声称整个家庭与平台在同一瞬间的全局快照。

新增匿名 `/api/members` 必须返回 401，其余匿名、TLS 静态资源、已退休资源拒绝、环境哈希及 0600、服务镜像/重启检查均保持。父级检查元组包含一条重复媒体设备路径，本轮保留：**38 个唯一匿名路径、39 次请求**，不能将请求数误写成唯一路径数。

## 实际本地验证与待验边界

[专项测试](../tests/test_household_members_release.py) 的 9 个 pytest 用例实际通过（0.36 秒）。原件位于作者工作树 `test-results/members-release-r1`：JUnit SHA `7d2b90ec03d7db0d99fa941dff3248e12a94a0502eeef42fe64603a241709c86`，stdout SHA `77e9653a0dac9c9f63469a6d07127eaf468c9d487a52b7291da4aefa8bc3019b`，stderr 为空。

实际父 9 原件 CLI 校验使用固定候选 `caf34d5a825716fe2ff0aaf363df0d4412c71e91`，经批量 Git blob 读取核对后，只在独立临时目录生成工具；所有生成工具的网络及子进程调用被拒绝。最终 `test-results/members-release-pinned-r3` exit 0，stdout JSON SHA `847d0df9bbf1b095724341c6bc0f22c00f90bfcc170d21eea47507527d49e30e`，stderr 为空，验证了：

- 实际父 archive/manifest/Docker 与 9 个工具 SHA、4 份批准源码 SHA，以及 196 个完整 build inputs 的选择。
- 122 次源码漂移拒绝、28 个非法 freeze 拒绝、8 个迁移证明损坏拒绝，以及 5 个未绑定服务器入口拒绝。
- 新 `/api/members` 只接受 401；200/403/404/500 均拒绝。迁移仅允许固定 helper 的唯一位置，直接 DDL/init_schema 或其它位置调用均拒绝。
- 正常及带合成 freeze 的临时生成均通过。合成计数 `9991` 仅测试配置边界，既不是收集数也不是执行数；该候选尚未包含本适配器及专项两个文件，报告明确列出这两个缺项，不宣称最终 freeze/打包接受。

CLI R1/R2 失败原件保留：先发现辅助测试不能 `literal_eval` 父匿名路径的字符串表达式，再发现父级原有重复路径；仅修正测试读取/计数方式，没有放宽生产守卫。9 项 pytest 在这些 CLI 辅助函数调整前执行；调整后的完整实际 CLI 已重新通过。生成器在两轮检查间字节不变，前后源码哈希记录见各目录 `evidence.json`。

最终容器选择由 `REQUIRED_TESTS` 的 8 个模块定义：members API、members migration、member sessions、household spaces、device sessions、platform backup、frontend runtime、此 release 专项。最终计数必须由最终冻结源码真实 collect-only 得到，并在 Linux 实际执行后分别报告，不预填。生成器专项当时没有再次运行上述业务/迁移套件，也没有执行正式 package/binder、SSH、迁移、备份或生产阶段；后续正式阶段以文首集中验收为准。
