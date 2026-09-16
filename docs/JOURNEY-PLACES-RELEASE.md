# 地点 43→44 迁移与源码发布候选

本工具基于已审地点 API `05f885b6cf50c48c03a5165c5e1356990e1447b1` 开发，明确依赖该非 main 提交。它新增独立检查器、构建器与控制器，未修改历史 42→43 或 SOURCE 43→43 门禁。本文不是生产执行授权，也不表示已完成真实 Docker 构建、迁移、恢复或上线。

业务接入另由集成人负责：app 注册、Dockerfile COPY、资料导出、静态入口和路由清单。此分支未修改这些业务文件。源码打包需要已审编排包四文件同时存在；缺少任一固定文件会失败并保留上一个 archive。工具专项使用合成源码/临时数据库/命令替身，不替代最终组合版本的真实验证。

## 固定边界

| 对象 | 允许与核验 |
|---|---|
| 数据库 | 每户原 43 表 → 44 表，只新增 `journey_places`；平台两表不变 |
| schema | AST 读取候选 `journey_places.SCHEMA_SQL` 并绑定 SHA；精确核验表、3 个显式索引、SQLite 自动索引、unlink revision trigger、列与外键 |
| 数据 | 原 43 表所有行、资料 BLOB 散列、schema 对象、内部序列保持；新地点表为空 |
| Python | 可更新批准的既有根模块，只允许新增根模块 `journey_places.py` |
| 运行配置 | `requirements.txt`、`compose.yaml`、`deploy/backup.py`、原 `.env` 与解析配置保持；不安装依赖 |
| 源码交付 | 原完整 manifest 加批准改动；新增根 `DESIGN.md` 与四个固定编排 Python 文件 |
| 镜像 | 验证不可变父镜像全部 Python/static/requirements；一层纯 COPY 覆盖完整候选 Python/static；配置和父层保持 |
| 开发工具 | `tools/inference_orchestrator/{__init__,__main__,client,runner}.py` 仅交付源码；不收整个 tools 目录；镜像拒绝 `/app/tools` 和 `/app/DESIGN.md` |

固定哈希绑定复用 `release_core.py`、历史资料 controller/checker、静态 builder 的纯函数和容器检查片段。新控制器不调用历史 activate，不修改其全局常量。所有调用者继续共用 `.static-release.lock`，避免与已有发布控制器并行。

为交付另行审查的 44 表恢复 profile，源码策略额外允许更新 **已存在于 BASE** 的准确路径 `deploy/rehearse_restore.py`。该程序仍不进入应用 runtime，也不由本发布控制器执行。新建同名路径或任意其他 deploy Python 文件不因此获准；其 fixture、测试和 Markdown 仍须在批准的完整候选 manifest 中。

NVIDIA 适配位于既有根 Python 模块，因此可随批准的源码更新交付。迁移没有推理请求、地理编码、外站调用或模型工具执行。此控制器保持现有运行配置：如果生产原本没有 NVIDIA 配置，源码发布成功也不代表 NVIDIA 已配置或验证。凭据注入和真实模型验收另行实施，秘密不放进 READY、通用日志、源码包或浏览器。

## 检查器

`deploy/check_journey_places_migration.py ACTION --data-dir DATA --inputs-dir INPUTS` 支持：

| action | 行为 |
|---|---|
| `snapshot` | 只读实际登记的全部家庭及 registry；拒绝缺失库、越界路径、不完整/混合表集合、损坏与外键错误 |
| `validate-backup` | 重新核对停写前状态；验证备份组映射、大小、主文件 SHA 与完整 SQLite 内容 |
| `warm` | 再查停写前状态及冻结备份 proof，只运行地点 DDL，逐户事务提交；不启动 app/worker；迁移后再核验备份 |
| `check` | 对照 before 验证 43 表保持、新空表及所有 DDL 对象，并重新验证原备份组 |

输入为 `schema.json`（`sql` 和 `sha256`）、`before.json`、`backup.json`（既有 backup.py 输出）、`backup-verification.json`。`snapshot` 只需 schema；其余按表格所述依赖输入。控制器逐阶段冻结这些文件的原始字节散列，检查器本身不制造批准或基线。

