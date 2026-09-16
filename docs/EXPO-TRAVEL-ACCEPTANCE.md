# Expo 助理与旅行协作验收

本功能已于 2026-09-17 07:38:17（北京时间）激活，07:39:46 正常 TLS 读回通过；当前入口见 [README](../README.md)。界面延续当前 Expo 官网的白底、黑色胶囊按钮和浅灰圆角卡片，复用 React Native Web／Paper，没有新增依赖。

<a id="expo-travel-release"></a>
## 实际发布与运行身份

运行包与后续纯文档提交分别记录；本文不改变已安装 manifest。发布目录 `/opt/family-dashboard-releases/expo-travel-55-20260916T233718910034Z`。

| 身份 | 实际值 |
| --- | --- |
| main／source | `6b2bb55758fce0df02f51252d5eac2441b7c9869`／`e0c1c6b03e14424bc170d1aa7d7c28529b381801` |
| tree | `bb00b3b6cde61296d7860fec56e7a2b0acf373ef` |
| manifest SHA256 | `4534b837252ec4cb31d7bc0ad074cfff53f1b0901117cbbfd234c6d570378e9c` |
| archive SHA256 | `6b652f275cfebcb67f1dc382734218ef7a095d198734064f9329c0dad27e284c` |
| app／sync／media 镜像 | `sha256:b394b59bc8e13f60d597f01e87e887c90358be81b073a928f6430d6a5b5b576f` |
| 内容 | 516 个源文件、113 个运行文件、23 个前端导出；构建与浏览器身份见下方 |

新镜像 Linux 11 模块收集 330 项，329 通过，唯一跳过为 `tests.test_frontend_runtime.test_windows_junction_rejected`（`Windows junction semantics`），零失败／错误，JUnit 350.537 秒；运行文件在测试前后核对保持。Linux 不执行需要 Node／TypeScript 的两组桥接测试，这些检查按下方 Windows 实际记录单列；各组有重叠，不相加为一次完整测试。

实际停写并完整备份 1 户两库；55→55 不执行迁移，`schemaChange=false`。新 app healthy 后的全部 55 表行、schema、序列和注册库与停写快照相等，随后才启动 worker／web；原配置保持。生产持仓操作回执当时为 0 行，允许非空及保全已有回执由合成双户测试验证，不能表述为生产已验证非空回执。`before.json`／`after-app.json` 同 SHA256 `3c314d127120f3e53312da1ec927020fc445279f28c778537c53046947273e4a`；五份 proof 原件均与激活报告绑定匹配，分别记录备份、备份核验、停写前快照、新 app 启动后快照及保全结论。

正常 TLS 读回核对 516 源／113 运行文件、75 项 HTTPS 静态资源；24 项内部生成路径及 1 项退役资源拒绝访问，22 个匿名 API 均返回 401；四服务 running、零重启，app healthy，配置保持。新备份 invocation `5c4f380aa6a14f29893c0892ec9f45ae` 成功且 timer active，其 `manifest-20260916T233942616081Z.json` SHA256 为 `edee484ee0486297f42e308cfb00da48b974a950aef6bf934f7960154b29f9b8`，完整 1 户两库备份的散列、55 表及注册结构可读性核验通过。这是逐库在线备份，`liveGroupSnapshotRechecked=false`，不等同跨库全局事务或再次读取 live 全组快照。

私有原件位于 `expo-travel-tools-20260917-r1/server-evidence/`：

| 原件 | SHA256 |
| --- | --- |
| `activation.json` | `a491513a35d07bb75f06f82823fa54a8e8df03f3c755b7285a233babbebda39b` |
| `post-readback.json` | `1733bc5ae69e49debfa3dd5f54b76ca5799ed422f146fcbc853c36e552ae21fa` |
| `validation.json` | `2965b200962c59e86f4192c0e11ccf1c36011a39a17bfba0df3595ad4accd115` |
| `validation/results.xml` | `a6e6cf268764e765b65c622d757fc90e712a940a1a58e129de19fd4b88f14bde` |

