# 地点模块的合成恢复演练

此候选扩展已有 `deploy/rehearse_restore.py` 和 `tests/restore_rehearsal_fixture.py`，不执行生产恢复，也不替代发布控制器的 43→44 迁移审查。首轮验证是本地真实 Flask HTTP／SQLite 配合合成数据；真实 Linux Docker 演练由集成人在独立审查通过后执行。

## 显式结构 profile

| 参数 | 精确家庭表集合 | 地点数据 | `schemaSha256` |
| --- | --- | --- | --- |
| `--profile legacy43`（默认） | 控制器内冻结的 43 个既有表名 | 不访问地点 API | `null`，不声称存在地点 DDL |
| `--profile journey_places44` | 同一 43 个表名加 `journey_places` | 本文的 24 条记录 | `journey_places.SCHEMA_SQL` 字符串的 UTF-8 SHA-256 |

表名集合必须相等，不能用“至少 43／44 张”或只比较数量替代；除可选的 `sqlite_sequence`，不忽略其他 SQLite 内部表或额外表。44 profile 还逐字比较地点表、自动索引、显式索引和 trigger 的 `sqlite_master` 定义：控制器通过 AST 读取唯一字面量 `SCHEMA_SQL`，只在内存 SQLite 建立参考 DDL，不导入应用、不执行源码，也不修改受检库。

`tableSetSha256` 是排序表名用 LF 连接后（无末尾 LF）的 UTF-8 SHA-256。`schemaFingerprints` 是逐家庭完整 `sqlite_master` 的规范 JSON SHA-256，包含所有表／索引／trigger，不含业务行。恢复前的私有 proof 另保存每库完整规范化内容摘要；它们不能与地点模块 DDL 的 `schemaSha256` 混用。`expected.json` 版本为 2，绑定 run UUID、profile、schema 指纹和原合成配置摘要；seed、verify 不能选择不同 profile。

旧默认调用 `Rehearsal(root, image, output)` 保持有效，新增第四个参数 `profile='legacy43'`。原 `volume`、`start_app`、`fixture`、`ephemeral`、`cleanup` 方法契约保留。当前 44 表镜像使用默认 legacy43 会主动拒绝，不自动降级或删表。

## 44 表数据与断言

通过真实 API 创建两家庭、四成员，保留既有照片、私有财务、8 份旅行资料、电视、两份加密的假云凭据和待恢复失效的 OAuth state。每成员新增六种地点，共 24 行（20 个活动地点，4 个 tombstone）：

| 地点 | 分享／坐标 | 状态及关联 |
| --- | --- | --- |
| 私密地点 | private／主人精确坐标 | visited，关联保留的旅行 |
| 粗化共享 | shared／0.1 度网格 | planned，负经纬度，用固定独立预期检查投影 |
| 精确共享 | shared／精确坐标 | wish |
| 隐藏坐标 | shared／其他成员坐标为空 | visited |
| 旅行解除关联 | shared／粗化 | visited，真实删除临时旅行后 `journeyId=null`、revision 1→2，确认人和确认时间保留 |
| 删除回执 | 创建后真实 DELETE | revision 1→2，地点名称和位置元数据清空，保留 requestId／payload digest 的 tombstone |

访问控制验证包括主人坐标和共享预览、另一成员的投影及 `canManage=false`、私密 404、共享他人修改／删除 403、跨家庭读取和写入 404，以及电视全部五个地点 API 403。旧四份成员 cookie 对地点列表为 401；重新登录后才读业务数据。地点不进入通用 `/api/state`。

恢复后用原 create payload 重放，返回当前地点且 `replayed=true`，包含原旅行已删除的地点；同 requestId 改 payload 为 409；墓碑 create 重放为 410，原 revision DELETE 重放为 200；解除关联后旧 revision PATCH 为 409。这些验证不自动重写地点。所有业务表（包括 `audit`、`sqlite_sequence` 和回执）在权限／重放探测之后仍须逐值等于备份前快照。

## 原恢复链与隔离

控制器仍检查调用者明确给出的本地不可变镜像 ID，并核对 `/app` 内所有根 Python、requirements 和静态资源字节与候选源码。使用原 `deploy/backup.py` 生成平台注册库及两个家庭库的完整三库备份；从 `docs/DEPLOYMENT.md` 提取唯一原恢复程序，从 `docs/MEMBER-SESSIONS.md` 提取唯一会话失效 SQL，报告两者 SHA-256。坏哈希、缺少子户快照、错误映射必须在创建目标库之前拒绝；有效备份才进入恢复和逐户会话失效。

