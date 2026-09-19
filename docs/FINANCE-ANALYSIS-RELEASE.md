# 本人账户分析：61/9 → 66/9 发布合同

本批是候选发布工具；本文不表示已经上线。集成人在独立审查及组合验证通过后，才构建、演练、组装并执行发布。API 见 [本人账户分析](FINANCE-ANALYSIS-API.md)。旧的账户三表常量、已执行的 55→58 和 58/2→61/9 迁移保持；不能重放它们，也不能重用已经消耗的 `followup-r1-steady` 计划。

## 固定起点与允许变更

新 profile 为 `order-inventory-r1-finance-analysis`，集中在 `deploy/finance_analysis_release_profile.py`。它只接受当前本人订单关联库存版本：

| 身份 | 完整值 |
|---|---|
| 已安装 source | `fe0c56ba5537e70207ae5b98213e3daa1daef95a` |
| 已安装 manifest SHA-256 | `c4d5ecc38675e6d9d97569664cb8141d4cfd030f52c6086449b8ea8d84ebf080` |
| 父镜像 | `sha256:32905e70879d28f36b0e584d69f03434e4a1bf38e580c0ca1aeb1ed7ae3a3cc6` |
| 独立只读审计 SHA-256 | `feee58ab01565aa0ed061edf013d46f7414b369e7b36b811ae849f27a18c2625` |
| 新 Dockerfile SHA-256 | `b1668b82416b3afa86ed8dc138fd6183204faeb6b0f89871381f9fb633d86116` |

Dockerfile 只增加 `COPY finance_analysis.py finance_fx.py ./`。依赖、Compose、nginx、环境文件及每个服务自己的最终环境保持。根目录仅允许 app 注册、本人导出、两个新模块、Dockerfile 和 README；前端、生成资源、文档、测试、发布工具按包与审查清单绑定。拒绝旧 runtime 删除和未列明的根模块变更。

## 接入、导出及 schema

`app.py` 在原 `register_finance_accounts` 之后注册 `register_finance_analysis`。后者初始化四张分析表和公共 FX 表；新 app 启动后必须证明旧逻辑数据保持。Docker、包 runtime 白名单同时加入两个新模块，保留既有 `inventory_sources.py`。

只增加以下五张户内表及其声明的索引，平台仍为九表：

- `finance_account_profiles`：本人分类和流动性。
- `finance_account_cashflows`：本人明确登记的原币资金流。
- `finance_account_reviews`：本人明确确认的区间及上下文摘要。
- `finance_analysis_operations`：本人操作回执。
- `finance_fx_rates`：带版本与来源的公共参考汇率。

`deploy/check_finance_analysis_migration.py` 从两个新模块读取唯一的字面量 schema 常量，拒绝其它 SQL、其它目标、重复表与对象碰撞；绑定源码 SHA、SQL SHA、sqlite_master 对象及列。迁移先保全完整注册库组，再对每户执行单个显式事务。跨户不是原子事务；中途失败保留已迁移部分和不可重放的 attempt，停止后续启动。

本人 ZIP 中 `personal.financeAnalysis` 由核心模块固定字段投影，仅含本人的 profiles、cashflows、reviews 和最小操作摘要；`includeShared` 不扩大此范围。原账户、估值和其它财务分组继续独立。公共汇率放在 `referenceData.financeFxRates`，按日期倒序、币种和版本固定排序，最多 10,000 条；coverage 明确总数、导出数、上限、是否截断，且不承诺重建历史报告。未来额外字段、操作 payload、结果内部字段和另一成员数据均不自动导出。

## 离线准备与证据

复用原严格包、构建与验证实现，通过新 profile 调用；历史 baseline 的镜像、manifest、Docker 和 23 文件规则不改变。新 Expo 导出为有上限的完整清单，必须和构建证据逐文件及所有前端输入逐字节一致，且恰有一个 entry；文件数不替代内容验证。

在未启动生产操作的候选目录运行：

1. `python -B -m deploy.finance_analysis_release_package prepare ...`：干净的固定 commit、完整 Expo evidence 和全新输出目录；输出 package SHA。
2. 同模块 `build ...` 与 `validate ...`：固定本地父镜像，只增加清除旧 Expo／COPY 两层；无网络、不安装依赖、不挂生产卷。精确 selection 列明模块、nodeid 和唯一许可 skip。
3. `python -B -m deploy.finance_analysis_release_plan ...`：核对 package/build/validation、逐项 JUnit、selection、独立审查文件和所有 operator 源码散列，组装全新 candidate，返回待审 plan SHA。此步骤不调用 Docker、不停止服务、不读真实库。
4. 独立复核实际 candidate、plan、镜像、schema 和演练原件后，由集成人执行 `finance_analysis_release_controller.py stage <candidate> <plan-sha>`，随后才按批准执行 `activate`。CLI 只接受 Linux root、`-B`、非 optimize 和固定候选父目录，拒绝 ambient Docker/Compose selector。

