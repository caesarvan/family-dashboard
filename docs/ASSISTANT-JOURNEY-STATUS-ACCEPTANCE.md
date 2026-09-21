# 旅行准备查询：候选验收记录

**尚未发布。** 本页记录已完成的候选检查，不改变当前生产电视回顾版本 `d4346d3`、77 张户内表／9 张平台表和五服务状态。本批没有 DDL，候选运行变化仅 `journey_workflows.py` 与前端；后续实际包、镜像、计划和部署身份取得后再补，不以文档提交或构建成功代替上线。

用户路径见[操作指南](ASSISTANT-JOURNEY-STATUS-USER-GUIDE.md)，权限、分页和响应见[冻结契约](ASSISTANT-JOURNEY-STATUS.md)。本片是查询已有旅行准备情况，再打开原旅行处理并返回刷新；查询本身无业务写入，不调用模型或云服务。

## 已完成与待完成

| 范围 | 已有实际结果 | 不能据此声称 |
|---|---|---|
| API `bc3619d05553b62cdf3a83893e92b54bcc279467` | 47 个唯一节点、50 次分轮执行，最终均通过；45 个专项及 2 个相邻节点。真实 Flask／SQLite 覆盖两户、成员／TV、撤权、双快照、原 ID、旧旅行、坏关联、上限、依赖和分页版本。根非作者源码／原件审查通过 | 不是候选镜像的 Linux 执行，也不是本人真实数据验收 |
| UI `2a89eaa5…` → `594b455347584690905898ec1b752ceff6084310` | 原 28 个唯一节点／30 次分轮执行；三项 P2 修复另有 4 个受影响节点／5 次执行及两组 tsc。增量非作者审查通过，原列表、未知保存和原 ID 恢复问题闭合 | 两组有重叠，不未经去重相加。受控 React 宿主与模拟网络不是实际浏览器或服务端提交证明 |
| 发布适配 `77cc8f60edc399076d71f50660f9e75153f684b4` | 18 个唯一节点／20 次分轮执行通过；根源码审查与非作者测试证据审查通过。固定父版、114 个非 Expo 运行输入中 113 个保留、47 节点选择及五服务 77→77 流程有检查 | 录制执行器不是新一轮实际 Docker、生产备份或恢复证明 |
| Expo `69ffb5cd0bb6fef38ae146705c742294b500d4a8` | fresh `npm ci`、应用 tsc、测试 tsc、Expo export 四阶段实际退出 0，23 个导出文件；完整输入／输出由 build evidence 绑定 | 本轮四阶段没有另跑 Node 用例；构建不替代浏览器或最终包验收 |
| 真实浏览器 | R1 两场景均在复制合成夹具时因 Windows 临时路径过长提前失败，未进入 UI，0 条流程通过；短路径 wrapper 已静审，补验待取得结果 | 不把夹具失败称为业务验证；不能用 UI 宿主检查替代 |
| 候选 Linux／最终发布 | 本页截止时尚未执行；实际包、镜像、计划、stage／activate／readback 待取得 | 不提前填写未来 SHA，不将旧媒体、迁移或生产原件改写为本批新实测 |

旧失败保留：API 首轮的 fixture／忙锁响应失败与后续窄修分轮记录不抹去；UI 原宿主失败及增量 R5 的文本遍历递归失败保留，R6 只复验该项且产品字节未变。Expo 最初一次命令因抄错 expected-head 被前置拒绝，未创建输出或安装依赖；读取真实 head 后完成上述正式四阶段。

## 当前可证实的产品范围

- 只有明确旅行上下文的状态问句自动进入查询；普通家庭待办问句不被抢走。候选按名称／目的地查找，用户明确选择原旅行，同名不自动决定。
- 每页 20 条；候选扫描最多处理 1000 条原旅行，准备／采购各最多核对 100 项。截断、无法核验的关联或缺失前置明确显示覆盖不足，不宣称全部准备妥当；选定原 ID 不受候选扫描上限限制。
- 状态来自当前任务、采购及直接前置；后页绑定来源版本，返回先重新读取。首尾成员核权、离线／后台隐藏和迟到响应丢弃均有专项检查；既有认证 session touch 与业务零写入分开记录。
- 原旅行处理沿原权限、预览确认和请求恢复。未知保存保留原组件、预览标识和操作标识；只在明确操作下核对，不自动重发新意图。

真实浏览器拟覆盖手机“同名选择→阻塞→原任务／采购完成→返回刷新”和桌面“候选／事项分页→版本变化→离线→旧身份迟到响应”。R1 失败原件保留，两个临时夹具目录均已清理；业务流程补验、HTTP／SQLite 原件与截图审查尚待补入。本批本人 A–D 完整验收仍 **0/4**，真实云账户和实体电视另验。

## 原件索引

下列路径相对本机独占证据根 `family-dashboard-access/`；原件位于忽略目录，不随源码提交。引用结论保留其执行头和分轮边界。

| 原件 | 相对路径 | SHA-256 |
|---|---|---|
| API 作者记录 | `worktrees/assistant-journey-status-api/test-results/assistant-journey-status-author-r1.json` | `0602aabca04e53322a0035116d49e6f023cac83d19eb9f2f7622826617033dad` |
| API 根独审 | `worktrees/assistant-journey-status-combination/test-results/assistant-journey-status-api-independent-root-r1.json` | `3db720e0254a7d21144da9695ba7c191874d7f078ab7900c61b94aa9fef133c2` |
| UI 原作者记录 | `worktrees/assistant-journey-status-ui/test-results/assistant-journey-status-author-r1.json` | `df5416894b61e9d3fb0316cdf213eedb9024eac613b230e0b0fe812d1c1151e3` |
| UI 修复作者记录 | `worktrees/assistant-journey-status-ui/test-results/assistant-journey-status-author-delta-r2.json` | `f8041afb855e66c8ef447a9a10ba9b30e568df00eca0693d8b23201ca3e18ffe` |
| UI 增量独审 | `worktrees/assistant-journey-status-api/test-results/assistant-journey-status-ui-independent-r2.json` | `323e5ccbee64fca0f6acb5ca68f9735bb577fa9b771ed32dfd48c1e1d9d7d950` |
| 发布源码根独审 | `worktrees/assistant-journey-status-combination/test-results/assistant-journey-status-release-source-root-r1.json` | `a15b52d3b8c48c599cfe94576b8b7b70b5206d0e9d30d872a2049d09be27f617` |
| 发布测试独审 | `worktrees/assistant-journey-status-ui/test-results/assistant-journey-status-release-tests-independent-r1.json` | `140c984ed71a139555705eb2c9f3114a545dbd87d58caecd858193179aa72f11` |
| 正式 Expo 构建 | `worktrees/assistant-journey-status-combination/test-results/expo-assistant-journey-status-combination/build-evidence.json` | `156027e008fc1cb3cb07c16972ff59986fbed4d3a4a7c936ce21ad6a960f47de` |
| 浏览器 R1 夹具阶段失败 | `worktrees/assistant-journey-status-combination/test-results/assistant-journey-status-browser-20260921T010547988916Z/result.json` | `21eb1fa5d929da067096247b842c1f45d7e12bd1e2050e663a9c30deee26266a` |

本批后续只追加真实终态与独立审查；正式发布必须生成新计划，不重放现有电视回顾发布计划。当前已发布版的事实仍见[电视回顾验收](TV-TRIP-ACCEPTANCE.md)。
