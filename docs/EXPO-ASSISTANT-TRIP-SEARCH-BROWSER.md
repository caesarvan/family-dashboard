# Expo 助理查找旅行：浏览器验收脚本

本文件与 [验收脚本](../tests/browser_expo_assistant_trip_search_check.py) 是下一批候选，基于 `37a393f149aeefb91a92da05b1d4d213b4831af0`。准备阶段只做静态编译、来源检查与差分检查，尚未执行浏览器、构建或部署；场景与截图数量是验收计划，不是通过结果。

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

静态准备不执行下面命令；须经另一位审查者确认固定脚本，再由 Root 提供已合并冻结源码和构建证据后授权运行：

```powershell
python -B -X utf8 tests/browser_expo_assistant_trip_search_check.py --source-root <冻结组合目录> --expected-head <40hex> --bundle <已审dist目录> --expected-build-evidence <64hex>
```

实际运行在作者树 `test-results/expo-assistant-trip-search-<UTC>/` 排他保留执行脚本、每组原件与 `result.json`。图片只覆盖滚动后的可见视口，仍需逐张视觉复核。该验收不证明真实 AI 提供方、云账号、真实家庭资料、原生手机或实体电视可用；本地查询页面复用原旅行能力，不推断真实到访或预订。
