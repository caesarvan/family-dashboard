# Expo 家庭例行计划验收

本轮把已有周期家务／采购规则接入新版「更多 → 家庭例行计划」。规则、worker 与表结构保持；预览给出后续三期，明确确认才生成事项。计划在家庭共享，负责人是分工；操作回执只由发起成员读取。本地 R3 十组真实流程及 Linux 277 项通过、1 项精确 Windows 跳过分别核验，2026-09-17 19:21:11（北京时间）已激活，19:21:45 TLS 读回通过；真实家庭、云端、长期调度和实体设备未验。

## 固定实现与审查

每个作者在独立 `codex/` 分支与物理 worktree 开发，经非作者固定差异审查后由 Root 合入候选。共同运行基线为 `c7bffed2aa51d55b88197d9c84ecbe1b7bc27337`；接口分支的原开发基线为资料候选 `e4499b88b89124f19fd6eb040435d133bdfffc7d`，并非另一个部署。

| 内容 | 接受的 head | 独立审查 |
| --- | --- | --- |
| 事务内会话核验、过期恢复、本人回执 | `9c440dde11ba33ddd398e746e7034f33798c951d` | Root PASS |
| 更多入口与来源导航保护 | `2d4bc881654c10d985837dda60f7cad147489522` | acceptance PASS |
| Paper 面板与客户端模型 | `19936b0096b12ba0ebbc9cfb306d1b1c76860124` | acceptance 复审 PASS |
| 真实浏览器专项 | `4837e0108a8988834dd9666bf2d2e86d69d73721` | UI 作者初版及增量审查 PASS |
| 55→55 发布适配器 | `4ba02fe9b0761475d04025835643069056ea30d2` | 非作者 UI agent PASS |
| API 与生成路由清单 | `73e99ff94fc674d57d492d1ab89f7f3cfc2b3201` | UI agent PASS |

组合 `0e6e16f0bab28ae7e94998e51bdfbe2d5548720f`／tree `9af55bb219e3c199b5feacb2a793e7808fb66a4a` 经非作者审查调用关系、DTO、身份与未知恢复接缝通过。原 UI `1f6f98c` 在保存成功而 context 读回失败时会留下旧操作，审查发现后由 `19936b0` 明确清空旧详情，仅保留已确认提示和读取按钮；浏览器增量检查实际完成及暂停后的此状态。该修复前的审查不视为最终通过。

## 已执行的模型、接口与构建检查

- API 实际一次 132 项通过（34 会话、81 原规则、17 跨模块），0 失败／错误／跳过，80.93 秒。`expo-routines-api/test-results/routines-session-r2.xml` SHA256 `26acd13466dad5d62606e436bb91ad50c1cc44742684c45d7949f279f9c5086b`。首轮新增测试对 Cache-Control 字符串的预期错误已按真实禁止缓存契约修正，失败原件保留。
- UI 作者模型 14 项通过，TAP SHA256 `993859177653f4cbc94634deebd40dac31b796c6c12673bb796af11294b2c83c`；另以真实临时 Flask／SQLite 生成两类计划各六种操作，12 组 DTO 由客户端解析通过。该次不是浏览器或生产证明。
- 组合目录实际安装 587 个锁定物理依赖，`npm run typecheck` 退出 0。Root 最初直接 `node --test` 遗漏 TS 转换参数，Node 在加载参数属性时失败；补 `--experimental-transform-types` 后同一 14 项通过，日志 SHA256 `4a921a3ae2ab689cdcbcf5d096863801f091d826153ce8bf8f09e2cd9a50486e`。没有为工具调用错误修改产品或放宽断言。
- 发布适配器独立 24 项通过；JUnit SHA256 `6b1a13211e7384ce1b362bcfcbc11346503055c7860d0f5f7dff746fc57a98b9`。真实父九原件／旧包核验、29 非法 freeze 和 7 未绑定入口拒绝另有报告 SHA256 `89c4f6564978b0e739d2bc1d68a03b983c13c618cae3ba4f8f57d139adfeeb5e`。这是本地生成检查，不是服务器执行。
- 实际 Expo R1 导出 23 文件，构建 source／tree 为上述组合；`expo-routines-build-20260917-r1/build-evidence.json` SHA256 `cc0dc7accb617e61d899279624d8897fc29a55ebdccc20feca1bfa71e62fdc66`。构建脚本相对资料 R4 仅更换物理 ROOT，经非作者逐字节审查后执行；保留输入／导出来源，不使用依赖链接或占位代码。

私有路径根为 `C:/Users/caesarf/Documents/Codex/family-dashboard-access/`，分支报告在 `worktrees/<分支目录>/test-results/`。报告、日志和截图不进入代码库。分次检查保留各自范围，不相加成一套“总通过”数字。

