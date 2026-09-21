# 旅行准备查询：候选验收记录

**尚未发布。** 本页记录已完成的候选检查，不改变当前生产电视回顾版本 `d4346d3`、77 张户内表／9 张平台表和五服务状态。本批没有 DDL，候选运行变化仅 `journey_workflows.py` 与前端；实际候选包、镜像、Linux 专项与容量 R2 结果已取得，容量独审、发布计划和生产执行仍待完成，不以文档提交或构建成功代替上线。

用户路径见[操作指南](ASSISTANT-JOURNEY-STATUS-USER-GUIDE.md)，权限、分页和响应见[冻结契约](ASSISTANT-JOURNEY-STATUS.md)。本片是查询已有旅行准备情况，再打开原旅行处理并返回刷新；查询本身无业务写入，不调用模型或云服务。

## 已完成与待完成

| 范围 | 已有实际结果 | 不能据此声称 |
|---|---|---|
| API `bc3619d05553b62cdf3a83893e92b54bcc279467` | 47 个唯一节点、50 次分轮执行，最终均通过；45 个专项及 2 个相邻节点。真实 Flask／SQLite 覆盖两户、成员／TV、撤权、双快照、原 ID、旧旅行、坏关联、上限、依赖和分页版本。根非作者源码／原件审查通过 | 不是候选镜像的 Linux 执行，也不是本人真实数据验收 |
| UI `2a89eaa5…` → `594b455347584690905898ec1b752ceff6084310` | 原 28 个唯一节点／30 次分轮执行；三项 P2 修复另有 4 个受影响节点／5 次执行及两组 tsc。增量非作者审查通过，原列表、未知保存和原 ID 恢复问题闭合 | 两组有重叠，不未经去重相加。受控 React 宿主与模拟网络不是实际浏览器或服务端提交证明 |
| 发布适配 `77cc8f60edc399076d71f50660f9e75153f684b4` | 18 个唯一节点／20 次分轮执行通过；根源码审查与非作者测试证据审查通过。固定父版、114 个非 Expo 运行输入中 113 个保留、47 节点选择及五服务 77→77 流程有检查 | 录制执行器不是新一轮实际 Docker、生产备份或恢复证明 |
| Expo `69ffb5cd0bb6fef38ae146705c742294b500d4a8` | fresh `npm ci`、应用 tsc、测试 tsc、Expo export 四阶段实际退出 0，23 个导出文件；完整输入／输出由 build evidence 绑定 | 本轮四阶段没有另跑 Node 用例；构建不替代浏览器或最终包验收 |
| 真实浏览器 | R2 手机 `original_completion_return` 与 R3 桌面 `paging_offline_identity` 分轮通过，共 2 条唯一流程；真实本地 HTTPS／Flask／SQLite／Edge，6 张成功截图已实际查看，独立审查通过 | R2 整轮仍失败，不能写成一次 2/2；合成家庭不是本人数据、真实云账户或实体电视验收 |
| 候选包／Linux | `554037c` 固定包实际构建为 `cb7a65e` 镜像；47/47 通过，0 skip／fail／error／deselect／xfail，实际独审通过。完整源码、137 个运行文件及 47 个精确节点与选择一致 | 这是同一组 API 节点在 Linux 的实际执行，不计作另增 47 个唯一场景；384MiB 上限不等于已测峰值或容量通过 |
| 查询容量 | R2 实际 PASS，独审待完成：4 个完整 WSGI 请求共同重叠 0.489643 秒、峰值 4；4 并发请求及 2 个后续请求全 200。384MiB／无 swap 限额下峰值 82153472B，cgroup max／oom／oom_kill 均 0，数据与输入前后保持 | 业务 view 实际峰值仅 1，没有四业务处理共同交集；不能称四业务并行，也不是 Gunicorn／Nginx 吞吐或媒体混合负载证明 |
| 最终发布 | 尚未 stage／activate／readback；新计划与生产结果待取得 | 不提前填写未来 SHA，不将旧媒体、迁移或生产原件改写为本批新实测 |

