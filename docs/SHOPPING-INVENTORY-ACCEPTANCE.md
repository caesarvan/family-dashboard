# 采购关联库存与首页编辑验收

本批测试从采购项进入现有库存编辑器，检查明确登记、收货、退回与安全恢复；同时检查首页待办编辑入口。**五条要求已取得分轮真实浏览器通过证据：R2 首页，R3 三条采购，R4 收货／返回／真实重启；没有一次全套 5/5，也不代表已经发布。** 失败原件保留。业务与构建输入在各轮保持一致；API 的既有独立验证不在本浏览器脚本中重复。

## 用户入口与验收范围

采购清单 → 采购项「登记或查看库存」→「这次采购的库存」。已关联的批次可「继续处理」；新增批次可以选择已有物品，或先新建物品。原采购的自由文本数量只供参考；批次数量保持空白，用户按单位填写并明确保存。保存批次尚不增加实物库存，实际到货后再登记收货。

复用 `InventoryScreen` 及既有写接口。新增只读查询为 `GET /api/inventory/shopping/:shoppingId/acquisitions?limit=12&offset=0`，返回安全的来源采购与当前有权查看的物品、批次。契约见 [库存接口](INVENTORY-API.md)。库存操作不改变采购的完成状态、预算、实付，也不记财务支出或退款。

| 连续流程 | 可验收结果 |
| --- | --- |
| 已有物品、分次收货与退回 | 在「已买到」筛选和搜索结果进入；批次数量空白，明确填 6，保存后库存 0。收 2、再收 4、退 1 后现有 5、累计收货 6、待收 0。返回保留筛选与搜索并聚焦原项，再进入只出现原关联批次，三次实物记录。随后真实停启 Flask、复用同一临时 SQLite，从原采购重新打开批次，核对原 id、数量、三条记录及五张库存表全部保持。 |
| 新建物品与取消 | 标题预填采购名称，默认仅本人可见。取消新建不写库；保存物品后自动进入尚未保存的批次草稿。取消该草稿不保存批次，也不删除已经明确保存的物品。 |
| 已提交但回复丢失 | 浏览器先取得真实收货 POST 的成功响应，然后丢弃响应。页面保留草稿、锁定返回和全局导航。明确核对后用原 requestId 读取真实回执，只发一次 POST，SQLite 只有一条实物变化及一条操作回执。 |
| 伙伴私密与撤回共享 | 同一采购关联的私人物品与批次、计数对伙伴不可见。伙伴打开共享批次并输入收货草稿后，拥有者撤回共享；前台重新核权清空旧详情和草稿，无额外实物写入，查询计数归零。 |
| 首页待办编辑 | 首页「编辑待办」复用原编辑器，实际保存负责人和截止日期；取消不写入。另一个真实更新造成 409 时保留输入，不能覆盖较新的记录。 |

每条流程建立独立合成家庭和临时 SQLite，包含非零采购预算/实付、本人财务交易和旅行 paid 哨兵；结束时逐行核对全部采购、旅行、财务及采购结算记录保持。库存取消单独比较五张库存表。完整运行保存四张关键截图：390 宽收货退回详情、390 宽新建批次草稿、1280 宽未知结果、1280 宽首页编辑后状态；同时检查水平溢出。

## 执行与证据绑定

脚本为 `tests/browser_expo_shopping_inventory_check.py`，继承 `browser_expo_memberships_check.Run` → `browser_expo_finance_check.Run`，复用真实 Flask factory、临时 HTTPS、成员 cookie/CSRF、SQLite 和 Edge。夹具路径、文件哈希、导出复制以及运行前后源码均校验。没有虚构业务响应；唯一故障注入仅丢弃真实提交成功后的回复。浏览器路由拒绝非该临时服务的请求，Python socket 拒绝非 loopback 连接。OAuth/模型密钥为空；不调用生产或云服务，不安装依赖。

运行参数必须由集成人提供实际值：

```text
python -B -X utf8 tests/browser_expo_shopping_inventory_check.py
  --source-root <冻结且干净的源码目录>
  --expected-head <对应完整 Git SHA>
  --bundle <实际 Expo export 目录>
  --build-evidence <原始构建证据 JSON 路径>
  --expected-build-evidence <原始证据 SHA-256>
```

参数示意不可直接运行。必须使用现有已安装依赖的 Python；禁止 `-O`。构建证据读取真实 `head/tree/inputFiles/files`、`buildExit=0` 和 `bundleMarkers=true`；完整 frontend 输入集合在构建 commit、受验 commit 和磁盘中逐一相等，所有 export 文件相等。原始证据的 `kind` 如实记录，不要求 `sourceHead` 别名，不复制改名或改写证据。作者脚本的 commit 与受验应用 commit 分别记录，允许后续纯文档或测试提交沿用字节相同的 export。