备份必须是独立主文件：拒绝硬链接和 `-wal`/`-shm`/`-journal` 侧文件，以 immutable 读取验证主文件独立可恢复。真实 live 数据库的只读快照仍正常包含 WAL 中已提交内容。变更后的备份内容即使重新计算 checksum，也不能匹配冻结 before。

每户单个 DDL 事务失败会回滚该户新增对象。多户之间没有跨库事务；第一户成功、第二户失败时保留 44/43 现场，再次 `warm` 和混合库 `check` 均拒绝。全 44 库也不能当作一次新的 43→44 迁移重复运行。失败后不得让旧镜像盲接未知 schema，不自动删除新表或覆盖数据库。

成功 proof 包含 `households`、`originalTablesPreserved:43`、`newTables:1`、`newTableEmpty:true`、`schemaIndexesAndTriggersVerified:true`、`allOriginalRowsAndSequencesPreserved:true` 与完整 `backup` proof。warm 另含 `cloudTicks:0`、`modelRequests:0`；这些只描述检查器没有调用外部服务，不代表生产服务配置状态。

## 构建与 READY

构建入口参数顺序：

```text
python deploy/build_journey_places_release.py CANDIDATE PARENT_IMAGE MANIFEST_SHA BASE_MANIFEST_SHA NEW_OUTPUT
```

CANDIDATE 必须提供 `RELEASE-MANIFEST.json` 与 `BASE-MANIFEST.json`；父镜像是 `sha256:<64hex>`，NEW_OUTPUT 必须不存在。一次冻结宿主环境并拒绝 `DOCKER_*`/`COMPOSE_*` 选择器。真实镜像探针使用禁网络、只读、非 root、去 capabilities 的临时容器。构建 context 只有固定 FROM 和 `COPY --chown=10001:10001 app/ /app/`，无 RUN、pip 或凭据。主文件/上下文字节、完整父子 runtime 集合、父层加一层、镜像 Config 和字节码边界必须全部相符；失败留 `build.json`，不泄漏 Docker 原始错误输出。

READY 不是由单元测试或此工具自动批准。集成人在最终同树候选上准备 READY，另一作者复核原始证据并批准其 SHA。顶层字段契约：

| 字段 | 值 |
|---|---|
| `version` / `verified` / `mode` | `1` / `true` / `journey-places-migration` |
| `image` / `previousImage` | 新镜像与实际运行旧镜像的不可变 ID，必须不同 |
| `manifestSha256` / `sourceHashes` | 完整候选 manifest 的原始 SHA / 完整文件散列映射 |
| `baseManifestSha256` / `baseHashes` | 此次实际安装源码的独立 BASE 原始 SHA / 完整映射，不用开发 base 代替 |
| `oldManifestSha256` | 当前安装目录原 RELEASE-MANIFEST 的原始 SHA，可与独立 BASE 不同 |
| `changedFiles` / `approvedRuntimeChanges` | 全部准确差异路径 / Python 与静态差异（含 before/after SHA） |
| `environmentSha256` | 原 `.env` 字节 SHA；仅存私有发布输入，不能放真实环境值 |
| `schema` | `{"from":43,"to":44,"newTables":["journey_places"]}` |
| `schemaSha256` / `helperSha256` | 地点 SCHEMA_SQL SHA / 新 checker 文件 SHA |
| `gitReview` | 已审 base/main/integration commit 与相同 mainTree/integrationTree，绑定 approvedRuntimeChanges |
| `evidence` | 下列 7 类 `{path,sha256}` 引用，路径都在 candidate/evidence/ 内 |

每类 evidence JSON 须含 `verified:true`、完整 `sourceHashes`、非空 `records:[{path,sha256}]` 原始报告引用。控制器保存并验证所有引用的原始字节；不能证明报告来源或替代非作者阅读。