## 浏览器与发布

九个服务器回归模块实际收集 **278 个唯一项**，只收集、尚未执行。收集源为 `0e6e16f0`，603 份源码前后相同；私有 `expo-routines-validation-20260917-r1/collection.json` SHA256 `22cd48215ab8daab6c9b192b229db72041e9b4d9a40e4de55bab022418765f77`，guard SHA256 `67114585ecf6151ffdd24cec1f1beb91ce087666ac38fac5787eae1a8d5c6568`。Linux 结果必须另行核实际 JUnit，不以 collection 代替。

浏览器 R1 实际 **2／10，整体失败**。第三组在读取已收到的恢复确认响应时，Playwright `Network.getResponseBody` 报无数据；当时界面已显示恢复操作确认、正在读取当前计划。这属于测试工具再次读取响应 body 的失败；没有证据证明产品发生页面导航，也不能把已保存当成该流程通过。`d9d8b7461a72dd412abf8cc07bcefae0f9a6304b` 仅将普通 confirm helper 改为一次真实请求后先保存原响应字节，再原样转给页面；200、DTO、UI／DB 及单次写入断言保持，经 Root 非作者审查后合入。故障专用分支和产品代码均未改。原件 `worktrees/expo-routines-browser/test-results/expo-routines-20260917T103442188522Z/result.json` SHA256 `c785480e6e30df1982afafe921c1a1fd06759032ad615fccf8bd08d6357485c6` 保留，603 源／23 导出前后相同、临时夹具清理完成，零页面错误和外网请求。

R1 已生成的 12 张图覆盖 320／390／1280／1920 的浅色编辑／确认与深色详情，由非执行作者逐张实际查看，可见区域无视觉阻断。`visual-review.json` SHA256 `2195a29ffd2a6ad48233ba91d06e76770c883fb0bb24184b5733f6c19acc9308`；Root 另抽看 390 编辑、1920 确认和 320 深色详情。部分内部滚动区、编辑底部及详情底部未被拍到，不声称整页视觉覆盖；截图通过不改变 R1 功能失败。

R2 已重新实际构建：source `8a9cbc1d85b966e051a64e4568006bce40af5695`／tree `ec0805099fc4055e6f356da2c0639925afda760e`，`expo-routines-build-20260917-r2/build-evidence.json` SHA256 `acce3f2521af2b5534f19051a686a1e8a3a95fe477ad85a8b51a4e7e812e2df0`。与 R1 的所有构建输入及 23 导出摘要逐项相同，变化仅为测试脚本；未重复已通过的 Node、API 或完整类型检查。R2 浏览器实际 **3／10，整体失败**，其中原第三组的全部推进与恢复检查通过。第四组把同户另一成员与不同家庭的 token 拒绝都期望为 403；实际不同家庭使用独立签名密钥，先以精确 400「预览凭据无法核对，请保留草稿」拒绝，同户另一成员才返回 403。原件 `worktrees/expo-routines-browser/test-results/expo-routines-20260917T104317497397Z/result.json` SHA256 `5135a236ec20f66b849eb0615a39b077466c4d2bd41832fcb8dd55fc99472eb6` 保留，源码／导出未变，临时夹具清理、零外网／页面错误；12 图仍保留。R1/R2 产品代码及导出逐字节相同，沿用 R1 真实视觉范围，不把相同 UI 的重复截图另算验收。

R2 九模块 collection 仍为 278 唯一项，未执行测试；source `8a9cbc1`，原件目录 `expo-routines-validation-20260917-r2`，collection SHA256 `4bb1b854f53cf66a95d2c09b3f6f070192cfbaf67e2dd470e902890143a786e9`，guard SHA256 `b1849a2014d31f840537f638c973f4832382975060af5b55c2a4c68c0a833938`。`e3290cd238612d34d7f54015416600fe616729aa` 修正两种精确拒绝码并增强零写断言；每组改用独立 Flask／SQLite／签名时钟及临时目录，资源清理后再开始下一组。任何场景或清理失败均保留原异常、移除该组完成数，并使整轮失败；其余独立组继续以便一次查齐问题。该测试与说明增量经 UI agent 非作者审查后合入。产品代码未改，前两轮失败不覆盖或拼接为通过。

R3 实际构建 source `785db20b5abb1b7677fe02417cc055874772e651`／tree `b289eef94c2ed663a2b7f90f21579d859e7b0253`，build-evidence SHA256 `e7a3f3166576976799a7cc7ece81b98978df7a9aedc2f7bd61de869781811d0a`；174 输入与 23 导出继续逐项等于 R1/R2。R3 重新仅收集九模块 278 唯一项，604 源文件前后相同；`expo-routines-validation-20260917-r3/collection.json` SHA256 `0ac8979a387ae9cfa20f060e76f56c2c283f8568f0444953e95337c5fe0a8cb4`，guard SHA256 `5f5dd22286e96fa9c3adc2da620606e986d9e2c61b3a3ccbb1912fb0bb5bcc1b`。本轮来源和失败历史分别保留，不能把各轮的部分完成数相加。

