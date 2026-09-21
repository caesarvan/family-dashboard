# 助理：查询已有旅行准备情况

待实现合同；核查基线 `3d62d153d8e2bdef319c0dd48f0833daf03c419b`。本片只读，不表示已经开发、验证或发布。目标：询问已有旅行 → 明确选择原旅行 → 查看尚未完成的准备与采购 → 在原旅行处理 → 返回同一查询核对最新状态。

## 现有依据与最小接入

- `frontend/src/lib/assistantJourney.ts` 的 `isJourneyRequest` 只要命中“旅行/行程/旅游”等词便进入新建简报；`AssistantScreen.tsx` 的提交分流目前没有准备状态查询。
- `journey_workflows.py` 的 `linked`、`detail` 已以 `journey_links` 和当前 `entities` 计算准备/采购进度；任务阻塞沿 `task_dependencies.project`。不得用最初 `plan.checklist` 的文字或完成状态替代现有事项。
- 当前 `/api/journeys` 会展开全部旅行详情，普通 `/api/assistant/search` 又混合多种记录，不能在客户端截取它们冒充旅行专用分页。新增下面一个窄只读入口，在 `register_journeys` 内复用成员读取围栏和关联语义；不改变这两个旧接口。
- 处理仍打开 `TripsScreen` 的原 `tripRequest.id`。复用它的准备/采购原实体操作、既有改期/同步入口和未知写结果恢复；状态页不提供完成、编辑、同步或新建按钮。

## 用户路径与文字分流

1. “冰岛旅行准备得怎么样”“冰岛行程准备进度”“旅行还有什么没办”“还有哪些没做”进入本地状态查询；按钮为“查询准备情况”。首版只识别明确词组 `准备得怎么样 / 准备怎么样 / 准备情况 / 准备进度 / 还有什么没办 / 还有哪些没办 / 还有什么没做 / 还有哪些没做 / 还有什么未完成 / 还有哪些未完成`，不承诺任意问法理解。
2. 显式“搜索/查找/找一下”、`待办/任务/采购：`、现有财务查询与明确改期保留原入口。状态识别优先于宽泛的新建旅行识别；兼有读和写意图时要求用户改写或从原旅行处理，不以状态查询产生草案。原“计划一趟冰岛旅行”仍进入原简报。
3. 从已识别句尾去掉状态词组、句末标点及紧邻状态词组的通用“旅行/行程/旅游”后得到搜索词；只接受剩余 0～100 字，可在页内修改。无法作此确定提取时只显示空搜索框和原问题，不猜地点、最近一趟或用户意指的旅行。空词表示分页选择已有旅行。
4. 候选显示名称、日期、目的地；即便只有一项也由用户点“查看这趟准备”。同名不得自动选择；日期只用于消歧，不据此推断准备是否完成。没有命中时允许改词或打开旅行列表，不自动创建/升级。
5. 选中后显示当前计数、未完成准备、未完成采购、负责人、截止及真实任务阻塞。“打开原旅行处理”只传原 ID；返回保留原问题、搜索词、候选页、原旅行 ID、事项分类/页码，重新读取后显示；来源变化时从该分类第一页核对。不把旧结果当刷新成功。

本查询不调用模型/provider，即使助理的 AI 开关开启，也明确显示“只读取本家庭已保存的旅行准备记录”。不发送家庭标题给外部服务，不产生 `assistant_plans`、操作回执、审计业务写入或云同步。

## 一个 GET，两种明确响应

`GET /api/assistant/journey-status`，仅当前家庭已登录成员，`Cache-Control: no-store`。参数不得重复、不得有未知字段；数值为规范十进制整数，ID 为 24 位小写 hex。`limit` 固定 20，可省略或传 `20`。

**候选读取**：仅 `q`（trim 后 0～100 字，默认空）、`offset`（0～980，20 的倍数，默认 0）、`limit`。

```ts
{
  version: 1, view: 'candidates', query: string,
  items: Array<{ tripId: string, journeyId: string | null, tripRevision: number,
    title: string, destination: string, start: string, end: string,
    status: 'available' | 'legacy' | 'needs_review' }>,
  limit: 20, offset: number, nextOffset: number | null,
  coverage: { scannedTrips: number, scanLimit: 1000, capped: boolean, unverifiable: number }
}
```

