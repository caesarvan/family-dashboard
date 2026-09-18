# 成员关系发布控制器

这是 58→61 户内表、2→9 平台表的独立发布候选，不是已发布记录。`deploy/membership_release_controller.py` 只提供 `stage` 和 `activate`。打包、构建、隔离测试、真实副本迁移演练和非作者审查先完成；不能将早期 58→58 工具改表数后执行。

输入为新的 `/opt/family-dashboard-candidates/<name>`：包含 `package/` 的完整包与验证器输出、已核对的 `source/`、构建与 Linux 测试原件、独立审查原件、`release-plan.json`。调用者从已审查的具体 plan 字节提供 SHA256，计划冻结 controller/verifier、包、镜像、旧 manifest、环境摘要和测试/审查原件。计划不含密码或密钥。

计划字段：`schemaVersion:1`、`kind:membership-release-plan`、`controllerSha256`、`packageVerifierSha256`、`packageSha256`、`imageId`、固定 `parentImage`/`webImage`/`oldManifestSha256`、`envSha256`、`validation:{path,sha256}`、`testCases:[[classname,name],…]`、`allowedSkips`、`reviews:{relativePath:sha256}`。SHA 必须来自实际原件；测试项与允许的平台 skip 在执行前冻结，不能根据失败结果缩减。

Linux 验证报告含 `imageId/sourceHead/manifestSha256/exitCode/evidence/junitPath/runtimePath`。runtime 原件含完整 `before/after` 文件哈希、`loadedBefore/loadedAfter` 的实际 `/app/<module>.py` 映射，以及 `sourceBefore/sourceAfter`。控制器逐项检查 JUnit、唯一用例集合、所有失败/错误/跳过、原始报告散列和镜像内容，不能只填一个成功布尔值。构建镜像必须保持固定父镜像层和配置，仅增加清理旧 Expo 文件与 COPY 两层。

`stage` 核验上述证据与真实旧镜像、容器标签和数据卷、配置摘要及源码，仅生成候选证据，不停服。`activate` 再核一次，持有全局发布锁，保留旧源码、完整环境文件及镜像标签；停止备份计时器、web 和全部数据卷写入者；检查容器确实干净退出。

之后在无网络且仅挂载数据卷/冻结源码/私有 proof 的容器中建立完整停写备份，验证全部 registry 家庭，并在不会被自动轮替的 `proof/backup-group` 再保存一组。`membership_release_data.warm_once` 只运行一次新代码初始化，逐库验证精确迁移和旧数据保全，持久标记阻止更换目录后重放。

迁移通过后才安装源码、启动新 app；验证健康与全部运行文件，再停止 app，关闭数据库后复核迁移后全组数据未变化。最后启动 app、worker、web，验证正常 TLS 健康并恢复备份计时器。原 Expo 文件完整保留在发布目录，不继续由 Web 服务提供。

任何失败保留 `activation.json` 已完成步骤和数据层 attempt，不自动启动旧程序、不自动覆盖恢复、不重放激活。恢复须先保全发布后新增数据，再按经审查的完整组恢复匹配程序/数据库；仅回退旧代码可能恢复已撤销成员权限。数据模块的 `verify_restored` 只用于恢复后的只读检查，不执行恢复。

候选 app 启动一旦被尝试，后续健康、运行文件、worker/web 部分启动或公开健康检查失败时，控制器会尝试停止候选服务及备份计时器，并记录是否确已停止。停止命令本身失败时明确记录 `candidateStoppedAfterFailure:false`，不能宣称已回到停写状态；不因此恢复旧数据或旧程序。SIGINT/SIGTERM 也进入同一收尾路径，强制杀进程仍需按保留步骤人工检查。

调用示意（必须替换为本轮真实候选及已审核摘要）：`python -B deploy/membership_release_controller.py stage /opt/family-dashboard-candidates/<name> <plan-sha256>`；核验 stage 后，同一计划调用 `activate`。CLI 限定 Linux root、无优化/字节码、无继承 Docker/Compose 选择器；完整 `.env` 从不输出到命令结果。

本地控制器专项首轮实际 22/22，通过路径/证据拒绝、原件排他保留、JUnit 失败/错误/隐藏跳过、未列运行文件、备份/迁移/首次启动复核失败时不开放 worker，以及正确开启次序。该组是隔离文件和命令替身测试，不证明 Docker、真实迁移或生产发布成功；数据层的真实 SQLite 演练与最终 Linux/浏览器组合另行记录。

独立审查发现直接脚本运行缺少仓库根导入路径、候选部分启动失败未停止服务两项问题。修正后第二轮完整 28/28，通过新增五个启动/读回失败窗口与停止命令失败的准确记录；第一轮原件保留。此项仍是命令替身验证，不冒充实际容器演练。

与独立构建器合同接线后，验证原件路径按 `validation.json` 所在目录解析，报告还必须明确 `allPassed:true` 且包摘要匹配。第三轮完整 33/33，新增真实嵌套目录证据、容器退出 0 但验证守卫失败、错误包、加载模块被源码目录遮蔽、源文件变化的准入检查。原件相对路径不能越界，`release-plan.json.validation.path` 仍相对候选根目录。

迁移容器环境必须来自已核验旧 app 容器的完整 `Config.Env`，包括 Compose 与镜像默认值。生产 R2 曾在户库完成 61 表初始化后被 `CloudAccounts.__init__` 的 HTTPS origin 校验拦截，平台仍为 2 表；服务器内私有副本确认 `docker run --env-file .env` 保留外层双引号，而 Compose 已将其解析，不能互换。完整停写备份和失败 attempt 保留；此修订不处理恢复、失败标记或迁移重放。

修订后 `stage` 的 app 服务身份包含完整运行环境序列化 SHA；`activate` 在停止服务前再按原容器 ID、镜像及该 SHA 核对，排他写入发布目录 `app-runtime.env`（0600）。每个 `Config.Env` 项按原顺序保留值，不去引号、不展开 `$`、不改空值；拒绝重复或非法 key、无赋值项、NUL、CR/LF 和不可编码字符，并要求原 `DATA_DIR=/data`。环境文件仅由 Docker 读取，不挂载进容器，不输出值；原 `.env` 保持原字节。

`data_call` 没有回退原 `.env` 的路径，也不以 `-e` 覆盖已绑定值。每次备份、warm 和迁移后复核前检查私有文件位置、0600 与摘要，以及原 `.env` 的权限和计划摘要；缺失、篡改或未绑定均在运行容器前拒绝。源码／运行文件守卫、禁网、UID 10001、只读容器根以及原数据卷／冻结源码／proof 挂载边界保持。环境原件含密钥，只能留在服务器私有发布目录，不能下载进验收报告或提交 Git。

本次 Windows 本地完整控制器专项实际 53/53（原 33 项与新增 20 项），2.11 秒，357 个 Python 输入前后不变。新增项核对真实序列化文件字节及拒绝条件、stage 服务环境摘要、停止前容器／环境变化，以及 `data_call` 禁止回退和隐私命令边界；Windows 的 POSIX 权限分支使用窄测试替身。XML 摘要 `f64f69bd649dec7e8af027baedfc49c80fa04ba330fe891847ed5189889f2a86`，详细原件为作者树 `test-results/runtime-environment-r1/`。这不声称修订已在 Docker 或生产迁移执行；后续容器读回和私有副本重验必须另有实际证据。
