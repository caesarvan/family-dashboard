# 本人旅行费用：固定 73→75 发布适配

本固定适配已用于 `302a62d` 的实际73→75发布，结果见[集中验收](JOURNEY-FINANCE-ACCEPTANCE.md#journey-finance-release)；本次计划已消费，后续部署须基于届时实际父版生成新计划。只接受固定 `journey-finance-73-to-75` 模式，不接收任意模块、schema 或服务策略。

父版固定 source `53ea3fdb571eae69154e61d264f3c3542631cb49`、package `44f8d8c3fd9a5a91e5cfde9e1893c89be345a2d5445b2636c77e3d5733e3466f`、manifest `e6898a234eb21c20a28b08a9bc48241202380c3857210f18b0278ad02a3b0ed9`、应用镜像 `sha256:cdbe4702e9fc1b7557e8cefb84b664b6d8c369fb0d9788e0235ff426f3c18ac2`。父费用批次见 [FINANCE-FLOW-ACCEPTANCE](FINANCE-FLOW-ACCEPTANCE.md)。父计划已经消费，只允许作为继承证据读取。

## 包和验证输入

`build_journey_finance_release.py` 调用原共享 packager/builder。113 个非 Expo 运行文件中 110 个保持父版字节；固定新增 `journey_finance.py`，仅既有 `app.py`、`data_portability.py` 改注册和本人导出。Dockerfile 只接受已审新 COPY 字节；Compose、Nginx、依赖和 decoder 原四文件不变。完整前端、九 supplemental 输入、`tests/test_expo_journey_finance.mjs` additional 输入及导出必须匹配实际新构建；不因后续部署工具提交要求重新构建未变前端。

Linux selection 固定 API 作者最终 46 节点（44 新＋2 相邻）、五模块 SHA、零跳过；新镜像必须真实验证全部运行／安装源码及实际加载模块前后不变。新镜像 ID 和最终 Git head 取实际构建，不在工具里虚构。

`prepare_journey_finance_activation.py` 要求 package/build/validation/selection/parentAudit、六角色独立审查（source/browser/release/linux/resources/migration）、新 `migrationRehearsal:{input,run}` 以及 image_overlap/nginx_raw/duplicates 原件。`retainedFinance` 固定父 package/build/plan，`retainedDiscovery` 保留其既有上游。两套已消费 plan 仅用于读取原文件散列；不得作为当前 stage/activate 入口。

旧媒体／重复提示原件在校验父包完整归档、原构建、全部原件后重新进入既有验证器。新旧 app／导出 AST 仅剥除精确新增节点后比较全部余下语法树。继承只证明原媒体／元数据负载；不称新费用负载、75 表恢复或无限资源容量已验证。

## 新迁移与五服务

新演练沿 [迁移合同](JOURNEY-FINANCE-MIGRATION.md)，必须实际使用最终候选镜像：两户三库、73→75、app-only 初始化停止后完整保全、75/73 部分失败拒重放、完整三库恢复父73、非空75重启与完整恢复。新表内容为 active/revoked/orphan 三关联及一回执，不从旅行预算、paid、采购或原付款回填。

演练工具提交与最终候选提交可以不同；输入必须明确 operator source/tree、固定 runtimeSourceHead，并逐字核候选所有根运行文件、迁移 reader 与真实五模块导入闭包。返回证明保留这三个来源，不把旧73恢复改写为新75演练。缺失或失败的实际演练不能准入。

控制器沿原独占锁、不可重放 attempt、固定父五服务身份与 timer 处理。停止原 writers 后完整备份 → 新 reader `migrate` → 安装 → 只启动 app 初始化所有家庭并停止 → `check_stopped` → 核迁移与保全的 plan/source/group/logical 同一性 → 启动 decoder、workers、web → 正常 TLS 健康检查。实际迁移回执不能用备份回执代替。

任一步失败保留原件并停止本次已核 candidate/helper，不自动恢复数据库、不自动重放迁移或启动旧版。明确完整组恢复后 `verify-rollback` 只读核父73；75上线后新费用记录不能由旧73备份无损恢复。新75稳态使用独立 `journey_finance_release_data`，旧默认 reader/controller 行为保持。

## 本地验证边界

专项检查使用真实临时 Git 归档、固定父字节、合成 Expo 输入／演练回执及录制型 Docker。它们核工具门禁和生命周期，不代替真实构建、46项Linux API、新迁移演练、生产或本人／实体设备验收。迁移 reader 的真实 SQLite 检查由其独立作者和审查报告保留；本适配不重复执行业务全组。
