# 旅行实际费用 73→75 Linux 合成迁移演练

本工具为独立候选，只准备与校验合成演练；此文不声明 Linux、生产迁移或上线通过。复用[视频迁移演练](MEDIA-VIDEO-MIGRATION-LINUX.md)的容器、完整库组恢复程序和隔离约束，使用[旅行费用迁移器](JOURNEY-FINANCE-MIGRATION.md)，不改旧发布策略或生命周期。

## 固定输入与真实边界

`prepare` 只接受 `a47372624e66cab0e8100a37f54223737780eb73` 加本工具、测试、本文三个文件。固定历史源为实际父版 `53ea3fdb571eae69154e61d264f3c3542631cb49`：导出全部根 Python 模块，核对其与原迁移夹具所用 `dc2b54cfc7fc9063eb839ece87fdab72a21855be` 根模块集合和字节相同、不含新 `journey_finance.py`，并核对候选 requirements 未变。历史 app 在候选镜像依赖环境中真实创建旧库，不复制 DDL、不删新表来伪造旧库。

闭合输入包含当前全部根 Python、deploy Python、原夹具 SQL 的 Git 源、恢复文档和十段生成程序；每个文件都有 SHA，目录不得混入额外文件。容器无需 Git、pytest、真实账户、生产配置或数据库。

- `sourceHead/tree`：本工具冻结 Git 提交及树；`runtimeSourceHead`：固定 `a473726...`。不能将工具提交冒充最终应用包源。
- `runtimeFiles`：Docker COPY 的根 Python 和 requirements 精确映射。首阶段核对实际 `/app` 根文件和 UID，所有后续迁移程序再次核对。迁移 reader、五个初始化依赖及旧辅助源码从已绑定的只读 release 加载；初始化依赖允许实际 `/app` 路径，但必须与 release 字节相等。
- `imageId`：调用者提供实际不可变镜像 ID；最终发布准入还须把该 ID、完整候选包、manifest、根运行映射及 reader 闭包逐项绑定。本工具不验证候选前端，也不创造未来包身份。

## 十个阶段

1. `verify`：实际镜像根运行字节及 UID 10001。
2. `seed`：历史 Flask 登录、邀请、成员与待办真实路径建立两户三库 73/9；添加固定合成财务、购物、路线、提醒、媒体缓存、电视播放及旧回执哨兵。
3. `migrate`：复制独立失败场景库组，完整备份主场景三库，调用实际 73→75 初始化器。
4. `startup`：仅调用候选 `/app/app.py` 的真实 `create_app()` 并初始化全部家庭；进程退出后才继续，无服务器、云 worker 或 decoder。
5. `check`：严格保全旧 73 表所有 schema、列、行、settings、序列、旧触发器及平台 9 表；新两表为空，不设豁免。
6. `rollback73`：原文档恢复算法恢复完整三库至全新目录，核对旧 73/9。
7. `partial`：将第二户数据库设为 0400，UID 10001 下必须实际写入失败；观测第一户 75／第二户 73，禁止重放原迁移，完整三库恢复后核验。
8. `populate75`：每户写入 `hub_journey_allocations: 3`（active、revoked、orphan）与 `hub_journey_allocation_operations: 1`。这是固定存储保全夹具，不冒充 API 创建或真实财务输入。其余全部表不变。
9. `restart`：实际 app-only 再启动，保留非空分配和回执。
10. `restore75`：完整备份并恢复非空 75/9，再核全部逻辑内容、marker 和三库集合。

完整恢复仅将原文档目标根路径改为独立新目录，算法不变；合成会话保持以便严格比较，恢复后不启动服务，不替代生产回退时的会话失效和服务切换。失败原件、备份和阶段输出保留，不能在原目录覆盖重试。

## 最短调用

入口 `python -B deploy/journey_finance_migration_linux_probe.py`：

| 操作 | 参数 | 范围 |
|---|---|---|
| `prepare` | `--repo --commit --output-dir` | 本地固定 Git 导出；输出必须全新且在仓库外 |
| `verify` | `--bundle --input-sha256` | 只读全文件、输入及工具自身字节核验 |
| `run` | `--bundle --input-sha256 --image-id --output-dir` | 另行授权后由 Linux root 调用本机 Docker |

可从 bundle 的 `release/deploy/journey_finance_migration_linux_probe.py` 执行。每阶段一个容器，network none、根只读、UID/GID 10001、cap-drop ALL、禁止提权、1 CPU、384 MiB 内存及同额 swap 上限、128 pids、128 MiB noexec/nosuid/nodev tmpfs；只读源码与程序，仅新建合成 data/proof 可写。只收停本次返回的已核 CID，不碰 Compose、生产挂载、端口或其它容器；不接受环境 Docker/Compose 选择器。

本地定向检查仅证明输入约束、命令隔离和真实 Python/Flask/SQLite 八段闭合路径。Windows 把准备源码目录作为 runtime，明确记录其实际文件集；这不是 Linux 镜像 `/app`、UID 或 0400 部分失败证明。后续实际 Linux 十阶段结果必须单列，不能用旧 71→73 或本地通过替代。