R3 真实临时 Flask／SQLite／Edge 实际 **10／10 独立流程通过**，退出 0。原件 `worktrees/expo-routines-browser/test-results/expo-routines-20260917T105419250478Z/result.json` SHA256 `63d9dd90b572957600fc24cae7afa7a849e92e8ca07b0b415c45dec3ecf4d493`，执行 harness SHA256 `8949911ca4cfea8c24c8d77deadeecf9fd03e415d5dd97ed8456d7da18afcd7c`。十组全部清理完成，scenarioFailures／pageErrors／externalRequests 均为空；604 源及 23 导出前后相同，零生产写入。12 PNG 实际生成并逐摘要核对；产品输入／导出与前两轮相同，沿用 R1/R2 的已视查范围，不重复作无变更视觉检查。

实际通过涵盖待办创建与重启持久化、采购未知／零预算、完成与真实 worker 逐期推进、暂停／恢复／跳过／归档、保存成功但读回失败时旧操作失效、同户共享管理及跨户／TV 隔离、409 保留草稿、已提交／未到达的未知恢复、过期原请求重放与精确 410、后台／离线及迟到账户结果丢弃。每组使用独立虚构家庭，没有成功业务响应替身。签名时钟推进 601 秒、visibility 注入和显式 worker tick 是测试条件，不代表真实经过时间或长期调度验收。

上述为本地组合验证记录。后续 Linux 与生产结果见下方发布段落，不能用单独提交或合入 main 代替部署验收。

## 范围边界

只生成本地共享待办或采购，不自动写 Microsoft／Google、不下单或计入付款。预览／回执 GET 不写业务记录，未知结果保留原凭证；GET 404 不证明未写，只有写锁内精确 410 才允许重新预览。完成 PATCH 没有操作回执，失败只读核对。历史回执与当前计划分开，不恢复删除／归档内容。实际显式 worker tick 的效果不等于长期墙钟调度验收。

实体电视暂时无法验收，保持待确认。屏幕阅读器全站审计、真实云、本人新流程、原生安装与完整产品目标另行跟踪。

## 最终发布准备

已审候选 `654b1e90df5facaf1da1c9b774231c0ba00e1c57` 合入正式 integration `3d8e90aec1a4006d99bb26a51464d0ef0f5404f0`，再合入 main `3387bc0c29f02ef89549d5ec56ce94f51cff67b0`，同树 `f8dc8e5d33f3c5e447c1fcfe5eed2b5e2cbf989e`。相对 R3 仅四篇文档变化；174 构建输入、275 Python 源及所有执行夹具均与实际受验版本匹配。

最终 `expo-routines-freeze-20260917-r1.json` SHA256 `1712c7848500b9d209df09bd6b4e1e50ab680469ac869bb5ccd77e05b18478a6`，完整差异 18 改／14 增／1 删。九个实际生成文件经非作者固定字节审查，等于已审适配器对真实父原件及最终 freeze 的输出；stage／validate／expo_contract 与父逐字节相同。55→55 无 DDL、原行／schema／序列／平台库保全、896 MiB 内存及 640 MiB tmpfs、精确 Windows 跳过和阶段不得重放等保护保持；post 另新增两个例行匿名接口严格要求 401。

七算子审查绑定 `operator-review.json` SHA256 `418ea569e3b6cbfe63e4749c508211185522ac269b16e563a09d16198515f8d4`。首次 freeze 调用误用了相对路径，被绝对路径保护在创建输出前拒绝；改为绝对路径后冻结成功，未放宽校验或执行生产操作。编辑器自动生成的九份 `.VSCodeCounter` 统计报告留在原位，逐份摘要保持，仅加入本地 `.git/info/exclude`，不进入源码提交或发布包。

本节记录冻结和工具审查，实际 Linux 与生产结果如下。

<a id="expo-routines-release"></a>
## 实际发布：2026-09-17 19:21

已安装 main `3387bc0c29f02ef89549d5ec56ce94f51cff67b0`、source／integration `3d8e90aec1a4006d99bb26a51464d0ef0f5404f0`，同树 `f8dc8e5d33f3c5e447c1fcfe5eed2b5e2cbf989e`。五阶段 build／validate／stage／activate／post_readback 各执行一次，均退出 0；激活于北京时间 **19:21:11** 完成，正常 TLS 读回于 **19:21:45** 完成。后续文档或工具提交不改变该运行身份。

