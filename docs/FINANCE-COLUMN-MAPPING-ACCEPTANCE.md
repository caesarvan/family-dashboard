# 财务列映射：组合与发布验收

<a id="finance-column-mapping-release"></a>
## 当前状态

**已发布：北京时间 2026-09-18 06:56:39 激活，06:57:18 正常 TLS post 通过，06:59:53 fresh 读回通过；非作者独立审计 PASS。** 本页集中记录可接手的来源、实际分轮验证与未验边界；Git 合并、收集测试项目、本地通过和生产发布分别记录，不相加为一套结果。

用户路径为「家庭资金 → 导入账单 → 通用表格 → 手动指定列 → 读取表头 → 选择日期／金额／标题／币种 → 按所选列预览 → 确认导入 · 仅本人」。CSV／TXT 沿用编码选择，XLSX 先选工作表。任一错误使整批不能保存，短行缺少币种不能沿用默认人民币。未知结果保留原编号与完整请求，先明确核对；404 不证明请求未提交。

使用：[Expo 四列映射](EXPO-FINANCE-COLUMN-MAPPING.md)。协议、行位置、去重和会话边界：[API 契约](FINANCE-COLUMN-MAPPING.md)。[场景 B](ACCEPTANCE-SCENARIOS.md#b财务导入与对账)的真实平台全链仍单独验收。

## 已审来源与本地证据

- API 固定 `8c835bf11d0b0a4bd5f47fc5100b2fe833e8bbdb`；`finance_hub.py` SHA `093fb1cd54adb4cce7e486b44834800ec018be01cd7b668fc51ceb33f21d3091`。`financial_files.py` 保持原字节，不增加表或路由。
- UI 固定 `74b77612440e1c2bb173a9ddb6639dab9f2eb651`，仅原导入 Panel／模型增量；已有完整身份、隐藏／离线及未知请求锁继续约束四列选择。
- 原实际构建源码为 `c958c1b2da6f4a79cbc828653d6d86afdfab76da`；R2 浏览器受验源码为 `2331b608056dec2175e6cca9d0e4beb9f9d2dc20`。196 构建输入与 23 导出相等，复用原 build evidence `3cafbe331fae7eca902af4b12496bdf13cd599c752177b4ec6d250aea4e9ca34`，没有重新构建。
- 最终代码组合 `c9ef18f402198a4b31a0c5d86510f4d4d06d7474`／tree `52f985d915086eb1401bc5c2eb75e0efcf474eaf` 相对 R2 仅加入已审发布适配器三文件，浏览器受验运行字节保持；实际安装 main／source 同树，见下方身份。
- 发布适配器固定 `9f882509122a2bfc280226891ab54d8a73169ea7`，非作者审查通过；[发布边界](FINANCE-COLUMN-MAPPING-RELEASE.md)使用当前角色结构的 58→58 无 DDL 检查。

| 证据 | 实际范围与边界 |
| --- | --- |
| 后端早期组合 | 修复缺币种问题前，393/393（46 映射＋21 会话＋326 旧模块）通过；不是修复后的全量结果 |
| 缺币种修正 | 修复后 228/228（50 映射＋178 hub/file/amount）通过；该轮未重跑其他已过会话／兼容模块，数量不与 393 相加 |
| UI 模型和类型 | Node 14/14；最终两份 TypeScript 配置均零诊断。模型为客户端合成断言，不能替代真实 API／浏览器 |
| 发布适配器 | 21/21 专项；已批准 pin 加入后，真实父九工具及父包 CLI 校核通过，196 构建输入均被 selector 包含；该作者专项／CLI 轮次无应用打包／绑定／远端操作 |
| 浏览器与视觉 | R2 实际 6/6，四宽浅深共 8 图由 Root 逐张查看；仅 PASS_VISIBLE_VIEWPORT，不代替完整滚动区或设备验收 |
| Linux 与生产 | 15 模块／497 唯一项目随后在容器实际执行：496 通过、1 项精确 Windows junction 跳过，零失败／错误／deselected，耗时 214.962 秒且节点与 collection 完全一致；激活、post、fresh 与独立审计均通过 |

后端作者原件：`worktrees/finance-column-mapping-api/test-results/column-mapping-combined-r3/` 和 `column-mapping-currency-r4/`；后者 `record.json` SHA `d69e7d72a8d39515bbbf45e1603a8b23aeb2b34d56ef97c0640ab6177f56671a`。修复前的 9 个基线失败及中间轮次保留，详细 XML／范围见 API 契约。

UI 最终报告：`worktrees/finance-column-mapping-ui/test-results/column-mapping-final/result.json` SHA `f81c4d18cc9ce3a2fd04dde143c5d0da7ab5c544513e1166f7db85ebabeffa98`。适配器专项、真实父九工具差异及 SHA 见其发布文档。上述 `worktrees/` 路径均相对维护者私有 access 目录，原件不进入仓库。

## 浏览器失败、修订与读回

R1 实际 0/6：测试在上一 Paper 菜单退出动画结束前连续选列，匹配到两个同名选项。仅在 harness 等待上一选项消失，保留精确选择器和业务断言；不使用 first/nth 绕开重复。原件 `worktrees/finance-column-mapping-browser/test-results/finance-column-mapping-20260917T222739281084Z/result.json` SHA `3772d78c6d36f64a26f93e0f5cac99978798f478574111aa7917e1cf32ef6964`。

R2 原件为同一作者树 `test-results/finance-column-mapping-20260917T223602014837Z/result.json`，SHA `97620fca69ae828f7247a4d3aa64640c36193577b1e64fa8de775b31f53462f4`；harness SHA `b07301680403c6b7eaa32cdd96e5183e680b5034401f709318a1b1c625cb46cc`。739 源文件、23 导出、4 实际 fixture 前后散列保持，6 个临时环境全部清理，页面错误／外网请求均为 0。真实应用覆盖首次来源、重传／改列去重、短行缺币种整批拒绝、保存丢响应后原回执恢复和另一成员／迟到响应隔离。

Root 八图视觉原件 `finance-column-mapping-visual-review-20260918-r1.json` SHA `817f074a5833291a768357936baa183f9b18ec05c986425a0f5229484b41a91b`，只支持实际可见视口。收集原件 `finance-column-mapping-collection-20260918-r1/result.json` SHA `50ecb39f4cd3b6e7326292f61184ef2d4629c91f9df2717fab0da674e086e51a`，497 是唯一 node 集合计数，不是执行通过数。

## 实际安装与服务器证据

- 安装 main：`49e69a6952c91e6014296ca5ed55eb4873733b58`；source／formal：`6725bbda659176a63c00209403829ba108244d9f`；同 tree：`52f985d915086eb1401bc5c2eb75e0efcf474eaf`。后续纯文档不改变这个运行包。
- app／sync／media 镜像：`sha256:039f7c7f4a601273bfbffa22ea9ca9494d8de2045240bf43244d41668469ada6`；web 镜像与环境 hash 保持。
- archive SHA：`3ff158acd53ec13b411f55d7b810e386e16c41c38ea65c07ccc0470846f31631`；manifest SHA：`32590f6186738d9de32064fd3e80de80de259c77f96981080c0583eb7525e0c9`。
- release：`/opt/family-dashboard-releases/finance-column-mapping-58-20260917T225540859168Z`。源包 764 文件＝741 源文件＋23 导出，196 构建输入一致；116 运行文件／39 已加载模块前后散列保持；正常 TLS 核对 75 静态资源、24 generated 禁止项、1 retired 禁止项，38 唯一匿名接口全部 401。
- 四服务 running、restarts=0，仅 app health=healthy，另外三项 health=null。post 新逐库在线备份完成，service success／timer active；不是跨库原子快照。

本地原件根为私有 `finance-column-mapping-tools-20260918-r1/`：`validate-command.stdout` SHA `e661083b1ab1f23eb3d9432733a152cc37cc01af01502cf0ea1db6b924b13357`，`activate-command.stdout` SHA `ebc9c8cc65ea9674f630e8f03ebafcf6186bc202181c3fab03f380fae854c3d4`，`post_readback-command.stdout` SHA `7941c38cc5e8386c4daf9b077740f0e3271015cfb1e9927d7e7bf1d1704556fd`。

Linux XML SHA `0fb1d4fbd7cec02ccfe7bfa7cd2b6c9b2b5ed9129b94463da5eceb3bf526792e`；runtime SHA `a5b794bac90cb9a0262818b26399287a58ba482c3f1026f38908e210ef775e9c`；log SHA `fee95e75f6cda8c3c304b98e0ba9b53038655119817baf984b3fe7314170d70c`。唯一跳过为 `tests.test_frontend_runtime::test_windows_junction_rejected`（Windows junction semantics）。这些是实际执行结果，先前 collection 仍只是集合证明。

非作者独立审计原件为私有 `finance-column-mapping-published-audit-20260918-r1/audit-review.json`，SHA `f408b1a6cc50883bd3e8d4f2dc9b814f1767fe7b87b5cd309a6977ac06bcb9da`。32 份本地原件与 8 份远端原件逐一绑定，远端两次散列及下载字节相同。北京时间激活 `06:56:39.508979`、post `06:57:18.959525`、fresh `06:59:53.600526`；fresh 原件 SHA `3d7c57cd647bb81d05102d8041dd9ad241849c35e3256ed57e45fd0878709015`。

同目录 `remote-evidence/activation.json` SHA `b03df53490af4bed98e029ce978299666d7b4c2a55bef3913193301fb9d83322`，`remote-evidence/post-readback.json` SHA `7125eacbd28f64658cd85f8483c1b7e012fcaa366749ad8811f81322cde8fb4c`。这两项是服务器保存的 JSON 原件；与上述命令 stdout 语义相符，但序列化字节及 SHA 不同。审计没有重放发布阶段、备份或测试，没有下载数据库或环境正文。

首次本地 verifier 误从 READY 读取应属于 metadata 的 Docker 字段而报 `KeyError: oldDockerfileSha256`，原件 `local-verifier-first-attempt.json` 保留；修正字段来源后完成上述审计，未重复远端操作。

## 发布保全与待验边界

实际 1 户／2 库在停写完整备份后安装，`schemaChange=false`。启动前与新 app 启动后的完整快照 SHA 同为 `634a6b7c59edfc5fa3f585355a0df2fb3bef4d5daefcca3d14d762961d3a3356`，保留 `users.household_role` 的现有值、58 表全部行／schema／sequence 与 registry。没有新增列或重置角色，不能重放上一版成员迁移。post 新逐库在线备份 `manifest-20260917T225714736323Z.json` 的 SHA `d04c8f0ef6064704c876cc03efcec66b2ec2bbaa79872f7b70c70adbc2b74a81`；它不是跨库全组原子快照，也不是再次核对运行中的全组业务状态。

手动映射只支持通用来源四字段，不连接金融机构、不换汇、不把未知方向改成支出、不自动修改公共荷包，也不扩展家庭管理员的私人账本权限。本人真实脱敏平台文件、云写入、原生设备、实体电视及完整财务场景 B 尚未在本批验收。
