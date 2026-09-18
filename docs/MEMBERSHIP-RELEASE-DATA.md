# 成员领域发布的数据组保护

本模块是发布控制器的本地数据步骤，尚未执行生产迁移。它读取完整 registry，校验停写副本和保留备份，只调用一次由控制器提供的初始化函数，再以 [只读迁移检查器](MEMBERSHIP-MIGRATION.md) 校验每对数据库。它不创建备份、不控制 Docker/服务、不加载环境配置，也不自行导入或启动应用。

实现：[deploy/membership_release_data.py](../deploy/membership_release_data.py)；专项：[tests/test_membership_release_data.py](../tests/test_membership_release_data.py)。

## 调用契约

| 函数 | 结果与约束 |
| --- | --- |
| `enumerate_databases(data_root)` | 返回 registry 中全部数据库的相对路径 tuple：平台库、默认家庭库和全部 `spaces/<id>/household.sqlite3`。缺库、无 default、非法 ID、未登记家庭库均拒绝。 |
| `snapshot(data_root)` | 返回逐库文件、schema、列、全部行及序列的散列/数量和迁移阶段；不返回姓名、密码、记录正文或邀请秘密。读取前后重新核完整枚举和文件散列。 |
| `validate_backup(data_root, before, manifest_path)` | 核验原 `deploy/backup.py` 全组 manifest 的精确条目集合、大小/散列、原逻辑状态及备份 registry。支持完整复制到不受轮替影响的目录后核验。 |
| `finish_stopped_backup(data_root, before, manifest_path)` | 仅在全组仍停写、原无 sidecar 的 `before` 和完整备份均保持时，用 SQLite `mode=rw` 的 `wal_checkpoint(TRUNCATE)` 与关闭连接整理备份读取后留下的空 WAL/SHM；随后要求严格无 sidecar、完整 `snapshot == before`。 |
| `warm_once(data_root, before, manifest_path, attempt_directory, *, source_identity, warm)` | 排他建立持久 attempt，重新核对数据与备份后只调用一次零参数 `warm()`；成功返回完整逐库迁移证明，失败保留锁定状态。 |
| `check_current_after(attempt_directory, data_root)` | 新应用首次启动后再次停写、关闭连接，再只读核验全部数据库仍与成功 warm 后的逻辑状态完全相同。 |
| `verify_restored(before, restored_root)` | 只读校验控制器已恢复的完整旧组；不复制、覆盖或删除数据库。 |

`source_identity` 必须恰含 `head`、`tree`（40 位小写 hex）、`imageId`（`sha256:` 后 64 位小写 hex）、非空 `sourceHashes` 和 `runtimeHashes`。后两项均为安全相对路径到 SHA-256 的映射。完整对象及其摘要写入 attempt。**控制器负责核实这些值对应真实冻结源码、运行文件与镜像**；本模块校验结构并绑定记录，不把调用方声明当作独立镜像证明。

控制器必须先停止全部写入者、关闭全部数据库连接并处理 WAL；本模块拒绝符号链接、Windows reparse 路径及残留 SQLite sidecar。多库读取不是跨库事务，只有调用方停写前提成立时才能称全组停写快照。模块对原行仅计算散列，返回相对数据库路径中的不透明家庭 ID，不输出家庭名或私人正文。

## 顺序与持久记录

1. 控制器绑定冻结的包、完整源码/运行文件与镜像，停止全部写入者；调用 `snapshot` 保留 `before`。
2. 控制器运行现有全组备份，并将 manifest 与其全部条目按原相对布局复制到独立保留目录，例如 `proof/backup-group/backups/manifest-<stamp>.json` 和 `proof/backup-group/spaces/<id>/backups/household-<stamp>.sqlite3`。调用 `validate_backup`；缺项、重复项、多项、路径越界、重算 manifest 后的旧行漂移均失败。
   Linux 的只读备份连接可能留下原库 `-wal` 0 字节与 `-shm` 32768 字节。控制器在复制保留组之前调用 `finish_stopped_backup`，先对全组核原文件字节及备份，再仅处理这类完整空对；非空 WAL、任何 journal、孤立/非预期大小或链接 sidecar 均拒绝。SQLite 自行 checkpoint/close，不手工删除、不放宽迁移读取器。结果另存 `backup-finish.json`；失败不进入 warm/创建迁移 attempt，控制器既有发布失败记录仍禁止自动重放。
