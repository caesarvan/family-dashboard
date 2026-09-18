# Expo 采购实付核对：验收记录

状态：**2026-09-18 08:03:15（北京时间）已激活，08:04:16 正常 TLS 读回通过；独立发布审计通过。** 本文集中记录使用路径与实际证据，经典采购实付入口继续可用。其他模块的历史见 [README](../README.md)。

## 家庭用户怎么用

1. 在采购项点「核对实付」；也可从「家庭资金 → 我的账本 → 交易详情 → 核对采购实付」进入。有未保存的交易分类或共享修改时，先保存或取消。
2. 查找并选中本人有效的人民币消费付款和家庭采购。订单只是线索，须先关联真实付款；外币、收入、转账和重复记录不能直接用作人民币实付。
3. 核对「整项实付（元）」并单独选择「已买到」。金额替换整项原值，不累加；未知金额与零元不同，付款不等于收货。
4. 点「预览共享变化」，核对前后金额与状态，勾选共享说明后「确认保存」。仅采购金额和完成状态进入家庭共享，付款标题、编号、商户和来源仍仅本人可见。
5. 在「本人的关联记录」可更新或解除。解除可保留采购现值；安全恢复须再次满足版本与原投影检查。来源付款、退款或采购变化时重新核对，不自动回滚。

这一步不新增账单，不改变账本、预算、公共荷包或旅行已付款，不执行转账。完整规则见[采购实付契约](SHOPPING-SETTLEMENT.md)，其他财务入口见 [Expo 财务](EXPO-FINANCE.md)。

## 保存与隐私边界

确认后须重新读取当前资料，再刷新父页面。已确认但读取失败时，只允许「重新读取当前资料」，不会再次确认。

若连接中断、返回不确定或无法核实身份，保留原意图并锁定修改；用户可点「读取当前核对资料」只读核对。当前状态不能证明本次请求是否执行；不会自动或手动重发确认。原目标已不存在时，可明确「读取当前可用资料」，成功核对身份后再「结束本次核对」；该本地结束不宣称原请求成功或失败。

只沿用 context、preview、confirm 三接口。预览凭据有效期 600 秒且绑定会话，没有新增 GET 回执接口。前后 `/me` 校验成员、家庭、角色、auth_version、CSRF；后台、离线和失焦隐藏私密内容，迟到响应不回显，同身份恢复须重新读取，换身份清空旧状态。本人输入与未确定意图仅存内存。

## 实际本地验证

- **后端会话：82/82。** 28 项新增会话边界、44 项已有采购核对、10 项旅行采购回归；基线实际 10 个失败保留，不与修复后结果相加。业务金额、三接口、DDL 与 600 秒语义未改。
- **客户端：14/14 Node、完整应用及测试两套类型检查通过。** Node 使用组合后的真实临时 Flask／SQLite；不是业务成功 DTO 模拟。类型检查发生在 API 合入前，组合审查逐项核对全部前端字节不变。此前 13 项与失败类型记录保留，不累加。
- **构建：198 项构建输入、23 项导出。** 实际构建源与浏览器受验源不同；后者只增加／更新浏览器脚本和说明，逐项构建输入与导出保持一致。
- **R2 浏览器：10/10、8 张 PNG。** 覆盖两入口、草稿与月份、精确实付持久化、更新及两种解除、退款／版本冲突、确认响应丢失与未送达、保存后子／父读取失败、成员／TV 隔离、后台离线和四宽键盘操作。751 个 tracked 源文件、23 项导出及 4 份实际 fixture 前后相同；10 个独立临时环境全部清理，零页面错误或外网请求。
- **视觉：仅实际可见视口。** 320／390／1280／1920 的浅色输入和深色预览共 8 图。Root 新看 R2 浅色 320 图，其余 7 图与 Root 已实际查看的 R1 图片逐字节相同，复用原视觉结论；不称 R2 又逐张看过，也不覆盖所有内部滚动、完整无障碍或实体设备。

R1 浏览器 9/10：交易入口场景在父详情恢复途中错误判断页面、等待不存在的账本入口而超时。只修脚本终态等待与真实关系读回，业务断言及产品字节保持；R1 全部原件保留。R2 独立完整运行通过，不将两轮部分通过相加。R2 stderr 保留 Playwright 内部 `Response.finished`／`Target closed` 清理警告；不是零 stderr，也未压掉警告或为此重跑。

