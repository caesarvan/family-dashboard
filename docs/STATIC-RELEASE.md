# 静态界面的 43→43 发布

本工具经非作者独立审查、最终镜像专项及真实两户 Docker 演练，已用于 2026-09-15 22:32:04（北京时间） 的旅行入口发布。镜像 `sha256:14c7db7ba55cb4bbbed919b0b14d4bb1b1670eeb07d9a6f90e05799220590dfb`，248 源文件；实际生产 1 户的 43 表与 2 张平台表保持，未执行 warm 或 schema 变更。完整证据见 [VALIDATION](VALIDATION.md)，Git 规则见 [协作指导](GIT-WORKFLOW.md)。历史 [42→43 控制器](JOURNEY-DOCUMENTS-RELEASE.md) 不对当前库重复执行。

## 适用范围

运行代码只允许已审查的 `static/` 变更。完整候选不能移除旧文件；README、`docs/*.md`、`tests/*.py` 可作为配套精确差异。部署工具仅允许 `deploy/activate_static_release.py`、`deploy/check_static_release.py`、`deploy/build_static_release.py`、`deploy/rehearse_static_release.py` 四个明确路径。其余根 Python、requirements、Dockerfile、Compose、Nginx、backup.py 和旧工具必须保持原字节。

每户必须恰有当前 43 张表，平台注册恰有 2 张表。资料表可以包含历史 BLOB、软删除及孤立资料，不能要求为空。全部旧 schema、索引、trigger、列、外键、行值及 SQLite 内部序号在停写窗口完全相同；SQLite 文件物理页的排列不作为逻辑相等条件。资料表的完整定义另与当前 `journey_documents.SCHEMA_SQL` 核对。

改变后端、依赖、配置或数据库结构时拒绝使用此模式。它不是可容许任意业务变更的通用迁移器，也不能只修改表数绕过比较。界面仍可能触发业务操作，受影响功能、权限和迟到响应必须真实验证。

## 构建及 READY

构建器从固定的当前不可变镜像继承，仅 COPY 完整静态树，不拉取新基础镜像或重装依赖。父子镜像完整 Config 必须相等，RootFS 必须恰为原 layers 加一层；根 Python 与 requirements 字节相同，完整静态集合及字节匹配新清单。控制器会再次实际 inspect 镜像，并在无数据卷的子镜像中检查 `/app`，不能仅凭构建报告的 true 值放行。

候选是应用根同级、无符号链接的绝对目录，名称前缀 `family-dashboard-candidate-static-`，包含完整源码、`RELEASE-MANIFEST.json`、实际原源码的 `BASE-MANIFEST.json`、`READY.json`、`evidence/` 下原始证据。清单与自身、READY、证据分离。私有配置和数据库不进入候选或通用包。

实际入口只有四个位置参数：

```sh
# 仅由已授权维护者填入经过独立核对的实际参数。
# python3 <candidate>/deploy/activate_static_release.py <candidate> \
#   sha256:<new-image> <manifest-sha256> <ready-sha256>
```

READY 的 SHA 由调用者独立传入；不能手工把未通过报告改成 verified。下例是不能执行的结构占位：

```json
{
  "version": 1,
  "mode": "static-only",
  "verified": false,
  "image": "<new immutable image>",
  "previousImage": "<actual old immutable image>",
  "manifestSha256": "<candidate manifest raw SHA>",
  "baseManifestSha256": "<actual old source manifest raw SHA>",
  "oldManifestSha256": "<original installed RELEASE-MANIFEST raw SHA>",
  "environmentSha256": "<original .env raw SHA; no values>",
  "sourceHashes": {"<every candidate source>": "<SHA>"},
  "baseHashes": {"<every actual old source>": "<SHA>"},
  "changedFiles": ["<exact reviewed differences>"],
  "schema": {"from": 43, "to": 43, "newTables": []},
  "evidence": {
    "staticBuild": {"path": "evidence/build.json", "sha256": "<SHA>"},
    "backendReuse": {"path": "evidence/backend.json", "sha256": "<SHA>"},
    "browsers": {"path": "evidence/browsers.json", "sha256": "<SHA>"},
    "releaseSafety": {"path": "evidence/safety.json", "sha256": "<SHA>"},
    "gitReview": {"path": "evidence/git.json", "sha256": "<SHA>"}
  },
  "gitReview": {"placeholder": "exact complete gitReview envelope"}
}
```

