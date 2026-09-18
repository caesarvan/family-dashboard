# Expo 助理旅行查找：发布适配器

本批是独立未绑定候选，未生成最终发布工具、打包、绑定或部署。父版本为已上线的[采购实付](EXPO-SHOPPING-SETTLEMENT-ACCEPTANCE.md#expo-shopping-settlement-release)，本批只接入显式旅行查找、打开原旅行详情与返回搜索，不增加后端路由或模型调用。

[prepare.py](../deploy/expo_assistant_trip_search_release/prepare.py) 从私有 `expo-shopping-settlement-tools-20260918-r1/` 九份实际固定 SHA 原件派生七算子、包准备器与绑定器。父 archive 为 `973c547235d6efd64369ecadb8003bb8d21e1847d8506fa3d13b2077a1921cd3`，manifest 为 `b5143c3bf4947772f0211d86c36cdb2aaed36d72f6b82e3ba8601ff2043c7efd`，实际 app／worker 镜像为 `sha256:c6246c280d19035ecc3b4ec49d8816cb019029a7a690a4285509ce73a9cf7cfd`。这些是父版本的实际安装身份，不是下一批新镜像。

## 范围与保全

- 必需修改仅 `frontend/src/screens/AssistantScreen.tsx`、`frontend/src/lib/assistantJourney.ts` 与原有 `tests/test_expo_assistant_journey_entry.mjs`。必需新增为 `tests/browser_expo_assistant_trip_search_check.py`、本适配器和对应 Python 测试；受审文档与实际导出仍由最终冻结清单明确列出。
- 父版允许改变的 `shopping_settlement.py` 加回不可变集合，仍固定 `90543ed9a2cbb41136a36d27da1558922fbf144030a50a689300ec15fd3e2067`。全部 39 个根级后端、原七个 `reviewedSourceHashes`、照片及旅行会话 pin、Docker、依赖、app、角色检查器和构建输入白名单保持。
- `household_members58`，58→58、无 DDL。当前角色值、全部行／schema／sequence 和 registry 必须完整满足 `before == after-app`，不重放成员初始化或迁移。先停写并完整验证、保留整组备份，再更新源码；原未知阶段与失败原件不得盲目重放。
- stage、validate、expo_contract 直接保留父字节；binder 函数及未变化的包、运行限制和备份辅助函数保留。包准备和绑定各自重新检查源码／构建输入／导出，不用前一次缓存跳过检查。
- post 沿用 39 条唯一匿名 GET 严格 401（父列表共 40 次请求，含一项已有重复），没有新增探测或匿名写请求。正常 TLS、静态资源／经典入口、配置摘要／权限、服务身份与新一次逐库在线备份守卫不变；在线备份不是跨库全局原子快照。

## 有界验证与交接

最终 Python 验证限定为 `test_home_assistant`、`test_assistant_source_search`、`test_assistant_journey_brief`、`test_household_spaces`、`test_household_members_migration`、`test_platform_backup`、`test_frontend_runtime` 与本适配器测试八模块。最终节点数只接受真实固定组合 collection；当前不预填。Node 旅行入口专项单独本地执行，`test_expo_assistant_flow.py` 不进入 Python 镜像验证。

本适配器的保护专项覆盖源 pin 缺失／畸形、路径／大小、Docker 不变、排他生成、非法冻结、禁止迁移 SQL，以及已有非空账户和普通 member 角色的真实临时 SQLite 保全、备份和重启。私有 CLI 用实际父九原件与归档核完整后端字节，在临时目录检查派生差异、原函数不变、敏感路径排除、必需构建输入、非法配置及未绑定入口拒绝；派生程序的子进程与网络被禁止。

作者在固定代码提交 `8a2326c183db74a5d7899fc1d861fd6d7693f215` 完成一次本地保护专项：8/8 通过、0 失败，pytest 2.29 秒；前后受验 Python 源码散列一致。私有原件位于作者工作树 `test-results/assistant-trip-search-release-r1/`：`results.xml` SHA `6e0e2ca37f61fe715d15bbc042d9ef907d3e1c784388d09637948f61035a81a1`，`record.json` SHA `0e772f83e44130e6894613253cac5754e2dd832fc5e5586187983a1c8f4a0eaf`。

同一代码提交的实际父九原件 CLI 检查退出 0，拒绝 124 个来源变更、18 个非法冻结，以及 2 个非法本地入口和 5 个未绑定阶段入口；核对 55 个未变父函数、完整 39 后端及原匿名清单。自己的两份代码和父九原件共 11 个输入前后散列一致。原件位于 `test-results/assistant-trip-search-pinned-r1/`：`record.json` SHA `fc061e276d5d303d5ffed9d5ed3892af888615b86dd085c520b321b2079a5583`，`stdout` SHA `c6d2f2d888d1f0e91f77254c1a04819b96bd3c653a823eef038f6137335e66f9`，`generated/generated-delta.patch` SHA `8e5570720a6cb758f029adf8a56278fbc5b0dc0a1acc08cf3367c6566ed9938e`。

该 CLI 只验证作者固定树当时的 198 项构建来源可被选择，不代表新 UI 的最终构建；浏览器文件尚待 Root 集成，已明确列入 `pendingFinalIntegrationFiles`。临时测试中的 `9991` 仅为合成 freeze 数字，最终八模块节点数仍须实际 collection。派生工具仅在临时目录用于拒绝检查，未生成最终发布目录、打包、绑定、远端或生产操作；非作者审查与最终组合验收尚待完成。