- 发布目录：`/opt/family-dashboard-releases/expo-routines-55-20260917T112012308579Z`。
- 候选及阶段报告目录：`/opt/family-dashboard-candidates/expo-routines-tools-20260917-r1`；本机同名私有目录保留原命令 stdout／stderr。原件和后续独立读回均不进入 Git。
- archive SHA256：`41735eb43154748bc912e4216c07b7131f7fdbd91e668c8c0da8afa8e1d95e55`；manifest SHA256：`0cb3bb21365f6dc923264b1a6504396dec303a932b766e926f336937580ad8a4`；绑定 SHA256：`1468a4d0c35c27f195b04113a83893c1efd083f17537fe85ece8df8dd70ebf34`。
- app／sync／media 镜像：`sha256:3c576cd3814f7ec8482ff190017eb3cc9a4c3b6dd2dd0aee7d9623e8d9ae7125`；web 镜像保持 `sha256:1ae82dcc4a34bcd976195b3c4c5a6b7e569505527a1e2a28c2101e032159a5c7`。
- 实际 Linux 九模块共 **278 项：277 通过、1 精确跳过、0 失败／错误／deselected**。唯一跳过为 `tests.test_frontend_runtime::test_windows_junction_rejected`，理由 `Windows junction semantics`，无通配跳过。JUnit SHA256 `1e65ef28a6255e59a1478e69159fef6aceb80b8b83a1cfe62eb3f5eaaa3b6517`；日志 SHA256 `c55c574c9ed0dd932b20a8481ceaae78e09e2a7fffd7558db80a54d0dd013a9a`；runtime SHA256 `5a257bd53b94327ff8ffa542173e81b7f33e5f2a924c259df000a82d34f542f7`。运行来源前后核验通过，未用 collection 代替测试执行。
- 包含 **626 文件＝603 选定源码＋23 导出**，实际读回 626 文件及 114 个运行文件；75 项 HTTPS 静态资源摘要、24 项生成内部资源拒绝和 1 项退役资源拒绝均通过。Expo 页面、`/tv` 精确跳转与 classic 回退均核对；27 个唯一匿名 API 全为 401，其中包含本次 context／本人例行操作回执。
- 激活期间停写并完整备份 **1 个家庭、2 个数据库**；保持 **55→55**，无 DDL。原表的行、schema、序列及两张平台注册表在新 app 启动后全部保持。before／after-app JSON 同 SHA256 `3ad80ea808581efe008fa7a012063507f85fef3fe81ad81f9622e62f970e0caf`；preservation SHA256 `9b8c0b9b4a06a13554fe04eaea9580ea0fa0fec6585e922f9a4ba1e09c407bfc`。
- 环境配置保持；四服务运行、零重启，app 为 healthy，其余三个没有健康检查字段，不能统称四项 healthy。
- post 新一次逐库在线备份成功，timer active；manifest `manifest-20260917T112140694210Z.json`，SHA256 `24f62e39465978575e031c5eba954e526ae56c89ed29e56c98eb7fff0e9cbb27`，两库和每户 55 表快照核验通过。这是每库分别在线备份，不是全组全局原子快照，也未重新获取实时全组数据快照。

独立非作者于北京时间 19:23:37 保存 13 份 JSON／XML／log 原件，远端与本地 SHA 全部一致；19:23:41 的新鲜只读摘要再次核对安装身份、四服务与配置摘要及权限 0600，并单独核对两个例行匿名端点均 401。完整绑定、构建、验证、READY、激活、post 及五份保全原件链通过；JUnit 为 278 唯一项、277 通过及唯一精确跳过（329.71 秒），集合与 R3 collection 一致，37 个实际加载模块及 114 运行文件在测试前后保持。

私有证据目录 `expo-routines-published-audit-20260917T112323006803Z`：audit SHA256 `f989ba5892600b48f36e0a5e6c3ff2f34d6fe39ce73395490af08ec054895e04`，readback 索引 SHA256 `a463448b1237418d09d452c5040273334997e7577900bb21c71a98a3225c5b4e`，activation 原件 SHA256 `1388af2d574328a3cfd8c5711f48aef2e7fd93550f576e460e1604643f4b11c6`，post 原件 SHA256 `df5aed15de51d8dc4e7c71602a3908315cc7103dbdf1e26da5cf8ef92d9a2b2b`。采集未下载数据库或环境配置内容，未重放发布阶段或另启备份，也未进行云端或设备操作。

本次发布证明服务、静态产物、匿名权限及启动时数据保全；没有使用真实家庭事项做写入验收，未替代本人长期例行计划体验、外部云同步或实体电视验收。