五份 envelope 均须 `verified:true`、完整 `sourceHashes` 与候选相等，且非空 `records:[{path,sha256}]` 指向原始字节文件；不能引用自身。控制器校验 SHA 并保全这些原件，证据真实性由独立审查者核对，不能以 envelope 自述代替真实运行。

| envelope | 必需附加字段 |
|---|---|
| staticBuild | image、parentImage、manifestSha256；nonStaticRuntimeHashes 为全部根 Python 与 requirements，staticHashes 为完整 static；parentLayersPreserved/configurationUnchanged=true、pipExecuted=false |
| backendReuse | coverageMode=`unchanged-backend-dependencies`、previousImage、nonStaticRuntimeHashes、singleFullRunPassed=false；windows/linux 各含 tests/passed/skipped 正确计数，集合适用性和原失败/重试另由 records 保留 |
| browsers | 非空、不重复 groups，每项 script 为清单内 tests 路径，checks 为实际正整数、passed=true、externalRequests 为整数 0 |
| releaseSafety | realDocker=true、相同 image/manifestSha256、households 至少 2、实际 checks、originalTablesPreserved=43、newTables=0、productionWrites=0、allPassed=true |
| gitReview | reviewed=true；完整 baseCommit/mainCommit/integrationCommit/mainTree/integrationTree，后两个相等；整份对象与 READY.gitReview 相同 |

原后端证据不改写为在新镜像重新运行的全部测试。新控制器、数据库核对器和受影响浏览器专项单独记录；若依赖适用性无法证明则补相应验证。合成演练可用明确标注的 fixture READY 驱动控制器，但该输入不是演练成功报告；实际演练原件随后独立审查并形成生产 releaseSafety，不能自引用。

## 控制流与配置保留

默认生产根为 `/opt/family-dashboard`，发布记录在同级 `family-dashboard-releases/static-<UTC>`；非覆盖创建。先独占发布锁，固定实际旧镜像、完整原清单及仍安装的原 RELEASE-MANIFEST，保留其原字节差异，不拿新清单覆盖原件来制造一致。

所有 Compose 命令固定 `--project-name PROJECT --file ROOT/compose.yaml --env-file ROOT/.env`，不自动合入 `compose.override.yaml` 等旁路文件。首个命令前拒绝宿主进程中任何 `COMPOSE_`／`DOCKER_` 前缀变量（含空值、大小写变体）；随后每个命令使用核对时的环境副本，不继承后来的进程环境变化。原 Compose 文件和 `.env` 在调用时再次核对字节。

停服前按 Compose 实际解析环境，并与正在运行 app 的 Config.Env 逐项比较。完整解析配置也单独冻结，每次 `up` 前整体重读核对，不能只凭相同环境放行不同 command、entrypoint 或 mounts。复用已冻结的 Compose 输出反解，保留引号、美元符号、换行和反斜杠；不自行解析 dotenv。完整环境与配置只写私有 `verification/environment.json`、`compose-config.json`，0400、UID 10001，绑定字节 SHA；普通结果只记 SHA。原 `.env` 独立保全并反复核对，不进入日志、普通证据或源码 TAR。

1. 无数据卷的新镜像容器验证完整源、后端及静态文件集合；失败不停止原服务。
2. 停 web，再停止 sync/app；均必须 exit 0、无 OOM，并确认没有其他运行容器使用目标卷。维护者同时保证没有宿主机上的导入、维护或其他写者。
3. 对注册库和所有合法注册家庭建立只读 snapshot，再执行原 backup.py。逐份验证备份大小、SHA、家庭映射、原 schema/列/行及完整成员集合，绑定 manifest 原字节。
4. 不执行 warm、DDL、worker 或云 tick。安装前再次比较全部 43 表与备份；以非覆盖临时文件逐一安装已审差异，保存完整旧源码 TAR 和原 manifest。
5. 启动 app，web/sync 仍关闭。完整数据库再次与停写 snapshot 相等。只通过 app 容器的 `127.0.0.1:8000` GET 检查健康、完整静态 SHA 和固定 8 个匿名受保护接口；禁用代理、拒绝重定向，不登录或调用提供者。
6. HTTP 后再次核对完整数据库和备份，才提交并启动 sync/web。后续自然同步可能改变业务数据，应独立记录，不能声称开放写者后所有数据库仍不变。

