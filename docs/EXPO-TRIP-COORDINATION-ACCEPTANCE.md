# Expo 旅行地点与日历：发布与验收记录

**2026-09-17 09:25:21（北京时间）实际激活，09:25:52 正常 TLS 读回通过。** 旅行详情的「旅行地点」「同步到日历」已上线。本文区分实际运行包、本地模拟云端验收和未完成的本人真实账户验收；发布后的文档提交不改变安装包或构建来源。

<a id="expo-trip-coordination-release"></a>
## 实际发布：55→55

运行 main `f7126dd59348eecfc749534953423d1df45dea14`，与下方受验 source 同树。发布包 SHA256 为 `e2314cd61234e3039fb988208e711aedee8a8c391e2cada68477b15dd2040c97`，manifest SHA256 为 `b2095ebe61b64980f5d9d87a17d5b11e434ecf7e378232cdc91b8ffadaf0334f`，包含 534 源文件与 113 运行文件；相对上一安装版本为 13 修改、19 新增、1 退役。

发布目录 `/opt/family-dashboard-releases/trip-coordination-55-20260917T012423888227Z`；镜像 `sha256:32b81bb0af5882333c1fafd5dfe9ca99b9eaf5c70999cd215dbe749bfad84c1a`。第二轮与第一轮使用同一镜像和业务字节，第一轮因验证资源不足被拒，详情保留于下文。

实际 1 户两库在停写后完整组备份并验证；55→55 不迁移，`schemaChange=false`。停写后的安装前快照与新 app 启动后快照相同，原 55 表及注册库的行、schema、序列保持；当次生产持仓操作回执为 0 行，非空回执保全由合成测试覆盖。五份 `activation-proof` 原件逐一匹配激活报告的 SHA，before／after-app 同为 `a00af82947e7b0cda86add967d5d87e8a868c3809f2e949dc6f6ee9e47e215c8`。

正常 TLS 读回核对 534 源／113 运行文件、75 项 HTTPS 静态资源；24 项内部生成资源和 1 项退役资源拒绝访问，22 个受保护 API 匿名返回 401。app／sync／media／web 均运行、重启计数 0，app 健康，原环境配置保持。

上线后新一次 backup service 成功、timer active，InvocationID `aebd7f9e96cb4986b35c9b5cea259bb9`。新备份 `manifest-20260917T012548578961Z.json`（SHA256 `b9a02523cef7907e35fb6b387acff74e75ab791bb9dda04d8b609c661ce9a473`）验证完整 1 户两库及 55 表结构；这是逐库在线备份，**不是跨库全局事务或再次核对 live 全组快照**，`liveGroupSnapshotRechecked=false`。

正式原件位于 `A/trip-coordination-tools-20260917-r2/server-evidence/`：`activation.json` SHA256 `5aa2285ff9c540a7359bd2120510343542e082f2d647b0a20ae1e67891ad2809`，`post-readback.json` SHA256 `5a4164b316321bbfab4b8c53037a958d22afe637c85b76b7fd8fa2095f30f9a8`。激活与读回时间分别为 UTC 01:25:21.239777／01:25:52.881797。发布流程和不可重放边界见 [发布记录](TRIP-COORDINATION-RELEASE.md)。

## 冻结身份与原件

以下路径以本机工作区根 `A = C:/Users/caesarf/Documents/Codex/family-dashboard-access` 为起点，原件不入 Git。

| 项目 | 实际身份 |
| --- | --- |
| 浏览器 source | `5d8a0c4d5e96a209ad80e6dddd80a086969f31d9` |
| source tree | `7a5ffaf5ea5f781f0b93c84901921363aab98a72` |
| 构建目录 | `A/expo-trip-coordination-build-20260917-r3`，23 个导出文件 |
| build-evidence.json SHA256 | `6ef09e1985eca4251b2e0e19c7fe2ffa0ecf59581f98f9f378d79eab8153db14` |
| JavaScript 入口 | `entry-e82094d8b3912a793408ecedc92061e0.js` |
| 浏览器报告 | `A/worktrees/expo-trip-coordination-tests/test-results/expo-trip-coordination-20260917T003550087190Z/result.json` |
| 报告 SHA256 | `8b6b9c9de9376c02bb960353ad83ecfa5d3e14e262f43a8059d0fcad5d0c9160` |
| 实际 harness SHA256 | `61e45d1d435c360383bc449c31e7dd09e1acf5b46bdafa2f6e7f1db543118307` |

报告核对 source 与 bundle 运行前后字节均不变；20 组通过，零页面异常、零外部请求、零模型调用和零生产写入。

## 已完成验证

- 各组件先经非作者独立审查，再审旅行／地点／地图／照片／日历组合契约。组合审查发现日历操作遇到 401／403 后仍短暂显示旧私人内容，修订 `a16246159231449aad86799e5545e671e0696779` 立即隐藏内容并刷新身份，同时保留可能已提交的未知状态；定向复审通过，第三轮源码包含此修订。
- Node 日历逻辑 11 项、地点逻辑 17 项分别通过；组合 TypeScript 检查及 Web 构建通过。这些是对应执行记录，不视为完整前端测试集。
- [日历会话及回归](CALENDAR-SESSION.md) 四模块共 115 项通过；[地点版本及回归](EXPO-JOURNEY-PLACES.md) 两模块共 115 项通过。它们分别执行，不合称一次完整套件；发布适配器另有 13 项通过。第一轮 Linux 的 545 项实际失败，不能用上述专项通过替代，见下文。
- 真实临时 HTTPS Flask、SQLite、Edge 完成两个提供方各 7 组主链，另有两个提供方各 401／403／429 三组后验身份故障，共 20 组。覆盖明确保存私人计划地点、地图选中及返回、预览零写、丢失提交与提供方回复后的恢复、同一远端事项改期、时间语义复核、云端冲突、停止／恢复、权限撤销、跨成员／跨家庭和迟到身份响应。