3. 调用 `warm_once`。`attempt_directory` 必须不存在、父目录存在，且与数据根互不包含。函数排他写入 `attempt.json`、`before.json`，再以 `O_EXCL` 在数据根写入 `membership-release-attempt.json`，所有证据文件请求权限 `0600` 并 flush/fsync。数据根标记绑定 attempt 文件、数据根及完整源码身份摘要。
4. 控制器的 `warm` 回调在已冻结、禁网的新源码容器内，对 registry 中每户构造一次应用，完成初始化并关闭全部连接；本模块不管理容器。回调之后必须仍能只读打开全部库。
5. 每户必须从原 58 表变为精确 61 表，平台从 2 表变为精确 9 表；逐库调用 `membership_migration.verify_household` / `verify_platform`，保留旧 users/password/role、所有旧行/列、schema/index/序列和平台记录，仅接受已定义的新增关系、空邀请/回执、session nullable 列、唯一 settings 标记及平台版本变更。备份原件和 manifest 再核未变。
6. 成功排他保存 `after.json`、`result.json`。控制器启动新 app 后，在开放正常写入和 worker 前再次停 app，调用 `check_current_after`；完整新 schema/行/列/序列/registry 必须与 warm 后相同。SQLite 容器文件的字节布局可因备份或启动而变化，逻辑内容不得变化。

成功、失败或仍在途的根标记都禁止重新执行 warm，包括改用另一个 attempt 目录。错误后只写固定错误码与 `automaticRetryAllowed=false`、`automaticRollbackPerformed=false`，不保存可能带秘密的异常正文。进程中断留下 started 或根标记也必须视作未决；不得据缺少 result 自动重试。

恢复由上层单独决定：继续保持全部写入者停止，保留本次所有原件，从已核验备份恢复**平台及 registry 全部家庭库**，调用 `verify_restored` 核完整旧逻辑状态，再由控制器核旧运行版本。函数不会删除 attempt/root 标记；是否在核定恢复后显式清理标记须由独立审查的控制器恢复流程处理。不能仅恢复迁移失败的单个家庭后继续发布。

## 本地实际验证

全部使用临时合成 SQLite；旧 `8e6a9954aec21ac69cf0c9d33817f631c4a789f4` 实际应用生成两户与私人记录，现有 `deploy/backup.py` 产生真实完整备份，固定新源码 `7b5b2c3b14b5727484fa6558e4e3a21074c4435a` 实际 warm 和 restart。测试 subprocess 封锁网络；镜像 ID 使用明确的合成占位身份，没有构建或运行 Docker。测试依赖本地已有的固定 Git 对象，未声称可直接在无 Git 历史的发布镜像执行。

原件均在作者树 `test-results/`，分轮如下：

| 轮次 | 实际结果与范围 | JUnit SHA-256 |
| --- | --- | --- |
| `membership-release-data-r1` | 1 个 fixture setup ERROR；Windows 长路径使原备份器无法打开目标，尚未进入 warm 测试。失败原件保留。 | `77d96ed4ffb54a82b49f5a85eb225519c999b0e38f4516c776e71a51439666fc` |
| `membership-release-data-r2` | 仅将调用的 `--basetemp` 改为新短路径；23 PASS，17.83 秒，无失败/错误/跳过。 | `c56a5f66106bb48ee1785d67c88a0b33bbd8f03f3da8ded5b071b3142493c32e` |
| `membership-release-data-concurrency-r3` | 新增一项真实线程在途竞争测试，单独运行 1 PASS，7.57 秒；原模块字节不变。 | `1f5d92067f8aacf69479db3636227e9f05f774100537428b2a32ede23ccc6aad` |

共覆盖 24 个不同用例，是 23 + 1 的分轮结果，未声称最终 24 项整套重新执行。每轮保留命令、stdout/stderr、XML 和 Python 输入前后散列。负例包括 registry 缺库/孤立库/非法路径、sidecar、备份缺项/重复/越界/漂移、部分迁移、旧密码改动、初始化异常、首次启动后私人数据漂移、证据篡改、完整恢复缺库，以及同目录/异目录/在途重放拒绝。

本证据不覆盖实际生产服务停写、容器网络隔离、镜像来源或远端恢复操作；这些须由上层控制器及其独立验收完成。

## 停写备份接缝修订

真实 Linux 合成演练 R1 的全组三库备份完成后，两户原库留下空 WAL/SHM，严格 `snapshot` 在 warm 创建 attempt 前拒绝；原失败目录保留。新增 [停写备份专项](../tests/test_membership_stopped_backup.py) 使用真实 SQLite 生成 sidecar，验证原检查仍拒绝、原生整理后整组字节和备份相等；非空 WAL、journal、孤立/错误大小、原库/备份漂移在全组预检时拒绝，仍有读连接也不能冒称完成。

Windows 作者验证原件在 `test-results/membership-stopped-backup-r1`（43 项：40 PASS、3 FAIL）。三项失败源于测试额外把实际采用 DELETE 的平台库也改为 WAL，导致备份平台副本本身产生 sidecar，严格检查正确拒绝；33 项原控制器测试全部通过。仅修夹具使其匹配真实父库模式后，`membership-stopped-backup-r2` 的 10 项新专项全部通过，11.69 秒，XML SHA-256 `060275a7a85294b1fe1bba56d9b4c27d59822154539a2217d62db2ddcb4ddcf5`。两轮各 357 个 Python 输入前后同字节；未重跑已通过的控制器测试，也未声称最终 43 项同轮通过。此时尚未执行修复后的 Linux 克隆补验或生产操作。