每次新建 `test-results/expo-shopping-inventory-<UTC>/`，保留执行脚本副本、`result.json`、每流程失败记录和截图。报告记录真实源码 head/tree、构建与脚本身份、输入及输出哈希、原始证据路径、各流程结果和临时目录清理。失败保留原件；修复后的有限补测可用 `--scenario <流程名>`；`--scenario shopping` 只执行前四条采购流程，报告 `fullSuite=false`，不重复首页或把不同轮次相加成一次全套通过。截图及合成运行证据不提交 Git。

## 实际分轮记录

各轮使用真实源码 `be4c63ee734a6fb1390a9781780122b5e6774ec1`；实际 Expo 构建来源 `d45210a499bca38b12e176259d0900bfd67457b1`，完整前端输入一致。原始证据为集成 worktree 的 `test-results/shopping-inventory-build-r1/build-evidence.json`，SHA-256 `e65a9fc55a06200a57e6342cabad7166aa281ad54795a38bdd17d43c8ae334fb`。证据如实保留 `kind=membership-expo-build`；Expo 自身 `buildExit=0`，包装程序 `wrapperExitCode=1` 是已生成 dist 目录尚未加入本地 Git 排除的收尾断言，集成人随后核对输入与产物，没有重新构建或改写旧退出码。

下表目录均位于测试作者 worktree 的 `test-results/`，每个目录有独立 `result.json`：

| 轮次、目录 | 作者脚本 commit | 实际结果与边界 |
| --- | --- | --- |
| R1 `expo-shopping-inventory-20260918T062756320278Z` | `7d5d7f69593760e49936519c2bdadf443eaf94a0` | 全五项，exit 1；首页业务检查通过，四条采购停在首个按钮名称定位。原名称带私用区图标；首页截图是保存后退出编辑器之前的过渡帧，不作为最终视觉证据。 |
| R2 `expo-shopping-inventory-20260918T063325739393Z` | `56009ce4442a8e21b2b14e8d8fed0939f2844046` | 全五项，exit 1；首页业务及稳定截图通过。四条采购仍停在 locator：Python 的 `\U` 转义传到 JS 正则不能匹配。 |
| R3 `expo-shopping-inventory-20260918T063715608170Z` | `0e789bda260ae6b65db65f93e39a7a819597eb90` | 仅四条采购，exit 1；新建／取消、未知回复恢复、伙伴隐私／撤权三项通过。收货退回的数量已核对，返回后错误地要求筛选按钮存在 `aria-checked`，停在测试 DOM 假设，未执行重启。 |
| R4 `expo-shopping-inventory-20260918T063824658995Z` | `6bfc85c412114ef9bdbb6aad7f4a958d2aa61dd7` | 仅已有物品收货流程，exit 0；用真实“已完成 · 1 项”栏目严格区分 done 与 all，并核对原搜索、聚焦、再进入及真实重启。重启无需重登，原批次、5/6/1/0、三次实物记录和五张库存表保持。 |

R1—R4 的源码、构建输入与产物、继承夹具、Git 冻结及临时目录清理守卫均通过，浏览器 pageErrors 与外网请求均为空。对应 `result.json` 的 SHA-256：

```text
R1 56a477310b3acdcd3a28d2f4ed65f6d5e83b97e9445a80776a34b51222319d24
R2 93089d86b329d3d8d872df7be73e955f791ee1d48caea9a52d35e0d0e3cb63fb
R3 0af2319612ed41ce883ee7b88d3625bace5163d50acb16fac885026c332d149b
R4 4b574f6e4b836b0b8b49aa03aff1ece56e104e87ad312934654934a0672e4673
```

最终四张视觉证据为 R2 `home_edit_cancel_conflict/home-edited-1280.png`、R3 `new_item_cancel/new-item-batch-draft-390.png` 与 `lost_movement_response/unknown-result-1280.png`、R4 `existing_receive_return/receive-return-390.png`。均无水平溢出；手机截图记录当时滚动位置，不宣称覆盖整个长页面。R3 故障为真实成功的收货提交后丢弃响应：只有一次 POST、一次 movement、一次 operation，恢复读取同一 requestId，没有重新创建操作。

