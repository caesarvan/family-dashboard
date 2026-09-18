# 库存售后 → 家庭待办：真实浏览器验收

**当前状态：R1 四条真实浏览器功能流程一次 4/4 通过，但截图视觉验收未通过；采集修订已编写，尚待独审和受影响流程重跑，未部署。** 不把 API 单元测试、UI recording doubles、脚本编译或源码提交写成完整用户流程通过。每次实际执行必须绑定集成人提供的冻结组合源码和原始 Expo 构建证据。

作者分支 `codex/inventory-followup-browser`，开发 base `8ac89b50df03ae66da1dc3b63c116f00344d9128`；脚本与本文仅为本批新增验收材料。UI 契约按作者冻结 head `124f0a2e84acf927582a0d1c2776ece6f3529095` 核对，后续执行身份由每次报告单独绑定。

## 四条有界流程

| CLI case | 真实操作与判定 |
| --- | --- |
| `private_task_lifecycle` | 从真实采购的关联入口打开私人、售后处理中批次。默认标题“跟进售后”、空备注及截止日，不复制私密物品名或批次备注；表单就近显示家庭共享说明。取消编辑不写库。明确选择负责人、截止日、备注后，由 UI 创建一次。家庭待办清单能看到该任务且任务对象没有库存来源字段；使用原清单完成控件真正 PATCH 后回批次读取最新完成状态。停止并重启实际 Flask、复用原库后，仍是同一 task/link；库存实物、售后状态、采购、财务和旅行哨兵保持。 |
| `lost_create_response` | 浏览器拦截器先 `fetch` 实际服务端 POST 并核对 201，再丢弃回复，绝不伪造成功。草稿保留、返回入口禁用，尝试全局导航被阻止。点击原恢复按钮发出原 requestId 的 GET 回执；真实 SQL 与浏览器请求计数确认只增加一条 task、一条 create_followup operation，无第二 POST，恢复动作不再写库。 |
| `partner_conflict_deleted` | 同一共享批次，原成员先打开草稿；另一真实登录成员通过正式接口抢先创建。原草稿的真实 POST 返回 409 并保留输入；点击重新核对读取已有任务并退出草稿，无新增任务或失败回执。另一成员正式 DELETE 任务后，刷新、退出批次再打开、通过原批次编辑 UI 关闭售后，都显示 deleted 且没有补建入口；原关联 operation 保留。 |
| `private_link_revocation` | 私人批次本人已明确创建的通用任务可以家庭共享，但伙伴的采购关联列表、批次、followup 与原回执读取均不泄漏该私人来源。伙伴打开另一共享物品的售后草稿后，拥有者通过正式接口撤共享；真实前后台事件触发重新核权，旧详情及草稿清空。SQL/API 核对没有意外创建 task、followup operation 或实物变动，原明确共享的家庭任务保持。 |

每个 case 使用新的临时库、实际成员会话和 HTTPS Flask listener。夹具通过真实 API 填入非零财务付款、采购预算／实付、旅行预算／支出及库存两件实物；不是全零数据库。检查完整采购／旅行记录和受保护财务表前后相同，实物流转与金融来源关联表保持；创建售后待办所需的独立 operation 和库存 revision 更新不冒充实物变动。

不重复后端全部 46 项边界测试。跨户、TV、CSRF、完整非法字段矩阵与事务 fault 的 API 证据需要单独引用，不能由这四条浏览器流程推出。

## 夹具、冻结身份与隔离

脚本 [browser_expo_inventory_followup_check.py](../tests/browser_expo_inventory_followup_check.py) 继承已存在的 [购物库存 Run](../tests/browser_expo_shopping_inventory_check.py)，后者依次继承 memberships 与 finance Run，保留实际 Flask/SQLite/Edge、会话、非 loopback 网络拒绝、截图稳定等待、横向溢出检查及清理守卫。

起服务前逐一核对当前实际导入的 shopping、memberships、finance 与 Git blob helper 字节等于传入冻结源码中的同名文件；拒绝已缓存的非冻结 app／测试 fixture 模块。继承 fixture 的 `test_financial_files`／`test_app` 实际路径和 SHA256、复制到临时静态目录的完整 bundle manifest 继续读回。临时目录前缀固定 `if-`，避免 Windows MAX_PATH。

准入及结束检查绑定：

- 源码完整 HEAD/tree、干净工作区、全部 tracked 文件的 Git 原始字节与工作文件 SHA256；前后完整散列相同。
- 构建证据文件精确 SHA256、成功退出及 bundle markers、build HEAD/tree；build 必须为本次 source 的祖先，两个 commit 的完整 frontend 输入集合及 SHA256 相同。
- bundle 完整文件集合和散列必须等于构建原件，前后不变。
- harness 自己的提交身份、实际执行文件原件、前后散列和干净工作区；它与被测应用源码身份分别记录。
- 每个 case 都关闭所有上下文、停止真实 Flask 线程／监听器并删除该 case 自己的临时目录；清理失败不能通过。
- `pageErrors`／`externalRequests` 必须为空；不访问生产、真实资料或云服务，不使用实体设备。

