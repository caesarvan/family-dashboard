# Expo 旅行准备同步：使用与集中验收

<a id="expo-trip-task-publish-release"></a>
## 当前状态

**2026-09-20 02:33:11（北京时间）实际激活，02:35:58 独立生产只读审计通过。** 本批把既有待办同步能力接入 Expo 旅行页，复用原任务、队列、完成回流、冲突及重连协议。业务后端、数据结构和依赖不变；采购的结构化截止、优先级与改期联动仍是独立候选，不在本次安装包中。

生产发布、临时浏览器验证与本人实际云端操作是不同证据。本批没有使用本人 Microsoft／Google 账户执行云写入，没有实体电视验证；本人完整场景 A–D 仍为 **0/4**。

## 最短使用路径

1. 打开「已保存旅行 → 准备 → 同步到主清单」。使用这趟旅行已保存的原准备事项，不另建本地副本。
2. 选择本人已授权清单，或账户拥有者明确开放的家庭主清单，再勾选本次事项。核对完整标题、负责人、截止日、完成状态、备注和目标清单，明确确认。
3. 查看实际同步进度。队列受理后可能仍在等待；只有最新内容确认后才显示「云端已确认」。看板负责人不代表提供方原生指派。
4. 返回原旅行查看重新读取的准备进度。需要处理冲突时先比较内容，再明确选择采用云端或以本地更新；原清单断开时只允许服务器认可的原目标重连。

结果不明先点「核对当前状态」，不自动重复提交。确认原事项已连接后仍需查看云端进度；没有证据时继续保留未知，必要时明确使用原预览凭证核对。暂停、恢复等操作丢回执也先读取实际状态。状态读取期间禁用修改操作，前后台切换、成员／家庭变更及迟到响应沿用身份保护。刷新不保存本页草稿，也不表示先前请求被取消。

完整操作与接缝见[使用说明](EXPO-JOURNEY-TASKS.md)，后端约定见[待办发布契约](TASK-PUBLISH.md)，发布复用边界见[发布适配](EXPO-JOURNEY-TASKS-RELEASE.md)。

## 固定发布身份