R3 前另做真实页面单按钮探针 `locator-pua-js-probe-r2/result.json`，验证 Python→Playwright→浏览器的传输路径；它不计入五条业务流程。探针第一次在 app 启动前触发既有 Windows 路径长度守卫（临时前缀多两个字符），改用主脚本同样的短前缀后通过。没有安装依赖或改业务代码。

<a id="shopping-inventory-release"></a>

## 2026-09-18 实际发布与验证

当前阶段：**2026-09-18 15:12:56（北京时间）实际激活成功，15:14:36 独立只读生产审计通过。** 生产实际一户两库，家庭 61→61、平台 9→9；两户三库是此前隔离合成演练的范围。47 项 Linux 验证与演练已分别通过。本地浏览器仍按上方 R2/R3/R4 分轮接受，没有一次全套 5/5；原失败与构建 wrapper exit 1 均保留。

首页「编辑待办」仅针对看板内可编辑的本地事项，沿用原编辑器、负责人/截止日期、revision 冲突及 CSRF/身份守卫；同步来源事项不增加这一编辑入口。采购「登记或查看库存」允许继续关联批次或明确新增，保存批次不等于收货；实物变化和财务核算独立。默认私人物品不自动向伴侣共享，电视不获得写入能力。本批入口不自动创建订单、退款或支出，也不新增云端清单写回。

本批实际运行身份如下，其他说明页只引用本节，不重复维护散列。发布后纯文档提交不改变已冻结、已安装的产品包：

| 身份 | 实际值 |
| --- | --- |
| 产品 source head | `c3488ed7bddd4100de1270a28645105be0071a4e` |
| tree | `d3059465805dbe84e2d6b1d5d83f363d66924ec1` |
| main 产品合并（同一 tree） | `35c6b2f4739a68e042afbcc8dddf88779e27ca49` |
| package.json SHA256 | `8718489b872f8f6ccec51b86abd7c1ba3838028f160d0f53e12e0d1f33b35d31` |
| release manifest SHA256 | `910b4ab67459d47dd77ec32fbb986fe298e71c24baf75c39c334ebc4db89fb1e` |
| archive SHA256 | `58d4d3ee9913a06a3b4f63e671e20283b4f2f397fa1839369ae9fa7261341caa` |
| 实际候选镜像 | `sha256:3ebb0a10eaf3aac44c5646478f25d49b85a66d9130007286ac869274e99b6c68` |
| 实际父镜像 | `sha256:c8e3da47800e3d11f609677bd6aca5f69aef6e7d7a49827c04fb6bea29946771` |
| 文件范围 | 850 源码/静态文件，120 runtime 文件，107 前端构建输入，23 Expo 产物 |

本批只增加 `inventory_api.py` 的只读关联查询和界面入口，未修改 schema、依赖、Compose 或 Dockerfile。最终前端及 43 个根 Python 模块与浏览器受验源码相同；后续发布工具、文档和测试变更分别审查，不触发重复产品构建。

| 实际验证 | 结果与原件 |
| --- | --- |
| 本地 API | 95 项真实 Flask/SQLite 用例通过，无失败/跳过；原件在 `worktrees/inventory-shopping-query/test-results/inventory-shopping-query-r3/`。本轮组合审查读取原件，没有重跑或把它算成 Linux 47 项。 |
| TypeScript / Expo | 两次 TypeScript 与一次 Expo 子进程均为 0，wrapper 为 1；独审原 session 回执、107 输入及 23 导出，确认唯一未跟踪 export 引起收尾 guard。未补造耗时或改写原退出码。 |
| 正式 Linux 镜像构建 | 14:55:15（北京时间）完成，从固定父镜像增加 cleanup/COPY 两层，配置保持，实际 runtime 120 文件全部匹配；`build/build.json` SHA256 `e37c97b96a5870d7841cbec9c1a4ffe845356c8368f3ab4cd50581cae0af0d6a`。 |
| 正式 Linux 隔离验证 | 14:56:44 完成，27 个查询/API 用例 + 20 个控制器用例，共 47/47，无失败/错误/跳过。实际容器、源码/runtime/模块来源、精确 nodeid 与 JUnit 均绑定；`validation/validation.json` SHA256 `fd47603ad5051f97316157305e6a3c92e08585ab2eb3edb359d34d690ac9eff2`。控制器用例仍是 recording 替身，不冒充真实服务切换。 |
| 正式候选镜像两户三库演练 | 14:57:57 完成，5 步全部通过、17 条 Docker 命令；家庭 61→61、平台 9→9，全组 schema/行/序列及合成 marker 不变。`rehearsal/result.json` SHA256 `8f6c241de8a0956b7290fe3e0e719b1e526dd06474cc2774664a5b76600421ee`。 |

