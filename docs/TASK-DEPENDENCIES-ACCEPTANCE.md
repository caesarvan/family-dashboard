# 本地待办前置事项：使用与集中验收

<a id="task-dependencies-release"></a>
## 本批状态

**2026-09-20 06:28:25（北京时间）实际激活成功，06:35:47 独立生产只读审计通过。** 代码经 [PR #10](https://github.com/caesarvan/family-dashboard/pull/10) 合入 main `40ea731b28510f7bd7f3db3d0e06fade62a530f8`，与正式 source `456585bc1a4f820ca238b3308f09a8d591628f41` 同树。Git 合并、实际发布和独立审计分别有原件，不能互相替代。

本批让本地待办表达“先完成哪些事项”：共同待办和首页显示阻塞原因，完成与删除在服务端重新核对。旅行重建、改期、例行事项及原任务发布保留当前实体依赖。继续使用原任务 JSON，家庭库 69／平台库 9 表，无 DDL、批量回填、前端依赖升级或新第三方授权。站内提醒仍是独立候选，未包含在本包。

## 最短使用路径

1. 在「共同待办」创建本地任务“确认日期”，再创建“订酒店”。新建时选择「看板本地待办」。
2. 添加或编辑“订酒店”，在「前置事项（可选）」搜索并勾选“确认日期”，核对后保存。最多选择 20 项；选择已有事项的原 ID，不会复制前置任务。
3. 返回清单或首页。前置未完成时，“订酒店”显示阻塞原因并禁用完成勾选，仍可打开编辑。首页在到期范围内优先显示可以执行的任务。
4. 完成“确认日期”，刷新后再完成“订酒店”。服务端使用最新版本和同一写事务核对，旧页面不能绕过前置条件。
5. 需要取消关系时，在后续任务中明确取消勾选并保存。被引用的前置任务不能直接删除，必须先解除相关依赖。

选择界面排除自身、云镜像及会形成循环的事项；服务端仍再次检查。历史失效引用会显示为阻塞，需本人明确取消，不能在保存时默默删除。旧记录没有依赖时按空数组显示，旧客户端省略字段时保留已有关系。

已完成后续任务不会因为前置重新打开而自动撤销完成历史；若把后续任务重新打开，再次完成仍需满足前置条件。409 保存失败保留输入；结果不明时冻结保存和依赖选择，先「关闭并核对」、刷新寻找原记录，避免再次创建。确认保存结果后再继续编辑。

同步清单镜像不能配置或作为前置事项。本地旅行任务明确发布到云后，依赖仍属于本地原任务；若远端已完成但本地前置未完成，保留冲突和本地未完成状态，不自动撤销远端。处理前置后，重新预览并明确采纳远端。此行为不代表 Microsoft To Do／Google Tasks 原生支持依赖，也不证明本轮已对真实云账户执行写入。

任务仍遵循现有家庭共享权限，不因负责人变成私人任务。成员、家庭、Origin／CSRF、revision 和迟到响应边界保持；电视只读。个人导出不会自动增加共享任务，明确 `includeShared:true` 时才保留共享任务已存的 `dependsOn`，不导出派生阻塞状态。

## 已完成的分段验证

下列结果存在重叠，不累加为一次全量检查或本人完整验收。

| 阶段 | 实际结果 | 范围与限制 |
| --- | --- | --- |
| 后端作者专项及相邻 | 36 项依赖专项、9 个相邻模块 284 项分别通过 | 真实合成 Flask／SQLite、成员和独立家庭；并发循环／完成／删除、旧损坏数据、旅行重建、例行、导出、合成 provider 冲突。早期测试修订失败保留。 |
| 组合后端 | 70/70 | 36 依赖＋34 资料搜索；核对自动合并后的两类业务接缝，没有重跑全部 284 项。 |
| 正式 Expo 构建 | 两组 TypeScript、64 Node、23 个导出 | source `cb539fae405165f0d7b6b67fb112107ab072f310`；独立 fresh npm，133 前端和 7 补充输入前后相同。最终发布前端逐字节一致，后续差异仅为经审工具／发布／文档。 |
| 浏览器 R1 | 前两项通过，整体 2/3，保留 8 图 | 选择和完成门禁、循环／失效解除／冲突草稿；第三项被工具定位问题阻断。不能把 R1 整体记为通过。 |
| 浏览器 R4 | 仅第三项 1/1，2 图 | 真实 POST 201 已提交后注入响应丢失或 503；原 ID／revision、单次创建与审计、刷新完成后的锁定及核对均有 HTTP／DB 原件。R1 前两项与 R4 此项组成三条唯一流程，不是 R4 单次 3/3。 |
| 实际隔离 Linux | 354/354，0 失败、错误、跳过 | 11 个指定模块的精确节点；1007 源文件、128 运行文件和 23 导出前后绑定同包，无网络、只读根、非特权用户、临时库，无生产挂载。 |

真实浏览器使用临时 HTTPS／Flask／SQLite／Edge 和合成任务，390／1280 截图及实际 body 水平溢出另行检查。Node 使用真实组件处理器配合合成宿主。浏览器 R1／R2 的定位问题及后续修订均保留；修订没有放松未知结果或完成门禁断言。R4 在业务 PASS 后、退出前有四条 `Response.finished / Target closed` 关闭阶段异步警告，作者记录了当时 session 输出；没有独立 stdout 文件，不能宣称另有原始日志。成功断言、HTTP／DB 核对和页面错误为空均在关闭前完成，最终退出 0。

## 固定包与计划身份

| 项目 | 固定值 |
| --- | --- |
| Source / tree | `456585bc1a4f820ca238b3308f09a8d591628f41` / `65a93964e5f20088a8cd0bad878fd03c84dccc94` |
| Expo build-evidence SHA256 | `b7f0cf9e304e55287bfd15c6e7f252972e4b97d9dc3c29f84db1698bf4f7da86` |
| Package SHA256 | `e4bf7d523a46870de53cc13cdbde3fd5510e39577c325beb452f75a9788b0ca2` |
| Manifest SHA256 | `14f5d762ae07ee33a5228631faa6dc6984da7b2a71e2fc5e508781d786e4aeec` |
| Archive SHA256 | `104472e7cdb309fdfbceb4366f39dea0eb8126ff615d7d04aa7f128a0dfae9a6` |
| Image | `sha256:fbb221027f4542cbfb3f9dc66b26d38314bfbbf2df00e43744936b8288fea547` |
| Linux build SHA256 | `5f6330a0a157616a794311d5e7da46287a330f1ecf7038f57285e05a36ffd578` |
| Linux validation SHA256 | `c8041a5ed293e9d227c708555e9164a80668720ec446dea450fe77c6610059e9` |
| Linux selection / JUnit SHA256 | `9b127b7e859ea30a96e9661e894944f601480b0b9bd0fd933c121090856073f2` / `5a1277822d1bb605d590354cd163beb924c492673fb7c7bf02570395eeadc219` |
| 已消费计划 SHA256 | `2984175983ecdac8a6e958093414f753a0fc61168d7e780b044906c194a7bde9` |
| Candidate | `/opt/family-dashboard-candidates/task-dependencies-69-20260920-r1` |
| Release directory | `/opt/family-dashboard-releases/task-dependencies-69-20260919T222650619763Z` |
| Stage / activation receipt SHA256 | `f202d573c8198001ad87152cfc7e8a91fdbaa3904ca0703f2c41e38a6f73b504` / `a8afc94fac86ec2b850a4bf0aa7b262f2ce7bf27956e19ed0242e7a6886eaa55` |

非 Expo 运行文件为 105 项：新增 `task_dependencies.py`，七个原模块改变，其余 97 项保持父版资料搜索文件哈希，映射 SHA256 为 `cddfd03c86a5ce77d023178438bd56e7c410d555bd44c7f8ef9a4c6c8f614b42`。Docker COPY 加入新模块；依赖、Compose 和环境合同不变。正式 Expo 原件直接绑定，不重新生成或改写证据。纯文档提交不改变上述包身份。

## 实际发布与独立审计

实际 stage 和 activate 均退出 0，激活回执完成时间为 `2026-09-19T22:28:25.053028+00:00`。计划已经消费，禁止重放；未来更新必须重新固定当时真实安装基线、包、镜像和完整库组。

独立只读审计观测时间 `2026-09-19T22:35:47.288912+00:00`，执行退出 0、stderr 为空。核对 1007 个安装文件，app／sync／media 各 128 个运行文件；105 个非 Expo 文件全部匹配，97 个保留项与父版一致。四服务 running、0 重启、app healthy；75 个正常 TLS 资源均 200 且匹配包，metadata 入口 404。env／成员 marker／web 镜像保持，备份 timer active。

生产为一户两库，户内 69→69／平台 9→9。停写发布前与新 app 启动后的保全原件，完整 schema、行、列和序列一致，逻辑 SHA256 均为 `22c6ef00da23bda5ed856166a2d53c19a7bf1df93604678efa3647087e4709ee`。本次审计没有查询活跃数据库；启动后正常业务可以继续改变数据，不能把此摘要解释成活跃库永久不变。

两份停机备份字节已核验：家庭库 `c7adba39c68cb3caa725e38837ed703a6031fbc2332ff298f93248446b3017ce`、平台库 `c55d9896eb65ed09e3e17e67970aa7a4303aab32fe9931b571ded7f6549087c8`。没有执行生产恢复，也没有在只读审计阶段新建备份。

27 项固定匿名 GET 与另 3 项助理 GET 探针均为 401；这只证明匿名 GET 被拒绝，不证明 POST 认证、本人流程或真实模型调用。审计没有 app／SQLite 导入、活跃库查询、账号写入、bootstrap、提供方请求、服务变更或恢复。

## 原件定位与下一候选

下列路径位于维护者受限的 `family-dashboard-access/` 下，数据库、完整回执和截图不提交到 Git；这里只保存定位与摘要。

| 原件 | 路径与 SHA256 |
| --- | --- |
| 激活调用终态 | `task-dependencies-release-20260920-r2/execution/activate.result.json`，`fea2a3add86eb806d8d08bc7bf58c7814025e4b6ca52a420f7ee99eb80e599d9`；同目录 stdout 绑定上表远端激活回执 |
| R1 浏览器 result | `worktrees/task-dependencies-browser-r1/test-results/expo-task-dependencies-20260919T212003277241Z/result.json`，`aa6b59db0e208febff0a79f01e91565fab20b25ce3eb0d795101d4e331f12e91` |
| R4 单流程 result | `worktrees/task-dependencies-browser-r4/test-results/expo-task-dependencies-20260919T214826149850Z/result.json`，`de8581129265f1720ac588e18bb7fc6b08ec44b6f45f135affb170feaf2e487d` |
| Linux 独立审查 | `task-dependencies-release-20260920-r2/reviews/linux-independent-review.json`，`8718e2257fbbc8283b511fa19611aff5770d6d31b2951b90cd54d75db5846449` |
| 生产独立审计 | `worktrees/task-dependencies-browser-r4/test-results/production-audit-r1/task-dependencies-production-readonly-r1.result.json`，`ea6f6cebea08105f7d809d0220c28c8e8de02ae35b599fcf6cd371d690ca17df` |
| 审计执行终态 | 同目录 `task-dependencies-production-readonly-r1.execution.json`，`7e8c755ff2b2e05b197fad086eefb73cd877aa3b6f0a07a57de7b7a14813e14f` |

本人完整 A–D 验收仍为 **0/4**；真实云写入需要明确目的地与本人确认，实体电视暂无设备，真实家庭连续使用和生产恢复另验。当前站内提醒候选 source `a382c9b1a8c4c92a93d9872b27a4ee3da0c916d4` 已有 82 后端／31 Node／两组 TypeScript／23 导出的独立证据审查，仍未上线；提醒的两表、已读、暂缓、恢复和迁移不能计入本次任务依赖版本。

后续协作从当前已审主线创建独立分支与 worktree，核对真实安装身份；不要把候选覆盖到发布目录。详细合同：[本地任务依赖](TASK-DEPENDENCIES.md) · [Expo 使用与交互](EXPO-TASK-DEPENDENCIES.md) · [发布适配](TASK-DEPENDENCIES-RELEASE.md) · [完整验收场景](ACCEPTANCE-SCENARIOS.md) · [Git 协作](GIT-WORKFLOW.md)。模块文档的作者阶段细节保留原范围，当前上线事实以本页为准。