[PR #5](https://github.com/caesarvan/family-dashboard/pull/5) 已合入 main `b35a141af0822b980891a5a3d07ba1a8b90ff50b`。下表记录实际打包及安装身份；Git 合并与服务器部署分别验证。后续纯文档提交不改变该包身份，也不表示服务器中的文档已更新。

| 项目 | 固定值 |
| --- | --- |
| 打包源码／Expo 构建源码 | `8f7af253261f28269465f3a77b6c8433f2dc8142` |
| 源码树 | `f3ce2dbc584f446a750060a59bfaf2bb8c5d5710` |
| `package.json` SHA-256 | `28c7389664710fe1d46aedbd1a5347ac370143187e06c1f590e8ef7bb5397487` |
| `release-manifest.json` SHA-256 | `8f6dbcde84adca5a63710b121904c2e9eae04d8b9bde5abf79599a01fbd7c5ad` |
| `release.tar.gz` SHA-256 | `9d9bb685cb5ad13e84dcd9a3907dfbc125a5e339e8f2dcd20d06d492fa50e937` |
| app／sync／media 镜像 | `sha256:6bfdeb35d63dd55e0654f7d21f958fe7e10ffdda81ab06c4e4f5f517c782bed9` |
| 发布目录 | `/opt/family-dashboard-releases/expo-trip-task-publish-69-20260919T183138972062Z` |
| 安装包文件／每个 app 镜像运行文件／Expo 产物 | 968／127／23 |
| 数据合同 | 户内 69→69、平台 9→9；无本批 DDL |

104 个非 Expo 运行文件与已安装父版一致，包括 50 个根 Python、53 个旧静态资源及 requirements.txt；其映射摘要固定为 `70b5a4fd7ad2fe27237d27013b32912c4bd2d58408ec210539b0bcc9713afc02`。Docker、Compose、Nginx、env 与成员 marker 保持。父版 source `882dce5d0bc7bba182d4fe4ba1175c040123e6fd` 的完整身份见[上一批验收](ASSISTANT-TRIP-ITEMS-ACCEPTANCE.md#assistant-trip-items-release)。

## 已完成的分段验证

各层范围不同，不相加为一个总通过数；提供方 HTTP 均为合成替身。

| 层次 | 实际结果与边界 |
| --- | --- |
| 正式 R2 Expo | 新 detached checkout、自有 `npm ci`；两组 TypeScript、53 项 Node、导出均 exit 0，Node 无失败／跳过，23 个产物。前端和补充输入前后核对一致。 |
| R3 真实临时浏览器 | HTTPS Flask／SQLite／Edge 八条流程全部通过：Microsoft、Google 各覆盖发布与完成回流、未知确认恢复、冲突与原目标重连、迟到预览与真实成员 Cookie 切换。48 份 HTTP、14 份数据库和 6 份提供方记录；无非预期外部请求或页面错误。 |
| 浏览器画面 | Microsoft 场景的预览、已确认、冲突，各 390／1280 宽度，共六图经非作者逐张查看。采样视口无横向裁切；不外推到所有滚动位置、Google 特定画面或实体设备。 |
| 发布策略 | 新入口及旧 trip-items 入口合计 48 个唯一用例，通过情况为首轮 40 项加仅重跑的 8 项；不是一次 48/48 运行。临时 Git／包和记录式控制器不等于真实 Docker 或生产执行。 |
| 实际 Linux 构建 | 固定父镜像上增加现有 cleanup／COPY 两层，构建 exit 0；父配置保持，包与完整运行文件匹配。独立候选目录与生产分离。 |
| 实际 Linux 待办 API | 冻结选择仅为 `tests/test_task_publish.py` 的 61 个节点，61 通过、0 失败／错误／跳过／删选，允许跳过集合为空。实际 Flask／SQLite 配合合成双提供方；968 个包文件与 127 个运行文件前后核对一致。 |
| 非作者审查 | 产品、增量文案、刷新竞态修正、构建、浏览器与画面、发布适配、Linux 执行及最终计划分别审查。计划绑定 11 份审查／验证原件及 23 个固定发布操作文件；实际只读准入通过后才 stage／activate。 |

浏览器中的“重启”指重建临时 app 和监听器并读回原 SQLite，不是操作系统或生产服务重启。正式浏览器结果、输入和产物均冻结，临时数据库已清理；不宣称真实云端已创建或完成任务。下一批采购候选的后端 229／Node 104 不属于上述任何一项本批结果。

## 实际发布与独立生产审计

- `stage`、`activate` 实际退出 0，激活完成于 02:33:11；本次计划已消费，不能重放。
- 生产实际 **一户两库**，户内 69→69、平台 9→9。完整停写备份与新 app 启动后再停写核对通过；schema、列、行、序号的组逻辑指纹前后同为 `603b3e8ac0f52d3ffff5358c97c6cf8f4a73f4ca5d47c451d4a21dce07cd9e7e`。
- 02:35:58 独立只读审计核对 968 个安装文件、app／sync／media 各 127 个运行文件、固定 104 个非 Expo 文件、75 个正常 TLS 静态资源及两份保留备份的散列。四服务运行、重启计数 0、app 健康，备份定时器 active。
- 24 个匿名 GET 拒绝探针均为 401，包含待办发布状态；旅行简报、旅行改期、财务查询另三个助理 GET 探针也均为 401。`/app`、`/app/assistant`、`/app/tv` 与 `/healthz` 为 200；GET 结果不证明本人 POST 或业务流程通过。
- `.env` 文件与实际变量映射、成员 marker 保持；env 只核对摘要与 0600 模式，不输出内容。变量排序变化不视为映射改变。

独立审计只读文件、容器状态、保留备份散列与匿名 GET；没有业务写入、provider 请求、数据库恢复或服务重启，没有打开活动 SQLite。发布前后停写指纹不是上线后的持续实时数据快照；本批未执行生产恢复。

## 保留的失败与修正

1. **浏览器 R1：7 条通过、1 条失败。** 管理操作与定时状态读取发生竞态。修正提交 `6697abbe820ae6c321802bbecb91fb8dc1387ab8` 在读取期间禁用修改；完成非作者审查后重新进行正式 R2 Expo 构建。R3 用两种提供方实际延迟周期 GET，核对恢复按钮在读取期间禁用、释放后仅发送一次操作。
2. **浏览器 R2：八条 setup 失败，零业务流程执行。** Windows 资源复制路径过长；R3 调用方使用 `\\?\` 扩展路径，源码、导出和业务脚本字节保持，不伪称 R2 业务通过。
3. **Linux 传输 R1 失败。** SCP 的源参数被变量遮蔽，传输 exit 1；远端仅创建空 tools／package 目录，未执行 bootstrap、build 或 validation。已审修正使用全新 R2 目录，依次传输、bootstrap、构建及 61 项验证，旧失败原件保留。
4. **策略测试首轮长路径失败。** 首轮 40 通过／8 项 WinError 206；产品和测试代码不变，使用短临时目录仅重跑这 8 项通过，不将重复节点算为新覆盖。

## 原件索引

原件位于忽略目录，不进入 Git。`A` 为本地 `C:/Users/caesarf/Documents/Codex/family-dashboard-access`，`W` 为 `A/worktrees`。以下为主记录，其内部绑定日志、输入与子原件。

| 原件 | SHA-256 |
| --- | --- |
| `W/expo-trip-task-publish-build-r2/test-results/expo-trip-task-publish-build-r2/build-evidence.json` | `c8a585d79170e2d3de2b02a716d4d6a8131a3b52d7d2794749dcd13d63bcd56d` |
| `W/integration/test-results/expo-journey-tasks-20260919T174317138251Z/result.json`（浏览器 R1） | `62be202d531e84c4047d1a5860fde18f30081356ecc3d3443bcc75144006aebc` |
| `W/integration/test-results/expo-journey-tasks-20260919T180942805620Z/result.json`（浏览器 R2） | `153212d782b89f16a7df605247d6c784856b40c8175dcad65da3c1399a92c16a` |
| `W/integration/test-results/expo-journey-tasks-20260919T181144209341Z/result.json`（浏览器 R3） | `08da17c574afef6e3821744f8e8eaab537c6069cbea7be565dccc1f84c4d80f6` |
| `W/shopping-schedule-ai-review/test-results/expo-trip-task-publish-final-independent-review-r1.json` | `58bbfb083cbaa36c17e49344e272899180189ee9920d85b7d77187f8c4fc6701` |
| `W/expo-trip-task-publish-release/test-results/expo-trip-task-publish-release-verification-r1.json` | `462629e5d94cf5df14880ca91f7a87dfc0d51c817f9bedf9fc23be07d628c940` |
| `W/expo-task-publish-linux-prep/test-results/expo-task-publish-linux-results-r2.json` | `68d081adc0466bfb7d8ee7747b4a09bada713b209d722b408e88eb91e8a43681` |
| `W/expo-task-publish-linux-prep/test-results/expo-task-publish-plan-independent-review-r1.json` | `33e40c4500ed3fcfbad1c964b55671fad3af97e061d0073ff03b3fb6efa069c4` |
| `W/shopping-schedule-ai-review/test-results/expo-trip-task-publish-production-readonly-review-r1.json` | `69a3cca9d82fa544e7a1a010611b31effb12dec8aca0932968f3f33f9b7bc73d` |

Linux 结果所在 `V` 为 `/opt/family-dashboard-candidates/expo-trip-task-publish-verification-20260920-r2`；正式计划与回执所在 `C` 为 `/opt/family-dashboard-candidates/expo-trip-task-publish-69-20260920-r1`。正式包在本地 `A/task-publish-release-20260920-r1/package`；包、manifest 和 archive 散列见上方固定身份。

| 服务器原件 | SHA-256 |
| --- | --- |
| `V/build/build.json` | `2b91a80c08dd9cf1a8b81c4ca794f4415c558216db4d66f9b15c91966e21dd4e` |
| `V/validation/validation.json` | `25b4d2661b4e67fcf5757ce2a058827cd214850e129b707b3c1700d99095aa0a` |
| `C/release-plan.json` | `a3131beb4c44b25ccfad7609609c26217a9e5eb5d7bc5c10738960af62328204` |
| `C/stage.json` | `2bcafc0d27dfc4bc5b7d36a83f68deeb27af17ab7daf1b693059fc54e2d3ab53` |
| `C/activation.json` | `279d3b6d780387e2bb799177f8fe5cddd0df0ec345f70351f7539bbf3dd2bf1d` |

## 本人验收仍待完成

在真实账户选定可写目标，明确同步一项原准备事项，核对云端最新内容、完成后回流及返回旅行进度，才可为本人这条流程增加证据。冲突、断线恢复、跨成员协作及实体电视分别验收，不能由模拟提供方或匿名线上读回代替。完整场景 A–D 的总状态仍为 0/4。