旧失败保留：API 首轮的 fixture／忙锁响应失败与后续窄修分轮记录不抹去；UI 原宿主失败及增量 R5 的文本遍历递归失败保留，R6 只复验该项且产品字节未变。Expo 最初一次命令因抄错 expected-head 被前置拒绝，未创建输出或安装依赖；读取真实 head 后完成上述正式四阶段。

## 当前可证实的产品范围

- 只有明确旅行上下文的状态问句自动进入查询；普通家庭待办问句不被抢走。候选按名称／目的地查找，用户明确选择原旅行，同名不自动决定。
- 每页 20 条；候选扫描最多处理 1000 条原旅行，准备／采购各最多核对 100 项。截断、无法核验的关联或缺失前置明确显示覆盖不足，不宣称全部准备妥当；选定原 ID 不受候选扫描上限限制。
- 状态来自当前任务、采购及直接前置；后页绑定来源版本，返回先重新读取。首尾成员核权、离线／后台隐藏和迟到响应丢弃均有专项检查；既有认证 session touch 与业务零写入分开记录。
- 原旅行处理沿原权限、预览确认和请求恢复。未知保存保留原组件、预览标识和操作标识；只在明确操作下核对，不自动重发新意图。

手机 R2 实际完成“同名选择→阻塞→原任务／采购完成→返回刷新”：开启 AI 整理后，状态查询仍只发 GET，没有模型调用；原任务／采购 PATCH 后，任务从 0/2、阻塞 1 项变为 1/2、阻塞 0 项，采购从 0/1 变为 1/1。SQLite 原件仅记录这次用户操作预期的实体、设置和审计变化。

桌面 R3 实际完成候选与事项 20+1 分页、旧来源版本返回 409、重新读取、离线隐藏，以及真实成员切换后的旧响应释放。新的 `/me` 已完成 200 响应，MutationObserver 未发现旧旅行摘要重新出现，身份阶段业务表摘要保持。6 张成功截图分别覆盖 390px／1280px，未见横向截断；两轮 stderr 均为空，已捕获 HTTP 原件无 500，夹具监听器停止、临时目录清理完成。此结论不声称另有完整网络日志，也不把受控 TSX 的未知保存恢复覆盖算作这两条浏览器流程。

运行／构建源码固定 `69ffb5cd0bb6fef38ae146705c742294b500d4a8`；R3 验证头 `7743c2a3b1d4b53401ba4b9b2d1c84d7da944772` 只改 harness 的请求身份配对，复用同一 `156027…` 构建、173 个输入和 23 个导出。R1 两场景在长路径夹具复制阶段失败，未进入 UI；R2 第二场景在请求对象身份断言处失败，整轮仍为 FAIL；旧请求／轮询导致串配只是可能原因，不写成已证实。R2 原 PID 46216 退出 1，R3 原 PID 48796 退出 0，仅补跑第二场景。全部失败原件保留。本批本人 A–D 完整验收仍 **0/4**，真实云账户和实体电视另验。

## 实际候选身份与 Linux 边界

| 身份 | 固定值 |
|---|---|
| 打包源码／树 | `554037c25ad2b2f54d6da5d86c5b8d8a20359057` ／ `96e95364aafc676d6e967deb8955bbc6d8d73e43` |
| package／manifest SHA-256 | `ae4aeb6b7e219e9b625e77171aa2dc7e9b3852ec006cb51bb1be4253ce252cec` ／ `36dcb7522cfabdc7493060106c7f5f3f72c8196c8ec936e2b40cbb78bd788497` |
| 实际候选 image ID | `sha256:cb7a65e02045badc482b8868d47afcdb053f07dd99481e8d9fbee09b2d60fa80` |

