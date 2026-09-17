# Expo 旅行地点与日历：候选验收记录

本页记录本地源码候选，**尚未部署**；当前安装版本见 [README](../README.md)。实际浏览器第三轮已通过 20 组检查，视觉复核范围和未完成事项见下文，不把本地模拟云端结果写成真实账户验收。

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
- [日历会话及回归](CALENDAR-SESSION.md) 四模块共 115 项通过；[地点版本及回归](EXPO-JOURNEY-PLACES.md) 两模块共 115 项通过。它们分别执行，不合称一次完整套件；发布适配器另有 13 项通过。更大集合的 545 项仅完成收集，尚无本轮 Linux 实跑结果。
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

## 尚未验收与接手边界

本人真实 Microsoft／Google 新写权限、实际云端创建／改期、真实模型、实体电视和 native 均未验收，本轮未操作生产。普通旅行改期更新关联本地日程及已授权的日历队列，**任务截止和地图地点日期不会自动移动**。目的地须本人核对后保存，默认私人、已计划、隐藏坐标，不推测位置或到访；高级日期段 fixture 不等于 Expo 已实现全部分段编辑。

后续接手先看 [使用与组件接线](EXPO-TRIP-COORDINATION.md)、[地点边界](EXPO-JOURNEY-PLACES.md) 和 [日历面板](EXPO-JOURNEY-CALENDAR.md)。发布仍须新冻结包、Linux 实跑和独立发布审查；页面刷新不会恢复未保存草稿或未知提交凭证，应先读回现有记录。
