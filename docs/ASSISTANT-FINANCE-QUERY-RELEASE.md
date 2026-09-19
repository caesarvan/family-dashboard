# 助理财务查询：发布工具候选

本工具只准备从已发布的 AI 旅行改期版本更新源码与 Expo 静态文件，数据库保持 **66/9 → 66/9**。工具存在、合成测试通过或离线组装成功，都不表示已经具备发布证据或已经上线。新 API/UI 的组合、真实 Expo 构建、Linux 镜像验证、双户演练、独立审查和最终计划均须由集成人另行取得原件。

## 固定已安装基线

| 项目 | 身份 |
|---|---|
| 运行源码 | `4c5988874d9f2b206030f6cd42864013db62454b` |
| tree | `8647c0398949d063b3e1a8aef10647b6a69e3a74` |
| 父镜像 | `sha256:5fc52d2cef49c1fa854bd1e34faf23dc661b8e4ed7822b5e6763bf5798f42dce` |
| manifest | `aa116533c6c725f8499f10bc6ac01c55645b69c659b1ae970a143eb1ae7b0696` |
| 已安装 package | `e2ab1963fb5a5d013d7c2cce718d764273ee55ea8e3b622be7cf4b9222d4f035` |
| 已安装版本只读审计 | `d9788b0434e49c45cfae59d065eedae7778383c341bcc7f05521bef6fd7ce2c3` |
| Docker 原字节 SHA-256 | `5856bdc2ef145f133084c879d92714f9aaa48301b6af5c941abaab64ef6895bd` |
| Docker 新字节 SHA-256 | `f68324febf8438eb7e0ed1277998e33510c948503a8cf9c633062ba8027cdefb` |

Docker 仅在原 `assistant_trip_intent.py assistant_trip_change_api.py` COPY 之后增加 `COPY assistant_finance_query.py ./`。新字节从 wiring 固定提交 `927cfb70089771b10a148118ef57edc7968a4d8d` 的 Git blob 核对；后续 harness 修订不改变 Docker。此作者分支不修改 Docker、app 或前端。

## 入口与复用边界

| 文件 | 职责 |
|---|---|
| [新 profile](../deploy/assistant_finance_query_release_profile.py) | 固定上述身份、允许的根文件变更、完整新增运行模块与前端测试文件 |
| [package 入口](../deploy/assistant_finance_query_release_package.py) | `prepare`、`verify`、`build`、`validate`；复用 membership package/build 并显式绑定新 baseline |
| [plan 入口](../deploy/assistant_finance_query_release_plan.py) | 在全新独立目录离线组装，不接触 Docker 或生产 |
| [controller 入口](../deploy/assistant_finance_query_release_controller.py) | 仅绑定新身份；复用既有停机、备份、安装、启动保全与故障停止 |

新 baseline 为 `assistant-trip-change-r1-finance-query`，计划类型为 `assistant-finance-query-release-plan`。不可变 `ReleaseSpec` 由固定 Python 入口选择；没有从计划 JSON 或 CLI 指定任意模块/profile 的入口。历史 baseline 的常量、默认包格式与原 14 个算子名单保持不变；新计划绑定 18 个算子，包括四个新入口/profile 和实际执行的共享 controller、plan、package/build/data。`controllerSha256` 绑定新薄入口，另核对实际导入位置；共享实现同时受 `operatorHashes` 与包源码双重绑定。

新包必须保留全部已安装的 inventory/finance/trip 模块，并包含 `assistant_finance_query.py`；新增前端专项只明确允许 `frontend/tests/assistantFinanceQuery.test.mjs`。根业务文件允许变更的范围为 `app.py`、`finance_hub.py`、`assistant_finance_query.py`、`Dockerfile`、`README.md`。依赖、compose、nginx、环境摘要与旧运行模块删除仍受原严格检查。

## 数据与执行顺序

直接复用 [66/9 populated 数据适配器](../deploy/assistant_trip_change_release_data.py) 的 `begin` 与 `check_stopped`。其历史 `assistant-trip-change-release-attempt` 字符串是保留的备份证据格式；每次仍绑定本批计划摘要、源码身份及独占 proof 目录，不把旧回执当作新操作。不会调用 membership/analysis 迁移或 warm；数据适配器导入的旧模块只用于已有严格快照、表集合及恢复检查。

保持既有顺序：检查固定计划与运行基线 → 只读 stage → 核对 stage 回执 → 保存旧源码/配置/镜像 → 停备份定时器及全部写入服务 → 全户完整备份并验证 → 安装源码 → 实际新 app 启动 → 停 app 并比较完整 66/9 数据和 marker → 恢复 app/worker/web → 核对运行源码、环境键值和健康状态 → 恢复备份定时器。候选启动后的失败必须停止写入者并保留证据，不自动恢复旧应用或复用旧 activation。

新发布目录使用 `assistant-finance-query-66-` 前缀。所有 prepare/build/validate/assemble 输出必须是独立新目录；旧已消费发布算子与计划不得拿来重放。

## 验证与尚未就绪项

专项 [测试](../tests/test_assistant_finance_query_release.py) 使用临时合成 Git/包/计划、受控记录式 runner；覆盖新模块缺失、额外 COPY、依赖与前端未授权输入、旧计划/父镜像/manifest、环境与算子哈希篡改、未知入口、精确 JUnit/原件绑定，以及备份/启动/保全/恢复服务顺序和失败停止。原 [trip 发布专项](../tests/test_assistant_trip_change_release.py) 继续验证旧默认 profile。记录式 Docker 回答不是真实 Docker 或 Linux 验收，合成 JUnit 是组装测试输入，不是业务通过证据。

提交交付时提供真实 pytest stdout、JUnit、命令、返回码及前后源码 SHA，保存在忽略的 `test-results/`。这些测试不读取真实订单、密钥或生产库，不启动模型请求。

2026-09-19 本地 Windows 专项实际 **77 passed / 0 failed / 0 error / 0 skipped**，exit 0，343.65 秒；范围仅为上述两份 release 专项。原执行记录为 `test-results/release-specialized-r1/execution.json`，同目录保留 `stdout.txt` 与 pytest 原生 `results.xml`，被测源码前后哈希一致。另有 AST 比较证明原部署生命周期仅替换发布目录前缀，备份及停机后比对等六个方法原样。尚未新增真实 Linux、业务组合或生产操作。

发布前仍待新完整组合的 fresh Expo、真实浏览器、实际 Linux 构建与精确选定测试、以当前 `5fc52d…` 父镜像创建的双户三库非空 66/9 演练、最终包/算子/审查映射及独立计划审查。旧批 448 项 Linux 通过与真实模型记录不能替代本批证据；本人 A–D 验收、生产新 POST、真实模型/云及实体电视不由本工具测试证明。
