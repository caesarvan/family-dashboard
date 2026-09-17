# 旅行资料与预订凭证

**状态：已于 2026-09-15 20:23:00（北京时间）发布。** 模块管理成员主动上传的文件，默认本人私有；API／浏览器使用虚构输入验证，43 表完整组 Docker 恢复与 42→43 配置迁移分别有实际记录。生产迁移及容器内部读回已通过，不代表真实预订凭证、公网浏览器、实体设备或新云写已验收。完整范围见 [README](../README.md) 与 [VALIDATION](VALIDATION.md)。

实现为 [journey_documents.py](../journey_documents.py)，专项为 [test_journey_documents.py](../tests/test_journey_documents.py)。注册接缝为 `register_journey_documents(app, db, Problem, body, require_member, limited, audit)`；必须在旅行表和成员会话初始化后注册。公开常量 `SCHEMA_SQL` 是新增表、索引和触发器的唯一参考结构，没有默认资料或后台任务。

## 使用流程与范围

1. 先保存旅行，再从该旅行进入资料夹，选择 PDF 或图片，填写标题及可选航班／住宿／活动分段。默认“仅本人”；只有上传者可以明确设为“家庭成员共享”。
2. 上传成功后读取列表。图片保存为去除元数据的 JPEG；PDF只提供附件下载，不内嵌网页、不提取文字、不执行其中内容，也不通过 URL 抓取文件。文件存在不等于航司、酒店或预订平台核验成功。
3. 上传者可改标题、共享范围和关联位置，或明确删除文件。伙伴只能读取共享资料，不能修改、删除或把它关联到其他旅行。
4. 删除旅行不会删除凭证。上传者从“我的旅行资料”仍能取回未关联资料，重新选择本户旅行后关联；未关联资料只有上传者可见。

资料不进入旅行 `plan`、通用 `entities`、`/api/state`、ICS、助理上下文或云日历／待办描述。上传、下载或改关联不修改 bookingState、日期、负责人、完成状态、实付和公共余额，不触发提供者请求或云发布。

## 权限与读取一致性

全部接口仅限有效成员会话，匿名 401、电视 403。家庭由现有 WSGI 路由选择的独立数据库确定；客户端不能指定 owner 或另一个家庭。写请求使用现有同源 JSON、Origin 与 CSRF 检查。

每次操作在数据库事务内重新核对当前会话、成员 auth_version 及家庭；图片解码后、提交前再次核对，已经撤销的登录不能继续写入。文件列表、权限和内容在同一读取事务内检查。服务端无法撤回已经开始下载的字节；前端还须按原成员／家庭／CSRF／弹窗节点和请求代次丢弃迟到结果。最后身份读取到下载点击之间的跨标签非原子窗口仍适用 [个人导出边界](PORTABILITY.md)。

**本轮会话加固候选，尚未部署：** 进一步比较请求最初捕获的具体 session ID；读取资料、文件和上传重放时，释放 SQLite 读快照后再核对当前会话；写事务在业务和审计完成后、提交前再核对有效期及凭据。下载还会在新的事务检查当前文件可见范围与 revision，避免 BLOB 读取期间取消共享、删除或修改后的旧文件响应；文件不可见返回 404，版本变化返回 409。最终检查之后已经开始发送的字节无法撤回，不据此承诺取消所有在途响应。接口形状与表结构保持。

该候选已在真实临时 SQLite／Flask 中执行原资料 68 项及新增 [23 项会话边界检查](../tests/test_journey_document_sessions.py)，合计 **91 passed，134.87 秒**，无失败或跳过。新增检查使用独立数据库写入者、真实成员请求和受控过期时间，覆盖读取快照期间撤销、实际 session ID 不符、提交前过期回滚、等待写锁时撤销，以及伙伴下载期间取消共享／删除／修改资料。私有 `worktrees/expo-documents-sessions/test-results/document-sessions-r1.xml` SHA256：`9d595924148f9624483bb9107bff3a64a6af05ba9ec9d9575c05827e9460636b`。这是候选后端结果，尚不包含新版面板、真实下载设备或生产发布。

私有资料对伙伴既不列出，也不返回标题、大小、分段或文件；按编号直接读取或修改返回 404。有效旅行中的 shared 资料可由本户伙伴读取，管理操作返回 403。所有文件内容响应使用 `Content-Disposition: attachment`、`Cache-Control: no-store` 和 `X-Content-Type-Options: nosniff`，不返回公共缓存 URL 或免登录签名链接。

