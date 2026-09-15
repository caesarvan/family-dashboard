# 旅行资料：42→43 发布控制器

本文说明 [发布控制器](../deploy/activate_journey_documents_release.py) 的准备条件和一次性迁移流程，不代表候选已获部署许可或已经上线。当前发布事实见 [VALIDATION](VALIDATION.md)，资料权限与生命周期见 [JOURNEY-DOCUMENTS](JOURNEY-DOCUMENTS.md)，通用安装与运维见 [DEPLOYMENT](DEPLOYMENT.md)。

## 1. 固定基线与适用范围

控制器仅接受旧镜像 `sha256:f1e4cc56979f793f32585f498fa2fca55987356bd68f67e8cc6c14f0b1b6a01d`，将每户 42 张业务表迁移为 43 张；平台仍为 2 张表。只新增空 `journey_documents` 表及其实际索引、触发器，旧表、每行每列、schema、SQLite 内部序号和家庭注册信息必须完全保持。

服务器原源码须逐文件匹配外部 **222 文件** `BASE-MANIFEST.json`，SHA-256 为 `045ad0ac30e9130fc62c9fa0e12b7f0d2240e21feb5c352226002f4e1062a828`。服务器原 `RELEASE-MANIFEST.json` 仍可能记录旧 **218 文件**，其固定 SHA-256 为 `4713e0a4486c3afa4fc7f73932b038dcda3df1697a408aaaa331735f099736f7`。两份清单承担不同职责；不能先用 222 文件清单覆盖旧清单以制造一致。

原清单会原字节另存，并与 222 文件旧源码一起进入 `source-before.tar.gz`。`.env` 单独保存，不进入源码 TAR。候选不得移除旧源码；`compose.yaml`、`requirements.txt`、`deploy/backup.py` 必须保持原字节。Dockerfile 等其他差异须列入已审查的 `changedFiles`。已迁移库不能再次套用此一次性流程。

## 2. 准备目录、权限与命令

固定应用根为 `/opt/family-dashboard`。候选必须是它的同级绝对目录，名称以 `family-dashboard-candidate-journey-documents-` 开头，不接受符号链接。控制器从**候选的实际文件路径**执行；不能通过 stdin 粘贴调用，也不能先把新增工具复制进应用根目录。

候选目录包含完整源码，以及以下发布输入；这些输入不列入源码清单的 `files`，清单本身也不自引用：

| 文件 | 内容与约束 |
|---|---|
| `RELEASE-MANIFEST.json` | `files` 为完整源码相对路径→SHA-256 字典；与已测镜像和最终审查树一致 |
| `BASE-MANIFEST.json` | 上述外部 222 文件清单的原始字节 |
| `READY.json` | 经集成人核对的就绪声明；其最终文件 SHA 从调用方独立传入 |
| `evidence/*.json` | 五类规范化证据 envelope；引用完整最终源码散列 |
| `evidence/` 下原始记录 | 实际报告、日志等安全文件；每个引用均固定路径与原始字节 SHA |

新镜像必须使用完整 `sha256:…` 标识。候选源码根和源码子目录须允许 UID/GID `10001:10001` 遍历、源码文件须可读；只对公开源码设置合适权限，例如目录 0755、文件 0644。**不得递归放宽整个发布目录**：READY、BASE、证据和 `.env` 保持维护者私有权限。候选不携带真实数据库、账单或凭据。

实际 CLI 按顺序接收四个参数：候选绝对路径、新镜像完整 ID、候选 `RELEASE-MANIFEST.json` 原始字节 SHA、`READY.json` 原始字节 SHA。以下全是注释，占位符不能执行：

```sh
# 由已获本次部署授权的维护者填写并再次核对四个实际参数。
# python /opt/family-dashboard-candidate-journey-documents-<本次标识>/deploy/activate_journey_documents_release.py \
#   /opt/family-dashboard-candidate-journey-documents-<本次标识> \
#   sha256:<已验证新镜像64位散列> <源码清单64位散列> <READY64位散列>
```

维护者须能访问 Docker、停止服务、写应用源码及受限发布目录，并能把校验输入设为 UID/GID 10001。控制器在 `/opt/family-dashboard-releases/journey-documents-<UTC标识>/` 创建独立目录，自动保存 `verification/` 输入；不能手工预填或覆盖它们。

## 3. READY 合同