## 固定来源与原件索引

私有证据根 `A = C:/Users/caesarf/Documents/Codex/family-dashboard-access`，`W = A/worktrees`。这里只记录路径与散列，不把私有输入或运行日志正文加入仓库。

| 证据 | 固定来源／SHA256 |
| --- | --- |
| UI 修订 | `85da1d91e90f8282ccd6b2a0a51427b73c676785`；删除来源后的 link-only 查询经真实 HTTP 回归 |
| API 会话修订 | `1f569df9a98a1482559f31e2888d93c41dae3031`；`shopping_settlement.py` 为 `90543ed9a2cbb41136a36d27da1558922fbf144030a50a689300ec15fd3e2067` |
| 父入口接线 | `445b91b70062aff4e0edbb23754511cd4e456114` |
| 实际构建源 | `8c15b68a3ff45c6495f44f2565087fd77f716cb5`，tree `e2d80666d7fdcf9fe5c20dc5d37fe7888b056ca8` |
| R2 浏览器受验源 | `c7db8709bdbe4db29618604be1cf95771a0f7ef3`，tree `04f12a05e4e73ce4c95e83bfdd8484951e16acf7` |
| 后端 XML | `W/shopping-settlement-session-contract/test-results/shopping-sessions-fixed-r1/results.xml`；`826611acc43abaf6b11ebc1efa5578794be4d41a11bc74089e79eb6ba52c77b8` |
| 两套类型 | `A/expo-shopping-settlement-client-check-20260918-r1/result.json`；`cf8fe6ddd14896ddf8afce5a5c341aa07d3a5dcd678dad2bf28049d51b7607f7` |
| 组合 Node | `A/expo-shopping-settlement-node-combination-20260918-r1/result.json`；`230eac0ff3f20e32d86d1281432774e4ee0e334b7ef2bde07eeacf56ca7e0d58` |
| 构建原件 | `A/expo-shopping-settlement-build-20260918-r1/build-evidence.json`；`3a5b1ea424c1ed8b439c0665389e10235fa341455ea2d0a64a68f59609c76588` |
| R2 浏览器 | `W/expo-shopping-settlement-browser/test-results/expo-shopping-settlement-20260917T234100828772Z/result.json`；`fd73931dd0c0b6c1bda454046bb80026cd5d88794738b567eb615162aa9381ee` |
| R2 视觉记录 | `A/expo-shopping-settlement-visual-review-20260918-r2.json`；`39317fc26ddb811246d16243c9952f780a4adfacf26cb962e2d33c4f9528da12` |

UI 由 Root 非作者审查，API 与接线由另一代理独立审查，组合核对来源文件未互相覆盖。发布适配器的本地审查不等于服务器执行；最终安装身份及 collection 与 Linux 实跑结果须分别记录。

## 安装包来源与 Linux 验证

正式 main `37a393f149aeefb91a92da05b1d4d213b4831af0` 与 source `16a1328768f4ed9a8c84c4ae42d5e6c4b23b4ee9` 同树 `47983d4b96b589c5cbb2b700a2b23f6f2efca255`。相对 R2 受验源只增加已审发布适配器、测试和说明三文件；198 项构建输入与运行界面保持。激活原件绑定同一组正式身份；后续纯文档提交不改变安装包身份。

`T = A/expo-shopping-settlement-tools-20260918-r1`。已实核 `T/package/RELEASE-MANIFEST.json` 共 776 文件＝753 源文件＋23 导出。该清单与激活、读回绑定一致；Linux、发布与独立审计结果见下。本文整理期间不执行生成工具或重复构建。

| 本地原件 | SHA256 |
| --- | --- |
| `T/package/metadata.json` | `10169b30a499b12aa1a00b97b8b103eb18efe1d4d57db2903183f3ec1e7b20b9` |
| `T/package/release.tar.gz` | `973c547235d6efd64369ecadb8003bb8d21e1847d8506fa3d13b2077a1921cd3` |
| `T/package/RELEASE-MANIFEST.json` | `b5143c3bf4947772f0211d86c36cdb2aaed36d72f6b82e3ba8601ff2043c7efd` |
| `A/expo-shopping-settlement-combination-review-20260918-r1.json` | `1e518c77097b2bd3913b5c5f29038ded9f56964978245dba8e0f0e32f6058b87` |