所有 helper 容器以新镜像、UID 10001、只读根、network none、受限内存运行；只有备份流程写新备份文件，核对器只读。每次调用校验源码、输入、原始 backup manifest；候选和验证目录只读挂载。只有 app 的内部 HTTP 读回使用其既有容器网络，URL 固定 loopback。

## 检查器与隔离演练接口

[check_static_release.py](../deploy/check_static_release.py) 的 CLI 为 `snapshot|validate-backup|check --data-dir PATH --inputs-dir PATH`，没有 warm。只读 `snapshot` 返回 `{registry,households}`，摘要含计数与 SHA 而非实际行；外层保存为 `before.json`。`backup.json` 是原 backup.py 的 `{manifest,databases}`；`validate-backup` 返回 `{databases,manifestSha256,groupVerified}`，保存为 `backup-verification.json`。

`check` 返回 households、originalTablesPreserved=43、newTables=0、schemaIndexesAndTriggersVerified=true、allOriginalRowsAndSequencesPreserved=true、以及完全相同的 backup proof。缺库不创建替代库，表缺失、结构漂移、资料 BLOB 变化、序号变化或备份重封均拒绝。

Python `activate(..., root=..., releases=..., project=..., volume=..., runner=...)` 允许真实合成演练显式指定全新目录和独立 Compose 项目；volume 必须为 `project + '_household-data'`，镜像 tag 为 `project + '-app'`，所有 Compose 调用固定该 project、配置文件及环境文件。`runner(args, *, cwd, env, input_bytes=None, timeout=180)` 必须把传入的环境副本用于实际进程，不能改回继承宿主环境。CLI 不暴露这些 override。演练使用新合成配置和数据，不能复制生产 .env、证书或真实库，也不能取消安全断言。

冻结复用依赖：旧 `activate_journey_documents_release.py` SHA `703a1540f7a632301382ec32aaee3b68e2c2157943469a71492a0d1a9e75972c`；旧 `check_journey_documents_migration.py` SHA `11adc9f40bf68aaca7015f3c9f18f92c7aa648b6c379b0812b60b5d22cd2781f`。导入前核对字节，只调用安全路径、摘要、备份核验与环境解析等纯函数；不调用旧 activate/preserved/warm。

## 失败与验证边界

停服前失败保留原服务；停服后失败停止 app/sync/web，保留完整备份、输入、旧源码和部分安装现场，不自动恢复数据库、不盲目回退镜像。超时的 Docker 客户端不等于容器已停止；只针对本次精确 name、image、ownership label 的 helper 停止并读回，身份不符保留并要求人工处理。SIGINT/SIGTERM 进入同一保全路径，强制 kill 或主机掉电仍须维护者处理现场。

[控制器专项](../tests/test_static_release.py) 使用命令替身；[数据库专项](../tests/test_static_release_database.py) 用当前 factory、双家庭 SQLite 和真实 Flask 路由验证完整静态 SHA、匿名权限与数据保持。最终这两模块 112 项，连构建 23、演练安全 52，在最终 Linux 镜像共 187 项通过。另行实际运行的两户 Docker 演练验证旧会话、8 份资料和 3 库备份保持，不是这些替身测试的重复计数；生产发布及两次不同阶段的失败见 [VALIDATION](VALIDATION.md)。下一次发布仍须重新冻结候选、证明依赖适用性、独立审查并验证实际环境，不能直接复用旧 READY。

后端根 Python 与静态共同变化时，另见 [无 schema 源码更新](SOURCE-RELEASE.md)。两个入口复用唯一事务核心和原发布锁；本静态入口仍固定 static-only，拒绝后端变化，不能通过 READY.mode 升级策略。新入口的实现、实际演练与生产发布须分别验证。此次共享抽取仅为上文静态工具白名单增加 `deploy/release_core.py`；`deploy/source_release.py` 不列入静态白名单，其他限制保持。
