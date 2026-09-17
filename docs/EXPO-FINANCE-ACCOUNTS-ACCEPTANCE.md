# 手动资产账户与日期估值：组合验收

<a id="finance-accounts-release"></a>
## 已发布与独立复核

2026-09-18 **00:23:38（北京时间）激活，00:24:23 正常 TLS 读回，00:27:22 独立只读复核通过**。
从「财务 → 我的资产账户」进入；账户明细仅本人可见，不自动更新已批准的共同资产汇总。

| 身份 | 实际值 |
|---|---|
| 安装 main | `40fa82ceba456e48b56ac181f51828bd7d4ff953` |
| 安装 source / integration | `545a890c7f53fbb21e35e097fb65d0d756bcd52c` |
| 同树 | `2b5281952b12fd533314a4826bc5ac39f394f528` |
| 镜像 | `sha256:6974cdb6cc98869d8cdc55927c7a1be05d941aaef76382645b1fbd8dfe422ad7` |
| 包 | `146e8e3553e8b4fcf00363a396414ee8f3da021f5fb68ecc588cbfee69dad74e` |
| manifest | `16aa062f50fb203a5b6a1da4150824613a6989f517cccf3aac65ee81a931a763` |
| binding | `e2bc1b643992abe96b4855b6ed0c3769b4b8679237e3540ec2ee26b5e980d04c` |
| 发布目录 | `/opt/family-dashboard-releases/finance-accounts-58-20260917T162235589936Z` |

下方 R2 实际构建／浏览器源与最终安装源的差异仅新增本验收文档；所有可执行字节相同，
已由包检查和独立审计逐文件核对。后续发布文档不改变安装身份。

Linux 在该实际镜像执行 10 个模块的 208 个唯一测试：**207 passed、1 skipped、0 failure/error**。
唯一跳过为 `tests.test_frontend_runtime::test_windows_junction_rejected`，原因 `Windows junction semantics`。
完整 JUnit node 集合与 R2 collection 相同，无 deselect；运行前后 115 个运行文件及 38 个模块加载路径核验一致。
JUnit SHA `1444551290be8845943e104773a8aab1e148436571e0aebe2d8b72677c389727`；
runtime SHA `471fc5166dc422312846dc9d9423cfeac531df80406e87709e35ba3cc02efdec`；
日志 SHA `f02ad921cff1a75615f7dc7df0d0d621d545254f42062eda3683de4aaea3ca03`。

实际 1 个家庭、2 个数据库停写全组备份后完成 55→58，仅增加三张空表。
原 55 表的行、schema、序列及 registry 保留，迁移后快照与新 app 启动后快照逐字节相同。
692 个包文件（669 源文件加 23 导出）、115 运行文件、75 HTTPS 资源验证通过；
24 个私有生成资源与 1 个退役资源拒绝访问，37 个唯一匿名接口均 401。
四服务运行、零重启，仅 app 的健康检查为 healthy；原配置摘要与 0600 权限保持。
post 新备份验证 58 表／全组成员，但它是逐库在线快照，并非跨库原子事务或再次 live 全组快照。

独立复核原件在 `A/finance-accounts-published-audit-20260917-r1`；15 份摘要／JUnit／日志经两次独立远端
SHA 与本地原件对齐。复核没有重放发布、启动备份或下载数据库／配置明文。

| 原件 | SHA-256 |
|---|---|
| audit.json | `a5c274d553822baf7645c036a15ae2f6f0d3d45090f8e395fcaf711c68c96d1a` |
| readback.json | `32df3623a7964f52300c9ea768ed67a80d9b67ba1e49a513bdf671a98f435e3a` |
| activation.json | `4168e2800a2c5b9bab70559b61f0f20d52e6dbe3526a4db5b2177ae5729a0c9a` |
| post-readback.json | `10f1828124aad06705ae83966f3f688fb80a4f48251654390ddef204a873cd00` |
| fresh-readback.json | `8477f1bbcd455dd4e526ae0107660d3053960db96cacea3b631ac532ce20b96f` |

真实本人财务、银行连接、原生安装及实体电视未验收；生产覆盖恢复未执行。
下文保留候选、R1 失败视觉与 R2 修正历史，各局部检查不累加成同一套件。


## 范围与当前阶段

