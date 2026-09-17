# 手动资产账户与日期估值：组合验收

## 范围与当前阶段

本批为独立账户候选，尚未部署。线上仍为 [Source R2](EXPO-FINANCE-SOURCE-ACCEPTANCE.md#expo-source-release) 的 55 张户内表版本。
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

服务器后续结果分别记录；本人真实财务、银行平台和实体电视均未验收。
用户当前无法进行实体电视检查，不据此阻塞其它可完成工作。

## 操作与数据边界

使用方式见 [账户界面](EXPO-FINANCE-ACCOUNTS.md)，请求字段与恢复语义见
[API](FINANCE-ACCOUNTS-API.md)，数据副本见 [导出](FINANCE-ACCOUNTS-PORTABILITY.md)。
保存结果未知时先按原编号核对；历史回执不能替代当前账户读回，不能据 `found:false` 自动创建替代记录。
只有使用者核对全部账户并再次明确确认，才结束未完成的核对；原请求仍可能完成，编号继续可查。

生产升级必须使用 [55→58 发布方案](FINANCE-ACCOUNTS-RELEASE.md)：停全部写入者，
完成完整组备份后显式迁移，验证旧 55 表及注册库、三张空新表和新 app 启动后不变。
原 55→55 来源发布工具不适用；任何失败保留证据，不自动重放或恢复数据库。