## 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/journey-documents` | 本人资料库，或指定旅行的可见资料 |
| POST | `/api/journey-documents` | 上传并关联到已存在的旅行 |
| PATCH | `/api/journey-documents/<document_id>` | 上传者完整替换可编辑元数据 |
| DELETE | `/api/journey-documents/<document_id>` | 上传者删除并保留防重放记录 |
| GET | `/api/journey-documents/<document_id>/file` | 经权限检查下载当前文件 |

### 列表

GET 仅接受可选 `journeyId`，不支持分页、documentId、搜索或重复查询参数。带 journeyId 时，该旅行必须存在，返回本人私有与本家庭共享资料；不带时仅返回本人全部未删除资料，包括未关联文件，绝不返回伙伴资料。

返回形状为 `{journey, segments, journeys, documents, limits}`：

- `journey` 为 `{id,title,revision}`；未指定旅行时为 null。
- `segments` 为所选旅行当前的 `{key,title,kind}` 数组；本人全库模式为空。
- `journeys` 为本户现存旅行的 `{id,title}` 数组，用于重新关联。旅行本身仍遵循既有家庭共享权限。
- `documents` 按更新时间倒序、ID 排序。单户 active 上限限定了列表长度。
- `limits` 为 `{"maxFileBytes":5000000,"formats":["pdf","jpg","jpeg","png","webp"]}`。

每个资料元数据具有 `id`、`journeyId`、`owner`、`title`、`filename`、`mimeType`、`bytes`、`visibility`、`createdAt`、`updatedAt`、`revision`、`segmentKey`、`segmentMissing`、`unlinked`、`canManage`、`downloadUrl`。owner 是本户成员 ID；时间是 UTC ISO8601 字符串；bytes 是实际保存文件的字节数。

### 上传

以下为虚构请求示例。dataBase64 编码的是一个仅用于格式边界测试的最小 PDF 外形，不代表可供阅读的实际预订文件。

```json
{
  "journeyId": "aaaaaaaaaaaaaaaaaaaaaaaa",
  "requestId": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "title": "合成酒店预订凭证",
  "visibility": "private",
  "segmentKey": "hotel",
  "file": {
    "name": "synthetic.pdf",
    "mimeType": "application/pdf",
    "dataBase64": "JVBERi0xLjcKJSVFT0YK"
  }
}
```

journeyId/requestId/title/file 必填，visibility 省略时为 private，segmentKey 省略时为空字符串。title 去除首尾空白后为 1–120 字符；segmentKey 为最多 80 字符。journeyId 为 24 位小写十六进制，requestId 为 32 位小写十六进制；非空分段必须属于当前旅行计划。

file 只接受 name/mimeType/dataBase64 三个必填字段。名称最多 180 字符，不能带路径分隔符或控制字符；扩展名和 MIME 声明须相符。标准 Base64 严格解码，拒绝 data URL、空内容和坏编码。外层和 file 的未知字段均拒绝，不默默采用 owner、下载 URL 或远端标识。

首次成功返回 `201 {document,replayed:false}`；同一请求重放返回 `200 {document,replayed:true}`。先完成格式处理，再在单一写事务中核对会话、旅行、分段、幂等与容量，保存 BLOB 和审计。事务失败不保留半份资料。

### 修改与删除

PATCH 五字段全部必填，不接受部分更新或未知字段：

```json
{
  "revision": 1,
  "title": "更清楚的资料标题",
  "visibility": "private",
  "segmentKey": "",
  "journeyId": null
}
```

journeyId=null 表示明确解除关联，此时 visibility 必须 private，segmentKey 必须为空。重新关联须选择本户现存旅行及有效分段，且目标旅行未达到文件数上限。同一旅行中原有分段已移除时，可保留原 segmentKey 改标题或共享范围，列表继续显示 segmentMissing；不能新建另一个不存在的分段引用。

revision 必须为大于等于 1 的 JSON 整数，拒绝布尔、浮点和字符串。成功返回 `200 {document}`，revision 递增一次；相同旧 revision 的两个并发修改只能成功一个。PATCH 不替换文件内容，换文件需明确新上传。

