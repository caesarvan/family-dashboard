# 部署、更新与恢复交接

## 当前助理清单版本：75/9，五服务

2026-09-21 05:41:15（北京时间）激活，05:41:40只读回读通过。实际安装 source `e8f0427`，部署身份、回执与验证边界见[助理清单验收](ASSISTANT-LIST-ACCEPTANCE.md#assistant-list-release)；本次沿[助理清单发布适配](ASSISTANT-LIST-RELEASE.md)执行。

生产一户两库完成完整组备份，75张家庭表和9张平台表没有迁移；app单独启动后再次停止，核对全部表、数据、settings和序列一致。1249个安装文件、三个应用服务各136个运行文件及decoder原4文件逐项核对；五服务运行，app/decoder健康，无OOM或重启，HTTPS正常校验证书，备份timer active。本次未执行生产恢复；只读回查不重新读取活库业务内容或重验备份SQLite字节。本人完整A–D验收仍0/4，实体电视待验。

当前stage／activate已消费。下次以实际75/9、五服务、manifest与镜像准备新包及新计划，不能重放本次或历史迁移。保留配套源码、镜像、配置和完整组备份；需要恢复时先停止全部写者和备份timer，以对应发布回执核对整组恢复，不仅回退镜像或单户。

## 历史视频版本：73/9，五服务

2026-09-20 17:26:15（北京时间）激活，17:33:17 生产只读检查通过，随后非作者复核通过。相册支持明确选择并保存视频、成员播放和逐台授权的照片／视频轮播；真实 Google 视频和实体电视仍待验。固定应用 source `b8c4d599`；新五服务为 app、sync、media、decoder、web，环境值保持。[发布身份与数据保全](MEDIA-VIDEO-ACCEPTANCE.md#media-video-release)列出完整包、镜像、plan、stage／activation SHA 和保全目录。

发布使用[独立五服务控制器](MEDIA-VIDEO-ACTIVATION.md)，本次计划已经消费，不能重放。该历史版本当时的后续更新须绑定73/9和新计划；现行身份以文首为准；不得让旧四服务适配器或 71 表迁移入口直接操作当前库。恢复必须停全部写者和备份 timer，核对本次保全目录，恢复同一时点的平台及全部家庭，再核验后启动；禁止只回退镜像或单户数据库。生产本批未执行恢复，隔离完整组演练另有证据。

## 历史本地日程隐私版本：71/9

2026-09-20 10:11:17（北京时间）激活，10:18:48 独立生产只读审计通过。一户两库保持 71/9，没有 DDL 或旧数据回填。[使用与集中验收](CALENDAR-PRIVACY-ACCEPTANCE.md#calendar-privacy-release)固定了实际 source、镜像、包、已消费计划和阶段原件；发布入口为 `build_calendar_privacy_release.py`／`activate_calendar_privacy_release.py`，合同见[发布适配](CALENDAR-PRIVACY-RELEASE.md)。

本批包含 107 个非 Expo 运行文件：4 个明确变动、103 个与父版一致；其余 23 个为正式 Expo 导出。停写后备份完整库组，app-only 启动并停下后严格核对全部表、settings、序列和非空提醒数据，再恢复服务。实际 stage／activate 已消费，不得重放；后续候选必须绑定当前安装身份和新计划。

## 历史日程重叠版本：71/9

2026-09-20 08:47:27（北京时间）激活，08:49:19 独立生产只读审计通过。一户两库保持 71/9；本批只替换 Expo 界面，106 个非 Expo 运行文件与提醒父版一致。[使用与集中验收](CALENDAR-CONFLICTS-ACCEPTANCE.md#calendar-conflicts-release)包含固定包、实际镜像、已消费计划和原件。发布适配为 `build_expo_calendar_conflicts_release.py`／`activate_expo_calendar_conflicts_release.py`，见[合同](EXPO-CALENDAR-CONFLICTS-RELEASE.md)。

本次按非空 71 表基线停写并备份完整数据库组，app-only 启动后核对全部表、settings、序列、提醒状态及回执完全保全，再恢复四服务。没有 DDL，也不重跑父版的 69→71 迁移。本次 stage／activate 已消费，不得重放；后续新版本必须重新绑定实际安装身份和新计划。

## 历史提醒版本：69/9→71/9

2026-09-20 07:52:22（北京时间）激活，07:56:49 独立生产只读审计通过；生产一户两库已完成 69/9→71/9。正式身份、已消费计划和原件集中在[提醒验收](TASK-REMINDERS-ACCEPTANCE.md#task-reminders-release)。发布工具为 build_task_reminders_release.py／activate_task_reminders_release.py，合同见[发布](TASK-REMINDERS-RELEASE.md)、[迁移检查器](TASK-REMINDERS-MIGRATION.md)与[隔离 Linux 演练](TASK-REMINDERS-LINUX-REHEARSAL.md)；本次 stage／activate 及首次迁移不得重放。

停写后备份完整注册库及所有家庭库，只新增两张空提醒表；先仅启动 app，再严格核对原 69 表、平台 9 表、全部 settings、序列及新空表。通过后才恢复全部服务，worker 正常生成提醒与 heartbeat；不能因此豁免 app-only 保全。失败保留现场并停止候选写入者；跨户部分失败须恢复同一完整库组并验证，不自动重跑 migrate 或仅恢复一个家庭。

本次隔离两户三库已验证旧 69 表整组回退及有提醒状态／回执的 71 表完整恢复；这是合成演练，不是生产恢复。后续部署必须重新固定实际安装身份、完整组备份和新计划，详见集中验收。

**历史父版：任务依赖，69/9。** 2026-09-20 06:28:25（北京时间）发布并独立审计，其结构随后由文首提醒版本升级。父包及原 354 项 Linux 验证见[任务依赖验收](TASK-DEPENDENCIES-ACCEPTANCE.md#task-dependencies-release)；下方更早版本均仅供追溯，不可作为当前安装身份。

**历史账户分析基线：66 张户内表、9 张平台表。** 本人账户分析于 2026-09-19 16:20:25（北京时间）激活，16:20:57 独立只读审计通过。生产实际一户两库从 61/9 迁至 66/9；固定 source `f25357f935d64774922efa68d42a2ba41bb18037`、镜像 `sha256:21625d6e2d9768ba48cca35100bb8bf02c1c4146afa6b7ad25b9b72cb559c1d2` 及完整身份见[分析发布验收](FINANCE-ANALYSIS-ACCEPTANCE.md#finance-analysis-release)，数据保全与恢复合同见[本批发布](FINANCE-ANALYSIS-RELEASE.md)。不得重放本批、成员迁移或下面的固定历史算子；后续更新必须绑定实际 manifest、镜像及全组数据库。下方旧基线与代码块仅供历史追溯。

**历史激活版：家庭与成员，2026-09-18 05:49:18（北京时间）。** 58→58 但 `schemaChange=true`，仅新增 `users.household_role`；停写后实际 1 户两库完整组备份，旧 users 五列、其它 57 表及 registry 保全，app 启动快照等于迁移后快照。05:49:55 发布后读回通过，05:55:19 独立读回及随后审计通过；固定身份、实际 Linux 226 通过／1 精确 Windows 跳过及迁移证据见[成员验收](EXPO-HOUSEHOLD-MEMBERS-ACCEPTANCE.md#household-members-release)。不得重放已完成算子或迁移。

**此前运行版：旅行 JSON 导入，2026-09-18 04:42:28（北京时间）激活。** 58→58，无 DDL；实际 1 户两库停写备份、启动时原行／schema／序列与平台注册库保持。发布身份、镜像、静态资源、HTTPS 和后置备份见[旅行导入验收](EXPO-TRIP-IMPORT-ACCEPTANCE.md#expo-trip-import-release)。后续发布须重新固定实际父版本，不重放已完成的固定算子。

**历史账户结构基线为 58 张户内表及 2 张平台注册表。** 2026-09-18 00:23:38（北京时间）完成手动资产账户发布，00:24:23 HTTPS 读回、00:27:22 独立只读复核通过。完整身份及证据见 [发布验收](EXPO-FINANCE-ACCOUNTS-ACCEPTANCE.md#finance-accounts-release)。后续更新须绑定新的实际基线，不可重放任何已完成迁移；该账户历史基线使用 [账户迁移检查器](FINANCE-ACCOUNTS-MIGRATION.md)。当时新增角色列后的完整组恢复必须改用 [成员角色迁移检查器](HOUSEHOLD-MEMBERS-MIGRATION.md) 的 snapshot-current／check-restored，旧结构整组回退用 check-rollback；不能仅凭同为 58 表混用检查器。生产覆盖恢复未执行。

当前安装版本及实际发布证据以 [README 最新上线记录](../README.md) 和其链接的验收页为准。下方保留数据库结构变化与恢复要求的历史基线；后续界面更新不能据此复用旧发布包、镜像或固定算子。

> **历史结构基线：2026-09-17 06:15:34（北京时间）持仓版，06:16:14 正常 TLS 读回通过。** main `f2146f2`／source `1bb4342`，503 源文件、113 运行文件、152 个方法／路径模板、55 张户内表与两张平台注册表。完整身份和实际验证见 [发布记录](VALIDATION.md#expo-holdings-release)，当次操作见 [持仓 54→55 发布](HOLDINGS-RELEASE.md)。

该历史持仓版实际 1 户两库备份后只新增空操作回执表，原 54 表及注册库保持至新 app 启动核对；原配置保持，四服务运行且 app healthy。该历史版本后续更新当时须绑定 55 表、镜像和清单；已完成的 54→55 及下方旧 44／43 表固定操作都不能重放。完整恢复需使用与该历史 55 表版本匹配的整组备份，并以 `check_investment_operation_migration.py` 的 `snapshot-current`／`check-restored` 核对；本轮只完成合成恢复测试，没有执行生产覆盖恢复。下方历史命令保留用于追溯，不能只改表数当作新发布流程。

> **历史地点版本：2026-09-16 16:33:32（北京时间），镜像 `sha256:9cd092392b27d6e2342ab1890ff3514149416281fe130df62976b8b1488acac8`。** 当时旅行地图完成 43→44 迁移发布；295 源文件、52 Markdown、47 静态资源、112 个方法／路径模板、44 张户内表及 2 张平台表。安装源码对应 main `6f3d978`／integration `cd857f5` 的同一文件树；该次发布后的交接文档当时尚未同步服务器。NVIDIA 于同日 16:58 完成配置与真实模型草稿验证；真实用户全流程和电视验收分别记录。

## 历史地点版：已完成 43→44

2026-09-16 16:33:32按 [地点发布流程](JOURNEY-PLACES-RELEASE.md) 上线，实际记录见 [VALIDATION](VALIDATION.md)。当时44户内表+2平台表；manifest `1a5990e0b7e500ed44986b979e413a8ba26c92bd6cf4c7757be429bed17e51d8`；发布目录 `/opt/family-dashboard-releases/journey-places-20260916T083232752975Z`。43→44不可重复执行，旧43→43 SOURCE不适用后续44表更新。

候选源码须允许校验UID10001读取：本次根root:10001 0750、manifest 0640，其余源文件及祖先可读。仅调整非秘密源码路径，READY/evidence/原配置/备份保持私有，不递归放宽权限。原0700预检拒绝记录保留。停写、组备份、精确DDL和数据读回仍由固定controller执行。

该历史源码初始化44+2表，完整新机安装当时仍待单独验收。该版本恢复演练显式选 `--profile journey_places44`，见 [恢复指导](RECOVERY-REHEARSAL.md)，不适用于后续 55／58 表。NVIDIA 配置于同日 16:58 独立启用：只新增 `ASSISTANT_PROVIDER`、`NVIDIA_MODEL`、`NVIDIA_API_KEY`，原镜像 no-build 有序重建 app/sync/web。旧 `.env` 原样 0600 备份位于 `/opt/family-dashboard/.env.assistant-backup-20260916T085405063887Z-04bea8ef39f84e6cb395db494622a4f0`；其他配置 record 原字节不变。仅配置回退须先核对现环境未被后续变更，再恢复配对备份并重建服务，不恢复数据库；此回退未实际执行。下方旧版本操作仅作历史追溯。

## 历史 13:24 的 43→43 SOURCE 更新

本次通过 [SOURCE-RELEASE](SOURCE-RELEASE.md) 的 `source-update` 入口更新一项既有根 Python 和三项静态文件。安装 Git 树 `e627bb843bcf84024b097eaa5e486d98d437c17f`，manifest `7089ca8899929ec8eee8b705547943c697b21c684014855f92b7f5ca4fa8fb42`；BASE 为 Git `54c0854` 的 255 文件，原 manifest `169c9621…` 保留。镜像 `sha256:ea399441e6696bc29214842ab8c47e3db943714c1ae72a05ca1266bdc4a1b739` 通过 Linux 后端 435 项、工具 275 项和真实双户演练后，完成实际单户／2 库备份、三阶段 43+2 全数据比较及读回。原配置保持，未初始化 schema 或恢复数据库；新三服务运行且 app 健康，随后独立核验全部 258 源文件与 HTTPS。原件与范围见 [VALIDATION](VALIDATION.md)。

SOURCE 与 static-only 共用原事务核心和锁；SOURCE 只接受逐文件审查的既有根 Python／静态变化，requirements、Dockerfile、Compose、Nginx 与运行配置保持。仍须冻结当前 BASE、完整原始证据和经独立审查的 READY，再由获授权维护者执行；停写、全组备份、43+2 全部数据比较与 HTTP 读回均不能省略。禁止重放一次性 42→43 或下方历史 42→42 算法。

## 历史旅行资料：已完成的一次性 42→43 发布

2026-09-15 20:23:00 已正式新增 `journey_documents`、两个显式索引和解除关联触发器；当时为 **43 张户内表及 2 张平台表**。原 42 表、行、schema 和序号在停写及启动核对窗口保持，原配置字节保留。实际发布、两类合成 Docker 演练和读回见 [VALIDATION](VALIDATION.md)。新服务器由该历史源码初始化为 43 + 2；完整空服务器安装与生产恢复仍须单列验收。

已随源码提供 [deploy/check_journey_documents_migration.py](../deploy/check_journey_documents_migration.py)，执行 `snapshot`、`validate-backup`、`warm`、`check` 四个动作；完整输入、命令和输出见 [迁移契约](JOURNEY-DOCUMENTS.md#一次性-4243-迁移检查器)。检查器不负责停服或恢复，不能把四条命令直接对运行中的数据库顺序执行。它拒绝旧表、行或序号漂移，拒绝新表预填和任何不匹配的 DDL，并在 warm 初始化前重新验证停写快照及全部备份。

专用 [发布控制器](../deploy/activate_journey_documents_release.py) 已独立审查并用于 20:23 的实际迁移。初版 66 项、第一轮配置修订 83 项保留为历史，最终控制器 100 项命令替身测试与真实单户配置迁移演练另有证据；不能把这些范围混算。四个 CLI 参数、只读挂载权限、READY 五类证据、原始记录及失败处理见 [完整发布指导](JOURNEY-DOCUMENTS-RELEASE.md)。

发布者须冻结经 Git 审查的源码、不可变镜像及测试记录；保留原源码、原镜像和相配 `.env`，先停 web，再停 sync/app，确认不存在其他写入者。停止后采集快照、生成并验证完整备份组，再串行初始化所有家庭；app 健康及迁移后读回通过后才重开 sync/web。失败保留现场和备份；部分迁移不能当作成功重启，也不能用旧数据库盲目覆盖。生产恢复仍需按第 6 节明确范围并使旧成员会话失效。

20:23 发布前独立核对了旧 222 文件源树和仍记载 218 文件的旧 `RELEASE-MANIFEST.json`，两者分别固定 SHA 并保留原字节。此前 225 文件的 Git 文档交接也不能冒充旧服务器的实际状态。20:23 的正式发布已安装新的 237 文件源码和发布清单；上述 222／218 只属于一次性控制器的原基线，不是当前安装目标。完整历史与交接边界见 [HANDOFF](HANDOFF.md)。

## 历史旅行入口：静态 43→43 更新

2026-09-15 22:32:04（北京时间） 已按 [STATIC-RELEASE](STATIC-RELEASE.md) 完成旅行入口静态更新，248 源文件、42 Markdown。新镜像固定继承父镜像，只追加完整 static 层；根 Python、依赖、Dockerfile、Compose、Nginx 和运行配置保持。全户备份、启动与 HTTP 后完整数据比较、44 静态和 8 匿名接口读回均通过，之后才开放 sync/web。

该路径没有 warm 或 DDL；比较全部 43 表已有记录（含资料 BLOB）、schema、外键、索引、trigger、序号及平台注册数据。本轮真实两户 Docker 演练通过后才执行生产，生产为实际 1 户及 2 库备份；两者统计分开。改变后端、依赖、配置或结构不适用此工具，须另行审查，不能只修改表数。

## 历史 42→42 更新

2026-09-15 16:25:03 的历史旅行执行版没有结构变化，当时使用第 5.2 节 42→42 流程。**该节所有代码现在仅供历史追溯，不能用于当前 69/9 表结构。** 已完成的一次性 42→43 同样不能重复执行。纯静态 43→43 使用 [STATIC-RELEASE](STATIC-RELEASE.md)，经明确审查的既有 Python／静态更新使用 [SOURCE-RELEASE](SOURCE-RELEASE.md)；配置、依赖或结构变化仍需另行准备与审查，不能只改表数绕过。

## 历史消费观察 40→42 升级要求（15:10:00）

该历史版首次 40→42 升级仅增加 `finance_spending_observations`、`finance_spending_receipts` 和 `finance_spending_receipts_owner` 索引。完整 DDL 在 `spending_observations.py` 的 `SCHEMA_SQL`，按该历史已发布清单核对。原 40 张表、平台注册表、历史业务／认证／例行记录、schema 对象及 SQLite 内部序号保持；新增两表初始为空，部署不预导入真实个人报告。

发布使用独立候选镜像，Linux 测试只挂载候选 tests、deploy 和 pytest.ini，不挂生产配置或卷。完成组合验收并保留原镜像、源码及 `.env` 后，先停止 web，再停止旧 sync/app；核验退出状态后生成并逐户验证完整备份组，才允许候选串行初始化所有已登记家庭。app 启动后再次读回，确认没有额外业务写入才开放 sync/web。

40 表原库可以升级；已经有任一新表、部分家庭已迁移、缺表或结构漂移均需停止核对，不能通过只改表数绕过。迁移检查必须匹配完整列、外键、隐式／显式索引及空行条件。失败只在提交前、配置相配且备份组验证通过时恢复；提交后发现新写入或结果不明时保全现场，禁止盲目旧库覆盖。新观察与账本导航不会写入第三方云账户。

**第 5.2 节是历史 42→42 零 schema 示例，不是当时 40→42 首次升级算法，也不是当前 69/9 表结构的更新步骤。** 历史消费观察迁移证据见 [VALIDATION](VALIDATION.md)；当时源码初始化 43 + 2；当前为 69/9，后续更新须使用针对实际结构另行审查并验证的流程。

消费观察文件经本人预览确认才接收；本次部署仅提供能力，不上传准备好的真实文件，不改来源刷新计划。准备工具、固定输入文件和接受契约见 [SPENDING-OBSERVATIONS](SPENDING-OBSERVATIONS.md)。

## 家庭例行计划 37→40 首次迁移

历史例行版当时为 207 源文件、33 Markdown、101 个 Flask 方法／路径模板、40 张户内表与 2 张平台表、42 静态资源。该历史发布将源码、依赖、测试及部署助手冻结到同一清单，以当时实际 Windows 1136 passed / 18 skipped、Linux 1153 passed / 1 skipped（各 1154 项）、浏览器和离线检查作为门槛；历史证据见 VALIDATION，不作为本版通过依据。

该历史 37→40 升级使用当时专门审核的三表迁移流程，不能运行第 5.2 节历史 42→42 的零 schema 更新代替：

1. 保留旧完整源码、不可变镜像、原 .env／主密钥、注册目录和全部家庭的完整备份组；禁止并行发布／导入／数据库维护。
2. 隔离镜像测试及候选 Nginx 校验成功后，停止 web 入口，再停止旧 sync/app 并确认停止。保全残存卷，使用 SQLite 备份 API 获取即时整组备份，核对 registry、全部户映射、字节／哈希／完整性。
3. 用候选逐户串行初始化，不 tick。原 37 表所有旧列与属性／顺序、schema 对象、行值及 SQLite 内部序号保持；平台两表完全保留。每户只允许新增三张例行表，完整约束与隐式／显式索引须与冻结 DDL 相同，且三表均为空。
4. 启动候选 app，健康及全部受保护内容再次读回一致后，才开放 sync/web。无预置规则，因此安装不会创建家庭事项；若三表预填、漏表、多表或旧值改变，保持停写进入排障。
5. 发布后核对备份组、环境保留、42 静态与 17 匿名受保护 GET；既有六来源晚于发布的自然成功独立记录。真实新云写、实体电视、公网和生产恢复仍未因这些检查完成。

离线激活／成组恢复 151 项、控制器 119 项只覆盖临时 SQLite/文件与命令替身，不是真实 Docker 回滚。提交前也只在整组备份和相配源码／镜像已核验、.env 未漂移且没有后续写入时受控恢复；不完整或模糊状态保持停止。开放后已有新写入，禁止恢复旧快照覆盖，应先保全现场。任何数据库恢复后先使目标家庭旧会话失效，再启动 app/web 核对，最后人工确认后启动 sync，见第 6 节。

> **历史例行计划版本：2026-09-15 13:43:04（北京时间），镜像 `sha256:5e338ef586fbc0e7b2f2efb842b08b464e33f1b3a4d8be9eb1996100fb371f6e`。** 新增 `household_routines`、`routine_occurrences`、`routine_receipts` 三张户内表；worker 在原三个云阶段后执行本地例行推进。安装不预置计划，用户未确认创建前无自动事项；每一期云发布仍需单独预览确认。当时的 37→40 升级、40→40 更新和更早的 35→37 采购迁移各有独立边界；第 5.2 节保留当时的 42→42，不能回用于这些历史结构。


> **历史采购版：2026-09-15 12:11:36，镜像 `sha256:1167dffd3b7e234d43460442acfe0d30959370c90c7e8147a1b30baa0e2380b5`。** 当时为 98 路由／37 户内表／2 平台表；10:43:53 的 `6882d2a…` 更早为 95／35／2。以下保留这些版本的证据范围，不能称其为本版当前结构或复用其迁移结果。

## 采购实付两表迁移边界（12:11:36 历史）

12:11:36 的 35→37 迁移新增 shopping_settlement.py、采购核对界面、本人导出接缝与两张私有表。该历史版最终为 98 路由／37 户内表／2 平台表；当时的两表 schema／数据保留核验继续保留。之后的历史例行版按 37→40 三表迁移；15:10:00 财务版按 40→42 两表迁移，第 5.2 节只用于两表迁移完成后的 42→42 更新。

35→37 只允许使用本轮独立审查、冻结并绑定测试镜像／源码／证据的专用两表迁移流程。先保留相配旧源码、不可变镜像、原 `.env`、注册目录和全家庭备份组，停止 web 入口，再停止 sync/app 并核验停止状态。停止后采集数据库快照，核对备份组大小、SHA-256、目标映射和内容，全部通过后才串行初始化每个已登记家庭。

迁移后的注册目录必须完全不变；每户旧 35 张表的所有旧列、列属性与顺序、schema 对象、行值及 SQLite 内部序号都必须与停止后快照完全相等。每户只允许新增上述两表；新表列、约束、隐式／显式索引须与冻结版本的定义精确相符，**初始化后两表必须为空**，不允许额外表、列、触发器或预填业务数据。不是把所有表笼统排除后再比较，也不能放宽旧 35 表的相等断言。新 app 健康且独立读回继续符合这些条件，才可提交并开放 sync/web。

已存在 138 项离线激活／恢复检查：假 Docker 控制流，加真实临时 SQLite 注册目录和两户数据库的 35→37 接受／拒绝、完整备份／恢复、临时源码归档恢复。这 138 项只证明离线模拟范围，不等于真实 Docker 回滚、新机安装或生产覆盖恢复已经验收；该历史采购版实际迁移与发布、Linux、浏览器及备份证据另见 [VALIDATION](VALIDATION.md)。失败时仅在提交前且原数据没有后续变化、完整恢复组及源码／镜像相配、`.env` 未漂移的条件下走已审查恢复；任何配置、完整性或恢复核验失败均保持停止。提交后发现新写入或状态不明，保留候选数据和现场，不能盲目恢复旧快照抹掉新数据。恢复相配备份后，先按第 6.2 节使目标家庭旧成员会话失效，再开放服务。

第 5.2 节历史示例不能承担 35→37、37→40、40→42 或 42→43 首次迁移，也不能用于当前 69/9 结构的更新。该历史源码直接初始化 43 张户内表及 2 张平台表，资料、采购、例行和观察新增业务表无预填数据；旧结构按各自已审查迁移处理。旧包 193／200 等数量只作历史。

## 同步状态的零迁移发布

以下为 **2026-09-15 10:43:53 同步状态版的历史零迁移流程**，保留 35 张户内表和 2 张平台注册表，包括已发布的 devices.display_layout。先冻结源码与测试镜像，保留旧镜像、源码及相配配置；停止 web 入口，再停止 sync/app，验证包含所有登记家庭的完整备份组。串行初始化后逐表核对列、schema、所有行和 SQLite 内部序号完全不变，候选 app 启动读回仍一致，才恢复 sync/web。采购实付的新增两表不属于这一历史验证范围。

候选启动前失败只允许使用已逐一验证的完整备份和旧源码恢复；配置漂移时不覆盖。开放写入后若数据已变化，停止服务并保留候选数据库人工核对，不能盲目恢复旧快照。控制器仅在本次明确终态的 preflight 失败、旧服务仍运行且未启动恢复时回退候选标签，不抢占其他恢复。激活／成组恢复 114 项，控制器标签保护 119 项，仅为离线模拟；不替代真实生产或跨机恢复。通用步骤见第 5—6 节。

## 电视显示设置的部署增量

以下为 2026-09-15 09:47:39 的历史升级：保留三服务与配置，tv_display.py 及 tv-display.js/.css 已发布；当时给每户 devices 表追加 display_layout TEXT NOT NULL DEFAULT '{}'。当前版本完整保留该列，不再增加或重建它；旧客户端省略布局仍保留原值。

先保留旧源码、镜像标签、配置和全家庭备份，停止入口与旧 app/sync 后验证备份组，再串行初始化所有已登记家庭。核对旧行、设备旧列和其他 schema 对象保持，候选 app 健康且启动读回后才恢复 sync/web；依据本页第 5—6 节保留相配回退材料。预检失败若只改了候选镜像标签，也要在确认旧服务仍运行后恢复旧标签，不能留下含糊的下一次启动目标。提交后已有新写入时不得自动恢复旧快照覆盖新数据。

字段、默认值和电视隐私边界见 [TV-DISPLAY](TV-DISPLAY.md)；初始化新增列兼容不代表任意旧版本都可直接接管新库。发布验证未执行生产恢复演练。

> 当前运行 Flask/Gunicorn、同步 worker、media worker 与 Nginx 四服务，家庭隔离及完整备份见 [平台扩展](PLATFORM.md)。新版 Python 模块必须与前端一起交付；prepare_release.py 只打包源码。最新发布见文首和 [VALIDATION](VALIDATION.md)，下方旧记录保留历史范围；成员会话与相配数据库恢复约束继续适用。

本文保留 Dockerfile、compose.yaml、deploy 的安装和维护说明；第 5.2 节仅保留已完成消费观察迁移的历史 42 表版本示例，不适用于当前 69/9 表结构，不能代替历史 40→42 首次迁移或更早的升级。源码／步骤核对日期为 2026-09-15；下方服务器快照保留 2026-09-14 历史，不代表之后实时状态。接口／权限见 [README](../README.md)，账号注册见 [ACCOUNT-SYNC](ACCOUNT-SYNC.md)，证据见 [VALIDATION](VALIDATION.md)。

成员会话已于 2026-09-15 07:58:24 发布。迁移新增认证表与 OAuth 上下文字段，完整约束见 [成员登录设备](MEMBER-SESSIONS.md#发布回滚与恢复)。迁移后的 `cloud_oauth_states` 不兼容 7b 旧程序按九列位置插入；不能直接让旧镜像接管新库。恢复相配备份后必须先使本次恢复家庭旧登录失效，再启动 app/web。

**已有服务器更新使用第 5 节；第 3 节只适用于空服务器首次安装。** 不要在已有账本上重新生成 `SECRET_KEY`、覆盖 `.env` 或删除命名卷。本文编写时仅做代码和运行状态核对，未执行新机安装、生产覆盖恢复或灾难恢复演练。

修订前正式基线记录（保留历史）：2026-09-15 10:43:53（北京时间）已发布同步新鲜度与问题中心，保留电视、投资、会话及此前全部模块；镜像 `sha256:6882d2a2009ce4ef378cc2448026f5a7edc4b63fd14e440bc104fcdd6d7e159c`。Windows **981 passed / 12 skipped**，Linux **992 passed / 1 skipped**；两端完整收集 993 项；本轮 3 组浏览器记录：131 项功能检查，另有 59 条页面／视口记录；两类不混算。停止入口和旧写进程后核对 35 张户内表与 2 张平台表，表、列、schema 对象、行及 SQLite 内部序号完全保留；初始化未增加表或列。发布前后完整备份、环境保留、三服务运行与 app 健康已核对；6 个既有来源有发布后成功记录，38 个静态资源匹配，15 个匿名受保护 API 返回 401。公网浏览器、两台实体电视、真实新增云写、私人来源映射和可选模型调用仍单独待验收；没有执行生产恢复或宣称商业化就绪。 完整证据见 [VALIDATION](VALIDATION.md)。

完整来源预览／CAS、旅行时间明细及独立消费观察均已在历史版本发布，当前保留。对应源码为 `finance_source_bridge.py`、`journey_time.py`、`deploy/prepare-finance-source.py` 和 `pytest.ini`；固定 `tzdata==2026.4`，Docker `PYTHONTZPATH=""` 使用该包。第 5.2 节历史零 schema 流程记录了停写、备份、串行初始化和分步启动；当前 69/9 表结构的后续更新不得直接执行该示例；任何新增结构必须使用该版本专门审核的首次迁移流程。

本次公网浏览器验收为 `browser_environment_blocked`：本机 Microsoft Defender SmartScreen 组织策略阻止正式域名页面加载。没有通过公网浏览器 UI 验收，容器内部结果不能替代该项；真实新增 Microsoft / Google 云端写入仍未验收。临时浏览器历史测试保留其原有范围与日期，不提升为生产验收。

<a id="投资整理表候选的部署增量"></a>

## 投资整理表的部署增量

本节增量已于 2026-09-15 08:56:01 发布；相对于 07:58 成员会话版本，不增加服务、依赖或环境变量。保持 Flask/Gunicorn、同步 worker、Nginx 三服务及现有数据卷。新模块 investment_import.py 已加入 Dockerfile 和 deploy/prepare_release.py；static/index.html 按依赖载入投资 JS/CSS。

升级前按本文保留源码、镜像、配置和全家庭完整备份，并校验归档。停止旧 app/sync 写入后，使用候选初始化每个已登记家庭，再验证旧表内容摘要未变、新表结构及 SQLite 完整性，最后启动应用和同步。预期新增 hub_investment_sources、hub_investment_links、hub_investment_import_previews、hub_investment_import_receipts，户内共 35 表；平台仍为 2 表。完整备份包含四表，成员 ZIP 不含预览暂存。

发布检查应包含新静态资源、匿名投资 API 拒绝访问、既有云来源同步和财务记录保留；真实持仓不作为部署测试输入。采用本文的相配源码与数据快照恢复流程，恢复认证失效处理沿用 [成员会话](MEMBER-SESSIONS.md)。接口和 15 分钟预览期限见 [持仓导入](INVESTMENT-IMPORT.md)。

## 1. 当前运行方式

以下表格和运行参数保留 2026-09-14 的环境快照；当前四服务及发布身份以文首和最新验收为准。

| 项目 | 2026-09-14 已核对的部署 |
|---|---|
| SSH 主机别名 | `racknerd`，具体 SSH 用户与密钥由维护者本机配置管理 |
| 服务器 | `96.44.160.28`，Ubuntu 24.04 |
| 主入口 / 电视 | `https://home.caesarcharles.world/`、`https://home.caesarcharles.world/tv` |
| 保留入口 | `https://96.44.160.28/`；外部账号绑定统一使用正式域名 |
| 源码 / Compose 工作目录 | `/opt/family-dashboard` |
| Docker / Compose | Docker 29.1.3；Compose 2.40.3（Ubuntu 包版本另带发行后缀） |
| 应用运行时 | 容器 Python 3.12.14；Nginx 1.30.4 |
| 应用服务 | `family-dashboard-app-1`：Gunicorn，1 个 worker / 4 个线程，内部 8000 端口 |
| 同步服务 | `family-dashboard-sync-1`：同一应用镜像，运行 `sync_worker.py` |
| 入口服务 | `family-dashboard-web-1`：Nginx，对外 80 / 443 |
| 数据卷 | `family-dashboard_household-data`，app 与 sync 共同挂载到 `/data` |
| 数据库 | 既有家庭 `/data/household.sqlite3`；平台扩展新增 `/data/platform.sqlite3` 和 `/data/spaces/<24位随机id>/household.sqlite3`，均在同一数据卷内 |
| 应用配置 | `/opt/family-dashboard/.env`，0600；不会打入镜像或发布源码包 |
| TLS / ACME | `/var/lib/family-dashboard/letsencrypt`、`/var/lib/family-dashboard/acme` |
| 快照状态 | app 健康，sync / web 运行；两个平台已配置且有实际绑定，不需要重新做首次注册 |

前端没有独立 Node 服务或前端构建服务。静态 HTML / CSS / JavaScript 与 Flask API 一起装入应用镜像，Nginx 把请求转发给 app。新版 sync 在每户处理已确认的旅行日历、本地待办发布队列和第三方轮询，不接收公网 HTTP。只发布 80 / 443；8000 不暴露到宿主机。

app / sync 以 UID **10001** 运行，根文件系统只读，`/tmp` 为 tmpfs，配置 `no-new-privileges`。内存限制分别为 app 384 MB、sync 192 MB、web 96 MB；三者 `restart: unless-stopped`。Compose 等 app 的 `/healthz` 成功后才启动依赖服务。`/healthz` 证明应用进程可响应，不证明外部账号、同步覆盖、电视实机或所有数据库业务均正常。

镜像版本与摘要在 `Dockerfile`、`compose.yaml`、`deploy/renew.sh` 中固定。应用默认镜像名为 **`family-dashboard-app`**，sync 明确使用这个名字，因此不要仅修改 Compose 项目名或镜像标签而不同时更新两者。

本项目已建立独立本地 Git 仓库，各 agent 使用独立分支/worktree，审查后合入 main；操作见 [Git 协作指导](GIT-WORKFLOW.md)。源码已托管于私有 [caesarvan/family-dashboard](https://github.com/caesarvan/family-dashboard)；服务器使用经核对的源码与 Expo 产物归档发布，不执行 `git pull` 更新。

## 2. 配置、密钥与数据文件

| 变量 | 用途与要求 |
|---|---|
| `SECRET_KEY` | 必填。首次生成高强度随机值；用于会话签名以及派生第三方令牌加密密钥。现有数据库恢复必须配套原值。 |
| `MEMBER1_PASSWORD` / `MEMBER2_PASSWORD` | 空数据库首次创建 `member1` / `member2` 时使用，各至少 12 个字符。已有用户只使用数据库内的 scrypt 散列；改 `.env` 不会重置密码。 |
| `PUBLIC_ORIGIN` | 当前为 `https://home.caesarcharles.world`，不得附加回调路径或结尾斜杠；服务商回调 URI 必须一致。 |
| `MICROSOFT_CLIENT_ID` / `MICROSOFT_CLIENT_SECRET` | Microsoft 网页应用凭据；缺少时该平台显示等待配置。secret 使用 Value，不是 Secret ID。 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google 网页应用凭据；缺少时该平台显示等待配置。 |
| `DATA_DIR` | 本地默认源码目录下 `data/`；Compose 显式设置为 `/data`。 |
| `COOKIE_SECURE` | 默认 `1`，HTTPS 会话；仅本地回环地址的 HTTP 调试可设 `0`。Compose 强制为 `1`。 |
| `TRUST_PROXY` | 只有值为 `1` 才启用单层 `ProxyFix`；仅应在当前受控 Nginx 代理后启用。Compose 的 app 设置为 `1`。 |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | 可选；两者均设置才启用家庭助理模型模式。成员仍须逐次选择使用模型及是否附带允许的家庭上下文；未设置时使用本地助理能力。 |

**Python 应用不会自动读取 `.env`**，没有 `python-dotenv` 加载器。Docker Compose 通过 `env_file: .env` 注入配置；直接运行 Python 时，必须先设置进程环境或通过 `create_app(config)` 传入。Flask CLI 在环境额外安装了 `python-dotenv` 时可能自行加载 `.env`，所以下面的本地命令明确设置 `FLASK_SKIP_DOTENV=1`。不要为了方便调试把生产 `.env` 复制到测试目录。

本地打包脚本 `python deploy/prepare_release.py` **只生成源码归档和逐文件 SHA-256 清单，不生成、读取或修改 `.env` 和登录密码**。若私人目录中仍有旧 `登录信息.md`，它只是历史初始安装记录，不能作为现有用户的有效密码或自动重置依据。首次密钥创建只在第 3.1 节对空服务器排他创建配置时进行。

本地 HTTP 调试如使用 PowerShell，可在当前进程中生成仅供测试的新随机密钥和密码，赋值不会把凭据打印到终端：

```powershell
# 在已创建 .venv 并装好依赖的项目目录执行；不要连接生产 DATA_DIR。
$py = (Resolve-Path .\.venv\Scripts\python.exe).Path
$env:SECRET_KEY = (& $py -c 'import secrets; print(secrets.token_hex(48))')
$env:MEMBER1_PASSWORD = (& $py -c 'import secrets; print(secrets.token_urlsafe(24))')
$env:MEMBER2_PASSWORD = (& $py -c 'import secrets; print(secrets.token_urlsafe(24))')
$env:COOKIE_SECURE = '0'
$env:TRUST_PROXY = '0'
$env:FLASK_SKIP_DOTENV = '1'
$env:PUBLIC_ORIGIN = 'https://home.caesarcharles.world'
$env:DATA_DIR = Join-Path $env:TEMP ('family-dashboard-dev-' + [guid]::NewGuid().ToString('N'))
& $py -m flask --app 'app:create_app()' run --host 127.0.0.1 --port 8765
```

上述随机密码可由同一 PowerShell 进程内的测试脚本读取，不是固定测试密码；浏览器测试若有自己的夹具密码，应按相应测试脚本的启动方式运行。`PUBLIC_ORIGIN` 必须保持有效 HTTPS 源站值，不能设成任意本地 HTTP 端口；此回环开发服务只验证本地页面/API，不完成真实 OAuth。隔离授权测试通过 `create_app` 的测试配置和模拟提供商运行。关闭进程后这些随机配置不会保存；需要长期本地账本时，自行保管独立开发配置并在后续启动复用。开发服务只绑定回环地址，不能用作公网服务。

多家庭运行需保留整棵 `/data`：平台注册目录保存家庭 id/slug 和一次性邀请哈希；每户文件夹保存该户 SQLite、锁及备份。子家庭会话和 OAuth 加密密钥从主 `SECRET_KEY` 与家庭 id 派生。只恢复一个家庭数据库到错误的 id 目录，或丢失主密钥，都会破坏隔离映射和凭证解密。不要靠创建空库或使用主家庭初始密码补建缺失家庭。

生产密钥仅在受控 SSH 终端中输入或用本地私人文件保存。不要把 `cat .env`、完整 `docker inspect`、`docker compose config`、原始数据库、财务 payload、OAuth 回调查询参数贴入文档或日志。需要查看容器元数据时只查询具体非敏感字段。

## 3. 空服务器首次安装

以下 Linux 命令在管理员的 root shell 中执行；已部署 racknerd **跳过整节**。先安装 Docker Engine 与 Compose v2、Python 3、curl、DNS 查询工具，并确保 Docker 开机启动。新系统安装方法以 [Docker Ubuntu 官方安装文档](https://docs.docker.com/engine/install/ubuntu/) 为准；已有 Docker 的服务器不要直接卸载或替换其软件包。

将正式域名 A 记录指向服务器 IP，确保公网能够到达 TCP 80 / 443，并保留管理员 SSH 入口。若存在 AAAA 记录，必须同时有可用 IPv6 入口；无 IPv6 服务时不要留下错误 AAAA。Docker 发布端口与宿主机防火墙有独立规则，应同时核对云平台/机房入口和 Docker 规则。[Docker 网络与防火墙说明](https://docs.docker.com/engine/install/ubuntu/#firewall-limitations)

### 3.1 准备源码与首次配置

本机先核对源码、测试，再打包；归档默认位置为 `Documents/Codex/family-dashboard-access/release.tar.gz`。上传时只传归档，不传整个私人访问目录。

```powershell
# 本机 Windows，当前目录为 family-dashboard。
python deploy/prepare_release.py
$releaseArchive = Join-Path $env:USERPROFILE 'Documents\Codex\family-dashboard-access\release.tar.gz'
scp $releaseArchive racknerd:/tmp/family-dashboard-release.tar.gz
```

服务器安装到既定路径。归档应是自己刚生成并核对的版本；首次安装要求目标目录没有旧账本与配置。

```sh
set -eu
install -d -m 0755 /opt/family-dashboard
install -d -m 0700 /var/lib/family-dashboard/letsencrypt
install -d -m 0755 /var/lib/family-dashboard/acme
cd /opt/family-dashboard
test ! -e .env
tar -xzf /tmp/family-dashboard-release.tar.gz -C /opt/family-dashboard
chmod 0755 deploy/*.sh
```

创建新 `.env`。下面以排他创建模式写文件，已有 `.env` 会失败；文件 0600，终端只提示创建成功。随机密码保存在这份私人配置中，由管理员使用私人编辑器或密码管理器取出，分别交给本人，不进入共享工单、电视或源码。

```sh
umask 077
python3 - <<'PY'
import os
import secrets

values = {
    'SECRET_KEY': secrets.token_hex(48),
    'MEMBER1_PASSWORD': secrets.token_urlsafe(24),
    'MEMBER2_PASSWORD': secrets.token_urlsafe(24),
    'PUBLIC_ORIGIN': 'https://home.caesarcharles.world',
}
fd = os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w', encoding='utf-8') as stream:
    stream.write(''.join(f'{key}={value}\n' for key, value in values.items()))
print('Private configuration created; no credentials printed.')
PY
```

### 3.2 先启动 app / sync，初始化卷权限

```sh
cd /opt/family-dashboard
docker compose build app
# 只修正首次空卷的根目录，不对已有账本递归 chown。
docker compose run --rm --no-deps --user 0:0 app python -c "import os; os.chown('/data', 10001, 10001); os.chmod('/data', 0o700)"
docker compose up -d --wait --wait-timeout 180 app sync
docker compose ps
```

当前完整源码结构为 69 张户内表及 9 张平台表，见[最新发布验收](ASSISTANT-TRIP-ITEMS-ACCEPTANCE.md#assistant-trip-items-release)。下方命令保留历史安装说明，首次空服务器的完整流程仍需单独验收，不能以已有生产的一户两库升级证据替代。未来启动只做幂等建表／兼容列迁移，不会重置已有密码或导入演示数据。UID 10001 必须能在 `/data` 创建数据库、WAL、备份及 `cloud-locks/`。暂不启动 Compose 的 web：正式 `nginx.conf` 同时引用 IP 与域名两套证书，缺任何一套都会启动失败。

### 3.3 用独立 HTTP 入口完成 ACME，随后启动正式 HTTPS

仓库的 `deploy/nginx-bootstrap.conf` 只开放 ACME 路径，其他请求返回 503；它不依赖 app 或任何证书。先用独立临时 Nginx 占用 80，正式 web 此时保持停止。

```sh
docker run -d --name family-dashboard-bootstrap --restart unless-stopped \
  -p 80:80 \
  -v /opt/family-dashboard/deploy/nginx-bootstrap.conf:/etc/nginx/conf.d/default.conf:ro \
  -v /var/lib/family-dashboard/acme:/var/www/acme:ro \
  nginx:stable-alpine@sha256:dc5069ad14f19660b141b21236140b91656bf89bbc3e2417c70ae650cd66104c
```

当前配置同时保留 IP 入口，因此**先后申请两张证书**。以下 Certbot 参数接受 CA 服务条款、暂不登记邮箱，与现有脚本一致；运维依赖 systemd 与主动检查，不能依赖邮件提醒。Certbot webroot 模式要求外网 HTTP 能访问挑战文件。[Certbot webroot 说明](https://eff-certbot.readthedocs.io/en/stable/using.html#webroot)

```sh
certbot_image='certbot/certbot@sha256:f70ad0adbb7e117f0fe42a63c553f28ea451edabc0148757b6efcd9735acaa20'
docker run --rm \
  -v /var/lib/family-dashboard/letsencrypt:/etc/letsencrypt \
  -v /var/lib/family-dashboard/acme:/var/www/acme \
  "$certbot_image" certonly --non-interactive --agree-tos --register-unsafely-without-email \
  --webroot --webroot-path /var/www/acme --preferred-profile shortlived \
  --ip-address 96.44.160.28 --cert-name family-dashboard
docker run --rm \
  -v /var/lib/family-dashboard/letsencrypt:/etc/letsencrypt \
  -v /var/lib/family-dashboard/acme:/var/www/acme \
  "$certbot_image" certonly --non-interactive --agree-tos --register-unsafely-without-email \
  --webroot --webroot-path /var/www/acme \
  -d home.caesarcharles.world --cert-name family-dashboard-domain
```

两次均成功后，校验正式候选配置，再关闭临时入口并创建正式 web。`compose run` 默认不发布 service 的端口，因此校验不会与 bootstrap 抢 80。

```sh
cd /opt/family-dashboard
docker compose run --rm --no-deps web nginx -t
docker stop family-dashboard-bootstrap
docker rm family-dashboard-bootstrap
docker compose up -d web
curl --fail --silent --show-error --retry 5 --retry-all-errors --retry-delay 2 \
  https://home.caesarcharles.world/healthz
curl --fail --silent --show-error https://96.44.160.28/healthz
```

签发失败时保留 bootstrap，修复 DNS、80 端口或 ACME 报错再申请；不要启动缺证书的正式入口，也不要关闭 TLS 校验来宣布成功。

### 3.4 安装定时任务、配置第三方账号与首次验收

```sh
cd /opt/family-dashboard
install -m 0644 deploy/family-dashboard-backup.service /etc/systemd/system/
install -m 0644 deploy/family-dashboard-backup.timer /etc/systemd/system/
install -m 0644 deploy/family-dashboard-renew.service /etc/systemd/system/
install -m 0644 deploy/family-dashboard-renew.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now family-dashboard-backup.timer family-dashboard-renew.timer
./deploy/backup.sh
systemctl list-timers 'family-dashboard-*'
```

管理员按 [ACCOUNT-SYNC.md](ACCOUNT-SYNC.md) 注册 Microsoft / Google 网页应用，在真实交互 SSH 终端使用配置助手输入 secret，避免放进命令参数：

```sh
cd /opt/family-dashboard
python3 deploy/configure-oauth.py --provider microsoft
python3 deploy/configure-oauth.py --provider google
python3 deploy/configure-oauth.py --check
docker compose up -d --force-recreate --wait --wait-timeout 180 app sync
docker compose up -d --no-deps --force-recreate web
```

`--check` 仅报告变量是否填写，不证明应用配置正确或成员授权已完成。新服务器还需两位成员各自登录、改初始密码、绑定账号及选择来源；两台电视分别配对。云日历读取、To Do 新建及完成/恢复、跨令牌刷新验收按账号文档执行；旅行日历写入需按 [CALENDAR-PUBLISH](CALENDAR-PUBLISH.md) 单独升级权限和验收。删除本地旅行不会自动删除云日历，不应把本地删除测试当作云端删除已实现。

## 4. 域名、证书与定时任务

正式配置的证书名称为 `family-dashboard-domain`，IP 证书名称为 `family-dashboard`。首张域名证书到期日记录为 2026-12-13；维护时以当前证书实际有效期为准。

`deploy/renew.sh` 在 Certbot 中运行 `renew --quiet`，随后检查 Nginx 并 reload。续期 timer 按**宿主机时区**在每日 00、06、12、18 点的第 10 分钟触发，附加最多 15 分钟随机延迟，`Persistent=true`。备份 timer 则明确使用 **UTC 20:20**，对应次日北京时间 04:20；不要把两个 timer 的时区规则混为一谈。

```sh
systemctl status family-dashboard-renew.timer family-dashboard-backup.timer --no-pager
systemctl list-timers 'family-dashboard-*'
journalctl -u family-dashboard-renew.service -n 30 --no-pager
journalctl -u family-dashboard-backup.service -n 30 --no-pager
docker run --rm \
  -v /var/lib/family-dashboard/letsencrypt:/etc/letsencrypt \
  -v /var/lib/family-dashboard/acme:/var/www/acme \
  certbot/certbot@sha256:f70ad0adbb7e117f0fe42a63c553f28ea451edabc0148757b6efcd9735acaa20 \
  renew --dry-run --no-random-sleep-on-renew
```

80 端口及 ACME 路径必须持续开放。已有模拟续期成功记录，但没有外部故障通知服务，timer 启用也不能保证未来每次都能成功。

`deploy/activate-domain.sh` 是**本家庭当前域名的迁移脚本**：包含 `.world` 父区、Name.com 权威服务器、域名和 IP 的固定检查，并依赖已能访问的 ACME HTTP 入口。它不是任意新主机的一键安装器。`configure-oauth.py` 同样把 `PUBLIC_ORIGIN` 限定为当前域名。迁到其他域名/服务器时，应一并修改这两个脚本、两份正式 Nginx 配置、bootstrap、OAuth 注册回调与文档，再验证。域名变更后的浏览器会话和电视 Cookie 属于不同站点，成员需重新登录，电视重新配对。

## 5. 已有服务器发布更新

发布前运行与改动相关的后端、JavaScript 及浏览器检查，参见 [VALIDATION.md](VALIDATION.md)。不要直接执行写死旧初始密码、未配置 OAuth 假设或生产写入的历史测试脚本。新版本业务逻辑、权限和数据库兼容性必须由测试证明；仅 healthz 200 不足以验收。

2026-09-15 06:50:21 历史批次同时发布 `financial_files.py`、`finance_hub.py`、财务 JS/CSS、`home_assistant.py`、助理 JS/CSS 与 `journey-ui.js`；保留既有静态示例。新路由由原助理模块注册，不新增依赖、环境变量或业务表。按既有停写、即时备份、串行初始化、app 健康后 web/sync 启动顺序执行；本轮镜像通过完整 Linux 回归，不能以旧 706 同源复用代替。

### 5.1 准备并检查源码归档

`prepare_release.py` 使用文件白名单，包含当前 Python 模块、Docker/Compose、pytest.ini、static、deploy、docs、tests、README、AGENTS 和 `.cursor/rules/git-collaboration.mdc`。当前 Python 运行模块在 Dockerfile 中有明确 COPY，来源准备 CLI 随 deploy 目录交接。不包含 `.git`、根 `.env`、数据库、`data/`、`.venv/`、`test-results/` 或私人访问目录。它将 `deploy/*.sh` 的归档权限设为 0755，生成 `RELEASE-MANIFEST.json`，并在源码发生并行修改时拒绝替换旧归档。

发布候选必须来自已按 [Git 流程](GIT-WORKFLOW.md) 审查并合入 main 的明确提交，在独立干净发布工作树中构建；记录 commit、归档 SHA、镜像 ID、测试与迁移类型。Git 合并不会更新正在运行的容器。各 agent 在自己的 worktree 开发，不直接改服务器目录；纯静态与既有 Python／静态更新分别按 [STATIC-RELEASE](STATIC-RELEASE.md) 和 [SOURCE-RELEASE](SOURCE-RELEASE.md) 的受审范围执行。旅行资料历史版已完成独立 42→43，当前 69/9 表结构不能执行本节历史 42→42 算法。

历史基线说明：16:25 为 218 文件，17:35 实际源树为 222，后续 225 文件文档交接未改运行镜像；20:23 安装 237 文件，22:32 静态发布安装 248 文件。2026-09-16 11:39:20 SOURCE 发布已安装 255 文件及 manifest `169c9621…`，旧源码和旧清单原样保留；本次文档修订不自动同步服务器。任何后续更新都须核对真实源树，不能覆盖清单制造一致。历史静态发布曾因两份未列入清单的旧 Nginx 备份而预检拒绝、未停服务，保留归档后才重试，见 [VALIDATION](VALIDATION.md)。

**这不是内容脱敏器。** 不得把真实财务 JSON、CSV、凭据或私人截图临时放入被整目录收录的 docs / tests / static / deploy。财务导入必须单独走第 7 节，不能加入发布包。Windows 本机至少检查归档路径和散列后再上传：

```powershell
python deploy/prepare_release.py
$releaseArchive = Join-Path $env:USERPROFILE 'Documents\Codex\family-dashboard-access\release.tar.gz'
tar -tzf $releaseArchive
Get-FileHash -Algorithm SHA256 -LiteralPath $releaseArchive
scp $releaseArchive racknerd:/tmp/family-dashboard-release.tar.gz
```

### 5.2 备份、保留回滚材料，再替换源码

> **历史代码限定：以下保留的是 42→42 更新程序及当时的验证条件，所有代码块原字节不变。当前为 69/9 表结构，不可执行这些更新命令。[STATIC-RELEASE](STATIC-RELEASE.md) 和 [SOURCE-RELEASE](SOURCE-RELEASE.md) 也仅适用于其各自固定历史基线；配置、依赖或结构变化仍需另审，一次性 42→43 工具也不能重复使用。**

以下在同一个 root shell 中按顺序执行，只适用于**已有 42 张户内表／2 张平台表，devices.display_layout、采购两表、例行三表和消费观察两表均存在的后续 42→42 零 schema 更新**。所有业务表可以有历史数据，所有原值必须保留；**不适用于 35→37、37→40、40→42 或任何表／列／索引增删改**。先比较归档 SHA-256 与已验收候选，冻结源码、不可变镜像及配置，禁止并行发布／导入。新迁移必须另行审查，不能修改数字、删除或放宽下方相等断言来强行通过。

构建及隔离测试期间旧服务继续运行。维护窗口先停止 web 入口，再停止 sync/app；保存停止后快照并验证备份完整组，才串行初始化。新 app 健康且再次读取全部数据库与停止后快照完全相等，才到达开放 sync/web 的提交边界。下方检查脚本只由文档 heredoc 创建在私有 release_dir，不需要复制 test-results 内部发布助手，也不加入源码归档。

隔离测试须将同一冻结源码中的 `tests`、`deploy` 与 `pytest.ini` 一并只读挂载到 `/app`；部分测试夹具会读取 `/app/pytest.ini`，仅挂载测试目录会在初始化阶段失败。测试容器仍不加载生产 `.env` 或数据卷。

`stop --timeout 45` 是 Docker 停止宽限期，不保证在途同步完成；超时可能升级 SIGKILL。下面记录容器 ID、退出码与 OOMKilled，137 或 OOM 必须先排障，不能称为平稳退出。所有后续核对失败都会终止命令，不自动恢复旧镜像或覆盖数据。

```sh
set -eu
umask 077
cd /opt/family-dashboard
sha256sum /tmp/family-dashboard-release.tar.gz
release_stamp=$(date -u +%Y%m%dT%H%M%SZ)
release_dir="/opt/family-dashboard-releases/$release_stamp"
test ! -e "$release_dir"
test ! -L "$release_dir"
install -d -m 0700 "$release_dir"
# 使用已校验候选包的新版备份脚本，避免旧服务器脚本只备份主家庭。
tar -xOf /tmp/family-dashboard-release.tar.gz deploy/backup.py > "$release_dir/backup.py"
chmod 0600 "$release_dir/backup.py"
docker compose exec -T app python < "$release_dir/backup.py" > "$release_dir/online-backup.json"
cat "$release_dir/online-backup.json"
install -m 0600 .env "$release_dir/.env"
tar -czf "$release_dir/source.tar.gz" \
  --exclude='./.env*' --exclude='./data' --exclude='./.venv' \
  --exclude='./.git' --exclude='./test-results' --exclude='./__pycache__' .
chmod 0600 "$release_dir/source.tar.gz"
previous_image=$(docker inspect --format '{{.Image}}' "$(docker compose ps -q app)")
docker image tag "$previous_image" "family-dashboard-app:rollback-$release_stamp"
env_digest=$(sha256sum .env | cut -d ' ' -f 1)
tar -xzf /tmp/family-dashboard-release.tar.gz -C /opt/family-dashboard
test "$env_digest" = "$(sha256sum .env | cut -d ' ' -f 1)"
chmod 0755 deploy/*.sh
docker compose build app
candidate_image=$(docker image inspect --format '{{.Id}}' family-dashboard-app)
# 候选镜像在隔离容器内运行测试：不注入生产 .env，也不挂载数据卷。
# 全量 pytest 的 /tmp 使用本次 release_dir 内独立磁盘目录，旧 192MiB tmpfs 会耗尽。
# 生产 compose 的 tmpfs 不变；本目录仅供隔离测试，保留排障，不递归清理。
test "${release_dir#/}" != "$release_dir"
test -d "$release_dir"
test ! -L "$release_dir"
test "$(readlink -f -- "$release_dir")" = "$release_dir"
test_tmp="$release_dir/test-tmp"
test ! -e "$test_tmp"
test ! -L "$test_tmp"
test "$(df -B1 --output=avail "$release_dir" | tail -n 1 | tr -d ' ')" -gt 2147483648
install -d -m 0700 "$test_tmp"
chown 10001:10001 "$test_tmp"
test "$(readlink -f -- "$test_tmp")" = "$test_tmp"
docker run --rm --read-only --memory=384m \
  --mount "type=bind,source=$test_tmp,target=/tmp" \
  -v /opt/family-dashboard/tests:/app/tests:ro \
  -v /opt/family-dashboard/deploy:/app/deploy:ro \
  -v /opt/family-dashboard/pytest.ini:/app/pytest.ini:ro \
  --entrypoint sh "$candidate_image" \
  -c 'pip install -q --no-cache-dir --target /tmp/test-deps pytest==9.1.1 && PYTHONPATH=/app:/tmp/test-deps python -m pytest -q -p no:cacheprovider /app/tests'
docker compose run --rm --no-deps web nginx -t
test "$candidate_image" = "$(docker image inspect --format '{{.Id}}' family-dashboard-app)"
# 私有校验目录只挂载到一次性容器；沿用应用 UID，避免 root 初始化数据卷。
verification_dir="$release_dir/verification-inputs"
install -d -m 0700 -o 10001 -g 10001 "$verification_dir"
cat > "$verification_dir/zero-schema-check.py" <<'PY'
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import sys
from contextlib import closing

# Only aggregate digests and schema metadata leave this process; never raw rows.
root = Path(os.environ['DATA_DIR']).resolve(strict=True)
inputs = Path('/release-check')
shopping_tables = {'hub_shopping_settlements', 'hub_shopping_settlement_receipts'}
# Frozen 42-table baseline; never execute this DDL against the household databases.
shopping_schema_sql = "\n        CREATE TABLE IF NOT EXISTS hub_shopping_settlements(\n            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),\n            payment_id TEXT NOT NULL, shopping_id TEXT NOT NULL,\n            amount_cents INTEGER NOT NULL CHECK(amount_cents BETWEEN 0 AND 100000000000),\n            status TEXT NOT NULL CHECK(status IN ('active','revoked')),\n            revision INTEGER NOT NULL DEFAULT 1,\n            before_values TEXT NOT NULL, projected_values TEXT NOT NULL,\n            applied_shopping_revision INTEGER NOT NULL,\n            source_snapshot TEXT NOT NULL, source_digest TEXT NOT NULL,\n            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);\n        CREATE UNIQUE INDEX IF NOT EXISTS hub_shopping_settlements_active\n            ON hub_shopping_settlements(owner,shopping_id) WHERE status='active';\n        CREATE INDEX IF NOT EXISTS hub_shopping_settlements_payment\n            ON hub_shopping_settlements(owner,payment_id,status);\n        CREATE TABLE IF NOT EXISTS hub_shopping_settlement_receipts(\n            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), nonce_digest TEXT NOT NULL,\n            operation TEXT NOT NULL, link_id TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL,\n            UNIQUE(owner,nonce_digest));\n        "

routine_tables = {'household_routines', 'routine_occurrences', 'routine_receipts'}
routine_schema_sql = "\n        CREATE TABLE IF NOT EXISTS household_routines(\n            id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('tasks','shopping')),\n            template TEXT NOT NULL, schedule TEXT NOT NULL,\n            state TEXT NOT NULL CHECK(state IN ('active','paused','archived')),\n            revision INTEGER NOT NULL DEFAULT 1, current_index INTEGER NOT NULL DEFAULT 0,\n            created_by TEXT NOT NULL REFERENCES users(id),\n            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);\n        CREATE INDEX IF NOT EXISTS household_routines_state ON household_routines(state,id);\n        CREATE TABLE IF NOT EXISTS routine_occurrences(\n            plan_id TEXT NOT NULL REFERENCES household_routines(id),\n            occurrence_index INTEGER NOT NULL CHECK(occurrence_index>0), entity_id TEXT NOT NULL UNIQUE,\n            scheduled_on TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('current','completed','skipped')),\n            created_at TEXT NOT NULL, closed_at TEXT,\n            PRIMARY KEY(plan_id,occurrence_index));\n        CREATE UNIQUE INDEX IF NOT EXISTS routine_occurrences_current\n            ON routine_occurrences(plan_id) WHERE state='current';\n        CREATE TABLE IF NOT EXISTS routine_receipts(\n            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), nonce_digest TEXT NOT NULL,\n            operation TEXT NOT NULL, plan_id TEXT NOT NULL REFERENCES household_routines(id),\n            result TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(owner,nonce_digest));\n        "

spending_tables = {'finance_spending_observations', 'finance_spending_receipts'}
spending_schema_sql = '\nCREATE TABLE IF NOT EXISTS finance_spending_observations(\n    owner TEXT PRIMARY KEY REFERENCES users(id), revision INTEGER NOT NULL,\n    source_digest TEXT NOT NULL, candidate_digest TEXT NOT NULL,\n    candidate_json TEXT NOT NULL, accepted_at TEXT NOT NULL);\nCREATE TABLE IF NOT EXISTS finance_spending_receipts(\n    id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),\n    candidate_digest TEXT NOT NULL, source_digest TEXT NOT NULL,\n    expected_revision INTEGER NOT NULL, expected_baseline_revision INTEGER NOT NULL,\n    observation_revision INTEGER NOT NULL, status TEXT NOT NULL,\n    accepted_at TEXT NOT NULL);\nCREATE INDEX IF NOT EXISTS finance_spending_receipts_owner\n    ON finance_spending_receipts(owner,accepted_at);\n'

def expected_shopping():
    with closing(sqlite3.connect(':memory:')) as reference:
        reference.executescript(shopping_schema_sql)
        objects = reference.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        columns = {name: [list(row) for row in reference.execute('PRAGMA table_xinfo("' + name + '")')]
                   for name in shopping_tables}
    return row_sha(objects), columns

def expected_routines():
    with closing(sqlite3.connect(':memory:')) as reference:
        reference.executescript(routine_schema_sql)
        objects = reference.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        columns = {name: [list(row) for row in reference.execute('PRAGMA table_xinfo("' + name + '")')]
                   for name in routine_tables}
    return row_sha(objects), columns

def expected_spending():
    with closing(sqlite3.connect(':memory:')) as reference:
        reference.executescript(spending_schema_sql)
        objects = reference.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        columns = {name: [list(row) for row in reference.execute('PRAGMA table_xinfo("' + name + '")')]
                   for name in spending_tables}
    return row_sha(objects), columns

def safe(relative):
    parts = PurePosixPath(relative)
    assert not parts.is_absolute() and '..' not in parts.parts and '\\' not in relative
    path = root
    for part in parts.parts:
        path = path / part
        assert not path.is_symlink(), 'Symlink in database or backup path'
    assert path.resolve(strict=True).is_relative_to(root) and path.is_file()
    assert path.stat().st_size > 0, 'Missing or empty database/manifest'
    return path

def file_sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def row_sha(rows):
    def binary(value):
        assert isinstance(value, bytes)
        return {'binarySha256': hashlib.sha256(value).hexdigest()}
    encoded = sorted(json.dumps(row, ensure_ascii=False, separators=(',', ':'),
                                default=binary) for row in rows)
    return hashlib.sha256(json.dumps(encoded, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()

def fingerprint(relative):
    path = safe(relative)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as con:
        con.execute('BEGIN')
        assert con.execute('PRAGMA quick_check').fetchall() == [('ok',)]
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
        objects = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        tables, internal = {}, {}
        for kind, name, table, sql in objects:
            if kind != 'table':
                continue
            quoted = '"' + name.replace('"', '""') + '"'
            columns = [list(row) for row in con.execute('PRAGMA table_xinfo(' + quoted + ')')]
            rows = con.execute('SELECT * FROM ' + quoted).fetchall()
            item = {'count': len(rows), 'rowsSha256': row_sha(rows), 'columns': columns}
            (internal if name.startswith('sqlite_') else tables)[name] = item
        return {'schemaSha256': row_sha(objects), 'tables': tables, 'internalTables': internal,
                'shoppingSchemaSha256': row_sha([item for item in objects if item[2] in shopping_tables]),
                'routineSchemaSha256': row_sha([item for item in objects if item[2] in routine_tables]),
                'spendingSchemaSha256': row_sha([item for item in objects if item[2] in spending_tables])}

def relative_database(uid):
    return 'household.sqlite3' if uid == 'default' else 'spaces/' + uid + '/household.sqlite3'

def snapshot():
    registry = fingerprint('platform.sqlite3')
    assert set(registry['tables']) == {'households', 'household_invitations'}
    with closing(sqlite3.connect(safe('platform.sqlite3').as_uri() + '?mode=ro', uri=True)) as con:
        ids = sorted(row[0] for row in con.execute('SELECT id FROM households'))
    assert ids and 'default' in ids and len(ids) == len(set(ids)), 'Missing original household'
    assert all(uid == 'default' or re.fullmatch('[0-9a-f]{24}', uid) for uid in ids)
    households = {uid: fingerprint(relative_database(uid)) for uid in ids}
    expected_schema, expected_columns = expected_shopping()
    expected_routine_schema, expected_routine_columns = expected_routines()
    expected_spending_schema, expected_spending_columns = expected_spending()
    for value in households.values():
        assert len(value['tables']) == 42, 'Expected completed 42-table baseline; migration needs separate review'
        assert {'devices'} | shopping_tables | routine_tables | spending_tables <= set(value['tables']), 'Missing required established tables'
        assert 'display_layout' in [column[1] for column in value['tables']['devices']['columns']]
        assert value['shoppingSchemaSha256'] == expected_schema, 'Unexpected established shopping schema or indexes'
        assert all(value['tables'][name]['columns'] == expected_columns[name] for name in shopping_tables), 'Unexpected shopping columns'
        assert value['routineSchemaSha256'] == expected_routine_schema, 'Unexpected established routine schema or indexes'
        assert all(value['tables'][name]['columns'] == expected_routine_columns[name] for name in routine_tables), 'Unexpected routine columns'
        assert value['spendingSchemaSha256'] == expected_spending_schema, 'Unexpected established spending schema or indexes'
        assert all(value['tables'][name]['columns'] == expected_spending_columns[name] for name in spending_tables), 'Unexpected spending columns'
        # Preserve all existing shopping/routine/spending rows, including nonempty history. Never require empty tables here.
    return {'registry': registry, 'households': households}

def validate_backup(before):
    info = json.loads((inputs / 'backup.json').read_text())
    name = info['manifest']
    assert isinstance(name, str) and re.fullmatch(r'manifest-[0-9TZ]+\.json', name)
    manifest_path = safe('backups/' + name)
    manifest = json.loads(manifest_path.read_text())
    expected = {'platform.sqlite3': before['registry']}
    expected.update({relative_database(uid): value for uid, value in before['households'].items()})
    found = set()
    for item in manifest['snapshots']:
        relative = item['path']
        parts = PurePosixPath(relative).parts
        if len(parts) == 2 and parts[0] == 'backups' and re.fullmatch(r'platform-[0-9TZ]+\.sqlite3', parts[1]):
            target = 'platform.sqlite3'
        elif len(parts) == 2 and parts[0] == 'backups' and re.fullmatch(r'household-[0-9TZ]+\.sqlite3', parts[1]):
            target = 'household.sqlite3'
        elif len(parts) == 4 and parts[0] == 'spaces' and re.fullmatch('[0-9a-f]{24}', parts[1]) and parts[2] == 'backups' and re.fullmatch(r'household-[0-9TZ]+\.sqlite3', parts[3]):
            target = relative_database(parts[1])
        else:
            raise AssertionError('Unexpected backup mapping')
        assert target in expected and target not in found, 'Unknown or duplicate backup target'
        path = safe(relative)
        assert path.stat().st_size == item['bytes'] and file_sha(path) == item['sha256'], 'Backup checksum mismatch'
        assert fingerprint(relative) == expected[target], 'Backup differs from stopped-writer snapshot'
        found.add(target)
    assert found == set(expected) and info['databases'] == len(expected), 'Incomplete backup group'
    return {'databases': len(found), 'manifestSha256': file_sha(manifest_path), 'groupVerified': True}

action = sys.argv[1]
if action == 'snapshot':
    result = snapshot()
else:
    before = json.loads((inputs / 'before.json').read_text())
    assert snapshot() == before, 'Database schema, rows, sequence or registered household set changed'
    if action == 'validate-backup':
        result = validate_backup(before)
    elif action == 'warm':
        # This is the only action that initializes application code. No worker/tick.
        from app import create_app
        application = create_app()
        platform = application.extensions['household_platform']
        households = platform.households()
        assert sorted(value['id'] for value in households) == sorted(before['households'])
        for household in households:
            platform.child(household)
        assert snapshot() == before, 'Zero-schema-change initialization altered stored data'
        result = {'households': len(households), 'schemaUnchanged': True,
                  'allDatabaseContentsUnchanged': True, 'cloudTicks': 0}
    elif action == 'check':
        result = {'households': len(before['households']), 'schemaUnchanged': True,
                  'allDatabaseContentsUnchanged': True}
    else:
        raise AssertionError('Unknown verification action')
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
PY
chown 10001:10001 "$verification_dir/zero-schema-check.py"
chmod 0400 "$verification_dir/zero-schema-check.py"
# 先记录旧容器，再关闭入口和所有写进程。
old_web_id=$(docker compose ps -q web)
old_app_id=$(docker compose ps -q app)
old_sync_id=$(docker compose ps -q sync)
test -n "$old_web_id"
test -n "$old_app_id"
test -n "$old_sync_id"
printf '%s\n' "$old_web_id" "$old_sync_id" "$old_app_id" > "$release_dir/old-container-ids.txt"
docker compose stop --timeout 45 web
test "$(docker inspect --format '{{.State.Running}}' "$old_web_id")" = false
docker compose stop --timeout 45 sync app
for old_id in "$old_web_id" "$old_sync_id" "$old_app_id"; do
  docker inspect --format '{{.Id}} {{.State.Running}} {{.State.ExitCode}} {{.State.OOMKilled}} {{.State.FinishedAt}}' "$old_id" >> "$release_dir/old-stops.txt"
  test "$(docker inspect --format '{{.State.Running}}' "$old_id")" = false
  test "$(docker inspect --format '{{.State.OOMKilled}}' "$old_id")" = false
  test "$(docker inspect --format '{{.State.ExitCode}}' "$old_id")" != 137
done
# 不允许手工容器、另一个 worker 或维护进程仍占用此数据卷。
test -z "$(docker ps -q --filter volume=family-dashboard_household-data)"
test "$env_digest" = "$(sha256sum .env | cut -d ' ' -f 1)"
test "$candidate_image" = "$(docker image inspect --format '{{.Id}}' family-dashboard-app)"
docker compose run --rm --no-deps -T -v "$verification_dir:/release-check:ro" app \
  python - snapshot < "$verification_dir/zero-schema-check.py" > "$release_dir/before.json"
install -m 0400 -o 10001 -g 10001 "$release_dir/before.json" "$verification_dir/before.json"
# 只运行标准库 SQLite backup，不初始化 app，不启动 worker。
docker compose run --rm --no-deps -T app python < deploy/backup.py > "$release_dir/pre-migration-backup.json"
install -m 0400 -o 10001 -g 10001 "$release_dir/pre-migration-backup.json" "$verification_dir/backup.json"
docker compose run --rm --no-deps -T -v "$verification_dir:/release-check:ro" app \
  python - validate-backup < "$verification_dir/zero-schema-check.py" > "$release_dir/backup-verification.json"
# 检查全部登记家庭、schema 对象/列/所有行/SQLite 内部表，再初始化并逐项严格比较。
docker compose run --rm --no-deps -T -v "$verification_dir:/release-check:ro" app \
  python - warm < "$verification_dir/zero-schema-check.py" > "$release_dir/initialization.json"
test "$env_digest" = "$(sha256sum .env | cut -d ' ' -f 1)"
test "$candidate_image" = "$(docker image inspect --format '{{.Id}}' family-dashboard-app)"
docker compose up -d --no-build --wait --wait-timeout 180 app
new_app_id=$(docker compose ps -q app)
test -n "$new_app_id"
test "$(docker inspect --format '{{.Image}}' "$new_app_id")" = "$candidate_image"
# app 启动后的独立读回：web/sync 仍停止，不能跳过这一步直接开放入口。
docker compose run --rm --no-deps -T -v "$verification_dir:/release-check:ro" app \
  python - check < "$verification_dir/zero-schema-check.py" > "$release_dir/startup-readback.json"
for old_id in "$old_web_id" "$old_sync_id"; do
  test "$(docker inspect --format '{{.State.Running}}' "$old_id")" = false
done
test "$env_digest" = "$(sha256sum .env | cut -d ' ' -f 1)"
# 提交边界：从启动 sync 起可能产生新云端/本地写入，不能再盲目恢复旧快照。
date -u +%Y-%m-%dT%H:%M:%SZ > "$release_dir/commit-started-at.txt"
docker compose up -d --no-build --no-deps sync
docker compose up -d --no-deps --force-recreate web
docker compose exec -T web nginx -t
for service in app sync; do
  service_id=$(docker compose ps -q "$service")
  test -n "$service_id"
  test "$(docker inspect --format '{{.Image}}' "$service_id")" = "$candidate_image"
done
test "$env_digest" = "$(sha256sum .env | cut -d ' ' -f 1)"
```

`before.json` 只保存 schema／列元数据、行数和 SHA-256，包括 SQLite 内部表摘要，不输出原始行或私人内容。平台注册必须非空并含 default，逐户路径合法、文件存在且无符号链接；每户恰好 42 张表，device 布局列存在，采购两表／例行三表／消费观察两表的完整 schema 与索引均匹配冻结定义；所有原表的 schema／列／行均与停止后快照相同。参考 DDL 仅在内存库比较，不对真实户库执行。42→42 允许所有历史非空，包括例行计划／期次／回执与本人消费观察／回执，但全部旧值必须相同；首次 40→42 才要求两张消费观察新表为空。缺库、空库、户集合变化、额外 schema、行或内部序号改变均拒绝，不补建空库。

`pre-migration-backup.json` 仅记录备份组名称和库数量，真正快照仍在数据卷。`validate-backup` 校验 manifest 路径、每个库的 SHA-256／大小、SQLite 完整性、目标映射和内容摘要；必须恰好覆盖停止后快照的全部家庭加注册目录，无重复目标，并与停止后内容一致。保留 manifest 和它引用的**全部文件**；只保留两份 JSON 输出不是可恢复备份。在线备份是额外恢复材料，维护窗口的完整组才是本次基准。

隔离镜像测试不挂生产卷或 .env，安装 pytest 需要网络。测试、安装或候选 Nginx 校验失败时旧服务仍运行；保留失败日志、恢复已记录的旧镜像标签／相配源码目标后再安排下一轮，不把新标签遗留为含糊的下次启动目标。标签恢复前仍需确认旧服务未被另一位维护者替换。后端检查不能代替浏览器或真实账号验收。

维护窗口内的备份、快照与 warm 容器使用原生产配置和数据卷；warm 是唯一调用 create_app／逐户 child 的步骤，不调用 tick。检查输入通过只读挂载提供，脚本经标准输入交给 /app 工作目录内的 Python（使 warm 能导入同一镜像的 app 模块），所有数据库读取使用 mode=ro；全数据摘要严格相等只证明**关闭入口与 worker 期间**未改变数据库，不保证开放后的同步不产生合法写入。

任何一步失败都停止后续步骤，保留旧容器 ID、停止记录、源码／镜像、.env、完整备份组、核对输出和原数据卷。若候选 app 或 sync/web 已部分启动，先停止 web，再停止 sync/app 并保全现场；不要自动启动旧 worker、重跑初始化或把新数据覆盖回旧快照。提交前恢复也必须核对整组备份、源码／镜像匹配和 .env 未漂移；需要实际恢复数据库时执行第 6.2 节，并先使恢复家庭旧会话失效。提交后任何写入状态不明，都保持停止并人工核对，不能用本节摘要当作覆盖新数据的许可。

测试目录挂载到 /app/tests、部署工具到 /app/deploy，不能改回 /tests／/deploy。源码解包不会自动删除新版本已移除的旧文件；删除须核对明确清单，不能递归清空 /opt/family-dashboard。若 service/timer 改动，还需核对并安装对应文件与 daemon-reload；普通更新保留生产 .env 和整棵数据卷，不重新生成密钥。

### 5.3 为什么必须重建 Nginx

有两个已实际遇到的边界：

1. **文件 inode**：Nginx 配置是单文件 bind mount。宿主机用替换文件方式更新配置时，旧容器可能仍指向旧 inode；旧容器 `nginx -t` 成功不能证明新候选配置生效。
2. **app 地址**：app 容器重建后 Docker 内网 IP 可能改变，已有 Nginx worker 可能保留旧上游地址。

因此先在**新的一次性 web 容器**中测试配置，再 `--force-recreate web`，同时刷新配置挂载和上游解析。不要仅做旧容器 `nginx -s reload` 就结束应用发布。普通证书续期在当前挂载目录内更新材料，仍按 `renew.sh` 的检查与 reload 流程处理。

### 5.4 发布后的最小核验

```sh
cd /opt/family-dashboard
docker compose ps
curl --fail --silent --show-error --retry 5 --retry-all-errors --retry-delay 2 \
  https://home.caesarcharles.world/healthz
curl --silent --show-error -o /dev/null -w '%{http_code}\n' \
  https://home.caesarcharles.world/api/state
docker compose logs --tail=60 app sync web
```

未登录 `/api/state` 应为 401。另核对当前镜像、主户及平台注册目录中每个家庭的数据库完整性、记录数量/摘要、来源最近同步和发布队列状态；主域名 healthz 不能证明其他家庭健康。用本人现有会话检查新功能与权限，特别是跨家庭会话切换、个人账本隔离和电视只读。新功能需要真人账号的部分由本人操作，不尝试旧初始密码，不伪造真实同意。新增云日历写入的授权和实际验收独立于原有读取绑定，见 [CALENDAR-PUBLISH](CALENDAR-PUBLISH.md)。

Gunicorn 与 Nginx 访问日志只记录路径，不记录查询字符串。若调整日志格式，保留此约束，尤其不可把 OAuth `code` / `state` 写入日志。对外分享诊断前仍需检查用户名、财务或其他个人数据是否混入。

本机 DNS 缓存异常且不存在组织访问限制时，可单独用严格 TLS 的 `curl --resolve home.caesarcharles.world:443:96.44.160.28 https://home.caesarcharles.world/healthz` 检查入口。此结果只证明指定地址与证书工作，不代表普通客户端 DNS 已正常。遇到 SmartScreen“组织已阻止此内容”时，保存阻断证据并标记浏览器验收未执行，不关闭策略、切换浏览器或改变访问路线绕过限制；服务器内部获授权的诊断单独记录范围。

## 6. 备份、恢复与回滚

### 6.1 当前备份覆盖

新版 `deploy/backup.sh` 将宿主机 `deploy/backup.py` 经标准输入交给运行中的 app 容器。脚本先快照 `/data/platform.sqlite3`（若存在），从该快照枚举已注册家庭，然后备份 `/data/household.sqlite3` 及 `/data/spaces/<id>/household.sqlite3`。每个数据库通过 SQLite backup API 包含 WAL 已提交数据，随后 `quick_check`。

快照写在各数据库同级 `backups/` 目录：主户和注册目录在 `/data/backups/`，子户在 `/data/spaces/<id>/backups/`。名称含 UTC 日期时间与微秒，文件 0600。全部成功后才在 `/data/backups/manifest-<UTCSTAMP>.json` 写完整组清单，记录每个快照相对于 `/data` 的路径、字节数和 SHA-256。保留最近 **14 组完整 manifest 及其引用文件**，不是只保留全平台 14 个数据库文件。首次过渡阶段会额外保留一部分旧单库快照。

各库分别一致，但不是跨所有数据库的同一全局事务时刻。在线备份期间新登记、但不在已拍下注册目录快照中的家庭由下一组备份覆盖。照片 BLOB、账单、投资、财务基线、日历发布队列及加密凭证都随各自户库进入备份。

备份包含个人财务、账户映射、加密第三方令牌、密码散列、日程等私人内容。数据库并非整体加密；家庭成员之间的 API 隔离不等于管理员无法读取数据库。当前照片总额限制为 200 MB / 500 张，但 14 份数据库副本仍会放大磁盘占用，需监控空间。

必须另行保管原 `.env`（特别是 `SECRET_KEY`）、TLS 目录和恢复用源码/镜像版本。SQLite 备份不包含这些宿主机文件，也不备份外部 Microsoft / Google 云端数据。`cloud-locks/` 是进程间锁文件，恢复后可由应用重建，不作为云端状态的来源。

**当前只有同服务器备份，无异地加密副本，无整机/磁盘丢失保护，未完成生产覆盖恢复演练。** 已有备份生成与 integrity_check 通过的记录，不能据此宣称灾难恢复已验证。

### 6.2 根据完整 manifest 恢复一户或整个平台

先选定具体备份时间及相配源码版本，确认可以接受该时间点之后的看板修改被回退。`restore_mode=household` 只恢复一户，`restore_household=default` 指原家庭；子户使用当前平台注册目录内的 24 位随机 id，不能使用 slug 代替。`restore_mode=platform` 恢复清单中的全部家庭，最后恢复该清单配套的平台注册目录。全平台回退会使备份时间后创建的家庭暂时不再出现在注册目录中，原文件不会被这个流程删除。

第三方来源恢复后仍读取云端最新状态；数据库恢复不会撤销已写回云端的任务或日历事项。新版本保留发布幂等键与 ETag 来核对恢复后的队列，但旧备份可能不包含最新外部动作；先检查队列和真实来源，再决定恢复写入。以下步骤使用标准库验证所有快照的路径、大小、SHA-256、SQLite 完整性、表类型和家庭映射，全部通过后才写目标。没有 manifest 的历史单库备份不适用该多户流程，需要独立确认原家庭身份和覆盖范围。

先选择源库状态，以下命令在**同一个 root shell** 中执行：

- `restore_source_state=healthy`：app 正常运行且全部注册户库完整，先生成新的在线完整备份。
- `restore_source_state=offline`：app 无法启动、注册目录/某户库缺失或数据库损坏。不要把在线备份成功作为恢复前提，使用此前已有、稍后能通过完整校验的 manifest。缺失目标需要选择 `restore_mode=platform`，由相配注册目录与全部户库恢复身份映射，不能凭主家庭密码创建空库。

两条路径都会先停止备份任务与应用写入，再将**残存整个数据卷**（包括 WAL/SHM）原样保存在数据卷之外的私人归档中，并保管当前 `.env`。此归档用于保全现场，不等于通过 SQLite 校验的可用备份，也不能作为把损坏库直接复制回运行卷的依据。先用 `df -h /opt` 确认宿主机有容纳整棵卷的一份额外归档的空间；空间不足时先准备足够容量的受控存储，不删除现有快照腾空间。

```sh
set -eu
cd /opt/family-dashboard
restore_source_state='healthy'  # 无法在线备份、缺库或损坏时改为 offline
restore_manifest='manifest-YYYYMMDDTHHMMSSffffffZ.json'  # 改为实际完整组清单
restore_mode='household'  # 或 platform；整个平台恢复包含注册目录
restore_household='default'  # 或该子家庭在平台注册目录中的 24 位 id
case "$restore_source_state" in
  healthy) ./deploy/backup.sh ;;
  offline) : ;;  # 使用此前已存在的完整组，不初始化缺失数据库
  *) echo 'Invalid source state.' >&2; exit 1 ;;
esac
backup_timer_was_active=$(systemctl is-active family-dashboard-backup.timer || true)
systemctl stop family-dashboard-backup.timer family-dashboard-backup.service
docker compose stop sync app
data_volume='family-dashboard_household-data'
docker volume inspect "$data_volume" >/dev/null
# 若仍有手工维护或其他容器占用此卷，先查明并停止它们，不继续复制。
test -z "$(docker ps -q --filter volume="$data_volume")"
recovery_stamp=$(date -u +%Y%m%dT%H%M%SZ)
recovery_dir=$(mktemp -d "/opt/family-dashboard-recovery-$recovery_stamp-XXXXXX")
chmod 0700 "$recovery_dir"
install -m 0600 .env "$recovery_dir/.env"
umask 077
docker run --rm --network none --read-only --user 0:0 \
  --mount "type=volume,src=$data_volume,dst=/data,readonly" \
  --entrypoint python family-dashboard-app \
  -c 'import sys,tarfile; archive=tarfile.open(fileobj=sys.stdout.buffer,mode="w|"); archive.add("/data",arcname="data"); archive.close()' \
  > "$recovery_dir/residual-volume.tar.partial"
mv "$recovery_dir/residual-volume.tar.partial" "$recovery_dir/residual-volume.tar"
chmod 0600 "$recovery_dir/residual-volume.tar"
sha256sum "$recovery_dir/residual-volume.tar"
# 完整组校验之前不修改任何现存数据库。
docker compose run --rm -T --no-deps app python - "$restore_manifest" "$restore_mode" "$restore_household" <<'PY'
from contextlib import ExitStack
from pathlib import Path
import hashlib
import json
import re
import sqlite3
import sys

root = Path('/data').resolve(strict=True)
name, mode, chosen = sys.argv[1:]
if not re.fullmatch(r'manifest-[0-9TZ]+\.json', name) or mode not in {'household', 'platform'}:
    raise SystemExit('Invalid manifest name or restore mode.')
if chosen != 'default' and not re.fullmatch(r'[a-f0-9]{24}', chosen):
    raise SystemExit('Invalid household id.')

def checked_path(relative, must_exist=True):
    candidate = root / relative
    if candidate.is_absolute() and not candidate.is_relative_to(root):
        raise SystemExit('Path outside data volume.')
    resolved = candidate.resolve(strict=must_exist)
    if not resolved.is_relative_to(root) or any(p.is_symlink() for p in [candidate, *candidate.parents] if p.is_relative_to(root)):
        raise SystemExit('Unsafe data path.')
    return resolved

manifest_file = checked_path('backups/' + name)
manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
items = manifest.get('snapshots')
if not isinstance(items, list) or not 1 <= len(items) <= 100:
    raise SystemExit('Invalid snapshot list.')
with ExitStack() as stack:
    sources = {}
    for item in items:
        relative = item.get('path', '')
        match = re.fullmatch(r'(backups|spaces/([a-f0-9]{24})/backups)/(household|platform)-[0-9TZ]+\.sqlite3', relative)
        if not match or (match[3] == 'platform' and match[2]):
            raise SystemExit('Unexpected snapshot path.')
        key = 'registry' if match[3] == 'platform' else (match[2] or 'default')
        if key in sources:
            raise SystemExit('Duplicate household snapshot.')
        source = checked_path(relative)
        if not source.is_file() or source.stat().st_size <= 0 or source.stat().st_size != item.get('bytes'):
            raise SystemExit('Snapshot size mismatch.')
        with source.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        if checksum != item.get('sha256'):
            raise SystemExit('Snapshot checksum mismatch.')
        con = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
        stack.callback(con.close)
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise SystemExit('Snapshot integrity check failed.')
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {'households', 'household_invitations'} if key == 'registry' else {'users', 'entities', 'settings'}
        if not required.issubset(tables):
            raise SystemExit('Snapshot database type mismatch.')
        if key != 'registry' and {r[0] for r in con.execute('SELECT id FROM users')} != {'member1', 'member2'}:
            raise SystemExit('Snapshot members invalid.')
        sources[key] = con
    if 'default' not in sources:
        raise SystemExit('Manifest lacks original household.')
    if 'registry' in sources:
        expected = {r[0] for r in sources['registry'].execute('SELECT id FROM households')}
        if expected != set(sources) - {'registry'}:
            raise SystemExit('Registry and household snapshot sets differ.')
    if mode == 'platform':
        if 'registry' not in sources:
            raise SystemExit('Full platform restore requires a registry snapshot.')
        selected = sorted(set(sources) - {'registry'}) + ['registry']
    else:
        if chosen not in sources:
            raise SystemExit('Household is not in this manifest.')
        if chosen != 'default':
            registry_path = checked_path('platform.sqlite3')
            current_registry = sqlite3.connect(registry_path.as_uri() + '?mode=ro', uri=True)
            stack.callback(current_registry.close)
            if not current_registry.execute('SELECT 1 FROM households WHERE id=?', (chosen,)).fetchone():
                raise SystemExit('Household is not in current registry; use matching full restore.')
        selected = [chosen]
    targets = {}
    for key in selected:
        relative = 'platform.sqlite3' if key == 'registry' else 'household.sqlite3' if key == 'default' else f'spaces/{key}/household.sqlite3'
        target = checked_path(relative, must_exist=mode == 'household')
        if target.exists() and (not target.is_file() or target.stat().st_size == 0):
            raise SystemExit('Existing restore target is not a nonempty database.')
        targets[key] = target
    # No writes occur before every selected source and target passes validation.
    for key in selected:
        target = targets[key]
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        active = sqlite3.connect(target.as_uri() + ('?mode=rw' if target.exists() else '?mode=rwc'), uri=True)
        try:
            sources[key].backup(active)
            if active.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise SystemExit('Restored target integrity check failed; keep services stopped.')
        finally:
            active.close()
        target.chmod(0o600)
print('Restore completed; database count:', len(selected))
PY
```

**恢复后必须先使本次恢复家庭的旧成员登录失效。** 上面的恢复块到此结束，app/sync 保持停止；不要立即执行启动命令。按 [恢复后使旧成员登录失效](MEMBER-SESSIONS.md#恢复后使旧成员登录失效)，仅在本次恢复的每个已核对家庭库中执行成员版本递增、会话撤销、浏览器代次推进与进行中 OAuth 清除；迁移前缺少两张会话表时按该节省略相应表更新，仍递增成员版本并清除 OAuth 状态。

逐户提交后检查版本递增、有效旧会话数与 OAuth 状态数为零，并执行 `PRAGMA quick_check`。全部恢复目标通过才继续；任一失败继续停机，保留残存卷与配置，不启动部分恢复的平台。不要删除已绑定账号、来源或 TV 配对，也不要把这个失效步骤用于普通升级。

完成上述失效与核对后，单独执行以下启动块；sync 仍保持停止：

```sh
docker compose up -d --wait --wait-timeout 180 app
docker compose up -d --no-deps --force-recreate web
```

如清单或任一快照无效，脚本停止且保持 app / sync 停止。多个目标不是跨库事务；若写入中途因磁盘或权限故障失败，应保持停止并从同一完整组重试或恢复先前组，不启动部分恢复的平台。此脚本不会删除任何旧家庭目录。不要直接复制运行中的主数据库文件而忽略 WAL；不要执行 `docker compose down -v` 或删除 `family-dashboard_household-data`。

离线路径不依赖 app 能否启动，保全残存卷的辅助容器不加载生产环境变量、网络或应用入口。若当前 `.env` 丢失，先找回与备份匹配的原配置，不能生成新密钥继续。现有恢复程序会拒绝零字节或非法目标，遇到具体物理损坏时应保持服务停止、保留现场归档并在隔离副本验证修复；不要删除目标或创建空库绕过校验。本项目没有声称所有 SQLite 物理损坏都已演练可恢复。

仅在完成上面的逐恢复户成员会话失效与检查后，app/web 才提供核验入口，成员需重新登录，sync 仍停止。核对记录、照片、TV 与私有隔离，并检查每户历史待写队列：备份之后暂停/撤销的动作可能仍为 pending/active，须核对来源并暂停不应继续的操作。不要点击立即同步或产生真实云写。全部目标核对完成后，才在同一 root shell 执行：

```sh
docker compose up -d --wait --wait-timeout 180 sync
if [ "$backup_timer_was_active" = active ]; then
  systemctl start family-dashboard-backup.timer
fi
docker compose logs --tail=60 app sync
```

随后核对每户最近同步和授权状态。恢复的刷新令牌可能已轮换或撤销，必要时由成员重新绑定；不要通过更换 `SECRET_KEY` 试图修复授权问题。若恢复途中中止，备份 timer 仍暂停，完成恢复并验证后再按原状态启动。

完整组可先用独立新卷和虚构家庭进行[隔离 Docker 恢复演练](RECOVERY-REHEARSAL.md)。该工具原样执行本节恢复程序和成员失效 SQL，记录实际容器与 HTTP 结果；不读取生产数据，不替代生产恢复或异地灾难恢复验收。

### 6.3 仅回退代码 / 镜像

2026-09-15 07:58:24 的成员会话历史迁移新增 `cloud_oauth_states.auth_context`；该字段在本次采购实付版本中保留，7b 旧程序的位置式插入不兼容新库。直接回退 7b 必须使用相配的迁移前完整恢复组或已独立验证的兼容适配；恢复后先处理目标家庭成员失效，再启动服务。只保留旧镜像标签不是可用回滚证明。

发布第 5 节保留了旧源码和镜像标签。只有数据库结构与旧代码仍兼容时，才能保留当前账本仅回退代码；存在破坏性迁移时应使用相配备份，并单独确认数据回退范围。目前没有通用的向下迁移工具。**若已有子家庭，不能把只支持单户的旧版本作为保持服务的回退方案**：旧版本会忽略平台注册目录、家庭路由和发布队列，即使主户健康也不代表其他家庭可用。还要避免回退到只备份单户的旧 `backup.py` 后继续清理多户完整组。

2026-09-15 02:33:28 的旅行 v2 和日历时间核对历史迁移引入了数据与队列语义变化，不能只凭“新增表／列不影响旧 SQL”判断兼容。只要已保存旅行 v2 或存在 `needs_review`／`review_required` 状态，不理解这些内容的旧 app / worker 就不能直接接管当前数据；将新列清零或把 schemaVersion 改回旧值也不是回滚方法。缺少明确兼容证据时，使用第 6.2 节恢复与旧源码／镜像相配的迁移前完整组，并先确认数据回退范围、保全残存卷与配置。数据库恢复不会撤销已经发生的云端写入，恢复后仍须在启动 sync 前核对各户队列和远端状态。

**下方仅适用于已确认目标版本支持当前全部数据和队列语义的代码回退。** 不满足条件时不要执行；转到第 6.2 节的相配恢复路径。

```sh
set -eu
cd /opt/family-dashboard
rollback_stamp='YYYYMMDDTHHMMSSZ'  # 改为第 5 节保留的具体版本
rollback_dir="/opt/family-dashboard-releases/$rollback_stamp"
test -f "$rollback_dir/source.tar.gz"
docker image inspect "family-dashboard-app:rollback-$rollback_stamp" --format '{{.Id}}'
./deploy/backup.sh
rollback_env_digest=$(sha256sum .env | cut -d ' ' -f 1)
docker compose stop --timeout 45 sync app
for rollback_service in sync app; do
  rollback_id=$(docker compose ps -a -q "$rollback_service")
  test -n "$rollback_id"
  test "$(docker inspect --format '{{.State.Running}}' "$rollback_id")" = false
done
tar -xzf "$rollback_dir/source.tar.gz" -C /opt/family-dashboard
test "$rollback_env_digest" = "$(sha256sum .env | cut -d ' ' -f 1)"
docker image tag "family-dashboard-app:rollback-$rollback_stamp" family-dashboard-app:latest
docker compose up -d --no-build --force-recreate --wait --wait-timeout 180 app
docker compose run --rm --no-deps web nginx -t
docker compose up -d --no-deps --force-recreate web
```

先执行第 5.4 节的 app / web 与每户数据核验，确认所选版本能正确解释现有旅行、队列和核对状态；sync 此时保持停止。确认后再启动同一回滚镜像的 worker：

```sh
docker compose up -d --no-build --no-deps --force-recreate sync
docker compose logs --tail=60 app sync web
```

以上保留当前 `.env`；若确需恢复历史密钥配置，必须先核对它与目标数据库的加密令牌相配，再从 0600 的私人备份恢复，不能盲目覆盖。任一步失败都停止后续操作；不要自动重启 worker。最后完成第 5.4 节的逐户同步与队列核验。

## 7. 私人财务基线的独立导入

此入口是管理员 CLI，不是公开上传 API，也不会自动读取本机 Personal_Finance 仓库。输入 JSON 顶层必须恰好为 `private` 与 `shared`，schema、字段与校验以 `finance_baseline.py` 和接口文档为准。金额使用整数分；未核对余额、外币换算、未来薪资/授予不能当作实时人民币资产。共享部分仅包含明确批准的资产/负债汇总与覆盖信息，账户、收入、消费明细仅在本人私有接口可见。

已于 2026-09-15 02:33 发布的常规更新入口另见 [来源准备与预览／CAS 确认](FINANCE-SOURCE-BRIDGE.md)：源码外私人配置驱动 `deploy/prepare-finance-source.py` 生成候选，再由本人通过三个来源 API 预览、确认和查状态。它不读取生产凭据、不自动刷新邮箱；后端不写实际账本、投资或荷包。来源写请求 HTTP 上限 3,000,000 字节，但规范化候选内容须控制在约 1.95 MB 以下。来源日期倒退、缺源、旧记录缺稳定映射或贷款余额缺核对日期时保留旧值。该 HTTP 流程已部署；银行分类与尾备注 CLI 增量已随 03:58:15 源码发布，真实私人映射和余额日期仍须核对。不能通过下方旧 CLI 跳过这些保护来完成普通刷新。

导入前生成经过核对的私人 payload，存放在源码目录之外的 0600 文件中。当前一次性导入版本不是自动刷新；个人银行余额不会写入公共小荷包。CLI 的 `--database` 默认值是 `/data/household.sqlite3`，只指向原家庭；payload 中的 `owner` 仅选择该数据库内的 `member1` 或 `member2`，不能选择家庭。浏览器当前空间、路由 Cookie 和家庭 slug 均不会影响这个 CLI。

以下示例仅用于原家庭，并显式写出数据库路径。程序从标准输入读取私人 payload，结果只输出状态及计数；示例文件路径须替换为实际私人文件，不能把 payload 内容放进命令行或通用日志：

```sh
set -eu
cd /opt/family-dashboard
./deploy/backup.sh
# 替换为服务器上已安全传输、仅管理员可读的私人文件。
docker compose exec -T app python /app/finance_baseline.py --database=/data/household.sqlite3 < /root/private-finance/baseline-payload.json
```

子家庭导入前，管理员须在 `/data/platform.sqlite3` 的 `households` 注册表中核对目标家庭的实际 `id` 与 `slug` 对应关系，再核对该家庭已有数据库中的成员身份，并先完成第 6 节的完整备份。数据库目录使用注册的随机 `id`，不是家庭名称或 slug；不能仅更改 `owner` 后照抄上面的原家庭命令。子家庭所需参数格式如下，尖括号是说明占位符，不能原样执行：

```text
--database=/data/spaces/<已核对的实际家庭ID>/household.sqlite3
```

确认注册信息、目标数据库和成员均正确后，才可在上述导入命令中替换 `--database` 为这一完整路径。若注册记录不明确、目标数据库不存在或成员归属无法确认，应停止导入；不要创建空库、回退默认路径或借此绕过家庭身份核对。

返回 `status=imported` 或 `unchanged` 及条目计数；相同内容再次导入不会增加版本。共享汇总与私有记录口径不一致、成员不存在或格式异常会拒绝导入。完成后以实际字段白名单、成员身份隔离和其他业务数据摘要验证，不把真实账户明细放进通用测试夹具。私人临时文件的保留/清理由数据持有人按其备份策略管理。

## 8. 维护排查速查

| 现象 | 优先核对 |
|---|---|
| app 启动报缺少 SECRET_KEY | Compose 是否在正确目录读取 `.env`；直接 Python 启动是否设置了进程环境。不要打印密钥值。 |
| 空库报 MEMBER 密码错误 | 首次两个密码均至少 12 字符；已有账本不能靠修改初始密码字段重置账户。 |
| SQLite / cloud-locks permission denied | `/data` 卷是否挂载正确，UID 10001 是否能写；不要误创建一个全新卷代替原账本。 |
| web 启动证书文件不存在 | 当前配置依赖 IP 和域名两张证书；按 bootstrap 顺序完成两次签发。 |
| 更新后 502 / 仍显示旧配置 | app 健康状态、新容器内 nginx -t、web 是否 force-recreate，检查 bind mount 与上游 IP。 |
| 小照片可上传，大图片失败 | Nginx 上限 8m；图片 API 请求体上限 8,000,000 字节，解码原图至多 5 MB / 4 百万像素。浏览器先压缩；财务导入请求体另限 3,000,000 字节、原文件至多 2 MiB，其他普通 API 限制 600,000 字节。 |
| 照片数/体积达到限额 | 全家 500 张 / 200 MB；无引用草稿超过 24 小时后在后续上传时清理，没有独立定时清理服务。 |
| 绑定后没有数据 | 本人是否选择了来源、最近同步时间与错误；配置存在不等于授权成功，来源读取失败不等于空列表。 |
| OAuth 改配置未生效 | restart 不会重新读取 `.env`，使用容器重建；保留原 `SECRET_KEY`。 |
| 共享日历权限提示 | 区分 Microsoft 基础权限与可选 Calendars.Read.Shared，见账号文档；不能仅凭绑定成功宣称所有共享日历可读。 |
| 备份/续期 timer 失败 | 查看对应 journal、Docker 状态、脚本 0755、证书/数据卷路径及磁盘空间。 |

本项目尚无 CI/CD 平台、蓝绿发布、滚动多副本、集中日志、外部告警、异地备份或自动数据库向下迁移。增加这些能力前，要保留现有双成员权限、电视只读、源选择共享和个人明细隔离，并为新增运维路径提供实际验证记录。

XLSX 工作表发现与助理旅行简报已于 2026-09-15 06:50:21 合入并发布，详情见 [验收记录](VALIDATION.md)。

历史 40→40 校验片段的 58 项离线检查仅对应当时版本。第 5.2 节保留的历史 42→42 代码及其当时整文档散列，曾与消费观察 SCHEMA_SQL 一起绑定离线复验记录，检查临时两户非空历史、完整备份和 fake app warm。本次只修改说明正文，代码字节未变；不能把历史整文档证明当作当前 69/9 表结构的更新验收。该范围也不是 Docker 或生产恢复实测。
