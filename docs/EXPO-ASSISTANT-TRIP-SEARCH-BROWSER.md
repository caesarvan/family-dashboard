# Expo 助理查找旅行：浏览器验收脚本

[验收脚本](../tests/browser_expo_assistant_trip_search_check.py) 起点为 `37a393f149aeefb91a92da05b1d4d213b4831af0`，最终修订 `2ff717cc9da029b94bfd0839c5d3f0f1c76839c8` 已通过非作者审查。R2 六组通过；服务器验证失败后仅拆分经典浏览器测试，再对新候选执行 R3 六组与四张视口图，均通过独立复核。R1 失败原件保留。生产状态见[集中验收](EXPO-ASSISTANT-TRIP-SEARCH-ACCEPTANCE.md#expo-assistant-trip-search-release)。

客户端接缝依据独立 UI 候选 `5320576d6062390b74f46d2aff7b340f96693c7f`：显式“搜索 / 查找 / 找一下”前缀保留原文字，仅在本地查询；“查看旅行 <真实标题>”使用 `kind=trips` 的实体 ID，嵌入现有详情。返回助理保留输入及查询页码，并重新读取本人身份、概览与查询结果。详见 [助理接口与界面](EXPO-ASSISTANT.md)。

## 六个独立场景

| 场景 | 真实流程与断言 |
| --- | --- |
| prefix_routing | 勾选已配置 AI 后分别输入三个搜索前缀，真实 `/assistant/plan` 请求两项 AI 标志仍为 false；旅行、实体、关联、回执及助理计划表无写入。真正的旅行规划进入原简报接口；明确待办产生真实草案，不确认执行。 |
| details_and_return | 真实 preview/apply 创建 v1/v2 工作流，查询结果的 tripId 打开原 journeyId 详情；另用 21 条真实基础旅行验证第二页。返回恢复原输入/query/offset，必须出现新的 `/me`、`/assistant/brief`、`/assistant/search` 读取，所有旅行记录保持。 |
| delete_and_failure | 查后由真实 API 删除旅行，旧结果不能打开旧详情或编辑入口；另一个真实详情响应被丢弃，错误期间无旧详情，用户明确返回查询再打开后恢复。 |
| identity_late | 暂扣真实查询响应后，同一成员重新登录替换真实 Cookie，迟到结果被清除；隐藏/离线清除结果；暂扣真实详情后替换第二家庭 Cookie，等身份更新完成，再确认旧详情不存在且新家庭查询无旧记录。 |
| unknown_save | 从新入口编辑原旅行，真实 apply 已提交后丢响应。原保存未知时返回/搜索入口不可用，取消被禁用；仅明确“核对原保存”重用完全相同 token/key，收到真实 replay，无重复旅行。 |
| layout | 320×844 与 1280×1000 各浅/深色，共四张可见视口 PNG；长标题自然布局、入口至少 44×44、键盘 Enter 打开原详情并返回，旅行数据无写入。 |

## 来源、故障与运行边界

- 复用 [既有本地夹具](../tests/browser_expo_finance_check.py)，每场景独立临时 Flask/SQLite/HTTPS/Edge 环境，沿真实登录、CSRF、成员及家庭请求。v2 来自 [仓库虚构示例](../static/examples/journey-plan-v2.json)，v1/分页数据也全部为合成数据。
- 五个直接或传递夹具记录实际加载绝对路径及 SHA：本脚本、finance 浏览器基类、`test_financial_files.py`、`test_app.py`、v2 示例 JSON。真实 app 与助理模块路径必须属于指定源树。
- 入口要求完整固定 `--expected-head` 和 build evidence SHA，构建 head/tree 与受验源码完全一致；核全部 tracked 文件、每个构建输入及完整导出。结束再次核源树、导出、夹具、HEAD/tree/clean，任一变化即失败。
- 浏览器只允许同一临时 HTTPS origin，Python socket 仅 loopback。假配置只使 AI 勾选框可用，真实模型调用入口一旦被触达立即失败；不返回模型成功替身，不启动云同步 worker。
- 路由仅原样转发、延迟或丢弃实际响应，保存真实合成响应原字节；不修改业务成功 JSON。未知保存测试确实先提交，再丢读回，不将当前状态当作操作回执。
- 六组逐一收集错误并继续，保存失败截图/ARIA/traceback；每组结束停止服务、关闭浏览器上下文及移除临时数据库。总结果需六组、四图、零页面异常/外网/模型调用、全部清理和来源不变同时满足。

运行入口如下；每轮须绑定已审固定脚本、组合与构建证据，不把历史命令直接用于浮动源码：

```powershell
python -B -X utf8 tests/browser_expo_assistant_trip_search_check.py --source-root <冻结组合目录> --expected-head <40hex> --bundle <已审dist目录> --expected-build-evidence <64hex>
```

实际运行在作者树 `test-results/expo-assistant-trip-search-<UTC>/` 排他保留执行脚本、每组原件与 `result.json`。图片只覆盖滚动后的可见视口；R2、R3 各四图均已由 Root 实际逐张复核，未来运行仍需独立视觉复核。该验收不证明真实 AI 提供方、云账号、真实家庭资料、原生手机或实体电视可用；本地查询页面复用原旅行能力，不推断真实到访或预订。

## R1 实际执行及候选选择器修正

2026-09-18 对冻结组合 `8c63ae1df514fceb11fbb8d874be5872a921a7e3` / build evidence `57234842f3f1329f41f86cb3c626b81aa482bc83aa91ca62f806bea1ead87c95` 单次执行六组：`prefix_routing`、`identity_late` 通过；其余四组均在 `open_match` 的“编辑旅行”精确定位失败。真实 ARIA 名称带 Paper 图标前缀，原旅行详情已经显示；失败后的下游断言未执行，不判定通过。

原件 `test-results/expo-assistant-trip-search-20260918T003155164991Z/result.json` SHA `d24ef84a745be96fa1d78d776a4a1bc08eaf71edf3de86b50e21ea77a345ae4c`，完整 stdout SHA `a9c3adc99a89f8ba479dec8d779c63dea0f0578d04a58be08c1cdc13f69519ae`、stderr 空；757 tracked、23 exports、5 fixtures 前后相同，六个临时环境全部清理，页面异常/外网/模型调用均为零。仅生成浅色 320/1280 两张视口图，深色与完整布局流程未完成。

修订仅统一局部 `edit_button` 为 button 角色及末尾“编辑旅行”的锚定名称，并在进入详情时要求唯一匹配；正断言、负断言与点击使用同一定位，不修改产品或业务断言。保留 R1 原件；修订经 Root 增量审查后合入，仍要求受验源码与实际 build 同 head/tree。

## R2 实际结果

2026-09-18，受验组合 `2856f376795a8ca1519cb2c7739993caee466f5d`／tree `1c59c6268f3406c1ac2692f61e3be8275dfba283` 使用独立 R2 构建实际六组全部通过。760 tracked、23 exports、5 fixtures 前后完全相同，六个临时环境均清理，页面异常、外网和模型调用均为零；未知保存确实先由服务端提交，再丢回应，仅明确核对时沿原 payload 重放。

原件 `test-results/expo-assistant-trip-search-20260918T003632986532Z/result.json` SHA `a32150582e54897097a69881aa32323d3297c5201234c354e5d2df62dec24319`；完整 stdout SHA `4f471741891b03c78d6f85cc271781e0e2a89d5e95d7900a57a520c07768e769`，stderr 空。Root 实际查看全部四图的独立记录 `expo-assistant-trip-search-visual-review-20260918-r2.json` SHA `117ed5529e2381e84f31567eefd8f58be94f6a13bec3e0a2c59f568aa5c689d3`：320×844、1280×1000 的浅／深色可见范围无阻断；长标题、旅行类型与操作区可读，按钮实测 44px 高。仅证明这些滚动视口，不扩大为整页、原生手机或实体电视验收。

## R3：经典浏览器测试拆分后的候选

首轮服务器验证因原 `test_assistant_source_search.py` 混入需要 Playwright 的经典浏览器测试而失败；该完整函数逐字移入独立模块，Windows／Edge 单项实际 1/1，内部八项检查全部完成。它与本页 Expo 六组是两个独立范围；失败原件、拆分与 167 collection 见[集中验收](EXPO-ASSISTANT-TRIP-SEARCH-ACCEPTANCE.md#expo-assistant-trip-search-release)。

R3 受验候选 `52adae89741c239168d2bdf7bffac430952065d1`／tree `4dd0ea975510a8efcf38b42f1450cafa1ba194d8`，实际构建证据 SHA `c3120d8f407266e8120842dcd7d22f6d8e456ae1384dab0bff7cd20e6ec16730`；198 构建输入与 23 导出和 R2 相同。六组全部通过、四 PNG、761 tracked／23 exports／5 fixtures 前后不变，六个临时环境清理，页面异常／外网／模型调用均为零。

原件 `test-results/expo-assistant-trip-search-20260918T010248112020Z/result.json` SHA `d44b9673f910c50baf77d3154d6319dc025ca36668ec254d307cfb2e3391d381`。Root 实际逐看四图的 `expo-assistant-trip-search-visual-review-20260918-r3.json` SHA `5457794ee1aa7a1c6b936d07f4d258466f4777180558268a96c32ae7e1972015`，仍仅覆盖 320×844／1280×1000 浅深色滚动后可见视口；这些本地报告本身不代替另行记录的生产激活与读回证据。
