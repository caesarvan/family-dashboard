# 无 schema 变化的源码更新（43→43）

此入口用于经过逐文件审查的既有根 Python 与静态文件更新。工具固定提交 `4c05e50` 已通过非作者代码审查，并在集成版本 `e0769e3` 完成 Windows 269 项组合；本页不代表已经完成新镜像 Linux 测试、Docker 演练或生产发布。当前运行版本及实际记录仍以 [VALIDATION](VALIDATION.md) 为准。纯静态更新继续使用 [STATIC-RELEASE](STATIC-RELEASE.md)，不能修改 READY.mode 来提升原静态入口的权限。

## 范围与共同安全流程

[source_release.py](../deploy/source_release.py) 固定选择 `source-update`，提供 build、rehearse、activate 三个独立命令。[release_core.py](../deploy/release_core.py) 保存唯一事务流程，原静态入口固定选择 `static-only`。两者共用原 `.static-release.lock` 文件及其锁 inode，不能并发操作同一发布根；生产 CLI 不开放 project、root 或 volume 替换参数。

候选不能删除旧文件，也不能新增根 Python 模块。只允许已存在根 Python 的明确批准差异、static，以及具体 docs/tests/发布工具配套路径；至少有一处既有根 Python 变化。requirements、Dockerfile、Compose、Nginx、backup.py、旧迁移器及其他未列入工具名单的文件必须保持原字节。工具路径仅在受审代码中列举，不由 READY 扩展。

本模式不初始化 schema、不 warm、不自动 restore。[check_static_release.py](../deploy/check_static_release.py) 保持原字节：每户 43 表及 2 张平台表，全部 schema、索引、触发器、列、外键、行值、认证、资料 BLOB、SQLite 内部序号与停写 snapshot 相同。不是只比较表数，也不要求业务表为空。源码的 DDL 与初始化路径还须人工审查；未搜到 SQL 关键字不等于无副作用证明。新 app 启动或读回导致数据变化时停止保全，不能把这种变化当作零 schema 更新放行。

共同顺序是：无数据卷验证子镜像 → 停 web → 干净停止 sync/app 且排除其他卷写者 → 全组 snapshot/backup/validate-backup → 安装前 check → 安装已审源与 manifest → 仅启动 app 并等待健康 → check → 容器 loopback 健康/全部静态 SHA/8 个匿名权限 GET → check → 最后启动 sync/web 并执行 nginx -t。开放写者后自然同步另计，不能继续声称所有行不变。