以上 build/validation/rehearsal 原件集中保留在外部 `family-dashboard-access/steady-shopping-linux-originals-r1/`；数据库不下载到文档或提交 Git。演练的全部 proof 文件经服务器只读流式摘要复核，记录 `steady-shopping-rehearsal-hash-readback-r1.json`。合成演练使用 synthetic marker override，`exactProductionControllerProgram=false`；它实际覆盖 UID 10001 读取候选源码/发布 helper 和正常 app 初始化，但没有提前验证真实生产环境或 marker。方法和边界见[合成演练说明](STEADY-LINUX-REHEARSAL.md)。

代码/包组合、实际构建补充证据、浏览器分轮、发布工具和 Linux 演练工具均由非作者审查。正式发布采用[61/9 普通更新](STEADY-RELEASE.md)：本次停写完整 registry 组备份，实际 app 启动后关闭核保全，再放行 workers/web；成功成员迁移 marker 保留，不执行 `warm_once`。实际激活、公开读回和独立生产审计原件如下。

### 生产激活与独立只读审计

实际激活于 `2026-09-18T07:12:56.508187+00:00` 完成，六步均成功：保留旧源码/配置/镜像；停止全部写入服务；验证并保留停写完整库组备份；安装新源码；新 app 健康后停止并验证全组与 marker 保全；放行新服务并启动原备份 timer。没有重放成员迁移。生产家庭数为 **1**、数据库数为 **2**；回执中的 `[61,61]` 和 `[9,9]` 分别是前后表数，不是两个家庭。

| 发布原件 | 绑定值 |
| --- | --- |
| candidate | `/opt/family-dashboard-candidates/steady-shopping-61-20260918-r1` |
| release | `/opt/family-dashboard-releases/steady-61-20260918T071129453952Z` |
| release-plan.json SHA256 | `0c96683cccce313be066df660764ca506fdefff3124dec356a04ee1274860b14` |
| stage.json SHA256 | `246ee5009eff1e3fb56ce7a46398f435498a1eadd1fb9ea9a467e833c474daf7` |
| activation.json SHA256 | `4c179d7023b41e80abe058729f88ae2070beb87d65d12e697de6d355439bf025` |
| 启动前后全组 logical SHA256 | `0219b1cb77dcb72317d1ffcd76b1ef5e7cd13f633b70833c1edce40408cebfe7` |
| 保留的成功成员迁移 marker SHA256 | `d223842c531e115b21430e860ffa8e742b1fbf0616942a228d04009e66dedb93` |
| 独立只读审计 SHA256 | `c97f5d76e0e4d2f9747e9b718d6a8da2c9f752d6e6838ed60bc08aae21439d8b` |

审计的服务器观测时间为 `2026-09-18T07:14:36.570408+00:00`，命令 exit 0、stderr 为空。850 源码/静态文件全部匹配，app/sync/media 各 120 个 runtime 文件匹配，四服务均运行、restart 0、无 OOM，app 为 healthy；web 仍用原固定镜像。正常 TLS 下 `/app`、`/app/tv` 与 `/healthz` 返回 200，`/tv` 保持转向新电视页，75 个公开静态资源逐字节匹配，13 个匿名私有接口均拒绝为 401，Expo metadata 返回 404。

原 `.env` 摘要保持、权限 0600；各服务与各自发布前环境的键值映射完全相同，Compose 重建后的顺序不同，不声称数组逐项顺序相等。成功迁移 marker、停写完整备份及历史 R2 失败/恢复证据均保留。审计仅核原备份 timer 为 active，没有启动新备份、迁移、真实产品写入或 `/api/me`，未下载数据库或环境明文。

独立报告为外部 `family-dashboard-access/steady-shopping-published-audit-r1.json`，其执行回执、原 stdout/stderr 和 13 份逐字节 JSON 原件在同级 `steady-shopping-published-audit-r1-originals/`。装配/stage/activate 命令日志仅记录摘要和字节数；没有把未下载的日志写成已归档原文。此生产审计证明安装身份、可用性和保全回执，不扩大为本人真实库存、云端写回或实体电视验收。

## 当前边界

剩余观察：既有 Paper 筛选按钮在 Web DOM 中未暴露选中 `aria-checked`，实际筛选与返回保持通过；这是独立的读屏状态改进点，本批未改业务组件。代码及四张稳定截图已分别完成独立审查；本人真实库存资料、云端交互、实体电视和长期使用仍未验收。本批未扩大售后功能；退回沿用实物记录，不推断退款、不创建财务结算。