每次执行创建独立 `test-results/expo-inventory-followup-<UTC>/`，包含 `executed-harness.py`、`result.json`、关键截图，失败时额外保留 traceback 和可取得的 DOM accessibility snapshot／截图。报告记录 `requestedScenarios`、`fullSuite`、每条结果、真实浏览器与 fixture API 的分开请求计数、SQL task／operation／movement 数量、受保护记录摘要、实际重启与完整散列守卫。故障记录不覆盖；不能把分轮通过拼成一次全通过。

采集修订计划五张关键截图：390 px 明确共享表单、1280 px 最新完成投影、390 px 未知结果恢复区、390 px 未知结果保留草稿、1280 px deleted 历史及售后关闭。每张先把实际关键卡片滚入 RN 内层 ScrollView，确认业务 idle 按钮可用或 pending 按钮仍禁用，等字体完成，再跨至少 600 ms 连续七次采样核对整个目标及祖先的几何、opacity、transform 与字体样式不变。目标须完整位于视口及滚动祖先交集内；截图前后位置不得漂移。报告额外保留 `targetBox`、稳定窗口与几何摘要、输入／浮动 label 几何、按钮状态。恢复区与草稿分图，导航锁 Snackbar 只通过真实“知道了”按钮关闭。

采集不注入样式、不隐藏文字、不关闭产品动画、不剪裁掩盖重叠，继续使用原横向溢出检查。若稳定后仍有 label／值重叠或按钮叠影，应报告产品视觉问题；像素截图仍须独立审查。精确 case 按 2／2／1／0 张核验，全量应为 5 张。

## R1 实际执行与未通过的视觉边界

2026-09-18 07:46:56–07:47:38 UTC，harness `74d0469d72606b58150984e1ef25719410fe8fdf`／SHA256 `40d3895851c38f849aea7a0d4a7bdc0cf91bea06e7b8ece4f66dbe8cc45c4c66`，对冻结组合 source `e165b088f2e01bd029de44793cc801c51bc04712`（tree `0d7f1ae4fa877bc309caa6ec992bcec7318314f5`）实际执行 `--case all`，四条一次 4/4、退出 0；没有失败重跑。

构建为 `adbb1d87c58fff11fd5b06ce3ee84b53d35251d5`，build evidence SHA256 `36a0258a72b46fb85465d24981d9442b8ad14531658435cfa3e6ca7843bc035b`。源码、bundle、构建证据和所有继承 fixture 的前后散列守卫均通过，双方工作区结束时干净、四个临时目录全部清理，pageErrors/externalRequests 均空。未知结果实测原 POST 1 次、原 requestId GET 1 次、task／operation 各新增 1；实际 Flask 重启保留同库、同 task/link。以上是功能及隔离证据，不是视觉通过结论。

R1 原件保留在作者 worktree 的 `test-results/expo-inventory-followup-20260918T074708795442Z/result.json`，SHA256 `d19d9af58319d827ae5770eaf27a1d85450a945f149ea579ac92c4a269333120`；命令／stdout／stderr／exit 在 `test-results/inventory-followup-run-r1/`。stdout SHA256 `5dfdc0412ab58b0dc9eaed56056c88c5b445dd76ee5fa2cc135b85ff9324d19b`，stderr 为空，exit 原件 SHA256 `3e449253753397fd7d3db8a32ad5535753b896a66905f196f2f06aa87f2debe9`。

作者、UI 作者和集成人读图一致发现：390 px 表单的截止日／备注 label 与输入值重叠、按钮文字叠影；1280 px 完成状态图没有把售后任务卡滚入镜头；未知结果图只有恢复区与草稿标题，关键字段在下方；deleted 图关键状态可读但按钮尚呈忙碌态。原截图虽无横向溢出，不能证明视觉通过。R1 原件不覆盖；下一轮只重跑有截图的前三条，已通过且无图的 `private_link_revocation` 保留 R1 证据，不写成修订版一次四条全通过。

## 冻结后执行

以下参数必须替换为集成人本轮实际冻结输入；修订脚本尚未执行。

```powershell
& 'C:/Users/caesarf/OneDrive - NVIDIA Corporation/Documents/AI/family-dashboard/.venv/Scripts/python.exe' -B -X utf8 `
  tests/browser_expo_inventory_followup_check.py `
  --source-root '<冻结组合源码绝对路径>' `
  --expected-head '<源码完整40位HEAD>' `
  --bundle '<Expo构建产物绝对路径>' `
  --build-evidence '<原始构建证据JSON绝对路径>' `
  --expected-build-evidence '<构建证据64位SHA256>' `
  --case all
```

失败修正后可以把 `--case all` 换成上表唯一精确 case，仅重跑受影响流程。报告必须保留首轮失败、修订后的 harness/source/build 身份和各轮覆盖；单 case 报告明确 `fullSuite: false`。

脚本静态检查使用指定 Python `-B -X utf8` 读取文件，执行 `ast.parse` 和 `compile(..., 'exec')`，不导入 app、不起服务、不写 pyc；提交前执行 `git diff --check`。当前采集修订尚未有实际截图与运行结论，尚无性能、部署或真实家庭验收结论。