## 实际激活顺序与失败边界

stage 与 activate 都核对旧 manifest/源码、候选 runtime、审查测试证据、环境和成功 membership marker。激活依次：保留旧源码／原 Expo／环境／镜像；停止备份计时器和所有写入服务；确认干净退出和无人挂写数据卷；读取本次当前完整 61/9 数据组；创建完整逐库备份并将原 manifest 与所有 SQLite 文件保留在发布 proof 下。

`finance_analysis_release_data.begin` 复用严格 61/9 停写备份流程。`migrate` 在任何 DDL 前再次核对 before、完整原备份、源码身份及 marker，独占创建 `migration-attempt.json`，然后只建五表。核对全部旧表行、列、schema、`sqlite_sequence`、application/user version、平台所有数据和家庭集合；新表须为空。成功后保存 `migrated.json` 和 `migration-result.json`。

随后安装源码并启动新 app，核对健康、镜像、runtime 和原服务环境，再停止 app。`check_stopped` 重核原完整备份、所有旧数据、仍为空的新表及迁移后逻辑指纹；只有通过才启动 app、sync、media、web，并做正常 TLS health 和备份计时器检查。任一失败留存原件；候选曾启动时执行停止并检查，无法确认停止时不声称停止成功。不自动恢复旧应用、回滚数据或重放 activation。

## 恢复与验证

备份仍使用 [完整组恢复程序](DEPLOYMENT.md)，选择原 manifest 的 platform、default 和全部注册家庭；不能单独恢复一户或只恢复注册库。原 membership 成功 marker 原件也必须保持。新表出现后不能让旧镜像继续写入。

完整回滚先停写并恢复 `proof/backup-group` 内的完整 61/9 组及保留的旧源码、Expo、镜像和原环境；新 app 不得在核对前启动。`finance_analysis_release_data.verify_rollback(proof, restored_root)` 只读比较全部原逻辑指纹与 marker。只有完整组相同后才进入既有恢复后会话失效步骤。实际生产恢复仍须集成人按现场状态执行，不由控制器自动处理。

已使用的新 66/9 数据，先用 `snapshot_current(root)` 留下封闭组指纹，执行正常完整备份及恢复，再由 `verify_restore(reference, restored_root)` 核对精确五表 DDL和全部数据、序列、平台与 marker，随后才失效恢复会话。此验证允许五表已有业务记录，不能用“新表为空”的发布检查代替日后的备份恢复验证。

新增测试覆盖真实临时双户三库迁移、原数据/序列/DDL/平台漂移、预检拒绝、失败重放、部分迁移后的完整回滚、已填新表恢复、本人 ZIP 与公共汇率截断；控制器测试记录调用与故障顺序，不代表真实 Docker 或生产操作。实际命令、计数和固定 head 以交付记录为准；本地候选测试不代表生产发布、真实金融输入或实体电视验收。

作者于 2026-09-19 在独立临时组合目录使用核心 `12feddd89d9847ba5c96b8cfddd62f4fedfc65ed`、FX `5e121f177cd15b3767c6c32cf1e5548948092868` 和本批接线，实际完成新迁移 17、新导出 3、原账户及通用导出 8，共 **28 passed，57.74 秒**；无网络、真实 SQLite、双户三库及实际 app 工厂重启。新 package/plan/controller 21 项及一个旧 Docker pin 回归共 **22 passed，105.70 秒**；这部分用记录型 runner，不调用真实 Docker。原包与 steady 的首次组合执行为 92 通过、1 个旧 Docker 测试 fixture 失败；修正后该精确 case 已在上述 22 项中通过，不相加为一个单次全套计数。

额外尝试旧 55→58 migration suite 时，其 fixture 仍要求旧两表平台注册库，在关闭本批分析初始化后依旧出现 `registry_tables`；27 项 setup error、6 项通过，原件保留，旧检查器未放宽、旧测试未修改。本批使用专用 61/9→66/9 测试取得迁移证据。新导出测试首轮两项因测试误写现金流响应为 201 失败，按 API 的 200 回执合同修正后已在最终 28 项中通过。JUnit 保存在作者 worktree 的忽略目录 `test-results/`；任何生产演练、激活或实际账户验收仍未在此作者阶段执行。
