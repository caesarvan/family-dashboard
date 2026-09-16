# Expo 旅行简报：55→55 发布适配记录（历史）

这是已用于 2026-09-17 07:38:17 旅行版本发布的固定历史适配器，入口为 [prepare.py](../deploy/travel_release/prepare.py)。实际安装身份见 [README](../README.md)，本次结果见 [发布验收](EXPO-TRAVEL-ACCEPTANCE.md#expo-travel-release)；旧 freeze、候选目录和已完成的发布步骤不得重放。它只读固定 SHA 的上一持仓版本九份本机／服务器脚本，在新的私有目录生成适配后的九文件和散列清单；不会执行生成代码、Git、SSH、Docker、数据库工具或生产命令。不修改旧算子及发布原件，也不重放 54→55 或历史 43 表流程。

## 固定基线与变更

本次发布当时使用的输入基线为 main `f2146f293541d0428b19546cb3539073d8a47321`／source `1bb434210f728af351fd9cd4b655b36b95cb1093`，manifest `3ce6cae326bb426703ab316c693a4e06c80c7fcae0abf853a9f8a9b31b7b43fc`，镜像 `sha256:3b831aaf898dacebcf3bb733ada13271e1be7707bb41ecfb14d85cb9d6ebf133`，旧归档 `a4f956af3b964fb9ea1296d06376ccd85b4186974aa6228b2ab4f8e56d625c08`。原件位于私有 `expo-holdings-tools-20260917-r2/`；原基线证据见 [验证记录](VALIDATION.md#expo-holdings-release)。本次新 Git、构建、完整文件变化和 Linux 测试选择／数量已另行冻结并发布；这组旧身份仅记录输入基线，不能作为当前安装身份或再次发布的参数。

适配保留原源码白名单、完整 Git／构建字节对应、不可变父镜像、七个服务器脚本的完整 SHA 绑定及精确平台跳过检查。Dockerfile 必须与旧归档逐字节相同，包括换行；requirements、Compose、Nginx、备份程序和财务／投资 schema 相关模块及检查器保持不变。生成器参数支持最终 freeze，不预设旧 446 个测试为本轮结果；没有 freeze 或缺少独立算子绑定时执行入口拒绝。

`migration` 三字段绑定沿用原格式，仅作为 `investment_operations55` 的 SQL／模块指纹。执行不含生产 migrate、旧基线校验、DDL 或“新增空表”操作。schema_definition 在内存数据库构造参考结构仅用于校验。Node／TypeScript 测试留在本地，不能放入当前 Python-only 镜像的选择。

## 保全与恢复边界

生成后的激活流程仍先保留旧源码、配置和镜像，再停 web、备份 timer 及全部数据卷 writer。读取完整 55 表与平台注册库，允许 `hub_investment_operations` 已有回执；执行整组备份、核对全部家庭映射及文件散列，并复制到发布目录保留。安装前再次比较同一快照。新 app 健康后核对全部行、schema、序列及注册库与安装前完全相等，通过后才启动 worker、web 和 timer。

证明文件为 `before.json`、`after-app.json`、`preservation.json` 和真实备份原件；报告明确 `schemaChange=false`、`originalTablesPreserved=55`、`newTables=0`。不伪造 migration／after-migration 证明，不继承 READY 的 `productionWrites:0` 当成激活事实。任一步失败保留现场，不自动回滚、覆盖数据库或重启服务。

最终读回复用新一次 backup service InvocationID 与新增 manifest 绑定；只对关闭且无侧车的备份文件用 immutable 读取。逐库在线备份不是跨库全局事务，`liveGroupSnapshotRechecked=false`。完整恢复沿用 [部署指导](DEPLOYMENT.md#6-备份恢复与回滚) 与 `check_investment_operation_migration.py` 的 `snapshot-current`／`check-restored`，恢复后失效旧会话并重新核对电视许可。候选合成恢复测试不等于生产恢复演练。

最终 post 脚本必须显式传入 `--reviewed-sha256 <独立审查确认的实际脚本SHA>`，不能无参数运行。本次首次包装调用漏传该参数，在 argparse 阶段退出 2，尚未执行主体；该失败原件保留。随后按已审查散列显式调用，07:39:46 正常 TLS 与新一次备份读回通过，详见 [发布验收](EXPO-TRAVEL-ACCEPTANCE.md#expo-travel-release)。这条参数约定不授权重放已完成的候选。

## 本地验证

[test_travel_release.py](../tests/test_travel_release.py) 用实际临时 SQLite 两家庭创建和删除持仓，保留非空回执，验证备份、app 启动、完整恢复及回执／schema／序列／注册库／家庭组漂移拒绝；测试同时覆盖固定字节、输出拒绝覆盖、路径限制和递归生成代码／嵌入 Python 的迁移调用检查。

普通 pytest 不依赖私有历史文件。另一个显式本地检查入口以 `--source-root`、`--git-repo` 和完整 `--git-revision` 读取真实固定算子及旧归档 Dockerfile，在临时目录生成并审查实际代码，验证缺绑定入口在任何网络／进程调用前拒绝。此检查不创建最终发布包，也不执行生产命令；本次新镜像 Linux 和正常 TLS 的实际结果见 [发布验收](EXPO-TRAVEL-ACCEPTANCE.md#expo-travel-release)，不能替代真实用户和实体设备验收。

作者本地实际执行 `tests/test_travel_release.py`：22 项通过、零失败／错误／跳过；另以真实九原件和 `afa9173d13058dad962d722e64463df0bb5d0084` 的 Dockerfile 执行显式检查，七个可执行入口在缺绑定／缺输入时拒绝，实际生成的保全断言接受 55 表／零新增／两家庭／四回执，并拒绝 54／56 表、意外新增、漏户、漏回执和保全标志为假。原件在作者 worktree 的私有 `test-results/travel-release-r2.xml` 与 `travel-release-operators-r2.json`，不入 Git。第一次显式 CLI 因导入根路径、第二次因相对 Git 路径被拒；补本地脚本导入路径并使用绝对参数后通过，当时没有生成最终包或执行生产动作。