| evidence | 必须提供的内容 |
|---|---|
| `placesBuild` | 实际 build.json 数据、镜像/父镜像、两个 manifest SHA、父/子 runtimeHashes、runtimeChanges；父层/配置/完整字节/字节码校验通过，pipExecuted=false |
| `windows`、`linux` | `exitCode:0`、准确 `tests/passed/skipped/failed/errors`、相同 scripts 列表与收集数、`junit` 和 `log` 原件引用；Linux 绑定新 image。解析真实 JUnit 重新计算，不只信计数 |
| `browsers` | 非空 groups，实际源码脚本、passed、正 checks、externalRequests=0；覆盖最终地图接线与隐私/身份边界 |
| `migrationSafety` | realDocker=true、新 image、manifest/schema SHA、至少两户、正 checks、productionWrites=0、allPassed=true、43 原表保持、新增空表 1 |
| `dockerRestore` | 同样实际 Docker/镜像/schema 绑定、至少两户；householdTables=44、placesRestored=true、oldSessionsRevoked=true |
| `gitReview` | reviewed=true，40hex commits/trees，相同 main/integration tree，approvedRuntimeChanges；与顶层完全一致 |

当前工具检查 scripts 对应 JUnit case 存在，并绑定整份源码 manifest；受影响范围是否充分仍由独立审查者判断。不得把单脚本通过或旧依赖未变当作整个新版本通过。Windows/Linux 计数不相加为独立场景。

## 控制器阶段与失败

```text
python deploy/activate_journey_places_release.py CANDIDATE IMAGE MANIFEST_SHA READY_SHA
```

生产默认目录仍为 `/opt/family-dashboard`，候选为同级 `family-dashboard-candidate-journey-places-*`，发布记录在同级 releases。Python API 的 root/project/volume 参数供隔离演练；CLI 不接受任意 policy。不要从本文复制占位参数直接操作生产。

阶段依次为：锁与证据预检 → 镜像/环境验证 → stop web → clean stop sync/app → 全部库 snapshot → backup → validate-backup → 显式 warm → check → 安装准确差异源码及 manifest → 启动 app → check → 同机 HTTP 静态摘要/匿名地点 401 等读回 → check → 开放 sync/web → 状态读回。每个 Compose 命令显式固定 project、文件、原 env 文件；每次 up 前重查完整解析配置。所有原服务须退出 0、无 OOM，停写后不得有其他卷使用者。

控制器维护私有 source-before archive、原 env、READY/BASE、证据原件、解析环境/Compose 和 deployment.json。helper 只接受散列冻结输入，禁网络，不启动 worker。SIGINT/SIGTERM 转入失败处理；中断/超时后停止服务及此轮准确命名、镜像和 label 均匹配的 helper，绝不停止不明容器或自动恢复数据。失败报告包含阶段与异常类型，不写远端 body/headers/命令输出。

恢复必须另行决定相配源码/镜像、主密钥、registry 和完整家庭备份映射，执行已审恢复程序并撤销旧成员登录；已产生新业务写入时不能盲覆旧快照。44 库恢复演练须覆盖私密/共享坐标投影、visited 确认、unlink revision、删除 tombstone/幂等回执、TV 拒绝和跨户不可读。原 `restore_rehearsal_fixture.py` 硬编码 43；本任务未扩展它，集成人必须用独立审查的 44 fixture 完成真实演练，不能改计数字段冒充通过。

## 已执行与未执行

本分支实际完成临时 SQLite 双户 43→44 迁移及备份/失败测试。首个 checker 提交 `8d59071` 有 33 项通过；中间 WAL fixture 首次构造未将旧值 checkpoint 到主文件，导致一项预期条件失败，修正 fixture 后通过，失败 XML 保留。构建器/控制器的初轮失败来自“restore”字符串误匹配 pytest 临时目录名，随后将断言改为确切命令 token；原 XML 同样保留。

最终专项计数、源码散列和原件由交付时 `test-results/journey-places-release/` 私有索引记录。没有在本任务运行真实 Docker、SSH、生产迁移或配置 NVIDIA 凭据。模拟 READY 的 realDocker 字段只用于门禁测试，不是可用于发布的证据。
