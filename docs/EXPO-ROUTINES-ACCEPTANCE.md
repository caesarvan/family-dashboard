# Expo 家庭例行计划验收

本轮把已有周期家务／采购规则接入新版「更多 → 家庭例行计划」。规则、worker 与表结构保持；预览给出后续三期，明确确认才生成事项。计划在家庭共享，负责人是分工；操作回执只由发起成员读取。本地 R3 十组真实流程已通过，Linux 与发布仍待完成；真实家庭、云端、长期调度和实体设备未验。

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

Linux 和生产验收仍待完成，单独提交或合入 main 不代表已部署。

## 范围边界

只生成本地共享待办或采购，不自动写 Microsoft／Google、不下单或计入付款。预览／回执 GET 不写业务记录，未知结果保留原凭证；GET 404 不证明未写，只有写锁内精确 410 才允许重新预览。完成 PATCH 没有操作回执，失败只读核对。历史回执与当前计划分开，不恢复删除／归档内容。实际显式 worker tick 的效果不等于长期墙钟调度验收。

实体电视暂时无法验收，保持待确认。屏幕阅读器全站审计、真实云、本人新流程、原生安装与完整产品目标另行跟踪。
