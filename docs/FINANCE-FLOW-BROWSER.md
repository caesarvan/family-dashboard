# 收支方向列：组合浏览器验收

固定组合 `9ee62cb140eb019fe3bcc03dc49731619f2547dd` 已实际完成下述三场景（3/3、六张截图），并通过非作者浏览器审查；代码已合入，随后固定53ea包已实际发布，状态见[集中验收](FINANCE-FLOW-ACCEPTANCE.md#finance-flow-release)。工具复用既有财务 HTTPS/Flask/SQLite 夹具和文件选择操作，业务响应来自实际应用。只使用虚构 CSV/XLSX，不访问真实账单、云服务、模型或生产。

默认三个独立临时家庭数据库、六张截图：

1. `csv_flow_budget_dedup`（390）：默认自动识别保守显示未知；明确选择方向列使旧预览失效，重新预览并私密确认；真实 100 元预算记录支出 10.50、剩余 89.50，收入 30 单列。刷新后重复文件和修改方向均不新增或改写原 ID、revision、来源，冲突保留原值。
2. `xlsx_lost_confirm_receipt`（1280）：选择真实工作表与方向列；取得真实确认成功响应后仅丢弃传输。本人核对原 requestId 回执，确认 POST、导入批次、回执和相应审计各仅一次，数据库原记录不变。
3. `identity_offline_late_preview`（390）：已保存私人记录之外再准备未确认文件；离线隐藏，恢复原身份保留所选列和文件。扣留真实预览响应，实际退出并登录成员二后才送达；新身份不能看到旧草稿／确认按钮、不能读原回执或账本记录，不新增确认。

每项保存实际 API 路径／状态顺序、关键真实响应、合成数据库终态及截图哈希。布局检查包括 body/root 水平溢出和可见映射控件裁切；不宣称完整纵向截图或真实设备覆盖。失败原件保留，默认不会重跑。后台响应 500、页面错误、外网请求、监听器或临时目录未清理均不能通过。

审查工具后，由协调者提供同一固定源码的正式 fresh Expo 导出。要求 build-evidence 绑定完全相同 HEAD/tree、全部前端输入和九个既有 supplemental 输入、全部实际导出、各阶段 exit 0、禁 dotenv 且无 EXPO_PUBLIC 注入。本工具不接受旧 build 的任意祖先复用。

```powershell
& '<主仓>/.venv/Scripts/python.exe' -B -X utf8 tests/browser_finance_flow_mapping_check.py `
  --source-root '<独立固定组合工作树>' --expected-head '<40位固定提交>' `
  --bundle '\\?\C:\<已审正式导出>\web' --expected-build-evidence '<64位SHA256>' `
  --temp-root 'C:/tmp'
```

默认全部三项。补验时可显式 `--case xlsx_lost_confirm_receipt`（可重复参数选不同项）；每次新建 `test-results/finance-flow-<UTC>/`，按所选项严格核验一项两图，不能把单项补验称为整轮三项通过。外层协调者另行保存 PID、argv、stdout/stderr 和真实终态。工具窄检查：`python -B -X utf8 -m pytest -q tests/test_finance_flow_browser_tool.py`；其中真实 Flask 测试客户端检查只是夹具自检，不代替浏览器执行。

## 本轮实际证据

以下原件保存在独立工作树的忽略目录，未提交到 Git；路径以 `family-dashboard-access/worktrees/` 为起点。

- 正式构建：`finance-flow-combination/test-results/expo-finance-flow-combination/build-evidence.json`，SHA256 `9e84b1bc937f0c8b9a8dc7d4aaf729b3cd8d5845ca4d06f818565257af0d3638`。fresh npm ci、两组 tsc、22 项财务 Node 检查和 Expo 导出全部 exit 0，实际 23 个导出文件。
- 本轮浏览器：`finance-flow-combination/test-results/finance-flow-20260920T150130152959Z/result.json`，SHA256 `0e73ee4be09923eef2a4834a18fdaafc39350b57ec15a89c981ad7517f74851b`；外层原件在同树 `test-results/finance-flow-browser-execution-r1/`。原 PID 46156、exit 0，一次执行全部 3/3；真实 HTTP／数据库证明、六图和临时夹具清理均留证。
- 非作者审查：`media-video-usability/test-results/finance-flow-browser-independent-r1.json`，SHA256 `e24fcb0504b997bcd8ef686ee8844f65f42f93f69cf35622de3a537554d38970`，结论为三场景通过。stderr 保留一条 `Response.finished` 的 `Target closed` 异步观察警告；无应用 traceback、HTTP 5xx、页面错误或外网请求。stdout／stderr 没有共同时间戳，不能断言该警告的精确时序或所有异步观察者均正常结束。

这些证据来自 Windows 上的合成本地浏览器流程，不是 Linux 或生产验收。固定53ea候选随后已完成实际33项 Linux 后端检查；该结果与本页浏览器证据分开留证。生产激活及独审进度见集中验收，仍须使用新固定单次计划，不重放历史计划。