DELETE 只接受 `{"revision":1}`，成功返回 `200 {"deleted":true,"id":"资料ID"}`。删除清空 BLOB、名称、标题、MIME、分段及关联，保存上传者、请求幂等键、摘要、ID、时间和删除标记；列表、下载及业务导出不再包含它。重复 DELETE 返回 404，应读取当前列表确认结果，不自动上传替代文件。

### 错误

沿用 `{error:固定说明}`，不返回原文件内容、内部路径或提供者错误，没有额外错误 code。

| 状态 | 含义 |
|---|---|
| 400 | 字段／类型／格式／请求编号不合法 |
| 401 | 未登录，或处理期间会话已撤销／改变 |
| 403 | 电视、错误 Origin/CSRF，或可读共享资料的非上传者尝试管理 |
| 404 | 旅行／文件不存在，或资料对当前成员不可见 |
| 409 | 元数据版本过时、分段已不存在、配额不足、请求键与内容冲突，或已删除上传的旧请求重放 |
| 413 | 请求或文件超过大小限制 |
| 415 | 写请求不是 JSON |
| 429 | 上传限频或图片解码槽忙 |
| 503 | 无法核对当前会话 |

## 文件限制与容量

原文件最多 5,000,000 字节，根应用仅为此 POST 设置 7,200,000 字节 JSON 请求上限，仍须保持反向代理限制与之兼容。每户最多 500 个未删除文件、合计 200,000,000 个实际存储字节；每个已关联旅行最多 100 个文件，统计包含该旅行双方的私有／共享文件。额度错误不披露另一成员文件名或明细。未关联文件仍占本户总额度，上传者可在资料库明确删除。

PDF 扩展名 .pdf、MIME application/pdf，内容必须以支持的 `%PDF-1.x`（1.0–1.7）或 `%PDF-2.0` 标记开头，最后除空白外须为 `%%EOF`。这只是声明与外形检查，不解析对象结构、不去除 PDF 活动内容、不做病毒扫描、不保证文档完整可读。原字节原样保存和下载。

JPG/JPEG、PNG、WebP 由 Pillow 实际解码，实际格式必须与声明一致。只接受单帧、最多 400 万像素；遵循 EXIF 朝向后缩小至最长边 1600，重新绘制 RGB 图像并编码 JPEG，去除 EXIF/GPS、注释及原色彩配置，透明背景为白色。保存后的 JPEG 不超过 2,000,000 字节，文件名后缀变为 .jpg；这不是原始图片字节备份，细小二维码或文字须由用户下载后核对。

图片解码同进程只允许一个进行中任务，忙时 429；每来源 IP 在现有 attempts 限流中每 10 分钟最多 30 次上传请求，包括重试。数量、存储大小、目标旅行容量的检查与 INSERT/PATCH 在 BEGIN IMMEDIATE 中完成，不允许两个并发请求同时越过最后一个空位。

## 幂等与生命周期

上传键在本户 `(owner,request_id)` 内唯一。摘要绑定规范化后的初始 journeyId、标题、共享范围、分段、输入文件名／MIME 和原文件字节的 SHA-256；不绑定后来修改后的元数据。同键同载荷返回原文件当前元数据，不恢复旧标题、共享范围或关联；同键不同载荷返回 409。不同成员即使使用相同请求键也不会读到对方回执。删除文件后的原键保持 tombstone，旧请求不能重建文件。

journey_id 是可空外键，ON DELETE SET NULL。旅行级联删除工作流时，只移除文件关联：BLOB 和上传者仍保留；即使数据库原 visibility 是 shared，未关联文件的有效 visibility 始终 private，伙伴无法枚举或下载。此处的存储值保留与对外有效值不同，显式 PATCH 会写入新的可见范围。

专用触发器只在旅行删除导致 journey_id 置空且 revision 未被主动修改时递增文件版本及更新时间；普通 PATCH 已递增版本，不会递增两次。因此删除旅行后仍持旧 revision 的文件修改或删除返回 409。重放原上传请求可取回这个未关联文件，但不会把旅行或旧关联恢复出来。

segmentKey 不是 SQL 外键。调整／删除分段不修改附件、不删除 BLOB、不改变文件 revision；segmentMissing 根据最新 plan 派生，分段相同 key 恢复时可再次匹配。旅行重新预览、迁期、任务完成或云同步都不复制文件，也不为新旅行自动搬运凭证。