日历 HTTP 由合成 `Remote.transport` 承接，实际 provider adapter、队列、worker 和本地业务 API 正常执行；合成 OAuth 数据不能证明真实授权。六组后验故障只替换真实确认成功之后的一次 `/me` 响应，并延后该页面的十秒轮询以控制交错；没有伪造业务保存成功。详细操作与限制见 [测试设计](EXPO-TRIP-COORDINATION-TESTS.md)。

## 视觉范围与失败留存

第三轮产生 12 张截图：Microsoft 路径的私人计划地点、日历预览、时间复核，各 320／390／1040／1440 四宽；验收作者逐张查看。自动指标均无横向溢出或所检测的控件裁切；原 320 宽地点截图有标签重叠，保留该过渡帧，不称全部原图无瑕。截图仅覆盖各次实际滚动位置，不代表长表单全部区域。

同 source／bundle 的补充检查等待 300ms 和至少 800ms 后各截图一次，验收作者查看两图均标签正常、无持续重叠，且图片字节相同；结果支持动画过渡的解释。原件 `A/expo-trip-320-visual-probe-20260917/20260917T003928068001Z/result.json`，SHA256 `40bcba83541a9a6f8d81d050a44560fb43f97947022ed89eac7f2538426f6838`；两图 SHA256 均为 `eb022faee9184ad35cc11ba3a77d149ffc96c9aec1db2ac7a53fbc8534a4c133`。该检查只通过真实 API 新建一条合成旅行并打开地点表单，未保存地点、未重跑 20 组；零页面异常／外部请求，source 与 bundle 前后不变。

前两轮失败原件保留在同一 `test-results` 父目录，未被第三轮覆盖：

| 原件目录 | 实际结果与原因 |
| --- | --- |
| `expo-trip-coordination-20260917T002740842189Z` | 1 组通过后，“旅行地点”图标进入可访问名称，原 selector 定位超时；尚未保存地点。报告 SHA256 `51d4ff8aa4fbba35ab69ff8a94a9ed2dd60f319c4dfc2de1a3d0dc98d3d6d358`。 |
| `expo-trip-coordination-20260917T003234435777Z` | Microsoft 7 组主链通过并生成 12 图；新增故障 fixture 缺目的地，被真实预览接口 400 拒绝，尚未执行该故障注入。报告 SHA256 `71147ce9d0f62664e0621ad0275ec1c5ed600e5c37346c35f516d10d0aa406da`。 |

第一轮修正 selector，第二轮补齐合成目的地；保留真实业务断言。三次结果不相加，也不声称所有命令首次即通过。

## 第一轮 Linux 验证被拒

`trip-coordination-tools-20260917-r1/server-evidence/validation.json` 的 `allPassed=false`：545 项中 **411 通过、10 failure、123 error、1 跳过**。唯一跳过为 `tests.test_frontend_runtime.test_windows_junction_rejected`，原因是 `Windows junction semantics`。逐条检查全部 133 项异常，均含 errno 28、No space left on device 或 SQLite disk full；集成人核定该轮 256 MiB tmpfs 用满。资源不足不等于这些业务测试已通过。

原报告 SHA256 `2f39765197cc45431a39c8745c6d8508b5ae86ea17761adc04b407793b34aa30`；`validation/results.xml` SHA256 `3993cba81fb53f83ff32e0b3241f8eeae5d9e4a61bef052dcceae2e2c21aecfd`。第一轮未 stage、未激活、未写生产；失败原件保留，不覆盖。

第二轮保持六个包文件、业务源码、前端和测试原字节，仅在私有 `validate.py` 将隔离验证容器内存由 512 提至 768 MiB、tmpfs 由 256 提至 512 MiB，经独立复审和新绑定执行；binder 继续沿用原 packager 及 package-checks 链。Git 生成器仍保留原 512 MiB 内存／256 MiB tmpfs 默认值，未自动包含此次调整；重新生成须另行审查实际资源，不可重放本轮固定算子。

第二轮实际 **545 项＝544 通过＋1 个相同 Windows 专属跳过，零失败／错误、零 deselect**，JUnit 602.711 秒；受验运行文件在测试前后核对通过。原件在 `A/trip-coordination-tools-20260917-r2/server-evidence/`：`validation.json` SHA256 `3fe385a9c8637134f8f82f6ada5479c480895b7a41949066819e923085b0c7a9`；`validation/results.xml` SHA256 `9296fe9edc899c7f56cc97dcfdaeba42e5dc8dbea14b147badd58a44779a61d3`；`ready.json` SHA256 `ab8076467bb4b3d6665292f6acc2ac6a1384b69e656b87e92e917661378967c2`。两轮及早前专项不相加；READY 之后的实际激活和 TLS 验收另见本页顶部。

## 尚未验收与接手边界

本人真实 Microsoft／Google 新写权限、实际云端创建／改期、真实模型、实体电视和 native 均未在本轮验收；部署成功不代替这些用户流程。普通旅行改期更新关联本地日程及已授权的日历队列，**任务截止和地图地点日期不会自动移动**。目的地须本人核对后保存，默认私人、已计划、隐藏坐标，不推测位置或到访；高级日期段 fixture 不等于 Expo 已实现全部分段编辑。

后续接手先看 [使用与组件接线](EXPO-TRIP-COORDINATION.md)、[地点边界](EXPO-JOURNEY-PLACES.md) 和 [日历面板](EXPO-JOURNEY-CALENDAR.md)，从独立分支继续，下一次发布重新绑定当前身份，不重放旧算子。页面刷新不会恢复未保存草稿或未知提交凭证，应先读回现有记录。