原 `.env`、完整 Compose 解析结果及正在运行 app 环境必须一致，保留引号、美元符号、换行和反斜杠。私有解析输入为 0400、UID 10001，普通报告只记录 SHA。Compose 始终指定 project、唯一配置文件与环境文件，拒绝宿主 COMPOSE_/DOCKER_ 选择变量；每次启动前重新比较完整配置。详情及失败边界沿用 [静态发布指导](STATIC-RELEASE.md#控制流与配置保留)。

## 输入与镜像构建

使用实际已发布源码包中的 BASE，不使用含未上线功能的 main 冒充生产。`BASE-MANIFEST.json` 与实际仍安装的 `RELEASE-MANIFEST.json` 可以有历史差别，两者各自绑定外部 SHA 并保全原字节；禁止先覆盖旧 manifest 制造一致。源包只含允许源码，不含 `.env`、数据库或真实财务文件。

候选目录是 root 同级的无符号链接绝对路径，前缀 `family-dashboard-candidate-source-`。包含完整候选、RELEASE-MANIFEST、BASE-MANIFEST、READY 和 evidence 原件；私有文件不进入源码 manifest。共享 core、实际入口、构建/演练模块和冻结旧依赖均按执行路径核对字节，不能只核薄入口自身。

```sh
# 分别完成审查并授权相应阶段后，填入实际参数；占位不可执行。
# python3 <candidate>/deploy/source_release.py build <candidate> \
#   sha256:<parent> <candidate-manifest-sha> <base-manifest-sha> <new-build-output>
# python3 <candidate>/deploy/source_release.py activate <candidate> \
#   sha256:<child> <candidate-manifest-sha> <ready-sha>
```

build 读取候选旁的 BASE-MANIFEST 并核对独立传入的 SHA。实际父镜像的全部根 Python、requirements、static 集合与字节必须等于 BASE；子镜像必须等于候选。上下文仅有固定 FROM 与一次 COPY 完整 Python/static 到 `/app` 的指令，没有 RUN、pip、环境或配置变更；requirements 继承父镜像。完整 Config 相等，layers 恰为父层加一层；实际 probe 拒绝旧 Python 遗留、额外文件或漏文件。上下文、BASE、候选和 manifest 在构建前后重验。build.json 里的 `runtimeChanges` 是事实差异，不是审批。源码模式另在无卷的父／子镜像检查 `sys.dont_write_bytecode`、`sys.pycache_prefix` 与 `/app` 内 `.pyc/.pyo`；有效 Compose 环境也必须禁写且无自定义缓存目录。仅设置 PYTHONDONTWRITEBYTECODE 不能证明没有旧缓存。每次源码 helper 及启动后 HTTP 程序入口重验缓存，不删除缓存来绕过拒绝。新 app 的真实业务行为还须由子镜像专项／演练验证；这里不声称读取了 gunicorn 进程内存。

## READY 合同

外部调用者批准 READY 原始 SHA。必须仍由独立审查者核对真实报告及最终 Git 树，不能只看 `verified:true`。以下仅为有效 JSON 结构占位；未填值不能通过控制器：

```json
{
  "version": 1,
  "mode": "source-update",
  "verified": false,
  "image": "<child immutable image>",
  "previousImage": "<actual parent immutable image>",
  "manifestSha256": "<candidate raw SHA>",
  "baseManifestSha256": "<actual BASE raw SHA>",
  "oldManifestSha256": "<installed manifest raw SHA>",
  "environmentSha256": "<original .env raw SHA>",
  "sourceHashes": {"<every candidate file>": "<SHA>"},
  "baseHashes": {"<every BASE file>": "<SHA>"},
  "changedFiles": ["<exact all changes>"],
  "approvedRuntimeChanges": [{"path": "<existing module.py>", "beforeSha256": "<old SHA>", "afterSha256": "<new SHA>", "kind": "rootPython"}],
  "schema": {"from": 43, "to": 43, "newTables": []},
  "evidence": {
    "sourceBuild": {"path": "evidence/build.json", "sha256": "<SHA>"},
    "backendValidation": {"path": "evidence/backend.json", "sha256": "<SHA>"},
    "browsers": {"path": "evidence/browsers.json", "sha256": "<SHA>"},
    "releaseSafety": {"path": "evidence/safety.json", "sha256": "<SHA>"},
    "gitReview": {"path": "evidence/git.json", "sha256": "<SHA>"}
  },
  "gitReview": {"placeholder": "complete identical gitReview envelope"}
}
```

approvedRuntimeChanges 按路径排序，恰为真实 root Python/static 差异；static 的 kind 为 `static`，新增静态文件 beforeSha256 为 null。缺少、多出或旧 SHA 不同均拒绝。changedFiles 还包含已审 docs/tests/工具差异，不能省略。gitReview 必须包含同一批准列表及 compatibility，不能拿另一棵树的审查代替。

五 envelope 均有 `verified:true`、完整当前 sourceHashes 和非空 `records:[{path,sha256}]` 原始记录；引用只能位于候选 evidence 下、不能自引用。外部原件不改写成新时间、新镜像或新测试结果。

| envelope | 附加约束 |
|---|---|
| sourceBuild | mode、image/parentImage、manifestSha256/baseManifestSha256；parentRuntimeHashes 等于 BASE 全部 Python/requirements/static，candidateRuntimeHashes 等于候选；approvedRuntimeChanges 相同；parentLayersPreserved/configurationUnchanged/parentBackendVerified/childBackendVerified/staticVerified/bytecodeExcluded=true，pipExecuted=false。引用未经改写的实际 build 原件。 |
| backendValidation | coverageMode=`affected-source-tests`，changedPython 为本次所有变化 Python；compatibility 四项均 true：noSchemaChanges/noDataMigration/noDependencyChanges/noConfigurationChanges。runs 与 historicalReuse 分开。 |
| browsers | 非空唯一 groups；script 在源码清单，checks 是本轮实际正整数、passed=true、externalRequests 为整数 0。各原报告及适用性由 records 保留；不把 route 数混作功能数。 |
| releaseSafety | realDocker=true，当前 image/manifestSha256，households≥2、实际 checks>0、originalTablesPreserved=43/newTables=0、productionWrites=0、allPassed=true。 |
| gitReview | reviewed=true；完整 baseCommit/mainCommit/integrationCommit/mainTree/integrationTree，后两树相等；与 READY.gitReview 整体相等，包含批准列表与上述 compatibility。 |

每个当前后端 run 有 platform（windows/linux）、scripts、coveredChanges、tests/passed/skipped/failures/errors、exitCode=0、dependencyHashesBefore/After、junit/log 引用。scripts 必须是实际 tests/test_*.py；依赖两次相同且包含全部当前根 Python/requirements 和实际测试脚本，所有散列都属于候选。Linux run 另绑当前子镜像。控制器解析实际 JUnit testcase 的计数、失败、跳过和脚本 classname，拒绝缺覆盖、假计数或不相关 JUnit；每个平台合计须覆盖本次全部变化 Python。选择哪些用例足以覆盖业务仍须独立审查，不由用例数量推断。

historicalReuse 是独立列表，每项有 record 引用、仍相同的 dependencyHashes、excludedChangedFiles（全部变化 Python）和 reason；不能把变化模块列为“未变依赖”。没有复用时明确空列表。历史失败、精准重试、跳过和镜像身份保留原意；本模式不强制重复无关的 1495 项，也不能把旧全量结果直接声明为当前后端通过。

## 真实隔离演练与验收

```sh
# 独立审查后才由授权维护者执行；只接受全新输出目录。
# python3 <candidate>/deploy/source_release.py rehearse \
#   --source <candidate> --manifest-sha256 <candidate-sha> \
#   --base-source <frozen-old-source-directory> --base-manifest-sha256 <old-sha> \
#   --parent-image sha256:<parent> --image sha256:<child> \
#   --build-proof <original-build.json> --build-proof-sha256 <raw-sha> \
#   --nginx-image sha256:<local-nginx> --output <new-private-directory>
```

旧 BASE 是原包核验后得到的独立源码目录，其 RELEASE-MANIFEST 原字节必须等于候选 BASE-MANIFEST。旧/new fixture 分别来自旧 BASE 和新候选，不把新 Python 伪装成旧源码。合成 Compose/Nginx 只在副本替换、前后相同，network none、无宿主端口/生产证书；两套 adaptations 分别记录。原冻结源、原 build 报告与 BASE 均不改写。

旧父镜像运行原合成 seed，建立两户 43 表、认证、历史数据与 8 份资料；再调用实际源码控制器。完成后真实比较 registry 与两户全行/schema/序号/认证、8 文件内容及三库备份。没有 restore。fixture READY 明确 synthetic/isAcceptanceEvidence=false，仅驱动实际流程；实际 controller、seed、独立读回和清理原件才形成新的验收证据。

只清理本 run 创建且名称、image、标签核对一致的容器/卷。输入镜像不删除，保留独立 project-app tag 并记录理由，不宣称所有 Docker 对象全部清除。任何超时或失败保留原始结果后回作者分支修正，不能现场放宽 gate 后把旧失败原件改成通过。

本机命令替身专项证明可执行控制流和拒绝边界；原真实 SQLite 专项证明检查器逻辑。二者不代替新子镜像上的实际工具/受影响业务测试及真实双户 Docker 源码更新演练。生产发布还需新鲜 BASE、配置、服务读回和独立 READY 审查，最后才单独授权调用。
