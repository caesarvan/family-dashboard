# 本地任务依赖发布适配

状态：本地待办前置事项已于 2026-09-20 06:28:25（北京时间）发布，06:35:47 独立只读审计通过；实际身份、分段验证与未验边界见[集中验收](TASK-DEPENDENCIES-ACCEPTANCE.md#task-dependencies-release)。下文保留本模块开发／工具合同，不将作者阶段结果扩写为真实云、提醒通知或实体电视验收。

## 固定父版本与范围

父版是 2026-09-20 05:15:29（北京时间）实际激活、05:16:46 独立只读审计通过的资料／照片搜索版本。包源码与后续 Git 合并提交分别记录，不能用 merge commit 替换包身份。

| 父版本原件 | 固定身份 |
| --- | --- |
| source / tree | `fd3ef3692528a18e3e6afc779fb15efe8463d559` / `419b5b62f962cb06e1fa52a8f2af541e44189452` |
| image | `sha256:3c572b73396b71dd651e1a02e9774484f06d50476d6d3b6a2a50b6306bb1b747` |
| package | `3da0f27a68eb375f5fddd0ad69c227018b869a7266ae93442935458cc87dfe9a` |
| manifest | `da779fc25df1b6df3c71c50851355bb452fb0afa65cde7b829a8b2604bd23b0c` |
| production audit | `0cab19c440085447f5db199a0797a231bd9fc3c2096eb9a04d04604bf31c103b` |

固定 profile 为 `assistant-document-search-r1-task-dependencies`。新入口为 `deploy/build_task_dependencies_release.py`（prepare / verify / build / validate / assemble）及 `deploy/activate_task_dependencies_release.py`（stage / activate）；父版已消费的计划不可重放。

非 Expo 运行文件从 104 增至 105：新增 `task_dependencies.py`，允许修改 `app.py`、`cloud_accounts.py`、`data_portability.py`、`home_assistant.py`、`household_routines.py`、`journey_workflows.py`、`task_publish.py`。其余 97 个文件的名称／哈希映射必须保持 SHA-256 `cddfd03c86a5ce77d023178438bd56e7c410d555bd44c7f8ef9a4c6c8f614b42`；元数据不能增加豁免项。实际 runtime 仍须与新包完整一致。

Dockerfile 仅在 `COPY task_publish.py household_routines.py ./` 中加入新模块，并保留原行 CRLF。固定前后哈希为 `36f5d699823890c26dbc243010f584c5aa5d44c109bd6e63b705e9e025a2a90b` → `6960db583e7c84dbeddd3c026054b989a878e31e56c9787728c9e9cde3bfebc9`。Compose、环境、requirements、前端依赖和固定 `prepare_release.py` 白名单不变。

新包强制包含 `frontend/tests/taskDependencies.test.mjs`、既有前端输入及唯一指定的 `scripts/check_expo_task_dependencies_browser.py`；只增加这一精确路径，其他 `scripts/` 文件不会入包，也不通过发布变更准入。浏览器执行与结果另验，脚本入包不等于流程已通过。

## 验证与发布边界

复用 `membership_release_build.py` 已审的冻结 nodeid 验证器：模块白名单、源码身份、实际收集集合、逐节点结果、无意外 deselection 和跳过合同均保持。正式 Linux selection、包、镜像和测试结果必须绑定本批新原件，不能沿用父版 175 项结果作本批验证。

新 controller 继承已审资料搜索控制器及 `assistant_trip_items_release_data` 的 69/9 生命周期，29 个发布工具的字节均由计划绑定。所有写入服务停止后先保存完整库组备份，核验全部户内 69 表、平台 9 表和根 marker，再安装并真实启动候选应用，核对完整 schema、行、列、序列及 registry 家庭集合，最后恢复 worker 和备份 timer。没有 DDL、旧记录回填或自动恢复；失败保留停止状态及证据，不能自动重试已消费计划。

本批定向发布测试使用临时 Git／tar、合成包与记录式 controller，验证 97 文件保全、精确脚本路径、固定 Docker／依赖、计划身份、69/9 顺序及失败不可重放。它们不启动 Docker、不读取生产库、不证明实际停机、真实账号或电视行为。正式构建、浏览器、Linux、stage / activate、生产只读审计与本人 A–D 完整验收分别记录，未完成项保持待验。