本批已完成账户发布；父版本为 [Source R2](EXPO-FINANCE-SOURCE-ACCEPTANCE.md#expo-source-release) 的 55 表，当前为 58 表。
新增本人资产／负债账户、按日原币估值、历史、归档／恢复，以及本人数据副本。
账户明细不共享，不自动访问银行，不将账户小计与来源基线、持仓或公共荷包相加。
历史筛选只选择估值日期，名称和归档状态仍为当前状态。

各部分使用独立分支，由非作者审查后合入候选：API `e5628fb2`、后端接入 `e6b80bc5`、
UI `97749512`、前端接入 `bedcd50c`、个人导出 `f0c1307e`、迁移与历史夹具 `b6cd21f2`、
浏览器 `0bb7cb84`、发布适配器 `83bb1b3d`。这些模块审查不代替组合或生产验收。

R1 固定组合为 `38d3a748a6b6a305e78d766a265fdb8b38ac7be6`，
tree `f0a833ad899c3c11eb5eaeb0ab17c23dd8a0994d`；下方分别保留 R1 与显示修正后的 R2 记录。
以下 `A` 指本机私有 `family-dashboard-access`，`W=A/worktrees`；原件不进入 Git。

## 已完成的局部验证

| 范围 | 实际结果与原件 |
|---|---|
| API | 真实 Flask／SQLite，81 passed，0 failed/error/skip。`W/finance-asset-accounts-api/test-results/finance-accounts-api-r4/results.xml` SHA `372c62cc154bfa27a884356efd6c7562c4d1f5e68295a04e8274f854ba0e8a48`。早期夹具失败与修正原件保留，产品权限及事务断言未删减。 |
| UI 模型 | 使用固定 API 的真实合成 DTO，15 passed。`W/expo-asset-accounts-ui/test-results/accounts-node-r1.tap` SHA `1c8478dba29249048c3c8a53babbf7be854cbbb2b0649d7238b290fe88910331`。 |
| 完整类型检查 | 组合 `5de5e999` 实际执行 `node frontend/typecheck.mjs`，应用与测试配置均 exit 0；与 R1 前端可执行字节相同；R2 显示修正后另行检查。`W/expo-asset-accounts-ui/test-results/accounts-full-types-r1/result.json` SHA `b51a98d8b70c0525978884c5b386b5b0fcd8c38bba1ff94e455b5504df414c19`。 |
| 本人导出 | 新专项及原导出／成员会话专项合计 10 passed，0 failed/error/skip。`W/finance-asset-accounts-portability/test-results/accounts-portability-r1/results.xml` SHA `021cc817e59daa0890684ea0fa7a30df9bafb99992a3dd4e1b35a39efe418b28`。 |
| 显式迁移与恢复 | 两家庭合成库，新增 33 项加原持仓迁移 9 项，42 passed。`W/finance-asset-accounts-migration/test-results/finance-accounts-migration-r1/results.xml` SHA `ba2234d4256d83963e8e67303138f6556da6bc913025d22b33b55df37403e212`。核 55→58、三空表、旧表和注册库、填充后恢复、完整及中断后的显式回滚。 |
| 历史夹具 | 原持仓回执 20 passed，另一次原库存／媒体 22 passed；各自 0 failed/error/skip，不累加成完整套件。XML SHA 分别为 `12261579da2ec345e857e26363aaadf064edd6302cc25c96663bd67442696a6d`、`463e6094005f5445c10edd003c401304a41d752f73ee565de066e4b40251a3b2`，位于迁移 worktree 的各专项目录。 |
| 发布适配器 | 23 passed，0 failed/error/skip。`W/finance-asset-accounts-release/test-results/accounts-release-final/results.xml` SHA `599d9f3fccacf5cd162f58cdeeb0a503d9ed700bac9e1db8cf510e372d2c6f0d`。实际九份父工具 CLI 的七个未绑定入口拒绝、45 个 freeze 负例及受控增量检查通过；这不是生产执行。 |

局部测试在各自固定提交执行，不能将上述数量相加作为本组合完整测试。
既有库存／媒体恢复及旅行资料／地点历史迁移夹具另有早期 schema 漂移，未在本批执行或宣称通过；
具体边界见 [迁移说明](FINANCE-ACCOUNTS-MIGRATION.md)。

## R1 构建、收集与视觉修正

上述固定组合实际构建产生 187 个构建输入、23 个导出。
`A/expo-finance-accounts-build-20260917-r1/build-evidence.json` SHA
`1783f4edf0f7345dcdca7eaa9e0274dd007c3d6c9625b69124611d2382115e84`，
入口为 `entry-32eb34fa5e7d13f01c0cbee27aaad33d.js`。

同源 `A/finance-accounts-validation-20260917-r1/collection.json` SHA
`f1b2866f76b8aa192f43137807695d510b35d78e7483ad45bbd7f5f3d46786e9`：
10 模块、208 个唯一 nodeId，**只收集，未执行**。
669 个 tracked 文件及 HEAD／tree／路径前后相同，工作树干净，stderr 为空。
此数量用于之后 Linux 验证的精确清单，不代表 208 项已经通过。

同源浏览器 R1 实际 **12／12 功能通过，12 PNG**。报告
`W/expo-asset-accounts-browser/test-results/expo-finance-accounts-20260917T153616824421Z/result.json`
SHA `3464a3f5638631516e6fd6cdb49e779aeaff6c9cf3ccd7b5a476929c6f289a9e`；
669 tracked／23 导出前后不变，12 个临时目录清理完成，0 页面错误／外网请求／生产写入。

Root 实际查看全部 12 图后发现 1280／1920 宽浅色备注框的浮动标签与第一行重叠，
视觉结论为 **NEEDS_LAYOUT_FIX**；原 `visual-review.json` SHA
`2a05f2e06541a2d3866b0075f938ddf19ff32498ac35d5900cac6142c0d88db9`。
最小修正 `ded81b18340bb78b183909fdc1f4b72f70263ea5` 由非作者审查通过：
备注使用外置 Paper 标签及输入留白，原可访问名称、权限和数据行为保持；不把 R1 功能通过当作视觉通过。

## R2 修正后组合

新组合 `e28c1f29582776af5a4b0d6479cc773f0872e97c`、tree
`8744993020fc55af15a9a3072e9e176d4b6a1b25` 实际重新构建。
`A/expo-finance-accounts-build-20260917-r2/build-evidence.json` SHA
`cca46bcf1450f1650ce061781ec5fb5bd57e45d4f54058e7fa39bbd9fdc2d11f`，
187 个输入／23 个导出，入口 `entry-16557e29d618f43df38db72f831237df.js`。
R1 构建、collection、浏览器与失败视觉结论全部保留，不覆盖或重绑为 R2。

R2 同源 `node frontend/typecheck.mjs` 实际 exit 0，应用及测试配置均通过。
`A/finance-accounts-validation-20260917-r2/typecheck-evidence.json` SHA
`2ef5119ab5f7582e390ae226b7459b4f9ae456daa2880d14d670470171ce59d7`。
该目录 `collection.json` SHA
`fc8cfff2f07d97f9db00ef8f8e9f15f10c2a40d3e804b173db92b1078b0a0e7b`：
仍为 10 模块／208 唯一项，仅收集未执行。两个步骤各自 669 个 tracked SHA、HEAD／tree／clean
前后相同，stderr 为空；没有重跑未变更的 API、导出或迁移业务专项。

R2 同一已审 harness 单次实际 **12／12 功能通过、12 PNG**。
`W/expo-asset-accounts-browser/test-results/expo-finance-accounts-20260917T154419646496Z/result.json`
SHA `2b2ab47561b170ef2770126bea006c816721ace4f045e1db0aa5c33354cec1b3`。
669 tracked／23 导出前后相同，HEAD／tree 保持干净，12 个临时目录全部清理，
0 页面错误、外网请求与生产写入。完整流程见 [浏览器范围](EXPO-FINANCE-ACCOUNTS-BROWSER.md)。

Root 实际逐张查看并核对这 12 张原图，结论 **PASS_VISIBLE_VIEWPORT**；
同目录 `visual-review.json` SHA `cd10642cf0d598b8e8bf218af180fe54a133de5d41cad5025a5dc90f3a53c132`。
桌面备注标签重叠已解决，长标题在窄屏换行，零与未知金额区别清楚。
截图只覆盖滚动后的可见区域；手机备注标签位于截图上方，内层滚动内容并未完整覆盖，
不能外推本人真实手机、银行平台或实体电视效果。

服务器结果见文首发布记录；本人真实财务、银行平台和实体电视均未验收。
用户当前无法进行实体电视检查，不据此阻塞其它可完成工作。

## 操作与数据边界

使用方式见 [账户界面](EXPO-FINANCE-ACCOUNTS.md)，请求字段与恢复语义见
[API](FINANCE-ACCOUNTS-API.md)，数据副本见 [导出](FINANCE-ACCOUNTS-PORTABILITY.md)。
保存结果未知时先按原编号核对；历史回执不能替代当前账户读回，不能据 `found:false` 自动创建替代记录。
只有使用者核对全部账户并再次明确确认，才结束未完成的核对；原请求仍可能完成，编号继续可查。

生产升级必须使用 [55→58 发布方案](FINANCE-ACCOUNTS-RELEASE.md)：停全部写入者，
完成完整组备份后显式迁移，验证旧 55 表及注册库、三张空新表和新 app 启动后不变。
原 55→55 来源发布工具不适用；任何失败保留证据，不自动重放或恢复数据库。
