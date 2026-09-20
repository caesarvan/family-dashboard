# 地点入口与重复照片提示：候选集中验收

<a id="discovery-candidate"></a>

本页记录 source `4559353790bd8bc7809125ff32ad487d9d373fc6` 的集成候选，**尚未发布，也未完成本人验收**。当前线上仍是 [设备照片与那年今日](LOCAL-PHOTO-ACCEPTANCE.md#local-photo-release)。代码合入、正式构建、隔离验收和生产部署是不同阶段。

## 最短操作路径

| 要做的事 | 候选中的操作 | 保持的边界 |
|---|---|---|
| 从助理找回地点 | 「家庭助理」输入 `搜索：地点名称` →「整理并预览」→「在地图查看」。可进入当前可见的原旅行／旅行相册，再「返回地点搜索」。 | 按原 ID 重新读取；保留原查询与页码。主动筛选或翻页清除地图选择。地点共享不额外共享照片，不把坐标或点击当成到访证明。 |
| 核对重复展示副本 | 「相册」打开本人已保存静态照片 →「查找重复照片」→分页查看→「打开原照片」→「返回重复提示」。 | 显示「展示副本一致，原图未核验」。仅 Google／设备上传不同来源间比较净化 JPEG 指纹；不会删除、合并、共享或授权电视。有草稿时沿原离开确认，可取消并保留草稿。 |

每次最多检查1000条候选元数据，每页20项；截断或不可核验时说明「仅检查了部分已保存照片」。零结果不证明原图不同；`total` 不是整个图库的重复总数。本人以外的成员、其它家庭和电视不能查询私人重复提示。结果只代表本次明确扫描，隐藏、离线、撤权或身份变化会清除旧提示，不自动重新扫描。

实现与接口：[地点入口](ASSISTANT-PLACES.md) · [重复提示 API](MEDIA-DUPLICATE-HINTS.md) · [重复提示 UI](EXPO-PHOTO-DUPLICATES.md)。这些模块文档保留各作者阶段的历史状态；本批组合状态以本页为准。

## 已有实际证据与待完成项

| 阶段 | 实际结果 | 不能据此推断 |
|---|---|---|
| 最终 R3 Expo 构建 | 固定455源，fresh npm ci、两组 TypeScript、71项 Node／0跳过、23项导出均成功；156前端＋9补充输入绑定，非作者独审通过。 | 71项为本轮实际执行，不能与前轮重复相加为更多唯一用例。 |
| R2 bundle 的地点浏览器 | 三流程／八图：搜索第二页→地图页外原 ID→旅行／照片→原查询页；主动筛选清选；撤权及身份迟到响应。真实临时 Flask／SQLite／HTTPS／Edge，独审通过。 | 非真实云、模型、用户家庭数据或实体电视验收。 |
| 重复提示浏览器分段 | R2 bundle 保留 `cross_source_pages`、`identity_and_revocation` 两流程；最终 R3仅补 `coverage_and_draft` 一流程／三图并独审通过。全前端及165构建输入相同，保留流程源码相同。 | 是前轮五流程加本轮一个受影响流程的覆盖，不是R3一次跑过六流程；旧整组无异常的结论不成立。 |
| R3预览异常收口 | 136条实际浏览器响应中无500／非预期5xx；唯一指定缺指纹照片的GET预览503被明确记录。部分覆盖、原ID、草稿保留及数据库不变通过。 | 第三张截图保留关闭确认框的淡出过程，不证明动画完全结束的最终帧。 |
| 实际 Linux 镜像 | build exit0，新镜像b63c；135运行文件、父配置、两层新增及五生产服务前后快照核对通过，165原件已由非作者复核。 | hash-only构建检查容器使用1024MiB，不是384MiB实际工作负载证明。 |
| 实际 Linux 测试 | 原进程终态0，125 passed，0失败／错误／跳过／deselected／xfail；1213执行原件与精确节点已由非作者核验。135运行文件、58个实际加载的 `/app` 模块和500依赖文件核对通过，生产五服务前后不变。 | 选择清单为117原节点＋8个预览回归；1024MiB测试容器不证明384MiB四并发容量，作者分轮检查不能重复相加。 |
| 重复提示资源 R1 | 实际失败。客户端只读数据库观察报 `OperationalError`，四个重复请求尚未开始；外层又因缺失 `database.json` 报 `FileNotFoundError`。110件原件保留，收尾无错误、没有未知创建结果。 | 尚未测得实际四请求重叠、扫描／恢复结果或该负载峰值；失败证据不能组装发布计划。工具窄修与新的实际验收待完成。 |
| 发布与本人验收 | 本批尚无生产stage／activate／读回；本人手机、真实账号及实体电视未验。 | Git、构建或隔离测试通过不代表上线或本人验收完成。 |

### 保留的失败与修正

最初构建R1的两组类型检查通过，但71项Node中4项因测试loader未指定TS文件名、把泛型箭头按TSX解析而失败，其余67项通过，未导出。随后只修loader并保留原件；最终R3已完成正式构建，不能将R1写成成功。

早期重复提示浏览器虽然三条业务断言通过、进程exit0，stderr却有缺少 `sha256` 的历史照片预览异常。独审据此阻断：不是可忽略的关闭警告；原失败响应体没有单独留存，直接证据是服务器traceback。修复仅将完整性条件的两处元数据下标改为缺失安全读取，保留解密、拒绝输出及再次核权；8个新回归加3个相邻检查实际11项通过。

工具另加context级HTTP守卫：所有页面响应记录方法／路径／状态，只有刻意缺指纹fixture的精确GET预览503可带原因接受，任何500或其它非预期5xx仍使验收失败。新增10项离线守卫检查通过，旧15项未重跑；R3实际补验确认上述异常已收口，没有移动坏fixture或屏蔽预览请求。

资源R1的客户端错误为 `unable to open database file`，外层缺文件错误掩盖了首个原因；`client/result.json` 与总回执分别保留这两层失败。主机67次采样最低1147408KiB、监控无错误，只能说明失败期间的观察，不能代替未开始的四并发测量。后续应保留本轮，审查工具修正后使用新的独占输入／输出验收，不能把脚本独审或本地pack成功改写为资源通过。

## 固定身份

| 输入 | 固定值 |
|---|---|
| Source／tree | `4559353790bd8bc7809125ff32ad487d9d373fc6`／`b7de4df079a626cb5b3fa10b3c4f289217bdc3f9` |
| Package | `34a43623142e5c7e7ac23b3fc37e242dfdcbfc57c69cb4633a72256a58a66206` |
| Manifest | `09b972ed4be7aa4029716613ef34085c5b310a7166c891f4b2fadda2e61593fa` |
| Archive | `2d3d2fc99aa3f351c1b747d54993a00b5205cd68b42fcec923dfad31f538650c` |
| R3 build evidence | `3974219c818695f6d69e2d1b14077ef4ebfbae7fa28b879f539fd8958c4048a0` |
| Linux build／image | `56d3858034b85e0046ffaca4a6eaa682bb1bf6da0b5c7b00ffbfb417e616e3fb`／`sha256:b63c1f57eac42a5b25c30d03b342030788796b57f9b51775569f126ae7997fa2` |
| Linux selection／validation | `c9cfd44bd164ccdb6518a4a38f82ff1e8a208a919d40bb0d092c53344ca5c52b`／`0b918a8ff4e7fd905f8f611ebb1b17a5860140d196327c5aa675a4a54953f342` |
| 资源 input | `83d5dd32fc0b5810e41abf7c8e3eb3c08fe29db45cdd00e20c6528e6321dd1c7` |
| 资源 R1 result（失败） | `e9c5ddb14d60dad319e35fdd4128b1efe3f85a658070b79c1cfa29fe8275a047` |

包有1187安装文件（1164源码＋23导出）；archive另含manifest本身。135运行文件＝112非Expo＋23导出，110个非Expo文件相对已发布父版保持，仅两个固定审查过的模块改变。父manifest为 `c9723cf4df9a2e2ee36f2300d4374cfd6a0358e91ebd5d5a9392151f20da8f76`，父应用镜像为 `sha256:ede2e6f716a75e5d245ed6d90c485d39fd0847108abb6e24e42de8e4f272a1c2`。继续73/9、五服务，decoder／Compose／Nginx／依赖不变。

## 独立审查索引

下列为协调者保留的本地忽略目录报告名称与完整SHA，不将报告、截图、日志或数据库提交Git。`U` 指 `worktrees/media-video-usability/test-results`；`HBG` 指 `worktrees/duplicate-browser-http-guard/test-results`。

| 报告 | SHA-256 |
|---|---|
| U/discovery-build-independent-r3.json | `a6340de3097f9945fd901ac7f9119fc29ed08499e5b7bec0f0e0933c91d7858f` |
| U/discovery-places-browser-independent-r1.json | `5f2c7d223ed381c9d6eff9877943753814863456b4f33c1cfd7fade3973f8da4` |
| U/discovery-duplicates-browser-independent-r1.json（原阻断） | `7da6e78213f2e454e75ef95c7fa228c87eaaca0bf2d5fb8742d871b741356e85` |
| U/discovery-duplicates-browser-independent-r3.json | `fc770ebcbc8a0fb17afdc00dbc22b6d8553615d09eefb8f70e064647109a6b31` |
| U/discovery-linux-build-readback-r2.json | `28d19b9bb7ca9806dca0fba31b184e3b2898e0ef02df24280c40ea377f643765` |
| U/discovery-linux-candidate-independent-r2.json | `fa2577264ded47cf1f1e29b31aa017cccf300b36a888d6d2696af38f06268e8e` |
| HBG/discovery-package-linux-inputs-independent-r2.json | `123508f7741b2f4f5e32cb737000a9cb3437cd06ddc3e4c274aebca33e5b474d` |
| HBG/discovery-duplicate-supervisors-independent-r1.json | `eaca3274eae65424429bde9bb072992f4f3facccd26f8570ec371c09be0eda7e` |

## 下一道准入与限制

125项执行独审已通过；下一阻断是资源工具修正后的真实四并发验收及非作者复核。通过后才可按 [发布合同](DISCOVERY-RELEASE.md) 绑定原件与审查，生成**全新**不可重放计划。仍需完整组备份、app-only启动后停止态严格保全、五服务健康和独立生产读回；不能套用旧71→73迁移或重放任何已消费计划。实际故障恢复与当前73→73合同沿既有已审生命周期，不能把历史隔离恢复写成此次生产恢复。

[资源工具合同](DISCOVERY-DUPLICATE-LINUX.md) 只检验四个重复元数据请求；即使通过，也不代表与图片净化／64MiB视频响应混合时的峰值、任意并发、真实Google账号或实体电视通过。两块电视、本人操作以及外部来源的真实授权继续单独验收。
