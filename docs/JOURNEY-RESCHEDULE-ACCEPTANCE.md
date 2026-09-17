# 旅行明确改期：验收与交接

本功能已于 **2026-09-17 11:09:53（北京时间）激活，11:10:38 正常 TLS 读回通过**。此前 [09:25 旅行地点与日历发布](EXPO-TRIP-COORDINATION-ACCEPTANCE.md#expo-trip-coordination-release) 保留为历史基线；Git 提交、本地合成浏览器、实际生产读回和本人真实外部流程分别记录。使用与 DTO 见 [旅行改期](JOURNEY-RESCHEDULE.md)，完整目标见 [产品计划](PRODUCT-PLAN.md)。

## 范围与固定源码

从旅行详情「调整日期」读取当前来源快照，默认保留可选日期；选择目的地、可调整分段、未完成准备截止和本人计划地点，核对前后日期、当地时刻及提醒后明确保存。旅行总览必改，其他修改在同一事务内完成；复用稳定实体与日历发布关系，重复确认不二次平移。夏令时不存在／重复时刻必须明确纠正，不猜偏移。采购没有截止字段；完成历史、固定／预订／取消分段、他人地点、金额和共享范围均保持。

后端固定提交 `ed180fe514e57a09df8317f5f2584cb36212e64d`；界面已包含未知结果原编号读回、内层退出保护，以及父层导航保护。组合 `70164db2ef59226b51602e5ffe92f6a028183dab` 首轮浏览器失败后，`796ff077b86eac1e4036733447e9b334821687b6` 修复显式详情读取被后台刷新抢占的问题；后一提交已完成非作者代码审查，第二轮已通过原详情返回断言。随后仅修正浏览器测试对 Paper 只读输入和图标按钮名称的判断，组合固定为 `06f5bd4719031d0c14a3220e791ca29a9f98d232`，第三轮真实临时浏览器完整通过。最终受验候选合入下列正式 integration／main 后，以同一文件树实际发布；发布后纯文档提交不改写运行包身份。

<a id="journey-reschedule-release"></a>
## 实际发布身份

| 项目 | 本轮固定身份 |
| --- | --- |
| 受验候选 | `06f5bd4719031d0c14a3220e791ca29a9f98d232` |
| 正式 integration／main | `0059cd9da2db43e1ad4f4cc95edc15b9bb3804a7`／`2092cc43c4660df905755475706a88dfd62e7203` |
| 三者同一文件树 | `07540964da68469d3861436afa04bb5dd8b36415` |
| r3 构建证据 SHA-256 | `11202ddc785b993532162dfee14b7d158497ce8e22121b855824f711971ec775` |
| Expo 入口 | `entry-05b4fba7a1cb356f406840a7f4939342.js` |
| app／sync／media 镜像 | `sha256:b83c0d9c272c00932d10a21640f0902776189bbfbef6e82a8dc05463330c6250` |
| manifest SHA-256 | `0d07e455fbda2e22ddd69a47e733afbd2e6f520eba2a8fc315e6409286e4f384` |
| release.tar.gz SHA-256 | `8b3d994670549e8353714e0874870f2bb446876a0bd2223183aa724e59ae7373` |
| 发布目录 | `/opt/family-dashboard-releases/journey-reschedule-55-20260917T030856597795Z` |

实际 1 户、两库在停写期间完整备份，55 张户内表及两张注册表的行、schema、序列在新 app 启动核对时保持；`schemaChange:false`。随后正常 TLS 读回核对 545 源文件、114 运行文件、75 项静态资源；24 个生成的私有资源路径及 1 个退役 JS 拒绝，24 个匿名 API 均为 401，Expo 根与子路由及经典入口通过。app healthy，四服务运行且零重启，原 web 镜像与环境保持。

发布后新一次独立 backup service invocation 成功、timer active；完整 1 户两库的 55+2 表结构与注册映射核对通过。这是逐库在线备份，不是跨库全局原子事务，也不代表再次核对 live 全组快照（`liveGroupSnapshotRechecked:false`）。

## 实际执行记录

| 验证 | 实际结果与范围 |
| --- | --- |
| 改期后端专项 | 固定 `ed180fe`，38 项通过；真实临时 Flask／SQLite，涵盖零写预览、版本冲突、事务撤权、101 个地点、历史越界保留后普通编辑、DST 时分／偏移及同日变更、幂等与回执 |
| 原相关后端回归 | 同一固定 `ed180fe`，182 项通过，控制台耗时 265.46 秒；不是对尚未冻结最终组合的一次全量验证 |
| 前端纯逻辑 | 20 项 Node 测试通过，使用 transform-types；涵盖真实回执形状、未知结果退出保护及时间 DTO 等，不能替代真实浏览器 |
| 发布适配器 | `4c9988d3aa4d8630385e47fe59f92aeb27e85a99`，21 项通过；另以真实旧包和九份固定脚本检查局部生成结果、唯一 Docker COPY 变化及未绑定拒绝。实际服务器执行结果另列，不把本地 guard 视为生产发布 |
| 新镜像 Linux | 18 模块实际 604 项：603 通过、0 失败、0 错误，唯一跳过 `test_frontend_runtime.test_windows_junction_rejected`，理由精确为 `Windows junction semantics`；运行文件前后保持，`productionOperations:false`。此前 604 项收集记录另保留，不能称为 604 项通过 |
| 首轮真实浏览器 | `70164db2`／r1 构建，1 项检查完成、8 张截图后失败；输入与导出前后相同，0 页面异常及外站请求。真实保存已返回 200，但后续详情标题断言失败，页面回到列表。`796ff077` 增加同步读取标记，阻止后台刷新覆盖显式详情读取；原详情返回断言保持，并已在第二轮通过 |
| 第二轮真实浏览器 | `796ff077`／r2 构建，2 项检查完成、8 张截图后因测试断言失败。Paper 禁用输入在 DOM 中表现为 `readonly`；断言改为不可编辑，并兼容原图标按钮的可访问名称。修正经非作者审查，未改产品逻辑；第三轮完整重跑已通过 |
| 第三轮真实浏览器 | 固定 `06f5bd`／r3 构建，16 项检查通过、产出 18 张截图；包含默认保留与明确选择、保存后详情及稳定 ID、丢请求／丢响应恢复、冲突重新核对、迟到身份隔离、DST 纠正、地图内旅行的未知操作恢复和首页可用性。Microsoft／Google HTTP 替身各创建 1 次、PATCH 1 次；源码和导出前后相同，0 页面异常、外站请求及生产写入 |

上述测试分次执行且可能重叠，不能相加为一次全套通过。浏览器使用合成家庭和提供方 HTTP 替身；本地保存或同步队列受理不代表真实云端确认。

原件位于私有 `family-dashboard-access` 下，未提交测试输出、截图或真实数据：

| 原件 | SHA-256 |
| --- | --- |
| `worktrees/journey-reschedule-tests/test-results/reschedule-api-r2/junit.xml` | `d67c3126cce6760902c26404015f9a3dcaa732dbe24068ad1ed423c84116c25f` |
| `worktrees/journey-reschedule-api-review/test-results/reschedule-existing-fixed-ed.xml` | `50aeb73ae750c8c62c00c63874d7d6c7fa8e6b72a71223d81bf1e97c7b204bb2` |
| `worktrees/journey-reschedule-release/test-results/reschedule-release-r1.xml` | `89c6df628396647cc1e5b1e2100ddfe12981f4147deafc5f91da99c3627fff73` |
| `worktrees/journey-reschedule-tests/test-results/expo-journey-reschedule-20260917T023010417214Z/result.json` | `0b69343dfb2b3e041c45399085a3de303546d9fea74625f0f9e5f48e815c0c80` |

第二轮原件 `worktrees/journey-reschedule-tests/test-results/expo-journey-reschedule-20260917T023526561072Z/result.json`，SHA-256 `d8c26e2900f6bcf240ab31922db12166b01a95fd08c3ae8e9b1671afc687219d`；未因断言修正删除失败记录。

第三轮原件 `worktrees/journey-reschedule-tests/test-results/expo-journey-reschedule-20260917T023831799000Z/result.json`，SHA-256 `ed8c285ddfea411bfd9d56db876ca2156ee9c12f62abd52aa1c3e0dcf642ceae`。截图是临时浏览器产物，不等同实体设备或所有内部滚动内容的视觉验收。

首次本地打包因 freeze 指向受验候选而非正式 integration，触发 `Integration moved since freeze` 拒绝；原始失败证据为会话 exec 输出，没有单独失败日志，另有 `freeze-correction-review` 记录。另存的 wrapper 修正两处正式分支引用，生成的 r2 freeze 实际仅改变 `integration` 字段，源码与九份算子保持。失败时尚未绑定，之后沿用原 review 绑定新 freeze；不改写旧冻结文件或跳过校验。

服务器原件位于私有 `journey-reschedule-tools-20260917-r1/server-evidence/`：

| 原件 | SHA-256 |
| --- | --- |
| `build.json` | `1a99f30e63a9794507a9113e352b4c07ec1e9e4c2e326afbb04b06baebe90477` |
| `validation.json` | `ad5c127a1e238e71507c0b82f22a716cdab7cb2f8e7786a0e82bc0ee1d5aae97` |
| `validation/results.xml` | `9ed863e90355a75f66c9e500f1595f9e7cb331d6713e12dc904a89dc35e6ac2f` |
| `ready.json` | `41d8a8cbab1687fc599fdec353d9fe2a4e998d8235852572e88f7e60680bde47` |
| `activation.json` | `a2413a785f460071351eb447e597cdf3f0d324be4badee072be2bc9a59f04f6f` |
| `post-readback.json` | `e704d5caf4c7717004eebec72b42795a3d988b34d5d0cdefbb33b88ee061be9d` |

## 仍须验收

助理内嵌旅行的导航保护经源码审查，未在本轮浏览器覆盖；地图内嵌旅行的未知操作恢复已在本轮浏览器验证。

本人真实 Microsoft／Google 写权限与持续改期、外部冲突和状态读回、本人在线 AI 到真实行程的完整场景 A，以及实体电视仍未验收。测试不办理外部预订改签或付款；强制关闭／退出登录不是内存草稿持久化。未知结果先读取原回执和当前旅行，不能据 404 或网络失败认定此前未保存。