下例是有效 JSON 的**结构占位**，不是可用就绪报告；`verified:false` 和占位内容会被控制器拒绝。只在实际证据成立后生成真值，不应手工把 false 改成 true。

```json
{
  "version": 1,
  "verified": false,
  "image": "<新镜像完整sha256:ID>",
  "previousImage": "sha256:f1e4cc56979f793f32585f498fa2fca55987356bd68f67e8cc6c14f0b1b6a01d",
  "manifestSha256": "<候选RELEASE-MANIFEST原始字节SHA>",
  "sourceHashes": {"<全部候选源码相对路径>": "<SHA>"},
  "baseManifestSha256": "045ad0ac30e9130fc62c9fa0e12b7f0d2240e21feb5c352226002f4e1062a828",
  "baseHashes": {"<全部222个原源码相对路径>": "<SHA>"},
  "oldManifestSha256": "4713e0a4486c3afa4fc7f73932b038dcda3df1697a408aaaa331735f099736f7",
  "changedFiles": ["<新旧源码清单的精确差异路径>"],
  "environmentSha256": "<原.env字节SHA，不放原文>",
  "migration": {"from": 42, "to": 43, "newTables": ["journey_documents"]},
  "schemaSha256": "<SCHEMA_SQL原字符串UTF-8字节SHA>",
  "helperSha256": "<deploy/check_journey_documents_migration.py的SHA>",
  "evidence": {
    "windows": {"path": "evidence/windows.json", "sha256": "<SHA>"},
    "linux": {"path": "evidence/linux.json", "sha256": "<SHA>"},
    "browsers": {"path": "evidence/browsers.json", "sha256": "<SHA>"},
    "dockerRestore": {"path": "evidence/docker-restore.json", "sha256": "<SHA>"},
    "gitReview": {"path": "evidence/git-review.json", "sha256": "<SHA>"}
  },
  "gitReview": {"说明": "替换为git-review.json的完整对象，包括公共字段"}
}
```

`version` 必须为整数 1；真实 READY 的 `verified` 必须为 true。源码清单、完整 source/base map、前后镜像、精确改动列表和 schema/helper SHA 均须匹配。入口还将自身文件 SHA 与候选清单比较，避免运行另一个版本的控制器。

## 4. 五种证据 envelope

`evidence` 必须恰有上面五个键。每个引用对象恰含 `path`、`sha256`；路径在候选 `evidence/` 下，不允许越界、符号链接或私密数据路径。SHA 均为小写 64 位十六进制；Git 提交与树对象为小写 40 位十六进制。

每个 envelope 共同包含 `verified:true`、与候选完全相等的 `sourceHashes`，以及非空 `records` 数组。`records` 每项也恰含 `path`、`sha256`，指向实际原始文件，不能引用 envelope 自身。以下同样仅是结构占位：

```json
{
  "verified": false,
  "sourceHashes": {"<全部最终源码相对路径>": "<SHA>"},
  "records": [{"path": "evidence/<原始报告或日志>", "sha256": "<原始字节SHA>"}]
}
```

在公共字段外，五类分别要求：

| 类型 | 必需字段与准确语义 |
|---|---|
| `windows` | `exitCode:0`；`tests`、`passed` 为正整数，`skipped` 为非负整数，`failed:0`、`errors:0`；`passed+skipped=tests` |
| `linux` | 同 Windows；两平台 `tests` 相等；另有相同新 `image`、`manifestSha256`，必须来自该实际镜像的测试 |
| `browsers` | 非空 `groups`；每项为 `{script,checks,passed,externalRequests}`：script 指清单内 `tests/*.py`，checks 为实际正整数，passed=true，externalRequests 为整数 0 |
| `dockerRestore` | `realDocker:true`、相同新 `image`、`manifestSha256`、`schemaSha256`、整数 `restoredHouseholds>=2`；必须是此候选实际 Docker 合成恢复证据 |
| `gitReview` | `reviewed:true`、`baseCommit`、`mainCommit`、`integrationCommit`、`mainTree`、`integrationTree`；两 tree 完全相同；整个 envelope 必须与 READY 内嵌 `gitReview` 相等 |

公共字段仍须保留在每一类里。布尔值不能代替测试数字。控制器不运行 Git、pytest 或浏览器，也不从这些自声明字段自动证明测试来源；集成人先核对原始证据，再把最终 READY 文件 SHA 作为外部批准绑定。