组合独审核对 23 个变化路径均与已审组件逐字相同，1267 个源码文件与 Git／归档一致；完整前端、114 个非 Expo 运行输入和 23 个导出与实际浏览器／构建源一致。相对父版，114 个非 Expo 输入仅 `journey_workflows.py` 改动，113 个保持；浏览器准入报告将分轮证据明确绑定此最终包，不冒称在 `554037c` 重新跑过浏览器。

Linux build 与 validate 原远端 PID 分别为 1225754／1226721，均退出 0；验证前后 1290 个安装输入、137 个运行文件保持，实际导入 60 个应用模块，47 个节点全部通过且无跳过。容器启动前核实 384MiB、无额外 swap、非 root、无网络、只读根及独占清理；本轮未保留 cgroup 峰值／事件，不能称零 OOM 事件或查询容量通过。构建保留 Docker legacy-builder 弃用提示，不写成 stderr 为空。父版五服务、镜像、PID 与配置摘要保持；这不是生产业务操作或恢复验收。

容量另列两轮：R1 保留 FAIL，虽四请求均 200，但 view 峰值为 2、四个 view 区间无共同交集；R1 未观测完整 WSGI 区间，且终态数据库摘要缺失。R2 记录包含认证在内的完整 WSGI 生命周期共同重叠，业务 view 则为串行观测；不将两种并发范围混写。R2 最大响应 199530B，实际内存峰值约 78.35MiB；数据库、运行源码和依赖前后摘要相等，仅归一化认证 session touch。执行方已采集并重哈希 33 份原件，父版五服务未变；容量非作者独审尚待完成，R1 不因 R2 通过改判。

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
| 浏览器 R2 手机通过、整轮失败 | `worktrees/assistant-journey-status-combination/test-results/assistant-journey-status-browser-20260921T010822773084Z/result.json` | `3081e3d5940c84b9e71fa911b61613aa7e46245cc6eadd82ef282b4c081f5a9b` |
| 浏览器 R3 仅桌面补验通过 | `worktrees/assistant-journey-status-combination/test-results/assistant-journey-status-browser-20260921T011302328497Z/result.json` | `a45eea9d26ebed2524e9704dad5b456431f3732834921e62ed46cc1e5a17cd99` |
| 浏览器分轮独立审查 | `worktrees/assistant-journey-status-api/test-results/assistant-journey-status-browser-independent-r1.json` | `b33d55789637fa03f686fb4326654e0c64297ab89d927c28d50d2915d7695381` |
| 最终包组合源码独审 | `worktrees/assistant-journey-status-api/test-results/assistant-journey-status-source-independent-r1.json` | `c31a013883923766e8362d791318203e06b9a1ade8ac5a557849a909c3905b36` |
| 最终包浏览器角色绑定 | `worktrees/assistant-journey-status-api/test-results/assistant-journey-status-browser-admission-independent-r1.json` | `c210d2322e83de5f4e901d2526955bc5e635355d6acfabcce6ac63d8ff363ad7` |
| 实际 Linux 构建及 47 节点独审 | `worktrees/assistant-journey-status-ui/test-results/assistant-journey-status-linux-candidate-independent-r1.json` | `7e02d0fb8af65a1738585a0bc26e83b8077d3a62eaa4a1330cc997f888e90c9a` |
| 容量 R2 实际结果（独审待完成） | `assistant-journey-status-candidate-r1/linux-evidence/capacity-r2/result.json` | `c70d1e19896a27887034e2d546bfb31e1348c5a5d8788224df5f1d8bafcc5f72` |
| 容量 R2 实际请求／数据／cgroup 原件 | `assistant-journey-status-candidate-r1/linux-evidence/capacity-r2/proof/capacity.json` | `0088ff032eb91b96f0014ae77416040413c73045c23b489cba2210e0a367e498` |

本批后续只追加真实终态与独立审查；正式发布必须生成新计划，不重放现有电视回顾发布计划。当前已发布版的事实仍见[电视回顾验收](TV-TRIP-ACCEPTANCE.md)。