删除记录及其 tombstone 随数据库备份保存。恢复较早备份可能恢复后来删除的文件或撤回后的共享状态；成员会话失效不会删除这些业务内容。恢复范围、用户核对及重新开放服务仍按 [DEPLOYMENT](DEPLOYMENT.md) 与 [成员会话恢复](MEMBER-SESSIONS.md) 执行，不能声称 tombstone 能跨数据库时间回退阻止复活。

## 导出、备份与验收

`exported_documents(con,owner,include_shared=False)` 仅读取已有表，缺表时返回 `{"personal":[],"shared":[]}`，不初始化或写数据库，也不读取 BLOB。personal 为本人全部未删除资料元数据；shared 仅在明确 include_shared 时包含伙伴仍关联有效旅行且设为 shared 的资料。本人记录只在 personal 一次，未关联文件不出现在 shared。

导出白名单为 id/journeyId/owner/title/filename/mimeType/bytes/visibility/segmentKey/unlinked/createdAt/updatedAt/revision，不含 requestId、payload_digest、删除 tombstone、下载 URL、会话或文件字节。根导出接缝分别放在 personal.journeyDocuments 和 shared.journeyDocuments。此轮 ZIP 与原采购照片一样只提供元数据；单份内容需从资料夹明确下载，完整文件批量携带／迁移尚未实现。管理员完整 SQLite 备份包含 BLOB 和 tombstone，不能作为成员业务副本分发。

发布需要独立验证 42→43 新表及索引／触发器，原 42 表与平台注册目录保持；后续零 schema 更新、恢复示例和源码清单也须相配更新。当前专文不宣称迁移或生产恢复已完成。

专项覆盖真实临时 SQLite/Flask 会话与两家庭、PDF 原字节、图片净化、严格类型与限额、事务回滚、并发幂等／CAS／配额、旅程删除保留文件、分段缺失、旧请求不复活及只读元数据导出。浏览器迟到响应、整体导出和恢复组合由对应独立专项另行给出结果；真实凭证可读性、公网、实体设备和外部预订状态不属于合成验证结论。

本候选的上述后端专项已实际运行 **68 passed，38.24 秒**，使用 `tests/test_journey_documents.py` 和严格拒网的临时库；JUnit 保存于私有 `test-results/journey-documents-api.xml`。这是模块专项结果，不是完整应用、浏览器或生产发布验收。其他 agent 的导出／恢复组合须使用各自报告及对应依赖散列，不合并计作这 68 项。

## 一次性 42→43 迁移检查器

[deploy/check_journey_documents_migration.py](../deploy/check_journey_documents_migration.py) 提供可随源码交付的检查器，不依赖 Git、开发者目录或旧候选定位文件。它只接受旧 42 张户内表，迁移后须恰好 43 张；不是后续 43→43 更新或通用恢复工具，不能修改表数来绕过校验。

保留检查覆盖平台注册库的两表、全部注册家庭及其对应数据库、每张旧表的列／外键／行摘要、全部旧 schema 对象与 SQLite 内部序号。新 `journey_documents` 必须为空，表、两个显式索引、自动索引和触发器须与当前 [SCHEMA_SQL](../journey_documents.py) 完全一致。BLOB 按原字节 SHA-256 纳入行摘要；输出不含业务行、文件内容、账号名或金额。这里验证逻辑内容和结构保留，不要求迁移后 SQLite 文件物理字节不变。

### 输入、命令与输出

在冻结的新源码根目录可调用 `schema_definition()`，得到 `{"sql":"原始 SCHEMA_SQL 字符串","sha256":"其 UTF-8 SHA-256"}`。部署控制器将此写为 `schema.json`，并记录该 JSON 文件本身的 SHA-256；检查器还会从自身源码根目录的 `journey_documents.py` 读取常量并逐字比较，不能靠自带的 SQL／散列认可另一份结构。

`DATA_DIR`（或 `--data-dir`）指向明确选定的数据库卷。默认只读输入目录 `/release-check` 可用 `--inputs-dir` 指定，含：

| 文件 | 内容与产生方式 |
|---|---|
| `schema.json` | 上述精确的 `sql`／`sha256` 对象，四个动作均要求 |
| `before.json` | 停止全部写入后，`snapshot` 返回的完整 JSON；后续三个动作要求 |
| `backup.json` | 原 `deploy/backup.py` 的 `backup_all()` 返回值 `{manifest,databases}`；`validate-backup` 与 `warm` 要求 |

