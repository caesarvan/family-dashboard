# 库存售后 → 家庭待办：真实浏览器验收

**当前状态：验收脚本已编写并做静态检查，尚未运行真实浏览器，未部署。** 本文不把 API 单元测试、UI recording doubles、脚本编译或源码提交写成完整用户流程通过。实际执行必须等待集成人提供冻结组合源码和对应的原始 Expo 构建证据。

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

全量只计划四张关键截图：390 px 明确共享表单、1280 px 最新完成投影、390 px 未知结果草稿、1280 px deleted 历史及售后关闭。截图先等字体、两帧布局和相应业务状态，检查横向溢出，再保存散列。像素截图本身仍需独立视觉审查。

## 冻结后执行

以下参数必须替换为集成人本轮实际冻结输入；本次作者没有执行此命令。

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

当前实际静态检查：用指定 Python `-B -X utf8` 读取新脚本，执行 `ast.parse` 和 `compile(..., 'exec')`，不导入 app、不起服务、不写 pyc；语法检查通过。提交前对两份新增文件执行 `git diff --check`。目前没有真实浏览器通过计数、截图、性能、部署或真实家庭验收结论。