独立最终组合审查源 `41fe8711d6964020dab1b9088979da9cc2a3ecba` 与上述实际安装源同树，结论为限定范围 PASS。8 个模块实际收集到 169 个唯一测试节点；该 collection 与后续执行结果分别记录。

Linux 已实际执行：168 通过、1 项精确 `tests.test_frontend_runtime::test_windows_junction_rejected` 跳过，零失败／错误／deselect，耗时 205.836 秒；运行源码在执行前后核实。保留 `T/validate-command.stdout` SHA256 `e572b86aefdf64ef3238fb629a92a70c2756ab98f0b70f3fa9812b690b5ebbc1`；该 stdout 是执行结果，不混称服务器存储 JSON 的原件散列。

<a id="expo-shopping-settlement-release"></a>

## 实际发布与读回

激活完成于北京时间 **2026-09-18 08:03:15.332642**，post 完成于 **08:04:16.147995**。发布目录 `/opt/family-dashboard-releases/expo-shopping-settlement-58-20260918T000217448502Z`；app／worker 镜像 `sha256:c6246c280d19035ecc3b4ec49d8816cb019029a7a690a4285509ce73a9cf7cfd`。main、source、tree、archive 和 manifest 均为上表固定身份。

- 五个服务端阶段各实际成功一次，五份 stderr 均为空；这与本地浏览器保留的清理警告是不同原件。
- `schemaChange=false`，58→58；停写全组备份覆盖 1 个家庭、2 个数据库。原 58 表全部行、schema、序列、当前角色与 registry 保持；before 与 after-app 快照同 SHA，不重放成员迁移。
- post 核验 776 包文件、116 运行文件、75 项正常 TLS 资源，24 项生成目录访问拒绝、1 项旧资源拒绝；39 个唯一匿名 GET 全部 401。
- 4 个服务运行、零重启；app 为 healthy，其余服务 health 字段为 null，不扩写成全部有健康探针。配置保持，备份 timer 为 active。
- post 新逐库在线备份 `manifest-20260918T000411703795Z.json`，SHA256 `6494fcebab87a565df6e0d1cadc0f419d4d828b44cc132c4ed2ee23a4dd773ab`，1 户 2 库、58 表结构核实。它不是跨库全局原子快照；`liveGroupSnapshotRechecked=false`。

本地 `T/activate-command.stdout` SHA256 `f80d3819f9d4fc09037fc74a83d81c9194050e4901cba5ecbdb07e63a74e4c92`；`T/post_readback-command.stdout` SHA256 `3f83be8953e031be2bbe830ab4b87a4041ce0f63e54dc02c0b625a9f0cf9a3be`。这些是命令输出散列，不能混称远端存储报告原件 SHA。

## 独立审计与未验范围

独立只读审计 **PASS**。`D = A/expo-shopping-settlement-published-audit-20260918-r1`，`D/audit-review.json` SHA256 `759a4455eed95c8eb612029c92b1e47951f733411017c0ec9df2c112219f646f`；已核 32 份本地及 8 份远端原件，远端前后与本地散列一致，存储阶段 JSON 内容与各自 stdout 一致。实际 169 个唯一 JUnit 节点与 collection 完全相同；116 个运行文件、39 个载入模块及构建输入／导出绑定一致。

北京时间 **08:07:20.861071** 独立 fresh 再核同一安装包、4 服务运行且零重启、39 个唯一匿名 GET 均为 401、正常 TLS 入口、配置散列与 `0600` 权限、备份 timer active。`D/fresh-readback.stdout` SHA256 `ec4dee3db479dc8112584ffffeb19c633ee6804ea6439895ffd045c9d41002fe`。

审计下载的存储报告 `D/remote-evidence/activation.json` SHA256 `c5fd6b6f4f9a72789fee51f1d74d51a89fa5bdb33d0744dd09acd9d19a3f42a2`、`D/remote-evidence/post-readback.json` SHA256 `fe7fda74fcdf924e413acf02ba65b246c78e2b6182df66fe184f382762d9679d`，与上文命令 stdout 是不同序列化原件。审计未读取或下载数据库、环境正文或 proof 正文，未重放发布阶段、启动备份或重跑测试；保全结论按既有激活指纹与读回证据核对。

真实本人金融数据、银行或支付平台操作、云写入、实体 TV、原生设备与完整目标场景 B 均未由本次合成流程验收。四宽浏览器结果只证明上述局部界面与真实本地 API 的组合行为。
