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

## 当前边界

剩余观察：既有 Paper 筛选按钮在 Web DOM 中未暴露选中 `aria-checked`，实际筛选与返回保持通过；这是独立的读屏状态改进点，本批未改业务组件。本人真实云数据、实体电视和长期使用不在本地验收范围；最终代码和截图仍由集成人独立审查。本批未扩大售后功能；退回沿用实物记录，不推断退款、不创建财务结算。
