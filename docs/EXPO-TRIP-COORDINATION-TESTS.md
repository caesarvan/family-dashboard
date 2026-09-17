# Expo 旅行地点与日历组合验收

本文件描述新增 `tests/browser_expo_trip_coordination_check.py` 的待执行验收方案。编写基线为 `f48c02dc51b6610a1f2af20a3b8dbc44286efda7`；提交、语法检查或旧测试通过均不代表本脚本已实际通过。必须由集成人给出包含新界面和本脚本的冻结 source、独立导出 bundle 与 build evidence 后执行，保留失败原件。

## 真实部分与夹具

继承 `browser_expo_journey_brief_check.Run`，继续使用其下层 `browser_expo_finance_check.Run` 的临时 HTTPS Flask、独立 SQLite、真实成员登录与 CSRF、Edge、请求记录、截图与停机清理。三个夹具和当前 harness 的实际文件 SHA 与冻结 source 逐一核对；不会执行旧 harness 的场景。

复用 `test_calendar_publish.Remote.transport` 代替外部日历 HTTP，两个 provider 各自运行独立临时家庭与 `Remote`。OAuth 账号和授予范围是写入临时库的合成 fixture；后续日历业务 HTTP、真实 provider adapter、持久队列与 worker 均使用产品实现。仅附加的身份后检场景会替换一次 `/me` 错误响应，详见下文；不替换保存或发布业务响应。Python 禁止非 loopback socket，浏览器禁止非本次本地 origin。旅行采用本地文字提取，任何模型调用都使测试失败，不以合成模型冒充成功。

## 场景与数据计数

每个 provider 执行以下七组，共十四组预期检查：

1. **旅行保存。** 单目的地文字简报经真实 UI 核对；在分段编辑中移除自动目的地段，保留唯一 `event:overview`。预览比较真实业务表零写；明确保存后验证一项日程及稳定工作流 ID。
2. **地点确认与地图。** 生成目的地建议和取消均零写；默认坐标为空、私人、已计划。输入合成坐标后明确保存，验证没有到访确认或共享，再进入已选地点地图。编辑地点时外层“返回旅行”必须禁用，明确放弃编辑后恢复可用且没有写入，再返回关联旅行。
3. **发布与未知结果。** 只展示本人来源。预览不新增队列、不调用 provider；确认请求先由实际 Flask 提交再丢弃响应，人工核对只 GET、不重发 POST。离开再重新打开后，新的明确预览／确认仍复用队列 ID。provider 创建成功后丢失回应，再处理仍恰好一条远端事件。
4. **普通改期。** 在 Trips 表单明确修改旅行及目的地日期，再预览保存；原事件 ID 保持。worker PATCH 成功后丢回复，恢复后仍只更新一次、不新建。准备截止与地图地点日期不会自动移动，测试明确记录这一当前边界，不把它称为全量日期协调。
5. **时间语义复核。** 另经真实旅行 API 建立“概览＋一个日期段”的两事件 fixture，并发布。经真实 preview/apply 将同段改为 v2 定时活动，服务端自己产生 `needs_review`，不直接改数据库 review 标志。UI 对照预览仅远端 GET，明确确认后 worker 更新原远端 ID。复杂分段编辑属于 API setup，不是 Expo 编辑能力的验收。
6. **云端冲突与停止。** 仅改变合成远端的标题／ETag，真实 worker 检出冲突；UI 读取对照、明确采用本地后才 PATCH。停止保留原远端事件，恢复不重复创建。
7. **权限与迟到响应。** 合成账号撤掉写 scope 后 worker 不再写远端；另一成员和通过真实邀请流程建立的另一家庭不能读取私人地点或控制队列。持有原成员真实 GET 响应期间切换成员 cookie，迟到内容不得重新显示本人来源。

主链每个 provider 一条远端事件；语义 fixture 另增两条，因此完整套件不是“总共只创建一条”。以分场景断言和报告计数为准。

另保留原十四组不变，追加两个 provider × 401／403／429 共六组身份后检故障场景，总计二十组预期检查。每组通过真实旅行 API 建一条合成概览，UI 预览和确认；确认响应是实际服务器成功提交后的原始 200。仅这组新页面将 10000ms 周期轮询延后至十分钟，其他计时器／实际 fetch／PlaceFence 不变，防止全局刷新先消费错误。实际确认响应后，将紧接的一次 `/me` 原始 200 验为原成员，再注入指定错误并记录精确顺序；不是伪造确认未写。

401／403 后检失败必须立即隐藏本人来源、旅行内容与预览／对照，只保留重新读取入口；429 可保留只读未知状态。三者原确认按钮均消失；明确读取当前状态不产生第二个 POST，同一队列仍在。随后实际登录另一成员并读回，旧私人来源清空。报告逐项记录注入一次、周期轮询延后、原业务响应未替换及实际成员切换结果。它证明这一受控交错，不声称所有后台计时交错均已覆盖；原十四组继续使用正常周期轮询。

首轮 source `54cd7718f2d0fb8a51b2233fff6c3c88b23a8be4` 已实际运行：第一组旅行保存通过，随后因图标计入“旅行地点”按钮可访问名称而定位超时，未进入地点保存。原件保留于 `expo-trip-coordination-20260917T002740842189Z/result.json`，SHA256 `51d4ff8aa4fbba35ab69ff8a94a9ed2dd60f319c4dfc2de1a3d0dc98d3d6d358`；source/bundle 前后不变。定位修订复用已审 `icon_button`，仍要求真实 button 唯一、可操作，不放宽业务断言。完整通过与十二截图仍须新冻结构建复跑，不能用这一首轮宣称。

## 执行与原件

只对集成人当次给出的冻结 source 和 bundle 执行；以下占位不可直接运行：

```powershell
& '<主仓>/.venv/Scripts/python.exe' -B -X utf8 `
  '<独立测试 worktree>/tests/browser_expo_trip_coordination_check.py' `
  --source-root '<冻结 source worktree>' `
  --expected-head '<完整提交 SHA>' `
  --bundle '<独立构建目录>/dist' `
  --expected-build-evidence '<build-evidence.json SHA256>'
```

输出到测试 worktree 下唯一时间戳目录：`test-results/expo-trip-coordination-*/result.json`、实际执行脚本副本、截图；失败额外保留 `failure.png` 与 `failure-aria.txt`。报告核对 source 和 bundle 前后全部字节，保存构建身份与夹具 SHA。截图为 Microsoft 路径三个关键页面（私人计划地点、发布预览、时间复核）各 320／390／1040／1440 四宽，共十二张预期截图；Google 独立执行相同业务链。截图仅当前内部滚动位置的可见内容，不覆盖所有长表单；生成后仍须实际查看。

不操作生产、不测试真实 OAuth／Microsoft／Google 账户、不调用实际模型或地理编码、不证明物理电视/native，也不改变真实云日历。真实云写权限授权、实际创建与改期需本人另行验收。