首次读回封装命令遗漏必需的 `--reviewed-sha256`，在 argparse 阶段退出 2、未运行读回或备份；`post_readback-command.stderr` 保留原件。显式传入已审脚本 SHA 后，`post-reviewed-command.stdout` 记录成功结果。没有重新部署或迁移，不能写成所有命令首次全绿。此前 06:15 持仓发布身份及全部历史证据继续保留于 [验证记录](VALIDATION.md#expo-holdings-release)。

## 用户流程

在「助理」输入旅行需求并点击「整理并预览」，或打开「规划一次旅行」。核对名称、日期、成员、目的地和家庭总预算后，继续编辑准备事项、负责人、截止日期及采购预算，最后预览并明确保存。保存后在旅行详情继续查看准备和采购完成情况。明确以「待办：」「采购：」「搜索：」开头的输入保持原来的处理方式。

AI 只在用户勾选后整理本次文字。模型失败保留原文，用户可明确关闭 AI 后改用本地字段整理；不会自动重复请求。未知预算与零预算分开，采购预算不自动记为实际支出。地图地点、云日历发布、复杂分段和文件仍通过对应入口操作，本次没有自动完成这些步骤。

保存响应丢失时，当前页面保留原预览和操作标识，通过「核对原保存」沿用同一预览和操作标识安全重试，并核对原保存结果，避免重复创建。原预览有效期为 30 分钟；刷新或离开页面后不提供跨会话草稿恢复，应先核对已有旅行。后台／离线隐藏私人输入，恢复时核对身份；成员改变后清除旧草稿。服务端在同一写事务内再次检查当前会话，撤销会话后不能继续提交或重放回执。

## 实际检查与证据边界

各模块使用独立分支／worktree，非作者审查后合入集成分支；本次还审查了组合接线与写事务内的身份校验。类型检查和构建在实际安装依赖的独立构建目录运行，没有使用 node_modules 链接替代构建来源。

| 检查 | 实际结果 |
| --- | --- |
| Node 入口、简报、旅行转换 | 31 项通过 |
| 后端及真实 TypeScript→Flask 桥接 | 八模块首次 195 通过、1 个因测试目录缺 TypeScript 失败；同代码在实际依赖目录补跑该项通过，共 196 个不同用例，非一次完整全绿执行 |
| 当前 55 表备份／持仓回执与前端托管基线 | 四模块 117 项通过 |
| 完整前端类型检查 | 可访问性修正后的实际构建目录通过 |
| 浏览器前三轮 | 前两轮定位 Paper Item 外层缺 ARIA 状态并修复；第三轮已通过键盘选择，随后因测试未匹配按钮图标名称停止。全部失败原件保留 |
| 浏览器最终组合 | 第四轮 7 场景通过，0 页面错误／外部请求；320／390／1040／1440 四宽 12 张截图全部查看，均为内部滚动区当前可见部分 |
| 55→55 发布适配器 | 作者和独立审查者各运行 22 项通过；实际旧九脚本生成检查通过；正式新镜像 Linux 和发布读回见上方 |

选择控件已改用现有账户／库存页面采用的 Paper TouchableRipple、Icon 和 Text 组合，视觉、原生辅助状态与网页 `aria-checked` 使用同一受控值。支持空格键切换、单选方向键及可见焦点；无嵌套交互控件。修正由非作者审查；真实浏览器的空格键、单选方向键及对应选中状态均已通过。保存后真实重启仍保留旅行、负责人、整数分采购预算及未知预算；响应丢失后原操作重放不重复写入；两种迟到响应均不能将旧成员输入带入新会话。

以下本地测试原件均保存在私有 `family-dashboard-access/`，使用合成家庭；上方生产保全原件亦属私有，不提交 Git：

- `worktrees/integration/test-results/expo-travel-combined.xml`：首次组合及环境失败。
- `worktrees/expo-n2/test-results/expo-travel-assistant-flow.xml`：唯一失败项补跑。
- `worktrees/integration/test-results/expo-travel-release-baseline.xml`：117 项基线检查。
- `expo-journey-brief-build-20260917-r1/` 至 `expo-journey-brief-build-20260917-r4/` 各自保留真实构建及散列；r1/r2 的 148 个输入和 23 个导出完全相同，r3 包含实际控件修正，r4 只更改测试选择器来源。
- `worktrees/expo-travel-acceptance/test-results/expo-journey-brief-20260916T225800557892Z/` 与 `expo-journey-brief-20260916T230207963299Z/` 以及 `expo-journey-brief-20260916T230757847925Z/` 保留前三次浏览器失败报告。

真实浏览器使用合成家庭和实际本地 Flask／SQLite／认证；可选模型响应仅在测试中模拟。不写生产，不调用真实模型或云日历。截图覆盖当前内部滚动位置，不能宣称整页每个位置、原生安装或实体电视通过。

最终受验来源 `ce5885035d13ba24d350dd6ad17aa8a1e39c0f20`，tree `98bfb35b1fdf5957437c58e8a451480e43ff6ef2`；构建证据 SHA256 `9d202c1b96a3060cd14ce417c3e27367d6f023a6344f75206edcdd253f083c71`。最终报告在 `worktrees/expo-travel-acceptance/test-results/expo-journey-brief-20260916T231150309219Z/result.json`，SHA256 `452e6ffb6bf6e76e6b30fcfe03b3b9d2087499f6464b4dea6c67267b4092dac7`；受验源码和导出均未变化。模型替身只验证一次失败后明确本地恢复，不是模型成功生成或真实模型质量验收。后续文档、发布工具合入与受验运行输入分开核对，不能改写该原件身份。

发布采用独立审查的 [55→55 适配器](TRAVEL-RELEASE.md)，实际保全范围见上方；后续发布须重新绑定当前 55 表、镜像及 manifest，不能重放旧 54→55 迁移或本次固定发布操作。

## 最终场景的剩余工作

本次完成的是场景 A 的旅行简报、准备与采购协作子流程。完整的地图联动、指定真实日历写入、改期协调及实际完成跟踪还需组合验收；文件导入、真实模型质量和实体设备不能由本轮替代。场景 B／C／D 及其他未完成范围继续按 [产品计划](PRODUCT-PLAN.md) 推进。