原始记录可以涵盖多次分段测试，但须列清实际用例集合、各段源码依赖、失败修订和重跑结果，并去重核对最终收集范围。未改依赖的历史结果只能在逐字一致且适用性可证明时引用；受影响项须重新实测。不能把旧完整套件换一个 `sourceHashes`、照抄总数，就宣称当前源码完整通过。测试尚未覆盖的当前改动必须留为待验证。

## 5. 一次性执行顺序

1. 停机前核对全部源文件、READY、原始证据、环境散列、旧镜像、三服务健康状态和数据卷使用者；验证 Compose 配置。额外容器占用数据卷时拒绝继续。
2. 新镜像先运行无数据卷的 `verify-image`：校验候选全源码和镜像 `/app` 中所有运行模块、静态资源、requirements 的字节。UID 10001 无法读取源码等问题会在停服前失败。
3. 依次停止 `web`、`sync/app`；必须干净退出、非 OOM、退出码 0，并确认数据卷无其他运行容器。137 或 143 不能当作平稳停机。
4. 新容器执行 `snapshot` 保存原 42 表状态；运行既有 `backup.py` 备份注册库和全部家庭；`validate-backup` 核对整组映射、大小、SHA 和 SQLite 内容，失败不得进入 warm。
5. `warm` 再次核验原状态和备份，再初始化所有家庭。`check` 确认只新增精确 DDL 的空表，旧 schema、全部行及内部序号不变；不运行同步 worker。
6. 全部校验通过后安装已审源码及新清单，标记新镜像；只启动 `app`，等待健康，再执行一次 `check`。未通过前不启动 `sync/web`。
7. 最后启动 `sync`、重建 `web`，检查 nginx 配置、服务和镜像，再读回源码与环境，生成控制器完成记录。后续真实入口、来源、发布后备份等仍按发布验收要求单独完成。

数据校验都在新镜像的独立容器中进行：网络禁用、只读根文件系统、UID/GID 10001、384 MiB 内存、受限进程数、tmpfs；候选挂载 `/release-source:ro`，输入挂载 `/release-check:ro`，数据卷挂 `/data`。这不等于数据卷只读：backup 和 warm 会按上述流程写入。

`frozen.json`、`schema.json`、`before.json`、`backup.json`、`backup-verification.json` 逐步固定 SHA；每次调用前后复核源码、环境和输入。容器内再次验证这些散列、候选与镜像运行字节，并固定备份 manifest 的原始字节散列。schema 原文从候选 `journey_documents.SCHEMA_SQL` 读取，不能维护另一份手写 DDL。

## 6. 失败、记录与验收边界

停服前验证失败不会停止现有服务。进入停机流程后失败，控制器尝试停止 `web/sync/app` 并保留现场；同时按本次唯一容器名停止可能在 Docker 客户端超时后仍存活的校验容器。停止失败会写入记录并要求人工处理，不能假定现场已无写入者。

**不自动恢复数据库、源码或镜像，不清除迁移后的数据。** 源码安装中途失败也保留已写文件和完整旧源码 TAR。不得反复运行同一迁移来“试到成功”；维护者先查实际阶段、容器和备份，再另行审查修复或恢复方案。恢复备份可能带回旧会话，按 [恢复演练](RECOVERY-REHEARSAL.md) 和 [成员会话](MEMBER-SESSIONS.md) 的失效要求处理。

每次发布目录保存 `deployment.json`、原始 READY/BASE/旧清单、源码 TAR、校验输入及原始证据副本；`.env` 为单独受限文件。部署记录输出阶段、服务、散列和安全汇总，不打印 `.env`、提供商输出或数据库内容。错误正文不外发，日志和备份仍只供授权维护者访问。

[控制流专项](../tests/test_journey_documents_release.py) 在提交 `aecfd6c373eb34c56e0144ee01b639c31389dd32` 已有 **66 项离线检查通过**：使用 fake Docker runner 和真实临时文件，覆盖门槛拒绝、备份失败禁止 warm、漂移与 DDL 失败、分步启动、部分安装失败、超时容器清理及保留现场。它没有执行真实 Docker、SSH 或生产迁移，也不是实际 Docker 恢复证据。迁移 SQLite 专项、当前源码组合测试、实际 Docker 合成恢复及正式发布必须分别记录。
