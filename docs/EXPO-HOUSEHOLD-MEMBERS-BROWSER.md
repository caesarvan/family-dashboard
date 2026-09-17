# 家庭与成员：真实本地浏览器验收（候选已验证）

脚本 `tests/browser_expo_household_members_check.py`，基于 `eda8632719a6f1a3202e6d5c2a9a986329c9c287` 独立分支开发。按 UI 固定 `b08ff47d523fdb86b4b06e88679f7169a91e4849` 和家庭成员三 API 合同编写；R1 已实际执行 7／7 通过，8 张截图经 Root 独立视觉审查；当前仍为候选，未部署。

## 七组场景

1. 两位默认管理员；真实调整另一人的角色使旧 Cookie 失效，重新登录普通成员后无管理能力；再晋升并重启，角色和原数据保持。
2. 明确一次撤销使两个真实目标浏览器会话失效，当前管理员保持；目标可以再次登录。
3. 匿名、配对 TV、普通成员直调被拒；真实签名第二家庭使用相同 member ID 只影响自己的数据库，额外 household 字段被拒。
4. POST／PATCH 分别真实提交后丢回复；无自动 GET 或重复写；用户明确读取当前状态并结束本地核对，列表不冒充操作回执。
5. 真并发版本变化触发 409；重新读取后再选择。成功 PATCH 后，阻断所有匹配的真实成员 GET 200，直到用户明确只读恢复；旧操作隐藏、PATCH 总次数不增加。
6. 模拟 hidden、window blur/focus 与浏览器真实 offline；确认意图恢复前重新核对，unknown 阻止导航；真实未送达请求也必须显式核对。真实 Cookie 切成员后迟到旧 DTO 丢弃、旧面板卸载。
7. 320／390／1280／1920 宽各一张浅色成员列表和深色紧凑确认框，共 **8 张**。等待字体、Paper 动画稳定及两帧后截图；验证新操作区至少 44px、可见按钮未越过左右边界，键盘打开／取消不写入。

每组独立 `TemporaryDirectory/ExitStack/Run/create_app/SQLite/HTTPS/BrowserContext`。成功数据来自真实服务器，故障只在传输层丢弃实际响应或阻止请求到达，不制造业务成功 DTO。各组失败保存并继续其余组，失败不计为通过。每组最多 1,000 条有界时间线，读回故障最多丢弃 32 份真实 200；不记录凭据、Cookie 或个人输入。

## 运行前绑定

先由非作者审查固定脚本，Root 给出受验完整应用和导出身份后才执行：

```powershell
<主仓虚拟环境Python> -B -X utf8 tests/browser_expo_household_members_check.py --expected-harness-head <脚本40位提交> --expected-harness-sha256 <脚本SHA256> --source-root <冻结应用工作树> --expected-head <应用40位提交> --bundle <冻结dist> --expected-build-evidence <build-evidence.json的SHA256>
```

脚本自身提交／tree／两份源码 SHA 与被测应用提交／tree／全部 tracked 文件分别绑定，不声称独立脚本必已包含于应用提交。构建 `sourceHead/sourceTree/inputFiles/files` 必须逐项一致。四项实际 fixture 为本脚本、`browser_expo_finance_check.py`、`test_financial_files.py`、`test_app.py`；后三者加载字节必须等于被测应用，运行前后全部 fixture、应用和导出保持。复用的 fixture 源路径随报告保存。

只在自己的 ignored `test-results/expo-household-members-<UTC>/` 排他保存执行脚本、各组报告、失败截图／ARIA、8 张范围内图片和总 `result.json`。运行方还应独占保存 stdout/stderr。源码、构建或临时清理不满足时整轮失败。没有自动重跑。

## R1 实际结果

单次运行于独立 `household-members-browser` 工作树，脚本提交 `5ffd087c4cd4f979369cce8e151280d58a2b18d9`、SHA `6710dcb0e9b9f0b052eaf6ba75990a452245e1874f992d0aa3f467e4bf93f623`。受验应用 `caf34d5a825716fe2ff0aaf363df0d4412c71e91`／tree `bfb9a1156931bd86225d5f220a6fed9c27a233ad`，构建 `household-members-build-20260918-r1/build-evidence.json` SHA `74b5a29e77cd088bd5a99a390330c3edd9a3c78d4c39ae9f5c2a9b69f19be0ee`。

实际 7／7 通过、退出 0，8 张 PNG 的 SHA 已核对；727 项 tracked 文件、23 项导出、4 项实际 fixture 及独立脚本前后相同，HEAD／clean 守卫通过。7 个临时环境全部清理，页面异常与外网请求均为 0；没有自动重跑。原件 `test-results/expo-household-members-20260917T211621366932Z/result.json` SHA `2cae6c990087227f1ec9606ca0343ac5e1b4f542db6bd53fbc17ae75293657b5`；同工作树 `test-results/members-browser-command-r1-20260917T211620475215Z/` 排他保留调用参数及 stdout/stderr，stderr 为空。

Root 实际逐张查看四宽浅色列表与深色紧凑确认框，结论 `PASS_VISIBLE_VIEWPORT`、无可见问题。私有 access 下 `household-members-visual-review-20260918-r1.json` SHA `6bb48de14a52ba544879aebc6c9125aca043c63d433ebe714688cf30144b6ccf`，绑定上述 report 和 8 图 SHA。320 浅色列表下方说明仍在内部滚动区，未做完整滚动视觉覆盖；不能外推实体设备或全站无障碍。

## 验证边界

不启动 worker，不连接真实云或生产，所有成员、密码、家庭、会话和财务基础为空或虚构 fixture。TV 是本地真实配对 API 与网页投影，不能代替实体电视。hidden/window focus 是浏览器事件夹具，offline 使用浏览器网络状态。

截图仅当前实际可见 viewport，内部滚动区不算全页覆盖；截图生成和 SHA 核对不代替独立逐张视觉审查。键盘与控件尺寸仅覆盖本轮新 UI，不宣称全站无障碍完成。底层权限、迁移、会话并发和旧 Cookie 矩阵由后端专项负责，本脚本不重复其全部组合。
