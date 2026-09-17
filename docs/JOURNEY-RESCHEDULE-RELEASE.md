# 旅行改期的 55→55 发布适配器

本适配器已用于 2026-09-17 11:09:53（北京时间）的实际发布，11:10:38 正常 TLS 读回通过；Linux 实际 603 通过、唯一精确 Windows 专用跳过。固定运行身份、失败修订与保全边界见 [改期发布验收](JOURNEY-RESCHEDULE-ACCEPTANCE.md#journey-reschedule-release)，当前安装版本见 [README](../README.md)。以下是本次已完成发布的历史输入与机制，不能重放旧候选或绑定。

`deploy/journey_reschedule_release/prepare.py` 复用上一轮 `deploy/trip_coordination_release` 的纯校验工具与实际私有 r2 九个固定脚本。逐字节 SHA 校验后，只在 access 根目录下创建全新的 `journey-reschedule-tools-<本轮标识>`；已有路径、符号链接、越界路径、输入漂移均拒绝。它不执行打包、绑定、SSH、Docker、服务控制或数据库操作。

本次发布前的固定历史输入基线（并非更新后的安装版本）：

- 安装清单：`b2095ebe61b64980f5d9d87a17d5b11e434ecf7e378232cdc91b8ffadaf0334f`。
- 原发布包：`e2314cd61234e3039fb988208e711aedee8a8c391e2cada68477b15dd2040c97`。
- 原 app／sync／media 镜像：`sha256:32b81bb0af5882333c1fafd5dfe9ca99b9eaf5c70999cd215dbe749bfad84c1a`。

最终源码、构建输入、导出资源、完整新增／修改／删除文件及实际测试数量通过独立 freeze 文件绑定，没有默认候选 HEAD 或虚构成功计数。必需验证集合为上一轮 16 个 Python 模块，加 `test_journey_reschedule.py` 和 `test_journey_reschedule_release.py`；Node／TypeScript 桥接测试继续在具备依赖的本机构建环境单独执行。最终 Linux 结果必须实际取得，不能由收集数量推断。

## 允许变化与保全

唯一 Docker 变化是把原 `COPY finance_source_bridge.py journey_time.py ./` 的 CRLF 行替换为包含 `journey_reschedule.py` 的 LF 行。其他字节必须完全一致；不整体转换换行。新模块必须同时进入源包、动态运行文件清单与 Docker COPY。Compose、依赖、备份、财务 schema、成员会话和既有地点／日历模块保持原字节。

沿用已审的完整 55 表和注册库停写备份、恢复输入验证、源码安装前核对、app 启动后行／schema／序列对等检查及新一次逐库在线备份。允许既有操作回执非空；不运行迁移或初始化。激活报告不能继承 READY 阶段的 `productionWrites:0`。发布后在线备份不是跨库全局原子快照，也不冒称再次核对 live 全组快照。

`stage.py` 和实际 r2 `validate.py` 保持逐字节不变，包括隔离验证的 768 MiB 内存和 512 MiB tmpfs。激活只更换本轮发布名称；读回只另加两个新增 GET 接口的匿名拒绝检查。旧环境摘要、web 镜像、锁顺序、备份调用、回滚材料和 TLS 检查不放宽。本次最终九份生成文件经独立审查后绑定并执行；下一次发布仍须新冻结、独立审查和新绑定，历史候选不能重放。post 入口继续要求独立审查确认的 `--reviewed-sha256`。

## 本地验证

在专属 worktree 用 `python -B -X utf8 -m pytest tests/test_journey_reschedule_release.py -q -p no:cacheprovider` 执行合成 guard 测试。

同一测试文件的显式 CLI 接受 `--source-root`、`--git-repo`、`--git-revision`，校验私有旧包和九个实际原件，在独立临时目录生成候选，并阻断生成脚本的一切网络及子进程调用。它核对真实归档 Docker 与指定 Git blob 的唯一差异、动态运行清单、错基线／漏必需测试拒绝、递归嵌入代码无迁移／DDL，以及全部七个执行入口缺少绑定时拒绝。此检查不生成正式 freeze 或操作批准，不执行生产发布。

业务契约见 [旅行改期](JOURNEY-RESCHEDULE.md)。本人真实云改期、真实账户、模型与电视设备仍按实际验收单独记录。