恢复后先完成整库 schema、列、外键、索引、SQLite 内部元数据和每行／BLOB 的比较，才发送第一次 HTTP。仅允许文档 SQL 对成员认证版本、浏览器代次、session 撤销时间和 OAuth states 的明确改变。资料下载字节、照片哈希、假 token 密文字节和相同家庭密钥下的解密摘要均验证。这里的“数据字节保留”指行值、BLOB 与下载内容一致，不声称 SQLite 文件页面布局或文件 SHA-256 在恢复后保持相同。

容器始终 `--network none`、无发布端口、只读根文件系统；仅新建并记录带本次 UUID label 的数据／proof 卷，清理逐次验证名称与 label。控制器不读取生产 Compose、`.env` 或既有卷。合成环境显式 `ASSISTANT_PROVIDER=local`，NVIDIA 与兼容 OpenAI 的 key／model 都为空。HTTP 夹具只允许 loopback，OAuth 控制请求使用 `error=access_denied`，不进行提供商 token 交换。`expected.json` 含合成 cookie／密文／记录，0600 写入私有 proof 卷，不应作为公开报告附件。

调用控制器的 Python 必须启用 `-B` 且 `sys.pycache_prefix` 为空，否则 CLI 拒绝。`-B` 只禁止写入缓存，不能阻止读取旧缓存，因此在源码哈希检查及每次 fixture 执行之前，还递归检查完整候选目录（包括未跟踪／忽略项）：拒绝符号链接、Windows junction／reparse point，以及 `.pyc`／`.pyo`。不自动删除这些输入；应使用干净的已核验源码目录。合成容器环境显式 `PYTHONDONTWRITEBYTECODE=1`、`PYTHONPYCACHEPREFIX=`，fixture 也用 `python -B`。该 fixture 前置检查只绑定候选源码，不比较调用方父镜像的运行代码，保留独立迁移 runner 先用父镜像 seed 的契约；完整恢复 `run()` 仍单独核对其指定镜像的运行代码。

独立审查后的 Linux Docker 命令（需使用实际已核验的候选镜像与不存在的证据目录）：

```sh
python -B deploy/rehearse_restore.py --image 'sha256:<verified-immutable-image-id>' \
  --profile journey_places44 --source-root '<verified-candidate-root>' \
  --output '<new-private-evidence-directory>'
```

报告保留原 `passed`、检查列表、镜像、容器隔离和 cleanup；增加顶层 `profile`、`schemaSha256`、`householdTables`。seed／verify 分别报告同一 profile、schema 指纹、检查和 HTTP 次数，计数包含 `householdTablesEach`、`journeyPlaces`、`placeTombstones`、`oldCookiesRejected`。不能把某个阶段通过或清理失败称为完整成功。

本控制器的 `sourceHashes` 覆盖运行时与演练直接输入，**不是发布清单全部文件**。发布控制器要求的完整候选 manifest、`manifestSha256`、原件 `records`、`realDocker`、`placesRestored`、`oldSessionsRevoked` 等 envelope 由集成人绑定真实原件后透明归一化；不能补造未运行证据，也不能把本地测试结果标成 `realDocker:true`。

## 本地验证边界

`tests/test_journey_places_restore.py` 校验明确 profile、错误表集合、缺失／漂移 DDL、参数传递和失败报告，并在临时目录启动当前真实应用工厂，通过真实 HTTP 执行 seed、原备份、文档恢复、文档失效 SQL 和 verify。测试仅把恢复／复制程序 AST 中固定容器根路径替换为测试临时目录；没有 Docker daemon、生产输入或远端请求，输出明确 `realDocker:false`。

缓存边界回归使用真实编译缓存和临时目录链接（Windows 实际 junction），检查未列缓存与链接在任何 Docker 操作前被拒绝；另测未启用 `-B`／外部 cache prefix 的 CLI 拒绝。运行此组回归也使用 `python -B -m pytest`，生成物不进入发布源码树。

既有 `tests/test_journey_documents_integration.py` 的恢复用例明确选择 legacy43，并仅在该测试作用域禁用新地点注册，以重建合成历史 43 表结构；原、子户和恢复工厂均受同一限制。这验证旧夹具回归，不能替代历史真实镜像验证。当前未改工厂的 44 表恢复由新测试负责。其余资源归属／不确定创建清理测试及旧会话恢复测试继续运行。