备份 manifest 及它列出的 SQLite 快照位于同一数据卷的原 `backups/`／子家庭备份目录。检查器拒绝越界路径、符号链接、缺失或零字节输入；备份必须包含唯一且完整的平台注册库／家庭映射，每份文件大小、SHA-256 与停写快照的逻辑内容均匹配。它不自行创建或替换备份。

以下命令在部署控制器准备的隔离容器中执行，源码挂在 `/release-source`，输入目录只读；仅 `warm` 需要数据库卷可写。所有命令只把结果写到 stdout，由外层保存并绑定散列，不能把重定向目标放在只读输入挂载内。

```sh
python /release-source/deploy/check_journey_documents_migration.py snapshot --data-dir /data --inputs-dir /release-check
python /release-source/deploy/check_journey_documents_migration.py validate-backup --data-dir /data --inputs-dir /release-check
python /release-source/deploy/check_journey_documents_migration.py warm --data-dir /data --inputs-dir /release-check
python /release-source/deploy/check_journey_documents_migration.py check --data-dir /data --inputs-dir /release-check
```

这四行不是可以直接对运行中数据库连续执行的部署脚本。外层先停写并固定 `schema.json`；保存 snapshot 为 `before.json` 后创建完整备份，再保存 `backup.json`，才能验证和迁移。只挂检查器单文件不够：`/release-source` 必须是已冻结的完整新源码，其运行模块须与已验证的新镜像一致。

- `snapshot`：只读旧 42 表，返回 `{registry,households}`，用于生成 `before.json`。
- `validate-backup`：先确认当下数据库仍等于 `before.json`，再核对备份全组；返回 `{databases,manifestSha256,groupVerified:true}`。
- `warm`：重复旧状态和备份全组检查后，调用真实 `create_app()`，串行初始化所有注册家庭，再比较完整前后快照。不会启动 worker 或调用云 tick；返回下述保留结果，另加 `cloudTicks:0` 与 `backup` 核验结果。失败可能已留下部分家庭的新表，不能因此重开写入或盲目重试。
- `check`：只读已迁移状态，返回 `{households,originalTablesPreserved:42,newTables:1,newTableEmpty:true,schemaIndexesAndTriggersVerified:true,allOriginalRowsAndSequencesPreserved:true}`。

可直接调用的函数为 `schema_definition()`、`snapshot(root,allow_new=False)`、`preserved(before,after,sql)`、`validated_backup(root,before,backup)` 与 `run(action,root,inputs)`；后三项中的 `before` 必须来自已冻结旧状态。只有 `run('warm',...)` 会初始化数据库。命令失败返回非零退出码，不生成通过结果；禁止使用 `python -O` 或 `PYTHONOPTIMIZE`，检查器会拒绝禁用断言的运行方式。

### 外层控制器与测试边界

外层发布流程仍负责：冻结旧 42 表版本和新版本、源码清单／镜像／检查器／DDL／三个输入文件及备份 manifest 的原字节散列；停止所有 app／worker／web 写入；保留 `.env`、主密钥、家庭派生密钥和原家庭映射；按完整备份组处理失败恢复，恢复后先使对应家庭旧会话失效，再按部署流程恢复服务。本工具不执行 Docker、SSH、停服、配置替换或恢复，也不能单凭自身检查证明这些外部步骤已完成。

[tests/test_journey_documents_migration.py](../tests/test_journey_documents_migration.py) 在独立 Python 进程中使用当前应用 factory，仅关闭新增 `register_journey_documents` 来构造精确旧 42 表；再由另一个进程运行真实当前 factory 迁至 43 表。两家庭、任务、会话与备份均为虚构输入，子进程硬拒 socket 网络。该测试不读取 Git、真实配置或历史候选路径，可从解压源码 TAR 运行：

```sh
python -m pytest -q tests/test_journey_documents_migration.py
```

原 13 个迁移／失配场景继续覆盖旧数据、旧索引、序号、家庭集合、新表预填／列／索引／触发器、重复迁移和备份缺失／校验和；另检查当前 DDL 绑定及 warm 在备份失败前不初始化。此夹具是隔离旧结构模拟，不能代替冻结的真实旧版本→新版本、实际停写和容器部署验收，更不证明生产恢复已经完成。
