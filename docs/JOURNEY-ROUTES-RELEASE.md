# 路线三表迁移与发布

状态：**2026-09-19 22:56:47（北京时间）已上线，22:57:29 独立只读审计通过。** R2 正式 Expo 构建、四场景真实临时浏览器与视觉核对、Linux 189 项零跳过、合成迁移／恢复演练分别通过。实际生产一户两库完成户内 66→69、平台 9→9，原数据、环境及成员迁移 marker 保全，四服务恢复。完整发布身份与本次执行记录集中在[路线验收](JOURNEY-ROUTES-ACCEPTANCE.md#journey-routes-release)。本次计划已消费，不可重放；上线不代表本人或 TV 验收，也不改变 A–D 的 0/4 口径。

## 固定基线与范围

`build_journey_routes_release.py` 的显式 profile 为 `finance-query-r2-journey-routes`。本次升级前的财务查询基线固定为：

| 项目 | 身份 |
| --- | --- |
| source | `68631bfe02d822434e8557aa247f0148d4e9d7dd` |
| tree | `136dec1288fe7fe5ea94b59b0ea2282de32c8ebf` |
| image | `sha256:73f18b95d870e49296320347d0988bb0232f120c9481d5f881bba0ad2748abac` |
| manifest | `21e0588d81730eda5e45fad16f25e9599e5f4f8bbb491b2aa65320d33d6b8270` |
| package | `509fe53dc0c5504aa4c64aa60ff9ab293458110687135123481a66627c080f78` |
| 独立只读审计 | `571afbe62c191018bab5c5d9ae63af1b12a4a73f7078a04f32bd3df17fe1575c` |

户内表从 **66 增为 69**，平台仍为 **9**；不会重放先前 61→66 迁移。三表为 `journey_routes`、`journey_route_stops`、`journey_route_operations`，两索引为 `journey_routes_owner`、`journey_routes_journey`，无新触发器或旧表修改。DDL 唯一来源是实际 `journey_routes.SCHEMA_SQL`，UTF-8 SHA-256 固定为 `2752b5ccc249cc78b84deb515bc6077452d9fc90606b6fd6bb14aac913038304`；通过模块本身的 `initialize_journey_routes()` 执行，无本地复制的 DDL。

Docker 只允许在 `COPY assistant_finance_query.py ./` 后加独立 `COPY journey_routes.py ./`：旧 SHA `f68324febf8438eb7e0ed1277998e33510c948503a8cf9c633062ba8027cdefb`，新 SHA `36f5d699823890c26dbc243010f584c5aa5d44c109bd6e63b705e9e025a2a90b`。依赖、Compose、Nginx 和原环境不变。共享包工具仅增加显式 profile，旧 profile 的常量与接受条件保留。

## 数据与失败边界

`check_journey_routes_migration.begin()` 复用既有 populated 66/9 全组备份：平台登记的所有家庭数据库都必须存在并纳入原件、备份清单和逐字节校验，五张已有分析表允许非空。保留原 `assistant-trip-change-release-attempt` 回执格式；本批 plan/source/image 身份绑定区分新尝试，不改变已成功的 membership marker。

`migrate()` 先核对原组、保留备份、DDL 和源文件身份，再独占写入 `migration-attempt.json`，逐户在显式事务内执行初始化。必须保全全部原表的 schema、列、行、SQLite sequence、版本和平台库，仅增加精确三表两索引。每户事务独立；第二户失败时第一户可能已完成，不宣称跨库原子性。不覆盖失败原件、不自动重试，不以 `IF NOT EXISTS` 重放失败尝试。

迁移回执为 `migrated.json` 和 `migration-result.json`。新 app 实际启动、健康检查后再次干净停止，再由 `check_stopped()` 绑定前述回执并核对完整组，写入 `after.json` 和 `result.json`。只有通过后才开启 app、sync、media、web 并恢复备份 timer。迁移及首次启动验证期间三张新表须为空；这不声明开放服务后的活动数据库仍为空。

`snapshot_current()` 与 `verify_restore()` 支持已非空的 69/9 组，包含软删除路线、不可用地点占位和操作回执；正常重启不得擦除任何记录。完整 66/9 回滚通过 `verify_rollback()` 复用旧分析恢复校验，必须先恢复保留的全部数据库组和原 marker，再验证完整逻辑内容，不能只恢复默认户。工具不执行恢复、删除新表或撤销会话；任何后续恢复操作应沿现有运维流程进行，原失败证据和发布前后回执继续保留。

## 工具入口与执行顺序

包、构建、验证和计划组装复用现有 `membership_release_*` 与 `assistant_trip_change_release_plan` 框架，输出目录必须全新；plan 绑定完整源、Expo 输入和产物、测试精确 nodeids/JUnit、image/runtime、operator 与审查原件哈希。没有新增独立审批层。

```text
python -B deploy/build_journey_routes_release.py prepare --repo <fixed-clean-repo> --commit <head> --export-dir <export> --build-evidence <evidence.json> --evidence-sha256 <sha> --output-dir <new-package>
python -B deploy/build_journey_routes_release.py verify --output-dir <new-package> --package-sha256 <sha>
python -B deploy/build_journey_routes_release.py build --package-dir <new-package> --package-sha256 <sha> --output-dir <new-build>
python -B deploy/build_journey_routes_release.py validate --package-dir <new-package> --package-sha256 <sha> --image-id <image> --selection <selection.json> --selection-sha256 <sha> --output-dir <new-validation>
python -B deploy/build_journey_routes_release.py assemble --package-dir <new-package> --package-sha256 <sha> --build-dir <new-build> --build-sha256 <sha> --validation-dir <new-validation> --validation-sha256 <sha> --reviews <reviews-map.json> --reviews-sha256 <sha> --candidate <new-candidate>
python -B deploy/activate_journey_routes_release.py stage <new-candidate> <reviewed-plan-sha>
python -B deploy/activate_journey_routes_release.py activate <new-candidate> <same-reviewed-plan-sha>
```

以上是命令形状示意，不是本次运行回执，也不能替代固定计划与原件核对。生产 controller 仅允许 Linux root、固定候选根目录、无环境 Docker/Compose selector；复用发布锁、独占 stage/activation、真实服务环境绑定、异常后停止新 writer、不自动恢复旧应用。数据容器保留原网络禁用、只读镜像、非 root uid、受控内存/tmpfs 和最小 mount；启动后校验的数据 volume 为只读。

## 合成验证范围

`tests/test_journey_routes_release.py` 用真实临时 Git/tar/文件和记录式命令验证包、计划、固定基线、身份拒绝与生命周期失败顺序；记录式 runner 不运行 Docker 或生产命令。`tests/test_journey_routes_migration.py` 在组合中从固定已上线 Git 源创建真实 Flask 两户三库，先填入五张已有分析表，再验证全组 66→69、实际 app 重启、旧行/schema/sequence/平台漂移拒绝、部分迁移回滚、非空路线/回执重启及完整恢复。

测试与独立审查原件保存在忽略的 `test-results`，不提交数据库、环境值或原始业务内容。Windows 测试不能替代后续同源 Linux 容器验证及独立生产只读审计。

本机工具首轮 30/30 通过；补充已审 `journey_places.py` 根文件范围后，相关范围、profile 和记录式 build/validate 共 14/14 通过（28 项未选择，不是跳过）。两轮含 42 个不同工具用例，按各轮范围保留，不与迁移用例相加。原件位于 `test-results/journey-routes-release-tools-r1`、`test-results/journey-routes-release-tools-r2`；本次无网络、Docker 或生产操作。

独立组合 `c71789d7251277326cbd69f6cfc6babe2f459a5f`（已审 API／接线 `bcfd77793036ed4d33711595d838896b2c7a685e` + 发布工具 `eff8bbc6f339e1c43082d4dd6fbb8cd2eb9014f2`）实际运行迁移专项 **20/20 通过，0 失败／错误／跳过，65.65 秒**。组合源码前后哈希一致且工作区干净；原件位于独立验证 worktree 的 `test-results/journey-routes-migration-r1/{started.json,execution.json,junit.xml,stdout.txt,stderr.txt}`。覆盖真实临时两户三库、五分析表非空、精确三表迁移、实际 app 启动、漂移拒绝、部分失败完整回滚、非空路线及软删除回执重启／恢复。此记录仍不代表 Linux 容器或生产验证。