只扫描当前家庭 `kind='trips'` 的原实体，按原 ID 升序，最多读取 1001 行以判断上限；处理前 1000 行，按当前 title/destination 的 Unicode casefold 子串匹配，匹配后分页，不扫描照片/资料/财务。`scannedTrips` 包含扫描内无法核验的原记录，`unverifiable` 是其中无法安全投影的数量；不返回坏记录内容。`capped` 或 `unverifiable>0` 时明确“仅核对部分已有旅行”，不能称全家庭无结果。每页都是当前读取，翻页期间列表可能变化；不自动遍历后页。选中原 ID 的详情读取不受候选扫描范围限制。

**原旅行状态读取**：仅 `tripId`、`section=tasks|shopping`（默认 tasks）、`offset`（0～80，20 的倍数，默认 0）、`limit`、可选 `sourceVersion`（64 位小写 hex，非零 offset 必须提供）。不能与 `q` 混用。

```ts
{
  version: 1, view: 'status', state: 'ready' | 'legacy' | 'needs_review',
  trip: { tripId: string, journeyId: string | null, tripRevision: number,
    journeyRevision: number | null, title: string, destination: string, start: string, end: string },
  sourceVersion: string,
  summary: null | { tasks: { done: number, total: number, remaining: number, blocked: number },
    shopping: { done: number, total: number, remaining: number } },
  section: 'tasks' | 'shopping', items: Array<StatusItem>,
  limit: 20, offset: number, nextOffset: number | null,
  coverage: { complete: boolean, unverifiable: number,
    reasonCodes: Array<'legacy_without_workflow' | 'linked_source_unavailable' | 'item_limit'> }
}
```

`StatusItem` 公共字段：`kind: 'tasks'|'shopping'`、原 `id`、正整数 `revision`、`title`、`owner: {id: string|null, name: string|null}`、`due: YYYY-MM-DD|''`。采购另含原 `quantity` 和 `priority: low|normal|high`；任务另含 `dependencyStatus: ready|blocked` 与 `blockers: Array<{id: string|null, title: string|null, reason: unfinished|unavailable}>`，最多 20 项。不返回备注、费用、凭证、云账号或模型推断。名称/数量等沿原实体字段限制；`shared` 投影为 `{id:'shared',name:'一起'}`，已不在当前家庭有效成员中的负责人投影 `{id:null,name:null}`，显示“负责人待核对”，不猜新负责人。

## 权威来源、上限和“已准备好”的边界

- 原 trip 必须存在且为 `trips`。有工作流时核实 `workflow.trip_id`、trip 数据内 `journeyId`、`journey_links` 的 `trip` 原 ID/kind 互指；不得借同名、旧计划或错误关联挂上另一趟旅行。原 trip 不可读返回统一 404；互指失效返回该原 trip 的 `needs_review`、空 items、`summary:null`，不回退全家庭清单。
- 原 trip 未声明 `journeyId` 且没有对应工作流时才是旧旅行，返回 `legacy`、`summary:null`、空 items 与 `legacy_without_workflow`，说明“这趟旅行尚未建立可核对的准备清单”，可打开原旅行；有悬空 `journeyId` 则是 `needs_review`。不能把缺少关联当作没有待办，也不自动升级。
- 只读取原工作流的 task/shopping links，逐项核对 link kind、原实体 kind、`journeyId`、`tripId`。最多 100 个准备及 100 个采购；用各类别的第 101 条识别超限。与工作流当前计划的事项 key 集合核对只用于发现删除/失联，不能从计划补造事项。重复/缺失/非法来源计入 `unverifiable`；超限或来源不全为 `needs_review`，返回可核实的当前项和计数，但 `coverage.complete=false`，这些计数不是全部准备量。
- `summary` 按可核验的全部关联项计算，不按当前 20 项分页计算；`remaining=total-done`，只以当前 `done===true` 作为完成。items 只列未完成项，按原 ID 升序。没有截止日显示“未设截止”，本片不推算逾期或时间紧迫性；采购 done 仅表示原清单已完成，不证明下单/付款/库存或云同步。
- 阻塞沿 `task_dependencies.project` 的直接前置语义，仅为本页任务读取最多 20 个前置 ID/项（单次最多 400 个），不递归遍历全家庭图。计数所需的关联任务及其直接前置同样有界（100×20）；缺失/异户/来源不可核验统一为 unavailable，`id/title=null`，不泄漏存在性。当前同户可读且未完成的本地前置才返回原 ID/title；不把云只读前置当作已成功同步。采购没有任务依赖，不制造 blocker。
- `sourceVersion` 是本次原 trip、workflow、所核验关联项和直接前置的当前版本/关联投影摘要；不含时钟、不是授权票据。后页携带前页值；有变化返回 409 `stale_journey_status`，UI 清旧结果、保留选择并提示重新读取，不把两版拼成一份进度。首次/返回刷新不携旧摘要。
- 只有 `state=ready` 且 `coverage.complete=true`、全部 remaining=0 才显示“已记录的准备事项均已完成”；任何情况下都不写“这趟旅行已全部准备妥当”。未记录事项、真实预订、云同步、签证等并未核验。

## 身份与恢复

后端采用真实成员 cookie/当前家庭数据库，沿 `edit_read_snapshot` 的读取前/释放快照后会话复核；不借 TV cookie 或请求参数选家庭。最终响应前再次核对原 trip/关联/前置投影；期间删除或变化则拒绝或返回新完整版本，不能保留被删标题。401/403 不带候选或进度；锁竞争以 503 `unavailable` 可恢复失败，不转成空列表；参数错误 400 `invalid_journey_status_query`；原 trip 不可用 404 `journey_status_unavailable`。

前端每次查询/选中/翻页/返回均有 `/me → GET → /me` 同身份围栏和请求代次、AbortSignal；整链 15 秒、响应最多 256 KiB。同时最多一条查询链；可见时每 10 秒最多一次当前页刷新，前次未结束不叠加。后台/离线立即隐藏并废弃旧响应，保留同身份的内存输入/选择，回前台 fresh `/me` 后重读；身份改变或撤权清除输入、选择及结果。异步迟到不能重新打开旧旅行或回显旧家庭。返回刷新和翻页失败只显示失败/重试，不显示旧计数为当前。

不把问题/旅行标题/结果放进 localStorage/sessionStorage；刷新页面回到助理入口，无保存结果待核对，因为本片从不写。原旅行页已有写入未决时沿它的阻止退出/核对机制；本片不得清除该未决操作。前后 `/me` 的 404/410 不能误报原旅行被删除；仅实际状态 GET 的 `journey_status_unavailable` 关闭当前详情。零业务写入不排除现有认证层必要的 session touch；测试须将该例外单列。

## 拆分与验收

拟后端只在 `journey_workflows.py` 增加读取投影/路由及专项 Flask/SQLite 测试，复用现有 schema/依赖语义，无新初始化、迁移或 module。拟前端改 `assistantJourney.ts`、`AssistantScreen.tsx`，新增小型 status lib/panel 和专项测试；用原 `TripsScreen.tripRequest`/退出回调，不更改旅行写接口。契约和实现经独立审查后才进入组合构建与浏览器验证。

- 两个同名旅行、另一家庭同名旅行：分页/日期消歧、选原 ID；无工作流、原 ID 在候选扫描范围外、1001 条截断和坏来源均有明确覆盖。
- 原任务/采购完成状态、负责人/无截止、直接前置阻塞、缺失关联、超限、分页间变更和删除真实 SQLite 复核；GET 前后业务行/审计/幂等表不变，既有认证 touch 单列。
- 真成员两户 cookie、TV、退出/撤权以及读取中变化；无跨户标题/计数，模型 transport 不被调用；旧新建简报、搜索、改期、任务采购输入分流保持。
- 手机真实浏览器：输入状态问句 → 同名选择 → 读原任务/采购 → 打开原旅行完成一项 → 返回原问题并刷新计数/阻塞。桌面真实浏览器：翻页/原 ID、离线恢复与迟到旧身份响应清空。只证明合成应用流程，不称真实云授权或用户本人验收。
